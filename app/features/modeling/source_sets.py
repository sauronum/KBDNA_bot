from __future__ import annotations

import html
import os
import re
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from app.features.modeling.navigation import nav_back_callback, nav_enter
from app.features.modeling.ui import footer_row as _footer_row
from app.features.modeling.ui import modeling_cb as _cb
from app.features.modeling.ui import page_nav_row
from app.features.modeling.ui import show_message as _show_message
from app.features.modeling.storage import read_record_list, write_record_list
from app.i18n import get_user_language
from app.main_menu import set_active_main_menu_message


QPADM_FLOW_KEY = "qpadm_classic_flow"
QPWAVE_FLOW_KEY = "qpwave_flow"
SOURCE_SET_FLOW_KEY = "source_set_flow"
SOURCE_SETS_PATH = Path(os.getenv("KBDNA_SOURCE_SETS_PATH", "/opt/kbdnabot/storage/modeling/source_sets.json"))
SOURCE_SET_PAGE_SIZE = 8

DATASET_LABELS = {
    "v62_1240k_public": "v62 1240k public",
    "human_origins": "Human Origins",
}
SOURCE_SET_PATTERN = re.compile(
    r"(?is)\b(name|title|left|sources?|right|references?|target)\s*[:=]\s*(.*?)(?=\b(?:name|title|left|sources?|right|references?|target)\s*[:=]|$)"
)

def _dataset_label(dataset: object) -> str:
    value = str(dataset or "")
    return DATASET_LABELS.get(value, value or "not selected")


def _clean_item(value: str) -> str:
    value = value.strip()
    value = re.sub(r"^[\s\-*•]+", "", value)
    value = re.sub(r"^\d+[\.)]\s*", "", value)
    return value.strip().strip(",;")


def _split_items(value: str) -> list[str]:
    raw_items = re.split(r"[\n,;]+", value)
    items: list[str] = []
    seen: set[str] = set()
    for raw in raw_items:
        item = _clean_item(raw)
        key = item.casefold()
        if not item or key in seen:
            continue
        seen.add(key)
        items.append(item)
    return items


def _safe_page(value: object) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _parse_source_set_import(value: str) -> dict[str, Any] | None:
    parsed: dict[str, Any] = {"name": None, "sources": [], "references": [], "target_ignored": None}
    for match in SOURCE_SET_PATTERN.finditer(value):
        key = match.group(1).lower()
        raw = match.group(2).strip()
        if not raw:
            continue
        if key in {"name", "title"}:
            parsed["name"] = raw.splitlines()[0].strip()[:80]
        elif key in {"left", "source", "sources"}:
            parsed["sources"] = _split_items(raw)
        elif key in {"right", "reference", "references"}:
            parsed["references"] = _split_items(raw)
        elif key == "target":
            items = _split_items(raw)
            parsed["target_ignored"] = items[0] if items else raw.splitlines()[0].strip()[:80]

    if not parsed["sources"] and not parsed["references"]:
        return None
    return parsed


def _default_set_name(dataset: str, sources: list[str], references: list[str]) -> str:
    first = sources[0] if sources else "Left/Right"
    stamp = time.strftime("%Y-%m-%d")
    return f"{first} · {len(sources)}L/{len(references)}R · {stamp}"


def _read_records() -> list[dict[str, Any]]:
    return read_record_list(SOURCE_SETS_PATH)


def _write_records(records: list[dict[str, Any]]) -> None:
    write_record_list(SOURCE_SETS_PATH, records)


def _user_records(user_id: int, *, dataset: str | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in _read_records():
        if int(item.get("owner_user_id") or 0) != int(user_id):
            continue
        if dataset is not None and str(item.get("dataset") or "") != dataset:
            continue
        rows.append(item)
    return sorted(rows, key=lambda item: str(item.get("created_at") or ""), reverse=True)


def _get_record(user_id: int, set_id: str) -> dict[str, Any] | None:
    for item in _read_records():
        if str(item.get("id") or "") == set_id and int(item.get("owner_user_id") or 0) == int(user_id):
            return item
    return None


def _save_record(user_id: int, *, dataset: str, name: str, sources: list[str], references: list[str]) -> dict[str, Any]:
    records = _read_records()
    item = {
        "id": uuid4().hex[:12],
        "owner_user_id": int(user_id),
        "dataset": dataset,
        "name": name.strip()[:80] or _default_set_name(dataset, sources, references),
        "sources": sources,
        "references": references,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    records.insert(0, item)
    _write_records(records)
    return item


def _delete_record(user_id: int, set_id: str) -> bool:
    records = _read_records()
    kept: list[dict[str, Any]] = []
    deleted = False
    for item in records:
        if str(item.get("id") or "") == set_id and int(item.get("owner_user_id") or 0) == int(user_id):
            deleted = True
            continue
        kept.append(item)
    if deleted:
        _write_records(kept)
    return deleted


def _qpadm_flow(context: ContextTypes.DEFAULT_TYPE) -> dict[str, Any] | None:
    flow = context.user_data.get(QPADM_FLOW_KEY)
    return flow if isinstance(flow, dict) else None


def _qpwave_flow(context: ContextTypes.DEFAULT_TYPE) -> dict[str, Any] | None:
    flow = context.user_data.get(QPWAVE_FLOW_KEY)
    return flow if isinstance(flow, dict) else None


def _as_list(flow: dict[str, Any], key: str) -> list[str]:
    value = flow.get(key)
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    return []


def _target_display(flow: dict[str, Any]) -> str:
    label = str(flow.get("target_label") or "").strip()
    if label:
        return label
    target = str(flow.get("target") or "").strip()
    if flow.get("target_type") == "raw_file" and target:
        return Path(target).name
    return target or "not selected"


def _preferred_model_order(context: ContextTypes.DEFAULT_TYPE) -> list[str]:
    current = str(context.user_data.get("modeling_nav_current") or "")
    if "qpadm" not in current and "qpwave" not in current:
        stack = context.user_data.get("modeling_nav_stack")
        if isinstance(stack, list):
            for item in reversed(stack):
                candidate = str(item or "")
                if "qpadm" in candidate or "qpwave" in candidate:
                    current = candidate
                    break
    return ["qpwave", "qpadm"] if "qpwave" in current else ["qpadm", "qpwave"]


def _preferred_apply_flow(context: ContextTypes.DEFAULT_TYPE) -> tuple[str, dict[str, Any]] | None:
    qpadm = _qpadm_flow(context)
    qpwave = _qpwave_flow(context)
    for kind in _preferred_model_order(context):
        flow = qpwave if kind == "qpwave" else qpadm
        if flow is None or not str(flow.get("dataset") or ""):
            continue
        if kind == "qpadm" and not flow.get("target"):
            continue
        return kind, flow
    return None


def _current_apply_dataset(context: ContextTypes.DEFAULT_TYPE) -> str | None:
    target = _preferred_apply_flow(context)
    if target is None:
        return None
    return str(target[1].get("dataset") or "") or None


def _apply_target_context(context: ContextTypes.DEFAULT_TYPE, item: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    target = _preferred_apply_flow(context)
    if target is None:
        return None
    kind, flow = target
    if str(flow.get("dataset") or "") != str(item.get("dataset") or ""):
        return None
    return kind, flow


def _active_model_context(context: ContextTypes.DEFAULT_TYPE) -> dict[str, Any] | None:
    qpadm = _qpadm_flow(context)
    qpwave = _qpwave_flow(context)
    flow_by_kind = {"qpadm": qpadm, "qpwave": qpwave}

    for kind in _preferred_model_order(context):
        flow = flow_by_kind[kind]
        if flow is None:
            continue
        if kind == "qpwave":
            sources = _as_list(flow, "left")
            references = _as_list(flow, "right")
            target = "qpWave"
            back_callback = _cb("qpwave_builder")
        else:
            sources = _as_list(flow, "sources")
            references = _as_list(flow, "references")
            target = _target_display(flow)
            back_callback = _cb("qpadm_review") if flow.get("target") else _cb("qpadm")
        dataset = str(flow.get("dataset") or "")
        if dataset and sources and references:
            return {
                "kind": kind,
                "dataset": dataset,
                "target": target,
                "sources": sources,
                "references": references,
                "back_callback": back_callback,
            }
    return None


def _state_lines(flow: dict[str, Any]) -> list[str]:
    sources = flow.get("sources") if isinstance(flow.get("sources"), list) else []
    references = flow.get("references") if isinstance(flow.get("references"), list) else []
    return [
        f"Dataset: <code>{html.escape(_dataset_label(flow.get('dataset')))}</code>",
        f"Target: <code>{html.escape(_target_display(flow))}</code>",
        f"Sources: <code>{len(sources)}</code>",
        f"References: <code>{len(references)}</code>",
    ]


def _source_set_summary(item: dict[str, Any]) -> list[str]:
    sources = item.get("sources") if isinstance(item.get("sources"), list) else []
    references = item.get("references") if isinstance(item.get("references"), list) else []
    return [
        f"Dataset: <code>{html.escape(_dataset_label(item.get('dataset')))}</code>",
        f"Sources: <code>{len(sources)}</code>",
        f"References: <code>{len(references)}</code>",
    ]


async def show_source_sets_menu(
    message,
    update: Update | None,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    edit_existing: bool = True,
    lang: str = "ru",
) -> None:
    user_id = int(update.effective_user.id) if update is not None and update.effective_user is not None else 0
    count = len(_user_records(user_id))
    apply_dataset = _current_apply_dataset(context)
    active_model = _active_model_context(context)
    nav_enter(context, _cb("source_sets"))
    rows: list[list[InlineKeyboardButton]] = []
    if apply_dataset:
        rows.append([InlineKeyboardButton("📚 Выбрать для текущей модели", callback_data=_cb("ss_pick"))])
    if active_model is not None:
        rows.append([InlineKeyboardButton("💾 Сохранить текущий Left/Right", callback_data=_cb("ss_save_current"))])
    rows.extend(
        [
            [InlineKeyboardButton("➕ Создать вручную", callback_data=_cb("ss_new"))],
            [InlineKeyboardButton(f"📁 Мои наборы ({count})", callback_data=_cb("ss_list"))],
            _footer_row(nav_back_callback(), lang),
        ]
    )
    text = "\n".join(
        [
            "<b>📚 Source sets</b>",
            "",
            "Сохраненные Left/Right-наборы без target.",
            "Их можно применять к любому sample или population в том же dataset.",
        ]
    )
    await _show_message(message, text, InlineKeyboardMarkup(rows), edit_existing=edit_existing)


async def _show_dataset_picker(message, context: ContextTypes.DEFAULT_TYPE, *, lang: str) -> None:
    nav_enter(context, _cb("ss_new"))
    text = "\n".join(
        [
            "<b>➕ Новый Source set</b>",
            "",
            "Выберите dataset для набора.",
        ]
    )
    markup = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("v62 / 1240k public", callback_data=_cb("ss_new_ds", "v62_1240k_public"))],
            [InlineKeyboardButton("Human Origins", callback_data=_cb("ss_new_ds", "human_origins"))],
            _footer_row(nav_back_callback(), lang),
        ]
    )
    await _show_message(message, text, markup, edit_existing=True)


async def _start_import_prompt(message, context: ContextTypes.DEFAULT_TYPE, dataset: str, *, lang: str) -> None:
    context.user_data[SOURCE_SET_FLOW_KEY] = {
        "awaiting": "import",
        "dataset": dataset,
        "chat_id": int(message.chat_id),
        "prompt_chat_id": int(message.chat_id),
        "prompt_message_id": int(message.message_id),
    }
    text = "\n".join(
        [
            "<b>➕ Новый Source set</b>",
            "",
            f"Dataset: <code>{html.escape(_dataset_label(dataset))}</code>",
            "",
            "Вставьте Left/Right. Можно добавить строку Name=.",
            "",
            "<code>Name=Caucasus 4-way</code>",
            "<code>Left=Source1,Source2</code>",
            "<code>Right=Ref1,Ref2</code>",
        ]
    )
    await _show_message(message, text, InlineKeyboardMarkup([_footer_row(_cb("source_sets"), lang)]), edit_existing=True)


async def _show_list(
    message,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    dataset: str | None = None,
    apply_mode: bool = False,
    page: int = 0,
    lang: str,
) -> None:
    user_id = int(update.effective_user.id) if update.effective_user is not None else 0
    page_action = "ss_pick_page" if apply_mode else "ss_list_page"
    nav_enter(context, _cb(page_action, page))
    rows = _user_records(user_id, dataset=dataset)
    title = "📚 Выбор Source set" if apply_mode else "📁 Мои Source sets"
    lines = [f"<b>{title}</b>"]
    if dataset:
        lines.extend(["", f"Dataset: <code>{html.escape(_dataset_label(dataset))}</code>"])

    buttons: list[list[InlineKeyboardButton]] = []
    if not rows:
        lines.extend(["", "Пока нет сохраненных наборов."])
        buttons.append([InlineKeyboardButton("➕ Создать вручную", callback_data=_cb("ss_new"))])
    else:
        page_count = max(1, (len(rows) + SOURCE_SET_PAGE_SIZE - 1) // SOURCE_SET_PAGE_SIZE)
        page = min(max(0, page), page_count - 1)
        start = page * SOURCE_SET_PAGE_SIZE
        end = min(len(rows), start + SOURCE_SET_PAGE_SIZE)
        rows = rows[start:end]
        lines.extend(["", "Выберите набор:"])
        for item in rows:
            sources = item.get("sources") if isinstance(item.get("sources"), list) else []
            references = item.get("references") if isinstance(item.get("references"), list) else []
            label = f"{str(item.get('name') or 'Source set')[:32]} · {len(sources)}L/{len(references)}R"
            action = "ss_apply" if apply_mode else "ss_view"
            buttons.append([InlineKeyboardButton(label, callback_data=_cb(action, item.get("id")))])
        if page_count > 1:
            buttons.append(page_nav_row(page, page_count, lambda value: _cb(page_action, value)))
    buttons.append(_footer_row(nav_back_callback(), lang))
    await _show_message(message, "\n".join(lines), InlineKeyboardMarkup(buttons), edit_existing=True)


async def _show_view(message, update: Update, context: ContextTypes.DEFAULT_TYPE, set_id: str, *, lang: str) -> None:
    user_id = int(update.effective_user.id) if update.effective_user is not None else 0
    item = _get_record(user_id, set_id)
    if item is None:
        await _show_list(message, update, context, lang=lang)
        return
    nav_enter(context, _cb("ss_view", set_id))
    sources = item.get("sources") if isinstance(item.get("sources"), list) else []
    references = item.get("references") if isinstance(item.get("references"), list) else []
    compatible = _apply_target_context(context, item) is not None
    lines = [
        f"<b>📚 {html.escape(str(item.get('name') or 'Source set'))}</b>",
        "",
        *_source_set_summary(item),
        "",
        "<b>Sources</b>",
        *[f"• <code>{html.escape(str(value))}</code>" for value in sources],
    ]
    lines.extend(["", "<b>References</b>"])
    lines.extend([f"• <code>{html.escape(str(value))}</code>" for value in references])

    buttons: list[list[InlineKeyboardButton]] = []
    if compatible:
        buttons.append([InlineKeyboardButton("✅ Применить к текущей модели", callback_data=_cb("ss_apply", set_id))])
    buttons.append([InlineKeyboardButton("Удалить", callback_data=_cb("ss_delete", set_id))])
    buttons.append(_footer_row(nav_back_callback(), lang))
    await _show_message(message, "\n".join(lines), InlineKeyboardMarkup(buttons), edit_existing=True)


async def _apply_to_current_model(message, update: Update, context: ContextTypes.DEFAULT_TYPE, set_id: str, *, lang: str) -> None:
    user_id = int(update.effective_user.id) if update.effective_user is not None else 0
    item = _get_record(user_id, set_id)
    if item is None:
        await _show_list(message, update, context, lang=lang)
        return

    target = _preferred_apply_flow(context)
    if target is None:
        text = "<b>📚 Source set</b>\n\nСначала откройте qpAdm classic или qpWave и выберите dataset."
        await _show_message(message, text, InlineKeyboardMarkup([_footer_row(_cb("source_sets"), lang)]), edit_existing=True)
        return

    kind, flow = target
    if str(flow.get("dataset") or "") != str(item.get("dataset") or ""):
        text = "\n".join(
            [
                "<b>📚 Source set</b>",
                "",
                f"Dataset модели: <code>{html.escape(_dataset_label(flow.get('dataset')))}</code>",
                f"Dataset набора: <code>{html.escape(_dataset_label(item.get('dataset')))}</code>",
                "",
                "Набор можно применить только к модели в том же dataset.",
            ]
        )
        await _show_message(message, text, InlineKeyboardMarkup([_footer_row(_cb("ss_list"), lang)]), edit_existing=True)
        return

    if kind == "qpwave":
        flow["left"] = [str(value) for value in item.get("sources", []) if str(value)]
        flow["right"] = [str(value) for value in item.get("references", []) if str(value)]
        from app.features.modeling.qpwave import _show_builder

        await _show_builder(message, context, edit_existing=True, lang=lang)
        return

    flow["sources"] = [str(value) for value in item.get("sources", []) if str(value)]
    flow["references"] = [str(value) for value in item.get("references", []) if str(value)]
    from app.features.modeling.qpadm_classic import _show_review_menu

    await _show_review_menu(message, context, edit_existing=True, lang=lang)


async def _save_current_model_set(message, update: Update, context: ContextTypes.DEFAULT_TYPE, *, lang: str) -> None:
    model = _active_model_context(context)
    if model is None:
        text = "<b>📚 Source set</b>\n\nСначала соберите полный Left/Right-набор."
        await _show_message(message, text, InlineKeyboardMarkup([_footer_row(_cb("source_sets"), lang)]), edit_existing=True)
        return

    user_id = int(update.effective_user.id) if update.effective_user is not None else 0
    sources = [str(value) for value in model["sources"] if str(value)]
    references = [str(value) for value in model["references"] if str(value)]
    target = str(model.get("target") or "").strip()
    dataset = str(model.get("dataset") or "")
    name = f"{target} · {len(sources)}L/{len(references)}R · {time.strftime('%Y-%m-%d')}" if target else _default_set_name(dataset, sources, references)
    item = _save_record(user_id, dataset=dataset, name=name, sources=sources, references=references)

    lines = [
        "<b>📚 Source set сохранен</b>",
        "",
        f"Название: <code>{html.escape(str(item.get('name')))}</code>",
        *_source_set_summary(item),
    ]
    markup = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Открыть набор", callback_data=_cb("ss_view", item.get("id")))],
            [InlineKeyboardButton("Мои наборы", callback_data=_cb("ss_list"))],
            _footer_row(str(model.get("back_callback") or _cb("source_sets")), lang),
        ]
    )
    await _show_message(message, "\n".join(lines), markup, edit_existing=True)


async def source_sets_text_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if update.message is None or update.message.text is None:
        return False
    flow = context.user_data.get(SOURCE_SET_FLOW_KEY)
    if not isinstance(flow, dict) or flow.get("awaiting") != "import":
        return False
    if int(flow.get("chat_id") or 0) != int(update.message.chat_id):
        return False

    lang = get_user_language(context, int(update.effective_user.id) if update.effective_user is not None else None)
    progress = await update.message.reply_text("Сохраняю Source set...", do_quote=False)
    if update.effective_chat is not None and update.effective_user is not None:
        set_active_main_menu_message(context, update.effective_chat.id, update.effective_user.id, progress.message_id)
    await _deactivate_prompt_markup(context, flow, progress.message_id)

    parsed = _parse_source_set_import(update.message.text.strip())
    if parsed is None:
        context.user_data.pop(SOURCE_SET_FLOW_KEY, None)
        text = "<b>Source set не сохранен</b>\n\nНе вижу <code>Left=</code> или <code>Right=</code>."
        await progress.edit_text(text, reply_markup=InlineKeyboardMarkup([_footer_row(_cb("source_sets"), lang)]), parse_mode="HTML")
        return True

    dataset = str(flow.get("dataset") or "")
    sources = [str(value) for value in parsed.get("sources", []) if str(value)]
    references = [str(value) for value in parsed.get("references", []) if str(value)]
    name = str(parsed.get("name") or _default_set_name(dataset, sources, references))
    user_id = int(update.effective_user.id) if update.effective_user is not None else 0
    item = _save_record(user_id, dataset=dataset, name=name, sources=sources, references=references)
    context.user_data.pop(SOURCE_SET_FLOW_KEY, None)

    lines = [
        "<b>📚 Source set сохранен</b>",
        "",
        f"Название: <code>{html.escape(str(item.get('name')))}</code>",
        *_source_set_summary(item),
    ]
    if parsed.get("target_ignored"):
        lines.extend(["", f"Target проигнорирован: <code>{html.escape(str(parsed['target_ignored']))}</code>"])
    markup = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Открыть набор", callback_data=_cb("ss_view", item.get("id")))],
            [InlineKeyboardButton("Мои наборы", callback_data=_cb("ss_list"))],
            _footer_row(_cb("source_sets"), lang),
        ]
    )
    await progress.edit_text("\n".join(lines), reply_markup=markup, parse_mode="HTML")
    return True


async def source_sets_callback_handler(
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

    if action == "source_sets":
        await show_source_sets_menu(message, update, context, edit_existing=True, lang=lang)
        return
    if action == "ss_new":
        await _show_dataset_picker(message, context, lang=lang)
        return
    if action == "ss_new_ds" and len(parts) >= 3:
        dataset = parts[2]
        if dataset not in DATASET_LABELS:
            await _show_dataset_picker(message, context, lang=lang)
            return
        await _start_import_prompt(message, context, dataset, lang=lang)
        return
    if action == "ss_list":
        await _show_list(message, update, context, lang=lang)
        return
    if action == "ss_list_page" and len(parts) >= 3:
        await _show_list(message, update, context, page=_safe_page(parts[2]), lang=lang)
        return
    if action == "ss_pick":
        dataset = _current_apply_dataset(context)
        await _show_list(message, update, context, dataset=dataset, apply_mode=True, lang=lang)
        return
    if action == "ss_pick_page" and len(parts) >= 3:
        dataset = _current_apply_dataset(context)
        await _show_list(message, update, context, dataset=dataset, apply_mode=True, page=_safe_page(parts[2]), lang=lang)
        return
    if action == "ss_view" and len(parts) >= 3:
        await _show_view(message, update, context, parts[2], lang=lang)
        return
    if action == "ss_apply" and len(parts) >= 3:
        await _apply_to_current_model(message, update, context, parts[2], lang=lang)
        return
    if action == "ss_save_current":
        await _save_current_model_set(message, update, context, lang=lang)
        return
    if action == "ss_delete" and len(parts) >= 3:
        user_id = int(update.effective_user.id) if update.effective_user is not None else 0
        _delete_record(user_id, parts[2])
        await _show_list(message, update, context, lang=lang)
        return
    await show_source_sets_menu(message, update, context, edit_existing=True, lang=lang)


async def _deactivate_prompt_markup(
    context: ContextTypes.DEFAULT_TYPE,
    flow: dict[str, Any],
    active_message_id: int,
) -> None:
    chat_id = flow.get("prompt_chat_id")
    message_id = flow.get("prompt_message_id")
    if chat_id is None or message_id is None or int(message_id) == int(active_message_id):
        return
    try:
        await context.bot.edit_message_reply_markup(
            chat_id=int(chat_id),
            message_id=int(message_id),
            reply_markup=None,
        )
    except BadRequest:
        return
