from __future__ import annotations

import html
import os
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from app.features.modeling.datasets import DATASET_LABELS, dataset_label
from app.features.modeling.navigation import nav_back_callback, nav_enter
from app.features.modeling.ui import footer_row as _footer_row
from app.features.modeling.ui import modeling_cb as _cb
from app.features.modeling.ui import page_nav_row
from app.features.modeling.ui import show_message as _show_message
from app.features.modeling.storage import read_record_list, write_record_list
from app.main_menu import set_active_main_menu_message


SAVED_MODELS_PATH = Path(os.getenv("KBDNA_SAVED_MODELS_PATH", "/opt/kbdnabot/storage/modeling/saved_models.json"))
PENDING_SAVES_KEY = "admixlab_pending_model_saves"
SAVED_MODELS_PAGE_SIZE = 8

def _dataset_label(dataset: object) -> str:
    return dataset_label(dataset)


def _safe_page(value: object) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _read_records() -> list[dict[str, Any]]:
    return read_record_list(SAVED_MODELS_PATH)


def _write_records(records: list[dict[str, Any]]) -> None:
    write_record_list(SAVED_MODELS_PATH, records)


def _user_records(user_id: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in _read_records():
        if int(item.get("owner_user_id") or 0) == int(user_id):
            rows.append(item)
    return sorted(rows, key=lambda item: str(item.get("saved_at") or item.get("created_at") or ""), reverse=True)


def _get_record(user_id: int, record_id: str) -> dict[str, Any] | None:
    for item in _read_records():
        if str(item.get("id") or "") == record_id and int(item.get("owner_user_id") or 0) == int(user_id):
            return item
    return None


def _delete_record(user_id: int, record_id: str) -> bool:
    records = _read_records()
    kept: list[dict[str, Any]] = []
    deleted = False
    for item in records:
        if str(item.get("id") or "") == record_id and int(item.get("owner_user_id") or 0) == int(user_id):
            deleted = True
            continue
        kept.append(item)
    if deleted:
        _write_records(kept)
    return deleted


def _pending_store(context: ContextTypes.DEFAULT_TYPE) -> dict[str, dict[str, Any]]:
    store = context.application.bot_data.get(PENDING_SAVES_KEY)
    if not isinstance(store, dict):
        store = {}
        context.application.bot_data[PENDING_SAVES_KEY] = store
    return store


def register_pending_save(context: ContextTypes.DEFAULT_TYPE, user_id: int, payload: dict[str, Any]) -> str:
    pending_id = uuid4().hex[:12]
    record = dict(payload)
    record["pending_id"] = pending_id
    record["owner_user_id"] = int(user_id)
    record["created_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _pending_store(context)[pending_id] = record
    return pending_id


def _save_pending(context: ContextTypes.DEFAULT_TYPE, user_id: int, pending_id: str) -> dict[str, Any] | None:
    pending = _pending_store(context).get(pending_id)
    if not isinstance(pending, dict) or int(pending.get("owner_user_id") or 0) != int(user_id):
        return None
    records = _read_records()
    record = dict(pending)
    record.pop("pending_id", None)
    record["id"] = uuid4().hex[:12]
    record["owner_user_id"] = int(user_id)
    record["saved_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    records.insert(0, record)
    _write_records(records)
    _pending_store(context).pop(pending_id, None)
    return record


def _kind_label(record: dict[str, Any]) -> str:
    kind = str(record.get("kind") or "")
    if kind == "qpadm_classic":
        return "qpAdm classic"
    if kind == "qpwave":
        return "qpWave"
    if kind == "qpgraph_admixtools2":
        return "ADMIXTOOLS2 qpGraph 2"
    return kind or "AdmixLab"


def _record_title(record: dict[str, Any]) -> str:
    title = str(record.get("title") or "").strip()
    if title:
        return title
    return f"{_kind_label(record)} · {_dataset_label(record.get('dataset'))}"


def _record_summary(record: dict[str, Any]) -> list[str]:
    lines = [
        f"Тип: <code>{html.escape(_kind_label(record))}</code>",
        f"Dataset: <code>{html.escape(_dataset_label(record.get('dataset')))}</code>",
    ]
    engine = str(record.get("engine_label") or record.get("engine") or "").strip()
    if engine:
        lines.append(f"Engine: <code>{html.escape(engine)}</code>")
    target = str(record.get("target") or "").strip()
    if target:
        lines.append(f"Target: <code>{html.escape(target)}</code>")
    left = record.get("sources") if isinstance(record.get("sources"), list) else record.get("left")
    right = record.get("references") if isinstance(record.get("references"), list) else record.get("right")
    if isinstance(left, list):
        lines.append(f"Left/Sources: <code>{len(left)}</code>")
    if isinstance(right, list):
        lines.append(f"Right/References: <code>{len(right)}</code>")
    saved_at = str(record.get("saved_at") or record.get("created_at") or "").strip()
    if saved_at:
        lines.append(f"Сохранено: <code>{html.escape(saved_at[:19].replace('T', ' '))}</code>")
    return lines


async def show_saved_models_menu(
    message,
    update: Update | None,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    edit_existing: bool = True,
    page: int = 0,
    lang: str = "ru",
) -> None:
    nav_enter(context, _cb("saved_page", page))
    user_id = int(update.effective_user.id) if update is not None and update.effective_user is not None else 0
    rows = _user_records(user_id)
    lines = ["<b>💾 Saved models</b>"]
    buttons: list[list[InlineKeyboardButton]] = []
    if not rows:
        lines.extend(["", "Пока нет сохраненных результатов. После расчета нажмите «Сохранить результат»."])
    else:
        page_count = max(1, (len(rows) + SAVED_MODELS_PAGE_SIZE - 1) // SAVED_MODELS_PAGE_SIZE)
        page = min(max(0, page), page_count - 1)
        start = page * SAVED_MODELS_PAGE_SIZE
        end = min(len(rows), start + SAVED_MODELS_PAGE_SIZE)
        lines.extend(["", f"Показаны: <code>{start + 1}-{end}</code> из <code>{len(rows)}</code>"])
        for item in rows[start:end]:
            label = f"{_kind_label(item)} · {_record_title(item)[:32]}"
            buttons.append([InlineKeyboardButton(label, callback_data=_cb("saved_view", item.get("id")))])
        if page_count > 1:
            buttons.append(page_nav_row(page, page_count, lambda value: _cb("saved_page", value)))
    buttons.append(_footer_row(nav_back_callback(), lang))
    await _show_message(message, "\n".join(lines), InlineKeyboardMarkup(buttons), edit_existing=edit_existing)


async def _show_saved_view(message, update: Update, context: ContextTypes.DEFAULT_TYPE, record_id: str, *, lang: str) -> None:
    user_id = int(update.effective_user.id) if update.effective_user is not None else 0
    record = _get_record(user_id, record_id)
    if record is None:
        await show_saved_models_menu(message, update, context, edit_existing=True, lang=lang)
        return
    nav_enter(context, _cb("saved_view", record_id))
    result_text = str(record.get("result_text") or "").strip()
    lines = [
        f"<b>💾 {html.escape(_record_title(record))}</b>",
        "",
        *_record_summary(record),
    ]
    if result_text:
        lines.extend(["", result_text])
    markup = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Удалить", callback_data=_cb("saved_delete", record_id))],
            _footer_row(nav_back_callback(), lang),
        ]
    )
    visual_value = str(record.get("visual_path") or "").strip()
    visual_path = Path(visual_value) if visual_value else None
    if visual_path is not None and visual_path.exists() and visual_path.is_file():
        caption = str(record.get("caption_text") or "").strip() or "\n".join(lines[:8])
        try:
            with visual_path.open("rb") as image_file:
                sent = await message.reply_photo(
                    photo=image_file,
                    caption=caption,
                    reply_markup=markup,
                    parse_mode="HTML",
                    do_quote=False,
                )
        except Exception:
            await _show_message(message, "\n".join(lines), markup, edit_existing=True)
            return
        try:
            await message.delete()
        except BadRequest:
            pass
        if update.effective_user is not None:
            set_active_main_menu_message(context, sent.chat_id, update.effective_user.id, sent.message_id)
        return
    await _show_message(message, "\n".join(lines), markup, edit_existing=True)


async def _save_pending_result(message, update: Update, context: ContextTypes.DEFAULT_TYPE, pending_id: str, *, lang: str) -> None:
    user_id = int(update.effective_user.id) if update.effective_user is not None else 0
    record = _save_pending(context, user_id, pending_id)
    if record is None:
        text = "<b>💾 Saved models</b>\n\nНе нашел результат для сохранения. Возможно, бот был перезапущен."
        await _show_message(message, text, InlineKeyboardMarkup([_footer_row(_cb("saved"), lang)]), edit_existing=True)
        return
    lines = [
        "<b>💾 Результат сохранен</b>",
        "",
        f"Название: <code>{html.escape(_record_title(record))}</code>",
        *_record_summary(record),
    ]
    markup = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Открыть", callback_data=_cb("saved_view", record.get("id")))],
            [InlineKeyboardButton("Saved models", callback_data=_cb("saved"))],
            _footer_row(_cb("saved"), lang),
        ]
    )
    await _show_message(message, "\n".join(lines), markup, edit_existing=True)


async def saved_models_callback_handler(
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
    message = query.message

    if action == "saved":
        await show_saved_models_menu(message, update, context, edit_existing=True, lang=lang)
        return
    if action == "saved_page" and len(parts) >= 3:
        await show_saved_models_menu(message, update, context, edit_existing=True, page=_safe_page(parts[2]), lang=lang)
        return
    if action == "saved_view" and len(parts) >= 3:
        await _show_saved_view(message, update, context, parts[2], lang=lang)
        return
    if action == "saved_save" and len(parts) >= 3:
        await _save_pending_result(message, update, context, parts[2], lang=lang)
        return
    if action == "saved_delete" and len(parts) >= 3:
        user_id = int(update.effective_user.id) if update.effective_user is not None else 0
        _delete_record(user_id, parts[2])
        await show_saved_models_menu(message, update, context, edit_existing=True, lang=lang)
        return
    await show_saved_models_menu(message, update, context, edit_existing=True, lang=lang)
