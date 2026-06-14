from __future__ import annotations

from dataclasses import dataclass

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.i18n import get_user_language, t
from app.features.reports.dna_passport.menu import (
    build_passport_intro_keyboard,
    dna_passport_callback_handler,
    passport_intro_text,
)
from app.main_menu import ensure_active_main_menu


REPORTS_CALLBACK_PREFIX = "reports"


@dataclass(frozen=True)
class ReportProduct:
    product_id: str
    emoji: str
    title_ru: str
    title_en: str
    summary_ru: str
    summary_en: str
    bullets_ru: tuple[str, ...]
    bullets_en: tuple[str, ...]
    status_ru: str
    status_en: str
    note_ru: str = ""
    note_en: str = ""
    free: bool = False
    extra_ru: tuple[str, ...] = ()
    extra_en: tuple[str, ...] = ()

    def title(self, lang: str) -> str:
        return self.title_en if lang == "en" else self.title_ru

    def summary(self, lang: str) -> str:
        return self.summary_en if lang == "en" else self.summary_ru

    def bullets(self, lang: str) -> tuple[str, ...]:
        return self.bullets_en if lang == "en" else self.bullets_ru

    def status(self, lang: str) -> str:
        return self.status_en if lang == "en" else self.status_ru

    def note(self, lang: str) -> str:
        return self.note_en if lang == "en" else self.note_ru

    def extra(self, lang: str) -> tuple[str, ...]:
        return self.extra_en if lang == "en" else self.extra_ru

    def button_label(self, lang: str) -> str:
        title = self.title(lang)
        if self.free and self.product_id != "passport":
            return f"{self.emoji} {title} · {'Free' if lang == 'en' else 'Бесплатно'}"
        return f"{self.emoji} {title}"


REPORT_PRODUCTS: tuple[ReportProduct, ...] = (
    ReportProduct(
        product_id="passport",
        emoji="🧬",
        title_ru="DNA-паспорт",
        title_en="DNA passport",
        summary_ru="Краткий обзор загруженного образца и доступных возможностей анализа.",
        summary_en="A short overview of the uploaded sample and available analysis options.",
        bullets_ru=(
            "сведения об исходном DNA-файле",
            "оценку доступности анализов",
            "краткое положение в пространстве G25",
            "основные результаты DNA Lab",
            "рекомендации по дальнейшему исследованию",
        ),
        bullets_en=(
            "source DNA file details",
            "analysis availability check",
            "short G25 coordinate-space position",
            "main DNA Lab results",
            "recommended next research steps",
        ),
        status_ru="Стоимость: Бесплатно\n\nВ разработке",
        status_en="Price: Free\n\nIn development",
        free=True,
    ),
    ReportProduct(
        product_id="origin_portrait",
        emoji="🧭",
        title_ru="Портрет происхождения",
        title_en="Origin portrait",
        summary_ru="Комплексное исследование генетического происхождения, объединяющее современные и древние сравнения.",
        summary_en="A combined ancestry report with modern and ancient comparisons.",
        bullets_ru=(
            "положение на глобальной и региональной карте",
            "ближайшие современные популяции",
            "основные направления генетического сходства",
            "модели происхождения",
            "древние генетические пласты",
            "единый итог понятным языком",
        ),
        bullets_en=(
            "global and regional map position",
            "closest modern populations",
            "main directions of genetic similarity",
            "ancestry models",
            "ancient genetic layers",
            "plain-language final summary",
        ),
        status_ru="Статус: В разработке",
        status_en="Status: In development",
    ),
    ReportProduct(
        product_id="ancient_roots",
        emoji="🏺",
        title_ru="Древние корни",
        title_en="Ancient roots",
        summary_ru="Исследование сходства с древними популяциями и археологическими группами разных эпох.",
        summary_en="A report on similarity to ancient populations and archaeological groups from different periods.",
        bullets_ru=(
            "ближайшие древние образцы",
            "временную шкалу",
            "географию находок",
            "группировку по эпохам и регионам",
            "объяснение древних генетических связей",
            "отделение реального вывода от простого внешнего сходства",
        ),
        bullets_en=(
            "closest ancient samples",
            "timeline",
            "find geography",
            "grouping by period and region",
            "explanation of ancient genetic links",
            "separation of evidence from superficial similarity",
        ),
        status_ru="Статус: В разработке",
        status_en="Status: In development",
    ),
    ReportProduct(
        product_id="regional_study",
        emoji="⛰",
        title_ru="Региональное исследование",
        title_en="Regional study",
        summary_ru="Углублённый анализ происхождения внутри выбранного историко-географического региона.",
        summary_en="A deeper ancestry analysis inside a selected historical-geographic region.",
        bullets_ru=(
            "сравнение с локальными популяциями",
            "современные и древние референсы",
            "региональные модели происхождения",
            "проверку нескольких гипотез",
            "подробный вывод по выбранному региону",
        ),
        bullets_en=(
            "comparison with local populations",
            "modern and ancient references",
            "regional ancestry models",
            "several hypothesis checks",
            "detailed conclusion for the selected region",
        ),
        extra_ru=(
            "Примеры будущих направлений:",
            "",
            "Кавказ · Степь · Ближний Восток",
            "Европа",
            "Центральная Азия",
            "Южная Азия",
            "Восточная Евразия",
        ),
        extra_en=(
            "Future direction examples:",
            "",
            "Caucasus · Steppe · Near East",
            "Europe",
            "Central Asia",
            "South Asia",
            "East Eurasia",
        ),
        status_ru="Статус: В разработке",
        status_en="Status: In development",
    ),
    ReportProduct(
        product_id="family_comparison",
        emoji="👥",
        title_ru="Семейное сравнение",
        title_en="Family comparison",
        summary_ru="Исследование генетического родства между двумя или несколькими образцами.",
        summary_en="A report on genetic relatedness between two or more samples.",
        bullets_ru=(
            "предполагаемую степень родства",
            "общую длину совпадений",
            "количество и размер общих сегментов",
            "распределение совпадений по хромосомам",
            "возможные варианты родственной связи",
            "оценку надёжности результата",
        ),
        bullets_en=(
            "estimated relationship degree",
            "total shared match length",
            "number and size of shared segments",
            "chromosome-level match distribution",
            "possible relationship scenarios",
            "result confidence estimate",
        ),
        status_ru="Статус: В разработке",
        status_en="Status: In development",
    ),
    ReportProduct(
        product_id="traits_portrait",
        emoji="✨",
        title_ru="Портрет признаков",
        title_en="Trait portrait",
        summary_ru="Сводный отчёт по генетическим признакам, доступным в загруженном DNA-файле.",
        summary_en="A combined report on genetic traits available in the uploaded DNA file.",
        bullets_ru=(
            "наиболее выраженные результаты",
            "признаки внешности и особенностей организма",
            "показатели образа жизни и физической активности",
            "процентили относительно референсной панели",
            "уровень надёжности каждого результата",
            "объяснение роли генетики и среды",
        ),
        bullets_en=(
            "strongest results",
            "appearance and body-related traits",
            "lifestyle and physical activity signals",
            "percentiles against a reference panel",
            "confidence level for each result",
            "explanation of genetics and environment",
        ),
        note_ru="Отчёт не является медицинским заключением.",
        note_en="This report is not a medical conclusion.",
        status_ru="Статус: В разработке",
        status_en="Status: In development",
    ),
    ReportProduct(
        product_id="lineage",
        emoji="🌿",
        title_ru="Отцовская и материнская линии",
        title_en="Paternal and maternal lines",
        summary_ru="Исследование прямых отцовской и материнской линий по Y-DNA и mtDNA.",
        summary_en="A report on direct paternal and maternal lines using Y-DNA and mtDNA.",
        bullets_ru=(
            "положение ветви на генетическом дереве",
            "предполагаемый возраст линии",
            "географию родственных ветвей",
            "современные и древние совпадения",
            "возможные направления миграций",
            "оценку точности определения",
        ),
        bullets_en=(
            "branch position on the genetic tree",
            "estimated lineage age",
            "geography of related branches",
            "modern and ancient matches",
            "possible migration directions",
            "accuracy estimate",
        ),
        note_ru="Доступность отчёта зависит от типа загруженных данных.",
        note_en="Report availability depends on the uploaded data type.",
        status_ru="Статус: В разработке",
        status_en="Status: In development",
    ),
)

LEGACY_PRODUCT_ALIASES = {
    "r0": "passport",
    "r1": "ancient_roots",
    "r2": "regional_study",
}


def _copy(lang: str, ru: str, en: str) -> str:
    return en if lang == "en" else ru


def _product(product_id: str) -> ReportProduct | None:
    product_id = LEGACY_PRODUCT_ALIASES.get(product_id, product_id)
    for item in REPORT_PRODUCTS:
        if item.product_id == product_id:
            return item
    return None


def reports_text(*, lang: str = "ru", show_products: bool = True) -> str:
    if not show_products:
        if lang == "en":
            return (
                "📊 Reports\n\n"
                "This section is in development.\n\n"
                "Personal DNA reports with results, visualizations, and clear explanations will appear here."
            )
        return (
            "📊 Отчёты\n\n"
            "Раздел находится в разработке.\n\n"
            "Здесь появятся персональные DNA-отчёты с результатами, визуализациями и понятными пояснениями."
        )
    if lang == "en":
        return (
            "📊 Reports\n\n"
            "Personal studies based on your DNA samples.\n\n"
            "Each report combines results from different methods into a clear outcome: conclusions, visuals, and explanations.\n\n"
            "Choose a direction."
        )
    return (
        "📊 Отчёты\n\n"
        "Персональные исследования по вашим DNA-образцам.\n\n"
        "Каждый отчёт объединяет результаты разных методов в понятный итог: с выводами, визуализациями и пояснениями.\n\n"
        "Выберите направление."
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
            [
                InlineKeyboardButton(
                    product.button_label(lang),
                    callback_data=f"{REPORTS_CALLBACK_PREFIX}:info:{product.product_id}",
                )
            ]
            for product in REPORT_PRODUCTS
        )
    rows.append(
        [
            InlineKeyboardButton(t("nav.back", lang), callback_data=back_callback),
            InlineKeyboardButton(t("nav.cancel", lang), callback_data="main:cancel"),
        ]
    )
    return InlineKeyboardMarkup(rows)


def report_detail_text(product: ReportProduct, samples_count: int = 0, *, lang: str = "ru") -> str:
    if product.product_id == "passport":
        return passport_intro_text(lang=lang)
    lines = [
        f"{product.emoji} {product.title(lang)}",
        "",
        product.summary(lang),
        "",
        _copy(lang, "Что вы получите:", "What you get:"),
        "",
    ]
    lines.extend(f"• {item}" for item in product.bullets(lang))
    extra = product.extra(lang)
    if extra:
        lines.extend(["", *extra])
    note = product.note(lang)
    if note:
        lines.extend(["", note])
    status = product.status(lang)
    if status:
        lines.extend(["", status])
    return "\n".join(lines)


def build_report_detail_keyboard(
    product: ReportProduct,
    samples: list[object] | None = None,
    *,
    page: int = 0,
    lang: str = "ru",
) -> InlineKeyboardMarkup:
    if product.product_id == "passport":
        return build_passport_intro_keyboard(lang=lang)
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(t("nav.back", lang), callback_data=f"{REPORTS_CALLBACK_PREFIX}:root"),
                InlineKeyboardButton(t("nav.cancel", lang), callback_data="main:cancel"),
            ]
        ]
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


def platform_report_error_text(error: Exception, *, lang: str = "ru") -> str:
    if lang == "en":
        return "📊 Reports\n\nThis report is in development."
    return "📊 Отчёты\n\nЭтот отчёт находится в разработке."


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
    show_products = show_products and _reports_admin_allowed(context, user_id=user_id)
    text = reports_text(lang=lang, show_products=show_products)
    markup = build_reports_keyboard(lang=lang, back_callback=back_callback or "mydna:root", show_products=show_products)
    if edit_existing:
        await message.edit_text(text, reply_markup=markup)
    else:
        await message.reply_text(text, reply_markup=markup, do_quote=False)


async def _show_report_detail(
    message,
    product: ReportProduct,
    *,
    lang: str = "ru",
) -> None:
    await message.edit_text(
        report_detail_text(product, lang=lang),
        reply_markup=build_report_detail_keyboard(product, lang=lang),
    )


async def reports_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None or query.message is None:
        return
    if not query.data.startswith(f"{REPORTS_CALLBACK_PREFIX}:"):
        return

    if not await ensure_active_main_menu(update, context):
        return

    user = update.effective_user
    if user is None:
        return
    user_id = int(user.id)
    lang = get_user_language(context, user_id)

    parts = query.data.split(":")
    action = parts[1] if len(parts) > 1 else "root"
    allowed = _reports_admin_allowed(context, update=update, user_id=user_id)
    if not allowed:
        if action not in {"root", "p"}:
            await query.answer("Раздел находится в разработке.", show_alert=True)
        else:
            await query.answer()
        await show_reports_menu(query.message, context, user_id, edit_existing=True, lang=lang, show_products=False)
        return

    await query.answer()

    if action == "passport":
        await dna_passport_callback_handler(update, context, user_id=user_id, lang=lang)
        return

    if action in {"root", "p"}:
        await show_reports_menu(query.message, context, user_id, edit_existing=True, lang=lang)
        return

    if action in {"info", "s", "sp"}:
        product_id = parts[2] if len(parts) > 2 else ""
        product = _product(product_id)
        if product is None:
            await show_reports_menu(query.message, context, user_id, edit_existing=True, lang=lang)
            return
        await _show_report_detail(query.message, product, lang=lang)
        return

    await show_reports_menu(query.message, context, user_id, edit_existing=True, lang=lang)


def _reports_admin_allowed(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    update: Update | None = None,
    user_id: int | None = None,
) -> bool:
    access_store = context.application.bot_data.get("g25_access_store")
    is_admin = getattr(access_store, "is_admin", None)
    if update is not None and callable(is_admin):
        try:
            return bool(is_admin(update))
        except Exception:
            return False
    if user_id is None:
        return False
    admin_ids = getattr(access_store, "admin_ids", None)
    if admin_ids is not None:
        try:
            return int(user_id) in {int(item) for item in admin_ids}
        except Exception:
            return False
    return False
