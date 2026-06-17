from __future__ import annotations

import asyncio
import logging
import secrets
import shutil
import tempfile
from math import ceil
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, Update
from telegram.ext import ContextTypes

from app.features.my_data.storage import CoordinateAsset, MyDataStore, SampleAsset
from app.features.traits.domain.runtime import TraitsRuntimeService
from app.i18n import t
from app.main_menu import set_active_main_menu_message
from g25_core.command_service import G25CommandService

from .domain import DNAPassportData
from .render import render_dna_passport_html
from .render_visual import DNAPassportVisualPage, render_dna_passport_pages
from .service import DNAPassportService


logger = logging.getLogger(__name__)

PASSPORT_CALLBACK_PREFIX = "reports:passport"
_PAGE_SIZE = 8
_DETAIL_CACHE_KEY = "dna_passport_detail_cache"
_DETAIL_CACHE_LIMIT = 8


def passport_intro_text(*, lang: str = "ru") -> str:
    if lang == "en":
        return (
            "🧬 DNA passport\n\n"
            "A short personal report for an uploaded DNA sample.\n\n"
            "The passport checks the source file, shows a short G25 position, calculates basic genetic traits, and estimates direct-line data availability."
        )
    return (
        "🧬 DNA-паспорт\n\n"
        "Краткий персональный отчёт по загруженному DNA-образцу.\n\n"
        "Паспорт проверит исходный файл, покажет краткое положение по G25, рассчитает базовые генетические признаки и оценит доступность данных прямых линий."
    )


def build_passport_intro_keyboard(*, lang: str = "ru") -> InlineKeyboardMarkup:
    label = "🧬 Generate DNA passport" if lang == "en" else "🧬 Сформировать DNA-паспорт"
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(label, callback_data=f"{PASSPORT_CALLBACK_PREFIX}:samples:0")],
            _back_cancel_row("reports:root", lang=lang),
        ]
    )


def sample_picker_text(samples: list[SampleAsset], *, lang: str = "ru") -> str:
    if not samples:
        if lang == "en":
            return (
                "🧬 DNA passport\n\n"
                "You do not have samples yet.\n\n"
                "Add a DNA file or G25 profile in My DNA."
            )
        return (
            "🧬 DNA-паспорт\n\n"
            "У вас пока нет образцов.\n\n"
            "Добавьте DNA-файл или G25-профиль в разделе My DNA."
        )
    return "🧬 DNA passport\n\nChoose a sample." if lang == "en" else "🧬 DNA-паспорт\n\nВыберите образец."


def build_sample_picker_keyboard(samples: list[SampleAsset], *, page: int = 0, lang: str = "ru") -> InlineKeyboardMarkup:
    page_items, current_page, total_pages = _paginate(samples, page)
    rows = [
        [InlineKeyboardButton(_button_label(sample.display_name), callback_data=f"{PASSPORT_CALLBACK_PREFIX}:sample:{sample.asset_id}")]
        for sample in page_items
    ]
    rows.extend(_pager_rows(current_page, total_pages, f"{PASSPORT_CALLBACK_PREFIX}:samples", lang=lang))
    rows.append(_back_cancel_row(f"{PASSPORT_CALLBACK_PREFIX}:intro", lang=lang))
    return InlineKeyboardMarkup(rows)


def build_passport_result_keyboard(*, back_callback: str, lang: str = "ru") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([_back_cancel_row(back_callback, lang=lang)])


def build_passport_visual_keyboard(*, detail_callback: str, back_callback: str, lang: str = "ru") -> InlineKeyboardMarkup:
    if lang == "en":
        detail_label = "📄 Detailed report"
        sample_label = "🔁 Another sample"
    else:
        detail_label = "📄 Подробный отчёт"
        sample_label = "🔁 Другой образец"
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(detail_label, callback_data=detail_callback)],
            [InlineKeyboardButton(sample_label, callback_data=f"{PASSPORT_CALLBACK_PREFIX}:samples:0")],
            [InlineKeyboardButton(t("nav.back", lang), callback_data=back_callback)],
        ]
    )


async def show_passport_intro_menu(
    message,
    *,
    edit_existing: bool = True,
    lang: str = "ru",
) -> None:
    markup = build_passport_intro_keyboard(lang=lang)
    if edit_existing:
        await message.edit_text(passport_intro_text(lang=lang), reply_markup=markup)
    else:
        await message.reply_text(passport_intro_text(lang=lang), reply_markup=markup, do_quote=False)


async def dna_passport_callback_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    user_id: int,
    lang: str = "ru",
) -> None:
    query = update.callback_query
    if query is None or query.data is None or query.message is None:
        return
    parts = query.data.split(":")
    action = parts[2] if len(parts) > 2 else "intro"
    if action == "intro":
        await show_passport_intro_menu(query.message, edit_existing=True, lang=lang)
        return
    if action == "samples":
        page = _int_part(parts, 3)
        await show_sample_picker_menu(query.message, context, user_id, page=page, lang=lang)
        return
    if action == "sample":
        sample_id = parts[3] if len(parts) > 3 else ""
        await handle_sample_selected(query.message, context, user_id, sample_id=sample_id, lang=lang)
        return
    if action == "detail":
        token = parts[3] if len(parts) > 3 else ""
        await show_passport_detail(query.message, context, token=token, lang=lang)
        return
    if action == "g25":
        sample_id = parts[3] if len(parts) > 3 else ""
        await run_passport(query.message, context, user_id, sample_id=sample_id, coordinate_id=None, origin="samples", lang=lang)
        return
    if action == "run":
        sample_id = parts[3] if len(parts) > 3 else ""
        coordinate_id = parts[4] if len(parts) > 4 and parts[4] != "-" else None
        origin = parts[5] if len(parts) > 5 else "samples"
        await run_passport(query.message, context, user_id, sample_id=sample_id, coordinate_id=coordinate_id, origin=origin, lang=lang)
        return
    await show_passport_intro_menu(query.message, edit_existing=True, lang=lang)


async def show_sample_picker_menu(message, context: ContextTypes.DEFAULT_TYPE, user_id: int, *, page: int = 0, lang: str = "ru") -> None:
    samples = _safe_samples(context, user_id)
    await message.edit_text(
        sample_picker_text(samples, lang=lang),
        reply_markup=build_sample_picker_keyboard(samples, page=page, lang=lang),
    )


async def handle_sample_selected(message, context: ContextTypes.DEFAULT_TYPE, user_id: int, *, sample_id: str, lang: str = "ru") -> None:
    store = _my_data_store(context)
    sample = store.get_sample(user_id, sample_id)
    if sample is None:
        await show_sample_picker_menu(message, context, user_id, page=0, lang=lang)
        return
    await run_passport(message, context, user_id, sample_id=sample.asset_id, coordinate_id=None, origin="samples", lang=lang)


async def show_passport_detail(message, context: ContextTypes.DEFAULT_TYPE, *, token: str, lang: str = "ru") -> None:
    payload = _get_passport_detail(context, token)
    if payload is None:
        text = (
            "Detailed report is no longer available. Please build the DNA passport again."
            if lang == "en"
            else "Подробная версия больше недоступна. Сформируйте DNA-паспорт ещё раз."
        )
        await message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("🔁 Another sample" if lang == "en" else "🔁 Другой образец", callback_data=f"{PASSPORT_CALLBACK_PREFIX}:samples:0")],
                    _back_cancel_row("reports:root", lang=lang),
                ]
            ),
        )
        return
    await message.edit_text(
        payload["text"],
        reply_markup=build_passport_result_keyboard(back_callback=payload["back_callback"], lang=lang),
        parse_mode="HTML",
    )


async def run_passport(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    sample_id: str,
    coordinate_id: str | None,
    origin: str,
    lang: str = "ru",
) -> None:
    await message.edit_text(_passport_status_text(context, user_id, sample_id, lang=lang))
    back_callback = f"{PASSPORT_CALLBACK_PREFIX}:samples:0"
    try:
        service = _passport_service(context)
        data = await asyncio.to_thread(
            service.build_for_sample,
            user_id=user_id,
            sample_id=sample_id,
            g25_coordinate_id=coordinate_id,
        )
        text = render_dna_passport_html(data, lang=lang)
    except Exception:
        logger.exception("Could not build DNA passport")
        text = (
            "Не удалось сформировать DNA-паспорт.\n\n"
            "Попробуйте ещё раз или проверьте данные образца."
        )
        await message.edit_text(text, reply_markup=build_passport_result_keyboard(back_callback=back_callback, lang=lang), parse_mode="HTML")
        return

    visual_sent = await _send_passport_visual_album(
        message,
        context,
        user_id,
        data,
        text,
        back_callback=back_callback,
        lang=lang,
    )
    if visual_sent:
        return
    await message.edit_text(text, reply_markup=build_passport_result_keyboard(back_callback=back_callback, lang=lang), parse_mode="HTML")


async def _send_passport_visual_album(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    data: DNAPassportData,
    detail_text: str,
    *,
    back_callback: str,
    lang: str = "ru",
) -> bool:
    if not hasattr(message, "reply_media_group"):
        return False
    try:
        pages = await asyncio.to_thread(_render_passport_visual_pages_temp, data)
        await _reply_visual_pages(message, pages)
        token = _store_passport_detail(context, text=detail_text, back_callback=back_callback)
        detail_callback = f"{PASSPORT_CALLBACK_PREFIX}:detail:{token}"
        await _send_passport_visual_followup(
            message,
            context,
            user_id=user_id,
            detail_callback=detail_callback,
            back_callback=back_callback,
            lang=lang,
        )
        return True
    except Exception:
        logger.exception("Could not send DNA passport visual album")
        return False
    finally:
        pages = locals().get("pages", [])
        for page in pages:
            try:
                page.path.unlink(missing_ok=True)
            except OSError:
                logger.debug("Could not delete DNA passport visual temp file", exc_info=True)
        parent = None
        if pages:
            parent = pages[0].path.parent
        if parent is not None:
            try:
                parent.rmdir()
            except OSError:
                logger.debug("Could not delete DNA passport visual temp directory", exc_info=True)


def _render_passport_visual_pages_temp(data: DNAPassportData) -> list[DNAPassportVisualPage]:
    path = Path(tempfile.mkdtemp(prefix="kbdna_passport_pages_"))
    try:
        return render_dna_passport_pages(data, path)
    except Exception:
        shutil.rmtree(path, ignore_errors=True)
        raise


async def _reply_visual_pages(message, pages: list[DNAPassportVisualPage]) -> None:
    handles = [page.path.open("rb") for page in pages]
    try:
        media = [InputMediaPhoto(media=handle) for handle in handles]
        await message.reply_media_group(media=media, do_quote=False)
    finally:
        for handle in handles:
            handle.close()


async def _send_passport_visual_followup(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    user_id: int,
    detail_callback: str,
    back_callback: str,
    lang: str = "ru",
) -> None:
    text = _passport_visual_followup_text(lang=lang)
    markup = build_passport_visual_keyboard(detail_callback=detail_callback, back_callback=back_callback, lang=lang)
    if hasattr(message, "reply_text"):
        sent = await message.reply_text(text, reply_markup=markup, do_quote=False)
        _remember_active_message(context, sent, user_id)
        await _delete_message_if_possible(message)
        return
    await message.edit_text(text, reply_markup=markup)
    _remember_active_message(context, message, user_id)


def _remember_active_message(context: ContextTypes.DEFAULT_TYPE, message, user_id: int) -> None:
    chat_id = getattr(message, "chat_id", None)
    message_id = getattr(message, "message_id", None)
    if chat_id is None or message_id is None:
        return
    set_active_main_menu_message(context, int(chat_id), int(user_id), int(message_id))


async def _delete_message_if_possible(message) -> None:
    if hasattr(message, "delete"):
        try:
            await message.delete()
        except Exception:
            logger.debug("Could not delete DNA passport status message", exc_info=True)


def _passport_visual_followup_text(*, lang: str = "ru") -> str:
    if lang == "en":
        return (
            "🧬 DNA passport is ready.\n\n"
            "This is the short visual version. Details and limitations are available in the text report."
        )
    return (
        "🧬 DNA-паспорт готов.\n\n"
        "Это краткая визуальная версия отчёта. Подробности и ограничения доступны в текстовой версии."
    )


def _store_passport_detail(context: ContextTypes.DEFAULT_TYPE, *, text: str, back_callback: str) -> str:
    token = secrets.token_urlsafe(8)
    user_data = getattr(context, "user_data", None)
    if not isinstance(user_data, dict):
        return token
    cache = user_data.setdefault(_DETAIL_CACHE_KEY, {})
    if not isinstance(cache, dict):
        cache = {}
        user_data[_DETAIL_CACHE_KEY] = cache
    while len(cache) >= _DETAIL_CACHE_LIMIT:
        oldest = next(iter(cache))
        cache.pop(oldest, None)
    cache[token] = {"text": text, "back_callback": back_callback}
    return token


def _get_passport_detail(context: ContextTypes.DEFAULT_TYPE, token: str) -> dict[str, str] | None:
    user_data = getattr(context, "user_data", None)
    if not isinstance(user_data, dict):
        return None
    cache = user_data.get(_DETAIL_CACHE_KEY)
    if not isinstance(cache, dict):
        return None
    payload = cache.get(token)
    if not isinstance(payload, dict):
        return None
    text = payload.get("text")
    back_callback = payload.get("back_callback")
    if not isinstance(text, str) or not isinstance(back_callback, str):
        return None
    return {"text": text, "back_callback": back_callback}


def _passport_service(context: ContextTypes.DEFAULT_TYPE) -> DNAPassportService:
    runtime = context.application.bot_data.get("traits_runtime")
    g25_service = context.application.bot_data.get("pca_service")
    return DNAPassportService(
        my_data_store=_my_data_store(context),
        traits_runtime=runtime if isinstance(runtime, TraitsRuntimeService) else None,
        g25_service=g25_service if isinstance(g25_service, G25CommandService) else None,
    )


def _my_data_store(context: ContextTypes.DEFAULT_TYPE) -> MyDataStore:
    return context.application.bot_data["my_data_store"]


def _safe_samples(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> list[SampleAsset]:
    try:
        return list(_my_data_store(context).list_samples(user_id))
    except Exception:
        logger.exception("Could not list samples for DNA passport")
        return []


def _sample_g25_coordinates(store: MyDataStore, user_id: int, sample_id: str) -> list[CoordinateAsset]:
    return [
        coordinate
        for coordinate in store.list_sample_coordinates(user_id, sample_id)
        if str(coordinate.coordinate_type or "").strip().lower() == "g25" and str(coordinate.g25_line or "").strip()
    ]


def _passport_status_text(context: ContextTypes.DEFAULT_TYPE, user_id: int, sample_id: str, *, lang: str = "ru") -> str:
    intro = passport_intro_text(lang=lang)
    if _needs_raw_g25_calculation(context, user_id, sample_id):
        if lang == "en":
            return f"{intro}\n\n⏳ Building the report...\nCalculating G25 coordinates from the DNA file."
        return f"{intro}\n\n⏳ Формируем отчёт…\nПолучаем координаты G25 из DNA-файла."
    status = "⏳ Building the report..." if lang == "en" else "⏳ Формируем отчёт…"
    return f"{intro}\n\n{status}"


def _needs_raw_g25_calculation(context: ContextTypes.DEFAULT_TYPE, user_id: int, sample_id: str) -> bool:
    try:
        store = _my_data_store(context)
        sample = store.get_sample(user_id, sample_id)
    except Exception:
        logger.debug("Could not inspect sample before DNA passport run", exc_info=True)
        return False
    if sample is None or not sample.raw_file_id:
        return False
    try:
        return not _sample_g25_coordinates(store, user_id, sample.asset_id)
    except Exception:
        logger.debug("Could not inspect sample G25 coordinates before DNA passport run", exc_info=True)
        return False


def _back_cancel_row(back_callback: str, *, lang: str = "ru") -> list[InlineKeyboardButton]:
    return [
        InlineKeyboardButton(t("nav.back", lang), callback_data=back_callback),
        InlineKeyboardButton(t("nav.cancel", lang), callback_data="main:cancel"),
    ]


def _pager_rows(current_page: int, total_pages: int, prefix: str, *, lang: str = "ru") -> list[list[InlineKeyboardButton]]:
    if total_pages <= 1:
        return []
    rows = []
    controls = []
    if current_page > 0:
        controls.append(InlineKeyboardButton("‹", callback_data=f"{prefix}:{current_page - 1}"))
    controls.append(InlineKeyboardButton(f"{current_page + 1}/{total_pages}", callback_data=f"{prefix}:{current_page}"))
    if current_page + 1 < total_pages:
        controls.append(InlineKeyboardButton("›", callback_data=f"{prefix}:{current_page + 1}"))
    rows.append(controls)
    return rows


def _paginate(items: list[SampleAsset], page: int) -> tuple[list[SampleAsset], int, int]:
    total_pages = max(1, ceil(len(items) / _PAGE_SIZE)) if items else 1
    current_page = max(0, min(page, total_pages - 1))
    start = current_page * _PAGE_SIZE
    return items[start : start + _PAGE_SIZE], current_page, total_pages


def _button_label(value: str, *, max_length: int = 46) -> str:
    cleaned = " ".join(str(value or "").split()) or "Sample"
    if len(cleaned) <= max_length:
        return cleaned
    return cleaned[: max_length - 3].rstrip() + "..."


def _int_part(parts: list[str], index: int, default: int = 0) -> int:
    try:
        return int(parts[index])
    except (IndexError, TypeError, ValueError):
        return default
