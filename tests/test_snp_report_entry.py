from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import bot
from PIL import Image

from app.features.snp_report.domain import SnpCategorySummary, SnpReportResult, SnpReportRow, load_snp_rules
from app.features.snp_report.storage import SnpReportRecord, SnpReportSummary
from app.features.snp_report.ui import build_db_rule_keyboard, db_rule_text, render_html_report, result_text
from app.features.snp_report.visuals import render_category_load_png


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

    def test_snp_base_card_has_description_and_sample_check_button(self) -> None:
        rules = load_snp_rules()
        rule_index = next(index for index, rule in enumerate(rules) if rule.rsid == "rs4680")
        rule = rules[rule_index]

        text = db_rule_text(rule)
        self.assertIn("COMT", text)
        self.assertIn("Описание:", text)
        self.assertIn("dbSNP", text)
        self.assertIn("SNPedia", text)

        callbacks = [
            button.callback_data
            for row in build_db_rule_keyboard(rule, rule_index, 2, 3).inline_keyboard
            for button in row
        ]
        labels = [
            button.text
            for row in build_db_rule_keyboard(rule, rule_index, 2, 3).inline_keyboard
            for button in row
        ]
        self.assertIn(f"snp_report:dbcheck:{rule_index}:2:3:0", callbacks)
        self.assertNotIn("📋 Скопировать rsID", labels)

    def test_html_report_includes_snp_annotation(self) -> None:
        rule = next(rule for rule in load_snp_rules() if rule.rsid == "rs4680")
        result = SnpReportResult(
            sample_id="sample",
            sample_name="Sample",
            raw_file_id="raw",
            total_rules=1,
            ok=1,
            warn=0,
            bad=0,
            missing=0,
            categories=(
                SnpCategorySummary(
                    category=rule.category,
                    total=1,
                    ok=1,
                    warn=0,
                    bad=0,
                    missing=0,
                    risk_percent=0,
                ),
            ),
            rows=(
                SnpReportRow(
                    rsid=rule.rsid,
                    category=rule.category,
                    normal_genotype=rule.normal_genotype,
                    user_genotype="GG",
                    status="ok",
                    gene=rule.gene,
                    title=rule.title,
                    description=rule.description,
                ),
            ),
        )

        html = render_html_report(result)

        self.assertIn("COMT", html)
        self.assertIn("Val158Met", html)

    def test_report_summary_caption_is_compact_when_png_is_sent(self) -> None:
        record = SnpReportRecord(
            summary=SnpReportSummary(
                report_id="report",
                sample_id="sample",
                sample_name="Sample",
                raw_file_id="raw",
                created_at="2026-01-01T00:00:00Z",
                total_rules=10,
                ok=4,
                warn=3,
                bad=2,
                missing=1,
                html_path="report.html",
            ),
            payload={
                "categories": [
                    {
                        "category": "Высокобелк. диета",
                        "total": 4,
                        "ok": 1,
                        "warn": 2,
                        "bad": 1,
                        "missing": 0,
                        "risk_percent": 50,
                    }
                ]
            },
        )

        text = result_text(record, visual=True)

        self.assertIn("Sample: <b>Sample</b>", text)
        self.assertNotIn("SNP в панели", text)
        self.assertNotIn("🔴 Гомо/вариант", text)
        self.assertNotIn("PNG-график", text)
        self.assertNotIn("HTML-файл готов", text)
        self.assertNotIn("█████░░░░░", text)
        self.assertNotIn("🔴 1, 🟡 2, ⚪ 0", text)

        fallback_text = result_text(record, visual=False)
        self.assertIn("PNG-график не отправился", fallback_text)

    def test_category_load_png_is_rendered(self) -> None:
        record = SnpReportRecord(
            summary=SnpReportSummary(
                report_id="report",
                sample_id="sample",
                sample_name="Sample",
                raw_file_id="raw",
                created_at="2026-01-01T00:00:00Z",
                total_rules=10,
                ok=4,
                warn=3,
                bad=2,
                missing=1,
                html_path="report.html",
            ),
            payload={
                "categories": [
                    {
                        "category": "Высокобелк. диета",
                        "total": 4,
                        "ok": 1,
                        "warn": 2,
                        "bad": 1,
                        "missing": 0,
                        "risk_percent": 50,
                    }
                ]
            },
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "load.png"
            render_category_load_png(record, path)

            self.assertTrue(path.exists())
            with Image.open(path) as image:
                self.assertEqual(image.format, "PNG")
                self.assertGreaterEqual(image.width, 1200)
                self.assertGreaterEqual(image.height, 500)


if __name__ == "__main__":
    unittest.main()
