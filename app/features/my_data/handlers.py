from __future__ import annotations

import html
import logging
import re
from pathlib import Path

from telegram import InputFile, Update
from telegram.ext import Application, ApplicationHandlerStop, ContextTypes

from g25_core.command_service import G25CommandError, G25CommandService

from app.main_menu import ensure_active_main_menu, set_active_main_menu_message
from app.features.admixture.menu import show_sample_admixture_reports_menu
from app.features.coordinate_space.reports import CoordinateSpaceReportStore
from app.features.haplogroups.menu import show_records_menu as show_sample_haplogroup_reports_menu
from app.features.matching.storage import MatchingStore
from app.features.matching.ui import saved_match_detail_text
from app.features.traits.menu import show_sample_trait_reports_menu
from app.i18n import get_user_language

from .state import MyDataFlowStore, matches_active_message
from .storage import CoordinateAsset, MyDataStore, RawArchiveError, RawFileAsset, SampleAsset
from .snp_lookup import lookup_snp_in_sample
from .ui import (
    MY_DATA_CALLBACK_PREFIX,
    add_coordinates_text,
    add_coordinates_type_text,
    build_add_coordinates_keyboard,
    build_add_coordinates_type_keyboard,
    build_coordinate_delete_prompt_keyboard,
    build_coordinate_detail_keyboard,
    build_coordinate_items_keyboard,
    build_coordinate_rename_keyboard,
    build_coordinates_keyboard,
    build_create_sample_keyboard,
    build_extract_coordinates_keyboard,
    build_extract_coordinates_type_keyboard,
    build_my_data_keyboard,
    build_new_g25_profile_keyboard,
    build_raw_file_delete_prompt_keyboard,
    build_raw_file_detail_keyboard,
    build_raw_file_rename_keyboard,
    build_sample_delete_prompt_keyboard,
    build_sample_detail_keyboard,
    build_sample_reports_keyboard,
    build_sample_coordinate_space_reports_keyboard,
    build_coordinate_space_report_delete_prompt_keyboard,
    build_coordinate_space_report_detail_keyboard,
    build_coordinate_space_report_not_found_keyboard,
    COORD_REPORT_DELETE_CONFIRM_ACTION,
    COORD_REPORT_DELETE_PROMPT_ACTION,
    COORD_REPORT_OPEN_ACTION,
    build_sample_saved_section_keyboard,
    build_sample_matching_detail_keyboard,
    build_sample_matching_reports_keyboard,
    build_sample_attached_coordinates_keyboard,
    build_sample_coordinate_detail_keyboard,
    build_sample_attach_coordinates_picker_keyboard,
    build_sample_coordinates_menu_keyboard,
    build_sample_items_keyboard,
    build_sample_add_coordinates_keyboard,
    build_sample_add_coordinates_type_keyboard,
    build_sample_rename_keyboard,
    build_sample_snp_lookup_input_keyboard,
    build_sample_snp_lookup_result_keyboard,
    build_sample_extract_coordinates_type_keyboard,
    build_quick_g25_result_keyboard,
    build_upload_raw_keyboard,
    build_view_coordinates_keyboard,
    build_view_samples_keyboard,
    coordinates_text,
    coordinate_delete_prompt_text,
    coordinate_detail_text,
    coordinate_rename_text,
    create_sample_text,
    extract_coordinates_type_text,
    extract_coordinates_text,
    my_data_text,
    new_g25_profile_text,
    quick_g25_result_text,
    quick_g25_saved_text,
    raw_file_delete_prompt_text,
    raw_file_detail_text,
    raw_file_rename_text,
    sample_attached_coordinates_text,
    sample_reports_text,
    sample_coordinate_space_reports_text,
    coordinate_space_report_delete_prompt_text,
    coordinate_space_report_detail_text,
    coordinate_space_report_not_found_text,
    coordinate_space_report_visual_caption,
    sample_attach_coordinates_picker_text,
    sample_coordinates_menu_text,
    sample_delete_prompt_text,
    sample_detail_text,
    sample_add_coordinates_text,
    sample_add_coordinates_type_text,
    sample_saved_section_text,
    sample_matching_reports_text,
    sample_extract_coordinates_type_text,
    sample_rename_text,
    sample_snp_lookup_input_text,
    sample_snp_lookup_invalid_text,
    sample_snp_lookup_no_raw_text,
    sample_snp_lookup_result_text,
    upload_raw_text,
    view_coordinates_text,
    view_samples_text,
)


logger = logging.getLogger(__name__)

TELEGRAM_BOT_DOWNLOAD_LIMIT_BYTES = 20 * 1024 * 1024
SAMPLE_CREATE_ACTION = "sample_create"
SAMPLE_RENAME_ACTION = "sample_rename"
SAMPLE_SNP_LOOKUP_ACTION = "sample_snp_lookup"
SAMPLE_ATTACH_COORD_ACTION = "sample_attach_coord_choose"
RAW_UPLOAD_ACTION = "raw_upload"
RAW_RENAME_ACTION = "raw_rename"
COORDINATE_ADD_ACTION = "coordinate_add"
COORDINATE_EXTRACT_ACTION = "coordinate_extract"
COORDINATE_RENAME_ACTION = "coordinate_rename"
QUICK_G25_RESULT_ACTION = "quick_g25_result"
QUICK_G25_CALLBACK_ACTIONS = {"qg25_create_sample", "qg25_save_g25_library"}
COORDINATE_REPORT_CALLBACK_ACTIONS = {
    COORD_REPORT_OPEN_ACTION,
    COORD_REPORT_DELETE_PROMPT_ACTION,
    COORD_REPORT_DELETE_CONFIRM_ACTION,
    "sample_coord_report",
    "sample_coord_report_delete_prompt",
    "sample_coord_report_delete_confirm",
}
PRIVACY_ROOT_BACK_KEY = "my_data_privacy_root_back"
PRIVACY_SAMPLES_BACK_KEY = "my_data_privacy_samples_back"
PRIVACY_G25_BACK_KEY = "my_data_privacy_g25_back"
PRIVACY_REPORTS_BACK_KEY = "my_data_privacy_reports_back"
SAMPLE_SNP_RSID_PATTERN = re.compile(r"^rs\d+$", re.IGNORECASE)
SAMPLE_SNP_DIGITS_PATTERN = re.compile(r"^\d+$")


def _raw_archive_error_text(error: RawArchiveError, *, lang: str) -> str:
    messages = {
        "rar_not_supported": (
            "RAR archives are not supported yet. Send a ZIP or GZ archive; it will be unpacked and saved as raw."
            if lang == "en"
            else "RAR-архивы пока не поддерживаются. Пришлите ZIP или GZ: архив будет распакован и сохранен как raw."
        ),
        "archive_empty": (
            "The archive is empty. Send a ZIP or GZ archive containing a raw file."
            if lang == "en"
            else "Архив пуст. Пришлите ZIP или GZ с raw-файлом внутри."
        ),
        "archive_too_large": (
            "The extracted raw file is too large to store."
            if lang == "en"
            else "Raw-файл после распаковки слишком большой для сохранения."
        ),
    }
    return messages.get(
        error.reason,
        "Could not unpack the archive. Send a valid ZIP or GZ containing a raw file."
        if lang == "en"
        else "Не удалось распаковать архив. Пришлите исправный ZIP или GZ с raw-файлом внутри.",
    )


def _raw_file_too_large_text(*, lang: str) -> str:
    if lang == "en":
        return "This file is larger than Telegram's 20 MB bot download limit. Send it as a ZIP or GZ archive."
    return "Файл больше лимита Telegram для бота (20 MB). Пришлите его в архиве ZIP или GZ."


def register_my_data_services(application: Application, settings) -> None:
    application.bot_data["my_data_store"] = MyDataStore(settings.root_dir / "storage" / "my_data")
    application.bot_data["my_data_flow_store"] = MyDataFlowStore()
    application.bot_data["coordinate_space_report_store"] = CoordinateSpaceReportStore(
        settings.root_dir / "storage" / "coordinate_space" / "reports"
    )
    if "pca_service" not in application.bot_data:
        application.bot_data["pca_service"] = G25CommandService(settings.root_dir / "g25_core")


def _data_store(context: ContextTypes.DEFAULT_TYPE) -> MyDataStore:
    return context.application.bot_data["my_data_store"]


def _flow_store(context: ContextTypes.DEFAULT_TYPE) -> MyDataFlowStore:
    return context.application.bot_data["my_data_flow_store"]


def _g25_service(context: ContextTypes.DEFAULT_TYPE) -> G25CommandService:
    return context.application.bot_data["pca_service"]


def _record_g25_usage(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    command: str = "g25",
    input_mode: str = "unknown",
    success: bool = True,
    query: str | None = None,
) -> None:
    usage_store = context.application.bot_data.get("usage_store")
    if usage_store is not None and hasattr(usage_store, "record_g25"):
        usage_store.record_g25(update, command=command, input_mode=input_mode, success=success, query=query)


def _record_dna_lab_usage(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    action: str,
    success: bool = True,
    input_mode: str = "callback",
) -> None:
    usage_store = context.application.bot_data.get("usage_store")
    if usage_store is not None and hasattr(usage_store, "record_dna_lab"):
        usage_store.record_dna_lab(update, "my_data", action=action, success=success, input_mode=input_mode)


def _matching_store(context: ContextTypes.DEFAULT_TYPE) -> MatchingStore:
    store = context.application.bot_data.get("matching_store")
    if isinstance(store, MatchingStore):
        return store
    store = MatchingStore(_data_store(context).root_dir.parent / "matching")
    context.application.bot_data["matching_store"] = store
    return store


def _coordinate_space_report_store(context: ContextTypes.DEFAULT_TYPE) -> CoordinateSpaceReportStore:
    store = context.application.bot_data.get("coordinate_space_report_store")
    if isinstance(store, CoordinateSpaceReportStore):
        return store
    store = CoordinateSpaceReportStore(_data_store(context).root_dir.parent / "coordinate_space" / "reports")
    context.application.bot_data["coordinate_space_report_store"] = store
    return store


def _visible_my_data_coordinates(items: list[CoordinateAsset]) -> list[CoordinateAsset]:
    return [item for item in items if item.coordinate_type.strip().lower() != "k36"]


def _standalone_my_data_coordinates(store: MyDataStore, user_id: int) -> list[CoordinateAsset]:
    attached_ids: set[str] = set()
    for sample in store.list_samples(user_id):
        attached_ids.update(str(value) for value in sample.coordinate_ids if str(value))
    return [
        item
        for item in _visible_my_data_coordinates(store.list_coordinates(user_id))
        if item.asset_id not in attached_ids
    ]


def _origin_callback(context: ContextTypes.DEFAULT_TYPE, key: str, default: str) -> str:
    value = str(context.user_data.get(key) or "").strip()
    return value or default


def _clear_privacy_origin(context: ContextTypes.DEFAULT_TYPE) -> None:
    for key in (
        PRIVACY_ROOT_BACK_KEY,
        PRIVACY_SAMPLES_BACK_KEY,
        PRIVACY_G25_BACK_KEY,
        PRIVACY_REPORTS_BACK_KEY,
        "reports_back_callback",
        "reports_my_dna_callback",
        "reports_sample_callback_template",
    ):
        context.user_data.pop(key, None)


def _safe_count(callback) -> int:
    try:
        return len(callback())
    except Exception:
        return 0


def _sample_report_counts(context: ContextTypes.DEFAULT_TYPE, user_id: int, sample_id: str) -> dict[str, int]:
    counts = {
        "coordinate_spaces": _safe_count(lambda: _coordinate_space_report_store(context).list_results(user_id, sample_id)),
        "admixture": 0,
        "matching": _safe_count(lambda: _matching_store(context).list_matches_for_sample(user_id, sample_id)),
        "traits": 0,
        "haplogroups": 0,
    }

    admixture_store = context.application.bot_data.get("admixture_report_store")
    if admixture_store is not None:
        counts["admixture"] = _safe_count(lambda: admixture_store.list_reports(user_id, sample_id))

    traits_store = context.application.bot_data.get("traits_report_store")
    if traits_store is not None:
        counts["traits"] = _safe_count(lambda: traits_store.list_reports(user_id, sample_id))

    haplogroup_store = context.application.bot_data.get("haplogroup_store")
    if haplogroup_store is not None:
        counts["haplogroups"] = _safe_count(lambda: haplogroup_store.list_sample_records(user_id, sample_id))

    return counts


def _sample_report_count(context: ContextTypes.DEFAULT_TYPE, user_id: int, sample_id: str) -> int:
    return sum(_sample_report_counts(context, user_id, sample_id).values())


def _build_sample_name(update: Update, fallback_name: str = "") -> str:
    fallback_name = fallback_name.strip()
    if fallback_name:
        return fallback_name

    user = update.effective_user
    if user is not None:
        full_name = " ".join(
            part for part in [getattr(user, "first_name", "") or "", getattr(user, "last_name", "") or ""] if part
        ).strip()
        if full_name:
            return full_name
        if getattr(user, "username", None):
            return str(user.username)
    return "Target"


def normalize_sample_snp_rsid(value: str) -> str | None:
    candidate = value.strip().lower()
    if SAMPLE_SNP_DIGITS_PATTERN.fullmatch(candidate):
        return f"rs{candidate}"
    return candidate if SAMPLE_SNP_RSID_PATTERN.fullmatch(candidate) else None


def _clear_my_data_pending(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int) -> None:
    store = _flow_store(context)
    if store.get_action(chat_id, user_id) == QUICK_G25_RESULT_ACTION:
        raw_temp_path = str(store.get_payload(chat_id, user_id).get("raw_temp_path") or "").strip()
        if raw_temp_path:
            _data_store(context).cleanup_temp_file(Path(raw_temp_path))
    store.clear(chat_id, user_id)


def _quick_g25_payload(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int) -> dict[str, str] | None:
    store = _flow_store(context)
    if store.get_action(chat_id, user_id) != QUICK_G25_RESULT_ACTION:
        return None

    payload = store.get_payload(chat_id, user_id)
    g25_line = str(payload.get("g25_line") or "").strip()
    if not g25_line:
        return None
    return {
        "coordinate_type": str(payload.get("coordinate_type") or "g25").strip().lower() or "g25",
        "target_name": str(payload.get("target_name") or "Target").strip() or "Target",
        "g25_line": g25_line,
        "input_mode": str(payload.get("input_mode") or "raw-file").strip() or "raw-file",
        "raw_temp_path": str(payload.get("raw_temp_path") or "").strip(),
        "raw_file_name": str(payload.get("raw_file_name") or "input.raw").strip() or "input.raw",
        "raw_display_name": str(payload.get("raw_display_name") or payload.get("target_name") or "raw-file").strip() or "raw-file",
    }


def _save_quick_g25_coordinate(context: ContextTypes.DEFAULT_TYPE, user_id: int, payload: dict[str, str], *, display_name: str | None = None) -> CoordinateAsset:
    target_name = payload["target_name"]
    return _data_store(context).save_coordinate(
        user_id,
        display_name=display_name or target_name,
        target_name=target_name,
        coordinate_type=payload["coordinate_type"],
        g25_line=payload["g25_line"],
        input_mode=payload["input_mode"],
    )


def _cleanup_quick_g25_raw_temp(context: ContextTypes.DEFAULT_TYPE, payload: dict[str, str]) -> None:
    raw_temp_path = payload.get("raw_temp_path", "")
    if raw_temp_path:
        _data_store(context).cleanup_temp_file(Path(raw_temp_path))


async def _redirect_legacy_branch(query, context: ContextTypes.DEFAULT_TYPE, user_id: int, message: str) -> None:
    await query.answer(message)
    await show_view_samples_menu(query.message, context, user_id, edit_existing=True)


async def _edit_menu_message(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    chat_id: int,
    message_id: int,
    text: str,
    reply_markup,
    parse_mode: str | None = None,
) -> None:
    await context.bot.edit_message_text(
        chat_id=chat_id,
        message_id=message_id,
        text=text,
        reply_markup=reply_markup,
        parse_mode=parse_mode,
    )


async def _show_or_edit(message, text: str, reply_markup, *, edit_existing: bool = False, parse_mode: str | None = None):
    if edit_existing:
        await message.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
        return message
    return await message.reply_text(text, reply_markup=reply_markup, parse_mode=parse_mode, do_quote=False)


def _message_has_photo(message) -> bool:
    return bool(getattr(message, "photo", None))


async def _replace_photo_with_text(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    text: str,
    reply_markup,
    *,
    parse_mode: str | None = None,
):
    sent = await message.reply_text(text, reply_markup=reply_markup, parse_mode=parse_mode, do_quote=False)
    try:
        await message.delete()
    except Exception:
        logger.exception("Could not delete Coordinate Space visual report message")
    chat_id = getattr(sent, "chat_id", getattr(message, "chat_id", None))
    message_id = getattr(sent, "message_id", None)
    if chat_id is not None and message_id is not None:
        set_active_main_menu_message(context, chat_id, user_id, message_id)
    return sent


async def _show_coordinate_report_fallback_detail(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    text: str,
    reply_markup,
    *,
    edit_existing: bool,
    query=None,
) -> None:
    try:
        if edit_existing and _message_has_photo(message):
            await _replace_photo_with_text(message, context, user_id, text, reply_markup)
            if query is not None:
                await query.answer()
            return
        await _show_or_edit(message, text, reply_markup, edit_existing=edit_existing)
        if query is not None:
            await query.answer()
    except Exception:
        logger.exception("Could not open Coordinate Space report fallback detail")
        if edit_existing:
            try:
                sent = await message.reply_text(text, reply_markup=reply_markup, do_quote=False)
                chat_id = getattr(sent, "chat_id", getattr(message, "chat_id", None))
                message_id = getattr(sent, "message_id", None)
                if chat_id is not None and message_id is not None:
                    set_active_main_menu_message(context, chat_id, user_id, message_id)
                if query is not None:
                    await query.answer()
                return
            except Exception:
                logger.exception("Could not send Coordinate Space report fallback detail as a new message")
        if query is not None:
            await query.answer("Не удалось открыть отчёт. Попробуйте ещё раз.", show_alert=True)
            return
        raise


async def _handle_coordinate_report_not_found(
    message,
    *,
    lang: str,
    edit_existing: bool,
    query=None,
) -> None:
    if query is not None:
        await query.answer(
            "Report not found. Refresh the list." if lang == "en" else "Отчёт не найден. Обновите список.",
            show_alert=True,
        )
        return
    await _show_or_edit(
        message,
        coordinate_space_report_not_found_text(lang=lang),
        build_coordinate_space_report_not_found_keyboard(lang=lang),
        edit_existing=edit_existing,
    )


async def show_view_samples_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    edit_existing: bool = False,
    page: int = 0,
    back_callback: str = "mydna:root",
) -> None:
    items = _data_store(context).list_samples(user_id)
    lang = get_user_language(context, user_id)
    await _show_or_edit(
        message,
        view_samples_text(items, page, lang=lang),
        build_sample_items_keyboard(items, page, lang=lang, back_callback=back_callback),
        edit_existing=edit_existing,
        parse_mode="HTML",
    )


async def show_my_data_menu(message, context: ContextTypes.DEFAULT_TYPE, user_id: int, *, edit_existing: bool = False) -> None:
    lang = get_user_language(context, user_id)
    sent = await _show_or_edit(
        message,
        my_data_text(lang=lang),
        build_my_data_keyboard(lang=lang),
        edit_existing=edit_existing,
    )
    chat_id = getattr(sent, "chat_id", None)
    message_id = getattr(sent, "message_id", None)
    if chat_id is not None and message_id is not None:
        set_active_main_menu_message(context, int(chat_id), int(user_id), int(message_id))


async def show_coordinates_menu(message, context: ContextTypes.DEFAULT_TYPE, user_id: int, *, edit_existing: bool = False) -> None:
    items = _standalone_my_data_coordinates(_data_store(context), user_id)
    lang = get_user_language(context, user_id)
    await _show_or_edit(
        message,
        coordinates_text(items, lang=lang),
        build_coordinates_keyboard(lang=lang),
        edit_existing=edit_existing,
    )


async def show_view_coordinates_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    edit_existing: bool = False,
    back_callback: str = "mydna:root",
) -> None:
    items = _standalone_my_data_coordinates(_data_store(context), user_id)
    lang = get_user_language(context, user_id)
    await _show_or_edit(
        message,
        view_coordinates_text(items, lang=lang),
        build_coordinate_items_keyboard(items, lang=lang, back_callback=back_callback),
        edit_existing=edit_existing,
    )


async def show_new_g25_profile_menu(message, context: ContextTypes.DEFAULT_TYPE, user_id: int, *, edit_existing: bool = False) -> None:
    lang = get_user_language(context, user_id)
    await _show_or_edit(
        message,
        new_g25_profile_text(lang=lang),
        build_new_g25_profile_keyboard(lang=lang),
        edit_existing=edit_existing,
    )


async def show_add_coordinates_type_menu(message, context: ContextTypes.DEFAULT_TYPE, user_id: int, *, edit_existing: bool = False) -> None:
    lang = get_user_language(context, user_id)
    await _show_or_edit(
        message,
        add_coordinates_type_text(lang=lang),
        build_add_coordinates_type_keyboard(lang=lang),
        edit_existing=edit_existing,
    )


async def show_add_coordinates_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    coordinate_type: str,
    *,
    back_callback: str | None = None,
    add_data_flow: bool = False,
    edit_existing: bool = False,
) -> None:
    lang = get_user_language(context, user_id)
    await _show_or_edit(
        message,
        add_coordinates_text(coordinate_type, lang=lang),
        build_add_coordinates_keyboard(
            back_callback=back_callback or f"{MY_DATA_CALLBACK_PREFIX}:coordinates_add_root",
            add_data_flow=add_data_flow,
            lang=lang,
        ),
        edit_existing=edit_existing,
    )


async def show_extract_coordinates_type_menu(message, context: ContextTypes.DEFAULT_TYPE, user_id: int, *, edit_existing: bool = False) -> None:
    lang = get_user_language(context, user_id)
    await _show_or_edit(
        message,
        extract_coordinates_type_text(lang=lang),
        build_extract_coordinates_type_keyboard(lang=lang),
        edit_existing=edit_existing,
    )


async def show_extract_coordinates_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    coordinate_type: str,
    *,
    edit_existing: bool = False,
) -> None:
    lang = get_user_language(context, user_id)
    await _show_or_edit(
        message,
        extract_coordinates_text(coordinate_type, lang=lang),
        build_extract_coordinates_keyboard(lang=lang),
        edit_existing=edit_existing,
    )


async def show_create_sample_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    raw_file_id: str,
    *,
    edit_existing: bool = False,
) -> None:
    lang = get_user_language(context, user_id)
    raw_file = _data_store(context).get_raw_file(user_id, raw_file_id)
    if raw_file is None:
        text = "Create sample from raw\n\nSaved raw file not found." if lang == "en" else "Создание sample из raw\n\nСохраненный raw-файл не найден."
        markup = build_view_samples_keyboard(lang=lang)
    else:
        text = create_sample_text(raw_file, lang=lang)
        markup = build_create_sample_keyboard(raw_file.asset_id, lang=lang)
    await _show_or_edit(message, text, markup, edit_existing=edit_existing, parse_mode="HTML")


async def show_sample_detail_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    asset_id: str,
    *,
    edit_existing: bool = False,
    back_callback: str | None = None,
) -> None:
    resolved_back_callback = back_callback or _origin_callback(context, PRIVACY_SAMPLES_BACK_KEY, f"{MY_DATA_CALLBACK_PREFIX}:samples_view")
    asset = _data_store(context).get_sample(user_id, asset_id)
    if asset is None:
        lang = get_user_language(context, user_id)
        text = "Sample\n\nSaved sample not found." if lang == "en" else "Sample\n\nСохраненный sample не найден."
        markup = build_view_samples_keyboard(lang=lang, back_callback=_origin_callback(context, PRIVACY_ROOT_BACK_KEY, "mydna:root"))
    else:
        lang = get_user_language(context, user_id)
        raw_file = _data_store(context).get_sample_raw_file(user_id, asset.asset_id)
        text = sample_detail_text(
            asset,
            raw_file=raw_file,
            coordinate_count=len(_visible_my_data_coordinates(_data_store(context).list_sample_coordinates(user_id, asset.asset_id))),
            report_counts=_sample_report_counts(context, user_id, asset.asset_id),
            lang=lang,
        )
        markup = build_sample_detail_keyboard(asset, lang=lang, back_callback=resolved_back_callback)
    await _show_or_edit(message, text, markup, edit_existing=edit_existing, parse_mode="HTML")


async def show_sample_delete_prompt_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    asset_id: str,
    *,
    edit_existing: bool = False,
) -> None:
    lang = get_user_language(context, user_id)
    asset = _data_store(context).get_sample(user_id, asset_id)
    if asset is None:
        text = "Delete sample\n\nSaved sample not found." if lang == "en" else "Удаление sample\n\nСохраненный sample не найден."
        markup = build_view_samples_keyboard(lang=lang)
    else:
        text = sample_delete_prompt_text(asset, lang=lang)
        markup = build_sample_delete_prompt_keyboard(asset.asset_id, lang=lang)
    await _show_or_edit(message, text, markup, edit_existing=edit_existing)


async def show_sample_rename_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    asset_id: str,
    *,
    edit_existing: bool = False,
) -> None:
    lang = get_user_language(context, user_id)
    asset = _data_store(context).get_sample(user_id, asset_id)
    if asset is None:
        text = "Rename sample\n\nSaved sample not found." if lang == "en" else "Переименование sample\n\nСохраненный sample не найден."
        markup = build_view_samples_keyboard(lang=lang)
    else:
        text = sample_rename_text(asset, lang=lang)
        markup = build_sample_rename_keyboard(asset.asset_id, lang=lang)
    await _show_or_edit(message, text, markup, edit_existing=edit_existing)


async def show_sample_snp_lookup_input_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    sample_id: str,
    *,
    chat_id: int | None = None,
    edit_existing: bool = False,
) -> None:
    lang = get_user_language(context, user_id)
    sample = _data_store(context).get_sample(user_id, sample_id)
    if sample is None:
        text = "SNP lookup\n\nSaved sample not found." if lang == "en" else "Поиск SNP\n\nСохранённый sample не найден."
        markup = build_view_samples_keyboard(lang=lang)
        await _show_or_edit(message, text, markup, edit_existing=edit_existing)
        return

    raw_file = _data_store(context).get_sample_raw_file(user_id, sample.asset_id)
    if raw_file is None:
        await _show_or_edit(
            message,
            sample_snp_lookup_no_raw_text(sample, lang=lang),
            build_sample_snp_lookup_input_keyboard(sample.asset_id, lang=lang),
            edit_existing=edit_existing,
            parse_mode="HTML",
        )
        return

    sent = await _show_or_edit(
        message,
        sample_snp_lookup_input_text(sample, lang=lang),
        build_sample_snp_lookup_input_keyboard(sample.asset_id, lang=lang),
        edit_existing=edit_existing,
        parse_mode="HTML",
    )
    active_chat_id = chat_id if chat_id is not None else getattr(sent, "chat_id", getattr(message, "chat_id", None))
    message_id = getattr(sent, "message_id", getattr(message, "message_id", None))
    if active_chat_id is not None and message_id is not None:
        _flow_store(context).expect(
            int(active_chat_id),
            user_id,
            SAMPLE_SNP_LOOKUP_ACTION,
            int(message_id),
            payload={"sample_id": sample.asset_id},
        )


async def show_sample_attach_raw_picker_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    sample_id: str,
    *,
    edit_existing: bool = False,
) -> None:
    await show_sample_detail_menu(message, context, user_id, sample_id, edit_existing=edit_existing)
    return
    lang = get_user_language(context, user_id)
    sample = _data_store(context).get_sample(user_id, sample_id)
    if sample is None:
        text = "Attach raw file\n\nSaved sample not found." if lang == "en" else "Attach raw file\n\nСохраненный sample не найден."
        markup = build_view_samples_keyboard(lang=lang)
    else:
        items = _data_store(context).list_attachable_raw_files(user_id, sample_id)
        text = sample_attach_raw_picker_text(sample, items)
        markup = build_sample_attach_raw_picker_keyboard(sample.asset_id, items)
    await _show_or_edit(message, text, markup, edit_existing=edit_existing)


async def show_sample_attach_coordinates_picker_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    sample_id: str,
    *,
    edit_existing: bool = False,
) -> None:
    lang = get_user_language(context, user_id)
    sample = _data_store(context).get_sample(user_id, sample_id)
    if sample is None:
        text = "Attach coordinates\n\nSaved sample not found." if lang == "en" else "Выбор координат\n\nСохраненный sample не найден."
        markup = build_view_samples_keyboard(lang=lang)
    else:
        items = _visible_my_data_coordinates(_data_store(context).list_attachable_coordinates(user_id, sample_id))
        text = sample_attach_coordinates_picker_text(sample, items, lang=lang)
        markup = build_sample_attach_coordinates_picker_keyboard(sample.asset_id, items, lang=lang)
    await _show_or_edit(message, text, markup, edit_existing=edit_existing)


async def show_sample_coordinates_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    sample_id: str,
    *,
    edit_existing: bool = False,
) -> None:
    lang = get_user_language(context, user_id)
    sample = _data_store(context).get_sample(user_id, sample_id)
    if sample is None:
        text = "Sample coordinates\n\nSaved sample not found." if lang == "en" else "Координаты sample\n\nСохранённый sample не найден."
        markup = build_view_samples_keyboard(lang=lang)
    else:
        raw_file = _data_store(context).get_sample_raw_file(user_id, sample.asset_id)
        text = sample_coordinates_menu_text(sample, raw_file=raw_file, lang=lang)
        markup = build_sample_coordinates_menu_keyboard(sample.asset_id, lang=lang)
    await _show_or_edit(message, text, markup, edit_existing=edit_existing)


async def show_sample_extract_coordinates_type_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    sample_id: str,
    *,
    edit_existing: bool = False,
) -> None:
    lang = get_user_language(context, user_id)
    sample = _data_store(context).get_sample(user_id, sample_id)
    if sample is None:
        text = "Extract coordinates\n\nSaved sample not found." if lang == "en" else "Извлечение координат\n\nСохранённый sample не найден."
        markup = build_view_samples_keyboard(lang=lang)
    else:
        raw_file = _data_store(context).get_sample_raw_file(user_id, sample.asset_id)
        text = sample_extract_coordinates_type_text(sample, raw_file=raw_file, lang=lang)
        markup = build_sample_extract_coordinates_type_keyboard(sample.asset_id, lang=lang)
    await _show_or_edit(message, text, markup, edit_existing=edit_existing)


async def show_sample_add_coordinates_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    sample_id: str,
    coordinate_type: str,
    *,
    edit_existing: bool = False,
) -> None:
    lang = get_user_language(context, user_id)
    sample = _data_store(context).get_sample(user_id, sample_id)
    if sample is None:
        text = "Add coordinates\n\nSaved sample not found." if lang == "en" else "Добавление координат\n\nСохранённый sample не найден."
        markup = build_view_samples_keyboard(lang=lang)
    else:
        text = sample_add_coordinates_text(sample, coordinate_type, lang=lang)
        markup = build_sample_add_coordinates_keyboard(sample.asset_id, lang=lang)
    await _show_or_edit(message, text, markup, edit_existing=edit_existing)


async def show_sample_add_coordinates_type_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    sample_id: str,
    *,
    edit_existing: bool = False,
) -> None:
    lang = get_user_language(context, user_id)
    sample = _data_store(context).get_sample(user_id, sample_id)
    if sample is None:
        text = "Add coordinates\n\nSaved sample not found." if lang == "en" else "Добавление координат\n\nСохранённый sample не найден."
        markup = build_view_samples_keyboard(lang=lang)
    else:
        text = sample_add_coordinates_type_text(sample, lang=lang)
        markup = build_sample_add_coordinates_type_keyboard(sample.asset_id, lang=lang)
    await _show_or_edit(message, text, markup, edit_existing=edit_existing)


async def show_sample_attached_raws_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    sample_id: str,
    *,
    edit_existing: bool = False,
) -> None:
    await show_sample_detail_menu(message, context, user_id, sample_id, edit_existing=edit_existing)
    return
    lang = get_user_language(context, user_id)
    sample = _data_store(context).get_sample(user_id, sample_id)
    if sample is None:
        text = "Attached raw files\n\nSaved sample not found." if lang == "en" else "Attached raw files\n\nСохраненный sample не найден."
        markup = build_view_samples_keyboard(lang=lang)
    else:
        items = _data_store(context).list_sample_raw_files(user_id, sample_id)
        text = sample_attached_raws_text(sample, items)
        markup = build_sample_attached_raws_keyboard(sample.asset_id)
    await _show_or_edit(message, text, markup, edit_existing=edit_existing)


async def show_sample_attached_coordinates_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    sample_id: str,
    *,
    edit_existing: bool = False,
) -> None:
    lang = get_user_language(context, user_id)
    sample = _data_store(context).get_sample(user_id, sample_id)
    if sample is None:
        text = "Attached coordinates\n\nSaved sample not found." if lang == "en" else "Привязанные координаты\n\nСохраненный sample не найден."
        markup = build_view_samples_keyboard(lang=lang)
    else:
        items = _visible_my_data_coordinates(_data_store(context).list_sample_coordinates(user_id, sample_id))
        if len(items) == 1:
            await show_sample_coordinate_detail_menu(
                message,
                context,
                user_id,
                sample.asset_id,
                items[0].asset_id,
                back_callback=f"{MY_DATA_CALLBACK_PREFIX}:sample_item:{sample.asset_id}",
                edit_existing=edit_existing,
            )
            return
        text = sample_attached_coordinates_text(sample, items)
        text = sample_attached_coordinates_text(sample, items, lang=lang)
        markup = build_sample_attached_coordinates_keyboard(sample.asset_id, items, lang=lang)
    await _show_or_edit(message, text, markup, edit_existing=edit_existing)


async def show_sample_coordinate_detail_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    sample_id: str,
    coordinate_id: str,
    *,
    back_callback: str | None = None,
    edit_existing: bool = False,
) -> None:
    lang = get_user_language(context, user_id)
    asset = _data_store(context).get_coordinate(user_id, coordinate_id)
    resolved_back_callback = back_callback or f"{MY_DATA_CALLBACK_PREFIX}:sample_view_coords:{sample_id}"
    if asset is None:
        text = "Coordinates\n\nAttached record not found." if lang == "en" else "Координаты\n\nПривязанная запись не найдена."
        markup = build_sample_coordinate_detail_keyboard(resolved_back_callback, lang=lang)
        parse_mode = None
    else:
        if asset.coordinate_type.strip().lower() == "k36":
            text = "Coordinates\n\nK36 coordinates now open in Admixture." if lang == "en" else "Координаты\n\nK36-координаты теперь открываются в разделе Admixture."
            markup = build_sample_coordinate_detail_keyboard(resolved_back_callback, lang=lang)
            parse_mode = None
        else:
            text = coordinate_detail_text(asset, lang=lang)
            markup = build_sample_coordinate_detail_keyboard(resolved_back_callback, lang=lang)
            parse_mode = "HTML"
    await _show_or_edit(message, text, markup, edit_existing=edit_existing, parse_mode=parse_mode)


async def show_sample_reports_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    sample_id: str,
    *,
    edit_existing: bool = False,
    back_callback: str | None = None,
) -> None:
    resolved_back_callback = back_callback or _origin_callback(context, PRIVACY_SAMPLES_BACK_KEY, f"{MY_DATA_CALLBACK_PREFIX}:sample_item:{sample_id}")
    sample = _data_store(context).get_sample(user_id, sample_id)
    if sample is None:
        lang = get_user_language(context, user_id)
        text = "Reports\n\nSaved sample not found." if lang == "en" else "Reports\n\nСохраненный sample не найден."
        markup = build_view_samples_keyboard(lang=lang, back_callback=_origin_callback(context, PRIVACY_ROOT_BACK_KEY, "mydna:root"))
    else:
        lang = get_user_language(context, user_id)
        text = sample_reports_text(sample, lang=lang)
        markup = build_sample_reports_keyboard(sample.asset_id, lang=lang, back_callback=resolved_back_callback)
    await _show_or_edit(message, text, markup, edit_existing=edit_existing)


async def show_sample_saved_section_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    sample_id: str,
    *,
    title: str,
    description: str,
    edit_existing: bool = False,
) -> None:
    lang = get_user_language(context, user_id)
    sample = _data_store(context).get_sample(user_id, sample_id)
    if sample is None:
        text = f"{title}\n\n" + ("Saved sample not found." if lang == "en" else "Сохраненный sample не найден.")
        markup = build_view_samples_keyboard(lang=lang)
    else:
        text = sample_saved_section_text(sample, title, description, lang=lang)
        markup = build_sample_saved_section_keyboard(sample.asset_id, lang=lang)
    await _show_or_edit(message, text, markup, edit_existing=edit_existing)


async def show_sample_coordinate_space_reports_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    sample_id: str,
    *,
    edit_existing: bool = False,
) -> None:
    lang = get_user_language(context, user_id)
    sample = _data_store(context).get_sample(user_id, sample_id)
    if sample is None:
        text = "🧭 Coordinate spaces\n\nSaved sample not found." if lang == "en" else "🧭 Coordinate spaces\n\nСохраненный sample не найден."
        markup = build_view_samples_keyboard(lang=lang)
    else:
        reports = _coordinate_space_report_store(context).list_results(user_id, sample.asset_id)
        text = sample_coordinate_space_reports_text(sample, reports, lang=lang)
        markup = build_sample_coordinate_space_reports_keyboard(sample.asset_id, reports, lang=lang)
    if edit_existing and _message_has_photo(message):
        await _replace_photo_with_text(message, context, user_id, text, markup)
        return
    await _show_or_edit(message, text, markup, edit_existing=edit_existing)


async def show_coordinate_space_report_detail_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    report_id: str,
    *,
    edit_existing: bool = False,
    query=None,
) -> None:
    lang = get_user_language(context, user_id)
    report = _coordinate_space_report_store(context).find_result(user_id, report_id)
    if report is None:
        await _handle_coordinate_report_not_found(
            message,
            lang=lang,
            edit_existing=edit_existing,
            query=query,
        )
        return
    else:
        report_store = _coordinate_space_report_store(context)
        image_path = report_store.resolve_image_path(report)
        markup = build_coordinate_space_report_detail_keyboard(report.result_id, report.sample_id, lang=lang)
        if image_path is not None and image_path.exists():
            caption = coordinate_space_report_visual_caption(report)
            if edit_existing and _message_has_photo(message):
                try:
                    await message.edit_caption(caption=caption, reply_markup=markup)
                    if query is not None:
                        await query.answer()
                except Exception:
                    logger.exception("Could not edit Coordinate Space visual report caption")
                    text = coordinate_space_report_detail_text(report)
                    await _show_coordinate_report_fallback_detail(
                        message,
                        context,
                        user_id,
                        text,
                        markup,
                        edit_existing=edit_existing,
                        query=query,
                    )
                return
            try:
                with image_path.open("rb") as handle:
                    sent = await message.reply_photo(photo=handle, caption=caption, reply_markup=markup, do_quote=False)
                if query is not None:
                    await query.answer()
                chat_id = getattr(sent, "chat_id", getattr(message, "chat_id", None))
                message_id = getattr(sent, "message_id", None)
                if chat_id is not None and message_id is not None:
                    set_active_main_menu_message(context, chat_id, user_id, message_id)
                if edit_existing:
                    try:
                        await message.delete()
                    except Exception:
                        logger.exception("Could not delete Coordinate Space reports list message after visual detail")
                return
            except Exception:
                logger.exception("Could not open Coordinate Space visual report detail")
        text = coordinate_space_report_detail_text(report)
    await _show_coordinate_report_fallback_detail(
        message,
        context,
        user_id,
        text,
        markup,
        edit_existing=edit_existing,
        query=query,
    )


async def show_coordinate_space_report_delete_prompt_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    report_id: str,
    *,
    edit_existing: bool = False,
    query=None,
) -> None:
    lang = get_user_language(context, user_id)
    report = _coordinate_space_report_store(context).find_result(user_id, report_id)
    if report is None:
        await _handle_coordinate_report_not_found(
            message,
            lang=lang,
            edit_existing=edit_existing,
            query=query,
        )
        return
    else:
        text = coordinate_space_report_delete_prompt_text()
        markup = build_coordinate_space_report_delete_prompt_keyboard(report.result_id, lang=lang)
    if edit_existing and _message_has_photo(message):
        await _replace_photo_with_text(message, context, user_id, text, markup)
        if query is not None:
            await query.answer()
        return
    await _show_or_edit(message, text, markup, edit_existing=edit_existing)
    if query is not None:
        await query.answer()


async def show_sample_matching_reports_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    sample_id: str,
    *,
    edit_existing: bool = False,
) -> None:
    lang = get_user_language(context, user_id)
    sample = _data_store(context).get_sample(user_id, sample_id)
    if sample is None:
        text = "Matching reports\n\nSaved sample not found." if lang == "en" else "Отчеты Matching\n\nСохраненный sample не найден."
        markup = build_view_samples_keyboard(lang=lang)
    else:
        matches = _matching_store(context).list_matches_for_sample(user_id, sample.asset_id)
        text = sample_matching_reports_text(sample, matches, lang=lang)
        markup = build_sample_matching_reports_keyboard(sample.asset_id, matches, lang=lang)
    await _show_or_edit(message, text, markup, edit_existing=edit_existing)


async def show_sample_matching_detail_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    match_id: str,
    *,
    edit_existing: bool = False,
) -> None:
    lang = get_user_language(context, user_id)
    record = _matching_store(context).find_match(user_id, match_id)
    if record is None:
        text = "Matching report\n\nSaved matching report not found." if lang == "en" else "Отчет Matching\n\nСохраненный matching report не найден."
        markup = build_view_samples_keyboard(lang=lang)
    else:
        text = saved_match_detail_text(record)
        markup = build_sample_matching_detail_keyboard(record, lang=lang)
    await _show_or_edit(message, text, markup, edit_existing=edit_existing, parse_mode="HTML")


async def show_upload_raw_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    back_callback: str | None = None,
    add_data_flow: bool = False,
    edit_existing: bool = False,
) -> None:
    lang = get_user_language(context, user_id)
    await _show_or_edit(
        message,
        upload_raw_text(lang=lang),
        build_upload_raw_keyboard(
            back_callback=back_callback or f"{MY_DATA_CALLBACK_PREFIX}:samples_view",
            add_data_flow=add_data_flow,
            lang=lang,
        ),
        edit_existing=edit_existing,
    )


async def show_raw_file_detail_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    asset_id: str,
    *,
    back_callback: str | None = None,
    show_sample_link: bool = True,
    edit_existing: bool = False,
) -> None:
    lang = get_user_language(context, user_id)
    asset = _data_store(context).get_raw_file(user_id, asset_id)
    if asset is None:
        text = "Raw file\n\nSaved raw file not found." if lang == "en" else "Raw-файл\n\nСохраненный raw-файл не найден."
        markup = build_view_samples_keyboard(lang=lang)
    else:
        sample = _data_store(context).get_sample_by_raw_file(user_id, asset.asset_id)
        text = raw_file_detail_text(asset, linked_sample=sample, lang=lang)
        markup = build_raw_file_detail_keyboard(
            asset.asset_id,
            sample_id=sample.asset_id if sample is not None else None,
            back_callback=back_callback,
            show_sample_link=show_sample_link,
            lang=lang,
        )
    await _show_or_edit(message, text, markup, edit_existing=edit_existing)


async def show_raw_file_delete_prompt_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    asset_id: str,
    *,
    edit_existing: bool = False,
) -> None:
    lang = get_user_language(context, user_id)
    asset = _data_store(context).get_raw_file(user_id, asset_id)
    if asset is None:
        text = "Delete raw file\n\nSaved raw file not found." if lang == "en" else "Удаление raw-файла\n\nСохраненный raw-файл не найден."
        markup = build_view_samples_keyboard(lang=lang)
    else:
        sample = _data_store(context).get_sample_by_raw_file(user_id, asset.asset_id)
        text = raw_file_delete_prompt_text(asset, linked_sample=sample, lang=lang)
        markup = build_raw_file_delete_prompt_keyboard(asset.asset_id, allow_delete=sample is None, lang=lang)
    await _show_or_edit(message, text, markup, edit_existing=edit_existing)


async def show_raw_file_rename_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    asset_id: str,
    *,
    edit_existing: bool = False,
) -> None:
    lang = get_user_language(context, user_id)
    asset = _data_store(context).get_raw_file(user_id, asset_id)
    if asset is None:
        text = "Rename raw file\n\nSaved raw file not found." if lang == "en" else "Переименование raw-файла\n\nСохраненный raw-файл не найден."
        markup = build_view_samples_keyboard(lang=lang)
    else:
        text = raw_file_rename_text(asset, lang=lang)
        markup = build_raw_file_rename_keyboard(asset.asset_id, lang=lang)
    await _show_or_edit(message, text, markup, edit_existing=edit_existing)


async def show_coordinate_detail_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    asset_id: str,
    *,
    edit_existing: bool = False,
    back_callback: str | None = None,
) -> None:
    resolved_back_callback = back_callback or _origin_callback(context, PRIVACY_G25_BACK_KEY, f"{MY_DATA_CALLBACK_PREFIX}:coordinates_view")
    lang = get_user_language(context, user_id)
    asset = _data_store(context).get_coordinate(user_id, asset_id)
    if asset is None:
        text = "Coordinates\n\nSaved coordinates not found." if lang == "en" else "Координаты\n\nСохраненные координаты не найдены."
        markup = build_view_coordinates_keyboard(lang=lang, back_callback=_origin_callback(context, PRIVACY_ROOT_BACK_KEY, "mydna:root"))
        parse_mode = None
    elif asset.coordinate_type.strip().lower() == "k36":
        text = "Coordinates\n\nK36 coordinates now open in Admixture." if lang == "en" else "Координаты\n\nK36-координаты теперь открываются в разделе Admixture."
        markup = build_view_coordinates_keyboard(lang=lang, back_callback=_origin_callback(context, PRIVACY_ROOT_BACK_KEY, "mydna:root"))
        parse_mode = None
    else:
        text = coordinate_detail_text(asset, lang=lang)
        markup = build_coordinate_detail_keyboard(asset.asset_id, lang=lang, back_callback=resolved_back_callback)
        parse_mode = "HTML"
    await _show_or_edit(message, text, markup, edit_existing=edit_existing, parse_mode=parse_mode)


async def show_coordinate_delete_prompt_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    asset_id: str,
    *,
    edit_existing: bool = False,
) -> None:
    lang = get_user_language(context, user_id)
    asset = _data_store(context).get_coordinate(user_id, asset_id)
    if asset is None:
        text = "Delete coordinates\n\nSaved coordinates not found." if lang == "en" else "Удаление координат\n\nСохраненные координаты не найдены."
        markup = build_view_coordinates_keyboard()
    else:
        text = coordinate_delete_prompt_text(asset, lang=lang)
        markup = build_coordinate_delete_prompt_keyboard(asset.asset_id, lang=lang)
    await _show_or_edit(message, text, markup, edit_existing=edit_existing)


async def show_coordinate_rename_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    asset_id: str,
    *,
    edit_existing: bool = False,
) -> None:
    lang = get_user_language(context, user_id)
    asset = _data_store(context).get_coordinate(user_id, asset_id)
    if asset is None:
        text = "Rename coordinates\n\nSaved coordinates not found." if lang == "en" else "Переименование координат\n\nСохраненные координаты не найдены."
        markup = build_view_coordinates_keyboard()
    else:
        text = coordinate_rename_text(asset, lang=lang)
        markup = build_coordinate_rename_keyboard(asset.asset_id, lang=lang)
    await _show_or_edit(message, text, markup, edit_existing=edit_existing)


def _is_data_input_action(action: str) -> bool:
    return action in {
        SAMPLE_CREATE_ACTION,
        SAMPLE_RENAME_ACTION,
        SAMPLE_SNP_LOOKUP_ACTION,
        SAMPLE_ATTACH_COORD_ACTION,
        RAW_UPLOAD_ACTION,
        RAW_RENAME_ACTION,
        COORDINATE_ADD_ACTION,
        COORDINATE_EXTRACT_ACTION,
        COORDINATE_RENAME_ACTION,
        *QUICK_G25_CALLBACK_ACTIONS,
    }


async def my_data_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None or query.message is None:
        return
    if not query.data.startswith(f"{MY_DATA_CALLBACK_PREFIX}:"):
        return
    if not await ensure_active_main_menu(update, context):
        return
    if update.effective_chat is None or update.effective_user is None:
        return

    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    lang = get_user_language(context, user_id)
    parts = query.data.split(":", 2)
    action = parts[1] if len(parts) > 1 else ""
    asset_id = parts[2] if len(parts) > 2 else ""
    if action not in COORDINATE_REPORT_CALLBACK_ACTIONS:
        await query.answer()

    if action == "cancel":
        _clear_my_data_pending(context, chat_id, user_id)
        try:
            await query.message.delete()
        except Exception:
            await query.message.edit_text("Отменено.")
        return

    if not _is_data_input_action(action):
        _clear_my_data_pending(context, chat_id, user_id)

    if action == "qg25_create_sample":
        payload = _quick_g25_payload(context, chat_id, user_id)
        if payload is None:
            await query.answer("Result expired. Run extraction again." if lang == "en" else "Результат устарел. Запустите извлечение ещё раз.", show_alert=True)
            return
        raw_temp_path = Path(payload["raw_temp_path"])
        if not payload["raw_temp_path"] or not raw_temp_path.is_file():
            _flow_store(context).clear(chat_id, user_id)
            await query.answer("Raw file expired. Run extraction again." if lang == "en" else "Raw-файл устарел. Запустите извлечение ещё раз.", show_alert=True)
            return
        raw_asset = _data_store(context).save_raw_file(
            user_id,
            raw_temp_path,
            original_file_name=payload["raw_file_name"],
            display_name=payload["raw_display_name"],
        )
        coordinate = _save_quick_g25_coordinate(context, user_id, payload)
        sample = _data_store(context).save_sample(
            user_id,
            display_name=payload["target_name"],
            raw_file_id=raw_asset.asset_id,
        )
        if sample is None:
            _data_store(context).delete_coordinate(user_id, coordinate.asset_id)
            _data_store(context).delete_raw_file(user_id, raw_asset.asset_id)
            _record_dna_lab_usage(update, context, action="qg25_create_sample", success=False)
            await query.answer("Could not create Sample." if lang == "en" else "Не удалось создать Sample.", show_alert=True)
            return
        updated_sample = _data_store(context).attach_coordinate_to_sample(user_id, sample.asset_id, coordinate.asset_id)
        if updated_sample is None:
            _data_store(context).delete_sample(user_id, sample.asset_id)
            _data_store(context).delete_coordinate(user_id, coordinate.asset_id)
            _data_store(context).delete_raw_file(user_id, raw_asset.asset_id)
            _record_dna_lab_usage(update, context, action="qg25_create_sample", success=False)
            await query.answer("Could not attach G25 to Sample." if lang == "en" else "Не удалось привязать G25 к Sample.", show_alert=True)
            return
        _cleanup_quick_g25_raw_temp(context, payload)
        _flow_store(context).clear(chat_id, user_id)
        await query.message.edit_text(
            quick_g25_saved_text(payload["target_name"], payload["g25_line"], sample_name=updated_sample.display_name, lang=lang),
            parse_mode="HTML",
            reply_markup=build_sample_detail_keyboard(updated_sample, lang=lang),
        )
        _record_dna_lab_usage(update, context, action="qg25_create_sample")
        return
    if action == "qg25_save_g25_library":
        payload = _quick_g25_payload(context, chat_id, user_id)
        if payload is None:
            await query.answer("Result expired. Run extraction again." if lang == "en" else "Результат устарел. Запустите извлечение ещё раз.", show_alert=True)
            return
        try:
            saved = _save_quick_g25_coordinate(context, user_id, payload)
        except Exception:
            logger.exception("Quick G25 library save failed")
            _record_dna_lab_usage(update, context, action="qg25_save_g25_library", success=False)
            await query.answer("Could not save the G25 profile." if lang == "en" else "Не удалось сохранить G25-профиль.", show_alert=True)
            return
        _cleanup_quick_g25_raw_temp(context, payload)
        _flow_store(context).clear(chat_id, user_id)
        await query.message.edit_text(
            quick_g25_saved_text(
                payload["target_name"],
                payload["g25_line"],
                g25_title=saved.display_name,
                lang=lang,
            ),
            parse_mode="HTML",
        )
        _record_dna_lab_usage(update, context, action="qg25_save_g25_library")
        return

    if action == "root":
        _clear_privacy_origin(context)
        await show_my_data_menu(query.message, context, user_id, edit_existing=True)
        return
    if action == "samples":
        await show_view_samples_menu(
            query.message,
            context,
            user_id,
            edit_existing=True,
            back_callback=_origin_callback(context, PRIVACY_ROOT_BACK_KEY, "mydna:root"),
        )
        return
    if action == "samples_view":
        await show_view_samples_menu(
            query.message,
            context,
            user_id,
            edit_existing=True,
            back_callback=_origin_callback(context, PRIVACY_ROOT_BACK_KEY, "mydna:root"),
        )
        return
    if action == "samples_page":
        try:
            page = int(asset_id)
        except ValueError:
            page = 0
        await show_view_samples_menu(
            query.message,
            context,
            user_id,
            edit_existing=True,
            page=page,
            back_callback=_origin_callback(context, PRIVACY_ROOT_BACK_KEY, "mydna:root"),
        )
        return
    if action == "samples_create":
        _flow_store(context).expect(chat_id, user_id, RAW_UPLOAD_ACTION, query.message.message_id)
        await show_upload_raw_menu(query.message, context, user_id, edit_existing=True)
        return
    if action == "sample_item":
        await show_sample_detail_menu(query.message, context, user_id, asset_id, edit_existing=True)
        return
    if action == "snp":
        await show_sample_snp_lookup_input_menu(
            query.message,
            context,
            user_id,
            asset_id,
            chat_id=chat_id,
            edit_existing=True,
        )
        return
    if action == "sample_attach_raws_disabled":
        await query.answer("Sample is already attached to one raw file." if lang == "en" else "Sample уже привязан к одному raw file.", show_alert=True)
        return
    if action == "sample_attach_raw_choose_disabled":
        await query.answer("A sample can have only one source raw." if lang == "en" else "У sample может быть только один source raw.", show_alert=True)
        return
        sample_id = str(_flow_store(context).get_payload(chat_id, user_id).get("sample_id") or "").strip()
        if not sample_id:
            await query.answer("Open the sample again." if lang == "en" else "Откройте sample заново.", show_alert=True)
            return
        asset = _data_store(context).attach_raw_file_to_sample(user_id, sample_id, asset_id)
        if asset is None:
            await query.answer("Could not attach the raw file." if lang == "en" else "Не удалось привязать raw file.", show_alert=True)
            return
        _flow_store(context).clear(chat_id, user_id)
        await show_sample_detail_menu(query.message, context, user_id, sample_id, edit_existing=True)
        return
    if action == "sample_view_raws_disabled":
        await show_sample_detail_menu(query.message, context, user_id, asset_id, edit_existing=True)
        return
        await show_sample_attached_raws_menu(query.message, context, user_id, asset_id, edit_existing=True)
        return
    if action == "sample_attach_coords":
        await show_sample_coordinates_menu(query.message, context, user_id, asset_id, edit_existing=True)
        return
    if action in {"sample_coords_extract_root", "scx"}:
        await show_sample_extract_coordinates_type_menu(query.message, context, user_id, asset_id, edit_existing=True)
        return
    if action in {"sample_coords_extract_type", "scxt"}:
        coordinate_type, _, sample_id = asset_id.partition("|")
        sample = _data_store(context).get_sample(user_id, sample_id)
        if sample is None:
            await query.answer("Open the sample again." if lang == "en" else "Откройте sample заново.", show_alert=True)
            return
        raw_file = _data_store(context).get_sample_raw_file(user_id, sample.asset_id)
        if raw_file is None:
            await query.answer("The sample has no source raw." if lang == "en" else "У sample не найден исходный raw.", show_alert=True)
            return
        raw_path = _data_store(context).resolve_raw_file_path(raw_file)
        if not raw_path.exists():
            await query.answer("Source raw file not found." if lang == "en" else "Файл source raw не найден.", show_alert=True)
            return
        await query.edit_message_text(
            (
                f"Extract coordinates\n\nSample: {sample.display_name}\nSource raw: {raw_file.display_name}\n\nExtracting {coordinate_type.upper()} coordinates..."
                if lang == "en"
                else f"Извлечение координат\n\nSample: {sample.display_name}\nИсходный raw: {raw_file.display_name}\n\nИзвлекаю {coordinate_type.upper()}-координаты..."
            ),
        )
        try:
            result = _g25_service(context).extract_coordinates_from_file(raw_path, sample.display_name, coordinate_type)
            coordinate = _data_store(context).save_coordinate(
                user_id,
                display_name=sample.display_name,
                target_name=result.target_name,
                coordinate_type=coordinate_type,
                g25_line=result.simulated_g25_line,
                input_mode=result.input_mode,
            )
            updated_sample = _data_store(context).attach_coordinate_to_sample(user_id, sample.asset_id, coordinate.asset_id)
        except G25CommandError as exc:
            if coordinate_type == "g25":
                _record_g25_usage(update, context, input_mode="raw-file", success=False, query=sample.display_name)
            await query.message.edit_text(
                (f"Could not extract coordinates.\n\n{exc}" if lang == "en" else f"Не удалось извлечь координаты.\n\n{exc}"),
                reply_markup=build_sample_coordinates_menu_keyboard(sample.asset_id, lang=lang),
            )
            return
        except Exception:
            logger.exception("Sample coordinate extraction failed")
            if coordinate_type == "g25":
                _record_g25_usage(update, context, input_mode="raw-file", success=False, query=sample.display_name)
            await query.message.edit_text(
                "Could not extract coordinates from the source raw. Try again." if lang == "en" else "Не удалось извлечь координаты из исходного raw. Попробуйте ещё раз.",
                reply_markup=build_sample_coordinates_menu_keyboard(sample.asset_id, lang=lang),
            )
            return
        if updated_sample is None:
            if coordinate_type == "g25":
                _record_g25_usage(update, context, input_mode="raw-file", success=False, query=sample.display_name)
            await query.message.edit_text(
                "Coordinates were extracted, but could not be attached to the sample." if lang == "en" else "Координаты извлечены, но не удалось привязать их к sample.",
                reply_markup=build_sample_coordinates_menu_keyboard(sample.asset_id, lang=lang),
            )
            return
        if coordinate_type == "g25":
            _record_g25_usage(update, context, input_mode=result.input_mode, success=True, query=result.target_name)
        await _refresh_sample_detail(context, chat_id, user_id, query.message.message_id, updated_sample)
        return
    if action in {"sample_coords_add_manual", "scm"}:
        await show_sample_add_coordinates_type_menu(query.message, context, user_id, asset_id, edit_existing=True)
        return
    if action in {"sample_coords_add_type", "scmt"}:
        coordinate_type, _, sample_id = asset_id.partition("|")
        if not coordinate_type or not sample_id:
            await query.answer("Open the sample again." if lang == "en" else "Откройте sample заново.", show_alert=True)
            return
        _flow_store(context).expect(
            chat_id,
            user_id,
            COORDINATE_ADD_ACTION,
            query.message.message_id,
            payload={"sample_id": sample_id, "coordinate_type": coordinate_type},
        )
        await show_sample_add_coordinates_menu(
            query.message,
            context,
            user_id,
            sample_id,
            coordinate_type,
            edit_existing=True,
        )
        return
    if action in {"sample_coords_attach_saved", "scl"}:
        _flow_store(context).expect(
            chat_id,
            user_id,
            SAMPLE_ATTACH_COORD_ACTION,
            query.message.message_id,
            payload={"sample_id": asset_id},
        )
        await show_sample_attach_coordinates_picker_menu(query.message, context, user_id, asset_id, edit_existing=True)
        return
    if action == "sample_attach_coord_choose":
        sample_id = str(_flow_store(context).get_payload(chat_id, user_id).get("sample_id") or "").strip()
        if not sample_id:
            await query.answer("Open the sample again." if lang == "en" else "Откройте sample заново.", show_alert=True)
            return
        asset = _data_store(context).attach_coordinate_to_sample(user_id, sample_id, asset_id)
        if asset is None:
            await query.answer("Could not attach coordinates." if lang == "en" else "Не удалось привязать coordinates.", show_alert=True)
            return
        _flow_store(context).clear(chat_id, user_id)
        await show_sample_detail_menu(query.message, context, user_id, sample_id, edit_existing=True)
        return
    if action == "sample_view_coords":
        await show_sample_attached_coordinates_menu(query.message, context, user_id, asset_id, edit_existing=True)
        return
    if action == "sample_reports":
        await show_sample_reports_menu(query.message, context, user_id, asset_id, edit_existing=True)
        return
    if action == "sample_admixture":
        await show_sample_admixture_reports_menu(
            query.message,
            context,
            user_id,
            asset_id,
            origin="my_data",
            edit_existing=True,
        )
        return
    if action == "sample_modeling":
        await show_sample_saved_section_menu(
            query.message,
            context,
            user_id,
            asset_id,
            title="AdmixLab reports",
            description="No saved AdmixLab reports for this sample yet." if lang == "en" else "Пока нет сохранённых отчётов AdmixLab для этого sample.",
            edit_existing=True,
        )
        return
    if action == "sample_pca_results":
        await show_sample_coordinate_space_reports_menu(query.message, context, user_id, asset_id, edit_existing=True)
        return
    if action in {COORD_REPORT_OPEN_ACTION, "sample_coord_report"}:
        try:
            await show_coordinate_space_report_detail_menu(query.message, context, user_id, asset_id, edit_existing=True, query=query)
        except Exception:
            logger.exception("Could not open Coordinate Space report detail")
            await query.answer("Не удалось открыть отчёт. Попробуйте ещё раз.", show_alert=True)
        return
    if action in {COORD_REPORT_DELETE_PROMPT_ACTION, "sample_coord_report_delete_prompt"}:
        await show_coordinate_space_report_delete_prompt_menu(query.message, context, user_id, asset_id, edit_existing=True, query=query)
        return
    if action in {COORD_REPORT_DELETE_CONFIRM_ACTION, "sample_coord_report_delete_confirm"}:
        deleted_report = _coordinate_space_report_store(context).delete_result(user_id, asset_id)
        if deleted_report is None:
            await query.answer("Report not found." if lang == "en" else "Отчёт не найден.", show_alert=True)
            return
        await query.answer("✅ Отчёт удалён", show_alert=True)
        await show_sample_coordinate_space_reports_menu(
            query.message,
            context,
            user_id,
            deleted_report.sample_id,
            edit_existing=True,
        )
        return
    if action == "sample_matching":
        await show_sample_matching_reports_menu(query.message, context, user_id, asset_id, edit_existing=True)
        return
    if action == "sample_match":
        await show_sample_matching_detail_menu(query.message, context, user_id, asset_id, edit_existing=True)
        return
    if action == "sample_traits":
        await show_sample_trait_reports_menu(
            query.message,
            context,
            user_id,
            asset_id,
            edit_existing=True,
        )
        return
    if action == "sample_haplogroups":
        await show_sample_haplogroup_reports_menu(
            query.message,
            context,
            user_id,
            sample_id=asset_id,
            back_callback=f"{MY_DATA_CALLBACK_PREFIX}:sample_reports:{asset_id}",
            edit_existing=True,
        )
        return
    if action == "sample_saved_reports":
        await show_sample_saved_section_menu(
            query.message,
            context,
            user_id,
            asset_id,
            title="Reports",
            description="No saved reports for this sample yet." if lang == "en" else "Пока нет сохранённых отчётов для этого sample.",
            edit_existing=True,
        )
        return
    if action in {"sample_coordinate_item", "sci"}:
        if "|" in asset_id:
            sample_id, _, coordinate_id = asset_id.partition("|")
        else:
            coordinate_id = asset_id
            sample = _data_store(context).find_sample_by_coordinate(user_id, coordinate_id)
            sample_id = sample.asset_id if sample is not None else ""
        if not sample_id or not coordinate_id:
            await query.answer("Open sample coordinates again." if lang == "en" else "Откройте координаты sample заново.", show_alert=True)
            return
        await show_sample_coordinate_detail_menu(
            query.message,
            context,
            user_id,
            sample_id,
            coordinate_id,
            edit_existing=True,
        )
        return
    if action == "sample_rename":
        _flow_store(context).expect(
            chat_id,
            user_id,
            SAMPLE_RENAME_ACTION,
            query.message.message_id,
            payload={"asset_id": asset_id},
        )
        await show_sample_rename_menu(query.message, context, user_id, asset_id, edit_existing=True)
        return
    if action == "sample_delete_prompt":
        await show_sample_delete_prompt_menu(query.message, context, user_id, asset_id, edit_existing=True)
        return
    if action == "sample_delete_confirm":
        deleted = _data_store(context).delete_sample(user_id, asset_id)
        if deleted:
            await show_view_samples_menu(query.message, context, user_id, edit_existing=True)
        else:
            await query.answer("Sample not found." if lang == "en" else "Sample не найден.", show_alert=True)
        return
    if action == "raw_files":
        await _redirect_legacy_branch(query, context, user_id, "Raw files now open through a sample." if lang == "en" else "Raw-файлы теперь открываются через sample.")
        return
    if action == "raw_files_view":
        await _redirect_legacy_branch(query, context, user_id, "Raw files now open through a sample." if lang == "en" else "Raw-файлы теперь открываются через sample.")
        return
    if action == "raw_files_upload":
        from_add_data = asset_id == "add_data"
        from_root = asset_id == "root"
        _flow_store(context).expect(chat_id, user_id, RAW_UPLOAD_ACTION, query.message.message_id)
        await show_upload_raw_menu(
            query.message,
            context,
            user_id,
            back_callback="mydna:add_data" if from_add_data else ("mydna:root" if from_root else None),
            add_data_flow=from_add_data,
            edit_existing=True,
        )
        return
    if action == "sfr":
        sample = _data_store(context).get_sample(user_id, asset_id)
        if sample is None or not sample.raw_file_id:
            await query.answer("Source raw not found." if lang == "en" else "Исходный raw не найден.", show_alert=True)
            return
        await show_raw_file_detail_menu(
            query.message,
            context,
            user_id,
            sample.raw_file_id,
            back_callback=f"{MY_DATA_CALLBACK_PREFIX}:sample_item:{sample.asset_id}",
            show_sample_link=False,
            edit_existing=True,
        )
        return
    if action == "raw_file_item":
        await show_raw_file_detail_menu(query.message, context, user_id, asset_id, edit_existing=True)
        return
    if action == "raw_file_create_sample":
        sample = _data_store(context).get_sample_by_raw_file(user_id, asset_id)
        if sample is not None:
            await show_sample_detail_menu(query.message, context, user_id, sample.asset_id, edit_existing=True)
            return
        _flow_store(context).expect(
            chat_id,
            user_id,
            SAMPLE_CREATE_ACTION,
            query.message.message_id,
            payload={"raw_file_id": asset_id},
        )
        await show_create_sample_menu(query.message, context, user_id, asset_id, edit_existing=True)
        return
    if action == "raw_file_send":
        asset = _data_store(context).get_raw_file(user_id, asset_id)
        if asset is None:
            await query.answer("Raw file not found." if lang == "en" else "Raw-файл не найден.", show_alert=True)
            return
        raw_path = _data_store(context).resolve_raw_file_path(asset)
        if not raw_path.exists():
            await query.answer("Stored file is missing." if lang == "en" else "Сохраненный файл не найден на диске.", show_alert=True)
            return
        with raw_path.open("rb") as handle:
            await query.message.reply_document(
                document=InputFile(handle, filename=asset.original_file_name),
                caption=f"Raw file: {asset.display_name}",
                do_quote=False,
            )
        return
    if action == "raw_file_rename":
        _flow_store(context).expect(
            chat_id,
            user_id,
            RAW_RENAME_ACTION,
            query.message.message_id,
            payload={"asset_id": asset_id},
        )
        await show_raw_file_rename_menu(query.message, context, user_id, asset_id, edit_existing=True)
        return
    if action == "raw_file_delete_prompt":
        await show_raw_file_delete_prompt_menu(query.message, context, user_id, asset_id, edit_existing=True)
        return
    if action == "raw_file_delete_confirm":
        sample = _data_store(context).get_sample_by_raw_file(user_id, asset_id)
        if sample is not None:
            await query.answer("Delete the sample built from this raw file first." if lang == "en" else "Сначала удалите sample, который построен на этом raw file.", show_alert=True)
            return
        deleted = _data_store(context).delete_raw_file(user_id, asset_id)
        if deleted:
            await show_view_samples_menu(query.message, context, user_id, edit_existing=True)
        else:
            await query.answer("Raw file not found." if lang == "en" else "Raw-файл не найден.", show_alert=True)
        return
    if action == "coordinates":
        await show_coordinates_menu(query.message, context, user_id, edit_existing=True)
        return
    if action == "coordinates_view":
        await show_view_coordinates_menu(
            query.message,
            context,
            user_id,
            edit_existing=True,
            back_callback=_origin_callback(context, PRIVACY_ROOT_BACK_KEY, "mydna:root"),
        )
        return
    if action == "coordinates_new_profile":
        await show_new_g25_profile_menu(query.message, context, user_id, edit_existing=True)
        return
    if action == "coordinates_add_root":
        await show_add_coordinates_type_menu(query.message, context, user_id, edit_existing=True)
        return
    if action == "coordinates_add_type":
        coordinate_type, _, origin = asset_id.strip().lower().partition(":")
        coordinate_type = coordinate_type or "g25"
        from_add_data = origin == "add_data"
        from_g25_profiles = origin == "g25_profiles"
        _flow_store(context).expect(
            chat_id,
            user_id,
            COORDINATE_ADD_ACTION,
            query.message.message_id,
            payload={"coordinate_type": coordinate_type},
        )
        await show_add_coordinates_menu(
            query.message,
            context,
            user_id,
            coordinate_type,
            back_callback="mydna:add_data" if from_add_data else (f"{MY_DATA_CALLBACK_PREFIX}:coordinates_new_profile" if from_g25_profiles else None),
            add_data_flow=from_add_data or from_g25_profiles,
            edit_existing=True,
        )
        return
    if action == "coordinates_extract_quick":
        from_g25_profiles = asset_id.strip().lower() == "g25_profiles"
        await open_quick_g25_prompt(
            query.message,
            context,
            chat_id,
            user_id,
            back_callback=f"{MY_DATA_CALLBACK_PREFIX}:coordinates_new_profile" if from_g25_profiles else None,
            add_data_flow=from_g25_profiles,
            edit_existing=True,
        )
        return
    if action == "coordinates_extract_root":
        await show_extract_coordinates_type_menu(query.message, context, user_id, edit_existing=True)
        return
    if action == "coordinates_extract_type":
        coordinate_type = asset_id.strip().lower() or "g25"
        _flow_store(context).expect(
            chat_id,
            user_id,
            COORDINATE_EXTRACT_ACTION,
            query.message.message_id,
            payload={"coordinate_type": coordinate_type},
        )
        await show_extract_coordinates_menu(query.message, context, user_id, coordinate_type, edit_existing=True)
        return
    if action == "coordinate_item":
        await show_coordinate_detail_menu(query.message, context, user_id, asset_id, edit_existing=True)
        return
    if action == "coordinate_rename":
        _flow_store(context).expect(
            chat_id,
            user_id,
            COORDINATE_RENAME_ACTION,
            query.message.message_id,
            payload={"asset_id": asset_id},
        )
        await show_coordinate_rename_menu(query.message, context, user_id, asset_id, edit_existing=True)
        return
    if action == "coordinate_delete_prompt":
        await show_coordinate_delete_prompt_menu(query.message, context, user_id, asset_id, edit_existing=True)
        return
    if action == "coordinate_delete_confirm":
        deleted = _data_store(context).delete_coordinate(user_id, asset_id)
        if deleted:
            await show_view_coordinates_menu(query.message, context, user_id, edit_existing=True)
        else:
            await query.answer("Coordinates not found." if lang == "en" else "Координаты не найдены.", show_alert=True)
        return
    # Compatibility branch for old My Data messages. Saved reports now open from
    # the product My DNA -> Reports entrypoint or from a sample card.
    if action == "results":
        await _redirect_legacy_branch(query, context, user_id, "Saved results now live inside sample -> Reports." if lang == "en" else "Сохраненные результаты теперь лежат внутри sample -> Reports.")
        return
    if action == "results_admixture":
        await _redirect_legacy_branch(query, context, user_id, "Saved results now live inside sample -> Reports." if lang == "en" else "Сохраненные результаты теперь лежат внутри sample -> Reports.")
        return
    if action == "results_haplogroups":
        await _redirect_legacy_branch(query, context, user_id, "Saved results now live inside sample -> Reports." if lang == "en" else "Сохраненные результаты теперь лежат внутри sample -> Reports.")
        return
    if action == "results_matches":
        await _redirect_legacy_branch(query, context, user_id, "Saved results now live inside sample -> Reports." if lang == "en" else "Сохраненные результаты теперь лежат внутри sample -> Reports.")
        return
    if action == "results_reports":
        await _redirect_legacy_branch(query, context, user_id, "Saved results now live inside sample -> Reports." if lang == "en" else "Сохраненные результаты теперь лежат внутри sample -> Reports.")


async def _refresh_samples_view(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int, message_id: int) -> None:
    items = _data_store(context).list_samples(user_id)
    lang = get_user_language(context, user_id)
    await _edit_menu_message(
        context,
        chat_id=chat_id,
        message_id=message_id,
        text=view_samples_text(items, lang=lang),
        reply_markup=build_sample_items_keyboard(items, lang=lang),
        parse_mode="HTML",
    )


async def _refresh_coordinates_view(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int, message_id: int) -> None:
    items = _standalone_my_data_coordinates(_data_store(context), user_id)
    lang = get_user_language(context, user_id)
    await _edit_menu_message(
        context,
        chat_id=chat_id,
        message_id=message_id,
        text=view_coordinates_text(items, lang=lang),
        reply_markup=build_coordinate_items_keyboard(items, lang=lang),
    )


async def _refresh_sample_detail(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_id: int,
    message_id: int,
    asset: SampleAsset,
) -> None:
    lang = get_user_language(context, user_id)
    raw_file = _data_store(context).get_sample_raw_file(user_id, asset.asset_id)
    coordinate_count = len(_visible_my_data_coordinates(_data_store(context).list_sample_coordinates(user_id, asset.asset_id)))
    await _edit_menu_message(
        context,
        chat_id=chat_id,
        message_id=message_id,
        text=sample_detail_text(
            asset,
            raw_file=raw_file,
            coordinate_count=coordinate_count,
            report_counts=_sample_report_counts(context, user_id, asset.asset_id),
            lang=lang,
        ),
        reply_markup=build_sample_detail_keyboard(asset, lang=lang),
        parse_mode="HTML",
    )


async def _refresh_raw_file_detail(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_id: int,
    message_id: int,
    asset: RawFileAsset,
) -> None:
    lang = get_user_language(context, user_id)
    sample = _data_store(context).get_sample_by_raw_file(user_id, asset.asset_id)
    await _edit_menu_message(
        context,
        chat_id=chat_id,
        message_id=message_id,
        text=raw_file_detail_text(asset, linked_sample=sample, lang=lang),
        reply_markup=build_raw_file_detail_keyboard(
            asset.asset_id,
            sample_id=sample.asset_id if sample is not None else None,
            back_callback=f"{MY_DATA_CALLBACK_PREFIX}:sample_item:{sample.asset_id}" if sample is not None else None,
            show_sample_link=sample is None,
            lang=lang,
        ),
    )


async def _refresh_coordinate_detail(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_id: int,
    message_id: int,
    asset: CoordinateAsset,
) -> None:
    lang = get_user_language(context, user_id)
    await _edit_menu_message(
        context,
        chat_id=chat_id,
        message_id=message_id,
        text=coordinate_detail_text(asset, lang=lang),
        reply_markup=build_coordinate_detail_keyboard(asset.asset_id, lang=lang),
        parse_mode="HTML",
    )


async def _handle_raw_upload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.message.document is None or update.effective_user is None or update.effective_chat is None:
        return

    document = update.message.document
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    lang = get_user_language(context, user_id)
    menu_message_id = _flow_store(context).get_message_id(chat_id, user_id)
    store = _data_store(context)
    if document.file_size and document.file_size > TELEGRAM_BOT_DOWNLOAD_LIMIT_BYTES:
        _record_dna_lab_usage(update, context, action="raw_upload", success=False, input_mode="file")
        await update.message.reply_text(_raw_file_too_large_text(lang=lang), do_quote=False)
        raise ApplicationHandlerStop
    temp_path = store.build_temp_path(user_id, document.file_name or "input.raw")
    status_message = await update.message.reply_text(
        "File received, saving it to your library..." if lang == "en" else "Файл получен, сохраняю в библиотеку...",
        do_quote=False,
    )

    try:
        telegram_file = await document.get_file()
        await telegram_file.download_to_drive(custom_path=str(temp_path))
        asset = store.save_raw_file(
            user_id,
            temp_path,
            original_file_name=document.file_name or temp_path.name,
            display_name=Path(document.file_name or temp_path.name).stem or "raw-file",
        )
    except RawArchiveError as exc:
        _record_dna_lab_usage(update, context, action="raw_upload", success=False, input_mode="file")
        await update.message.reply_text(_raw_archive_error_text(exc, lang=lang), do_quote=False)
        raise ApplicationHandlerStop
    except Exception:
        logger.exception("My data raw upload failed")
        _record_dna_lab_usage(update, context, action="raw_upload", success=False, input_mode="file")
        await update.message.reply_text("Could not save the raw file. Try again." if lang == "en" else "Не удалось сохранить raw-файл. Попробуйте ещё раз.", do_quote=False)
        raise ApplicationHandlerStop
    finally:
        store.cleanup_temp_file(temp_path)

    try:
        if menu_message_id is not None:
            await _refresh_samples_view(context, chat_id, user_id, menu_message_id)
        await status_message.edit_text(
            create_sample_text(asset, lang=lang),
            reply_markup=build_create_sample_keyboard(asset.asset_id, lang=lang),
        )
        set_active_main_menu_message(context, chat_id, user_id, status_message.message_id)
    except Exception:
        logger.debug("Failed to refresh raw files view", exc_info=True)
    _flow_store(context).expect(
        chat_id,
        user_id,
        SAMPLE_CREATE_ACTION,
        status_message.message_id,
        payload={"raw_file_id": asset.asset_id},
    )
    _record_dna_lab_usage(update, context, action="raw_upload", input_mode="file")
    raise ApplicationHandlerStop


async def _handle_coordinate_add(update: Update, context: ContextTypes.DEFAULT_TYPE, body: str) -> None:
    if update.message is None or update.effective_user is None or update.effective_chat is None:
        return

    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    lang = get_user_language(context, user_id)
    menu_message_id = _flow_store(context).get_message_id(chat_id, user_id)
    payload = _flow_store(context).get_payload(chat_id, user_id)
    sample_id = str(payload.get("sample_id") or "").strip()
    coordinate_type = str(payload.get("coordinate_type") or "g25").strip().lower() or "g25"
    sample = _data_store(context).get_sample(user_id, sample_id) if sample_id else None
    sample_name = sample.display_name if sample is not None else _build_sample_name(update)

    try:
        if coordinate_type == "g25":
            result = _g25_service(context).extract_coordinates_from_text(body, sample_name)
            asset = _data_store(context).save_coordinate(
                user_id,
                display_name=sample.display_name if sample is not None else result.target_name,
                target_name=result.target_name,
                coordinate_type="g25",
                g25_line=result.simulated_g25_line,
                input_mode=result.input_mode,
            )
        elif coordinate_type == "k36":
            target_name = sample_name or "Target"
            asset = _data_store(context).save_coordinate(
                user_id,
                display_name=sample.display_name if sample is not None else target_name,
                target_name=target_name,
                coordinate_type="k36",
                g25_line=body,
                input_mode="manual",
            )
        else:
            _record_dna_lab_usage(update, context, action=COORDINATE_ADD_ACTION, success=False, input_mode="text")
            await update.message.reply_text("This coordinate type is not supported yet." if lang == "en" else "Этот тип координат пока не поддержан.", do_quote=False)
            raise ApplicationHandlerStop
    except G25CommandError as exc:
        _record_dna_lab_usage(update, context, action=COORDINATE_ADD_ACTION, success=False, input_mode="text")
        if coordinate_type == "g25":
            _record_g25_usage(update, context, input_mode="g25-text", success=False, query=sample_name)
        await update.message.reply_text(str(exc), do_quote=False)
        raise ApplicationHandlerStop
    except Exception:
        logger.exception("My data coordinate add failed")
        _record_dna_lab_usage(update, context, action=COORDINATE_ADD_ACTION, success=False, input_mode="text")
        if coordinate_type == "g25":
            _record_g25_usage(update, context, input_mode="g25-text", success=False, query=sample_name)
        await update.message.reply_text("Could not save coordinates. Check the format and try again." if lang == "en" else "Не удалось сохранить координаты. Проверьте формат и попробуйте ещё раз.", do_quote=False)
        raise ApplicationHandlerStop

    if sample is not None:
        updated_sample = _data_store(context).attach_coordinate_to_sample(user_id, sample.asset_id, asset.asset_id)
        if updated_sample is None:
            _flow_store(context).clear(chat_id, user_id)
            _record_dna_lab_usage(update, context, action=COORDINATE_ADD_ACTION, success=False, input_mode="text")
            if coordinate_type == "g25":
                _record_g25_usage(update, context, input_mode=asset.input_mode, success=False, query=asset.target_name)
            await update.message.reply_text("Coordinates were saved, but could not be attached to the sample." if lang == "en" else "Координаты сохранены, но не удалось привязать их к sample.", do_quote=False)
            raise ApplicationHandlerStop
        try:
            if menu_message_id is not None:
                await _refresh_sample_detail(context, chat_id, user_id, menu_message_id, updated_sample)
        except Exception:
            logger.debug("Failed to refresh sample coordinates flow", exc_info=True)
    else:
        await update.message.reply_text(
            (f"Coordinates saved: {asset.display_name}\n<code>{html.escape(asset.g25_line)}</code>" if lang == "en" else f"Координаты сохранены: {asset.display_name}\n<code>{html.escape(asset.g25_line)}</code>"),
            parse_mode="HTML",
            do_quote=False,
        )
        try:
            if menu_message_id is not None:
                await _refresh_coordinates_view(context, chat_id, user_id, menu_message_id)
        except Exception:
            logger.debug("Failed to refresh coordinates library view", exc_info=True)
    _flow_store(context).clear(chat_id, user_id)
    _record_dna_lab_usage(update, context, action=COORDINATE_ADD_ACTION, input_mode="text")
    if coordinate_type == "g25":
        _record_g25_usage(update, context, input_mode=asset.input_mode, success=True, query=asset.target_name)
    raise ApplicationHandlerStop


async def _handle_sample_snp_lookup(update: Update, context: ContextTypes.DEFAULT_TYPE, body: str) -> None:
    if update.message is None or update.effective_user is None or update.effective_chat is None:
        return

    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    lang = get_user_language(context, user_id)
    flow = _flow_store(context)
    menu_message_id = flow.get_message_id(chat_id, user_id)
    payload = flow.get_payload(chat_id, user_id)
    sample_id = str(payload.get("sample_id") or "").strip()
    sample = _data_store(context).get_sample(user_id, sample_id) if sample_id else None
    if sample is None:
        flow.clear(chat_id, user_id)
        await update.message.reply_text(
            "Could not identify the sample. Open My DNA again." if lang == "en" else "Не удалось определить sample. Откройте My DNA заново.",
            do_quote=False,
        )
        raise ApplicationHandlerStop

    rsid = normalize_sample_snp_rsid(body)
    if rsid is None:
        if menu_message_id is not None:
            await _edit_menu_message(
                context,
                chat_id=chat_id,
                message_id=menu_message_id,
                text=sample_snp_lookup_invalid_text(lang=lang),
                reply_markup=build_sample_snp_lookup_input_keyboard(sample.asset_id, lang=lang),
                parse_mode="HTML",
            )
        else:
            await update.message.reply_text(
                sample_snp_lookup_invalid_text(lang=lang),
                reply_markup=build_sample_snp_lookup_input_keyboard(sample.asset_id, lang=lang),
                parse_mode="HTML",
                do_quote=False,
            )
        raise ApplicationHandlerStop

    raw_file = _data_store(context).get_sample_raw_file(user_id, sample.asset_id)
    if raw_file is None:
        flow.clear(chat_id, user_id)
        text = sample_snp_lookup_no_raw_text(sample, lang=lang)
    else:
        result = lookup_snp_in_sample(_data_store(context), user_id, sample, rsid)
        if result.error:
            logger.warning("Sample SNP lookup failed for sample_id=%s rsid=%s error=%s", sample.asset_id, rsid, result.error)
        text = sample_snp_lookup_result_text(sample, result, lang=lang)
        flow.clear(chat_id, user_id)

    markup = build_sample_snp_lookup_result_keyboard(sample.asset_id, lang=lang)
    if menu_message_id is not None:
        await _edit_menu_message(
            context,
            chat_id=chat_id,
            message_id=menu_message_id,
            text=text,
            reply_markup=markup,
            parse_mode="HTML",
        )
    else:
        await update.message.reply_text(text, reply_markup=markup, parse_mode="HTML", do_quote=False)
    raise ApplicationHandlerStop


async def _handle_coordinate_extract(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.message.document is None or update.effective_user is None or update.effective_chat is None:
        return

    document = update.message.document
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    lang = get_user_language(context, user_id)
    menu_message_id = _flow_store(context).get_message_id(chat_id, user_id)
    payload = _flow_store(context).get_payload(chat_id, user_id)
    coordinate_type = str(payload.get("coordinate_type") or "g25").strip().lower() or "g25"
    save_after_extract = payload.get("save_after_extract", True) is not False
    sample_name = _build_sample_name(update, Path(document.file_name or "input").stem)
    store = _data_store(context)
    temp_path = store.build_temp_path(user_id, document.file_name or "input.raw")
    extraction_succeeded = False
    status_message = await update.message.reply_text(
        f"File received, extracting {coordinate_type.upper()} coordinates..." if lang == "en" else f"Файл получен, извлекаю {coordinate_type.upper()}-координаты...",
        do_quote=False,
    )

    try:
        telegram_file = await document.get_file()
        await telegram_file.download_to_drive(custom_path=str(temp_path))
        result = _g25_service(context).extract_coordinates_from_file(temp_path, sample_name, coordinate_type)
        extraction_succeeded = True
        asset = None
        if save_after_extract:
            asset = store.save_coordinate(
                user_id,
                display_name=result.target_name,
                target_name=result.target_name,
                coordinate_type=coordinate_type,
                g25_line=result.simulated_g25_line,
                input_mode=result.input_mode,
            )
    except G25CommandError as exc:
        if save_after_extract:
            _record_dna_lab_usage(update, context, action=COORDINATE_EXTRACT_ACTION, success=False, input_mode="file")
        if coordinate_type == "g25":
            _record_g25_usage(update, context, input_mode="raw-file", success=False, query=sample_name)
        await update.message.reply_text(str(exc), do_quote=False)
        raise ApplicationHandlerStop
    except Exception:
        logger.exception("My data coordinate extraction failed")
        if save_after_extract:
            _record_dna_lab_usage(update, context, action=COORDINATE_EXTRACT_ACTION, success=False, input_mode="file")
        if coordinate_type == "g25":
            _record_g25_usage(update, context, input_mode="raw-file", success=False, query=sample_name)
        await update.message.reply_text("Could not extract coordinates from the file. Try again." if lang == "en" else "Не удалось извлечь координаты из файла. Попробуйте ещё раз.", do_quote=False)
        raise ApplicationHandlerStop
    finally:
        if save_after_extract or not extraction_succeeded:
            store.cleanup_temp_file(temp_path)

    if not save_after_extract:
        result_message = await update.message.reply_text(
            quick_g25_result_text(result.target_name, result.simulated_g25_line, lang=lang),
            reply_markup=build_quick_g25_result_keyboard(lang=lang),
            parse_mode="HTML",
            do_quote=False,
        )
        set_active_main_menu_message(context, chat_id, user_id, result_message.message_id)
        _flow_store(context).expect(
            chat_id,
            user_id,
            QUICK_G25_RESULT_ACTION,
            result_message.message_id,
            payload={
                "coordinate_type": coordinate_type,
                "target_name": result.target_name,
                "g25_line": result.simulated_g25_line,
                "input_mode": result.input_mode,
                "raw_temp_path": str(temp_path),
                "raw_file_name": document.file_name or "input.raw",
                "raw_display_name": result.target_name or Path(document.file_name or "input").stem,
            },
        )
        try:
            await status_message.edit_text("G25 profile is ready." if lang == "en" else "G25-профиль готов.")
        except Exception:
            logger.debug("Failed to update quick G25 status message", exc_info=True)
        if coordinate_type == "g25":
            _record_g25_usage(update, context, input_mode=result.input_mode, success=True, query=result.target_name)
        raise ApplicationHandlerStop

    if asset is None:
        logger.error("Coordinate extraction reached save branch without a saved asset")
        _record_dna_lab_usage(update, context, action=COORDINATE_EXTRACT_ACTION, success=False, input_mode="file")
        if coordinate_type == "g25":
            _record_g25_usage(update, context, input_mode=result.input_mode, success=False, query=result.target_name)
        await update.message.reply_text("Could not save coordinates. Try again." if lang == "en" else "Не удалось сохранить координаты. Попробуйте ещё раз.", do_quote=False)
        raise ApplicationHandlerStop

    await update.message.reply_text(
        (
            f"{coordinate_type.upper()} coordinates extracted and saved: {asset.display_name}\n<code>{html.escape(asset.g25_line)}</code>"
            if lang == "en"
            else f"Координаты {coordinate_type.upper()} извлечены и сохранены: {asset.display_name}\n<code>{html.escape(asset.g25_line)}</code>"
        ),
        parse_mode="HTML",
        do_quote=False,
    )
    try:
        if menu_message_id is not None and payload.get("refresh_coordinates_view", True) is not False:
            await _refresh_coordinates_view(context, chat_id, user_id, menu_message_id)
        await status_message.edit_text("Coordinates saved." if lang == "en" else "Координаты сохранены.")
    except Exception:
        logger.debug("Failed to refresh extracted coordinates view", exc_info=True)
    _flow_store(context).clear(chat_id, user_id)
    _record_dna_lab_usage(update, context, action=COORDINATE_EXTRACT_ACTION, input_mode="file")
    if coordinate_type == "g25":
        _record_g25_usage(update, context, input_mode=asset.input_mode, success=True, query=asset.target_name)
    raise ApplicationHandlerStop


async def quick_g25_coordinates_reply_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.effective_chat is None or update.effective_user is None:
        return

    await open_quick_g25_prompt(
        update.message,
        context,
        update.effective_chat.id,
        update.effective_user.id,
    )
    raise ApplicationHandlerStop


async def open_quick_g25_prompt(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_id: int,
    *,
    back_callback: str | None = None,
    add_data_flow: bool = False,
    edit_existing: bool = False,
) -> None:
    lang = get_user_language(context, user_id)
    _clear_my_data_pending(context, chat_id, user_id)
    prompt_text = extract_coordinates_text("g25", lang=lang)
    prompt_markup = build_extract_coordinates_keyboard(
        back_callback=back_callback or f"{MY_DATA_CALLBACK_PREFIX}:coordinates_extract_root",
        add_data_flow=add_data_flow,
        lang=lang,
    )

    if edit_existing:
        await message.edit_text(prompt_text, reply_markup=prompt_markup)
        message_id = message.message_id
    else:
        sent = await message.reply_text(prompt_text, reply_markup=prompt_markup, do_quote=False)
        message_id = sent.message_id

    set_active_main_menu_message(context, chat_id, user_id, message_id)
    _flow_store(context).expect(
        chat_id,
        user_id,
        COORDINATE_EXTRACT_ACTION,
        message_id,
        payload={"coordinate_type": "g25", "save_after_extract": False},
    )


async def my_data_document_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.message.document is None or update.effective_chat is None or update.effective_user is None:
        return

    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    lang = get_user_language(context, user_id)
    store = _flow_store(context)
    action = store.get_action(chat_id, user_id)
    if action is None:
        return
    if not matches_active_message(update, store):
        return

    if action == RAW_UPLOAD_ACTION:
        await _handle_raw_upload(update, context)
        return
    if action == COORDINATE_EXTRACT_ACTION:
        await _handle_coordinate_extract(update, context)
        return
    if action == SAMPLE_SNP_LOOKUP_ACTION:
        await update.message.reply_text("For this step, send an rsID as text." if lang == "en" else "Для этого шага пришлите rsID текстом.", do_quote=False)
        raise ApplicationHandlerStop
    if action in {SAMPLE_CREATE_ACTION, SAMPLE_RENAME_ACTION, RAW_RENAME_ACTION, COORDINATE_RENAME_ACTION}:
        await update.message.reply_text("For this step, send the new name as text." if lang == "en" else "Для этого шага пришлите новое имя текстом.", do_quote=False)
        raise ApplicationHandlerStop
    if action == COORDINATE_ADD_ACTION:
        coordinate_type = str(store.get_payload(chat_id, user_id).get("coordinate_type") or "g25").strip().upper() or "G25"
        await update.message.reply_text(
            (
                f"For this step, send {coordinate_type} coordinates as text. Use Extract from raw for files."
                if lang == "en"
                else f"Для этого шага пришлите {coordinate_type}-координаты текстом. Для файла используйте Extract from raw."
            ),
            do_quote=False,
        )
        raise ApplicationHandlerStop


async def my_data_text_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.message.text is None or update.effective_chat is None or update.effective_user is None:
        return

    body = update.message.text.strip()
    if not body or body.startswith("/"):
        return

    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    lang = get_user_language(context, user_id)
    store = _flow_store(context)
    action = store.get_action(chat_id, user_id)
    if action is None:
        return
    if not matches_active_message(update, store):
        return

    payload = store.get_payload(chat_id, user_id)

    if action == SAMPLE_SNP_LOOKUP_ACTION:
        await _handle_sample_snp_lookup(update, context, body)
        return
    if action == SAMPLE_CREATE_ACTION:
        raw_file_id = str(payload.get("raw_file_id") or "").strip()
        if not raw_file_id:
            store.clear(chat_id, user_id)
            _record_dna_lab_usage(update, context, action=SAMPLE_CREATE_ACTION, success=False, input_mode="text")
            await update.message.reply_text("Could not identify the raw file for sample creation. Open the raw file again." if lang == "en" else "Не удалось определить raw file для создания sample. Откройте raw file заново.", do_quote=False)
            raise ApplicationHandlerStop
        asset = _data_store(context).save_sample(user_id, display_name=body, raw_file_id=raw_file_id)
        if asset is None:
            store.clear(chat_id, user_id)
            _record_dna_lab_usage(update, context, action=SAMPLE_CREATE_ACTION, success=False, input_mode="text")
            await update.message.reply_text(
                (
                    "Could not create the sample. Check that the raw file exists and is not already used by another sample."
                    if lang == "en"
                    else "Не удалось создать sample. Проверьте, что raw file существует и еще не занят другим sample."
                ),
                do_quote=False,
            )
            raise ApplicationHandlerStop
        menu_message_id = store.get_message_id(chat_id, user_id)
        if menu_message_id is not None:
            try:
                await _refresh_sample_detail(context, chat_id, user_id, menu_message_id, asset)
            except Exception:
                logger.debug("Failed to refresh sample detail after sample creation", exc_info=True)
        store.clear(chat_id, user_id)
        _record_dna_lab_usage(update, context, action=SAMPLE_CREATE_ACTION, input_mode="text")
        raise ApplicationHandlerStop
    if action == COORDINATE_ADD_ACTION:
        await _handle_coordinate_add(update, context, body)
        return
    if action == RAW_UPLOAD_ACTION:
        await update.message.reply_text("For this step, send the raw file as a document." if lang == "en" else "Для этого шага пришлите raw-файл документом.", do_quote=False)
        raise ApplicationHandlerStop
    if action == COORDINATE_EXTRACT_ACTION:
        coordinate_type = str(payload.get("coordinate_type") or "g25").strip().upper() or "G25"
        await update.message.reply_text(
            (
                f"For this step, send a raw file as a document to extract {coordinate_type}."
                if lang == "en"
                else f"Для этого шага пришлите raw-файл документом для извлечения {coordinate_type}."
            ),
            do_quote=False,
        )
        raise ApplicationHandlerStop
    if action == SAMPLE_RENAME_ACTION:
        asset_id = str(payload.get("asset_id") or "").strip()
        if not asset_id:
            store.clear(chat_id, user_id)
            await update.message.reply_text("Could not identify the sample to rename. Open My DNA again." if lang == "en" else "Не удалось определить sample для переименования. Откройте My DNA заново.", do_quote=False)
            raise ApplicationHandlerStop
        asset = _data_store(context).rename_sample(user_id, asset_id, body)
        if asset is None:
            await update.message.reply_text("Could not rename the sample. Check the name and try again." if lang == "en" else "Не удалось переименовать sample. Проверьте имя и попробуйте ещё раз.", do_quote=False)
            raise ApplicationHandlerStop
        menu_message_id = store.get_message_id(chat_id, user_id)
        if menu_message_id is not None:
            try:
                await _refresh_sample_detail(context, chat_id, user_id, menu_message_id, asset)
            except Exception:
                logger.debug("Failed to refresh sample detail", exc_info=True)
        await update.message.reply_text((f"New sample name: {asset.display_name}" if lang == "en" else f"Новое имя sample: {asset.display_name}"), do_quote=False)
        store.clear(chat_id, user_id)
        raise ApplicationHandlerStop
    if action == RAW_RENAME_ACTION:
        asset_id = str(payload.get("asset_id") or "").strip()
        if not asset_id:
            store.clear(chat_id, user_id)
            await update.message.reply_text("Could not identify the raw file to rename. Open My DNA again." if lang == "en" else "Не удалось определить raw-файл для переименования. Откройте My DNA заново.", do_quote=False)
            raise ApplicationHandlerStop
        asset = _data_store(context).rename_raw_file(user_id, asset_id, body)
        if asset is None:
            await update.message.reply_text("Could not rename the raw file. Check the name and try again." if lang == "en" else "Не удалось переименовать raw-файл. Проверьте имя и попробуйте ещё раз.", do_quote=False)
            raise ApplicationHandlerStop
        menu_message_id = store.get_message_id(chat_id, user_id)
        if menu_message_id is not None:
            try:
                await _refresh_raw_file_detail(context, chat_id, user_id, menu_message_id, asset)
            except Exception:
                logger.debug("Failed to refresh raw file detail", exc_info=True)
        await update.message.reply_text((f"New raw file name: {asset.display_name}" if lang == "en" else f"Новое имя raw-файла: {asset.display_name}"), do_quote=False)
        store.clear(chat_id, user_id)
        raise ApplicationHandlerStop
    if action == COORDINATE_RENAME_ACTION:
        asset_id = str(payload.get("asset_id") or "").strip()
        if not asset_id:
            store.clear(chat_id, user_id)
            await update.message.reply_text("Could not identify the coordinates to rename. Open My DNA again." if lang == "en" else "Не удалось определить координаты для переименования. Откройте My DNA заново.", do_quote=False)
            raise ApplicationHandlerStop
        asset = _data_store(context).rename_coordinate(user_id, asset_id, body)
        if asset is None:
            await update.message.reply_text("Could not rename coordinates. Check the name and try again." if lang == "en" else "Не удалось переименовать координаты. Проверьте имя и попробуйте ещё раз.", do_quote=False)
            raise ApplicationHandlerStop
        menu_message_id = store.get_message_id(chat_id, user_id)
        if menu_message_id is not None:
            try:
                await _refresh_coordinate_detail(context, chat_id, user_id, menu_message_id, asset)
            except Exception:
                logger.debug("Failed to refresh coordinate detail", exc_info=True)
        await update.message.reply_text((f"New coordinates name: {asset.display_name}" if lang == "en" else f"Новое имя координат: {asset.display_name}"), do_quote=False)
        store.clear(chat_id, user_id)
        raise ApplicationHandlerStop
