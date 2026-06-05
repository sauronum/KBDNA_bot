from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ui import sozluk as sozluk_ui
from features.sozluk import SozlukClient, filter_exact_sozluk_items


class SozlukClientTests(unittest.TestCase):
    def test_plain_text_from_html_keeps_line_breaks_and_decodes_entities(self) -> None:
        text = SozlukClient.plain_text_from_html("карача<br>тест&nbsp;<b>слово</b>")

        self.assertEqual(text, "карача\nтест слово")

    def test_exact_filter_is_case_and_space_insensitive(self) -> None:
        items = [
            {"word": " Кривой ", "desc": "точное", "direction": 1},
            {"word": "кривизна", "desc": "не точное", "direction": 1},
        ]

        exact = filter_exact_sozluk_items("кривой", items)

        self.assertEqual([item["word"] for item in exact], [" Кривой "])

    def test_lookup_can_return_cached_payload_without_network(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            client = SozlukClient(Path(tmp_dir) / "sozluk.sqlite3", api_base="https://example.invalid")
            payload = [{"id": "1", "word": "КРИВОЙ", "desc": "desc", "direction": 1}]
            client._store_cached("кривой", 1, payload)

            result = client.lookup("Кривой", 1)

        self.assertEqual(result, payload)


class SozlukUiTests(unittest.TestCase):
    def test_format_result_contains_direction_source_and_no_action_buttons(self) -> None:
        text = sozluk_ui.format_sozluk_results(
            "кривой",
            [{"word": "КРИВОЙ", "desc": "-ая, -ое ...", "direction": 1}],
        )

        self.assertIn("<b>КРИВОЙ</b>", text)
        self.assertIn("Русский → карачаево-балкарский", text)
        self.assertIn("Русско-карачаево-балкарский словарь", text)
        self.assertNotIn("Новый поиск", text)

    def test_prompt_keyboard_uses_menu_prefix_for_back_and_cancel(self) -> None:
        keyboard = sozluk_ui.build_sozluk_prompt_keyboard("menu")
        callbacks = [[button.callback_data for button in row] for row in keyboard.inline_keyboard]

        self.assertEqual(callbacks, [["menu:root", "menu:cancel"]])

    def test_prompt_keyboard_can_return_to_more_menu(self) -> None:
        keyboard = sozluk_ui.build_sozluk_prompt_keyboard("menu", back_action="more")
        callbacks = [[button.callback_data for button in row] for row in keyboard.inline_keyboard]

        self.assertEqual(callbacks, [["menu:more", "menu:cancel"]])


if __name__ == "__main__":
    unittest.main()
