from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.i18n import get_user_language, t
from app.main_menu import ensure_active_main_menu


def build_stub_keyboard(lang: str = "ru") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[
            InlineKeyboardButton(t("nav.back", lang), callback_data='main:root'),
            InlineKeyboardButton(t("nav.cancel", lang), callback_data='main:cancel'),
        ]]
    )


async def show_stub_section(message, *, text: str, edit_existing: bool = False, lang: str = "ru") -> None:
    markup = build_stub_keyboard(lang)
    if edit_existing:
        await message.edit_text(text, reply_markup=markup)
    else:
        await message.reply_text(text, reply_markup=markup, do_quote=False)


async def handle_stub_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    callback_prefix: str,
    show_menu,
) -> None:
    query = update.callback_query
    if query is None or query.data is None or query.message is None:
        return
    if not query.data.startswith(f'{callback_prefix}:'):
        return

    if not await ensure_active_main_menu(update, context):
        return

    await query.answer()
    action = query.data.split(':', 1)[1]
    if action == 'root':
        user_id = int(update.effective_user.id) if update.effective_user is not None else None
        await show_menu(query.message, edit_existing=True, lang=get_user_language(context, user_id))
