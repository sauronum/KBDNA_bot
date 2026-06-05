from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from app.storage_io import write_json_atomic


@dataclass(frozen=True)
class AdmixtureReportSummary:
    report_id: str
    sample_id: str
    sample_name: str
    coordinate_id: str
    coordinate_name: str
    model: str
    title: str
    strongest_component: str
    strongest_component_value: float
    macro_summary: str
    created_at: str


@dataclass(frozen=True)
class AdmixtureReportRecord:
    summary: AdmixtureReportSummary
    technical_payload: dict[str, object]
    product_payload: dict[str, object]


class AdmixtureReportStore:
    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def save_report(
        self,
        user_id: int,
        *,
        sample_id: str,
        sample_name: str,
        coordinate_id: str,
        coordinate_name: str,
        technical_payload: dict[str, object],
        product_payload: dict[str, object],
    ) -> AdmixtureReportRecord:
        existing = self.find_report_for_coordinate(user_id, sample_id, coordinate_id, str(product_payload.get("model") or "K36"))
        report_id = existing.summary.report_id if existing is not None else self._new_report_id()
        top_components = list(product_payload.get("top_components") or [])
        macro_groups = list(product_payload.get("macro_groups") or [])
        strongest = top_components[0] if top_components and isinstance(top_components[0], dict) else {}
        macro = macro_groups[0] if macro_groups and isinstance(macro_groups[0], dict) else {}
        model = str(product_payload.get("model") or "K36")
        title = f"{model} profile"
        summary = AdmixtureReportSummary(
            report_id=report_id,
            sample_id=sample_id,
            sample_name=sample_name,
            coordinate_id=coordinate_id,
            coordinate_name=coordinate_name,
            model=model,
            title=title,
            strongest_component=str(strongest.get("name") or ""),
            strongest_component_value=self._float(strongest.get("value")),
            macro_summary=str(macro.get("name") or ""),
            created_at=self._now_iso(),
        )
        record = AdmixtureReportRecord(
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
            if not (
                str(item.get("coordinate_id") or "") == coordinate_id
                and str(item.get("model") or "K36") == model
            )
        ]
        items.insert(0, asdict(summary))
        self._write_json_list(index_path, items)
        return record

    def list_reports(self, user_id: int, sample_id: str) -> list[AdmixtureReportSummary]:
        reports = [
            AdmixtureReportSummary(**item)
            for item in self._read_json_list(self._sample_index_path(user_id, sample_id))
        ]
        return self._dedupe_summaries(reports)

    def list_all_reports(self, user_id: int) -> list[AdmixtureReportSummary]:
        root = self._user_root(user_id) / "samples"
        if not root.exists():
            return []
        reports: list[AdmixtureReportSummary] = []
        for index_path in root.glob("*/admixture_reports.json"):
            reports.extend(
                AdmixtureReportSummary(**item)
                for item in self._read_json_list(index_path)
            )
        return self._dedupe_summaries(reports)

    def find_report_for_coordinate(
        self,
        user_id: int,
        sample_id: str,
        coordinate_id: str,
        model: str,
    ) -> AdmixtureReportRecord | None:
        for summary in self.list_reports(user_id, sample_id):
            if summary.coordinate_id == coordinate_id and summary.model == model:
                return self.find_report(user_id, summary.report_id)
        return None

    def find_report(self, user_id: int, report_id: str) -> AdmixtureReportRecord | None:
        path = self._report_path(user_id, report_id)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        if not isinstance(payload, dict):
            return None
        return AdmixtureReportRecord(
            summary=AdmixtureReportSummary(**payload["summary"]),
            technical_payload=dict(payload.get("technical_payload") or {}),
            product_payload=dict(payload.get("product_payload") or {}),
        )

    def _user_root(self, user_id: int) -> Path:
        return self.root_dir / "users" / str(int(user_id))

    def _sample_index_path(self, user_id: int, sample_id: str) -> Path:
        return self._user_root(user_id) / "samples" / sample_id / "admixture_reports.json"

    def _report_path(self, user_id: int, report_id: str) -> Path:
        return self._user_root(user_id) / "reports" / f"{report_id}.json"

    @staticmethod
    def _dedupe_summaries(reports: list[AdmixtureReportSummary]) -> list[AdmixtureReportSummary]:
        seen: set[tuple[str, str]] = set()
        deduped: list[AdmixtureReportSummary] = []
        for report in reports:
            key = (report.model, report.coordinate_id)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(report)
        return deduped

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
    def _float(value: object) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _new_report_id() -> str:
        return datetime.now().strftime("%Y%m%d%H%M%S%f") + "-" + uuid4().hex[:8]

    @staticmethod
    def _now_iso() -> str:
        return datetime.now().isoformat(timespec="seconds")
