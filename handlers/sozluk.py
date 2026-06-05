from __future__ import annotations

from typing import Any

from telegram import Update
from telegram.ext import ApplicationHandlerStop, ContextTypes

from features.sozluk import SozlukClient, filter_exact_sozluk_items
from ui.sozluk import build_sozluk_prompt_keyboard, format_sozluk_results, sozluk_prompt_text
from stores.usage import UsageStore


def set_sozluk_pending(context: ContextTypes.DEFAULT_TYPE, chat_id: int, direction: int = 0) -> None:
    context.user_data.pop("sozluk_pending_direction", None)
    context.user_data["sozluk_pending"] = {"chat_id": chat_id, "direction": direction}


def clear_sozluk_pending(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop("sozluk_pending", None)
    context.user_data.pop("sozluk_pending_direction", None)


def pop_sozluk_pending(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> int | None:
    pending = context.user_data.get("sozluk_pending")
    if isinstance(pending, dict):
        if int(pending.get("chat_id") or 0) != chat_id:
            return None
        context.user_data.pop("sozluk_pending", None)
        try:
            return int(pending.get("direction") or 0)
        except (TypeError, ValueError):
            return 0

    if "sozluk_pending_direction" in context.user_data:
        try:
            return int(context.user_data.pop("sozluk_pending_direction", 0) or 0)
        except (TypeError, ValueError):
            return 0
    return None


def should_show_sozluk_prompt_keyboard(update: Update | None) -> bool:
    return update is None or update.effective_chat is None or update.effective_chat.type != "private"


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


async def send_sozluk_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    update: Update | None = None,
    *,
    menu_callback_prefix: str = "menu",
) -> None:
    set_sozluk_pending(context, message.chat_id)
    await _collapse_active_reply_menu(context, message.chat_id)
    reply_markup = build_sozluk_prompt_keyboard(menu_callback_prefix) if should_show_sozluk_prompt_keyboard(update) else None
    sent = await message.reply_text(
        sozluk_prompt_text(),
        parse_mode="HTML",
        reply_markup=reply_markup,
        do_quote=False,
    )
    if reply_markup is not None:
        _remember_active_reply_menu(context, sent.chat_id, sent.message_id)
    if reply_markup is not None and update is not None and update.effective_user is not None:
        _remember_reply_menu_owner(context, sent.chat_id, sent.message_id, update.effective_user.id)


async def open_sozluk_inline_menu(
    message,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    menu_callback_prefix: str = "menu",
    back_action: str = "root",
) -> None:
    set_sozluk_pending(context, message.chat_id)
    await message.edit_text(
        sozluk_prompt_text(),
        parse_mode="HTML",
        reply_markup=build_sozluk_prompt_keyboard(menu_callback_prefix, back_action=back_action),
    )


async def send_sozluk_results(
    message,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    query: str,
    *,
    direction: int = 0,
) -> None:
    sozluk: SozlukClient = context.application.bot_data["sozluk"]
    usage_store: UsageStore = context.application.bot_data["usage_store"]
    query = " ".join(str(query or "").split())
    if len(query) < 2:
        await message.reply_text("Введите минимум 2 символа для поиска.", do_quote=False)
        return
    try:
        items = sozluk.lookup_all(query) if direction == 0 else sozluk.lookup(query, direction)
        items = filter_exact_sozluk_items(query, items)
    except Exception:
        usage_store.record_sozluk(update, query, False)
        await message.reply_text(
            "Не удалось обратиться к словарю. Попробуйте еще раз чуть позже.",
            do_quote=False,
        )
        return

    usage_store.record_sozluk(update, query, bool(items))

    await message.reply_text(
        format_sozluk_results(query, items),
        parse_mode="HTML",
        disable_web_page_preview=True,
        do_quote=False,
    )


async def sozluk_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return

    query = " ".join(context.args).strip() if context.args else ""
    if query:
        await send_sozluk_results(update.message, update, context, query, direction=0)
        return

    await send_sozluk_menu(update.message, context, update)


async def sozluk_pending_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.message.text is None:
        return
    direction = pop_sozluk_pending(context, update.message.chat_id)
    if direction is None:
        return

    await send_sozluk_results(update.message, update, context, update.message.text, direction=direction)
    raise ApplicationHandlerStop
