from __future__ import annotations

import re
from pathlib import Path

from telegram import Update
from telegram.ext import Application, ApplicationHandlerStop, ContextTypes

from app.features.matching.domain import lookup_snp_in_raw
from app.features.my_data.storage import MyDataStore, SampleAsset
from app.heavy_runtime import run_in_heavy_pool
from app.i18n import get_user_language

from .domain import SnpRule, build_snp_report, load_snp_rules
from .storage import SnpReportStore
from .ui import (
    build_db_categories_keyboard,
    build_db_category_keyboard,
    build_db_rule_keyboard,
    build_error_keyboard,
    build_lab_root_keyboard,
    build_report_picker_keyboard,
    build_result_keyboard,
    build_search_input_keyboard,
    build_search_picker_keyboard,
    build_search_result_keyboard,
    db_categories_text,
    db_category_text,
    db_rule_text,
    error_text,
    lab_root_text,
    render_html_report,
    report_picker_text,
    result_text,
    running_text,
    search_input_text,
    search_invalid_text,
    search_no_raw_text,
    search_picker_text,
    search_result_text,
)


SNP_REPORT_CALLBACK_PREFIX = "snp_report"
SNP_LOOKUP_PENDING_KEY = "snp_lab_lookup_pending"
RSID_RE = re.compile(r"^rs\d+$", re.IGNORECASE)


def register_snp_report_services(application: Application, settings) -> None:
    application.bot_data["snp_report_rules"] = load_snp_rules()
    application.bot_data["snp_report_store"] = SnpReportStore(settings.root_dir / "storage" / "snp_report")


def _rules(context: ContextTypes.DEFAULT_TYPE) -> tuple[SnpRule, ...]:
    return context.application.bot_data["snp_report_rules"]


def _report_store(context: ContextTypes.DEFAULT_TYPE) -> SnpReportStore:
    return context.application.bot_data["snp_report_store"]


def _my_data_store(context: ContextTypes.DEFAULT_TYPE) -> MyDataStore:
    return context.application.bot_data["my_data_store"]


def _record_snp_report_usage(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    action: str,
    *,
    success: bool = True,
    input_mode: str = "callback",
) -> None:
    usage_store = context.application.bot_data.get("usage_store")
    if usage_store is not None and hasattr(usage_store, "record_dna_lab"):
        usage_store.record_dna_lab(update, "snp_report", action=action, success=success, input_mode=input_mode)


def _ui_lang(context: ContextTypes.DEFAULT_TYPE, user_id: int | None = None) -> str:
    return get_user_language(context, user_id, fallback="ru")


def _samples_with_raw(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> list[SampleAsset]:
    store = _my_data_store(context)
    return [
        sample
        for sample in store.list_samples(user_id)
        if sample.raw_file_id and store.get_sample_raw_file(user_id, sample.asset_id) is not None
    ]


async def show_snp_report_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    edit_existing: bool = False,
    page: int = 0,
) -> None:
    del page
    lang = _ui_lang(context, user_id)
    samples = _samples_with_raw(context, user_id)
    text = lab_root_text(samples, _rules(context), lang=lang)
    markup = build_lab_root_keyboard(lang=lang)
    if edit_existing:
        await message.edit_text(text, parse_mode="HTML", reply_markup=markup)
    else:
        await message.reply_text(text, parse_mode="HTML", reply_markup=markup, do_quote=False)


async def snp_report_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.message is None or update.effective_user is None:
        return
    if not query.data or not query.data.startswith(f"{SNP_REPORT_CALLBACK_PREFIX}:"):
        return

    user_id = int(update.effective_user.id)
    parts = query.data.split(":")
    action = parts[1] if len(parts) > 1 else "root"

    if action == "root":
        await query.answer()
        _clear_lookup_pending(context)
        await show_snp_report_menu(query.message, context, user_id, edit_existing=True)
        return

    if action == "noop":
        await query.answer()
        return

    if action == "search":
        await query.answer()
        _clear_lookup_pending(context)
        await _show_search_picker(query.message, context, user_id, edit_existing=True)
        return

    if action == "search_page":
        await query.answer()
        page = _parse_int(parts[2] if len(parts) > 2 else "0")
        await _show_search_picker(query.message, context, user_id, edit_existing=True, page=page)
        return

    if action == "search_sample":
        await query.answer()
        sample_id = parts[2] if len(parts) > 2 else ""
        await _show_search_input(query.message, context, user_id, sample_id, edit_existing=True)
        return

    if action == "db":
        await query.answer()
        _clear_lookup_pending(context)
        await _show_db_categories(query.message, context, user_id, edit_existing=True)
        return

    if action == "db_page":
        await query.answer()
        page = _parse_int(parts[2] if len(parts) > 2 else "0")
        await _show_db_categories(query.message, context, user_id, edit_existing=True, page=page)
        return

    if action == "dbcat":
        await query.answer()
        category_index = _parse_int(parts[2] if len(parts) > 2 else "0")
        page = _parse_int(parts[3] if len(parts) > 3 else "0")
        await _show_db_category(query.message, context, user_id, category_index, page=page, edit_existing=True)
        return

    if action == "dbsnp":
        await query.answer()
        rule_index = _parse_int(parts[2] if len(parts) > 2 else "-1")
        category_index = _parse_int(parts[3] if len(parts) > 3 else "0")
        page = _parse_int(parts[4] if len(parts) > 4 else "0")
        await _show_db_rule(query.message, context, user_id, rule_index, category_index=category_index, page=page, edit_existing=True)
        return

    if action == "report":
        await query.answer()
        _clear_lookup_pending(context)
        await _show_report_picker(query.message, context, user_id, edit_existing=True)
        return

    if action in {"report_page", "page"}:
        await query.answer()
        page = _parse_int(parts[2] if len(parts) > 2 else "0")
        await _show_report_picker(query.message, context, user_id, edit_existing=True, page=page)
        return

    if action == "run":
        await query.answer()
        _clear_lookup_pending(context)
        sample_id = parts[2] if len(parts) > 2 else ""
        await _run_snp_report(query.message, update, context, user_id, sample_id)
        return

    if action == "html":
        await query.answer()
        report_id = parts[2] if len(parts) > 2 else ""
        await _send_html_report(query.message, update, context, user_id, report_id)
        return

    await query.answer("Неизвестное действие.", show_alert=True)


async def snp_report_text_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user is None or update.effective_chat is None or update.effective_message is None:
        return
    pending = context.user_data.get(SNP_LOOKUP_PENDING_KEY)
    if not isinstance(pending, dict):
        return
    if int(pending.get("user_id", 0) or 0) != int(update.effective_user.id):
        return
    if int(pending.get("chat_id", 0) or 0) != int(update.effective_chat.id):
        return

    body = (update.effective_message.text or "").strip()
    if not body:
        return
    if _looks_like_navigation_text(body):
        _clear_lookup_pending(context)
        return

    user_id = int(update.effective_user.id)
    lang = _ui_lang(context, user_id)
    sample_id = str(pending.get("sample_id") or "")
    message_id = int(pending.get("message_id", 0) or 0)
    chat_id = int(pending.get("chat_id", 0) or 0)
    store = _my_data_store(context)
    sample = store.get_sample(user_id, sample_id)

    rsid = _normalize_rsid(body)
    if rsid is None:
        _record_snp_report_usage(update, context, "lookup", success=False, input_mode="text")
        await _edit_pending_lookup_message(
            context,
            chat_id,
            message_id,
            search_invalid_text(lang=lang),
            build_search_input_keyboard(sample_id, lang=lang),
        )
        raise ApplicationHandlerStop

    if sample is None:
        _clear_lookup_pending(context)
        _record_snp_report_usage(update, context, "lookup", success=False, input_mode="text")
        await update.effective_message.reply_text(
            error_text("SNP Lab", "Sample не найден."),
            parse_mode="HTML",
            reply_markup=build_error_keyboard(),
            do_quote=False,
        )
        raise ApplicationHandlerStop

    raw_file = store.get_sample_raw_file(user_id, sample.asset_id)
    if raw_file is None:
        _clear_lookup_pending(context)
        _record_snp_report_usage(update, context, "lookup", success=False, input_mode="text")
        await _edit_pending_lookup_message(
            context,
            chat_id,
            message_id,
            search_no_raw_text(sample, lang=lang),
            build_search_result_keyboard(sample.asset_id, lang=lang),
        )
        raise ApplicationHandlerStop

    raw_path = store.resolve_raw_file_path(raw_file)
    result = await run_in_heavy_pool(context, _lookup_snp_in_raw_path, str(raw_path), rsid)
    _clear_lookup_pending(context)
    _record_snp_report_usage(update, context, "lookup", success=(getattr(result, "error", None) is None), input_mode="text")
    await _edit_pending_lookup_message(
        context,
        chat_id,
        message_id,
        search_result_text(sample, result, lang=lang),
        build_search_result_keyboard(sample.asset_id, lang=lang),
    )
    raise ApplicationHandlerStop


async def _show_report_picker(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    edit_existing: bool,
    page: int = 0,
) -> None:
    lang = _ui_lang(context, user_id)
    samples = _samples_with_raw(context, user_id)
    text = report_picker_text(samples, lang=lang, page=page)
    markup = build_report_picker_keyboard(samples, lang=lang, page=page)
    if edit_existing:
        await message.edit_text(text, parse_mode="HTML", reply_markup=markup)
    else:
        await message.reply_text(text, parse_mode="HTML", reply_markup=markup, do_quote=False)


async def _show_search_picker(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    edit_existing: bool,
    page: int = 0,
) -> None:
    lang = _ui_lang(context, user_id)
    samples = _samples_with_raw(context, user_id)
    text = search_picker_text(samples, lang=lang, page=page)
    markup = build_search_picker_keyboard(samples, lang=lang, page=page)
    if edit_existing:
        await message.edit_text(text, parse_mode="HTML", reply_markup=markup)
    else:
        await message.reply_text(text, parse_mode="HTML", reply_markup=markup, do_quote=False)


async def _show_search_input(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    sample_id: str,
    *,
    edit_existing: bool,
) -> None:
    lang = _ui_lang(context, user_id)
    sample = _my_data_store(context).get_sample(user_id, sample_id)
    if sample is None:
        await message.edit_text(
            error_text("SNP Lab", "Sample не найден."),
            parse_mode="HTML",
            reply_markup=build_error_keyboard(),
        )
        return
    text = search_input_text(sample, lang=lang)
    markup = build_search_input_keyboard(sample.asset_id, lang=lang)
    if edit_existing:
        edited = await message.edit_text(text, parse_mode="HTML", reply_markup=markup)
        message_id = edited.message_id
        chat_id = edited.chat_id
    else:
        sent = await message.reply_text(text, parse_mode="HTML", reply_markup=markup, do_quote=False)
        message_id = sent.message_id
        chat_id = sent.chat_id
    context.user_data[SNP_LOOKUP_PENDING_KEY] = {
        "chat_id": int(chat_id),
        "message_id": int(message_id),
        "sample_id": sample.asset_id,
        "user_id": int(user_id),
    }


async def _show_db_categories(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    edit_existing: bool,
    page: int = 0,
) -> None:
    lang = _ui_lang(context, user_id)
    rules = _rules(context)
    text = db_categories_text(rules, lang=lang)
    markup = build_db_categories_keyboard(rules, lang=lang, page=page)
    if edit_existing:
        await message.edit_text(text, parse_mode="HTML", reply_markup=markup)
    else:
        await message.reply_text(text, parse_mode="HTML", reply_markup=markup, do_quote=False)


async def _show_db_category(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    category_index: int,
    *,
    page: int,
    edit_existing: bool,
) -> None:
    lang = _ui_lang(context, user_id)
    rules = _rules(context)
    categories = _category_names(rules)
    if category_index < 0 or category_index >= len(categories):
        await message.edit_text(error_text("SNP база", "Раздел не найден."), parse_mode="HTML", reply_markup=build_error_keyboard())
        return
    category = categories[category_index]
    category_rules = [(index, rule) for index, rule in enumerate(rules) if rule.category == category]
    text = db_category_text(category, category_rules, lang=lang, page=page)
    markup = build_db_category_keyboard(category_index, category_rules, lang=lang, page=page)
    if edit_existing:
        await message.edit_text(text, parse_mode="HTML", reply_markup=markup)
    else:
        await message.reply_text(text, parse_mode="HTML", reply_markup=markup, do_quote=False)


async def _show_db_rule(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    rule_index: int,
    *,
    category_index: int,
    page: int,
    edit_existing: bool,
) -> None:
    lang = _ui_lang(context, user_id)
    rules = _rules(context)
    if rule_index < 0 or rule_index >= len(rules):
        await message.edit_text(error_text("SNP база", "SNP не найден."), parse_mode="HTML", reply_markup=build_error_keyboard())
        return
    rule = rules[rule_index]
    text = db_rule_text(rule, lang=lang)
    markup = build_db_rule_keyboard(rule, category_index, page, lang=lang)
    if edit_existing:
        await message.edit_text(text, parse_mode="HTML", reply_markup=markup)
    else:
        await message.reply_text(text, parse_mode="HTML", reply_markup=markup, do_quote=False)


async def _run_snp_report(message, update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int, sample_id: str) -> None:
    store = _my_data_store(context)
    sample = store.get_sample(user_id, sample_id)
    if sample is None:
        _record_snp_report_usage(update, context, "run", success=False)
        await message.edit_text(
            error_text("SNP Lab", "Sample не найден."),
            parse_mode="HTML",
            reply_markup=build_error_keyboard(),
        )
        return

    raw_file = store.get_sample_raw_file(user_id, sample.asset_id)
    if raw_file is None:
        _record_snp_report_usage(update, context, "run", success=False)
        await message.edit_text(
            error_text("SNP Lab", "К этому sample не привязан raw-файл."),
            parse_mode="HTML",
            reply_markup=build_error_keyboard(),
        )
        return

    raw_path = store.resolve_raw_file_path(raw_file)
    if not raw_path.exists():
        _record_snp_report_usage(update, context, "run", success=False)
        await message.edit_text(
            error_text("SNP Lab", "Raw-файл не найден на диске."),
            parse_mode="HTML",
            reply_markup=build_error_keyboard(),
        )
        return

    lang = _ui_lang(context, user_id)
    await message.edit_text(running_text(sample, lang=lang), parse_mode="HTML")

    try:
        result, html_report = await run_in_heavy_pool(
            context,
            _build_snp_report_artifacts,
            str(raw_path),
            _rules(context),
            sample.asset_id,
            sample.display_name,
            raw_file.asset_id,
        )
    except Exception:
        _record_snp_report_usage(update, context, "run", success=False)
        await message.edit_text(
            error_text("SNP Lab", "Не удалось прочитать raw-файл или построить отчет."),
            parse_mode="HTML",
            reply_markup=build_error_keyboard(),
        )
        return

    record = _report_store(context).save_report(user_id, result, html_report)
    _record_snp_report_usage(update, context, "run")
    await message.edit_text(
        result_text(record, lang=lang),
        parse_mode="HTML",
        reply_markup=build_result_keyboard(record.summary.report_id, lang=lang),
    )


async def _send_html_report(message, update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int, report_id: str) -> None:
    record = _report_store(context).find_report(user_id, report_id)
    if record is None:
        _record_snp_report_usage(update, context, "html", success=False)
        await message.reply_text(
            error_text("SNP Lab", "Отчет не найден."),
            parse_mode="HTML",
            reply_markup=build_error_keyboard(),
            do_quote=False,
        )
        return
    html_path = _report_store(context).resolve_html_path(record.summary)
    if not html_path.exists():
        _record_snp_report_usage(update, context, "html", success=False)
        await message.reply_text(
            error_text("SNP Lab", "HTML-файл отчета не найден."),
            parse_mode="HTML",
            reply_markup=build_error_keyboard(),
            do_quote=False,
        )
        return
    filename = f"{_safe_filename(record.summary.sample_name)}_snp_report.html"
    with html_path.open("rb") as handle:
        await message.reply_document(
            document=handle,
            filename=filename,
            caption="🧾 SNP Lab HTML",
            do_quote=False,
        )
    _record_snp_report_usage(update, context, "html")


async def _edit_pending_lookup_message(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int, text: str, reply_markup) -> None:
    try:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            parse_mode="HTML",
            reply_markup=reply_markup,
        )
    except Exception:
        return


def _clear_lookup_pending(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop(SNP_LOOKUP_PENDING_KEY, None)


def _normalize_rsid(value: str) -> str | None:
    cleaned = value.strip().lower()
    cleaned = cleaned.split()[0] if cleaned else ""
    if RSID_RE.match(cleaned):
        return cleaned
    return None


def _looks_like_navigation_text(value: str) -> bool:
    return value.strip() in {
        "Назад",
        "Отмена",
        "🔎 Поиск",
        "🔎 Поиск по фамилии",
        "🔎 Поиск по фамилиям",
        "ℹ️ Инструкция",
        "📊 Аналитика",
        "🧬 My DNA",
        "🧪 DNA Lab",
        "🧪 Лаборатория",
        "📚 Справка",
        "🧬 SNP Lab",
        "🧾 SNP Report",
        "📚 База SNP",
        "🧾 SNP отчёт",
        "📄 Скачать HTML",
        "🔁 Новый SNP отчёт",
        "🔁 Проверить другой SNP",
        "👤 Другой sample",
        "✨ Traits",
        "🧬 Admixture",
        "🏛 AdmixLab",
        "📐 Vahaduo Lab",
        "🧩 Matching",
        "🌿 Haplogroups",
    }


def _category_names(rules: tuple[SnpRule, ...]) -> list[str]:
    seen: dict[str, None] = {}
    for rule in rules:
        seen.setdefault(rule.category, None)
    return sorted(seen, key=str.casefold)


def _parse_int(value: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _safe_filename(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    return cleaned.strip("._-") or "sample"


def _build_snp_report_artifacts(
    raw_path: str,
    rules: tuple[SnpRule, ...],
    sample_id: str,
    sample_name: str,
    raw_file_id: str,
) -> tuple[object, str]:
    result = build_snp_report(
        Path(raw_path),
        rules,
        sample_id=sample_id,
        sample_name=sample_name,
        raw_file_id=raw_file_id,
    )
    return result, render_html_report(result)


def _lookup_snp_in_raw_path(raw_path: str, rsid: str) -> object:
    return lookup_snp_in_raw(Path(raw_path), rsid)
