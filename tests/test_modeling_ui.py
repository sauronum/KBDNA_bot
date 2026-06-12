from __future__ import annotations

import asyncio
import unittest

from telegram import InlineKeyboardMarkup
from telegram.error import BadRequest

from app.features.modeling.menu import build_admixtools2_keyboard, build_modeling_keyboard, modeling_text
from app.features.modeling.source_sets import _parse_source_set_import
from app.features.modeling.ui import show_message


class ModelingUiTests(unittest.TestCase):
    def test_modeling_menu_opens_live_formal_model_tools(self) -> None:
        keyboard = build_modeling_keyboard("ru")
        buttons = [button for row in keyboard.inline_keyboard for button in row]
        labels = [button.text for button in buttons]
        callbacks = [button.callback_data for button in buttons]

        self.assertIn("AdmixLab", modeling_text("ru"))
        self.assertTrue(any("qpAdm classic" in label for label in labels))
        self.assertTrue(any("ADMIXTOOLS 2" in label for label in labels))
        self.assertTrue(any("qpWave classic" in label for label in labels))
        self.assertTrue(any("Source sets" in label for label in labels))
        self.assertTrue(any("Saved models" in label for label in labels))
        self.assertIn("modeling:qpadm", callbacks)
        self.assertIn("modeling:at2", callbacks)
        self.assertIn("modeling:qpwave", callbacks)
        self.assertIn("modeling:source_sets", callbacks)
        self.assertIn("modeling:saved", callbacks)

    def test_admixtools2_menu_groups_backend_tools(self) -> None:
        keyboard = build_admixtools2_keyboard("ru")
        buttons = [button for row in keyboard.inline_keyboard for button in row]
        labels = [button.text for button in buttons]
        callbacks = [button.callback_data for button in buttons]

        self.assertIn("🧪 qpAdm 2", labels)
        self.assertIn("〰️ qpWave 2", labels)
        self.assertIn("🕸 qpGraph 2", labels)
        self.assertIn("📊 f-statistics", labels)
        self.assertIn("📦 f2 cache", labels)
        self.assertIn("modeling:qpadm_at2", callbacks)
        self.assertIn("modeling:at2_qpwave", callbacks)
        self.assertIn("modeling:at2_qpgraph", callbacks)
        self.assertIn("modeling:at2_fstats", callbacks)
        self.assertIn("modeling:at2_f2_cache", callbacks)

    def test_modeling_menu_has_standard_footer(self) -> None:
        keyboard = build_modeling_keyboard("ru")
        footer = keyboard.inline_keyboard[-1]

        self.assertEqual(len(footer), 2)
        self.assertEqual(footer[0].callback_data, "main:root")
        self.assertEqual(footer[1].callback_data, "main:cancel")

    def test_show_message_replaces_non_text_messages_without_traceback(self) -> None:
        class Message:
            def __init__(self) -> None:
                self.reply_sent = False
                self.markup_removed = False

            async def edit_text(self, *args, **kwargs) -> None:
                raise BadRequest("There is no text in the message to edit")

            async def edit_reply_markup(self, *args, **kwargs) -> None:
                self.markup_removed = True

            async def reply_text(self, *args, **kwargs):
                self.reply_sent = True
                return type("Sent", (), {"chat_id": 1, "message_id": 2})()

        message = Message()

        asyncio.run(show_message(message, "text", InlineKeyboardMarkup([]), edit_existing=True))

        self.assertTrue(message.markup_removed)
        self.assertTrue(message.reply_sent)

    def test_source_set_import_accepts_spaced_left_right_format(self) -> None:
        parsed = _parse_source_set_import(
            "\n".join(
                [
                    "Name=testkam",
                    "left = Russia_MLBA_Sintashta.AG,",
                    "Mongolia_LBA_Ulaanzukh_2.AG,",
                    "Russia_Caucasus_Maikop_Novosvobodnaya.AG",
                    "right = Russia_AfontovaGora3_UP.AG:AfontovaGora3.AG,",
                    "Israel_Natufian.AG",
                ]
            )
        )

        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed["name"], "testkam")
        self.assertEqual(
            parsed["sources"],
            [
                "Russia_MLBA_Sintashta.AG",
                "Mongolia_LBA_Ulaanzukh_2.AG",
                "Russia_Caucasus_Maikop_Novosvobodnaya.AG",
            ],
        )
        self.assertEqual(
            parsed["references"],
            ["Russia_AfontovaGora3_UP.AG:AfontovaGora3.AG", "Israel_Natufian.AG"],
        )


if __name__ == "__main__":
    unittest.main()
