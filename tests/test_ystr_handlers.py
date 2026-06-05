from __future__ import annotations

from types import SimpleNamespace
import unittest

from handlers import ystr as ystr_handlers


class YstrHandlerStateTests(unittest.TestCase):
    def test_pending_state_is_chat_scoped_and_cleared_on_pop(self) -> None:
        context = SimpleNamespace(user_data={}, application=SimpleNamespace(bot_data={}))

        ystr_handlers.set_ystr_pending(context, 10, "nearest_name")

        self.assertIsNone(ystr_handlers.pop_ystr_pending(context, 11))
        self.assertEqual(ystr_handlers.pop_ystr_pending(context, 10), "nearest_name")
        self.assertIsNone(ystr_handlers.pop_ystr_pending(context, 10))

    def test_clear_ystr_pending_removes_all_flow_state(self) -> None:
        context = SimpleNamespace(
            user_data={
                "ystr_pending": {},
                "ystr_candidates": [1],
                "ystr_data_candidates": [2],
                "ystr_data_back_action": "datacandidates",
                "ystr_compare": {"left": 1},
                "ystr_uploaded_profile": {"marker_count": 12},
                "ystr_upload_compare_candidates": [3],
                "other": "kept",
            },
            application=SimpleNamespace(bot_data={}),
        )

        ystr_handlers.clear_ystr_pending(context)

        self.assertEqual(context.user_data, {"other": "kept"})

    def test_data_back_action_falls_back_to_candidates_when_available(self) -> None:
        context = SimpleNamespace(user_data={"ystr_data_candidates": [1, 2]}, application=SimpleNamespace(bot_data={}))

        self.assertEqual(ystr_handlers.get_ystr_data_back_action(context), "datacandidates")

        ystr_handlers.set_ystr_data_back_action(context, "testdata")

        self.assertEqual(ystr_handlers.get_ystr_data_back_action(context), "testdata")


if __name__ == "__main__":
    unittest.main()
