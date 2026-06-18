from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from app.storage_io import write_json_atomic


@dataclass(frozen=True)
class HaplogroupRecord:
    record_id: str
    sample_id: str
    sample_name: str
    haplogroup_type: str
    haplogroup: str
    terminal_snp: str
    source: str
    confidence: str
    note: str
    created_at: str


@dataclass(frozen=True)
class YStrProfile:
    profile_id: str
    sample_id: str
    sample_name: str
    source: str
    marker_values: dict[str, list[int]]
    marker_count: int
    created_at: str


class HaplogroupStore:
    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def save_record(
        self,
        user_id: int,
        *,
        sample_id: str,
        sample_name: str,
        haplogroup_type: str,
        haplogroup: str,
        terminal_snp: str = "",
        source: str = "",
        confidence: str = "user-entered",
        note: str = "",
    ) -> HaplogroupRecord:
        record = HaplogroupRecord(
            record_id=self._new_record_id(),
            sample_id=sample_id,
            sample_name=sample_name.strip()[:160],
            haplogroup_type=haplogroup_type,
            haplogroup=haplogroup.strip()[:80],
            terminal_snp=terminal_snp.strip()[:80],
            source=source.strip()[:160],
            confidence=(confidence.strip() or "user-entered")[:80],
            note=note.strip()[:2000],
            created_at=self._now_iso(),
        )
        path = self._index_path(user_id)
        record_key = self._record_key(asdict(record))
        items = [
            item
            for item in self._read_json_list(path)
            if self._record_key(item) != record_key
        ]
        items.insert(0, asdict(record))
        self._write_json_list(path, items)
        return record

    def list_records(self, user_id: int) -> list[HaplogroupRecord]:
        return [
            HaplogroupRecord(**item)
            for item in self._dedupe_record_items(self._read_json_list(self._index_path(user_id)))
        ]

    def list_sample_records(self, user_id: int, sample_id: str) -> list[HaplogroupRecord]:
        return [record for record in self.list_records(user_id) if record.sample_id == sample_id]

    def find_record(self, user_id: int, record_id: str) -> HaplogroupRecord | None:
        for record in self.list_records(user_id):
            if record.record_id == record_id:
                return record
        return None

    def delete_sample_data(self, user_id: int, sample_id: str) -> tuple[int, int]:
        record_path = self._index_path(user_id)
        record_items = self._read_json_list(record_path)
        kept_records = [item for item in record_items if str(item.get("sample_id") or "") != sample_id]
        removed_records = len(record_items) - len(kept_records)
        if removed_records:
            self._write_json_list(record_path, kept_records)

        profile_path = self._str_index_path(user_id)
        profile_items = self._read_json_list(profile_path)
        kept_profiles = [item for item in profile_items if str(item.get("sample_id") or "") != sample_id]
        removed_profiles = len(profile_items) - len(kept_profiles)
        if removed_profiles:
            self._write_json_list(profile_path, kept_profiles)
        return removed_records, removed_profiles

    def save_y_str_profile(
        self,
        user_id: int,
        *,
        sample_id: str,
        sample_name: str,
        source: str,
        marker_values: dict[str, list[int]],
    ) -> YStrProfile:
        profile = YStrProfile(
            profile_id=self._new_record_id(),
            sample_id=sample_id,
            sample_name=sample_name.strip()[:160],
            source=(source.strip() or "uploaded file")[:160],
            marker_values={key: list(values) for key, values in sorted(marker_values.items())},
            marker_count=len(marker_values),
            created_at=self._now_iso(),
        )
        path = self._str_index_path(user_id)
        items = [
            item
            for item in self._read_json_list(path)
            if str(item.get("sample_id") or "") != sample_id
        ]
        items.insert(0, asdict(profile))
        self._write_json_list(path, items)
        return profile

    def list_y_str_profiles(self, user_id: int) -> list[YStrProfile]:
        return [
            self._str_profile_from_item(item)
            for item in self._read_json_list(self._str_index_path(user_id))
        ]

    def find_y_str_profile(self, user_id: int, profile_id: str) -> YStrProfile | None:
        for profile in self.list_y_str_profiles(user_id):
            if profile.profile_id == profile_id:
                return profile
        return None

    def get_sample_y_str_profile(self, user_id: int, sample_id: str) -> YStrProfile | None:
        for profile in self.list_y_str_profiles(user_id):
            if profile.sample_id == sample_id:
                return profile
        return None

    def _index_path(self, user_id: int) -> Path:
        return self.root_dir / "users" / str(int(user_id)) / "haplogroups.json"

    def _str_index_path(self, user_id: int) -> Path:
        return self.root_dir / "users" / str(int(user_id)) / "y_str_profiles.json"

    @staticmethod
    def _read_json_list(path: Path) -> list[dict[str, object]]:
        if not path.exists():
            return []
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return []
        if not isinstance(payload, list):
            return []
        return [item for item in payload if isinstance(item, dict)]

    @staticmethod
    def _write_json_list(path: Path, items: list[dict[str, object]]) -> None:
        write_json_atomic(path, items)

    @classmethod
    def _dedupe_record_items(cls, items: list[dict[str, object]]) -> list[dict[str, object]]:
        deduped: list[dict[str, object]] = []
        seen: set[tuple[str, str, str, str]] = set()
        for item in items:
            key = cls._record_key(item)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        return deduped

    @staticmethod
    def _record_key(item: dict[str, object]) -> tuple[str, str, str, str]:
        return (
            str(item.get("sample_id") or "").strip(),
            str(item.get("haplogroup_type") or "").strip().lower(),
            str(item.get("haplogroup") or "").strip().lower(),
            str(item.get("terminal_snp") or "").strip().lower(),
        )

    @staticmethod
    def _str_profile_from_item(item: dict[str, object]) -> YStrProfile:
        payload = dict(item)
        raw_markers = payload.get("marker_values") if isinstance(payload.get("marker_values"), dict) else {}
        payload["marker_values"] = {
            str(marker): [int(value) for value in values if str(value).strip().lstrip("-").isdigit()]
            for marker, values in raw_markers.items()
            if isinstance(values, list)
        }
        payload["marker_count"] = int(payload.get("marker_count") or len(payload["marker_values"]))
        return YStrProfile(**payload)

    @staticmethod
    def _new_record_id() -> str:
        return datetime.now().strftime("%Y%m%d%H%M%S%f") + "-" + uuid4().hex[:8]

    @staticmethod
    def _now_iso() -> str:
        return datetime.now().isoformat(timespec="seconds")
