from __future__ import annotations

import asyncio
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app import bot_app
from app.main_menu import (
    G25_COORDINATES_REPLY_BUTTON_TEXT,
    build_main_menu_keyboard,
    build_reply_menu_keyboard,
    main_menu_callback_handler,
    set_active_main_menu_message,
    start_text,
)


class MainMenuUiTests(unittest.TestCase):
    def test_reply_keyboard_has_quick_g25_button(self) -> None:
        keyboard = build_reply_menu_keyboard().to_dict()["keyboard"]

        self.assertEqual(
            [button["text"] for button in keyboard[0]],
            ["Menu", G25_COORDINATES_REPLY_BUTTON_TEXT],
        )

    def test_start_text_mentions_beta_and_menu(self) -> None:
        text = start_text()

        self.assertIn("beta", text.lower())
        self.assertIn("Menu", text)
        self.assertIn("G25", text)

    def test_reply_keyboard_does_not_show_stats_for_admin(self) -> None:
        update = SimpleNamespace(effective_user=SimpleNamespace(username="jb_cc"))
        keyboard = build_reply_menu_keyboard(update).to_dict()["keyboard"]

        self.assertEqual(len(keyboard), 1)
        self.assertEqual(
            [button["text"] for button in keyboard[0]],
            ["Menu", G25_COORDINATES_REPLY_BUTTON_TEXT],
        )

    def test_main_menu_hides_reports_section(self) -> None:
        keyboard = build_main_menu_keyboard().to_dict()["inline_keyboard"]
        callbacks = [row[0]["callback_data"] for row in keyboard]
        labels = [row[0]["text"] for row in keyboard]

        self.assertNotIn("reports:root", callbacks)
        self.assertNotIn("📊 Reports", labels)

    def test_main_menu_hides_settings_section(self) -> None:
        keyboard = build_main_menu_keyboard().to_dict()["inline_keyboard"]
        callbacks = [row[0]["callback_data"] for row in keyboard]
        labels = [row[0]["text"] for row in keyboard]

        self.assertNotIn("settings:root", callbacks)
        self.assertNotIn("⚙️ Настройки", labels)

    def test_main_menu_hides_help_section(self) -> None:
        keyboard = build_main_menu_keyboard().to_dict()["inline_keyboard"]
        callbacks = [row[0]["callback_data"] for row in keyboard]
        labels = [row[0]["text"] for row in keyboard]

        self.assertNotIn("help:root", callbacks)
        self.assertNotIn("📖 Справка", labels)

    def test_traits_entry_opens_sections_directly(self) -> None:
        keyboard = build_main_menu_keyboard().to_dict()["inline_keyboard"]
        callbacks = [button["callback_data"] for row in keyboard for button in row]

        self.assertIn("traits:s", callbacks)
        self.assertNotIn("traits:root", callbacks)

    def test_server_checklist_removes_legacy_pca(self) -> None:
        readme = Path("README.md").read_text(encoding="utf-8")
        gitignore = Path(".gitignore").read_text(encoding="utf-8")

        self.assertIn("rm -rf /opt/kbdnabot/g25_feature", readme)
        self.assertIn("rm -f /opt/kbdnabot/handlers/g25.py", readme)
        self.assertIn("rm -f /opt/kbdnabot/ui/g25.py", readme)
        self.assertNotIn("g25_feature/runs", gitignore)

    def test_vahaduo_ui_has_no_legacy_pca_entrypoints(self) -> None:
        source = Path("app/features/vahaduo/ui.py").read_text(encoding="utf-8")
        stats_ui = Path("ui/stats.py").read_text(encoding="utf-8")
        usage_source = Path("stores/usage.py").read_text(encoding="utf-8")

        self.assertNotIn("PANEL_CALLBACK_PREFIX", source)
        self.assertNotIn("_build_g25menu_keyboard", source)
        self.assertNotIn("_build_g25coords_keyboard", source)
        self.assertNotIn("coords_sim", source)
        self.assertNotIn("stats['g25_quick_panel']", stats_ui)
        self.assertIn(
            'VISIBLE_G25_STATS_COMMANDS = ("vahaduo_distance", "vahaduo_single", "vahaduo_multi")',
            usage_source,
        )

    def test_legacy_standalone_entrypoint_is_guarded(self) -> None:
        with patch.dict("os.environ", {bot_app.ALLOW_LEGACY_STANDALONE_ENV: ""}, clear=False):
            with self.assertRaisesRegex(RuntimeError, "legacy standalone DNA Lab launcher"):
                bot_app.main()

    def test_cancel_clears_active_main_menu_state(self) -> None:
        forgotten: list[tuple[int, int]] = []
        cleared_flows: list[tuple[int, int]] = []

        def forget_active(_context, chat_id: int, *, message_id: int | None = None) -> None:
            forgotten.append((chat_id, int(message_id or 0)))

        class FakeQuery:
            data = "main:cancel"

            def __init__(self) -> None:
                self.message = SimpleNamespace(chat_id=10, message_id=99)
                self.answered = False
                self.edited_text = ""

            async def answer(self, *args, **kwargs) -> None:
                self.answered = True

            async def edit_message_text(self, text: str) -> None:
                self.edited_text = text

        query = FakeQuery()
        flow_store = SimpleNamespace(clear=lambda chat_id, user_id: cleared_flows.append((chat_id, user_id)))
        context = SimpleNamespace(application=SimpleNamespace(bot_data={
            "reply_menu_hooks": {"forget_active_reply_menu": forget_active},
            "haplogroup_flow_store": flow_store,
        }))
        update = SimpleNamespace(
            callback_query=query,
            effective_chat=SimpleNamespace(id=10),
            effective_user=SimpleNamespace(id=20),
        )

        set_active_main_menu_message(context, 10, 20, 99)
        asyncio.run(main_menu_callback_handler(update, context))

        self.assertTrue(query.answered)
        self.assertEqual(query.edited_text, "Меню закрыто.")
        self.assertEqual(forgotten, [(10, 99)])
        self.assertEqual(cleared_flows, [(10, 20)])


if __name__ == "__main__":
    unittest.main()
