from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import bot
from PIL import Image

from app.features.snp_report.domain import SnpCategorySummary, SnpReportResult, SnpReportRow, SnpRule, load_snp_rules
from app.features.snp_report.interesting import analyze_interesting_snps, load_interesting_snps
from app.features.snp_report.menu import _find_rules_by_gene, show_snp_report_menu
from app.features.snp_report.storage import SnpReportRecord, SnpReportSummary
from app.features.snp_report.ui import (
    build_db_categories_keyboard,
    build_db_category_keyboard,
    build_db_gene_results_keyboard,
    build_db_rsid_not_found_keyboard,
    build_db_root_keyboard,
    build_db_rule_keyboard,
    build_db_sources_keyboard,
    build_interesting_detail_keyboard,
    build_interesting_picker_keyboard,
    build_interesting_result_keyboard_for_analysis,
    build_interesting_sample_picker_keyboard,
    build_interesting_single_result_keyboard,
    build_sample_home_keyboard,
    build_search_result_keyboard_for_rule,
    db_rsid_not_found_text,
    db_rule_text,
    db_root_text,
    db_sources_text,
    interesting_detail_text,
    interesting_result_text,
    interesting_picker_text,
    interesting_sample_picker_text,
    render_html_report,
    result_text,
    sample_home_text,
    search_result_text,
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
        sample = SimpleNamespace(asset_id="12345678-1234-1234-1234-123456789abc", display_name="Zaur", raw_file_id="raw-1")
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
        labels = [[button.text for button in row] for row in keyboard]
        callbacks = [[button.callback_data for button in row] for row in keyboard]
        self.assertEqual(
            labels[:4],
            [
                ["🔎 Поиск SNP"],
                ["🧪 Интересные SNP"],
                ["📚 База SNP"],
                ["📊 Нагрузка по категориям"],
            ],
        )
        self.assertEqual(
            callbacks,
            [
                ["snp_report:search"],
                ["snp_report:interesting"],
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
        self.assertIn("С трактовкой:", text)
        self.assertIn("Не найдено в raw:", text)
        self.assertIn("• <b>Переносимость лактозы</b>", text)
        self.assertNotIn("Ограничение:", text)

        keyboard = build_interesting_result_keyboard_for_analysis(result).inline_keyboard
        callbacks = [
            button.callback_data
            for row in keyboard
            for button in row
        ]
        self.assertIn("snp_report:intdetail:sample:rs4988235", callbacks)
        self.assertNotIn("snp_report:intdetail:sample:rs17822931", callbacks)
        self.assertLessEqual(max(len(row) for row in keyboard), 2)

        detail = interesting_detail_text(by_rsid["rs4988235"], "Demo", position=1, total=result.found)
        self.assertIn("Что это значит", detail)
        self.assertIn("Итог:", detail)
        self.assertIn("Карточка: <b>1/", detail)

        detail_keyboard = build_interesting_detail_keyboard("sample", "rs4988235", next_rsid="rs17822931").inline_keyboard
        detail_callbacks = [
            button.callback_data
            for row in detail_keyboard
            for button in row
        ]
        self.assertIn("snp_report:intdetail:sample:rs17822931", detail_callbacks)
        self.assertIn("snp_report:interesting_sample:sample", detail_callbacks)
        self.assertIn("snp_report:sample:sample", detail_callbacks)

    def test_interesting_snp_entry_starts_from_marker_list(self) -> None:
        panel = load_interesting_snps()
        definition = next(item for item in panel if item.rsid == "rs4988235")
        sample = SimpleNamespace(asset_id="12345678-1234-1234-1234-123456789abc", display_name="Zaur", raw_file_id="raw-1")

        text = interesting_picker_text(panel)
        self.assertIn("Сначала выберите интересный SNP", text)

        callbacks = [
            button.callback_data
            for row in build_interesting_picker_keyboard(panel).inline_keyboard
            for button in row
        ]
        self.assertIn("snp_report:interesting_snp:rs4988235", callbacks)

        sample_text = interesting_sample_picker_text(definition, [sample])
        self.assertIn("Переносимость лактозы", sample_text)
        self.assertIn("Выберите sample", sample_text)

        sample_callbacks = [
            button.callback_data
            for row in build_interesting_sample_picker_keyboard(definition, [sample]).inline_keyboard
            for button in row
        ]
        self.assertIn("snp_report:isp:rs4988235:12345678-1234-1234-1234-123456789abc", sample_callbacks)
        self.assertIn("snp_report:interesting", sample_callbacks)
        self.assertLessEqual(max(len(callback or "") for callback in sample_callbacks), 64)

        result_callbacks = [
            button.callback_data
            for row in build_interesting_single_result_keyboard("sample-1", "rs4988235").inline_keyboard
            for button in row
        ]
        self.assertIn("snp_report:interesting_rsid:rs4988235", result_callbacks)
        self.assertIn("snp_report:interesting", result_callbacks)

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
        labels = [
            button.text
            for row in build_db_root_keyboard().inline_keyboard
            for button in row
        ]
        callbacks = [
            button.callback_data
            for row in build_db_root_keyboard().inline_keyboard
            for button in row
        ]

        self.assertIn("🔎 Найти rsID", labels)
        self.assertIn("🧬 Найти gene/locus", labels)
        self.assertIn("📂 Разделы базы", labels)
        self.assertIn("ℹ️ Источники базы", labels)
        self.assertIn("snp_report:db_search", callbacks)
        self.assertIn("snp_report:db_gene", callbacks)
        self.assertIn("snp_report:dbcats", callbacks)
        self.assertIn("snp_report:dbpopular", callbacks)
        self.assertIn("snp_report:db_sources", callbacks)

    def test_snp_base_sources_are_explicit(self) -> None:
        rules = load_snp_rules()

        root_text = db_root_text(rules)
        self.assertIn("Источников панели:", root_text)
        self.assertIn("Слоёв описаний:", root_text)

        sources_text = db_sources_text(rules)
        self.assertIn("Слой генотипов панели", sources_text)
        self.assertIn("legacy-импорт панели отчёта", sources_text)
        self.assertIn("Норма панели", sources_text)

        callbacks = [
            button.callback_data
            for row in build_db_sources_keyboard().inline_keyboard
            for button in row
        ]
        self.assertIn("snp_report:db", callbacks)

    def test_snp_base_rsid_miss_can_be_checked_in_sample(self) -> None:
        text = db_rsid_not_found_text("rs999999")
        self.assertIn("rs999999", text)
        self.assertIn("проверить в raw sample", text)

        callbacks = [
            button.callback_data
            for row in build_db_rsid_not_found_keyboard("rs999999").inline_keyboard
            for button in row
        ]
        self.assertIn("snp_report:search_rsid_page:rs999999:0", callbacks)
        self.assertIn("snp_report:db_gene", callbacks)

    def test_sample_lookup_result_links_back_to_known_snp_card(self) -> None:
        callbacks = [
            button.callback_data
            for row in build_search_result_keyboard_for_rule("sample-1", rule_index=17).inline_keyboard
            for button in row
        ]
        self.assertEqual(callbacks[0], "snp_report:dbsnp:17:0:0")
        self.assertIn("snp_report:search_sample:sample-1", callbacks)

    def test_gene_search_result_buttons_show_gene_and_rsid(self) -> None:
        rules = load_snp_rules()
        rule_index = next(index for index, rule in enumerate(rules) if rule.rsid == "rs4680")
        labels = [
            button.text
            for row in build_db_gene_results_keyboard("COMT", [(rule_index, rules[rule_index])]).inline_keyboard
            for button in row
        ]

        self.assertTrue(any("rs4680" in label and "COMT" in label for label in labels))

    def test_gene_search_prioritizes_exact_gene_and_described_cards(self) -> None:
        rules = (
            SnpRule(rsid="rs1", normal_genotype="AA", category="Other", gene="XCOMT", title="Weak match"),
            SnpRule(rsid="rs2", normal_genotype="GG", category="Methylation", gene="COMT", title="COMT marker", description="Useful card"),
            SnpRule(rsid="rs3", normal_genotype="CC", category="Methylation", gene="COMT", title=""),
        )

        matches = _find_rules_by_gene(rules, "COMT")

        self.assertEqual([rule.rsid for _index, rule in matches[:2]], ["rs2", "rs3"])

    def test_categories_prioritize_richer_sections_and_show_counts(self) -> None:
        rules = (
            SnpRule(rsid="rs1", normal_genotype="AA", category="Sparse"),
            SnpRule(rsid="rs2", normal_genotype="GG", category="Rich", gene="COMT", title="COMT marker"),
            SnpRule(rsid="rs3", normal_genotype="CC", category="Rich", description="Useful card"),
        )

        labels = [
            button.text
            for row in build_db_categories_keyboard(rules).inline_keyboard
            for button in row
        ]

        self.assertEqual(labels[0], "Rich · 2/2")
        self.assertIn("Sparse · 0/1", labels)

    def test_category_snp_buttons_show_rsid_gene_and_title(self) -> None:
        rule = SnpRule(
            rsid="rs4680",
            normal_genotype="GG",
            category="Methylation",
            gene="COMT",
            title="COMT Val158Met",
            description="Useful card",
        )

        labels = [
            button.text
            for row in build_db_category_keyboard(0, [(0, rule)]).inline_keyboard
            for button in row
        ]

        self.assertTrue(any("rs4680" in label and "COMT" in label for label in labels))

    def test_snp_base_card_has_description_and_sample_check_button(self) -> None:
        rules = load_snp_rules()
        rule_index = next(index for index, rule in enumerate(rules) if rule.rsid == "rs4680")
        rule = rules[rule_index]

        text = db_rule_text(rule)
        self.assertIn("COMT", text)
        self.assertIn("Что известно", text)
        self.assertIn("В панели", text)
        self.assertIn("Норма панели:", text)
        self.assertIn("Источник нормы:", text)
        self.assertIn("Источник описания:", text)
        self.assertNotIn("Описание:", text)
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

    def test_snp_base_card_without_description_is_honest(self) -> None:
        rule = next(rule for rule in load_snp_rules() if not rule.description)

        text = db_rule_text(rule)

        self.assertIn("Подробного описания для этого SNP пока нет", text)
        self.assertIn("Норма панели:", text)

    def test_sample_lookup_result_explains_panel_status_for_known_snp(self) -> None:
        rule = next(rule for rule in load_snp_rules() if rule.rsid == "rs4680")
        sample = SimpleNamespace(display_name="Demo")
        result = SimpleNamespace(rsid=rule.rsid, found=True, genotype=rule.normal_genotype, chromosome="22", position=19963748, error=None)

        text = search_result_text(sample, result, rule=rule)

        self.assertIn("SNP в sample", text)
        self.assertIn("COMT", text)
        self.assertIn("Норма панели:", text)
        self.assertIn("Статус в панели:", text)
        self.assertIn("норма панели", text)

    def test_sample_lookup_result_mentions_known_card_when_raw_is_missing_snp(self) -> None:
        rule = next(rule for rule in load_snp_rules() if rule.rsid == "rs4680")
        sample = SimpleNamespace(display_name="Demo")
        result = SimpleNamespace(rsid=rule.rsid, found=False, genotype="--", chromosome=None, position=None, error=None)

        text = search_result_text(sample, result, rule=rule)

        self.assertIn("Карточка SNP есть в базе", text)

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
                        "category": f"Категория {index}",
                        "total": 4,
                        "ok": 1,
                        "warn": 2,
                        "bad": 1,
                        "missing": 0,
                        "risk_percent": 50 + index,
                    }
                    for index in range(10)
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
                        "category": f"Категория {index}",
                        "total": 4,
                        "ok": 1,
                        "warn": 2,
                        "bad": 1,
                        "missing": 0,
                        "risk_percent": 50 + index,
                    }
                    for index in range(10)
                ]
            },
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "load.png"
            render_category_load_png(record, path)

            self.assertTrue(path.exists())
            with Image.open(path) as image:
                self.assertEqual(image.format, "PNG")
                self.assertGreaterEqual(image.width, 1400)
                self.assertGreaterEqual(image.height, 950)
                self.assertLessEqual(image.height, 1100)


if __name__ == "__main__":
    unittest.main()
