from __future__ import annotations

import unittest

from app.features.modeling.qpadm_classic import _format_messages, _format_preflight


class QpadmClassicFormattingTests(unittest.TestCase):
    def test_format_messages_limits_long_backend_lists(self) -> None:
        messages = [{"message": f"warning {index}"} for index in range(6)]

        lines = _format_messages(messages, limit=3, lang="en")

        self.assertEqual(len(lines), 4)
        self.assertIn("warning 0", lines[0])
        self.assertIn("warning 2", lines[2])
        self.assertIn("and 3 more", lines[3])
        self.assertNotIn("warning 3", "\n".join(lines))

    def test_preflight_limits_warnings_and_errors(self) -> None:
        payload = {
            "status": "ok",
            "engine_status": "ready",
            "can_run": True,
            "warnings": [{"message": f"warning {index}"} for index in range(6)],
            "errors": [{"message": f"error {index}"} for index in range(5)],
        }

        text, can_run = _format_preflight(payload, elapsed_seconds=1.25, lang="en")

        self.assertTrue(can_run)
        self.assertIn("warning 0", text)
        self.assertIn("warning 3", text)
        self.assertIn("and 2 more", text)
        self.assertIn("error 0", text)
        self.assertIn("error 3", text)
        self.assertIn("and 1 more", text)
        self.assertNotIn("warning 4", text)
        self.assertNotIn("error 4", text)


if __name__ == "__main__":
    unittest.main()
