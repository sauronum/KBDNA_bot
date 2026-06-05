from __future__ import annotations

import asyncio
from types import SimpleNamespace
import unittest

from ui import common as bot_ui
from handlers import sozluk as sozluk_handlers


def _inline_text_rows(markup) -> list[list[str]]:
    return [[button.text for button in row] for row in markup.inline_keyboard]


def _inline_callback_rows(markup) -> list[list[str]]:
    return [[button.callback_data for button in row] for row in markup.inline_keyboard]


class SozlukHandlerStateTests(unittest.TestCase):
    def test_pending_state_is_chat_scoped_and_cleared_on_pop(self) -> None:
        context = SimpleNamespace(user_data={}, application=SimpleNamespace(bot_data={}))

        sozluk_handlers.set_sozluk_pending(context, 10, direction=2)

        self.assertIsNone(sozluk_handlers.pop_sozluk_pending(context, 11))
        self.assertEqual(sozluk_handlers.pop_sozluk_pending(context, 10), 2)
        self.assertIsNone(sozluk_handlers.pop_sozluk_pending(context, 10))

    def test_legacy_pending_direction_is_supported(self) -> None:
        context = SimpleNamespace(user_data={"sozluk_pending_direction": "1"}, application=SimpleNamespace(bot_data={}))

        self.assertEqual(sozluk_handlers.pop_sozluk_pending(context, 10), 1)
        self.assertNotIn("sozluk_pending_direction", context.user_data)

    def test_prompt_keyboard_is_hidden_in_private_chat(self) -> None:
        private_update = SimpleNamespace(effective_chat=SimpleNamespace(type="private"))
        group_update = SimpleNamespace(effective_chat=SimpleNamespace(type="group"))

        self.assertFalse(sozluk_handlers.should_show_sozluk_prompt_keyboard(private_update))
        self.assertTrue(sozluk_handlers.should_show_sozluk_prompt_keyboard(group_update))
        self.assertTrue(sozluk_handlers.should_show_sozluk_prompt_keyboard(None))

    def test_inline_sozluk_menu_keeps_navigation_even_in_private_chat(self) -> None:
        class FakeMessage:
            chat_id = 10

            def __init__(self) -> None:
                self.reply_markup = None

            async def edit_text(self, _text, *, parse_mode=None, reply_markup=None) -> None:
                self.reply_markup = reply_markup

        message = FakeMessage()
        context = SimpleNamespace(user_data={}, application=SimpleNamespace(bot_data={}))
        update = SimpleNamespace(effective_chat=SimpleNamespace(type="private"))

        asyncio.run(
            sozluk_handlers.open_sozluk_inline_menu(
                message,
                update,
                context,
                menu_callback_prefix="menu",
                back_action="more",
            )
        )

        self.assertEqual(context.user_data["sozluk_pending"], {"chat_id": 10, "direction": 0})
        self.assertEqual(_inline_callback_rows(message.reply_markup), [["menu:more", "menu:cancel"]])


class LookupKeyboardTests(unittest.TestCase):
    def test_lookup_suggestions_keyboard_uses_lookup_callbacks(self) -> None:
        keyboard = bot_ui.build_lookup_suggestions_keyboard("lookup", ["Абаев", "Аба"])

        self.assertEqual(_inline_text_rows(keyboard), [["Абаев"], ["Аба"]])
        self.assertEqual(_inline_callback_rows(keyboard), [["lookup:s:0"], ["lookup:s:1"]])

    def test_lookup_result_keyboard_adds_show_all_for_multiple_records(self) -> None:
        keyboard = bot_ui.build_lookup_result_keyboard(
            "lookup",
            [
                {"button_label": "G2a1 · 1"},
                {"button_label": "R1a · 1"},
            ],
        )

        self.assertEqual(_inline_text_rows(keyboard), [["G2a1 · 1"], ["R1a · 1"], ["Показать все"]])
        self.assertEqual(_inline_callback_rows(keyboard)[-1], ["lookup:a:all"])


if __name__ == "__main__":
    unittest.main()
