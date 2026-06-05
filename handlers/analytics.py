from __future__ import annotations

import html
from functools import partial
from io import BytesIO
import logging
from pathlib import Path
from typing import Any

from telegram import InputFile, InputMediaPhoto, Update
from telegram.ext import ContextTypes

from render.analytics import (
    haplo_distribution_caption,
    haplo_png_mode_title,
    haplo_subclade_caption,
    mtdna_distribution_caption,
    render_haplo_distribution_png,
)
from ui.analytics import (
    build_haplo_group_mode_keyboard,
    build_haplo_mode_keyboard,
    build_haplo_navigator_groups_keyboard,
    build_haplo_navigator_names_keyboard,
    build_haplo_navigator_subclades_keyboard,
    build_haplo_root_keyboard,
    build_haplo_subclade_groups_keyboard,
    build_haplo_subclade_mode_keyboard,
    build_mtdna_mode_keyboard,
    build_mtdna_navigator_entries_keyboard,
    build_mtdna_navigator_groups_keyboard,
    build_mtdna_navigator_subclades_keyboard,
    build_mtdna_root_keyboard,
    build_stats_view_keyboard,
    build_untested_surname_groups_keyboard,
    build_untested_surname_view_keyboard,
    build_ydna_diagram_keyboard,
    format_mtdna_entries_text,
    format_subclade_surnames_text,
    format_untested_surname_group,
    untested_surname_count,
)
from ui.common import build_stats_root_keyboard
from clients.search_bases import (
    search_base_caption_label,
    search_base_for_update,
    search_base_png_scope_title,
    sheets_client_for_search_base,
)
from clients.sheets import MtdnaSheetsClient, SheetsClient
from ui.stats import build_stats_detail_text, build_stats_visual_payload
from features.untested_surnames import load_untested_surname_groups
from handlers.sozluk import clear_sozluk_pending
from handlers.ystr import _build_ystr_root_keyboard, clear_ystr_pending, open_ystr_root_inline_menu
from stores.usage import UsageStore


logger = logging.getLogger(__name__)

HAPLO_CALLBACK_PREFIX = "haplo"
MENU_CALLBACK_PREFIX = "menu"
UNTESTED_SURNAMES_PATH = Path("untested_surnames.txt")

ANALYTICS_ROOT_TEXT = (
    "<b>📊 Аналитика</b>\n\n"
    "Статистика базы KBDNA: Y-ДНК, mtDNA, субклады, STR-маркеры и связанные фамилии.\n\n"
    "Выберите раздел."
)
YDNA_TEXT = (
    "<b>🧬 Y-ДНК</b>\n\n"
    "Мужские линии базы: гаплогруппы, субклады, STR-маркеры и роды без ДНК-теста.\n\n"
    "Выберите действие."
)
MTDNA_TEXT = (
    "<b>🧬 mtDNA</b>\n\n"
    "Материнские линии базы: распределение, субклады и записи внутри выбранной линии.\n\n"
    "Выберите действие."
)

_build_haplo_group_mode_keyboard = partial(build_haplo_group_mode_keyboard, HAPLO_CALLBACK_PREFIX)
_build_haplo_navigator_names_keyboard = partial(build_haplo_navigator_names_keyboard, HAPLO_CALLBACK_PREFIX)
_build_haplo_subclade_mode_keyboard = partial(build_haplo_subclade_mode_keyboard, HAPLO_CALLBACK_PREFIX)
_build_haplo_root_keyboard = partial(build_haplo_root_keyboard, HAPLO_CALLBACK_PREFIX, MENU_CALLBACK_PREFIX)
_build_stats_root_keyboard = partial(build_stats_root_keyboard, HAPLO_CALLBACK_PREFIX)
_build_stats_view_keyboard = partial(build_stats_view_keyboard, HAPLO_CALLBACK_PREFIX)
_load_untested_surname_groups = partial(load_untested_surname_groups, UNTESTED_SURNAMES_PATH)
_build_untested_surname_groups_keyboard = partial(build_untested_surname_groups_keyboard, HAPLO_CALLBACK_PREFIX)
_build_untested_surname_view_keyboard = partial(build_untested_surname_view_keyboard, HAPLO_CALLBACK_PREFIX)
_build_haplo_mode_keyboard = partial(build_haplo_mode_keyboard, HAPLO_CALLBACK_PREFIX)
_build_ydna_diagram_keyboard = partial(build_ydna_diagram_keyboard, HAPLO_CALLBACK_PREFIX)
_build_mtdna_root_keyboard = partial(build_mtdna_root_keyboard, HAPLO_CALLBACK_PREFIX)
_build_mtdna_mode_keyboard = partial(build_mtdna_mode_keyboard, HAPLO_CALLBACK_PREFIX)
_build_mtdna_navigator_groups_keyboard = partial(build_mtdna_navigator_groups_keyboard, HAPLO_CALLBACK_PREFIX)
_build_mtdna_navigator_subclades_keyboard = partial(build_mtdna_navigator_subclades_keyboard, HAPLO_CALLBACK_PREFIX)
_build_mtdna_navigator_entries_keyboard = partial(build_mtdna_navigator_entries_keyboard, HAPLO_CALLBACK_PREFIX)
_build_haplo_subclade_groups_keyboard = partial(build_haplo_subclade_groups_keyboard, HAPLO_CALLBACK_PREFIX)
_build_haplo_navigator_groups_keyboard = partial(build_haplo_navigator_groups_keyboard, HAPLO_CALLBACK_PREFIX)
_build_haplo_navigator_subclades_keyboard = partial(build_haplo_navigator_subclades_keyboard, HAPLO_CALLBACK_PREFIX)


def _get_haplo_menu_state(context: ContextTypes.DEFAULT_TYPE, message_id: int) -> dict[str, object]:
    state_map = context.user_data.setdefault("haplo_menu_state", {})
    return state_map.setdefault(message_id, {})


def _clear_haplo_menu_state(context: ContextTypes.DEFAULT_TYPE, message_id: int) -> None:
    state_map = context.user_data.get("haplo_menu_state", {})
    if not isinstance(state_map, dict):
        return
    state_map.pop(message_id, None)
    if not state_map:
        context.user_data.pop("haplo_menu_state", None)


def _move_haplo_menu_state(context: ContextTypes.DEFAULT_TYPE, old_message_id: int, new_message_id: int) -> dict[str, object]:
    state_map = context.user_data.setdefault("haplo_menu_state", {})
    if not isinstance(state_map, dict):
        context.user_data["haplo_menu_state"] = {}
        state_map = context.user_data["haplo_menu_state"]
    state = state_map.pop(old_message_id, {})
    if not isinstance(state, dict):
        state = {}
    state_map[new_message_id] = state
    return state


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


async def _activate_reply_menu(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int) -> bool:
    hook = _reply_menu_hooks(context).get("activate_reply_menu")
    if hook is None:
        return True
    return bool(await hook(context, chat_id, message_id))


def _forget_active_reply_menu(context: ContextTypes.DEFAULT_TYPE, chat_id: int, *, message_id: int | None = None) -> None:
    hook = _reply_menu_hooks(context).get("forget_active_reply_menu")
    if hook is not None:
        hook(context, chat_id, message_id=message_id)


def _message_has_media(message: object) -> bool:
    return bool(
        getattr(message, "photo", None)
        or getattr(message, "document", None)
        or getattr(message, "video", None)
        or getattr(message, "animation", None)
    )


async def _delete_message_quietly(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int) -> None:
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        logger.debug("Failed to delete analytics message", exc_info=True)


def _remember_analytics_message(context: ContextTypes.DEFAULT_TYPE, update: Update, chat_id: int, message_id: int) -> None:
    _remember_active_reply_menu(context, chat_id, message_id)
    if update.effective_user is not None:
        _remember_reply_menu_owner(context, chat_id, message_id, update.effective_user.id)


async def _show_text_screen(
    query,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    *,
    reply_markup=None,
    parse_mode: str | None = None,
    disable_web_page_preview: bool | None = None,
) -> object:
    message = query.message
    chat_id = message.chat_id
    old_message_id = message.message_id
    if _message_has_media(message):
        sent = await context.bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
            disable_web_page_preview=disable_web_page_preview,
        )
        _move_haplo_menu_state(context, old_message_id, sent.message_id)
        _forget_active_reply_menu(context, chat_id, message_id=old_message_id)
        _remember_analytics_message(context, update, sent.chat_id, sent.message_id)
        await _delete_message_quietly(context, chat_id, old_message_id)
        return sent

    await query.edit_message_text(
        text,
        parse_mode=parse_mode,
        reply_markup=reply_markup,
        disable_web_page_preview=disable_web_page_preview,
    )
    _remember_analytics_message(context, update, chat_id, old_message_id)
    return message


async def _show_photo_screen(
    query,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    png_bytes: bytes,
    filename: str,
    caption: str,
    reply_markup,
) -> object:
    message = query.message
    chat_id = message.chat_id
    old_message_id = message.message_id
    if getattr(message, "photo", None):
        await query.edit_message_media(
            media=InputMediaPhoto(media=InputFile(BytesIO(png_bytes), filename=filename), caption=caption),
            reply_markup=reply_markup,
        )
        _remember_analytics_message(context, update, chat_id, old_message_id)
        return message

    sent = await context.bot.send_photo(
        chat_id=chat_id,
        photo=InputFile(BytesIO(png_bytes), filename=filename),
        caption=caption,
        reply_markup=reply_markup,
    )
    _move_haplo_menu_state(context, old_message_id, sent.message_id)
    _forget_active_reply_menu(context, chat_id, message_id=old_message_id)
    _remember_analytics_message(context, update, sent.chat_id, sent.message_id)
    await _delete_message_quietly(context, chat_id, old_message_id)
    return sent


def _is_lookup_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    access_store = context.application.bot_data["g25_access_store"]
    return bool(access_store.is_admin(update))


async def haplo_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return

    await send_haplo_root_message(update.message, update, context)


async def send_haplo_root_message(
    message,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    edit_existing: bool = False,
    include_back: bool = False,
) -> None:
    usage_store: UsageStore = context.application.bot_data["usage_store"]
    usage_store.record_analytics(update, "root")
    text = ANALYTICS_ROOT_TEXT
    reply_markup = _build_haplo_root_keyboard(include_back=include_back)
    if edit_existing:
        await message.edit_text(text, parse_mode="HTML", reply_markup=reply_markup)
        _remember_active_reply_menu(context, message.chat_id, message.message_id)
        if update.effective_user is not None:
            _remember_reply_menu_owner(context, message.chat_id, message.message_id, update.effective_user.id)
    else:
        await _collapse_active_reply_menu(context, message.chat_id)
        sent = await message.reply_text(
            text,
            parse_mode="HTML",
            reply_markup=reply_markup,
            do_quote=False,
        )
        _remember_active_reply_menu(context, sent.chat_id, sent.message_id)
        if update.effective_user is not None:
            _remember_reply_menu_owner(context, sent.chat_id, sent.message_id, update.effective_user.id)


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return

    await send_stats_root_message(update.message, update, context)


async def g25stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return

    access_store = context.application.bot_data["g25_access_store"]
    if not access_store.is_admin(update):
        await update.message.reply_text("Команда доступна только администратору G25.", do_quote=False)
        return

    await send_stats_detail_messages(
        update.message.chat_id,
        update,
        context,
        stats_kind="g25",
    )


async def _send_stats_root_messages(
    chat_id: int,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> tuple[object, object]:
    usage_store: UsageStore = context.application.bot_data["usage_store"]
    png_bytes, filename = build_stats_visual_payload(usage_store)

    stats_message = await context.bot.send_photo(
        chat_id=chat_id,
        photo=InputFile(BytesIO(png_bytes), filename=filename),
        reply_markup=_build_stats_root_keyboard(),
    )

    _remember_active_reply_menu(context, stats_message.chat_id, stats_message.message_id)
    if update.effective_user is not None:
        _remember_reply_menu_owner(context, stats_message.chat_id, stats_message.message_id, update.effective_user.id)
    _get_haplo_menu_state(context, stats_message.message_id)
    return None, stats_message


async def send_stats_root_message(message, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_lookup_admin(update, context):
        await message.reply_text("Раздел доступен только ограниченному кругу пользователей.", do_quote=False)
        return

    await _collapse_active_reply_menu(context, message.chat_id)
    await _send_stats_root_messages(message.chat_id, update, context)


async def send_stats_detail_messages(
    chat_id: int,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    stats_kind: str,
    reply_markup=None,
) -> tuple[object, object]:
    usage_store: UsageStore = context.application.bot_data["usage_store"]
    is_private = update.effective_chat is not None and update.effective_chat.type == "private"
    text = build_stats_detail_text(usage_store, stats_kind, is_private=is_private)
    text_message = await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode="HTML",
        reply_markup=reply_markup,
    )
    return None, text_message


async def _delete_stats_chart_message(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    state: dict[str, object],
) -> None:
    chart_message_id = state.pop("stats_chart_message_id", None)
    if not chart_message_id:
        return
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=int(chart_message_id))
    except Exception:
        logger.debug("Failed to delete stats chart message", exc_info=True)


async def _open_stats_detail_from_menu(
    query,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    stats_kind: str,
) -> None:
    await _delete_stats_chart_message(context, query.message.chat_id, _get_haplo_menu_state(context, query.message.message_id))
    _, text_message = await send_stats_detail_messages(
        query.message.chat_id,
        update,
        context,
        stats_kind=stats_kind,
        reply_markup=_build_stats_view_keyboard(),
    )
    _clear_haplo_menu_state(context, query.message.message_id)
    _forget_active_reply_menu(context, query.message.chat_id, message_id=query.message.message_id)
    try:
        await query.message.delete()
    except Exception:
        logger.debug("Failed to delete stats root message", exc_info=True)

    _remember_active_reply_menu(context, text_message.chat_id, text_message.message_id)
    if update.effective_user is not None:
        _remember_reply_menu_owner(context, text_message.chat_id, text_message.message_id, update.effective_user.id)


async def haplo_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.message is None:
        return

    try:
        _, action = (query.data or "").split(":", 1)
    except (ValueError, TypeError):
        await query.answer("Неизвестное действие.", show_alert=True)
        return

    message_id = query.message.message_id
    state = _get_haplo_menu_state(context, message_id)
    search_base = search_base_for_update(update, context)
    sheets: SheetsClient = sheets_client_for_search_base(context, search_base)
    ydna_scope = search_base_png_scope_title(search_base)
    ydna_caption_scope = search_base_caption_label(search_base)
    mtdna_sheets: MtdnaSheetsClient | None = context.application.bot_data.get("mtdna_sheets")
    if not await _activate_reply_menu(context, query.message.chat_id, message_id):
        await query.answer("Это старое меню. Используйте последнее.")
        return

    if action == "root":
        await query.answer()
        _clear_haplo_menu_state(context, message_id)
        _get_haplo_menu_state(context, message_id)
        await _show_text_screen(
            query,
            update,
            context,
            ANALYTICS_ROOT_TEXT,
            parse_mode="HTML",
            reply_markup=_build_haplo_root_keyboard(include_back=True),
        )
        return

    if action == "statsroot":
        if not _is_lookup_admin(update, context):
            await query.answer("Нет доступа.", show_alert=True)
            return
        await query.answer()
        await _delete_stats_chart_message(context, query.message.chat_id, state)
        _clear_haplo_menu_state(context, message_id)
        _forget_active_reply_menu(context, query.message.chat_id, message_id=query.message.message_id)
        try:
            await query.message.delete()
        except Exception:
            logger.debug("Failed to delete stats detail message", exc_info=True)
        await _send_stats_root_messages(query.message.chat_id, update, context)
        return

    if action == "cancel":
        await query.answer()
        await _delete_stats_chart_message(context, query.message.chat_id, state)
        _clear_haplo_menu_state(context, message_id)
        _forget_active_reply_menu(context, query.message.chat_id, message_id=query.message.message_id)
        await query.message.delete()
        return

    if action == "groups":
        await query.answer()
        await _show_text_screen(
            query,
            update,
            context,
            ANALYTICS_ROOT_TEXT,
            parse_mode="HTML",
            reply_markup=_build_haplo_root_keyboard(include_back=True),
        )
        return

    if action == "ydna":
        await query.answer()
        await _show_text_screen(
            query,
            update,
            context,
            YDNA_TEXT,
            parse_mode="HTML",
            reply_markup=_build_haplo_mode_keyboard(),
        )
        return

    if action == "ydna_diagrams":
        await query.answer()
        await _show_text_screen(
            query,
            update,
            context,
            YDNA_TEXT,
            parse_mode="HTML",
            reply_markup=_build_haplo_mode_keyboard(),
        )
        return

    if action == "ystr":
        await query.answer()
        if _message_has_media(query.message):
            clear_ystr_pending(context)
            clear_sozluk_pending(context)
            back_callback = f"{HAPLO_CALLBACK_PREFIX}:ydna"
            context.user_data["ystr_root_back_callback"] = back_callback
            await _show_text_screen(
                query,
                update,
                context,
                "🧬 <b>Y-STR анализ</b>\n\nВыберите режим:",
                parse_mode="HTML",
                reply_markup=_build_ystr_root_keyboard(back_callback),
            )
            return
        await open_ystr_root_inline_menu(
            query.message,
            context,
            back_callback=f"{HAPLO_CALLBACK_PREFIX}:ydna",
        )
        return

    if action == "untested":
        groups = _load_untested_surname_groups()
        if not any(untested_surname_count(group) for group in groups):
            await query.answer("Список непротестированных родов пока недоступен.", show_alert=True)
            return
        await query.answer()
        await _show_text_screen(
            query,
            update,
            context,
            "<b>Y-ДНК · Непротестированные роды</b>\n\n"
            "Роды без Y-ДНК теста в базе KBDNA.\n\n"
            "Выберите группу:",
            parse_mode="HTML",
            reply_markup=_build_untested_surname_groups_keyboard(groups),
        )
        return

    if action.startswith("untested:"):
        groups = _load_untested_surname_groups()
        try:
            group_index = int(action.split(":", 1)[1])
            group = groups[group_index]
        except (ValueError, IndexError, TypeError):
            await query.answer("Список устарел. Откройте раздел заново.", show_alert=True)
            return
        await query.answer()
        await _show_text_screen(
            query,
            update,
            context,
            format_untested_surname_group(group),
            parse_mode="HTML",
            reply_markup=_build_untested_surname_view_keyboard(),
        )
        return

    if action == "mtdna":
        await query.answer()
        await _show_text_screen(
            query,
            update,
            context,
            MTDNA_TEXT,
            parse_mode="HTML",
            reply_markup=_build_mtdna_root_keyboard(),
        )
        return

    if action == "mtdna_diagrams":
        await query.answer()
        await _show_text_screen(
            query,
            update,
            context,
            MTDNA_TEXT,
            parse_mode="HTML",
            reply_markup=_build_mtdna_root_keyboard(),
        )
        return

    if action == "groupmodes":
        await query.answer()
        await _show_text_screen(
            query,
            update,
            context,
            "<b>📊 Гаплогруппы Y-ДНК</b>\n\nВыберите режим распределения.",
            parse_mode="HTML",
            reply_markup=_build_haplo_group_mode_keyboard(),
        )
        return

    if action in {"requests", "stats_lookup"}:
        if not _is_lookup_admin(update, context):
            await query.answer("Нет доступа.", show_alert=True)
            return
        await query.answer()
        await _open_stats_detail_from_menu(query, update, context, stats_kind="lookup")
        return

    if action in {"stats_analytics", "stats_dna_lab", "stats_sozluk", "stats_ystr"}:
        await query.answer("Этот раздел убран из глубокой статистики.", show_alert=True)
        return

    if action == "stats_quality":
        if not _is_lookup_admin(update, context):
            await query.answer("Нет доступа.", show_alert=True)
            return
        await query.answer()
        await _open_stats_detail_from_menu(query, update, context, stats_kind="quality")
        return

    if action == "navigator":
        groups = sheets.get_navigation_groups()
        state["nav_groups"] = groups
        state.pop("nav_group_index", None)
        state.pop("nav_group_label", None)
        state.pop("nav_subclades", None)
        usage_store: UsageStore = context.application.bot_data["usage_store"]
        usage_store.record_analytics(update, "navigator")
        await query.answer()
        await _show_text_screen(
            query,
            update,
            context,
            f"<b>🧭 Навигатор Y-ДНК</b>\n\n{html.escape(ydna_caption_scope)}\n\nВыберите гаплогруппу:",
            parse_mode="HTML",
            reply_markup=_build_haplo_navigator_groups_keyboard(groups),
        )
        return

    if action == "subclades":
        groups = sheets.get_available_haplogroups()
        state["sub_groups"] = groups
        await query.answer()
        await _show_text_screen(
            query,
            update,
            context,
            f"<b>🧬 Субклады Y-ДНК</b>\n\n{html.escape(ydna_caption_scope)}\n\nВыберите гаплогруппу:",
            parse_mode="HTML",
            reply_markup=_build_haplo_subclade_groups_keyboard(groups),
        )
        return

    if action in {"mtdna_groups", "mtdna_subclades"}:
        if mtdna_sheets is None:
            await query.answer("Таблица МтДНК пока недоступна.", show_alert=True)
            return

        kind = "groups" if action == "mtdna_groups" else "subclades"
        usage_store: UsageStore = context.application.bot_data["usage_store"]
        usage_store.record_analytics(update, action)
        try:
            payload = mtdna_sheets.get_distribution(kind)
        except Exception:
            logger.exception("mtDNA distribution failed")
            await query.answer("Не удалось прочитать таблицу МтДНК.", show_alert=True)
            return

        items = payload["items"]
        total = int(payload["total"])
        if not items or total <= 0:
            await query.answer("Нет данных по МтДНК.", show_alert=True)
            return

        title = "MTDNA HAPLOGROUPS" if kind == "groups" else "MTDNA SUBCLADES"
        png_bytes = render_haplo_distribution_png(
            items,
            total,
            "tests",
            title=title,
            subtitle="BY SAMPLES",
        )
        filename = f"mtdna_{kind}.png"
        caption = mtdna_distribution_caption(kind, total)

        await query.answer()
        await _show_photo_screen(
            query,
            update,
            context,
            png_bytes=png_bytes,
            filename=filename,
            caption=caption,
            reply_markup=_build_mtdna_mode_keyboard(kind),
        )
        return

    if action == "mtdna_navigator":
        if mtdna_sheets is None:
            await query.answer("Таблица МтДНК пока недоступна.", show_alert=True)
            return

        try:
            groups = mtdna_sheets.get_navigation_groups()
        except Exception:
            logger.exception("mtDNA navigator groups failed")
            await query.answer("Не удалось прочитать таблицу МтДНК.", show_alert=True)
            return
        if not groups:
            await query.answer("Нет данных по МтДНК.", show_alert=True)
            return

        state["mtdna_nav_groups"] = groups
        state.pop("mtdna_nav_group_index", None)
        state.pop("mtdna_nav_group_label", None)
        state.pop("mtdna_nav_subclades", None)
        usage_store: UsageStore = context.application.bot_data["usage_store"]
        usage_store.record_analytics(update, "mtdna_navigator")
        await query.answer()
        await _show_text_screen(
            query,
            update,
            context,
            "<b>🧭 Навигатор mtDNA</b>\n\nВыберите основную mtDNA-группу:",
            parse_mode="HTML",
            reply_markup=_build_mtdna_navigator_groups_keyboard(groups),
        )
        return

    if action.startswith("mtnavg:"):
        if mtdna_sheets is None:
            await query.answer("Таблица МтДНК пока недоступна.", show_alert=True)
            return
        try:
            group_index = int(action.split(":", 1)[1])
            groups = state.get("mtdna_nav_groups") or []
            selected_group = groups[group_index]
        except (ValueError, IndexError, TypeError):
            await query.answer("Список устарел. Откройте заново.", show_alert=True)
            return

        group_label = str(selected_group["label"])
        try:
            subclades = mtdna_sheets.get_navigation_subclades(group_label)
        except Exception:
            logger.exception("mtDNA navigator subclades failed")
            await query.answer("Не удалось прочитать таблицу МтДНК.", show_alert=True)
            return
        if not subclades:
            await query.answer("Нет субкладов для этой mtDNA-группы.", show_alert=True)
            return

        state["mtdna_nav_group_index"] = group_index
        state["mtdna_nav_group_label"] = group_label
        state["mtdna_nav_subclades"] = subclades
        usage_store: UsageStore = context.application.bot_data["usage_store"]
        usage_store.record_analytics(update, "mtdna_nav_group")
        description = str(selected_group.get("description") or "")
        text = f"МтДНК · Навигатор\n\n<b>{html.escape(group_label)}</b>"
        if description:
            text += f"\n\n{html.escape(description)}"
        text += "\n\nВыберите субклад:"
        await query.answer()
        await _show_text_screen(
            query,
            update,
            context,
            text,
            parse_mode="HTML",
            reply_markup=_build_mtdna_navigator_subclades_keyboard(subclades),
        )
        return

    if action.startswith("mtnavs:"):
        if mtdna_sheets is None:
            await query.answer("Таблица МтДНК пока недоступна.", show_alert=True)
            return
        try:
            sub_index = int(action.split(":", 1)[1])
            subclades = state.get("mtdna_nav_subclades") or []
            subclade_item = subclades[sub_index]
            group_label = str(state["mtdna_nav_group_label"])
            group_index = int(state["mtdna_nav_group_index"])
        except (ValueError, IndexError, KeyError, TypeError):
            await query.answer("Список устарел. Откройте заново.", show_alert=True)
            return

        subclade_label = str(subclade_item["label"])
        try:
            entries = mtdna_sheets.get_entries_in_subclade(group_label, subclade_label)
        except Exception:
            logger.exception("mtDNA navigator entries failed")
            await query.answer("Не удалось прочитать таблицу МтДНК.", show_alert=True)
            return

        usage_store: UsageStore = context.application.bot_data["usage_store"]
        usage_store.record_analytics(update, "mtdna_nav_subclade")
        await query.answer()
        await _show_text_screen(
            query,
            update,
            context,
            format_mtdna_entries_text(group_label, subclade_label, entries),
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=_build_mtdna_navigator_entries_keyboard(group_index),
        )
        return

    if action.startswith("navg:"):
        try:
            group_index = int(action.split(":", 1)[1])
            groups = state.get("nav_groups") or []
            selected_group = groups[group_index]
        except (ValueError, IndexError, TypeError):
            await query.answer("Список устарел. Откройте заново.", show_alert=True)
            return

        group_label = str(selected_group["label"])
        subclades = sheets.get_navigation_subclades(group_label)
        state["nav_group_index"] = group_index
        state["nav_group_label"] = group_label
        state["nav_subclades"] = subclades
        usage_store: UsageStore = context.application.bot_data["usage_store"]
        usage_store.record_analytics(update, "nav_group")
        await query.answer()
        await _show_text_screen(
            query,
            update,
            context,
            f"<b>🧭 Навигатор</b>\n\n{html.escape(group_label)}\n\nВыберите субклад:",
            parse_mode="HTML",
            reply_markup=_build_haplo_navigator_subclades_keyboard(subclades),
        )
        return

    if action.startswith("navs:"):
        try:
            sub_index = int(action.split(":", 1)[1])
            subclades = state.get("nav_subclades") or []
            subclade_item = subclades[sub_index]
            group_label = str(state["nav_group_label"])
            group_index = int(state["nav_group_index"])
        except (ValueError, IndexError, KeyError, TypeError):
            await query.answer("Список устарел. Откройте заново.", show_alert=True)
            return

        subclade_label = str(subclade_item["label"])
        names = sheets.get_surnames_in_subclade(group_label, subclade_label)
        usage_store: UsageStore = context.application.bot_data["usage_store"]
        usage_store.record_analytics(update, "nav_subclade")
        await query.answer()
        await _show_text_screen(
            query,
            update,
            context,
            format_subclade_surnames_text(group_label, subclade_label, names),
            parse_mode="HTML",
            reply_markup=_build_haplo_navigator_names_keyboard(group_index),
        )
        return

    if action.startswith("subg:"):
        try:
            group_index = int(action.split(":", 1)[1])
            groups = state.get("sub_groups") or []
            group_label = groups[group_index]
        except (ValueError, IndexError, TypeError):
            await query.answer("Список устарел. Откройте заново.", show_alert=True)
            return

        state["sub_group_index"] = group_index
        state["sub_group_label"] = group_label
        usage_store: UsageStore = context.application.bot_data["usage_store"]
        usage_store.record_analytics(update, f"subclade_group:{group_label}")
        await query.answer()
        await _show_text_screen(
            query,
            update,
            context,
            f"<b>🧬 Субклады {html.escape(group_label)}</b>\n\nВыберите режим распределения.",
            parse_mode="HTML",
            reply_markup=_build_haplo_subclade_mode_keyboard(group_index),
        )
        return

    if action in {"families", "tests"}:
        usage_store: UsageStore = context.application.bot_data["usage_store"]
        usage_store.record_analytics(update, f"haplo_{action}")
        payload = sheets.get_haplogroup_distribution(action)
        items = payload["items"]
        total = int(payload["total"])
        if not items or total <= 0:
            await query.answer("Нет данных для статистики.", show_alert=True)
            return

        png_bytes = render_haplo_distribution_png(items, total, action, scope=ydna_scope)
        filename = f"haplogroups_{action}.png"
        caption = haplo_distribution_caption(action, total, scope_label=ydna_caption_scope)

        await query.answer()
        await _show_photo_screen(
            query,
            update,
            context,
            png_bytes=png_bytes,
            filename=filename,
            caption=caption,
            reply_markup=_build_haplo_group_mode_keyboard(action),
        )
        return

    if action.startswith("subf:") or action.startswith("subt:"):
        try:
            group_index = int(action.rsplit(":", 1)[1])
            groups = state.get("sub_groups") or []
            group_label = groups[group_index]
        except (ValueError, IndexError, TypeError):
            await query.answer("Список устарел. Откройте заново.", show_alert=True)
            return

        mode = "families" if action.startswith("subf:") else "tests"
        payload = sheets.get_subclade_distribution(group_label, mode)
        items = payload["items"]
        total = int(payload["total"])
        if not items or total <= 0:
            await query.answer("Нет данных по субкладам.", show_alert=True)
            return

        png_bytes = render_haplo_distribution_png(
            items,
            total,
            mode,
            title=f"SUBCLADES {group_label}",
            subtitle=haplo_png_mode_title(mode),
            scope=ydna_scope,
        )
        filename = f"subclades_{group_label}_{mode}.png".replace("/", "_")
        caption = haplo_subclade_caption(group_label, mode, total, scope_label=ydna_caption_scope)

        await query.answer()
        await _show_photo_screen(
            query,
            update,
            context,
            png_bytes=png_bytes,
            filename=filename,
            caption=caption,
            reply_markup=_build_haplo_subclade_mode_keyboard(group_index, mode),
        )
        return

    await query.answer("Неизвестное действие.", show_alert=True)
