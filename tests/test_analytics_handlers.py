from __future__ import annotations

from types import SimpleNamespace
import unittest

from handlers import analytics as analytics_handlers


class AnalyticsHandlerStateTests(unittest.TestCase):
    def test_haplo_menu_state_is_message_scoped(self) -> None:
        context = SimpleNamespace(user_data={}, application=SimpleNamespace(bot_data={}))

        first = analytics_handlers._get_haplo_menu_state(context, 10)
        second = analytics_handlers._get_haplo_menu_state(context, 11)

        first["group"] = "G2a"
        self.assertEqual(context.user_data["haplo_menu_state"][10], {"group": "G2a"})
        self.assertEqual(second, {})

    def test_clear_haplo_menu_state_removes_empty_storage(self) -> None:
        context = SimpleNamespace(
            user_data={"haplo_menu_state": {10: {"group": "G2a"}}},
            application=SimpleNamespace(bot_data={}),
        )

        analytics_handlers._clear_haplo_menu_state(context, 10)

        self.assertNotIn("haplo_menu_state", context.user_data)


if __name__ == "__main__":
    unittest.main()
