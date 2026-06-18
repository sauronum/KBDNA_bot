from __future__ import annotations

import unittest
import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory

from telegram import InlineKeyboardButton

from app.features.admixture.ui import (
    admixture_root_text,
    build_markup as build_admixture_markup,
    compare_project_models_text,
    compare_profiles_text,
    compare_report_button_label,
    compare_report_picker_text,
    compare_visual_caption,
    k36_sample_picker_text,
    oracle_project_models_text,
    oracle_mix_projects_text,
    oracle_mix_project_models_text,
    oracle_mix_mode_text,
    oracle_mix_report_button_label,
    oracle_mix_report_picker_text,
    oracle_mix_visual_caption,
    oracle_projects_text,
    oracle_report_picker_text,
    oracle_visual_caption,
    placeholder_feature_text,
    raw_calculators_text,
    raw_model_sample_picker_text,
    raw_project_models_text,
    sample_admixture_reports_text as admixture_sample_reports_text,
    similar_report_button_label,
)
from app.features.admixture.model_catalog import RawAdmixtureModel, RawAdmixtureProject
from app.features.admixture.oracle import OracleMatch, OracleMixMatch
from app.features.admixture.storage import AdmixtureReportRecord, AdmixtureReportSummary
from app.features.help.menu import HELP_SECTIONS_EN, build_help_keyboard, help_text
from app.features.haplogroups.ui import (
    build_markup as build_haplogroups_markup,
    haplogroup_input_text,
    haplogroups_root_text,
    lineage_menu_text,
    manual_type_text,
    records_list_text as haplogroup_records_list_text,
    sample_picker_text as haplogroup_sample_picker_text,
    str_profiles_text,
)
from app.features.matching.menu import MATCHING_CALLBACK_PREFIX, show_matching_menu
from app.features.matching.ui import build_markup, matching_root_text, sample_picker_text, saved_matches_text
from app.features.modeling.menu import (
    admixtools2_text,
    build_admixtools2_keyboard,
    build_modeling_keyboard,
    modeling_text,
)
from app.features.my_data.storage import SampleAsset
from app.features.reports.menu import (
    REPORT_PRODUCTS,
    build_report_detail_keyboard,
    build_reports_keyboard,
    platform_report_error_text,
    report_detail_text,
    reports_text,
)
from app.features.reports.g25_platform import _platform_reference_args, build_report_summary_lines, choose_sample_g25_coordinate
from app.features.traits.texts import localize_group, localize_product_status, localize_status


class SectionTranslationUiTests(unittest.TestCase):
    def test_modeling_stub_uses_english_copy(self) -> None:
        keyboard = build_modeling_keyboard("en")
        labels = [button.text for row in keyboard.inline_keyboard for button in row]

        self.assertIn("🏛 AdmixLab", modeling_text("en"))
        self.assertIn("Formal models.", modeling_text("en"))
        self.assertIn("🧬 ADMIXTOOLS 2", labels)
        self.assertIn("🏛 qpAdm classic", labels)
        self.assertIn("🌊 qpWave classic", labels)
        self.assertIn("📚 Source sets", labels)
        self.assertIn("💾 Saved models", labels)
        self.assertIn("⬅️ Back", labels)
        self.assertIn("Cancel", labels)

    def test_modeling_root_and_placeholders_use_product_copy(self) -> None:
        keyboard = build_modeling_keyboard("ru")
        labels = [[button.text for button in row] for row in keyboard.inline_keyboard]
        callbacks = [[button.callback_data for button in row] for row in keyboard.inline_keyboard]

        self.assertIn("🏛 AdmixLab", modeling_text("ru"))
        self.assertIn("Формальные модели.", modeling_text("ru"))
        self.assertEqual(labels, [
            ["🧬 ADMIXTOOLS 2"],
            ["🏛 qpAdm classic"],
            ["🌊 qpWave classic"],
            ["📚 Source sets"],
            ["💾 Saved models"],
            ["⬅️ Назад", "Отмена"],
        ])
        self.assertEqual(callbacks, [
            ["modeling:at2"],
            ["modeling:qpadm"],
            ["modeling:qpwave"],
            ["modeling:source_sets"],
            ["modeling:saved"],
            ["main:root", "main:cancel"],
        ])

    def test_admixtools2_workflow_menu_uses_product_copy(self) -> None:
        keyboard = build_admixtools2_keyboard("ru")
        text = admixtools2_text("ru")

        self.assertIn("🧬 ADMIXTOOLS 2", text)
        self.assertEqual(
            [[button.text for button in row] for row in keyboard.inline_keyboard],
            [
                ["🧪 qpAdm 2"],
                ["〰️ qpWave 2"],
                ["🕸 qpGraph 2"],
                ["📊 f-statistics"],
                ["📦 f2 cache"],
                ["⬅️ Назад", "Отмена"],
            ],
        )

    def test_reports_uses_english_copy(self) -> None:
        text = reports_text(lang="en")
        keyboard = build_reports_keyboard(lang="en")
        labels = [button.text for row in keyboard.inline_keyboard for button in row]

        self.assertIn("Personal studies based on your DNA samples.", text)
        self.assertIn("Choose a direction.", text)
        self.assertIn("🧬 DNA passport", labels)
        self.assertIn("🧭 Origin portrait", labels)
        self.assertIn("Back", labels)
        self.assertIn("Cancel", labels)

    def test_reports_root_uses_new_catalog_copy_and_order(self) -> None:
        text = reports_text()
        keyboard = build_reports_keyboard()
        labels = [row[0].text for row in keyboard.inline_keyboard[:-1]]
        callbacks = [row[0].callback_data for row in keyboard.inline_keyboard[:-1]]

        self.assertIn("Персональные исследования по вашим DNA-образцам.", text)
        self.assertIn("Выберите направление.", text)
        self.assertEqual(
            labels,
            [
                "🧬 DNA-паспорт",
                "🧭 Портрет происхождения",
                "🏺 Древние корни",
                "⛰ Региональное исследование",
                "👥 Семейное сравнение",
                "✨ Портрет признаков",
                "🌿 Отцовская и материнская линии",
            ],
        )
        self.assertEqual(
            callbacks,
            [
                "reports:passport:samples:0",
                "reports:info:origin_portrait",
                "reports:info:ancient_roots",
                "reports:info:regional_study",
                "reports:info:family_comparison",
                "reports:info:traits_portrait",
                "reports:info:lineage",
            ],
        )
        self.assertNotIn("Комплексный обзор", text)
        self.assertNotIn("Древние совпадения", " ".join(labels))
        self.assertNotIn("dna_platform", text)
        self.assertNotIn("Админский прототип", text)

    def test_reports_can_return_to_product_my_dna_entry(self) -> None:
        keyboard = build_reports_keyboard(back_callback="mydna:root")
        rows = [[button.callback_data for button in row] for row in keyboard.inline_keyboard]

        self.assertNotIn(["my_data:samples_view"], rows)
        self.assertEqual(rows[-1], ["mydna:root", "main:cancel"])

    def test_report_cards_are_informational_only(self) -> None:
        for product in REPORT_PRODUCTS:
            with self.subTest(product=product.product_id):
                if product.product_id == "passport":
                    continue
                text = report_detail_text(product)
                keyboard = build_report_detail_keyboard(product)
                rows = [[button.callback_data for button in row] for row in keyboard.inline_keyboard]

                self.assertIn(product.title("ru"), text)
                self.assertIn("Что вы получите:", text)
                self.assertIn("В разработке", text)
                self.assertNotIn("Выберите образец", text)
                self.assertNotIn("Сформировать демо", text)
                self.assertNotIn("backbone", text)
                self.assertNotIn("dna_platform", text)
                self.assertEqual(rows, [["reports:root", "main:cancel"]])

    def test_platform_report_summary_extracts_backbone_fields(self) -> None:
        analysis = {
            "sample_name": "Target",
            "routing": {
                "global": {
                    "modern_macro": {
                        "predicted_group": "West Eurasia",
                        "nearest": [{"reference": "Kabardin", "distance": 0.03123}],
                    },
                    "ancient_macro": {"predicted_group": "WestEurasia"},
                },
                "decision": {"selected_regions": [{"label": "West Eurasia"}]},
                "selected_backbone_branch": "west_eurasia",
                "regional_backbone": {
                    "west_eurasia": {
                        "modern_cluster": {"predicted_group": "Caucasus_North"},
                        "ancient_family": {"predicted_group": "Caucasus"},
                        "ancient_core": {"predicted_group": "Maikop"},
                    }
                },
            },
        }

        lines = build_report_summary_lines(analysis)

        self.assertIn("Modern macro: West Eurasia", lines)
        self.assertIn("Modern cluster: Caucasus_North", lines)
        self.assertIn("Nearest modern: Kabardin (0.0312)", lines)

    def test_platform_report_uses_first_attached_g25_coordinate(self) -> None:
        sample = SampleAsset("sample-a", "Азамат", "raw-a", ["coord-k36", "coord-g25"], "2026-05-31T19:30:00")

        class Store:
            def list_sample_coordinates(self, user_id, sample_id):
                self.called_with = (user_id, sample_id)
                return [
                    type("Coordinate", (), {"coordinate_type": "k36", "g25_line": "K36,1", "asset_id": "coord-k36"})(),
                    type("Coordinate", (), {"coordinate_type": "g25", "g25_line": "G25,1", "asset_id": "coord-g25"})(),
                ]

        store = Store()

        coordinate = choose_sample_g25_coordinate(store, 7, sample)

        self.assertEqual(store.called_with, (7, "sample-a"))
        self.assertEqual(coordinate.asset_id, "coord-g25")

    def test_platform_report_passes_linux_safe_reference_paths(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for relative_path in (
                "data/bootstrap_global/Global25_PCA_modern_pop_averages_scaled.txt",
                "data/bootstrap_global/Global25_PCA_ancient_pop_averages_scaled.txt",
                "data/bootstrap_global/Modern_Global_v1.txt",
                "data/bootstrap_global/Modern_Global_v1_manifest.tsv",
                "data/bootstrap_global/Ancient_Global_v1.txt",
                "data/bootstrap_global/Ancient_Global_v1_manifest.tsv",
                "backbone_method_hybrid/modern_population_seed_manifest.tsv",
                "backbone_method_hybrid/macroregion_scorer_thresholds.json",
                "backbone_method_hybrid/ancient_shortlist_by_macroregion.tsv",
                "backbone_method_hybrid/ancient_modern_bridge_seed.tsv",
            ):
                path = root / relative_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("", encoding="utf-8")

            args = _platform_reference_args(root)

        self.assertIn("--v2-modern-source", args)
        self.assertIn("--v2-modern-manifest", args)
        self.assertIn("--vahaduo-modern-refs", args)
        self.assertNotIn("Desktop\\DNA\\Vahaduo", " ".join(args))

    def test_platform_report_error_text_hides_traceback(self) -> None:
        text = platform_report_error_text(RuntimeError("Traceback (most recent call last):\nFileNotFoundError: missing"))

        self.assertIn("Этот отчёт находится в разработке.", text)
        self.assertNotIn("Traceback", text)
        self.assertNotIn("FileNotFoundError", text)

    def test_matching_root_uses_english_copy(self) -> None:
        text = matching_root_text(lang="en")
        keyboard = build_markup([[InlineKeyboardButton("Pairwise", callback_data="matching:pair:0")]], "main:root", lang="en")
        labels = [button.text for row in keyboard.inline_keyboard for button in row]

        self.assertIn("Sample closeness and matches.", text)
        self.assertNotIn("What you can do", text)
        self.assertIn("⬅️ Back", labels)

    def test_matching_root_uses_clean_russian_copy_and_callbacks(self) -> None:
        class Message:
            def __init__(self) -> None:
                self.calls = []
                self.chat_id = 10
                self.message_id = 1

            async def reply_text(self, text, reply_markup=None, parse_mode=None, do_quote=False):
                self.calls.append((text, reply_markup, parse_mode))
                return self

        message = Message()
        context = type("Context", (), {"application": type("App", (), {"bot_data": {}})()})()

        asyncio.run(show_matching_menu(message, context, 1, lang="ru"))

        text, keyboard, parse_mode = message.calls[-1]
        rows = keyboard.inline_keyboard
        labels = [[button.text for button in row] for row in rows]
        callbacks = [[button.callback_data for button in row] for row in rows]

        self.assertEqual(text, "<b>🧩 Matching</b>\n\nБлизость и совпадения sample’ов.")
        self.assertEqual(labels, [
            ["🧬 Сравнить два sample"],
            ["✅ Сравнить выбранные sample"],
            ["📊 Сравнить все sample"],
            ["🔎 Сравнить SNP"],
            ["💾 Сохранённые matches"],
            ["⬅️ Назад", "Отмена"],
        ])
        self.assertEqual(callbacks, [
            [f"{MATCHING_CALLBACK_PREFIX}:pair:0"],
            [f"{MATCHING_CALLBACK_PREFIX}:selected"],
            [f"{MATCHING_CALLBACK_PREFIX}:all"],
            [f"{MATCHING_CALLBACK_PREFIX}:snp"],
            [f"{MATCHING_CALLBACK_PREFIX}:saved"],
            ["main:root", "main:cancel"],
        ])
        self.assertEqual(parse_mode, "HTML")

    def test_matching_picker_uses_english_copy(self) -> None:
        sample = SampleAsset("sample-a", "Sample A", "raw-a", [], "2026-05-13T12:00:00")

        self.assertIn("Choose the first sample", sample_picker_text([sample], side="left", lang="en"))
        self.assertIn("Choose the second sample", sample_picker_text([], side="right", left_sample=sample, lang="en"))
        self.assertIn("There are no samples with raw files", sample_picker_text([], side="left", lang="en"))

    def test_saved_matches_uses_english_copy(self) -> None:
        self.assertIn("There are no saved matching results yet", saved_matches_text([], lang="en"))

    def test_haplogroups_uses_english_copy(self) -> None:
        sample = SampleAsset("sample-a", "Sample A", "raw-a", [], "2026-05-13T12:00:00")
        keyboard = build_haplogroups_markup([], "main:root", lang="en")
        labels = [button.text for row in keyboard.inline_keyboard for button in row]

        self.assertIn("Choose a section", haplogroups_root_text("en"))
        self.assertIn("Y-SNP/raw prediction", lineage_menu_text("Y-DNA", "en"))
        self.assertIn("Choose a sample", haplogroup_sample_picker_text([sample], "Y-DNA", lang="en"))
        self.assertIn("Send the branch as text", haplogroup_input_text(sample, "Y-DNA", "en"))
        self.assertIn("Add haplogroup", manual_type_text("en"))
        self.assertNotIn("known result", manual_type_text("en"))
        self.assertIn("There are no saved haplogroup records yet", haplogroup_records_list_text([], lang="en"))
        self.assertIn("No Y-STR/DYS profiles yet", str_profiles_text([], "en"))
        self.assertIn("⬅️ Back", labels)
        self.assertIn("Cancel", labels)

    def test_traits_uses_english_enum_labels(self) -> None:
        self.assertEqual(localize_group("sensitive_research", lang="en"), "Sensitive research")
        self.assertEqual(localize_status("usable", lang="en"), "ready")
        self.assertEqual(localize_product_status("consumer_trait", lang="en"), "consumer trait")

    def test_admixture_uses_english_copy(self) -> None:
        sample = SampleAsset("sample-a", "Sample A", "raw-a", [], "2026-05-13T12:00:00")
        keyboard = build_admixture_markup([], "main:root", lang="en")
        labels = [button.text for row in keyboard.inline_keyboard for button in row]

        self.assertIn("Components, similar populations, and oracle mix", admixture_root_text("en"))
        self.assertNotIn("Modes", admixture_root_text("en"))
        self.assertIn("Choose a sample for the K36 profile", k36_sample_picker_text([sample], "en"))
        self.assertIn("Choose a saved profile", admixture_sample_reports_text(sample, [object()], [], "en"))
        self.assertIn("Back", labels)
        self.assertIn("Cancel", labels)

    def test_admixture_project_pickers_use_clean_russian_copy(self) -> None:
        model = RawAdmixtureModel("K36", 36, "alleles.txt", "freq.txt", True)
        project = RawAdmixtureProject("eurogenes", "Eurogenes", (model,))

        self.assertIn("Установлено: <b>1</b> / 1", raw_calculators_text([project], "ru"))
        self.assertIn("Выберите проект калькулятора.", raw_calculators_text([project], "ru"))
        self.assertIn("Установлено: 1 / 1", raw_project_models_text(project, "ru"))
        self.assertIn("Сравнение сохранённых admixture-профилей.", compare_profiles_text([("eurogenes", 2)], "ru"))
        self.assertIn("Выберите проект.", compare_profiles_text([("eurogenes", 2)], "ru"))
        self.assertIn("Поиск ближайших популяций по сохранённому admixture-профилю.", oracle_projects_text([("eurogenes", 2)], "ru"))
        self.assertIn("Выберите проект.", oracle_projects_text([("eurogenes", 2)], "ru"))
        self.assertIn("Подбор смеси популяций по сохранённому admixture-профилю.", oracle_mix_projects_text([("eurogenes", 2)], "ru"))
        self.assertIn("Выберите проект.", oracle_mix_projects_text([("eurogenes", 2)], "ru"))
        self.assertIn(
            "Функция пока не реализована.",
            placeholder_feature_text("🎨 Chromosome painting", "Разметка участков хромосом по admixture-компонентам.", "ru"),
        )

    def test_admixture_compare_profiles_uses_clean_copy(self) -> None:
        project = RawAdmixtureProject("eurogenes", "Eurogenes", ())
        left_summary = AdmixtureReportSummary(
            "report-left",
            "sample-left",
            "Дотдаева М.",
            "coord-left",
            "coord-left",
            "K13",
            "K13 profile",
            "West Asian",
            45.6,
            "",
            "2026-05-24T08:11:00",
        )
        right_summary = AdmixtureReportSummary(
            "report-right",
            "sample-right",
            "Заур",
            "coord-right",
            "coord-right",
            "K13",
            "K13 profile",
            "West Asian",
            44.0,
            "",
            "2026-05-24T08:12:00",
        )
        left_record = AdmixtureReportRecord(left_summary, {}, {})
        right_record = AdmixtureReportRecord(right_summary, {}, {})
        comparison = {
            "model": "K13",
            "total_absolute_difference": 14.27,
            "average_absolute_difference": 1.19,
        }

        project_text = compare_profiles_text([("eurogenes", 2)], "ru")
        model_text = compare_project_models_text(project, [("K13", 2)], "ru")
        first_text = compare_report_picker_text("K13", [left_summary, right_summary], side="left", lang="ru")
        second_text = compare_report_picker_text("K13", [right_summary], side="right", first_report=left_summary, lang="ru")
        caption = compare_visual_caption(left_record, right_record, comparison)

        self.assertIn("⚖️ Compare profiles", project_text)
        self.assertIn("Сравнение сохранённых admixture-профилей.", project_text)
        self.assertIn("Выберите проект.", project_text)
        self.assertIn("⚖️ Eurogenes", model_text)
        self.assertIn("Выберите модель для сравнения.", model_text)
        self.assertIn("⚖️ K13 comparison", first_text)
        self.assertIn("Выберите первый профиль.", first_text)
        self.assertIn("Сохранённых профилей:", first_text)
        self.assertIn("Первый профиль: Дотдаева М.", second_text)
        self.assertIn("Выберите второй профиль.", second_text)
        self.assertIn("Доступно для сравнения:", second_text)
        self.assertEqual(compare_report_button_label(left_summary), "Дотдаева М. · West Asian 45.6%")
        self.assertNotIn("K13:", compare_report_button_label(left_summary))
        self.assertIn("⚖️ K13 comparison", caption)
        self.assertIn("Дотдаева М. × Заур", caption)
        self.assertIn("Общая разница: 14.27", caption)
        self.assertIn("Средняя разница: 1.19", caption)
        self.assertNotIn("Total diff:", caption)
        self.assertNotIn("Avg:", caption)
        self.assertNotIn(" vs ", caption)

    def test_admixture_similar_populations_uses_clean_copy(self) -> None:
        project = RawAdmixtureProject("eurogenes", "Eurogenes", ())
        left_summary = AdmixtureReportSummary(
            "report-left",
            "sample-left",
            "Дотдаева М.",
            "coord-left",
            "coord-left",
            "K13",
            "K13 profile",
            "West Asian",
            45.6,
            "",
            "2026-05-24T08:11:00",
        )
        right_summary = AdmixtureReportSummary(
            "report-right",
            "sample-right",
            "Заур",
            "coord-right",
            "coord-right",
            "K13",
            "K13 profile",
            "West Asian",
            44.0,
            "",
            "2026-05-24T08:12:00",
        )
        record = AdmixtureReportRecord(left_summary, {}, {})
        matches = [
            OracleMatch("Balkar", "ref", 6.7471),
            OracleMatch("Karachay", "ref", 7.0441),
        ]

        project_text = oracle_projects_text([("eurogenes", 2)], "ru")
        model_text = oracle_project_models_text(project, [("K13", 2)], "ru")
        picker_text = oracle_report_picker_text("K13", [left_summary, right_summary], 178, "ru")
        caption = oracle_visual_caption(record, matches)

        self.assertIn("🧭 Similar populations", project_text)
        self.assertIn("Поиск ближайших популяций по сохранённому admixture-профилю.", project_text)
        self.assertIn("Выберите проект.", project_text)
        self.assertIn("🧭 Eurogenes", model_text)
        self.assertIn("Выберите модель для поиска похожих популяций.", model_text)
        self.assertIn("🧭 K13 similar populations", picker_text)
        self.assertIn("Референсных популяций: 178", picker_text)
        self.assertIn("Сохранённых профилей: 2", picker_text)
        self.assertIn("Выберите профиль.", picker_text)
        self.assertEqual(similar_report_button_label(left_summary), "Дотдаева М. · West Asian 45.6%")
        self.assertEqual(similar_report_button_label(right_summary), "Заур · West Asian 44.0%")
        self.assertNotIn("Дотдаева М.: K13:", similar_report_button_label(left_summary))
        self.assertIn("🧭 K13 similar populations", caption)
        self.assertIn("Sample: <b>Дотдаева М.</b>", caption)
        self.assertIn("Ближайшая популяция: Balkar", caption)
        self.assertIn("Дистанция: 6.7471", caption)
        self.assertIn("Отрыв от #2: 0.2970", caption)
        self.assertNotIn("Similar populations: Eurogenes", model_text)
        self.assertNotIn("Reference populations:", picker_text)
        self.assertNotIn("Saved profiles:", picker_text)
        self.assertNotIn("Выберите сохранённый profile", picker_text)
        self.assertNotIn("Closest:", caption)

    def test_admixture_oracle_mix_uses_clean_copy(self) -> None:
        project = RawAdmixtureProject("dodecad", "Dodecad", ())
        left_summary = AdmixtureReportSummary(
            "report-left",
            "sample-left",
            "Люда",
            "coord-left",
            "coord-left",
            "K7b",
            "K7b profile",
            "West Asian",
            40.2,
            "",
            "2026-05-24T08:11:00",
        )
        right_summary = AdmixtureReportSummary(
            "report-right",
            "sample-right",
            "Заур",
            "coord-right",
            "coord-right",
            "K7b",
            "K7b profile",
            "West Asian",
            43.1,
            "",
            "2026-05-24T08:12:00",
        )
        record = AdmixtureReportRecord(right_summary, {}, {})
        matches = [
            OracleMixMatch(
                populations=("Greek_D", "Lezgin", "Nogais_Y"),
                sources=("ref", "ref", "ref"),
                percents=(20, 50, 30),
                distance=2.8386,
            )
        ]

        model_text = oracle_mix_project_models_text(project, [("K7b", 2)], "ru")
        mode_text = oracle_mix_mode_text("K7b", 223, 2, "ru")
        picker_text = oracle_mix_report_picker_text("K7b", "3-way", [left_summary, right_summary], 223, "ru")
        caption = oracle_mix_visual_caption(record, "3-way", matches)

        self.assertIn("🧬 Dodecad", model_text)
        self.assertIn("Выберите модель для oracle mix.", model_text)
        self.assertNotIn("Oracle mix: Dodecad", model_text)
        self.assertIn("🧬 K7b oracle mix", mode_text)
        self.assertIn("Референсных популяций: 223", mode_text)
        self.assertIn("Сохранённых профилей: 2", mode_text)
        self.assertIn("Выберите режим смеси.", mode_text)
        self.assertIn("Режим: 3-way mix", picker_text)
        self.assertIn("Выберите профиль.", picker_text)
        self.assertEqual(oracle_mix_report_button_label(left_summary), "Люда · West Asian 40.2%")
        self.assertEqual(oracle_mix_report_button_label(right_summary), "Заур · West Asian 43.1%")
        self.assertNotIn("Люда: K7b:", oracle_mix_report_button_label(left_summary))
        self.assertNotIn("Заур: K7b:", oracle_mix_report_button_label(right_summary))
        self.assertIn("🧬 K7b oracle mix", caption)
        self.assertIn("Sample: <b>Заур</b>", caption)
        self.assertIn("Режим: 3-way mix", caption)
        self.assertIn("Лучшая смесь: 20% Greek_D + 50% Lezgin + 30% Nogais_Y", caption)
        self.assertIn("Дистанция: 2.8386", caption)
        self.assertNotIn("Best 3-way:", caption)
        self.assertNotIn("\n2.8386", caption)
        self.assertNotIn("Reference populations:", picker_text)
        self.assertNotIn("Saved profiles:", picker_text)
        self.assertNotIn("Выберите сохраненный profile", picker_text)
        self.assertNotIn("Выберите сохранённый profile", picker_text)
        self.assertNotIn("Mode:", picker_text)

    def test_admixture_raw_model_sample_picker_uses_clean_copy(self) -> None:
        sample = SampleAsset("sample-a", "Sample A", "raw-a", [], "2026-05-13T12:00:00")
        text = raw_model_sample_picker_text("K36", [sample], "ru")

        self.assertIn("🧮 K36 profile", text)
        self.assertIn("Выберите sample для K36-профиля.", text)
        self.assertIn("Если профиль уже сохранён, откроется сохранённый результат.", text)
        self.assertIn("Sample с raw-файлом:", text)
        self.assertNotIn("calculator", text)
        self.assertNotIn("reports", text)
        self.assertNotIn("profile preview", text)
        self.assertNotIn("Samples:", text)

    def test_help_uses_full_english_copy(self) -> None:
        keyboard = build_help_keyboard("en")
        labels = [button.text for row in keyboard.inline_keyboard for button in row]
        my_dna_body = HELP_SECTIONS_EN["mydna"][1]

        self.assertIn("Choose a topic below", help_text("en"))
        self.assertIn("personal library", my_dna_body)
        self.assertIn("Practical rule", my_dna_body)
        self.assertTrue(any("Quick Start" in label for label in labels))
        self.assertIn("Cancel", labels)


if __name__ == "__main__":
    unittest.main()
