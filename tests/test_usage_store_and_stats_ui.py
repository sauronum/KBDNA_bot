from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from ui import stats as stats_ui
from stores.usage import UsageStore


def _update(user_id: int = 100, username: str = "tester") -> SimpleNamespace:
    return SimpleNamespace(
        effective_user=SimpleNamespace(id=user_id, username=username, first_name="Test", last_name="User"),
        effective_chat=SimpleNamespace(id=200, type="private"),
    )


def _png_size(png_bytes: bytes) -> tuple[int, int]:
    return (
        int.from_bytes(png_bytes[16:20], "big"),
        int.from_bytes(png_bytes[20:24], "big"),
    )


class UsageStoreModuleTests(unittest.TestCase):
    def test_excluded_username_is_not_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = UsageStore(Path(tmp_dir) / "usage.sqlite3")

            store.record_lookup(_update(username="jb_cc"), "Эркенов", success=True)

            summary = store.get_summary()

        self.assertEqual(summary["total"], 0)
        self.assertEqual(summary["lookup_total"], 0)

    def test_lookup_top_merges_case_variants(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = UsageStore(Path(tmp_dir) / "usage.sqlite3")

            store.record_lookup(_update(), "эркенов", success=True)
            store.record_lookup(_update(), "ЭРКЕНОВ", success=True)

            summary = store.get_summary()

        self.assertEqual(summary["lookup_total"], 2)
        self.assertEqual(summary["top_queries"][0], ("Эркенов", 2))

    def test_dna_lab_summary_tracks_sections_and_actions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = UsageStore(Path(tmp_dir) / "usage.sqlite3")

            store.record_dna_lab(_update(101), "my_data", action="samples_view")
            store.record_dna_lab(_update(109), "my_data", action="sample_create")
            store.record_dna_lab(_update(110), "my_data", action="coordinate_add")
            store.record_dna_lab(_update(104), "quick_g25", action="open")
            store.record_dna_lab(_update(108), "main", action="open")
            store.record_dna_lab(_update(105), "settings", action="root")
            store.record_dna_lab(_update(106), "reports", action="root")
            store.record_dna_lab(_update(111), "coordinate_space", action="root")
            store.record_dna_lab(_update(112), "coordinate_space", action="global_sample")
            store.record_dna_lab(_update(113), "traits", action="s")
            store.record_dna_lab(_update(114), "traits", action="u")
            store.record_dna_lab(_update(102), "vahaduo", action="vahaduo_run", success=False)
            store.record_g25(_update(107), command="g25", input_mode="raw-file", success=True)
            store.record_g25(_update(103), command="vahaduo_single", input_mode="g25-text", success=True)

            summary = store.get_summary()

        self.assertEqual(summary["dna_lab_total"], 4)
        self.assertEqual(summary["dna_lab_success"], 4)
        self.assertEqual(summary["dna_lab_unique_users"], 4)
        self.assertIn(("my_data", 2), summary["dna_lab_sections"])
        self.assertIn(("coordinate_space", 1), summary["dna_lab_sections"])
        self.assertIn(("traits", 1), summary["dna_lab_sections"])
        self.assertIn(("my_data", "sample_create", 1), summary["dna_lab_top_actions"])
        self.assertIn(("my_data", "coordinate_add", 1), summary["dna_lab_top_actions"])
        self.assertIn(("coordinate_space", "global_sample", 1), summary["dna_lab_top_actions"])
        self.assertIn(("traits", "u", 1), summary["dna_lab_top_actions"])
        self.assertNotIn(("my_data", "samples_view", 1), summary["dna_lab_top_actions"])
        self.assertNotIn(("vahaduo", "vahaduo_run", 1), summary["dna_lab_top_actions"])
        self.assertIn(("my_data", 2, 2, 2, 2, 2), summary["dna_lab_section_rows"])
        self.assertIn(("coordinate_space", 1, 1, 1, 1, 1), summary["dna_lab_section_rows"])
        self.assertIn(("traits", 1, 1, 1, 1, 1), summary["dna_lab_section_rows"])
        self.assertIn(("vahaduo", 1, 1, 1, 1, 1), summary["dna_lab_section_rows"])
        self.assertFalse(any(row[0] in {"main", "quick_g25", "settings", "reports"} for row in summary["dna_lab_section_rows"]))
        self.assertEqual(sum(int(row[1]) for row in summary["summary_section_rows"]), summary["total"])


class StatsUiTests(unittest.TestCase):
    def test_stats_summary_text_has_one_line_per_section(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = UsageStore(Path(tmp_dir) / "usage.sqlite3")
            store.record_lookup(_update(101), "Эркенов", success=True)
            store.record_dna_lab(_update(107), "my_data", action="samples_view")
            store.record_dna_lab(_update(112), "my_data", action="sample_create")
            store.record_dna_lab(_update(108), "quick_g25", action="open")
            store.record_dna_lab(_update(111), "main", action="open")
            store.record_dna_lab(_update(109), "settings", action="root")
            store.record_dna_lab(_update(110), "reports", action="root")
            store.record_dna_lab(_update(113), "coordinate_space", action="root")
            store.record_dna_lab(_update(114), "coordinate_space", action="global_sample")
            store.record_dna_lab(_update(115), "traits", action="s")
            store.record_dna_lab(_update(116), "traits", action="u")
            store.record_analytics(_update(102), "haplo_families")
            store.record_ystr(_update(103), command="nearest")
            store.record_g25(_update(104), command="panel", input_mode="text", success=True)
            store.record_g25(_update(106), command="vahaduo_single", input_mode="g25-text", success=True)
            store.record_sozluk(_update(105), "къол", success=True)

            text = stats_ui.build_stats_summary_text(store)

        self.assertIn("Статистика", text)
        self.assertIn("Всего событий: 8", text)
        self.assertIn("За 30 дней: 8", text)
        self.assertIn("Успешность:", text)
        self.assertIn("Раздел", text)
        self.assertIn("Фамилии", text)
        self.assertLess(text.index("Фамилии"), text.index("Аналитика"))
        self.assertLess(text.index("Аналитика"), text.index("My DNA"))
        self.assertIn("My DNA", text)
        self.assertLess(text.index("Coordinate spaces"), text.index("Vahaduo Lab"))
        self.assertIn("Vahaduo Lab", text)
        self.assertNotIn("Главное меню", text)
        self.assertNotIn("Quick G25", text)
        self.assertNotIn("Settings", text)
        self.assertNotIn("Reports", text)
        self.assertIn("Аналитика", text)
        self.assertNotIn("Y-STR", text)
        self.assertNotIn("PCA", text)
        self.assertIn("Словарь", text)
        self.assertIn("<pre>", text)
        self.assertIn("Подробно по разделам:", text)

    def test_analytics_stats_text_includes_ystr_inside_ydna(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = UsageStore(Path(tmp_dir) / "usage.sqlite3")
            store.record_analytics(_update(101), "haplo_families")
            store.record_ystr(_update(102), command="nearest")

            text = stats_ui.build_analytics_stats_text(store)

        self.assertIn("Всего: 2", text)
        self.assertIn("STR-маркеры: 1", text)
        self.assertIn("Y-STR · найти ближайших: 1", text)

    def test_dna_lab_stats_text_includes_sections_and_actions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = UsageStore(Path(tmp_dir) / "usage.sqlite3")
            store.record_dna_lab(_update(101), "my_data", action="samples_view")
            store.record_dna_lab(_update(108), "my_data", action="sample_create")
            store.record_dna_lab(_update(109), "my_data", action="coordinate_add")
            store.record_dna_lab(_update(104), "quick_g25", action="open")
            store.record_dna_lab(_update(105), "settings", action="root")
            store.record_dna_lab(_update(106), "reports", action="root")
            store.record_dna_lab(_update(110), "coordinate_space", action="global_sample")
            store.record_dna_lab(_update(111), "traits", action="u")
            store.record_dna_lab(_update(102), "vahaduo", action="vahaduo_run", success=False)
            store.record_g25(_update(107), command="g25", input_mode="raw-file", success=True)
            store.record_g25(_update(103), command="vahaduo_single", input_mode="g25-text", success=True)

            text = stats_ui.build_dna_lab_stats_text(store)

        self.assertIn("DNA Lab", text)
        self.assertIn("My DNA - 2", text)
        self.assertIn("Coordinate spaces - 1", text)
        self.assertIn("Vahaduo Lab - 1", text)
        self.assertIn("Traits - 1", text)
        self.assertNotIn("Quick G25", text)
        self.assertNotIn("Settings", text)
        self.assertNotIn("Reports", text)
        self.assertIn("Получение G25: 0", text)
        self.assertIn("Всего Vahaduo: 1", text)
        self.assertIn("Single: 1", text)
        self.assertIn("My DNA · Sample сохранен - 1", text)
        self.assertIn("My DNA · Координаты сохранены - 1", text)
        self.assertNotIn("Просмотр samples", text)
        self.assertNotIn("Vahaduo Lab · Расчет - 1", text)

    def test_quality_stats_text_includes_failures_and_top_users(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = UsageStore(Path(tmp_dir) / "usage.sqlite3")
            store.record_lookup(_update(101, username="alpha"), "Эркенов", success=True)
            store.record_dna_lab(_update(102, username="beta"), "my_data", action="coordinate_add", success=False)

            text = stats_ui.build_quality_stats_text(store)

        self.assertIn("Качество и нагрузка", text)
        self.assertIn("Всего событий: 2", text)
        self.assertIn("Ошибок: 1", text)
        self.assertIn("DNA Lab · My DNA - 1", text)
        self.assertIn("alpha", text)

    def test_lookup_stats_text_uses_compact_top_for_non_private_views(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = UsageStore(Path(tmp_dir) / "usage.sqlite3")
            store.record_lookup(_update(), "эркенов", success=True)

            text = stats_ui.build_lookup_stats_text(store, is_private=False, show_details=True)

        self.assertIn("Статистика по фамилиям", text)
        self.assertIn("1. Эркенов - 1", text)
        self.assertNotIn("Всего запросов", text)

    def test_lookup_stats_text_has_only_top_25_rows_for_private_views(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = UsageStore(Path(tmp_dir) / "usage.sqlite3")
            for index in range(30):
                store.record_lookup(_update(1000 + index), f"name{index:02d}", success=True)

            text = stats_ui.build_lookup_stats_text(store, is_private=True, show_details=True)

        numbered_rows = [
            line
            for line in text.splitlines()
            if line[:1].isdigit() and ". " in line
        ]
        self.assertEqual(len(numbered_rows), 25)
        self.assertIn("25. Name24 - 1", text)
        self.assertNotIn("26. Name25 - 1", text)
        self.assertNotIn("Всего запросов", text)
        self.assertNotIn("Успешных", text)
        self.assertNotIn("За сегодня", text)
        self.assertNotIn("За 7 дней", text)
        self.assertNotIn("Уникальных пользователей", text)
        self.assertNotIn("Топ фамилий", text)

    def test_stats_chart_payload_returns_png_and_filename(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = UsageStore(Path(tmp_dir) / "usage.sqlite3")
            store.record_lookup(_update(), "эркенов", success=True)
            store.record_dna_lab(_update(), "my_data", action="samples_view")

            png_bytes, filename = stats_ui.build_stats_chart_payload(store, "summary")

        self.assertEqual(filename, "stats_summary_30d.png")
        self.assertTrue(png_bytes.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertEqual(_png_size(png_bytes), (1080, 460))

    def test_stats_visual_payload_returns_single_summary_image(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = UsageStore(Path(tmp_dir) / "usage.sqlite3")
            store.record_lookup(_update(), "СЌСЂРєРµРЅРѕРІ", success=True)
            store.record_analytics(_update(101), "haplo_families")
            store.record_dna_lab(_update(102), "my_data", action="sample_create")
            store.record_dna_lab(_update(103), "coordinate_space", action="global_sample")
            store.record_g25(_update(104), command="vahaduo_single", input_mode="g25-text", success=True)
            store.record_sozluk(_update(105), "РєСЉРѕР»", success=False)

            png_bytes, filename = stats_ui.build_stats_visual_payload(store)

        width, height = _png_size(png_bytes)
        self.assertEqual(filename, "stats_summary_full_30d.png")
        self.assertTrue(png_bytes.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertEqual(width, 1080)
        self.assertGreaterEqual(height, 1240)

    def test_stats_chart_payload_rejects_section_charts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = UsageStore(Path(tmp_dir) / "usage.sqlite3")
            store.record_dna_lab(_update(), "my_data", action="samples_view")

            with self.assertRaises(ValueError):
                stats_ui.build_stats_chart_payload(store, "dna_lab")


if __name__ == "__main__":
    unittest.main()
