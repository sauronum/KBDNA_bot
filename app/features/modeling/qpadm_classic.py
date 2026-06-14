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

from app.features.modeling.datasets import DATASET_LABELS, dataset_choices, dataset_label
from app.features.modeling.navigation import (
    nav_back_callback,
    nav_enter,
    nav_reset,
)
from app.features.modeling.saved_models import register_pending_save
from app.features.modeling.ui import footer_row as _footer_row
from app.features.modeling.ui import modeling_cb as _cb
from app.features.modeling.ui import page_nav_row
from app.features.modeling.ui import show_message as _show_message
from app.features.modeling.visuals import render_admixtools2_qpadm_batch_result, render_qpadm_result
from app.heavy_runtime import heavy_command
from app.i18n import get_user_language
from app.main_menu import set_active_main_menu_message


QPADM_FLOW_KEY = "qpadm_classic_flow"
QPADM_QUEUE_KEY = "qpadm_classic_queue"
QPADM_ENGINE_KEY = "qpadm_classic_engine"

DNA_PLATFORM_ROOT = Path(os.getenv("DNA_PLATFORM_ROOT", "/srv/dna_platform"))
DNA_PLATFORM_PYTHON = os.getenv("DNA_PLATFORM_PYTHON", "python3")
ADMIXLAB_BIN_DIR = Path(os.getenv("ADMIXLAB_BIN_DIR", "/srv/dna_platform/tools/admixtools/bin"))
ADMIXLAB_QPADM_BACKEND_CONFIG_DEFAULT = "/etc/admixlab/qpadm_backend_config.json"
ADMIXLAB_QPADM_ADMIXTOOLS2_BACKEND_CONFIG_DEFAULT = "/etc/admixlab/qpadm_backend_config.admixtools2.json"
ADMIXLAB_QPADM_BACKEND_CONFIG = os.getenv("ADMIXLAB_QPADM_BACKEND_CONFIG", ADMIXLAB_QPADM_BACKEND_CONFIG_DEFAULT)
ADMIXLAB_RAW_MERGE_CONFIG = os.getenv("ADMIXLAB_RAW_MERGE_CONFIG", "/etc/admixlab/raw_merge_config.json")
BOT_QPADM_OUTPUT_DIR = Path(
    os.getenv("KBDNA_QPADM_OUTPUT_DIR", str(DNA_PLATFORM_ROOT / "output" / "admixlab" / "bot"))
)
QPADM_TIMEOUT_SECONDS = int(os.getenv("KBDNA_QPADM_TIMEOUT_SECONDS", "7200"))
QPADM_PREFLIGHT_TIMEOUT_SECONDS = int(os.getenv("KBDNA_QPADM_PREFLIGHT_TIMEOUT_SECONDS", "1800"))
QPADM_SEARCH_TIMEOUT_SECONDS = int(os.getenv("KBDNA_QPADM_SEARCH_TIMEOUT_SECONDS", "60"))
QPADM_MAX_CONCURRENT_JOBS = int(os.getenv("KBDNA_QPADM_MAX_CONCURRENT_JOBS", "3"))
QPADM_SAMPLE_PAGE_SIZE = 10

QPADM_ENGINE_CLASSIC = "classic_qpadm"
QPADM_ENGINE_ADMIXTOOLS2 = "admixtools2_qpadm"
QPADM_ENGINE_LABELS = {
    QPADM_ENGINE_CLASSIC: "Classic ADMIXTOOLS qpAdm",
    QPADM_ENGINE_ADMIXTOOLS2: "ADMIXTOOLS2 qpAdm",
}
QPADM_ENGINE_ALIASES = {
    "classic": QPADM_ENGINE_CLASSIC,
    "classic_qpadm": QPADM_ENGINE_CLASSIC,
    "admixtools": QPADM_ENGINE_CLASSIC,
    "admixtools_qpadm": QPADM_ENGINE_CLASSIC,
    "admixtools2": QPADM_ENGINE_ADMIXTOOLS2,
    "admixtools2_qpadm": QPADM_ENGINE_ADMIXTOOLS2,
}
ROLE_LABELS = {
    "target": "target",
    "source": "source",
    "reference": "reference",
    "import": "model",
    "import_lr": "left/right",
}
ROLE_LABELS_RU = {
    "target": "target",
    "source": "source",
    "reference": "reference",
    "import": "модель",
    "import_lr": "Left/Right",
}

MODEL_IMPORT_PATTERN = re.compile(
    r"(?is)\b(left|sources?|right|references?|target)\s*[:=]\s*(.*?)(?=\b(?:left|sources?|right|references?|target)\s*[:=]|$)"
)

def _dataset_label(dataset: object) -> str:
    return dataset_label(dataset)


def _qpadm_engine(value: object) -> str:
    raw = str(value or "").strip().casefold()
    return QPADM_ENGINE_ALIASES.get(raw, QPADM_ENGINE_CLASSIC)


def _is_admixtools2_engine(value: object) -> bool:
    return _qpadm_engine(value) == QPADM_ENGINE_ADMIXTOOLS2


def _has_supported_target_for_engine(flow: dict[str, Any]) -> bool:
    if not _is_admixtools2_engine(flow.get("engine")):
        return True
    target_type = str(flow.get("target_type") or "")
    return target_type in {"dataset_population", "raw_file"} and bool(_targets_list(flow))


def _is_qpadm_engine(value: object) -> bool:
    return str(value or "").strip().casefold() in QPADM_ENGINE_ALIASES


def _qpadm_engine_label(engine: object) -> str:
    return QPADM_ENGINE_LABELS.get(_qpadm_engine(engine), QPADM_ENGINE_LABELS[QPADM_ENGINE_CLASSIC])


def _qpadm_engine_display(engine: object) -> str:
    if _is_qpadm_engine(engine):
        return _qpadm_engine_label(engine)
    text = str(engine or "").strip()
    return text or _qpadm_engine_label(QPADM_ENGINE_CLASSIC)


def _qpadm_title(engine: object, *, prefix: str = "🏛", suffix: str | None = None) -> str:
    base = "ADMIXTOOLS2 qpAdm" if _qpadm_engine(engine) == QPADM_ENGINE_ADMIXTOOLS2 else "qpAdm classic"
    title = f"{prefix} {base}" if prefix else base
    return f"{title} · {suffix}" if suffix else title


def _flow_title(flow: dict[str, Any], *, prefix: str = "🏛", suffix: str | None = None) -> str:
    return _qpadm_title(flow.get("engine"), prefix=prefix, suffix=suffix)


def _qpadm_backend_config_for_engine(engine: object) -> str:
    legacy_config = os.getenv("ADMIXLAB_QPADM_BACKEND_CONFIG", ADMIXLAB_QPADM_BACKEND_CONFIG)
    classic_config = os.getenv("ADMIXLAB_QPADM_CLASSIC_BACKEND_CONFIG", legacy_config)
    if _qpadm_engine(engine) == QPADM_ENGINE_ADMIXTOOLS2:
        return os.getenv("ADMIXLAB_QPADM_ADMIXTOOLS2_BACKEND_CONFIG", ADMIXLAB_QPADM_ADMIXTOOLS2_BACKEND_CONFIG_DEFAULT)
    return classic_config


def _role_label(role: str, lang: str = "ru") -> str:
    labels = ROLE_LABELS if lang == "en" else ROLE_LABELS_RU
    return labels.get(role, role)


def _target_menu_markup(flow: dict[str, Any], lang: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]]
    if _is_admixtools2_engine(flow.get("engine")):
        rows = [
            [InlineKeyboardButton("🧬 My raw samples", callback_data=_cb("qpadm_target_kind", "sample"))],
            [InlineKeyboardButton("🌐 Dataset population(s)", callback_data=_cb("qpadm_target_kind", "population"))],
            [InlineKeyboardButton("\U0001f4cb Import population model", callback_data=_cb("qpadm_import"))],
        ]
    else:
        rows = [
            [InlineKeyboardButton("\U0001f9ec My samples", callback_data=_cb("qpadm_target_kind", "sample"))],
            [InlineKeyboardButton("\U0001f310 Dataset populations", callback_data=_cb("qpadm_target_kind", "population"))],
            [InlineKeyboardButton("\U0001f4cb Import Left/Right/Target", callback_data=_cb("qpadm_import"))],
        ]
    rows.append(_footer_row(nav_back_callback(), lang))
    return InlineKeyboardMarkup(rows)


def _get_flow(context: ContextTypes.DEFAULT_TYPE) -> dict[str, Any] | None:
    flow = context.user_data.get(QPADM_FLOW_KEY)
    return flow if isinstance(flow, dict) else None


def _snapshot_flow(flow: dict[str, Any]) -> dict[str, Any]:
    return {
        "engine": _qpadm_engine(flow.get("engine")),
        "dataset": flow.get("dataset"),
        "target_type": flow.get("target_type"),
        "target": flow.get("target"),
        "target_label": flow.get("target_label"),
        "targets": _targets_list(flow),
        "target_labels": _target_labels_list(flow),
        "sources": _as_list(flow, "sources"),
        "references": _as_list(flow, "references"),
    }


def _start_flow(context: ContextTypes.DEFAULT_TYPE, dataset: str, *, engine: object = QPADM_ENGINE_CLASSIC) -> dict[str, Any]:
    flow: dict[str, Any] = {
        "engine": _qpadm_engine(engine),
        "dataset": dataset,
        "target_type": None,
        "target": None,
        "target_label": None,
        "targets": [],
        "target_labels": [],
        "sources": [],
        "references": [],
        "search_results": [],
        "search_role": None,
        "awaiting_query": None,
        "awaiting_chat_id": None,
    }
    context.user_data[QPADM_FLOW_KEY] = flow
    return flow


def _clear_search(flow: dict[str, Any]) -> None:
    flow["search_results"] = []
    flow["search_role"] = None
    flow["awaiting_query"] = None
    flow["awaiting_chat_id"] = None
    flow.pop("prompt_chat_id", None)
    flow.pop("prompt_message_id", None)


def _as_list(flow: dict[str, Any], key: str) -> list[str]:
    value = flow.get(key)
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    return []


def _targets_list(flow: dict[str, Any]) -> list[str]:
    targets = _as_list(flow, "targets")
    if targets:
        return targets
    target = str(flow.get("target") or "").strip()
    return [target] if target else []


def _target_labels_list(flow: dict[str, Any]) -> list[str]:
    labels = _as_list(flow, "target_labels")
    targets = _targets_list(flow)
    if labels:
        if len(labels) < len(targets):
            labels.extend(targets[len(labels) :])
        return labels[: len(targets)]
    label = str(flow.get("target_label") or "").strip()
    if label and targets:
        return [label, *targets[1:]]
    return list(targets)


def _target_entries(flow: dict[str, Any]) -> list[dict[str, str]]:
    target_type = str(flow.get("target_type") or "dataset_population")
    targets = _targets_list(flow)
    labels = _target_labels_list(flow)
    entries: list[dict[str, str]] = []
    for index, target in enumerate(targets):
        label = labels[index] if index < len(labels) else target
        entries.append({"target_type": target_type, "target": target, "target_label": label})
    return entries


def _sync_primary_target(flow: dict[str, Any]) -> None:
    targets = _targets_list(flow)
    if not targets:
        flow["target"] = None
        flow["target_label"] = None
        flow["targets"] = []
        flow["target_labels"] = []
        return
    labels = _target_labels_list(flow)
    flow["targets"] = targets
    flow["target_labels"] = labels
    flow["target"] = targets[0]
    flow["target_label"] = labels[0] if labels else targets[0]


def _set_single_target(flow: dict[str, Any], label: str, target_type: str = "dataset_population") -> None:
    flow["target_type"] = target_type
    flow["target"] = label
    flow["target_label"] = label
    flow["targets"] = [label] if target_type in {"dataset_population", "raw_file"} else []
    flow["target_labels"] = [label] if target_type in {"dataset_population", "raw_file"} else []


def _add_dataset_target(flow: dict[str, Any], label: str) -> None:
    if not _is_admixtools2_engine(flow.get("engine")):
        _set_single_target(flow, label)
        return
    targets = _targets_list(flow) if flow.get("target_type") == "dataset_population" else []
    if label not in targets:
        targets.append(label)
    flow["target_type"] = "dataset_population"
    flow["targets"] = targets
    flow["target_labels"] = targets
    _sync_primary_target(flow)


def _add_raw_target(flow: dict[str, Any], path: str, label: str) -> None:
    if not _is_admixtools2_engine(flow.get("engine")):
        flow["target_type"] = "raw_file"
        flow["target"] = path
        flow["target_label"] = label
        flow["targets"] = []
        flow["target_labels"] = []
        return
    targets = _targets_list(flow) if flow.get("target_type") == "raw_file" else []
    labels = _target_labels_list(flow) if flow.get("target_type") == "raw_file" else []
    if path not in targets:
        targets.append(path)
        labels.append(label)
    flow["target_type"] = "raw_file"
    flow["targets"] = targets
    flow["target_labels"] = labels
    _sync_primary_target(flow)


def _remove_target(flow: dict[str, Any], index: int) -> None:
    targets = _targets_list(flow)
    labels = _target_labels_list(flow)
    try:
        del targets[index]
        if index < len(labels):
            del labels[index]
    except (IndexError, TypeError):
        return
    flow["targets"] = targets
    flow["target_labels"] = labels
    _sync_primary_target(flow)


def _remove_dataset_target(flow: dict[str, Any], index: int) -> None:
    _remove_target(flow, index)


def _has_complete_model(flow: dict[str, Any]) -> bool:
    return bool(_targets_list(flow) and _as_list(flow, "sources") and _as_list(flow, "references"))


def _target_display(flow: dict[str, Any]) -> str:
    entries = _target_entries(flow)
    targets = [entry["target"] for entry in entries]
    if len(targets) > 1:
        preview = ", ".join(_clip(entry["target_label"], 28) for entry in entries[:3])
        suffix = f" +{len(targets) - 3}" if len(targets) > 3 else ""
        return f"{len(targets)} targets: {preview}{suffix}"
    label = str(flow.get("target_label") or "").strip()
    if label:
        return label
    target = str(flow.get("target") or "").strip()
    if flow.get("target_type") == "raw_file" and target:
        return Path(target).name
    return target or "not selected"


def _clip(value: object, limit: int = 48) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)] + "…"


def _format_number(value: object, *, percent: bool = False) -> str:
    if value is None:
        return "n/a"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return html.escape(str(value))
    suffix = "%" if percent else ""
    text = f"{number:.3f}".rstrip("0").rstrip(".")
    if text == "-0":
        text = "0"
    return f"{text}{suffix}"


def _normalize_label(value: str) -> str:
    return value.strip().casefold()


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
        key = _normalize_label(item)
        if not item or key in seen:
            continue
        seen.add(key)
        items.append(item)
    return items


def _looks_like_item_list(value: str) -> bool:
    return "\n" in value or "," in value or ";" in value


def _looks_like_direct_qpadm_label(value: str) -> bool:
    text = _clean_item(value)
    if not text or any(char.isspace() for char in text):
        return False
    if any(separator in text for separator in (",", ";", "\n")):
        return False
    return "." in text or "_" in text or ":" in text


def _parse_model_import(value: str) -> dict[str, list[str] | str]:
    parsed: dict[str, list[str] | str] = {}
    for match in MODEL_IMPORT_PATTERN.finditer(value):
        key = match.group(1).lower()
        raw = match.group(2).strip()
        if not raw:
            continue
        if key == "target":
            items = _split_items(raw)
            if items:
                parsed["target"] = items[0]
            continue
        if key in {"left", "source", "sources"}:
            parsed["sources"] = _split_items(raw)
            continue
        if key in {"right", "reference", "references"}:
            parsed["references"] = _split_items(raw)
    return parsed


def _merge_role_items(flow: dict[str, Any], role: str, items: list[str], *, replace: bool = False) -> dict[str, Any]:
    key = "sources" if role == "source" else "references"
    other_key = "references" if key == "sources" else "sources"
    existing = [] if replace else _as_list(flow, key)
    other = {_normalize_label(item) for item in _as_list(flow, other_key)}
    target = _normalize_label(_target_display(flow))
    existing_keys = {_normalize_label(item) for item in existing}
    added: list[str] = []
    skipped: list[str] = []

    for item in items:
        clean = _clean_item(item)
        norm = _normalize_label(clean)
        if not clean:
            continue
        if norm in existing_keys or norm in other or (target and norm == target):
            skipped.append(clean)
            continue
        existing.append(clean)
        existing_keys.add(norm)
        added.append(clean)

    flow[key] = existing
    return {"added": added, "skipped": skipped, "role": role}


def _apply_model_import(flow: dict[str, Any], value: str, *, allow_target: bool = True) -> dict[str, Any] | None:
    parsed = _parse_model_import(value)
    if not parsed:
        return None
    if not allow_target and "sources" not in parsed and "references" not in parsed:
        return None

    imported: dict[str, Any] = {"target": None, "sources": [], "references": [], "skipped": [], "target_ignored": None}
    if "sources" in parsed:
        flow["sources"] = []
    if "references" in parsed:
        flow["references"] = []

    target = parsed.get("target")
    if isinstance(target, str) and target and allow_target:
        _set_single_target(flow, target)
        imported["target"] = target
    elif isinstance(target, str) and target:
        imported["target_ignored"] = target

    sources = parsed.get("sources")
    if isinstance(sources, list):
        result = _merge_role_items(flow, "source", sources, replace=True)
        imported["sources"] = result["added"]
        imported["skipped"].extend(result["skipped"])

    references = parsed.get("references")
    if isinstance(references, list):
        result = _merge_role_items(flow, "reference", references, replace=True)
        imported["references"] = result["added"]
        imported["skipped"].extend(result["skipped"])

    flow["search_results"] = []
    flow["search_role"] = None
    flow["awaiting_query"] = None
    flow["awaiting_chat_id"] = None
    return imported


def _qpadm_env(engine: object = QPADM_ENGINE_CLASSIC) -> dict[str, str]:
    env = os.environ.copy()
    env["PATH"] = f"{ADMIXLAB_BIN_DIR}:{env.get('PATH', '')}"
    env["ADMIXLAB_QPADM_BACKEND_CONFIG"] = _qpadm_backend_config_for_engine(engine)
    env["ADMIXLAB_RAW_MERGE_CONFIG"] = ADMIXLAB_RAW_MERGE_CONFIG
    return env


async def _run_process(args: list[str], *, timeout_seconds: int, engine: object = QPADM_ENGINE_CLASSIC) -> str:
    returncode, stdout, stderr = await _run_process_result(args, timeout_seconds=timeout_seconds, engine=engine)
    if returncode != 0:
        raise RuntimeError(_process_error_detail(returncode, stdout, stderr))
    return stdout


async def _run_process_result(args: list[str], *, timeout_seconds: int, engine: object = QPADM_ENGINE_CLASSIC) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *heavy_command(args),
        cwd=str(DNA_PLATFORM_ROOT),
        env=_qpadm_env(engine),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        raise RuntimeError("process timed out")

    stdout = stdout_bytes.decode("utf-8", errors="replace")
    stderr = stderr_bytes.decode("utf-8", errors="replace")
    return int(proc.returncode or 0), stdout, stderr


def _process_error_detail(returncode: int, stdout: str, stderr: str) -> str:
    detail = (stderr or stdout).strip().splitlines()[-10:]
    return "\n".join(detail) or f"process failed with exit code {returncode}"


async def _load_qpadm_summary(output_path: Path, *, engine: object) -> dict[str, Any]:
    summary_args = [DNA_PLATFORM_PYTHON, "dna_platform.py", "admixlab-summary", str(output_path), "--json"]
    summary_stdout = await _run_process(summary_args, timeout_seconds=60, engine=engine)
    payload = json.loads(summary_stdout)
    if not isinstance(payload, dict):
        raise RuntimeError("admixlab-summary returned a non-object JSON payload")
    return payload


def _summary_error_detail(summary: dict[str, Any] | None, fallback: str = "") -> str:
    if isinstance(summary, dict):
        errors = summary.get("errors") if isinstance(summary.get("errors"), list) else []
        parts: list[str] = []
        for item in errors[:2]:
            if not isinstance(item, dict):
                parts.append(str(item))
                continue
            message = str(item.get("message") or item.get("code") or "").strip()
            details = item.get("details") if isinstance(item.get("details"), dict) else {}
            missing = details.get("missing") if isinstance(details.get("missing"), list) else []
            if not missing and details.get("population_id"):
                missing = [{"role": "target", "label": details.get("population_id")}]
            missing_bits = []
            for row in missing[:4]:
                if not isinstance(row, dict):
                    continue
                label = str(row.get("label") or "").strip()
                if not label:
                    continue
                role = str(row.get("role") or "population").strip()
                missing_bits.append(f"{role}: {label}")
            if missing_bits:
                message = f"{message} ({'; '.join(missing_bits)})" if message else "; ".join(missing_bits)
            if message:
                parts.append(message)
        if parts:
            return " | ".join(parts)
    return fallback.strip() or "qpAdm run failed"


async def show_qpadm_classic_dataset_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE | None = None,
    *,
    edit_existing: bool = True,
    lang: str = "ru",
) -> None:
    await _show_qpadm_entry_dataset_menu(
        message,
        context,
        engine=QPADM_ENGINE_CLASSIC,
        edit_existing=edit_existing,
        lang=lang,
    )


async def show_qpadm_admixtools2_dataset_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE | None = None,
    *,
    edit_existing: bool = True,
    lang: str = "ru",
) -> None:
    await _show_qpadm_entry_dataset_menu(
        message,
        context,
        engine=QPADM_ENGINE_ADMIXTOOLS2,
        edit_existing=edit_existing,
        lang=lang,
    )


async def _show_qpadm_entry_dataset_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE | None,
    *,
    engine: object,
    edit_existing: bool,
    lang: str,
) -> None:
    if context is not None:
        context.user_data.pop(QPADM_FLOW_KEY, None)
        context.user_data.pop(QPADM_ENGINE_KEY, None)
        await _show_qpadm_dataset_menu(message, context, engine=engine, edit_existing=edit_existing, lang=lang)
        return
    title = _qpadm_title(engine)
    text = "\n".join([f"<b>{title}</b>", "", "Context is not available for qpAdm setup."])
    await _show_message(message, text, InlineKeyboardMarkup([_footer_row(nav_back_callback(), lang)]), edit_existing=edit_existing)


async def _show_qpadm_dataset_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    engine: object,
    edit_existing: bool = True,
    lang: str = "ru",
) -> None:
    selected_engine = _qpadm_engine(engine)
    context.user_data[QPADM_ENGINE_KEY] = selected_engine
    nav_enter(context, _cb("qpadm_engine", selected_engine))
    title = _qpadm_title(selected_engine)
    text = "\n".join(
        [
            f"<b>{title}</b>",
            "",
            f"Engine: <code>{html.escape(_qpadm_engine_label(selected_engine))}</code>",
            "",
            "Выберите базу для модели.",
            "После этого выберем target, sources, references и запустим расчет.",
        ]
        if lang != "en"
        else [
            f"<b>{title}</b>",
            "",
            f"Engine: <code>{html.escape(_qpadm_engine_label(selected_engine))}</code>",
            "",
            "Choose the dataset first, then target, sources, references, and run the model.",
        ]
    )
    markup = InlineKeyboardMarkup(
        [
            *[
                [InlineKeyboardButton(label, callback_data=_cb("qpadm_ds", selected_engine, dataset))]
                for dataset, label in dataset_choices()
            ],
            _footer_row(nav_back_callback(), lang),
        ]
    )
    await _show_message(message, text, markup, edit_existing=edit_existing)


async def _show_target_menu(message, context: ContextTypes.DEFAULT_TYPE, *, edit_existing: bool = True, lang: str) -> None:
    flow = _get_flow(context)
    if flow is None:
        await show_qpadm_classic_dataset_menu(message, context, edit_existing=edit_existing, lang=lang)
        return
    nav_enter(context, _cb("qpadm_target"))

    text = "\n".join(
        [
            f"<b>{_flow_title(flow)}</b>",
            "",
            f"Engine: <code>{html.escape(_qpadm_engine_label(flow.get('engine')))}</code>",
            f"Dataset: <code>{html.escape(_dataset_label(flow.get('dataset')))}</code>",
            "",
            "Выберите target: свой sample из My DNA или population из выбранной базы.",
        ]
    )
    if lang == "en":
        text = "\n".join(
            [
                f"<b>{_flow_title(flow)}</b>",
                "",
                f"Engine: <code>{html.escape(_qpadm_engine_label(flow.get('engine')))}</code>",
                f"Dataset: <code>{html.escape(_dataset_label(flow.get('dataset')))}</code>",
                "",
                "Choose the target: one of your samples or a dataset population.",
            ]
        )
    markup = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🧬 My samples", callback_data=_cb("qpadm_target_kind", "sample"))],
            [InlineKeyboardButton("🌐 Dataset populations", callback_data=_cb("qpadm_target_kind", "population"))],
            [InlineKeyboardButton("📋 Импорт Left/Right/Target", callback_data=_cb("qpadm_import"))],
            _footer_row(nav_back_callback(), lang),
        ]
    )
    if _is_admixtools2_engine(flow.get("engine")):
        text = "\n".join(
            [
                f"<b>{_flow_title(flow)}</b>",
                "",
                f"Engine: <code>{html.escape(_qpadm_engine_label(flow.get('engine')))}</code>",
                f"Dataset: <code>{html.escape(_dataset_label(flow.get('dataset')))}</code>",
                "",
                "Выберите target для ADMIXTOOLS2: dataset population(s) или raw sample(s) из My DNA.",
                "Для batch run можно выбрать несколько targets одного типа.",
            ]
        )
    target_markup = _target_menu_markup(flow, lang) if _is_admixtools2_engine(flow.get("engine")) else markup
    await _show_message(message, text, target_markup, edit_existing=edit_existing)


def _safe_page(value: object) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


async def _show_sample_menu(
    message,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    lang: str,
    page: int = 0,
) -> None:
    flow = _get_flow(context)
    user_id = int(update.effective_user.id) if update.effective_user is not None else 0
    store = context.application.bot_data.get("my_data_store")
    samples = []
    if store is not None:
        samples = [sample for sample in store.list_samples(user_id) if getattr(sample, "raw_file_id", "")]

    if not samples:
        nav_enter(context, _cb("qpadm_samples_page", 0))
        text = "\n".join(
            [
                "<b>🧬 My samples</b>",
                "",
                "В My DNA пока нет sample с raw-файлом.",
                "Можно выбрать population из базы или сначала добавить raw в My DNA.",
            ]
        )
        markup = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("🌐 Dataset populations", callback_data=_cb("qpadm_target_kind", "population"))],
                _footer_row(nav_back_callback(), lang),
            ]
        )
        await _show_message(message, text, markup, edit_existing=True)
        return

    page_count = max(1, (len(samples) + QPADM_SAMPLE_PAGE_SIZE - 1) // QPADM_SAMPLE_PAGE_SIZE)
    page = min(max(0, page), page_count - 1)
    nav_enter(context, _cb("qpadm_samples_page", page))
    start = page * QPADM_SAMPLE_PAGE_SIZE
    end = min(len(samples), start + QPADM_SAMPLE_PAGE_SIZE)
    page_samples = samples[start:end]

    rows = [
        [InlineKeyboardButton(_clip(getattr(sample, "display_name", sample.asset_id), 38), callback_data=_cb("qpadm_sample", sample.asset_id))]
        for sample in page_samples
    ]
    if page_count > 1:
        rows.append(page_nav_row(page, page_count, lambda value: _cb("qpadm_samples_page", value)))
    rows.append(_footer_row(nav_back_callback(), lang))

    text = "\n".join(
        [
            "<b>🧬 My samples</b>",
            "",
            f"Dataset: <code>{html.escape(_dataset_label((_get_flow(context) or {}).get('dataset')))}</code>",
            f"Показаны: <code>{start + 1}-{end}</code> из <code>{len(samples)}</code>",
            "Выберите sample как target.",
        ]
    )
    await _show_message(message, text, InlineKeyboardMarkup(rows), edit_existing=True)


async def _select_sample_target(
    message,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    sample_id: str,
    *,
    lang: str,
) -> None:
    flow = _get_flow(context)
    user_id = int(update.effective_user.id) if update.effective_user is not None else 0
    store = context.application.bot_data.get("my_data_store")
    if flow is None or store is None:
        await show_qpadm_classic_dataset_menu(message, context, edit_existing=True, lang=lang)
        return

    sample = store.get_sample(user_id, sample_id)
    if sample is None or not sample.raw_file_id:
        await _show_sample_menu(message, update, context, lang=lang)
        return

    raw_file = store.get_raw_file(user_id, sample.raw_file_id)
    if raw_file is None:
        await _show_sample_menu(message, update, context, lang=lang)
        return

    raw_path = store.resolve_raw_file_path(raw_file)
    _add_raw_target(flow, str(raw_path), sample.display_name)
    _clear_search(flow)
    if _has_complete_model(flow):
        await _show_review_menu(message, context, edit_existing=True, lang=lang)
        return
    await _show_target_ready_menu(message, context, edit_existing=True, lang=lang)


def _state_lines(flow: dict[str, Any]) -> list[str]:
    sources = _as_list(flow, "sources")
    references = _as_list(flow, "references")
    targets = _targets_list(flow)
    target = _target_display(flow)
    target_label = "Targets" if len(targets) > 1 else "Target"
    lines = [
        f"Engine: <code>{html.escape(_qpadm_engine_label(flow.get('engine')))}</code>",
        f"Dataset: <code>{html.escape(_dataset_label(flow.get('dataset')))}</code>",
        f"{target_label}: <code>{html.escape(str(target))}</code>",
        f"Sources: <code>{len(sources)}</code>",
        f"References: <code>{len(references)}</code>",
    ]
    return lines


def _items_lines(title: str, items: list[str], *, limit: int = 8) -> list[str]:
    if not items:
        return [f"<b>{title}</b>", "none"]
    lines = [f"<b>{title}</b>"]
    for item in items:
        lines.append(f"• <code>{html.escape(item)}</code>")
    return lines


async def _show_target_ready_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    edit_existing: bool = True,
    lang: str,
) -> None:
    flow = _get_flow(context)
    if flow is None:
        await show_qpadm_classic_dataset_menu(message, context, edit_existing=edit_existing, lang=lang)
        return
    if not flow.get("target"):
        await _show_target_menu(message, context, edit_existing=edit_existing, lang=lang)
        return
    if not _has_supported_target_for_engine(flow):
        await _show_target_menu(message, context, edit_existing=edit_existing, lang=lang)
        return
    nav_enter(context, _cb("qpadm_target_ready"))

    sources = _as_list(flow, "sources")
    references = _as_list(flow, "references")
    complete = bool(sources and references)
    rows: list[list[InlineKeyboardButton]] = []
    if complete:
        rows.extend(
            [
                [InlineKeyboardButton("🧪 Проверить модель", callback_data=_cb("qpadm_review"))],
                [
                    InlineKeyboardButton("Sources", callback_data=_cb("qpadm_sources")),
                    InlineKeyboardButton("References", callback_data=_cb("qpadm_refs")),
                ],
                [InlineKeyboardButton("💾 Сохранить Source set", callback_data=_cb("ss_save_current"))],
                [InlineKeyboardButton("Заменить Left/Right", callback_data=_cb("qpadm_clear_lr"))],
                [InlineKeyboardButton("Изменить target", callback_data=_cb("qpadm_target"))],
                _footer_row(nav_back_callback(), lang),
            ]
        )
        title = _flow_title(flow, suffix="модель собрана")
        hint = "Модель собрана. Запустите проверку или отредактируйте отдельные части."
    else:
        if sources and not references:
            rows.extend(
                [
                    [InlineKeyboardButton("References", callback_data=_cb("qpadm_refs"))],
                    [InlineKeyboardButton("Sources", callback_data=_cb("qpadm_sources"))],
                    [InlineKeyboardButton("📚 Выбрать Source set", callback_data=_cb("ss_pick"))],
                    [InlineKeyboardButton("📋 Импорт Left/Right", callback_data=_cb("qpadm_import_lr"))],
                ]
            )
            hint = "Sources добавлены. Теперь добавьте References или замените Left/Right целиком."
        elif references and not sources:
            rows.extend(
                [
                    [InlineKeyboardButton("Sources", callback_data=_cb("qpadm_sources"))],
                    [InlineKeyboardButton("References", callback_data=_cb("qpadm_refs"))],
                    [InlineKeyboardButton("📚 Выбрать Source set", callback_data=_cb("ss_pick"))],
                    [InlineKeyboardButton("📋 Импорт Left/Right", callback_data=_cb("qpadm_import_lr"))],
                ]
            )
            hint = "References добавлены. Теперь добавьте Sources или замените Left/Right целиком."
        else:
            rows.extend(
                [
                    [InlineKeyboardButton("📚 Выбрать Source set", callback_data=_cb("ss_pick"))],
                    [InlineKeyboardButton("📋 Импорт Left/Right", callback_data=_cb("qpadm_import_lr"))],
                    [InlineKeyboardButton("🔎 Собрать вручную", callback_data=_cb("qpadm_sources"))],
                ]
            )
            hint = "Добавьте Left/Right: выберите Source set, импортируйте список или соберите вручную."
        rows.extend(
            [
                [InlineKeyboardButton("Изменить target", callback_data=_cb("qpadm_target"))],
                _footer_row(nav_back_callback(), lang),
            ]
        )
        title = _flow_title(flow, suffix="target выбран")

    targets = _targets_list(flow)
    if _is_admixtools2_engine(flow.get("engine")) and targets:
        entries = _target_entries(flow)
        target_rows = [
            [InlineKeyboardButton(f"✕ {_clip(entry['target_label'], 42)}", callback_data=_cb("qpadm_del", "target", index))]
            for index, entry in enumerate(entries[:8])
        ]
        add_callback = _cb("qpadm_samples_page", 0) if flow.get("target_type") == "raw_file" else _cb("qpadm_search", "target")
        rows[0:0] = target_rows
        rows.insert(len(target_rows), [InlineKeyboardButton("➕ Добавить target", callback_data=add_callback)])

    text = "\n".join(
        [
            f"<b>{title}</b>",
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
        await show_qpadm_classic_dataset_menu(message, context, edit_existing=True, lang=lang)
        return
    flow["sources"] = []
    flow["references"] = []
    _clear_search(flow)
    flow.pop("last_notice", None)
    await _show_target_ready_menu(message, context, edit_existing=True, lang=lang)


def _take_notice(flow: dict[str, Any], role: str) -> list[str]:
    notice = flow.pop("last_notice", None)
    if not isinstance(notice, dict) or notice.get("role") != role:
        return []
    added = notice.get("added") if isinstance(notice.get("added"), list) else []
    skipped = notice.get("skipped") if isinstance(notice.get("skipped"), list) else []
    lines: list[str] = []
    if added:
        lines.append(f"Добавлено: <code>{len(added)}</code>")
    if skipped:
        lines.append(f"Пропущено дублей/пересечений: <code>{len(skipped)}</code>")
    return lines


async def _show_sources_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    edit_existing: bool = True,
    lang: str,
) -> None:
    flow = _get_flow(context)
    if flow is None:
        await show_qpadm_classic_dataset_menu(message, context, edit_existing=edit_existing, lang=lang)
        return
    nav_enter(context, _cb("qpadm_sources"))
    sources = _as_list(flow, "sources")
    references = _as_list(flow, "references")
    notice_lines = _take_notice(flow, "source")
    done_label = "К проверке модели" if references else "✅ Sources выбраны"
    done_callback = _cb("qpadm_review") if references else _cb("qpadm_sources_done")
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton("🔎 Добавить source", callback_data=_cb("qpadm_search", "source"))],
    ]
    for index, source in enumerate(sources):
        rows.append([InlineKeyboardButton(f"✕ {_clip(source, 38)}", callback_data=_cb("qpadm_del", "source", index))])
    if sources:
        rows.append([InlineKeyboardButton(done_label, callback_data=done_callback)])
    rows.append(_footer_row(nav_back_callback(), lang))

    text = "\n".join(
        [
            f"<b>{_flow_title(flow, suffix='sources')}</b>",
            "",
            *_state_lines(flow),
            "",
            *_items_lines("Sources", sources),
            *([""] + notice_lines if notice_lines else []),
            "",
            "Добавьте одну или несколько left/source populations.",
            "Можно вставить список строками или через запятую.",
        ]
    )
    await _show_message(message, text, InlineKeyboardMarkup(rows), edit_existing=edit_existing)


async def _show_references_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    edit_existing: bool = True,
    lang: str,
) -> None:
    flow = _get_flow(context)
    if flow is None:
        await show_qpadm_classic_dataset_menu(message, context, edit_existing=edit_existing, lang=lang)
        return
    nav_enter(context, _cb("qpadm_refs"))
    references = _as_list(flow, "references")
    sources = _as_list(flow, "sources")
    notice_lines = _take_notice(flow, "reference")
    done_label = "К проверке модели" if sources else "✅ References выбраны"
    done_callback = _cb("qpadm_review") if sources else _cb("qpadm_refs_done")
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton("🔎 Добавить reference", callback_data=_cb("qpadm_search", "reference"))],
    ]
    for index, reference in enumerate(references):
        rows.append([InlineKeyboardButton(f"✕ {_clip(reference, 38)}", callback_data=_cb("qpadm_del", "reference", index))])
    if references:
        rows.append([InlineKeyboardButton(done_label, callback_data=done_callback)])
    rows.append(_footer_row(nav_back_callback(), lang))

    text = "\n".join(
        [
            f"<b>{_flow_title(flow, suffix='references')}</b>",
            "",
            *_state_lines(flow),
            "",
            *_items_lines("References", references),
            *([""] + notice_lines if notice_lines else []),
            "",
            "Добавьте right/reference populations.",
            "Можно вставить список строками или через запятую.",
        ]
    )
    await _show_message(message, text, InlineKeyboardMarkup(rows), edit_existing=edit_existing)


async def _show_review_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    edit_existing: bool = True,
    lang: str,
) -> None:
    flow = _get_flow(context)
    if flow is None:
        await show_qpadm_classic_dataset_menu(message, context, edit_existing=edit_existing, lang=lang)
        return
    sources = _as_list(flow, "sources")
    references = _as_list(flow, "references")
    if not flow.get("target"):
        await _show_target_menu(message, context, edit_existing=edit_existing, lang=lang)
        return
    if not _has_supported_target_for_engine(flow):
        await _show_target_menu(message, context, edit_existing=edit_existing, lang=lang)
        return
    if not sources:
        await _show_sources_menu(message, context, edit_existing=edit_existing, lang=lang)
        return
    if not references:
        await _show_references_menu(message, context, edit_existing=edit_existing, lang=lang)
        return
    nav_enter(context, _cb("qpadm_review"))

    text = "\n".join(
        [
            f"<b>{_flow_title(flow, suffix='проверка модели')}</b>",
            "",
            *_state_lines(flow),
            "",
            *_items_lines("Sources", sources),
            "",
            *_items_lines("References", references),
        ]
    )
    markup = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🧪 Preflight", callback_data=_cb("qpadm_preflight"))],
            [
                InlineKeyboardButton("Sources", callback_data=_cb("qpadm_sources")),
                InlineKeyboardButton("References", callback_data=_cb("qpadm_refs")),
            ],
            [InlineKeyboardButton("Изменить target", callback_data=_cb("qpadm_target_ready"))],
            [InlineKeyboardButton("💾 Сохранить Source set", callback_data=_cb("ss_save_current"))],
            [InlineKeyboardButton("Начать заново", callback_data=_cb("qpadm_reset"))],
            _footer_row(nav_back_callback(), lang),
        ]
    )
    await _show_message(message, text, markup, edit_existing=edit_existing)


async def _start_population_search(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    role: str,
    *,
    lang: str,
) -> None:
    flow = _get_flow(context)
    if flow is None:
        await show_qpadm_classic_dataset_menu(message, context, edit_existing=True, lang=lang)
        return
    _clear_search(flow)
    flow["awaiting_query"] = role
    flow["awaiting_chat_id"] = int(message.chat_id)
    flow["prompt_chat_id"] = int(message.chat_id)
    flow["prompt_message_id"] = int(message.message_id)

    role_label = _role_label(role, lang)
    text = "\n".join(
        [
            f"<b>🔎 Поиск {html.escape(role_label)}</b>",
            "",
            f"Dataset: <code>{html.escape(_dataset_label(flow.get('dataset')))}</code>",
            "",
            "Напишите часть названия population одним сообщением.",
            "Например: <code>Balkar</code>, <code>Mbuti</code>, <code>Sintashta</code>.",
        ]
    )
    if role == "target" and _is_admixtools2_engine(flow.get("engine")):
        text += "\n\nМожно выбрать несколько populations: нажимайте найденные варианты по очереди или вставьте список строками/через запятую."
    elif role in {"source", "reference"}:
        text += "\n\nМожно вставить сразу список: строками или через запятую."
    markup = InlineKeyboardMarkup([_footer_row(_back_callback_for_role(role), lang)])
    await _show_message(message, text, markup, edit_existing=True)


async def _start_model_import(message, context: ContextTypes.DEFAULT_TYPE, *, lang: str) -> None:
    flow = _get_flow(context)
    if flow is None:
        await show_qpadm_classic_dataset_menu(message, context, edit_existing=True, lang=lang)
        return
    _clear_search(flow)
    flow["awaiting_query"] = "import"
    flow["awaiting_chat_id"] = int(message.chat_id)
    flow["prompt_chat_id"] = int(message.chat_id)
    flow["prompt_message_id"] = int(message.message_id)

    text = "\n".join(
        [
            "<b>📋 Импорт модели</b>",
            "",
            f"Dataset: <code>{html.escape(_dataset_label(flow.get('dataset')))}</code>",
            "",
            "Вставьте модель в формате:",
            "<code>Target=Balkar.HO</code>",
            "<code>Left=Source1,Source2</code>",
            "<code>Right=Ref1,Ref2</code>",
        ]
    )
    await _show_message(message, text, InlineKeyboardMarkup([_footer_row(_cb("qpadm_target"), lang)]), edit_existing=True)


async def _start_left_right_import(message, context: ContextTypes.DEFAULT_TYPE, *, lang: str) -> None:
    flow = _get_flow(context)
    if flow is None:
        await show_qpadm_classic_dataset_menu(message, context, edit_existing=True, lang=lang)
        return
    if not flow.get("target"):
        await _show_target_menu(message, context, edit_existing=True, lang=lang)
        return

    _clear_search(flow)
    flow["awaiting_query"] = "import_lr"
    flow["awaiting_chat_id"] = int(message.chat_id)
    flow["prompt_chat_id"] = int(message.chat_id)
    flow["prompt_message_id"] = int(message.message_id)

    text = "\n".join(
        [
            "<b>📋 Импорт Left/Right</b>",
            "",
            f"Target: <code>{html.escape(_target_display(flow))}</code>",
            f"Dataset: <code>{html.escape(_dataset_label(flow.get('dataset')))}</code>",
            "",
            "Вставьте только Left и Right. Target останется выбранным sample/population.",
            "",
            "<code>Left=Source1,Source2</code>",
            "<code>Right=Ref1,Ref2</code>",
        ]
    )
    await _show_message(message, text, InlineKeyboardMarkup([_footer_row(_cb("qpadm_target_ready"), lang)]), edit_existing=True)


async def qpadm_classic_text_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if update.message is None or update.message.text is None:
        return False
    flow = _get_flow(context)
    if flow is None:
        return False
    role = flow.get("awaiting_query")
    if role not in ROLE_LABELS:
        return False
    chat_id = flow.get("awaiting_chat_id")
    if chat_id is not None and int(chat_id) != int(update.message.chat_id):
        return False

    query_text = update.message.text.strip()
    if not query_text:
        return True

    lang = get_user_language(context, int(update.effective_user.id) if update.effective_user is not None else None)
    imported = _apply_model_import(flow, query_text, allow_target=(role != "import_lr"))
    if imported is not None:
        progress_text = "Импортирую Left/Right..." if role == "import_lr" else "Импортирую модель..."
        progress = await update.message.reply_text(progress_text, do_quote=False)
        if update.effective_chat is not None and update.effective_user is not None:
            set_active_main_menu_message(context, update.effective_chat.id, update.effective_user.id, progress.message_id)
        await _deactivate_prompt_markup(context, flow, progress.message_id)
        flow.pop("prompt_chat_id", None)
        flow.pop("prompt_message_id", None)
        if _has_complete_model(flow):
            await _show_review_menu(progress, context, edit_existing=True, lang=lang)
        else:
            await _show_import_result(progress, context, imported, lang=lang, left_right_only=(role == "import_lr"))
        return True

    if role == "target" and _is_admixtools2_engine(flow.get("engine")) and _looks_like_item_list(query_text):
        progress = await update.message.reply_text("Добавляю targets...", do_quote=False)
        if update.effective_chat is not None and update.effective_user is not None:
            set_active_main_menu_message(context, update.effective_chat.id, update.effective_user.id, progress.message_id)
        await _deactivate_prompt_markup(context, flow, progress.message_id)
        for label in _split_items(query_text):
            if _looks_like_direct_qpadm_label(label):
                _add_dataset_target(flow, _clean_item(label))
        _clear_search(flow)
        if _has_complete_model(flow):
            await _show_review_menu(progress, context, edit_existing=True, lang=lang)
        else:
            await _show_target_ready_menu(progress, context, edit_existing=True, lang=lang)
        return True

    if role in {"source", "reference"} and _looks_like_item_list(query_text):
        progress = await update.message.reply_text("Добавляю список...", do_quote=False)
        if update.effective_chat is not None and update.effective_user is not None:
            set_active_main_menu_message(context, update.effective_chat.id, update.effective_user.id, progress.message_id)
        await _deactivate_prompt_markup(context, flow, progress.message_id)
        result = _merge_role_items(flow, str(role), _split_items(query_text))
        flow["last_notice"] = result
        _clear_search(flow)
        if _has_complete_model(flow):
            flow.pop("last_notice", None)
            await _show_review_menu(progress, context, edit_existing=True, lang=lang)
        elif role == "source":
            await _show_sources_menu(progress, context, edit_existing=True, lang=lang)
        else:
            await _show_references_menu(progress, context, edit_existing=True, lang=lang)
        return True

    if role in {"target", "source", "reference"} and _looks_like_direct_qpadm_label(query_text):
        progress = await update.message.reply_text("Добавляю exact label...", do_quote=False)
        if update.effective_chat is not None and update.effective_user is not None:
            set_active_main_menu_message(context, update.effective_chat.id, update.effective_user.id, progress.message_id)
        await _deactivate_prompt_markup(context, flow, progress.message_id)
        if role == "target":
            label = _clean_item(query_text)
            _add_dataset_target(flow, label)
            _clear_search(flow)
            if _has_complete_model(flow):
                await _show_review_menu(progress, context, edit_existing=True, lang=lang)
            else:
                await _show_target_ready_menu(progress, context, edit_existing=True, lang=lang)
            return True
        result = _merge_role_items(flow, str(role), [_clean_item(query_text)])
        flow["last_notice"] = result
        _clear_search(flow)
        if _has_complete_model(flow):
            flow.pop("last_notice", None)
            await _show_review_menu(progress, context, edit_existing=True, lang=lang)
        elif role == "source":
            await _show_sources_menu(progress, context, edit_existing=True, lang=lang)
        else:
            await _show_references_menu(progress, context, edit_existing=True, lang=lang)
        return True

    if role in {"import", "import_lr"}:
        progress = await update.message.reply_text("Не вижу Left/Right/Target в сообщении.", do_quote=False)
        if update.effective_chat is not None and update.effective_user is not None:
            set_active_main_menu_message(context, update.effective_chat.id, update.effective_user.id, progress.message_id)
        await _deactivate_prompt_markup(context, flow, progress.message_id)
        retry_callback = _cb("qpadm_import_lr") if role == "import_lr" else _cb("qpadm_import")
        back_callback = _cb("qpadm_target_ready") if role == "import_lr" else _cb("qpadm_target")
        hint = (
            "Сообщение должно содержать строки <code>Left=</code> или <code>Right=</code>."
            if role == "import_lr"
            else "Сообщение должно содержать строки <code>Target=</code>, <code>Left=</code> или <code>Right=</code>."
        )
        markup = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("📋 Попробовать еще раз", callback_data=retry_callback)],
                _footer_row(back_callback, lang),
            ]
        )
        await progress.edit_text(
            f"<b>📋 Импорт модели</b>\n\n{hint}",
            reply_markup=markup,
            parse_mode="HTML",
        )
        return True

    searching_text = "Searching populations..." if lang == "en" else "Ищу populations..."
    progress = await update.message.reply_text(searching_text, do_quote=False)
    if update.effective_chat is not None and update.effective_user is not None:
        set_active_main_menu_message(context, update.effective_chat.id, update.effective_user.id, progress.message_id)
    await _deactivate_prompt_markup(context, flow, progress.message_id)

    try:
        results = await _list_populations(str(flow.get("dataset")), query_text, engine=flow.get("engine"))
        flow["search_results"] = results
        flow["search_role"] = role
        flow["awaiting_query"] = None
        flow["awaiting_chat_id"] = None
        flow.pop("prompt_chat_id", None)
        flow.pop("prompt_message_id", None)
        text = _search_results_text(flow, query_text, results, str(role), lang=lang)
        markup = _search_results_keyboard(results, str(role), lang=lang)
        await progress.edit_text(text, reply_markup=markup, parse_mode="HTML")
    except Exception as exc:
        _clear_search(flow)
        text = f"<b>Поиск не прошел</b>\n\n<code>{html.escape(str(exc))}</code>"
        await progress.edit_text(text, reply_markup=InlineKeyboardMarkup([_footer_row(_back_callback_for_role(str(role)), lang)]), parse_mode="HTML")
    return True


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


async def _show_import_result(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    imported: dict[str, Any],
    *,
    lang: str,
    left_right_only: bool = False,
) -> None:
    flow = _get_flow(context)
    if flow is None:
        await show_qpadm_classic_dataset_menu(message, context, edit_existing=True, lang=lang)
        return

    skipped = imported.get("skipped") if isinstance(imported.get("skipped"), list) else []
    title = "📋 Left/Right импортированы" if left_right_only else "📋 Модель импортирована"
    lines = [
        f"<b>{title}</b>",
        "",
        *_state_lines(flow),
    ]
    target_ignored = imported.get("target_ignored")
    if target_ignored:
        lines.extend(["", f"Target из импорта проигнорирован: <code>{html.escape(str(target_ignored))}</code>"])
    if skipped:
        lines.extend(["", f"Пропущено дублей/пересечений: <code>{len(skipped)}</code>"])

    complete = _has_complete_model(flow)
    rows: list[list[InlineKeyboardButton]] = []
    if complete:
        rows.append([InlineKeyboardButton("Проверить модель", callback_data=_cb("qpadm_review"))])
    else:
        next_callback = _cb("qpadm_target_ready") if flow.get("target") else _cb("qpadm_target")
        rows.append([InlineKeyboardButton("Продолжить сборку", callback_data=next_callback)])
    rows.extend(
        [
            [
                InlineKeyboardButton("Sources", callback_data=_cb("qpadm_sources")),
                InlineKeyboardButton("References", callback_data=_cb("qpadm_refs")),
            ],
            _footer_row(_cb("qpadm_target_ready") if flow.get("target") else _cb("qpadm_target"), lang),
        ]
    )
    await _show_message(message, "\n".join(lines), InlineKeyboardMarkup(rows), edit_existing=True)


async def _list_populations(dataset: str, query_text: str, *, engine: object = QPADM_ENGINE_CLASSIC) -> list[dict[str, Any]]:
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
    stdout = await _run_process(args, timeout_seconds=QPADM_SEARCH_TIMEOUT_SECONDS, engine=engine)
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
        results.append(
            {
                "id": population_id,
                "label": label or population_id,
                "sample_count": item.get("sample_count"),
            }
        )
    return results


def _search_results_text(
    flow: dict[str, Any],
    query_text: str,
    results: list[dict[str, Any]],
    role: str,
    *,
    lang: str,
) -> str:
    role_label = _role_label(role, lang)
    lines = [
        f"<b>🔎 Поиск {html.escape(role_label)}</b>",
        "",
        f"Dataset: <code>{html.escape(_dataset_label(flow.get('dataset')))}</code>",
        f"Запрос: <code>{html.escape(query_text)}</code>",
    ]
    if not results:
        lines.extend(["", "Ничего не найдено. Попробуйте другой запрос."])
        return "\n".join(lines)
    lines.extend(["", "Выберите population:"])
    if role == "target" and _is_admixtools2_engine(flow.get("engine")):
        lines[-1] = "Выберите population для добавления в targets:"
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
        rows.append([InlineKeyboardButton(label, callback_data=_cb("qpadm_pick", role, index))])
    rows.append([InlineKeyboardButton("🔎 Новый поиск", callback_data=_cb("qpadm_search", role))])
    rows.append(_footer_row(_back_callback_for_role(role), lang))
    return InlineKeyboardMarkup(rows)


def _back_callback_for_role(role: str) -> str:
    if role == "target":
        return _cb("qpadm_target")
    if role == "source":
        return _cb("qpadm_sources")
    if role == "reference":
        return _cb("qpadm_refs")
    if role == "import_lr":
        return _cb("qpadm_target_ready")
    if role == "import":
        return _cb("qpadm_target")
    return _cb("qpadm")


async def _pick_population(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    role: str,
    index_text: str,
    *,
    lang: str,
) -> None:
    flow = _get_flow(context)
    if flow is None:
        await show_qpadm_classic_dataset_menu(message, context, edit_existing=True, lang=lang)
        return
    results = flow.get("search_results")
    if not isinstance(results, list):
        await _start_population_search(message, context, role, lang=lang)
        return
    try:
        index = int(index_text)
        item = results[index]
    except (ValueError, IndexError, TypeError):
        await _start_population_search(message, context, role, lang=lang)
        return

    population_id = str(item.get("id") or item.get("label"))
    if role == "target":
        _add_dataset_target(flow, population_id)
        _clear_search(flow)
        if _has_complete_model(flow):
            await _show_review_menu(message, context, edit_existing=True, lang=lang)
            return
        await _show_target_ready_menu(message, context, edit_existing=True, lang=lang)
        return

    key = "sources" if role == "source" else "references"
    items = _as_list(flow, key)
    if population_id not in items:
        items.append(population_id)
    flow[key] = items
    _clear_search(flow)
    if role == "source":
        await _show_sources_menu(message, context, edit_existing=True, lang=lang)
        return
    await _show_references_menu(message, context, edit_existing=True, lang=lang)


async def _delete_item(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    role: str,
    index_text: str,
    *,
    lang: str,
) -> None:
    flow = _get_flow(context)
    if flow is None:
        await show_qpadm_classic_dataset_menu(message, context, edit_existing=True, lang=lang)
        return
    if role == "target":
        try:
            _remove_target(flow, int(index_text))
        except ValueError:
            pass
        if _targets_list(flow):
            await _show_target_ready_menu(message, context, edit_existing=True, lang=lang)
        else:
            await _show_target_menu(message, context, edit_existing=True, lang=lang)
        return
    key = "sources" if role == "source" else "references"
    items = _as_list(flow, key)
    try:
        index = int(index_text)
        del items[index]
    except (ValueError, IndexError):
        pass
    flow[key] = items
    if role == "source":
        await _show_sources_menu(message, context, edit_existing=True, lang=lang)
        return
    await _show_references_menu(message, context, edit_existing=True, lang=lang)


def _qpadm_args(flow: dict[str, Any], command: str) -> list[str]:
    args = [
        DNA_PLATFORM_PYTHON,
        "dna_platform.py",
        command,
        "--engine",
        _qpadm_engine(flow.get("engine")),
        "--dataset",
        str(flow.get("dataset")),
        "--target-type",
        str(flow.get("target_type")),
        "--target",
        str(flow.get("target")),
    ]
    for source in _as_list(flow, "sources"):
        args.extend(["--source", source])
    for reference in _as_list(flow, "references"):
        args.extend(["--reference", reference])
    args.extend(["--allsnps", "true", "--inbreed", "false"])
    return args


def _extract_can_run(payload: dict[str, Any]) -> bool:
    for key in ("can_run", "ready"):
        if isinstance(payload.get(key), bool):
            return bool(payload[key])
    for value in payload.values():
        if isinstance(value, dict):
            nested = _extract_can_run(value)
            if nested:
                return True
    return False


def _friendly_warning(value: object, lang: str = "ru") -> str:
    text = str(value)
    lower = text.casefold()
    if "ambiguous snps" in lower and "dropped" in lower:
        if lang == "en":
            return "Ambiguous SNPs were dropped during raw harmonization. This is normal for raw files."
        return "Неоднозначные SNP исключены при harmonization raw-файла. Для raw-файлов это нормально."
    if "strand flips" in lower and "applied" in lower:
        if lang == "en":
            return "Some non-ambiguous variants were strand-flipped during harmonization. This is expected."
        return "Для части SNP применен strand flip при harmonization. Это ожидаемая нормализация."
    return text


def _format_messages(items: object, limit: int = 4, *, lang: str = "ru", friendly: bool = False) -> list[str]:
    if not isinstance(items, list):
        return []
    lines: list[str] = []
    try:
        safe_limit = max(0, int(limit))
    except (TypeError, ValueError):
        safe_limit = 4
    shown_items = items[:safe_limit]
    for item in shown_items:
        if isinstance(item, dict):
            message = item.get("message") or item.get("code") or item
        else:
            message = item
        text = _friendly_warning(message, lang) if friendly else str(message)
        lines.append(f"• {html.escape(text)}")
        if isinstance(item, dict):
            lines.extend(_format_diagnostic_details(item, lang=lang))
    remaining = len(items) - len(shown_items)
    if remaining > 0:
        suffix = f"... and {remaining} more" if lang == "en" else f"... и еще {remaining}"
        lines.append(f"• {html.escape(suffix)}")
    return lines


def _format_diagnostic_details(item: dict[str, Any], *, lang: str) -> list[str]:
    details = item.get("details")
    if not isinstance(details, dict):
        return []
    missing = details.get("missing")
    if not isinstance(missing, list) or not missing:
        population_id = str(details.get("population_id") or "").strip()
        if not population_id:
            return []
        missing = [{"role": "target", "label": population_id}]

    if not missing:
        return []

    header = "  Missing in dataset:" if lang == "en" else "  Нет в dataset:"
    lines = [header]
    detail_limit = 8
    for row in missing[:detail_limit]:
        if not isinstance(row, dict):
            continue
        role = str(row.get("role") or "population")
        label = str(row.get("label") or "").strip()
        if not label:
            continue
        text = f"{role}: {label}"
        suggestions = row.get("suggestions")
        if isinstance(suggestions, list):
            suggestion_labels = [str(value).strip() for value in suggestions[:3] if str(value).strip()]
            if suggestion_labels:
                text = f"{text} (try: {', '.join(suggestion_labels)})"
        lines.append(f"  - {html.escape(text)}")

    remaining = len(missing) - min(len(missing), detail_limit)
    if remaining > 0:
        suffix = f"... and {remaining} more" if lang == "en" else f"... и еще {remaining}"
        lines.append(f"  - {html.escape(suffix)}")
    return lines


def _format_preflight(
    payload: dict[str, Any],
    *,
    elapsed_seconds: float,
    lang: str,
    product_title: str = "qpAdm classic",
) -> tuple[str, bool]:
    can_run = _extract_can_run(payload)
    status = payload.get("status", "unknown")
    engine_status = payload.get("engine_status", "unknown")
    warnings = payload.get("warnings")
    errors = payload.get("errors")
    lines = [
        f"<b>🧪 {html.escape(product_title)} · проверка</b>",
        "",
        f"Статус: <code>{html.escape(str(status))}</code>",
        f"Движок: <code>{html.escape(str(engine_status))}</code>",
        f"Можно запускать: <code>{'да' if can_run else 'нет'}</code>",
        f"Время: <code>{elapsed_seconds:.1f}s</code>",
    ]
    warning_lines = _format_messages(warnings, lang=lang, friendly=True)
    error_lines = _format_messages(errors, lang=lang)
    if warning_lines:
        lines.extend(["", "<b>Предупреждения</b>", *warning_lines])
    if error_lines:
        lines.extend(["", "<b>Ошибки</b>", *error_lines])
    return "\n".join(lines), can_run


def _format_preflight_process_result(
    *,
    returncode: int,
    stdout: str,
    stderr: str,
    elapsed_seconds: float,
    lang: str,
    product_title: str,
) -> tuple[str, bool]:
    try:
        payload = json.loads(stdout)
    except Exception:
        detail = _process_error_detail(returncode, stdout, stderr)
        return f"<b>🧪 {html.escape(product_title)} preflight</b>\n\n<code>{html.escape(detail)}</code>", False
    if not isinstance(payload, dict):
        detail = _process_error_detail(returncode, stdout, stderr)
        return f"<b>🧪 {html.escape(product_title)} preflight</b>\n\n<code>{html.escape(detail)}</code>", False
    return _format_preflight(payload, elapsed_seconds=elapsed_seconds, lang=lang, product_title=product_title)


async def _run_preflight(message, context: ContextTypes.DEFAULT_TYPE, *, lang: str) -> None:
    flow = _get_flow(context)
    if flow is None:
        await show_qpadm_classic_dataset_menu(message, context, edit_existing=True, lang=lang)
        return
    product_title = _qpadm_title(flow.get("engine"), prefix="")

    await _show_message(
        message,
        f"<b>🧪 {html.escape(product_title)} preflight</b>\n\nПроверяю файлы, mapping и параметры...",
        InlineKeyboardMarkup([_footer_row(_cb("qpadm_review"), lang)]),
        edit_existing=True,
    )
    started = time.monotonic()
    try:
        returncode, stdout, stderr = await _run_process_result(
            _qpadm_args(flow, "admixlab-qpadm-preflight"),
            timeout_seconds=QPADM_PREFLIGHT_TIMEOUT_SECONDS,
            engine=flow.get("engine"),
        )
        text, can_run = _format_preflight_process_result(
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
            elapsed_seconds=time.monotonic() - started,
            lang=lang,
            product_title=product_title,
        )
    except Exception as exc:
        can_run = False
        text = f"<b>🧪 {html.escape(product_title)} preflight</b>\n\n<code>{html.escape(str(exc))}</code>"

    rows: list[list[InlineKeyboardButton]] = []
    if can_run:
        run_label = "🚀 Запустить batch" if len(_targets_list(flow)) > 1 else "🚀 Запустить qpAdm"
        rows.append([InlineKeyboardButton(run_label, callback_data=_cb("qpadm_run"))])
    rows.extend(
        [
            [
                InlineKeyboardButton("Sources", callback_data=_cb("qpadm_sources")),
                InlineKeyboardButton("References", callback_data=_cb("qpadm_refs")),
            ],
            _footer_row(_cb("qpadm_review"), lang),
        ]
    )
    await _show_message(message, text, InlineKeyboardMarkup(rows), edit_existing=True)


def _format_qpadm_summary(summary: dict[str, Any], *, elapsed_seconds: float, flow: dict[str, Any], lang: str) -> str:
    target = summary.get("target") if isinstance(summary.get("target"), dict) else {}
    fit = summary.get("fit") if isinstance(summary.get("fit"), dict) else {}
    feasibility = summary.get("feasibility") if isinstance(summary.get("feasibility"), dict) else {}
    weights = summary.get("weights") if isinstance(summary.get("weights"), list) else []
    errors = summary.get("errors") if isinstance(summary.get("errors"), list) else []
    warnings = summary.get("warnings") if isinstance(summary.get("warnings"), list) else []
    engine_display = _qpadm_engine_display(summary.get("engine") or flow.get("engine"))
    target_label = _target_display(flow) or target.get("label") or target.get("display_label")
    references = _as_list(flow, "references")

    lines = [
        f"<b>{_flow_title(flow)}</b>",
        "",
        f"База: <code>{html.escape(_dataset_label(flow.get('dataset')))}</code>",
        f"Статус: <code>{html.escape(str(summary.get('status', 'unknown')))}</code>",
        f"Движок: <code>{html.escape(engine_display)}</code>",
        f"Target: <code>{html.escape(str(target_label or 'unknown'))}</code>",
        f"Fit: <code>{html.escape(str(feasibility.get('status', 'unknown')))}</code>",
        f"p-value: <code>{_format_number(fit.get('p_value'))}</code>",
        f"Время: <code>{elapsed_seconds:.1f}s</code>",
    ]
    if weights:
        lines.extend(["", "<b>Sources</b>"])
        for item in weights:
            if not isinstance(item, dict):
                continue
            source = html.escape(str(item.get("source", "unknown")))
            weight = _format_number(item.get("weight_percent"), percent=True)
            stderr = _format_number(item.get("stderr_percent"), percent=True)
            lines.append(f"<code>{source}</code>: {weight} ± {stderr}")
    if references:
        lines.extend(["", "<b>References</b>"])
        for item in references:
            lines.append(f"• <code>{html.escape(item)}</code>")
    warning_lines = _format_messages(warnings, lang=lang, friendly=True)
    error_lines = _format_messages(errors, lang=lang)
    if warning_lines:
        lines.extend(["", "<b>Предупреждения</b>" if lang != "en" else "<b>Warnings</b>", *warning_lines])
    if errors:
        lines.extend(["", "<b>Ошибки</b>" if lang != "en" else "<b>Errors</b>", *(error_lines or [f"• {len(errors)}"])])
    return "\n".join(lines)


def _format_qpadm_caption(summary: dict[str, Any], *, elapsed_seconds: float, flow: dict[str, Any]) -> str:
    fit = summary.get("fit") if isinstance(summary.get("fit"), dict) else {}
    return "\n".join(
        [
            f"<b>{_flow_title(flow)}</b>",
            f"База: <code>{html.escape(_dataset_label(flow.get('dataset')))}</code>",
            f"Target: <code>{html.escape(_target_display(flow))}</code>",
            f"p-value: <code>{_format_number(fit.get('p_value'))}</code>",
        ]
    )


def _queue_state(context: ContextTypes.DEFAULT_TYPE) -> dict[str, Any]:
    state = context.application.bot_data.get(QPADM_QUEUE_KEY)
    if not isinstance(state, dict):
        state = {
            "semaphore": asyncio.Semaphore(QPADM_MAX_CONCURRENT_JOBS),
            "lock": asyncio.Lock(),
            "pending": [],
            "active": {},
            "next_id": 0,
        }
        context.application.bot_data[QPADM_QUEUE_KEY] = state
    return state


def _queue_markup(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([_footer_row(_cb("qpadm_review"), lang)])


def _result_markup(lang: str, pending_save_id: str | None = None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if pending_save_id:
        rows.append([InlineKeyboardButton("💾 Сохранить результат", callback_data=_cb("saved_save", pending_save_id))])
    rows.extend(
        [
            [InlineKeyboardButton("Новый расчет", callback_data=_cb("qpadm_reset"))],
            [
                InlineKeyboardButton("Sources", callback_data=_cb("qpadm_sources")),
                InlineKeyboardButton("References", callback_data=_cb("qpadm_refs")),
            ],
            [InlineKeyboardButton("💾 Сохранить Source set", callback_data=_cb("ss_save_current"))],
            _footer_row(_cb("qpadm_review"), lang),
        ]
    )
    return InlineKeyboardMarkup(rows)


def _format_queue_text(
    flow: dict[str, Any],
    *,
    job_id: int,
    position: int,
    active_count: int,
) -> str:
    lines = [
        f"<b>{_flow_title(flow, suffix='очередь')}</b>",
        "",
        *_state_lines(flow),
        "",
        f"Задача: <code>#{job_id}</code>",
    ]
    if position > 1 or active_count >= QPADM_MAX_CONCURRENT_JOBS:
        lines.append(f"Место в очереди: <code>{position}</code>")
    if active_count >= QPADM_MAX_CONCURRENT_JOBS:
        lines.append(f"Сейчас считается: <code>{active_count}/{QPADM_MAX_CONCURRENT_JOBS}</code>")
    return "\n".join(lines)


def _format_started_text(flow: dict[str, Any], *, job_id: int, active_count: int) -> str:
    targets = _targets_list(flow)
    mode_line = f"Batch targets: <code>{len(targets)}</code>" if len(targets) > 1 else "Обычно это занимает от минуты до нескольких минут."
    lines = [
        f"<b>{_flow_title(flow, suffix='расчет запущен')}</b>",
        "",
        *_state_lines(flow),
        "",
        mode_line,
    ]
    return "\n".join(lines)


async def _edit_job_message(
    context: ContextTypes.DEFAULT_TYPE,
    entry: dict[str, Any],
    text: str,
    reply_markup: InlineKeyboardMarkup,
) -> bool:
    try:
        await context.bot.edit_message_text(
            chat_id=int(entry["chat_id"]),
            message_id=int(entry["message_id"]),
            text=text,
            reply_markup=reply_markup,
            parse_mode="HTML",
        )
        return True
    except BadRequest:
        return False


async def _send_job_text_fallback(
    context: ContextTypes.DEFAULT_TYPE,
    entry: dict[str, Any],
    text: str,
    reply_markup: InlineKeyboardMarkup,
) -> None:
    if await _edit_job_message(context, entry, text, reply_markup):
        return
    chat_id = int(entry["chat_id"])
    user_id = int(entry["user_id"])
    sent = await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=reply_markup,
        parse_mode="HTML",
    )
    set_active_main_menu_message(context, chat_id, user_id, sent.message_id)


async def _send_job_result(
    context: ContextTypes.DEFAULT_TYPE,
    entry: dict[str, Any],
    text: str,
    reply_markup: InlineKeyboardMarkup,
    *,
    caption: str | None = None,
    visual_path: str | None = None,
) -> None:
    path = Path(visual_path) if visual_path else None
    if path is None or not path.exists():
        await _send_job_text_fallback(context, entry, text, reply_markup)
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
                reply_markup=reply_markup,
                parse_mode="HTML",
            )
        set_active_main_menu_message(context, chat_id, user_id, sent.message_id)
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
        except BadRequest:
            pass
    except Exception:
        await _send_job_text_fallback(context, entry, text, reply_markup)


async def _refresh_pending_messages(context: ContextTypes.DEFAULT_TYPE, pending: list[dict[str, Any]], active_count: int) -> None:
    for position, entry in enumerate(pending, start=1):
        text = _format_queue_text(
            entry["flow"],
            job_id=int(entry["job_id"]),
            position=position,
            active_count=active_count,
        )
        await _edit_job_message(context, entry, text, _queue_markup(str(entry.get("lang") or "ru")))


async def _register_qpadm_job(
    context: ContextTypes.DEFAULT_TYPE,
    entry: dict[str, Any],
) -> tuple[int, int, int]:
    state = _queue_state(context)
    async with state["lock"]:
        state["next_id"] = int(state.get("next_id") or 0) + 1
        entry["job_id"] = state["next_id"]
        state["pending"].append(entry)
        return int(entry["job_id"]), len(state["pending"]), len(state["active"])


async def _qpadm_worker(context: ContextTypes.DEFAULT_TYPE, entry: dict[str, Any]) -> None:
    state = _queue_state(context)
    semaphore = state["semaphore"]
    job_id = int(entry["job_id"])
    async with semaphore:
        async with state["lock"]:
            state["pending"] = [item for item in state["pending"] if int(item.get("job_id") or 0) != job_id]
            state["active"][job_id] = entry
            pending_snapshot = list(state["pending"])
            active_count = len(state["active"])

        await _refresh_pending_messages(context, pending_snapshot, active_count)
        await _edit_job_message(
            context,
            entry,
            _format_started_text(entry["flow"], job_id=job_id, active_count=active_count),
            _queue_markup(str(entry.get("lang") or "ru")),
        )

        pending_save_id: str | None = None
        caption: str | None = None
        visual_path: str | None = None
        try:
            text, save_payload = await _run_qpadm_job(
                entry["flow"],
                int(entry["user_id"]),
                job_id=job_id,
                lang=str(entry.get("lang") or "ru"),
            )
            pending_save_id = register_pending_save(context, int(entry["user_id"]), save_payload)
            caption = str(save_payload.get("caption_text") or "")
            visual_path = str(save_payload.get("visual_path") or "")
        except Exception as exc:
            text = f"<b>{html.escape(_flow_title(entry['flow'], prefix=''))} не прошел</b>\n\n<code>{html.escape(str(exc))}</code>"

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


async def _run_qpadm_job(flow: dict[str, Any], user_id: int, *, job_id: int, lang: str) -> tuple[str, dict[str, Any]]:
    if _is_admixtools2_engine(flow.get("engine")) and len(_targets_list(flow)) > 1:
        return await _run_qpadm_batch_job(flow, user_id, job_id=job_id, lang=lang)

    BOT_QPADM_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    engine = _qpadm_engine(flow.get("engine"))
    output_prefix = "admixtools2" if engine == QPADM_ENGINE_ADMIXTOOLS2 else "classic"
    output_path = BOT_QPADM_OUTPUT_DIR / f"{output_prefix}_{user_id}_{int(time.time())}_{job_id}.json"
    started = time.monotonic()
    run_args = _qpadm_args(flow, "admixlab-run-qpadm")
    run_args.extend(["--details", "--summary", "--output", str(output_path)])
    returncode, stdout, stderr = await _run_process_result(run_args, timeout_seconds=QPADM_TIMEOUT_SECONDS, engine=flow.get("engine"))
    if returncode != 0 and not output_path.exists():
        raise RuntimeError(_process_error_detail(returncode, stdout, stderr))
    try:
        summary_payload = await _load_qpadm_summary(output_path, engine=flow.get("engine"))
    except Exception:
        if returncode != 0:
            raise RuntimeError(_process_error_detail(returncode, stdout, stderr))
        raise
    elapsed = time.monotonic() - started
    text = _format_qpadm_summary(summary_payload, elapsed_seconds=elapsed, flow=flow, lang=lang)
    caption = _format_qpadm_caption(summary_payload, elapsed_seconds=elapsed, flow=flow)
    visual_path: Path | None = None
    visual_error: str | None = None
    try:
        visual_path = render_qpadm_result(summary_payload, flow=flow, elapsed_seconds=elapsed, output_dir=BOT_QPADM_OUTPUT_DIR)
    except Exception as exc:
        visual_error = str(exc)
    save_payload = {
        "kind": "qpadm_classic",
        "engine": engine,
        "engine_label": _qpadm_engine_label(engine),
        "title": f"{_target_display(flow)} · {_dataset_label(flow.get('dataset'))}",
        "dataset": flow.get("dataset"),
        "target": _target_display(flow),
        "sources": _as_list(flow, "sources"),
        "references": _as_list(flow, "references"),
        "result_text": text,
        "caption_text": caption,
        "visual_path": str(visual_path or ""),
        "visual_error": visual_error,
        "result_payload": summary_payload,
        "output_path": str(output_path),
    }
    return text, save_payload


def _flow_for_target(flow: dict[str, Any], target: object) -> dict[str, Any]:
    if isinstance(target, dict):
        target_type = str(target.get("target_type") or flow.get("target_type") or "dataset_population")
        target_value = str(target.get("target") or "")
        target_label = str(target.get("target_label") or target_value)
    else:
        target_type = str(flow.get("target_type") or "dataset_population")
        if target_type not in {"dataset_population", "raw_file"}:
            target_type = "dataset_population"
        target_value = str(target)
        target_label = str(target)
    single = dict(flow)
    single["target_type"] = target_type
    single["target"] = target_value
    single["target_label"] = target_label
    single["targets"] = [target_value]
    single["target_labels"] = [target_label]
    return single


def _format_qpadm_batch_summary(batch_payload: dict[str, Any], *, flow: dict[str, Any], elapsed_seconds: float, lang: str) -> str:
    results = batch_payload.get("results") if isinstance(batch_payload.get("results"), list) else []
    completed = sum(1 for item in results if isinstance(item, dict) and item.get("status") == "completed")
    lines = [
        f"<b>{_flow_title(flow, suffix='batch')}</b>",
        "",
        f"База: <code>{html.escape(_dataset_label(flow.get('dataset')))}</code>",
        f"Targets: <code>{completed}/{len(results)}</code>",
        f"Время: <code>{elapsed_seconds:.1f}s</code>",
        "",
        "<b>Results</b>",
    ]
    for item in results:
        if not isinstance(item, dict):
            continue
        target = str(item.get("target_label") or item.get("target") or "unknown")
        status = str(item.get("status") or "unknown")
        if status != "completed":
            error = str(item.get("error") or status)
            lines.append(f"• <code>{html.escape(target)}</code>: <code>{html.escape(error)}</code>")
            continue
        summary = item.get("summary") if isinstance(item.get("summary"), dict) else {}
        fit = summary.get("fit") if isinstance(summary.get("fit"), dict) else {}
        feasibility = summary.get("feasibility") if isinstance(summary.get("feasibility"), dict) else {}
        p_value = _format_number(fit.get("p_value"))
        fit_status = html.escape(str(feasibility.get("status", "unknown")))
        reason = str(feasibility.get("reason") or "").strip()
        reason_text = f", reason=<code>{html.escape(reason)}</code>" if reason and fit_status.upper() != "PASS" else ""
        lines.append(f"• <code>{html.escape(target)}</code>: p=<code>{p_value}</code>, fit=<code>{fit_status}</code>{reason_text}")
    return "\n".join(lines)


def _format_qpadm_batch_caption(batch_payload: dict[str, Any], *, flow: dict[str, Any], elapsed_seconds: float) -> str:
    results = batch_payload.get("results") if isinstance(batch_payload.get("results"), list) else []
    completed = sum(1 for item in results if isinstance(item, dict) and item.get("status") == "completed")
    return "\n".join(
        [
            f"<b>{_flow_title(flow, suffix='batch')}</b>",
            f"База: <code>{html.escape(_dataset_label(flow.get('dataset')))}</code>",
            f"Targets: <code>{completed}/{len(results)}</code>",
        ]
    )


async def _run_qpadm_batch_job(flow: dict[str, Any], user_id: int, *, job_id: int, lang: str) -> tuple[str, dict[str, Any]]:
    BOT_QPADM_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    engine = _qpadm_engine(flow.get("engine"))
    started = time.monotonic()
    batch_results: list[dict[str, Any]] = []
    target_entries = _target_entries(flow)
    targets = [entry["target"] for entry in target_entries]

    for index, target_entry in enumerate(target_entries, start=1):
        single_flow = _flow_for_target(flow, target_entry)
        output_path = BOT_QPADM_OUTPUT_DIR / f"admixtools2_batch_{user_id}_{int(time.time())}_{job_id}_{index}.json"
        run_args = _qpadm_args(single_flow, "admixlab-run-qpadm")
        run_args.extend(["--details", "--summary", "--output", str(output_path)])
        try:
            returncode, stdout, stderr = await _run_process_result(run_args, timeout_seconds=QPADM_TIMEOUT_SECONDS, engine=engine)
            summary_payload = None
            if output_path.exists():
                try:
                    summary_payload = await _load_qpadm_summary(output_path, engine=engine)
                except Exception:
                    summary_payload = None
            if returncode != 0:
                fallback = _process_error_detail(returncode, stdout, stderr)
                raise RuntimeError(_summary_error_detail(summary_payload, fallback))
            if summary_payload is None:
                summary_payload = await _load_qpadm_summary(output_path, engine=engine)
            batch_results.append(
                {
                    "target": target_entry["target"],
                    "target_label": target_entry["target_label"],
                    "target_type": target_entry["target_type"],
                    "status": "completed",
                    "summary": summary_payload,
                    "output_path": str(output_path),
                }
            )
        except Exception as exc:
            batch_results.append(
                {
                    "target": target_entry["target"],
                    "target_label": target_entry["target_label"],
                    "target_type": target_entry["target_type"],
                    "status": "failed",
                    "error": str(exc),
                    "output_path": str(output_path),
                }
            )

    elapsed = time.monotonic() - started
    batch_payload = {
        "status": "completed" if all(item.get("status") == "completed" for item in batch_results) else "partial",
        "engine": engine,
        "dataset": flow.get("dataset"),
        "targets": targets,
        "target_entries": target_entries,
        "sources": _as_list(flow, "sources"),
        "references": _as_list(flow, "references"),
        "results": batch_results,
    }
    text = _format_qpadm_batch_summary(batch_payload, elapsed_seconds=elapsed, flow=flow, lang=lang)
    caption = _format_qpadm_batch_caption(batch_payload, elapsed_seconds=elapsed, flow=flow)
    visual_path: Path | None = None
    visual_error: str | None = None
    try:
        visual_path = render_admixtools2_qpadm_batch_result(
            batch_payload,
            flow=flow,
            elapsed_seconds=elapsed,
            output_dir=BOT_QPADM_OUTPUT_DIR,
        )
    except Exception as exc:
        visual_error = str(exc)
    save_payload = {
        "kind": "qpadm_batch",
        "engine": engine,
        "engine_label": _qpadm_engine_label(engine),
        "title": f"{len(targets)} targets · {_dataset_label(flow.get('dataset'))}",
        "dataset": flow.get("dataset"),
        "target": _target_display(flow),
        "targets": targets,
        "sources": _as_list(flow, "sources"),
        "references": _as_list(flow, "references"),
        "result_text": text,
        "caption_text": caption,
        "visual_path": str(visual_path or ""),
        "visual_error": visual_error,
        "result_payload": batch_payload,
        "output_path": "",
    }
    return text, save_payload


async def _enqueue_qpadm(message, update: Update, context: ContextTypes.DEFAULT_TYPE, *, lang: str) -> None:
    flow = _get_flow(context)
    if flow is None:
        await show_qpadm_classic_dataset_menu(message, context, edit_existing=True, lang=lang)
        return
    if not flow.get("target") or not _as_list(flow, "sources") or not _as_list(flow, "references"):
        await _show_review_menu(message, context, edit_existing=True, lang=lang)
        return
    if not _has_supported_target_for_engine(flow):
        await _show_target_menu(message, context, edit_existing=True, lang=lang)
        return

    frozen_flow = _snapshot_flow(flow)
    user_id = int(update.effective_user.id) if update.effective_user is not None else 0
    entry: dict[str, Any] = {
        "chat_id": int(message.chat_id),
        "message_id": int(message.message_id),
        "user_id": user_id,
        "lang": lang,
        "flow": frozen_flow,
    }
    job_id, position, active_count = await _register_qpadm_job(context, entry)
    await _show_message(
        message,
        _format_queue_text(frozen_flow, job_id=job_id, position=position, active_count=active_count),
        _queue_markup(lang),
        edit_existing=True,
    )
    context.application.create_task(_qpadm_worker(context, entry))


async def qpadm_classic_callback_handler(
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

    if action == "qpadm_engine" and len(parts) >= 3:
        engine = _qpadm_engine(parts[2])
        await _show_qpadm_dataset_menu(message, context, engine=engine, edit_existing=True, lang=lang)
        return

    if action == "qpadm_ds" and len(parts) >= 3:
        if len(parts) >= 4 and _is_qpadm_engine(parts[2]):
            engine = _qpadm_engine(parts[2])
            dataset = parts[3]
        else:
            engine = _qpadm_engine(context.user_data.get(QPADM_ENGINE_KEY))
            dataset = parts[2]
        if dataset not in DATASET_LABELS:
            await _show_qpadm_dataset_menu(message, context, engine=engine, edit_existing=True, lang=lang)
            return
        _start_flow(context, dataset, engine=engine)
        await _show_target_menu(message, context, edit_existing=True, lang=lang)
        return

    if action == "qpadm_target":
        await _show_target_menu(message, context, edit_existing=True, lang=lang)
        return

    if action == "qpadm_target_ready":
        await _show_target_ready_menu(message, context, edit_existing=True, lang=lang)
        return

    if action == "qpadm_import":
        await _start_model_import(message, context, lang=lang)
        return

    if action == "qpadm_import_lr":
        await _start_left_right_import(message, context, lang=lang)
        return

    if action == "qpadm_clear_lr":
        await _clear_left_right(message, context, lang=lang)
        return

    if action == "qpadm_target_kind" and len(parts) >= 3:
        kind = parts[2]
        if kind == "sample":
            await _show_sample_menu(message, update, context, lang=lang, page=0)
            return
        if kind == "population":
            await _start_population_search(message, context, "target", lang=lang)
            return

    if action == "qpadm_samples_page" and len(parts) >= 3:
        await _show_sample_menu(message, update, context, lang=lang, page=_safe_page(parts[2]))
        return

    if action == "qpadm_sample" and len(parts) >= 3:
        await _select_sample_target(message, update, context, parts[2], lang=lang)
        return

    if action == "qpadm_search" and len(parts) >= 3:
        role = parts[2]
        if role in ROLE_LABELS:
            await _start_population_search(message, context, role, lang=lang)
        return

    if action == "qpadm_pick" and len(parts) >= 4:
        await _pick_population(message, context, parts[2], parts[3], lang=lang)
        return

    if action == "qpadm_del" and len(parts) >= 4:
        await _delete_item(message, context, parts[2], parts[3], lang=lang)
        return

    if action == "qpadm_sources":
        await _show_sources_menu(message, context, edit_existing=True, lang=lang)
        return

    if action == "qpadm_sources_done":
        flow = _get_flow(context)
        if flow is not None and _has_complete_model(flow):
            await _show_review_menu(message, context, edit_existing=True, lang=lang)
            return
        await _show_references_menu(message, context, edit_existing=True, lang=lang)
        return

    if action == "qpadm_refs":
        await _show_references_menu(message, context, edit_existing=True, lang=lang)
        return

    if action == "qpadm_refs_done" or action == "qpadm_review":
        await _show_review_menu(message, context, edit_existing=True, lang=lang)
        return

    if action == "qpadm_preflight":
        await _run_preflight(message, context, lang=lang)
        return

    if action == "qpadm_run":
        await _enqueue_qpadm(message, update, context, lang=lang)
        return

    if action == "qpadm_reset":
        flow = _get_flow(context) or {}
        engine = _qpadm_engine(flow.get("engine") or context.user_data.get(QPADM_ENGINE_KEY))
        nav_reset(context, _cb("at2" if engine == QPADM_ENGINE_ADMIXTOOLS2 else "root"))
        await _show_qpadm_entry_dataset_menu(
            message,
            context,
            engine=engine,
            edit_existing=True,
            lang=lang,
        )
        return

    await show_qpadm_classic_dataset_menu(message, context, edit_existing=True, lang=lang)
