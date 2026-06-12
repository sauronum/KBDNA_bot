from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace

from app.features.modeling.navigation import NAV_CURRENT_KEY, NAV_STACK_KEY, nav_enter, nav_pop
from app.features.modeling.qpadm_classic import show_qpadm_admixtools2_dataset_menu
from app.features.modeling.qpwave import show_qpwave_admixtools2_dataset_menu


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

    def test_admixtools2_qpadm_dataset_back_returns_to_admixtools2_menu(self) -> None:
        class Message:
            async def edit_text(self, *args, **kwargs) -> None:
                self.args = args
                self.kwargs = kwargs

        context = SimpleNamespace(user_data={})
        nav_enter(context, "modeling:root")
        nav_enter(context, "modeling:at2")

        asyncio.run(show_qpadm_admixtools2_dataset_menu(Message(), context, edit_existing=True, lang="ru"))

        self.assertEqual(context.user_data[NAV_CURRENT_KEY], "modeling:qpadm_engine:admixtools2_qpadm")
        self.assertEqual(context.user_data[NAV_STACK_KEY], ["modeling:root", "modeling:at2"])
        self.assertEqual(nav_pop(context), "modeling:at2")

    def test_admixtools2_qpwave_dataset_back_returns_to_admixtools2_menu(self) -> None:
        class Message:
            async def edit_text(self, *args, **kwargs) -> None:
                self.args = args
                self.kwargs = kwargs

        context = SimpleNamespace(user_data={})
        nav_enter(context, "modeling:root")
        nav_enter(context, "modeling:at2")

        asyncio.run(show_qpwave_admixtools2_dataset_menu(Message(), context, edit_existing=True, lang="ru"))

        self.assertEqual(context.user_data[NAV_CURRENT_KEY], "modeling:qpwave_engine:admixtools2_qpwave")
        self.assertEqual(context.user_data[NAV_STACK_KEY], ["modeling:root", "modeling:at2"])
        self.assertEqual(nav_pop(context), "modeling:at2")


if __name__ == "__main__":
    unittest.main()
