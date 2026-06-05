from __future__ import annotations

import unittest
from tempfile import TemporaryDirectory
from pathlib import Path

from app.features.admixture.domain import build_k36_profile, compare_admixture_payloads, profile_to_payload
from app.features.admixture.model_catalog import RawAdmixtureModel, list_raw_admixture_models, list_raw_admixture_projects
from app.features.admixture.menu import (
    ADMIXTURE_CALLBACK_PREFIX,
    _next_label,
    _raw_model_coordinate_id,
    _raw_model_button_label,
    _sample_admixture_reports_for_origin,
)
from app.features.admixture.oracle import load_oracle_references, similar_populations, three_way_oracle_mixes, two_way_oracle_mixes
from app.features.admixture.storage import AdmixtureReportRecord, AdmixtureReportStore, AdmixtureReportSummary
from app.features.admixture.ui import profile_preview_text, profile_visual_caption, sample_admixture_reports_text, report_detail_text
from app.features.admixture.visualization import _visible_components, render_compare_png, render_oracle_mix_png, render_oracle_png, render_profile_png
from app.features.my_data.storage import CoordinateAsset, SampleAsset
from g25_core.g25_engine import K36_COMPONENTS


class AdmixtureDomainTests(unittest.TestCase):
    def test_raw_model_button_label_has_no_status_emoji(self) -> None:
        installed = RawAdmixtureModel("K36", 36, "alleles.txt", "freq.txt", True)
        missing = RawAdmixtureModel("K13", 13, "alleles.txt", "freq.txt", False)

        self.assertEqual(_raw_model_button_label(installed), "K36")
        self.assertEqual(_raw_model_button_label(missing), "K13 (not installed)")
        self.assertNotIn("✅", _raw_model_button_label(installed))
        self.assertNotIn("⚠️", _raw_model_button_label(missing))

    def test_build_k36_profile_summarizes_components_and_macro_groups(self) -> None:
        values = [0.0] * len(K36_COMPONENTS)
        values[K36_COMPONENTS.index("North_Atlantic")] = 30.0
        values[K36_COMPONENTS.index("North_Sea")] = 20.0
        values[K36_COMPONENTS.index("West_Caucasian")] = 12.5
        line = "Sample_A," + ",".join(str(value) for value in values)

        profile = build_k36_profile(line)

        self.assertEqual(profile.sample_name, "Sample_A")
        self.assertEqual(profile.model, "K36")
        self.assertEqual(profile.top_components[0].name, "North_Atlantic")
        self.assertEqual(profile.top_components[0].value, 30.0)
        self.assertEqual(profile.macro_groups[0].name, "North / Central / East Europe")
        self.assertEqual(profile.macro_groups[0].value, 50.0)

    def test_profile_payload_is_json_ready(self) -> None:
        line = "Sample_B," + ",".join("1" for _ in K36_COMPONENTS)

        payload = profile_to_payload(build_k36_profile(line))

        self.assertEqual(payload["model"], "K36")
        self.assertEqual(len(payload["components"]), 36)
        self.assertEqual(len(payload["top_components"]), 8)

    def test_profile_caption_uses_clean_raw_calculator_format(self) -> None:
        sample = SampleAsset("sample", "Асият", "raw", [], "2026-05-13T12:00:00")
        payload = {
            "model": "K36",
            "total": 100.0,
            "top_components": [{"name": "North_Caucasian", "value": 42.08}],
        }

        caption = profile_visual_caption(sample, payload)

        self.assertIn("🧮 K36 profile", caption)
        self.assertIn("Top: North Caucasian — 42.08%", caption)
        self.assertIn("Total: 100.00", caption)
        self.assertNotIn(" · Total:", caption)

    def test_admixture_next_label_is_show_more(self) -> None:
        self.assertEqual(_next_label("ru"), "Показать ещё")

    def test_admixture_callback_data_stays_under_telegram_limit(self) -> None:
        asset_id = "20260430185412345678-12345678"

        callbacks = [
            f"{ADMIXTURE_CALLBACK_PREFIX}:k:{asset_id}",
            f"{ADMIXTURE_CALLBACK_PREFIX}:save:{asset_id}",
            f"{ADMIXTURE_CALLBACK_PREFIX}:svx:12345678",
            f"{ADMIXTURE_CALLBACK_PREFIX}:s:{asset_id}",
            f"{ADMIXTURE_CALLBACK_PREFIX}:o:{asset_id}",
            f"{ADMIXTURE_CALLBACK_PREFIX}:mo:{asset_id}",
            f"{ADMIXTURE_CALLBACK_PREFIX}:mdl:HarappaWorld",
            f"{ADMIXTURE_CALLBACK_PREFIX}:ms:AncientNearEast13:0",
            f"{ADMIXTURE_CALLBACK_PREFIX}:mr:AncientNearEast13:{asset_id}",
            f"{ADMIXTURE_CALLBACK_PREFIX}:savem:12345678",
            f"{ADMIXTURE_CALLBACK_PREFIX}:grp:eurogenes",
            f"{ADMIXTURE_CALLBACK_PREFIX}:cgrp:eurogenes",
            f"{ADMIXTURE_CALLBACK_PREFIX}:cm:AncientNearEast13",
            f"{ADMIXTURE_CALLBACK_PREFIX}:cl:AncientNearEast13:{asset_id}",
            f"{ADMIXTURE_CALLBACK_PREFIX}:cr:12345678:{asset_id}",
            f"{ADMIXTURE_CALLBACK_PREFIX}:opg:eurogenes",
            f"{ADMIXTURE_CALLBACK_PREFIX}:om:AncientNearEast13",
            f"{ADMIXTURE_CALLBACK_PREFIX}:or:{asset_id}",
            f"{ADMIXTURE_CALLBACK_PREFIX}:omix",
            f"{ADMIXTURE_CALLBACK_PREFIX}:omg:eurogenes",
            f"{ADMIXTURE_CALLBACK_PREFIX}:omd:AncientNearEast13",
            f"{ADMIXTURE_CALLBACK_PREFIX}:omm:3:AncientNearEast13",
            f"{ADMIXTURE_CALLBACK_PREFIX}:omr:3:{asset_id}",
            f"{ADMIXTURE_CALLBACK_PREFIX}:paint",
        ]

        for callback in callbacks:
            self.assertLessEqual(len(callback.encode("utf-8")), 64, callback)

    def test_report_detail_shows_all_k36_components(self) -> None:
        line = "Sample_C," + ",".join(str(index) for index, _ in enumerate(K36_COMPONENTS, start=1))
        payload = profile_to_payload(build_k36_profile(line))
        record = AdmixtureReportRecord(
            summary=AdmixtureReportSummary(
                report_id="report",
                sample_id="sample",
                sample_name="Sample C",
                coordinate_id="coord",
                coordinate_name="Sample C K36",
                model="K36",
                title="K36 profile",
                strongest_component="West_Med",
                strongest_component_value=36.0,
                macro_summary="North / Central / East Europe",
                created_at="2026-04-30T21:00:00",
            ),
            technical_payload={},
            product_payload=payload,
        )

        text = report_detail_text(record)

        for component in K36_COMPONENTS:
            self.assertIn(f"{component}:", text)

    def test_profile_preview_is_explicitly_unsaved(self) -> None:
        line = "Sample_D," + ",".join("1" for _ in K36_COMPONENTS)
        payload = profile_to_payload(build_k36_profile(line))
        sample = SampleAsset(
            asset_id="sample",
            display_name="Sample D",
            raw_file_id="raw",
            coordinate_ids=["coord"],
            created_at="2026-04-30T21:00:00",
        )
        coordinate = CoordinateAsset(
            asset_id="coord",
            display_name="Sample D K36",
            target_name="Sample_D",
            coordinate_type="k36",
            g25_line=line,
            input_mode="manual",
            created_at="2026-04-30T21:00:00",
        )

        text = profile_preview_text(sample, coordinate, payload)

        self.assertIn("Status: not saved", text)
        self.assertNotIn("Saved:", text)

    def test_report_store_replaces_duplicate_coordinate_reports(self) -> None:
        line = "Sample_E," + ",".join("1" for _ in K36_COMPONENTS)
        payload = profile_to_payload(build_k36_profile(line))

        with TemporaryDirectory() as temp_dir:
            store = AdmixtureReportStore(Path(temp_dir))
            first = store.save_report(
                1,
                sample_id="sample",
                sample_name="Sample E",
                coordinate_id="coord",
                coordinate_name="Sample E K36",
                technical_payload={},
                product_payload=payload,
            )
            second = store.save_report(
                1,
                sample_id="sample",
                sample_name="Sample E",
                coordinate_id="coord",
                coordinate_name="Sample E K36",
                technical_payload={},
                product_payload=payload,
            )

            reports = store.list_reports(1, "sample")

        self.assertEqual(first.summary.report_id, second.summary.report_id)
        self.assertEqual(len(reports), 1)

    def test_k36_calculator_origin_filters_sample_reports_to_k36(self) -> None:
        k36 = AdmixtureReportSummary(
            report_id="k36",
            sample_id="sample",
            sample_name="Sample F",
            coordinate_id="coord-k36",
            coordinate_name="Sample F K36",
            model="K36",
            title="K36 profile",
            strongest_component="North_Caucasian",
            strongest_component_value=42.1,
            macro_summary="Caucasus / West Asia",
            created_at="2026-04-30T21:00:00",
        )
        k47 = AdmixtureReportSummary(
            report_id="k47",
            sample_id="sample",
            sample_name="Sample F",
            coordinate_id="coord-k47",
            coordinate_name="Sample F K47",
            model="K47",
            title="K47 profile",
            strongest_component="Caucasus",
            strongest_component_value=38.4,
            macro_summary="Caucasus / West Asia",
            created_at="2026-04-30T21:01:00",
        )

        self.assertEqual(_sample_admixture_reports_for_origin([k36, k47], origin="admixture"), [k36])
        self.assertEqual(_sample_admixture_reports_for_origin([k36, k47], origin="my_data"), [k36, k47])

    def test_raw_model_coordinate_id_is_stable_per_raw_file_and_model(self) -> None:
        self.assertEqual(
            _raw_model_coordinate_id("raw-file", "K13"),
            "raw:raw-file:K13",
        )

    def test_sample_reports_text_does_not_offer_new_run_when_report_exists(self) -> None:
        sample = SampleAsset(
            asset_id="sample",
            display_name="Sample F",
            raw_file_id="raw",
            coordinate_ids=["coord"],
            created_at="2026-04-30T21:00:00",
        )
        coordinate = CoordinateAsset(
            asset_id="coord",
            display_name="Sample F K36",
            target_name="Sample_F",
            coordinate_type="k36",
            g25_line="",
            input_mode="manual",
            created_at="2026-04-30T21:00:00",
        )
        report = AdmixtureReportSummary(
            report_id="report",
            sample_id="sample",
            sample_name="Sample F",
            coordinate_id="coord",
            coordinate_name="Sample F K36",
            model="K36",
            title="K36 profile",
            strongest_component="North_Caucasian",
            strongest_component_value=42.1,
            macro_summary="Caucasus / West Asia",
            created_at="2026-04-30T21:00:00",
        )

        text = sample_admixture_reports_text(sample, [report], [coordinate])

        self.assertIn("Выберите сохранённый профиль.", text)
        self.assertNotIn("запустите новый", text)

    def test_raw_model_catalog_detects_installed_reference_files(self) -> None:
        with TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            (data_dir / "K13.alleles").write_text("", encoding="utf-8")
            (data_dir / "K13.13.F").write_text("", encoding="utf-8")
            (data_dir / "K36.alleles").write_text("", encoding="utf-8")
            (data_dir / "K36.36.F").write_text("", encoding="utf-8")

            models = list_raw_admixture_models(data_dir)

        by_name = {model.name: model for model in models}
        self.assertTrue(by_name["K13"].installed)
        self.assertTrue(by_name["K36"].installed)
        self.assertFalse(by_name["K47"].installed)
        self.assertEqual(by_name["K47"].frequency_file, "K47.47.F")

    def test_raw_model_catalog_groups_models_by_project(self) -> None:
        with TemporaryDirectory() as temp_dir:
            projects = list_raw_admixture_projects(Path(temp_dir))

        by_code = {project.code: project for project in projects}
        self.assertIn("K13", [model.name for model in by_code["eurogenes"].models])
        self.assertIn("K36", [model.name for model in by_code["eurogenes"].models])
        self.assertIn("K12b", [model.name for model in by_code["dodecad"].models])
        self.assertIn("K47", [model.name for model in by_code["gedrosia"].models])
        self.assertEqual(sum(len(project.models) for project in projects), 28)

    def test_oracle_references_load_and_rank_similar_population(self) -> None:
        reference_set = load_oracle_references(
            Path("g25_core") / "vendor" / "admix" / "oracle_references",
            "K13",
        )
        self.assertIsNotNone(reference_set)
        assert reference_set is not None
        armenian = next(pop for pop in reference_set.populations if pop.name == "Armenian")
        payload = {
            "model": "K13",
            "components": [
                {"name": "West Asian", "value": 38.88},
                {"name": "East Med", "value": 34.79},
                {"name": "West Med", "value": 13.02},
                {"name": "South Asian", "value": 3.41},
                {"name": "Red Sea", "value": 5.23},
                {"name": "Baltic", "value": 0.85},
                {"name": "North Atlantic", "value": 2.79},
                {"name": "Siberian", "value": 0.03},
                {"name": "Amerindian", "value": 0.05},
                {"name": "East Asian", "value": 0.43},
                {"name": "Oceanian", "value": 0.44},
                {"name": "Northeast African", "value": 0.04},
                {"name": "Sub-Saharan", "value": 0.05},
            ],
        }

        matches = similar_populations(payload, reference_set, top=1)

        self.assertEqual(armenian.name, matches[0].population)
        self.assertEqual(matches[0].distance, 0.0)

    def test_two_way_oracle_mix_finds_reference_blend(self) -> None:
        reference_set = load_oracle_references(
            Path("g25_core") / "vendor" / "admix" / "oracle_references",
            "K13",
        )
        self.assertIsNotNone(reference_set)
        assert reference_set is not None
        chechen = next(pop for pop in reference_set.populations if pop.name == "Chechen")
        armenian = next(pop for pop in reference_set.populations if pop.name == "Armenian")
        values = {
            key: chechen.values.get(key, 0.0) * 0.75 + armenian.values.get(key, 0.0) * 0.25
            for key in set(chechen.values) | set(armenian.values)
        }
        payload = {
            "model": "K13",
            "components": [
                {"name": name, "value": value}
                for name, value in values.items()
            ],
        }

        matches = two_way_oracle_mixes(payload, reference_set, candidate_limit=80, step=5, top=5)

        self.assertTrue(
            any(
                {match.population_a, match.population_b} == {"Chechen", "Armenian"}
                and match.distance == 0.0
                for match in matches
            )
        )

    def test_three_way_oracle_mix_finds_reference_blend(self) -> None:
        reference_set = load_oracle_references(
            Path("g25_core") / "vendor" / "admix" / "oracle_references",
            "K13",
        )
        self.assertIsNotNone(reference_set)
        assert reference_set is not None
        chechen = next(pop for pop in reference_set.populations if pop.name == "Chechen")
        armenian = next(pop for pop in reference_set.populations if pop.name == "Armenian")
        kumyk = next(pop for pop in reference_set.populations if pop.name == "Kumyk")
        values = {
            key: (
                chechen.values.get(key, 0.0) * 0.6
                + armenian.values.get(key, 0.0) * 0.3
                + kumyk.values.get(key, 0.0) * 0.1
            )
            for key in set(chechen.values) | set(armenian.values) | set(kumyk.values)
        }
        payload = {
            "model": "K13",
            "components": [
                {"name": name, "value": value}
                for name, value in values.items()
            ],
        }

        matches = three_way_oracle_mixes(payload, reference_set, candidate_limit=15, step=10, top=10)

        self.assertTrue(
            any(
                set(match.populations) == {"Chechen", "Armenian", "Kumyk"}
                and match.distance == 0.0
                for match in matches
            )
        )

    def test_compare_admixture_payloads_reports_largest_differences(self) -> None:
        left = {
            "model": "K36",
            "components": [
                {"name": "North_Atlantic", "value": 30.0},
                {"name": "North_Caucasian", "value": 10.0},
            ],
        }
        right = {
            "model": "K36",
            "components": [
                {"name": "North_Atlantic", "value": 20.0},
                {"name": "North_Caucasian", "value": 15.0},
            ],
        }

        comparison = compare_admixture_payloads(left, right)

        self.assertEqual(comparison["model"], "K36")
        self.assertEqual(comparison["component_count"], 2)
        self.assertEqual(comparison["total_absolute_difference"], 15.0)
        self.assertEqual(comparison["differences"][0]["name"], "North_Atlantic")

    def test_admixture_visualizations_render_png_files(self) -> None:
        line = "Sample_G," + ",".join(str((index % 9) + 1) for index, _ in enumerate(K36_COMPONENTS))
        payload = profile_to_payload(build_k36_profile(line))
        comparison = compare_admixture_payloads(
            payload,
            {
                "model": "K36",
                "components": [
                    {"name": item["name"], "value": max(0.0, float(item["value"]) - 1.0)}
                    for item in payload["components"]
                ],
            },
        )
        reference_set = load_oracle_references(
            Path("g25_core") / "vendor" / "admix" / "oracle_references",
            "K13",
        )
        self.assertIsNotNone(reference_set)
        assert reference_set is not None
        oracle_payload = {
            "model": "K13",
            "components": [
                {"name": "West Asian", "value": 38.88},
                {"name": "East Med", "value": 34.79},
                {"name": "West Med", "value": 13.02},
                {"name": "South Asian", "value": 3.41},
                {"name": "Red Sea", "value": 5.23},
                {"name": "Baltic", "value": 0.85},
                {"name": "North Atlantic", "value": 2.79},
                {"name": "Siberian", "value": 0.03},
                {"name": "Amerindian", "value": 0.05},
                {"name": "East Asian", "value": 0.43},
                {"name": "Oceanian", "value": 0.44},
                {"name": "Northeast African", "value": 0.04},
                {"name": "Sub-Saharan", "value": 0.05},
            ],
        }
        matches = similar_populations(oracle_payload, reference_set, top=8)
        mixes = two_way_oracle_mixes(oracle_payload, reference_set, candidate_limit=20, top=4)

        with TemporaryDirectory() as temp_dir:
            paths = {
                "profile": Path(temp_dir) / "profile.png",
                "compare": Path(temp_dir) / "compare.png",
                "oracle": Path(temp_dir) / "oracle.png",
                "mix": Path(temp_dir) / "mix.png",
            }
            render_profile_png(paths["profile"], sample_name="Sample G", coordinate_name="Sample G K36", payload=payload)
            render_compare_png(paths["compare"], left_name="Sample G", right_name="Sample H", comparison=comparison)
            render_oracle_png(paths["oracle"], sample_name="Sample G", model="K13", reference_set=reference_set, matches=matches)
            render_oracle_mix_png(
                paths["mix"],
                sample_name="Sample G",
                model="K13",
                mode_label="2-way",
                reference_set=reference_set,
                single_matches=matches,
                mix_matches=mixes,
            )

            for path in paths.values():
                self.assertTrue(path.exists(), path)
                self.assertGreater(path.stat().st_size, 10_000, path)

    def test_profile_visualization_keeps_all_significant_components(self) -> None:
        payload = {
            "model": "K36",
            "components": [
                {"name": "North_Atlantic", "value": 30.0},
                {"name": "North_Caucasian", "value": 0.1},
                {"name": "Trace", "value": 0.09},
                {"name": "Zero", "value": 0.0},
            ],
        }

        self.assertEqual(
            _visible_components(payload),
            [("North_Atlantic", 30.0), ("North_Caucasian", 0.1)],
        )


if __name__ == "__main__":
    unittest.main()
