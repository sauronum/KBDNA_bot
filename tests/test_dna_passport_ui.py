from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.features.my_data.storage import CoordinateAsset, SampleAsset
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
    build_passport_intro_keyboard,
    build_sample_picker_keyboard,
    handle_sample_selected,
    passport_intro_text,
    sample_picker_text,
    show_sample_picker_menu,
)
from app.features.reports.dna_passport.render import render_dna_passport_html
from app.features.reports.menu import (
    REPORT_PRODUCTS,
    build_report_detail_keyboard,
    build_reports_keyboard,
    reports_callback_handler,
    reports_text,
    report_detail_text,
    show_reports_menu,
)


class _FakeMessage:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, object, str | None]] = []

    async def edit_text(self, text, reply_markup=None, parse_mode=None):
        self.calls.append(("edit_text", text, reply_markup, parse_mode))

    async def reply_text(self, text, reply_markup=None, parse_mode=None, do_quote=False):
        self.calls.append(("reply_text", text, reply_markup, parse_mode))
        return self


class _FakeQuery:
    def __init__(self, data: str, message: _FakeMessage) -> None:
        self.data = data
        self.message = message
        self.answers: list[tuple[str | None, bool]] = []

    async def answer(self, text=None, show_alert=False):
        self.answers.append((text, show_alert))


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
        labels_ru = [button.text for row in build_reports_keyboard().inline_keyboard for button in row]
        labels_en = [button.text for row in build_reports_keyboard(lang="en").inline_keyboard for button in row]

        self.assertIn("🧬 DNA-паспорт", labels_ru)
        self.assertIn("🧬 DNA passport", labels_en)
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

    def test_passport_card_has_generate_button_and_no_free_or_development_status(self) -> None:
        passport = _product("passport")
        text = report_detail_text(passport)
        labels = [button.text for row in build_report_detail_keyboard(passport).inline_keyboard for button in row]
        callbacks = [button.callback_data for row in build_report_detail_keyboard(passport).inline_keyboard for button in row]

        self.assertEqual(text, passport_intro_text())
        self.assertIn("🧬 Сформировать DNA-паспорт", labels)
        self.assertIn("reports:passport:samples:0", callbacks)
        self.assertNotIn("Бесплатно", text)
        self.assertNotIn("В разработке", text)

    def test_admin_opens_passport_card_and_starts_generation(self) -> None:
        sample = _sample("sample-1", "Zaur")
        store = _FakeStore(samples=[sample])
        service = _FakePassportService()
        message = _FakeMessage()

        update = _callback_update("reports:info:passport", user_id=1, message=message)
        with patch("app.features.reports.menu.ensure_active_main_menu", return_value=True):
            _run(reports_callback_handler(update, _context(store, admin_ids={1})))

        self.assertTrue(any("Сформировать DNA-паспорт" in label for label in _labels(message.calls[-1][2])))

        update = _callback_update("reports:passport:sample:sample-1", user_id=1, message=message)
        with patch("app.features.reports.menu.ensure_active_main_menu", return_value=True), patch(
            "app.features.reports.dna_passport.menu._passport_service",
            return_value=service,
        ):
            _run(reports_callback_handler(update, _context(store, admin_ids={1})))

        self.assertEqual(service.calls[0]["sample_id"], "sample-1")
        self.assertEqual(message.calls[-1][3], "HTML")

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
        self.assertIn("reports:passport:intro", callbacks)

    def test_no_samples_screen_is_handled(self) -> None:
        text = sample_picker_text([])
        keyboard = build_sample_picker_keyboard([])
        callbacks = [button.callback_data for row in keyboard.inline_keyboard for button in row]

        self.assertIn("У вас пока нет образцов", text)
        self.assertEqual(callbacks, ["reports:passport:intro", "main:cancel"])

    def test_show_sample_picker_uses_existing_sample_store(self) -> None:
        store = _FakeStore(samples=[_sample("sample-1", "Zaur")])
        message = _FakeMessage()

        _run(show_sample_picker_menu(message, _context(store), 1, page=0))

        self.assertEqual(store.calls, ["list_samples"])
        self.assertIn("Выберите образец", message.calls[-1][1])

    def test_sample_without_g25_runs_passport_immediately(self) -> None:
        store = _FakeStore(samples=[_sample("sample-1", "Zaur")], coordinates={"sample-1": []})
        service = _FakePassportService()
        message = _FakeMessage()

        with patch("app.features.reports.dna_passport.menu._passport_service", return_value=service):
            _run(handle_sample_selected(message, _context(store), 1, sample_id="sample-1"))

        self.assertEqual(service.calls[0]["sample_id"], "sample-1")
        self.assertIsNone(service.calls[0]["g25_coordinate_id"])
        self.assertEqual(message.calls[0][1], "🧬 Формируем DNA-паспорт…")
        self.assertEqual(message.calls[-1][3], "HTML")

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
    return SimpleNamespace(callback_query=query, effective_user=user)


def _labels(keyboard) -> list[str]:
    return [button.text for row in keyboard.inline_keyboard for button in row]


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
