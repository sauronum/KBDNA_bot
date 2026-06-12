from __future__ import annotations

import unittest
from types import SimpleNamespace

from app.features.modeling.navigation import NAV_CURRENT_KEY, NAV_STACK_KEY, nav_enter, nav_pop


class ModelingNavigationTests(unittest.TestCase):
    def test_page_navigation_replaces_current_page_without_polluting_back_stack(self) -> None:
        context = SimpleNamespace(user_data={})

        nav_enter(context, "modeling:source_sets")
        nav_enter(context, "modeling:ss_list_page:0")
        nav_enter(context, "modeling:ss_list_page:1")
        nav_enter(context, "modeling:ss_list_page:2")

        self.assertEqual(context.user_data[NAV_CURRENT_KEY], "modeling:ss_list_page:2")
        self.assertEqual(context.user_data[NAV_STACK_KEY], ["modeling:source_sets"])
        self.assertEqual(nav_pop(context), "modeling:source_sets")

    def test_distinct_pages_still_push_their_parent_screen(self) -> None:
        context = SimpleNamespace(user_data={})

        nav_enter(context, "modeling:qpadm_target")
        nav_enter(context, "modeling:qpadm_samples_page:0")

        self.assertEqual(context.user_data[NAV_STACK_KEY], ["modeling:qpadm_target"])


if __name__ == "__main__":
    unittest.main()
