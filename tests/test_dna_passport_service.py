from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.features.coordinate_space.g25_summary import summarize_g25_coordinate
from app.features.coordinate_space import menu as coordinate_space_menu
from app.features.my_data.storage import CoordinateAsset, RawFileAsset, SampleAsset
from app.features.reports.dna_passport.service import DNA_PASSPORT_TRAIT_IDS, DNAPassportService
from g25_core.command_service import G25CommandError, G25CoordinatesResult


RAW_CONTENT = """# 23andMe demo raw
rsid,chromosome,position,genotype
rs1,1,100,AA
rs2,2,200,AG
rs3,X,300,CC
rs4,Y,400,TT
rs5,MT,500,GG
rs6,1,600,--
bad,row
"""


class _FakeTraitsRuntime:
    def __init__(self, payload: dict[str, object] | None = None, exc: Exception | None = None) -> None:
        self.payload = payload if payload is not None else _traits_payload()
        self.exc = exc
        self.calls: list[dict[str, object]] = []

    def run_batch(self, **kwargs):
        self.calls.append(dict(kwargs))
        if self.exc is not None:
            raise self.exc
        return self.payload


class _FakeMyDataStore:
    def __init__(
        self,
        *,
        root: Path,
        sample: SampleAsset | None = None,
        raw_file: RawFileAsset | None = None,
        coordinate: CoordinateAsset | None = None,
    ) -> None:
        self.root = root
        self.sample = sample
        self.raw_file = raw_file
        self.coordinate = coordinate
        self.calls: list[str] = []
        self.writes: list[str] = []

    def get_sample(self, user_id: int, sample_id: str):
        self.calls.append("get_sample")
        if self.sample is not None and self.sample.asset_id == sample_id:
            return self.sample
        return None

    def get_sample_raw_file(self, user_id: int, sample_id: str):
        self.calls.append("get_sample_raw_file")
        return self.raw_file

    def resolve_raw_file_path(self, raw_file: RawFileAsset) -> Path:
        self.calls.append("resolve_raw_file_path")
        return self.root / raw_file.stored_path

    def get_coordinate(self, user_id: int, coordinate_id: str):
        self.calls.append("get_coordinate")
        if self.coordinate is not None and self.coordinate.asset_id == coordinate_id:
            return self.coordinate
        return None

    def list_sample_coordinates(self, user_id: int, sample_id: str):
        self.calls.append("list_sample_coordinates")
        if self.sample is None or self.sample.asset_id != sample_id or self.coordinate is None:
            return []
        if self.coordinate.asset_id in set(self.sample.coordinate_ids):
            return [self.coordinate]
        return []

    def save_coordinate(self, *args, **kwargs):
        self.writes.append("save_coordinate")
        raise AssertionError("DNA passport must not save CoordinateAsset")

    def attach_coordinate_to_sample(self, *args, **kwargs):
        self.writes.append("attach_coordinate_to_sample")
        raise AssertionError("DNA passport must not attach CoordinateAsset")

    def __getattr__(self, name: str):
        if name.startswith("save") or name.startswith("delete") or "report" in name.lower() or "haplogroup" in name.lower():
            raise AssertionError(f"DNA passport must not use saved DNA Lab storage method: {name}")
        raise AttributeError(name)


class _FakeG25Service:
    def __init__(self, *, line: str | None = None, exc: Exception | None = None) -> None:
        self.line = line or _first_modern_g25_line()
        self.exc = exc
        self.calls: list[tuple[Path, str, str]] = []

    def extract_coordinates_from_file(self, input_path: Path, sample_name: str, coordinate_type: str = "g25", **kwargs):
        self.calls.append((Path(input_path), sample_name, coordinate_type, dict(kwargs)))
        if self.exc is not None:
            raise self.exc
        return G25CoordinatesResult(
            target_name=sample_name or "Demo",
            simulated_g25_line=self.line,
            input_mode="raw-file",
        )


class DNAPassportServiceTests(unittest.TestCase):
    def test_builds_raw_and_g25_passport_without_saved_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw_file = _write_raw(root)
            g25_line = _first_modern_g25_line()
            sample = SampleAsset("sample-1", "Demo", raw_file.asset_id, ["coord-1"], "2026-06-14T00:00:00")
            coordinate = CoordinateAsset("coord-1", "Demo G25", "Demo", "g25", g25_line, "manual", "2026-06-14T00:00:00")
            store = _FakeMyDataStore(root=root, sample=sample, raw_file=raw_file, coordinate=coordinate)
            traits = _FakeTraitsRuntime()
            g25_service = _FakeG25Service()

            data = DNAPassportService(my_data_store=store, traits_runtime=traits, g25_service=g25_service).build_for_sample(
                user_id=1,
                sample_id="sample-1",
                g25_coordinate_id="coord-1",
            )

        self.assertEqual(data.sample.status, "ok")
        self.assertEqual(data.raw.status, "ok")
        self.assertEqual(data.raw.provider_hint, "23andMe")
        self.assertEqual(data.raw.total_records, 7)
        self.assertEqual(data.raw.called_snps, 5)
        self.assertEqual(data.raw.autosomal_count, 3)
        self.assertEqual(data.raw.x_count, 1)
        self.assertEqual(data.raw.y_count, 1)
        self.assertEqual(data.raw.mtdna_count, 1)
        self.assertEqual(data.raw.skipped_invalid_count, 1)
        self.assertEqual(data.g25.status, "ok")
        self.assertEqual(data.g25.source, "attached")
        self.assertEqual(len(data.g25.top_modern), 3)
        self.assertIsNotNone(data.g25.first_distance)
        self.assertIsNotNone(data.g25.first_second_gap)
        self.assertEqual(data.traits.status, "ok")
        self.assertEqual(data.lineage.status, "ok")
        self.assertTrue(data.lineage.y_markers_detected)
        self.assertTrue(data.lineage.mtdna_markers_detected)
        self.assertNotIn("list_reports", store.calls)
        self.assertEqual(g25_service.calls, [])
        self.assertEqual(traits.calls[0]["explicit_trait_ids"], DNA_PASSPORT_TRAIT_IDS)

    def test_builds_raw_without_attached_g25_calculates_temporary_g25(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw_file = _write_raw(root)
            sample = SampleAsset("sample-1", "Demo", raw_file.asset_id, [], "2026-06-14T00:00:00")
            store = _FakeMyDataStore(root=root, sample=sample, raw_file=raw_file)
            g25_service = _FakeG25Service()

            data = DNAPassportService(my_data_store=store, traits_runtime=_FakeTraitsRuntime(), g25_service=g25_service).build_for_sample(
                user_id=1,
                sample_id="sample-1",
            )

        self.assertEqual(data.raw.status, "ok")
        self.assertEqual(data.g25.status, "ok")
        self.assertEqual(data.g25.source, "calculated_from_raw")
        self.assertEqual(len(data.g25.top_modern), 3)
        self.assertEqual(data.traits.status, "ok")
        self.assertEqual(len(g25_service.calls), 1)
        self.assertEqual(g25_service.calls[0][1:3], ("Demo", "g25"))
        self.assertEqual(g25_service.calls[0][3], {"cleanup_run": True})
        self.assertEqual(store.writes, [])

    def test_builds_g25_without_raw(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            g25_line = _first_modern_g25_line()
            sample = SampleAsset("sample-1", "Demo", "", ["coord-1"], "2026-06-14T00:00:00")
            coordinate = CoordinateAsset("coord-1", "Demo G25", "Demo", "g25", g25_line, "manual", "2026-06-14T00:00:00")
            store = _FakeMyDataStore(root=root, sample=sample, coordinate=coordinate)

            data = DNAPassportService(my_data_store=store, traits_runtime=_FakeTraitsRuntime()).build_for_sample(
                user_id=1,
                sample_id="sample-1",
                g25_coordinate_id="coord-1",
            )

        self.assertEqual(data.raw.status, "unavailable")
        self.assertEqual(data.g25.status, "ok")
        self.assertEqual(data.g25.source, "attached")
        self.assertEqual(data.traits.status, "unavailable")
        self.assertEqual(data.lineage.status, "unavailable")

    def test_builds_passport_without_any_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sample = SampleAsset("sample-1", "Demo", "", [], "2026-06-14T00:00:00")
            store = _FakeMyDataStore(root=root, sample=sample)

            data = DNAPassportService(my_data_store=store, traits_runtime=_FakeTraitsRuntime()).build_for_sample(
                user_id=1,
                sample_id="sample-1",
            )

        self.assertEqual(data.sample.status, "ok")
        self.assertEqual(data.raw.status, "unavailable")
        self.assertEqual(data.g25.status, "unavailable")
        self.assertEqual(data.traits.status, "unavailable")
        self.assertEqual(data.lineage.status, "unavailable")

    def test_raw_parser_error_does_not_break_g25(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw_file = _write_raw(root)
            g25_line = _first_modern_g25_line()
            sample = SampleAsset("sample-1", "Demo", raw_file.asset_id, ["coord-1"], "2026-06-14T00:00:00")
            coordinate = CoordinateAsset("coord-1", "Demo G25", "Demo", "g25", g25_line, "manual", "2026-06-14T00:00:00")
            store = _FakeMyDataStore(root=root, sample=sample, raw_file=raw_file, coordinate=coordinate)
            g25_service = _FakeG25Service()

            with patch("app.features.reports.dna_passport.service.parse_raw_dna", side_effect=ValueError("broken raw")):
                data = DNAPassportService(my_data_store=store, traits_runtime=_FakeTraitsRuntime(), g25_service=g25_service).build_for_sample(
                    user_id=1,
                    sample_id="sample-1",
                    g25_coordinate_id="coord-1",
                )

        self.assertEqual(data.raw.status, "error")
        self.assertIn("broken raw", data.raw.error)
        self.assertEqual(data.g25.status, "ok")
        self.assertEqual(data.g25.source, "attached")
        self.assertEqual(g25_service.calls, [])
        self.assertEqual(data.traits.status, "ok")
        self.assertEqual(data.lineage.status, "unavailable")

    def test_unavailable_g25_reference_does_not_break_raw(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw_file = _write_raw(root)
            sample = SampleAsset("sample-1", "Demo", raw_file.asset_id, ["coord-1"], "2026-06-14T00:00:00")
            coordinate = CoordinateAsset("coord-1", "Demo G25", "Demo", "g25", _first_modern_g25_line(), "manual", "2026-06-14T00:00:00")
            store = _FakeMyDataStore(root=root, sample=sample, raw_file=raw_file, coordinate=coordinate)

            with patch("app.features.reports.dna_passport.service.summarize_g25_coordinate", side_effect=FileNotFoundError("missing refs")):
                data = DNAPassportService(my_data_store=store, traits_runtime=_FakeTraitsRuntime()).build_for_sample(
                    user_id=1,
                    sample_id="sample-1",
                    g25_coordinate_id="coord-1",
                )

        self.assertEqual(data.raw.status, "ok")
        self.assertEqual(data.g25.status, "error")
        self.assertIn("missing refs", data.g25.error)

    def test_partially_unavailable_traits_are_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw_file = _write_raw(root)
            sample = SampleAsset("sample-1", "Demo", raw_file.asset_id, [], "2026-06-14T00:00:00")
            store = _FakeMyDataStore(root=root, sample=sample, raw_file=raw_file)
            g25_service = _FakeG25Service()
            runtime = _FakeTraitsRuntime(
                {
                    "run_summary": {
                        "requested_trait_count": 2,
                        "completed_trait_count": 1,
                        "failed_trait_count": 1,
                    },
                    "traits": [_trait_payload("pgs003835_height", "Height", percentile=80.0)],
                    "failures": [
                        {
                            "trait_id": "pgs001123_coffee",
                            "display_name": "Coffee consumption",
                            "code": "low_overlap",
                            "message": "not enough data",
                        }
                    ],
                }
            )

            data = DNAPassportService(my_data_store=store, traits_runtime=runtime, g25_service=g25_service).build_for_sample(
                user_id=1,
                sample_id="sample-1",
            )

        self.assertEqual(data.traits.status, "partial")
        self.assertEqual(data.traits.completed_count, 1)
        self.assertEqual(data.traits.failed_count, 1)
        self.assertEqual(data.traits.failures[0].status, "low_overlap")

    def test_no_db_writes_or_saved_dna_lab_result_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw_file = _write_raw(root)
            sample = SampleAsset("sample-1", "Demo", raw_file.asset_id, [], "2026-06-14T00:00:00")
            store = _FakeMyDataStore(root=root, sample=sample, raw_file=raw_file)
            g25_service = _FakeG25Service()

            data = DNAPassportService(my_data_store=store, traits_runtime=_FakeTraitsRuntime(), g25_service=g25_service).build_for_sample(
                user_id=1,
                sample_id="sample-1",
            )

        self.assertEqual(data.raw.status, "ok")
        self.assertEqual(
            store.calls,
            ["get_sample", "get_sample_raw_file", "resolve_raw_file_path", "list_sample_coordinates"],
        )
        self.assertEqual(store.writes, [])
        self.assertEqual(len(g25_service.calls), 1)

    def test_does_not_run_y_or_mtdna_prediction(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw_file = _write_raw(root)
            sample = SampleAsset("sample-1", "Demo", raw_file.asset_id, [], "2026-06-14T00:00:00")
            store = _FakeMyDataStore(root=root, sample=sample, raw_file=raw_file)
            g25_service = _FakeG25Service()

            with patch(
                "app.features.haplogroups.domain.predict_y_haplogroup_from_raw",
                side_effect=AssertionError("Y predictor must not run"),
            ):
                data = DNAPassportService(my_data_store=store, traits_runtime=_FakeTraitsRuntime(), g25_service=g25_service).build_for_sample(
                    user_id=1,
                    sample_id="sample-1",
                )

        self.assertEqual(data.lineage.status, "ok")
        self.assertEqual(data.lineage.y_count, 1)
        self.assertEqual(data.lineage.mtdna_count, 1)

    def test_raw_g25_calculation_error_does_not_break_other_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw_file = _write_raw(root)
            sample = SampleAsset("sample-1", "Demo", raw_file.asset_id, [], "2026-06-14T00:00:00")
            store = _FakeMyDataStore(root=root, sample=sample, raw_file=raw_file)
            g25_service = _FakeG25Service(exc=G25CommandError("boom"))

            data = DNAPassportService(my_data_store=store, traits_runtime=_FakeTraitsRuntime(), g25_service=g25_service).build_for_sample(
                user_id=1,
                sample_id="sample-1",
            )

        self.assertEqual(data.raw.status, "ok")
        self.assertEqual(data.g25.status, "error")
        self.assertEqual(data.g25.source, "calculated_from_raw")
        self.assertIn("boom", data.g25.error)
        self.assertEqual(data.traits.status, "ok")
        self.assertEqual(data.lineage.status, "ok")
        self.assertEqual(store.writes, [])

    def test_temporary_g25_uses_same_existing_extraction_entrypoint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw_file = _write_raw(root)
            sample = SampleAsset("sample-1", "Demo", raw_file.asset_id, [], "2026-06-14T00:00:00")
            store = _FakeMyDataStore(root=root, sample=sample, raw_file=raw_file)
            g25_service = _FakeG25Service(line=_first_modern_g25_line())

            data = DNAPassportService(my_data_store=store, traits_runtime=_FakeTraitsRuntime(), g25_service=g25_service).build_for_sample(
                user_id=1,
                sample_id="sample-1",
            )

        self.assertEqual(data.g25.status, "ok")
        self.assertEqual(data.g25.source, "calculated_from_raw")
        self.assertEqual(g25_service.calls, [(root / "raw.csv", "Demo", "g25", {"cleanup_run": True})])
        self.assertNotIn("save_coordinate", store.writes)
        self.assertNotIn("attach_coordinate_to_sample", store.writes)

    def test_g25_summary_matches_coordinate_space_ranking(self) -> None:
        g25_line = _first_modern_g25_line()

        summary = summarize_g25_coordinate(g25_line)
        menu_populations = coordinate_space_menu._load_modern_population_averages()
        menu_ranked = coordinate_space_menu._rank_profile_distances(g25_line, menu_populations, limit=3)

        self.assertEqual(summary.region, coordinate_space_menu._classify_global_region(g25_line))
        self.assertEqual(
            [(item.name, round(item.distance, 8)) for item in summary.top_modern],
            [(name, round(distance, 8)) for name, distance in menu_ranked],
        )


def _write_raw(root: Path) -> RawFileAsset:
    raw_path = root / "raw.csv"
    raw_path.write_text(RAW_CONTENT, encoding="utf-8")
    return RawFileAsset("raw-1", "Demo raw", "raw.csv", "raw.csv", "2026-06-14T00:00:00", raw_path.stat().st_size)


def _first_modern_g25_line() -> str:
    path = Path("app/features/coordinate_space/data/Global25_PCA_modern_pop_averages_scaled.txt")
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if line.strip() and not line.startswith(",PC1"):
            return line
    raise AssertionError("No modern G25 line found")


def _trait_payload(trait_id: str = "pgs001123_coffee", display_name: str = "Coffee consumption", *, percentile: float = 42.0) -> dict[str, object]:
    return {
        "trait_id": trait_id,
        "display_name": display_name,
        "product_status": "limited",
        "percentile": percentile,
        "confidence": "low",
        "qc_flags": ["low_overlap"],
        "key_metrics": {"overlap_percent": 12.5},
    }


def _traits_payload() -> dict[str, object]:
    return {
        "run_summary": {
            "requested_trait_count": len(DNA_PASSPORT_TRAIT_IDS),
            "completed_trait_count": 1,
            "failed_trait_count": 0,
        },
        "traits": [_trait_payload()],
        "failures": [],
    }


if __name__ == "__main__":
    unittest.main()
