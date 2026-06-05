from __future__ import annotations

import re
import tempfile
from itertools import combinations
from math import ceil
from pathlib import Path
from uuid import uuid4

from telegram import InlineKeyboardButton, Update
from telegram.ext import Application, ApplicationHandlerStop, ContextTypes

from app.i18n import get_user_language
from app.features.my_data.storage import MyDataStore, SampleAsset
from app.main_menu import ensure_active_main_menu, set_active_main_menu_message

from .domain import compare_raw_autosomal_match, compare_raw_autosomal_profiles, load_raw_autosomal_profile, lookup_snp_in_raw
from .genetic_map import default_genetic_map
from .ui import (
    all_pairs_confirm_text,
    all_pairs_result_text,
    all_pairs_running_text,
    all_pairs_visual_caption,
    build_markup,
    matching_error_text,
    matching_root_text,
    matching_running_text,
    match_saved_text,
    pairwise_result_text,
    pairwise_visual_caption,
    sample_picker_text,
    saved_match_button_label,
    saved_match_detail_text,
    saved_match_visual_caption,
    saved_matches_text,
    selected_samples_picker_text,
    selected_samples_running_text,
    selected_samples_visual_caption,
    snp_input_text,
    snp_result_text,
    snp_sample_picker_text,
)
from .storage import MatchingStore
from .visualization import render_all_pairs_match_png, render_pairwise_match_png


MATCHING_CALLBACK_PREFIX = "matching"
_PAGE_SIZE = 8
_SNP_INPUT_ACTION = "snp_input"
_RSID_PATTERN = re.compile(r"^rs\d+$", re.IGNORECASE)


class MatchingFlowStore:
    def __init__(self) -> None:
        self._payloads: dict[str, dict[str, object]] = {}
        self._pending: dict[tuple[int, int], dict[str, object]] = {}

    def create(self, *, user_id: int, payload: dict[str, object]) -> str:
        token = uuid4().hex[:8]
        self._payloads[token] = {"user_id": int(user_id), **payload}
        return token

    def get(self, token: str, user_id: int) -> dict[str, object] | None:
        payload = self._payloads.get(token)
        if payload is None or int(payload.get("user_id", -1)) != int(user_id):
            return None
        return dict(payload)

    def update(self, token: str, user_id: int, payload: dict[str, object]) -> bool:
        current = self._payloads.get(token)
        if current is None or int(current.get("user_id", -1)) != int(user_id):
            return False
        self._payloads[token] = {"user_id": int(user_id), **payload}
        return True

    def expect(self, chat_id: int, user_id: int, payload: dict[str, object]) -> None:
        self._pending[(int(chat_id), int(user_id))] = dict(payload)

    def get_pending(self, chat_id: int, user_id: int) -> dict[str, object] | None:
        payload = self._pending.get((int(chat_id), int(user_id)))
        return dict(payload) if payload is not None else None

    def clear_pending(self, chat_id: int, user_id: int) -> None:
        self._pending.pop((int(chat_id), int(user_id)), None)


def register_matching_services(application: Application, settings) -> None:
    application.bot_data["matching_flow_store"] = MatchingFlowStore()
    application.bot_data["matching_store"] = MatchingStore(settings.root_dir / "storage" / "matching")


def _my_data_store(context: ContextTypes.DEFAULT_TYPE) -> MyDataStore:
    return context.application.bot_data["my_data_store"]


def _flow_store(context: ContextTypes.DEFAULT_TYPE) -> MatchingFlowStore:
    store = context.application.bot_data.get("matching_flow_store")
    if isinstance(store, MatchingFlowStore):
        return store
    store = MatchingFlowStore()
    context.application.bot_data["matching_flow_store"] = store
    return store


def _match_store(context: ContextTypes.DEFAULT_TYPE) -> MatchingStore:
    store = context.application.bot_data.get("matching_store")
    if isinstance(store, MatchingStore):
        return store
    store = MatchingStore(context.application.bot_data["my_data_store"].root_dir.parent / "matching")
    context.application.bot_data["matching_store"] = store
    return store


def _paginate(items: list[SampleAsset], page: int) -> tuple[list[SampleAsset], int, int]:
    total_pages = max(1, ceil(len(items) / _PAGE_SIZE)) if items else 1
    normalized_page = max(0, min(page, total_pages - 1))
    start = normalized_page * _PAGE_SIZE
    return items[start:start + _PAGE_SIZE], normalized_page, total_pages


def _samples_with_raw(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> list[SampleAsset]:
    store = _my_data_store(context)
    return [sample for sample in store.list_samples(user_id) if store.get_sample_raw_file(user_id, sample.asset_id) is not None]


def _pair_count(sample_count: int) -> int:
    return sample_count * (sample_count - 1) // 2


def _selected_ids(flow: dict[str, object] | None) -> list[str]:
    if not flow:
        return []
    values = flow.get("sample_ids")
    if not isinstance(values, list):
        return []
    return [str(value) for value in values if value]


def _selected_samples_from_ids(samples: list[SampleAsset], sample_ids: list[str]) -> list[SampleAsset]:
    by_id = {sample.asset_id: sample for sample in samples}
    return [by_id[sample_id] for sample_id in sample_ids if sample_id in by_id]


def _store_selected_ids(context: ContextTypes.DEFAULT_TYPE, user_id: int, token: str, sample_ids: list[str]) -> None:
    _flow_store(context).update(
        token,
        user_id,
        {
            "mode": "selected_samples",
            "sample_ids": list(dict.fromkeys(sample_ids)),
        },
    )


def normalize_rsid(value: str) -> str | None:
    candidate = value.strip().lower()
    return candidate if _RSID_PATTERN.fullmatch(candidate) else None


def _has_other_text_pending(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> bool:
    user_data = getattr(context, "user_data", {}) or {}
    sozluk_pending = user_data.get("sozluk_pending")
    if isinstance(sozluk_pending, dict):
        if int(sozluk_pending.get("chat_id") or 0) == int(chat_id):
            return True
    elif "sozluk_pending_direction" in user_data:
        return True

    ystr_pending = user_data.get("ystr_pending")
    return isinstance(ystr_pending, dict) and int(ystr_pending.get("chat_id") or 0) == int(chat_id)


def _snp_selected_ids(flow: dict[str, object] | None) -> list[str]:
    return _selected_ids(flow)


def _store_snp_selected_ids(context: ContextTypes.DEFAULT_TYPE, user_id: int, token: str, rsid: str, sample_ids: list[str]) -> None:
    _flow_store(context).update(
        token,
        user_id,
        {
            "mode": "snp_lookup",
            "rsid": rsid,
            "sample_ids": list(dict.fromkeys(sample_ids)),
        },
    )


def _create_visualization_path() -> Path:
    return Path(tempfile.gettempdir()) / f"dna_matching_{uuid4().hex}.png"


def _is_photo_message(message) -> bool:
    return bool(getattr(message, "photo", None))


def _message_chat_id(message) -> int | None:
    chat_id = getattr(message, "chat_id", None)
    if chat_id is not None:
        return int(chat_id)
    chat = getattr(message, "chat", None)
    if chat is not None and getattr(chat, "id", None) is not None:
        return int(chat.id)
    return None


def _set_active_if_possible(context: ContextTypes.DEFAULT_TYPE | None, message, user_id: int | None) -> None:
    chat_id = _message_chat_id(message)
    message_id = getattr(message, "message_id", None)
    if context is not None and user_id is not None and chat_id is not None and message_id is not None:
        set_active_main_menu_message(context, chat_id, user_id, int(message_id))


async def _clear_old_visual_markup(message) -> None:
    try:
        await message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass


async def _delete_old_status_message(message) -> None:
    if _is_photo_message(message):
        await _clear_old_visual_markup(message)
        return
    try:
        await message.delete()
    except Exception:
        pass


async def _show_status_message(
    message,
    text_value: str,
    reply_markup=None,
    *,
    context: ContextTypes.DEFAULT_TYPE | None = None,
    user_id: int | None = None,
):
    if _is_photo_message(message):
        status_message = await message.reply_text(text_value, reply_markup=reply_markup, parse_mode="HTML", do_quote=False)
        _set_active_if_possible(context, status_message, user_id)
        await _clear_old_visual_markup(message)
        return status_message
    await message.edit_text(text_value, reply_markup=reply_markup, parse_mode="HTML")
    return message


async def _show_or_edit(
    message,
    text_value: str,
    reply_markup,
    *,
    edit_existing: bool = False,
    context: ContextTypes.DEFAULT_TYPE | None = None,
    user_id: int | None = None,
) -> None:
    if edit_existing:
        if _is_photo_message(message):
            sent = await message.reply_text(text_value, reply_markup=reply_markup, parse_mode="HTML", do_quote=False)
            _set_active_if_possible(context, sent, user_id)
            await _clear_old_visual_markup(message)
            return
        await message.edit_text(text_value, reply_markup=reply_markup, parse_mode="HTML")
    else:
        sent = await message.reply_text(text_value, reply_markup=reply_markup, parse_mode="HTML", do_quote=False)
        _set_active_if_possible(context, sent, user_id)


async def _send_visual_or_fallback(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    image_path: Path,
    caption: str,
    fallback_text: str,
    reply_markup,
    edit_existing: bool = True,
) -> None:
    try:
        with image_path.open("rb") as handle:
            sent = await message.reply_photo(
                photo=handle,
                caption=caption,
                reply_markup=reply_markup,
                parse_mode="HTML",
                do_quote=False,
            )
        _set_active_if_possible(context, sent, user_id)
        await _delete_old_status_message(message)
    except Exception:
        if edit_existing and not _is_photo_message(message):
            await message.edit_text(fallback_text, reply_markup=reply_markup, parse_mode="HTML")
        else:
            await _show_or_edit(
                message,
                fallback_text,
                reply_markup,
                edit_existing=edit_existing,
                context=context,
                user_id=user_id,
            )
    finally:
        try:
            image_path.unlink()
        except FileNotFoundError:
            pass


async def _show_pairwise_visual(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    left: SampleAsset,
    right: SampleAsset,
    result,
    caption: str,
    fallback_text: str,
    reply_markup,
    status_label: str = "PAIRWISE",
    edit_existing: bool = True,
) -> None:
    image_path = _create_visualization_path()
    try:
        render_pairwise_match_png(
            image_path,
            left_name=left.display_name,
            right_name=right.display_name,
            result=result,
            status_label=status_label,
        )
    except Exception:
        try:
            image_path.unlink()
        except FileNotFoundError:
            pass
        await _show_or_edit(
            message,
            fallback_text,
            reply_markup,
            edit_existing=edit_existing,
            context=context,
            user_id=user_id,
        )
        return
    await _send_visual_or_fallback(
        message,
        context,
        user_id,
        image_path=image_path,
        caption=caption,
        fallback_text=fallback_text,
        reply_markup=reply_markup,
        edit_existing=edit_existing,
    )


async def _show_saved_match_visual(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    record,
    caption: str,
    fallback_text: str,
    reply_markup,
    status_label: str = "SAVED",
    edit_existing: bool = True,
) -> None:
    image_path = _create_visualization_path()
    try:
        render_pairwise_match_png(
            image_path,
            left_name=record.summary.left_sample_name,
            right_name=record.summary.right_sample_name,
            result=record.payload,
            status_label=status_label,
        )
    except Exception:
        try:
            image_path.unlink()
        except FileNotFoundError:
            pass
        await _show_or_edit(
            message,
            fallback_text,
            reply_markup,
            edit_existing=edit_existing,
            context=context,
            user_id=user_id,
        )
        return
    await _send_visual_or_fallback(
        message,
        context,
        user_id,
        image_path=image_path,
        caption=caption,
        fallback_text=fallback_text,
        reply_markup=reply_markup,
        edit_existing=edit_existing,
    )


async def _show_all_pairs_visual(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    results,
    sample_count: int,
    caption: str,
    fallback_text: str,
    reply_markup,
    edit_existing: bool = True,
) -> None:
    image_path = _create_visualization_path()
    try:
        render_all_pairs_match_png(
            image_path,
            results=results,
            sample_count=sample_count,
        )
    except Exception:
        try:
            image_path.unlink()
        except FileNotFoundError:
            pass
        await _show_or_edit(
            message,
            fallback_text,
            reply_markup,
            edit_existing=edit_existing,
            context=context,
            user_id=user_id,
        )
        return
    await _send_visual_or_fallback(
        message,
        context,
        user_id,
        image_path=image_path,
        caption=caption,
        fallback_text=fallback_text,
        reply_markup=reply_markup,
        edit_existing=edit_existing,
    )


async def _calculate_pairwise_results(
    store: MyDataStore,
    user_id: int,
    samples: list[SampleAsset],
    *,
    status_message=None,
    progress_text_factory=None,
    progress_back_callback: str | None = None,
    lang: str = "ru",
):
    parsed = {}
    for sample in samples:
        raw_file = store.get_sample_raw_file(user_id, sample.asset_id)
        if raw_file is None:
            continue
        parsed[sample.asset_id] = load_raw_autosomal_profile(store.resolve_raw_file_path(raw_file))

    cm_map = default_genetic_map()
    results = []
    sample_pairs = list(combinations(samples, 2))
    total_pairs = len(sample_pairs)
    for index, (left, right) in enumerate(sample_pairs, start=1):
        left_profile = parsed.get(left.asset_id)
        right_profile = parsed.get(right.asset_id)
        if left_profile is None or right_profile is None:
            continue
        result = compare_raw_autosomal_profiles(
            left_profile,
            right_profile,
            genetic_map=cm_map,
        )
        results.append((left, right, result))
        if (
            status_message is not None
            and progress_text_factory is not None
            and progress_back_callback is not None
            and index < total_pairs
            and (index == 1 or index % 5 == 0)
        ):
            await status_message.edit_text(
                progress_text_factory(completed_pairs=index, total_pairs=total_pairs),
                reply_markup=build_markup([], progress_back_callback, lang=lang),
                parse_mode="HTML",
            )
    return results


async def show_matching_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    edit_existing: bool = False,
    lang: str = "ru",
) -> None:
    pair_label = "🧬 Compare two samples" if lang == "en" else "🧬 Сравнить два sample"
    selected_label = "✅ Compare selected samples" if lang == "en" else "✅ Сравнить выбранные sample"
    all_label = "📊 Compare all samples" if lang == "en" else "📊 Сравнить все sample"
    snp_label = "🔎 Compare SNP" if lang == "en" else "🔎 Сравнить SNP"
    saved_label = "💾 Saved matches" if lang == "en" else "💾 Сохранённые matches"
    rows = [
        [InlineKeyboardButton(pair_label, callback_data=f"{MATCHING_CALLBACK_PREFIX}:pair:0")],
        [InlineKeyboardButton(selected_label, callback_data=f"{MATCHING_CALLBACK_PREFIX}:selected")],
        [InlineKeyboardButton(all_label, callback_data=f"{MATCHING_CALLBACK_PREFIX}:all")],
        [InlineKeyboardButton(snp_label, callback_data=f"{MATCHING_CALLBACK_PREFIX}:snp")],
        [InlineKeyboardButton(saved_label, callback_data=f"{MATCHING_CALLBACK_PREFIX}:saved")],
    ]
    await _show_or_edit(
        message,
        matching_root_text(lang=lang),
        build_markup(rows, "main:root", lang=lang),
        edit_existing=edit_existing,
        context=context,
        user_id=user_id,
    )


async def show_left_sample_picker(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    page: int = 0,
    edit_existing: bool = False,
    lang: str = "ru",
) -> None:
    samples = _samples_with_raw(context, user_id)
    page_samples, current_page, total_pages = _paginate(samples, page)
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(sample.display_name, callback_data=f"{MATCHING_CALLBACK_PREFIX}:a:{sample.asset_id}")]
        for sample in page_samples
    ]
    pager = []
    if current_page > 0:
        pager.append(InlineKeyboardButton("Back" if lang == "en" else "Назад", callback_data=f"{MATCHING_CALLBACK_PREFIX}:pair:{current_page - 1}"))
    if current_page + 1 < total_pages:
        pager.append(InlineKeyboardButton("Next" if lang == "en" else "Далее", callback_data=f"{MATCHING_CALLBACK_PREFIX}:pair:{current_page + 1}"))
    if pager:
        rows.append(pager)
    await _show_or_edit(
        message,
        sample_picker_text(samples, side="left", lang=lang),
        build_markup(rows, f"{MATCHING_CALLBACK_PREFIX}:root", lang=lang),
        edit_existing=edit_existing,
        context=context,
        user_id=user_id,
    )


async def show_right_sample_picker(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    left_sample_id: str,
    *,
    page: int = 0,
    edit_existing: bool = False,
    lang: str = "ru",
) -> None:
    store = _my_data_store(context)
    left_sample = store.get_sample(user_id, left_sample_id)
    if left_sample is None or store.get_sample_raw_file(user_id, left_sample.asset_id) is None:
        await show_left_sample_picker(message, context, user_id, edit_existing=edit_existing, lang=lang)
        return
    token = _flow_store(context).create(user_id=user_id, payload={"left_sample_id": left_sample.asset_id})
    samples = [sample for sample in _samples_with_raw(context, user_id) if sample.asset_id != left_sample.asset_id]
    page_samples, current_page, total_pages = _paginate(samples, page)
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(sample.display_name, callback_data=f"{MATCHING_CALLBACK_PREFIX}:b:{token}:{sample.asset_id}")]
        for sample in page_samples
    ]
    pager = []
    if current_page > 0:
        pager.append(InlineKeyboardButton("Back" if lang == "en" else "Назад", callback_data=f"{MATCHING_CALLBACK_PREFIX}:pb:{token}:{current_page - 1}"))
    if current_page + 1 < total_pages:
        pager.append(InlineKeyboardButton("Next" if lang == "en" else "Далее", callback_data=f"{MATCHING_CALLBACK_PREFIX}:pb:{token}:{current_page + 1}"))
    if pager:
        rows.append(pager)
    await _show_or_edit(
        message,
        sample_picker_text(samples, side="right", left_sample=left_sample, lang=lang),
        build_markup(rows, f"{MATCHING_CALLBACK_PREFIX}:pair:0", lang=lang),
        edit_existing=edit_existing,
        context=context,
        user_id=user_id,
    )


async def show_selected_sample_picker(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    token: str | None = None,
    page: int = 0,
    edit_existing: bool = False,
    lang: str = "ru",
) -> str:
    store = _flow_store(context)
    if token is None:
        token = store.create(user_id=user_id, payload={"mode": "selected_samples", "sample_ids": []})
        selected_ids: list[str] = []
    else:
        flow = store.get(token, user_id)
        if flow is None:
            token = store.create(user_id=user_id, payload={"mode": "selected_samples", "sample_ids": []})
            selected_ids = []
        else:
            selected_ids = _selected_ids(flow)

    samples = _samples_with_raw(context, user_id)
    available_ids = {sample.asset_id for sample in samples}
    selected_ids = [sample_id for sample_id in selected_ids if sample_id in available_ids]
    _store_selected_ids(context, user_id, token, selected_ids)

    page_samples, current_page, total_pages = _paginate(samples, page)
    selected_set = set(selected_ids)
    rows: list[list[InlineKeyboardButton]] = []
    for offset, sample in enumerate(page_samples, start=1):
        index = current_page * _PAGE_SIZE + offset
        marker = "[x] " if sample.asset_id in selected_set else ""
        rows.append([
            InlineKeyboardButton(
                f"{marker}{index}. {sample.display_name}",
                callback_data=f"{MATCHING_CALLBACK_PREFIX}:st:{token}:{sample.asset_id}:{current_page}",
            )
        ])

    pager = []
    if current_page > 0:
        pager.append(InlineKeyboardButton("Back" if lang == "en" else "Назад", callback_data=f"{MATCHING_CALLBACK_PREFIX}:ss:{token}:{current_page - 1}"))
    if current_page + 1 < total_pages:
        pager.append(InlineKeyboardButton("Next" if lang == "en" else "Далее", callback_data=f"{MATCHING_CALLBACK_PREFIX}:ss:{token}:{current_page + 1}"))
    if pager:
        rows.append(pager)

    rows.append([InlineKeyboardButton("✅ Select all" if lang == "en" else "✅ Выбрать все", callback_data=f"{MATCHING_CALLBACK_PREFIX}:sall:{token}:{current_page}")])
    rows.append([
        InlineKeyboardButton("✅ Done" if lang == "en" else "✅ Готово", callback_data=f"{MATCHING_CALLBACK_PREFIX}:srun:{token}"),
        InlineKeyboardButton("🧹 Clear" if lang == "en" else "🧹 Очистить", callback_data=f"{MATCHING_CALLBACK_PREFIX}:sclr:{token}:{current_page}"),
    ])
    await _show_or_edit(
        message,
        selected_samples_picker_text(len(selected_ids), lang=lang),
        build_markup(rows, f"{MATCHING_CALLBACK_PREFIX}:root", lang=lang),
        edit_existing=edit_existing,
        context=context,
        user_id=user_id,
    )
    return token


async def show_snp_input_screen(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    chat_id: int,
    *,
    edit_existing: bool = False,
    lang: str = "ru",
) -> None:
    _flow_store(context).expect(chat_id, user_id, {"action": _SNP_INPUT_ACTION})
    await _show_or_edit(
        message,
        snp_input_text(lang=lang),
        build_markup([], f"{MATCHING_CALLBACK_PREFIX}:root", lang=lang),
        edit_existing=edit_existing,
        context=context,
        user_id=user_id,
    )


async def show_snp_sample_picker(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    token: str,
    page: int = 0,
    edit_existing: bool = False,
    lang: str = "ru",
) -> None:
    flow = _flow_store(context).get(token, user_id)
    rsid = str((flow or {}).get("rsid") or "")
    if not rsid:
        await show_snp_input_screen(message, context, user_id, _message_chat_id(message) or 0, edit_existing=edit_existing, lang=lang)
        return

    selected_ids = _snp_selected_ids(flow)
    samples = _samples_with_raw(context, user_id)
    available_ids = {sample.asset_id for sample in samples}
    selected_ids = [sample_id for sample_id in selected_ids if sample_id in available_ids]
    _store_snp_selected_ids(context, user_id, token, rsid, selected_ids)

    page_samples, current_page, total_pages = _paginate(samples, page)
    selected_set = set(selected_ids)
    rows: list[list[InlineKeyboardButton]] = []
    for offset, sample in enumerate(page_samples, start=1):
        index = current_page * _PAGE_SIZE + offset
        marker = "[x] " if sample.asset_id in selected_set else ""
        rows.append([
            InlineKeyboardButton(
                f"{marker}{index}. {sample.display_name}",
                callback_data=f"{MATCHING_CALLBACK_PREFIX}:snpt:{token}:{sample.asset_id}:{current_page}",
            )
        ])

    pager = []
    if current_page > 0:
        pager.append(InlineKeyboardButton("Back" if lang == "en" else "Назад", callback_data=f"{MATCHING_CALLBACK_PREFIX}:snps:{token}:{current_page - 1}"))
    if current_page + 1 < total_pages:
        pager.append(InlineKeyboardButton("Next" if lang == "en" else "Далее", callback_data=f"{MATCHING_CALLBACK_PREFIX}:snps:{token}:{current_page + 1}"))
    if pager:
        rows.append(pager)

    rows.append([InlineKeyboardButton("✅ Select all" if lang == "en" else "✅ Выбрать все", callback_data=f"{MATCHING_CALLBACK_PREFIX}:snpall:{token}:{current_page}")])
    rows.append([
        InlineKeyboardButton("✅ Done" if lang == "en" else "✅ Готово", callback_data=f"{MATCHING_CALLBACK_PREFIX}:snprun:{token}"),
        InlineKeyboardButton("🧹 Clear" if lang == "en" else "🧹 Очистить", callback_data=f"{MATCHING_CALLBACK_PREFIX}:snpclr:{token}:{current_page}"),
    ])
    await _show_or_edit(
        message,
        snp_sample_picker_text(rsid, len(selected_ids), lang=lang),
        build_markup(rows, f"{MATCHING_CALLBACK_PREFIX}:snp", lang=lang),
        edit_existing=edit_existing,
        context=context,
        user_id=user_id,
    )


async def toggle_snp_sample(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    token: str,
    sample_id: str,
    *,
    page: int = 0,
    edit_existing: bool = True,
    lang: str = "ru",
) -> None:
    flow = _flow_store(context).get(token, user_id)
    rsid = str((flow or {}).get("rsid") or "")
    if not flow or not rsid:
        await show_snp_input_screen(message, context, user_id, _message_chat_id(message) or 0, edit_existing=edit_existing, lang=lang)
        return
    selected_ids = _snp_selected_ids(flow)
    if sample_id in selected_ids:
        selected_ids = [value for value in selected_ids if value != sample_id]
    else:
        selected_ids.append(sample_id)
    _store_snp_selected_ids(context, user_id, token, rsid, selected_ids)
    await show_snp_sample_picker(message, context, user_id, token=token, page=page, edit_existing=edit_existing, lang=lang)


async def select_all_snp_samples(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    token: str,
    *,
    page: int = 0,
    edit_existing: bool = True,
    lang: str = "ru",
) -> None:
    flow = _flow_store(context).get(token, user_id)
    rsid = str((flow or {}).get("rsid") or "")
    if not rsid:
        await show_snp_input_screen(message, context, user_id, _message_chat_id(message) or 0, edit_existing=edit_existing, lang=lang)
        return
    sample_ids = [sample.asset_id for sample in _samples_with_raw(context, user_id)]
    _store_snp_selected_ids(context, user_id, token, rsid, sample_ids)
    await show_snp_sample_picker(message, context, user_id, token=token, page=page, edit_existing=edit_existing, lang=lang)


async def clear_snp_samples(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    token: str,
    *,
    page: int = 0,
    edit_existing: bool = True,
    lang: str = "ru",
) -> None:
    flow = _flow_store(context).get(token, user_id)
    rsid = str((flow or {}).get("rsid") or "")
    if not rsid:
        await show_snp_input_screen(message, context, user_id, _message_chat_id(message) or 0, edit_existing=edit_existing, lang=lang)
        return
    _store_snp_selected_ids(context, user_id, token, rsid, [])
    await show_snp_sample_picker(message, context, user_id, token=token, page=page, edit_existing=edit_existing, lang=lang)


async def toggle_selected_sample(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    token: str,
    sample_id: str,
    *,
    page: int = 0,
    edit_existing: bool = True,
    lang: str = "ru",
) -> None:
    flow = _flow_store(context).get(token, user_id)
    if flow is None:
        await show_selected_sample_picker(message, context, user_id, edit_existing=edit_existing, lang=lang)
        return
    selected_ids = _selected_ids(flow)
    if sample_id in selected_ids:
        selected_ids = [value for value in selected_ids if value != sample_id]
    else:
        selected_ids.append(sample_id)
    _store_selected_ids(context, user_id, token, selected_ids)
    await show_selected_sample_picker(message, context, user_id, token=token, page=page, edit_existing=edit_existing, lang=lang)


async def select_all_selected_samples(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    token: str,
    *,
    page: int = 0,
    edit_existing: bool = True,
    lang: str = "ru",
) -> None:
    sample_ids = [sample.asset_id for sample in _samples_with_raw(context, user_id)]
    _store_selected_ids(context, user_id, token, sample_ids)
    await show_selected_sample_picker(message, context, user_id, token=token, page=page, edit_existing=edit_existing, lang=lang)


async def clear_selected_samples(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    token: str,
    *,
    page: int = 0,
    edit_existing: bool = True,
    lang: str = "ru",
) -> None:
    _store_selected_ids(context, user_id, token, [])
    await show_selected_sample_picker(message, context, user_id, token=token, page=page, edit_existing=edit_existing, lang=lang)


async def show_pairwise_result(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    token: str,
    right_sample_id: str,
    *,
    edit_existing: bool = False,
    lang: str = "ru",
) -> None:
    flow = _flow_store(context).get(token, user_id)
    if flow is None:
        await show_left_sample_picker(message, context, user_id, edit_existing=edit_existing, lang=lang)
        return

    store = _my_data_store(context)
    left = store.get_sample(user_id, str(flow.get("left_sample_id") or ""))
    right = store.get_sample(user_id, right_sample_id)
    if left is None or right is None or left.asset_id == right.asset_id:
        await _show_or_edit(
            message,
            matching_error_text("Pairwise autosomal match", "Could not choose two different samples." if lang == "en" else "Не удалось выбрать две разные sample."),
            build_markup([], f"{MATCHING_CALLBACK_PREFIX}:pair:0", lang=lang),
            edit_existing=edit_existing,
            context=context,
            user_id=user_id,
        )
        return

    left_raw = store.get_sample_raw_file(user_id, left.asset_id)
    right_raw = store.get_sample_raw_file(user_id, right.asset_id)
    if left_raw is None or right_raw is None:
        await _show_or_edit(
            message,
            matching_error_text("Pairwise autosomal match", "One of the samples has no raw file." if lang == "en" else "У одной из sample нет raw-файла."),
            build_markup([], f"{MATCHING_CALLBACK_PREFIX}:pair:0", lang=lang),
            edit_existing=edit_existing,
            context=context,
            user_id=user_id,
        )
        return

    status_message = await _show_status_message(
        message,
        matching_running_text(left, right, lang=lang),
        build_markup([], f"{MATCHING_CALLBACK_PREFIX}:pair:0", lang=lang),
        context=context,
        user_id=user_id,
    )
    result = compare_raw_autosomal_match(
        store.resolve_raw_file_path(left_raw),
        store.resolve_raw_file_path(right_raw),
    )
    save_token = _flow_store(context).create(
        user_id=user_id,
        payload={
            "mode": "pairwise_result",
            "left_sample_id": left.asset_id,
            "right_sample_id": right.asset_id,
            "result": result,
        },
    )
    rows = [
        [InlineKeyboardButton("💾 Save report" if lang == "en" else "💾 Сохранить отчёт", callback_data=f"{MATCHING_CALLBACK_PREFIX}:save:{save_token}")],
    ]
    markup = build_markup(rows, f"{MATCHING_CALLBACK_PREFIX}:a:{left.asset_id}", lang=lang)
    await _show_pairwise_visual(
        status_message,
        context,
        user_id,
        left=left,
        right=right,
        result=result,
        caption=pairwise_visual_caption(left, right, result, lang=lang),
        fallback_text=pairwise_result_text(left, right, result, lang=lang),
        reply_markup=markup,
        edit_existing=True,
    )


async def show_all_pairs_confirm(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    edit_existing: bool = False,
    lang: str = "ru",
) -> None:
    samples = _samples_with_raw(context, user_id)
    if len(samples) < 2:
        await _show_or_edit(
            message,
            matching_error_text("Compare all samples", "At least two samples with raw files are required." if lang == "en" else "Нужно минимум два sample с raw-файлами."),
            build_markup([], f"{MATCHING_CALLBACK_PREFIX}:root", lang=lang),
            edit_existing=edit_existing,
            context=context,
            user_id=user_id,
        )
        return
    rows = [
        [InlineKeyboardButton("▶️ Run calculation" if lang == "en" else "▶️ Запустить расчёт", callback_data=f"{MATCHING_CALLBACK_PREFIX}:allrun")],
    ]
    await _show_or_edit(
        message,
        all_pairs_confirm_text(samples, lang=lang),
        build_markup(rows, f"{MATCHING_CALLBACK_PREFIX}:root", lang=lang),
        edit_existing=edit_existing,
        context=context,
        user_id=user_id,
    )


async def show_selected_samples_result(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    token: str,
    *,
    edit_existing: bool = False,
    lang: str = "ru",
) -> None:
    flow = _flow_store(context).get(token, user_id)
    samples = _selected_samples_from_ids(_samples_with_raw(context, user_id), _selected_ids(flow))
    if len(samples) < 2:
        await show_selected_sample_picker(message, context, user_id, token=token, edit_existing=edit_existing, lang=lang)
        return

    back_callback = f"{MATCHING_CALLBACK_PREFIX}:ss:{token}:0"
    status_message = await _show_status_message(
        message,
        selected_samples_running_text(len(samples), lang=lang),
        build_markup([], back_callback, lang=lang),
        context=context,
        user_id=user_id,
    )
    store = _my_data_store(context)
    results = await _calculate_pairwise_results(
        store,
        user_id,
        samples,
        status_message=status_message,
        progress_text_factory=lambda completed_pairs, total_pairs: selected_samples_running_text(
            len(samples),
            completed_pairs=completed_pairs,
            total_pairs=total_pairs,
            lang=lang,
        ),
        progress_back_callback=back_callback,
        lang=lang,
    )
    await _show_all_pairs_visual(
        status_message,
        context,
        user_id,
        results=results,
        sample_count=len(samples),
        caption=selected_samples_visual_caption(results, len(samples), lang=lang),
        fallback_text=matching_error_text(
            "✅ Compare selected samples" if lang == "en" else "✅ Сравнить выбранные sample",
            "Could not show the result. Try again." if lang == "en" else "Не удалось показать результат. Попробуйте ещё раз.",
        ),
        reply_markup=build_markup([], back_callback, lang=lang),
        edit_existing=True,
    )


async def show_snp_result(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    token: str,
    *,
    edit_existing: bool = False,
    lang: str = "ru",
) -> None:
    flow = _flow_store(context).get(token, user_id)
    rsid = str((flow or {}).get("rsid") or "")
    samples = _selected_samples_from_ids(_samples_with_raw(context, user_id), _snp_selected_ids(flow))
    if not rsid:
        await show_snp_input_screen(message, context, user_id, _message_chat_id(message) or 0, edit_existing=edit_existing, lang=lang)
        return
    if not samples:
        await show_snp_sample_picker(message, context, user_id, token=token, edit_existing=edit_existing, lang=lang)
        return

    store = _my_data_store(context)
    rows = []
    for sample in samples:
        raw_file = store.get_sample_raw_file(user_id, sample.asset_id)
        if raw_file is None:
            rows.append((sample, lookup_snp_in_raw(Path("__missing_raw__"), rsid)))
            continue
        rows.append((sample, lookup_snp_in_raw(store.resolve_raw_file_path(raw_file), rsid)))

    await _show_or_edit(
        message,
        snp_result_text(rsid, rows, lang=lang),
        build_markup([], f"{MATCHING_CALLBACK_PREFIX}:snps:{token}:0", lang=lang),
        edit_existing=edit_existing,
        context=context,
        user_id=user_id,
    )


async def matching_text_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.message.text is None or update.effective_user is None or update.effective_chat is None:
        return
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    flow = _flow_store(context)
    pending = flow.get_pending(chat_id, user_id)
    if pending is None or pending.get("action") != _SNP_INPUT_ACTION:
        return
    if _has_other_text_pending(context, chat_id):
        return

    lang = get_user_language(context, user_id)
    rsid = normalize_rsid(update.message.text)
    if rsid is None:
        await update.message.reply_text(
            "Enter an rsID like rs2455144." if lang == "en" else "Введите rsID в формате rs2455144.",
            do_quote=False,
        )
        raise ApplicationHandlerStop

    flow.clear_pending(chat_id, user_id)
    token = flow.create(user_id=user_id, payload={"mode": "snp_lookup", "rsid": rsid, "sample_ids": []})
    await show_snp_sample_picker(update.message, context, user_id, token=token, edit_existing=False, lang=lang)
    raise ApplicationHandlerStop


async def save_pairwise_result(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    token: str,
    *,
    lang: str = "ru",
) -> None:
    flow = _flow_store(context).get(token, user_id)
    if flow is None:
        await _show_or_edit(
            message,
            matching_error_text("Save matching", "Calculation not found. Run pairwise match again." if lang == "en" else "Расчет не найден. Запустите pairwise match заново."),
            build_markup([], f"{MATCHING_CALLBACK_PREFIX}:root", lang=lang),
            edit_existing=True,
            context=context,
            user_id=user_id,
        )
        return
    store = _my_data_store(context)
    left = store.get_sample(user_id, str(flow.get("left_sample_id") or ""))
    right = store.get_sample(user_id, str(flow.get("right_sample_id") or ""))
    result = flow.get("result")
    if left is None or right is None or not hasattr(result, "segments"):
        await _show_or_edit(
            message,
            matching_error_text("Save matching", "Sample or result not found." if lang == "en" else "Sample или результат не найден."),
            build_markup([], f"{MATCHING_CALLBACK_PREFIX}:root", lang=lang),
            edit_existing=True,
            context=context,
            user_id=user_id,
        )
        return
    saved = _match_store(context).save_pairwise_match(user_id, left, right, result)
    rows = [
        [InlineKeyboardButton("📊 Open saved" if lang == "en" else "📊 Открыть сохраненное", callback_data=f"{MATCHING_CALLBACK_PREFIX}:m:{saved.summary.match_id}")],
        [InlineKeyboardButton("💾 Saved matches", callback_data=f"{MATCHING_CALLBACK_PREFIX}:saved")],
    ]
    await _show_saved_match_visual(
        message,
        context,
        user_id,
        record=saved,
        caption=saved_match_visual_caption(saved, lang=lang),
        fallback_text=match_saved_text(saved, lang=lang),
        reply_markup=build_markup(rows, f"{MATCHING_CALLBACK_PREFIX}:root", lang=lang),
        status_label="SAVED",
        edit_existing=True,
    )


async def show_saved_matches_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    edit_existing: bool = False,
    lang: str = "ru",
) -> None:
    matches = _match_store(context).list_matches(user_id)
    rows = [
        [InlineKeyboardButton(saved_match_button_label(match), callback_data=f"{MATCHING_CALLBACK_PREFIX}:m:{match.match_id}")]
        for match in matches[:20]
    ]
    await _show_or_edit(
        message,
        saved_matches_text(matches, lang=lang),
        build_markup(rows, f"{MATCHING_CALLBACK_PREFIX}:root", lang=lang),
        edit_existing=edit_existing,
        context=context,
        user_id=user_id,
    )


async def show_saved_match_detail(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    match_id: str,
    *,
    edit_existing: bool = False,
    lang: str = "ru",
) -> None:
    record = _match_store(context).find_match(user_id, match_id)
    if record is None:
        await _show_or_edit(
            message,
            matching_error_text("Saved match", "Saved matching result not found." if lang == "en" else "Сохраненный matching не найден."),
            build_markup([], f"{MATCHING_CALLBACK_PREFIX}:saved", lang=lang),
            edit_existing=edit_existing,
            context=context,
            user_id=user_id,
        )
        return
    await _show_saved_match_visual(
        message,
        context,
        user_id,
        record=record,
        caption=saved_match_visual_caption(record, lang=lang),
        fallback_text=saved_match_detail_text(record, lang=lang),
        reply_markup=build_markup([], f"{MATCHING_CALLBACK_PREFIX}:saved", lang=lang),
        status_label="SAVED",
        edit_existing=edit_existing,
    )


async def show_all_pairs_result(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    edit_existing: bool = False,
    lang: str = "ru",
) -> None:
    store = _my_data_store(context)
    samples = _samples_with_raw(context, user_id)
    if len(samples) < 2:
        await _show_or_edit(
            message,
            matching_error_text("Compare all samples", "At least two samples with raw files are required." if lang == "en" else "Нужно минимум два sample с raw-файлами."),
            build_markup([], f"{MATCHING_CALLBACK_PREFIX}:root", lang=lang),
            edit_existing=edit_existing,
            context=context,
            user_id=user_id,
        )
        return

    status_message = await _show_status_message(
        message,
        all_pairs_running_text(samples, lang=lang),
        build_markup([], f"{MATCHING_CALLBACK_PREFIX}:root", lang=lang),
        context=context,
        user_id=user_id,
    )

    results = await _calculate_pairwise_results(
        store,
        user_id,
        samples,
        status_message=status_message,
        progress_text_factory=lambda completed_pairs, total_pairs: all_pairs_running_text(
            samples,
            completed_pairs=completed_pairs,
            total_pairs=total_pairs,
            lang=lang,
        ),
        progress_back_callback=f"{MATCHING_CALLBACK_PREFIX}:root",
        lang=lang,
    )

    await _show_all_pairs_visual(
        status_message,
        context,
        user_id,
        results=results,
        sample_count=len(samples),
        caption=all_pairs_visual_caption(results, len(samples), lang=lang),
        fallback_text=all_pairs_result_text(results, len(samples), lang=lang),
        reply_markup=build_markup([], f"{MATCHING_CALLBACK_PREFIX}:root", lang=lang),
        edit_existing=True,
    )


async def matching_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None or query.message is None or update.effective_user is None:
        return
    if not query.data.startswith(f"{MATCHING_CALLBACK_PREFIX}:"):
        return

    if not await ensure_active_main_menu(update, context):
        return

    user_id = update.effective_user.id
    chat_id = update.effective_chat.id if update.effective_chat is not None else (_message_chat_id(query.message) or 0)
    lang = get_user_language(context, user_id)
    parts = query.data.split(":")
    action = parts[1] if len(parts) > 1 else "root"
    if action != "snp":
        _flow_store(context).clear_pending(chat_id, user_id)
    if action not in {"srun", "snprun"}:
        await query.answer()

    if action == "root":
        await show_matching_menu(query.message, context, user_id, edit_existing=True, lang=lang)
        return
    if action == "pair":
        await show_left_sample_picker(
            query.message,
            context,
            user_id,
            page=int(parts[2] if len(parts) > 2 else 0),
            edit_existing=True,
            lang=lang,
        )
        return
    if action == "selected":
        await show_selected_sample_picker(query.message, context, user_id, edit_existing=True, lang=lang)
        return
    if action == "snp":
        await show_snp_input_screen(query.message, context, user_id, chat_id, edit_existing=True, lang=lang)
        return
    if action == "snps":
        await show_snp_sample_picker(
            query.message,
            context,
            user_id,
            token=parts[2] if len(parts) > 2 else "",
            page=int(parts[3] if len(parts) > 3 else 0),
            edit_existing=True,
            lang=lang,
        )
        return
    if action == "snpt":
        await toggle_snp_sample(
            query.message,
            context,
            user_id,
            token=parts[2] if len(parts) > 2 else "",
            sample_id=parts[3] if len(parts) > 3 else "",
            page=int(parts[4] if len(parts) > 4 else 0),
            edit_existing=True,
            lang=lang,
        )
        return
    if action == "snpall":
        await select_all_snp_samples(
            query.message,
            context,
            user_id,
            token=parts[2] if len(parts) > 2 else "",
            page=int(parts[3] if len(parts) > 3 else 0),
            edit_existing=True,
            lang=lang,
        )
        return
    if action == "snpclr":
        await clear_snp_samples(
            query.message,
            context,
            user_id,
            token=parts[2] if len(parts) > 2 else "",
            page=int(parts[3] if len(parts) > 3 else 0),
            edit_existing=True,
            lang=lang,
        )
        return
    if action == "snprun":
        token = parts[2] if len(parts) > 2 else ""
        selected_ids = _snp_selected_ids(_flow_store(context).get(token, user_id))
        selected_samples = _selected_samples_from_ids(_samples_with_raw(context, user_id), selected_ids)
        if not selected_samples:
            await query.answer("Choose at least 1 sample." if lang == "en" else "Выберите минимум 1 sample.", show_alert=True)
            return
        await query.answer()
        await show_snp_result(
            query.message,
            context,
            user_id,
            token=token,
            edit_existing=True,
            lang=lang,
        )
        return
    if action == "ss":
        await show_selected_sample_picker(
            query.message,
            context,
            user_id,
            token=parts[2] if len(parts) > 2 else "",
            page=int(parts[3] if len(parts) > 3 else 0),
            edit_existing=True,
            lang=lang,
        )
        return
    if action == "st":
        await toggle_selected_sample(
            query.message,
            context,
            user_id,
            token=parts[2] if len(parts) > 2 else "",
            sample_id=parts[3] if len(parts) > 3 else "",
            page=int(parts[4] if len(parts) > 4 else 0),
            edit_existing=True,
            lang=lang,
        )
        return
    if action == "sall":
        await select_all_selected_samples(
            query.message,
            context,
            user_id,
            token=parts[2] if len(parts) > 2 else "",
            page=int(parts[3] if len(parts) > 3 else 0),
            edit_existing=True,
            lang=lang,
        )
        return
    if action == "sclr":
        await clear_selected_samples(
            query.message,
            context,
            user_id,
            token=parts[2] if len(parts) > 2 else "",
            page=int(parts[3] if len(parts) > 3 else 0),
            edit_existing=True,
            lang=lang,
        )
        return
    if action == "srun":
        token = parts[2] if len(parts) > 2 else ""
        selected_ids = _selected_ids(_flow_store(context).get(token, user_id))
        selected_samples = _selected_samples_from_ids(_samples_with_raw(context, user_id), selected_ids)
        if len(selected_samples) < 2:
            await query.answer("Choose at least 2 samples." if lang == "en" else "Выберите минимум 2 sample.", show_alert=True)
            return
        await query.answer()
        await show_selected_samples_result(
            query.message,
            context,
            user_id,
            token=token,
            edit_existing=True,
            lang=lang,
        )
        return
    if action == "all":
        await show_all_pairs_confirm(query.message, context, user_id, edit_existing=True, lang=lang)
        return
    if action == "allrun":
        await show_all_pairs_result(query.message, context, user_id, edit_existing=True, lang=lang)
        return
    if action == "saved":
        await show_saved_matches_menu(query.message, context, user_id, edit_existing=True, lang=lang)
        return
    if action == "m":
        await show_saved_match_detail(
            query.message,
            context,
            user_id,
            parts[2] if len(parts) > 2 else "",
            edit_existing=True,
            lang=lang,
        )
        return
    if action == "save":
        await save_pairwise_result(
            query.message,
            context,
            user_id,
            parts[2] if len(parts) > 2 else "",
            lang=lang,
        )
        return
    if action == "a":
        await show_right_sample_picker(
            query.message,
            context,
            user_id,
            left_sample_id=parts[2] if len(parts) > 2 else "",
            edit_existing=True,
            lang=lang,
        )
        return
    if action == "pb":
        flow = _flow_store(context).get(parts[2] if len(parts) > 2 else "", user_id)
        if flow is None:
            await show_left_sample_picker(query.message, context, user_id, edit_existing=True, lang=lang)
            return
        await show_right_sample_picker(
            query.message,
            context,
            user_id,
            left_sample_id=str(flow.get("left_sample_id") or ""),
            page=int(parts[3] if len(parts) > 3 else 0),
            edit_existing=True,
            lang=lang,
        )
        return
    if action == "b":
        await show_pairwise_result(
            query.message,
            context,
            user_id,
            token=parts[2] if len(parts) > 2 else "",
            right_sample_id=parts[3] if len(parts) > 3 else "",
            edit_existing=True,
            lang=lang,
        )
