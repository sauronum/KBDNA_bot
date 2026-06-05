from __future__ import annotations

from functools import partial
from pathlib import Path
from typing import Any

from telegram import Update
from telegram.ext import ApplicationHandlerStop, ContextTypes

from clients.sheets import SheetsClient
from handlers.sozluk import clear_sozluk_pending
from stores.usage import UsageStore
from features.ystr import make_uploaded_ystr_entry, parse_ystr_markers_from_text
from ui.ystr import (
    build_ystr_candidates_keyboard as build_ystr_candidates_keyboard_ui,
    build_ystr_compare_candidates_keyboard as build_ystr_compare_candidates_keyboard_ui,
    build_ystr_compare_prompt_keyboard as build_ystr_compare_prompt_keyboard_ui,
    build_ystr_compare_result_keyboard as build_ystr_compare_result_keyboard_ui,
    build_ystr_data_candidates_keyboard as build_ystr_data_candidates_keyboard_ui,
    build_ystr_data_matches_keyboard as build_ystr_data_matches_keyboard_ui,
    build_ystr_prompt_keyboard as build_ystr_prompt_keyboard_ui,
    build_ystr_result_keyboard as build_ystr_result_keyboard_ui,
    build_ystr_root_keyboard as build_ystr_root_keyboard_ui,
    build_ystr_test_data_keyboard as build_ystr_test_data_keyboard_ui,
    build_ystr_upload_compare_candidates_keyboard as build_ystr_upload_compare_candidates_keyboard_ui,
    build_ystr_uploaded_profile_keyboard as build_ystr_uploaded_profile_keyboard_ui,
    build_ystr_uploaded_view_keyboard as build_ystr_uploaded_view_keyboard_ui,
    format_ystr_comparison_text,
    format_ystr_matches_text,
    format_ystr_test_data_text,
    format_ystr_uploaded_summary_text,
)


DEFAULT_YSTR_CALLBACK_PREFIX = "ystr"

_build_ystr_root_keyboard = partial(build_ystr_root_keyboard_ui, DEFAULT_YSTR_CALLBACK_PREFIX)
_build_ystr_prompt_keyboard = partial(build_ystr_prompt_keyboard_ui, DEFAULT_YSTR_CALLBACK_PREFIX)
_build_ystr_compare_prompt_keyboard = partial(build_ystr_compare_prompt_keyboard_ui, DEFAULT_YSTR_CALLBACK_PREFIX)
_build_ystr_candidates_keyboard = partial(build_ystr_candidates_keyboard_ui, DEFAULT_YSTR_CALLBACK_PREFIX)
_build_ystr_data_candidates_keyboard = partial(build_ystr_data_candidates_keyboard_ui, DEFAULT_YSTR_CALLBACK_PREFIX)
_build_ystr_compare_candidates_keyboard = partial(build_ystr_compare_candidates_keyboard_ui, DEFAULT_YSTR_CALLBACK_PREFIX)
_build_ystr_result_keyboard = partial(build_ystr_result_keyboard_ui, DEFAULT_YSTR_CALLBACK_PREFIX)
_build_ystr_data_matches_keyboard = partial(build_ystr_data_matches_keyboard_ui, DEFAULT_YSTR_CALLBACK_PREFIX)
_build_ystr_test_data_keyboard = partial(build_ystr_test_data_keyboard_ui, DEFAULT_YSTR_CALLBACK_PREFIX)
_build_ystr_compare_result_keyboard = partial(build_ystr_compare_result_keyboard_ui, DEFAULT_YSTR_CALLBACK_PREFIX)
_build_ystr_uploaded_profile_keyboard = partial(build_ystr_uploaded_profile_keyboard_ui, DEFAULT_YSTR_CALLBACK_PREFIX)
_build_ystr_uploaded_view_keyboard = partial(build_ystr_uploaded_view_keyboard_ui, DEFAULT_YSTR_CALLBACK_PREFIX)
_build_ystr_upload_compare_candidates_keyboard = partial(
    build_ystr_upload_compare_candidates_keyboard_ui,
    DEFAULT_YSTR_CALLBACK_PREFIX,
)


def clear_ystr_pending(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop("ystr_pending", None)
    context.user_data.pop("ystr_candidates", None)
    context.user_data.pop("ystr_data_candidates", None)
    context.user_data.pop("ystr_data_back_action", None)
    context.user_data.pop("ystr_compare", None)
    context.user_data.pop("ystr_uploaded_profile", None)
    context.user_data.pop("ystr_upload_compare_candidates", None)


def set_ystr_pending(context: ContextTypes.DEFAULT_TYPE, chat_id: int, mode: str) -> None:
    context.user_data["ystr_pending"] = {"chat_id": chat_id, "mode": mode}


def pop_ystr_pending(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> str | None:
    pending = context.user_data.get("ystr_pending")
    if not isinstance(pending, dict):
        return None
    if int(pending.get("chat_id") or 0) != chat_id:
        return None
    context.user_data.pop("ystr_pending", None)
    return str(pending.get("mode") or "")


def set_ystr_data_back_action(context: ContextTypes.DEFAULT_TYPE, action: str) -> None:
    context.user_data["ystr_data_back_action"] = action


def get_ystr_data_back_action(context: ContextTypes.DEFAULT_TYPE) -> str:
    action = str(context.user_data.get("ystr_data_back_action") or "")
    if action in {"datacandidates", "testdata"}:
        return action
    return "datacandidates" if context.user_data.get("ystr_data_candidates") else "testdata"


def _reply_menu_hooks(context: ContextTypes.DEFAULT_TYPE) -> dict[str, Any]:
    hooks = context.application.bot_data.get("reply_menu_hooks", {})
    return hooks if isinstance(hooks, dict) else {}


async def _collapse_active_reply_menu(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    hook = _reply_menu_hooks(context).get("collapse_active_reply_menu")
    if hook is not None:
        await hook(context, chat_id)


def _remember_active_reply_menu(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int) -> None:
    hook = _reply_menu_hooks(context).get("remember_active_reply_menu")
    if hook is not None:
        hook(context, chat_id, message_id)


def _remember_reply_menu_owner(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int, user_id: int) -> None:
    hook = _reply_menu_hooks(context).get("remember_reply_menu_owner")
    if hook is not None:
        hook(context, chat_id, message_id, user_id)


async def _ensure_reply_menu_owner(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    hook = _reply_menu_hooks(context).get("ensure_reply_menu_owner")
    if hook is None:
        return True
    return bool(await hook(update, context))


async def _activate_reply_menu(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int) -> bool:
    hook = _reply_menu_hooks(context).get("activate_reply_menu")
    if hook is None:
        return True
    return bool(await hook(context, chat_id, message_id))


def _forget_active_reply_menu(context: ContextTypes.DEFAULT_TYPE, chat_id: int, *, message_id: int | None = None) -> None:
    hook = _reply_menu_hooks(context).get("forget_active_reply_menu")
    if hook is not None:
        hook(context, chat_id, message_id=message_id)


async def send_ystr_root_message(message, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    clear_ystr_pending(context)
    clear_sozluk_pending(context)
    context.user_data.pop("ystr_root_back_callback", None)
    await _collapse_active_reply_menu(context, message.chat_id)
    sent = await message.reply_text(
        "🧬 <b>Y-STR анализ</b>\n\nВыберите режим:",
        parse_mode="HTML",
        reply_markup=_build_ystr_root_keyboard(),
        do_quote=False,
    )
    _remember_active_reply_menu(context, sent.chat_id, sent.message_id)
    if update.effective_user is not None:
        _remember_reply_menu_owner(context, sent.chat_id, sent.message_id, update.effective_user.id)


async def open_ystr_root_inline_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    back_callback: str | None = None,
) -> None:
    clear_ystr_pending(context)
    clear_sozluk_pending(context)
    if back_callback:
        context.user_data["ystr_root_back_callback"] = back_callback
    else:
        context.user_data.pop("ystr_root_back_callback", None)
    await message.edit_text(
        "🧬 <b>Y-STR анализ</b>\n\nВыберите режим:",
        parse_mode="HTML",
        reply_markup=_build_ystr_root_keyboard(back_callback),
    )


def record_ystr_action(
    context: ContextTypes.DEFAULT_TYPE,
    update: Update,
    command: str,
    *,
    success: bool = True,
    query: str | None = None,
    input_mode: str = "menu",
) -> None:
    usage_store: UsageStore | None = context.application.bot_data.get("usage_store")
    if usage_store is not None:
        usage_store.record_ystr(update, command=command, success=success, query=query, input_mode=input_mode)


async def ystr_pending_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.message.text is None:
        return
    mode = pop_ystr_pending(context, update.message.chat_id)
    if mode not in {"nearest_name", "testdata_name", "compare_left_name", "compare_right_name", "upload_text", "upload_compare_name"}:
        return

    sheets: SheetsClient = context.application.bot_data["sheets"]
    query = " ".join(update.message.text.split())

    if mode == "upload_text":
        markers = parse_ystr_markers_from_text(update.message.text)
        if len(markers) < 8:
            await update.message.reply_text(
                "Не удалось распознать достаточно STR-маркеров. Пришлите строки вида:\nDYS393 13\nDYS390 24",
                do_quote=False,
            )
            raise ApplicationHandlerStop
        entry = make_uploaded_ystr_entry(markers)
        context.user_data["ystr_uploaded_profile"] = entry
        record_ystr_action(context, update, "upload", query=f"{len(markers)} markers", input_mode="text")
        await _collapse_active_reply_menu(context, update.message.chat_id)
        sent = await update.message.reply_text(
            format_ystr_uploaded_summary_text(entry),
            parse_mode="HTML",
            reply_markup=_build_ystr_uploaded_profile_keyboard(),
            do_quote=False,
        )
        _remember_active_reply_menu(context, sent.chat_id, sent.message_id)
        if update.effective_user is not None:
            _remember_reply_menu_owner(context, sent.chat_id, sent.message_id, update.effective_user.id)
        raise ApplicationHandlerStop

    candidates = sheets.get_ystr_records_by_name(query)
    if not candidates:
        failure_command = {
            "nearest_name": "nearest",
            "testdata_name": "testdata",
            "compare_left_name": "compare",
            "compare_right_name": "compare",
            "upload_compare_name": "upload_compare",
        }.get(mode, "search")
        record_ystr_action(context, update, failure_command, success=False, query=query)
        await _collapse_active_reply_menu(context, update.message.chat_id)
        await update.message.reply_text(
            "По этой фамилии нет записей с STR-маркерами. Попробуйте другую фамилию.",
            do_quote=False,
        )
        raise ApplicationHandlerStop

    if mode == "upload_compare_name":
        context.user_data["ystr_upload_compare_candidates"] = [int(entry.get("entry_index") or 0) for entry in candidates[:20]]
        await _collapse_active_reply_menu(context, update.message.chat_id)
        if len(candidates) == 1:
            uploaded = context.user_data.get("ystr_uploaded_profile")
            if not isinstance(uploaded, dict):
                await update.message.reply_text("Загруженные маркеры не найдены. Отправьте их заново.", do_quote=False)
                raise ApplicationHandlerStop
            comparison = sheets.compare_ystr_entries(uploaded, candidates[0])
            record_ystr_action(context, update, "upload_compare", query=query)
            sent = await update.message.reply_text(
                format_ystr_comparison_text(uploaded, candidates[0], comparison),
                parse_mode="HTML",
                reply_markup=_build_ystr_uploaded_view_keyboard(),
                do_quote=False,
            )
        else:
            sent = await update.message.reply_text(
                "Найдено несколько STR-записей. Выберите нужную:",
                reply_markup=_build_ystr_upload_compare_candidates_keyboard(candidates),
                do_quote=False,
            )
        _remember_active_reply_menu(context, sent.chat_id, sent.message_id)
        if update.effective_user is not None:
            _remember_reply_menu_owner(context, sent.chat_id, sent.message_id, update.effective_user.id)
        raise ApplicationHandlerStop

    if mode.startswith("compare_"):
        side = "left" if mode == "compare_left_name" else "right"
        compare_state = context.user_data.setdefault("ystr_compare", {})
        compare_state[f"{side}_candidates"] = [int(entry.get("entry_index") or 0) for entry in candidates[:20]]
        if len(candidates) == 1:
            entry_index = int(candidates[0].get("entry_index") or 0)
            compare_state[side] = entry_index
            await _collapse_active_reply_menu(context, update.message.chat_id)
            if side == "left":
                set_ystr_pending(context, update.message.chat_id, "compare_right_name")
                sent = await update.message.reply_text(
                    "🧬 <b>Сравнить две записи</b>\n\nПервая запись выбрана.\n\nВведите вторую фамилию:",
                    parse_mode="HTML",
                    reply_markup=_build_ystr_compare_prompt_keyboard("compare_left_selected"),
                    do_quote=False,
                )
                _remember_active_reply_menu(context, sent.chat_id, sent.message_id)
                if update.effective_user is not None:
                    _remember_reply_menu_owner(context, sent.chat_id, sent.message_id, update.effective_user.id)
                raise ApplicationHandlerStop

            left = sheets.get_ystr_entry_by_index(int(compare_state.get("left") or -1))
            right = sheets.get_ystr_entry_by_index(entry_index)
            if left is None or right is None:
                await update.message.reply_text("Не удалось найти одну из записей. Начните сравнение заново.", do_quote=False)
                raise ApplicationHandlerStop
            comparison = sheets.compare_ystr_entries(left, right)
            record_ystr_action(context, update, "compare", query=query)
            sent = await update.message.reply_text(
                format_ystr_comparison_text(left, right, comparison),
                parse_mode="HTML",
                reply_markup=_build_ystr_compare_result_keyboard(),
                do_quote=False,
            )
            _remember_active_reply_menu(context, sent.chat_id, sent.message_id)
            if update.effective_user is not None:
                _remember_reply_menu_owner(context, sent.chat_id, sent.message_id, update.effective_user.id)
            raise ApplicationHandlerStop

        await _collapse_active_reply_menu(context, update.message.chat_id)
        sent = await update.message.reply_text(
            "Найдено несколько STR-записей. Выберите нужную:",
            reply_markup=_build_ystr_compare_candidates_keyboard(candidates, side),
            do_quote=False,
        )
        _remember_active_reply_menu(context, sent.chat_id, sent.message_id)
        if update.effective_user is not None:
            _remember_reply_menu_owner(context, sent.chat_id, sent.message_id, update.effective_user.id)
        raise ApplicationHandlerStop

    candidate_key = "ystr_data_candidates" if mode == "testdata_name" else "ystr_candidates"
    callback_keyboard = _build_ystr_data_candidates_keyboard if mode == "testdata_name" else _build_ystr_candidates_keyboard

    if len(candidates) == 1:
        await _collapse_active_reply_menu(context, update.message.chat_id)
        if mode == "testdata_name":
            entry = candidates[0]
            entry_index = int(entry.get("entry_index") or 0)
            marker_count = int(entry.get("marker_count") or 0)
            context.user_data.pop("ystr_data_candidates", None)
            set_ystr_data_back_action(context, "testdata")
            record_ystr_action(context, update, "testdata", query=query)
            sent = await update.message.reply_text(
                format_ystr_test_data_text(entry, show_all=False),
                parse_mode="HTML",
                reply_markup=_build_ystr_test_data_keyboard(entry_index, show_all=False, has_more=marker_count > 37),
                do_quote=False,
            )
            _remember_active_reply_menu(context, sent.chat_id, sent.message_id)
            if update.effective_user is not None:
                _remember_reply_menu_owner(context, sent.chat_id, sent.message_id, update.effective_user.id)
        else:
            entry = candidates[0]
            context.user_data["ystr_candidates"] = [int(entry.get("entry_index") or 0)]
            matches = sheets.find_ystr_matches(candidates[0])
            record_ystr_action(context, update, "nearest", query=query)
            sent = await update.message.reply_text(
                format_ystr_matches_text(entry, matches),
                parse_mode="HTML",
                reply_markup=_build_ystr_result_keyboard("nearest"),
                do_quote=False,
            )
            _remember_active_reply_menu(context, sent.chat_id, sent.message_id)
            if update.effective_user is not None:
                _remember_reply_menu_owner(context, sent.chat_id, sent.message_id, update.effective_user.id)
        raise ApplicationHandlerStop

    context.user_data[candidate_key] = [int(entry.get("entry_index") or 0) for entry in candidates[:20]]
    if mode == "testdata_name":
        set_ystr_data_back_action(context, "testdata")
    await _collapse_active_reply_menu(context, update.message.chat_id)
    sent = await update.message.reply_text(
        "Найдено несколько STR-записей. Выберите нужную:",
        reply_markup=callback_keyboard(candidates),
        do_quote=False,
    )
    _remember_active_reply_menu(context, sent.chat_id, sent.message_id)
    if update.effective_user is not None:
        _remember_reply_menu_owner(context, sent.chat_id, sent.message_id, update.effective_user.id)
    raise ApplicationHandlerStop


async def ystr_document_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.message.document is None:
        return
    pending = context.user_data.get("ystr_pending")
    if not isinstance(pending, dict) or str(pending.get("mode") or "") != "upload_text":
        return
    if int(pending.get("chat_id") or 0) != update.message.chat_id:
        return

    document = update.message.document
    file_name = document.file_name or "markers.txt"
    if not file_name.lower().endswith((".txt", ".csv", ".tsv")):
        await update.message.reply_text("Пока принимаю STR-маркеры в .txt, .csv или .tsv.", do_quote=False)
        raise ApplicationHandlerStop

    telegram_file = await document.get_file()
    data = await telegram_file.download_as_bytearray()
    text = bytes(data).decode("utf-8-sig", errors="replace")
    markers = parse_ystr_markers_from_text(text)
    if len(markers) < 8:
        await update.message.reply_text(
            "Не удалось распознать достаточно STR-маркеров в файле. Проверьте формат: DYS393 13, DYS390 24 и т.п.",
            do_quote=False,
        )
        raise ApplicationHandlerStop

    context.user_data.pop("ystr_pending", None)
    entry = make_uploaded_ystr_entry(markers, label=Path(file_name).stem or "Пользовательский STR-профиль")
    context.user_data["ystr_uploaded_profile"] = entry
    record_ystr_action(context, update, "upload", query=file_name, input_mode="file")
    await _collapse_active_reply_menu(context, update.message.chat_id)
    sent = await update.message.reply_text(
        format_ystr_uploaded_summary_text(entry),
        parse_mode="HTML",
        reply_markup=_build_ystr_uploaded_profile_keyboard(),
        do_quote=False,
    )
    _remember_active_reply_menu(context, sent.chat_id, sent.message_id)
    if update.effective_user is not None:
        _remember_reply_menu_owner(context, sent.chat_id, sent.message_id, update.effective_user.id)
    raise ApplicationHandlerStop


async def ystr_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.message is None:
        return
    try:
        _, action = (query.data or "").split(":", 1)
    except (ValueError, TypeError):
        await query.answer("Неизвестное действие.", show_alert=True)
        return
    if not await _ensure_reply_menu_owner(update, context):
        return
    await query.answer()
    if not await _activate_reply_menu(context, query.message.chat_id, query.message.message_id):
        return

    if action == "root":
        clear_ystr_pending(context)
        back_callback = str(context.user_data.get("ystr_root_back_callback") or "")
        await query.message.edit_text(
            "🧬 <b>Y-STR анализ</b>\n\nВыберите режим:",
            parse_mode="HTML",
            reply_markup=_build_ystr_root_keyboard(back_callback if back_callback else None),
        )
        return

    if action == "nearest":
        set_ystr_pending(context, query.message.chat_id, "nearest_name")
        await query.message.edit_text(
            "🧬 <b>Y-STR анализ</b>\n\nВведите фамилию из базы, для которой нужно найти ближайшие STR-совпадения.",
            parse_mode="HTML",
            reply_markup=_build_ystr_prompt_keyboard(),
        )
        return

    if action == "testdata":
        set_ystr_pending(context, query.message.chat_id, "testdata_name")
        await query.message.edit_text(
            "🧬 <b>Данные теста</b>\n\nВведите фамилию из базы, чтобы посмотреть STR-маркеры.",
            parse_mode="HTML",
            reply_markup=_build_ystr_prompt_keyboard(),
        )
        return

    if action == "upload":
        set_ystr_pending(context, query.message.chat_id, "upload_text")
        await query.message.edit_text(
            "🧬 <b>Загрузить маркеры</b>\n\n"
            "Отправьте STR-маркеры текстом или .txt/.csv файлом.\n\n"
            "Пример:\n<code>DYS393 13\nDYS390 24\nDYS19 15\nDYS385 11-14</code>",
            parse_mode="HTML",
            reply_markup=_build_ystr_prompt_keyboard(),
        )
        return

    if action == "uploaded":
        uploaded = context.user_data.get("ystr_uploaded_profile")
        if not isinstance(uploaded, dict):
            await query.answer("Загруженные маркеры не найдены. Отправьте их заново.", show_alert=True)
            return
        await query.message.edit_text(
            format_ystr_uploaded_summary_text(uploaded),
            parse_mode="HTML",
            reply_markup=_build_ystr_uploaded_profile_keyboard(),
        )
        return

    if action == "uploadshow":
        uploaded = context.user_data.get("ystr_uploaded_profile")
        if not isinstance(uploaded, dict):
            await query.answer("Загруженные маркеры не найдены. Отправьте их заново.", show_alert=True)
            return
        await query.message.edit_text(
            format_ystr_test_data_text(uploaded, show_all=True),
            parse_mode="HTML",
            reply_markup=_build_ystr_uploaded_view_keyboard(),
        )
        return

    if action == "uploadmatches":
        uploaded = context.user_data.get("ystr_uploaded_profile")
        if not isinstance(uploaded, dict):
            await query.answer("Загруженные маркеры не найдены. Отправьте их заново.", show_alert=True)
            return
        sheets: SheetsClient = context.application.bot_data["sheets"]
        matches = sheets.find_ystr_matches(uploaded)
        record_ystr_action(context, update, "upload_nearest", query=f"{int(uploaded.get('marker_count') or 0)} markers")
        await query.message.edit_text(
            format_ystr_matches_text(uploaded, matches),
            parse_mode="HTML",
            reply_markup=_build_ystr_uploaded_view_keyboard(),
        )
        return

    if action == "uploadcompare":
        if not isinstance(context.user_data.get("ystr_uploaded_profile"), dict):
            await query.answer("Загруженные маркеры не найдены. Отправьте их заново.", show_alert=True)
            return
        set_ystr_pending(context, query.message.chat_id, "upload_compare_name")
        await query.message.edit_text(
            "🧬 <b>Сравнить с тестом KBDNA</b>\n\nВведите фамилию из базы:",
            parse_mode="HTML",
            reply_markup=_build_ystr_uploaded_view_keyboard(),
        )
        return

    if action == "compare_start":
        context.user_data["ystr_compare"] = {}
        set_ystr_pending(context, query.message.chat_id, "compare_left_name")
        await query.message.edit_text(
            "🧬 <b>Сравнить две записи</b>\n\nВведите первую фамилию:",
            parse_mode="HTML",
            reply_markup=_build_ystr_compare_prompt_keyboard("root"),
        )
        return

    if action == "compare_help":
        context.user_data["ystr_compare"] = {}
        set_ystr_pending(context, query.message.chat_id, "compare_left_name")
        await query.message.edit_text(
            "🧬 <b>Сравнить две записи</b>\n\nВведите первую фамилию:",
            parse_mode="HTML",
            reply_markup=_build_ystr_compare_prompt_keyboard("root"),
        )
        return

    if action == "help":
        await query.message.edit_text(
            "🧬 <b>Y-STR анализ</b>\n\n"
            "Бот сравнивает STR-маркеры только по общим заполненным полям и считает genetic distance (GD).\n\n"
            "Чем меньше GD и чем больше общих маркеров, тем ближе совпадение. "
            "Это ориентир по отцовской линии, а не точная дата общего предка.",
            parse_mode="HTML",
            reply_markup=_build_ystr_prompt_keyboard(),
        )
        return

    if action == "cancel":
        clear_ystr_pending(context)
        context.user_data.pop("ystr_root_back_callback", None)
        _forget_active_reply_menu(context, query.message.chat_id, message_id=query.message.message_id)
        await query.message.delete()
        return

    if action.startswith("pick:"):
        try:
            pick_index = int(action.split(":", 1)[1])
            entry_indexes = context.user_data.get("ystr_candidates") or []
            entry_index = int(entry_indexes[pick_index])
        except (ValueError, IndexError, TypeError):
            await query.answer("Список устарел. Откройте Y-STR анализ заново.", show_alert=True)
            return
        sheets: SheetsClient = context.application.bot_data["sheets"]
        entry = sheets.get_ystr_entry_by_index(entry_index)
        if entry is None:
            await query.answer("Запись не найдена. Откройте Y-STR анализ заново.", show_alert=True)
            return
        matches = sheets.find_ystr_matches(entry)
        record_ystr_action(context, update, "nearest", query=str(entry.get("name") or ""))
        await query.message.edit_text(
            format_ystr_matches_text(entry, matches),
            parse_mode="HTML",
            reply_markup=_build_ystr_result_keyboard(),
        )
        return

    if action == "compare_left_selected":
        compare_state = context.user_data.get("ystr_compare") if isinstance(context.user_data.get("ystr_compare"), dict) else {}
        left_index = compare_state.get("left")
        if left_index is None:
            set_ystr_pending(context, query.message.chat_id, "compare_left_name")
            await query.message.edit_text(
                "🧬 <b>Сравнить две записи</b>\n\nВведите первую фамилию:",
                parse_mode="HTML",
                reply_markup=_build_ystr_compare_prompt_keyboard("root"),
            )
            return
        set_ystr_pending(context, query.message.chat_id, "compare_right_name")
        await query.message.edit_text(
            "🧬 <b>Сравнить две записи</b>\n\nПервая запись выбрана.\n\nВведите вторую фамилию:",
            parse_mode="HTML",
            reply_markup=_build_ystr_compare_prompt_keyboard("compare_left_selected"),
        )
        return

    if action.startswith("comparepick:"):
        try:
            _, side, index_text = action.split(":", 2)
            pick_index = int(index_text)
            compare_state = context.user_data.setdefault("ystr_compare", {})
            entry_indexes = compare_state.get(f"{side}_candidates") or []
            entry_index = int(entry_indexes[pick_index])
        except (ValueError, IndexError, TypeError):
            await query.answer("Список устарел. Начните сравнение заново.", show_alert=True)
            return
        if side not in {"left", "right"}:
            await query.answer("Неизвестная сторона сравнения.", show_alert=True)
            return
        compare_state[side] = entry_index
        sheets: SheetsClient = context.application.bot_data["sheets"]
        if side == "left":
            set_ystr_pending(context, query.message.chat_id, "compare_right_name")
            await query.message.edit_text(
                "🧬 <b>Сравнить две записи</b>\n\nПервая запись выбрана.\n\nВведите вторую фамилию:",
                parse_mode="HTML",
                reply_markup=_build_ystr_compare_prompt_keyboard("compare_left_selected"),
            )
            return

        left = sheets.get_ystr_entry_by_index(int(compare_state.get("left") or -1))
        right = sheets.get_ystr_entry_by_index(entry_index)
        if left is None or right is None:
            await query.answer("Не удалось найти одну из записей. Начните сравнение заново.", show_alert=True)
            return
        comparison = sheets.compare_ystr_entries(left, right)
        record_ystr_action(context, update, "compare", query=f"{left.get('name') or ''} / {right.get('name') or ''}")
        await query.message.edit_text(
            format_ystr_comparison_text(left, right, comparison),
            parse_mode="HTML",
            reply_markup=_build_ystr_compare_result_keyboard(),
        )
        return

    if action.startswith("uploadpick:"):
        uploaded = context.user_data.get("ystr_uploaded_profile")
        if not isinstance(uploaded, dict):
            await query.answer("Загруженные маркеры не найдены. Отправьте их заново.", show_alert=True)
            return
        try:
            pick_index = int(action.split(":", 1)[1])
            entry_indexes = context.user_data.get("ystr_upload_compare_candidates") or []
            entry_index = int(entry_indexes[pick_index])
        except (ValueError, IndexError, TypeError):
            await query.answer("Список устарел. Введите фамилию заново.", show_alert=True)
            return
        sheets: SheetsClient = context.application.bot_data["sheets"]
        entry = sheets.get_ystr_entry_by_index(entry_index)
        if entry is None:
            await query.answer("Запись не найдена.", show_alert=True)
            return
        comparison = sheets.compare_ystr_entries(uploaded, entry)
        record_ystr_action(context, update, "upload_compare", query=str(entry.get("name") or ""))
        await query.message.edit_text(
            format_ystr_comparison_text(uploaded, entry, comparison),
            parse_mode="HTML",
            reply_markup=_build_ystr_uploaded_view_keyboard(),
        )
        return

    if action == "datacandidates":
        sheets: SheetsClient = context.application.bot_data["sheets"]
        entry_indexes = context.user_data.get("ystr_data_candidates") or []
        candidates = [
            entry
            for entry_index in entry_indexes
            for entry in [sheets.get_ystr_entry_by_index(int(entry_index))]
            if entry is not None
        ]
        if not candidates:
            await query.answer("Список устарел. Введите фамилию заново.", show_alert=True)
            return
        await query.message.edit_text(
            "Найдено несколько STR-записей. Выберите нужную:",
            reply_markup=_build_ystr_data_candidates_keyboard(candidates),
        )
        return

    if action == "databack":
        back_action = get_ystr_data_back_action(context)
        if back_action == "datacandidates":
            sheets: SheetsClient = context.application.bot_data["sheets"]
            entry_indexes = context.user_data.get("ystr_data_candidates") or []
            candidates = [
                entry
                for entry_index in entry_indexes
                for entry in [sheets.get_ystr_entry_by_index(int(entry_index))]
                if entry is not None
            ]
            if candidates:
                await query.message.edit_text(
                    "Найдено несколько STR-записей. Выберите нужную:",
                    reply_markup=_build_ystr_data_candidates_keyboard(candidates),
                )
                return

        set_ystr_pending(context, query.message.chat_id, "testdata_name")
        await query.message.edit_text(
            "🧬 <b>Данные теста</b>\n\nВведите фамилию из базы, чтобы посмотреть STR-маркеры.",
            parse_mode="HTML",
            reply_markup=_build_ystr_prompt_keyboard(),
        )
        return

    if action.startswith("datapick:"):
        try:
            pick_index = int(action.split(":", 1)[1])
            entry_indexes = context.user_data.get("ystr_data_candidates") or []
            entry_index = int(entry_indexes[pick_index])
        except (ValueError, IndexError, TypeError):
            await query.answer("Список устарел. Откройте данные теста заново.", show_alert=True)
            return
        sheets: SheetsClient = context.application.bot_data["sheets"]
        entry = sheets.get_ystr_entry_by_index(entry_index)
        if entry is None:
            await query.answer("Запись не найдена. Откройте данные теста заново.", show_alert=True)
            return
        marker_count = int(entry.get("marker_count") or 0)
        set_ystr_data_back_action(context, "datacandidates")
        record_ystr_action(context, update, "testdata", query=str(entry.get("name") or ""))
        await query.message.edit_text(
            format_ystr_test_data_text(entry, show_all=False),
            parse_mode="HTML",
            reply_markup=_build_ystr_test_data_keyboard(entry_index, show_all=False, has_more=marker_count > 37),
        )
        return

    if action.startswith("dataall:"):
        try:
            entry_index = int(action.split(":", 1)[1])
        except (ValueError, TypeError):
            await query.answer("Запись не найдена.", show_alert=True)
            return
        sheets: SheetsClient = context.application.bot_data["sheets"]
        entry = sheets.get_ystr_entry_by_index(entry_index)
        if entry is None:
            await query.answer("Запись не найдена.", show_alert=True)
            return
        await query.message.edit_text(
            format_ystr_test_data_text(entry, show_all=True),
            parse_mode="HTML",
            reply_markup=_build_ystr_test_data_keyboard(entry_index, show_all=True, has_more=False),
        )
        return

    if action.startswith("datamatches:"):
        try:
            entry_index = int(action.split(":", 1)[1])
        except (ValueError, TypeError):
            await query.answer("Запись не найдена.", show_alert=True)
            return
        sheets: SheetsClient = context.application.bot_data["sheets"]
        entry = sheets.get_ystr_entry_by_index(entry_index)
        if entry is None:
            await query.answer("Запись не найдена.", show_alert=True)
            return
        matches = sheets.find_ystr_matches(entry)
        record_ystr_action(context, update, "nearest", query=str(entry.get("name") or ""))
        await query.message.edit_text(
            format_ystr_matches_text(entry, matches),
            parse_mode="HTML",
            reply_markup=_build_ystr_data_matches_keyboard(entry_index),
        )
        return

    if action.startswith("data:"):
        try:
            entry_index = int(action.split(":", 1)[1])
        except (ValueError, TypeError):
            await query.answer("Запись не найдена.", show_alert=True)
            return
        sheets: SheetsClient = context.application.bot_data["sheets"]
        entry = sheets.get_ystr_entry_by_index(entry_index)
        if entry is None:
            await query.answer("Запись не найдена.", show_alert=True)
            return
        marker_count = int(entry.get("marker_count") or 0)
        await query.message.edit_text(
            format_ystr_test_data_text(entry, show_all=False),
            parse_mode="HTML",
            reply_markup=_build_ystr_test_data_keyboard(entry_index, show_all=False, has_more=marker_count > 37),
        )
        return

    if action == "candidates":
        sheets: SheetsClient = context.application.bot_data["sheets"]
        entry_indexes = context.user_data.get("ystr_candidates") or []
        candidates = [
            entry
            for entry_index in entry_indexes
            for entry in [sheets.get_ystr_entry_by_index(int(entry_index))]
            if entry is not None
        ]
        if not candidates:
            await query.answer("Список устарел. Введите фамилию заново.", show_alert=True)
            return
        await query.message.edit_text(
            "Найдено несколько STR-записей. Выберите нужную:",
            reply_markup=_build_ystr_candidates_keyboard(candidates),
        )
        return

    await query.answer("Неизвестное действие.", show_alert=True)
