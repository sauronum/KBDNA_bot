from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputFile, Update
from telegram.ext import ContextTypes

from app.i18n import get_user_language, t
from app.main_menu import ensure_active_main_menu
from app.features.reports.g25_platform import (
    G25PlatformReport,
    G25PlatformReportError,
    choose_sample_g25_coordinate,
    generate_g25_platform_report,
    safe_artifact_filename,
)


REPORTS_CALLBACK_PREFIX = "reports"
REPORT_SAMPLE_PAGE_SIZE = 8
PLATFORM_REPORT_PRODUCT_ID = "r0"


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReportProduct:
    product_id: str
    emoji: str
    title_ru: str
    title_en: str
    price_ru: str
    price_en: str
    description_ru: str
    description_en: str
    is_paid: bool = False

    def title(self, lang: str) -> str:
        return self.title_en if lang == "en" else self.title_ru

    def price(self, lang: str) -> str:
        return self.price_en if lang == "en" else self.price_ru

    def description(self, lang: str) -> str:
        return self.description_en if lang == "en" else self.description_ru

    def button_label(self, lang: str) -> str:
        return f"{self.emoji} {self.title(lang)} · {self.price(lang)}"


REPORT_PRODUCTS: tuple[ReportProduct, ...] = (
    ReportProduct(
        product_id="r0",
        emoji="🧬",
        title_ru="Комплексный обзор",
        title_en="Complete overview",
        price_ru="Бесплатно",
        price_en="Free",
        description_ru=(
            "Короткий понятный отчёт по образцу: что уже есть в My DNA, какие G25-профили привязаны, "
            "какие разделы можно запускать дальше и где будут появляться сохранённые результаты."
        ),
        description_en=(
            "A short sample overview: stored My DNA data, linked G25 profiles, suggested next steps, "
            "and where saved results will live."
        ),
    ),
    ReportProduct(
        product_id="r1",
        emoji="🏺",
        title_ru="Древние совпадения",
        title_en="Ancient matches",
        price_ru="⭐ 99",
        price_en="⭐ 99",
        description_ru=(
            "Заготовка для красивого отчёта по древним и средневековым параллелям: близкие профили, "
            "временные пласты и аккуратные пояснения без ручного входа в DNA Lab."
        ),
        description_en=(
            "A polished report concept for ancient and medieval parallels: close profiles, time layers, "
            "and plain-language notes without manual DNA Lab setup."
        ),
        is_paid=True,
    ),
    ReportProduct(
        product_id="r2",
        emoji="⛰",
        title_ru="Кавказ / Степь / Ближний Восток",
        title_en="Caucasus / Steppe / Near East",
        price_ru="⭐ 149",
        price_en="⭐ 149",
        description_ru=(
            "Региональный комплексный отчёт: G25-ориентиры, близкие кластеры, исторический контекст "
            "и компактное резюме по выбранному образцу."
        ),
        description_en=(
            "A regional report concept: G25 anchors, close clusters, historical context, "
            "and a compact summary for the selected sample."
        ),
        is_paid=True,
    ),
)


def _copy(lang: str, ru: str, en: str) -> str:
    return en if lang == "en" else ru


def _product(product_id: str) -> ReportProduct | None:
    for item in REPORT_PRODUCTS:
        if item.product_id == product_id:
            return item
    return None


def _samples(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> list[object]:
    store = context.application.bot_data.get("my_data_store")
    if store is None:
        return []
    try:
        return list(store.list_samples(user_id))
    except Exception:
        return []


def _sample_by_id(context: ContextTypes.DEFAULT_TYPE, user_id: int, sample_id: str) -> object | None:
    store = context.application.bot_data.get("my_data_store")
    if store is None:
        return None
    try:
        sample = store.get_sample(user_id, sample_id)
    except Exception:
        return None
    return sample


def _sample_page_bounds(samples: list[object], page: int) -> tuple[int, int, int, int]:
    page_count = max(1, (len(samples) + REPORT_SAMPLE_PAGE_SIZE - 1) // REPORT_SAMPLE_PAGE_SIZE)
    safe_page = min(max(int(page), 0), page_count - 1)
    start = safe_page * REPORT_SAMPLE_PAGE_SIZE
    end = min(start + REPORT_SAMPLE_PAGE_SIZE, len(samples))
    return safe_page, start, end, page_count


def _is_report_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    access_store = context.application.bot_data.get("g25_access_store")
    if access_store is None or not hasattr(access_store, "is_admin"):
        return False
    try:
        return bool(access_store.is_admin(update))
    except Exception:
        return False


def reports_text(*, lang: str = "ru", show_products: bool = True) -> str:
    if not show_products:
        if lang == "en":
            return (
                "📊 Reports\n\n"
                "Ready-made DNA reports are being prepared.\n\n"
                "Saved DNA Lab results remain available inside each sample card."
            )
        return (
            "📊 Отчёты\n\n"
            "Готовые комплексные отчёты пока готовятся.\n\n"
            "Сохранённые результаты DNA Lab доступны внутри карточек образцов."
        )
    if lang == "en":
        return (
            "📊 Reports\n\n"
            "Ready-made DNA reports for people who want a clear result without configuring DNA Lab by hand.\n\n"
            "Choose a report, then choose a sample. Saved DNA Lab results still live inside each sample card."
        )
    return (
        "📊 Отчёты\n\n"
        "Готовые комплексные отчёты по вашим образцам без ручной настройки DNA Lab.\n\n"
        "Выберите отчёт, затем образец. Сохранённые результаты DNA Lab остаются внутри карточек образцов."
    )


def build_reports_keyboard(
    *,
    lang: str = "ru",
    back_callback: str = "mydna:root",
    show_products: bool = True,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if show_products:
        rows.extend(
            [InlineKeyboardButton(product.button_label(lang), callback_data=f"{REPORTS_CALLBACK_PREFIX}:s:{product.product_id}")]
            for product in REPORT_PRODUCTS
        )
    rows.append(
        [
            InlineKeyboardButton(t("nav.back", lang), callback_data=back_callback),
            InlineKeyboardButton(t("nav.cancel", lang), callback_data="main:cancel"),
        ]
    )
    return InlineKeyboardMarkup(rows)


def report_detail_text(product: ReportProduct, samples_count: int, *, lang: str = "ru") -> str:
    if lang == "en":
        if samples_count:
            tail = "Choose a sample below. This is a placeholder screen for now."
        else:
            tail = "Add a raw file first, then come back here to generate this report."
        return (
            f"{product.emoji} {product.title(lang)}\n"
            f"{product.price(lang)}\n\n"
            f"{product.description(lang)}\n\n"
            f"{tail}\n\n"
            "Saved DNA Lab results remain available from Samples -> sample -> Reports."
        )
    tail = (
        "Выберите образец ниже. Пока это экран-заглушка для будущей генерации."
        if samples_count
        else "Сначала загрузите файл и создайте образец, потом вернитесь сюда за отчётом."
    )
    return (
        f"{product.emoji} {product.title(lang)}\n"
        f"{product.price(lang)}\n\n"
        f"{product.description(lang)}\n\n"
        f"{tail}\n\n"
        "Сохранённые результаты DNA Lab доступны в Образцы -> образец -> Отчёты."
    )


def build_report_detail_keyboard(
    product: ReportProduct,
    samples: list[object],
    *,
    page: int = 0,
    lang: str = "ru",
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if samples:
        safe_page, start, end, page_count = _sample_page_bounds(samples, page)
        for index, sample in enumerate(samples[start:end], start=start + 1):
            sample_id = str(getattr(sample, "asset_id", ""))
            sample_name = str(getattr(sample, "display_name", _copy(lang, "Образец", "Sample")))
            rows.append(
                [
                    InlineKeyboardButton(
                        f"{index}. {sample_name}",
                        callback_data=f"{REPORTS_CALLBACK_PREFIX}:c:{product.product_id}:{sample_id}",
                    )
                ]
            )
        if page_count > 1:
            nav_row: list[InlineKeyboardButton] = []
            if safe_page > 0:
                nav_row.append(
                    InlineKeyboardButton(
                        f"← {t('nav.back', lang)}",
                        callback_data=f"{REPORTS_CALLBACK_PREFIX}:sp:{product.product_id}:{safe_page - 1}",
                    )
                )
            if end < len(samples):
                nav_row.append(
                    InlineKeyboardButton(
                        f"{_copy(lang, 'Далее', 'Next')} →",
                        callback_data=f"{REPORTS_CALLBACK_PREFIX}:sp:{product.product_id}:{safe_page + 1}",
                    )
                )
            if nav_row:
                rows.append(nav_row)
    else:
        rows.append(
            [
                InlineKeyboardButton(
                    _copy(lang, "📤 Загрузить файл", "📤 Upload file"),
                    callback_data="my_data:raw_files_upload:root",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(t("nav.back", lang), callback_data=f"{REPORTS_CALLBACK_PREFIX}:root"),
            InlineKeyboardButton(t("nav.cancel", lang), callback_data="main:cancel"),
        ]
    )
    return InlineKeyboardMarkup(rows)


def report_confirmation_text(product: ReportProduct, sample: object, *, lang: str = "ru") -> str:
    sample_name = str(getattr(sample, "display_name", _copy(lang, "Образец", "Sample")))
    if lang == "en":
        if product.product_id == PLATFORM_REPORT_PRODUCT_ID:
            return (
                f"{product.emoji} {product.title(lang)}\n\n"
                f"Sample: {sample_name}\n"
                f"Price: {product.price(lang)}\n\n"
                "Admin prototype: the bot will take the sample's saved G25 profile, run dna_platform backbone analysis, "
                "then send a short summary and generated artifacts."
            )
        return (
            f"{product.emoji} {product.title(lang)}\n\n"
            f"Sample: {sample_name}\n"
            f"Price: {product.price(lang)}\n\n"
            "This is a clean placeholder: the real report generator and Stars payment flow will be connected later."
        )
    if product.product_id == PLATFORM_REPORT_PRODUCT_ID:
        return (
            f"{product.emoji} {product.title(lang)}\n\n"
            f"Образец: {sample_name}\n"
            f"Стоимость: {product.price(lang)}\n\n"
            "Админский прототип: бот возьмёт сохранённый G25-профиль образца, запустит backbone-анализ через dna_platform "
            "и отправит краткое резюме с артефактами."
        )
    return (
        f"{product.emoji} {product.title(lang)}\n\n"
        f"Образец: {sample_name}\n"
        f"Стоимость: {product.price(lang)}\n\n"
        "Это аккуратная заглушка: настоящую генерацию отчёта и оплату звёздами подключим следующим шагом."
    )


def build_report_confirmation_keyboard(product: ReportProduct, sample: object, *, lang: str = "ru") -> InlineKeyboardMarkup:
    sample_id = str(getattr(sample, "asset_id", ""))
    if product.is_paid:
        action_label = _copy(lang, f"Получить за {product.price(lang)}", f"Get for {product.price(lang)}")
        action_callback = f"{REPORTS_CALLBACK_PREFIX}:pay:{product.product_id}:{sample_id}"
    else:
        action_label = _copy(lang, "🚀 Сформировать демо", "🚀 Generate demo")
        action_callback = f"{REPORTS_CALLBACK_PREFIX}:g:{product.product_id}:{sample_id}"
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(action_label, callback_data=action_callback)],
            [
                InlineKeyboardButton(t("nav.back", lang), callback_data=f"{REPORTS_CALLBACK_PREFIX}:s:{product.product_id}"),
                InlineKeyboardButton(t("nav.cancel", lang), callback_data="main:cancel"),
            ],
        ]
    )


def report_demo_text(product: ReportProduct, sample: object, *, lang: str = "ru") -> str:
    sample_name = str(getattr(sample, "display_name", _copy(lang, "Образец", "Sample")))
    if lang == "en":
        return (
            f"✅ {product.title(lang)}\n\n"
            f"Sample: {sample_name}\n\n"
            "Report preview\n"
            "1. Input data check\n"
            "2. G25 and raw-file readiness\n"
            "3. Suggested next DNA Lab calculations\n\n"
            "The full renderer will replace this placeholder."
        )
    return (
        f"✅ {product.title(lang)}\n\n"
        f"Образец: {sample_name}\n\n"
        "Черновик отчёта\n"
        "1. Проверка исходных данных\n"
        "2. Готовность raw/G25\n"
        "3. Что стоит посчитать дальше в DNA Lab\n\n"
        "Позже эту заглушку заменит полноценный генератор."
    )


def payment_stub_text(product: ReportProduct, sample: object, *, lang: str = "ru") -> str:
    sample_name = str(getattr(sample, "display_name", _copy(lang, "Образец", "Sample")))
    if lang == "en":
        return (
            f"⭐ {product.title(lang)}\n\n"
            f"Sample: {sample_name}\n"
            f"Price: {product.price(lang)}\n\n"
            "Stars payment is not connected yet. This screen reserves the future purchase flow."
        )
    return (
        f"⭐ {product.title(lang)}\n\n"
        f"Образец: {sample_name}\n"
        f"Стоимость: {product.price(lang)}\n\n"
        "Оплата звёздами пока не подключена. Этот экран фиксирует будущий сценарий покупки."
    )


def build_stub_keyboard(*, lang: str = "ru") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(_copy(lang, "📊 К отчётам", "📊 Reports"), callback_data=f"{REPORTS_CALLBACK_PREFIX}:root"),
                InlineKeyboardButton(t("nav.cancel", lang), callback_data="main:cancel"),
            ],
        ]
    )


def platform_report_running_text(product: ReportProduct, sample: object, *, lang: str = "ru") -> str:
    sample_name = str(getattr(sample, "display_name", _copy(lang, "Образец", "Sample")))
    if lang == "en":
        return (
            f"{product.emoji} {product.title(lang)}\n\n"
            f"Sample: {sample_name}\n\n"
            "Generating the admin prototype report. This can take a few minutes."
        )
    return (
        f"{product.emoji} {product.title(lang)}\n\n"
        f"Образец: {sample_name}\n\n"
        "Генерирую админский прототип отчёта. Это может занять несколько минут."
    )


def platform_report_missing_g25_text(sample: object, *, lang: str = "ru") -> str:
    sample_name = str(getattr(sample, "display_name", _copy(lang, "Образец", "Sample")))
    if lang == "en":
        return (
            "🧬 Complete overview\n\n"
            f"Sample: {sample_name}\n\n"
            "No saved G25 profile is attached to this sample. Add or extract G25 first, then run the report again."
        )
    return (
        "🧬 Комплексный обзор\n\n"
        f"Образец: {sample_name}\n\n"
        "У этого образца нет привязанного G25-профиля. Сначала добавьте или получите G25, затем запустите отчёт снова."
    )


def platform_report_error_text(error: Exception, *, lang: str = "ru") -> str:
    detail = str(error).strip()
    if "Traceback" in detail or "FileNotFoundError" in detail:
        detail = "Technical backend error. Details are in the server log."
    elif len(detail) > 240:
        detail = detail[:240].rstrip() + "..."
    if lang == "en":
        return (
            "🧬 Complete overview\n\n"
            "Could not generate the dna_platform report.\n\n"
            f"{detail}"
        )
    return (
        "🧬 Комплексный обзор\n\n"
        "Не удалось сформировать отчёт через dna_platform.\n\n"
        f"{detail}"
    )


def platform_report_result_text(report: G25PlatformReport, *, lang: str = "ru") -> str:
    title = "🧬 Complete overview" if lang == "en" else "🧬 Комплексный обзор"
    sample_label = "Sample" if lang == "en" else "Образец"
    g25_label = "G25 profile" if lang == "en" else "G25-профиль"
    artifact_label = "Artifacts" if lang == "en" else "Артефакты"
    lines = [
        title,
        "",
        f"{sample_label}: {report.sample_name}",
        f"{g25_label}: {report.coordinate_name}",
        "",
        "Backbone summary:",
    ]
    lines.extend(f"• {item}" for item in report.summary_lines[:8])
    lines.extend(
        [
            "",
            f"{artifact_label}: {len(report.artifact_paths)} SVG + analysis.json",
        ]
    )
    return "\n".join(lines)


def _reports_storage_root(context: ContextTypes.DEFAULT_TYPE) -> Path:
    my_data_store = context.application.bot_data.get("my_data_store")
    root_dir = getattr(my_data_store, "root_dir", None)
    if root_dir is not None:
        return Path(root_dir).parent / "reports"
    return Path("storage") / "reports"


async def show_reports_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    edit_existing: bool = False,
    lang: str = "ru",
    back_callback: str | None = None,
    show_products: bool = True,
    **_ignored,
) -> None:
    text = reports_text(lang=lang, show_products=show_products)
    markup = build_reports_keyboard(lang=lang, back_callback=back_callback or "mydna:root", show_products=show_products)
    if edit_existing:
        await message.edit_text(text, reply_markup=markup)
    else:
        await message.reply_text(text, reply_markup=markup, do_quote=False)


async def _show_report_detail(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    product: ReportProduct,
    *,
    page: int = 0,
    lang: str = "ru",
) -> None:
    samples = _samples(context, user_id)
    text = report_detail_text(product, len(samples), lang=lang)
    markup = build_report_detail_keyboard(product, samples, page=page, lang=lang)
    await message.edit_text(text, reply_markup=markup)


async def _show_report_confirmation(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    product: ReportProduct,
    sample_id: str,
    *,
    lang: str = "ru",
) -> None:
    sample = _sample_by_id(context, user_id, sample_id)
    if sample is None:
        await message.edit_text(
            _copy(lang, "Отчёт\n\nОбразец не найден. Откройте My DNA заново.", "Report\n\nSample not found. Open My DNA again."),
            reply_markup=build_reports_keyboard(lang=lang),
        )
        return
    await message.edit_text(
        report_confirmation_text(product, sample, lang=lang),
        reply_markup=build_report_confirmation_keyboard(product, sample, lang=lang),
    )


async def _show_report_stub(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    product: ReportProduct,
    sample_id: str,
    *,
    lang: str = "ru",
    paid: bool = False,
) -> None:
    sample = _sample_by_id(context, user_id, sample_id)
    if sample is None:
        await message.edit_text(
            _copy(lang, "Отчёт\n\nОбразец не найден. Откройте My DNA заново.", "Report\n\nSample not found. Open My DNA again."),
            reply_markup=build_reports_keyboard(lang=lang),
        )
        return
    text = payment_stub_text(product, sample, lang=lang) if paid else report_demo_text(product, sample, lang=lang)
    await message.edit_text(text, reply_markup=build_stub_keyboard(lang=lang))


async def _show_platform_report(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    product: ReportProduct,
    sample_id: str,
    *,
    lang: str = "ru",
) -> None:
    store = context.application.bot_data.get("my_data_store")
    sample = _sample_by_id(context, user_id, sample_id)
    if sample is None or store is None:
        await message.edit_text(
            _copy(lang, "Отчёт\n\nОбразец не найден. Откройте My DNA заново.", "Report\n\nSample not found. Open My DNA again."),
            reply_markup=build_reports_keyboard(lang=lang),
        )
        return

    coordinate = choose_sample_g25_coordinate(store, user_id, sample)
    if coordinate is None:
        await message.edit_text(platform_report_missing_g25_text(sample, lang=lang), reply_markup=build_stub_keyboard(lang=lang))
        return

    await message.edit_text(platform_report_running_text(product, sample, lang=lang), reply_markup=build_stub_keyboard(lang=lang))
    try:
        report = await generate_g25_platform_report(
            storage_root=_reports_storage_root(context),
            sample=sample,
            coordinate=coordinate,
            user_id=user_id,
        )
    except G25PlatformReportError as exc:
        logger.warning("G25 platform report failed: %s", exc)
        await message.edit_text(platform_report_error_text(exc, lang=lang), reply_markup=build_stub_keyboard(lang=lang))
        return
    except Exception as exc:
        logger.exception("Unexpected G25 platform report failure")
        await message.edit_text(platform_report_error_text(exc, lang=lang), reply_markup=build_stub_keyboard(lang=lang))
        return

    await message.edit_text(platform_report_result_text(report, lang=lang), reply_markup=build_stub_keyboard(lang=lang))
    chat_id = getattr(message, "chat_id", None)
    if chat_id is None:
        return
    for artifact_path in report.artifact_paths:
        try:
            with artifact_path.open("rb") as handle:
                await context.bot.send_document(
                    chat_id=chat_id,
                    document=InputFile(handle, filename=safe_artifact_filename(artifact_path)),
                    caption=artifact_path.stem,
                )
        except Exception:
            logger.exception("Could not send G25 platform report artifact: %s", artifact_path)
    try:
        with report.analysis_path.open("rb") as handle:
            await context.bot.send_document(
                chat_id=chat_id,
                document=InputFile(handle, filename="analysis.json"),
                caption="analysis.json",
            )
    except Exception:
        logger.exception("Could not send G25 platform analysis artifact: %s", report.analysis_path)


async def reports_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None or query.message is None:
        return
    if not query.data.startswith(f"{REPORTS_CALLBACK_PREFIX}:"):
        return

    if not await ensure_active_main_menu(update, context):
        return

    await query.answer()
    user = update.effective_user
    if user is None:
        return
    user_id = int(user.id)
    lang = get_user_language(context, user_id)
    is_admin = _is_report_admin(update, context)

    parts = query.data.split(":")
    action = parts[1] if len(parts) > 1 else "root"
    if not is_admin:
        await show_reports_menu(query.message, context, user_id, edit_existing=True, lang=lang, show_products=False)
        return
    if action in {"root", "p"}:
        await show_reports_menu(query.message, context, user_id, edit_existing=True, lang=lang, show_products=True)
        return
    if action in {"s", "sp"}:
        product_id = parts[2] if len(parts) > 2 else ""
        product = _product(product_id)
        if product is None:
            await show_reports_menu(query.message, context, user_id, edit_existing=True, lang=lang, show_products=True)
            return
        page = int(parts[3]) if action == "sp" and len(parts) > 3 and parts[3].isdigit() else 0
        await _show_report_detail(query.message, context, user_id, product, page=page, lang=lang)
        return
    if action in {"c", "g", "pay"}:
        product_id = parts[2] if len(parts) > 2 else ""
        sample_id = parts[3] if len(parts) > 3 else ""
        product = _product(product_id)
        if product is None:
            await show_reports_menu(query.message, context, user_id, edit_existing=True, lang=lang, show_products=True)
            return
        if action == "c":
            await _show_report_confirmation(query.message, context, user_id, product, sample_id, lang=lang)
            return
        if action == "g" and product.product_id == PLATFORM_REPORT_PRODUCT_ID:
            await _show_platform_report(query.message, context, user_id, product, sample_id, lang=lang)
            return
        await _show_report_stub(query.message, context, user_id, product, sample_id, lang=lang, paid=action == "pay")
