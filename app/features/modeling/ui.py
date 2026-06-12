from __future__ import annotations

from collections.abc import Callable

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest

from app.features.modeling.navigation import current_callback_context, current_callback_user_id
from app.i18n import t
from app.main_menu import set_active_main_menu_message


MODELING_CALLBACK_PREFIX = "modeling"


def modeling_cb(*parts: object) -> str:
    return ":".join([MODELING_CALLBACK_PREFIX, *(str(part) for part in parts)])


def back_label(lang: str) -> str:
    return "⬅️ Back" if lang == "en" else "⬅️ Назад"


def footer_row(back_callback: str, lang: str = "ru") -> list[InlineKeyboardButton]:
    return [
        InlineKeyboardButton(back_label(lang), callback_data=back_callback),
        InlineKeyboardButton(t("nav.cancel", lang), callback_data="main:cancel"),
    ]


def page_nav_row(page: int, page_count: int, callback_for_page: Callable[[int], str]) -> list[InlineKeyboardButton]:
    row: list[InlineKeyboardButton] = []
    if page > 0:
        row.append(InlineKeyboardButton("◀️ Пред.", callback_data=callback_for_page(page - 1)))
    row.append(InlineKeyboardButton(f"Стр. {page + 1}/{page_count}", callback_data=callback_for_page(page)))
    if page < page_count - 1:
        row.append(InlineKeyboardButton("След. ▶️", callback_data=callback_for_page(page + 1)))
    return row


async def show_message(message, text: str, reply_markup: InlineKeyboardMarkup, *, edit_existing: bool = True) -> None:
    if edit_existing:
        try:
            await message.edit_text(text, reply_markup=reply_markup, parse_mode="HTML")
        except BadRequest as exc:
            error_text = str(exc).lower()
            if "message is not modified" in error_text:
                return
            can_replace = bool(getattr(message, "photo", None)) or "there is no text" in error_text
            if not can_replace:
                raise
            try:
                await message.edit_reply_markup(reply_markup=None)
            except BadRequest:
                pass
            sent = await message.reply_text(text, reply_markup=reply_markup, parse_mode="HTML", do_quote=False)
            context = current_callback_context()
            user_id = current_callback_user_id()
            if context is not None and user_id is not None:
                set_active_main_menu_message(context, sent.chat_id, user_id, sent.message_id)
        return
    await message.reply_text(text, reply_markup=reply_markup, parse_mode="HTML", do_quote=False)
