from __future__ import annotations

import asyncio
import html
import json
import os
import re
import time
from pathlib import Path
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from app.features.modeling.navigation import (
    nav_back_callback,
    nav_enter,
    nav_reset,
)
from app.features.modeling.datasets import DATASET_LABELS, dataset_choices, dataset_label
from app.features.modeling.admixtools2 import _dataset_files as _at2_dataset_files
from app.features.modeling.admixtools2 import run_admixtools2_runner
from app.features.modeling.saved_models import register_pending_save
from app.features.modeling.source_sets import _dataset_matches
from app.features.modeling.source_sets import _dataset_mismatch_lines
from app.features.modeling.source_sets import _get_record as _get_source_set
from app.features.modeling.source_sets import _record_dataset_label
from app.features.modeling.source_sets import _user_records as _user_source_sets
from app.features.modeling.ui import footer_row as _footer_row
from app.features.modeling.ui import modeling_cb as _cb
from app.features.modeling.ui import page_nav_row
from app.features.modeling.ui import show_message as _show_message
from app.features.modeling.visuals import render_qpwave_result
from app.heavy_runtime import heavy_command
from app.i18n import get_user_language
from app.main_menu import set_active_main_menu_message


QPWAVE_FLOW_KEY = "qpwave_flow"
QPWAVE_QUEUE_KEY = "qpwave_queue"
QPWAVE_ENGINE_CLASSIC = "classic_qpwave"
QPWAVE_ENGINE_ADMIXTOOLS2 = "admixtools2_qpwave"

DNA_PLATFORM_ROOT = Path(os.getenv("DNA_PLATFORM_ROOT", "/srv/dna_platform"))
DNA_PLATFORM_PYTHON = os.getenv("DNA_PLATFORM_PYTHON", "python3")
ADMIXLAB_BIN_DIR = Path(os.getenv("ADMIXLAB_BIN_DIR", "/srv/dna_platform/tools/admixtools/bin"))
QPWAVE_EXECUTABLE = Path(os.getenv("QPWAVE_EXECUTABLE", str(ADMIXLAB_BIN_DIR / "qpWave")))
BOT_QPWAVE_OUTPUT_DIR = Path(
    os.getenv("KBDNA_QPWAVE_OUTPUT_DIR", str(DNA_PLATFORM_ROOT / "output" / "admixlab" / "bot" / "qpwave"))
)
QPWAVE_TIMEOUT_SECONDS = int(os.getenv("KBDNA_QPWAVE_TIMEOUT_SECONDS", "7200"))
QPWAVE_SEARCH_TIMEOUT_SECONDS = int(os.getenv("KBDNA_QPWAVE_SEARCH_TIMEOUT_SECONDS", "60"))
QPWAVE_MAX_CONCURRENT_JOBS = int(os.getenv("KBDNA_QPWAVE_MAX_CONCURRENT_JOBS", "3"))
QPWAVE_SOURCE_SET_PAGE_SIZE = 8

DATASET_FILES = {
    "v62_1240k_public": {
        "geno": "/data/admixlab/v62.0_1240k_public/v62.0_1240k_public.geno",
        "snp": "/data/admixlab/v62.0_1240k_public/v62.0_1240k_public.snp",
        "ind": "/data/admixlab/v62.0_1240k_public/v62.0_1240k_public.ind",
    },
    "human_origins": {
        "geno": "/data/admixlab/human_origins/human_origins.geno",
        "snp": "/data/admixlab/human_origins/human_origins.snp",
        "ind": "/data/admixlab/human_origins/human_origins.ind",
    },
    "v66p1_1240k_public": {
        "geno": "/data/admixlab/v66.p1_1240k_public/v66.p1_1240K.aadr.patch.PUB.geno",
        "snp": "/data/admixlab/v66.p1_1240k_public/v66.p1_1240K.aadr.patch.PUB.snp",
        "ind": "/data/admixlab/v66.p1_1240k_public/v66.p1_1240K.aadr.patch.PUB.ind",
    },
    "v66p1_human_origins": {
        "geno": "/data/admixlab/v66.p1_human_origins/v66.p1_HO.aadr.patch.PUB.geno",
        "snp": "/data/admixlab/v66.p1_human_origins/v66.p1_HO.aadr.patch.PUB.snp",
        "ind": "/data/admixlab/v66.p1_human_origins/v66.p1_HO.aadr.patch.PUB.ind",
    },
}
ROLE_LABELS_RU = {
    "left": "Left",
    "right": "Right",
    "import": "Left/Right",
}
MODEL_IMPORT_PATTERN = re.compile(
    r"(?is)\b(left|sources?|right|references?|target|name|title)\s*[:=]\s*(.*?)(?=\b(?:left|sources?|right|references?|target|name|title)\s*[:=]|$)"
)
RANK_PATTERN = re.compile(
    r"f4rank:\s*(?P<rank>\d+)\s+dof:\s*(?P<dof>[-+0-9.eE]+)\s+chisq:\s*(?P<chisq>[-+0-9.eE]+)\s+tail:\s*(?P<tail>[-+0-9.eE]+)"
)

def _dataset_label(dataset: object) -> str:
    return dataset_label(dataset)


def _get_flow(context: ContextTypes.DEFAULT_TYPE) -> dict[str, Any] | None:
    flow = context.user_data.get(QPWAVE_FLOW_KEY)
    return flow if isinstance(flow, dict) else None


def _qpwave_engine(value: object) -> str:
    return QPWAVE_ENGINE_ADMIXTOOLS2 if str(value) in {"admixtools2", QPWAVE_ENGINE_ADMIXTOOLS2} else QPWAVE_ENGINE_CLASSIC


def _is_admixtools2_engine(value: object) -> bool:
    return _qpwave_engine(value) == QPWAVE_ENGINE_ADMIXTOOLS2


def _qpwave_title(flow_or_engine: object = None, *, suffix: str | None = None) -> str:
    engine = flow_or_engine.get("engine") if isinstance(flow_or_engine, dict) else flow_or_engine
    title = "〰️ ADMIXTOOLS2 qpWave" if _is_admixtools2_engine(engine) else "🌊 qpWave classic"
    return f"{title} · {suffix}" if suffix else title


def _start_flow(context: ContextTypes.DEFAULT_TYPE, dataset: str, *, engine: object = QPWAVE_ENGINE_CLASSIC) -> dict[str, Any]:
    flow: dict[str, Any] = {
        "dataset": dataset,
        "engine": _qpwave_engine(engine),
        "left": [],
        "right": [],
        "search_results": [],
        "search_role": None,
        "awaiting_query": None,
        "awaiting_chat_id": None,
    }
    context.user_data[QPWAVE_FLOW_KEY] = flow
    return flow


def _snapshot_flow(flow: dict[str, Any]) -> dict[str, Any]:
    return {
        "dataset": flow.get("dataset"),
        "engine": _qpwave_engine(flow.get("engine")),
        "left": _as_list(flow, "left"),
        "right": _as_list(flow, "right"),
    }


def _as_list(flow: dict[str, Any], key: str) -> list[str]:
    value = flow.get(key)
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    return []


def _has_complete_model(flow: dict[str, Any]) -> bool:
    return bool(_as_list(flow, "left") and _as_list(flow, "right"))


def _safe_page(value: object) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _state_lines(flow: dict[str, Any]) -> list[str]:
    return [
        f"Dataset: <code>{html.escape(_dataset_label(flow.get('dataset')))}</code>",
        f"Left: <code>{len(_as_list(flow, 'left'))}</code>",
        f"Right: <code>{len(_as_list(flow, 'right'))}</code>",
    ]


def _clip(value: object, limit: int = 48) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)] + "..."


def _format_number(value: object) -> str:
    if value is None:
        return "n/a"
    try:
        text = f"{float(value):.3f}".rstrip("0").rstrip(".")
        return "0" if text == "-0" else text
    except (TypeError, ValueError):
        return html.escape(str(value))


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


def _looks_like_item_list(value: str) -> bool:
    return "\n" in value or "," in value or ";" in value


def _parse_left_right(value: str) -> dict[str, Any] | None:
    parsed: dict[str, Any] = {"left": [], "right": [], "target_ignored": None}
    for match in MODEL_IMPORT_PATTERN.finditer(value):
        key = match.group(1).lower()
        raw = match.group(2).strip()
        if not raw:
            continue
        if key in {"left", "source", "sources"}:
            parsed["left"] = _split_items(raw)
        elif key in {"right", "reference", "references"}:
            parsed["right"] = _split_items(raw)
        elif key == "target":
            items = _split_items(raw)
            parsed["target_ignored"] = items[0] if items else raw.splitlines()[0].strip()[:80]
    if not parsed["left"] and not parsed["right"]:
        return None
    return parsed


def _merge_role_items(flow: dict[str, Any], role: str, items: list[str], *, replace: bool = False) -> dict[str, Any]:
    key = "left" if role == "left" else "right"
    other_key = "right" if key == "left" else "left"
    existing = [] if replace else _as_list(flow, key)
    other = {item.casefold() for item in _as_list(flow, other_key)}
    existing_keys = {item.casefold() for item in existing}
    added: list[str] = []
    skipped: list[str] = []
    for item in items:
        clean = _clean_item(item)
        normalized = clean.casefold()
        if not clean:
            continue
        if normalized in existing_keys or normalized in other:
            skipped.append(clean)
            continue
        existing.append(clean)
        existing_keys.add(normalized)
        added.append(clean)
    flow[key] = existing
    return {"role": role, "added": added, "skipped": skipped}


def _apply_left_right(flow: dict[str, Any], value: str) -> dict[str, Any] | None:
    parsed = _parse_left_right(value)
    if parsed is None:
        return None
    result = {"left": [], "right": [], "skipped": [], "target_ignored": parsed.get("target_ignored")}
    if parsed["left"]:
        flow["left"] = []
        left_result = _merge_role_items(flow, "left", parsed["left"], replace=True)
        result["left"] = left_result["added"]
        result["skipped"].extend(left_result["skipped"])
    if parsed["right"]:
        flow["right"] = []
        right_result = _merge_role_items(flow, "right", parsed["right"], replace=True)
        result["right"] = right_result["added"]
        result["skipped"].extend(right_result["skipped"])
    _clear_search(flow)
    return result


def _clear_search(flow: dict[str, Any]) -> None:
    flow["search_results"] = []
    flow["search_role"] = None
    flow["awaiting_query"] = None
    flow["awaiting_chat_id"] = None
    flow.pop("prompt_chat_id", None)
    flow.pop("prompt_message_id", None)


def _env() -> dict[str, str]:
    env = os.environ.copy()
    env["PATH"] = f"{ADMIXLAB_BIN_DIR}:{env.get('PATH', '')}"
    return env


async def _run_process(args: list[str], *, cwd: Path, timeout_seconds: int) -> str:
    proc = await asyncio.create_subprocess_exec(
        *heavy_command(args),
        cwd=str(cwd),
        env=_env(),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        raise RuntimeError("qpWave timed out")

    stdout = stdout_bytes.decode("utf-8", errors="replace")
    stderr = stderr_bytes.decode("utf-8", errors="replace")
    if proc.returncode != 0:
        detail = (stderr or stdout).strip().splitlines()[-12:]
        raise RuntimeError("\n".join(detail) or f"qpWave failed with exit code {proc.returncode}")
    return stdout


async def show_qpwave_dataset_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE | None = None,
    *,
    engine: object = QPWAVE_ENGINE_CLASSIC,
    edit_existing: bool = True,
    lang: str = "ru",
) -> None:
    selected_engine = _qpwave_engine(engine)
    if context is not None:
        context.user_data.pop(QPWAVE_FLOW_KEY, None)
        nav_enter(context, _cb("qpwave_engine", selected_engine))
    text = "\n".join(
        [
            f"<b>{html.escape(_qpwave_title(selected_engine))}</b>",
            "",
            "Выберите базу. Затем соберем Left и Right и проверим число потоков происхождения.",
        ]
    )
    markup = InlineKeyboardMarkup(
        [
            *[
                [InlineKeyboardButton(label, callback_data=_cb("qpwave_ds", selected_engine, dataset))]
                for dataset, label in dataset_choices()
            ],
            _footer_row(nav_back_callback(), lang),
        ]
    )
    await _show_message(message, text, markup, edit_existing=edit_existing)


async def show_qpwave_admixtools2_dataset_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE | None = None,
    *,
    edit_existing: bool = True,
    lang: str = "ru",
) -> None:
    await show_qpwave_dataset_menu(
        message,
        context,
        engine=QPWAVE_ENGINE_ADMIXTOOLS2,
        edit_existing=edit_existing,
        lang=lang,
    )


async def _show_builder(message, context: ContextTypes.DEFAULT_TYPE, *, edit_existing: bool = True, lang: str) -> None:
    flow = _get_flow(context)
    if flow is None:
        await show_qpwave_dataset_menu(message, context, edit_existing=edit_existing, lang=lang)
        return
    nav_enter(context, _cb("qpwave_builder"))
    left = _as_list(flow, "left")
    right = _as_list(flow, "right")
    run_label = "〰️ Запустить qpWave 2" if _is_admixtools2_engine(flow.get("engine")) else "🌊 Запустить qpWave"
    rows: list[list[InlineKeyboardButton]] = []
    if left and right:
        rows.extend(
            [
                [InlineKeyboardButton(run_label, callback_data=_cb("qpwave_run"))],
                [
                    InlineKeyboardButton("Left", callback_data=_cb("qpwave_left")),
                    InlineKeyboardButton("Right", callback_data=_cb("qpwave_right")),
                ],
                [InlineKeyboardButton("💾 Сохранить Source set", callback_data=_cb("ss_save_current"))],
                [InlineKeyboardButton("Заменить Left/Right", callback_data=_cb("qpwave_clear_lr"))],
            ]
        )
        hint = "Модель собрана. Запустите qpWave или отредактируйте отдельные части."
    elif left:
        rows.extend(
            [
                [InlineKeyboardButton("Right", callback_data=_cb("qpwave_right"))],
                [InlineKeyboardButton("Left", callback_data=_cb("qpwave_left"))],
                [InlineKeyboardButton("📚 Выбрать Source set", callback_data=_cb("qpwave_sets"))],
                [InlineKeyboardButton("📋 Импорт Left/Right", callback_data=_cb("qpwave_import"))],
            ]
        )
        hint = "Left добавлен. Теперь добавьте Right или замените Left/Right целиком."
    elif right:
        rows.extend(
            [
                [InlineKeyboardButton("Left", callback_data=_cb("qpwave_left"))],
                [InlineKeyboardButton("Right", callback_data=_cb("qpwave_right"))],
                [InlineKeyboardButton("📚 Выбрать Source set", callback_data=_cb("qpwave_sets"))],
                [InlineKeyboardButton("📋 Импорт Left/Right", callback_data=_cb("qpwave_import"))],
            ]
        )
        hint = "Right добавлен. Теперь добавьте Left или замените Left/Right целиком."
    else:
        rows.extend(
            [
                [InlineKeyboardButton("📚 Выбрать Source set", callback_data=_cb("qpwave_sets"))],
                [InlineKeyboardButton("📋 Импорт Left/Right", callback_data=_cb("qpwave_import"))],
                [
                    InlineKeyboardButton("Left", callback_data=_cb("qpwave_left")),
                    InlineKeyboardButton("Right", callback_data=_cb("qpwave_right")),
                ],
            ]
        )
        hint = "Добавьте Left и Right: через Source set, импорт или вручную."
    rows.append([InlineKeyboardButton("Начать заново", callback_data=_cb("qpwave_reset"))])
    rows.append(_footer_row(nav_back_callback(), lang))
    text = "\n".join(
        [
            f"<b>{html.escape(_qpwave_title(flow, suffix='модель'))}</b>",
            "",
            *_state_lines(flow),
            "",
            hint,
        ]
    )
    await _show_message(message, text, InlineKeyboardMarkup(rows), edit_existing=edit_existing)


async def _clear_left_right(message, context: ContextTypes.DEFAULT_TYPE, *, lang: str) -> None:
    flow = _get_flow(context)
    if flow is None:
        await show_qpwave_dataset_menu(message, context, edit_existing=True, lang=lang)
        return
    flow["left"] = []
    flow["right"] = []
    _clear_search(flow)
    await _show_builder(message, context, edit_existing=True, lang=lang)


def _items_lines(title: str, items: list[str], *, limit: int = 10) -> list[str]:
    if not items:
        return [f"<b>{title}</b>", "none"]
    lines = [f"<b>{title}</b>"]
    for item in items:
        lines.append(f"• <code>{html.escape(item)}</code>")
    return lines


async def _show_role_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    role: str,
    *,
    edit_existing: bool = True,
    lang: str,
) -> None:
    flow = _get_flow(context)
    if flow is None:
        await show_qpwave_dataset_menu(message, context, edit_existing=edit_existing, lang=lang)
        return
    nav_enter(context, _cb(f"qpwave_{role}"))
    items = _as_list(flow, role)
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(f"🔎 Добавить {ROLE_LABELS_RU[role]}", callback_data=_cb("qpwave_search", role))],
    ]
    for index, item in enumerate(items):
        rows.append([InlineKeyboardButton(f"✕ {_clip(item, 38)}", callback_data=_cb("qpwave_del", role, index))])
    rows.append([InlineKeyboardButton("Готово", callback_data=_cb("qpwave_builder"))])
    rows.append(_footer_row(nav_back_callback(), lang))
    text = "\n".join(
        [
            f"<b>{html.escape(_qpwave_title(flow, suffix=ROLE_LABELS_RU[role]))}</b>",
            "",
            *_state_lines(flow),
            "",
            *_items_lines(ROLE_LABELS_RU[role], items),
            "",
            "Можно вставить список строками или через запятую.",
        ]
    )
    await _show_message(message, text, InlineKeyboardMarkup(rows), edit_existing=edit_existing)


async def _start_import(message, context: ContextTypes.DEFAULT_TYPE, *, lang: str) -> None:
    flow = _get_flow(context)
    if flow is None:
        await show_qpwave_dataset_menu(message, context, edit_existing=True, lang=lang)
        return
    nav_enter(context, _cb("qpwave_import"))
    _clear_search(flow)
    flow["awaiting_query"] = "import"
    flow["awaiting_chat_id"] = int(message.chat_id)
    flow["prompt_chat_id"] = int(message.chat_id)
    flow["prompt_message_id"] = int(message.message_id)
    text = "\n".join(
        [
            f"<b>📋 {html.escape(_qpwave_title(flow, suffix='импорт Left/Right'))}</b>",
            "",
            f"Dataset: <code>{html.escape(_dataset_label(flow.get('dataset')))}</code>",
            "",
            "<code>Left=Pop1,Pop2</code>",
            "<code>Right=Ref1,Ref2</code>",
        ]
    )
    await _show_message(message, text, InlineKeyboardMarkup([_footer_row(_cb("qpwave_builder"), lang)]), edit_existing=True)


async def _start_search(message, context: ContextTypes.DEFAULT_TYPE, role: str, *, lang: str) -> None:
    flow = _get_flow(context)
    if flow is None:
        await show_qpwave_dataset_menu(message, context, edit_existing=True, lang=lang)
        return
    _clear_search(flow)
    flow["awaiting_query"] = role
    flow["awaiting_chat_id"] = int(message.chat_id)
    flow["prompt_chat_id"] = int(message.chat_id)
    flow["prompt_message_id"] = int(message.message_id)
    text = "\n".join(
        [
            f"<b>🔎 {html.escape(_qpwave_title(flow, suffix='поиск ' + ROLE_LABELS_RU[role]))}</b>",
            "",
            f"Dataset: <code>{html.escape(_dataset_label(flow.get('dataset')))}</code>",
            "",
            "Напишите часть названия population одним сообщением.",
            "Можно вставить сразу список: строками или через запятую.",
        ]
    )
    await _show_message(message, text, InlineKeyboardMarkup([_footer_row(_cb(f"qpwave_{role}"), lang)]), edit_existing=True)


async def qpwave_text_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if update.message is None or update.message.text is None:
        return False
    flow = _get_flow(context)
    if flow is None:
        return False
    role = flow.get("awaiting_query")
    if role not in {"left", "right", "import"}:
        return False
    if int(flow.get("awaiting_chat_id") or 0) != int(update.message.chat_id):
        return False

    text_value = update.message.text.strip()
    if not text_value:
        return True
    lang = get_user_language(context, int(update.effective_user.id) if update.effective_user is not None else None)

    if role == "import":
        progress = await update.message.reply_text("Импортирую Left/Right...", do_quote=False)
        if update.effective_chat is not None and update.effective_user is not None:
            set_active_main_menu_message(context, update.effective_chat.id, update.effective_user.id, progress.message_id)
        await _deactivate_prompt_markup(context, flow, progress.message_id)
        result = _apply_left_right(flow, text_value)
        if result is None:
            _clear_search(flow)
            await progress.edit_text(
                f"<b>{html.escape(_qpwave_title(flow))}</b>\n\nНе вижу <code>Left=</code> или <code>Right=</code>.",
                reply_markup=InlineKeyboardMarkup([_footer_row(_cb("qpwave_builder"), lang)]),
                parse_mode="HTML",
            )
            return True
        await _show_builder(progress, context, edit_existing=True, lang=lang)
        return True

    if role in {"left", "right"} and _looks_like_item_list(text_value):
        progress = await update.message.reply_text("Добавляю список...", do_quote=False)
        if update.effective_chat is not None and update.effective_user is not None:
            set_active_main_menu_message(context, update.effective_chat.id, update.effective_user.id, progress.message_id)
        await _deactivate_prompt_markup(context, flow, progress.message_id)
        _merge_role_items(flow, str(role), _split_items(text_value))
        _clear_search(flow)
        if _has_complete_model(flow):
            await _show_builder(progress, context, edit_existing=True, lang=lang)
        else:
            await _show_role_menu(progress, context, str(role), edit_existing=True, lang=lang)
        return True

    progress = await update.message.reply_text("Ищу populations...", do_quote=False)
    if update.effective_chat is not None and update.effective_user is not None:
        set_active_main_menu_message(context, update.effective_chat.id, update.effective_user.id, progress.message_id)
    await _deactivate_prompt_markup(context, flow, progress.message_id)
    try:
        results = await _list_populations(str(flow.get("dataset")), text_value)
        flow["search_results"] = results
        flow["search_role"] = role
        flow["awaiting_query"] = None
        flow["awaiting_chat_id"] = None
        text = _search_results_text(flow, text_value, results, str(role))
        await progress.edit_text(text, reply_markup=_search_results_keyboard(results, str(role), lang=lang), parse_mode="HTML")
    except Exception as exc:
        _clear_search(flow)
        await progress.edit_text(
            f"<b>Поиск не прошел</b>\n\n<code>{html.escape(str(exc))}</code>",
            reply_markup=InlineKeyboardMarkup([_footer_row(_cb(f"qpwave_{role}"), lang)]),
            parse_mode="HTML",
        )
    return True


async def _list_populations(dataset: str, query_text: str) -> list[dict[str, Any]]:
    args = [
        DNA_PLATFORM_PYTHON,
        "dna_platform.py",
        "admixlab-list-populations",
        "--dataset",
        dataset,
        "--query",
        query_text,
        "--limit",
        "10",
    ]
    stdout = await _run_process(args, cwd=DNA_PLATFORM_ROOT, timeout_seconds=QPWAVE_SEARCH_TIMEOUT_SECONDS)
    payload = json.loads(stdout)
    populations = payload.get("populations")
    if not isinstance(populations, list):
        return []
    results: list[dict[str, Any]] = []
    for item in populations:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or item.get("population_id") or "")
        population_id = str(item.get("population_id") or label)
        if not population_id:
            continue
        results.append({"id": population_id, "label": label or population_id, "sample_count": item.get("sample_count")})
    return results


def _search_results_text(flow: dict[str, Any], query_text: str, results: list[dict[str, Any]], role: str) -> str:
    lines = [
        f"<b>🔎 {html.escape(_qpwave_title(flow, suffix='поиск ' + ROLE_LABELS_RU[role]))}</b>",
        "",
        f"Dataset: <code>{html.escape(_dataset_label(flow.get('dataset')))}</code>",
        f"Запрос: <code>{html.escape(query_text)}</code>",
    ]
    if not results:
        lines.extend(["", "Ничего не найдено. Попробуйте другой запрос."])
        return "\n".join(lines)
    lines.extend(["", "Выберите population:"])
    for index, item in enumerate(results, start=1):
        label = html.escape(str(item.get("label") or item.get("id")))
        count = item.get("sample_count")
        suffix = f" ({count})" if count is not None else ""
        lines.append(f"{index}. <code>{label}</code>{suffix}")
    return "\n".join(lines)


def _search_results_keyboard(results: list[dict[str, Any]], role: str, *, lang: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for index, item in enumerate(results[:10]):
        label = _clip(item.get("label") or item.get("id"), 34)
        count = item.get("sample_count")
        if count is not None:
            label = f"{label} ({count})"
        rows.append([InlineKeyboardButton(label, callback_data=_cb("qpwave_pick", role, index))])
    rows.append([InlineKeyboardButton("🔎 Новый поиск", callback_data=_cb("qpwave_search", role))])
    rows.append(_footer_row(_cb(f"qpwave_{role}"), lang))
    return InlineKeyboardMarkup(rows)


async def _pick_population(message, context: ContextTypes.DEFAULT_TYPE, role: str, index_text: str, *, lang: str) -> None:
    flow = _get_flow(context)
    if flow is None:
        await show_qpwave_dataset_menu(message, context, edit_existing=True, lang=lang)
        return
    results = flow.get("search_results")
    if not isinstance(results, list):
        await _start_search(message, context, role, lang=lang)
        return
    try:
        item = results[int(index_text)]
    except (ValueError, IndexError, TypeError):
        await _start_search(message, context, role, lang=lang)
        return
    population_id = str(item.get("id") or item.get("label"))
    _merge_role_items(flow, role, [population_id])
    _clear_search(flow)
    await _show_role_menu(message, context, role, edit_existing=True, lang=lang)


async def _delete_item(message, context: ContextTypes.DEFAULT_TYPE, role: str, index_text: str, *, lang: str) -> None:
    flow = _get_flow(context)
    if flow is None:
        await show_qpwave_dataset_menu(message, context, edit_existing=True, lang=lang)
        return
    items = _as_list(flow, role)
    try:
        del items[int(index_text)]
    except (ValueError, IndexError):
        pass
    flow[role] = items
    await _show_role_menu(message, context, role, edit_existing=True, lang=lang)


async def _show_source_sets(message, update: Update, context: ContextTypes.DEFAULT_TYPE, *, lang: str, page: int = 0) -> None:
    flow = _get_flow(context)
    if flow is None:
        await show_qpwave_dataset_menu(message, context, edit_existing=True, lang=lang)
        return
    nav_enter(context, _cb("qpwave_sets_page", page))
    user_id = int(update.effective_user.id) if update.effective_user is not None else 0
    rows = _user_source_sets(user_id, dataset=str(flow.get("dataset") or ""))
    lines = [
        f"<b>📚 Source sets · {html.escape(_qpwave_title(flow))}</b>",
        "",
        f"Dataset: <code>{html.escape(_dataset_label(flow.get('dataset')))}</code>",
    ]
    buttons: list[list[InlineKeyboardButton]] = []
    if not rows:
        lines.extend(["", "Для этого dataset нет сохраненных Source sets."])
        buttons.append([InlineKeyboardButton("Открыть Source sets", callback_data=_cb("source_sets"))])
    else:
        page_count = max(1, (len(rows) + QPWAVE_SOURCE_SET_PAGE_SIZE - 1) // QPWAVE_SOURCE_SET_PAGE_SIZE)
        page = min(max(0, page), page_count - 1)
        start = page * QPWAVE_SOURCE_SET_PAGE_SIZE
        end = min(len(rows), start + QPWAVE_SOURCE_SET_PAGE_SIZE)
        rows = rows[start:end]
        lines.extend(["", "Выберите Left/Right-набор:"])
        for item in rows:
            left = item.get("sources") if isinstance(item.get("sources"), list) else []
            right = item.get("references") if isinstance(item.get("references"), list) else []
            label = f"{str(item.get('name') or 'Source set')[:32]} · {len(left)}L/{len(right)}R"
            buttons.append([InlineKeyboardButton(label, callback_data=_cb("qpwave_set", item.get("id")))])
        if page_count > 1:
            buttons.append(page_nav_row(page, page_count, lambda value: _cb("qpwave_sets_page", value)))
    buttons.append(_footer_row(nav_back_callback(), lang))
    await _show_message(message, "\n".join(lines), InlineKeyboardMarkup(buttons), edit_existing=True)


async def _apply_source_set(message, update: Update, context: ContextTypes.DEFAULT_TYPE, set_id: str, *, lang: str) -> None:
    flow = _get_flow(context)
    if flow is None:
        await show_qpwave_dataset_menu(message, context, edit_existing=True, lang=lang)
        return
    user_id = int(update.effective_user.id) if update.effective_user is not None else 0
    item = _get_source_set(user_id, set_id)
    if item is None:
        await _show_source_sets(message, update, context, lang=lang)
        return
    if not _dataset_matches(item, str(flow.get("dataset") or "")):
        text = "\n".join(
            [
                "<b>📚 Source set</b>",
                "",
                *_dataset_mismatch_lines(flow.get("dataset"), _record_dataset_label(item)),
            ]
        )
        await _show_message(message, text, InlineKeyboardMarkup([_footer_row(_cb("qpwave_sets"), lang)]), edit_existing=True)
        return
    flow["left"] = [str(value) for value in item.get("sources", []) if str(value)]
    flow["right"] = [str(value) for value in item.get("references", []) if str(value)]
    await _show_builder(message, context, edit_existing=True, lang=lang)


def _queue_state(context: ContextTypes.DEFAULT_TYPE) -> dict[str, Any]:
    state = context.application.bot_data.get(QPWAVE_QUEUE_KEY)
    if not isinstance(state, dict):
        state = {
            "semaphore": asyncio.Semaphore(QPWAVE_MAX_CONCURRENT_JOBS),
            "lock": asyncio.Lock(),
            "pending": [],
            "active": {},
            "next_id": 0,
        }
        context.application.bot_data[QPWAVE_QUEUE_KEY] = state
    return state


def _queue_markup(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([_footer_row(_cb("qpwave_builder"), lang)])


def _result_markup(lang: str, pending_save_id: str | None = None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if pending_save_id:
        rows.append([InlineKeyboardButton("💾 Сохранить результат", callback_data=_cb("saved_save", pending_save_id))])
    rows.extend(
        [
            [InlineKeyboardButton("🌊 Новый qpWave", callback_data=_cb("qpwave_reset"))],
            [
                InlineKeyboardButton("Left", callback_data=_cb("qpwave_left")),
                InlineKeyboardButton("Right", callback_data=_cb("qpwave_right")),
            ],
            [InlineKeyboardButton("💾 Сохранить Source set", callback_data=_cb("ss_save_current"))],
            _footer_row(_cb("qpwave_builder"), lang),
        ]
    )
    return InlineKeyboardMarkup(rows)


def _format_queue_text(flow: dict[str, Any], *, job_id: int, position: int, active_count: int) -> str:
    lines = [
        f"<b>{html.escape(_qpwave_title(flow, suffix='очередь'))}</b>",
        "",
        *_state_lines(flow),
        "",
        f"Задача: <code>#{job_id}</code>",
    ]
    if position > 1 or active_count >= QPWAVE_MAX_CONCURRENT_JOBS:
        lines.append(f"Место в очереди: <code>{position}</code>")
    if active_count >= QPWAVE_MAX_CONCURRENT_JOBS:
        lines.append(f"Сейчас считается: <code>{active_count}/{QPWAVE_MAX_CONCURRENT_JOBS}</code>")
    return "\n".join(lines)


def _format_started_text(flow: dict[str, Any]) -> str:
    return "\n".join([f"<b>{html.escape(_qpwave_title(flow, suffix='расчет запущен'))}</b>", "", *_state_lines(flow), "", "Обычно это занимает от минуты до нескольких минут."])


def _format_qpwave_error(flow: dict[str, Any], exc: Exception) -> str:
    detail = str(exc) or exc.__class__.__name__
    lines = [
        f"<b>{html.escape(_qpwave_title(flow, suffix='не прошел'))}</b>",
        "",
        *_state_lines(flow),
        "",
        "<b>Ошибка</b>",
        f"<code>{html.escape(detail)}</code>",
    ]
    lowered = detail.casefold()
    if "block_lengths" in lowered or "extract_f2" in lowered or "f2" in lowered:
        lines.extend(
            [
                "",
                "Подсказка: проверьте <b>ADMIXTOOLS 2 → f2 cache</b> и повторите расчет после готового cache.",
            ]
        )
    return "\n".join(lines)


async def _register_job(context: ContextTypes.DEFAULT_TYPE, entry: dict[str, Any]) -> tuple[int, int, int]:
    state = _queue_state(context)
    async with state["lock"]:
        state["next_id"] = int(state.get("next_id") or 0) + 1
        entry["job_id"] = state["next_id"]
        state["pending"].append(entry)
        return int(entry["job_id"]), len(state["pending"]), len(state["active"])


async def _edit_job_message(context: ContextTypes.DEFAULT_TYPE, entry: dict[str, Any], text: str, markup: InlineKeyboardMarkup) -> bool:
    try:
        await context.bot.edit_message_text(
            chat_id=int(entry["chat_id"]),
            message_id=int(entry["message_id"]),
            text=text,
            reply_markup=markup,
            parse_mode="HTML",
        )
        return True
    except BadRequest:
        return False


async def _send_job_text_fallback(context: ContextTypes.DEFAULT_TYPE, entry: dict[str, Any], text: str, markup: InlineKeyboardMarkup) -> None:
    if await _edit_job_message(context, entry, text, markup):
        return
    chat_id = int(entry["chat_id"])
    user_id = int(entry["user_id"])
    sent = await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=markup, parse_mode="HTML")
    set_active_main_menu_message(context, chat_id, user_id, sent.message_id)


async def _send_job_result(
    context: ContextTypes.DEFAULT_TYPE,
    entry: dict[str, Any],
    text: str,
    markup: InlineKeyboardMarkup,
    *,
    caption: str | None = None,
    visual_path: str | None = None,
) -> None:
    path = Path(visual_path) if visual_path else None
    if path is None or not path.exists():
        await _send_job_text_fallback(context, entry, text, markup)
        return
    chat_id = int(entry["chat_id"])
    message_id = int(entry["message_id"])
    user_id = int(entry["user_id"])
    try:
        with path.open("rb") as image_file:
            sent = await context.bot.send_photo(
                chat_id=chat_id,
                photo=image_file,
                caption=caption or text[:900],
                reply_markup=markup,
                parse_mode="HTML",
            )
        set_active_main_menu_message(context, chat_id, user_id, sent.message_id)
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
        except BadRequest:
            pass
    except Exception:
        await _send_job_text_fallback(context, entry, text, markup)


async def _refresh_pending(context: ContextTypes.DEFAULT_TYPE, pending: list[dict[str, Any]], active_count: int) -> None:
    for position, entry in enumerate(pending, start=1):
        await _edit_job_message(
            context,
            entry,
            _format_queue_text(entry["flow"], job_id=int(entry["job_id"]), position=position, active_count=active_count),
            _queue_markup(str(entry.get("lang") or "ru")),
        )


async def _enqueue_qpwave(message, update: Update, context: ContextTypes.DEFAULT_TYPE, *, lang: str) -> None:
    flow = _get_flow(context)
    if flow is None:
        await show_qpwave_dataset_menu(message, context, edit_existing=True, lang=lang)
        return
    if not _as_list(flow, "left") or not _as_list(flow, "right"):
        await _show_builder(message, context, edit_existing=True, lang=lang)
        return
    frozen_flow = _snapshot_flow(flow)
    user_id = int(update.effective_user.id) if update.effective_user is not None else 0
    entry = {
        "chat_id": int(message.chat_id),
        "message_id": int(message.message_id),
        "user_id": user_id,
        "lang": lang,
        "flow": frozen_flow,
    }
    job_id, position, active_count = await _register_job(context, entry)
    await _show_message(message, _format_queue_text(frozen_flow, job_id=job_id, position=position, active_count=active_count), _queue_markup(lang), edit_existing=True)
    context.application.create_task(_worker(context, entry))


async def _worker(context: ContextTypes.DEFAULT_TYPE, entry: dict[str, Any]) -> None:
    state = _queue_state(context)
    semaphore = state["semaphore"]
    job_id = int(entry["job_id"])
    async with semaphore:
        async with state["lock"]:
            state["pending"] = [item for item in state["pending"] if int(item.get("job_id") or 0) != job_id]
            state["active"][job_id] = entry
            pending_snapshot = list(state["pending"])
            active_count = len(state["active"])
        await _refresh_pending(context, pending_snapshot, active_count)
        await _edit_job_message(context, entry, _format_started_text(entry["flow"]), _queue_markup(str(entry.get("lang") or "ru")))
        pending_save_id: str | None = None
        caption: str | None = None
        visual_path: str | None = None
        try:
            text, save_payload = await _run_qpwave_job(
                entry["flow"],
                int(entry["user_id"]),
                job_id=job_id,
                lang=str(entry.get("lang") or "ru"),
            )
            pending_save_id = register_pending_save(context, int(entry["user_id"]), save_payload)
            caption = str(save_payload.get("caption_text") or "")
            visual_path = str(save_payload.get("visual_path") or "")
        except Exception as exc:
            text = _format_qpwave_error(entry["flow"], exc)
        await _send_job_result(
            context,
            entry,
            text,
            _result_markup(str(entry.get("lang") or "ru"), pending_save_id),
            caption=caption,
            visual_path=visual_path,
        )
        async with state["lock"]:
            state["active"].pop(job_id, None)


async def _run_qpwave_job(flow: dict[str, Any], user_id: int, *, job_id: int, lang: str) -> tuple[str, dict[str, Any]]:
    if _is_admixtools2_engine(flow.get("engine")):
        return await _run_qpwave_admixtools2_job(flow, user_id, job_id=job_id, lang=lang)

    dataset = str(flow.get("dataset") or "")
    files = DATASET_FILES.get(dataset)
    if files is None:
        raise RuntimeError(f"unknown dataset: {dataset}")
    if not QPWAVE_EXECUTABLE.exists():
        raise RuntimeError(f"qpWave executable not found: {QPWAVE_EXECUTABLE}")

    BOT_QPWAVE_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    work_dir = BOT_QPWAVE_OUTPUT_DIR / f"job_{user_id}_{int(time.time())}_{job_id}"
    work_dir.mkdir(parents=True, exist_ok=True)
    left_path = work_dir / "left.txt"
    right_path = work_dir / "right.txt"
    par_path = work_dir / "qpwave.par"
    out_path = work_dir / "qpwave.out"
    left_path.write_text("\n".join(_as_list(flow, "left")) + "\n", encoding="utf-8")
    right_path.write_text("\n".join(_as_list(flow, "right")) + "\n", encoding="utf-8")
    par_path.write_text(
        "\n".join(
            [
                f"genotypename: {files['geno']}",
                f"snpname: {files['snp']}",
                f"indivname: {files['ind']}",
                f"popleft: {left_path}",
                f"popright: {right_path}",
                "details: YES",
                "allsnps: YES",
                "inbreed: NO",
                "",
            ]
        ),
        encoding="utf-8",
    )
    started = time.monotonic()
    stdout = await _run_process([str(QPWAVE_EXECUTABLE), "-p", str(par_path)], cwd=work_dir, timeout_seconds=QPWAVE_TIMEOUT_SECONDS)
    out_path.write_text(stdout, encoding="utf-8")
    elapsed = time.monotonic() - started
    ranks = _parse_ranks(stdout)
    text = _format_qpwave_result(stdout, flow=flow, elapsed_seconds=elapsed)
    caption = _format_qpwave_caption(ranks, flow=flow, elapsed_seconds=elapsed)
    visual_path: Path | None = None
    visual_error: str | None = None
    try:
        visual_path = render_qpwave_result(ranks=ranks, flow=flow, elapsed_seconds=elapsed, output_dir=BOT_QPWAVE_OUTPUT_DIR)
    except Exception as exc:
        visual_error = str(exc)
    save_payload = {
        "kind": "qpwave",
        "title": f"🌊 qpWave · {_dataset_label(flow.get('dataset'))} · {len(_as_list(flow, 'left'))}L/{len(_as_list(flow, 'right'))}R",
        "dataset": flow.get("dataset"),
        "engine_label": "qpWave classic",
        "left": _as_list(flow, "left"),
        "right": _as_list(flow, "right"),
        "result_text": text,
        "caption_text": caption,
        "visual_path": str(visual_path or ""),
        "visual_error": visual_error,
        "raw_output_path": str(out_path),
        "raw_output": stdout,
    }
    return text, save_payload


async def _run_qpwave_admixtools2_job(flow: dict[str, Any], user_id: int, *, job_id: int, lang: str) -> tuple[str, dict[str, Any]]:
    dataset = str(flow.get("dataset") or "")
    files = _at2_dataset_files(dataset)
    if not files:
        raise RuntimeError(f"ADMIXTOOLS2 dataset files not found: {dataset}")

    BOT_QPWAVE_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    work_dir = BOT_QPWAVE_OUTPUT_DIR / f"at2_job_{user_id}_{int(time.time())}_{job_id}"
    work_dir.mkdir(parents=True, exist_ok=True)
    out_path = work_dir / "qpwave_admixtools2.json"

    started = time.monotonic()
    payload = await run_admixtools2_runner(
        {
            "command": "qpwave",
            "dataset": dataset,
            "dataset_files": files,
            "left": _as_list(flow, "left"),
            "right": _as_list(flow, "right"),
            "options": {"boot": False},
        },
        timeout_seconds=QPWAVE_TIMEOUT_SECONDS,
    )
    elapsed = time.monotonic() - started
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    ranks = _extract_admixtools2_ranks(payload)
    text = _format_qpwave_result("", flow=flow, elapsed_seconds=elapsed, ranks_override=ranks)
    caption = _format_qpwave_caption(ranks, flow=flow, elapsed_seconds=elapsed)
    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    data_source = result.get("data_source") if isinstance(result.get("data_source"), dict) else {}
    f4_rows = result.get("f4") if isinstance(result.get("f4"), list) else []
    warnings = [str(item) for item in payload.get("warnings", []) if str(item)] if isinstance(payload.get("warnings"), list) else []
    visual_path: Path | None = None
    visual_error: str | None = None
    try:
        visual_path = render_qpwave_result(
            ranks=ranks,
            flow=flow,
            elapsed_seconds=elapsed,
            output_dir=BOT_QPWAVE_OUTPUT_DIR,
            data_source=data_source,
            warnings=warnings,
            f4_rows=f4_rows,
        )
    except Exception as exc:
        visual_error = str(exc)
    raw_output = json.dumps(payload, ensure_ascii=False, indent=2)
    save_payload = {
        "kind": "qpwave_admixtools2",
        "title": f"〰️ ADMIXTOOLS2 qpWave · {_dataset_label(flow.get('dataset'))} · {len(_as_list(flow, 'left'))}L/{len(_as_list(flow, 'right'))}R",
        "dataset": flow.get("dataset"),
        "engine": QPWAVE_ENGINE_ADMIXTOOLS2,
        "engine_label": "ADMIXTOOLS2 qpWave 2",
        "left": _as_list(flow, "left"),
        "right": _as_list(flow, "right"),
        "result_text": text,
        "caption_text": caption,
        "visual_path": str(visual_path or ""),
        "visual_error": visual_error,
        "raw_output_path": str(out_path),
        "raw_output": raw_output,
        "admixtools2_payload": payload,
        "data_source": data_source,
        "warnings": warnings,
        "f4_rows": f4_rows,
    }
    return text, save_payload


def _parse_ranks(stdout: str) -> list[dict[str, Any]]:
    ranks: list[dict[str, Any]] = []
    for match in RANK_PATTERN.finditer(stdout):
        ranks.append(
            {
                "rank": int(match.group("rank")),
                "dof": float(match.group("dof")),
                "chisq": float(match.group("chisq")),
                "tail": float(match.group("tail")),
            }
        )
    return ranks


def _scalar_value(value: object) -> object:
    if isinstance(value, list) and value:
        return value[0]
    return value


def _float_value(value: object) -> float | None:
    value = _scalar_value(value)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_value(value: object, default: int = 0) -> int:
    value = _scalar_value(value)
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _extract_admixtools2_ranks(payload: dict[str, Any]) -> list[dict[str, Any]]:
    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    rows = result.get("ranks") if isinstance(result.get("ranks"), list) else []
    ranks: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        ranks.append(
            {
                "rank": _int_value(row.get("rank"), index),
                "dof": _float_value(row.get("dof")),
                "chisq": _float_value(row.get("chisq")),
                "tail": _float_value(row.get("tail")),
            }
        )
    return ranks


def _format_qpwave_result(
    stdout: str,
    *,
    flow: dict[str, Any],
    elapsed_seconds: float,
    ranks_override: list[dict[str, Any]] | None = None,
) -> str:
    ranks = ranks_override if ranks_override is not None else _parse_ranks(stdout)
    lines = [
        f"<b>{html.escape(_qpwave_title(flow))}</b>",
        "",
        f"Dataset: <code>{html.escape(_dataset_label(flow.get('dataset')))}</code>",
        f"Status: <code>completed</code>",
        f"Left: <code>{len(_as_list(flow, 'left'))}</code>",
        f"Right: <code>{len(_as_list(flow, 'right'))}</code>",
        f"Время: <code>{elapsed_seconds:.1f}s</code>",
    ]
    if ranks:
        lines.extend(["", "<b>Rank tests</b>"])
        for item in ranks:
            lines.append(
                f"rank <code>{item['rank']}</code>: p-value <code>{_format_number(item['tail'])}</code>, "
                f"chisq <code>{_format_number(item['chisq'])}</code>, dof <code>{_format_number(item['dof'])}</code>"
            )
    lines.extend(["", *_items_lines("Left", _as_list(flow, "left"))])
    lines.extend(["", *_items_lines("Right", _as_list(flow, "right"))])
    return "\n".join(lines)


def _format_qpwave_caption(ranks: list[dict[str, Any]], *, flow: dict[str, Any], elapsed_seconds: float) -> str:
    lines = [
        f"<b>{html.escape(_qpwave_title(flow))}</b>",
        f"Dataset: <code>{html.escape(_dataset_label(flow.get('dataset')))}</code>",
        f"Left: <code>{len(_as_list(flow, 'left'))}</code>",
        f"Right: <code>{len(_as_list(flow, 'right'))}</code>",
        f"Время: <code>{elapsed_seconds:.1f}s</code>",
    ]
    if ranks:
        best = ranks[0]
        lines.append(
            f"rank <code>{best.get('rank')}</code>: p-value <code>{_format_number(best.get('tail'))}</code>"
        )
    return "\n".join(lines)


async def qpwave_callback_handler(
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

    if action == "qpwave_engine" and len(parts) >= 3:
        await show_qpwave_dataset_menu(message, context, engine=parts[2], edit_existing=True, lang=lang)
        return
    if action == "qpwave_ds" and len(parts) >= 3:
        if len(parts) >= 4:
            engine = _qpwave_engine(parts[2])
            dataset = parts[3]
        else:
            engine = QPWAVE_ENGINE_CLASSIC
            dataset = parts[2]
        if dataset not in DATASET_LABELS:
            await show_qpwave_dataset_menu(message, context, engine=engine, edit_existing=True, lang=lang)
            return
        _start_flow(context, dataset, engine=engine)
        await _show_builder(message, context, edit_existing=True, lang=lang)
        return
    if action == "qpwave_builder":
        await _show_builder(message, context, edit_existing=True, lang=lang)
        return
    if action == "qpwave_reset":
        flow = _get_flow(context)
        engine = _qpwave_engine(flow.get("engine") if flow is not None else QPWAVE_ENGINE_CLASSIC)
        nav_reset(context, _cb("at2" if engine == QPWAVE_ENGINE_ADMIXTOOLS2 else "root"))
        await show_qpwave_dataset_menu(message, context, engine=engine, edit_existing=True, lang=lang)
        return
    if action == "qpwave_import":
        await _start_import(message, context, lang=lang)
        return
    if action == "qpwave_sets":
        await _show_source_sets(message, update, context, lang=lang)
        return
    if action == "qpwave_sets_page" and len(parts) >= 3:
        await _show_source_sets(message, update, context, lang=lang, page=_safe_page(parts[2]))
        return
    if action == "qpwave_set" and len(parts) >= 3:
        await _apply_source_set(message, update, context, parts[2], lang=lang)
        return
    if action == "qpwave_clear_lr":
        await _clear_left_right(message, context, lang=lang)
        return
    if action == "qpwave_left":
        await _show_role_menu(message, context, "left", edit_existing=True, lang=lang)
        return
    if action == "qpwave_right":
        await _show_role_menu(message, context, "right", edit_existing=True, lang=lang)
        return
    if action == "qpwave_search" and len(parts) >= 3 and parts[2] in {"left", "right"}:
        await _start_search(message, context, parts[2], lang=lang)
        return
    if action == "qpwave_pick" and len(parts) >= 4 and parts[2] in {"left", "right"}:
        await _pick_population(message, context, parts[2], parts[3], lang=lang)
        return
    if action == "qpwave_del" and len(parts) >= 4 and parts[2] in {"left", "right"}:
        await _delete_item(message, context, parts[2], parts[3], lang=lang)
        return
    if action == "qpwave_run":
        await _enqueue_qpwave(message, update, context, lang=lang)
        return
    await _show_builder(message, context, edit_existing=True, lang=lang)


async def _deactivate_prompt_markup(context: ContextTypes.DEFAULT_TYPE, flow: dict[str, Any], active_message_id: int) -> None:
    chat_id = flow.get("prompt_chat_id")
    message_id = flow.get("prompt_message_id")
    if chat_id is None or message_id is None or int(message_id) == int(active_message_id):
        return
    try:
        await context.bot.edit_message_reply_markup(chat_id=int(chat_id), message_id=int(message_id), reply_markup=None)
    except BadRequest:
        return
