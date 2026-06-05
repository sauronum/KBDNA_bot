from __future__ import annotations

import unittest

from app.features.modeling.menu import build_modeling_keyboard, modeling_text


class ModelingUiTests(unittest.TestCase):
    def test_modeling_menu_opens_live_formal_model_tools(self) -> None:
        keyboard = build_modeling_keyboard("ru")
        buttons = [button for row in keyboard.inline_keyboard for button in row]
        labels = [button.text for button in buttons]
        callbacks = [button.callback_data for button in buttons]

        self.assertIn("AdmixLab", modeling_text("ru"))
        self.assertTrue(any("qpAdm classic" in label for label in labels))
        self.assertTrue(any("qpWave" in label for label in labels))
        self.assertTrue(any("Source sets" in label for label in labels))
        self.assertTrue(any("Saved models" in label for label in labels))
        self.assertIn("modeling:qpadm", callbacks)
        self.assertIn("modeling:qpwave", callbacks)
        self.assertIn("modeling:source_sets", callbacks)
        self.assertIn("modeling:saved", callbacks)

    def test_modeling_menu_has_standard_footer(self) -> None:
        keyboard = build_modeling_keyboard("ru")
        footer = keyboard.inline_keyboard[-1]

        self.assertEqual(len(footer), 2)
        self.assertEqual(footer[0].callback_data, "main:root")
        self.assertEqual(footer[1].callback_data, "main:cancel")


if __name__ == "__main__":
    unittest.main()
