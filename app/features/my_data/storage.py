from __future__ import annotations

import gzip
import json
import shutil
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from app.storage_io import write_json_atomic


MAX_EXTRACTED_RAW_SIZE_BYTES = 256 * 1024 * 1024


class RawArchiveError(ValueError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class RawFileAsset:
    asset_id: str
    display_name: str
    original_file_name: str
    stored_path: str
    created_at: str
    size_bytes: int


@dataclass(frozen=True)
class CoordinateAsset:
    asset_id: str
    display_name: str
    target_name: str
    coordinate_type: str
    g25_line: str
    input_mode: str
    created_at: str


@dataclass(frozen=True)
class SampleAsset:
    asset_id: str
    display_name: str
    raw_file_id: str
    coordinate_ids: list[str]
    created_at: str


class MyDataStore:
    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def list_raw_files(self, user_id: int) -> list[RawFileAsset]:
        return [
            RawFileAsset(**item)
            for item in self._read_json_list(self._user_root(user_id) / "raw_files.json")
        ]

    def get_raw_file(self, user_id: int, asset_id: str) -> RawFileAsset | None:
        for item in self.list_raw_files(user_id):
            if item.asset_id == asset_id:
                return item
        return None

    def save_raw_file(
        self,
        user_id: int,
        source_path: Path,
        *,
        original_file_name: str,
        display_name: str,
    ) -> RawFileAsset:
        user_root = self._user_root(user_id)
        raw_dir = user_root / "raw_files"
        raw_dir.mkdir(parents=True, exist_ok=True)

        asset_id = self._new_asset_id()
        stored_original_file_name = self._raw_payload_name(source_path, original_file_name)
        suffix = Path(stored_original_file_name).suffix
        stored_file_name = f"{asset_id}{suffix}" if suffix else asset_id
        destination = raw_dir / stored_file_name
        try:
            self._store_raw_payload(source_path, destination)
        except Exception:
            try:
                destination.unlink()
            except FileNotFoundError:
                pass
            raise

        asset = RawFileAsset(
            asset_id=asset_id,
            display_name=display_name.strip() or Path(stored_original_file_name).stem or "raw-file",
            original_file_name=stored_original_file_name,
            stored_path=str(destination.relative_to(self.root_dir)),
            created_at=self._now_iso(),
            size_bytes=destination.stat().st_size,
        )
        index_path = user_root / "raw_files.json"
        items = self._read_json_list(index_path)
        items.insert(0, asdict(asset))
        self._write_json_list(index_path, items)
        return asset

    @classmethod
    def _raw_payload_name(cls, source_path: Path, original_file_name: str) -> str:
        suffix = source_path.suffix.lower()
        if suffix == ".rar":
            raise RawArchiveError("rar_not_supported")
        if suffix == ".gz":
            return Path(original_file_name).stem or "raw-file"
        if suffix == ".zip":
            try:
                with zipfile.ZipFile(source_path) as archive:
                    return cls._zip_member_name(cls._select_zip_member(archive))
            except RawArchiveError:
                raise
            except (OSError, RuntimeError, zipfile.BadZipFile):
                raise RawArchiveError("invalid_archive")
        return Path(original_file_name).name or source_path.name or "raw-file"

    @classmethod
    def _store_raw_payload(cls, source_path: Path, destination: Path) -> None:
        suffix = source_path.suffix.lower()
        if suffix == ".gz":
            try:
                with gzip.open(source_path, "rb") as source, destination.open("wb") as target:
                    cls._copy_extracted_payload(source, target)
            except RawArchiveError:
                raise
            except (EOFError, OSError):
                raise RawArchiveError("invalid_archive")
            return
        if suffix == ".zip":
            try:
                with zipfile.ZipFile(source_path) as archive:
                    member = cls._select_zip_member(archive)
                    if member.file_size > MAX_EXTRACTED_RAW_SIZE_BYTES:
                        raise RawArchiveError("archive_too_large")
                    with archive.open(member) as source, destination.open("wb") as target:
                        cls._copy_extracted_payload(source, target)
            except RawArchiveError:
                raise
            except (OSError, RuntimeError, zipfile.BadZipFile):
                raise RawArchiveError("invalid_archive")
            return
        shutil.copy2(str(source_path), str(destination))

    @staticmethod
    def _select_zip_member(archive: zipfile.ZipFile) -> zipfile.ZipInfo:
        members = [member for member in archive.infolist() if not member.is_dir()]
        if not members:
            raise RawArchiveError("archive_empty")
        priority = {".csv": 0, ".txt": 1, ".tsv": 2, ".raw": 3}
        return sorted(
            members,
            key=lambda member: (
                priority.get(Path(member.filename).suffix.lower(), 9),
                member.filename.lower(),
            ),
        )[0]

    @staticmethod
    def _zip_member_name(member: zipfile.ZipInfo) -> str:
        return Path(member.filename.replace("\\", "/")).name or "raw-file"

    @staticmethod
    def _copy_extracted_payload(source, target) -> None:
        size_bytes = 0
        while True:
            chunk = source.read(1024 * 1024)
            if not chunk:
                return
            size_bytes += len(chunk)
            if size_bytes > MAX_EXTRACTED_RAW_SIZE_BYTES:
                raise RawArchiveError("archive_too_large")
            target.write(chunk)

    def delete_raw_file(self, user_id: int, asset_id: str) -> bool:
        if self.get_sample_by_raw_file(user_id, asset_id) is not None:
            return False

        user_root = self._user_root(user_id)
        index_path = user_root / "raw_files.json"
        items = self._read_json_list(index_path)
        kept: list[dict[str, object]] = []
        deleted_item: RawFileAsset | None = None
        for item in items:
            if str(item.get("asset_id")) == asset_id and deleted_item is None:
                deleted_item = RawFileAsset(**item)
                continue
            kept.append(item)
        if deleted_item is None:
            return False

        raw_path = self.resolve_raw_file_path(deleted_item)
        try:
            raw_path.unlink()
        except FileNotFoundError:
            pass

        self._write_json_list(index_path, kept)
        return True

    def rename_raw_file(self, user_id: int, asset_id: str, display_name: str) -> RawFileAsset | None:
        clean_name = display_name.strip()
        if not clean_name:
            return None

        user_root = self._user_root(user_id)
        index_path = user_root / "raw_files.json"
        items = self._read_json_list(index_path)
        renamed: RawFileAsset | None = None

        for item in items:
            if str(item.get("asset_id")) != asset_id:
                continue
            item["display_name"] = clean_name
            renamed = RawFileAsset(**item)
            break

        if renamed is None:
            return None

        self._write_json_list(index_path, items)
        return renamed

    def list_samples(self, user_id: int) -> list[SampleAsset]:
        items = [
            self._sample_asset_from_item(item)
            for item in self._read_json_list(self._user_root(user_id) / "samples.json")
        ]
        return sorted(items, key=lambda item: (item.created_at, item.asset_id))

    def get_sample(self, user_id: int, asset_id: str) -> SampleAsset | None:
        for item in self.list_samples(user_id):
            if item.asset_id == asset_id:
                return item
        return None

    def get_sample_by_raw_file(self, user_id: int, raw_file_id: str) -> SampleAsset | None:
        for item in self.list_samples(user_id):
            if item.raw_file_id == raw_file_id:
                return item
        return None

    def save_sample(self, user_id: int, *, display_name: str, raw_file_id: str) -> SampleAsset | None:
        raw_file = self.get_raw_file(user_id, raw_file_id)
        if raw_file is None:
            return None
        if self.get_sample_by_raw_file(user_id, raw_file_id) is not None:
            return None

        user_root = self._user_root(user_id)
        user_root.mkdir(parents=True, exist_ok=True)
        asset = SampleAsset(
            asset_id=self._new_asset_id(),
            display_name=display_name.strip() or raw_file.display_name or "sample",
            raw_file_id=raw_file_id,
            coordinate_ids=[],
            created_at=self._now_iso(),
        )
        index_path = user_root / "samples.json"
        items = self._read_json_list(index_path)
        items.append(asdict(asset))
        self._write_json_list(index_path, items)
        return asset

    def rename_sample(self, user_id: int, asset_id: str, display_name: str) -> SampleAsset | None:
        clean_name = display_name.strip()
        if not clean_name:
            return None

        user_root = self._user_root(user_id)
        index_path = user_root / "samples.json"
        items = self._read_json_list(index_path)
        renamed: SampleAsset | None = None

        for item in items:
            if str(item.get("asset_id")) != asset_id:
                continue
            item["display_name"] = clean_name
            renamed = self._sample_asset_from_item(item)
            break

        if renamed is None:
            return None

        self._write_json_list(index_path, items)
        return renamed

    def delete_sample(self, user_id: int, asset_id: str) -> bool:
        user_root = self._user_root(user_id)
        index_path = user_root / "samples.json"
        items = self._read_json_list(index_path)
        kept = [item for item in items if str(item.get("asset_id")) != asset_id]
        if len(kept) == len(items):
            return False
        self._write_json_list(index_path, kept)
        return True

    def attach_coordinate_to_sample(self, user_id: int, sample_id: str, coordinate_id: str) -> SampleAsset | None:
        if self.get_coordinate(user_id, coordinate_id) is None:
            return None
        return self._attach_id_to_sample_list(user_id, sample_id, "coordinate_ids", coordinate_id)

    def get_sample_raw_file(self, user_id: int, sample_id: str) -> RawFileAsset | None:
        sample = self.get_sample(user_id, sample_id)
        if sample is None or not sample.raw_file_id:
            return None
        return self.get_raw_file(user_id, sample.raw_file_id)

    def list_sample_raw_files(self, user_id: int, sample_id: str) -> list[RawFileAsset]:
        asset = self.get_sample_raw_file(user_id, sample_id)
        return [asset] if asset is not None else []

    def list_unlinked_raw_files(self, user_id: int) -> list[RawFileAsset]:
        assigned = {item.raw_file_id for item in self.list_samples(user_id) if item.raw_file_id}
        return [item for item in self.list_raw_files(user_id) if item.asset_id not in assigned]

    def list_attachable_raw_files(self, user_id: int, sample_id: str) -> list[RawFileAsset]:
        sample = self.get_sample(user_id, sample_id)
        if sample is None or sample.raw_file_id:
            return []
        return self.list_unlinked_raw_files(user_id)

    def list_sample_coordinates(self, user_id: int, sample_id: str) -> list[CoordinateAsset]:
        sample = self.get_sample(user_id, sample_id)
        if sample is None:
            return []
        items: list[CoordinateAsset] = []
        for coordinate_id in sample.coordinate_ids:
            asset = self.get_coordinate(user_id, coordinate_id)
            if asset is not None:
                items.append(asset)
        return items

    def find_sample_by_coordinate(self, user_id: int, coordinate_id: str) -> SampleAsset | None:
        for sample in self.list_samples(user_id):
            if coordinate_id in sample.coordinate_ids:
                return sample
        return None

    def list_attachable_coordinates(self, user_id: int, sample_id: str) -> list[CoordinateAsset]:
        sample = self.get_sample(user_id, sample_id)
        if sample is None:
            return []
        attached = set(sample.coordinate_ids)
        return [item for item in self.list_coordinates(user_id) if item.asset_id not in attached]

    def list_coordinates(self, user_id: int) -> list[CoordinateAsset]:
        return [
            self._coordinate_asset_from_item(item)
            for item in self._read_json_list(self._user_root(user_id) / "coordinates.json")
        ]

    def get_coordinate(self, user_id: int, asset_id: str) -> CoordinateAsset | None:
        for item in self.list_coordinates(user_id):
            if item.asset_id == asset_id:
                return item
        return None

    def save_coordinate(
        self,
        user_id: int,
        *,
        display_name: str,
        target_name: str,
        coordinate_type: str,
        g25_line: str,
        input_mode: str,
    ) -> CoordinateAsset:
        user_root = self._user_root(user_id)
        user_root.mkdir(parents=True, exist_ok=True)
        asset = CoordinateAsset(
            asset_id=self._new_asset_id(),
            display_name=display_name.strip() or target_name.strip() or "coordinates",
            target_name=target_name.strip() or "Target",
            coordinate_type=coordinate_type.strip().lower() or "g25",
            g25_line=g25_line.strip(),
            input_mode=input_mode.strip() or "unknown",
            created_at=self._now_iso(),
        )
        index_path = user_root / "coordinates.json"
        items = self._read_json_list(index_path)
        items.insert(0, asdict(asset))
        self._write_json_list(index_path, items)
        return asset

    def delete_coordinate(self, user_id: int, asset_id: str) -> bool:
        user_root = self._user_root(user_id)
        index_path = user_root / "coordinates.json"
        items = self._read_json_list(index_path)
        kept = [item for item in items if str(item.get("asset_id")) != asset_id]
        if len(kept) == len(items):
            return False
        self._write_json_list(index_path, kept)
        self._detach_id_from_all_samples(user_id, "coordinate_ids", asset_id)
        return True

    def rename_coordinate(self, user_id: int, asset_id: str, display_name: str) -> CoordinateAsset | None:
        clean_name = display_name.strip()
        if not clean_name:
            return None

        user_root = self._user_root(user_id)
        index_path = user_root / "coordinates.json"
        items = self._read_json_list(index_path)
        renamed: CoordinateAsset | None = None

        for item in items:
            if str(item.get("asset_id")) != asset_id:
                continue
            item["display_name"] = clean_name
            renamed = self._coordinate_asset_from_item(item)
            break

        if renamed is None:
            return None

        self._write_json_list(index_path, items)
        return renamed

    def build_temp_path(self, user_id: int, file_name: str) -> Path:
        temp_dir = self._user_root(user_id) / "_tmp"
        temp_dir.mkdir(parents=True, exist_ok=True)
        suffix = Path(file_name).suffix
        temp_name = f"{self._new_asset_id()}{suffix}" if suffix else self._new_asset_id()
        return temp_dir / temp_name

    @staticmethod
    def cleanup_temp_file(path: Path) -> None:
        try:
            path.unlink()
        except (FileNotFoundError, OSError):
            return

    def resolve_raw_file_path(self, asset: RawFileAsset) -> Path:
        return self.root_dir / Path(asset.stored_path)

    def _user_root(self, user_id: int) -> Path:
        return self.root_dir / "users" / str(int(user_id))

    @staticmethod
    def _read_json_list(path: Path) -> list[dict[str, object]]:
        if not path.exists():
            return []
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return []
        if not isinstance(payload, list):
            return []
        return [item for item in payload if isinstance(item, dict)]

    @staticmethod
    def _write_json_list(path: Path, items: list[dict[str, object]]) -> None:
        write_json_atomic(path, items)

    @staticmethod
    def _coordinate_asset_from_item(item: dict[str, object]) -> CoordinateAsset:
        payload = dict(item)
        payload["asset_id"] = str(payload.get("asset_id") or MyDataStore._new_asset_id())
        payload["display_name"] = str(payload.get("display_name") or payload.get("target_name") or "coordinates")
        payload["target_name"] = str(payload.get("target_name") or payload.get("display_name") or "Target")
        payload["coordinate_type"] = str(payload.get("coordinate_type") or "g25").strip().lower() or "g25"
        payload["g25_line"] = str(payload.get("g25_line") or payload.get("line") or payload.get("coordinates") or "")
        payload["input_mode"] = str(payload.get("input_mode") or "unknown")
        payload["created_at"] = str(payload.get("created_at") or MyDataStore._now_iso())
        allowed = {field.name for field in CoordinateAsset.__dataclass_fields__.values()}
        payload = {key: value for key, value in payload.items() if key in allowed}
        return CoordinateAsset(**payload)

    @staticmethod
    def _sample_asset_from_item(item: dict[str, object]) -> SampleAsset:
        payload = dict(item)
        raw_file_id = str(payload.get("raw_file_id") or "").strip()
        if not raw_file_id:
            legacy_raw_ids = [str(value) for value in payload.get("raw_file_ids") or [] if str(value)]
            raw_file_id = legacy_raw_ids[0] if legacy_raw_ids else ""
        payload["raw_file_id"] = raw_file_id
        payload["coordinate_ids"] = [str(value) for value in payload.get("coordinate_ids") or [] if str(value)]
        payload.pop("raw_file_ids", None)
        return SampleAsset(**payload)

    def _attach_id_to_sample_list(self, user_id: int, sample_id: str, field_name: str, asset_id: str) -> SampleAsset | None:
        user_root = self._user_root(user_id)
        index_path = user_root / "samples.json"
        items = self._read_json_list(index_path)
        updated: SampleAsset | None = None

        for item in items:
            if str(item.get("asset_id")) != sample_id:
                continue
            values = [str(value) for value in item.get(field_name) or [] if str(value)]
            if asset_id not in values:
                values.append(asset_id)
            item[field_name] = values
            updated = self._sample_asset_from_item(item)
            break

        if updated is None:
            return None

        self._write_json_list(index_path, items)
        return updated

    def _detach_id_from_all_samples(self, user_id: int, field_name: str, asset_id: str) -> None:
        user_root = self._user_root(user_id)
        index_path = user_root / "samples.json"
        items = self._read_json_list(index_path)
        changed = False

        for item in items:
            values = [str(value) for value in item.get(field_name) or [] if str(value)]
            filtered = [value for value in values if value != asset_id]
            if filtered != values:
                item[field_name] = filtered
                changed = True

        if changed:
            self._write_json_list(index_path, items)

    @staticmethod
    def _new_asset_id() -> str:
        return datetime.now().strftime("%Y%m%d%H%M%S%f") + "-" + uuid4().hex[:8]

    @staticmethod
    def _now_iso() -> str:
        return datetime.now().isoformat(timespec="seconds")
