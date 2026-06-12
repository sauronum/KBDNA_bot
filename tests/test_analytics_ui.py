from __future__ import annotations

import unittest

from ui import analytics as analytics_ui


def _inline_text_rows(markup) -> list[list[str]]:
    return [[button.text for button in row] for row in markup.inline_keyboard]


def _inline_callback_rows(markup) -> list[list[str]]:
    return [[button.callback_data for button in row] for row in markup.inline_keyboard]


class AnalyticsUiTests(unittest.TestCase):
    def test_root_keyboard_can_return_to_main_menu(self) -> None:
        keyboard = analytics_ui.build_haplo_root_keyboard("haplo", "menu", include_back=True)

        self.assertEqual(_inline_text_rows(keyboard), [["🧬 Y-ДНК"], ["🧬 mtDNA"], ["Назад", "Отмена"]])
        self.assertEqual(_inline_callback_rows(keyboard)[-1], ["menu:root", "haplo:cancel"])

    def test_mtdna_groups_keyboard_uses_two_columns_and_footer(self) -> None:
        groups = [
            {"label": "U", "count": 40},
            {"label": "H", "count": 12},
            {"label": "T", "count": 11},
        ]

        keyboard = analytics_ui.build_mtdna_navigator_groups_keyboard("haplo", groups)

        self.assertEqual(_inline_text_rows(keyboard)[0], ["U · 40", "H · 12"])
        self.assertEqual(_inline_text_rows(keyboard)[1], ["T · 11"])
        self.assertEqual(_inline_callback_rows(keyboard)[-1], ["haplo:mtdna", "haplo:cancel"])

    def test_untested_group_text_counts_primary_and_confirm_names(self) -> None:
        group = {
            "label": "Къарачай",
            "subtitle": "Карачаевские роды",
            "names": ["Род1", "Род2"],
            "confirm_names": ["Род3"],
        }

        text = analytics_ui.format_untested_surname_group(group)

        self.assertIn("Всего: 3", text)
        self.assertIn("Род1, Род2", text)
        self.assertIn("Требуют подтверждения", text)

    def test_mtdna_subclade_description_allows_deeper_prefixes(self) -> None:
        description = analytics_ui.mtdna_subclade_description("U1B2D1")

        self.assertIn("U1b2d", description)

    def test_mtdna_entries_text_renders_links_as_separate_block(self) -> None:
        text = analytics_ui.format_mtdna_entries_text(
            "B",
            "B4B1A3A",
            [
                {"name": "YF02397", "links": [{"label": "YFull", "url": "https://www.yfull.com/mtree/B4b1a3a/"}]},
                {"name": "YF95220", "links": []},
            ],
        )

        self.assertIn("1. YF02397", text)
        self.assertIn("2. YF95220", text)
        self.assertIn("Ссылки:", text)
        self.assertIn("YFull", text)


if __name__ == "__main__":
    unittest.main()
