from __future__ import annotations

import unittest
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image, ImageStat

from app.features.my_data.storage import CoordinateAsset, SampleAsset
from app.features.settings.storage import UserSettingsStore
from app.features.reports.dna_passport.domain import (
    DNAPassportData,
    DNAPassportG25Population,
    DNAPassportG25Summary,
    DNAPassportInterestingSnpItem,
    DNAPassportInterestingSnpsSummary,
    DNAPassportLineageReadiness,
    DNAPassportRawSummary,
    DNAPassportSampleSummary,
    DNAPassportTraitItem,
    DNAPassportTraitsSummary,
)
from app.features.snp_report.domain import load_snp_rules
from app.features.reports.dna_passport.menu import (
    build_sample_picker_keyboard,
    handle_sample_selected,
    _passport_theme,
    sample_picker_text,
    show_sample_picker_menu,
)
from app.features.reports.dna_passport.render import render_dna_passport_html
from app.features.reports.dna_passport.render_visual import render_dna_passport_pages, visual_page_order
from app.features.reports.dna_passport.visual import render_dna_passport_visual_png
from app.features.reports.dna_passport.visual_pages import _radial_reference_layout
from app.features.reports.dna_passport.visual_style import BACKGROUND_ASSET, DARK_BACKGROUND_ASSET, draw_footer, draw_header, snp_display_result, snp_metric, visual_snp_items
from app.features.reports.menu import (
    REPORT_PRODUCTS,
    build_report_detail_keyboard,
    build_reports_keyboard,
    reports_callback_handler,
    reports_text,
    report_detail_text,
    show_reports_menu,
)
from app.main_menu import set_active_main_menu_message


class _FakeMessage:
    def __init__(self, *, chat_id: int = 10, message_id: int = 100) -> None:
        self.chat_id = chat_id
        self.message_id = message_id
        self.calls: list[tuple[str, object, object, str | None]] = []

    async def edit_text(self, text, reply_markup=None, parse_mode=None):
        self.calls.append(("edit_text", text, reply_markup, parse_mode))

    async def reply_text(self, text, reply_markup=None, parse_mode=None, do_quote=False):
        self.calls.append(("reply_text", text, reply_markup, parse_mode))
        return _FakeMessage(chat_id=self.chat_id, message_id=self.message_id + 1)

    async def reply_photo(self, photo, caption=None, reply_markup=None, do_quote=False):
        self.calls.append(("reply_photo", caption, reply_markup, None))
        return self

    async def reply_media_group(self, media, do_quote=False):
        self.calls.append(("reply_media_group", len(media), None, None))
        return [self for _ in media]

    async def delete(self):
        self.calls.append(("delete", "", None, None))


class _FakeQuery:
    def __init__(self, data: str, message: _FakeMessage) -> None:
        self.data = data
        self.message = message
        self.answers: list[tuple[str | None, bool]] = []

    async def answer(self, text=None, show_alert=False):
        self.answers.append((text, show_alert))


class _CaptureDraw:
    def __init__(self) -> None:
        self.texts: list[str] = []

    def text(self, xy, text, font=None, fill=None, anchor=None):
        self.texts.append(str(text))

    def textlength(self, text, font=None):
        return len(str(text)) * 12

    def rounded_rectangle(self, *args, **kwargs):
        return None

    def line(self, *args, **kwargs):
        return None


def _fake_fonts() -> dict[str, object]:
    return {
        "eyebrow": object(),
        "hero": object(),
        "sample_title": object(),
        "subtitle": object(),
        "small_bold": object(),
        "section_title": object(),
        "badge": object(),
        "small": object(),
    }


class _FakeStore:
    def __init__(self, *, samples=None, coordinates=None) -> None:
        self.samples = list(samples or [])
        self.coordinates = {sample_id: list(items) for sample_id, items in (coordinates or {}).items()}
        self.calls: list[str] = []

    def list_samples(self, user_id: int):
        self.calls.append("list_samples")
        return list(self.samples)

    def get_sample(self, user_id: int, sample_id: str):
        self.calls.append("get_sample")
        for sample in self.samples:
            if sample.asset_id == sample_id:
                return sample
        return None

    def list_sample_coordinates(self, user_id: int, sample_id: str):
        self.calls.append("list_sample_coordinates")
        return list(self.coordinates.get(sample_id, []))

    def __getattr__(self, name: str):
        if name.startswith("save") or "report" in name.lower() or "haplogroup" in name.lower():
            raise AssertionError(f"DNA passport UI must not use saved/write method: {name}")
        raise AttributeError(name)


class _FakePassportService:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def build_for_sample(self, **kwargs):
        self.calls.append(dict(kwargs))
        return _passport_data()


class _FakeAccessStore:
    def __init__(self, admin_ids=None, admin_usernames=None) -> None:
        self.admin_ids = set(admin_ids or [])
        self.admin_usernames = {str(item).strip().lstrip("@").lower() for item in (admin_usernames or [])}

    def is_admin(self, update) -> bool:
        username = str(getattr(update.effective_user, "username", "") or "").strip().lstrip("@").lower()
        return getattr(update.effective_user, "id", None) in self.admin_ids or username in self.admin_usernames


class DNAPassportUiTests(unittest.TestCase):
    def test_catalog_button_has_no_free_label(self) -> None:
        keyboard_ru = build_reports_keyboard()
        labels_ru = [button.text for row in keyboard_ru.inline_keyboard for button in row]
        labels_en = [button.text for row in build_reports_keyboard(lang="en").inline_keyboard for button in row]
        passport_button = next(button for row in keyboard_ru.inline_keyboard for button in row if button.text == "🧬 DNA-паспорт")

        self.assertIn("🧬 DNA-паспорт", labels_ru)
        self.assertIn("🧬 DNA passport", labels_en)
        self.assertEqual(passport_button.callback_data, "reports:passport:samples:0")
        self.assertNotIn("Бесплатно", " ".join(labels_ru))
        self.assertNotIn("Free", " ".join(labels_en[:1]))

    def test_admin_reports_screen_shows_full_catalog(self) -> None:
        store = _FakeStore()
        message = _FakeMessage()

        _run(show_reports_menu(message, _context(store, admin_ids={1}), 1, edit_existing=True))

        text = message.calls[-1][1]
        labels = [button.text for row in message.calls[-1][2].inline_keyboard for button in row]
        self.assertIn("Персональные исследования по вашим DNA-образцам", text)
        self.assertIn("🧬 DNA-паспорт", labels)
        self.assertEqual(
            labels[:7],
            [
                "🧬 DNA-паспорт",
                "🧭 Портрет происхождения",
                "🏺 Древние корни",
                "⛰ Региональное исследование",
                "👥 Семейное сравнение",
                "✨ Портрет признаков",
                "🌿 Отцовская и материнская линии",
            ],
        )

    def test_username_admin_reports_callback_shows_full_catalog(self) -> None:
        store = _FakeStore()
        message = _FakeMessage()
        update = _callback_update("reports:root", user_id=2, username="jb_cc", message=message)

        with patch("app.features.reports.menu.ensure_active_main_menu", return_value=True):
            _run(reports_callback_handler(update, _context(store, admin_usernames={"jb_cc"})))

        labels = [button.text for row in message.calls[-1][2].inline_keyboard for button in row]
        self.assertIn("🧬 DNA-паспорт", labels)
        self.assertIn("🧭 Портрет происхождения", labels)
        self.assertNotIn("Раздел находится в разработке", message.calls[-1][1])

    def test_regular_reports_screen_shows_only_stub(self) -> None:
        store = _FakeStore()
        message = _FakeMessage()

        _run(show_reports_menu(message, _context(store, admin_ids={99}), 1, edit_existing=True))

        text = message.calls[-1][1]
        keyboard = message.calls[-1][2]
        labels = [button.text for row in keyboard.inline_keyboard for button in row]
        callbacks = [button.callback_data for row in keyboard.inline_keyboard for button in row]
        self.assertIn("Раздел находится в разработке", text)
        self.assertIn("Здесь появятся персональные DNA-отчёты", text)
        self.assertEqual(labels, ["Назад", "Отмена"])
        self.assertEqual(callbacks, ["mydna:root", "main:cancel"])
        self.assertNotIn("🧬 DNA-паспорт", labels)
        self.assertNotIn("🧭 Портрет происхождения", labels)
        self.assertNotIn("Бесплатно", text)
        self.assertNotIn("admin", text.lower())
        self.assertNotIn("beta", text.lower())
        self.assertNotIn("dna_platform", text)

    def test_admin_opens_passport_card_and_starts_generation(self) -> None:
        sample = _sample("sample-1", "Zaur")
        store = _FakeStore(samples=[sample])
        service = _FakePassportService()
        message = _FakeMessage()
        context = _context(store, admin_ids={1})

        update = _callback_update("reports:info:passport", user_id=1, message=message)
        with patch("app.features.reports.menu.ensure_active_main_menu", return_value=True):
            _run(reports_callback_handler(update, context))

        self.assertIn("Выберите образец", message.calls[-1][1])
        self.assertNotIn("Сформировать DNA-паспорт", _labels(message.calls[-1][2]))

        update = _callback_update("reports:passport:sample:sample-1", user_id=1, message=message)
        with patch("app.features.reports.menu.ensure_active_main_menu", return_value=True), patch(
            "app.features.reports.dna_passport.menu._passport_service",
            return_value=service,
        ):
            _run(reports_callback_handler(update, context))

        self.assertEqual(service.calls[0]["sample_id"], "sample-1")
        call_names = [call[0] for call in message.calls]
        self.assertIn("reply_media_group", call_names)
        self.assertIn("reply_text", call_names)
        followup = _last_call(message, "reply_text")
        self.assertIn("DNA-паспорт готов", followup[1])
        labels = _labels(followup[2])
        callbacks = [button.callback_data for row in followup[2].inline_keyboard for button in row]
        self.assertIn("📄 Подробный отчёт", labels)
        self.assertIn("🔁 Другой образец", labels)
        self.assertTrue(any(callback.startswith("reports:passport:detail:") for callback in callbacks))
        self.assertIn("dna_passport_detail_cache", context.user_data)

    def test_passport_visual_pages_render_five_page_album(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pages = render_dna_passport_pages(_passport_data(), root / "dark")

            self.assertEqual([page.slug for page in pages], ["overview", "ancestry", "traits", "snps", "lines"])
            self.assertEqual(visual_page_order(), ("overview", "ancestry", "traits", "snps", "lines"))
            self.assertEqual([page.title for page in pages], ["Обложка", "Краткое происхождение", "Базовые признаки", "Интересные SNP", "Следующие шаги"])
            brightness = {}
            for page in pages:
                self.assertTrue(page.path.exists())
                with Image.open(page.path) as image:
                    self.assertEqual(image.format, "PNG")
                    self.assertEqual(image.size, (1440, 1800))
                    extrema = image.convert("L").getextrema()
                    brightness[page.slug] = ImageStat.Stat(image.convert("L")).mean[0]
                self.assertGreater(extrema[1] - extrema[0], 20)
            self.assertTrue(BACKGROUND_ASSET.exists())
            self.assertTrue(DARK_BACKGROUND_ASSET.exists())
            for slug, value in brightness.items():
                self.assertLess(value, 80, slug)

            light_pages = render_dna_passport_pages(_passport_data(), root / "light", theme="light")
            for page in light_pages:
                with Image.open(page.path) as image:
                    value = ImageStat.Stat(image.convert("L")).mean[0]
                self.assertGreater(value, 180, page.slug)

    def test_passport_visual_header_footer_rules(self) -> None:
        data = _passport_data()
        fonts = _fake_fonts()

        cover_draw = _CaptureDraw()
        draw_header(cover_draw, fonts, data, page_title="Обложка", page_number=1, total_pages=5)
        self.assertIn("DNA-паспорт", cover_draw.texts)
        self.assertNotIn("Обложка", cover_draw.texts)

        section_draw = _CaptureDraw()
        draw_header(section_draw, fonts, data, page_title="Краткое происхождение", page_number=2, total_pages=5)
        self.assertIn("KBDNA / DNA-ПАСПОРТ", section_draw.texts)
        self.assertIn("Краткое происхождение", section_draw.texts)

        middle_footer = _CaptureDraw()
        draw_footer(middle_footer, fonts, page_number=2, total_pages=5)
        self.assertEqual(middle_footer.texts, [])

        first_footer = _CaptureDraw()
        draw_footer(first_footer, fonts, page_number=1, total_pages=5)
        self.assertIn("Визуальная версия. Подробности и ограничения доступны в текстовом отчёте.", first_footer.texts)
        self.assertFalse(any("стр." in item for item in first_footer.texts))

    def test_passport_visual_metrics_and_snp_filtering_use_ready_data(self) -> None:
        items = (
            DNAPassportInterestingSnpItem(
                "rs1805007",
                "MC1R",
                "Внешность",
                "MC1R",
                "CC",
                "Обычный вариант MC1R по этому SNP",
            ),
            DNAPassportInterestingSnpItem(
                "rs1815739",
                "ACTN3",
                "Физическая активность",
                "ACTN3",
                "TT",
                "Вариант, чаще связываемый с выносливостью",
            ),
        )
        summary = DNAPassportInterestingSnpsSummary(status="ok", total=10, found=7, missing=3, items=items)
        data = _passport_data(interesting_snps=summary)

        self.assertEqual(snp_metric(data), "7 из 10")
        visual_items = visual_snp_items(items)
        self.assertEqual([item.gene for item in visual_items], ["ACTN3"])

        mixed_actn3 = DNAPassportInterestingSnpItem(
            "rs1815739",
            "ACTN3: мышечные волокна",
            "Физическая активность",
            "ACTN3",
            "CT",
            "Промежуточный вариант ACTN3",
        )
        self.assertEqual(snp_display_result(mixed_actn3), "Смешанный вариант по ACTN3")

    def test_passport_visual_g25_radial_labels_do_not_overlap_fixture(self) -> None:
        refs = _passport_data().g25.top_modern
        layout = _radial_reference_layout((150, 750, 1290, 1320), refs)
        boxes = []
        for _item, _sx, _sy, lx, ly, anchor in layout:
            box = (lx - 360, ly, lx, ly + 44) if anchor == "ra" else (lx, ly, lx + 360, ly + 44)
            boxes.append(box)

        for index, first in enumerate(boxes):
            for second in boxes[index + 1 :]:
                self.assertFalse(_boxes_overlap(first, second), (first, second))

    def test_passport_visual_renderer_handles_partial_data(self) -> None:
        data = DNAPassportData(
            sample=DNAPassportSampleSummary(status="ok", sample_id="sample-1", display_name="Very Long Sample Name For Visual Passport Layout Check"),
            raw=DNAPassportRawSummary(status="unavailable"),
            g25=DNAPassportG25Summary(status="unavailable"),
            traits=DNAPassportTraitsSummary(status="unavailable"),
            interesting_snps=DNAPassportInterestingSnpsSummary(status="ok", total=10, found=0, missing=10, items=()),
            lineage=DNAPassportLineageReadiness(status="ok", y_count=0, mtdna_count=0),
            generated_at="2026-06-17T00:00:00Z",
        )

        with tempfile.TemporaryDirectory() as tmp:
            pages = render_dna_passport_pages(data, Path(tmp))

            self.assertEqual(len(pages), 5)
            for page in pages:
                self.assertTrue(page.path.exists())

    def test_passport_visual_legacy_preview_wrapper_renders_overview(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "passport.png"

            result_path = render_dna_passport_visual_png(_passport_data(), output_path)

            self.assertEqual(result_path, output_path)
            with Image.open(output_path) as image:
                self.assertEqual(image.size, (1440, 1800))

    def test_passport_visual_themes_are_isolated_between_threads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            jobs = (("dark", root / "dark.png"), ("light", root / "light.png"))
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [executor.submit(render_dna_passport_visual_png, _passport_data(), path, theme=theme) for theme, path in jobs]
                for future in futures:
                    future.result()

            with Image.open(root / "dark.png") as image:
                dark_brightness = ImageStat.Stat(image.convert("L")).mean[0]
            with Image.open(root / "light.png") as image:
                light_brightness = ImageStat.Stat(image.convert("L")).mean[0]

            self.assertLess(dark_brightness, 80)
            self.assertGreater(light_brightness, 180)

    def test_passport_uses_saved_user_theme_with_dark_fallback(self) -> None:
        context = _context(_FakeStore())
        self.assertEqual(_passport_theme(context, 42), "dark")

        with tempfile.TemporaryDirectory() as tmp:
            settings_store = UserSettingsStore(Path(tmp))
            settings_store.set_theme(42, "light")
            context.application.bot_data["user_settings_store"] = settings_store
            self.assertEqual(_passport_theme(context, 42), "light")

    def test_passport_visual_renderer_uses_ready_passport_data_only(self) -> None:
        root = Path("app/features/reports/dna_passport")
        source = "\n".join(
            [
                (root / "render_visual.py").read_text(encoding="utf-8"),
                (root / "visual_pages.py").read_text(encoding="utf-8"),
                (root / "visual_style.py").read_text(encoding="utf-8"),
            ]
        )

        for forbidden in (
            "parse_raw_dna",
            "DNAPassportService",
            "TraitsRuntimeService",
            "G25CommandService",
            "analyze_interesting_snps",
            "load_interesting_snps",
            "dna_platform",
        ):
            self.assertNotIn(forbidden, source)
        self.assertIn("main_summary_lines", source)
        self.assertIn("8 базовых признаков", source)
        self.assertIn("Что можно изучить дальше", source)
        self.assertIn("Исходные данные", source)
        self.assertIn("create_background_image", source)
        self.assertIn("Качество чтения", source)
        self.assertIn("autosomal raw", source)
        self.assertIn("ФОТО НЕ ДОБАВЛЕНО", source)
        self.assertIn("Дата рождения", source)
        self.assertIn("X хромосома", source)
        self.assertIn("Y хромосома", source)
        self.assertIn("Для точного анализа нужны отдельные Y-DNA и mtDNA-тесты", source)
        self.assertNotIn("_draw_metric_icon", source)
        self.assertIn("Выбранные маркеры", source)
        self.assertIn("Схема генетической близости", source)
        self.assertIn("расчёт по полному G25-вектору", source)
        self.assertIn("Звёзды отражают качество расчёта", source)
        self.assertIn("Региональное исследование Кавказа", source)
        self.assertIn("Портрет происхождения", source)
        self.assertIn("Портрет признаков", source)
        self.assertIn("Древние корни", source)
        self.assertIn("Семейное сравнение", source)
        self.assertIn("Отцовская и материнская линии", source)
        self.assertNotIn("Найдено с трактовкой", source)
        self.assertNotIn("SNP Lab", source)
        for removed in (
            "Слои паспорта",
            "Ключевые результаты",
            "Самый выраженный Trait",
            "Coordinate Space",
            "LOCAL G25 VIEW",
            "полная 25D-логика",
            "низко",
            "высоко",
            "Содержательные маркеры",
            "Техническая готовность",
            "Недоступна по autosomal raw",
            "Обычный вариант MC1R",
            "собрать более глубокую карту совпадений",
            "развернуть базовую панель",
            "стр.",
        ):
            self.assertNotIn(removed, source)

    def test_passport_detail_button_opens_existing_text_report(self) -> None:
        sample = _sample("sample-1", "Zaur")
        store = _FakeStore(samples=[sample])
        service = _FakePassportService()
        message = _FakeMessage()
        context = _context(store, admin_ids={1})

        update = _callback_update("reports:passport:sample:sample-1", user_id=1, message=message)
        with patch("app.features.reports.menu.ensure_active_main_menu", return_value=True), patch(
            "app.features.reports.dna_passport.menu._passport_service",
            return_value=service,
        ):
            _run(reports_callback_handler(update, context))

        followup = _last_call(message, "reply_text")
        callbacks = [button.callback_data for row in followup[2].inline_keyboard for button in row]
        detail_callback = next(callback for callback in callbacks if callback.startswith("reports:passport:detail:"))

        update = _callback_update(detail_callback, user_id=1, message=message)
        with patch("app.features.reports.menu.ensure_active_main_menu", return_value=True):
            _run(reports_callback_handler(update, context))

        self.assertEqual(message.calls[-1][3], "HTML")
        self.assertIn("<b>🧬 DNA-паспорт</b>", message.calls[-1][1])
        self.assertIn("📁 Исходные данные", message.calls[-1][1])

    def test_passport_detail_followup_is_registered_as_active_menu(self) -> None:
        sample = _sample("sample-1", "Zaur")
        store = _FakeStore(samples=[sample])
        service = _FakePassportService()
        message = _FakeMessage(chat_id=10, message_id=100)
        context = _context(store, admin_ids={1})
        set_active_main_menu_message(context, 10, 1, 100)

        update = _callback_update("reports:passport:sample:sample-1", user_id=1, message=message)
        with patch("app.features.reports.menu.ensure_active_main_menu", return_value=True), patch(
            "app.features.reports.dna_passport.menu._passport_service",
            return_value=service,
        ):
            _run(reports_callback_handler(update, context))

        active_id = context.application.bot_data["main_menu_store"].get(10, 1)
        self.assertEqual(active_id, 101)

        followup = _last_call(message, "reply_text")
        callbacks = [button.callback_data for row in followup[2].inline_keyboard for button in row]
        detail_callback = next(callback for callback in callbacks if callback.startswith("reports:passport:detail:"))
        detail_message = _FakeMessage(chat_id=10, message_id=101)
        update = _callback_update(detail_callback, user_id=1, message=detail_message)

        _run(reports_callback_handler(update, context))

        self.assertEqual(update.callback_query.answers, [(None, False)])
        self.assertEqual(detail_message.calls[-1][3], "HTML")
        self.assertIn("DNA-", detail_message.calls[-1][1])

    def test_passport_visual_failure_falls_back_to_text_report(self) -> None:
        sample = _sample("sample-1", "Zaur")
        store = _FakeStore(samples=[sample])
        service = _FakePassportService()
        message = _FakeMessage()

        update = _callback_update("reports:passport:sample:sample-1", user_id=1, message=message)
        with patch("app.features.reports.menu.ensure_active_main_menu", return_value=True), patch(
            "app.features.reports.dna_passport.menu._passport_service",
            return_value=service,
        ), patch("app.features.reports.dna_passport.menu.render_dna_passport_pages", side_effect=RuntimeError("visual failed")), patch(
            "app.features.reports.dna_passport.menu.logger.exception"
        ):
            _run(reports_callback_handler(update, _context(store, admin_ids={1})))

        self.assertEqual(message.calls[-1][3], "HTML")
        self.assertIn("<b>🧬 DNA-паспорт</b>", message.calls[-1][1])
        self.assertNotIn("reply_media_group", [call[0] for call in message.calls])

    def test_regular_user_direct_passport_callback_is_closed_before_service(self) -> None:
        store = _FakeStore(samples=[_sample("sample-1", "Zaur", raw_file_id="raw-1")])
        service = _FakePassportService()
        message = _FakeMessage()
        update = _callback_update("reports:passport:sample:sample-1", user_id=2, message=message)

        with patch("app.features.reports.menu.ensure_active_main_menu", return_value=True), patch(
            "app.features.reports.dna_passport.menu._passport_service",
            return_value=service,
        ):
            _run(reports_callback_handler(update, _context(store, admin_ids={1})))

        self.assertEqual(service.calls, [])
        self.assertEqual(update.callback_query.answers, [("Раздел находится в разработке.", True)])
        self.assertIn("Раздел находится в разработке", message.calls[-1][1])
        self.assertNotIn("get_sample", store.calls)

    def test_regular_user_future_cards_and_legacy_callbacks_are_closed(self) -> None:
        for callback in (
            "reports:info:origin_portrait",
            "reports:s:r0",
            "reports:s:r1",
            "reports:s:r2",
            "reports:run:passport",
            "reports:pay:passport",
        ):
            with self.subTest(callback=callback):
                store = _FakeStore()
                message = _FakeMessage()
                update = _callback_update(callback, user_id=2, message=message)

                with patch("app.features.reports.menu.ensure_active_main_menu", return_value=True):
                    _run(reports_callback_handler(update, _context(store, admin_ids={1})))

                self.assertEqual(update.callback_query.answers, [("Раздел находится в разработке.", True)])
                self.assertIn("Раздел находится в разработке", message.calls[-1][1])
                self.assertNotIn("Портрет происхождения", message.calls[-1][1])

    def test_reports_stub_copy_has_no_product_labels(self) -> None:
        text = reports_text(show_products=False)

        self.assertIn("Раздел находится в разработке", text)
        self.assertNotIn("DNA-паспорт", text)
        self.assertNotIn("Портрет происхождения", text)
        self.assertNotIn("Бесплатно", text)

    def test_sample_picker_lists_samples(self) -> None:
        samples = [_sample("sample-1", "Zaur"), _sample("sample-2", "Test")]
        keyboard = build_sample_picker_keyboard(samples)
        labels = [button.text for row in keyboard.inline_keyboard for button in row]
        callbacks = [button.callback_data for row in keyboard.inline_keyboard for button in row]

        self.assertIn("Zaur", labels)
        self.assertIn("Test", labels)
        self.assertIn("reports:passport:sample:sample-1", callbacks)
        self.assertIn("reports:root", callbacks)

    def test_no_samples_screen_is_handled(self) -> None:
        text = sample_picker_text([])
        keyboard = build_sample_picker_keyboard([])
        callbacks = [button.callback_data for row in keyboard.inline_keyboard for button in row]

        self.assertIn("У вас пока нет образцов", text)
        self.assertEqual(callbacks, ["reports:root", "main:cancel"])

    def test_show_sample_picker_uses_existing_sample_store(self) -> None:
        store = _FakeStore(samples=[_sample("sample-1", "Zaur")])
        message = _FakeMessage()

        _run(show_sample_picker_menu(message, _context(store), 1, page=0))

        self.assertEqual(store.calls, ["list_samples"])
        self.assertIn("Выберите образец", message.calls[-1][1])

    def test_sample_without_g25_runs_passport_immediately(self) -> None:
        store = _FakeStore(samples=[_sample("sample-1", "Zaur", raw_file_id="raw-1")], coordinates={"sample-1": []})
        service = _FakePassportService()
        message = _FakeMessage()

        with patch("app.features.reports.dna_passport.menu._passport_service", return_value=service):
            _run(handle_sample_selected(message, _context(store), 1, sample_id="sample-1"))

        self.assertEqual(service.calls[0]["sample_id"], "sample-1")
        self.assertIsNone(service.calls[0]["g25_coordinate_id"])
        self.assertIn("🧬 Формируем DNA-паспорт…", message.calls[0][1])
        self.assertNotIn("Краткий персональный отчёт", message.calls[0][1])
        self.assertIn("Получаем координаты G25", message.calls[0][1])
        self.assertIn("reply_media_group", [call[0] for call in message.calls])
        self.assertIn("reply_text", [call[0] for call in message.calls])

    def test_sample_with_attached_g25_does_not_show_picker(self) -> None:
        sample = _sample("sample-1", "Zaur")
        coordinate = _coordinate("coord-1", "Main G25")
        store = _FakeStore(samples=[sample], coordinates={"sample-1": [coordinate]})
        service = _FakePassportService()
        message = _FakeMessage()

        with patch("app.features.reports.dna_passport.menu._passport_service", return_value=service):
            _run(handle_sample_selected(message, _context(store), 1, sample_id="sample-1"))

        self.assertEqual(service.calls[0]["sample_id"], "sample-1")
        self.assertIsNone(service.calls[0]["g25_coordinate_id"])
        self.assertNotIn("Выберите профиль", message.calls[0][1])
        self.assertNotIn("Получаем координаты G25", message.calls[0][1])

    def test_multiple_g25_does_not_show_picker(self) -> None:
        sample = _sample("sample-1", "Zaur")
        coordinates = [_coordinate("coord-1", "Main G25"), _coordinate("coord-2", "Second G25")]
        store = _FakeStore(samples=[sample], coordinates={"sample-1": coordinates})
        service = _FakePassportService()
        message = _FakeMessage()

        with patch("app.features.reports.dna_passport.menu._passport_service", return_value=service):
            _run(handle_sample_selected(message, _context(store), 1, sample_id="sample-1"))

        self.assertEqual(service.calls[0]["sample_id"], "sample-1")
        self.assertIsNone(service.calls[0]["g25_coordinate_id"])
        self.assertNotIn("Выберите профиль", message.calls[0][1])

    def test_raw_without_attached_g25_status_mentions_g25_calculation(self) -> None:
        store = _FakeStore(samples=[_sample("sample-1", "Zaur", raw_file_id="raw-1")], coordinates={"sample-1": []})
        service = _FakePassportService()
        message = _FakeMessage()

        with patch("app.features.reports.dna_passport.menu._passport_service", return_value=service):
            _run(handle_sample_selected(message, _context(store), 1, sample_id="sample-1"))

        self.assertIn("Получаем координаты G25 из DNA-файла", message.calls[0][1])

    def test_renderer_escapes_values_and_stays_compact(self) -> None:
        data = _passport_data(sample_name="<Zaur>", g25_name="<Main>", population="<UnknownPop>")

        text = render_dna_passport_html(data)

        self.assertLessEqual(len(text), 4096)
        self.assertIn("&lt;Zaur&gt;", text)
        self.assertIn("&lt;UnknownPop&gt;", text)
        self.assertNotIn("<Zaur>", text)
        self.assertNotIn("pgs003835", text)

    def test_renderer_uses_user_friendly_raw_copy(self) -> None:
        data = _passport_data()
        text = render_dna_passport_html(data)

        self.assertIn("📁 Исходные данные", text)
        self.assertIn("Провайдер: FamilyTreeDNA", text)
        self.assertIn("Качество чтения: 98,7%", text)
        self.assertNotIn("Call rate", text)
        self.assertNotIn("автосомный DNA-файл", text)
        self.assertNotIn("автосомный файл", text)

    def test_renderer_hides_ambiguous_provider_hint(self) -> None:
        data = _passport_data(
            raw=DNAPassportRawSummary(
                status="ok",
                raw_file_id="raw-1",
                original_file_name="raw.txt",
                provider_hint="23andMe/FTDNA/MyHeritage-like",
                called_snps=612438,
                autosomal_count=598210,
                x_count=14012,
                y_count=0,
                mtdna_count=32,
                call_rate=0.981,
            )
        )

        text = render_dna_passport_html(data)

        self.assertIn("Формат: autosomal raw", text)
        self.assertNotIn("23andMe/FTDNA/MyHeritage-like", text)
        self.assertNotIn("like", text)

    def test_renderer_localizes_g25_and_removes_gap_copy(self) -> None:
        data = _passport_data()
        text = render_dna_passport_html(data)

        self.assertIn("Генетическое пространство: Кавказ", text)
        self.assertIn("Ближайшие референсные популяции", text)
        self.assertIn("1. Балкарцы — 2,14", text)
        self.assertIn("2. Черкесы — 2,56", text)
        self.assertIn("3. Кумыки — 2,72", text)
        self.assertNotIn("Отрыв от второго результата", text)
        self.assertNotIn("практически на одинаковой дистанции", text)

    def test_renderer_shows_all_traits_as_percentages(self) -> None:
        data = _passport_data()
        text = render_dna_passport_html(data)

        for label in (
            "Рост",
            "Хронотип",
            "Потребление кофе",
            "Длительность сна",
            "Сила хвата",
            "Темп ходьбы",
            "Пигментация кожи",
            "Потребление воды",
        ):
            self.assertIn(label, text)
        self.assertIn("Потребление кофе — 73% · ★★☆", text)
        self.assertIn("Хронотип — 40% · ★☆☆", text)
        self.assertNotIn("процентиль", text.split("ℹ️ Важно", 1)[0])
        self.assertNotIn("низкая надёжность", text)

    def test_renderer_important_copy_explains_trait_percentages(self) -> None:
        text = render_dna_passport_html(_passport_data())

        self.assertIn("Проценты признаков показывают положение результата относительно референсной панели", text)
        self.assertIn("а не вероятность наличия признака", text)

    def test_renderer_shows_compact_interesting_snp_block_without_medical_markers(self) -> None:
        rules = load_snp_rules()
        rule_ids = {rule.rsid for rule in rules}
        text = render_dna_passport_html(_passport_data())

        self.assertIn("rs4988235", rule_ids)
        self.assertIn("rs429358", rule_ids)
        self.assertIn("🧪 Интересные SNP", text)
        self.assertIn("Переносимость лактозы: CT", text)
        self.assertIn("Тип ушной серы: AA", text)
        self.assertNotIn("Найдено с трактовкой", text)
        self.assertNotIn("SNP Lab", text)
        self.assertNotIn("APOE", text)
        self.assertNotIn("Lactase persistence", text)
        self.assertNotIn("Genotype", text)

    def test_renderer_shows_five_interesting_snps_without_overflow_count(self) -> None:
        interesting_snps = DNAPassportInterestingSnpsSummary(
            status="ok",
            total=10,
            found=6,
            missing=4,
            items=tuple(
                DNAPassportInterestingSnpItem(
                    f"rs{i}",
                    f"SNP {i}",
                    "Категория",
                    "GENE",
                    "AA",
                    f"Трактовка {i}",
                )
                for i in range(1, 7)
            ),
        )

        text = render_dna_passport_html(_passport_data(interesting_snps=interesting_snps))

        for i in range(1, 6):
            self.assertIn(f"SNP {i}: AA", text)
        self.assertNotIn("SNP 6: AA", text)
        self.assertNotIn("Ещё 1 в SNP Lab", text)
        self.assertNotIn("Найдено с трактовкой", text)

    def test_renderer_deduplicates_interesting_snp_topics(self) -> None:
        interesting_snps = DNAPassportInterestingSnpsSummary(
            status="ok",
            total=10,
            found=2,
            missing=8,
            items=(
                DNAPassportInterestingSnpItem(
                    "rs713598",
                    "Горький вкус: TAS2R38",
                    "Вкус и запах",
                    "TAS2R38",
                    "GG",
                    "Чаще более низкая чувствительность к PTC/PROP",
                ),
                DNAPassportInterestingSnpItem(
                    "rs10246939",
                    "Горький вкус: TAS2R38-3",
                    "Вкус и запах",
                    "TAS2R38",
                    "CC",
                    "Чаще более высокая чувствительность к PTC/PROP",
                ),
            ),
        )

        text = render_dna_passport_html(_passport_data(interesting_snps=interesting_snps))

        self.assertIn("Горький вкус: TAS2R38: GG", text)
        self.assertNotIn("Горький вкус: TAS2R38-3", text)

    def test_renderer_uses_user_friendly_lineage_statuses_summary_and_recommendations(self) -> None:
        data = _passport_data(
            lineage=DNAPassportLineageReadiness(status="ok", y_markers_detected=False, y_count=0, mtdna_markers_detected=True, mtdna_count=179)
        )
        text = render_dna_passport_html(data)

        self.assertIn("Отцовская линия: недоступна по этому файлу", text)
        self.assertIn("Материнская линия: ограниченные данные", text)
        self.assertIn("Для точного определения прямых линий нужны специализированные Y-DNA и mtDNA-тесты", text)
        self.assertIn("Autosomal raw подходит для анализа происхождения", text)
        self.assertIn("По G25 образец относится к кавказскому генетическому пространству", text)
        self.assertIn("➡️ Что исследовать дальше", text)
        recommendations_section = text.split("➡️ Что исследовать дальше", 1)[1].split("ℹ️ Важно", 1)[0]
        recommendation_lines = [line for line in recommendations_section.splitlines() if line.startswith("• ")]
        self.assertLessEqual(len(recommendation_lines), 3)
        self.assertNotIn("DNA-файл прочитан", text)
        self.assertNotIn("G25-сравнение рассчитано", text)

    def test_renderer_handles_missing_raw_g25_and_partial_traits(self) -> None:
        data = DNAPassportData(
            sample=DNAPassportSampleSummary(status="ok", sample_id="sample-1", display_name="Zaur"),
            raw=DNAPassportRawSummary(status="unavailable"),
            g25=DNAPassportG25Summary(status="unavailable"),
            traits=DNAPassportTraitsSummary(
                status="partial",
                traits=(DNAPassportTraitItem("pgs003835_height", "Height", "limited", percentile=72.0, confidence="medium"),),
                failures=(DNAPassportTraitItem("pgs000336_chronotype", "Chronotype", "low_overlap", error="x"),),
            ),
            lineage=DNAPassportLineageReadiness(status="unavailable"),
            generated_at="2026-06-14T00:00:00Z",
        )

        text = render_dna_passport_html(data)

        self.assertIn("Autosomal raw не прикреплён", text)
        self.assertIn("G25-профиль не прикреплён", text)
        self.assertIn("Рост — 72% · ★★☆", text)
        self.assertIn("Хронотип — недостаточно данных", text)
        self.assertIn("Недоступны без autosomal raw", text)

    def test_renderer_shows_temporary_raw_g25_source(self) -> None:
        data = _passport_data()
        data = DNAPassportData(
            sample=data.sample,
            raw=data.raw,
            g25=DNAPassportG25Summary(
                status="ok",
                source="calculated_from_raw",
                display_name="Zaur",
                target_name="Zaur",
                region="Caucasus",
                top_modern=data.g25.top_modern,
                first_distance=data.g25.first_distance,
                first_second_gap=data.g25.first_second_gap,
            ),
            traits=data.traits,
            lineage=data.lineage,
            generated_at=data.generated_at,
        )

        text = render_dna_passport_html(data)

        self.assertIn("Генетическое пространство: Кавказ", text)
        self.assertIn("Ближайшие референсные популяции", text)

    def test_renderer_hides_raw_g25_traceback(self) -> None:
        data = DNAPassportData(
            sample=DNAPassportSampleSummary(status="ok", sample_id="sample-1", display_name="Zaur"),
            raw=DNAPassportRawSummary(status="ok", raw_file_id="raw-1"),
            g25=DNAPassportG25Summary(
                status="error",
                source="calculated_from_raw",
                error="Traceback (most recent call last): boom",
            ),
            traits=DNAPassportTraitsSummary(status="unavailable"),
            lineage=DNAPassportLineageReadiness(status="ok"),
            generated_at="2026-06-14T00:00:00Z",
        )

        text = render_dna_passport_html(data)

        self.assertIn("Не удалось получить координаты G25 из этого DNA-файла", text)
        self.assertIn("Вы можете добавить готовый G25-профиль", text)
        self.assertNotIn("Traceback", text)


def _run(coro):
    import asyncio

    return asyncio.run(coro)


def _context(store: _FakeStore, *, admin_ids=None, admin_usernames=None):
    return SimpleNamespace(
        application=SimpleNamespace(
            bot_data={
                "my_data_store": store,
                "traits_runtime": object(),
                "g25_access_store": _FakeAccessStore(admin_ids, admin_usernames),
            }
        ),
        user_data={},
    )


def _callback_update(data: str, *, user_id: int, message: _FakeMessage, username: str | None = None):
    query = _FakeQuery(data, message)
    user = SimpleNamespace(id=user_id, username=username)
    chat = SimpleNamespace(id=message.chat_id)
    return SimpleNamespace(callback_query=query, effective_user=user, effective_chat=chat)


def _labels(keyboard) -> list[str]:
    return [button.text for row in keyboard.inline_keyboard for button in row]


def _last_call(message: _FakeMessage, name: str):
    for call in reversed(message.calls):
        if call[0] == name:
            return call
    raise AssertionError(name)


def _boxes_overlap(first: tuple[int, int, int, int], second: tuple[int, int, int, int]) -> bool:
    return first[0] < second[2] and first[2] > second[0] and first[1] < second[3] and first[3] > second[1]


def _sample(sample_id: str, name: str, *, raw_file_id: str = "") -> SampleAsset:
    return SampleAsset(sample_id, name, raw_file_id, [], "2026-06-14T00:00:00")


def _coordinate(asset_id: str, name: str) -> CoordinateAsset:
    return CoordinateAsset(asset_id, name, name, "g25", "Target," + ",".join(["0"] * 25), "manual", "2026-06-14T00:00:00")


def _product(product_id: str):
    for product in REPORT_PRODUCTS:
        if product.product_id == product_id:
            return product
    raise AssertionError(product_id)


def _passport_data(
    sample_name: str = "Zaur",
    g25_name: str = "Main",
    population: str = "Balkar",
    raw: DNAPassportRawSummary | None = None,
    interesting_snps: DNAPassportInterestingSnpsSummary | None = None,
    lineage: DNAPassportLineageReadiness | None = None,
) -> DNAPassportData:
    return DNAPassportData(
        sample=DNAPassportSampleSummary(status="ok", sample_id="sample-1", display_name=sample_name),
        raw=raw or DNAPassportRawSummary(
            status="ok",
            raw_file_id="raw-1",
            original_file_name="raw.txt",
            provider_hint="FamilyTreeDNA",
            called_snps=612438,
            autosomal_count=598210,
            x_count=14012,
            y_count=184,
            mtdna_count=32,
            call_rate=0.987,
        ),
        g25=DNAPassportG25Summary(
            status="ok",
            source="attached",
            coordinate_id="coord-1",
            display_name=g25_name,
            region="Caucasus",
            top_modern=(
                DNAPassportG25Population(population, 0.0214),
                DNAPassportG25Population("Cherkes", 0.0256),
                DNAPassportG25Population("Kumyk", 0.0272),
            ),
            first_distance=0.0214,
            first_second_gap=0.0023,
        ),
        traits=DNAPassportTraitsSummary(
            status="ok",
            traits=(
                DNAPassportTraitItem("pgs003835_height", "Height", "limited", percentile=21.0, confidence="medium"),
                DNAPassportTraitItem("pgs000336_chronotype", "Chronotype", "limited", percentile=40.0, confidence="low"),
                DNAPassportTraitItem("pgs001123_coffee", "Coffee consumption", "limited", percentile=73.0, confidence="medium"),
                DNAPassportTraitItem("pgs001150_sleep_duration", "Sleep duration", "limited", percentile=28.0, confidence="low"),
                DNAPassportTraitItem("pgs001927_mean_hand_grip_strength", "Grip strength", "limited", percentile=1.0, confidence="low"),
                DNAPassportTraitItem("pgs001075_walking_pace", "Walking pace", "limited", percentile=87.0, confidence="low"),
                DNAPassportTraitItem("pgs001897_skin_pigmentation", "Skin pigmentation", "limited", percentile=11.0, confidence="low"),
                DNAPassportTraitItem("pgs002011_water_intake", "Water intake", "limited", percentile=79.0, confidence="low"),
            ),
        ),
        interesting_snps=interesting_snps or DNAPassportInterestingSnpsSummary(
            status="ok",
            total=10,
            found=2,
            missing=8,
            items=(
                DNAPassportInterestingSnpItem(
                    "rs4988235",
                    "Переносимость лактозы",
                    "Питание",
                    "MCM6/LCT",
                    "CT",
                    "Промежуточный вариант переносимости лактозы",
                ),
                DNAPassportInterestingSnpItem(
                    "rs17822931",
                    "Тип ушной серы",
                    "Внешние признаки",
                    "ABCC11",
                    "AA",
                    "Сухой тип ушной серы",
                ),
            ),
        ),
        lineage=lineage or DNAPassportLineageReadiness(status="ok", y_markers_detected=True, y_count=184, mtdna_markers_detected=True, mtdna_count=32),
        generated_at="2026-06-14T00:00:00Z",
    )


if __name__ == "__main__":
    unittest.main()
