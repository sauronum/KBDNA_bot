from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.i18n import get_user_language, t
from app.features.coordinate_space.reports import CoordinateSpaceReportStore
from app.main_menu import ensure_active_main_menu


REPORTS_CALLBACK_PREFIX = "reports"
REPORTS_PAGE_SIZE = 10


def _safe_count(callback) -> int:
    try:
        return len(callback())
    except Exception:
        return 0


def _sample_report_count(context: ContextTypes.DEFAULT_TYPE, user_id: int, sample_id: str) -> int:
    total = 0
    coordinate_store = context.application.bot_data.get("coordinate_space_report_store")
    if isinstance(coordinate_store, CoordinateSpaceReportStore):
        total += _safe_count(lambda: coordinate_store.list_results(user_id, sample_id))

    admixture_store = context.application.bot_data.get("admixture_report_store")
    if admixture_store is not None:
        total += _safe_count(lambda: admixture_store.list_reports(user_id, sample_id))

    matching_store = context.application.bot_data.get("matching_store")
    if matching_store is not None:
        total += _safe_count(lambda: matching_store.list_matches_for_sample(user_id, sample_id))

    traits_store = context.application.bot_data.get("traits_report_store")
    if traits_store is not None:
        total += _safe_count(lambda: traits_store.list_reports(user_id, sample_id))

    haplogroup_store = context.application.bot_data.get("haplogroup_store")
    if haplogroup_store is not None:
        total += _safe_count(lambda: haplogroup_store.list_sample_records(user_id, sample_id))

    return total


def _report_samples(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> list[tuple[object, int]]:
    store = context.application.bot_data.get("my_data_store")
    if store is None:
        return []
    try:
        samples = store.list_samples(user_id)
    except Exception:
        return []

    items: list[tuple[object, int]] = []
    for sample in samples:
        sample_id = str(getattr(sample, "asset_id", ""))
        if not sample_id:
            continue
        report_count = _sample_report_count(context, user_id, sample_id)
        if report_count > 0:
            items.append((sample, report_count))
    return items


def _page_bounds(items: list[tuple[object, int]], page: int) -> tuple[int, int, int, int]:
    page_count = max(1, (len(items) + REPORTS_PAGE_SIZE - 1) // REPORTS_PAGE_SIZE)
    safe_page = min(max(int(page), 0), page_count - 1)
    start = safe_page * REPORTS_PAGE_SIZE
    end = min(start + REPORTS_PAGE_SIZE, len(items))
    return safe_page, start, end, page_count


def _copy(lang: str, ru: str, en: str) -> str:
    return en if lang == "en" else ru


def reports_text(items: list[tuple[object, int]], *, total_samples: int, page: int = 0, lang: str = "ru") -> str:
    total_reports = sum(report_count for _sample, report_count in items)
    safe_page, start, end, page_count = _page_bounds(items, page)
    lines = [
        _copy(lang, "📊 Отчёты", "📊 Reports"),
        "",
        f"{_copy(lang, 'Образцы с отчетами', 'Samples with reports')}: {len(items)} / {total_samples}",
        f"{_copy(lang, 'Сохраненных отчетов', 'Saved reports')}: {total_reports}",
    ]
    if not items:
        lines.extend(
            [
                "",
                _copy(lang, "Пока нет сохраненных отчетов.", "There are no saved reports yet."),
                _copy(lang, "Запустите расчет в Coordinate spaces, Admixture, Matching, Traits или Haplogroups и сохраните результат.", "Run a calculation in Coordinate spaces, Admixture, Matching, Traits, or Haplogroups and save the result."),
            ]
        )
        return "\n".join(lines)
    lines.extend(["", _copy(lang, "Выберите образец, чтобы открыть его отчеты.", "Choose a sample to open its reports.")])
    if len(items) > REPORTS_PAGE_SIZE:
        lines.append(_copy(lang, f"Показаны {start + 1}-{end} из {len(items)}. Страница {safe_page + 1}/{page_count}.", f"Showing {start + 1}-{end} of {len(items)}. Page {safe_page + 1}/{page_count}."))
    return "\n".join(lines)


def build_reports_keyboard(
    items: list[tuple[object, int]],
    *,
    page: int = 0,
    lang: str = "ru",
    back_callback: str = "mydna:root",
    my_dna_callback: str = "mydna:root",
    show_my_dna_shortcut: bool = False,
    sample_callback_template: str = "my_data:sample_reports:{sample_id}",
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    safe_page, start, end, _page_count = _page_bounds(items, page)
    for sample, report_count in items[start:end]:
        sample_id = str(getattr(sample, "asset_id", ""))
        sample_name = str(getattr(sample, "display_name", "Sample"))
        rows.append(
            [
                InlineKeyboardButton(
                    f"{sample_name} · {report_count}",
                    callback_data=sample_callback_template.format(sample_id=sample_id),
                )
            ]
        )

    if len(items) > REPORTS_PAGE_SIZE:
        nav_row: list[InlineKeyboardButton] = []
        if safe_page > 0:
            nav_row.append(InlineKeyboardButton(f"← {t('nav.back', lang)}", callback_data=f"{REPORTS_CALLBACK_PREFIX}:p:{safe_page - 1}"))
        if end < len(items):
            nav_row.append(InlineKeyboardButton(f"{_copy(lang, 'Далее', 'Next')} →", callback_data=f"{REPORTS_CALLBACK_PREFIX}:p:{safe_page + 1}"))
        if nav_row:
            rows.append(nav_row)

    if show_my_dna_shortcut:
        rows.append([InlineKeyboardButton("📁 My DNA", callback_data=my_dna_callback)])
    rows.append(
        [
            InlineKeyboardButton(t("nav.back", lang), callback_data=back_callback),
            InlineKeyboardButton(t("nav.cancel", lang), callback_data="main:cancel"),
        ]
    )
    return InlineKeyboardMarkup(rows)


async def show_reports_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    page: int = 0,
    edit_existing: bool = False,
    lang: str = "ru",
    back_callback: str | None = None,
    my_dna_callback: str | None = None,
    show_my_dna_shortcut: bool | None = None,
    sample_callback_template: str | None = None,
) -> None:
    store = context.application.bot_data.get("my_data_store")
    if store is None:
        samples = []
    else:
        try:
            samples = store.list_samples(user_id)
        except Exception:
            samples = []
    items = _report_samples(context, user_id)
    text = reports_text(items, total_samples=len(samples), page=page, lang=lang)
    resolved_back_callback = back_callback or str(context.user_data.get("reports_back_callback") or context.application.bot_data.get("reports_back_callback") or "mydna:root")
    resolved_my_dna_callback = my_dna_callback or str(context.user_data.get("reports_my_dna_callback") or context.application.bot_data.get("reports_my_dna_callback") or "mydna:root")
    resolved_show_my_dna_shortcut = bool(context.application.bot_data.get("reports_show_my_dna_shortcut", False)) if show_my_dna_shortcut is None else bool(show_my_dna_shortcut)
    resolved_sample_callback_template = sample_callback_template or str(context.user_data.get("reports_sample_callback_template") or "my_data:sample_reports:{sample_id}")
    markup = build_reports_keyboard(
        items,
        page=page,
        lang=lang,
        back_callback=resolved_back_callback,
        my_dna_callback=resolved_my_dna_callback,
        show_my_dna_shortcut=resolved_show_my_dna_shortcut,
        sample_callback_template=resolved_sample_callback_template,
    )
    if edit_existing:
        await message.edit_text(text, reply_markup=markup)
    else:
        await message.reply_text(text, reply_markup=markup, do_quote=False)


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
    lang = get_user_language(context, int(user.id))

    parts = query.data.split(":")
    action = parts[1] if len(parts) > 1 else "root"
    if action == "root":
        await show_reports_menu(query.message, context, int(user.id), edit_existing=True, lang=lang)
        return
    if action == "p":
        page = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
        await show_reports_menu(query.message, context, int(user.id), page=page, edit_existing=True, lang=lang)
