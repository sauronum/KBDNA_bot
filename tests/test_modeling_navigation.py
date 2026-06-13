from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.features.modeling import saved_models
from app.features.modeling.admixtools2 import show_f2_cache_status, show_fstats_dataset_menu, show_qpgraph_dataset_menu
from app.features.modeling.menu import show_admixtools2_pending
from app.features.modeling.navigation import (
    NAV_CURRENT_KEY,
    NAV_STACK_KEY,
    nav_back_callback,
    nav_enter,
    nav_pop,
)
from app.features.modeling.qpadm_classic import (
    QPADM_ENGINE_ADMIXTOOLS2,
    QPADM_FLOW_KEY,
    qpadm_classic_callback_handler,
    show_qpadm_admixtools2_dataset_menu,
)
from app.features.modeling.qpwave import (
    QPWAVE_ENGINE_ADMIXTOOLS2,
    QPWAVE_FLOW_KEY,
    qpwave_callback_handler,
    show_qpwave_admixtools2_dataset_menu,
)


class Message:
    def __init__(self) -> None:
        self.args = ()
        self.kwargs = {}
        self.text = ""
        self.reply_markup = None

    async def edit_text(self, *args, **kwargs) -> None:
        self.args = args
        self.kwargs = kwargs
        if args:
            self.text = args[0]
        self.reply_markup = kwargs.get("reply_markup")


def _update(message: Message) -> SimpleNamespace:
    return SimpleNamespace(
        callback_query=SimpleNamespace(message=message),
        effective_user=SimpleNamespace(id=1001),
    )


def _footer_back_callback(message: Message) -> str:
    return message.reply_markup.inline_keyboard[-1][0].callback_data


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
        context = SimpleNamespace(user_data={})
        nav_enter(context, "modeling:root")
        nav_enter(context, "modeling:at2")

        asyncio.run(show_qpadm_admixtools2_dataset_menu(Message(), context, edit_existing=True, lang="ru"))

        self.assertEqual(context.user_data[NAV_CURRENT_KEY], "modeling:qpadm_engine:admixtools2_qpadm")
        self.assertEqual(context.user_data[NAV_STACK_KEY], ["modeling:root", "modeling:at2"])
        self.assertEqual(nav_pop(context), "modeling:at2")

    def test_admixtools2_qpwave_dataset_back_returns_to_admixtools2_menu(self) -> None:
        context = SimpleNamespace(user_data={})
        nav_enter(context, "modeling:root")
        nav_enter(context, "modeling:at2")

        asyncio.run(show_qpwave_admixtools2_dataset_menu(Message(), context, edit_existing=True, lang="ru"))

        self.assertEqual(context.user_data[NAV_CURRENT_KEY], "modeling:qpwave_engine:admixtools2_qpwave")
        self.assertEqual(context.user_data[NAV_STACK_KEY], ["modeling:root", "modeling:at2"])
        self.assertEqual(nav_pop(context), "modeling:at2")

    def test_admixtools2_qpadm_reset_keeps_admixtools2_parent(self) -> None:
        message = Message()
        context = SimpleNamespace(user_data={QPADM_FLOW_KEY: {"engine": QPADM_ENGINE_ADMIXTOOLS2}})
        nav_enter(context, "modeling:root")
        nav_enter(context, "modeling:at2")
        nav_enter(context, "modeling:qpadm_engine:admixtools2_qpadm")
        nav_enter(context, "modeling:qpadm_review")

        asyncio.run(
            qpadm_classic_callback_handler(
                _update(message),
                context,
                "qpadm_reset",
                ["modeling", "qpadm_reset"],
                lang="ru",
            )
        )

        self.assertEqual(context.user_data[NAV_CURRENT_KEY], "modeling:qpadm_engine:admixtools2_qpadm")
        self.assertEqual(context.user_data[NAV_STACK_KEY], ["modeling:at2"])
        self.assertEqual(nav_pop(context), "modeling:at2")

    def test_admixtools2_qpwave_reset_keeps_admixtools2_parent(self) -> None:
        message = Message()
        context = SimpleNamespace(user_data={QPWAVE_FLOW_KEY: {"engine": QPWAVE_ENGINE_ADMIXTOOLS2}})
        nav_enter(context, "modeling:root")
        nav_enter(context, "modeling:at2")
        nav_enter(context, "modeling:qpwave_engine:admixtools2_qpwave")
        nav_enter(context, "modeling:qpwave_builder")

        asyncio.run(
            qpwave_callback_handler(
                _update(message),
                context,
                "qpwave_reset",
                ["modeling", "qpwave_reset"],
                lang="ru",
            )
        )

        self.assertEqual(context.user_data[NAV_CURRENT_KEY], "modeling:qpwave_engine:admixtools2_qpwave")
        self.assertEqual(context.user_data[NAV_STACK_KEY], ["modeling:at2"])
        self.assertEqual(nav_pop(context), "modeling:at2")

    def test_admixtools2_utility_screens_use_nav_back(self) -> None:
        context = SimpleNamespace(user_data={})
        nav_enter(context, "modeling:root")
        nav_enter(context, "modeling:at2")

        f2_message = Message()
        asyncio.run(show_f2_cache_status(f2_message, context, edit_existing=True, lang="ru"))

        self.assertEqual(context.user_data[NAV_CURRENT_KEY], "modeling:at2_f2_cache")
        self.assertEqual(context.user_data[NAV_STACK_KEY], ["modeling:root", "modeling:at2"])
        self.assertEqual(_footer_back_callback(f2_message), nav_back_callback())
        self.assertEqual(nav_pop(context), "modeling:at2")

        context = SimpleNamespace(user_data={})
        nav_enter(context, "modeling:root")
        nav_enter(context, "modeling:at2")

        fstats_message = Message()
        asyncio.run(show_fstats_dataset_menu(fstats_message, context, edit_existing=True, lang="ru"))

        self.assertEqual(context.user_data[NAV_CURRENT_KEY], "modeling:at2_fstats_ds")
        self.assertEqual(context.user_data[NAV_STACK_KEY], ["modeling:root", "modeling:at2"])
        self.assertEqual(_footer_back_callback(fstats_message), nav_back_callback())
        self.assertEqual(nav_pop(context), "modeling:at2")

    def test_admixtools2_pending_screen_uses_nav_back(self) -> None:
        message = Message()
        context = SimpleNamespace(user_data={})
        nav_enter(context, "modeling:root")
        nav_enter(context, "modeling:at2")

        asyncio.run(
            show_admixtools2_pending(message, context, "at2_qpgraph", edit_existing=True, lang="ru")
        )

        self.assertEqual(context.user_data[NAV_CURRENT_KEY], "modeling:at2_qpgraph")
        self.assertEqual(context.user_data[NAV_STACK_KEY], ["modeling:root", "modeling:at2"])
        self.assertEqual(_footer_back_callback(message), nav_back_callback())
        self.assertEqual(nav_pop(context), "modeling:at2")

    def test_admixtools2_qpgraph_dataset_back_returns_to_admixtools2_menu(self) -> None:
        message = Message()
        context = SimpleNamespace(user_data={})
        nav_enter(context, "modeling:root")
        nav_enter(context, "modeling:at2")

        asyncio.run(show_qpgraph_dataset_menu(message, context, edit_existing=True, lang="ru"))

        self.assertEqual(context.user_data[NAV_CURRENT_KEY], "modeling:at2_qpgraph_ds")
        self.assertEqual(context.user_data[NAV_STACK_KEY], ["modeling:root", "modeling:at2"])
        self.assertEqual(_footer_back_callback(message), nav_back_callback())
        self.assertEqual(nav_pop(context), "modeling:at2")

    def test_saved_model_view_uses_nav_back_without_polluting_list_stack(self) -> None:
        old_path = saved_models.SAVED_MODELS_PATH
        with tempfile.TemporaryDirectory() as temp_dir:
            saved_models.SAVED_MODELS_PATH = Path(temp_dir) / "saved_models.json"
            saved_models._write_records(
                [
                    {
                        "id": "record-1",
                        "owner_user_id": 1001,
                        "kind": "qpadm_classic",
                        "title": "Audit record",
                        "dataset": "human_origins",
                    }
                ]
            )
            try:
                message = Message()
                context = SimpleNamespace(user_data={})
                nav_enter(context, "modeling:root")

                asyncio.run(
                    saved_models.show_saved_models_menu(
                        message,
                        _update(message),
                        context,
                        edit_existing=True,
                        lang="ru",
                    )
                )
                asyncio.run(
                    saved_models.saved_models_callback_handler(
                        _update(message),
                        context,
                        "saved_view",
                        ["modeling", "saved_view", "record-1"],
                        lang="ru",
                    )
                )

                self.assertEqual(context.user_data[NAV_CURRENT_KEY], "modeling:saved_view:record-1")
                self.assertEqual(context.user_data[NAV_STACK_KEY], ["modeling:root", "modeling:saved_page:0"])
                self.assertEqual(_footer_back_callback(message), nav_back_callback())
                self.assertEqual(nav_pop(context), "modeling:saved_page:0")
            finally:
                saved_models.SAVED_MODELS_PATH = old_path


if __name__ == "__main__":
    unittest.main()
