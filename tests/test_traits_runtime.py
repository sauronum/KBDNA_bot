from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.features.traits.domain.catalog import TraitCatalog
from app.features.traits.import_artifacts import import_trait_artifacts
from app.features.traits.domain.runtime import TraitsRuntimeService
from app.features.traits.menu import TRAITS_CALLBACK_PREFIX
from app.features.traits.storage import TraitReportStore
from app.features.traits.ui import sample_picker_text, trait_button_label, trait_catalog_text, trait_detail_text, trait_run_sample_picker_text, trait_visual_caption, traits_about_text, traits_root_text
from app.features.traits.visualization import render_trait_result_png


DEMO_RAW = """# Family Tree DNA demo file
# rsid,chromosome,position,genotype
rsid,chromosome,position,genotype
rs547237130,1,72526,AA
rs9283150,1,565508,GG
rs567161598,1,726912,AA
rs3131972,1,752721,GG
rs12184325,1,754105,CC
rs11240777,1,798959,GG
"""


class TraitsRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = TraitCatalog()
        self.runtime = TraitsRuntimeService(self.catalog)

    def test_catalog_loads_registry_and_trait_detail(self) -> None:
        traits = self.catalog.list_traits()
        self.assertGreater(len(traits), 0)

        coffee = self.catalog.get_trait_detail("pgs001123_coffee")
        self.assertEqual(coffee.entry.display_name, "Coffee consumption")
        self.assertEqual(coffee.entry.status, "usable")
        self.assertTrue(coffee.entry.reference_panel is not None)

        sleep_duration = self.catalog.get_trait_detail("pgs001150_sleep_duration")
        self.assertEqual(sleep_duration.entry.display_name, "Sleep-duration tendency")
        self.assertEqual(sleep_duration.entry.status, "usable")
        self.assertTrue(sleep_duration.entry.reference_panel is not None)

    def test_runtime_scores_single_trait_against_demo_raw(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            raw_path = Path(tmpdir) / "demo_ftdna.csv"
            raw_path.write_text(DEMO_RAW, encoding="utf-8")

            result = self.runtime.score_trait(
                trait_id="pgs001123_coffee",
                raw_path=raw_path,
                sample_id="Demo sample",
                input_format="ftdna",
            )

        self.assertEqual(result.trait_id, "pgs001123_coffee")
        self.assertEqual(result.sample_id, "Demo sample")
        self.assertEqual(result.product_payload["display_name"], "Coffee consumption")
        self.assertIn("key_metrics", result.product_payload)
        self.assertIn("qc_summary", result.technical_payload)

    def test_runtime_runs_small_batch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            raw_path = Path(tmpdir) / "demo_ftdna.csv"
            raw_path.write_text(DEMO_RAW, encoding="utf-8")

            payload = self.runtime.run_batch(
                raw_path=raw_path,
                sample_id="Batch demo",
                explicit_trait_ids=["pgs001123_coffee", "pgs000336_chronotype"],
                input_format="ftdna",
            )

        self.assertEqual(payload["run_summary"]["requested_trait_count"], 2)
        self.assertEqual(payload["run_summary"]["completed_trait_count"], 2)
        self.assertEqual(payload["run_summary"]["failed_trait_count"], 0)

    def test_report_store_persists_saved_reports(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = TraitReportStore(Path(tmpdir))
            record = store.save_report(
                1,
                sample_id="sample-1",
                sample_name="Sample One",
                raw_file_id="raw-1",
                technical_payload={
                    "trait_id": "pgs001123_coffee",
                    "confidence": "low",
                    "qc_summary": {"matched_variants": 0, "total_variants": 48, "overlap_percent": 0.0},
                },
                product_payload={
                    "trait_id": "pgs001123_coffee",
                    "display_name": "Coffee consumption",
                    "short_name": "Coffee",
                    "confidence": "low",
                    "percentile": 12.5,
                    "product_status": "limited",
                    "status": "usable",
                    "result_summary": "Within the reference range.",
                },
            )

            listed = store.list_reports(1, "sample-1")
            loaded = store.find_report(1, record.summary.report_id)

        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0].trait_id, "pgs001123_coffee")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.summary.sample_name, "Sample One")

    def test_report_store_replaces_same_trait_for_sample(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = TraitReportStore(Path(tmpdir))
            store.save_report(
                1,
                sample_id="sample-1",
                sample_name="Sample One",
                raw_file_id="raw-1",
                technical_payload={"trait_id": "pgs001123_coffee", "confidence": "low"},
                product_payload={
                    "trait_id": "pgs001123_coffee",
                    "display_name": "Coffee consumption",
                    "confidence": "low",
                    "percentile": 12.5,
                },
            )
            second = store.save_report(
                1,
                sample_id="sample-1",
                sample_name="Sample One",
                raw_file_id="raw-1",
                technical_payload={"trait_id": "pgs001123_coffee", "confidence": "medium"},
                product_payload={
                    "trait_id": "pgs001123_coffee",
                    "display_name": "Coffee consumption",
                    "confidence": "medium",
                    "percentile": 66.0,
                },
            )

            listed = store.list_reports(1, "sample-1")
            counts = store.count_reports_by_sample(1)

        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0].report_id, second.summary.report_id)
        self.assertEqual(listed[0].percentile, 66.0)
        self.assertEqual(counts["sample-1"], 1)

    def test_traits_about_moves_limitations_off_root_screen(self) -> None:
        counts = self.catalog.counts()
        root = traits_root_text(
            trait_count=counts["trait_count"],
            consumer_ready_trait_count=counts["consumer_ready_trait_count"],
            usable_trait_count=counts["usable_trait_count"],
            lang="ru",
        )
        about = traits_about_text(lang="ru")

        self.assertIn("PGS-отчёты по raw-файлу.", root)
        self.assertIn("Готово к расчёту", root)
        self.assertIn("Выберите sample", root)
        self.assertNotIn("не диагноз", root)
        self.assertIn("не диагноз", about)
        self.assertLessEqual(len(f"{TRAITS_CALLBACK_PREFIX}:about".encode("utf-8")), 64)

    def test_traits_run_sample_picker_starts_from_sample(self) -> None:
        screen_text = trait_run_sample_picker_text([], page=0, total_pages=1, lang="ru")

        self.assertIn("🧬 Выберите sample", screen_text)
        self.assertIn("Для расчёта нужен sample с raw-файлом.", screen_text)
        self.assertIn("Пока нет sample с raw-файлом.", screen_text)
        self.assertNotIn("Признак", screen_text)

    def test_trait_catalog_section_text_uses_compact_group_heading(self) -> None:
        entries = [item for item in self.catalog.list_traits() if item.group == "appearance"][:8]

        screen_text = trait_catalog_text(entries, page=0, total_pages=2, group_name="👤 Внешность", lang="ru")

        self.assertIn("<b>👤 Внешность</b>", screen_text)
        self.assertIn("Страница 1/2", screen_text)
        self.assertNotIn("Выберите признак:", screen_text)
        self.assertNotIn("Раздел:", screen_text)
        self.assertNotIn("Выберите признак ниже", screen_text)

    def test_trait_button_label_shortens_visible_list_labels_only(self) -> None:
        by_id = {item.trait_id: item for item in self.catalog.list_traits()}

        self.assertEqual(trait_button_label(by_id["pgs001092_hair_black"], lang="ru"), "Черные волосы")
        self.assertEqual(trait_button_label(by_id["pgs001071_facial_aging_about_age"], lang="ru"), "Возраст по лицу")
        self.assertEqual(trait_button_label(by_id["pgs000843_whr_adjusted_bmi"], lang="ru"), "Талия/бедра с поправкой на ИМТ")
        self.assertEqual(trait_button_label(by_id["pgs001019_gym_sports_club_attendance"], lang="ru"), "Посещение спортзала")
        self.assertEqual(trait_button_label(by_id["pgs003504_cannabis_use"], lang="ru"), "Употребление каннабиса")
        self.assertEqual(trait_button_label(by_id["pgs001537_left_accumbens_volume"], lang="ru"), "Объём левого прилежащего ядра")

    def test_trait_sample_picker_uses_direct_run_copy(self) -> None:
        screen_text = sample_picker_text("Возраст по лицу", [], page=0, total_pages=1, lang="ru")

        self.assertIn("🧬 Выберите sample", screen_text)
        self.assertIn("Признак", screen_text)
        self.assertIn("Возраст по лицу", screen_text)
        self.assertIn("Для расчёта нужен sample с raw-файлом.", screen_text)
        self.assertIn("Пока нет sample с raw-файлом.", screen_text)
        self.assertNotIn("Расчет признака", screen_text)

    def test_trait_visual_caption_uses_short_label_and_confidence_stars(self) -> None:
        caption = trait_visual_caption(
            sample_name="Заур",
            technical_payload={"trait_id": "pgs001092_hair_black"},
            product_payload={
                "trait_id": "pgs001092_hair_black",
                "display_name": "Hair color: black",
                "group": "appearance",
                "percentile": 34.1,
                "confidence": "Low",
            },
            lang="ru",
        )

        self.assertEqual(
            caption,
            "<b>👤 Черные волосы</b>\n\nSample: Заур\nПроцентиль: 34.1\nНадёжность: ★☆☆",
        )

    def test_trait_info_screen_hides_debug_fields(self) -> None:
        detail = self.catalog.get_trait_detail("pgs005316_body_fat_mass")

        screen_text = trait_detail_text(detail, lang="ru")

        self.assertIn("ℹ️ О признаке", screen_text)
        self.assertIn("🏃 Жировая масса тела", screen_text)
        self.assertIn("Раздел", screen_text)
        self.assertIn("Тело", screen_text)
        self.assertIn("Статус", screen_text)
        self.assertIn("Что показывает", screen_text)
        self.assertIn("Генетическая оценка по признаку «Жировая масса тела»", screen_text)
        self.assertIn("В расчёте", screen_text)
        self.assertIn("34 / 34", screen_text)
        self.assertIn("Технически", screen_text)
        self.assertIn("PGS ID", screen_text)
        self.assertIn("Исходное название", screen_text)
        self.assertNotIn("pgs005316_body_fat_mass", screen_text)
        self.assertNotIn("Кратко", screen_text)
        self.assertNotIn("Название в боте", screen_text)
        self.assertNotIn("ID в PGS Catalog", screen_text)

    def test_sensitive_trait_info_screen_includes_warning(self) -> None:
        detail = self.catalog.get_trait_detail("pgs003497_depression_episode")

        screen_text = trait_detail_text(detail, lang="ru")

        self.assertIn("🔬 Депрессивный эпизод", screen_text)
        self.assertIn("Раздел", screen_text)
        self.assertIn("Исследовательские", screen_text)
        self.assertIn("Важно", screen_text)
        self.assertIn("не является медицинским диагнозом", screen_text)
        self.assertNotIn("pgs003497_depression_episode", screen_text)

    def test_trait_visualization_renders_png(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            raw_path = Path(tmpdir) / "demo_ftdna.csv"
            raw_path.write_text(DEMO_RAW, encoding="utf-8")
            result = self.runtime.score_trait(
                trait_id="pgs001123_coffee",
                raw_path=raw_path,
                sample_id="Demo sample",
                input_format="ftdna",
            )
            image_path = Path(tmpdir) / "trait.png"

            render_trait_result_png(
                image_path,
                sample_name="Demo sample",
                product_payload=result.product_payload,
                technical_payload=result.technical_payload,
                lang="ru",
                status_label="PREVIEW",
            )

            self.assertTrue(image_path.exists())
            self.assertGreater(image_path.stat().st_size, 10_000)

    def test_importer_upserts_selected_trait_artifacts(self) -> None:
        source_root = Path(__file__).resolve().parents[1] / "app" / "features" / "traits"
        with tempfile.TemporaryDirectory() as tmpdir:
            target_root = Path(tmpdir) / "traits"

            result = import_trait_artifacts(
                source_root,
                target_root=target_root,
                trait_ids=["pgs001123_coffee"],
            )
            catalog = TraitCatalog(target_root / "data" / "pgs" / "trait_registry.json")
            trait = catalog.get_trait("pgs001123_coffee")

        self.assertEqual(result.imported_trait_ids, ["pgs001123_coffee"])
        self.assertTrue(trait.scoring_file_path.name.endswith(".txt.gz"))
        self.assertEqual(trait.display_name, "Coffee consumption")


if __name__ == "__main__":
    unittest.main()
