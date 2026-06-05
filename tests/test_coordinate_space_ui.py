from __future__ import annotations

import ast
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.main_menu import MainMenuStore
from app.features.coordinate_space.menu import (
    _classify_global_region,
    _coordinate_space_photo_caption,
    _list_global_ready_samples,
    _list_ready_samples_for_source,
    _population_view_group_map,
    _population_view_profiles,
    _project_global_sample_position,
    _project_population_view_position,
    _rank_caucasus_steppe_all_populations,
    _render_global_visualization,
    _render_population_view_visualization,
    _ready_made_g25_profiles,
    build_coordinate_space_keyboard,
    build_configured_space_sample_picker_keyboard,
    build_configured_space_result_keyboard,
    build_caucasus_steppe_all_populations_result_keyboard,
    build_europe_detail_sample_picker_keyboard,
    build_east_eurasia_detail_keyboard,
    build_europe_detail_keyboard,
    build_global_result_keyboard,
    build_global_sample_picker_keyboard,
    build_south_asia_detail_keyboard,
    build_ready_made_spaces_keyboard,
    build_west_eurasia_detail_keyboard,
    build_west_eurasia_sample_picker_keyboard,
    caucasus_detail_text,
    coordinate_space_callback_handler,
    coordinate_space_text,
    ready_made_spaces_text,
)
from app.features.coordinate_space.reports import CoordinateSpaceReportStore
from app.features.my_data.storage import MyDataStore


class CoordinateSpaceUiTests(unittest.TestCase):
    def _back_callback(self, keyboard) -> str:
        for row in keyboard.inline_keyboard:
            for button in row:
                if button.text in {"⬅️ Назад", "Back"}:
                    return button.callback_data
        self.fail("Back button not found")

    def test_root_uses_english_copy(self) -> None:
        text = coordinate_space_text(lang="en")
        keyboard = build_coordinate_space_keyboard(lang="en")
        labels = [button.text for row in keyboard.inline_keyboard for button in row]

        self.assertIn("Ready-made regional spaces", text)
        self.assertIn("for comparing G25 profiles", text)
        self.assertIn("🌍 Global", labels)
        self.assertIn("🧭 West Eurasia", labels)
        self.assertNotIn("Custom space", labels)
        self.assertIn("Back", labels)
        self.assertIn("Cancel", labels)

    def test_coordinate_root_back_returns_to_dna_lab_root(self) -> None:
        keyboard = build_coordinate_space_keyboard()

        self.assertEqual(self._back_callback(keyboard), "main:root")

    def test_global_source_picker_back_returns_to_global_mode(self) -> None:
        keyboard = build_global_sample_picker_keyboard([], source=None)

        self.assertEqual(self._back_callback(keyboard), "coordinate_space:ready_made_global")

    def test_global_target_pickers_back_to_source_picker(self) -> None:
        samples_keyboard = build_global_sample_picker_keyboard([], source="samples")
        other_keyboard = build_global_sample_picker_keyboard([], source="other")

        self.assertEqual(self._back_callback(samples_keyboard), "coordinate_space:picksrc:global_sample")
        self.assertEqual(self._back_callback(other_keyboard), "coordinate_space:picksrc:global_sample")

    def test_global_result_back_after_g25_profile_returns_to_g25_picker(self) -> None:
        keyboard = build_global_result_keyboard("g:coordinate-id")

        self.assertEqual(self._back_callback(keyboard), "coordinate_space:picksrc:global_sample:other")

    def test_caucasus_steppe_source_picker_back_returns_to_mode_screen(self) -> None:
        keyboard = build_configured_space_sample_picker_keyboard("ready_made_caucasus_steppe", [], source=None)

        self.assertEqual(self._back_callback(keyboard), "coordinate_space:ready_made_caucasus_steppe")

    def test_caucasus_steppe_result_back_after_sample_returns_to_samples_picker(self) -> None:
        keyboard = build_configured_space_result_keyboard("ready_made_caucasus_steppe", "sample-id")
        all_populations_keyboard = build_caucasus_steppe_all_populations_result_keyboard("sample-id")

        self.assertEqual(self._back_callback(keyboard), "coordinate_space:picksrc:cs_sample:samples")
        self.assertEqual(self._back_callback(all_populations_keyboard), "coordinate_space:picksrc:csp_sample:samples")

    def test_europe_subregion_source_picker_back_returns_to_subregion_mode(self) -> None:
        keyboard = build_europe_detail_sample_picker_keyboard("east_europe_detail", [], source=None)

        self.assertEqual(self._back_callback(keyboard), "coordinate_space:east_europe_detail")

    def test_ready_made_menu_uses_english_copy(self) -> None:
        text = ready_made_spaces_text(lang="en")
        keyboard = build_ready_made_spaces_keyboard(lang="en")
        labels = [button.text for row in keyboard.inline_keyboard for button in row]

        self.assertIn("Ready-made regional spaces", text)
        self.assertEqual(text.splitlines()[0], "🧭 Coordinates")
        self.assertNotIn("<b>", text)
        self.assertNotIn("</b>", text)
        self.assertIn("🌍 Global", labels)
        self.assertEqual(keyboard.inline_keyboard[0][0].callback_data, "coordinate_space:ready_made_global")
        self.assertEqual(keyboard.inline_keyboard[1][0].callback_data, "coordinate_space:ready_made_west_eurasia")
        self.assertIn("Back", labels)
        self.assertIn("Cancel", labels)

    def test_ready_made_detail_uses_short_mode_prompt(self) -> None:
        self.assertEqual(caucasus_detail_text(lang="en"), "⛰ Caucasus / Steppe\n\nChoose a mode")
        self.assertNotIn("Choose a mode.", caucasus_detail_text(lang="en"))

    def test_ready_made_region_menus_include_all_populations(self) -> None:
        menus = [
            build_west_eurasia_detail_keyboard(lang="en"),
            build_europe_detail_keyboard(lang="en"),
            build_south_asia_detail_keyboard(lang="en"),
            build_east_eurasia_detail_keyboard(lang="en"),
        ]
        for keyboard in menus:
            labels = [button.text for row in keyboard.inline_keyboard for button in row]
            self.assertIn("🧭 Whole region", labels)
            self.assertIn("👥 All populations", labels)

    def test_coordinate_space_sees_my_g25_coordinates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = MyDataStore(Path(tmp))
            coordinate = store.save_coordinate(
                1,
                display_name="Standalone G25",
                target_name="Standalone",
                coordinate_type="g25",
                g25_line="Standalone,1,2",
                input_mode="manual",
            )

            items = _list_global_ready_samples(store, 1)

            self.assertEqual(len(items), 1)
            self.assertEqual(items[0][0].display_name, "Standalone G25")
            self.assertEqual(items[0][1], coordinate)

    def test_coordinate_space_does_not_hide_my_g25_coordinates_after_many_samples(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = MyDataStore(root / "my_data")
            g25_line = Path("app/features/coordinate_space/data/Global25_PCA_modern_pop_averages_scaled.txt").read_text(
                encoding="utf-8-sig"
            ).splitlines()[1]

            for index in range(12):
                raw_path = root / f"raw-{index}.txt"
                raw_path.write_text("raw", encoding="utf-8")
                raw = store.save_raw_file(1, raw_path, original_file_name=raw_path.name, display_name=f"Raw {index}")
                sample = store.save_sample(1, display_name=f"Sample {index}", raw_file_id=raw.asset_id)
                assert sample is not None
                coordinate = store.save_coordinate(
                    1,
                    display_name=f"Sample {index} G25",
                    target_name=f"Sample {index}",
                    coordinate_type="g25",
                    g25_line=g25_line,
                    input_mode="manual",
                )
                store.attach_coordinate_to_sample(1, sample.asset_id, coordinate.asset_id)

            store.save_coordinate(
                1,
                display_name="Standalone G25",
                target_name="Standalone",
                coordinate_type="g25",
                g25_line=g25_line,
                input_mode="manual",
            )

            items = _list_global_ready_samples(store, 1)
            keyboard = build_global_sample_picker_keyboard(items)
            labels = [button.text for row in keyboard.inline_keyboard for button in row]
            other_items = _list_ready_samples_for_source(store, 1, "other")
            other_keyboard = build_global_sample_picker_keyboard(other_items, source="other")
            other_labels = [button.text for row in other_keyboard.inline_keyboard for button in row]

            self.assertIn("🧬 Samples", labels)
            self.assertIn("📍 G25-профили", labels)
            self.assertIn("1. Standalone G25", other_labels)

    def test_coordinate_space_standalone_g25_callbacks_fit_telegram_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = MyDataStore(Path(tmp))
            store.save_coordinate(
                1,
                display_name="Standalone G25",
                target_name="Standalone",
                coordinate_type="g25",
                g25_line="Standalone,1,2",
                input_mode="manual",
            )

            items = _list_global_ready_samples(store, 1)
            other_items = _list_ready_samples_for_source(store, 1, "other")
            keyboards = [
                build_global_sample_picker_keyboard(items),
                build_global_sample_picker_keyboard(other_items, source="other"),
                build_west_eurasia_sample_picker_keyboard(items),
                build_west_eurasia_sample_picker_keyboard(other_items, source="other"),
                build_configured_space_sample_picker_keyboard("ready_made_europe", items),
                build_configured_space_sample_picker_keyboard("ready_made_europe", other_items, source="other"),
                build_configured_space_sample_picker_keyboard("ready_made_caucasus_steppe", items),
                build_configured_space_sample_picker_keyboard("ready_made_south_asia", items),
                build_configured_space_sample_picker_keyboard("ready_made_east_eurasia", items),
            ]

            callbacks = [
                button.callback_data
                for keyboard in keyboards
                for row in keyboard.inline_keyboard
                for button in row
                if button.callback_data
            ]

            self.assertTrue(callbacks)
            self.assertTrue(all(len(callback.encode("utf-8")) <= 64 for callback in callbacks))

    def test_coordinate_space_handler_has_no_missing_show_helpers(self) -> None:
        source = Path("app/features/coordinate_space/menu.py").read_text(encoding="utf-8-sig")
        module = ast.parse(source)
        defined = {
            node.name
            for node in module.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        }
        used_show = {
            node.id
            for node in ast.walk(module)
            if isinstance(node, ast.Name) and node.id.startswith("show_")
        }

        self.assertEqual(sorted(used_show - defined), [])

    def test_ready_made_visualizations_render_png(self) -> None:
        g25_line = Path("app/features/coordinate_space/data/Global25_PCA_modern_pop_averages_scaled.txt").read_text(
            encoding="utf-8-sig"
        ).splitlines()[1]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            global_path = root / "global.png"
            population_path = root / "population.png"

            _render_global_visualization(
                global_path,
                sample_point=_project_global_sample_position(g25_line),
                g25_line=g25_line,
                summary_lines=("Sample: Smoke", f"Closest region: {_classify_global_region(g25_line)}"),
            )
            _render_population_view_visualization(
                "ready_made_caucasus_steppe_all_populations",
                population_path,
                sample_point=_project_population_view_position("ready_made_caucasus_steppe_all_populations", g25_line),
                g25_line=g25_line,
                summary_lines=("Sample: Smoke", "Top populations: " + ", ".join(_rank_caucasus_steppe_all_populations(g25_line))),
            )

            for output_path in (global_path, population_path):
                self.assertEqual(output_path.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
                self.assertGreater(output_path.stat().st_size, 20_000)

    def test_photo_caption_uses_clean_region_labels_without_top_list(self) -> None:
        g25_line = Path("app/features/coordinate_space/data/Global25_PCA_modern_pop_averages_scaled.txt").read_text(
            encoding="utf-8-sig"
        ).splitlines()[1]
        sample = SimpleNamespace(display_name="Sample One")

        caption = _coordinate_space_photo_caption(sample, g25_line, _ready_made_g25_profiles()["global"], space_title="Global")

        lines = caption.splitlines()
        self.assertEqual(lines[0], "🌍 Global")
        self.assertEqual(lines[2], "G25-профиль: Sample One")
        self.assertTrue(lines[3].startswith("Ближайшая зона: "))
        self.assertTrue(lines[4].startswith("Дистанция: "))
        self.assertTrue(lines[5].startswith("Отрыв от #2: "))
        self.assertNotIn("Top:", caption)

    def test_photo_caption_uses_population_labels_and_region_when_available(self) -> None:
        g25_line = Path("app/features/coordinate_space/data/Global25_PCA_modern_pop_averages_scaled.txt").read_text(
            encoding="utf-8-sig"
        ).splitlines()[1]
        sample = SimpleNamespace(display_name="Sample One")
        view_action = "ready_made_caucasus_steppe_all_populations"

        caption = _coordinate_space_photo_caption(
            sample,
            g25_line,
            _population_view_profiles()[view_action],
            space_title="Caucasus / Steppe",
            mode="population",
            group_map=_population_view_group_map(view_action),
        )

        self.assertIn("⛰ Caucasus / Steppe", caption)
        self.assertIn("Ближайшая популяция: ", caption)
        self.assertIn("Регион: ", caption)
        self.assertNotIn("Top:", caption)


class _FakeMessage:
    photo = []

    def __init__(self, message_id: int = 1) -> None:
        self.message_id = message_id
        self.calls: list[tuple[str, object]] = []

    async def edit_text(self, text, reply_markup=None, parse_mode=None):
        self.calls.append(("edit_text", text))

    async def reply_text(self, text, reply_markup=None, parse_mode=None, do_quote=False):
        self.calls.append(("reply_text", text))
        return _FakeMessage(99)

    async def reply_photo(self, photo, reply_markup=None, do_quote=False, caption=None):
        self.calls.append(("reply_photo", caption))
        return _FakeMessage(98)

    async def edit_reply_markup(self, reply_markup=None):
        self.calls.append(("edit_reply_markup", reply_markup))


class _FakeQuery:
    def __init__(self, data: str) -> None:
        self.data = data
        self.message = _FakeMessage(1)
        self.answers: list[tuple[str | None, bool]] = []

    async def answer(self, text=None, show_alert=False):
        self.answers.append((text, show_alert))

    async def edit_message_text(self, text, reply_markup=None, parse_mode=None):
        self.message.calls.append(("query_edit_message_text", text))

    async def edit_message_caption(self, caption=None, reply_markup=None):
        self.message.calls.append(("query_edit_message_caption", caption))

    async def edit_message_reply_markup(self, reply_markup=None):
        self.message.calls.append(("query_edit_message_reply_markup", reply_markup))


class CoordinateSpaceCallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_region_menu_callbacks_do_not_raise(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            context = SimpleNamespace(
                application=SimpleNamespace(
                    bot_data={
                        "my_data_store": MyDataStore(Path(tmp) / "my_data"),
                        "main_menu_store": MainMenuStore(),
                    }
                )
            )
            callbacks = [
                "coordinate_space:ready_made_global",
                "coordinate_space:ready_made_west_eurasia",
                "coordinate_space:ready_made_europe",
                "coordinate_space:ready_made_caucasus_steppe",
                "coordinate_space:ready_made_south_asia",
                "coordinate_space:ready_made_east_eurasia",
                "coordinate_space:north_caucasus_detail",
                "coordinate_space:picksrc:global_sample:other",
            ]

            for callback in callbacks:
                context.application.bot_data["main_menu_store"].set(10, 1, 1)
                query = _FakeQuery(callback)
                update = SimpleNamespace(
                    callback_query=query,
                    effective_chat=SimpleNamespace(id=10),
                    effective_user=SimpleNamespace(id=1),
                )

                await coordinate_space_callback_handler(update, context)

                self.assertTrue(query.answers or query.message.calls)

    async def test_save_callback_writes_coordinate_space_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = MyDataStore(root / "my_data")
            raw_path = root / "raw.txt"
            raw_path.write_text("raw", encoding="utf-8")
            raw = store.save_raw_file(1, raw_path, original_file_name="raw.txt", display_name="Raw")
            sample = store.save_sample(1, display_name="Sample", raw_file_id=raw.asset_id)
            assert sample is not None
            g25_line = Path("app/features/coordinate_space/data/Global25_PCA_modern_pop_averages_scaled.txt").read_text(
                encoding="utf-8-sig"
            ).splitlines()[1]
            coordinate = store.save_coordinate(
                1,
                display_name="Sample G25",
                target_name="Sample",
                coordinate_type="g25",
                g25_line=g25_line,
                input_mode="manual",
            )
            store.attach_coordinate_to_sample(1, sample.asset_id, coordinate.asset_id)
            report_store = CoordinateSpaceReportStore(root / "coordinate_space" / "reports")
            context = SimpleNamespace(
                application=SimpleNamespace(
                    bot_data={
                        "my_data_store": store,
                        "coordinate_space_report_store": report_store,
                        "main_menu_store": MainMenuStore(),
                    }
                )
            )
            context.application.bot_data["main_menu_store"].set(10, 1, 1)
            query = _FakeQuery(f"coordinate_space:global_save:{sample.asset_id}")
            update = SimpleNamespace(
                callback_query=query,
                effective_chat=SimpleNamespace(id=10),
                effective_user=SimpleNamespace(id=1),
            )

            await coordinate_space_callback_handler(update, context)

            reports = report_store.list_results(1, sample.asset_id)
            self.assertEqual(len(reports), 1)
            self.assertEqual(reports[0].title, "Global")
            self.assertIn("🌍 Global", reports[0].caption)
            self.assertTrue(reports[0].image_path)
            image_path = report_store.resolve_image_path(reports[0])
            self.assertIsNotNone(image_path)
            assert image_path is not None
            self.assertTrue(image_path.exists())
            self.assertIn(("✅ Отчёт сохранён в My DNA.", True), query.answers)


if __name__ == "__main__":
    unittest.main()
