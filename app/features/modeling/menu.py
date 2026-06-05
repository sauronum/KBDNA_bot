from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ApplicationHandlerStop, ContextTypes

from app.features.modeling.navigation import nav_pop, nav_reset, reset_callback_context, set_callback_context
from app.features.modeling.qpadm_classic import (
    qpadm_classic_callback_handler,
    qpadm_classic_text_input_handler,
    show_qpadm_classic_dataset_menu,
)
from app.features.modeling.qpwave import qpwave_callback_handler, qpwave_text_input_handler, show_qpwave_dataset_menu
from app.features.modeling.saved_models import saved_models_callback_handler
from app.features.modeling.source_sets import source_sets_callback_handler, source_sets_text_input_handler
from app.features.modeling.ui import MODELING_CALLBACK_PREFIX, footer_row, show_message
from app.i18n import get_user_language
from app.main_menu import ensure_active_main_menu


def modeling_text(lang: str = "ru") -> str:
    if lang == "en":
        return "<b>🏛 AdmixLab</b>\n\nFormal models."
    return "<b>🏛 AdmixLab</b>\n\nФормальные модели."


def build_modeling_keyboard(lang: str = "ru") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🏛 qpAdm classic", callback_data=f"{MODELING_CALLBACK_PREFIX}:qpadm")],
            [InlineKeyboardButton("🌊 qpWave", callback_data=f"{MODELING_CALLBACK_PREFIX}:qpwave")],
            [InlineKeyboardButton("📚 Source sets", callback_data=f"{MODELING_CALLBACK_PREFIX}:source_sets")],
            [InlineKeyboardButton("💾 Saved models", callback_data=f"{MODELING_CALLBACK_PREFIX}:saved")],
            footer_row("main:root", lang),
        ]
    )


async def show_modeling_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE | None = None,
    *,
    edit_existing: bool = False,
    lang: str = "ru",
):
    nav_reset(context, f"{MODELING_CALLBACK_PREFIX}:root")
    markup = build_modeling_keyboard(lang)
    await show_message(message, modeling_text(lang), markup, edit_existing=edit_existing)
    return message


async def modeling_text_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    for handler in (
        source_sets_text_input_handler,
        qpadm_classic_text_input_handler,
        qpwave_text_input_handler,
    ):
        if await handler(update, context):
            raise ApplicationHandlerStop


async def _dispatch_modeling_action(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    action: str,
    parts: list[str],
    *,
    lang: str,
) -> None:
    query = update.callback_query
    if query is None or query.message is None:
        return

    if action == "root":
        await show_modeling_menu(query.message, context, edit_existing=True, lang=lang)
        return
    if action == "qpadm":
        await show_qpadm_classic_dataset_menu(query.message, context, edit_existing=True, lang=lang)
        return
    if action == "qpwave":
        await show_qpwave_dataset_menu(query.message, context, edit_existing=True, lang=lang)
        return
    if action == "source_sets" or action.startswith("ss_"):
        await source_sets_callback_handler(update, context, action, parts, lang=lang)
        return
    if action == "saved" or action.startswith("saved_"):
        await saved_models_callback_handler(update, context, action, parts, lang=lang)
        return
    if action.startswith("qpadm_"):
        await qpadm_classic_callback_handler(update, context, action, parts, lang=lang)
        return
    if action.startswith("qpwave_"):
        await qpwave_callback_handler(update, context, action, parts, lang=lang)
        return

    await show_modeling_menu(query.message, context, edit_existing=True, lang=lang)


async def modeling_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None or query.message is None:
        return
    if not query.data.startswith(f"{MODELING_CALLBACK_PREFIX}:"):
        return
    if not await ensure_active_main_menu(update, context):
        return

    await query.answer()
    parts = query.data.split(":")
    action = parts[1] if len(parts) > 1 and parts[1] else "root"
    user_id = int(update.effective_user.id) if update.effective_user is not None else None
    lang = get_user_language(context, user_id)

    if action == "nav_back":
        parts = nav_pop(context).split(":")
        action = parts[1] if len(parts) > 1 and parts[1] else "root"

    tokens = set_callback_context(context, user_id)
    try:
        await _dispatch_modeling_action(update, context, action, parts, lang=lang)
    finally:
        reset_callback_context(tokens)
