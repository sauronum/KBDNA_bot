from __future__ import annotations

import asyncio
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from g25_core.g25_engine import RawSummary

from app.features.matching.domain import (
    MatchSegment,
    PairwiseMatchResult,
    compare_raw_autosomal_match,
    relationship_hint,
)
from app.features.matching.domain import lookup_snp_in_raw
from app.features.matching.genetic_map import GeneticMap
from app.features.matching.menu import (
    MATCHING_CALLBACK_PREFIX,
    MatchingFlowStore,
    matching_text_input_handler,
    matching_callback_handler,
    normalize_rsid,
    show_all_pairs_confirm,
    show_pairwise_result,
    show_snp_input_screen,
    show_snp_sample_picker,
    show_snp_result,
    show_selected_sample_picker,
    show_selected_samples_result,
    toggle_snp_sample,
    toggle_selected_sample,
)
from app.features.matching.ui import (
    all_pairs_confirm_text,
    matching_running_text,
    pairwise_result_text,
    pairwise_visual_caption,
    sample_picker_text,
    saved_match_button_label,
    saved_matches_text,
    selected_samples_picker_text,
    selected_samples_visual_caption,
    snp_input_text,
    snp_result_text,
    snp_sample_picker_text,
)
from app.features.matching.storage import MatchingRecordSummary, MatchingStore
from app.features.matching.visualization import render_all_pairs_match_png, render_pairwise_match_png
from app.features.my_data.storage import SampleAsset
from PIL import Image


def _write_raw(path: Path, rows: list[tuple[str, str, int, str]]) -> None:
    body = ["rsid\tchromosome\tposition\tgenotype"]
    body.extend(f"{rsid}\t{chromosome}\t{position}\t{genotype}" for rsid, chromosome, position, genotype in rows)
    path.write_text("\n".join(body) + "\n", encoding="utf-8")


def _summary(name: str = "raw.tsv") -> RawSummary:
    return RawSummary(name, "test", 0, 0, 0, 0, 0.0, {})


def _pairwise_result() -> PairwiseMatchResult:
    return PairwiseMatchResult(
        left_summary=_summary("left.tsv"),
        right_summary=_summary("right.tsv"),
        overlap_snps=1000,
        half_identical_snps=800,
        identical_snps=100,
        segments=(MatchSegment("1", 1, 2, 500, 100, 126.9),),
        total_estimated_cm=2444.7,
        longest_estimated_cm=126.9,
        relationship_hint="Близкое родство: родитель-ребенок, full sibling или похожий уровень",
        genetic_map_used=True,
    )


class _FakeMatchingMessage:
    def __init__(self) -> None:
        self.calls = []
        self.chat_id = 10
        self.message_id = 20
        self.photo = None
        self.text = None

    async def edit_text(self, text, reply_markup=None, parse_mode=None):
        self.calls.append(("edit_text", text, reply_markup, parse_mode))
        return self

    async def reply_text(self, text, reply_markup=None, parse_mode=None, do_quote=False):
        self.calls.append(("reply_text", text, reply_markup, parse_mode))
        return self

    async def reply_photo(self, photo, caption=None, reply_markup=None, parse_mode=None, do_quote=False):
        self.calls.append(("reply_photo", caption, reply_markup, parse_mode))
        return self

    async def delete(self):
        self.calls.append(("delete",))


class _FakeMatchingQuery:
    def __init__(self, data: str, message: _FakeMatchingMessage | None = None) -> None:
        self.data = data
        self.message = message or _FakeMatchingMessage()
        self.answers = []

    async def answer(self, text=None, show_alert=False):
        self.answers.append((text, show_alert))


class _FakeMatchingUpdate:
    def __init__(self, query: _FakeMatchingQuery, *, user_id: int = 1, chat_id: int = 10) -> None:
        self.callback_query = query
        self.effective_user = type("User", (), {"id": user_id})()
        self.effective_chat = type("Chat", (), {"id": chat_id})()


class _FakeTextUpdate:
    def __init__(self, text: str, *, user_id: int = 1, chat_id: int = 10) -> None:
        self.message = _FakeMatchingMessage()
        self.message.text = text
        self.message.chat_id = chat_id
        self.effective_user = type("User", (), {"id": user_id})()
        self.effective_chat = type("Chat", (), {"id": chat_id})()
        self.callback_query = None


class _FakeMyDataStore:
    def __init__(self, *samples: SampleAsset, raw_paths: dict[str, Path] | None = None, raw_missing: set[str] | None = None) -> None:
        self.samples = {sample.asset_id: sample for sample in samples}
        self.raw_paths = raw_paths or {}
        self.raw_missing = raw_missing or set()
        self.root_dir = Path(".")

    def list_samples(self, user_id: int):
        return list(self.samples.values())

    def get_sample(self, user_id: int, sample_id: str):
        return self.samples.get(sample_id)

    def get_sample_raw_file(self, user_id: int, sample_id: str):
        if sample_id in self.raw_missing:
            return None
        return f"{sample_id}.raw" if sample_id in self.samples else None

    def resolve_raw_file_path(self, raw_file: str) -> Path:
        return self.raw_paths.get(str(raw_file), Path(raw_file))


class MatchingDomainTests(unittest.TestCase):
    def test_pairwise_match_finds_shared_autosomal_segments(self) -> None:
        with TemporaryDirectory() as temp_dir:
            left_path = Path(temp_dir) / "left.tsv"
            right_path = Path(temp_dir) / "right.tsv"
            shared_rows_left = [
                (f"rs{i}", "1", 1_000_000 + i * 1_000_000, "AA")
                for i in range(10)
            ]
            shared_rows_right = [
                (f"rs{i}", "1", 1_000_000 + i * 1_000_000, "AG")
                for i in range(10)
            ]
            breaker_left = [("rs_break", "1", 12_000_000, "CC")]
            breaker_right = [("rs_break", "1", 12_000_000, "TT")]
            _write_raw(left_path, shared_rows_left + breaker_left)
            _write_raw(right_path, shared_rows_right + breaker_right)

            result = compare_raw_autosomal_match(
                left_path,
                right_path,
                min_estimated_cm=5.0,
                min_shared_snps=5,
                use_default_genetic_map=False,
            )

        self.assertEqual(result.overlap_snps, 11)
        self.assertEqual(result.half_identical_snps, 10)
        self.assertEqual(len(result.segments), 1)
        self.assertEqual(result.segments[0].chromosome, "1")
        self.assertEqual(result.segments[0].snp_count, 10)
        self.assertEqual(result.longest_estimated_cm, 9.0)

    def test_pairwise_result_text_marks_cm_as_estimated(self) -> None:
        with TemporaryDirectory() as temp_dir:
            left_path = Path(temp_dir) / "left.tsv"
            right_path = Path(temp_dir) / "right.tsv"
            rows = [(f"rs{i}", "2", 1_000_000 + i * 1_000_000, "AA") for i in range(10)]
            _write_raw(left_path, rows)
            _write_raw(right_path, rows)
            result = compare_raw_autosomal_match(
                left_path,
                right_path,
                min_estimated_cm=5.0,
                min_shared_snps=5,
                use_default_genetic_map=False,
            )

        left = SampleAsset("left", "Left Sample", "raw-left", [], "2026-05-01T00:00:00")
        right = SampleAsset("right", "Right Sample", "raw-right", [], "2026-05-01T00:00:00")
        text = pairwise_result_text(left, right, result)

        self.assertIn("Total estimated cM", text)
        self.assertIn("<pre>", text)

    def test_pairwise_picker_text_uses_clean_russian_copy(self) -> None:
        left = SampleAsset("left", "Заур", "raw-left", [], "2026-05-01T00:00:00")
        first_text = sample_picker_text([left], side="left")
        second_text = sample_picker_text([], side="right", left_sample=left)

        self.assertIn("🧬 Pairwise match", first_text)
        self.assertIn("Выберите первый sample.", first_text)
        self.assertIn("Sample с raw-файлом:", first_text)
        self.assertNotIn("sample A", first_text)
        self.assertNotIn("Samples with raw", first_text)
        self.assertIn("Первый sample: <b>Заур</b>", second_text)
        self.assertIn("Выберите второй sample.", second_text)
        self.assertNotIn("<b>A:</b>", second_text)
        self.assertNotIn("sample B", second_text)

    def test_pairwise_running_text_uses_clean_status(self) -> None:
        left = SampleAsset("left", "Заур", "raw-left", [], "2026-05-01T00:00:00")
        right = SampleAsset("right", "Азнаур", "raw-right", [], "2026-05-01T00:00:00")
        text = matching_running_text(left, right)

        self.assertIn("🧬 Pairwise match", text)
        self.assertIn("Заур × Азнаур", text)
        self.assertIn("Считаю общие аутосомные сегменты...", text)
        self.assertNotIn("A:", text)
        self.assertNotIn("B:", text)

    def test_pairwise_visual_caption_uses_clean_labels(self) -> None:
        left = SampleAsset("left", "Заур", "raw-left", [], "2026-05-01T00:00:00")
        right = SampleAsset("right", "Азнаур", "raw-right", [], "2026-05-01T00:00:00")
        caption = pairwise_visual_caption(left, right, _pairwise_result())

        self.assertIn("🧬 Pairwise match", caption)
        self.assertIn("Заур × Азнаур", caption)
        self.assertIn("Total:", caption)
        self.assertIn("Longest: 126.90 cM", caption)
        self.assertIn("Segments:", caption)
        self.assertIn("Сигнал: близкое родство", caption)
        self.assertIn("Диапазон: родитель–ребёнок / полные сиблинги / близкий уровень", caption)
        self.assertNotIn("Нт:", caption)
        self.assertNotIn("Hint:", caption)

    def test_pairwise_result_keyboard_uses_save_report_label_and_safe_photo_order(self) -> None:
        left = SampleAsset("left", "Заур", "raw-left", [], "2026-05-01T00:00:00")
        right = SampleAsset("right", "Азнаур", "raw-right", [], "2026-05-01T00:00:00")
        flow_store = MatchingFlowStore()
        context = type(
            "Context",
            (),
            {
                "application": type(
                    "App",
                    (),
                    {
                        "bot_data": {
                            "my_data_store": _FakeMyDataStore(left, right),
                            "matching_flow_store": flow_store,
                        }
                    },
                )()
            },
        )()
        token = flow_store.create(user_id=1, payload={"left_sample_id": left.asset_id})
        message = _FakeMatchingMessage()

        def fake_render(path, **kwargs):
            Path(path).write_bytes(b"png")

        with patch("app.features.matching.menu.compare_raw_autosomal_match", return_value=_pairwise_result()), patch(
            "app.features.matching.menu.render_pairwise_match_png",
            side_effect=fake_render,
        ):
            asyncio.run(show_pairwise_result(message, context, 1, token, right.asset_id, edit_existing=True))

        call_names = [call[0] for call in message.calls]
        self.assertEqual(call_names, ["edit_text", "reply_photo", "delete"])
        reply_markup = message.calls[1][2]
        labels = [button.text for row in reply_markup.inline_keyboard for button in row]
        self.assertIn("💾 Сохранить отчёт", labels)
        self.assertIn("⬅️ Назад", labels)
        self.assertIn("Отмена", labels)
        self.assertNotIn("💾 Сохранить matching", labels)

    def test_compare_all_confirm_uses_clean_russian_copy(self) -> None:
        samples = [
            SampleAsset(f"sample-{index}", f"Sample {index}", f"raw-{index}", [], "2026-05-01T00:00:00")
            for index in range(19)
        ]
        text = all_pairs_confirm_text(samples)

        self.assertIn("📊 Сравнить все sample", text)
        self.assertIn("Sample с raw-файлом: 19", text)
        self.assertIn("Пар для сравнения: 171", text)
        self.assertIn("Карта: GRCh37", text)
        self.assertIn("all-vs-all расчёт", text)
        self.assertIn("⚠️ Если sample больше 15, расчёт может занять заметное время.", text)
        self.assertNotIn("Samples with raw", text)
        self.assertNotIn("Pairs to compare", text)
        self.assertNotIn("Compare all samples", text)

    def test_selected_samples_picker_text_uses_counts(self) -> None:
        text = selected_samples_picker_text(0)

        self.assertIn("✅ Сравнить выбранные sample", text)
        self.assertIn("Выберите sample для сравнения.", text)
        self.assertIn("Выбрано: <b>0 sample</b>", text)
        self.assertIn("Пар для сравнения: <b>0</b>", text)

    def test_compare_all_confirm_button_uses_clean_run_label(self) -> None:
        samples = [
            SampleAsset(f"sample-{index}", f"Sample {index}", f"raw-{index}", [], "2026-05-01T00:00:00")
            for index in range(3)
        ]
        context = type(
            "Context",
            (),
            {
                "application": type(
                    "App",
                    (),
                    {"bot_data": {"my_data_store": _FakeMyDataStore(*samples)}} ,
                )()
            },
        )()
        message = _FakeMatchingMessage()

        asyncio.run(show_all_pairs_confirm(message, context, 1, edit_existing=True))

        text, keyboard, parse_mode = message.calls[-1][1:]
        labels = [button.text for row in keyboard.inline_keyboard for button in row]
        callbacks = [button.callback_data for row in keyboard.inline_keyboard for button in row]

        self.assertIn("📊 Сравнить все sample", text)
        self.assertIn("▶️ Запустить расчёт", labels)
        self.assertIn(f"{MATCHING_CALLBACK_PREFIX}:allrun", callbacks)

    def test_selected_sample_picker_toggles_selection(self) -> None:
        samples = [
            SampleAsset(f"sample-{index}", name, f"raw-{index}", [], "2026-05-01T00:00:00")
            for index, name in enumerate(["Заур", "Азнаур", "Рамазан"], start=1)
        ]
        flow_store = MatchingFlowStore()
        context = type(
            "Context",
            (),
            {
                "application": type(
                    "App",
                    (),
                    {"bot_data": {"my_data_store": _FakeMyDataStore(*samples), "matching_flow_store": flow_store}},
                )()
            },
        )()
        message = _FakeMatchingMessage()

        token = asyncio.run(show_selected_sample_picker(message, context, 1, edit_existing=True))
        text, keyboard = message.calls[-1][1], message.calls[-1][2]
        labels = [button.text for row in keyboard.inline_keyboard for button in row]

        self.assertIn("Выбрано: <b>0 sample</b>", text)
        self.assertIn("Пар для сравнения: <b>0</b>", text)
        self.assertIn("✅ Выбрать все", labels)
        self.assertIn("✅ Готово", labels)
        self.assertIn("🧹 Очистить", labels)
        self.assertIn("⬅️ Назад", labels)
        self.assertIn("Отмена", labels)

        asyncio.run(toggle_selected_sample(message, context, 1, token, samples[0].asset_id))
        asyncio.run(toggle_selected_sample(message, context, 1, token, samples[1].asset_id))
        text, keyboard = message.calls[-1][1], message.calls[-1][2]
        labels = [button.text for row in keyboard.inline_keyboard for button in row]

        self.assertIn("Выбрано: <b>2 sample</b>", text)
        self.assertIn("Пар для сравнения: <b>1</b>", text)
        self.assertIn("[x] 1. Заур", labels)
        self.assertIn("[x] 2. Азнаур", labels)

    def test_selected_samples_done_requires_two_samples(self) -> None:
        samples = [
            SampleAsset("sample-1", "Заур", "raw-1", [], "2026-05-01T00:00:00"),
            SampleAsset("sample-2", "Азнаур", "raw-2", [], "2026-05-01T00:00:00"),
        ]
        flow_store = MatchingFlowStore()
        token = flow_store.create(user_id=1, payload={"mode": "selected_samples", "sample_ids": [samples[0].asset_id]})
        context = type(
            "Context",
            (),
            {
                "application": type(
                    "App",
                    (),
                    {"bot_data": {"my_data_store": _FakeMyDataStore(*samples), "matching_flow_store": flow_store}},
                )()
            },
        )()
        query = _FakeMatchingQuery(f"{MATCHING_CALLBACK_PREFIX}:srun:{token}")
        update = _FakeMatchingUpdate(query)

        asyncio.run(matching_callback_handler(update, context))

        self.assertEqual(query.answers, [("Выберите минимум 2 sample.", True)])

    def test_selected_sample_toggle_keeps_current_page(self) -> None:
        samples = [
            SampleAsset(f"sample-{index}", f"Sample {index}", f"raw-{index}", [], "2026-05-01T00:00:00")
            for index in range(1, 12)
        ]
        flow_store = MatchingFlowStore()
        token = flow_store.create(user_id=1, payload={"mode": "selected_samples", "sample_ids": []})
        context = type(
            "Context",
            (),
            {
                "application": type(
                    "App",
                    (),
                    {"bot_data": {"my_data_store": _FakeMyDataStore(*samples), "matching_flow_store": flow_store}},
                )()
            },
        )()
        message = _FakeMatchingMessage()

        asyncio.run(show_selected_sample_picker(message, context, 1, token=token, page=1, edit_existing=True))
        asyncio.run(toggle_selected_sample(message, context, 1, token, "sample-9", page=1))

        labels = [button.text for row in message.calls[-1][2].inline_keyboard for button in row]
        self.assertIn("[x] 9. Sample 9", labels)
        self.assertIn("10. Sample 10", labels)
        self.assertNotIn("1. Sample 1", labels)

    def test_selected_samples_result_uses_only_selected_subset(self) -> None:
        samples = [
            SampleAsset(f"sample-{index}", f"Sample {index}", f"raw-{index}", [], "2026-05-01T00:00:00")
            for index in range(1, 6)
        ]
        selected = samples[:4]
        flow_store = MatchingFlowStore()
        token = flow_store.create(user_id=1, payload={"mode": "selected_samples", "sample_ids": [sample.asset_id for sample in selected]})
        context = type(
            "Context",
            (),
            {
                "application": type(
                    "App",
                    (),
                    {"bot_data": {"my_data_store": _FakeMyDataStore(*samples), "matching_flow_store": flow_store}},
                )()
            },
        )()
        message = _FakeMatchingMessage()

        def fake_render(path, **kwargs):
            Path(path).write_bytes(b"png")

        with patch("app.features.matching.menu.load_raw_autosomal_profile", side_effect=lambda path: str(path)), patch(
            "app.features.matching.menu.compare_raw_autosomal_profiles",
            return_value=_pairwise_result(),
        ) as compare_mock, patch(
            "app.features.matching.menu.render_all_pairs_match_png",
            side_effect=fake_render,
        ):
            asyncio.run(show_selected_samples_result(message, context, 1, token, edit_existing=True))

        compared_pairs = [(call.args[0], call.args[1]) for call in compare_mock.call_args_list]
        normalized_pairs = {tuple(sorted(pair)) for pair in compared_pairs}
        self.assertEqual(len(compared_pairs), 6)
        self.assertEqual(len(normalized_pairs), 6)
        self.assertTrue(all(left != right for left, right in compared_pairs))
        self.assertTrue(all("sample-5" not in left + right for left, right in compared_pairs))
        caption = next(call[1] for call in message.calls if call[0] == "reply_photo")
        self.assertIn("✅ Сравнить выбранные sample", caption)
        self.assertIn("Sample: 4", caption)
        self.assertIn("Пар: 6", caption)
        self.assertNotIn("Compare all samples", caption)

    def test_selected_samples_visual_caption_shows_best_match(self) -> None:
        left = SampleAsset("left", "Заур", "raw-left", [], "2026-05-01T00:00:00")
        right = SampleAsset("right", "Азнаур", "raw-right", [], "2026-05-01T00:00:00")
        caption = selected_samples_visual_caption([(left, right, _pairwise_result())], 2)

        self.assertIn("✅ Сравнить выбранные sample", caption)
        self.assertIn("Sample: 2", caption)
        self.assertIn("Пар: 1", caption)
        self.assertIn("Лучшее совпадение: Заур × Азнаур · 2444.7 cM", caption)

    def test_snp_input_text_and_rsid_validation(self) -> None:
        text = snp_input_text()

        self.assertIn("🔎 Сравнить SNP", text)
        self.assertIn("Введите rsID", text)
        self.assertIn("rs2455144", text)
        self.assertEqual(normalize_rsid("rs2455144"), "rs2455144")
        self.assertEqual(normalize_rsid("  RS2455144  "), "rs2455144")
        self.assertIsNone(normalize_rsid("2455144"))
        self.assertIsNone(normalize_rsid("chr1:12345"))

    def test_snp_invalid_text_input_shows_validation_message(self) -> None:
        flow_store = MatchingFlowStore()
        flow_store.expect(10, 1, {"action": "snp_input"})
        context = type(
            "Context",
            (),
            {"application": type("App", (), {"bot_data": {"matching_flow_store": flow_store}})()},
        )()
        update = _FakeTextUpdate("chr1:12345")

        with self.assertRaises(Exception):
            asyncio.run(matching_text_input_handler(update, context))

        self.assertEqual(update.message.calls[-1][0], "reply_text")
        self.assertIn("Введите rsID в формате rs2455144.", update.message.calls[-1][1])

    def test_snp_text_input_yields_to_active_ystr_state(self) -> None:
        flow_store = MatchingFlowStore()
        flow_store.expect(10, 1, {"action": "snp_input"})
        context = type(
            "Context",
            (),
            {
                "application": type("App", (), {"bot_data": {"matching_flow_store": flow_store}})(),
                "user_data": {"ystr_pending": {"chat_id": 10, "mode": "test_data"}},
            },
        )()
        update = _FakeTextUpdate("Мамчуев")

        asyncio.run(matching_text_input_handler(update, context))

        self.assertEqual(update.message.calls, [])
        self.assertEqual(flow_store.get_pending(10, 1), {"action": "snp_input"})

    def test_snp_text_input_opens_sample_picker(self) -> None:
        sample = SampleAsset("sample-1", "Заур", "raw-1", [], "2026-05-01T00:00:00")
        flow_store = MatchingFlowStore()
        flow_store.expect(10, 1, {"action": "snp_input"})
        context = type(
            "Context",
            (),
            {
                "application": type(
                    "App",
                    (),
                    {"bot_data": {"my_data_store": _FakeMyDataStore(sample), "matching_flow_store": flow_store}},
                )()
            },
        )()
        update = _FakeTextUpdate("RS2455144")

        with self.assertRaises(Exception):
            asyncio.run(matching_text_input_handler(update, context))

        text, keyboard = update.message.calls[-1][1], update.message.calls[-1][2]
        labels = [button.text for row in keyboard.inline_keyboard for button in row]
        self.assertIn("SNP: <b>rs2455144</b>", text)
        self.assertIn("Выбрано: <b>0 sample</b>", text)
        self.assertIn("1. Заур", labels)

    def test_snp_sample_picker_shows_only_samples_with_raw_and_toggles(self) -> None:
        samples = [
            SampleAsset("sample-1", "Заур", "raw-1", [], "2026-05-01T00:00:00"),
            SampleAsset("sample-2", "Азнаур", "raw-2", [], "2026-05-01T00:00:00"),
        ]
        flow_store = MatchingFlowStore()
        token = flow_store.create(user_id=1, payload={"mode": "snp_lookup", "rsid": "rs2455144", "sample_ids": []})
        context = type(
            "Context",
            (),
            {
                "application": type(
                    "App",
                    (),
                    {
                        "bot_data": {
                            "my_data_store": _FakeMyDataStore(*samples, raw_missing={"sample-2"}),
                            "matching_flow_store": flow_store,
                        }
                    },
                )()
            },
        )()
        message = _FakeMatchingMessage()

        asyncio.run(show_snp_sample_picker(message, context, 1, token=token, edit_existing=True))
        text, keyboard = message.calls[-1][1], message.calls[-1][2]
        labels = [button.text for row in keyboard.inline_keyboard for button in row]

        self.assertIn("🔎 Сравнить SNP", text)
        self.assertIn("SNP: <b>rs2455144</b>", text)
        self.assertIn("Выбрано: <b>0 sample</b>", text)
        self.assertIn("✅ Выбрать все", labels)
        self.assertIn("✅ Готово", labels)
        self.assertIn("🧹 Очистить", labels)
        self.assertIn("1. Заур", labels)
        self.assertNotIn("2. Азнаур", labels)

        asyncio.run(toggle_snp_sample(message, context, 1, token, "sample-1"))
        labels = [button.text for row in message.calls[-1][2].inline_keyboard for button in row]
        self.assertIn("[x] 1. Заур", labels)

    def test_snp_sample_toggle_keeps_current_page(self) -> None:
        samples = [
            SampleAsset(f"sample-{index}", f"Sample {index}", f"raw-{index}", [], "2026-05-01T00:00:00")
            for index in range(1, 12)
        ]
        flow_store = MatchingFlowStore()
        token = flow_store.create(user_id=1, payload={"mode": "snp_lookup", "rsid": "rs7349332", "sample_ids": []})
        context = type(
            "Context",
            (),
            {
                "application": type(
                    "App",
                    (),
                    {"bot_data": {"my_data_store": _FakeMyDataStore(*samples), "matching_flow_store": flow_store}},
                )()
            },
        )()
        message = _FakeMatchingMessage()

        asyncio.run(show_snp_sample_picker(message, context, 1, token=token, page=1, edit_existing=True))
        asyncio.run(toggle_snp_sample(message, context, 1, token, "sample-9", page=1))

        labels = [button.text for row in message.calls[-1][2].inline_keyboard for button in row]
        self.assertIn("[x] 9. Sample 9", labels)
        self.assertIn("10. Sample 10", labels)
        self.assertNotIn("1. Sample 1", labels)

    def test_snp_done_requires_one_sample(self) -> None:
        sample = SampleAsset("sample-1", "Заур", "raw-1", [], "2026-05-01T00:00:00")
        flow_store = MatchingFlowStore()
        token = flow_store.create(user_id=1, payload={"mode": "snp_lookup", "rsid": "rs2455144", "sample_ids": []})
        context = type(
            "Context",
            (),
            {
                "application": type(
                    "App",
                    (),
                    {"bot_data": {"my_data_store": _FakeMyDataStore(sample), "matching_flow_store": flow_store}},
                )()
            },
        )()
        query = _FakeMatchingQuery(f"{MATCHING_CALLBACK_PREFIX}:snprun:{token}")
        update = _FakeMatchingUpdate(query)

        asyncio.run(matching_callback_handler(update, context))

        self.assertEqual(query.answers, [("Выберите минимум 1 sample.", True)])

    def test_lookup_snp_in_raw_finds_genotype_and_handles_missing_or_bad_raw(self) -> None:
        with TemporaryDirectory() as temp_dir:
            raw_path = Path(temp_dir) / "raw.csv"
            raw_path.write_text(
                "\n".join(
                    [
                        "rsid,chromosome,position,genotype",
                        "rs2455144,1,3214732,AA",
                        "rs999,2,10,AG",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            found = lookup_snp_in_raw(raw_path, "RS2455144")
            missing = lookup_snp_in_raw(raw_path, "rs404")
            broken = lookup_snp_in_raw(Path(temp_dir) / "missing.txt", "rs2455144")

        self.assertTrue(found.found)
        self.assertEqual(found.chromosome, "1")
        self.assertEqual(found.position, 3214732)
        self.assertEqual(found.genotype, "AA")
        self.assertFalse(missing.found)
        self.assertEqual(missing.genotype, "--")
        self.assertEqual(broken.genotype, "ошибка чтения raw")

    def test_snp_result_text_has_no_medical_interpretation(self) -> None:
        sample_a = SampleAsset("sample-a", "Заур", "raw-a", [], "2026-05-01T00:00:00")
        sample_b = SampleAsset("sample-b", "Азнаур", "raw-b", [], "2026-05-01T00:00:00")
        with TemporaryDirectory() as temp_dir:
            path_a = Path(temp_dir) / "a.txt"
            path_b = Path(temp_dir) / "b.txt"
            path_a.write_text("rsid\tchromosome\tposition\tgenotype\nrs2455144\t1\t3214732\tAA\n", encoding="utf-8")
            path_b.write_text("rsid\tchromosome\tposition\tgenotype\nrs999\t1\t1\tAG\n", encoding="utf-8")
            rows = [
                (sample_a, lookup_snp_in_raw(path_a, "rs2455144")),
                (sample_b, lookup_snp_in_raw(path_b, "rs2455144")),
            ]
        text = snp_result_text("rs2455144", rows)

        self.assertIn("🔎 Сравнить SNP", text)
        self.assertIn("rs2455144", text)
        self.assertIn("Позиция: chr1:3,214,732", text)
        self.assertIn("Заур — AA", text)
        self.assertIn("Азнаур — --", text)
        self.assertIn("-- = SNP не найден в raw", text)
        self.assertNotIn("ClinVar", text)
        self.assertNotIn("SNPedia", text)

    def test_snp_result_shows_not_found_when_no_sample_has_snp(self) -> None:
        sample = SampleAsset("sample-a", "Заур", "raw-a", [], "2026-05-01T00:00:00")
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "a.txt"
            path.write_text("rsid\tchromosome\tposition\tgenotype\nrs999\t1\t1\tAG\n", encoding="utf-8")
            text = snp_result_text("rs2455144", [(sample, lookup_snp_in_raw(path, "rs2455144"))])

        self.assertIn("SNP не найден в выбранных raw-файлах.", text)
        self.assertIn("Проверьте rsID или выберите другие sample.", text)

    def test_show_snp_result_reads_selected_raw_files(self) -> None:
        sample_a = SampleAsset("sample-a", "Заур", "raw-a", [], "2026-05-01T00:00:00")
        sample_b = SampleAsset("sample-b", "Азнаур", "raw-b", [], "2026-05-01T00:00:00")
        with TemporaryDirectory() as temp_dir:
            path_a = Path(temp_dir) / "a.txt"
            path_b = Path(temp_dir) / "b.txt"
            path_a.write_text("rsid\tchromosome\tposition\tgenotype\nrs2455144\t1\t3214732\tAA\n", encoding="utf-8")
            path_b.write_text("rsid\tchromosome\tposition\tgenotype\nrs2455144\t1\t3214732\tAG\n", encoding="utf-8")
            flow_store = MatchingFlowStore()
            token = flow_store.create(
                user_id=1,
                payload={"mode": "snp_lookup", "rsid": "rs2455144", "sample_ids": [sample_a.asset_id, sample_b.asset_id]},
            )
            context = type(
                "Context",
                (),
                {
                    "application": type(
                        "App",
                        (),
                        {
                            "bot_data": {
                                "my_data_store": _FakeMyDataStore(
                                    sample_a,
                                    sample_b,
                                    raw_paths={
                                        "sample-a.raw": path_a,
                                        "sample-b.raw": path_b,
                                    },
                                ),
                                "matching_flow_store": flow_store,
                            }
                        },
                    )()
                },
            )()
            message = _FakeMatchingMessage()

            asyncio.run(show_snp_result(message, context, 1, token, edit_existing=True))

        text, keyboard = message.calls[-1][1], message.calls[-1][2]
        callbacks = [button.callback_data for row in keyboard.inline_keyboard for button in row]
        self.assertIn("Заур — AA", text)
        self.assertIn("Азнаур — AG", text)
        self.assertIn(f"{MATCHING_CALLBACK_PREFIX}:snps:{token}:0", callbacks)

    def test_saved_matches_uses_clean_russian_copy_and_button_label(self) -> None:
        summary = MatchingRecordSummary(
            match_id="match-1",
            left_sample_id="left",
            left_sample_name="Заур",
            right_sample_id="right",
            right_sample_name="Азнаур",
            total_estimated_cm=2444.7,
            longest_estimated_cm=126.9,
            segment_count=72,
            relationship_hint="Близкое родство",
            created_at="2026-05-01T00:00:00",
        )
        text = saved_matches_text([summary])
        label = saved_match_button_label(summary)

        self.assertIn("💾 Сохранённые matches", text)
        self.assertIn("Сохранено:", text)
        self.assertIn("Выберите сохранённое сравнение.", text)
        self.assertNotIn("Saved:", text)
        self.assertNotIn("Выберите сохраненное pairwise сравнение.", text)
        self.assertEqual(label, "Заур × Азнаур · 2444.7 cM")

    def test_pairwise_visualization_renders_png(self) -> None:
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            left_path = temp_path / "left.tsv"
            right_path = temp_path / "right.tsv"
            rows = [(f"rs{i}", "2", 1_000_000 + i * 1_000_000, "AA") for i in range(10)]
            _write_raw(left_path, rows)
            _write_raw(right_path, rows)
            result = compare_raw_autosomal_match(
                left_path,
                right_path,
                min_estimated_cm=5.0,
                min_shared_snps=5,
                use_default_genetic_map=False,
            )
            output_path = temp_path / "matching.png"

            render_pairwise_match_png(
                output_path,
                left_name="Left Sample",
                right_name="Right Sample",
                result=result,
            )

            with Image.open(output_path) as image:
                self.assertEqual(image.size, (1280, 800))

    def test_all_pairs_visualization_renders_png(self) -> None:
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            left_path = temp_path / "left.tsv"
            right_path = temp_path / "right.tsv"
            rows = [(f"rs{i}", "1", 1_000_000 + i * 1_000_000, "AA") for i in range(10)]
            _write_raw(left_path, rows)
            _write_raw(right_path, rows)
            result = compare_raw_autosomal_match(
                left_path,
                right_path,
                min_estimated_cm=5.0,
                min_shared_snps=5,
                use_default_genetic_map=False,
            )
            left = SampleAsset("left", "Left Sample", "raw-left", [], "2026-05-01T00:00:00")
            right = SampleAsset("right", "Right Sample", "raw-right", [], "2026-05-01T00:00:00")
            output_path = temp_path / "matching_all.png"

            render_all_pairs_match_png(
                output_path,
                results=[(left, right, result)],
                sample_count=2,
            )

            with Image.open(output_path) as image:
                self.assertEqual(image.size, (1280, 800))

    def test_relationship_hint_handles_no_significant_segments(self) -> None:
        self.assertEqual(relationship_hint(0.0, 0.0), "Значимых сегментов выше порога не найдено")
        self.assertEqual(relationship_hint(0.0, 0.0, lang="en"), "No significant segments above the threshold")

    def test_genetic_map_changes_segment_cm_by_interpolation(self) -> None:
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            map_path = temp_path / "test.map"
            map_path.write_text(
                "\n".join(
                    [
                        "1 m1 0.0 1000000",
                        "1 m2 2.0 5000000",
                        "1 m3 10.0 10000000",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            left_path = temp_path / "left.tsv"
            right_path = temp_path / "right.tsv"
            rows = [(f"rs{i}", "1", 1_000_000 + i * 1_000_000, "AA") for i in range(10)]
            _write_raw(left_path, rows)
            _write_raw(right_path, rows)

            result = compare_raw_autosomal_match(
                left_path,
                right_path,
                min_estimated_cm=5.0,
                min_shared_snps=5,
                genetic_map=GeneticMap.from_plink_map(map_path),
            )

        self.assertEqual(len(result.segments), 1)
        self.assertEqual(result.longest_estimated_cm, 10.0)

    def test_matching_callback_data_stays_under_telegram_limit(self) -> None:
        asset_id = "20260430185412345678-12345678"
        record_id = "20260510222712345678-12345678"
        callbacks = [
            f"{MATCHING_CALLBACK_PREFIX}:root",
            f"{MATCHING_CALLBACK_PREFIX}:pair:0",
            f"{MATCHING_CALLBACK_PREFIX}:selected",
            f"{MATCHING_CALLBACK_PREFIX}:all",
            f"{MATCHING_CALLBACK_PREFIX}:allrun",
            f"{MATCHING_CALLBACK_PREFIX}:snp",
            f"{MATCHING_CALLBACK_PREFIX}:saved",
            f"{MATCHING_CALLBACK_PREFIX}:save:12345678",
            f"{MATCHING_CALLBACK_PREFIX}:m:{record_id}",
            f"{MATCHING_CALLBACK_PREFIX}:a:{asset_id}",
            f"{MATCHING_CALLBACK_PREFIX}:pb:12345678:0",
            f"{MATCHING_CALLBACK_PREFIX}:b:12345678:{asset_id}",
            f"{MATCHING_CALLBACK_PREFIX}:ss:12345678:0",
            f"{MATCHING_CALLBACK_PREFIX}:st:12345678:{asset_id}",
            f"{MATCHING_CALLBACK_PREFIX}:st:12345678:{asset_id}:1",
            f"{MATCHING_CALLBACK_PREFIX}:sall:12345678",
            f"{MATCHING_CALLBACK_PREFIX}:sall:12345678:1",
            f"{MATCHING_CALLBACK_PREFIX}:sclr:12345678",
            f"{MATCHING_CALLBACK_PREFIX}:sclr:12345678:1",
            f"{MATCHING_CALLBACK_PREFIX}:srun:12345678",
            f"{MATCHING_CALLBACK_PREFIX}:snps:12345678:0",
            f"{MATCHING_CALLBACK_PREFIX}:snpt:12345678:{asset_id}",
            f"{MATCHING_CALLBACK_PREFIX}:snpt:12345678:{asset_id}:1",
            f"{MATCHING_CALLBACK_PREFIX}:snpall:12345678",
            f"{MATCHING_CALLBACK_PREFIX}:snpall:12345678:1",
            f"{MATCHING_CALLBACK_PREFIX}:snpclr:12345678",
            f"{MATCHING_CALLBACK_PREFIX}:snpclr:12345678:1",
            f"{MATCHING_CALLBACK_PREFIX}:snprun:12345678",
        ]

        for callback in callbacks:
            self.assertLessEqual(len(callback.encode("utf-8")), 64, callback)

    def test_matching_store_saves_pairwise_result_once_per_pair(self) -> None:
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            left_path = temp_path / "left.tsv"
            right_path = temp_path / "right.tsv"
            rows = [(f"rs{i}", "1", 1_000_000 + i * 1_000_000, "AA") for i in range(10)]
            _write_raw(left_path, rows)
            _write_raw(right_path, rows)
            result = compare_raw_autosomal_match(
                left_path,
                right_path,
                min_estimated_cm=5.0,
                min_shared_snps=5,
                use_default_genetic_map=False,
            )
            store = MatchingStore(temp_path / "matching")
            left = SampleAsset("left", "Left Sample", "raw-left", [], "2026-05-01T00:00:00")
            right = SampleAsset("right", "Right Sample", "raw-right", [], "2026-05-01T00:00:00")

            first = store.save_pairwise_match(1, left, right, result)
            second = store.save_pairwise_match(1, right, left, result)
            matches = store.list_matches(1)

        self.assertEqual(first.summary.match_id, second.summary.match_id)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].total_estimated_cm, result.total_estimated_cm)


if __name__ == "__main__":
    unittest.main()
