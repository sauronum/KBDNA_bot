from __future__ import annotations

import html
import logging
from functools import partial

from telegram import Update
from telegram.ext import ContextTypes

from ui.common import (
    build_lookup_result_keyboard as build_lookup_result_keyboard_ui,
    build_lookup_suggestions_keyboard as build_lookup_suggestions_keyboard_ui,
)
from clients.sheets import SheetsClient
from clients.search_bases import (
    search_base_caption_label,
    search_base_for_update,
    sheets_client_for_search_base,
)
from stores.usage import UsageStore


logger = logging.getLogger(__name__)

LOOKUP_CALLBACK_PREFIX = "lookup"

_build_lookup_suggestions_keyboard = partial(build_lookup_suggestions_keyboard_ui, LOOKUP_CALLBACK_PREFIX)
_build_lookup_result_keyboard = partial(build_lookup_result_keyboard_ui, LOOKUP_CALLBACK_PREFIX)


async def _send_lookup_record(message, record: dict[str, object], base_label: str | None = None) -> None:
    del base_label
    await message.reply_text(str(record["text"]), parse_mode="HTML", do_quote=False)


async def lookup_suggestion_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.message is None:
        return

    try:
        _, action, raw_value = (query.data or "").split(":", 2)
    except (ValueError, TypeError):
        await query.answer("Не удалось определить вариант.", show_alert=True)
        return

    item_index: int | None = None
    if action in {"s", "r"}:
        try:
            item_index = int(raw_value)
        except (ValueError, TypeError):
            await query.answer("Не удалось определить вариант.", show_alert=True)
            return

    message_id = query.message.message_id
    if action == "s":
        suggestions_map = context.user_data.get("lookup_suggestions", {})
        suggestion_state = suggestions_map.get(message_id) or []
        if isinstance(suggestion_state, dict):
            suggestions = suggestion_state.get("suggestions") or []
            search_base = str(suggestion_state.get("search_base") or search_base_for_update(update, context))
            base_label = str(suggestion_state.get("base_label") or search_base_caption_label(search_base))
        else:
            suggestions = suggestion_state
            search_base = search_base_for_update(update, context)
            base_label = search_base_caption_label(search_base)
        if item_index < 0 or item_index >= len(suggestions):
            await query.answer("Подсказка больше не доступна.", show_alert=True)
            return

        selected_name = suggestions[item_index]
        suggestions_map.pop(message_id, None)
        if suggestions_map:
            context.user_data["lookup_suggestions"] = suggestions_map
        else:
            context.user_data.pop("lookup_suggestions", None)

        await query.answer()
        await query.edit_message_reply_markup(reply_markup=None)

        sheets: SheetsClient = sheets_client_for_search_base(context, search_base)
        usage_store: UsageStore = context.application.bot_data["usage_store"]
        records = sheets.get_group_records(selected_name)
        if records:
            usage_store.record_lookup(update, selected_name, success=True)
        await send_lookup_records(
            message=query.message,
            context=context,
            title_name=selected_name,
            records=records,
            use_buttons=True,
            base_label=base_label,
        )
        return

    if action == "r":
        result_map = context.user_data.get("lookup_result_options", {})
        result_state = result_map.get(message_id) or {}
        records = result_state.get("records") or []
        remaining_indexes = result_state.get("remaining_indexes") or []
        if item_index < 0 or item_index >= len(records) or item_index not in remaining_indexes:
            await query.answer("Вариант больше не доступен.", show_alert=True)
            return

        selected_record = records[item_index]
        remaining_indexes = [index for index in remaining_indexes if index != item_index]
        await query.answer()
        await _send_lookup_record(query.message, selected_record, result_state.get("base_label"))
        if remaining_indexes:
            result_state["remaining_indexes"] = remaining_indexes
            result_map[message_id] = result_state
            context.user_data["lookup_result_options"] = result_map
            await query.edit_message_reply_markup(reply_markup=_build_lookup_result_keyboard(records, remaining_indexes))
        else:
            result_map.pop(message_id, None)
            if result_map:
                context.user_data["lookup_result_options"] = result_map
            else:
                context.user_data.pop("lookup_result_options", None)
            await query.message.delete()
        return

    if action == "a":
        if raw_value != "all":
            await query.answer("Вариант больше не доступен.", show_alert=True)
            return

        result_map = context.user_data.get("lookup_result_options", {})
        result_state = result_map.get(message_id) or {}
        records = result_state.get("records") or []
        remaining_indexes = result_state.get("remaining_indexes") or []
        if not remaining_indexes:
            await query.answer("Варианты больше не доступны.", show_alert=True)
            return

        await query.answer()
        for index in remaining_indexes:
            await _send_lookup_record(query.message, records[index], result_state.get("base_label"))

        result_map.pop(message_id, None)
        if result_map:
            context.user_data["lookup_result_options"] = result_map
        else:
            context.user_data.pop("lookup_result_options", None)
        await query.message.delete()
        return

    await query.answer("Неизвестное действие.", show_alert=True)


async def send_lookup_records(
    *,
    message,
    context: ContextTypes.DEFAULT_TYPE,
    title_name: str,
    records: list[dict[str, str]],
    use_buttons: bool,
    base_label: str | None = None,
) -> None:
    if not records:
        return

    if not use_buttons or len(records) <= 1:
        for item in records:
            await _send_lookup_record(message, item, base_label)
        return

    header_lines = [f"<b>{html.escape(title_name.upper())}</b>"]
    sent = await message.reply_text(
        "\n".join(header_lines) + "\n\nВыберите вариант:",
        parse_mode="HTML",
        reply_markup=_build_lookup_result_keyboard(records),
        do_quote=False,
    )
    result_map = context.user_data.setdefault("lookup_result_options", {})
    result_state = {
        "records": records,
        "remaining_indexes": list(range(len(records))),
    }
    if base_label:
        result_state["base_label"] = base_label
    result_map[sent.message_id] = result_state


async def handle_lookup(update: Update, context: ContextTypes.DEFAULT_TYPE, name: str) -> None:
    search_base = search_base_for_update(update, context)
    base_label = search_base_caption_label(search_base)
    sheets: SheetsClient = sheets_client_for_search_base(context, search_base)
    usage_store: UsageStore = context.application.bot_data["usage_store"]
    message = update.effective_message
    if message is None:
        return
    normalized_name = " ".join(name.split())

    try:
        records = sheets.get_group_records(name)
    except Exception:
        logger.exception("Sheets read error")
        usage_store.record_lookup(update, normalized_name, success=False)
        await message.reply_text(
            "Не удалось получить данные из таблицы. Попробуйте чуть позже.",
            do_quote=False,
        )
        return

    if not records:
        similar_names = sheets.find_similar_names(normalized_name)
        used_collective_form = sheets._uses_collective_suffix(normalized_name)
        if similar_names:
            if used_collective_form:
                resolved_name = similar_names[0]
                resolved_records = sheets.get_group_records(resolved_name)
                if resolved_records:
                    usage_store.record_lookup(update, resolved_name, success=True)
                    await send_lookup_records(
                        message=message,
                        context=context,
                        title_name=resolved_name,
                        records=resolved_records,
                        use_buttons=True,
                        base_label=base_label,
                    )
                    return

            sent = await message.reply_text(
                f"Фамилия <b>{html.escape(normalized_name)}</b> не найдена.\n\n"
                + "Выберите подходящий вариант:",
                parse_mode="HTML",
                reply_markup=_build_lookup_suggestions_keyboard(similar_names),
                do_quote=False,
            )
            suggestions_map = context.user_data.setdefault("lookup_suggestions", {})
            suggestions_map[sent.message_id] = {
                "suggestions": list(similar_names),
                "search_base": search_base,
                "base_label": base_label,
            }
        else:
            usage_store.record_lookup(update, normalized_name, success=False)
            fallback = (
                f"Фамилия <b>{html.escape(normalized_name)}</b> в такой форме не найдена.\n"
                + "Попробуйте русскую форму написания или другой вариант."
                if used_collective_form
                else f"Фамилия <b>{html.escape(normalized_name)}</b> не найдена.\n"
                + "Проверьте написание и попробуйте другой вариант."
            )
            await message.reply_text(
                fallback,
                parse_mode="HTML",
                do_quote=False,
            )
        return

    usage_store.record_lookup(update, normalized_name, success=True)
    await send_lookup_records(
        message=message,
        context=context,
        title_name=normalized_name,
        records=records,
        use_buttons=True,
        base_label=base_label,
    )


async def find_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return

    if not context.args:
        await update.message.reply_text("Укажите фамилию: /f <Фамилия>", do_quote=False)
        return

    name = " ".join(context.args).strip()
    await handle_lookup(update, context, name)


async def text_lookup_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.message.text is None:
        return

    if update.effective_chat is None or update.effective_chat.type != "private":
        return

    name = update.message.text.strip()
    if not name:
        return

    await handle_lookup(update, context, name)
