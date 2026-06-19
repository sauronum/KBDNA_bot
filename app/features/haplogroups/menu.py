from __future__ import annotations

import asyncio
import hashlib
import html
import logging
import tempfile
import time
from math import ceil
from pathlib import Path
from uuid import uuid4

from telegram import InlineKeyboardButton, Update
from telegram.ext import Application, ApplicationHandlerStop, ContextTypes

from app.features.my_data.storage import MyDataStore, SampleAsset
from app.i18n import get_user_language, t
from app.main_menu import ensure_active_main_menu, set_active_main_menu_message

from .branch_ui import (
    branch_lookup_error_text,
    branch_lookup_loading_text,
    branch_lookup_prompt_text,
    branch_lookup_result_text,
)
from .domain import (
    ImportedHaplogroup,
    compare_y_str_profiles,
    normalize_haplogroup_value,
    parse_haplogroup_result_file,
    parse_y_str_result_file,
    predict_y_haplogroup_from_raw,
    scan_raw_haplogroup_markers,
)
from .storage import HaplogroupRecord, HaplogroupStore, YStrProfile
from .ui import (
    build_markup,
    error_text,
    haplogroup_input_text,
    haplogroups_root_text,
    imported_str_profile_text,
    imported_records_text,
    lineage_menu_text,
    manual_type_text,
    record_button_label,
    record_detail_text,
    record_saved_text,
    records_list_text,
    raw_detect_type_text,
    raw_scan_result_text,
    sample_picker_text,
    str_compare_picker_text,
    str_distance_text,
    str_profile_detail_text,
    str_profiles_text,
    upload_result_prompt_text,
    upload_result_text,
    y_prediction_text,
)
from .visualization import render_yfull_branch_png
from .yfull import TREE_MTDNA, YFullBranchService, YFullLookupError


HAPLOGROUPS_CALLBACK_PREFIX = "haplogroups"
_PAGE_SIZE = 8
_RECORDS_PAGE_SIZE = 8
HAPLOGROUP_RESULT_UPLOAD_LIMIT_BYTES = 20 * 1024 * 1024
_TEXT_ADD_ACTION = "haplogroup_add"
_FILE_UPLOAD_ACTION = "haplogroup_file_upload"
_STR_COMPARE_ACTION = "haplogroup_str_compare"
_BRANCH_LOOKUP_ACTION = "haplogroup_branch_lookup"
_BRANCH_NAV_KEY = "haplogroup_branch_nav"
_BRANCH_NAV_LIMIT = 64
_FLOW_TTL_SECONDS = 15 * 60
_TYPE_CODES = {"y": "Y-DNA", "mt": "mtDNA"}
logger = logging.getLogger(__name__)
THEME_DARK = "dark"


def _copy(lang: str, ru: str, en: str) -> str:
    return en if lang == "en" else ru


def _next_label(lang: str) -> str:
    return _copy(lang, "Далее", "Next")


def _parse_page(value: str | None) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _file_too_large_text(lang: str) -> str:
    size_mb = HAPLOGROUP_RESULT_UPLOAD_LIMIT_BYTES // (1024 * 1024)
    return _copy(
        lang,
        f"Файл слишком большой для Haplogroups. Пришлите .txt/.csv/.tsv до {size_mb} MB.",
        f"The file is too large for Haplogroups. Send a .txt/.csv/.tsv file up to {size_mb} MB.",
    )


class HaplogroupFlowStore:
    def __init__(self, *, ttl_seconds: float = _FLOW_TTL_SECONDS) -> None:
        self.ttl_seconds = max(0.0, float(ttl_seconds))
        self._pending: dict[tuple[int, int], tuple[float, dict[str, object]]] = {}

    def expect(self, chat_id: int, user_id: int, payload: dict[str, object], *, action: str = _TEXT_ADD_ACTION) -> None:
        expires_at = time.monotonic() + self.ttl_seconds
        self._pending[(int(chat_id), int(user_id))] = (expires_at, {"action": action, **payload})

    def get(self, chat_id: int, user_id: int) -> dict[str, object] | None:
        key = (int(chat_id), int(user_id))
        entry = self._pending.get(key)
        if entry is None:
            return None
        expires_at, payload = entry
        if time.monotonic() > expires_at:
            self._pending.pop(key, None)
            return None
        return dict(payload)

    def clear(self, chat_id: int, user_id: int) -> None:
        self._pending.pop((int(chat_id), int(user_id)), None)

    def clear_pending(self, chat_id: int, user_id: int) -> None:
        self.clear(chat_id, user_id)


def register_haplogroup_services(application: Application, settings) -> None:
    haplogroup_root = settings.root_dir / "storage" / "haplogroups"
    application.bot_data["haplogroup_store"] = HaplogroupStore(haplogroup_root)
    application.bot_data["haplogroup_flow_store"] = HaplogroupFlowStore()
    application.bot_data["yfull_branch_service"] = YFullBranchService(haplogroup_root / "yfull_cache")
    application.bot_data["yfull_mtree_service"] = YFullBranchService(
        haplogroup_root / "yfull_mtree_cache",
        tree_type=TREE_MTDNA,
    )


def _store(context: ContextTypes.DEFAULT_TYPE) -> HaplogroupStore:
    store = context.application.bot_data.get("haplogroup_store")
    if isinstance(store, HaplogroupStore):
        return store
    store = HaplogroupStore(context.application.bot_data["my_data_store"].root_dir.parent / "haplogroups")
    context.application.bot_data["haplogroup_store"] = store
    return store


def _flow_store(context: ContextTypes.DEFAULT_TYPE) -> HaplogroupFlowStore:
    store = context.application.bot_data.get("haplogroup_flow_store")
    if isinstance(store, HaplogroupFlowStore):
        return store
    store = HaplogroupFlowStore()
    context.application.bot_data["haplogroup_flow_store"] = store
    return store


def _my_data_store(context: ContextTypes.DEFAULT_TYPE) -> MyDataStore:
    return context.application.bot_data["my_data_store"]


def _yfull_branch_service(context: ContextTypes.DEFAULT_TYPE) -> YFullBranchService:
    service = context.application.bot_data.get("yfull_branch_service")
    if isinstance(service, YFullBranchService):
        return service
    cache_dir = _store(context).root_dir / "yfull_cache"
    service = YFullBranchService(cache_dir)
    context.application.bot_data["yfull_branch_service"] = service
    return service


def _yfull_mtree_service(context: ContextTypes.DEFAULT_TYPE) -> YFullBranchService:
    service = context.application.bot_data.get("yfull_mtree_service")
    if isinstance(service, YFullBranchService):
        return service
    cache_dir = _store(context).root_dir / "yfull_mtree_cache"
    service = YFullBranchService(cache_dir, tree_type=TREE_MTDNA)
    context.application.bot_data["yfull_mtree_service"] = service
    return service


def _yfull_tree_service(context: ContextTypes.DEFAULT_TYPE, tree_type: str) -> YFullBranchService:
    return _yfull_mtree_service(context) if tree_type == "mt" else _yfull_branch_service(context)


def _branch_visual_theme(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> str:
    store = context.application.bot_data.get("user_settings_store")
    get_theme = getattr(store, "get_theme", None)
    if not callable(get_theme):
        return THEME_DARK
    try:
        return "light" if str(get_theme(user_id)).strip().lower() == "light" else THEME_DARK
    except Exception:
        logger.debug("Could not read haplogroup visual theme", exc_info=True)
        return THEME_DARK


def _create_branch_visual_path() -> Path:
    return Path(tempfile.gettempdir()) / f"kbdna_yfull_{uuid4().hex}.png"


def _remember_branch_nav_target(context: ContextTypes.DEFAULT_TYPE, branch_name: str) -> str:
    user_data = getattr(context, "user_data", None)
    if not isinstance(user_data, dict):
        user_data = {}
        setattr(context, "user_data", user_data)
    storage = user_data.setdefault(_BRANCH_NAV_KEY, {})
    if not isinstance(storage, dict):
        storage = {}
        user_data[_BRANCH_NAV_KEY] = storage
    token = hashlib.sha256(branch_name.encode("utf-8")).hexdigest()[:12]
    storage[token] = branch_name
    while len(storage) > _BRANCH_NAV_LIMIT:
        storage.pop(next(iter(storage)), None)
    return token


def _resolve_branch_nav_target(context: ContextTypes.DEFAULT_TYPE, token: str) -> str:
    user_data = getattr(context, "user_data", None)
    if not isinstance(user_data, dict):
        return ""
    storage = user_data.get(_BRANCH_NAV_KEY)
    if not isinstance(storage, dict):
        return ""
    return str(storage.get(token) or "")


def _other_input_flow_active(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int) -> bool:
    my_data_flow = context.application.bot_data.get("my_data_flow_store")
    if my_data_flow is not None and hasattr(my_data_flow, "get_action"):
        if my_data_flow.get_action(chat_id, user_id) is not None:
            return True
    matching_flow = context.application.bot_data.get("matching_flow_store")
    if matching_flow is not None and hasattr(matching_flow, "get_pending"):
        if matching_flow.get_pending(chat_id, user_id) is not None:
            return True
    vahaduo_flow = context.application.bot_data.get("dna_lab_vahaduo_store") or context.application.bot_data.get("vahaduo_store")
    if vahaduo_flow is not None and hasattr(vahaduo_flow, "get"):
        state = vahaduo_flow.get(chat_id, user_id)
        if isinstance(state, dict) and state.get("awaiting"):
            return True
    user_data = getattr(context, "user_data", {}) or {}
    for key in ("sozluk_pending", "ystr_pending"):
        pending = user_data.get(key)
        if isinstance(pending, dict) and int(pending.get("chat_id") or 0) == int(chat_id):
            return True
    return False


def _looks_like_haplogroup_input(value: str) -> bool:
    clean = value.strip()
    return bool(normalize_haplogroup_value(clean) or "://" in clean or any(character.isdigit() for character in clean))


def _paginate(items: list[SampleAsset], page: int) -> tuple[list[SampleAsset], int, int]:
    total_pages = max(1, ceil(len(items) / _PAGE_SIZE)) if items else 1
    normalized_page = max(0, min(page, total_pages - 1))
    start = normalized_page * _PAGE_SIZE
    return items[start:start + _PAGE_SIZE], normalized_page, total_pages


def _paginate_records(records: list[HaplogroupRecord], page: int) -> tuple[list[HaplogroupRecord], int, int]:
    total_pages = max(1, ceil(len(records) / _RECORDS_PAGE_SIZE)) if records else 1
    normalized_page = max(0, min(page, total_pages - 1))
    start = normalized_page * _RECORDS_PAGE_SIZE
    return records[start:start + _RECORDS_PAGE_SIZE], normalized_page, total_pages


async def _show_or_edit(message, text_value: str, reply_markup, *, edit_existing: bool = False) -> None:
    if edit_existing:
        await message.edit_text(text_value, reply_markup=reply_markup, parse_mode="HTML")
    else:
        await message.reply_text(text_value, reply_markup=reply_markup, parse_mode="HTML", do_quote=False)


async def show_haplogroups_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    lang: str | None = None,
    edit_existing: bool = False,
) -> None:
    lang = lang or get_user_language(context, user_id)
    rows = [
        [InlineKeyboardButton(_copy(lang, "🌳 Деревья гаплогрупп", "🌳 Haplogroup trees"), callback_data=f"{HAPLOGROUPS_CALLBACK_PREFIX}:trees")],
        [InlineKeyboardButton("🧬 Y-DNA", callback_data=f"{HAPLOGROUPS_CALLBACK_PREFIX}:y")],
        [InlineKeyboardButton("🧬 mtDNA", callback_data=f"{HAPLOGROUPS_CALLBACK_PREFIX}:mt")],
        [InlineKeyboardButton("🧮 Y-STR", callback_data=f"{HAPLOGROUPS_CALLBACK_PREFIX}:str")],
    ]
    await _show_or_edit(message, haplogroups_root_text(lang), build_markup(rows, "main:root", lang=lang), edit_existing=edit_existing)


async def show_branch_trees_menu(message, *, lang: str = "ru", edit_existing: bool = False) -> None:
    rows = [
        [InlineKeyboardButton("🧬 Y-DNA · YFull YTree", callback_data=f"{HAPLOGROUPS_CALLBACK_PREFIX}:branch:y")],
        [InlineKeyboardButton("🧬 mtDNA · YFull MTree", callback_data=f"{HAPLOGROUPS_CALLBACK_PREFIX}:branch:mt")],
    ]
    text_value = "\n".join(
        [
            f"<b>{_copy(lang, '🌳 Деревья гаплогрупп', '🌳 Haplogroup trees')}</b>",
            "",
            _copy(lang, "Выберите линию для поиска ветви.", "Choose a lineage to look up a branch."),
        ]
    )
    await _show_or_edit(
        message,
        text_value,
        build_markup(rows, f"{HAPLOGROUPS_CALLBACK_PREFIX}:root", lang=lang),
        edit_existing=edit_existing,
    )


async def show_branch_lookup_prompt(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    chat_id: int,
    *,
    tree_type: str = "y",
    lang: str = "ru",
    edit_existing: bool = False,
) -> None:
    tree_type = "mt" if tree_type == "mt" else "y"
    _flow_store(context).expect(chat_id, user_id, {"tree_type": tree_type}, action=_BRANCH_LOOKUP_ACTION)
    await _show_or_edit(
        message,
        branch_lookup_prompt_text(lang, tree_type=tree_type),
        build_markup([], f"{HAPLOGROUPS_CALLBACK_PREFIX}:trees", lang=lang),
        edit_existing=edit_existing,
    )


async def show_lineage_menu(message, type_code: str, *, lang: str = "ru", edit_existing: bool = False) -> None:
    haplogroup_type = _TYPE_CODES.get(type_code)
    if haplogroup_type is None:
        return
    rows = [
        [InlineKeyboardButton(_copy(lang, "🧬 Определить из raw", "🧬 Detect from raw"), callback_data=f"{HAPLOGROUPS_CALLBACK_PREFIX}:dadd:{type_code}:0")],
        [InlineKeyboardButton(_copy(lang, "📤 Загрузить результат", "📤 Upload test result"), callback_data=f"{HAPLOGROUPS_CALLBACK_PREFIX}:upload")],
        [InlineKeyboardButton(_copy(lang, "🌿 Добавить гаплогруппу", "🌿 Add haplogroup"), callback_data=f"{HAPLOGROUPS_CALLBACK_PREFIX}:add:{type_code}:0")],
        [InlineKeyboardButton(_copy(lang, "💾 Сохранённые записи", "💾 Saved results"), callback_data=f"{HAPLOGROUPS_CALLBACK_PREFIX}:list:{type_code}")],
    ]
    await _show_or_edit(
        message,
        lineage_menu_text(haplogroup_type, lang),
        build_markup(rows, f"{HAPLOGROUPS_CALLBACK_PREFIX}:root", lang=lang),
        edit_existing=edit_existing,
    )


async def show_detect_type_menu(message, *, lang: str = "ru", edit_existing: bool = False) -> None:
    rows = [
        [InlineKeyboardButton(_copy(lang, "🧬 Y-DNA из raw", "🧬 Y-DNA SNP scan"), callback_data=f"{HAPLOGROUPS_CALLBACK_PREFIX}:dadd:y:0")],
        [InlineKeyboardButton(_copy(lang, "🧬 mtDNA из raw", "🧬 mtDNA marker scan"), callback_data=f"{HAPLOGROUPS_CALLBACK_PREFIX}:dadd:mt:0")],
    ]
    await _show_or_edit(message, raw_detect_type_text(lang), build_markup(rows, f"{HAPLOGROUPS_CALLBACK_PREFIX}:root", lang=lang), edit_existing=edit_existing)


async def show_manual_type_menu(
    message,
    *,
    back_callback: str = f"{HAPLOGROUPS_CALLBACK_PREFIX}:root",
    lang: str = "ru",
    edit_existing: bool = False,
) -> None:
    rows = [
        [InlineKeyboardButton("🌿 Y-DNA", callback_data=f"{HAPLOGROUPS_CALLBACK_PREFIX}:add:y:0")],
        [InlineKeyboardButton("🌿 mtDNA", callback_data=f"{HAPLOGROUPS_CALLBACK_PREFIX}:add:mt:0")],
    ]
    await _show_or_edit(message, manual_type_text(lang), build_markup(rows, back_callback, lang=lang), edit_existing=edit_existing)


async def show_upload_sample_picker(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    page: int = 0,
    lang: str = "ru",
    edit_existing: bool = False,
) -> None:
    samples = _my_data_store(context).list_samples(user_id)
    page_samples, current_page, total_pages = _paginate(samples, page)
    rows = [
        [
            InlineKeyboardButton(
                f"📄 {sample.display_name}",
                callback_data=f"{HAPLOGROUPS_CALLBACK_PREFIX}:upick:{sample.asset_id}",
            )
        ]
        for sample in page_samples
    ]
    pager = []
    if current_page > 0:
        pager.append(InlineKeyboardButton(t("nav.back", lang), callback_data=f"{HAPLOGROUPS_CALLBACK_PREFIX}:upload:{current_page - 1}"))
    if current_page + 1 < total_pages:
        pager.append(InlineKeyboardButton(_next_label(lang), callback_data=f"{HAPLOGROUPS_CALLBACK_PREFIX}:upload:{current_page + 1}"))
    if pager:
        rows.append(pager)
    await _show_or_edit(message, upload_result_text(samples, lang), build_markup(rows, f"{HAPLOGROUPS_CALLBACK_PREFIX}:root", lang=lang), edit_existing=edit_existing)


async def show_sample_picker(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    type_code: str,
    *,
    page: int = 0,
    mode: str = "manual",
    back_callback: str | None = None,
    lang: str = "ru",
    edit_existing: bool = False,
) -> None:
    haplogroup_type = _TYPE_CODES.get(type_code)
    if haplogroup_type is None:
        await show_haplogroups_menu(message, context, user_id, lang=lang, edit_existing=edit_existing)
        return
    samples = _my_data_store(context).list_samples(user_id)
    page_samples, current_page, total_pages = _paginate(samples, page)
    rows = [
        [
            InlineKeyboardButton(
                f"🧬 {sample.display_name}" if mode == "detect" else f"🌿 {sample.display_name}",
                callback_data=f"{HAPLOGROUPS_CALLBACK_PREFIX}:{'dpick' if mode == 'detect' else 'pick'}:{type_code}:{sample.asset_id}",
            )
        ]
        for sample in page_samples
    ]
    pager = []
    if current_page > 0:
        pager.append(
            InlineKeyboardButton(
                t("nav.back", lang),
                callback_data=f"{HAPLOGROUPS_CALLBACK_PREFIX}:{'dadd' if mode == 'detect' else 'add'}:{type_code}:{current_page - 1}",
            )
        )
    if current_page + 1 < total_pages:
        pager.append(
            InlineKeyboardButton(
                _next_label(lang),
                callback_data=f"{HAPLOGROUPS_CALLBACK_PREFIX}:{'dadd' if mode == 'detect' else 'add'}:{type_code}:{current_page + 1}",
            )
        )
    if pager:
        rows.append(pager)
    await _show_or_edit(
        message,
        sample_picker_text(samples, haplogroup_type, mode=mode, lang=lang),
        build_markup(
            rows,
            back_callback or f"{HAPLOGROUPS_CALLBACK_PREFIX}:{'detect' if mode == 'detect' else 'manual'}",
            lang=lang,
        ),
        edit_existing=edit_existing,
    )


async def show_raw_scan_result(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    type_code: str,
    sample_id: str,
    *,
    lang: str = "ru",
    edit_existing: bool = False,
) -> None:
    haplogroup_type = _TYPE_CODES.get(type_code)
    sample = _my_data_store(context).get_sample(user_id, sample_id)
    if haplogroup_type is None or sample is None:
        await show_detect_type_menu(message, lang=lang, edit_existing=edit_existing)
        return
    raw_file = _my_data_store(context).get_sample_raw_file(user_id, sample.asset_id)
    if raw_file is None:
        await _show_or_edit(
            message,
            error_text(_copy(lang, "Определить из raw", "Detect from raw"), _copy(lang, "У sample нет исходного raw-файла.", "This sample has no source raw file.")),
            build_markup([], f"{HAPLOGROUPS_CALLBACK_PREFIX}:dadd:{type_code}:0", lang=lang),
            edit_existing=edit_existing,
        )
        return
    raw_path = _my_data_store(context).resolve_raw_file_path(raw_file)
    try:
        scan = await asyncio.to_thread(scan_raw_haplogroup_markers, raw_path, haplogroup_type)
    except Exception:
        logger.exception("Haplogroup raw scan failed")
        await _show_or_edit(
            message,
            error_text(
                _copy(lang, "Определить из raw", "Detect from raw"),
                _copy(lang, "Не удалось прочитать raw-файл этого sample.", "Could not read this sample's raw file."),
            ),
            build_markup([], f"{HAPLOGROUPS_CALLBACK_PREFIX}:dadd:{type_code}:0", lang=lang),
            edit_existing=edit_existing,
        )
        return
    rows = []
    if type_code == "y" and scan.called_markers:
        rows.append([InlineKeyboardButton(_copy(lang, "🧬 Прогноз Y-DNA", "🧬 Predict Y haplogroup"), callback_data=f"{HAPLOGROUPS_CALLBACK_PREFIX}:yp:{sample.asset_id}")])
    await _show_or_edit(
        message,
        raw_scan_result_text(sample, scan, lang=lang),
        build_markup(rows, f"{HAPLOGROUPS_CALLBACK_PREFIX}:dadd:{type_code}:0", lang=lang),
        edit_existing=edit_existing,
    )


async def show_y_prediction(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    sample_id: str,
    *,
    lang: str = "ru",
    edit_existing: bool = False,
) -> None:
    sample = _my_data_store(context).get_sample(user_id, sample_id)
    if sample is None:
        await show_detect_type_menu(message, lang=lang, edit_existing=edit_existing)
        return
    raw_file = _my_data_store(context).get_sample_raw_file(user_id, sample.asset_id)
    if raw_file is None:
        await _show_or_edit(
            message,
            error_text(_copy(lang, "Прогноз Y-DNA", "Y-DNA prediction"), _copy(lang, "У sample нет исходного raw-файла.", "This sample has no source raw file.")),
            build_markup([], f"{HAPLOGROUPS_CALLBACK_PREFIX}:dadd:y:0", lang=lang),
            edit_existing=edit_existing,
        )
        return
    raw_path = _my_data_store(context).resolve_raw_file_path(raw_file)
    try:
        prediction = await asyncio.to_thread(predict_y_haplogroup_from_raw, raw_path)
    except Exception:
        logger.exception("Y-DNA prediction failed")
        await _show_or_edit(
            message,
            error_text(
                _copy(lang, "Прогноз Y-DNA", "Y-DNA prediction"),
                _copy(lang, "Не удалось построить прогноз по этому raw-файлу.", "Could not build a prediction from this raw file."),
            ),
            build_markup([], f"{HAPLOGROUPS_CALLBACK_PREFIX}:dpick:y:{sample.asset_id}", lang=lang),
            edit_existing=edit_existing,
        )
        return
    await _show_or_edit(
        message,
        y_prediction_text(sample, prediction, lang=lang),
        build_markup([], f"{HAPLOGROUPS_CALLBACK_PREFIX}:dpick:y:{sample.asset_id}", lang=lang),
        edit_existing=edit_existing,
    )


async def show_haplogroup_input_prompt(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    chat_id: int,
    type_code: str,
    sample_id: str,
    *,
    lang: str = "ru",
    edit_existing: bool = False,
) -> None:
    haplogroup_type = _TYPE_CODES.get(type_code)
    sample = _my_data_store(context).get_sample(user_id, sample_id)
    if haplogroup_type is None or sample is None:
        await show_sample_picker(message, context, user_id, type_code, lang=lang, edit_existing=edit_existing)
        return
    _flow_store(context).expect(
        chat_id,
        user_id,
        {"haplogroup_type": haplogroup_type, "sample_id": sample.asset_id},
    )
    await _show_or_edit(
        message,
        haplogroup_input_text(sample, haplogroup_type, lang),
        build_markup([], f"{HAPLOGROUPS_CALLBACK_PREFIX}:add:{type_code}:0", lang=lang),
        edit_existing=edit_existing,
    )


async def show_upload_result_prompt(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    chat_id: int,
    sample_id: str,
    *,
    lang: str = "ru",
    edit_existing: bool = False,
) -> None:
    sample = _my_data_store(context).get_sample(user_id, sample_id)
    if sample is None:
        await show_upload_sample_picker(message, context, user_id, lang=lang, edit_existing=edit_existing)
        return
    _flow_store(context).expect(
        chat_id,
        user_id,
        {"sample_id": sample.asset_id},
        action=_FILE_UPLOAD_ACTION,
    )
    await _show_or_edit(
        message,
        upload_result_prompt_text(sample, lang),
        build_markup([], f"{HAPLOGROUPS_CALLBACK_PREFIX}:upload", lang=lang),
        edit_existing=edit_existing,
    )


async def show_records_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    sample_id: str | None = None,
    haplogroup_type: str | None = None,
    page: int = 0,
    page_callback_base: str | None = None,
    back_callback: str = f"{HAPLOGROUPS_CALLBACK_PREFIX}:root",
    record_action: str = "o",
    lang: str = "ru",
    edit_existing: bool = False,
) -> None:
    sample = _my_data_store(context).get_sample(user_id, sample_id) if sample_id else None
    records = _store(context).list_sample_records(user_id, sample_id) if sample_id else _store(context).list_records(user_id)
    if haplogroup_type:
        records = [record for record in records if record.haplogroup_type == haplogroup_type]
    page_records, current_page, total_pages = _paginate_records(records, page)
    if page_callback_base is None:
        if sample_id:
            page_action = "hsample" if record_action == "ho" else "sample"
            page_callback_base = f"{HAPLOGROUPS_CALLBACK_PREFIX}:{page_action}:{sample_id}"
        else:
            type_code = next((code for code, value in _TYPE_CODES.items() if value == haplogroup_type), "all")
            page_callback_base = f"{HAPLOGROUPS_CALLBACK_PREFIX}:list:{type_code}"
    rows = [
        [
            InlineKeyboardButton(
                record_button_label(record, include_sample=sample is None),
                callback_data=f"{HAPLOGROUPS_CALLBACK_PREFIX}:{record_action}:{record.record_id}",
            )
        ]
        for record in page_records
    ]
    if page_callback_base and total_pages > 1:
        pager = []
        if current_page > 0:
            pager.append(InlineKeyboardButton(t("nav.back", lang), callback_data=f"{page_callback_base}:{current_page - 1}"))
        if current_page + 1 < total_pages:
            pager.append(InlineKeyboardButton(_next_label(lang), callback_data=f"{page_callback_base}:{current_page + 1}"))
        if pager:
            rows.append(pager)
    if sample is not None:
        rows.append([InlineKeyboardButton(_copy(lang, "🌿 Добавить Y-DNA", "🌿 Add Y-DNA"), callback_data=f"{HAPLOGROUPS_CALLBACK_PREFIX}:pick:y:{sample.asset_id}")])
        rows.append([InlineKeyboardButton(_copy(lang, "🌿 Добавить mtDNA", "🌿 Add mtDNA"), callback_data=f"{HAPLOGROUPS_CALLBACK_PREFIX}:pick:mt:{sample.asset_id}")])
    await _show_or_edit(
        message,
        records_list_text(records, sample=sample, haplogroup_type=haplogroup_type, lang=lang),
        build_markup(rows, back_callback, lang=lang),
        edit_existing=edit_existing,
    )


async def show_str_profiles_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    lang: str = "ru",
    edit_existing: bool = False,
) -> None:
    profiles = _store(context).list_y_str_profiles(user_id)
    rows = [
        [
            InlineKeyboardButton(
                f"📈 {profile.sample_name} ({profile.marker_count})",
                callback_data=f"{HAPLOGROUPS_CALLBACK_PREFIX}:strv:{profile.profile_id}",
            )
        ]
        for profile in profiles
    ]
    if len(profiles) >= 2:
        rows.insert(0, [InlineKeyboardButton(_copy(lang, "🧮 Сравнить STR", "🧮 Compare STR distance"), callback_data=f"{HAPLOGROUPS_CALLBACK_PREFIX}:scmp")])
    rows.append([InlineKeyboardButton(_copy(lang, "📤 Загрузить Y-STR", "📤 Upload Y-STR result"), callback_data=f"{HAPLOGROUPS_CALLBACK_PREFIX}:upload")])
    await _show_or_edit(message, str_profiles_text(profiles, lang), build_markup(rows, f"{HAPLOGROUPS_CALLBACK_PREFIX}:root", lang=lang), edit_existing=edit_existing)


async def show_str_profile_detail(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    profile_id: str,
    *,
    lang: str = "ru",
    edit_existing: bool = False,
) -> None:
    profile = _store(context).find_y_str_profile(user_id, profile_id)
    if profile is None:
        await _show_or_edit(
            message,
            error_text(_copy(lang, "Y-STR профиль", "Y-STR profile"), _copy(lang, "Профиль не найден.", "Profile not found.")),
            build_markup([], f"{HAPLOGROUPS_CALLBACK_PREFIX}:str", lang=lang),
            edit_existing=edit_existing,
        )
        return
    rows = []
    if len(_store(context).list_y_str_profiles(user_id)) >= 2:
        rows.append([InlineKeyboardButton(_copy(lang, "🧮 Сравнить STR", "🧮 Compare STR distance"), callback_data=f"{HAPLOGROUPS_CALLBACK_PREFIX}:stra:{profile.profile_id}")])
    await _show_or_edit(
        message,
        str_profile_detail_text(profile, lang),
        build_markup(rows, f"{HAPLOGROUPS_CALLBACK_PREFIX}:str", lang=lang),
        edit_existing=edit_existing,
    )


async def show_str_compare_picker(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    left_profile: YStrProfile | None = None,
    lang: str = "ru",
    edit_existing: bool = False,
) -> None:
    profiles = _store(context).list_y_str_profiles(user_id)
    rows = []
    for profile in profiles:
        if left_profile is not None and profile.profile_id == left_profile.profile_id:
            continue
        action = "strb" if left_profile is not None else "stra"
        rows.append(
            [
                InlineKeyboardButton(
                    f"📈 {profile.sample_name} ({profile.marker_count})",
                    callback_data=f"{HAPLOGROUPS_CALLBACK_PREFIX}:{action}:{profile.profile_id}",
                )
            ]
        )
    back_callback = f"{HAPLOGROUPS_CALLBACK_PREFIX}:str" if left_profile is None else f"{HAPLOGROUPS_CALLBACK_PREFIX}:scmp"
    await _show_or_edit(
        message,
        str_compare_picker_text(profiles, left=left_profile, lang=lang),
        build_markup(rows, back_callback, lang=lang),
        edit_existing=edit_existing,
    )


async def show_str_distance_result(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    left_profile_id: str,
    right_profile_id: str,
    *,
    lang: str = "ru",
    edit_existing: bool = False,
) -> None:
    left = _store(context).find_y_str_profile(user_id, left_profile_id)
    right = _store(context).find_y_str_profile(user_id, right_profile_id)
    if left is None or right is None:
        await _show_or_edit(
            message,
            error_text(_copy(lang, "Y-STR сравнение", "Y-STR distance"), _copy(lang, "Профиль не найден.", "Profile not found.")),
            build_markup([], f"{HAPLOGROUPS_CALLBACK_PREFIX}:str", lang=lang),
            edit_existing=edit_existing,
        )
        return
    result = compare_y_str_profiles(left.sample_name, left.marker_values, right.sample_name, right.marker_values)
    await _show_or_edit(
        message,
        str_distance_text(result, lang),
        build_markup([], f"{HAPLOGROUPS_CALLBACK_PREFIX}:scmp", lang=lang),
        edit_existing=edit_existing,
    )


async def show_record_detail(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    record_id: str,
    *,
    back_callback: str | None = None,
    lang: str = "ru",
    edit_existing: bool = False,
) -> None:
    record = _store(context).find_record(user_id, record_id)
    if record is None:
        await _show_or_edit(
            message,
            error_text("Haplogroups", _copy(lang, "Запись не найдена.", "Record not found.")),
            build_markup([], f"{HAPLOGROUPS_CALLBACK_PREFIX}:list", lang=lang),
            edit_existing=edit_existing,
        )
        return
    await _show_or_edit(
        message,
        record_detail_text(record, lang),
        build_markup([], back_callback or f"{HAPLOGROUPS_CALLBACK_PREFIX}:sample:{record.sample_id}", lang=lang),
        edit_existing=edit_existing,
    )


def parse_haplogroup_input(body: str) -> dict[str, str]:
    fields = {"haplogroup": "", "terminal_snp": "", "source": "", "confidence": "user-entered", "note": ""}
    note_lines: list[str] = []
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        key, separator, value = line.partition(":")
        normalized_key = key.strip().lower().replace("_", " ")
        clean_value = value.strip()
        if separator and normalized_key in {"haplogroup", "haplo", "hg"}:
            fields["haplogroup"] = clean_value
        elif separator and normalized_key in {"terminal", "terminal snp", "snp"}:
            fields["terminal_snp"] = clean_value
        elif separator and normalized_key == "source":
            fields["source"] = clean_value
        elif separator and normalized_key == "confidence":
            fields["confidence"] = clean_value or "user-entered"
        elif separator and normalized_key == "note":
            note_lines.append(clean_value)
        elif not fields["haplogroup"]:
            fields["haplogroup"] = line
        else:
            note_lines.append(line)
    fields["haplogroup"] = normalize_haplogroup_value(fields["haplogroup"])
    fields["note"] = "\n".join(item for item in note_lines if item)
    return fields


def _imported_haplogroup_note(file_name: str, result: ImportedHaplogroup) -> str:
    lines = [
        f"Imported from {file_name}",
        f"Evidence: {result.evidence}",
    ]
    if result.positive_snp_count:
        lines.append(f"Positive SNPs in file: {result.positive_snp_count}")
    if result.matched_snp_count:
        lines.append(f"Matched reference SNPs: {result.matched_snp_count}")
    if result.lineage_votes:
        lines.append("Lineage vote: " + ", ".join(f"{lineage}:{count}" for lineage, count in result.lineage_votes[:8]))
    if result.top_snps:
        lines.append("Top positive SNPs: " + "; ".join(result.top_snps[:12]))
    if result.conflicting_snps:
        lines.append("Conflicting positives: " + "; ".join(result.conflicting_snps[:12]))
    return "\n".join(lines)


def _import_haplogroup_document(
    store: HaplogroupStore,
    user_id: int,
    sample: SampleAsset,
    temp_path: Path,
    file_name: str,
) -> tuple[list[HaplogroupRecord], YStrProfile | None]:
    imported = parse_haplogroup_result_file(temp_path, original_file_name=file_name)
    imported_str = parse_y_str_result_file(temp_path, original_file_name=file_name)
    records = [
        store.save_record(
            user_id,
            sample_id=sample.asset_id,
            sample_name=sample.display_name,
            haplogroup_type=result.haplogroup_type,
            haplogroup=result.haplogroup,
            terminal_snp=result.terminal_snp,
            source=result.source,
            confidence=result.confidence,
            note=_imported_haplogroup_note(file_name, result),
        )
        for result in imported
    ]
    str_profile = None
    if imported_str is not None:
        str_profile = store.save_y_str_profile(
            user_id,
            sample_id=sample.asset_id,
            sample_name=sample.display_name,
            source=imported_str.source,
            marker_values=imported_str.marker_values,
        )
    return records, str_profile


def _render_branch_visual(
    service: YFullBranchService,
    branch_name: str,
    output_path: Path,
    *,
    lang: str,
    theme: str,
):
    result = service.lookup(branch_name)
    render_yfull_branch_png(output_path, result, lang=lang, theme=theme)
    return result


def _branch_visual_caption(result, lang: str, *, tree_type: str = "y") -> str:
    branch = result.branch
    tree_name = "MTree" if tree_type == "mt" else "YTree"
    version = f"YFull {tree_name} v{branch.tree_version}" if branch.tree_version else f"YFull {tree_name}"
    details = []
    if branch.formed_ybp is not None:
        details.append(f"{_copy(lang, 'сформировалась', 'formed')}: {branch.formed_ybp:,}".replace(",", " "))
    if branch.tmrca_ybp is not None:
        details.append(f"TMRCA: {branch.tmrca_ybp:,}".replace(",", " "))
    lines = [f"<b>{html.escape(branch.name)}</b>", html.escape(version)]
    if details:
        lines.append(" · ".join(details))
    return "\n".join(lines)


async def _send_branch_visual(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    branch_name: str,
    user_id: int,
    lang: str,
    tree_type: str = "y",
) -> bool:
    image_path = _create_branch_visual_path()
    try:
        result = await asyncio.to_thread(
            _render_branch_visual,
            _yfull_tree_service(context, tree_type),
            branch_name,
            image_path,
            lang=lang,
            theme=_branch_visual_theme(context, user_id),
        )
        with image_path.open("rb") as handle:
            await message.reply_photo(
                photo=handle,
                caption=_branch_visual_caption(result, lang, tree_type=tree_type),
                parse_mode="HTML",
                do_quote=False,
            )
        return True
    except YFullLookupError as exc:
        await message.reply_text(branch_lookup_error_text(exc.reason, lang, tree_type=tree_type), parse_mode="HTML", do_quote=False)
        return False
    except Exception:
        logger.exception("YFull branch visual failed")
        await message.reply_text(
            _copy(lang, "Не удалось собрать карточку ветви.", "Could not render the branch card."),
            do_quote=False,
        )
        return False
    finally:
        try:
            image_path.unlink()
        except OSError:
            pass


def _branch_result_rows(context: ContextTypes.DEFAULT_TYPE, result, lang: str, *, tree_type: str = "y") -> list[list[InlineKeyboardButton]]:
    branch = result.branch
    rows: list[list[InlineKeyboardButton]] = []
    if branch.parent:
        parent_token = _remember_branch_nav_target(context, branch.parent)
        rows.append(
            [
                InlineKeyboardButton(
                    f"↑ {branch.parent}"[:60],
                    callback_data=f"{HAPLOGROUPS_CALLBACK_PREFIX}:bn:{tree_type}:{parent_token}",
                )
            ]
        )
    for child in (item for item in branch.children if not item.name.endswith("*")):
        child_token = _remember_branch_nav_target(context, child.name)
        label = f"↓ {child.name}"
        if child.public_sample_count:
            label += f" · {child.public_sample_count}"
        rows.append(
            [
                InlineKeyboardButton(
                    label[:60],
                    callback_data=f"{HAPLOGROUPS_CALLBACK_PREFIX}:bn:{tree_type}:{child_token}",
                )
            ]
        )
        if len(rows) >= 9:
            break
    rows.extend(
        [
            [
                InlineKeyboardButton(
                    _copy(lang, "🖼 Карточка ветви", "🖼 Branch card"),
                    callback_data=f"{HAPLOGROUPS_CALLBACK_PREFIX}:bv:{tree_type}:{_remember_branch_nav_target(context, branch.name)}",
                )
            ],
            [InlineKeyboardButton(_copy(lang, "Открыть в YFull", "Open in YFull"), url=branch.source_url)],
            [InlineKeyboardButton(_copy(lang, "Найти другую ветвь", "Find another branch"), callback_data=f"{HAPLOGROUPS_CALLBACK_PREFIX}:branch:{tree_type}")],
        ]
    )
    return rows


async def _complete_branch_lookup(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    body: str,
    chat_id: int,
    user_id: int,
    lang: str,
    tree_type: str = "y",
) -> bool:
    try:
        result = await asyncio.to_thread(_yfull_tree_service(context, tree_type).lookup, body)
    except YFullLookupError as exc:
        rows = [[InlineKeyboardButton(_copy(lang, "Попробовать снова", "Try again"), callback_data=f"{HAPLOGROUPS_CALLBACK_PREFIX}:branch:{tree_type}")]]
        await message.edit_text(
            branch_lookup_error_text(exc.reason, lang, tree_type=tree_type),
            reply_markup=build_markup(rows, f"{HAPLOGROUPS_CALLBACK_PREFIX}:trees", lang=lang),
            parse_mode="HTML",
        )
        set_active_main_menu_message(context, chat_id, user_id, message.message_id)
        return False
    except Exception:
        logger.exception("YFull branch lookup failed")
        await message.edit_text(
            branch_lookup_error_text("unavailable", lang, tree_type=tree_type),
            reply_markup=build_markup([], f"{HAPLOGROUPS_CALLBACK_PREFIX}:trees", lang=lang),
            parse_mode="HTML",
        )
        set_active_main_menu_message(context, chat_id, user_id, message.message_id)
        return False

    await message.edit_text(
        branch_lookup_result_text(result, lang, tree_type=tree_type),
        reply_markup=build_markup(_branch_result_rows(context, result, lang, tree_type=tree_type), f"{HAPLOGROUPS_CALLBACK_PREFIX}:trees", lang=lang),
        parse_mode="HTML",
    )
    set_active_main_menu_message(context, chat_id, user_id, message.message_id)
    return True


async def _handle_branch_lookup_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    body: str,
    chat_id: int,
    user_id: int,
    lang: str,
    flow: HaplogroupFlowStore,
    tree_type: str = "y",
) -> None:
    assert update.message is not None
    status_message = await update.message.reply_text(
        branch_lookup_loading_text(body, lang, tree_type=tree_type),
        parse_mode="HTML",
        do_quote=False,
    )
    completed = await _complete_branch_lookup(
        status_message,
        context,
        body=body,
        tree_type=tree_type,
        chat_id=chat_id,
        user_id=user_id,
        lang=lang,
    )
    if completed:
        flow.clear(chat_id, user_id)
    raise ApplicationHandlerStop


async def haplogroups_text_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.message.text is None or update.effective_chat is None or update.effective_user is None:
        return
    body = update.message.text.strip()
    if not body or body.startswith("/"):
        return

    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    lang = get_user_language(context, user_id)
    if _other_input_flow_active(context, chat_id, user_id):
        return
    flow = _flow_store(context)
    pending = flow.get(chat_id, user_id)
    if pending is None:
        return
    if pending.get("action") == _BRANCH_LOOKUP_ACTION:
        if not _looks_like_haplogroup_input(body):
            flow.clear(chat_id, user_id)
            return
        await _handle_branch_lookup_input(
            update,
            context,
            body=body,
            tree_type="mt" if pending.get("tree_type") == "mt" else "y",
            chat_id=chat_id,
            user_id=user_id,
            lang=lang,
            flow=flow,
        )
        return
    if pending.get("action") != _TEXT_ADD_ACTION:
        return

    fields = parse_haplogroup_input(body)
    if not fields["haplogroup"]:
        if not _looks_like_haplogroup_input(body):
            flow.clear(chat_id, user_id)
            return
        await update.message.reply_text(
            _copy(lang, "Пришлите haplogroup, например J2a1a или H13a1a.", "Send a haplogroup, for example J2a1a or H13a1a."),
            do_quote=False,
        )
        raise ApplicationHandlerStop

    sample_id = str(pending.get("sample_id") or "")
    sample = _my_data_store(context).get_sample(user_id, sample_id)
    if sample is None:
        flow.clear(chat_id, user_id)
        await update.message.reply_text(
            _copy(lang, "Не удалось найти sample. Откройте Haplogroups заново.", "Could not find the sample. Open Haplogroups again."),
            do_quote=False,
        )
        raise ApplicationHandlerStop

    record = _store(context).save_record(
        user_id,
        sample_id=sample.asset_id,
        sample_name=sample.display_name,
        haplogroup_type=str(pending.get("haplogroup_type") or "Y-DNA"),
        haplogroup=fields["haplogroup"],
        terminal_snp=fields["terminal_snp"],
        source=fields["source"],
        confidence=fields["confidence"],
        note=fields["note"],
    )
    flow.clear(chat_id, user_id)
    rows = [[InlineKeyboardButton(_copy(lang, "Открыть запись", "Open record"), callback_data=f"{HAPLOGROUPS_CALLBACK_PREFIX}:ho:{record.record_id}")]]
    sent = await update.message.reply_text(
        record_saved_text(record, lang),
        reply_markup=build_markup(rows, f"{HAPLOGROUPS_CALLBACK_PREFIX}:hsample:{sample.asset_id}", lang=lang),
        parse_mode="HTML",
        do_quote=False,
    )
    set_active_main_menu_message(context, chat_id, user_id, sent.message_id)
    raise ApplicationHandlerStop


async def haplogroups_document_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.message.document is None or update.effective_chat is None or update.effective_user is None:
        return

    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    lang = get_user_language(context, user_id)
    if _other_input_flow_active(context, chat_id, user_id):
        return
    flow = _flow_store(context)
    pending = flow.get(chat_id, user_id)
    if pending is None or pending.get("action") != _FILE_UPLOAD_ACTION:
        return

    sample_id = str(pending.get("sample_id") or "")
    sample = _my_data_store(context).get_sample(user_id, sample_id)
    if sample is None:
        flow.clear(chat_id, user_id)
        await update.message.reply_text(
            _copy(lang, "Не удалось найти sample. Откройте Haplogroups заново.", "Could not find the sample. Open Haplogroups again."),
            do_quote=False,
        )
        raise ApplicationHandlerStop

    document = update.message.document
    if document.file_size and document.file_size > HAPLOGROUP_RESULT_UPLOAD_LIMIT_BYTES:
        await update.message.reply_text(_file_too_large_text(lang), do_quote=False)
        raise ApplicationHandlerStop

    file_name = document.file_name or "haplogroup-result.txt"
    temp_path = _my_data_store(context).build_temp_path(user_id, file_name)
    status_message = await update.message.reply_text(
        _copy(lang, "Файл получен, читаю haplogroup/SNP/STR данные...", "File received, reading haplogroup/SNP/STR data..."),
        do_quote=False,
    )

    try:
        telegram_file = await document.get_file()
        await telegram_file.download_to_drive(custom_path=str(temp_path))
        if temp_path.stat().st_size > HAPLOGROUP_RESULT_UPLOAD_LIMIT_BYTES:
            flow.clear(chat_id, user_id)
            await status_message.edit_text(_file_too_large_text(lang))
            raise ApplicationHandlerStop
        records, str_profile = await asyncio.to_thread(
            _import_haplogroup_document,
            _store(context),
            user_id,
            sample,
            temp_path,
            file_name,
        )
    except ApplicationHandlerStop:
        raise
    except Exception:
        logger.exception("Haplogroup result file import failed")
        await update.message.reply_text(
            _copy(
                lang,
                "Не удалось прочитать haplogroup-файл. Лучше прислать .txt/.csv/.tsv экспорт.",
                "Could not read the haplogroup file. A .txt/.csv/.tsv export works best.",
            ),
            do_quote=False,
        )
        raise ApplicationHandlerStop
    finally:
        _my_data_store(context).cleanup_temp_file(temp_path)

    flow.clear(chat_id, user_id)
    if not records:
        if str_profile is not None:
            rows = [[InlineKeyboardButton(_copy(lang, "📈 Открыть Y-STR", "📈 Open Y-STR profiles"), callback_data=f"{HAPLOGROUPS_CALLBACK_PREFIX}:str")]]
            await status_message.edit_text(
                imported_str_profile_text(sample, str_profile, lang),
                reply_markup=build_markup(rows, f"{HAPLOGROUPS_CALLBACK_PREFIX}:str", lang=lang),
                parse_mode="HTML",
            )
            set_active_main_menu_message(context, chat_id, user_id, status_message.message_id)
            raise ApplicationHandlerStop
        await status_message.edit_text(
            _copy(
                lang,
                "В файле не нашёл Y-DNA/mtDNA haplogroup или FTDNA SNP Results. "
                "Y-STR/DYS CSV тоже поддерживается, если это таблица DYS markers + values.",
                "I could not find a Y-DNA/mtDNA haplogroup or FTDNA SNP Results in the file. "
                "Y-STR/DYS CSV is also supported when it is a table of DYS markers and values.",
            )
        )
        raise ApplicationHandlerStop

    rows = [[InlineKeyboardButton(_copy(lang, "Открыть записи", "Open records"), callback_data=f"{HAPLOGROUPS_CALLBACK_PREFIX}:hsample:{sample.asset_id}")]]
    await status_message.edit_text(
        imported_records_text(sample, records, lang, str_profile=str_profile),
        reply_markup=build_markup(rows, f"{HAPLOGROUPS_CALLBACK_PREFIX}:root", lang=lang),
        parse_mode="HTML",
    )
    set_active_main_menu_message(context, chat_id, user_id, status_message.message_id)
    raise ApplicationHandlerStop


async def haplogroups_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None or query.message is None or update.effective_user is None or update.effective_chat is None:
        return
    if not query.data.startswith(f"{HAPLOGROUPS_CALLBACK_PREFIX}:"):
        return
    if not await ensure_active_main_menu(update, context):
        return

    await query.answer()
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    lang = get_user_language(context, user_id)
    parts = query.data.split(":")
    action = parts[1] if len(parts) > 1 else "root"

    if action not in {"pick", "strb"}:
        _flow_store(context).clear(chat_id, user_id)

    if action == "cancel":
        _flow_store(context).clear(chat_id, user_id)
        context.user_data.pop("haplogroups_add_data_origin", None)
        try:
            await query.message.delete()
        except Exception:
            await query.message.edit_text(_copy(lang, "Отменено.", "Cancelled."))
        return
    if action == "root":
        context.user_data.pop("haplogroups_add_data_origin", None)
        await show_haplogroups_menu(query.message, context, user_id, lang=lang, edit_existing=True)
        return
    if action == "trees":
        await show_branch_trees_menu(query.message, lang=lang, edit_existing=True)
        return
    if action == "branch":
        tree_type = "mt" if len(parts) > 2 and parts[2] == "mt" else "y"
        await show_branch_lookup_prompt(
            query.message,
            context,
            user_id,
            chat_id,
            tree_type=tree_type,
            lang=lang,
            edit_existing=True,
        )
        return
    if action == "bv":
        tree_type = parts[2] if len(parts) > 2 and parts[2] in {"y", "mt"} else "y"
        token_index = 3 if len(parts) > 2 and parts[2] in {"y", "mt"} else 2
        branch_name = _resolve_branch_nav_target(context, parts[token_index] if len(parts) > token_index else "")
        if not branch_name:
            await show_branch_lookup_prompt(
                query.message,
                context,
                user_id,
                chat_id,
                tree_type=tree_type,
                lang=lang,
                edit_existing=True,
            )
            return
        await _send_branch_visual(
            query.message,
            context,
            branch_name=branch_name,
            tree_type=tree_type,
            user_id=user_id,
            lang=lang,
        )
        return
    if action == "bn":
        tree_type = parts[2] if len(parts) > 2 and parts[2] in {"y", "mt"} else "y"
        token_index = 3 if len(parts) > 2 and parts[2] in {"y", "mt"} else 2
        branch_name = _resolve_branch_nav_target(context, parts[token_index] if len(parts) > token_index else "")
        if not branch_name:
            await show_branch_lookup_prompt(
                query.message,
                context,
                user_id,
                chat_id,
                tree_type=tree_type,
                lang=lang,
                edit_existing=True,
            )
            return
        await _show_or_edit(
            query.message,
            branch_lookup_loading_text(branch_name, lang, tree_type=tree_type),
            build_markup([], f"{HAPLOGROUPS_CALLBACK_PREFIX}:trees", lang=lang),
            edit_existing=True,
        )
        await _complete_branch_lookup(
            query.message,
            context,
            body=branch_name,
            tree_type=tree_type,
            chat_id=chat_id,
            user_id=user_id,
            lang=lang,
        )
        return
    if action == "y":
        await show_lineage_menu(query.message, "y", lang=lang, edit_existing=True)
        return
    if action == "mt":
        await show_lineage_menu(query.message, "mt", lang=lang, edit_existing=True)
        return
    if action == "detect":
        await show_detect_type_menu(query.message, lang=lang, edit_existing=True)
        return
    if action == "manual":
        context.user_data.pop("haplogroups_add_data_origin", None)
        await show_manual_type_menu(query.message, lang=lang, edit_existing=True)
        return
    if action == "manual_add_data":
        context.user_data["haplogroups_add_data_origin"] = True
        await show_manual_type_menu(
            query.message,
            back_callback="mydna:add_data",
            lang=lang,
            edit_existing=True,
        )
        return
    if action == "upload":
        await show_upload_sample_picker(
            query.message,
            context,
            user_id,
            page=_parse_page(parts[2] if len(parts) > 2 else None),
            lang=lang,
            edit_existing=True,
        )
        return
    if action == "saved":
        await show_haplogroups_menu(query.message, context, user_id, lang=lang, edit_existing=True)
        return
    if action == "str":
        await show_str_profiles_menu(query.message, context, user_id, lang=lang, edit_existing=True)
        return
    if action == "strv":
        await show_str_profile_detail(
            query.message,
            context,
            user_id,
            parts[2] if len(parts) > 2 else "",
            lang=lang,
            edit_existing=True,
        )
        return
    if action == "scmp":
        await show_str_compare_picker(query.message, context, user_id, lang=lang, edit_existing=True)
        return
    if action == "stra":
        left_profile = _store(context).find_y_str_profile(user_id, parts[2] if len(parts) > 2 else "")
        if left_profile is None:
            await show_str_profiles_menu(query.message, context, user_id, lang=lang, edit_existing=True)
            return
        _flow_store(context).expect(
            chat_id,
            user_id,
            {"left_profile_id": left_profile.profile_id},
            action=_STR_COMPARE_ACTION,
        )
        await show_str_compare_picker(query.message, context, user_id, left_profile=left_profile, lang=lang, edit_existing=True)
        return
    if action == "strb":
        pending = _flow_store(context).get(chat_id, user_id)
        left_profile_id = str((pending or {}).get("left_profile_id") or "")
        _flow_store(context).clear(chat_id, user_id)
        await show_str_distance_result(
            query.message,
            context,
            user_id,
            left_profile_id,
            parts[2] if len(parts) > 2 else "",
            lang=lang,
            edit_existing=True,
        )
        return
    if action == "upick":
        await show_upload_result_prompt(
            query.message,
            context,
            user_id,
            chat_id,
            parts[2] if len(parts) > 2 else "",
            lang=lang,
            edit_existing=True,
        )
        return
    if action == "add":
        back_to_add_data = bool(context.user_data.get("haplogroups_add_data_origin"))
        await show_sample_picker(
            query.message,
            context,
            user_id,
            parts[2] if len(parts) > 2 else "",
            page=_parse_page(parts[3] if len(parts) > 3 else None),
            mode="manual",
            back_callback=f"{HAPLOGROUPS_CALLBACK_PREFIX}:manual_add_data" if back_to_add_data else None,
            lang=lang,
            edit_existing=True,
        )
        return
    if action == "dadd":
        await show_sample_picker(
            query.message,
            context,
            user_id,
            parts[2] if len(parts) > 2 else "",
            page=_parse_page(parts[3] if len(parts) > 3 else None),
            mode="detect",
            lang=lang,
            edit_existing=True,
        )
        return
    if action == "dpick":
        await show_raw_scan_result(
            query.message,
            context,
            user_id,
            parts[2] if len(parts) > 2 else "",
            parts[3] if len(parts) > 3 else "",
            lang=lang,
            edit_existing=True,
        )
        return
    if action == "yp":
        await show_y_prediction(
            query.message,
            context,
            user_id,
            parts[2] if len(parts) > 2 else "",
            lang=lang,
            edit_existing=True,
        )
        return
    if action == "pick":
        await show_haplogroup_input_prompt(
            query.message,
            context,
            user_id,
            chat_id,
            parts[2] if len(parts) > 2 else "",
            parts[3] if len(parts) > 3 else "",
            lang=lang,
            edit_existing=True,
        )
        return
    if action == "list":
        type_code = parts[2] if len(parts) > 2 else ""
        page_text = parts[3] if len(parts) > 3 else None
        if type_code == "all":
            type_code = ""
        elif type_code and type_code not in _TYPE_CODES and type_code.isdigit():
            page_text = type_code
            type_code = ""
        await show_records_menu(
            query.message,
            context,
            user_id,
            haplogroup_type=_TYPE_CODES.get(type_code),
            page=_parse_page(page_text),
            page_callback_base=f"{HAPLOGROUPS_CALLBACK_PREFIX}:list:{type_code or 'all'}",
            back_callback=f"{HAPLOGROUPS_CALLBACK_PREFIX}:{type_code}" if type_code in _TYPE_CODES else f"{HAPLOGROUPS_CALLBACK_PREFIX}:root",
            lang=lang,
            edit_existing=True,
        )
        return
    if action == "hsample":
        await show_records_menu(
            query.message,
            context,
            user_id,
            sample_id=parts[2] if len(parts) > 2 else "",
            page=_parse_page(parts[3] if len(parts) > 3 else None),
            page_callback_base=f"{HAPLOGROUPS_CALLBACK_PREFIX}:hsample:{parts[2]}" if len(parts) > 2 else None,
            back_callback=f"{HAPLOGROUPS_CALLBACK_PREFIX}:root",
            record_action="ho",
            lang=lang,
            edit_existing=True,
        )
        return
    if action == "sample":
        await show_records_menu(
            query.message,
            context,
            user_id,
            sample_id=parts[2] if len(parts) > 2 else "",
            page=_parse_page(parts[3] if len(parts) > 3 else None),
            page_callback_base=f"{HAPLOGROUPS_CALLBACK_PREFIX}:sample:{parts[2]}" if len(parts) > 2 else None,
            back_callback="my_data:samples_view",
            lang=lang,
            edit_existing=True,
        )
        return
    if action == "o":
        await show_record_detail(query.message, context, user_id, parts[2] if len(parts) > 2 else "", lang=lang, edit_existing=True)
        return
    if action == "ho":
        record_id = parts[2] if len(parts) > 2 else ""
        record = _store(context).find_record(user_id, record_id)
        await show_record_detail(
            query.message,
            context,
            user_id,
            record_id,
            back_callback=f"{HAPLOGROUPS_CALLBACK_PREFIX}:hsample:{record.sample_id}" if record is not None else f"{HAPLOGROUPS_CALLBACK_PREFIX}:root",
            lang=lang,
            edit_existing=True,
        )
