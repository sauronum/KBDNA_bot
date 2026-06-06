from __future__ import annotations

import asyncio
import unittest
from pathlib import Path
from types import SimpleNamespace

import bot
from app.features.snp_report.domain import load_snp_rules


class _FakeMyDataStore:
    def list_samples(self, user_id: int) -> list[object]:
        return []


class _FakeMessage:
    chat_id = 10
    message_id = 20

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def edit_text(self, text: str, **kwargs: object):
        self.calls.append((text, kwargs))
        return self


class SnpReportEntryTests(unittest.TestCase):
    def test_bot_registers_snp_lab_callbacks_and_services(self) -> None:
        source = Path("bot.py").read_text(encoding="utf-8")

        self.assertIn("register_snp_report_services as register_dna_lab_snp_report_services", source)
        self.assertIn("show_snp_report_menu as show_dna_lab_snp_report_menu", source)
        self.assertIn('"snp_report": "snp_report"', source)
        self.assertIn(
            'dna_lab_snp_report_callback_handler), pattern=fr"^{DNA_LAB_SNP_REPORT_CALLBACK_PREFIX}:"',
            source,
        )
        self.assertIn("dna_lab_snp_report_text_input_handler), group=-2", source)

    def test_dna_lab_snp_report_entry_renders_root_screen(self) -> None:
        message = _FakeMessage()
        context = SimpleNamespace(
            application=SimpleNamespace(
                bot_data={
                    "my_data_store": _FakeMyDataStore(),
                    "snp_report_rules": load_snp_rules(),
                }
            ),
            user_data={},
        )

        asyncio.run(bot._show_dna_lab_feature_root(message, context, 1, "snp_report", edit_existing=True))

        self.assertEqual(len(message.calls), 1)
        text, kwargs = message.calls[0]
        self.assertIn("<b>SNP Lab</b>", text)
        keyboard = kwargs["reply_markup"].inline_keyboard
        callbacks = [[button.callback_data for button in row] for row in keyboard]
        self.assertEqual(
            callbacks,
            [
                ["snp_report:search"],
                ["snp_report:db"],
                ["snp_report:report"],
                ["main:root", "main:cancel"],
            ],
        )


if __name__ == "__main__":
    unittest.main()
