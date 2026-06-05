from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from app.features.my_data.storage import SampleAsset
from app.storage_io import write_json_atomic

from .domain import PairwiseMatchResult


@dataclass(frozen=True)
class MatchingRecordSummary:
    match_id: str
    left_sample_id: str
    left_sample_name: str
    right_sample_id: str
    right_sample_name: str
    total_estimated_cm: float
    longest_estimated_cm: float
    segment_count: int
    relationship_hint: str
    created_at: str


@dataclass(frozen=True)
class MatchingRecord:
    summary: MatchingRecordSummary
    payload: dict[str, object]


class MatchingStore:
    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def save_pairwise_match(
        self,
        user_id: int,
        left: SampleAsset,
        right: SampleAsset,
        result: PairwiseMatchResult,
    ) -> MatchingRecord:
        existing = self.find_pairwise_match(user_id, left.asset_id, right.asset_id)
        match_id = existing.summary.match_id if existing is not None else self._new_match_id()
        summary = MatchingRecordSummary(
            match_id=match_id,
            left_sample_id=left.asset_id,
            left_sample_name=left.display_name,
            right_sample_id=right.asset_id,
            right_sample_name=right.display_name,
            total_estimated_cm=result.total_estimated_cm,
            longest_estimated_cm=result.longest_estimated_cm,
            segment_count=len(result.segments),
            relationship_hint=result.relationship_hint,
            created_at=self._now_iso(),
        )
        record = MatchingRecord(summary=summary, payload=self._result_payload(result))
        self._write_record(user_id, record)
        self._write_index(user_id, summary)
        return record

    def list_matches(self, user_id: int) -> list[MatchingRecordSummary]:
        items = [
            MatchingRecordSummary(**item)
            for item in self._read_json_list(self._index_path(user_id))
        ]
        return sorted(items, key=lambda item: item.created_at, reverse=True)

    def list_matches_for_sample(self, user_id: int, sample_id: str) -> list[MatchingRecordSummary]:
        return [
            item
            for item in self.list_matches(user_id)
            if item.left_sample_id == sample_id or item.right_sample_id == sample_id
        ]

    def find_match(self, user_id: int, match_id: str) -> MatchingRecord | None:
        path = self._record_path(user_id, match_id)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        if not isinstance(payload, dict):
            return None
        return MatchingRecord(
            summary=MatchingRecordSummary(**payload["summary"]),
            payload=dict(payload.get("payload") or {}),
        )

    def find_pairwise_match(self, user_id: int, left_sample_id: str, right_sample_id: str) -> MatchingRecord | None:
        key = self._pair_key(left_sample_id, right_sample_id)
        for summary in self.list_matches(user_id):
            if self._pair_key(summary.left_sample_id, summary.right_sample_id) == key:
                return self.find_match(user_id, summary.match_id)
        return None

    def _write_record(self, user_id: int, record: MatchingRecord) -> None:
        path = self._record_path(user_id, record.summary.match_id)
        write_json_atomic(
            path,
            {
                "summary": asdict(record.summary),
                "payload": record.payload,
            },
        )

    def _write_index(self, user_id: int, summary: MatchingRecordSummary) -> None:
        index_path = self._index_path(user_id)
        pair_key = self._pair_key(summary.left_sample_id, summary.right_sample_id)
        items = [
            item
            for item in self._read_json_list(index_path)
            if self._pair_key(str(item.get("left_sample_id") or ""), str(item.get("right_sample_id") or "")) != pair_key
        ]
        items.insert(0, asdict(summary))
        self._write_json_list(index_path, items)

    def _user_root(self, user_id: int) -> Path:
        return self.root_dir / "users" / str(int(user_id))

    def _index_path(self, user_id: int) -> Path:
        return self._user_root(user_id) / "matches.json"

    def _record_path(self, user_id: int, match_id: str) -> Path:
        return self._user_root(user_id) / "records" / f"{match_id}.json"

    @staticmethod
    def _result_payload(result: PairwiseMatchResult) -> dict[str, object]:
        return {
            "overlap_snps": result.overlap_snps,
            "shared_snps": result.half_identical_snps,
            "identical_snps": result.identical_snps,
            "total_estimated_cm": result.total_estimated_cm,
            "longest_estimated_cm": result.longest_estimated_cm,
            "relationship_hint": result.relationship_hint,
            "genetic_map_used": result.genetic_map_used,
            "segments": [
                {
                    "chromosome": segment.chromosome,
                    "start": segment.start,
                    "end": segment.end,
                    "snp_count": segment.snp_count,
                    "identical_snps": segment.identical_snps,
                    "estimated_cm": segment.estimated_cm,
                }
                for segment in result.segments
            ],
        }

    @staticmethod
    def _pair_key(left_sample_id: str, right_sample_id: str) -> tuple[str, str]:
        return tuple(sorted((left_sample_id, right_sample_id)))

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
    def _new_match_id() -> str:
        return datetime.now().strftime("%Y%m%d%H%M%S%f") + "-" + uuid4().hex[:8]

    @staticmethod
    def _now_iso() -> str:
        return datetime.now().isoformat(timespec="seconds")
