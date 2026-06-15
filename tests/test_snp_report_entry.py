from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import bot
from PIL import Image

from app.features.snp_report.domain import SnpCategorySummary, SnpReportResult, SnpReportRow, load_snp_rules
from app.features.snp_report.interesting import analyze_interesting_snps, load_interesting_snps
from app.features.snp_report.menu import show_snp_report_menu
from app.features.snp_report.storage import SnpReportRecord, SnpReportSummary
from app.features.snp_report.ui import (
    build_db_root_keyboard,
    build_db_rule_keyboard,
    build_interesting_result_keyboard_for_analysis,
    build_sample_home_keyboard,
    db_rule_text,
    interesting_result_text,
    render_html_report,
    result_text,
    sample_home_text,
)
from app.features.snp_report.visuals import render_category_load_png


class _FakeMyDataStore:
    def __init__(self, samples: list[object] | None = None) -> None:
        self._samples = samples if samples is not None else []

    def list_samples(self, user_id: int) -> list[object]:
        return self._samples

    def get_sample_raw_file(self, user_id: int, sample_id: str) -> object | None:
        sample = next((item for item in self._samples if item.asset_id == sample_id), None)
        if sample is None or not sample.raw_file_id:
            return None
        return SimpleNamespace(asset_id=sample.raw_file_id)


class _FakeMessage:
    chat_id = 10
    message_id = 20

    def __init__(self, *, photo: bool = False) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.actions: list[str] = []
        self.photo = [object()] if photo else []

    async def edit_text(self, text: str, **kwargs: object):
        self.actions.append("edit_text")
        self.calls.append((text, kwargs))
        return self

    async def reply_text(self, text: str, **kwargs: object):
        self.actions.append("reply_text")
        self.calls.append((text, kwargs))
        return self

    async def edit_reply_markup(self, **kwargs: object):
        self.actions.append("edit_reply_markup")
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
        self.assertIn("dna_lab_snp_report_text_input_handler), group=-7", source)
        self.assertLess(
            source.index("dna_lab_snp_report_text_input_handler), group=-7"),
            source.index("MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, text_lookup_command)"),
        )

    def test_dna_lab_snp_report_entry_renders_root_screen(self) -> None:
        message = _FakeMessage()
        sample = SimpleNamespace(asset_id="sample-1", display_name="Zaur", raw_file_id="raw-1")
        context = SimpleNamespace(
            application=SimpleNamespace(
                bot_data={
                    "my_data_store": _FakeMyDataStore([sample]),
                    "snp_report_rules": load_snp_rules(),
                }
            ),
            user_data={},
        )

        asyncio.run(bot._show_dna_lab_feature_root(message, context, 1, "snp_report", edit_existing=True))

        self.assertEqual(len(message.calls), 1)
        text, kwargs = message.calls[0]
        self.assertIn("<b>SNP Lab</b>", text)
        self.assertIn("Выберите действие", text)
        keyboard = kwargs["reply_markup"].inline_keyboard
        callbacks = [[button.callback_data for button in row] for row in keyboard]
        self.assertEqual(
            callbacks,
            [
                ["snp_report:interesting"],
                ["snp_report:search"],
                ["snp_report:db"],
                ["snp_report:report"],
                ["main:root", "main:cancel"],
            ],
        )

    def test_snp_lab_menu_from_photo_sends_new_text_message(self) -> None:
        message = _FakeMessage(photo=True)
        context = SimpleNamespace(
            application=SimpleNamespace(
                bot_data={
                    "my_data_store": _FakeMyDataStore(),
                    "snp_report_rules": load_snp_rules(),
                }
            ),
            user_data={},
        )

        asyncio.run(show_snp_report_menu(message, context, 1, edit_existing=True))

        self.assertEqual(message.actions, ["reply_text", "edit_reply_markup"])
        text, kwargs = message.calls[0]
        self.assertIn("<b>SNP Lab</b>", text)
        self.assertEqual(kwargs["parse_mode"], "HTML")

    def test_interesting_snp_panel_interprets_safe_consumer_markers(self) -> None:
        panel = load_interesting_snps()
        self.assertGreaterEqual(len(panel), 8)
        self.assertTrue(all(not item.medical for item in panel))

        with tempfile.TemporaryDirectory() as tmp_dir:
            raw_path = Path(tmp_dir) / "raw.tsv"
            raw_path.write_text(
                "\n".join(
                    [
                        "rsid\tchromosome\tposition\tgenotype",
                        "rs4988235\t2\t136608646\tCT",
                        "rs17822931\t16\t48258198\tAA",
                        "rs12913832\t15\t28365618\tGG",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            result = analyze_interesting_snps(raw_path, panel, sample_id="sample", sample_name="Demo")

        by_rsid = {item.rsid: item for item in result.results}
        self.assertEqual(by_rsid["rs4988235"].status, "ok")
        self.assertIn("Промежуточный", by_rsid["rs4988235"].interpretation)
        self.assertEqual(by_rsid["rs17822931"].interpretation, "Сухой тип ушной серы")
        self.assertEqual(by_rsid["rs12913832"].status, "ok")
        self.assertGreaterEqual(result.found, 3)

        text = interesting_result_text(result)
        self.assertIn("Интересные SNP", text)
        self.assertIn("Переносимость лактозы", text)
        self.assertIn("Доступно:", text)
        self.assertNotIn("Ограничение:", text)

        callbacks = [
            button.callback_data
            for row in build_interesting_result_keyboard_for_analysis(result).inline_keyboard
            for button in row
        ]
        self.assertIn("snp_report:intdetail:sample:rs4988235", callbacks)

    def test_snp_lab_sample_home_is_lightweight_and_action_first(self) -> None:
        sample = SimpleNamespace(asset_id="sample-1", display_name="Zaur", raw_file_id="raw-1")

        text = sample_home_text(sample)

        self.assertIn("Raw-файл подключен.", text)
        self.assertIn("Выберите действие", text)
        self.assertNotIn("Записей в raw", text)

        callbacks = [
            button.callback_data
            for row in build_sample_home_keyboard(sample.asset_id).inline_keyboard
            for button in row
        ]
        self.assertEqual(
            callbacks,
            [
                "snp_report:interesting_sample:sample-1",
                "snp_report:search_sample:sample-1",
                "snp_report:run:sample-1",
                "snp_report:db",
                "snp_report:root",
                "main:cancel",
            ],
        )

    def test_snp_base_root_has_fast_entry_points(self) -> None:
        callbacks = [
            button.callback_data
            for row in build_db_root_keyboard().inline_keyboard
            for button in row
        ]

        self.assertIn("snp_report:db_search", callbacks)
        self.assertIn("snp_report:db_gene", callbacks)
        self.assertIn("snp_report:dbcats", callbacks)
        self.assertIn("snp_report:dbpopular", callbacks)

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
                self.assertLessEqual(image.height, 700)


if __name__ == "__main__":
    unittest.main()
