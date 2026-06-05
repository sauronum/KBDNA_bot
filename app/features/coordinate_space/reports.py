from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from dataclasses import fields
from datetime import datetime
from pathlib import Path
import shutil
from uuid import uuid4

from app.storage_io import write_json_atomic


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CoordinateSpaceResult:
    result_id: str
    sample_id: str
    coordinate_id: str
    title: str
    mode: str
    coordinate_system: str
    session_id: str
    preset_id: str | None = None
    summary_lines: list[str] = field(default_factory=list)
    top_populations: list[str] = field(default_factory=list)
    config_snapshot: dict[str, object] = field(default_factory=dict)
    created_at: str = ""
    image_path: str = ""
    caption: str = ""


class CoordinateSpaceReportStore:
    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def save_result(
        self,
        user_id: int,
        *,
        sample_id: str,
        coordinate_id: str,
        title: str,
        mode: str,
        coordinate_system: str,
        session_id: str,
        preset_id: str | None = None,
        summary_lines: list[str] | None = None,
        top_populations: list[str] | None = None,
        config_snapshot: dict[str, object] | None = None,
        image_source_path: Path | None = None,
        caption: str = "",
    ) -> CoordinateSpaceResult:
        result_id = self._new_id()
        image_path = ""
        if image_source_path is not None:
            try:
                artifact_path = self._artifact_path(user_id, result_id)
                artifact_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(image_source_path), str(artifact_path))
                image_path = str(artifact_path.relative_to(self.root_dir))
            except Exception:
                logger.exception("Could not save Coordinate Space report PNG artifact")

        result = CoordinateSpaceResult(
            result_id=result_id,
            sample_id=sample_id,
            coordinate_id=coordinate_id,
            title=title.strip() or "Coordinate space result",
            mode=mode,
            coordinate_system=coordinate_system.strip() or "G25",
            session_id=session_id,
            preset_id=preset_id,
            summary_lines=list(summary_lines or []),
            top_populations=list(top_populations or []),
            config_snapshot=dict(config_snapshot or {}),
            created_at=self._now_iso(),
            image_path=image_path,
            caption=caption.strip(),
        )
        payload = asdict(result)

        report_path = self._result_path(user_id, result.result_id)
        write_json_atomic(report_path, payload)

        index_path = self._sample_index_path(user_id, sample_id)
        items = self._read_json_list(index_path)
        items.insert(0, payload)
        self._write_json_list(index_path, items)
        return result

    def list_results(self, user_id: int, sample_id: str) -> list[CoordinateSpaceResult]:
        results: list[CoordinateSpaceResult] = []
        for item in self._read_json_list(self._sample_index_path(user_id, sample_id)):
            try:
                results.append(self._result_from_payload(item))
            except Exception:
                logger.exception("Could not read Coordinate Space report from sample index")
        return results

    def find_result(self, user_id: int, result_id: str) -> CoordinateSpaceResult | None:
        path = self._result_path(user_id, result_id)
        if not path.exists():
            return self._find_result_in_sample_indexes(user_id, result_id)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return self._find_result_in_sample_indexes(user_id, result_id)
        if not isinstance(payload, dict):
            return self._find_result_in_sample_indexes(user_id, result_id)
        if not self._payload_has_report_body(payload):
            return self._find_result_in_sample_indexes(user_id, result_id)
        try:
            return self._result_from_payload(payload)
        except Exception:
            logger.exception("Could not read Coordinate Space report record: %s", result_id)
            return self._find_result_in_sample_indexes(user_id, result_id)

    def delete_result(self, user_id: int, result_id: str) -> CoordinateSpaceResult | None:
        report = self.find_result(user_id, result_id)
        if report is None:
            return None

        path = self._result_path(user_id, result_id)
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            logger.exception("Could not delete Coordinate Space report record: %s", result_id)

        index_path = self._sample_index_path(user_id, report.sample_id)
        items = [
            item
            for item in self._read_json_list(index_path)
            if str(item.get("result_id")) != result_id
        ]
        self._write_json_list(index_path, items)

        artifact_path = self.resolve_image_path(report)
        if artifact_path is not None and artifact_path.exists():
            try:
                artifact_path.unlink()
            except OSError:
                logger.exception("Could not delete Coordinate Space report PNG artifact: %s", artifact_path)
        return report

    def resolve_image_path(self, report: CoordinateSpaceResult) -> Path | None:
        raw_path = str(getattr(report, "image_path", "") or "").strip()
        if not raw_path:
            return None
        path = Path(raw_path)
        if path.is_absolute():
            return path
        return self.root_dir / path

    def _user_root(self, user_id: int) -> Path:
        return self.root_dir / "users" / str(int(user_id))

    def _sample_index_path(self, user_id: int, sample_id: str) -> Path:
        return self._user_root(user_id) / "samples" / sample_id / "coordinate_space_reports.json"

    def _result_path(self, user_id: int, result_id: str) -> Path:
        return self._user_root(user_id) / "reports" / f"{result_id}.json"

    def _artifact_path(self, user_id: int, result_id: str) -> Path:
        return self._user_root(user_id) / "artifacts" / f"{result_id}.png"

    def _find_result_in_sample_indexes(self, user_id: int, result_id: str) -> CoordinateSpaceResult | None:
        samples_root = self._user_root(user_id) / "samples"
        if not samples_root.exists():
            return None
        for index_path in samples_root.glob("*/coordinate_space_reports.json"):
            for item in self._read_json_list(index_path):
                if self._payload_result_id(item) == result_id:
                    try:
                        return self._result_from_payload(item)
                    except Exception:
                        logger.exception("Could not read Coordinate Space report from index: %s", result_id)
        return None

    @staticmethod
    def _result_from_payload(payload: dict[str, object]) -> CoordinateSpaceResult:
        allowed = {item.name for item in fields(CoordinateSpaceResult)}
        clean_payload = {key: value for key, value in payload.items() if key in allowed}
        clean_payload.setdefault("result_id", CoordinateSpaceReportStore._payload_result_id(payload))
        clean_payload.setdefault("sample_id", str(payload.get("sample_id") or ""))
        clean_payload.setdefault("coordinate_id", str(payload.get("coordinate_id") or payload.get("target_id") or ""))
        clean_payload.setdefault("title", str(payload.get("title") or payload.get("space_title") or payload.get("preset_title") or "Coordinate space result"))
        clean_payload.setdefault("mode", str(payload.get("mode") or payload.get("view_mode") or "region"))
        clean_payload.setdefault("coordinate_system", str(payload.get("coordinate_system") or payload.get("system") or "G25"))
        clean_payload.setdefault("session_id", str(payload.get("session_id") or "saved_report"))
        clean_payload.setdefault("summary_lines", CoordinateSpaceReportStore._payload_list(payload.get("summary_lines") or payload.get("summary")))
        clean_payload.setdefault("top_populations", CoordinateSpaceReportStore._payload_list(payload.get("top_populations") or payload.get("top")))
        clean_payload.setdefault("config_snapshot", dict(payload.get("config_snapshot") or {}))
        clean_payload.setdefault("created_at", str(payload.get("created_at") or payload.get("created") or ""))
        clean_payload.setdefault("image_path", str(payload.get("image_path") or payload.get("png_path") or payload.get("visual_artifact_path") or ""))
        clean_payload.setdefault("caption", str(payload.get("caption") or ""))
        return CoordinateSpaceResult(**clean_payload)

    @staticmethod
    def _payload_result_id(payload: dict[str, object]) -> str:
        return str(payload.get("result_id") or payload.get("report_id") or payload.get("id") or "").strip()

    @staticmethod
    def _payload_has_report_body(payload: dict[str, object]) -> bool:
        return any(
            str(payload.get(key) or "").strip()
            for key in (
                "title",
                "space_title",
                "preset_title",
                "mode",
                "view_mode",
                "coordinate_system",
                "summary_lines",
                "summary",
                "caption",
                "image_path",
                "png_path",
                "visual_artifact_path",
            )
        )

    @staticmethod
    def _payload_list(value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item) for item in value]
        if isinstance(value, tuple):
            return [str(item) for item in value]
        return [str(value)]

    @staticmethod
    def _new_id() -> str:
        return datetime.utcnow().strftime("%Y%m%d%H%M%S%f") + "-" + uuid4().hex[:8]

    @staticmethod
    def _now_iso() -> str:
        return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

    @staticmethod
    def _read_json_list(path: Path) -> list[dict[str, object]]:
        if not path.exists():
            return []
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        return []

    @staticmethod
    def _write_json_list(path: Path, items: list[dict[str, object]]) -> None:
        write_json_atomic(path, items)
