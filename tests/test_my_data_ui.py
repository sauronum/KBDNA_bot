from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.features.coordinate_space.reports import CoordinateSpaceReportStore, CoordinateSpaceResult
from app.features.my_data.handlers import (
    QUICK_G25_RESULT_ACTION,
    _clear_my_data_pending,
    _standalone_my_data_coordinates,
    _visible_my_data_coordinates,
    normalize_sample_snp_rsid,
    show_coordinate_space_report_detail_menu,
    show_coordinate_space_report_delete_prompt_menu,
)
from app.features.my_data.state import MyDataFlowStore
from app.features.my_data.snp_lookup import lookup_snp_in_sample
from app.features.my_data.ui import MY_DATA_CALLBACK_PREFIX
from app.features.my_data.storage import CoordinateAsset, MyDataStore, RawFileAsset, SampleAsset
from app.features.my_data.ui import (
    build_coordinate_items_keyboard,
    build_coordinates_keyboard,
    build_add_coordinates_keyboard,
    build_extract_coordinates_keyboard,
    build_my_data_keyboard,
    build_new_g25_profile_keyboard,
    build_sample_items_keyboard,
    build_sample_matching_reports_keyboard,
    build_quick_g25_result_keyboard,
    build_coordinate_space_report_delete_prompt_keyboard,
    build_coordinate_space_report_detail_keyboard,
    build_coordinate_space_report_not_found_keyboard,
    build_sample_coordinate_space_reports_keyboard,
    build_sample_coordinates_menu_keyboard,
    build_sample_detail_keyboard,
    build_sample_reports_keyboard,
    build_sample_snp_lookup_input_keyboard,
    build_sample_snp_lookup_result_keyboard,
    build_upload_raw_keyboard,
    add_coordinates_text,
    coordinate_detail_text,
    coordinates_text,
    create_sample_text,
    extract_coordinates_text,
    my_data_text,
    new_g25_profile_text,
    coordinate_space_report_delete_prompt_text,
    coordinate_space_report_detail_text,
    coordinate_space_report_not_found_text,
    coordinate_space_report_visual_caption,
    results_text,
    matching_report_button_label,
    quick_g25_result_text,
    raw_file_detail_text,
    sample_coordinate_space_reports_text,
    sample_coordinates_menu_text,
    sample_detail_text,
    sample_reports_text,
    sample_snp_lookup_input_text,
    sample_snp_lookup_invalid_text,
    sample_snp_lookup_no_raw_text,
    sample_snp_lookup_result_text,
    upload_raw_text,
    view_coordinates_text,
    view_samples_text,
)
from app.features.matching.storage import MatchingRecordSummary


class _FakeMessage:
    def __init__(self, *, photo: bool = False, fail_reply_photo: bool = False, fail_edit_text: bool = False) -> None:
        self.photo = [object()] if photo else []
        self.chat_id = 10
        self.message_id = 1
        self.calls: list[tuple[str, object, object]] = []
        self.fail_reply_photo = fail_reply_photo
        self.fail_edit_text = fail_edit_text

    async def edit_text(self, text, reply_markup=None, parse_mode=None):
        if self.fail_edit_text:
            raise RuntimeError("edit_text failed")
        self.calls.append(("edit_text", text, reply_markup))
        return self

    async def edit_caption(self, caption=None, reply_markup=None):
        self.calls.append(("edit_caption", caption, reply_markup))
        return self

    async def reply_text(self, text, reply_markup=None, parse_mode=None, do_quote=False):
        self.calls.append(("reply_text", text, reply_markup))
        return _FakeMessage()

    async def reply_photo(self, photo, caption=None, reply_markup=None, do_quote=False):
        if self.fail_reply_photo:
            raise RuntimeError("reply_photo failed")
        self.calls.append(("reply_photo", caption, reply_markup))
        return _FakeMessage(photo=True)

    async def delete(self):
        self.calls.append(("delete", None, None))


class _FakeQuery:
    def __init__(self) -> None:
        self.answers: list[tuple[str | None, bool]] = []

    async def answer(self, text=None, show_alert=False):
        self.answers.append((text, show_alert))


class MyDataUiTests(unittest.TestCase):
    def test_visible_my_data_coordinates_hide_k36_records(self) -> None:
        g25 = CoordinateAsset(
            asset_id="g25",
            display_name="Sample G25",
            target_name="Sample",
            coordinate_type="g25",
            g25_line="",
            input_mode="manual",
            created_at="2026-05-10T22:00:00",
        )
        k36 = CoordinateAsset(
            asset_id="k36",
            display_name="Sample K36",
            target_name="Sample",
            coordinate_type="K36",
            g25_line="",
            input_mode="raw-file-k36",
            created_at="2026-05-10T22:00:00",
        )

        self.assertEqual(_visible_my_data_coordinates([g25, k36]), [g25])

    def test_standalone_my_data_coordinates_exclude_sample_coordinates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = MyDataStore(Path(tmp))
            raw_path = Path(tmp) / "raw.txt"
            raw_path.write_text("raw", encoding="utf-8")
            raw = store.save_raw_file(1, raw_path, original_file_name="raw.txt", display_name="Raw")
            sample = store.save_sample(1, display_name="Sample", raw_file_id=raw.asset_id)
            attached = store.save_coordinate(
                1,
                display_name="Sample G25",
                target_name="Sample",
                coordinate_type="g25",
                g25_line="Sample,1,2",
                input_mode="raw-file",
            )
            standalone = store.save_coordinate(
                1,
                display_name="Standalone G25",
                target_name="Standalone",
                coordinate_type="g25",
                g25_line="Standalone,1,2",
                input_mode="manual",
            )
            assert sample is not None
            store.attach_coordinate_to_sample(1, sample.asset_id, attached.asset_id)

            self.assertEqual(_standalone_my_data_coordinates(store, 1), [standalone])

    def test_clearing_quick_g25_pending_removes_temp_raw_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_store = MyDataStore(Path(tmp) / "my_data")
            flow_store = MyDataFlowStore()
            temp_path = data_store.build_temp_path(1, "raw.txt")
            temp_path.write_text("raw", encoding="utf-8")
            flow_store.expect(
                10,
                1,
                QUICK_G25_RESULT_ACTION,
                99,
                payload={"raw_temp_path": str(temp_path)},
            )
            context = SimpleNamespace(
                application=SimpleNamespace(
                    bot_data={
                        "my_data_store": data_store,
                        "my_data_flow_store": flow_store,
                    }
                )
            )

            _clear_my_data_pending(context, 10, 1)

            self.assertFalse(temp_path.exists())
            self.assertIsNone(flow_store.get_action(10, 1))

    def test_sample_matching_reports_link_saved_pairwise_matches(self) -> None:
        sample = SampleAsset("sample-a", "A", "raw-a", [], "2026-05-10T22:00:00")
        match = MatchingRecordSummary(
            match_id="20260510222712345678-12345678",
            left_sample_id=sample.asset_id,
            left_sample_name="A",
            right_sample_id="sample-b",
            right_sample_name="B",
            total_estimated_cm=123.4,
            longest_estimated_cm=20.0,
            segment_count=3,
            relationship_hint="test",
            created_at="2026-05-10T22:27:00",
        )

        label = matching_report_button_label(sample.asset_id, match)
        keyboard = build_sample_matching_reports_keyboard(sample.asset_id, [match])
        callback = keyboard.inline_keyboard[0][0].callback_data

        self.assertEqual(label, "B: 123.4 cM")
        self.assertEqual(callback, f"{MY_DATA_CALLBACK_PREFIX}:sample_match:{match.match_id}")
        self.assertLessEqual(len(callback.encode("utf-8")), 64)

    def test_sample_reports_root_uses_product_labels(self) -> None:
        sample = SampleAsset("sample-a", "Азнаур", "raw-a", [], "2026-05-24T08:11:00")
        text = sample_reports_text(sample)
        keyboard = build_sample_reports_keyboard(sample.asset_id)
        labels = [row[0].text for row in keyboard.inline_keyboard[:6]]

        self.assertIn("📊 Reports", text)
        self.assertIn("Sample: Азнаур", text)
        self.assertIn("Сохранённые отчёты по этому sample.", text)
        self.assertEqual(labels, [
            "🧭 Coordinate spaces",
            "🧬 Admixture",
            "🧩 Matching",
            "🧱 AdmixLab",
            "🧾 Traits",
            "🌿 Haplogroups",
        ])
        self.assertTrue(all("Отчеты" not in label for label in labels))

    def test_sample_reports_can_use_custom_back_callback(self) -> None:
        keyboard = build_sample_reports_keyboard("sample-a", back_callback="main:privacy_reports")

        self.assertEqual([button.callback_data for button in keyboard.inline_keyboard[-1]], ["main:privacy_reports", "main:cancel"])

    def test_coordinate_reports_list_uses_clean_copy_and_emoji_titles(self) -> None:
        sample = SampleAsset("sample-a", "Азнаур", "raw-a", [], "2026-05-24T08:11:00")
        report = CoordinateSpaceResult(
            result_id="report-a",
            sample_id=sample.asset_id,
            coordinate_id="coord-a",
            title="Caucasus / Steppe",
            mode="region",
            coordinate_system="G25",
            session_id="ready_made",
            preset_id="ready_made_caucasus_steppe",
            summary_lines=["Sample: Азнаур", "Closest region: NW Caucasus"],
            created_at="2026-05-24T08:11:00Z",
        )
        text = sample_coordinate_space_reports_text(sample, [report])
        keyboard = build_sample_coordinate_space_reports_keyboard(sample.asset_id, [report])

        self.assertIn("🧭 Coordinate spaces", text)
        self.assertIn("Sample: Азнаур", text)
        self.assertIn("Отчётов: 1", text)
        self.assertIn("Выберите сохранённый отчёт.", text)
        self.assertEqual(keyboard.inline_keyboard[0][0].text, "1. ⛰ Caucasus / Steppe")
        self.assertEqual(keyboard.inline_keyboard[0][0].callback_data, "my_data:scr:report-a")

    def test_empty_coordinate_reports_list_uses_clean_copy(self) -> None:
        sample = SampleAsset("sample-a", "Азнаур", "raw-a", [], "2026-05-24T08:11:00")
        text = sample_coordinate_space_reports_text(sample, [])

        self.assertIn("🧭 Coordinate spaces", text)
        self.assertIn("Отчётов пока нет.", text)
        self.assertIn("Сохраните результат из раздела DNA Lab → Coordinates.", text)

    def test_old_coordinate_report_fallback_detail_is_not_debug_dump(self) -> None:
        report = CoordinateSpaceResult(
            result_id="report-a",
            sample_id="sample-a",
            coordinate_id="coord-a",
            title="Caucasus / Steppe",
            mode="region",
            coordinate_system="G25",
            session_id="ready_made",
            preset_id="ready_made_caucasus_steppe",
            summary_lines=["Sample: Азнаур", "Closest region: NW Caucasus"],
            top_populations=[],
            created_at="2026-05-24T08:11:00Z",
        )
        text = coordinate_space_report_detail_text(report)
        keyboard = build_coordinate_space_report_detail_keyboard(report.result_id, report.sample_id)
        labels = [button.text for row in keyboard.inline_keyboard for button in row]

        self.assertIn("⛰ Caucasus / Steppe", text)
        self.assertIn("Sample: Азнаур", text)
        self.assertIn("Тип: региональный обзор", text)
        self.assertIn("Система: G25", text)
        self.assertIn("Создан: 24.05.2026, 08:11", text)
        self.assertIn("Ближайшая зона: NW Caucasus", text)
        self.assertNotIn("Mode:", text)
        self.assertNotIn("Coordinate system:", text)
        self.assertNotIn("Created:", text)
        self.assertNotIn("Closest region:", text)
        self.assertIn("🗑 Удалить отчёт", labels)

    def test_population_coordinate_report_fallback_uses_population_labels(self) -> None:
        report = CoordinateSpaceResult(
            result_id="report-a",
            sample_id="sample-a",
            coordinate_id="coord-a",
            title="Caucasus / Steppe",
            mode="populations",
            coordinate_system="G25",
            session_id="ready_made",
            preset_id="north_caucasus_detail",
            summary_lines=["Sample: Азнаур", "Closest cluster: NW Caucasus"],
            top_populations=["Balkar", "Karachay"],
            created_at="2026-05-24T08:11:00Z",
        )
        text = coordinate_space_report_detail_text(report)

        self.assertIn("Тип: популяционный обзор", text)
        self.assertIn("Ближайшая популяция: Balkar", text)
        self.assertIn("Регион: NW Caucasus", text)
        self.assertNotIn("Top populations:", text)

    def test_coordinate_report_delete_prompt_keyboard_returns_to_detail(self) -> None:
        self.assertEqual(coordinate_space_report_delete_prompt_text(), "Удалить этот отчёт?")
        keyboard = build_coordinate_space_report_delete_prompt_keyboard("report-a")

        self.assertEqual(keyboard.inline_keyboard[0][0].text, "✅ Да, удалить")
        self.assertEqual(keyboard.inline_keyboard[0][0].callback_data, "my_data:scrdc:report-a")
        self.assertEqual(keyboard.inline_keyboard[1][0].callback_data, "my_data:scr:report-a")

    def test_coordinate_report_callbacks_fit_telegram_limit(self) -> None:
        long_report_id = "2026052417541915862222-abcdef12"
        sample = SampleAsset("sample-a", "Азнаур", "raw-a", [], "2026-05-24T08:11:00")
        report = CoordinateSpaceResult(
            result_id=long_report_id,
            sample_id=sample.asset_id,
            coordinate_id="coord-a",
            title="North Caucasus",
            mode="region",
            coordinate_system="G25",
            session_id="ready_made",
        )
        list_keyboard = build_sample_coordinate_space_reports_keyboard(sample.asset_id, [report])
        detail_keyboard = build_coordinate_space_report_detail_keyboard(report.result_id, report.sample_id)
        delete_keyboard = build_coordinate_space_report_delete_prompt_keyboard(report.result_id)
        callbacks = [
            button.callback_data
            for keyboard in (list_keyboard, detail_keyboard, delete_keyboard)
            for row in keyboard.inline_keyboard
            for button in row
            if button.callback_data
        ]

        self.assertTrue(all(len(callback.encode("utf-8")) <= 64 for callback in callbacks))

    def test_coordinate_report_store_saves_and_deletes_png_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image_path = root / "result.png"
            image_path.write_bytes(b"\x89PNG\r\n\x1a\nfake")
            store = CoordinateSpaceReportStore(root / "coordinate_space" / "reports")

            report = store.save_result(
                1,
                sample_id="sample-a",
                coordinate_id="coord-a",
                title="Global",
                mode="region",
                coordinate_system="G25",
                session_id="ready_made",
                preset_id="global",
                summary_lines=["Sample: Азнаур", "Closest region: Caucasus"],
                image_source_path=image_path,
                caption="🌍 Global\n\nG25-профиль: Азнаур",
            )
            artifact_path = store.resolve_image_path(report)

            self.assertTrue(report.image_path)
            self.assertEqual(report.caption, "🌍 Global\n\nG25-профиль: Азнаур")
            self.assertIsNotNone(artifact_path)
            assert artifact_path is not None
            self.assertTrue(artifact_path.exists())
            self.assertEqual(len(store.list_results(1, "sample-a")), 1)

            deleted = store.delete_result(1, report.result_id)

            self.assertIsNotNone(deleted)
            self.assertFalse(artifact_path.exists())
            self.assertEqual(store.list_results(1, "sample-a"), [])

    def test_coordinate_report_store_deletes_old_report_without_png(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = CoordinateSpaceReportStore(Path(tmp) / "coordinate_space" / "reports")
            report = store.save_result(
                1,
                sample_id="sample-a",
                coordinate_id="coord-a",
                title="Global",
                mode="region",
                coordinate_system="G25",
                session_id="ready_made",
                preset_id="global",
                summary_lines=["Sample: Азнаур"],
            )

            deleted = store.delete_result(1, report.result_id)

            self.assertIsNotNone(deleted)
            self.assertEqual(store.list_results(1, "sample-a"), [])

    def test_coordinate_report_store_finds_old_index_only_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = CoordinateSpaceReportStore(Path(tmp) / "coordinate_space" / "reports")
            report = store.save_result(
                1,
                sample_id="sample-a",
                coordinate_id="coord-a",
                title="Caucasus / Steppe",
                mode="region",
                coordinate_system="G25",
                session_id="ready_made",
                preset_id="ready_made_caucasus_steppe",
                summary_lines=["Sample: Расул", "Closest region: NW Caucasus"],
            )
            (store.root_dir / "users" / "1" / "reports" / f"{report.result_id}.json").unlink()

            found = store.find_result(1, report.result_id)

            self.assertIsNotNone(found)
            assert found is not None
            self.assertEqual(found.title, "Caucasus / Steppe")
            self.assertIn("Sample: Расул", found.summary_lines)

    def test_coordinate_reports_list_callback_uses_real_report_id_that_store_can_open(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = CoordinateSpaceReportStore(Path(tmp) / "coordinate_space" / "reports")
            report = store.save_result(
                1,
                sample_id="sample-a",
                coordinate_id="coord-a",
                title="Caucasus / Steppe",
                mode="region",
                coordinate_system="G25",
                session_id="ready_made",
                preset_id="ready_made_caucasus_steppe",
                summary_lines=["Sample: Расул", "Closest region: NW Caucasus"],
            )
            reports = store.list_results(1, "sample-a")
            keyboard = build_sample_coordinate_space_reports_keyboard("sample-a", reports)
            callback = keyboard.inline_keyboard[0][0].callback_data
            report_id = callback.rsplit(":", 1)[-1]

            self.assertEqual(callback, f"my_data:scr:{report.result_id}")
            self.assertEqual(report_id, report.result_id)
            self.assertIsNotNone(store.find_result(1, report_id))

    def test_missing_coordinate_report_alerts_without_showing_new_sample(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report_store = CoordinateSpaceReportStore(Path(tmp) / "coordinate_space" / "reports")
            context = SimpleNamespace(application=SimpleNamespace(bot_data={"coordinate_space_report_store": report_store}))
            message = _FakeMessage()
            query = _FakeQuery()

            asyncio.run(show_coordinate_space_report_detail_menu(message, context, 1, "missing-report", edit_existing=True, query=query))

            self.assertEqual(message.calls, [])
            self.assertEqual(query.answers, [("Отчёт не найден. Обновите список.", True)])

    def test_missing_coordinate_report_fallback_has_no_new_sample_button(self) -> None:
        text = coordinate_space_report_not_found_text()
        keyboard = build_coordinate_space_report_not_found_keyboard()
        labels = [button.text for row in keyboard.inline_keyboard for button in row]

        self.assertIn("Отчёт не найден. Обновите список.", text)
        self.assertNotIn("➕ Новый sample", labels)

    def test_missing_coordinate_report_delete_prompt_alerts_without_editing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report_store = CoordinateSpaceReportStore(Path(tmp) / "coordinate_space" / "reports")
            context = SimpleNamespace(application=SimpleNamespace(bot_data={"coordinate_space_report_store": report_store}))
            message = _FakeMessage()
            query = _FakeQuery()

            asyncio.run(show_coordinate_space_report_delete_prompt_menu(message, context, 1, "missing-report", edit_existing=True, query=query))

            self.assertEqual(message.calls, [])
            self.assertEqual(query.answers, [("Отчёт не найден. Обновите список.", True)])

    def test_visual_coordinate_report_detail_uses_photo_path_and_clean_caption(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image_path = root / "result.png"
            image_path.write_bytes(b"\x89PNG\r\n\x1a\nfake")
            report_store = CoordinateSpaceReportStore(root / "coordinate_space" / "reports")
            report = report_store.save_result(
                1,
                sample_id="sample-a",
                coordinate_id="coord-a",
                title="Global",
                mode="region",
                coordinate_system="G25",
                session_id="ready_made",
                preset_id="global",
                summary_lines=["Sample: Азнаур", "Closest region: Caucasus"],
                image_source_path=image_path,
                caption="🌍 Global\n\nG25-профиль: Азнаур\nБлижайшая зона: Caucasus",
            )
            context = SimpleNamespace(application=SimpleNamespace(bot_data={"coordinate_space_report_store": report_store}))
            message = _FakeMessage()

            self.assertNotIn("Top:", coordinate_space_report_visual_caption(report))

            asyncio.run(show_coordinate_space_report_detail_menu(message, context, 1, report.result_id, edit_existing=True))

            self.assertEqual(message.calls[0][0], "reply_photo")
            self.assertEqual(message.calls[1][0], "delete")
            self.assertIn("🌍 Global", message.calls[0][1])
            self.assertNotIn("Top:", message.calls[0][1])
            markup = message.calls[0][2]
            labels = [button.text for row in markup.inline_keyboard for button in row]
            self.assertIn("🗑 Удалить отчёт", labels)
            self.assertEqual(markup.inline_keyboard[1][0].callback_data, "my_data:sample_pca_results:sample-a")

    def test_visual_coordinate_report_send_photo_failure_falls_back_without_delete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image_path = root / "result.png"
            image_path.write_bytes(b"\x89PNG\r\n\x1a\nfake")
            report_store = CoordinateSpaceReportStore(root / "coordinate_space" / "reports")
            report = report_store.save_result(
                1,
                sample_id="sample-a",
                coordinate_id="coord-a",
                title="Global",
                mode="region",
                coordinate_system="G25",
                session_id="ready_made",
                preset_id="global",
                summary_lines=["Sample: Азнаур", "Closest region: Caucasus"],
                image_source_path=image_path,
                caption="🌍 Global\n\nG25-профиль: Азнаур",
            )
            context = SimpleNamespace(application=SimpleNamespace(bot_data={"coordinate_space_report_store": report_store}))
            message = _FakeMessage(fail_reply_photo=True)

            asyncio.run(show_coordinate_space_report_detail_menu(message, context, 1, report.result_id, edit_existing=True))

            self.assertEqual([call[0] for call in message.calls], ["edit_text"])
            self.assertIn("🌍 Global", message.calls[0][1])
            self.assertIn("🗑 Удалить отчёт", [button.text for row in message.calls[0][2].inline_keyboard for button in row])

    def test_coordinate_report_missing_image_path_opens_fallback_detail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report_store = CoordinateSpaceReportStore(Path(tmp) / "coordinate_space" / "reports")
            report = report_store.save_result(
                1,
                sample_id="sample-a",
                coordinate_id="coord-a",
                title="Global",
                mode="region",
                coordinate_system="G25",
                session_id="ready_made",
                preset_id="global",
                summary_lines=["Sample: Азнаур", "Closest region: Caucasus"],
            )
            context = SimpleNamespace(application=SimpleNamespace(bot_data={"coordinate_space_report_store": report_store}))
            message = _FakeMessage()

            asyncio.run(show_coordinate_space_report_detail_menu(message, context, 1, report.result_id, edit_existing=True))

            self.assertEqual([call[0] for call in message.calls], ["edit_text"])
            self.assertIn("Ближайшая зона: Caucasus", message.calls[0][1])

    def test_coordinate_report_missing_image_file_opens_fallback_detail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image_path = root / "result.png"
            image_path.write_bytes(b"\x89PNG\r\n\x1a\nfake")
            report_store = CoordinateSpaceReportStore(root / "coordinate_space" / "reports")
            report = report_store.save_result(
                1,
                sample_id="sample-a",
                coordinate_id="coord-a",
                title="Global",
                mode="region",
                coordinate_system="G25",
                session_id="ready_made",
                preset_id="global",
                summary_lines=["Sample: Азнаур", "Closest region: Caucasus"],
                image_source_path=image_path,
            )
            artifact_path = report_store.resolve_image_path(report)
            assert artifact_path is not None
            artifact_path.unlink()
            context = SimpleNamespace(application=SimpleNamespace(bot_data={"coordinate_space_report_store": report_store}))
            message = _FakeMessage()

            asyncio.run(show_coordinate_space_report_detail_menu(message, context, 1, report.result_id, edit_existing=True))

            self.assertEqual([call[0] for call in message.calls], ["edit_text"])
            self.assertIn("Ближайшая зона: Caucasus", message.calls[0][1])

    def test_coordinate_report_fallback_edit_failure_sends_new_detail_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report_store = CoordinateSpaceReportStore(Path(tmp) / "coordinate_space" / "reports")
            report = report_store.save_result(
                1,
                sample_id="sample-a",
                coordinate_id="coord-a",
                title="Global",
                mode="region",
                coordinate_system="G25",
                session_id="ready_made",
                preset_id="global",
                summary_lines=["Sample: Азнаур", "Closest region: Caucasus"],
            )
            context = SimpleNamespace(application=SimpleNamespace(bot_data={"coordinate_space_report_store": report_store}))
            message = _FakeMessage(fail_edit_text=True)
            query = _FakeQuery()

            asyncio.run(show_coordinate_space_report_detail_menu(message, context, 1, report.result_id, edit_existing=True, query=query))

            self.assertEqual([call[0] for call in message.calls], ["reply_text"])
            self.assertIn("🌍 Global", message.calls[0][1])
            self.assertEqual(query.answers, [(None, False)])

    def test_coordinate_report_store_falls_back_to_index_when_record_is_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = CoordinateSpaceReportStore(Path(tmp) / "coordinate_space" / "reports")
            report = store.save_result(
                1,
                sample_id="sample-a",
                coordinate_id="coord-a",
                title="North Caucasus",
                mode="region",
                coordinate_system="G25",
                session_id="ready_made",
                summary_lines=["Sample: Мухаммад М.", "Closest region: North Caucasus"],
            )
            record_path = store.root_dir / "users" / "1" / "reports" / f"{report.result_id}.json"
            record_path.write_text('{"result_id": "%s"}' % report.result_id, encoding="utf-8")

            found = store.find_result(1, report.result_id)

            self.assertIsNotNone(found)
            assert found is not None
            self.assertEqual(found.title, "North Caucasus")
            self.assertIn("Sample: Мухаммад М.", found.summary_lines)

    def test_my_data_sample_dashboard_uses_english_copy(self) -> None:
        sample = SampleAsset("sample-a", "A", "raw-a", [], "2026-05-10T22:00:00")
        text = sample_detail_text(
            sample,
            raw_file=None,
            coordinate_count=0,
            report_counts={"coordinate_spaces": 0, "admixture": 0, "matching": 0, "traits": 0, "haplogroups": 0},
            lang="en",
        )
        keyboard = build_sample_detail_keyboard(sample, lang="en")
        labels = [row[0].text for row in keyboard.inline_keyboard[:5]]

        self.assertIn("<b>🧬 Sample · A</b>", text)
        self.assertIn("<b>Created:</b> 10.05.2026", text)
        self.assertIn("raw file not found", text)
        self.assertIn("Source raw: raw file not found", text)
        self.assertIn("G25 profiles: none", text)
        self.assertIn("🧭 Coordinate spaces: 0", text)
        self.assertIn("<b>Total reports:</b> 0", text)
        self.assertEqual(labels, ["📊 Reports", "🧬 Source raw", "🔎 SNP lookup", "📍 Coordinates", "✏️ Rename"])

    def test_sample_detail_contains_single_sample_snp_lookup_button(self) -> None:
        sample = SampleAsset("sample-a", "Заур", "raw-a", [], "2026-05-10T22:00:00")
        keyboard = build_sample_detail_keyboard(sample)
        labels = [button.text for row in keyboard.inline_keyboard for button in row]
        callbacks = [button.callback_data for row in keyboard.inline_keyboard for button in row if button.callback_data]

        self.assertIn("🔎 Поиск SNP", labels)
        self.assertIn(f"{MY_DATA_CALLBACK_PREFIX}:snp:{sample.asset_id}", callbacks)

    def test_sample_snp_lookup_input_and_normalization(self) -> None:
        sample = SampleAsset("sample-a", "Заур", "raw-a", [], "2026-05-10T22:00:00")
        text = sample_snp_lookup_input_text(sample)
        keyboard = build_sample_snp_lookup_input_keyboard(sample.asset_id)

        self.assertIn("🔎 Поиск SNP", text)
        self.assertIn("Sample:", text)
        self.assertIn("Введите rsID", text)
        self.assertIn("rs2455144", text)
        self.assertEqual(normalize_sample_snp_rsid("RS2455144"), "rs2455144")
        self.assertEqual(normalize_sample_snp_rsid(" 2455144 "), "rs2455144")
        self.assertIsNone(normalize_sample_snp_rsid("chr1:12345"))
        self.assertIn("Введите rsID в формате rs123456.", sample_snp_lookup_invalid_text())
        self.assertEqual([button.callback_data for button in keyboard.inline_keyboard[-1]], [f"{MY_DATA_CALLBACK_PREFIX}:sample_item:sample-a", "main:cancel"])

    def test_lookup_snp_in_sample_result_and_no_raw_copy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = MyDataStore(Path(tmp) / "my_data")
            raw_path = Path(tmp) / "raw.tsv"
            raw_path.write_text("rsid\tchromosome\tposition\tgenotype\nrs2455144\t1\t12345678\tAG\n", encoding="utf-8")
            raw = store.save_raw_file(1, raw_path, original_file_name="raw.tsv", display_name="Заур raw")
            sample = store.save_sample(1, display_name="Заур", raw_file_id=raw.asset_id)
            assert sample is not None

            result = lookup_snp_in_sample(store, 1, sample, "rs2455144")
            text = sample_snp_lookup_result_text(sample, result)
            keyboard = build_sample_snp_lookup_result_keyboard(sample.asset_id)

        self.assertIn("Sample: <b>Заур</b>", text)
        self.assertIn("SNP: <b>rs2455144</b>", text)
        self.assertIn("Genotype: <b>AG</b>", text)
        self.assertIn("Chromosome: 1", text)
        self.assertIn("Position: 12345678", text)
        self.assertIn("Источник: raw-файл sample.", text)
        self.assertIn("🔁 Проверить другой SNP", [button.text for row in keyboard.inline_keyboard for button in row])
        self.assertNotIn("risk", text.lower())

    def test_sample_snp_lookup_not_found_and_no_raw_states(self) -> None:
        sample = SampleAsset("sample-a", "Заур", "", [], "2026-05-10T22:00:00")
        with tempfile.TemporaryDirectory() as tmp:
            store = MyDataStore(Path(tmp) / "my_data")
            no_raw_result = lookup_snp_in_sample(store, 1, sample, "rs2455144")

        not_found_text = sample_snp_lookup_result_text(
            sample,
            type("Result", (), {"rsid": "rs2455144", "found": False, "genotype": "--", "chromosome": None, "position": None, "error": None})(),
        )

        self.assertEqual(no_raw_result.error, "no_raw")
        self.assertIn("У этого sample нет raw-файла.", sample_snp_lookup_no_raw_text(sample))
        self.assertIn("SNP не найден в raw-файле.", not_found_text)
        self.assertIn("Это может зависеть от чипа", not_found_text)

    def test_samples_list_puts_new_sample_button_first(self) -> None:
        samples = [
            SampleAsset("sample-a", "A", "raw-a", [], "2026-05-10T22:00:00"),
            SampleAsset("sample-b", "B", "raw-b", [], "2026-05-10T22:00:00"),
        ]
        keyboard = build_sample_items_keyboard(samples)
        rows = keyboard.inline_keyboard

        self.assertEqual(rows[0][0].text, "➕ Новый sample")
        self.assertEqual(rows[0][0].callback_data, f"{MY_DATA_CALLBACK_PREFIX}:raw_files_upload")
        self.assertEqual(rows[1][0].text, "1. A")
        self.assertEqual(rows[2][0].text, "2. B")
        self.assertEqual([button.text for button in rows[-1]], ["Назад", "Отмена"])

    def test_samples_list_can_use_custom_back_callback(self) -> None:
        keyboard = build_sample_items_keyboard([], back_callback="main:privacy")

        self.assertEqual([button.callback_data for button in keyboard.inline_keyboard[-1]], ["main:privacy", "main:cancel"])

    def test_my_data_sample_coordinate_flow_uses_english_copy(self) -> None:
        sample = SampleAsset("sample-a", "A", "raw-a", [], "2026-05-10T22:00:00")
        raw = RawFileAsset("raw-a", "A raw", "a.txt", "stored/a.txt", "2026-05-10T22:00:00", 2048)
        text = sample_coordinates_menu_text(sample, raw_file=raw, lang="en")
        keyboard = build_sample_coordinates_menu_keyboard(sample.asset_id, lang="en")
        labels = [row[0].text for row in keyboard.inline_keyboard[:3]]

        self.assertIn("Sample coordinates", text)
        self.assertIn("Source raw: A raw", text)
        self.assertEqual(labels, ["Extract from source raw", "Add manually", "Choose from library"])

    def test_my_data_raw_upload_and_detail_use_english_copy(self) -> None:
        raw = RawFileAsset("raw-a", "A raw", "a.txt", "stored/a.txt", "2026-05-10T22:00:00", 2048)

        self.assertIn("Send the raw file as a document", upload_raw_text(lang="en"))
        self.assertIn("Send the sample name in one message", create_sample_text(raw, lang="en"))

        detail = raw_file_detail_text(raw, linked_sample=None, lang="en")
        samples = view_samples_text([], lang="en")

        self.assertIn("Source file: a.txt", detail)
        self.assertIn("Sample: not created", detail)
        self.assertIn("No saved samples yet", samples)

    def test_my_data_coordinates_library_uses_english_copy(self) -> None:
        coordinate = CoordinateAsset("coord-a", "A G25", "A", "g25", "A,1,2", "manual", "2026-05-10T22:00:00")
        root_keyboard = build_coordinates_keyboard(lang="en")
        items_keyboard = build_coordinate_items_keyboard([coordinate], lang="en")
        root_labels = [row[0].text for row in root_keyboard.inline_keyboard[:3]]
        item_labels = [row[0].text for row in items_keyboard.inline_keyboard[:-1]]
        footer_labels = [button.text for button in items_keyboard.inline_keyboard[-1]]

        self.assertIn("📍 G25 profiles", coordinates_text(lang="en"))
        self.assertIn("Standalone coordinates: 0", coordinates_text(lang="en"))
        self.assertIn("These G25 profiles are not attached to a sample.", view_coordinates_text([coordinate], lang="en"))
        self.assertNotIn("Choose a profile below", view_coordinates_text([coordinate], lang="en"))
        self.assertEqual(root_labels, ["G25 profiles", "Paste G25 manually", "Get G25"])
        self.assertEqual(item_labels, ["➕ New G25 profile", "1. A G25"])
        self.assertNotIn("Paste G25 manually", item_labels)
        self.assertNotIn("Get G25", item_labels)
        self.assertEqual(footer_labels, ["Back", "Cancel"])

    def test_coordinate_items_can_use_custom_back_callback(self) -> None:
        keyboard = build_coordinate_items_keyboard([], back_callback="main:privacy")

        self.assertEqual([button.callback_data for button in keyboard.inline_keyboard[-1]], ["main:privacy", "main:cancel"])

    def test_coordinate_items_hide_type_suffix_and_truncate_long_names(self) -> None:
        long_name = "ULEEDCBB3987_E250090817_L01_114_raw_sorted_23andMe"
        coordinate = CoordinateAsset("coord-a", long_name, "A", "g25", "A,1,2", "manual", "2026-05-10T22:00:00")
        keyboard = build_coordinate_items_keyboard([coordinate])
        button = keyboard.inline_keyboard[1][0]

        self.assertTrue(button.text.startswith("1. ULEEDCBB3987"))
        self.assertIn("...", button.text)
        self.assertTrue(button.text.endswith("d_23andMe"))
        self.assertNotIn("[G25]", button.text)
        self.assertEqual(button.callback_data, f"{MY_DATA_CALLBACK_PREFIX}:coordinate_item:coord-a")

    def test_coordinate_items_paginate_after_first_ten(self) -> None:
        coordinates = [
            CoordinateAsset(f"coord-{index}", f"Profile {index}", f"Profile {index}", "g25", f"Profile {index},1,2", "manual", "2026-05-10T22:00:00")
            for index in range(1, 13)
        ]
        text = view_coordinates_text(coordinates, page=1, lang="en")
        keyboard = build_coordinate_items_keyboard(coordinates, page=1, lang="en")
        rows = keyboard.inline_keyboard

        self.assertIn("Showing 11-12 of 12. Page 2/2.", text)
        self.assertEqual(rows[0][0].callback_data, f"{MY_DATA_CALLBACK_PREFIX}:coordinates_new_profile")
        self.assertEqual(rows[1][0].text, "11. Profile 11")
        self.assertEqual(rows[2][0].text, "12. Profile 12")
        self.assertEqual(rows[3][0].callback_data, f"{MY_DATA_CALLBACK_PREFIX}:coordinates_page:0")

    def test_new_g25_profile_menu_routes_to_existing_flows(self) -> None:
        keyboard = build_new_g25_profile_keyboard()
        rows = keyboard.inline_keyboard

        self.assertIn("➕ Новый G25-профиль", new_g25_profile_text())
        self.assertEqual(rows[0][0].text, "✍️ Вставить G25 вручную")
        self.assertEqual(rows[0][0].callback_data, f"{MY_DATA_CALLBACK_PREFIX}:coordinates_add_type:g25:g25_profiles")
        self.assertEqual(rows[1][0].text, "🧬 Получить G25")
        self.assertEqual(rows[1][0].callback_data, f"{MY_DATA_CALLBACK_PREFIX}:coordinates_extract_quick:g25_profiles")
        self.assertEqual([button.text for button in rows[-1]], ["⬅️ Назад", "Отмена"])
        self.assertEqual([button.callback_data for button in rows[-1]], [f"{MY_DATA_CALLBACK_PREFIX}:coordinates_view", f"{MY_DATA_CALLBACK_PREFIX}:cancel"])

    def test_coordinate_detail_uses_g25_profile_card_copy(self) -> None:
        coordinate = CoordinateAsset("coord-a", "Ibragim", "Ibragim", "g25", "Ibragim,\n0.1,0.2", "raw-file", "2026-05-19T16:32:00")
        text = coordinate_detail_text(coordinate)

        self.assertIn("<b>📍 G25-профиль · Ibragim</b>", text)
        self.assertIn("Target: Ibragim", text)
        self.assertIn("Источник: raw-file", text)
        self.assertIn("Создан: 19.05.2026", text)
        self.assertIn("━━━━━━━━━━━━━━", text)
        self.assertIn("<b>🧬 Координаты</b>", text)
        self.assertIn("<code>Ibragim,\n0.1,0.2</code>", text)
        self.assertNotIn("Тип: G25", text)

    def test_coordinate_detail_keeps_unexpected_created_at_value(self) -> None:
        coordinate = CoordinateAsset("coord-a", "Ibragim", "Ibragim", "g25", "Ibragim,1,2", "manual", "not-a-date")
        text = coordinate_detail_text(coordinate)

        self.assertIn("Создан: not-a-date", text)

    def test_my_data_root_links_my_g25_database(self) -> None:
        rows = build_my_data_keyboard().inline_keyboard
        labels = [row[0].text for row in rows]
        callbacks = [row[0].callback_data for row in rows]

        self.assertIn("G25-профили", my_data_text())
        self.assertEqual(my_data_text(), "🧬 My DNA\n\nВаши samples и G25-профили.")
        self.assertEqual(labels, ["Samples", "Загрузить raw", "Получить G25", "G25-профили", "Reports"])
        self.assertEqual(
            callbacks,
            [
                f"{MY_DATA_CALLBACK_PREFIX}:samples_view",
                f"{MY_DATA_CALLBACK_PREFIX}:raw_files_upload:root",
                "mydna:get_g25_raw",
                f"{MY_DATA_CALLBACK_PREFIX}:coordinates_view",
                "reports:root",
            ],
        )

    def test_quick_g25_reply_result_does_not_auto_save_in_copy(self) -> None:
        prompt = extract_coordinates_text("g25")
        result = quick_g25_result_text("Target", "Target,1,2")
        keyboard = build_quick_g25_result_keyboard()
        labels = [row[0].text for row in keyboard.inline_keyboard]

        self.assertIn("Я извлеку G25-координаты и покажу результат.", prompt)
        self.assertIn("<code>Target,1,2</code>", result)
        self.assertEqual(labels, ["Создать Sample", "Сохранить G25-профиль"])

    def test_g25_profile_input_screens_use_profile_back_footer(self) -> None:
        manual_keyboard = build_add_coordinates_keyboard(back_callback="my_data:coordinates_new_profile", add_data_flow=True)
        extract_keyboard = build_extract_coordinates_keyboard(back_callback="my_data:coordinates_new_profile", add_data_flow=True)

        self.assertIn("🧬 Загрузить raw", upload_raw_text())
        self.assertIn("Я сохраню его в вашей библиотеке My DNA.", upload_raw_text())
        self.assertIn("✍️ Вставить G25 вручную", add_coordinates_text("g25"))
        self.assertIn("Я сохраню их как отдельный G25-профиль.", add_coordinates_text("g25"))
        for keyboard in (manual_keyboard, extract_keyboard):
            self.assertEqual([button.text for button in keyboard.inline_keyboard[-1]], ["⬅️ Назад", "Отмена"])
            self.assertEqual([button.callback_data for button in keyboard.inline_keyboard[-1]], ["my_data:coordinates_new_profile", "my_data:cancel"])

    def test_sample_without_raw_copy_does_not_claim_missing_raw(self) -> None:
        sample = SampleAsset("sample-a", "A", "", ["coord-a"], "2026-05-10T22:00:00")
        text = sample_detail_text(
            sample,
            raw_file=None,
            coordinate_count=1,
            report_counts={"coordinate_spaces": 0, "admixture": 0, "matching": 0, "traits": 0, "haplogroups": 0},
        )

        self.assertIn("<b>🧬 Sample · A</b>", text)
        self.assertIn("<b>Создан:</b> 10.05.2026", text)
        self.assertIn("━━━━━━━━━━━━━━", text)
        self.assertIn("Raw-файл: нет", text)
        self.assertIn("G25-профили: 1", text)
        self.assertIn("<b>📊 Отчёты</b>\n\n", text)
        self.assertIn("🧭 Coordinate spaces: 0", text)
        self.assertIn("🧬 Admixture: 0", text)
        self.assertIn("<b>Всего отчётов:</b> 0", text)

    def test_sample_detail_report_counts_are_numeric_and_safe(self) -> None:
        sample = SampleAsset("sample-a", "A", "", [], "2026-05-10T22:00:00")
        text = sample_detail_text(
            sample,
            raw_file=None,
            coordinate_count=0,
            report_counts={"coordinate_spaces": None, "admixture": 17, "matching": 7, "traits": 27, "haplogroups": 1},
        )

        self.assertIn("🧭 Coordinate spaces: 0", text)
        self.assertIn("🧬 Admixture: 17", text)
        self.assertIn("🧩 Matching: 7", text)
        self.assertIn("🧾 Traits: 27", text)
        self.assertIn("🌿 Haplogroups: 1", text)
        self.assertIn("<b>Всего отчётов:</b> 52", text)

    def test_sample_detail_keeps_unexpected_created_at_value(self) -> None:
        sample = SampleAsset("sample-a", "A", "", [], "not-a-date")
        text = sample_detail_text(
            sample,
            raw_file=None,
            coordinate_count=0,
            report_counts={"coordinate_spaces": 0, "admixture": 0, "matching": 0, "traits": 0, "haplogroups": 0},
        )

        self.assertIn("<b>Создан:</b> not-a-date", text)

    def test_my_data_legacy_results_use_english_copy(self) -> None:
        self.assertIn("Saved reports", results_text(lang="en"))


if __name__ == "__main__":
    unittest.main()
