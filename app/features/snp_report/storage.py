from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from app.storage_io import write_json_atomic

from .domain import SnpReportResult


@dataclass(frozen=True)
class SnpReportSummary:
    report_id: str
    sample_id: str
    sample_name: str
    raw_file_id: str
    created_at: str
    total_rules: int
    ok: int
    warn: int
    bad: int
    missing: int
    html_path: str


@dataclass(frozen=True)
class SnpReportRecord:
    summary: SnpReportSummary
    payload: dict[str, object]


class SnpReportStore:
    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def save_report(self, user_id: int, result: SnpReportResult, html_text: str) -> SnpReportRecord:
        report_id = uuid4().hex[:12]
        created_at = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
        sample_dir = self._sample_root(user_id, result.sample_id)
        sample_dir.mkdir(parents=True, exist_ok=True)

        html_rel_path = Path("users") / str(user_id) / "samples" / result.sample_id / f"{report_id}.html"
        html_path = self.root_dir / html_rel_path
        html_path.write_text(html_text, encoding="utf-8")

        summary = SnpReportSummary(
            report_id=report_id,
            sample_id=result.sample_id,
            sample_name=result.sample_name,
            raw_file_id=result.raw_file_id,
            created_at=created_at,
            total_rules=result.total_rules,
            ok=result.ok,
            warn=result.warn,
            bad=result.bad,
            missing=result.missing,
            html_path=str(html_rel_path),
        )
        payload = {
            "summary": asdict(summary),
            "categories": [asdict(item) for item in result.categories],
            "rows": [asdict(item) for item in result.rows],
        }
        write_json_atomic(sample_dir / f"{report_id}.json", payload)

        index_path = self._sample_index_path(user_id, result.sample_id)
        items = self._read_json_list(index_path)
        items.insert(0, asdict(summary))
        self._write_json_list(index_path, items)
        return SnpReportRecord(summary=summary, payload=payload)

    def find_report(self, user_id: int, report_id: str) -> SnpReportRecord | None:
        user_root = self._user_root(user_id) / "samples"
        if not user_root.exists():
            return None
        for sample_dir in user_root.iterdir():
            if not sample_dir.is_dir():
                continue
            payload_path = sample_dir / f"{report_id}.json"
            if not payload_path.exists():
                continue
            try:
                payload = json.loads(payload_path.read_text(encoding="utf-8"))
                return SnpReportRecord(summary=SnpReportSummary(**payload["summary"]), payload=payload)
            except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
                return None
        return None

    def resolve_html_path(self, summary: SnpReportSummary) -> Path:
        return self.root_dir / summary.html_path

    def _user_root(self, user_id: int) -> Path:
        return self.root_dir / "users" / str(user_id)

    def _sample_root(self, user_id: int, sample_id: str) -> Path:
        return self._user_root(user_id) / "samples" / sample_id

    def _sample_index_path(self, user_id: int, sample_id: str) -> Path:
        return self._sample_root(user_id, sample_id) / "snp_reports.json"

    @staticmethod
    def _read_json_list(path: Path) -> list[dict[str, object]]:
        if not path.exists():
            return []
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        if not isinstance(payload, list):
            return []
        return [item for item in payload if isinstance(item, dict)]

    @staticmethod
    def _write_json_list(path: Path, items: list[dict[str, object]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json_atomic(path, items)
