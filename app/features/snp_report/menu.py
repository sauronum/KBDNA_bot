from __future__ import annotations

import logging
import re
from pathlib import Path

from telegram import Update
from telegram.ext import Application, ApplicationHandlerStop, ContextTypes

from app.features.matching.domain import lookup_snp_in_raw
from app.features.my_data.storage import MyDataStore, SampleAsset
from app.heavy_runtime import run_in_heavy_pool
from app.i18n import get_user_language
from .domain import SnpRule, build_snp_report, load_snp_rules
from .interesting import InterestingSnpDefinition, analyze_interesting_snps, load_interesting_snps
from .storage import SnpReportStore
from .ui import (
    build_db_categories_keyboard,
    build_db_category_keyboard,
    build_db_gene_results_keyboard,
    build_db_rule_keyboard,
    build_db_rule_lookup_result_keyboard,
    build_db_rule_sample_picker_keyboard,
    build_db_root_keyboard,
    build_db_search_input_keyboard,
    build_error_keyboard,
    build_interesting_picker_keyboard,
    build_interesting_detail_keyboard,
    build_interesting_result_keyboard,
    build_interesting_result_keyboard_for_analysis,
    build_lab_root_keyboard,
    build_popular_snps_keyboard,
    build_report_picker_keyboard,
    build_result_keyboard,
    build_sample_home_keyboard,
    build_search_input_keyboard,
    build_search_picker_keyboard,
    build_search_result_keyboard,
    db_categories_text,
    db_category_text,
    db_gene_results_text,
    db_rule_lookup_result_text,
    db_rule_sample_picker_text,
    db_rule_text,
    db_root_text,
    db_search_input_text,
    error_text,
    interesting_detail_text,
    interesting_picker_text,
    interesting_result_text,
    interesting_running_text,
    lab_root_text,
    popular_snps_text,
    render_html_report,
    report_picker_text,
    result_text,
    running_text,
    sample_home_text,
    search_input_text,
    search_invalid_text,
    search_no_raw_text,
    search_picker_text,
    search_result_text,
)
from .visuals import render_category_load_png


SNP_REPORT_CALLBACK_PREFIX = "snp_report"
SNP_LOOKUP_PENDING_KEY = "snp_lab_lookup_pending"
SNP_DB_LOOKUP_PENDING_KEY = "snp_lab_db_lookup_pending"
SNP_DB_SEARCH_PENDING_KEY = "snp_lab_db_search_pending"
RSID_RE = re.compile(r"^rs\d+$", re.IGNORECASE)
LOGGER = logging.getLogger(__name__)


def register_snp_report_services(application: Application, settings) -> None:
    application.bot_data["snp_report_rules"] = load_snp_rules()
    application.bot_data["snp_report_interesting_snps"] = load_interesting_snps()
    application.bot_data["snp_report_store"] = SnpReportStore(settings.root_dir / "storage" / "snp_report")


def _rules(context: ContextTypes.DEFAULT_TYPE) -> tuple[SnpRule, ...]:
    return context.application.bot_data["snp_report_rules"]


def _interesting_panel(context: ContextTypes.DEFAULT_TYPE) -> tuple[InterestingSnpDefinition, ...]:
    return context.application.bot_data["snp_report_interesting_snps"]


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


def _is_media_message(message) -> bool:
    return any(
        getattr(message, attribute, None)
        for attribute in ("photo", "document", "video", "animation", "audio", "voice", "video_note", "sticker")
    )


async def _show_text_menu(message, text: str, markup, *, edit_existing: bool):
    if edit_existing and not _is_media_message(message):
        return await message.edit_text(text, parse_mode="HTML", reply_markup=markup)

    sent = await message.reply_text(text, parse_mode="HTML", reply_markup=markup, do_quote=False)
    if edit_existing:
        try:
            await message.edit_reply_markup(reply_markup=None)
        except Exception as exc:  # pragma: no cover - best-effort cleanup for Telegram media messages
            LOGGER.debug("Could not clear SNP Lab media keyboard: %s", exc)
    return sent


async def show_snp_report_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    edit_existing: bool = False,
    page: int = 0,
) -> None:
    lang = _ui_lang(context, user_id)
    samples = _samples_with_raw(context, user_id)
    text = lab_root_text(samples, _rules(context), lang=lang, page=page)
    markup = build_lab_root_keyboard(samples, lang=lang, page=page)
    await _show_text_menu(message, text, markup, edit_existing=edit_existing)


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
        _clear_db_lookup_pending(context)
        _clear_db_search_pending(context)
        await show_snp_report_menu(query.message, context, user_id, edit_existing=True)
        return

    if action == "noop":
        await query.answer()
        return

    if action == "sample_page":
        await query.answer()
        page = _parse_int(parts[2] if len(parts) > 2 else "0")
        await show_snp_report_menu(query.message, context, user_id, edit_existing=True, page=page)
        return

    if action == "sample":
        await query.answer()
        sample_id = parts[2] if len(parts) > 2 else ""
        await _show_sample_home(query.message, update, context, user_id, sample_id)
        return

    if action == "search":
        await query.answer()
        _clear_lookup_pending(context)
        _clear_db_lookup_pending(context)
        _clear_db_search_pending(context)
        await _show_search_picker(query.message, context, user_id, edit_existing=True)
        return

    if action == "search_page":
        await query.answer()
        page = _parse_int(parts[2] if len(parts) > 2 else "0")
        await _show_search_picker(query.message, context, user_id, edit_existing=True, page=page)
        return

    if action == "search_rsid_page":
        await query.answer()
        rsid = parts[2] if len(parts) > 2 else ""
        page = _parse_int(parts[3] if len(parts) > 3 else "0")
        await _show_search_picker(query.message, context, user_id, edit_existing=True, page=page, prefill_rsid=rsid)
        return

    if action == "search_sample":
        await query.answer()
        sample_id = parts[2] if len(parts) > 2 else ""
        await _show_search_input(query.message, context, user_id, sample_id, edit_existing=True)
        return

    if action == "search_rsid_sample":
        await query.answer()
        rsid = parts[2] if len(parts) > 2 else ""
        sample_id = parts[3] if len(parts) > 3 else ""
        await _run_prefilled_snp_lookup(query.message, update, context, user_id, sample_id, rsid)
        return

    if action == "db":
        await query.answer()
        _clear_lookup_pending(context)
        _clear_db_lookup_pending(context)
        _clear_db_search_pending(context)
        await _show_db_root(query.message, context, user_id, edit_existing=True)
        return

    if action == "dbcats":
        await query.answer()
        _clear_lookup_pending(context)
        _clear_db_lookup_pending(context)
        _clear_db_search_pending(context)
        await _show_db_categories(query.message, context, user_id, edit_existing=True)
        return

    if action == "db_page":
        await query.answer()
        page = _parse_int(parts[2] if len(parts) > 2 else "0")
        await _show_db_categories(query.message, context, user_id, edit_existing=True, page=page)
        return

    if action in {"db_search", "db_gene"}:
        await query.answer()
        mode = "gene" if action == "db_gene" else "rsid"
        _clear_lookup_pending(context)
        _clear_db_lookup_pending(context)
        await _show_db_search_input(query.message, context, user_id, mode=mode, edit_existing=True)
        return

    if action == "dbgene_page":
        await query.answer()
        query_text = parts[2] if len(parts) > 2 else ""
        page = _parse_int(parts[3] if len(parts) > 3 else "0")
        await _show_db_gene_results(query.message, context, user_id, query_text, page=page, edit_existing=True)
        return

    if action == "dbpopular":
        await query.answer()
        await _show_popular_snps(query.message, context, user_id, edit_existing=True)
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

    if action == "dbcheck":
        await query.answer()
        _clear_lookup_pending(context)
        rule_index = _parse_int(parts[2] if len(parts) > 2 else "-1")
        category_index = _parse_int(parts[3] if len(parts) > 3 else "0")
        rule_page = _parse_int(parts[4] if len(parts) > 4 else "0")
        sample_page = _parse_int(parts[5] if len(parts) > 5 else "0")
        await _show_db_rule_sample_picker(
            query.message,
            context,
            user_id,
            rule_index,
            category_index=category_index,
            rule_page=rule_page,
            sample_page=sample_page,
            edit_existing=True,
        )
        return

    if action == "dbcheck_page":
        await query.answer()
        pending = _db_lookup_pending(context, user_id)
        if pending is None:
            await show_snp_report_menu(query.message, context, user_id, edit_existing=True)
            return
        sample_page = _parse_int(parts[2] if len(parts) > 2 else "0")
        await _show_db_rule_sample_picker(
            query.message,
            context,
            user_id,
            int(pending["rule_index"]),
            category_index=int(pending["category_index"]),
            rule_page=int(pending["rule_page"]),
            sample_page=sample_page,
            edit_existing=True,
        )
        return

    if action == "dbsample":
        await query.answer()
        sample_id = parts[2] if len(parts) > 2 else ""
        await _run_db_rule_lookup(query.message, update, context, user_id, sample_id)
        return

    if action == "interesting":
        await query.answer()
        _clear_lookup_pending(context)
        _clear_db_lookup_pending(context)
        await _show_interesting_picker(query.message, context, user_id, edit_existing=True)
        return

    if action == "interesting_page":
        await query.answer()
        page = _parse_int(parts[2] if len(parts) > 2 else "0")
        await _show_interesting_picker(query.message, context, user_id, edit_existing=True, page=page)
        return

    if action == "interesting_sample":
        await query.answer()
        _clear_lookup_pending(context)
        _clear_db_lookup_pending(context)
        _clear_db_search_pending(context)
        sample_id = parts[2] if len(parts) > 2 else ""
        await _run_interesting_snps(query.message, update, context, user_id, sample_id)
        return

    if action == "intdetail":
        await query.answer()
        sample_id = parts[2] if len(parts) > 2 else ""
        rsid = parts[3] if len(parts) > 3 else ""
        await _show_interesting_detail(query.message, update, context, user_id, sample_id, rsid)
        return

    if action == "interesting_rsid":
        await query.answer()
        rsid = parts[2] if len(parts) > 2 else ""
        await _show_search_picker(query.message, context, user_id, edit_existing=True, prefill_rsid=rsid)
        return

    if action == "report":
        await query.answer()
        _clear_lookup_pending(context)
        _clear_db_lookup_pending(context)
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
        _clear_db_lookup_pending(context)
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
    db_pending = context.user_data.get(SNP_DB_SEARCH_PENDING_KEY)
    if isinstance(db_pending, dict):
        handled = await _handle_db_search_text(update, context, db_pending)
        if handled:
            raise ApplicationHandlerStop

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


async def _handle_db_search_text(update: Update, context: ContextTypes.DEFAULT_TYPE, pending: dict) -> bool:
    if update.effective_user is None or update.effective_chat is None or update.effective_message is None:
        return False
    if int(pending.get("user_id", 0) or 0) != int(update.effective_user.id):
        return False
    if int(pending.get("chat_id", 0) or 0) != int(update.effective_chat.id):
        return False

    body = (update.effective_message.text or "").strip()
    if not body:
        return False
    if _looks_like_navigation_text(body):
        _clear_db_search_pending(context)
        return True

    user_id = int(update.effective_user.id)
    lang = _ui_lang(context, user_id)
    mode = str(pending.get("mode") or "rsid")
    message_id = int(pending.get("message_id", 0) or 0)
    chat_id = int(pending.get("chat_id", 0) or 0)
    rules = _rules(context)

    if mode == "gene":
        query_text = _normalize_gene_query(body)
        _clear_db_search_pending(context)
        matches = _find_rules_by_gene(rules, query_text)
        await _edit_pending_lookup_message(
            context,
            chat_id,
            message_id,
            db_gene_results_text(query_text, matches, lang=lang),
            build_db_gene_results_keyboard(query_text, matches, lang=lang),
        )
        return True

    rsid = _normalize_rsid(body)
    if rsid is None:
        await _edit_pending_lookup_message(
            context,
            chat_id,
            message_id,
            db_search_input_text(mode="rsid", lang=lang),
            build_db_search_input_keyboard(lang=lang),
        )
        return True

    rule_index = _find_rule_index_by_rsid(rules, rsid)
    _clear_db_search_pending(context)
    if rule_index is None:
        await _edit_pending_lookup_message(
            context,
            chat_id,
            message_id,
            error_text("База SNP", f"{rsid} не найден в текущей SNP-базе."),
            build_db_root_keyboard(lang=lang),
        )
        return True

    rule = rules[rule_index]
    await _edit_pending_lookup_message(
        context,
        chat_id,
        message_id,
        db_rule_text(rule, lang=lang),
        build_db_rule_keyboard(rule, rule_index, 0, 0, lang=lang),
    )
    return True


async def _show_sample_home(
    message,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    sample_id: str,
) -> None:
    store = _my_data_store(context)
    sample = store.get_sample(user_id, sample_id)
    lang = _ui_lang(context, user_id)
    if sample is None:
        _record_snp_report_usage(update, context, "sample", success=False)
        await message.edit_text(
            error_text("SNP Lab", "Sample не найден."),
            parse_mode="HTML",
            reply_markup=build_error_keyboard(),
        )
        return

    raw_file = store.get_sample_raw_file(user_id, sample.asset_id)
    if raw_file is None:
        _record_snp_report_usage(update, context, "sample", success=False)
        await message.edit_text(
            search_no_raw_text(sample, lang=lang),
            parse_mode="HTML",
            reply_markup=build_error_keyboard(),
        )
        return

    if not store.resolve_raw_file_path(raw_file).exists():
        _record_snp_report_usage(update, context, "sample", success=False)
        await message.edit_text(
            error_text("SNP Lab", "Raw-файл не найден на диске."),
            parse_mode="HTML",
            reply_markup=build_error_keyboard(),
        )
        return

    _record_snp_report_usage(update, context, "sample")
    await message.edit_text(
        sample_home_text(sample, lang=lang),
        parse_mode="HTML",
        reply_markup=build_sample_home_keyboard(sample.asset_id, lang=lang),
    )


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
    await _show_text_menu(message, text, markup, edit_existing=edit_existing)


async def _show_interesting_picker(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    edit_existing: bool,
    page: int = 0,
) -> None:
    lang = _ui_lang(context, user_id)
    samples = _samples_with_raw(context, user_id)
    text = interesting_picker_text(samples, lang=lang, page=page)
    markup = build_interesting_picker_keyboard(samples, lang=lang, page=page)
    await _show_text_menu(message, text, markup, edit_existing=edit_existing)


async def _show_search_picker(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    edit_existing: bool,
    page: int = 0,
    prefill_rsid: str = "",
) -> None:
    lang = _ui_lang(context, user_id)
    samples = _samples_with_raw(context, user_id)
    text = search_picker_text(samples, lang=lang, page=page, prefill_rsid=prefill_rsid)
    markup = build_search_picker_keyboard(samples, lang=lang, page=page, prefill_rsid=prefill_rsid)
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


async def _show_db_root(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    edit_existing: bool,
) -> None:
    lang = _ui_lang(context, user_id)
    rules = _rules(context)
    text = db_root_text(rules, lang=lang)
    markup = build_db_root_keyboard(lang=lang)
    await _show_text_menu(message, text, markup, edit_existing=edit_existing)


async def _show_db_search_input(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    mode: str,
    edit_existing: bool,
) -> None:
    lang = _ui_lang(context, user_id)
    text = db_search_input_text(mode=mode, lang=lang)
    markup = build_db_search_input_keyboard(lang=lang)
    edited = await _show_text_menu(message, text, markup, edit_existing=edit_existing)
    context.user_data[SNP_DB_SEARCH_PENDING_KEY] = {
        "chat_id": int(edited.chat_id),
        "message_id": int(edited.message_id),
        "mode": mode,
        "user_id": int(user_id),
    }


async def _show_db_gene_results(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    query_text: str,
    *,
    page: int,
    edit_existing: bool,
) -> None:
    lang = _ui_lang(context, user_id)
    matches = _find_rules_by_gene(_rules(context), query_text)
    text = db_gene_results_text(query_text, matches, lang=lang, page=page)
    markup = build_db_gene_results_keyboard(query_text, matches, lang=lang, page=page)
    await _show_text_menu(message, text, markup, edit_existing=edit_existing)


async def _show_popular_snps(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    edit_existing: bool,
) -> None:
    lang = _ui_lang(context, user_id)
    text = popular_snps_text(lang=lang)
    markup = build_popular_snps_keyboard(_rules(context), lang=lang)
    await _show_text_menu(message, text, markup, edit_existing=edit_existing)


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
    markup = build_db_rule_keyboard(rule, rule_index, category_index, page, lang=lang)
    if edit_existing:
        await message.edit_text(text, parse_mode="HTML", reply_markup=markup)
    else:
        await message.reply_text(text, parse_mode="HTML", reply_markup=markup, do_quote=False)


async def _show_db_rule_sample_picker(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    rule_index: int,
    *,
    category_index: int,
    rule_page: int,
    sample_page: int,
    edit_existing: bool,
) -> None:
    lang = _ui_lang(context, user_id)
    rules = _rules(context)
    if rule_index < 0 or rule_index >= len(rules):
        await message.edit_text(error_text("SNP база", "SNP не найден."), parse_mode="HTML", reply_markup=build_error_keyboard())
        return
    rule = rules[rule_index]
    samples = _samples_with_raw(context, user_id)
    context.user_data[SNP_DB_LOOKUP_PENDING_KEY] = {
        "user_id": int(user_id),
        "rule_index": int(rule_index),
        "category_index": int(category_index),
        "rule_page": int(rule_page),
    }
    text = db_rule_sample_picker_text(rule, samples, lang=lang, page=sample_page)
    markup = build_db_rule_sample_picker_keyboard(
        samples,
        rule_index=rule_index,
        category_index=category_index,
        rule_page=rule_page,
        sample_page=sample_page,
    )
    if edit_existing:
        await message.edit_text(text, parse_mode="HTML", reply_markup=markup)
    else:
        await message.reply_text(text, parse_mode="HTML", reply_markup=markup, do_quote=False)


async def _run_db_rule_lookup(
    message,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    sample_id: str,
) -> None:
    pending = _db_lookup_pending(context, user_id)
    if pending is None:
        _record_snp_report_usage(update, context, "lookup", success=False)
        await show_snp_report_menu(message, context, user_id, edit_existing=True)
        return

    rules = _rules(context)
    rule_index = int(pending["rule_index"])
    category_index = int(pending["category_index"])
    rule_page = int(pending["rule_page"])
    if rule_index < 0 or rule_index >= len(rules):
        _record_snp_report_usage(update, context, "lookup", success=False)
        await message.edit_text(error_text("SNP база", "SNP не найден."), parse_mode="HTML", reply_markup=build_error_keyboard())
        return
    rule = rules[rule_index]

    store = _my_data_store(context)
    sample = store.get_sample(user_id, sample_id)
    if sample is None:
        _record_snp_report_usage(update, context, "lookup", success=False)
        await message.edit_text(error_text("SNP Lab", "Sample не найден."), parse_mode="HTML", reply_markup=build_error_keyboard())
        return
    raw_file = store.get_sample_raw_file(user_id, sample.asset_id)
    if raw_file is None:
        _record_snp_report_usage(update, context, "lookup", success=False)
        await message.edit_text(
            search_no_raw_text(sample, lang=_ui_lang(context, user_id)),
            parse_mode="HTML",
            reply_markup=build_db_rule_lookup_result_keyboard(rule_index, category_index, rule_page, lang=_ui_lang(context, user_id)),
        )
        return

    raw_path = store.resolve_raw_file_path(raw_file)
    result = await run_in_heavy_pool(context, _lookup_snp_in_raw_path, str(raw_path), rule.rsid)
    lang = _ui_lang(context, user_id)
    _record_snp_report_usage(update, context, "lookup", success=(getattr(result, "error", None) is None), input_mode="callback")
    await message.edit_text(
        db_rule_lookup_result_text(rule, sample, result, lang=lang),
        parse_mode="HTML",
        reply_markup=build_db_rule_lookup_result_keyboard(rule_index, category_index, rule_page, lang=lang),
    )


async def _run_prefilled_snp_lookup(
    message,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    sample_id: str,
    rsid: str,
) -> None:
    normalized_rsid = _normalize_rsid(rsid)
    if normalized_rsid is None:
        _record_snp_report_usage(update, context, "lookup", success=False)
        await message.edit_text(
            search_invalid_text(lang=_ui_lang(context, user_id)),
            parse_mode="HTML",
            reply_markup=build_error_keyboard(),
        )
        return

    store = _my_data_store(context)
    sample = store.get_sample(user_id, sample_id)
    lang = _ui_lang(context, user_id)
    if sample is None:
        _record_snp_report_usage(update, context, "lookup", success=False)
        await message.edit_text(error_text("SNP Lab", "Sample не найден."), parse_mode="HTML", reply_markup=build_error_keyboard())
        return

    raw_file = store.get_sample_raw_file(user_id, sample.asset_id)
    if raw_file is None:
        _record_snp_report_usage(update, context, "lookup", success=False)
        await message.edit_text(search_no_raw_text(sample, lang=lang), parse_mode="HTML", reply_markup=build_search_result_keyboard(sample.asset_id, lang=lang))
        return

    raw_path = store.resolve_raw_file_path(raw_file)
    result = await run_in_heavy_pool(context, _lookup_snp_in_raw_path, str(raw_path), normalized_rsid)
    _record_snp_report_usage(update, context, "lookup", success=(getattr(result, "error", None) is None), input_mode="callback")
    await message.edit_text(
        search_result_text(sample, result, lang=lang),
        parse_mode="HTML",
        reply_markup=build_search_result_keyboard(sample.asset_id, lang=lang),
    )


async def _run_interesting_snps(
    message,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    sample_id: str,
) -> None:
    store = _my_data_store(context)
    sample = store.get_sample(user_id, sample_id)
    lang = _ui_lang(context, user_id)
    if sample is None:
        _record_snp_report_usage(update, context, "interesting", success=False)
        await message.edit_text(
            error_text("SNP Lab", "Sample не найден."),
            parse_mode="HTML",
            reply_markup=build_error_keyboard(),
        )
        return

    raw_file = store.get_sample_raw_file(user_id, sample.asset_id)
    if raw_file is None:
        _record_snp_report_usage(update, context, "interesting", success=False)
        await message.edit_text(
            search_no_raw_text(sample, lang=lang),
            parse_mode="HTML",
            reply_markup=build_interesting_result_keyboard(lang=lang),
        )
        return

    raw_path = store.resolve_raw_file_path(raw_file)
    if not raw_path.exists():
        _record_snp_report_usage(update, context, "interesting", success=False)
        await message.edit_text(
            error_text("SNP Lab", "Raw-файл не найден на диске."),
            parse_mode="HTML",
            reply_markup=build_error_keyboard(),
        )
        return

    await message.edit_text(interesting_running_text(sample, lang=lang), parse_mode="HTML")
    try:
        analysis = await run_in_heavy_pool(
            context,
            _build_interesting_snp_analysis,
            str(raw_path),
            _interesting_panel(context),
            sample.asset_id,
            sample.display_name,
        )
    except Exception:
        LOGGER.exception("Could not analyze interesting SNP panel")
        _record_snp_report_usage(update, context, "interesting", success=False)
        await message.edit_text(
            error_text("SNP Lab", "Не удалось прочитать raw-файл или построить результат."),
            parse_mode="HTML",
            reply_markup=build_error_keyboard(),
        )
        return

    _record_snp_report_usage(update, context, "interesting")
    await message.edit_text(
        interesting_result_text(analysis, lang=lang),
        parse_mode="HTML",
        reply_markup=build_interesting_result_keyboard_for_analysis(analysis, lang=lang),
        disable_web_page_preview=True,
    )


async def _show_interesting_detail(
    message,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    sample_id: str,
    rsid: str,
) -> None:
    store = _my_data_store(context)
    sample = store.get_sample(user_id, sample_id)
    lang = _ui_lang(context, user_id)
    if sample is None:
        _record_snp_report_usage(update, context, "interesting_detail", success=False)
        await message.edit_text(error_text("SNP Lab", "Sample не найден."), parse_mode="HTML", reply_markup=build_error_keyboard())
        return

    raw_file = store.get_sample_raw_file(user_id, sample.asset_id)
    if raw_file is None:
        _record_snp_report_usage(update, context, "interesting_detail", success=False)
        await message.edit_text(search_no_raw_text(sample, lang=lang), parse_mode="HTML", reply_markup=build_interesting_result_keyboard(lang=lang))
        return

    raw_path = store.resolve_raw_file_path(raw_file)
    try:
        analysis = await run_in_heavy_pool(
            context,
            _build_interesting_snp_analysis,
            str(raw_path),
            _interesting_panel(context),
            sample.asset_id,
            sample.display_name,
        )
    except Exception:
        LOGGER.exception("Could not build interesting SNP detail")
        _record_snp_report_usage(update, context, "interesting_detail", success=False)
        await message.edit_text(error_text("SNP Lab", "Не удалось прочитать raw-файл."), parse_mode="HTML", reply_markup=build_error_keyboard())
        return

    item = next((result for result in analysis.results if result.rsid == rsid and result.status == "ok"), None)
    if item is None:
        _record_snp_report_usage(update, context, "interesting_detail", success=False)
        await message.edit_text(error_text("SNP Lab", "Результат не найден."), parse_mode="HTML", reply_markup=build_interesting_result_keyboard(lang=lang))
        return

    _record_snp_report_usage(update, context, "interesting_detail")
    await message.edit_text(
        interesting_detail_text(item, sample.display_name, lang=lang),
        parse_mode="HTML",
        reply_markup=build_interesting_detail_keyboard(sample.asset_id, item.rsid, rule_index=_find_rule_index_by_rsid(_rules(context), item.rsid), lang=lang),
        disable_web_page_preview=True,
    )


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
    await _send_report_result(message, context, user_id, record, lang=lang)


async def _send_report_result(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    record,
    *,
    lang: str,
) -> None:
    markup = build_result_keyboard(record.summary.report_id, lang=lang)
    caption = result_text(record, lang=lang, visual=True)
    fallback_text = result_text(record, lang=lang, visual=False)
    image_path = _report_store(context).resolve_html_path(record.summary).with_suffix(".png")
    try:
        render_category_load_png(record, image_path, lang=lang)
        with image_path.open("rb") as handle:
            await message.reply_photo(
                photo=handle,
                caption=caption,
                parse_mode="HTML",
                reply_markup=markup,
                do_quote=False,
            )
        try:
            await message.delete()
        except Exception:
            LOGGER.debug("Could not delete SNP Lab status message", exc_info=True)
    except Exception:
        LOGGER.exception("Could not send SNP Lab visual report")
        await message.edit_text(
            fallback_text,
            parse_mode="HTML",
            reply_markup=markup,
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


def _clear_db_lookup_pending(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop(SNP_DB_LOOKUP_PENDING_KEY, None)


def _clear_db_search_pending(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop(SNP_DB_SEARCH_PENDING_KEY, None)


def _db_lookup_pending(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> dict[str, int] | None:
    pending = context.user_data.get(SNP_DB_LOOKUP_PENDING_KEY)
    if not isinstance(pending, dict):
        return None
    if int(pending.get("user_id", 0) or 0) != int(user_id):
        return None
    try:
        return {
            "rule_index": int(pending["rule_index"]),
            "category_index": int(pending["category_index"]),
            "rule_page": int(pending["rule_page"]),
        }
    except (KeyError, TypeError, ValueError):
        return None


def _normalize_rsid(value: str) -> str | None:
    cleaned = value.strip().lower()
    cleaned = cleaned.split()[0] if cleaned else ""
    if RSID_RE.match(cleaned):
        return cleaned
    return None


def _normalize_gene_query(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9/_-]+", "", value.strip().upper())
    return cleaned[:40]


def _find_rule_index_by_rsid(rules: tuple[SnpRule, ...], rsid: str) -> int | None:
    normalized = rsid.strip().lower()
    for index, rule in enumerate(rules):
        if rule.rsid == normalized:
            return index
    return None


def _find_rules_by_gene(rules: tuple[SnpRule, ...], query_text: str) -> list[tuple[int, SnpRule]]:
    query = _normalize_gene_query(query_text)
    if not query:
        return []
    matches: list[tuple[int, SnpRule]] = []
    for index, rule in enumerate(rules):
        haystack = " ".join([rule.gene, rule.title, rule.description]).upper()
        if query in haystack:
            matches.append((index, rule))
    return matches


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
        "🧪 Интересные SNP",
        "📊 Нагрузка по категориям",
        "🔎 Проверить rsID",
        "🔎 По rsID",
        "🧬 По gene",
        "📂 По категории",
        "⭐ Популярные SNP",
        "📚 Открыть в базе SNP",
        "👤 Проверить в другом sample",
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


def _build_interesting_snp_analysis(
    raw_path: str,
    panel: tuple[InterestingSnpDefinition, ...],
    sample_id: str,
    sample_name: str,
) -> object:
    return analyze_interesting_snps(Path(raw_path), panel, sample_id=sample_id, sample_name=sample_name)


def _lookup_snp_in_raw_path(raw_path: str, rsid: str) -> object:
    return lookup_snp_in_raw(Path(raw_path), rsid)
