from __future__ import annotations

import tempfile
from math import ceil
from pathlib import Path
from uuid import uuid4

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import Application, ContextTypes

from app.features.my_data.storage import MyDataStore, SampleAsset
from app.i18n import get_user_language
from app.main_menu import ensure_active_main_menu, set_active_main_menu_message

from .domain.catalog import TraitCatalog, TraitCatalogError
from .domain.runtime import TraitRuntimeError, TraitsRuntimeService
from .storage import TraitReportStore
from .texts import (
    DEFAULT_LANGUAGE,
    localize_confidence,
    localize_group,
    localize_trait_name,
    text,
)
from .ui import (
    build_markup,
    error_text,
    pager_row,
    report_button_label,
    report_saved_text,
    sample_picker_text,
    sample_trait_reports_text,
    saved_report_samples_text,
    running_trait_text,
    trait_button_label,
    trait_catalog_text,
    trait_detail_text,
    trait_report_visual_caption,
    trait_result_preview_text,
    trait_run_sample_picker_text,
    trait_visual_caption,
    trait_report_text,
    trait_sections_text,
    traits_about_text,
    traits_root_text,
)
from .visualization import render_trait_result_png


TRAITS_CALLBACK_PREFIX = "traits"
_PAGE_SIZE = 8
_GROUP_ORDER = (
    "appearance",
    "body",
    "nutrition",
    "lifestyle",
    "mind",
    "health_research",
    "sensitive_research",
    "internal",
)
_GROUP_CODES = {
    "appearance": "ap",
    "body": "bd",
    "nutrition": "nt",
    "lifestyle": "ls",
    "mind": "md",
    "health_research": "hr",
    "sensitive_research": "sr",
    "internal": "in",
}
_ROOT_GROUP_LABELS = {
    "ru": {
        "appearance": "👤 Внешность",
        "body": "🏃 Тело",
        "nutrition": "🥗 Питание",
        "lifestyle": "☕ Образ жизни",
        "mind": "🧠 Психика",
        "health_research": "🧬 Здоровье",
        "sensitive_research": "🔬 Исследовательские",
    },
    "en": {
        "appearance": "👁 Appearance",
        "body": "🏃 Body",
        "nutrition": "🥗 Nutrition",
        "lifestyle": "☕ Lifestyle",
        "mind": "🧠 Mind",
        "health_research": "🧬 Health Research",
        "sensitive_research": "🔬 Research",
    },
}


class TraitsFlowStore:
    def __init__(self) -> None:
        self._payloads: dict[str, dict[str, object]] = {}

    def create(self, *, user_id: int, payload: dict[str, object]) -> str:
        token = uuid4().hex[:8]
        self._payloads[token] = {"user_id": int(user_id), **payload}
        return token

    def get(self, token: str, user_id: int) -> dict[str, object] | None:
        payload = self._payloads.get(token)
        if payload is None or int(payload.get("user_id", -1)) != int(user_id):
            return None
        return dict(payload)


def register_traits_services(application: Application, settings) -> None:
    catalog = TraitCatalog()
    application.bot_data["traits_catalog"] = catalog
    application.bot_data["traits_runtime"] = TraitsRuntimeService(catalog)
    application.bot_data["traits_report_store"] = TraitReportStore(settings.root_dir / "storage" / "traits")
    application.bot_data["traits_flow_store"] = TraitsFlowStore()


def _catalog(context: ContextTypes.DEFAULT_TYPE) -> TraitCatalog:
    return context.application.bot_data["traits_catalog"]


def _runtime(context: ContextTypes.DEFAULT_TYPE) -> TraitsRuntimeService:
    return context.application.bot_data["traits_runtime"]


def _report_store(context: ContextTypes.DEFAULT_TYPE) -> TraitReportStore:
    return context.application.bot_data["traits_report_store"]


def _flow_store(context: ContextTypes.DEFAULT_TYPE) -> TraitsFlowStore:
    return context.application.bot_data["traits_flow_store"]


def _my_data_store(context: ContextTypes.DEFAULT_TYPE) -> MyDataStore:
    return context.application.bot_data["my_data_store"]


def _ui_lang(context: ContextTypes.DEFAULT_TYPE, user_id: int | None = None) -> str:
    return get_user_language(context, user_id, fallback=DEFAULT_LANGUAGE)


def _paginate(items: list[object], page: int) -> tuple[list[object], int, int]:
    total_pages = max(1, ceil(len(items) / _PAGE_SIZE)) if items else 1
    normalized_page = max(0, min(page, total_pages - 1))
    start = normalized_page * _PAGE_SIZE
    end = start + _PAGE_SIZE
    return items[start:end], normalized_page, total_pages


def _group_entries(context: ContextTypes.DEFAULT_TYPE) -> list[tuple[str, int]]:
    traits = _catalog(context).list_traits()
    counts: dict[str, int] = {}
    for item in traits:
        counts[item.group] = counts.get(item.group, 0) + 1
    ordered: list[tuple[str, int]] = []
    for group in _GROUP_ORDER:
        if counts.get(group):
            ordered.append((group, counts[group]))
    for group, count in sorted(counts.items()):
        if group not in _GROUP_ORDER:
            ordered.append((group, count))
    return ordered


def _traits_for_group(context: ContextTypes.DEFAULT_TYPE, group: str | None):
    traits = _catalog(context).list_traits()
    if not group:
        return traits
    return [item for item in traits if item.group == group]


def _encode_group(group: str | None) -> str | None:
    if group is None:
        return None
    return _GROUP_CODES.get(group, group)


def _decode_group(group_code: str | None) -> str | None:
    if not group_code:
        return None
    for group, code in _GROUP_CODES.items():
        if code == group_code:
            return group
    return group_code


def _root_group_label(group: str, count: int, *, lang: str = "ru") -> str:
    label = _ROOT_GROUP_LABELS.get(lang, _ROOT_GROUP_LABELS["en"]).get(group)
    if not label:
        label = localize_group(group, lang=lang)
    return f"{label} ({count})"


def _group_heading_label(group: str | None, *, lang: str = "ru") -> str | None:
    if group is None:
        return None
    label = _ROOT_GROUP_LABELS.get(lang, _ROOT_GROUP_LABELS["en"]).get(group)
    if label:
        return label
    return localize_group(group, lang=lang)


def _footer_row(back_callback: str, *, lang: str = "ru") -> list[InlineKeyboardButton]:
    back_label = "⬅️ Назад" if lang == "ru" else "⬅️ Back"
    return [
        InlineKeyboardButton(back_label, callback_data=back_callback),
        InlineKeyboardButton(text("cancel", lang=lang), callback_data="main:cancel"),
    ]


def _root_footer_row(*, lang: str = "ru") -> list[InlineKeyboardButton]:
    return _footer_row("main:root", lang=lang)


def _samples_with_raw(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> list[SampleAsset]:
    store = _my_data_store(context)
    samples = []
    for sample in store.list_samples(user_id):
        if sample.raw_file_id and store.get_sample_raw_file(user_id, sample.asset_id) is not None:
            samples.append(sample)
    return samples


def _result_preview_markup(
    *,
    save_token: str,
    sample_id: str,
    back_callback: str,
    lang: str = "ru",
) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text("save_trait_report", lang=lang), callback_data=f"{TRAITS_CALLBACK_PREFIX}:sv:{save_token}")],
        [InlineKeyboardButton(text("sample_trait_reports", lang=lang), callback_data=f"{TRAITS_CALLBACK_PREFIX}:rs:{sample_id}")],
        [InlineKeyboardButton(text("trait_info", lang=lang), callback_data=f"{TRAITS_CALLBACK_PREFIX}:i:{save_token}")],
    ]
    return InlineKeyboardMarkup(rows + [_footer_row(back_callback, lang=lang)])


async def _show_or_edit(
    message,
    text_value: str,
    reply_markup,
    *,
    edit_existing: bool = False,
    parse_mode: str | None = "HTML",
    context: ContextTypes.DEFAULT_TYPE | None = None,
    user_id: int | None = None,
) -> None:
    if edit_existing:
        if _is_photo_message(message):
            sent = await message.reply_text(text_value, reply_markup=reply_markup, parse_mode=parse_mode, do_quote=False)
            _set_active_if_possible(context, sent, user_id)
            await _clear_old_visual_markup(message)
            return
        try:
            await message.edit_text(text_value, reply_markup=reply_markup, parse_mode=parse_mode)
        except BadRequest as exc:
            if "message is not modified" not in str(exc).lower():
                raise
    else:
        sent = await message.reply_text(text_value, reply_markup=reply_markup, parse_mode=parse_mode, do_quote=False)
        _set_active_if_possible(context, sent, user_id)


def _create_visualization_path() -> Path:
    return Path(tempfile.gettempdir()) / f"dna_traits_{uuid4().hex}.png"


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
    if context is not None and user_id is not None and chat_id is not None:
        set_active_main_menu_message(context, chat_id, user_id, message.message_id)


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


async def _show_status_message(message, text_value: str):
    if _is_photo_message(message):
        status_message = await message.reply_text(text_value, parse_mode="HTML", do_quote=False)
        await _clear_old_visual_markup(message)
        return status_message
    await message.edit_text(text_value, parse_mode="HTML")
    return message


async def _send_visual_or_fallback(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    image_path: Path,
    caption: str,
    fallback_text: str,
    reply_markup,
    edit_existing: bool = False,
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


async def _show_trait_visual(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    sample_name: str,
    technical_payload: dict[str, object],
    product_payload: dict[str, object],
    caption: str,
    fallback_text: str,
    reply_markup,
    lang: str,
    status_label: str,
    edit_existing: bool = True,
) -> None:
    image_path = _create_visualization_path()
    try:
        render_trait_result_png(
            image_path,
            sample_name=sample_name,
            product_payload=product_payload,
            technical_payload=technical_payload,
            lang=lang,
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


async def show_traits_root_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int | None = None,
    *,
    edit_existing: bool = False,
) -> None:
    lang = _ui_lang(context, user_id)
    counts = _catalog(context).counts()
    rows = [
        [InlineKeyboardButton(text("start_trait_report", lang=lang), callback_data=f"{TRAITS_CALLBACK_PREFIX}:pick:0")],
        [InlineKeyboardButton(text("open_saved_reports", lang=lang), callback_data=f"{TRAITS_CALLBACK_PREFIX}:saved:0")],
        [InlineKeyboardButton(text("about_limitations", lang=lang), callback_data=f"{TRAITS_CALLBACK_PREFIX}:about")],
    ]
    markup = InlineKeyboardMarkup(rows + [_root_footer_row(lang=lang)])
    await _show_or_edit(
        message,
        traits_root_text(
            trait_count=counts["trait_count"],
            consumer_ready_trait_count=counts["consumer_ready_trait_count"],
            usable_trait_count=counts["usable_trait_count"],
            lang=lang,
        ),
        markup,
        edit_existing=edit_existing,
        context=context,
        user_id=user_id,
    )


async def show_traits_about_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int | None = None,
    *,
    edit_existing: bool = False,
) -> None:
    lang = _ui_lang(context, user_id)
    await _show_or_edit(
        message,
        traits_about_text(lang=lang),
        build_markup([], f"{TRAITS_CALLBACK_PREFIX}:root", lang=lang),
        edit_existing=edit_existing,
        context=context,
        user_id=user_id,
    )


async def show_trait_run_sample_picker_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    page: int,
    edit_existing: bool = False,
) -> None:
    lang = _ui_lang(context, user_id)
    samples = _samples_with_raw(context, user_id)
    page_samples, current_page, total_pages = _paginate(samples, page)
    rows = []
    for item in page_samples:
        scope_token = _flow_store(context).create(
            user_id=user_id,
            payload={
                "mode": "sample_scope",
                "sample_id": item.asset_id,
                "back_callback": f"{TRAITS_CALLBACK_PREFIX}:pick:{current_page}",
            },
        )
        rows.append([InlineKeyboardButton(item.display_name, callback_data=f"{TRAITS_CALLBACK_PREFIX}:ss:{scope_token}")])

    previous_callback = f"{TRAITS_CALLBACK_PREFIX}:pick:{current_page - 1}" if current_page > 0 else None
    next_callback = f"{TRAITS_CALLBACK_PREFIX}:pick:{current_page + 1}" if current_page + 1 < total_pages else None
    rows.extend(pager_row(previous_callback=previous_callback, next_callback=next_callback, lang=lang))
    if not samples:
        rows.append([InlineKeyboardButton("🧬 My DNA", callback_data="my_data:root")])

    await _show_or_edit(
        message,
        trait_run_sample_picker_text(page_samples, page=current_page, total_pages=total_pages, lang=lang),
        build_markup(rows, f"{TRAITS_CALLBACK_PREFIX}:root", lang=lang),
        edit_existing=edit_existing,
        context=context,
        user_id=user_id,
    )


async def show_trait_sections_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    sample_scope_token: str | None = None,
    edit_existing: bool = False,
) -> None:
    lang = _ui_lang(context, user_id)
    rows = []
    sample: SampleAsset | None = None
    if sample_scope_token is not None:
        scope = _flow_store(context).get(sample_scope_token, user_id)
        if scope is None:
            await show_trait_sections_menu(message, context, user_id, edit_existing=edit_existing)
            return
        sample_id = str(scope.get("sample_id") or "")
        sample = _my_data_store(context).get_sample(user_id, sample_id)
        if sample is None:
            await show_trait_sections_menu(message, context, user_id, edit_existing=edit_existing)
            return
        back_callback = str(scope.get("back_callback") or f"{TRAITS_CALLBACK_PREFIX}:rs:{sample.asset_id}")
    else:
        back_callback = f"{TRAITS_CALLBACK_PREFIX}:root"

    for group, count in _group_entries(context):
        if sample_scope_token is None and group == "internal":
            continue
        label = _root_group_label(group, count, lang=lang)
        group_code = _encode_group(group) or group
        if sample_scope_token is None:
            callback = f"{TRAITS_CALLBACK_PREFIX}:g:{group_code}:0"
        else:
            callback = f"{TRAITS_CALLBACK_PREFIX}:sg:{sample_scope_token}:{group_code}:0"
        rows.append([InlineKeyboardButton(label, callback_data=callback)])

    if sample_scope_token is None:
        markup = InlineKeyboardMarkup(rows + [_root_footer_row(lang=lang)])
    else:
        markup = build_markup(rows, back_callback, lang=lang)
    screen_text = trait_sections_text(sample_name=sample.display_name if sample is not None else None, lang=lang)
    await _show_or_edit(message, screen_text, markup, edit_existing=edit_existing, context=context, user_id=user_id)


async def show_trait_catalog_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    page: int,
    group: str | None = None,
    sample_scope_token: str | None = None,
    edit_existing: bool = False,
) -> None:
    lang = _ui_lang(context, user_id)
    entries = _traits_for_group(context, group)
    sample: SampleAsset | None = None
    back_callback = f"{TRAITS_CALLBACK_PREFIX}:s"
    if sample_scope_token is not None:
        scope = _flow_store(context).get(sample_scope_token, user_id)
        if scope is None:
            await show_trait_sections_menu(message, context, user_id, edit_existing=edit_existing)
            return
        sample_id = str(scope.get("sample_id") or "")
        sample = _my_data_store(context).get_sample(user_id, sample_id)
        if sample is None:
            await show_trait_sections_menu(message, context, user_id, edit_existing=edit_existing)
            return
        sample_reports_callback = str(scope.get("back_callback") or f"{TRAITS_CALLBACK_PREFIX}:rs:{sample.asset_id}")
        back_callback = sample_reports_callback if group is None else f"{TRAITS_CALLBACK_PREFIX}:ss:{sample_scope_token}"

    page_entries, current_page, total_pages = _paginate(entries, page)
    rows = []
    for entry in page_entries:
        list_back_callback = (
            f"{TRAITS_CALLBACK_PREFIX}:l:{current_page}"
            if group is None
            else f"{TRAITS_CALLBACK_PREFIX}:g:{_encode_group(group)}:{current_page}"
        )
        if sample_scope_token is None:
            pick_token = _flow_store(context).create(
                user_id=user_id,
                payload={
                    "mode": "sample_picker",
                    "trait_id": entry.trait_id,
                    "trait_name": trait_button_label(entry, lang=lang),
                    "back_callback": list_back_callback,
                },
            )
            callback = f"{TRAITS_CALLBACK_PREFIX}:p:{pick_token}:0"
        else:
            scoped_back_callback = (
                f"{TRAITS_CALLBACK_PREFIX}:sl:{sample_scope_token}:{current_page}"
                if group is None
                else f"{TRAITS_CALLBACK_PREFIX}:sg:{sample_scope_token}:{_encode_group(group)}:{current_page}"
            )
            run_token = _flow_store(context).create(
                user_id=user_id,
                payload={
                    "mode": "sample_run",
                    "sample_id": sample.asset_id if sample is not None else "",
                    "trait_id": entry.trait_id,
                    "back_callback": scoped_back_callback,
                },
            )
            callback = f"{TRAITS_CALLBACK_PREFIX}:sr:{run_token}"
        rows.append(
            [InlineKeyboardButton(trait_button_label(entry, lang=lang), callback_data=callback)]
        )

    previous_callback = None
    next_callback = None
    if current_page > 0:
        if sample_scope_token is None:
            previous_callback = (
                f"{TRAITS_CALLBACK_PREFIX}:l:{current_page - 1}"
                if group is None
                else f"{TRAITS_CALLBACK_PREFIX}:g:{_encode_group(group)}:{current_page - 1}"
            )
        else:
            previous_callback = (
                f"{TRAITS_CALLBACK_PREFIX}:sl:{sample_scope_token}:{current_page - 1}"
                if group is None
                else f"{TRAITS_CALLBACK_PREFIX}:sg:{sample_scope_token}:{_encode_group(group)}:{current_page - 1}"
            )
    if current_page + 1 < total_pages:
        if sample_scope_token is None:
            next_callback = (
                f"{TRAITS_CALLBACK_PREFIX}:l:{current_page + 1}"
                if group is None
                else f"{TRAITS_CALLBACK_PREFIX}:g:{_encode_group(group)}:{current_page + 1}"
            )
        else:
            next_callback = (
                f"{TRAITS_CALLBACK_PREFIX}:sl:{sample_scope_token}:{current_page + 1}"
                if group is None
                else f"{TRAITS_CALLBACK_PREFIX}:sg:{sample_scope_token}:{_encode_group(group)}:{current_page + 1}"
            )
    rows.extend(pager_row(previous_callback=previous_callback, next_callback=next_callback, lang=lang))

    screen_text = trait_catalog_text(
        page_entries,
        page=current_page,
        total_pages=total_pages,
        sample_name=sample.display_name if sample is not None else None,
        group_name=_group_heading_label(group, lang=lang),
        lang=lang,
    )
    if sample_scope_token is None:
        markup = InlineKeyboardMarkup(rows + [_footer_row(back_callback, lang=lang)])
    else:
        markup = build_markup(rows, back_callback, lang=lang)
    await _show_or_edit(message, screen_text, markup, edit_existing=edit_existing, context=context, user_id=user_id)


async def show_trait_detail_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    trait_id: str,
    page: int,
    group: str | None = None,
    sample_scope_token: str | None = None,
    edit_existing: bool = False,
) -> None:
    lang = _ui_lang(context, user_id)
    detail = _catalog(context).get_trait_detail(trait_id)
    rows = []
    if sample_scope_token is None:
        pick_token = _flow_store(context).create(
            user_id=user_id,
            payload={
                "mode": "sample_picker",
                "trait_id": trait_id,
                "back_callback": (
                    f"{TRAITS_CALLBACK_PREFIX}:d:{page}:{trait_id}"
                    if group is None
                    else f"{TRAITS_CALLBACK_PREFIX}:dg:{_encode_group(group)}:{page}:{trait_id}"
                ),
                "trait_name": localize_trait_name(detail.entry.trait_id, detail.entry.display_name, lang=lang),
            },
        )
        rows.append(
            [InlineKeyboardButton(text("choose_sample_and_run", lang=lang), callback_data=f"{TRAITS_CALLBACK_PREFIX}:p:{pick_token}:0")]
        )
        back_callback = (
            f"{TRAITS_CALLBACK_PREFIX}:l:{page}"
            if group is None
            else f"{TRAITS_CALLBACK_PREFIX}:g:{_encode_group(group)}:{page}"
        )
        sample_name = None
    else:
        scope = _flow_store(context).get(sample_scope_token, user_id)
        if scope is None:
            await show_trait_sections_menu(message, context, user_id, edit_existing=edit_existing)
            return
        sample_id = str(scope.get("sample_id") or "")
        sample = _my_data_store(context).get_sample(user_id, sample_id)
        if sample is None:
            await show_trait_sections_menu(message, context, user_id, edit_existing=edit_existing)
            return
        run_token = _flow_store(context).create(
            user_id=user_id,
            payload={
                "mode": "sample_run",
                "sample_id": sample.asset_id,
                "trait_id": trait_id,
                "back_callback": (
                    f"{TRAITS_CALLBACK_PREFIX}:sd:{sample_scope_token}:{page}:{trait_id}"
                    if group is None
                    else f"{TRAITS_CALLBACK_PREFIX}:sgd:{sample_scope_token}:{_encode_group(group)}:{page}:{trait_id}"
                ),
            },
        )
        rows.append(
            [InlineKeyboardButton(text("run_for_this_sample", lang=lang), callback_data=f"{TRAITS_CALLBACK_PREFIX}:sr:{run_token}")]
        )
        back_callback = (
            f"{TRAITS_CALLBACK_PREFIX}:sl:{sample_scope_token}:{page}"
            if group is None
            else f"{TRAITS_CALLBACK_PREFIX}:sg:{sample_scope_token}:{_encode_group(group)}:{page}"
        )
        sample_name = sample.display_name

    screen_text = trait_detail_text(detail, sample_name=sample_name, lang=lang)
    markup = build_markup(rows, back_callback, lang=lang)
    await _show_or_edit(message, screen_text, markup, edit_existing=edit_existing, context=context, user_id=user_id)


async def show_sample_picker_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    flow_token: str,
    page: int,
    edit_existing: bool = False,
) -> None:
    lang = _ui_lang(context, user_id)
    flow = _flow_store(context).get(flow_token, user_id)
    if flow is None:
        await show_trait_sections_menu(message, context, user_id, edit_existing=edit_existing)
        return
    trait_name = str(flow.get("trait_name") or text("trait_label", lang=lang))
    back_callback = str(flow.get("back_callback") or f"{TRAITS_CALLBACK_PREFIX}:r")
    samples = _samples_with_raw(context, user_id)
    page_samples, current_page, total_pages = _paginate(samples, page)
    rows = []
    for item in page_samples:
        rows.append([InlineKeyboardButton(item.display_name, callback_data=f"{TRAITS_CALLBACK_PREFIX}:u:{flow_token}:{item.asset_id}")])
    previous_callback = f"{TRAITS_CALLBACK_PREFIX}:p:{flow_token}:{current_page - 1}" if current_page > 0 else None
    next_callback = f"{TRAITS_CALLBACK_PREFIX}:p:{flow_token}:{current_page + 1}" if current_page + 1 < total_pages else None
    rows.extend(pager_row(previous_callback=previous_callback, next_callback=next_callback, lang=lang))

    screen_text = sample_picker_text(trait_name, page_samples, page=current_page, total_pages=total_pages, lang=lang)
    markup = InlineKeyboardMarkup(rows + [_footer_row(back_callback, lang=lang)])
    await _show_or_edit(message, screen_text, markup, edit_existing=edit_existing, context=context, user_id=user_id)


async def show_sample_trait_reports_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    sample_id: str,
    *,
    back_callback: str | None = None,
    edit_existing: bool = False,
) -> None:
    lang = _ui_lang(context, user_id)
    sample = _my_data_store(context).get_sample(user_id, sample_id)
    if sample is None:
        await _show_or_edit(
            message,
            error_text(text("trait_reports_title", lang=lang), text("saved_sample_not_found", lang=lang)),
            build_markup([], f"{TRAITS_CALLBACK_PREFIX}:saved:0", lang=lang),
            edit_existing=edit_existing,
            context=context,
            user_id=user_id,
        )
        return

    reports = _report_store(context).list_reports(user_id, sample.asset_id)
    actual_back_callback = back_callback or f"{TRAITS_CALLBACK_PREFIX}:saved:0"
    scope_token = _flow_store(context).create(
        user_id=user_id,
        payload={"mode": "sample_scope", "sample_id": sample.asset_id, "back_callback": f"{TRAITS_CALLBACK_PREFIX}:rs:{sample.asset_id}"},
    )
    rows = []
    for item in reports[:10]:
        rows.append(
            [
                InlineKeyboardButton(
                    report_button_label(item, lang=lang),
                    callback_data=f"{TRAITS_CALLBACK_PREFIX}:o:{item.report_id}",
                )
            ]
        )
    rows.append(
        [InlineKeyboardButton(text("run_new_trait_report", lang=lang), callback_data=f"{TRAITS_CALLBACK_PREFIX}:ss:{scope_token}")]
    )
    screen_text = sample_trait_reports_text(sample, reports, lang=lang)
    markup = build_markup(rows, actual_back_callback, lang=lang)
    await _show_or_edit(message, screen_text, markup, edit_existing=edit_existing, context=context, user_id=user_id)


async def show_saved_report_sample_picker(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    page: int,
    edit_existing: bool = False,
) -> None:
    lang = _ui_lang(context, user_id)
    samples = _my_data_store(context).list_samples(user_id)
    report_counts = _report_store(context).count_reports_by_sample(user_id)
    page_samples, current_page, total_pages = _paginate(samples, page)
    rows = [
        [
            InlineKeyboardButton(
                f"{sample.display_name} ({report_counts.get(sample.asset_id, 0)})",
                callback_data=f"{TRAITS_CALLBACK_PREFIX}:rs:{sample.asset_id}",
            )
        ]
        for sample in page_samples
    ]
    previous_callback = f"{TRAITS_CALLBACK_PREFIX}:saved:{current_page - 1}" if current_page > 0 else None
    next_callback = f"{TRAITS_CALLBACK_PREFIX}:saved:{current_page + 1}" if current_page + 1 < total_pages else None
    rows.extend(pager_row(previous_callback=previous_callback, next_callback=next_callback, lang=lang))
    await _show_or_edit(
        message,
        saved_report_samples_text(samples, report_counts, lang=lang),
        build_markup(rows, f"{TRAITS_CALLBACK_PREFIX}:root", lang=lang),
        edit_existing=edit_existing,
        context=context,
        user_id=user_id,
    )


async def show_trait_report_detail_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    report_id: str,
    *,
    edit_existing: bool = False,
) -> None:
    lang = _ui_lang(context, user_id)
    record = _report_store(context).find_report(user_id, report_id)
    if record is None:
        await _show_or_edit(
            message,
            error_text(text("trait_reports_title", lang=lang), text("saved_report_not_found", lang=lang)),
            build_markup([], f"{TRAITS_CALLBACK_PREFIX}:r", lang=lang),
            edit_existing=edit_existing,
            context=context,
            user_id=user_id,
        )
        return

    rows = [
        [InlineKeyboardButton(text("run_trait_again", lang=lang), callback_data=f"{TRAITS_CALLBACK_PREFIX}:d:0:{record.summary.trait_id}")]
    ]
    screen_text = trait_report_text(record, lang=lang)
    markup = build_markup(rows, f"{TRAITS_CALLBACK_PREFIX}:rs:{record.summary.sample_id}", lang=lang)
    await _show_trait_visual(
        message,
        context,
        user_id,
        sample_name=record.summary.sample_name,
        technical_payload=record.technical_payload,
        product_payload=record.product_payload,
        caption=trait_report_visual_caption(record, lang=lang),
        fallback_text=screen_text,
        reply_markup=markup,
        lang=lang,
        status_label="SAVED",
        edit_existing=edit_existing,
    )


async def show_trait_info_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    trait_id: str,
    back_callback: str,
    edit_existing: bool = False,
) -> None:
    lang = _ui_lang(context, user_id)
    detail = _catalog(context).get_trait_detail(trait_id)
    await _show_or_edit(
        message,
        trait_detail_text(detail, lang=lang),
        InlineKeyboardMarkup([_footer_row(back_callback, lang=lang)]),
        edit_existing=edit_existing,
        context=context,
        user_id=user_id,
    )


async def show_trait_info_from_result(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    token: str,
    *,
    edit_existing: bool = False,
) -> None:
    flow = _flow_store(context).get(token, user_id)
    if flow is None or flow.get("mode") != "save_report":
        await show_trait_sections_menu(message, context, user_id, edit_existing=edit_existing)
        return
    technical_payload = dict(flow.get("technical_payload") or {})
    product_payload = dict(flow.get("product_payload") or {})
    trait_id = str(product_payload.get("trait_id") or technical_payload.get("trait_id") or "")
    await show_trait_info_menu(
        message,
        context,
        user_id,
        trait_id=trait_id,
        back_callback=f"{TRAITS_CALLBACK_PREFIX}:rp:{token}",
        edit_existing=edit_existing,
    )


async def show_trait_result_preview_from_flow(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    token: str,
    *,
    edit_existing: bool = False,
) -> None:
    lang = _ui_lang(context, user_id)
    flow = _flow_store(context).get(token, user_id)
    if flow is None or flow.get("mode") != "save_report":
        await show_trait_sections_menu(message, context, user_id, edit_existing=edit_existing)
        return
    technical_payload = dict(flow.get("technical_payload") or {})
    product_payload = dict(flow.get("product_payload") or {})
    sample_name = str(flow.get("sample_name") or "")
    back_callback = str(flow.get("back_callback") or f"{TRAITS_CALLBACK_PREFIX}:r")
    markup = _result_preview_markup(
        save_token=token,
        sample_id=str(flow.get("sample_id") or ""),
        back_callback=back_callback,
        lang=lang,
    )
    await _show_trait_visual(
        message,
        context,
        user_id,
        sample_name=sample_name,
        technical_payload=technical_payload,
        product_payload=product_payload,
        caption=trait_visual_caption(
            sample_name=sample_name,
            technical_payload=technical_payload,
            product_payload=product_payload,
            lang=lang,
        ),
        fallback_text=trait_result_preview_text(
            sample_name=sample_name,
            technical_payload=technical_payload,
            product_payload=product_payload,
            lang=lang,
        ),
        reply_markup=markup,
        lang=lang,
        status_label="PREVIEW",
        edit_existing=edit_existing,
    )


async def save_pending_trait_report(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    token: str,
    *,
    edit_existing: bool = False,
) -> None:
    lang = _ui_lang(context, user_id)
    flow = _flow_store(context).get(token, user_id)
    if flow is None or flow.get("mode") != "save_report":
        await _show_or_edit(
            message,
            error_text(text("trait_result", lang=lang), text("saved_report_not_found", lang=lang)),
            build_markup([], f"{TRAITS_CALLBACK_PREFIX}:r", lang=lang),
            edit_existing=edit_existing,
            context=context,
            user_id=user_id,
        )
        return
    saved = _report_store(context).save_report(
        user_id,
        sample_id=str(flow.get("sample_id") or ""),
        sample_name=str(flow.get("sample_name") or ""),
        raw_file_id=str(flow.get("raw_file_id") or ""),
        technical_payload=dict(flow.get("technical_payload") or {}),
        product_payload=dict(flow.get("product_payload") or {}),
    )
    rows = [
        [InlineKeyboardButton(text("open_saved_report", lang=lang), callback_data=f"{TRAITS_CALLBACK_PREFIX}:o:{saved.summary.report_id}")],
        [InlineKeyboardButton(text("sample_trait_reports", lang=lang), callback_data=f"{TRAITS_CALLBACK_PREFIX}:rs:{saved.summary.sample_id}")],
    ]
    markup = build_markup(rows, str(flow.get("back_callback") or f"{TRAITS_CALLBACK_PREFIX}:r"), lang=lang)
    await _show_trait_visual(
        message,
        context,
        user_id,
        sample_name=saved.summary.sample_name,
        technical_payload=saved.technical_payload,
        product_payload=saved.product_payload,
        caption=trait_report_visual_caption(saved, lang=lang),
        fallback_text=text("result_saved", lang=lang) + "\n\n" + report_saved_text(saved, lang=lang),
        reply_markup=markup,
        lang=lang,
        status_label="SAVED",
        edit_existing=edit_existing,
    )


async def _run_trait_for_sample(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    trait_id: str,
    sample_id: str,
    back_callback: str,
) -> None:
    lang = _ui_lang(context, user_id)
    sample = _my_data_store(context).get_sample(user_id, sample_id)
    if sample is None:
        await _show_or_edit(
            message,
            error_text(text("trait_result", lang=lang), text("saved_sample_not_found", lang=lang)),
            build_markup([], back_callback, lang=lang),
            edit_existing=True,
            context=context,
            user_id=user_id,
        )
        return

    raw_file = _my_data_store(context).get_sample_raw_file(user_id, sample.asset_id)
    if raw_file is None:
        await _show_or_edit(
            message,
            error_text(text("trait_result", lang=lang), text("source_raw_not_found", lang=lang)),
            build_markup([], back_callback, lang=lang),
            edit_existing=True,
            context=context,
            user_id=user_id,
        )
        return

    raw_path = _my_data_store(context).resolve_raw_file_path(raw_file)
    if not raw_path.exists():
        await _show_or_edit(
            message,
            error_text(text("trait_result", lang=lang), text("source_raw_missing_on_disk", lang=lang)),
            build_markup([], back_callback, lang=lang),
            edit_existing=True,
            context=context,
            user_id=user_id,
        )
        return

    message = await _show_status_message(message, running_trait_text(trait_id=trait_id, sample_name=sample.display_name, lang=lang))
    try:
        result = _runtime(context).score_trait(
            trait_id=trait_id,
            raw_path=Path(raw_path),
            sample_id=sample.display_name,
        )
    except (TraitRuntimeError, TraitCatalogError) as exc:
        await _show_or_edit(
            message,
            error_text(text("trait_result", lang=lang), text("could_not_run_trait", lang=lang), details=str(exc)),
            build_markup([], back_callback, lang=lang),
            edit_existing=True,
            context=context,
            user_id=user_id,
        )
        return

    save_token = _flow_store(context).create(
        user_id=user_id,
        payload={
            "mode": "save_report",
            "sample_id": sample.asset_id,
            "sample_name": sample.display_name,
            "raw_file_id": sample.raw_file_id,
            "technical_payload": result.technical_payload,
            "product_payload": result.product_payload,
            "back_callback": back_callback,
        },
    )
    markup = _result_preview_markup(
        save_token=save_token,
        sample_id=sample.asset_id,
        back_callback=back_callback,
        lang=lang,
    )
    preview_text = trait_result_preview_text(
        sample_name=sample.display_name,
        technical_payload=result.technical_payload,
        product_payload=result.product_payload,
        lang=lang,
    )
    await _show_trait_visual(
        message,
        context,
        user_id,
        sample_name=sample.display_name,
        technical_payload=result.technical_payload,
        product_payload=result.product_payload,
        caption=trait_visual_caption(
            sample_name=sample.display_name,
            technical_payload=result.technical_payload,
            product_payload=result.product_payload,
            lang=lang,
        ),
        fallback_text=preview_text,
        reply_markup=markup,
        lang=lang,
        status_label="PREVIEW",
        edit_existing=True,
    )


async def traits_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None or query.message is None:
        return
    if not query.data.startswith(f"{TRAITS_CALLBACK_PREFIX}:"):
        return
    if not await ensure_active_main_menu(update, context):
        return
    if update.effective_user is None:
        return

    await query.answer()
    parts = query.data.split(":")
    action = parts[1] if len(parts) > 1 else ""
    user_id = update.effective_user.id

    try:
        if action in {"root", "r"}:
            await show_traits_root_menu(query.message, context, user_id, edit_existing=True)
            return
        if action == "s":
            await show_trait_sections_menu(query.message, context, user_id, edit_existing=True)
            return
        if action == "pick":
            await show_trait_run_sample_picker_menu(
                query.message,
                context,
                user_id,
                page=int(parts[2] if len(parts) > 2 else 0),
                edit_existing=True,
            )
            return
        if action == "about":
            await show_traits_about_menu(query.message, context, user_id, edit_existing=True)
            return
        if action == "saved":
            await show_saved_report_sample_picker(
                query.message,
                context,
                user_id,
                page=int(parts[2] if len(parts) > 2 else 0),
                edit_existing=True,
            )
            return
        if action == "rs":
            await show_sample_trait_reports_menu(
                query.message,
                context,
                user_id,
                parts[2] if len(parts) > 2 else "",
                back_callback=f"{TRAITS_CALLBACK_PREFIX}:saved:0",
                edit_existing=True,
            )
            return
        if action == "ss":
            await show_trait_sections_menu(query.message, context, user_id, sample_scope_token=parts[2], edit_existing=True)
            return
        if action == "l":
            await show_trait_catalog_menu(query.message, context, user_id, page=int(parts[2] if len(parts) > 2 else 0), group=None, edit_existing=True)
            return
        if action == "g":
            await show_trait_catalog_menu(
                query.message,
                context,
                user_id,
                group=_decode_group(parts[2] if len(parts) > 2 else None),
                page=int(parts[3] if len(parts) > 3 else 0),
                edit_existing=True,
            )
            return
        if action == "sg":
            await show_trait_catalog_menu(
                query.message,
                context,
                user_id,
                sample_scope_token=parts[2] if len(parts) > 2 else None,
                group=_decode_group(parts[3] if len(parts) > 3 else None),
                page=int(parts[4] if len(parts) > 4 else 0),
                edit_existing=True,
            )
            return
        if action == "d":
            await show_trait_detail_menu(
                query.message,
                context,
                user_id,
                trait_id=parts[3] if len(parts) > 3 else "",
                page=int(parts[2] if len(parts) > 2 else 0),
                group=None,
                edit_existing=True,
            )
            return
        if action == "dg":
            await show_trait_detail_menu(
                query.message,
                context,
                user_id,
                group=_decode_group(parts[2] if len(parts) > 2 else None),
                page=int(parts[3] if len(parts) > 3 else 0),
                trait_id=parts[4] if len(parts) > 4 else "",
                edit_existing=True,
            )
            return
        if action == "p":
            await show_sample_picker_menu(
                query.message,
                context,
                user_id,
                flow_token=parts[2] if len(parts) > 2 else "",
                page=int(parts[3] if len(parts) > 3 else 0),
                edit_existing=True,
            )
            return
        if action == "u":
            flow = _flow_store(context).get(parts[2] if len(parts) > 2 else "", user_id)
            if flow is None:
                await show_trait_sections_menu(query.message, context, user_id, edit_existing=True)
                return
            await _run_trait_for_sample(
                query.message,
                context,
                user_id,
                trait_id=str(flow.get("trait_id") or ""),
                sample_id=parts[3] if len(parts) > 3 else "",
                back_callback=str(flow.get("back_callback") or f"{TRAITS_CALLBACK_PREFIX}:r"),
            )
            return
        if action == "sl":
            await show_trait_catalog_menu(
                query.message,
                context,
                user_id,
                sample_scope_token=parts[2] if len(parts) > 2 else None,
                page=int(parts[3] if len(parts) > 3 else 0),
                group=None,
                edit_existing=True,
            )
            return
        if action == "sd":
            await show_trait_detail_menu(
                query.message,
                context,
                user_id,
                sample_scope_token=parts[2] if len(parts) > 2 else None,
                page=int(parts[3] if len(parts) > 3 else 0),
                trait_id=parts[4] if len(parts) > 4 else "",
                group=None,
                edit_existing=True,
            )
            return
        if action == "sgd":
            await show_trait_detail_menu(
                query.message,
                context,
                user_id,
                sample_scope_token=parts[2] if len(parts) > 2 else None,
                group=_decode_group(parts[3] if len(parts) > 3 else None),
                page=int(parts[4] if len(parts) > 4 else 0),
                trait_id=parts[5] if len(parts) > 5 else "",
                edit_existing=True,
            )
            return
        if action == "sr":
            flow = _flow_store(context).get(parts[2] if len(parts) > 2 else "", user_id)
            if flow is None:
                await show_trait_sections_menu(query.message, context, user_id, edit_existing=True)
                return
            await _run_trait_for_sample(
                query.message,
                context,
                user_id,
                trait_id=str(flow.get("trait_id") or ""),
                sample_id=str(flow.get("sample_id") or ""),
                back_callback=str(flow.get("back_callback") or f"{TRAITS_CALLBACK_PREFIX}:r"),
            )
            return
        if action == "i":
            await show_trait_info_from_result(
                query.message,
                context,
                user_id,
                parts[2] if len(parts) > 2 else "",
                edit_existing=True,
            )
            return
        if action == "rp":
            await show_trait_result_preview_from_flow(
                query.message,
                context,
                user_id,
                parts[2] if len(parts) > 2 else "",
                edit_existing=True,
            )
            return
        if action == "sv":
            await save_pending_trait_report(
                query.message,
                context,
                user_id,
                parts[2] if len(parts) > 2 else "",
                edit_existing=True,
            )
            return
        if action == "o":
            await show_trait_report_detail_menu(
                query.message,
                context,
                user_id,
                parts[2] if len(parts) > 2 else "",
                edit_existing=True,
            )
            return
    except (TraitCatalogError, TraitRuntimeError, ValueError) as exc:
        lang = _ui_lang(context, user_id)
        await _show_or_edit(
            query.message,
            error_text(text("traits_title", lang=lang), text("could_not_open_screen", lang=lang), details=str(exc)),
            build_markup([], "main:root", lang=lang),
            edit_existing=True,
            context=context,
            user_id=user_id,
        )
