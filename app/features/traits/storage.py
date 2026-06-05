from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from app.storage_io import write_json_atomic


@dataclass(frozen=True)
class TraitReportSummary:
    report_id: str
    sample_id: str
    sample_name: str
    raw_file_id: str
    trait_id: str
    display_name: str
    short_name: str
    confidence: str
    percentile: float | None
    product_status: str
    status: str
    result_summary: str
    created_at: str


@dataclass(frozen=True)
class TraitReportRecord:
    summary: TraitReportSummary
    technical_payload: dict[str, object]
    product_payload: dict[str, object]


class TraitReportStore:
    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def save_report(
        self,
        user_id: int,
        *,
        sample_id: str,
        sample_name: str,
        raw_file_id: str,
        technical_payload: dict[str, object],
        product_payload: dict[str, object],
    ) -> TraitReportRecord:
        report_id = self._new_report_id()
        summary = TraitReportSummary(
            report_id=report_id,
            sample_id=sample_id,
            sample_name=sample_name,
            raw_file_id=raw_file_id,
            trait_id=str(product_payload.get("trait_id") or technical_payload.get("trait_id") or ""),
            display_name=str(product_payload.get("display_name") or ""),
            short_name=str(product_payload.get("short_name") or product_payload.get("display_name") or ""),
            confidence=str(product_payload.get("confidence") or technical_payload.get("confidence") or "unknown"),
            percentile=self._optional_float(product_payload.get("percentile")),
            product_status=str(product_payload.get("product_status") or ""),
            status=str(product_payload.get("status") or ""),
            result_summary=str(product_payload.get("result_summary") or ""),
            created_at=self._now_iso(),
        )
        record = TraitReportRecord(
            summary=summary,
            technical_payload=dict(technical_payload),
            product_payload=dict(product_payload),
        )

        report_path = self._report_path(user_id, report_id)
        write_json_atomic(
            report_path,
            {
                "summary": asdict(summary),
                "technical_payload": record.technical_payload,
                "product_payload": record.product_payload,
            },
        )

        index_path = self._sample_index_path(user_id, sample_id)
        items = [
            item
            for item in self._read_json_list(index_path)
            if str(item.get("trait_id") or "") != summary.trait_id
        ]
        items.insert(0, asdict(summary))
        self._write_json_list(index_path, items)
        return record

    def list_reports(self, user_id: int, sample_id: str) -> list[TraitReportSummary]:
        return [
            TraitReportSummary(**item)
            for item in self._read_json_list(self._sample_index_path(user_id, sample_id))
        ]

    def count_reports_by_sample(self, user_id: int) -> dict[str, int]:
        samples_root = self._user_root(user_id) / "samples"
        if not samples_root.exists():
            return {}
        counts: dict[str, int] = {}
        for sample_dir in samples_root.iterdir():
            if not sample_dir.is_dir():
                continue
            counts[sample_dir.name] = len(self._read_json_list(sample_dir / "trait_reports.json"))
        return counts

    def find_report(self, user_id: int, report_id: str) -> TraitReportRecord | None:
        path = self._report_path(user_id, report_id)
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        return TraitReportRecord(
            summary=TraitReportSummary(**payload["summary"]),
            technical_payload=dict(payload.get("technical_payload") or {}),
            product_payload=dict(payload.get("product_payload") or {}),
        )

    def _user_root(self, user_id: int) -> Path:
        return self.root_dir / "users" / str(int(user_id))

    def _sample_index_path(self, user_id: int, sample_id: str) -> Path:
        return self._user_root(user_id) / "samples" / sample_id / "trait_reports.json"

    def _report_path(self, user_id: int, report_id: str) -> Path:
        return self._user_root(user_id) / "reports" / f"{report_id}.json"

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
    def _optional_float(value: object) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _new_report_id() -> str:
        return datetime.now().strftime("%Y%m%d%H%M%S%f") + "-" + uuid4().hex[:8]

    @staticmethod
    def _now_iso() -> str:
        return datetime.now().isoformat(timespec="seconds")
