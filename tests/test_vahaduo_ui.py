from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.features.my_data.storage import MyDataStore
from app.features.vahaduo.menu import (
    _send_distance_result_photo_from_query,
    _send_multi_result_photo_from_query,
    _send_single_result_photo_from_query,
    vahaduo_callback_handler,
)
from app.features.vahaduo.ready_models import (
    ReadyModelTarget,
    build_ready_model_confirmation_keyboard,
    build_ready_model_result_keyboard,
    build_ready_models_sets_keyboard,
    build_ready_models_targets_keyboard,
    ready_model_confirmation_text,
    ready_model_result_text,
    ready_models_sets_text,
    ready_models_targets_text,
)
from app.features.vahaduo.storage import VahaduoFullStore
from app.features.vahaduo.ui import (
    _build_g25vahaduo_distance_result_keyboard,
    _build_g25vahaduo_full_keyboard,
    _build_g25vahaduo_multi_result_keyboard,
    _build_g25vahaduo_multi_targets_keyboard,
    _build_g25vahaduo_saved_components_keyboard,
    _build_g25vahaduo_saved_keyboard,
    _build_g25vahaduo_source_menu_keyboard,
    _build_g25vahaduo_single_components_keyboard,
    _build_g25vahaduo_single_result_keyboard,
    _build_g25vahaduo_targets_keyboard,
    _build_g25vahaduo_target_library_keyboard,
    _build_g25vahaduo_target_keyboard,
    _g25vahaduo_data_source_text,
    _g25vahaduo_distance_result_caption,
    _g25vahaduo_full_text,
    _g25vahaduo_multi_result_caption,
    _g25vahaduo_multi_targets_text,
    _g25vahaduo_saved_text,
    _g25vahaduo_single_result_caption,
    _g25vahaduo_source_menu_text,
    _g25vahaduo_targets_text,
    _g25vahaduo_target_library_text,
    _g25vahaduo_target_text,
)
from app.features.vahaduo.ready_models_runtime import SourceFitComponent, SourceFitResult
from app.features.vahaduo.ready_model_sets import get_source_set, list_source_sets
from app.main_menu import MainMenuStore
from g25_core.render_fit_png import _multi_component_header, _single_visible_groups, render_distance_png, render_multi_heatmap_png, render_single_card_png


def _png_size(png_bytes: bytes) -> tuple[int, int]:
    return (
        int.from_bytes(png_bytes[16:20], "big"),
        int.from_bytes(png_bytes[20:24], "big"),
    )


class VahaduoUiTests(unittest.TestCase):
    def test_vahaduo_root_uses_english_copy(self) -> None:
        text = _g25vahaduo_full_text(lang="en")
        keyboard = _build_g25vahaduo_full_keyboard(lang="en")
        labels = [button.text for row in keyboard.inline_keyboard for button in row]

        self.assertIn("📐 Vahaduo Lab", text)
        self.assertIn("G25 tools", text)
        self.assertNotIn("Modes", text)
        self.assertEqual(labels[:5], ["📚 My sources", "📏 Distance", "🧬 Single", "🧩 Multi", "📚 Ready models"])
        self.assertIn("⬅️ Back", labels)
        self.assertIn("Cancel", labels)

    def test_vahaduo_root_uses_clean_russian_copy(self) -> None:
        text = _g25vahaduo_full_text()
        keyboard = _build_g25vahaduo_full_keyboard()
        labels = [button.text for row in keyboard.inline_keyboard for button in row]

        self.assertEqual(text, "<b>📐 Vahaduo Lab</b>\n\nG25-инструменты")
        self.assertEqual(labels[:5], ["📚 Мои источники", "📏 Distance", "🧬 Single", "🧩 Multi", "📚 Ready models"])
        self.assertEqual(labels[-2:], ["⬅️ Назад", "Отмена"])

    def test_ready_models_flow_uses_vahaduo_copy(self) -> None:
        source_sets = list_source_sets()
        source_set = get_source_set("steppe_russia")
        self.assertIsNotNone(source_set)
        target = ReadyModelTarget("coord-1", "Заур", "Za'ur,0,0")
        result = SourceFitResult(
            status="ok",
            target_name="Заур",
            source_set_id="steppe_russia",
            source_set_title="Steppe / Russia",
            distance=0.0151,
            components=(SourceFitComponent("Maikop / Caucasus", "🏔", "Maikop", 62.7),),
        )

        targets_text = ready_models_targets_text([target])
        targets_keyboard = build_ready_models_targets_keyboard([target])
        sets_text = ready_models_sets_text("Заур", source_sets)
        sets_keyboard = build_ready_models_sets_keyboard(source_sets, "flow1234")
        confirm_text = ready_model_confirmation_text("Заур", source_set)  # type: ignore[arg-type]
        confirm_keyboard = build_ready_model_confirmation_keyboard("flow1234")
        result_text = ready_model_result_text(result, source_set)  # type: ignore[arg-type]
        result_keyboard = build_ready_model_result_keyboard("flow1234")

        self.assertIn("📚 Ready models", targets_text)
        self.assertIn("Готовые G25-модели источников.", targets_text)
        self.assertIn("Выберите G25-профиль.", targets_text)
        self.assertEqual(targets_keyboard.inline_keyboard[0][0].callback_data, "vahaduo:ready_model_target:coord-1")
        self.assertIn("G25-профиль: Заур", sets_text)
        self.assertIn("Выберите модель.", sets_text)
        self.assertEqual(sets_keyboard.inline_keyboard[0][0].callback_data, "vahaduo:ready_model_set:flow1234:steppe_russia")
        self.assertIn("📚 Ready model", confirm_text)
        self.assertIn("Модель: Steppe / Russia", confirm_text)
        self.assertIn("Это G25-fit модель, не qpAdm.", confirm_text)
        self.assertIn("▶️ Запустить модель", [button.text for row in confirm_keyboard.inline_keyboard for button in row])
        self.assertIn("📚 Ready models", result_text)
        self.assertIn("Distance: 0.0151", result_text)
        self.assertIn("🔁 Проверить другую модель", [button.text for row in result_keyboard.inline_keyboard for button in row])

    def test_distance_source_picker_uses_clean_labels(self) -> None:
        service = SimpleNamespace(
            list_vahaduo_preset_sources=lambda mode: [
                {"key": "modern", "label": "modern"},
                {"key": "origin", "label": "ancestry"},
            ]
        )
        state = {"mode": "distance"}
        text = _g25vahaduo_source_menu_text(state)
        keyboard = _build_g25vahaduo_source_menu_keyboard(service, state)
        rows = keyboard.inline_keyboard
        labels = [row[0].text for row in rows[:-1]]

        self.assertEqual(text, "📏 Distance\n\nВыберите источники")
        self.assertEqual(labels, ["🌍 Modern", "🏺 Ancient", "📚 Мои источники"])
        self.assertEqual(rows[0][0].callback_data, "vahaduo:vahaduo_preset:modern")
        self.assertEqual(rows[1][0].callback_data, "vahaduo:vahaduo_preset:origin")
        self.assertEqual([button.text for button in rows[-1]], ["⬅️ Назад", "Отмена"])

    def test_source_picker_title_follows_mode_without_changing_callbacks(self) -> None:
        service = SimpleNamespace(list_vahaduo_preset_sources=lambda mode: [{"key": "panel1", "label": "Steppe_Russia"}])
        single_keyboard = _build_g25vahaduo_source_menu_keyboard(service, {"mode": "single"})

        self.assertEqual(_g25vahaduo_source_menu_text({"mode": "single"}), "🧬 Single\n\nВыберите источники")
        self.assertEqual(_g25vahaduo_source_menu_text({"mode": "multi"}), "🧩 Multi\n\nВыберите источники")
        self.assertEqual(single_keyboard.inline_keyboard[0][0].text, "🐎 Steppe / Russia")
        self.assertEqual(single_keyboard.inline_keyboard[0][0].callback_data, "vahaduo:vahaduo_preset:panel1")

    def test_saved_sources_uses_english_copy(self) -> None:
        text = _g25vahaduo_saved_text([], "distance", lang="en")
        keyboard = _build_g25vahaduo_saved_keyboard([], include_upload=True, lang="en")
        labels = [button.text for row in keyboard.inline_keyboard for button in row]

        self.assertIn("Mode: Distance", text)
        self.assertIn("You do not have saved sets", text)
        self.assertIn("Upload source file", labels)
        self.assertIn("Back", labels)

    def test_target_library_uses_english_copy(self) -> None:
        state = {"source_key": "modern", "source_label": "modern", "mode": "distance"}
        text = _g25vahaduo_target_library_text(for_run=True, state=state, lang="en")
        keyboard = _build_g25vahaduo_target_library_keyboard(for_run=True, lang="en")
        labels = [button.text for row in keyboard.inline_keyboard for button in row]

        self.assertIn("📏 Distance", text)
        self.assertIn("Source: 🌍 Modern", text)
        self.assertIn("Choose a G25 profile.", text)
        self.assertNotIn("target", text)
        self.assertIn("🧬 Samples", labels)
        self.assertIn("📍 G25 profiles", labels)
        self.assertIn("⬅️ Back", labels)

    def test_target_flow_uses_english_copy(self) -> None:
        state = {"source_key": "modern", "source_label": "modern", "source_count": 2, "mode": "distance"}
        text = _g25vahaduo_target_text(state, lang="en")
        keyboard = _build_g25vahaduo_target_keyboard(state, lang="en")
        labels = [button.text for row in keyboard.inline_keyboard for button in row]

        self.assertIn("📏 Distance", text)
        self.assertIn("Source: 🌍 Modern", text)
        self.assertIn("Populations: 2", text)
        self.assertIn("Send G25 as text or a file.", text)
        self.assertIn("Or choose a saved profile.", text)
        self.assertNotIn("Mode:", text)
        self.assertNotIn("SOURCE:", text)
        self.assertNotIn("TARGET", text)
        self.assertNotIn("In a group", text)
        self.assertIn("📍 G25 profiles", labels)
        self.assertIn("⬅️ Back", labels)
        self.assertNotIn("Paste target as text", labels)
        self.assertNotIn("Upload target file", labels)

    def test_target_flow_uses_clean_russian_copy(self) -> None:
        state = {"source_key": "modern", "source_label": "modern", "source_count": 1013, "mode": "distance"}
        text = _g25vahaduo_target_text(state)
        keyboard = _build_g25vahaduo_target_keyboard(state)
        labels = [button.text for row in keyboard.inline_keyboard for button in row]

        self.assertEqual(
            text,
            "📏 Distance\n\n"
            "Источник: 🌍 Modern\n"
            "Популяций: 1013\n\n"
            "Отправьте G25 текстом или файлом.\n"
            "Или выберите сохранённый профиль.",
        )
        self.assertEqual(labels, ["📍 G25-профили", "⬅️ Назад", "Отмена"])
        self.assertNotIn("Вставить target текстом", labels)
        self.assertNotIn("Загрузить target файлом", labels)
        self.assertNotIn("В группе", text)

    def test_target_picker_lists_use_clean_russian_copy(self) -> None:
        state = {"source_key": "modern", "source_label": "modern", "mode": "distance"}
        samples_text = _g25vahaduo_targets_text(
            [{"id": "sample|abc", "title": "Заур"}],
            for_run=True,
            source="samples",
            state=state,
        )
        other_text = _g25vahaduo_targets_text(
            [{"id": "abc", "title": "Ibragim"}],
            for_run=True,
            source="other",
            state=state,
        )
        samples_keyboard = _build_g25vahaduo_targets_keyboard(
            [{"id": "sample|abc", "title": "Заур"}],
            for_run=True,
            source="samples",
        )
        other_keyboard = _build_g25vahaduo_targets_keyboard(
            [{"id": "abc", "title": "Ibragim"}],
            for_run=True,
            source="other",
        )
        samples_labels = [button.text for row in samples_keyboard.inline_keyboard for button in row]
        other_labels = [button.text for row in other_keyboard.inline_keyboard for button in row]

        self.assertIn("📏 Distance", samples_text)
        self.assertIn("Источник: 🌍 Modern", samples_text)
        self.assertIn("🧬 Samples", samples_text)
        self.assertIn("Выберите G25-профиль.", samples_text)
        self.assertNotIn("target", samples_text)
        self.assertIn("📍 G25-профили", other_text)
        self.assertEqual(samples_labels, ["1. Заур", "⬅️ Назад", "Отмена"])
        self.assertEqual(other_labels, ["1. Ibragim", "⬅️ Назад", "Отмена"])

    def test_single_target_screens_use_model_summary(self) -> None:
        state = {
            "source_key": "single_panel1",
            "source_label": "Steppe_Russia: Maikop, Steppe Sintashta, Yellow River",
            "source_count": 75,
            "mode": "single",
        }
        target_text = _g25vahaduo_target_text(state)
        picker_text = _g25vahaduo_target_library_text(for_run=True, state=state)
        samples_text = _g25vahaduo_targets_text(
            [{"id": "sample|abc", "title": "Заур"}],
            for_run=True,
            source="samples",
            state=state,
        )
        other_text = _g25vahaduo_targets_text(
            [{"id": "abc", "title": "Ibragim"}],
            for_run=True,
            source="other",
            state=state,
        )

        self.assertIn("🧬 Single", target_text)
        self.assertIn("Набор: 🐎 Steppe / Russia", target_text)
        self.assertIn("Источники: Maikop · Steppe Sintashta · Yellow River", target_text)
        self.assertIn("Популяций: 75", target_text)
        self.assertIn("Выберите G25-профиль.", picker_text)
        self.assertIn("🧬 Samples", samples_text)
        self.assertIn("📍 G25-профили", other_text)
        for text in (target_text, picker_text, samples_text, other_text):
            self.assertNotIn("Источник: Steppe_Russia", text)
            self.assertNotIn("Steppe_Russia", text)
            self.assertNotIn("target", text)
            self.assertNotIn("source", text)

    def test_single_source_list_is_compact(self) -> None:
        state = {
            "source_key": "single_panel1",
            "source_label": "Steppe_Russia: Maikop, Steppe Sintashta, Yellow River, Yamnaya, Afanasievo",
            "source_count": 120,
            "mode": "single",
        }

        text = _g25vahaduo_target_text(state)

        self.assertIn("Источники: Maikop · Steppe Sintashta · Yellow River · + ещё 2", text)

    def test_multi_target_screens_use_model_summary_and_plural_copy(self) -> None:
        state = {
            "source_key": "single_panel1",
            "source_label": "Steppe_Russia: Maikop, Steppe Sintashta, Yellow River, Anatolia BA, Baltic BA, KuraAraxes",
            "source_count": 173,
            "mode": "multi",
        }
        target_text = _g25vahaduo_target_text(state)
        picker_text = _g25vahaduo_target_library_text(for_run=True, state=state)
        samples_text = _g25vahaduo_multi_targets_text(
            [{"id": "sample|abc", "title": "Заур"}],
            [],
            state=state,
            source="samples",
        )
        other_text = _g25vahaduo_multi_targets_text(
            [{"id": "abc", "title": "Ibragim"}],
            [],
            state=state,
            source="other",
        )

        self.assertIn("🧩 Multi", target_text)
        self.assertIn("Набор: 🐎 Steppe / Russia", target_text)
        self.assertIn("Источники: Maikop · Steppe Sintashta · Yellow River · + ещё 3", target_text)
        self.assertIn("Популяций: 173", target_text)
        self.assertIn("Выберите G25-профили.", picker_text)
        self.assertIn("🧬 Samples", samples_text)
        self.assertIn("📍 G25-профили", other_text)
        self.assertIn("Выберите G25-профили.", samples_text)
        self.assertIn("Выбрано: 0 профилей", samples_text)
        for text in (target_text, picker_text, samples_text, other_text):
            self.assertNotIn("Источник: Steppe_Russia", text)
            self.assertNotIn("Steppe_Russia", text)
            self.assertNotIn("target", text)
            self.assertNotIn("source", text)

    def test_multi_target_keyboards_use_action_emojis(self) -> None:
        targets_keyboard = _build_g25vahaduo_multi_targets_keyboard(
            [{"id": "sample|abc", "title": "Заур"}],
            [],
        )
        target_labels = [button.text for row in targets_keyboard.inline_keyboard for button in row]
        service = SimpleNamespace(list_vahaduo_single_components=lambda panel_key: [{"key": "maikop", "label": "Maikop"}])
        components_keyboard = _build_g25vahaduo_single_components_keyboard(service, "panel1", [], mode="multi")
        component_labels = [button.text for row in components_keyboard.inline_keyboard for button in row]

        self.assertIn("✅ Выбрать все", target_labels)
        self.assertIn("✅ Готово", target_labels)
        self.assertIn("🧹 Очистить", target_labels)
        self.assertIn("⬅️ Назад", target_labels)
        self.assertIn("Отмена", target_labels)
        self.assertIn("✅ Выбрать все", component_labels)
        self.assertIn("✅ Готово", component_labels)
        self.assertIn("🧹 Очистить", component_labels)

    def test_component_picker_select_all_button_keeps_component_callbacks(self) -> None:
        service = SimpleNamespace(
            list_vahaduo_single_components=lambda panel_key: [
                {"key": "maikop", "label": "Maikop"},
                {"key": "yamnaya", "label": "Yamnaya"},
            ]
        )
        keyboard = _build_g25vahaduo_single_components_keyboard(service, "panel1", [], mode="single")
        rows = keyboard.inline_keyboard
        labels = [button.text for row in rows for button in row]

        self.assertIn("✅ Выбрать все", labels)
        self.assertEqual(rows[0][0].callback_data, "vahaduo:vahaduo_single_toggle:panel1:maikop")
        self.assertEqual(rows[0][1].callback_data, "vahaduo:vahaduo_single_toggle:panel1:yamnaya")
        self.assertIn("vahaduo:vahaduo_single_all:panel1", [button.callback_data for row in rows for button in row])

    def test_saved_component_picker_select_all_button_is_available(self) -> None:
        keyboard = _build_g25vahaduo_saved_components_keyboard(
            [
                {"key": "maikop", "label": "Maikop"},
                {"key": "yamnaya", "label": "Yamnaya"},
            ],
            [],
        )
        labels = [button.text for row in keyboard.inline_keyboard for button in row]

        self.assertIn("✅ Выбрать все", labels)
        self.assertIn("✅ Готово", labels)
        self.assertIn("🧹 Очистить", labels)

    def test_data_source_uses_english_copy(self) -> None:
        state = {"source_label": "Demo", "source_count": 3, "mode": "single"}
        text = _g25vahaduo_data_source_text(state, lang="en")

        self.assertIn("My sources", text)
        self.assertIn("Populations: 3", text)
        self.assertIn("The set is validated", text)

    def test_target_list_uses_stable_callbacks(self) -> None:
        coordinate_id = "20260514183000123456-abcdef12"
        other_keyboard = _build_g25vahaduo_targets_keyboard(
            [{"id": coordinate_id, "title": "Standalone G25"}],
            source="other",
        )
        sample_keyboard = _build_g25vahaduo_targets_keyboard(
            [{"id": f"sample|{coordinate_id}", "title": "Sample G25"}],
            source="samples",
        )

        self.assertEqual(other_keyboard.inline_keyboard[0][0].callback_data, f"vahaduo:vmo:{coordinate_id}")
        self.assertEqual(sample_keyboard.inline_keyboard[0][0].callback_data, f"vahaduo:vms:sample|{coordinate_id}")
        self.assertLessEqual(len(other_keyboard.inline_keyboard[0][0].callback_data.encode("utf-8")), 64)
        self.assertLessEqual(len(sample_keyboard.inline_keyboard[0][0].callback_data.encode("utf-8")), 64)

    def test_distance_result_caption_and_keyboard_are_clean(self) -> None:
        state = {"source_key": "modern", "source_label": "modern"}
        caption = _g25vahaduo_distance_result_caption(state, "Заур")
        keyboard = _build_g25vahaduo_distance_result_keyboard()
        labels = [button.text for row in keyboard.inline_keyboard for button in row]

        self.assertIn("📏 Distance", caption)
        self.assertIn("G25-профиль: Заур", caption)
        self.assertIn("Источник: 🌍 Modern", caption)
        self.assertNotIn("target", caption)
        self.assertNotIn("source", caption)
        self.assertNotIn("SOURCE", caption)
        self.assertNotIn("Режим", caption)
        self.assertEqual(labels, ["⬅️ Назад", "Отмена"])
        self.assertNotIn("К источникам", labels)
        self.assertNotIn("Расчет готов", caption)

    def test_single_result_caption_and_keyboard_are_clean(self) -> None:
        state = {
            "source_key": "single_panel1",
            "source_label": "Steppe_Russia: Maikop, Yamnaya, Ulaanzhukh, Yellow River",
            "mode": "single",
        }
        result = SimpleNamespace(
            panel_name="Steppe_Russia",
            target_name="Заур",
            distance=0.018917,
            sources=73,
            iterations=250,
            elapsed_seconds=0.044,
            groups=[
                ("Maikop", 0.599),
                ("Yamnaya", 0.335),
                ("Ulaanzhukh", 0.016),
                ("Yellow_River", 0.05),
            ],
        )
        caption = _g25vahaduo_single_result_caption(state, result)
        keyboard = _build_g25vahaduo_single_result_keyboard()
        labels = [button.text for row in keyboard.inline_keyboard for button in row]

        self.assertNotIn("🧬 Single", caption)
        self.assertTrue(caption.startswith("Source: 🐎 Steppe / Russia"))
        self.assertIn("Source: 🐎 Steppe / Russia", caption)
        self.assertIn("Target: Заур", caption)
        self.assertIn("Distance: 1.8917% / 0.018917", caption)
        self.assertIn("Sources: 73 | Cycles: 250 | Time: 0.044 s", caption)
        self.assertIn("🏔️ 59.9%  Maikop", caption)
        self.assertIn("🐎 33.5%  Yamnaya", caption)
        self.assertIn("🦌 1.6%  Ulaanzhukh", caption)
        self.assertIn("⛩️ 5.0%  Yellow River", caption)
        self.assertNotIn("Источники: Maikop", caption)
        self.assertNotIn("target", caption)
        self.assertNotIn("SOURCE", caption)
        self.assertNotIn("Режим", caption)
        self.assertNotIn("Steppe_Russia", caption)
        self.assertEqual(labels, ["⬅️ Назад", "Отмена"])
        self.assertNotIn("К источникам", labels)
        self.assertNotIn("Расчет готов", caption)

    def test_multi_result_caption_and_keyboard_are_clean(self) -> None:
        state = {
            "source_key": "single_panel1",
            "source_label": "Steppe_Russia: Maikop, Yamnaya, Ulaanzhukh",
            "mode": "multi",
        }
        result = SimpleNamespace(
            panel_name="Steppe_Russia",
            target_count=18,
            average_distance=0.015562,
            sources=173,
            iterations=250,
            elapsed_seconds=2.069,
        )
        caption = _g25vahaduo_multi_result_caption(state, result)
        keyboard = _build_g25vahaduo_multi_result_keyboard()
        labels = [button.text for row in keyboard.inline_keyboard for button in row]

        self.assertIn("Source: 🐎 Steppe / Russia", caption)
        self.assertIn("Targets: 18", caption)
        self.assertIn("Average distance: 1.5562% / 0.0155620", caption)
        self.assertIn("Sources: 173 | Cycles: 250 | Time: 2.069 s", caption)
        self.assertNotIn("Vahaduo Multi:", caption)
        self.assertNotIn("Steppe_Russia", caption)
        self.assertNotIn("🧩 Multi", caption)
        self.assertEqual(labels, ["⬅️ Назад", "Отмена"])
        self.assertNotIn("К источникам", labels)
        self.assertNotIn("Расчет готов", caption)

    def test_single_card_renderer_preserves_order_and_omits_zero_components(self) -> None:
        groups = [
            ("Yamnaya", 0.30),
            ("Maikop", 0.632),
            ("Yellow_River", 0.0),
            ("Ulaanzhukh", 0.068),
        ]

        self.assertEqual(
            _single_visible_groups(groups),
            [("Yamnaya", 0.30), ("Maikop", 0.632), ("Ulaanzhukh", 0.068)],
        )
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "single.png"
            render_single_card_png("Steppe_Russia: Yamnaya, Maikop, Yellow River, Ulaanzhukh", "Заур", 0.01726, 73, groups, output)
            png_bytes = output.read_bytes()

        self.assertTrue(png_bytes.startswith(b"\x89PNG\r\n\x1a\n"))
        width, height = _png_size(png_bytes)
        self.assertGreaterEqual(width, 1160)
        self.assertGreaterEqual(height, 430)

    def test_multi_card_renderer_outputs_table_without_collapsing_components(self) -> None:
        rows = [
            {"target": "Zaur", "distance": 0.016679, "groups": {"Maikop": 0.629, "Steppe_Sintashta": 0.306, "Yellow_River": 0.065}},
            {"target": "Aznaur", "distance": 0.020323, "groups": {"Maikop": 0.715, "Steppe_Sintashta": 0.214, "Yellow_River": 0.0}},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "multi.png"
            render_multi_heatmap_png(
                "Steppe_Russia",
                rows,
                ["Maikop", "Steppe_Sintashta", "Yellow_River"],
                0.018501,
                {"Maikop": 0.672, "Steppe_Sintashta": 0.26, "Yellow_River": 0.032},
                output,
            )
            png_bytes = output.read_bytes()

        self.assertTrue(png_bytes.startswith(b"\x89PNG\r\n\x1a\n"))
        width, height = _png_size(png_bytes)
        self.assertGreaterEqual(width, 700)
        self.assertGreaterEqual(height, 250)

    def test_multi_component_headers_use_plain_names(self) -> None:
        self.assertEqual(_multi_component_header("Steppe_Sintashta"), "STEPPE SINTASHTA")
        self.assertEqual(_multi_component_header("Yellow_River"), "YELLOW RIVER")
        self.assertEqual(_multi_component_header("Anatolia_BA"), "ANATOLIA BA")
        self.assertEqual(_multi_component_header("Afanasievo"), "AFANASIEVO")
        self.assertEqual(_multi_component_header("Angara_River_BA"), "ANGARA RIVER BA")

    def test_distance_card_renderer_outputs_ranked_board(self) -> None:
        matches = [
            (0.0126513, "Balkar KBDNA"),
            (0.0173198, "Karachay-Balkar averaged"),
            (0.0182933, "Karachay KBDNA"),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "distance.png"
            render_distance_png("modern", "Shamil", matches, output)
            png_bytes = output.read_bytes()

        self.assertTrue(png_bytes.startswith(b"\x89PNG\r\n\x1a\n"))
        width, height = _png_size(png_bytes)
        self.assertGreaterEqual(width, 760)
        self.assertGreaterEqual(height, 360)


class _FakeMessage:
    def __init__(self, message_id: int = 1, *, fail_photo: bool = False) -> None:
        self.message_id = message_id
        self.fail_photo = fail_photo
        self.photo = []
        self.calls: list[tuple[str, object]] = []

    async def edit_text(self, text, reply_markup=None, parse_mode=None):
        self.calls.append(("edit_text", text))

    async def reply_text(self, text, reply_markup=None, parse_mode=None, do_quote=False):
        self.calls.append(("reply_text", text))
        return _FakeMessage(101)

    async def reply_photo(self, photo, caption=None, reply_markup=None, do_quote=False):
        self.calls.append(("reply_photo", caption))
        if self.fail_photo:
            raise RuntimeError("reply_photo failed")
        return _FakeMessage(100)

    async def delete(self):
        self.calls.append(("delete", self.message_id))

    async def edit_reply_markup(self, reply_markup=None):
        self.calls.append(("edit_reply_markup", reply_markup))


class _FakeQuery:
    def __init__(self, data: str, *, fail_photo: bool = False) -> None:
        self.data = data
        self.message = _FakeMessage(1, fail_photo=fail_photo)
        self.answers: list[tuple[str | None, bool]] = []

    async def answer(self, text=None, show_alert=False):
        self.answers.append((text, show_alert))

    async def edit_message_text(self, text, reply_markup=None, parse_mode=None):
        self.message.calls.append(("query_edit_message_text", text, reply_markup))

    async def edit_message_reply_markup(self, reply_markup=None):
        self.message.calls.append(("query_edit_message_reply_markup", reply_markup))


class VahaduoCallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_single_component_select_all_and_clear_update_state(self) -> None:
        flow = VahaduoFullStore()
        flow.open(10, 1)
        flow.set_mode(10, 1, "single", awaiting="")
        main_menu_store = MainMenuStore()
        main_menu_store.set(10, 1, 1)
        context = SimpleNamespace(
            application=SimpleNamespace(
                bot_data={
                    "main_menu_store": main_menu_store,
                    "vahaduo_store": flow,
                }
            )
        )
        query = _FakeQuery("vahaduo:vahaduo_single_all:panel1")
        update = SimpleNamespace(
            callback_query=query,
            effective_chat=SimpleNamespace(id=10),
            effective_user=SimpleNamespace(id=1),
        )

        await vahaduo_callback_handler(update, context)

        service = context.application.bot_data["dna_lab_vahaduo_service"]
        expected_keys = [str(item["key"]) for item in service.list_vahaduo_single_components("panel1")]
        state = flow.get(10, 1)
        self.assertEqual(state["single_selected"], expected_keys)
        self.assertTrue(expected_keys)
        edit_calls = [call for call in query.message.calls if call[0] == "query_edit_message_text"]
        self.assertTrue(edit_calls)
        selected_labels = [button.text for row in edit_calls[-1][2].inline_keyboard for button in row if button.callback_data and "vahaduo_single_toggle" in button.callback_data]
        self.assertTrue(selected_labels)
        self.assertTrue(all(label.startswith("[x] ") for label in selected_labels))

        clear_query = _FakeQuery("vahaduo:vahaduo_single_clear:panel1")
        clear_update = SimpleNamespace(
            callback_query=clear_query,
            effective_chat=SimpleNamespace(id=10),
            effective_user=SimpleNamespace(id=1),
        )

        await vahaduo_callback_handler(clear_update, context)

        self.assertEqual(flow.get(10, 1)["single_selected"], [])

    async def test_eba_component_select_all_updates_state(self) -> None:
        flow = VahaduoFullStore()
        flow.open(10, 1)
        flow.set_mode(10, 1, "single", awaiting="")
        main_menu_store = MainMenuStore()
        main_menu_store.set(10, 1, 1)
        context = SimpleNamespace(
            application=SimpleNamespace(
                bot_data={
                    "main_menu_store": main_menu_store,
                    "vahaduo_store": flow,
                }
            )
        )
        query = _FakeQuery("vahaduo:vahaduo_single_all:panel2")
        update = SimpleNamespace(
            callback_query=query,
            effective_chat=SimpleNamespace(id=10),
            effective_user=SimpleNamespace(id=1),
        )

        await vahaduo_callback_handler(update, context)

        service = context.application.bot_data["dna_lab_vahaduo_service"]
        expected_keys = [str(item["key"]) for item in service.list_vahaduo_single_components("panel2")]
        self.assertEqual(flow.get(10, 1)["single_selected"], expected_keys)

    async def test_distance_result_photo_send_deletes_picker_after_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            png_path = Path(tmp) / "distance.png"
            png_path.write_bytes(b"png")
            query = _FakeQuery("vahaduo:vmor:1")
            result = SimpleNamespace(png_path=png_path, target_name="Заур")

            sent = await _send_distance_result_photo_from_query(
                query=query,
                state={"source_key": "modern", "source_label": "modern"},
                result=result,
                lang="ru",
            )

            self.assertIsNotNone(sent)
            self.assertEqual([call[0] for call in query.message.calls], ["reply_photo", "delete"])
            self.assertIn("📏 Distance", query.message.calls[0][1])

    async def test_distance_result_photo_failure_keeps_picker_and_shows_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            png_path = Path(tmp) / "distance.png"
            png_path.write_bytes(b"png")
            query = _FakeQuery("vahaduo:vmor:1", fail_photo=True)
            result = SimpleNamespace(png_path=png_path, target_name="Заур")

            sent = await _send_distance_result_photo_from_query(
                query=query,
                state={"source_key": "modern", "source_label": "modern"},
                result=result,
                lang="ru",
            )

            self.assertIsNone(sent)
            self.assertEqual([call[0] for call in query.message.calls], ["reply_photo", "reply_text"])
            self.assertNotIn("delete", [call[0] for call in query.message.calls])
            self.assertIn("Не удалось показать результат", query.message.calls[-1][1])

    async def test_single_result_photo_send_deletes_picker_after_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            png_path = Path(tmp) / "single.png"
            png_path.write_bytes(b"png")
            query = _FakeQuery("vahaduo:vmor:1")
            result = SimpleNamespace(
                png_path=png_path,
                target_name="Заур",
                distance=0.018917,
                groups=[("Maikop", 0.599), ("Yamnaya", 0.335)],
            )

            sent = await _send_single_result_photo_from_query(
                query=query,
                state={"source_key": "single_panel1", "source_label": "Steppe_Russia: Maikop, Yamnaya", "mode": "single"},
                result=result,
                lang="ru",
            )

            self.assertIsNotNone(sent)
            self.assertEqual([call[0] for call in query.message.calls], ["reply_photo", "delete"])
            self.assertTrue(str(query.message.calls[0][1]).startswith("Source: 🐎 Steppe / Russia"))

    async def test_single_result_photo_failure_keeps_picker_and_shows_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            png_path = Path(tmp) / "single.png"
            png_path.write_bytes(b"png")
            query = _FakeQuery("vahaduo:vmor:1", fail_photo=True)
            result = SimpleNamespace(
                png_path=png_path,
                target_name="Заур",
                distance=0.018917,
                groups=[("Maikop", 0.599), ("Yamnaya", 0.335)],
            )

            sent = await _send_single_result_photo_from_query(
                query=query,
                state={"source_key": "single_panel1", "source_label": "Steppe_Russia: Maikop, Yamnaya", "mode": "single"},
                result=result,
                lang="ru",
            )

            self.assertIsNone(sent)
            self.assertEqual([call[0] for call in query.message.calls], ["reply_photo", "reply_text"])
            self.assertNotIn("delete", [call[0] for call in query.message.calls])
            self.assertIn("Не удалось показать результат", query.message.calls[-1][1])

    async def test_multi_result_photo_send_deletes_picker_after_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            png_path = Path(tmp) / "multi.png"
            png_path.write_bytes(b"png")
            query = _FakeQuery("vahaduo:vahaduo_multi_target_done")
            result = SimpleNamespace(
                png_path=png_path,
                panel_name="Steppe_Russia",
                target_count=18,
                average_distance=0.015562,
                sources=173,
                iterations=250,
                elapsed_seconds=2.069,
            )

            sent = await _send_multi_result_photo_from_query(
                query=query,
                state={"source_key": "single_panel1", "source_label": "Steppe_Russia: Maikop, Yamnaya", "mode": "multi"},
                result=result,
                lang="ru",
            )

            self.assertIsNotNone(sent)
            self.assertEqual([call[0] for call in query.message.calls], ["reply_photo", "delete"])
            self.assertTrue(str(query.message.calls[0][1]).startswith("Source: 🐎 Steppe / Russia"))

    async def test_multi_result_photo_failure_keeps_picker_and_shows_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            png_path = Path(tmp) / "multi.png"
            png_path.write_bytes(b"png")
            query = _FakeQuery("vahaduo:vahaduo_multi_target_done", fail_photo=True)
            result = SimpleNamespace(
                png_path=png_path,
                panel_name="Steppe_Russia",
                target_count=18,
                average_distance=0.015562,
                sources=173,
                iterations=250,
                elapsed_seconds=2.069,
            )

            sent = await _send_multi_result_photo_from_query(
                query=query,
                state={"source_key": "single_panel1", "source_label": "Steppe_Russia: Maikop, Yamnaya", "mode": "multi"},
                result=result,
                lang="ru",
            )

            self.assertIsNone(sent)
            self.assertEqual([call[0] for call in query.message.calls], ["reply_photo", "reply_text"])
            self.assertNotIn("delete", [call[0] for call in query.message.calls])
            self.assertIn("Не удалось показать результат", query.message.calls[-1][1])

    async def test_multi_result_back_returns_multi_target_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_path = root / "source.txt"
            source_path.write_text("Maikop,0,0\nYamnaya,0,0\n", encoding="utf-8")
            store = MyDataStore(root / "my_data")
            coordinate = store.save_coordinate(
                1,
                display_name="Standalone G25",
                target_name="Standalone",
                coordinate_type="g25",
                g25_line="Standalone,1,2",
                input_mode="manual",
            )
            flow = VahaduoFullStore()
            flow.open(10, 1)
            flow.set_source(
                10,
                1,
                source_key="single_panel1",
                source_label="Steppe_Russia: Maikop, Yamnaya",
                source_path=source_path,
                source_count=2,
                source_input_mode="preset",
            )
            flow.set_mode(10, 1, "multi", awaiting="")
            flow.set_value(10, 1, "target_list_kind", "other")
            flow.set_value(10, 1, "result_back", "targets")
            flow.set_value(10, 1, "result_back_source", "other")
            flow.set_value(10, 1, "multi_target_selected", [coordinate.asset_id])
            main_menu_store = MainMenuStore()
            context = SimpleNamespace(
                application=SimpleNamespace(
                    bot_data={
                        "main_menu_store": main_menu_store,
                        "my_data_store": store,
                        "vahaduo_store": flow,
                    }
                )
            )
            query = _FakeQuery("vahaduo:vahaduo_result_back")
            query.message.photo = ["photo"]
            update = SimpleNamespace(
                callback_query=query,
                effective_chat=SimpleNamespace(id=10),
                effective_user=SimpleNamespace(id=1),
            )

            await vahaduo_callback_handler(update, context)

            reply_calls = [call for call in query.message.calls if call[0] == "reply_text"]
            self.assertTrue(reply_calls)
            self.assertIn("🧩 Multi", reply_calls[-1][1])
            self.assertIn("Выберите G25-профили.", reply_calls[-1][1])
            self.assertIn("Выбрано: 1 профилей", reply_calls[-1][1])
            self.assertNotIn("Выберите G25-профиль.", reply_calls[-1][1])
            self.assertIn(("query_edit_message_reply_markup", None), query.message.calls)
            self.assertNotIn("delete", [call[0] for call in query.message.calls])

    async def test_result_cancel_keeps_photo_and_clears_keyboard(self) -> None:
        flow = VahaduoFullStore()
        flow.open(10, 1)
        main_menu_store = MainMenuStore()
        main_menu_store.set(10, 1, 1)
        context = SimpleNamespace(
            application=SimpleNamespace(
                bot_data={
                    "main_menu_store": main_menu_store,
                    "vahaduo_store": flow,
                }
            )
        )
        query = _FakeQuery("vahaduo:cancel")
        query.message.photo = ["photo"]
        update = SimpleNamespace(
            callback_query=query,
            effective_chat=SimpleNamespace(id=10),
            effective_user=SimpleNamespace(id=1),
        )

        await vahaduo_callback_handler(update, context)

        self.assertIn(("query_edit_message_reply_markup", None), query.message.calls)
        self.assertNotIn("delete", [call[0] for call in query.message.calls])

    async def test_stable_my_g25_callback_opens_coordinate_card_after_state_loss(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = MyDataStore(Path(tmp) / "my_data")
            coordinate = store.save_coordinate(
                1,
                display_name="Standalone G25",
                target_name="Standalone",
                coordinate_type="g25",
                g25_line="Standalone,1,2",
                input_mode="manual",
            )
            main_menu_store = MainMenuStore()
            main_menu_store.set(10, 1, 1)
            context = SimpleNamespace(
                application=SimpleNamespace(
                    bot_data={
                        "main_menu_store": main_menu_store,
                        "my_data_store": store,
                        "vahaduo_store": VahaduoFullStore(),
                    }
                )
            )
            query = _FakeQuery(f"vahaduo:vmo:{coordinate.asset_id}")
            update = SimpleNamespace(
                callback_query=query,
                effective_chat=SimpleNamespace(id=10),
                effective_user=SimpleNamespace(id=1),
            )

            await vahaduo_callback_handler(update, context)

            edit_calls = [call for call in query.message.calls if call[0] == "query_edit_message_text"]
            self.assertTrue(edit_calls)
            self.assertIn("TARGET: Standalone G25", edit_calls[-1][1])
            self.assertIn("Standalone,1,2", edit_calls[-1][1])

    async def test_legacy_indexed_my_g25_callback_recovers_after_state_loss_and_stale_menu(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = MyDataStore(Path(tmp) / "my_data")
            store.save_coordinate(
                1,
                display_name="Standalone G25",
                target_name="Standalone",
                coordinate_type="g25",
                g25_line="Standalone,1,2",
                input_mode="manual",
            )
            main_menu_store = MainMenuStore()
            main_menu_store.set(10, 1, 999)
            context = SimpleNamespace(
                application=SimpleNamespace(
                    bot_data={
                        "main_menu_store": main_menu_store,
                        "my_data_store": store,
                        "vahaduo_store": VahaduoFullStore(),
                    }
                )
            )
            query = _FakeQuery("vahaduo:vahaduo_target_pick:0")
            update = SimpleNamespace(
                callback_query=query,
                effective_chat=SimpleNamespace(id=10),
                effective_user=SimpleNamespace(id=1),
            )

            await vahaduo_callback_handler(update, context)

            edit_calls = [call for call in query.message.calls if call[0] == "query_edit_message_text"]
            self.assertTrue(edit_calls)
            self.assertIn("TARGET: Standalone G25", edit_calls[-1][1])
            self.assertIn("Standalone,1,2", edit_calls[-1][1])


if __name__ == "__main__":
    unittest.main()
