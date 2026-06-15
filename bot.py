# -*- coding: utf-8 -*-
from __future__ import annotations

from functools import partial
import logging
import os
import re
from pathlib import Path
from types import SimpleNamespace

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, ApplicationHandlerStop, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters
from handlers.analytics import (
    g25stats_command,
    haplo_callback_handler,
    haplo_command,
    send_haplo_root_message as _send_haplo_root_message,
    stats_command,
)
from ui.common import (
    BOTTOM_BUTTON_BACK,
    BOTTOM_BUTTON_CANCEL,
    BOTTOM_BUTTON_DNA_LAB,
    BOTTOM_BUTTON_GET_G25,
    BOTTOM_BUTTON_HELP,
    BOTTOM_BUTTON_COORDINATE_SPACES,
    BOTTOM_BUTTON_LAB,
    BOTTOM_BUTTON_LOOKUP,
    BOTTOM_BUTTON_MATCHING,
    BOTTOM_BUTTON_MORE,
    BOTTOM_BUTTON_MODELING,
    BOTTOM_BUTTON_MY_DNA,
    BOTTOM_BUTTON_SETTINGS,
    BOTTOM_BUTTON_SOZLUK,
    BOTTOM_BUTTON_STATS,
    BOTTOM_BUTTON_SUPPORT,
    BOTTOM_BUTTON_TRAITS,
    BOTTOM_BUTTON_VAHADUO,
    BOTTOM_BUTTON_YSTR,
    HELP_ROOT_TEXT,
    MORE_BUTTON_ADMIXTURE,
    MORE_BUTTON_HAPLOGROUPS,
    build_bottom_menu_keyboard as build_bottom_menu_keyboard_ui,
    build_group_sections_keyboard as build_group_sections_keyboard_ui,
    build_help_keyboard as build_help_keyboard_ui,
    build_help_section_keyboard as build_help_section_keyboard_ui,
    build_help_inline_keyboard as build_help_inline_keyboard_ui,
    build_laboratory_inline_keyboard as build_laboratory_inline_keyboard_ui,
    build_lookup_start_text,
    build_my_dna_inline_keyboard as build_my_dna_inline_keyboard_ui,
    build_stats_root_keyboard as build_stats_root_keyboard_ui,
    help_section_text,
)
from clients.sheets import MtdnaSheetsClient, SheetsClient
from handlers.lookup import (
    find_command,
    lookup_suggestion_callback_handler,
    text_lookup_command,
)
from features.sozluk import SozlukClient
from handlers.sozluk import (
    clear_sozluk_pending as _clear_sozluk_pending,
    open_sozluk_inline_menu as _open_sozluk_inline_menu,
    send_sozluk_menu as _send_sozluk_menu,
    sozluk_command,
    sozluk_pending_text_handler,
)
from stores.usage import UsageStore
from stores.vahaduo import G25AccessStore
from handlers.ystr import (
    clear_ystr_pending as _clear_ystr_pending,
    open_ystr_root_inline_menu as _open_ystr_root_inline_menu,
    send_ystr_root_message as _send_ystr_root_message,
    ystr_callback_handler,
    ystr_document_input_handler,
    ystr_pending_text_handler,
)
from app.features.admixture.menu import (
    ADMIXTURE_CALLBACK_PREFIX as DNA_LAB_ADMIXTURE_CALLBACK_PREFIX,
    admixture_callback_handler as dna_lab_admixture_callback_handler,
    register_admixture_services as register_dna_lab_admixture_services,
    show_admixture_menu as show_dna_lab_admixture_menu,
)
from app.features.coordinate_space.menu import (
    COORDINATE_SPACE_CALLBACK_PREFIX as DNA_LAB_COORDINATE_SPACE_CALLBACK_PREFIX,
    coordinate_space_callback_handler as dna_lab_coordinate_space_callback_handler,
    show_coordinate_space_menu as show_dna_lab_coordinate_space_menu,
)
from app.features.haplogroups.menu import (
    HAPLOGROUPS_CALLBACK_PREFIX as DNA_LAB_HAPLOGROUPS_CALLBACK_PREFIX,
    haplogroups_callback_handler as dna_lab_haplogroups_callback_handler,
    haplogroups_document_input_handler as dna_lab_haplogroups_document_input_handler,
    haplogroups_text_input_handler as dna_lab_haplogroups_text_input_handler,
    register_haplogroup_services as register_dna_lab_haplogroup_services,
    show_haplogroups_menu as show_dna_lab_haplogroups_menu,
)
from app.features.matching.menu import (
    MATCHING_CALLBACK_PREFIX as DNA_LAB_MATCHING_CALLBACK_PREFIX,
    matching_callback_handler as dna_lab_matching_callback_handler,
    matching_text_input_handler as dna_lab_matching_text_input_handler,
    register_matching_services as register_dna_lab_matching_services,
    show_matching_menu as show_dna_lab_matching_menu,
)
from app.features.modeling.menu import (
    MODELING_CALLBACK_PREFIX as DNA_LAB_MODELING_CALLBACK_PREFIX,
    modeling_callback_handler as dna_lab_modeling_callback_handler,
    modeling_text_input_handler as dna_lab_modeling_text_input_handler,
    show_modeling_menu as show_dna_lab_modeling_menu,
)
from app.features.my_data.menu import (
    MY_DATA_CALLBACK_PREFIX as DNA_LAB_MY_DATA_CALLBACK_PREFIX,
    my_data_callback_handler as dna_lab_my_data_callback_handler,
    my_data_document_input_handler as dna_lab_my_data_document_input_handler,
    my_data_text_input_handler as dna_lab_my_data_text_input_handler,
    open_quick_g25_prompt as open_dna_lab_quick_g25_prompt,
    register_my_data_services as register_dna_lab_my_data_services,
    show_my_data_menu as show_dna_lab_my_data_menu,
    show_sample_reports_menu as show_dna_lab_sample_reports_menu,
    show_view_coordinates_menu as show_dna_lab_view_coordinates_menu,
    show_view_samples_menu as show_dna_lab_view_samples_menu,
)
from app.features.reports.menu import (
    REPORTS_CALLBACK_PREFIX as DNA_LAB_REPORTS_CALLBACK_PREFIX,
    reports_callback_handler as dna_lab_reports_callback_handler,
    show_reports_menu as show_dna_lab_reports_menu,
)
from app.features.settings.menu import (
    SETTINGS_CALLBACK_PREFIX as DNA_LAB_SETTINGS_CALLBACK_PREFIX,
    build_card_format_keyboard as build_global_card_format_keyboard,
    build_language_keyboard as build_global_language_keyboard,
    build_notifications_keyboard as build_global_notifications_keyboard,
    build_privacy_keyboard as build_global_privacy_keyboard,
    build_privacy_placeholder_keyboard as build_global_privacy_placeholder_keyboard,
    build_result_mode_keyboard as build_global_result_mode_keyboard,
    build_search_base_keyboard as build_global_search_base_keyboard,
    build_settings_keyboard as build_global_settings_keyboard,
    card_format_text as global_card_format_text,
    get_user_card_format as get_global_user_card_format,
    get_user_notifications_enabled as get_global_user_notifications_enabled,
    get_user_result_mode as get_global_user_result_mode,
    get_user_search_base as get_global_user_search_base,
    language_text as global_language_text,
    notifications_text as global_notifications_text,
    privacy_data_summary as global_privacy_data_summary,
    privacy_placeholder_text as global_privacy_placeholder_text,
    privacy_text as global_privacy_text,
    register_settings_services as register_dna_lab_settings_services,
    result_mode_text as global_result_mode_text,
    search_base_text as global_search_base_text,
    set_user_card_format as set_global_user_card_format,
    set_user_language as set_global_user_language,
    set_user_notifications_enabled as set_global_user_notifications_enabled,
    set_user_result_mode as set_global_user_result_mode,
    set_user_search_base as set_global_user_search_base,
    show_privacy_delete_confirm as show_global_privacy_delete_confirm,
    show_privacy_delete_done as show_global_privacy_delete_done,
    show_privacy_export_menu as show_global_privacy_export_menu,
    show_privacy_export_result as show_global_privacy_export_result,
    settings_callback_handler as dna_lab_settings_callback_handler,
    settings_text as global_settings_text,
)
from app.features.settings.storage import (
    SEARCH_BASE_ABAZA,
    SEARCH_BASE_ABKHAZ,
    SEARCH_BASE_ADYGHE,
    SEARCH_BASE_KBDNA,
)
from app.features.snp_report.menu import (
    SNP_REPORT_CALLBACK_PREFIX as DNA_LAB_SNP_REPORT_CALLBACK_PREFIX,
    register_snp_report_services as register_dna_lab_snp_report_services,
    show_snp_report_menu as show_dna_lab_snp_report_menu,
    snp_report_callback_handler as dna_lab_snp_report_callback_handler,
    snp_report_text_input_handler as dna_lab_snp_report_text_input_handler,
)
from app.features.traits.menu import (
    TRAITS_CALLBACK_PREFIX as DNA_LAB_TRAITS_CALLBACK_PREFIX,
    register_traits_services as register_dna_lab_traits_services,
    show_traits_root_menu as show_dna_lab_traits_root_menu,
    traits_callback_handler as dna_lab_traits_callback_handler,
)
from app.features.vahaduo.menu import (
    VAHADUO_CALLBACK_PREFIX as DNA_LAB_VAHADUO_CALLBACK_PREFIX,
    register_vahaduo_services as register_dna_lab_vahaduo_services,
    show_vahaduo_menu as show_dna_lab_vahaduo_menu,
    vahaduo_callback_handler as dna_lab_vahaduo_callback_handler,
    vahaduo_document_input_handler as dna_lab_vahaduo_document_input_handler,
    vahaduo_text_input_handler as dna_lab_vahaduo_text_input_handler,
)
from app.i18n import get_user_language as get_dna_lab_user_language
from app.main_menu import (
    G25_COORDINATES_REPLY_BUTTON_TEXT,
    MAIN_CALLBACK_PREFIX as DNA_LAB_MAIN_CALLBACK_PREFIX,
    set_active_main_menu_message as set_active_dna_lab_menu_message,
)

BUILD_ID = "build-2026-04-09-1950"
USAGE_DB_PATH = Path("usage_stats.sqlite3")
G25_ACCESS_PATH = Path("g25_access.json")
DEFAULT_MTDNA_SPREADSHEET_ID = "1Vdh5RB7X2LBLNZnO6L61VHWmaK_puP8C2hVxKlO6abE"
DEFAULT_ADYGHE_ABKHAZ_SPREADSHEET_ID = "1on2rH1tsd8I2RebbWbqRct9qzbYKEC0hH0nZ0RLGbY0"
DEFAULT_ADYGHE_ABKHAZ_WORKSHEET = "Haplotypes"
SOZLUK_COMMAND = "sozluk"
SOZLUK_SHORT_COMMAND = "s"
YSTR_CALLBACK_PREFIX = "ystr"
MENU_CALLBACK_PREFIX = "menu"
LAB_CALLBACK_PREFIX = "lab"
HELP_CALLBACK_PREFIX = "help"
MY_DNA_CALLBACK_PREFIX = "mydna"
MENU_COMMAND = "menu"
HAPLO_COMMAND = "haplo"
HAPLO_CALLBACK_PREFIX = "haplo"
SOZLUK_DB_PATH = Path("sozluk_cache.sqlite3")
UNTESTED_SURNAMES_PATH = Path("untested_surnames.txt")

LOOKUP_START_TEXT = build_lookup_start_text(BUILD_ID)

logging.basicConfig(
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def get_required_env(name: str, *aliases: str) -> str:
    value = os.getenv(name)
    if not value:
        value = os.getenv(f"\ufeff{name}")
    if not value:
        for alias in aliases:
            value = os.getenv(alias)
            if value:
                break
    if not value:
        names = ", ".join((name, *aliases))
        raise RuntimeError(f"Environment variable {names} is required")
    return value


_build_group_sections_keyboard = partial(build_group_sections_keyboard_ui, MENU_CALLBACK_PREFIX)
_build_laboratory_inline_keyboard = partial(build_laboratory_inline_keyboard_ui, LAB_CALLBACK_PREFIX)
_build_help_inline_keyboard = partial(build_help_inline_keyboard_ui, HELP_CALLBACK_PREFIX)
_build_my_dna_inline_keyboard = partial(build_my_dna_inline_keyboard_ui, MY_DNA_CALLBACK_PREFIX)
_build_help_keyboard = partial(build_help_keyboard_ui, MENU_CALLBACK_PREFIX)
_build_help_section_keyboard = partial(build_help_section_keyboard_ui, MENU_CALLBACK_PREFIX)
_build_bottom_menu_keyboard = build_bottom_menu_keyboard_ui
_build_stats_root_keyboard = partial(build_stats_root_keyboard_ui, HAPLO_CALLBACK_PREFIX)

DNA_LAB_STATS_FEATURES = {
    DNA_LAB_MAIN_CALLBACK_PREFIX: "main",
    DNA_LAB_MY_DATA_CALLBACK_PREFIX: "my_data",
    DNA_LAB_COORDINATE_SPACE_CALLBACK_PREFIX: "coordinate_space",
    DNA_LAB_ADMIXTURE_CALLBACK_PREFIX: "admixture",
    DNA_LAB_MODELING_CALLBACK_PREFIX: "modeling",
    DNA_LAB_MATCHING_CALLBACK_PREFIX: "matching",
    DNA_LAB_TRAITS_CALLBACK_PREFIX: "traits",
    DNA_LAB_HAPLOGROUPS_CALLBACK_PREFIX: "haplogroups",
    DNA_LAB_REPORTS_CALLBACK_PREFIX: "reports",
    DNA_LAB_SETTINGS_CALLBACK_PREFIX: "settings",
    DNA_LAB_VAHADUO_CALLBACK_PREFIX: "vahaduo",
    DNA_LAB_SNP_REPORT_CALLBACK_PREFIX: "snp_report",
}
DNA_LAB_MANUAL_USAGE_CALLBACKS = {
    ("my_data", "qg25_create_sample"),
    ("my_data", "qg25_save_g25_library"),
    ("snp_report", "html"),
    ("snp_report", "run"),
    ("traits", "i"),
    ("traits", "p"),
    ("traits", "rp"),
    ("settings", "root"),
    ("settings", "language"),
    ("settings", "set_language"),
    ("settings", "card_format"),
    ("settings", "set_card_format"),
    ("settings", "result_mode"),
    ("settings", "set_result_mode"),
    ("settings", "search_base"),
    ("settings", "set_search_base"),
    ("settings", "notifications"),
    ("settings", "set_notifications"),
    ("settings", "privacy"),
    ("settings", "export_data"),
    ("settings", "export_data_run"),
    ("settings", "delete_data"),
    ("settings", "delete_data_confirm"),
    ("settings", "privacy_info"),
}


def _active_reply_menu_map(context: ContextTypes.DEFAULT_TYPE) -> dict[str, int]:
    storage = context.chat_data if context.chat_data is not None else context.user_data
    active_menus = storage.setdefault("active_reply_menus", {})
    if storage is not context.user_data:
        legacy_menus = context.user_data.pop("active_reply_menus", None)
        if isinstance(legacy_menus, dict):
            active_menus.update(legacy_menus)
    return active_menus


def _reply_menu_owner_map(context: ContextTypes.DEFAULT_TYPE) -> dict[str, int]:
    storage = context.chat_data if context.chat_data is not None else context.user_data
    owners = storage.setdefault("reply_menu_owners", {})
    if storage is not context.user_data:
        legacy_owners = context.user_data.pop("reply_menu_owners", None)
        if isinstance(legacy_owners, dict):
            owners.update(legacy_owners)
    return owners


def _remember_reply_menu_owner(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    message_id: int,
    user_id: int,
) -> None:
    _reply_menu_owner_map(context)[f"{int(chat_id)}:{int(message_id)}"] = int(user_id)


def _forget_reply_menu_owner(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int) -> None:
    _reply_menu_owner_map(context).pop(f"{int(chat_id)}:{int(message_id)}", None)


async def _ensure_reply_menu_owner(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    query = update.callback_query
    if query is None or query.message is None or update.effective_user is None:
        return True
    if update.effective_chat is not None and update.effective_chat.type == "private":
        return True

    key = f"{int(query.message.chat_id)}:{int(query.message.message_id)}"
    owner_id = _reply_menu_owner_map(context).get(key)
    if owner_id is None:
        return True
    try:
        owner_id = int(owner_id)
    except (TypeError, ValueError):
        return True
    if owner_id == int(update.effective_user.id):
        return True

    await query.answer("Это меню не для вас. Откройте свое меню через /menu.", show_alert=True)
    return False


async def _collapse_active_reply_menu(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    *,
    except_message_id: int | None = None,
) -> None:
    active_menus = _active_reply_menu_map(context)
    key = str(chat_id)
    message_id = active_menus.get(key)
    if not message_id or message_id == except_message_id:
        return

    try:
        await context.bot.edit_message_reply_markup(chat_id=chat_id, message_id=message_id, reply_markup=None)
        active_menus.pop(key, None)
        _forget_reply_menu_owner(context, chat_id, message_id)
        return
    except Exception:
        logger.debug("Failed to collapse active reply menu markup", exc_info=True)

    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
        active_menus.pop(key, None)
        _forget_reply_menu_owner(context, chat_id, message_id)
    except Exception:
        logger.debug("Failed to delete active reply menu", exc_info=True)


async def _collapse_reply_menu_message(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    message_id: int,
) -> None:
    try:
        await context.bot.edit_message_reply_markup(chat_id=chat_id, message_id=message_id, reply_markup=None)
        _forget_reply_menu_owner(context, chat_id, message_id)
        return
    except Exception:
        logger.debug("Failed to collapse stale reply menu markup", exc_info=True)

    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
        _forget_reply_menu_owner(context, chat_id, message_id)
    except Exception:
        logger.debug("Failed to delete stale reply menu", exc_info=True)


def _remember_active_reply_menu(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int) -> None:
    _active_reply_menu_map(context)[str(chat_id)] = int(message_id)


async def _discard_stale_reply_menu(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    message_id: int,
) -> bool:
    active_menus = _active_reply_menu_map(context)
    active_message_id = active_menus.get(str(chat_id))
    try:
        active_message_id = int(active_message_id) if active_message_id is not None else None
    except (TypeError, ValueError):
        active_message_id = None

    if active_message_id and message_id < active_message_id:
        await _collapse_reply_menu_message(context, chat_id, message_id)
        return True
    return False


async def _activate_reply_menu(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    message_id: int,
) -> bool:
    if await _discard_stale_reply_menu(context, chat_id, message_id):
        return False

    await _collapse_active_reply_menu(context, chat_id, except_message_id=message_id)
    _remember_active_reply_menu(context, chat_id, message_id)
    return True


def _forget_active_reply_menu(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    *,
    message_id: int | None = None,
) -> None:
    active_menus = _active_reply_menu_map(context)
    key = str(chat_id)
    if message_id is None or active_menus.get(key) == message_id:
        active_menus.pop(key, None)
    if message_id is not None:
        _forget_reply_menu_owner(context, chat_id, message_id)


def _dna_lab_settings() -> SimpleNamespace:
    return SimpleNamespace(root_dir=Path(__file__).resolve().parent)


def _register_dna_lab_services(app: Application) -> None:
    settings = _dna_lab_settings()
    register_dna_lab_settings_services(app, settings)
    register_dna_lab_my_data_services(app, settings)
    register_dna_lab_traits_services(app, settings)
    register_dna_lab_admixture_services(app, settings)
    register_dna_lab_matching_services(app, settings)
    register_dna_lab_haplogroup_services(app, settings)
    register_dna_lab_vahaduo_services(app, settings)
    register_dna_lab_snp_report_services(app, settings)


def _language_for_effective_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    user_id = int(update.effective_user.id) if update.effective_user is not None else None
    return get_dna_lab_user_language(context, user_id)


def _card_format_for_effective_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    if update.effective_user is None:
        return "wide"
    return get_global_user_card_format(context, int(update.effective_user.id))


def _result_mode_for_effective_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    if update.effective_user is None:
        return "simple"
    return get_global_user_result_mode(context, int(update.effective_user.id))


def _search_base_for_effective_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    if update.effective_user is None:
        return "kbdna"
    return get_global_user_search_base(context, int(update.effective_user.id))


def _notifications_enabled_for_effective_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if update.effective_user is None:
        return True
    return get_global_user_notifications_enabled(context, int(update.effective_user.id))


def _is_private_chat(update: Update) -> bool:
    return update.effective_chat is not None and update.effective_chat.type == "private"


def _build_menu_navigation_keyboard(back_action: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("Назад", callback_data=f"{MENU_CALLBACK_PREFIX}:{back_action}"),
        InlineKeyboardButton("Отмена", callback_data=f"{MENU_CALLBACK_PREFIX}:cancel"),
    ]])


def _record_dna_lab_usage(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    feature: str,
    action: str = "",
    *,
    success: bool = True,
    input_mode: str = "callback",
) -> None:
    usage_store = context.application.bot_data.get("usage_store")
    if isinstance(usage_store, UsageStore):
        usage_store.record_dna_lab(update, feature, action=action, success=success, input_mode=input_mode)


def _dna_lab_callback_stats_parts(callback_data: str | None) -> tuple[str, str]:
    prefix, _, tail = str(callback_data or "").partition(":")
    feature = DNA_LAB_STATS_FEATURES.get(prefix, prefix or "unknown")
    action = tail.split(":", 1)[0] if tail else "root"
    return feature, action or "root"


async def _guarded_dna_lab_callback(handler, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _ensure_reply_menu_owner(update, context):
        return
    feature, action = _dna_lab_callback_stats_parts(getattr(update.callback_query, "data", None))
    try:
        await handler(update, context)
    except Exception:
        if (feature, action) not in DNA_LAB_MANUAL_USAGE_CALLBACKS:
            _record_dna_lab_usage(update, context, feature, action, success=False)
        raise
    if (feature, action) not in DNA_LAB_MANUAL_USAGE_CALLBACKS:
        _record_dna_lab_usage(update, context, feature, action, success=True)


def _message_chat_id(message) -> int | None:
    chat_id = getattr(message, "chat_id", None)
    if chat_id is not None:
        return int(chat_id)
    chat = getattr(message, "chat", None)
    if chat is not None and getattr(chat, "id", None) is not None:
        return int(chat.id)
    return None


def _activate_dna_lab_message(context: ContextTypes.DEFAULT_TYPE, message, user_id: int) -> None:
    chat_id = _message_chat_id(message)
    message_id = getattr(message, "message_id", None)
    if chat_id is not None and message_id is not None:
        set_active_dna_lab_menu_message(context, chat_id, int(user_id), int(message_id))


async def _show_dna_lab_modeling_root(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    lang: str,
    edit_existing: bool,
) -> None:
    sent = await show_dna_lab_modeling_menu(message, lang=lang, edit_existing=edit_existing)
    _activate_dna_lab_message(context, sent, user_id)


async def _show_dna_lab_feature_root(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    feature: str,
    *,
    edit_existing: bool,
) -> None:
    lang = get_dna_lab_user_language(context, user_id)
    if feature == "my_data":
        await show_dna_lab_my_data_menu(message, context, user_id, edit_existing=edit_existing)
    elif feature == "coordinate_space":
        await show_dna_lab_coordinate_space_menu(message, edit_existing=edit_existing, lang=lang)
        _activate_dna_lab_message(context, message, user_id)
    elif feature == "vahaduo":
        await show_dna_lab_vahaduo_menu(message, context, user_id, lang=lang, edit_existing=edit_existing)
    elif feature == "admixture":
        await show_dna_lab_admixture_menu(message, context, user_id, lang=lang, edit_existing=edit_existing)
    elif feature == "modeling":
        await _show_dna_lab_modeling_root(message, context, user_id, lang=lang, edit_existing=edit_existing)
    elif feature == "matching":
        await show_dna_lab_matching_menu(message, context, user_id, edit_existing=edit_existing, lang=lang)
    elif feature == "traits":
        await show_dna_lab_traits_root_menu(message, context, user_id, edit_existing=edit_existing)
    elif feature == "haplogroups":
        await show_dna_lab_haplogroups_menu(message, context, user_id, lang=lang, edit_existing=edit_existing)
        _activate_dna_lab_message(context, message, user_id)
    elif feature == "snp_report":
        await show_dna_lab_snp_report_menu(message, context, user_id, edit_existing=edit_existing)


async def _open_dna_lab_feature_from_message(update: Update, context: ContextTypes.DEFAULT_TYPE, feature: str) -> None:
    if update.message is None or update.effective_chat is None or update.effective_user is None:
        return

    _clear_sozluk_pending(context)
    _clear_ystr_pending(context)
    context.user_data.pop("ystr_root_back_callback", None)
    await _collapse_active_reply_menu(context, update.message.chat_id)
    await _show_dna_lab_feature_root(
        update.message,
        context,
        int(update.effective_user.id),
        feature,
        edit_existing=False,
    )
    _record_dna_lab_usage(update, context, feature, "open", input_mode="reply")


async def _open_dna_lab_feature_from_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, feature: str) -> None:
    query = update.callback_query
    if query is None or query.message is None or update.effective_user is None:
        return

    _clear_sozluk_pending(context)
    _clear_ystr_pending(context)
    context.user_data.pop("ystr_root_back_callback", None)
    await _show_dna_lab_feature_root(
        query.message,
        context,
        int(update.effective_user.id),
        feature,
        edit_existing=True,
    )
    _record_dna_lab_usage(update, context, feature, "open", input_mode="inline")


async def _open_quick_g25_from_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.effective_chat is None or update.effective_user is None:
        return

    _clear_sozluk_pending(context)
    _clear_ystr_pending(context)
    await _collapse_active_reply_menu(context, update.message.chat_id)
    await open_dna_lab_quick_g25_prompt(
        update.message,
        context,
        update.effective_chat.id,
        update.effective_user.id,
    )
    _record_dna_lab_usage(update, context, "quick_g25", "open", input_mode="reply")


async def _open_quick_g25_from_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    back_callback: str | None = None,
    add_data_flow: bool = False,
) -> None:
    query = update.callback_query
    if query is None or query.message is None or update.effective_chat is None or update.effective_user is None:
        return

    _clear_sozluk_pending(context)
    _clear_ystr_pending(context)
    await open_dna_lab_quick_g25_prompt(
        query.message,
        context,
        update.effective_chat.id,
        update.effective_user.id,
        back_callback=back_callback,
        add_data_flow=add_data_flow,
        edit_existing=True,
    )
    if not add_data_flow:
        _record_dna_lab_usage(update, context, "quick_g25", "open", input_mode="inline")


async def _open_settings_from_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.effective_chat is None or update.effective_user is None:
        return

    _clear_sozluk_pending(context)
    _clear_ystr_pending(context)
    await _collapse_active_reply_menu(context, update.message.chat_id)

    lang = _language_for_effective_user(update, context)
    card_format = _card_format_for_effective_user(update, context)
    result_mode = _result_mode_for_effective_user(update, context)
    sent = await update.message.reply_text(
        global_settings_text(lang, card_format, result_mode),
        parse_mode="HTML",
        reply_markup=build_global_settings_keyboard(
            lang,
            callback_prefix=MENU_CALLBACK_PREFIX,
            back_callback=f"{MENU_CALLBACK_PREFIX}:cancel",
            cancel_callback=f"{MENU_CALLBACK_PREFIX}:cancel",
        ),
        do_quote=False,
    )
    _remember_active_reply_menu(context, sent.chat_id, sent.message_id)
    _remember_reply_menu_owner(context, sent.chat_id, sent.message_id, update.effective_user.id)


async def _send_inline_entry_from_reply(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    text: str,
    reply_markup: InlineKeyboardMarkup,
) -> None:
    if update.message is None:
        return

    _clear_sozluk_pending(context)
    _clear_ystr_pending(context)
    context.user_data.pop("ystr_root_back_callback", None)
    await _collapse_active_reply_menu(context, update.message.chat_id)
    sent = await update.message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=reply_markup,
        do_quote=False,
    )
    _remember_active_reply_menu(context, sent.chat_id, sent.message_id)
    if update.effective_user is not None:
        _remember_reply_menu_owner(context, sent.chat_id, sent.message_id, update.effective_user.id)
        _activate_dna_lab_message(context, sent, int(update.effective_user.id))


def _laboratory_entry_text() -> str:
    return (
        "🧪 <b>DNA Lab</b>\n\n"
        "Выберите инструмент."
    )


def _my_dna_entry_text() -> str:
    return "🧬 <b>My DNA</b>\n\nЗдесь хранятся ваши образцы и координаты."


def _help_entry_text() -> str:
    return "📚 <b>Справка</b>\n\nДанные, разделы и ограничения.\nОсновные пояснения по KBDNA."


def _help_topic_text(action: str) -> str:
    legacy_redirects = {
        "instruction": "quick_start",
        "raw": "terms",
        "g25": "terms",
        "pgs": "terms",
        "qpadm": "admixlab",
    }
    action = legacy_redirects.get(action, action)
    topics = {
        "quick_start": (
            "🚀 <b>Быстрый старт</b>\n\n"
            "KBDNA можно использовать двумя способами: 🔎 искать сведения по фамилиям и 🧬 работать со своими ДНК-данными.\n\n"
            "<b>1. 🔎 Поиск по фамилиям</b>\n"
            "Если хотите начать без загрузки файлов, используйте поиск по фамилии. Он показывает записи из базы проекта: происхождение, "
            "гаплогруппы, ветки и близкие совпадения, если они есть.\n\n"
            "<b>2. 📊 Аналитика</b>\n"
            "Аналитика помогает смотреть распределения по базе: гаплогруппы, субклады, STR-маркеры и связанные записи.\n\n"
            "<b>3. 🧬 My DNA</b>\n"
            "My DNA хранит ваши samples, raw-файлы, G25-профили и сохранённые отчёты.\n\n"
            "Sample — это отдельный профиль человека или образца. К нему можно привязать raw-файл, G25-координаты и результаты расчётов.\n\n"
            "<b>4. 🧪 DNA Lab</b>\n"
            "DNA Lab — набор инструментов для работы с sample: Coordinate spaces, Vahaduo Lab, Matching, Admixture, AdmixLab, Traits и Haplogroups.\n\n"
            "Проще всего начать так: добавьте sample в My DNA, привяжите raw-файл или G25-профиль, затем откройте нужный инструмент в DNA Lab.\n\n"
            "⚠️ <b>Важно:</b> результаты KBDNA — это расчёты и модели. Они помогают анализировать данные, но не являются медицинской диагностикой "
            "или окончательным доказательством происхождения."
        ),
        "surname_search": (
            "🔎 <b>Поиск по фамилиям</b>\n\n"
            "Это самый быстрый вход в базу KBDNA. Он работает без загрузки ДНК-файлов: достаточно отправить фамилию.\n\n"
            "<b>Как искать</b>\n"
            "В приватном чате нажмите <b>🔎 Поиск по фамилиям</b> или просто отправьте фамилию одним сообщением.\n"
            "В группе используйте команду: <code>/f Фамилия</code>.\n\n"
            "<b>Что показывает результат</b>\n"
            "• найденные записи по фамилии;\n"
            "• происхождение или населённый пункт, если они указаны;\n"
            "• Y-ДНК/мтДНК гаплогруппу и субклад;\n"
            "• близкие совпадения по той же ветви;\n"
            "• дополнительные сведения, если они есть в базе.\n\n"
            "<b>Если фамилия не найдена</b>\n"
            "Попробуйте другой вариант написания, форму без окончания или транслитерацию. Для редких фамилий данных может пока не быть.\n\n"
            "<b>Важно</b>\n"
            "Поиск показывает записи из базы проекта. Он помогает найти ориентиры и связи, но не заменяет генеалогическую проверку."
        ),
        "analytics": (
            "📊 <b>Аналитика KBDNA</b>\n\n"
            "Аналитика показывает общую картину по базе проекта: какие линии встречаются, как они распределены "
            "и с какими фамилиями связаны.\n\n"
            "<b>Что можно смотреть</b>\n"
            "• распределение Y-ДНК и мтДНК гаплогрупп;\n"
            "• переход от крупных ветвей к субкладам;\n"
            "• связанные фамилии и записи внутри ветви;\n"
            "• STR-маркеры и ближайшие STR-совпадения;\n"
            "• отдельные карточки тестов, если данные есть в базе.\n\n"
            "<b>Как использовать</b>\n"
            "1. Начните с общего распределения.\n"
            "2. Откройте интересующую гаплогруппу или субклад.\n"
            "3. Посмотрите связанные фамилии, записи и STR-данные.\n"
            "4. Сравните это с поиском по фамилии и семейной информацией.\n\n"
            "<b>Важно</b>\n"
            "Аналитика показывает структуру базы KBDNA, а не полную картину всех линий. Чем больше данных в базе, "
            "тем точнее становятся распределения и связи."
        ),
        "data_formats": (
            "🧬 <b>Данные: raw, G25, SNP</b>\n\n"
            "В KBDNA встречаются разные типы данных. Главное — понимать, что они не заменяют друг друга.\n\n"
            "<b>🧾 Raw-файл</b>\n"
            "Исходный файл из ДНК-сервиса: 23andMe, Ancestry, MyHeritage, FTDNA и похожих платформ. "
            "Он нужен для поиска SNP, Matching, Traits, Haplogroups и получения G25.\n\n"
            "<b>📍 G25</b>\n"
            "Координатный профиль autosomal-ДНК. Он нужен для Coordinate spaces, Vahaduo Lab, distance/single/multi и готовых G25-моделей.\n\n"
            "<b>🧬 SNP</b>\n"
            "Отдельная позиция в ДНК. По SNP можно проверять конкретные маркеры в raw-файле и сравнивать профили.\n\n"
            "<b>🧪 PGS</b>\n"
            "Polygenic score — расчётный показатель по набору SNP. В KBDNA такие результаты являются справочными и экспериментальными.\n\n"
            "<b>Как начать</b>\n"
            "Если у вас есть raw-файл, загрузите его в My DNA. Если raw нет, но есть G25-строка, добавьте её как G25-профиль."
        ),
        "dna_lab_sections": (
            "🧪 <b>Разделы DNA Lab</b>\n\n"
            "DNA Lab — это рабочая зона для ваших samples, координат и расчётов.\n\n"
            "<b>🧬 My DNA</b>\n"
            "Хранит samples, raw-файлы, G25-профили и сохранённые отчёты.\n\n"
            "<b>🧭 Coordinate spaces</b>\n"
            "Показывает положение sample или G25-профиля в готовых координатных пространствах.\n\n"
            "<b>📐 Vahaduo Lab</b>\n"
            "Distance, Single, Multi и Ready models для G25-разборов.\n\n"
            "<b>🧩 Matching</b>\n"
            "Сравнение raw/SNP между samples и поиск похожих профилей.\n\n"
            "<b>🧬 Admixture</b>\n"
            "Компонентные профили и raw calculators.\n\n"
            "<b>🧱 AdmixLab</b>\n"
            "Формальные модели: qpAdm, qpWave, sources и outgroups.\n\n"
            "<b>✨ Traits и 🌿 Haplogroups</b>\n"
            "Справочные отчёты по признакам, SNP-маркерам и Y/mtDNA-направлениям.\n\n"
            "Обычно удобнее сначала создать sample в My DNA, а затем открывать нужный инструмент."
        ),
        "admixlab": (
            "🧱 <b>AdmixLab / qpAdm</b>\n\n"
            "AdmixLab — раздел для формальных моделей происхождения. Он не про готовые G25-fit модели, а про проверку гипотез через sources и outgroups.\n\n"
            "<b>🏛 qpAdm</b>\n"
            "Проверяет, можно ли описать target как смесь выбранных sources при заданных outgroups.\n\n"
            "<b>〰️ qpWave</b>\n"
            "Оценивает, сколько потоков происхождения нужно, чтобы различить группы в модели.\n\n"
            "<b>📚 Source sets</b>\n"
            "Наборы sources и outgroups для формальных моделей.\n\n"
            "<b>💾 Saved models</b>\n"
            "Место для сохранённых результатов AdmixLab.\n\n"
            "Важно: AdmixLab требует аккуратной постановки вопроса. Набор sources/outgroups влияет на результат так же сильно, как и сам target."
        ),
        "limitations": (
            "🛡 <b>Ограничения</b>\n\n"
            "KBDNA помогает анализировать данные, но у каждого расчёта есть границы.\n\n"
            "<b>Что важно помнить</b>\n"
            "• результаты зависят от качества raw-файла, G25-профиля и reference panels;\n"
            "• совпадения и близость не всегда означают прямое родство;\n"
            "• G25-модели и distance — это приближения, а не окончательное происхождение;\n"
            "• qpAdm/qpWave зависят от выбранных sources и outgroups;\n"
            "• PGS/Traits в боте являются справочными и экспериментальными.\n\n"
            "<b>Чего бот не утверждает</b>\n"
            "KBDNA не ставит медицинские диагнозы, не определяет национальность и не доказывает происхождение окончательно.\n\n"
            "Лучший подход — использовать результаты как ориентир и проверять их вместе с генеалогией, историей семьи и дополнительными тестами."
        ),
        "terms": (
            "📖 <b>Термины DNA</b>\n\n"
            "<b>Raw</b> — исходный файл с ДНК-данными из тест-сервиса.\n\n"
            "<b>G25</b> — координаты autosomal-профиля для сравнений и моделей.\n\n"
            "<b>SNP</b> — отдельная позиция в ДНК, по которой можно смотреть вариант генотипа.\n\n"
            "<b>cM</b> — centimorgan, единица генетического расстояния в matching.\n\n"
            "<b>Target</b> — человек, sample или координаты, которые анализируются.\n\n"
            "<b>Source</b> — компонент или группа, через которую строится модель.\n\n"
            "<b>Outgroup</b> — внешняя группа для формальных моделей qpAdm/qpWave.\n\n"
            "<b>Distance</b> — численная близость target к reference population или source.\n\n"
            "<b>Sample</b> — карточка человека или образца в My DNA."
        ),
    }
    return topics.get(action, "Раздел готовится.")


def _build_help_topic_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("⬅️ Назад", callback_data=f"{HELP_CALLBACK_PREFIX}:root"),
        InlineKeyboardButton("Отмена", callback_data=f"{HELP_CALLBACK_PREFIX}:cancel"),
    ]])


def _build_legacy_more_bridge_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🧪 DNA Lab", callback_data=f"{MENU_CALLBACK_PREFIX}:lab"),
            InlineKeyboardButton("📚 Справка", callback_data=f"{MENU_CALLBACK_PREFIX}:support"),
        ],
        [InlineKeyboardButton("Отмена", callback_data=f"{MENU_CALLBACK_PREFIX}:cancel")],
    ])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return

    await update.message.reply_text(
        LOOKUP_START_TEXT,
        parse_mode="HTML",
        reply_markup=_build_bottom_menu_keyboard(
            include_requests=_is_lookup_admin(update, context),
            include_g25=True,
        ) if update.effective_chat and update.effective_chat.type == "private" else None,
        do_quote=False,
    )


async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return

    _clear_sozluk_pending(context)
    if _is_private_chat(update):
        await _collapse_active_reply_menu(context, update.message.chat_id)
        await update.message.reply_text(
            "Главное меню обновлено.",
            reply_markup=_build_bottom_menu_keyboard(
                include_requests=_is_lookup_admin(update, context),
                include_g25=True,
            ),
            do_quote=False,
        )
        return

    await _collapse_active_reply_menu(context, update.message.chat_id)
    sent = await update.message.reply_text(
        "Выберите раздел:",
        reply_markup=_build_group_sections_keyboard(include_g25=True),
        do_quote=False,
    )
    _remember_active_reply_menu(context, sent.chat_id, sent.message_id)
    if update.effective_user is not None:
        _remember_reply_menu_owner(context, sent.chat_id, sent.message_id, update.effective_user.id)


def _is_lookup_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    access_store: G25AccessStore = context.application.bot_data["g25_access_store"]
    return access_store.is_admin(update)


async def menu_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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

    if action == "help":
        _clear_sozluk_pending(context)
        _clear_ystr_pending(context)
        context.user_data.pop("ystr_root_back_callback", None)
        await query.message.edit_text(
            HELP_ROOT_TEXT,
            parse_mode="HTML",
            reply_markup=_build_help_keyboard(),
        )
        return

    if action == "support":
        _clear_sozluk_pending(context)
        _clear_ystr_pending(context)
        context.user_data.pop("ystr_root_back_callback", None)
        await query.message.edit_text(
            _help_entry_text(),
            parse_mode="HTML",
            reply_markup=_build_help_inline_keyboard(),
        )
        return

    if action.startswith("help:"):
        _clear_sozluk_pending(context)
        _clear_ystr_pending(context)
        context.user_data.pop("ystr_root_back_callback", None)
        section_key = action.split(":", 1)[1]
        section_text = help_section_text(section_key)
        if section_text is None:
            await query.answer("Раздел справки не найден.", show_alert=True)
            return
        await query.message.edit_text(
            section_text,
            parse_mode="HTML",
            reply_markup=_build_help_section_keyboard(),
        )
        return

    if action == "lookup":
        _clear_sozluk_pending(context)
        _clear_ystr_pending(context)
        context.user_data.pop("ystr_root_back_callback", None)
        await query.message.edit_text(
            "🔎 <b>Поиск по фамилии</b>\n\n"
            "В группе используйте команду:\n"
            "<code>/f Фамилия</code>",
            parse_mode="HTML",
            reply_markup=_build_menu_navigation_keyboard("root"),
        )
        return

    if action == "stats":
        _clear_sozluk_pending(context)
        _clear_ystr_pending(context)
        context.user_data.pop("ystr_root_back_callback", None)
        await _send_haplo_root_message(query.message, update, context, edit_existing=True, include_back=True)
        return

    if action == "ystr":
        await _open_ystr_root_inline_menu(
            query.message,
            context,
            back_callback=f"{MENU_CALLBACK_PREFIX}:root",
        )
        return

    if action == "my_data":
        _clear_sozluk_pending(context)
        _clear_ystr_pending(context)
        context.user_data.pop("ystr_root_back_callback", None)
        await query.message.edit_text(
            _my_dna_entry_text(),
            parse_mode="HTML",
            reply_markup=_build_my_dna_inline_keyboard(),
        )
        if update.effective_user is not None:
            _activate_dna_lab_message(context, query.message, int(update.effective_user.id))
        return

    if action in {"coordinate_space", "vahaduo", "admixture", "modeling", "matching", "traits", "haplogroups"}:
        await _open_dna_lab_feature_from_callback(update, context, action)
        return

    if action == "lab":
        _clear_sozluk_pending(context)
        _clear_ystr_pending(context)
        context.user_data.pop("ystr_root_back_callback", None)
        await query.message.edit_text(
            _laboratory_entry_text(),
            parse_mode="HTML",
            reply_markup=_build_laboratory_inline_keyboard(),
        )
        return

    if action == "dna_lab":
        _clear_sozluk_pending(context)
        _clear_ystr_pending(context)
        context.user_data.pop("ystr_root_back_callback", None)
        await query.message.edit_text(
            _laboratory_entry_text(),
            parse_mode="HTML",
            reply_markup=_build_laboratory_inline_keyboard(),
        )
        return

    if action == "quick_g25":
        context.user_data.pop("ystr_root_back_callback", None)
        await _open_quick_g25_from_callback(update, context)
        return

    if action == "more":
        _clear_sozluk_pending(context)
        _clear_ystr_pending(context)
        context.user_data.pop("ystr_root_back_callback", None)
        await query.message.edit_text(
            "🧩 <b>Прочее перенесено</b>\n\nОткройте нужный раздел:",
            parse_mode="HTML",
            reply_markup=_build_legacy_more_bridge_keyboard(),
        )
        return

    if action == "settings":
        _clear_sozluk_pending(context)
        _clear_ystr_pending(context)
        context.user_data.pop("ystr_root_back_callback", None)
        lang = _language_for_effective_user(update, context)
        card_format = _card_format_for_effective_user(update, context)
        result_mode = _result_mode_for_effective_user(update, context)
        await query.message.edit_text(
            global_settings_text(lang, card_format, result_mode),
            parse_mode="HTML",
            reply_markup=build_global_settings_keyboard(
                lang,
                callback_prefix=MENU_CALLBACK_PREFIX,
                back_callback=f"{MENU_CALLBACK_PREFIX}:root",
                cancel_callback=f"{MENU_CALLBACK_PREFIX}:cancel",
            ),
        )
        return

    if action in {"settings_card_format", "card_format"}:
        _clear_sozluk_pending(context)
        _clear_ystr_pending(context)
        context.user_data.pop("ystr_root_back_callback", None)
        lang = _language_for_effective_user(update, context)
        card_format = _card_format_for_effective_user(update, context)
        await query.message.edit_text(
            global_card_format_text(lang, card_format),
            parse_mode="HTML",
            reply_markup=build_global_card_format_keyboard(
                lang,
                card_format,
                callback_prefix=MENU_CALLBACK_PREFIX,
                back_callback=f"{MENU_CALLBACK_PREFIX}:settings",
                cancel_callback=f"{MENU_CALLBACK_PREFIX}:cancel",
            ),
        )
        return

    if action in {"settings_result_mode", "result_mode"}:
        _clear_sozluk_pending(context)
        _clear_ystr_pending(context)
        context.user_data.pop("ystr_root_back_callback", None)
        lang = _language_for_effective_user(update, context)
        result_mode = _result_mode_for_effective_user(update, context)
        await query.message.edit_text(
            global_result_mode_text(lang, result_mode),
            parse_mode="HTML",
            reply_markup=build_global_result_mode_keyboard(
                lang,
                result_mode,
                callback_prefix=MENU_CALLBACK_PREFIX,
                back_callback=f"{MENU_CALLBACK_PREFIX}:settings",
                cancel_callback=f"{MENU_CALLBACK_PREFIX}:cancel",
            ),
        )
        return

    if action in {"settings_search_base", "search_base"}:
        _clear_sozluk_pending(context)
        _clear_ystr_pending(context)
        context.user_data.pop("ystr_root_back_callback", None)
        lang = _language_for_effective_user(update, context)
        search_base = _search_base_for_effective_user(update, context)
        await query.message.edit_text(
            global_search_base_text(lang, search_base),
            parse_mode="HTML",
            reply_markup=build_global_search_base_keyboard(
                lang,
                search_base,
                callback_prefix=MENU_CALLBACK_PREFIX,
                back_callback=f"{MENU_CALLBACK_PREFIX}:settings",
                cancel_callback=f"{MENU_CALLBACK_PREFIX}:cancel",
            ),
        )
        return

    if action in {"settings_notifications", "notifications"}:
        _clear_sozluk_pending(context)
        _clear_ystr_pending(context)
        context.user_data.pop("ystr_root_back_callback", None)
        lang = _language_for_effective_user(update, context)
        enabled = _notifications_enabled_for_effective_user(update, context)
        await query.message.edit_text(
            global_notifications_text(lang, enabled),
            parse_mode="HTML",
            reply_markup=build_global_notifications_keyboard(
                lang,
                enabled,
                callback_prefix=MENU_CALLBACK_PREFIX,
                back_callback=f"{MENU_CALLBACK_PREFIX}:settings",
                cancel_callback=f"{MENU_CALLBACK_PREFIX}:cancel",
            ),
        )
        return

    if action in {"settings_privacy", "privacy"}:
        _clear_sozluk_pending(context)
        _clear_ystr_pending(context)
        context.user_data.pop("ystr_root_back_callback", None)
        lang = _language_for_effective_user(update, context)
        user_id = int(update.effective_user.id) if update.effective_user is not None else 0
        await query.message.edit_text(
            global_privacy_text(lang, global_privacy_data_summary(context, user_id)),
            parse_mode="HTML",
            reply_markup=build_global_privacy_keyboard(
                lang,
                callback_prefix=MENU_CALLBACK_PREFIX,
                back_callback=f"{MENU_CALLBACK_PREFIX}:settings",
                cancel_callback=f"{MENU_CALLBACK_PREFIX}:cancel",
            ),
        )
        return

    if action == "export_data":
        _clear_sozluk_pending(context)
        _clear_ystr_pending(context)
        context.user_data.pop("ystr_root_back_callback", None)
        if update.effective_user is None:
            return
        await show_global_privacy_export_menu(
            query.message,
            context,
            int(update.effective_user.id),
            callback_prefix=MENU_CALLBACK_PREFIX,
            back_callback=f"{MENU_CALLBACK_PREFIX}:privacy",
            cancel_callback=f"{MENU_CALLBACK_PREFIX}:cancel",
            edit_existing=True,
        )
        return

    if action == "export_data_run":
        _clear_sozluk_pending(context)
        _clear_ystr_pending(context)
        context.user_data.pop("ystr_root_back_callback", None)
        if update.effective_user is None:
            return
        await show_global_privacy_export_result(
            query.message,
            context,
            int(update.effective_user.id),
            callback_prefix=MENU_CALLBACK_PREFIX,
            back_callback=f"{MENU_CALLBACK_PREFIX}:privacy",
            cancel_callback=f"{MENU_CALLBACK_PREFIX}:cancel",
            edit_existing=True,
        )
        return

    if action == "delete_data":
        _clear_sozluk_pending(context)
        _clear_ystr_pending(context)
        context.user_data.pop("ystr_root_back_callback", None)
        if update.effective_user is None:
            return
        await show_global_privacy_delete_confirm(
            query.message,
            context,
            int(update.effective_user.id),
            callback_prefix=MENU_CALLBACK_PREFIX,
            back_callback=f"{MENU_CALLBACK_PREFIX}:privacy",
            cancel_callback=f"{MENU_CALLBACK_PREFIX}:cancel",
            edit_existing=True,
        )
        return

    if action == "delete_data_confirm":
        _clear_sozluk_pending(context)
        _clear_ystr_pending(context)
        context.user_data.pop("ystr_root_back_callback", None)
        if update.effective_user is None:
            return
        await show_global_privacy_delete_done(
            query.message,
            context,
            int(update.effective_user.id),
            back_callback=f"{MENU_CALLBACK_PREFIX}:settings",
            cancel_callback=f"{MENU_CALLBACK_PREFIX}:cancel",
            edit_existing=True,
        )
        return

    if action == "privacy_info":
        _clear_sozluk_pending(context)
        _clear_ystr_pending(context)
        context.user_data.pop("ystr_root_back_callback", None)
        lang = _language_for_effective_user(update, context)
        await query.message.edit_text(
            global_privacy_placeholder_text(action, lang),
            parse_mode="HTML",
            reply_markup=build_global_privacy_placeholder_keyboard(
                lang,
                back_callback=f"{MENU_CALLBACK_PREFIX}:privacy",
                cancel_callback=f"{MENU_CALLBACK_PREFIX}:cancel",
            ),
        )
        return

    if action in {"privacy_samples", "privacy_g25", "privacy_reports"}:
        _clear_sozluk_pending(context)
        _clear_ystr_pending(context)
        context.user_data.pop("ystr_root_back_callback", None)
        if update.effective_user is None:
            return
        user_id = int(update.effective_user.id)
        set_active_dna_lab_menu_message(context, query.message.chat_id, user_id, query.message.message_id)
        if action == "privacy_samples":
            context.user_data["my_data_privacy_root_back"] = f"{MENU_CALLBACK_PREFIX}:privacy"
            context.user_data["my_data_privacy_samples_back"] = f"{MENU_CALLBACK_PREFIX}:privacy_samples"
            await show_dna_lab_view_samples_menu(
                query.message,
                context,
                user_id,
                edit_existing=True,
                back_callback=f"{MENU_CALLBACK_PREFIX}:privacy",
            )
            return
        if action == "privacy_g25":
            context.user_data["my_data_privacy_root_back"] = f"{MENU_CALLBACK_PREFIX}:privacy"
            context.user_data["my_data_privacy_g25_back"] = f"{MENU_CALLBACK_PREFIX}:privacy_g25"
            await show_dna_lab_view_coordinates_menu(
                query.message,
                context,
                user_id,
                edit_existing=True,
                back_callback=f"{MENU_CALLBACK_PREFIX}:privacy",
            )
            return
        lang = _language_for_effective_user(update, context)
        context.user_data["my_data_privacy_root_back"] = f"{MENU_CALLBACK_PREFIX}:privacy"
        context.user_data["my_data_privacy_reports_back"] = f"{MENU_CALLBACK_PREFIX}:privacy_reports"
        context.user_data["reports_back_callback"] = f"{MENU_CALLBACK_PREFIX}:privacy"
        context.user_data["reports_my_dna_callback"] = f"{MENU_CALLBACK_PREFIX}:privacy"
        context.user_data["reports_sample_callback_template"] = f"{MENU_CALLBACK_PREFIX}:privacy_sample_reports:{{sample_id}}"
        await show_dna_lab_reports_menu(
            query.message,
            context,
            user_id,
            edit_existing=True,
            lang=lang,
            back_callback=f"{MENU_CALLBACK_PREFIX}:privacy",
            my_dna_callback=f"{MENU_CALLBACK_PREFIX}:privacy",
            show_my_dna_shortcut=False,
            sample_callback_template=f"{MENU_CALLBACK_PREFIX}:privacy_sample_reports:{{sample_id}}",
        )
        return

    if action.startswith("privacy_sample_reports:"):
        _clear_sozluk_pending(context)
        _clear_ystr_pending(context)
        context.user_data.pop("ystr_root_back_callback", None)
        if update.effective_user is None:
            return
        user_id = int(update.effective_user.id)
        sample_id = action.split(":", 1)[1]
        context.user_data["my_data_privacy_root_back"] = f"{MENU_CALLBACK_PREFIX}:privacy"
        context.user_data["my_data_privacy_reports_back"] = f"{MENU_CALLBACK_PREFIX}:privacy_reports"
        set_active_dna_lab_menu_message(context, query.message.chat_id, user_id, query.message.message_id)
        await show_dna_lab_sample_reports_menu(
            query.message,
            context,
            user_id,
            sample_id,
            edit_existing=True,
            back_callback=f"{MENU_CALLBACK_PREFIX}:privacy_reports",
        )
        return

    if action in {"settings_language", "language"}:
        _clear_sozluk_pending(context)
        _clear_ystr_pending(context)
        context.user_data.pop("ystr_root_back_callback", None)
        lang = _language_for_effective_user(update, context)
        await query.message.edit_text(
            global_language_text(lang),
            parse_mode="HTML",
            reply_markup=build_global_language_keyboard(
                lang,
                callback_prefix=MENU_CALLBACK_PREFIX,
                back_callback=f"{MENU_CALLBACK_PREFIX}:settings",
                cancel_callback=f"{MENU_CALLBACK_PREFIX}:cancel",
            ),
        )
        return

    if action.startswith("set_card_format:"):
        selected = action.split(":", 1)[1]
        if update.effective_user is None or not set_global_user_card_format(context, int(update.effective_user.id), selected):
            await query.answer("Не удалось сохранить формат.", show_alert=True)
            return
        lang = _language_for_effective_user(update, context)
        card_format = _card_format_for_effective_user(update, context)
        await query.message.edit_text(
            global_card_format_text(lang, card_format),
            parse_mode="HTML",
            reply_markup=build_global_card_format_keyboard(
                lang,
                card_format,
                callback_prefix=MENU_CALLBACK_PREFIX,
                back_callback=f"{MENU_CALLBACK_PREFIX}:settings",
                cancel_callback=f"{MENU_CALLBACK_PREFIX}:cancel",
            ),
        )
        return

    if action.startswith("set_result_mode:"):
        selected = action.split(":", 1)[1]
        if update.effective_user is None or not set_global_user_result_mode(context, int(update.effective_user.id), selected):
            await query.answer("Не удалось сохранить режим.", show_alert=True)
            return
        lang = _language_for_effective_user(update, context)
        result_mode = _result_mode_for_effective_user(update, context)
        await query.message.edit_text(
            global_result_mode_text(lang, result_mode),
            parse_mode="HTML",
            reply_markup=build_global_result_mode_keyboard(
                lang,
                result_mode,
                callback_prefix=MENU_CALLBACK_PREFIX,
                back_callback=f"{MENU_CALLBACK_PREFIX}:settings",
                cancel_callback=f"{MENU_CALLBACK_PREFIX}:cancel",
            ),
        )
        return

    if action.startswith("set_search_base:"):
        selected = action.split(":", 1)[1]
        if update.effective_user is None or not set_global_user_search_base(context, int(update.effective_user.id), selected):
            await query.answer("Не удалось сохранить базу.", show_alert=True)
            return
        lang = _language_for_effective_user(update, context)
        search_base = _search_base_for_effective_user(update, context)
        await query.message.edit_text(
            global_search_base_text(lang, search_base),
            parse_mode="HTML",
            reply_markup=build_global_search_base_keyboard(
                lang,
                search_base,
                callback_prefix=MENU_CALLBACK_PREFIX,
                back_callback=f"{MENU_CALLBACK_PREFIX}:settings",
                cancel_callback=f"{MENU_CALLBACK_PREFIX}:cancel",
            ),
        )
        return

    if action.startswith("set_notifications:"):
        selected = action.split(":", 1)[1]
        if update.effective_user is None:
            await query.answer("Не удалось сохранить уведомления.", show_alert=True)
            return
        set_global_user_notifications_enabled(context, int(update.effective_user.id), selected == "on")
        lang = _language_for_effective_user(update, context)
        enabled = _notifications_enabled_for_effective_user(update, context)
        await query.message.edit_text(
            global_notifications_text(lang, enabled),
            parse_mode="HTML",
            reply_markup=build_global_notifications_keyboard(
                lang,
                enabled,
                callback_prefix=MENU_CALLBACK_PREFIX,
                back_callback=f"{MENU_CALLBACK_PREFIX}:settings",
                cancel_callback=f"{MENU_CALLBACK_PREFIX}:cancel",
            ),
        )
        return

    if action.startswith("set_language:"):
        selected = action.split(":", 1)[1]
        if update.effective_user is None or not set_global_user_language(context, int(update.effective_user.id), selected):
            await query.answer("Не удалось сохранить язык.", show_alert=True)
            return
        lang = _language_for_effective_user(update, context)
        card_format = _card_format_for_effective_user(update, context)
        result_mode = _result_mode_for_effective_user(update, context)
        await query.message.edit_text(
            global_settings_text(lang, card_format, result_mode),
            parse_mode="HTML",
            reply_markup=build_global_settings_keyboard(
                lang,
                callback_prefix=MENU_CALLBACK_PREFIX,
                back_callback=f"{MENU_CALLBACK_PREFIX}:root",
                cancel_callback=f"{MENU_CALLBACK_PREFIX}:cancel",
            ),
        )
        return

    if action == "sozluk":
        _clear_ystr_pending(context)
        context.user_data.pop("ystr_root_back_callback", None)
        await _open_sozluk_inline_menu(
            query.message,
            update,
            context,
            menu_callback_prefix=MENU_CALLBACK_PREFIX,
            back_action="support",
        )
        return

    if action == "cancel":
        _clear_sozluk_pending(context)
        _clear_ystr_pending(context)
        context.user_data.pop("ystr_root_back_callback", None)
        _forget_active_reply_menu(context, query.message.chat_id, message_id=query.message.message_id)
        await query.message.delete()
        return

    if action == "root":
        _clear_sozluk_pending(context)
        _clear_ystr_pending(context)
        context.user_data.pop("ystr_root_back_callback", None)
        if _is_private_chat(update):
            _forget_active_reply_menu(context, query.message.chat_id, message_id=query.message.message_id)
            await query.message.edit_text("Главное меню доступно внизу.")
            return
        await query.message.edit_text(
            "Выберите раздел:",
            reply_markup=_build_group_sections_keyboard(include_g25=True),
        )
        return

    await query.answer("Неизвестное действие.", show_alert=True)


async def laboratory_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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

    feature_by_action = {
        "coordinates": "coordinate_space",
        "admixture": "admixture",
        "modeling": "modeling",
        "matching": "matching",
        "haplogroups": "haplogroups",
        "traits": "traits",
        "vahaduo": "vahaduo",
        "snp_report": "snp_report",
    }
    if action in feature_by_action:
        await _open_dna_lab_feature_from_callback(update, context, feature_by_action[action])
        return

    if action == "get_g25":
        context.user_data.pop("ystr_root_back_callback", None)
        await _open_quick_g25_from_callback(update, context)
        return

    if action == "root":
        _clear_sozluk_pending(context)
        _clear_ystr_pending(context)
        context.user_data.pop("ystr_root_back_callback", None)
        await query.message.edit_text(
            _laboratory_entry_text(),
            parse_mode="HTML",
            reply_markup=_build_laboratory_inline_keyboard(),
        )
        return

    if action == "cancel":
        _clear_sozluk_pending(context)
        _clear_ystr_pending(context)
        context.user_data.pop("ystr_root_back_callback", None)
        _forget_active_reply_menu(context, query.message.chat_id, message_id=query.message.message_id)
        await query.message.delete()
        return

    await query.answer("Неизвестное действие.", show_alert=True)


async def my_dna_entry_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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

    if update.effective_user is not None:
        _activate_dna_lab_message(context, query.message, int(update.effective_user.id))

    if action == "root":
        _clear_sozluk_pending(context)
        _clear_ystr_pending(context)
        context.user_data.pop("ystr_root_back_callback", None)
        await query.message.edit_text(
            _my_dna_entry_text(),
            parse_mode="HTML",
            reply_markup=_build_my_dna_inline_keyboard(),
        )
        return

    if action == "add_data":
        _clear_sozluk_pending(context)
        _clear_ystr_pending(context)
        context.user_data.pop("ystr_root_back_callback", None)
        await query.message.edit_text(
            _my_dna_entry_text(),
            parse_mode="HTML",
            reply_markup=_build_my_dna_inline_keyboard(),
        )
        return

    if action == "get_g25_raw":
        context.user_data.pop("ystr_root_back_callback", None)
        await _open_quick_g25_from_callback(update, context, back_callback=f"{MY_DNA_CALLBACK_PREFIX}:root")
        return

    await query.answer("Неизвестное действие.", show_alert=True)


async def help_entry_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
        _clear_sozluk_pending(context)
        _clear_ystr_pending(context)
        context.user_data.pop("ystr_root_back_callback", None)
        await query.message.edit_text(
            _help_entry_text(),
            parse_mode="HTML",
            reply_markup=_build_help_inline_keyboard(),
        )
        return

    if action == "back":
        _clear_sozluk_pending(context)
        _clear_ystr_pending(context)
        context.user_data.pop("ystr_root_back_callback", None)
        _forget_active_reply_menu(context, query.message.chat_id, message_id=query.message.message_id)
        await query.message.edit_text("Главное меню доступно внизу.")
        return

    if action == "dictionary":
        _clear_ystr_pending(context)
        context.user_data.pop("ystr_root_back_callback", None)
        await _open_sozluk_inline_menu(
            query.message,
            update,
            context,
            menu_callback_prefix=HELP_CALLBACK_PREFIX,
            back_action="root",
        )
        return

    if action in {
        "quick_start",
        "surname_search",
        "analytics",
        "data_formats",
        "dna_lab_sections",
        "admixlab",
        "limitations",
        "terms",
        "instruction",
        "raw",
        "g25",
        "pgs",
        "qpadm",
    }:
        _clear_sozluk_pending(context)
        _clear_ystr_pending(context)
        context.user_data.pop("ystr_root_back_callback", None)
        await query.message.edit_text(
            _help_topic_text(action),
            parse_mode="HTML",
            reply_markup=_build_help_topic_keyboard(),
        )
        return

    if action == "cancel":
        _clear_sozluk_pending(context)
        _clear_ystr_pending(context)
        context.user_data.pop("ystr_root_back_callback", None)
        _forget_active_reply_menu(context, query.message.chat_id, message_id=query.message.message_id)
        await query.message.delete()
        return

    await query.answer("Неизвестное действие.", show_alert=True)


async def dna_lab_main_navigation_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
        _clear_sozluk_pending(context)
        _clear_ystr_pending(context)
        context.user_data.pop("ystr_root_back_callback", None)
        await query.message.edit_text(
            _laboratory_entry_text(),
            parse_mode="HTML",
            reply_markup=_build_laboratory_inline_keyboard(),
        )
        return

    if action == "cancel":
        _clear_sozluk_pending(context)
        _clear_ystr_pending(context)
        context.user_data.pop("ystr_root_back_callback", None)
        _forget_active_reply_menu(context, query.message.chat_id, message_id=query.message.message_id)
        await query.message.delete()
        return

    await query.answer("Неизвестное действие.", show_alert=True)


async def private_bottom_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.message.text is None:
        return

    text = update.message.text.strip()
    chat_id = update.effective_chat.id if update.effective_chat is not None else update.message.chat_id
    user_id = update.effective_user.id if update.effective_user is not None else None
    _clear_matching_pending(context, chat_id, user_id)
    if text in {BOTTOM_BUTTON_BACK, BOTTOM_BUTTON_CANCEL}:
        _clear_sozluk_pending(context)
        _clear_ystr_pending(context)
        context.user_data.pop("ystr_root_back_callback", None)
        await update.message.reply_text(
            "Главное меню.",
            reply_markup=_build_bottom_menu_keyboard(),
            do_quote=False,
        )
        raise ApplicationHandlerStop

    if text == BOTTOM_BUTTON_LOOKUP:
        _clear_sozluk_pending(context)
        _clear_ystr_pending(context)
        await update.message.reply_text(
            "Введите фамилию одним сообщением или используйте <code>/f Фамилия</code>.",
            parse_mode="HTML",
            do_quote=False,
        )
        raise ApplicationHandlerStop

    if text == BOTTOM_BUTTON_HELP:
        _clear_sozluk_pending(context)
        _clear_ystr_pending(context)
        await _collapse_active_reply_menu(context, update.message.chat_id)
        sent = await update.message.reply_text(
            HELP_ROOT_TEXT,
            parse_mode="HTML",
            reply_markup=_build_help_keyboard(),
            do_quote=False,
        )
        _remember_active_reply_menu(context, sent.chat_id, sent.message_id)
        if update.effective_user is not None:
            _remember_reply_menu_owner(context, sent.chat_id, sent.message_id, update.effective_user.id)
        raise ApplicationHandlerStop

    if text == BOTTOM_BUTTON_SUPPORT:
        await _send_inline_entry_from_reply(
            update,
            context,
            text=_help_entry_text(),
            reply_markup=_build_help_inline_keyboard(),
        )
        raise ApplicationHandlerStop

    if text == BOTTOM_BUTTON_MY_DNA:
        await _send_inline_entry_from_reply(
            update,
            context,
            text=_my_dna_entry_text(),
            reply_markup=_build_my_dna_inline_keyboard(),
        )
        raise ApplicationHandlerStop

    if text == BOTTOM_BUTTON_STATS:
        _clear_sozluk_pending(context)
        _clear_ystr_pending(context)
        await _send_haplo_root_message(update.message, update, context)
        raise ApplicationHandlerStop

    if text == BOTTOM_BUTTON_MORE:
        _clear_sozluk_pending(context)
        _clear_ystr_pending(context)
        context.user_data.pop("ystr_root_back_callback", None)
        await update.message.reply_text(
            "Главное меню.",
            reply_markup=_build_bottom_menu_keyboard(),
            do_quote=False,
        )
        raise ApplicationHandlerStop

    if text == BOTTOM_BUTTON_SOZLUK:
        _clear_ystr_pending(context)
        await _send_sozluk_menu(update.message, context, update)
        raise ApplicationHandlerStop

    if text == BOTTOM_BUTTON_YSTR:
        await _send_ystr_root_message(update.message, update, context)
        raise ApplicationHandlerStop

    dna_lab_reply_features = {
        BOTTOM_BUTTON_COORDINATE_SPACES: "coordinate_space",
        BOTTOM_BUTTON_VAHADUO: "vahaduo",
        "🧪 Vahaduo Lab": "vahaduo",
        BOTTOM_BUTTON_MATCHING: "matching",
        BOTTOM_BUTTON_MODELING: "modeling",
        "🛠 Admixtool": "modeling",
        BOTTOM_BUTTON_TRAITS: "traits",
        "🧾 Traits": "traits",
        MORE_BUTTON_ADMIXTURE: "admixture",
        MORE_BUTTON_HAPLOGROUPS: "haplogroups",
    }
    if text in dna_lab_reply_features:
        await _open_dna_lab_feature_from_message(update, context, dna_lab_reply_features[text])
        raise ApplicationHandlerStop

    if text == BOTTOM_BUTTON_LAB:
        await _send_inline_entry_from_reply(
            update,
            context,
            text=_laboratory_entry_text(),
            reply_markup=_build_laboratory_inline_keyboard(),
        )
        raise ApplicationHandlerStop

    if text == BOTTOM_BUTTON_DNA_LAB:
        await _send_inline_entry_from_reply(
            update,
            context,
            text=_laboratory_entry_text(),
            reply_markup=_build_laboratory_inline_keyboard(),
        )
        raise ApplicationHandlerStop

    if text == BOTTOM_BUTTON_SETTINGS:
        await _open_settings_from_message(update, context)
        raise ApplicationHandlerStop

    if text in {BOTTOM_BUTTON_GET_G25, G25_COORDINATES_REPLY_BUTTON_TEXT}:
        await _open_quick_g25_from_message(update, context)
        raise ApplicationHandlerStop


def _pending_text_target(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> str | None:
    sozluk_pending = context.user_data.get("sozluk_pending")
    if isinstance(sozluk_pending, dict):
        if int(sozluk_pending.get("chat_id") or 0) == chat_id:
            return "sozluk"
    elif "sozluk_pending_direction" in context.user_data:
        return "sozluk"

    ystr_pending = context.user_data.get("ystr_pending")
    if isinstance(ystr_pending, dict) and int(ystr_pending.get("chat_id") or 0) == chat_id:
        return "ystr"

    return None


def _clear_matching_pending(context: ContextTypes.DEFAULT_TYPE, chat_id: int | None, user_id: int | None) -> None:
    if chat_id is None or user_id is None:
        return
    store = context.application.bot_data.get("matching_flow_store")
    clear_pending = getattr(store, "clear_pending", None)
    if callable(clear_pending):
        clear_pending(int(chat_id), int(user_id))


async def pending_text_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.message.text is None:
        return

    target = _pending_text_target(context, update.message.chat_id)
    if target == "sozluk":
        await sozluk_pending_text_handler(update, context)
        return
    if target == "ystr":
        await ystr_pending_text_handler(update, context)
        return



async def build_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    await update.message.reply_text(BUILD_ID, do_quote=False)


def _parse_g25_admin_ids(raw: str) -> set[int]:
    values = set()
    for token in re.split(r"[,\s]+", raw.strip()):
        if not token:
            continue
        try:
            values.add(int(token))
        except ValueError:
            continue
    return values

def _parse_g25_admin_usernames(raw: str) -> set[str]:
    values = set()
    for token in re.split(r"[,\s]+", raw.strip()):
        normalized = G25AccessStore._normalize_username(token)
        if normalized:
            values.add(normalized)
    return values


def _normalized_sheet_value(value: str) -> str:
    return " ".join(str(value or "").strip().lower().replace("ё", "е").split())


def _sheet_cell(headers: list[str], row: list[str], aliases: tuple[str, ...]) -> str:
    normalized_headers = [_normalized_sheet_value(header) for header in headers]
    for alias in aliases:
        normalized_alias = _normalized_sheet_value(alias)
        if normalized_alias in normalized_headers:
            index = normalized_headers.index(normalized_alias)
            return row[index].strip() if len(row) > index else ""
    return ""


def _adyghe_abkhaz_row_filter(search_base: str):
    def row_filter(headers: list[str], row: list[str]) -> bool:
        country = _normalized_sheet_value(_sheet_cell(headers, row, ("country", "страна")))
        subethnos = _normalized_sheet_value(_sheet_cell(headers, row, ("субэтнос", "subethnos", "ethnicity")))
        if search_base == SEARCH_BASE_ADYGHE:
            return "circassia" in country or "adygea" in country
        if search_base == SEARCH_BASE_ABKHAZ:
            return country.startswith("abkh")
        if search_base == SEARCH_BASE_ABAZA:
            return country.startswith("abaza") or "абаз" in subethnos or "abaza" in subethnos
        return False

    return row_filter


def _build_search_base_sheets(creds_path: str, default_sheets: SheetsClient) -> dict[str, SheetsClient]:
    sheets_by_search_base: dict[str, SheetsClient] = {SEARCH_BASE_KBDNA: default_sheets}
    spreadsheet_id = os.getenv("ADYGHE_ABKHAZ_GOOGLE_SHEETS_ID", DEFAULT_ADYGHE_ABKHAZ_SPREADSHEET_ID).strip()
    worksheet_name = os.getenv("ADYGHE_ABKHAZ_GOOGLE_SHEETS_WORKSHEET", DEFAULT_ADYGHE_ABKHAZ_WORKSHEET).strip()
    if not spreadsheet_id:
        return sheets_by_search_base

    for search_base in (SEARCH_BASE_ADYGHE, SEARCH_BASE_ABKHAZ, SEARCH_BASE_ABAZA):
        try:
            sheets_by_search_base[search_base] = SheetsClient(
                creds_path=creds_path,
                spreadsheet_id=spreadsheet_id,
                worksheet_name=worksheet_name,
                name_aliases=("фамилия", "name", "имя"),
                origin_aliases=("lacation", "location", "локация", "место", "населенный пункт", "населённый пункт", "аул", "село"),
                row_filter=_adyghe_abkhaz_row_filter(search_base),
                related_match_mode=SheetsClient.RELATED_MATCH_HAPLOGROUP,
                lookup_label_mode=SheetsClient.LOOKUP_LABEL_TERMINAL_HAPLOGROUP,
                values_range="A:Q",
            )
        except Exception:
            logger.exception("Failed to initialize search base sheet: %s", search_base)
    return sheets_by_search_base


async def statslist_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return

    access_store: G25AccessStore = context.application.bot_data["g25_access_store"]
    if not access_store.is_admin(update):
        await update.message.reply_text("Команда доступна только администратору статистики.", do_quote=False)
        return

    await update.message.reply_text(access_store.format_admin_list(), parse_mode="HTML", do_quote=False)


def main() -> None:
    load_dotenv()

    bot_token = get_required_env("BOT_TOKEN")
    spreadsheet_id = get_required_env("GOOGLE_SHEETS_ID", "GOOGLE_SHETS_ID")
    worksheet_name = os.getenv("GOOGLE_SHEETS_WORKSHEET", "").strip()
    mtdna_spreadsheet_id = os.getenv("MTDNA_GOOGLE_SHEETS_ID", DEFAULT_MTDNA_SPREADSHEET_ID).strip()
    mtdna_worksheet_name = os.getenv("MTDNA_GOOGLE_SHEETS_WORKSHEET", "").strip()
    creds_path = get_required_env("GOOGLE_CREDENTIALS_PATH")
    g25_admin_ids = _parse_g25_admin_ids(os.getenv("G25_ADMIN_IDS", ""))
    g25_admin_usernames = _parse_g25_admin_usernames(os.getenv("G25_ADMIN_USERNAMES", ""))

    sheets = SheetsClient(
        creds_path=creds_path,
        spreadsheet_id=spreadsheet_id,
        worksheet_name=worksheet_name,
    )
    sheets_by_search_base = _build_search_base_sheets(creds_path, sheets)
    mtdna_sheets: MtdnaSheetsClient | None = None
    if mtdna_spreadsheet_id:
        try:
            mtdna_sheets = MtdnaSheetsClient(
                creds_path=creds_path,
                spreadsheet_id=mtdna_spreadsheet_id,
                worksheet_name=mtdna_worksheet_name,
            )
            logger.info("mtDNA sheet schema: %s", mtdna_sheets.get_schema_summary())
        except Exception:
            logger.exception("Failed to initialize mtDNA sheets client")
    usage_store = UsageStore(USAGE_DB_PATH)
    sozluk = SozlukClient(SOZLUK_DB_PATH)
    g25_access_store = G25AccessStore(G25_ACCESS_PATH, admin_ids=g25_admin_ids, admin_usernames=g25_admin_usernames)

    app = Application.builder().token(bot_token).build()
    app.bot_data["sheets"] = sheets
    app.bot_data["sheets_by_search_base"] = sheets_by_search_base
    app.bot_data["mtdna_sheets"] = mtdna_sheets
    app.bot_data["usage_store"] = usage_store
    app.bot_data["sozluk"] = sozluk
    app.bot_data["g25_access_store"] = g25_access_store
    app.bot_data["reports_back_callback"] = f"{MY_DNA_CALLBACK_PREFIX}:root"
    app.bot_data["reports_my_dna_callback"] = f"{MY_DNA_CALLBACK_PREFIX}:root"
    app.bot_data["reports_show_my_dna_shortcut"] = False
    app.bot_data["reply_menu_hooks"] = {
        "collapse_active_reply_menu": _collapse_active_reply_menu,
        "remember_active_reply_menu": _remember_active_reply_menu,
        "remember_reply_menu_owner": _remember_reply_menu_owner,
        "ensure_reply_menu_owner": _ensure_reply_menu_owner,
        "discard_stale_reply_menu": _discard_stale_reply_menu,
        "activate_reply_menu": _activate_reply_menu,
        "forget_active_reply_menu": _forget_active_reply_menu,
    }
    _register_dna_lab_services(app)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler(MENU_COMMAND, menu_command))
    app.add_handler(CommandHandler("build", build_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler(HAPLO_COMMAND, haplo_command))
    app.add_handler(CommandHandler("g25stats", g25stats_command))
    app.add_handler(CommandHandler("statslist", statslist_command))
    app.add_handler(CommandHandler(SOZLUK_COMMAND, sozluk_command))
    app.add_handler(CommandHandler(SOZLUK_SHORT_COMMAND, sozluk_command))
    app.add_handler(CallbackQueryHandler(ystr_callback_handler, pattern=r"^ystr:"))
    app.add_handler(CallbackQueryHandler(haplo_callback_handler, pattern=r"^haplo:"))
    app.add_handler(CallbackQueryHandler(menu_callback_handler, pattern=r"^menu:"))
    app.add_handler(CallbackQueryHandler(laboratory_callback_handler, pattern=r"^lab:"))
    app.add_handler(CallbackQueryHandler(my_dna_entry_callback_handler, pattern=r"^(?:mydna:|my_data:root$)"))
    app.add_handler(CallbackQueryHandler(help_entry_callback_handler, pattern=r"^help:"))
    app.add_handler(CallbackQueryHandler(dna_lab_main_navigation_callback_handler, pattern=fr"^{DNA_LAB_MAIN_CALLBACK_PREFIX}:"))
    app.add_handler(CallbackQueryHandler(partial(_guarded_dna_lab_callback, dna_lab_my_data_callback_handler), pattern=fr"^{DNA_LAB_MY_DATA_CALLBACK_PREFIX}:"))
    app.add_handler(CallbackQueryHandler(partial(_guarded_dna_lab_callback, dna_lab_coordinate_space_callback_handler), pattern=fr"^{DNA_LAB_COORDINATE_SPACE_CALLBACK_PREFIX}:"))
    app.add_handler(CallbackQueryHandler(partial(_guarded_dna_lab_callback, dna_lab_admixture_callback_handler), pattern=fr"^{DNA_LAB_ADMIXTURE_CALLBACK_PREFIX}:"))
    app.add_handler(CallbackQueryHandler(partial(_guarded_dna_lab_callback, dna_lab_modeling_callback_handler), pattern=fr"^{DNA_LAB_MODELING_CALLBACK_PREFIX}:"))
    app.add_handler(CallbackQueryHandler(partial(_guarded_dna_lab_callback, dna_lab_matching_callback_handler), pattern=fr"^{DNA_LAB_MATCHING_CALLBACK_PREFIX}:"))
    app.add_handler(CallbackQueryHandler(partial(_guarded_dna_lab_callback, dna_lab_traits_callback_handler), pattern=fr"^{DNA_LAB_TRAITS_CALLBACK_PREFIX}:"))
    app.add_handler(CallbackQueryHandler(partial(_guarded_dna_lab_callback, dna_lab_haplogroups_callback_handler), pattern=fr"^{DNA_LAB_HAPLOGROUPS_CALLBACK_PREFIX}:"))
    app.add_handler(CallbackQueryHandler(partial(_guarded_dna_lab_callback, dna_lab_reports_callback_handler), pattern=fr"^{DNA_LAB_REPORTS_CALLBACK_PREFIX}:"))
    app.add_handler(CallbackQueryHandler(partial(_guarded_dna_lab_callback, dna_lab_settings_callback_handler), pattern=fr"^{DNA_LAB_SETTINGS_CALLBACK_PREFIX}:"))
    app.add_handler(CallbackQueryHandler(partial(_guarded_dna_lab_callback, dna_lab_vahaduo_callback_handler), pattern=fr"^{DNA_LAB_VAHADUO_CALLBACK_PREFIX}:"))
    app.add_handler(CallbackQueryHandler(partial(_guarded_dna_lab_callback, dna_lab_snp_report_callback_handler), pattern=fr"^{DNA_LAB_SNP_REPORT_CALLBACK_PREFIX}:"))
    app.add_handler(CallbackQueryHandler(lookup_suggestion_callback_handler, pattern=r"^lookup:(?:[sr]:\d+|a:all)$"))
    app.add_handler(CommandHandler("find", find_command))
    app.add_handler(CommandHandler("f", find_command))
    app.add_handler(MessageHandler(filters.Document.ALL, dna_lab_my_data_document_input_handler), group=1)
    app.add_handler(MessageHandler(filters.Document.ALL, dna_lab_vahaduo_document_input_handler), group=2)
    app.add_handler(MessageHandler(filters.Document.ALL, dna_lab_haplogroups_document_input_handler), group=3)
    app.add_handler(
        MessageHandler(
            filters.ChatType.PRIVATE
            & filters.TEXT
            & ~filters.COMMAND
            & filters.Regex(r"^(?:🔎 Поиск по фамилии|ℹ️ Инструкция|📊 Аналитика|🧬 My DNA|🧪 Лаборатория|🧪 DNA Lab|📚 Справка|🧭 Coordinate spaces|📐 Vahaduo Lab|🧪 Vahaduo Lab|🧩 Matching|🧱 AdmixLab|🛠 Admixtool|✨ Traits|🧾 Traits|🧬 Admixture|🌿 Haplogroups|🧬 Получить G25 координаты|Получить G25 координаты|⚙️ Настройки|🧬 Y-STR анализ|📚 Словарь|🧩 Прочее|Назад|Отмена)$"),
            private_bottom_menu_handler,
        ),
        group=-6,
    )
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, dna_lab_snp_report_text_input_handler), group=-7)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, dna_lab_my_data_text_input_handler), group=-5)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, dna_lab_vahaduo_text_input_handler), group=-4)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, dna_lab_haplogroups_text_input_handler), group=-3)
    app.add_handler(MessageHandler(filters.Document.ALL, ystr_document_input_handler), group=-2)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, dna_lab_matching_text_input_handler), group=-2)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, pending_text_router), group=-2)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, dna_lab_modeling_text_input_handler), group=-1)
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, text_lookup_command))

    logger.info("Bot started: %s", BUILD_ID)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()



