from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

from app.features.coordinate_space.g25_summary import summarize_g25_coordinate
from app.features.my_data.storage import CoordinateAsset, MyDataStore, RawFileAsset, SampleAsset
from app.features.snp_report.interesting import InterestingSnpDefinition, analyze_interesting_snps, load_interesting_snps
from app.features.traits.domain.catalog import TraitCatalog
from app.features.traits.domain.runtime import TraitsRuntimeService
from g25_core.command_service import G25CommandError, G25CommandService
from g25_core.g25_engine import MISSING_GENOTYPES, parse_raw_dna

from .domain import (
    DNAPassportData,
    DNAPassportG25Population,
    DNAPassportG25Summary,
    DNAPassportInterestingSnpItem,
    DNAPassportInterestingSnpsSummary,
    DNAPassportLineageReadiness,
    DNAPassportRawSummary,
    DNAPassportSampleSummary,
    DNAPassportTraitItem,
    DNAPassportTraitsSummary,
)


DNA_PASSPORT_TRAIT_IDS: tuple[str, ...] = (
    "pgs003835_height",
    "pgs000336_chronotype",
    "pgs001123_coffee",
    "pgs001150_sleep_duration",
    "pgs001927_mean_hand_grip_strength",
    "pgs001075_walking_pace",
    "pgs001897_skin_pigmentation",
    "pgs002011_water_intake",
)


class DNAPassportService:
    def __init__(
        self,
        *,
        my_data_store: MyDataStore,
        traits_runtime: TraitsRuntimeService | None = None,
        g25_service: G25CommandService | None = None,
        trait_ids: Sequence[str] = DNA_PASSPORT_TRAIT_IDS,
        interesting_snp_panel: Sequence[InterestingSnpDefinition] | None = None,
    ) -> None:
        self.my_data_store = my_data_store
        self.traits_runtime = traits_runtime or TraitsRuntimeService(TraitCatalog())
        self.g25_service = g25_service
        self.trait_ids = tuple(trait_ids)
        self.interesting_snp_panel = tuple(interesting_snp_panel) if interesting_snp_panel is not None else None

    def build_for_sample(
        self,
        *,
        user_id: int,
        sample_id: str,
        g25_coordinate_id: str | None = None,
        g25_coordinate: CoordinateAsset | None = None,
    ) -> DNAPassportData:
        warnings: list[str] = []
        sample = self._get_sample(user_id, sample_id, warnings)
        sample_summary = self._build_sample_summary(sample, sample_id)

        raw_file = self._get_raw_file(user_id, sample, warnings)
        raw_path = self._resolve_raw_path(raw_file, warnings)
        raw_summary = self._build_raw_summary(raw_file, raw_path)

        coordinate = self._get_g25_input(
            user_id,
            sample,
            raw_path,
            coordinate_id=g25_coordinate_id,
            coordinate=g25_coordinate,
            warnings=warnings,
        )
        g25_summary = self._build_g25_summary(coordinate)
        traits_summary = self._build_traits_summary(raw_path, sample_name=sample.display_name if sample is not None else "")
        interesting_snps = self._build_interesting_snps_summary(raw_path, sample_id=sample_id, sample_name=sample.display_name if sample is not None else "")
        lineage = self._build_lineage_readiness(raw_summary)

        return DNAPassportData(
            sample=sample_summary,
            raw=raw_summary,
            g25=g25_summary,
            traits=traits_summary,
            interesting_snps=interesting_snps,
            lineage=lineage,
            warnings=tuple(warnings),
            generated_at=datetime.utcnow().isoformat(timespec="seconds") + "Z",
        )

    def _get_sample(self, user_id: int, sample_id: str, warnings: list[str]) -> SampleAsset | None:
        try:
            return self.my_data_store.get_sample(user_id, sample_id)
        except Exception as exc:
            warnings.append(f"sample lookup failed: {exc}")
            return None

    @staticmethod
    def _build_sample_summary(sample: SampleAsset | None, sample_id: str) -> DNAPassportSampleSummary:
        if sample is None:
            return DNAPassportSampleSummary(status="unavailable", sample_id=sample_id, error="sample not found")
        return DNAPassportSampleSummary(
            status="ok",
            sample_id=sample.asset_id,
            display_name=sample.display_name,
            created_at=sample.created_at,
        )

    def _get_raw_file(
        self,
        user_id: int,
        sample: SampleAsset | None,
        warnings: list[str],
    ) -> RawFileAsset | None:
        if sample is None or not sample.raw_file_id:
            return None
        try:
            return self.my_data_store.get_sample_raw_file(user_id, sample.asset_id)
        except Exception as exc:
            warnings.append(f"raw lookup failed: {exc}")
            return None

    def _resolve_raw_path(self, raw_file: RawFileAsset | None, warnings: list[str]) -> Path | None:
        if raw_file is None:
            return None
        try:
            path = self.my_data_store.resolve_raw_file_path(raw_file)
        except Exception as exc:
            warnings.append(f"raw path resolve failed: {exc}")
            return None
        return path if path.exists() else None

    def _build_raw_summary(self, raw_file: RawFileAsset | None, raw_path: Path | None) -> DNAPassportRawSummary:
        if raw_file is None:
            return DNAPassportRawSummary(status="unavailable", error="raw file is not attached")
        base = {
            "raw_file_id": raw_file.asset_id,
            "display_name": raw_file.display_name,
            "original_file_name": raw_file.original_file_name,
        }
        if raw_path is None:
            return DNAPassportRawSummary(status="unavailable", error="raw file is missing on disk", **base)
        try:
            summary, calls = parse_raw_dna(raw_path)
        except Exception as exc:
            return DNAPassportRawSummary(status="error", error=str(exc), **base)

        chromosome_counts = summary.chromosome_counts
        called_snps = sum(
            1
            for call in calls
            if call.genotype.strip().upper() not in MISSING_GENOTYPES
        )
        return DNAPassportRawSummary(
            status="ok",
            provider_hint=summary.vendor_hint,
            total_records=summary.total_rows,
            called_snps=called_snps,
            autosomal_count=summary.autosomal_rows,
            x_count=_chromosome_count(chromosome_counts, "X", "23"),
            y_count=_chromosome_count(chromosome_counts, "Y", "24"),
            mtdna_count=_chromosome_count(chromosome_counts, "M", "MT", "25", "26"),
            call_rate=summary.call_rate,
            skipped_invalid_count=summary.skipped_rows,
            **base,
        )

    def _get_g25_input(
        self,
        user_id: int,
        sample: SampleAsset | None,
        raw_path: Path | None,
        *,
        coordinate_id: str | None,
        coordinate: CoordinateAsset | None,
        warnings: list[str],
    ) -> "_G25Input | None":
        if coordinate is not None:
            return _g25_input_from_coordinate(coordinate) if _is_g25_coordinate(coordinate) else None
        if coordinate_id:
            try:
                candidate = self.my_data_store.get_coordinate(user_id, coordinate_id)
            except Exception as exc:
                warnings.append(f"G25 lookup failed: {exc}")
                candidate = None
            if candidate is not None and _is_g25_coordinate(candidate):
                if sample is not None and coordinate_id not in set(sample.coordinate_ids):
                    warnings.append("G25 coordinate is not attached to the selected sample")
                else:
                    return _g25_input_from_coordinate(candidate)

        attached = self._get_first_attached_g25(user_id, sample, warnings)
        if attached is not None:
            return _g25_input_from_coordinate(attached)
        if raw_path is None:
            return None
        return self._calculate_g25_from_raw(raw_path, sample_name=sample.display_name if sample else "", warnings=warnings)

    def _get_first_attached_g25(
        self,
        user_id: int,
        sample: SampleAsset | None,
        warnings: list[str],
    ) -> CoordinateAsset | None:
        if sample is None:
            return None
        try:
            coordinates = self.my_data_store.list_sample_coordinates(user_id, sample.asset_id)
        except AttributeError:
            coordinates = []
            for coordinate_id in sample.coordinate_ids:
                try:
                    coordinate = self.my_data_store.get_coordinate(user_id, coordinate_id)
                except Exception as exc:
                    warnings.append(f"G25 lookup failed: {exc}")
                    continue
                if coordinate is not None:
                    coordinates.append(coordinate)
        except Exception as exc:
            warnings.append(f"G25 lookup failed: {exc}")
            return None
        for coordinate in coordinates:
            if _is_g25_coordinate(coordinate):
                return coordinate
        return None

    def _calculate_g25_from_raw(self, raw_path: Path, *, sample_name: str, warnings: list[str]) -> "_G25Input":
        if self.g25_service is None:
            return _G25Input(status="unavailable", source="calculated_from_raw")
        try:
            result = self.g25_service.extract_coordinates_from_file(
                raw_path,
                sample_name or raw_path.stem,
                "g25",
                cleanup_run=True,
            )
        except G25CommandError as exc:
            warnings.append(f"G25 raw calculation failed: {exc}")
            return _G25Input(status="error", source="calculated_from_raw", error=str(exc))
        except Exception as exc:
            warnings.append(f"G25 raw calculation failed: {exc}")
            return _G25Input(status="error", source="calculated_from_raw", error="Не удалось получить координаты G25 из этого DNA-файла.")
        return _G25Input(
            status="ok",
            source="calculated_from_raw",
            display_name=str(getattr(result, "target_name", "") or sample_name or raw_path.stem),
            target_name=str(getattr(result, "target_name", "") or sample_name or raw_path.stem),
            g25_line=str(getattr(result, "simulated_g25_line", "") or ""),
        )

    @staticmethod
    def _build_g25_summary(coordinate: "_G25Input | None") -> DNAPassportG25Summary:
        if coordinate is None:
            return DNAPassportG25Summary(status="unavailable")
        if coordinate.status == "error":
            return DNAPassportG25Summary(status="error", source=coordinate.source, error=coordinate.error)
        if not str(coordinate.g25_line or "").strip():
            return DNAPassportG25Summary(status="unavailable", source=coordinate.source)
        try:
            summary = summarize_g25_coordinate(coordinate.g25_line)
        except Exception as exc:
            return DNAPassportG25Summary(
                status="error",
                source=coordinate.source,
                coordinate_id=coordinate.coordinate_id,
                display_name=coordinate.display_name,
                target_name=coordinate.target_name,
                error=str(exc),
            )
        return DNAPassportG25Summary(
            status="ok",
            source=coordinate.source,
            coordinate_id=coordinate.coordinate_id,
            display_name=coordinate.display_name,
            target_name=coordinate.target_name,
            region=summary.region,
            top_modern=tuple(
                DNAPassportG25Population(name=item.name, distance=item.distance)
                for item in summary.top_modern
            ),
            first_distance=summary.first_distance,
            first_second_gap=summary.first_second_gap,
        )

    def _build_traits_summary(self, raw_path: Path | None, *, sample_name: str = "") -> DNAPassportTraitsSummary:
        if raw_path is None:
            return DNAPassportTraitsSummary(status="unavailable", requested_count=len(self.trait_ids), error="raw file is unavailable")
        try:
            payload = self.traits_runtime.run_batch(
                raw_path=raw_path,
                sample_id=sample_name or str(raw_path.name),
                explicit_trait_ids=self.trait_ids,
                input_format="auto",
            )
        except Exception as exc:
            return DNAPassportTraitsSummary(status="error", requested_count=len(self.trait_ids), error=str(exc))

        traits = tuple(_trait_item_from_payload(item) for item in _list_of_dicts(payload.get("traits")))
        failures = tuple(_trait_failure_from_payload(item) for item in _list_of_dicts(payload.get("failures")))
        run_summary = payload.get("run_summary") if isinstance(payload.get("run_summary"), dict) else {}
        failed_count = int(run_summary.get("failed_trait_count") or len(failures))
        completed_count = int(run_summary.get("completed_trait_count") or len(traits))
        status = "partial" if failures and traits else "ok"
        if failures and not traits:
            status = "error"
        return DNAPassportTraitsSummary(
            status=status,
            requested_count=int(run_summary.get("requested_trait_count") or len(self.trait_ids)),
            completed_count=completed_count,
            failed_count=failed_count,
            traits=traits,
            failures=failures,
        )

    def _build_interesting_snps_summary(self, raw_path: Path | None, *, sample_id: str, sample_name: str = "") -> DNAPassportInterestingSnpsSummary:
        if raw_path is None:
            return DNAPassportInterestingSnpsSummary(status="unavailable", error="raw file is unavailable")
        try:
            panel = self.interesting_snp_panel if self.interesting_snp_panel is not None else load_interesting_snps()
        except Exception as exc:
            return DNAPassportInterestingSnpsSummary(status="error", error=str(exc))
        if not panel:
            return DNAPassportInterestingSnpsSummary(status="unavailable", error="interesting SNP panel is empty")
        try:
            analysis = analyze_interesting_snps(
                raw_path,
                tuple(panel),
                sample_id=sample_id,
                sample_name=sample_name or str(raw_path.name),
            )
        except Exception as exc:
            return DNAPassportInterestingSnpsSummary(status="error", total=len(panel), error=str(exc))

        items = tuple(
            DNAPassportInterestingSnpItem(
                rsid=item.rsid,
                title=item.title,
                category=item.category,
                gene=item.gene,
                genotype=item.genotype,
                interpretation=item.interpretation,
            )
            for item in analysis.results
            if item.status == "ok"
        )
        status = "ok" if items else "no_matches"
        return DNAPassportInterestingSnpsSummary(
            status=status,
            total=analysis.total,
            found=analysis.found,
            missing=analysis.missing,
            unsupported=analysis.unsupported,
            items=items,
        )

    @staticmethod
    def _build_lineage_readiness(raw_summary: DNAPassportRawSummary | None) -> DNAPassportLineageReadiness:
        if raw_summary is None or raw_summary.status != "ok":
            return DNAPassportLineageReadiness(status="unavailable", error="raw summary is unavailable")
        return DNAPassportLineageReadiness(
            status="ok",
            y_markers_detected=raw_summary.y_count > 0,
            y_count=raw_summary.y_count,
            mtdna_markers_detected=raw_summary.mtdna_count > 0,
            mtdna_count=raw_summary.mtdna_count,
        )


def _chromosome_count(counts: dict[str, int], *aliases: str) -> int:
    return sum(int(counts.get(alias, 0) or 0) for alias in aliases)


def _is_g25_coordinate(coordinate: CoordinateAsset) -> bool:
    return str(coordinate.coordinate_type or "").strip().lower() == "g25" and bool(str(coordinate.g25_line or "").strip())


@dataclass(frozen=True)
class _G25Input:
    status: str
    source: str
    coordinate_id: str = ""
    display_name: str = ""
    target_name: str = ""
    g25_line: str = ""
    error: str = ""


def _g25_input_from_coordinate(coordinate: CoordinateAsset) -> _G25Input:
    return _G25Input(
        status="ok",
        source="attached",
        coordinate_id=coordinate.asset_id,
        display_name=coordinate.display_name,
        target_name=coordinate.target_name,
        g25_line=coordinate.g25_line,
    )


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _trait_item_from_payload(payload: dict[str, Any]) -> DNAPassportTraitItem:
    metrics = payload.get("key_metrics") if isinstance(payload.get("key_metrics"), dict) else {}
    technical = payload.get("technical_summary") if isinstance(payload.get("technical_summary"), dict) else {}
    overlap = metrics.get("overlap_percent", technical.get("overlap_percent"))
    percentile = payload.get("percentile")
    return DNAPassportTraitItem(
        trait_id=str(payload.get("trait_id") or ""),
        display_name=str(payload.get("display_name") or payload.get("short_name") or ""),
        status=str(payload.get("product_status") or payload.get("status") or "available"),
        percentile=_optional_float(percentile),
        confidence=str(payload.get("confidence") or technical.get("confidence") or ""),
        overlap=_optional_float(overlap),
        qc_flags=tuple(str(item) for item in payload.get("qc_flags") or technical.get("qc_flags") or []),
    )


def _trait_failure_from_payload(payload: dict[str, Any]) -> DNAPassportTraitItem:
    return DNAPassportTraitItem(
        trait_id=str(payload.get("trait_id") or ""),
        display_name=str(payload.get("display_name") or ""),
        status=str(payload.get("code") or "unavailable"),
        error=str(payload.get("message") or ""),
    )


def _optional_float(value: Any) -> float | None:
    if value is None or value == "n/a":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
