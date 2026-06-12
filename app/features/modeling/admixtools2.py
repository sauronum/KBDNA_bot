from __future__ import annotations

import asyncio
import html
import json
import os
import time
from pathlib import Path
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.features.modeling.navigation import nav_back_callback, nav_enter, nav_reset
from app.features.modeling.ui import footer_row as _footer_row
from app.features.modeling.ui import modeling_cb as _cb
from app.features.modeling.ui import show_message as _show_message
from app.heavy_runtime import heavy_command
from app.i18n import get_user_language
from app.main_menu import set_active_main_menu_message


AT2_FSTATS_FLOW_KEY = "admixtools2_fstats_flow"

DNA_PLATFORM_ROOT = Path(os.getenv("DNA_PLATFORM_ROOT", "/srv/dna_platform"))
BOT_AT2_OUTPUT_DIR = Path(os.getenv("KBDNA_AT2_OUTPUT_DIR", str(DNA_PLATFORM_ROOT / "output" / "admixlab" / "bot" / "at2")))
AT2_QPADM_CONFIG = Path(os.getenv("ADMIXLAB_QPADM_ADMIXTOOLS2_BACKEND_CONFIG", "/etc/admixlab/qpadm_backend_config.admixtools2.json"))
AT2_RUNNER = Path(__file__).with_name("admixtools2_runner.R")
AT2_TIMEOUT_SECONDS = int(os.getenv("KBDNA_AT2_TIMEOUT_SECONDS", "7200"))
AT2_FSTATS_TIMEOUT_SECONDS = int(os.getenv("KBDNA_AT2_FSTATS_TIMEOUT_SECONDS", "1800"))

DATASET_LABELS = {
    "v62_1240k_public": "v62 1240k public",
    "human_origins": "Human Origins",
}
FSTAT_ARITIES = {"f2": 2, "f3": 3, "f4": 4}


def _dataset_label(dataset: object) -> str:
    value = str(dataset or "")
    return DATASET_LABELS.get(value, value or "not selected")


def _safe_name(value: object) -> str:
    text = str(value or "").strip()
    return "".join(char if char.isalnum() or char in "._-" else "_" for char in text)[:80] or "at2"


def _load_at2_config() -> dict[str, Any]:
    try:
        payload = json.loads(AT2_QPADM_CONFIG.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _dataset_files(dataset: str) -> dict[str, Any]:
    config = _load_at2_config()
    datasets = config.get("datasets")
    if not isinstance(datasets, dict):
        return {}
    row = datasets.get(dataset)
    if not isinstance(row, dict):
        return {}
    files = row.get("required_files")
    return dict(files) if isinstance(files, dict) else {}


def _format_bytes(size: int) -> str:
    value = float(max(0, size))
    for suffix in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or suffix == "TB":
            return f"{value:.1f} {suffix}" if suffix != "B" else f"{int(value)} B"
        value /= 1024
    return f"{value:.1f} TB"


def _dir_size(path: Path, *, max_files: int = 4000) -> tuple[int, int]:
    total = 0
    count = 0
    try:
        for root, _dirs, files in os.walk(path):
            for filename in files:
                count += 1
                if count > max_files:
                    return total, count
                try:
                    total += (Path(root) / filename).stat().st_size
                except OSError:
                    continue
    except OSError:
        return 0, 0
    return total, count


def _cache_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    config = _load_at2_config()
    datasets = config.get("datasets")
    if not isinstance(datasets, dict):
        return rows
    for dataset, dataset_payload in datasets.items():
        if not isinstance(dataset_payload, dict):
            continue
        files = dataset_payload.get("required_files")
        if not isinstance(files, dict):
            continue
        cache_dir = Path(str(files.get("f2_cache_dir") or files.get("f2_cache") or ""))
        entries = []
        latest_mtime = None
        if cache_dir.exists():
            try:
                entries = [item for item in cache_dir.iterdir() if item.is_dir() and item.name.startswith("f2_")]
            except OSError:
                entries = []
            for entry in entries:
                try:
                    mtime = entry.stat().st_mtime
                except OSError:
                    continue
                latest_mtime = mtime if latest_mtime is None else max(latest_mtime, mtime)
        size, file_count = _dir_size(cache_dir) if cache_dir.exists() else (0, 0)
        rows.append(
            {
                "dataset": str(dataset),
                "path": str(cache_dir),
                "exists": cache_dir.exists(),
                "entries": len(entries),
                "size": size,
                "file_count": file_count,
                "latest_mtime": latest_mtime,
            }
        )
    return rows


def _format_cache_status(lang: str = "ru") -> str:
    rows = _cache_rows()
    lines = ["<b>📦 f2 cache</b>", "", f"Config: <code>{html.escape(str(AT2_QPADM_CONFIG))}</code>"]
    if not rows:
        lines.extend(["", "Cache config не найден или пока пуст."])
        return "\n".join(lines)
    lines.extend(["", "<b>Datasets</b>"])
    for row in rows:
        latest = "none"
        if isinstance(row.get("latest_mtime"), (int, float)):
            latest = time.strftime("%Y-%m-%d %H:%M", time.localtime(float(row["latest_mtime"])))
        status = "ready" if row.get("exists") else "missing"
        lines.extend(
            [
                f"• <b>{html.escape(_dataset_label(row.get('dataset')))}</b> · <code>{status}</code>",
                f"  caches: <code>{int(row.get('entries') or 0)}</code>, size: <code>{_format_bytes(int(row.get('size') or 0))}</code>, files: <code>{int(row.get('file_count') or 0)}</code>",
                f"  latest: <code>{html.escape(latest)}</code>",
            ]
        )
    return "\n".join(lines)


async def show_f2_cache_status(
    message,
    context: ContextTypes.DEFAULT_TYPE | None,
    *,
    edit_existing: bool = True,
    lang: str = "ru",
) -> None:
    nav_enter(context, _cb("at2_f2_cache"))
    markup = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🔄 Refresh", callback_data=_cb("at2_f2_cache"))],
            _footer_row(_cb("at2"), lang),
        ]
    )
    await _show_message(message, _format_cache_status(lang), markup, edit_existing=edit_existing)


async def run_admixtools2_runner(payload: dict[str, Any], *, timeout_seconds: int = AT2_TIMEOUT_SECONDS) -> dict[str, Any]:
    if not AT2_RUNNER.exists():
        raise RuntimeError(f"ADMIXTOOLS2 runner not found: {AT2_RUNNER}")
    BOT_AT2_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    request_path = BOT_AT2_OUTPUT_DIR / f"request_{_safe_name(payload.get('command'))}_{int(time.time() * 1000)}.json"
    request_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    proc = await asyncio.create_subprocess_exec(
        *heavy_command(["Rscript", str(AT2_RUNNER), "--request", str(request_path)]),
        cwd=str(DNA_PLATFORM_ROOT),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        raise RuntimeError("ADMIXTOOLS2 runner timed out")
    stdout = stdout_bytes.decode("utf-8", errors="replace")
    stderr = stderr_bytes.decode("utf-8", errors="replace")
    try:
        result = json.loads(stdout)
    except Exception as exc:
        detail = (stderr or stdout).strip().splitlines()[-12:]
        raise RuntimeError("\n".join(detail) or f"ADMIXTOOLS2 runner emitted invalid JSON: {exc}")
    if not isinstance(result, dict):
        raise RuntimeError("ADMIXTOOLS2 runner emitted a non-object JSON response")
    if result.get("status") == "error":
        errors = result.get("errors") if isinstance(result.get("errors"), list) else []
        messages = [str(item.get("message")) for item in errors if isinstance(item, dict) and item.get("message")]
        raise RuntimeError("\n".join(messages) or "ADMIXTOOLS2 runner failed")
    return result


def _new_fstats_flow(dataset: str) -> dict[str, Any]:
    return {"dataset": dataset, "statistic": "f4", "populations": [], "awaiting": None}


def _get_fstats_flow(context: ContextTypes.DEFAULT_TYPE) -> dict[str, Any] | None:
    flow = context.user_data.get(AT2_FSTATS_FLOW_KEY)
    return flow if isinstance(flow, dict) else None


def _fstats_arity(flow: dict[str, Any]) -> int:
    return FSTAT_ARITIES.get(str(flow.get("statistic") or "f4"), 4)


def _parse_populations(text: str, expected: int) -> list[str]:
    values: list[str] = []
    keyed: dict[str, str] = {}
    for raw_line in re_split_items(text):
        if "=" in raw_line:
            key, value = raw_line.split("=", 1)
            keyed[key.strip().lower()] = value.strip()
        else:
            values.append(raw_line.strip())
    if keyed:
        values = [keyed.get(f"pop{index}") or keyed.get(f"p{index}") or "" for index in range(1, expected + 1)]
    return [value for value in values[:expected] if value]


def re_split_items(text: str) -> list[str]:
    import re

    return [item.strip().strip(",;") for item in re.split(r"[\n,;]+", text) if item.strip().strip(",;")]


def _fstats_state_lines(flow: dict[str, Any]) -> list[str]:
    stat = str(flow.get("statistic") or "f4")
    pops = [str(item) for item in flow.get("populations", []) if str(item)]
    expected = _fstats_arity(flow)
    lines = [
        f"Dataset: <code>{html.escape(_dataset_label(flow.get('dataset')))}</code>",
        f"Statistic: <code>{html.escape(stat)}</code>",
        f"Populations: <code>{len(pops)}/{expected}</code>",
    ]
    for index, pop in enumerate(pops, start=1):
        lines.append(f"p{index}: <code>{html.escape(pop)}</code>")
    return lines


async def show_fstats_dataset_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE | None,
    *,
    edit_existing: bool = True,
    lang: str = "ru",
) -> None:
    if context is not None:
        context.user_data.pop(AT2_FSTATS_FLOW_KEY, None)
        nav_enter(context, _cb("at2_fstats_ds"))
    markup = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("v62 / 1240k public", callback_data=_cb("at2_fstats_ds_pick", "v62_1240k_public"))],
            [InlineKeyboardButton("Human Origins", callback_data=_cb("at2_fstats_ds_pick", "human_origins"))],
            _footer_row(nav_back_callback(), lang),
        ]
    )
    await _show_message(message, "<b>📊 f-statistics</b>\n\nВыберите dataset.", markup, edit_existing=edit_existing)


async def _show_fstats_builder(message, context: ContextTypes.DEFAULT_TYPE, *, edit_existing: bool = True, lang: str = "ru") -> None:
    flow = _get_fstats_flow(context)
    if flow is None:
        await show_fstats_dataset_menu(message, context, edit_existing=edit_existing, lang=lang)
        return
    nav_enter(context, _cb("at2_fstats_builder"))
    ready = len([item for item in flow.get("populations", []) if str(item)]) >= _fstats_arity(flow)
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton("f2", callback_data=_cb("at2_fstats_type", "f2")),
            InlineKeyboardButton("f3", callback_data=_cb("at2_fstats_type", "f3")),
            InlineKeyboardButton("f4", callback_data=_cb("at2_fstats_type", "f4")),
        ],
        [InlineKeyboardButton("📝 Populations", callback_data=_cb("at2_fstats_pops"))],
    ]
    if ready:
        rows.append([InlineKeyboardButton("🚀 Run f-statistics", callback_data=_cb("at2_fstats_run"))])
    rows.extend([[InlineKeyboardButton("Начать заново", callback_data=_cb("at2_fstats"))], _footer_row(nav_back_callback(), lang)])
    text = "\n".join(
        [
            "<b>📊 f-statistics</b>",
            "",
            *_fstats_state_lines(flow),
            "",
            "Введите populations списком или через pop1=, pop2=, pop3=, pop4=.",
        ]
    )
    await _show_message(message, text, InlineKeyboardMarkup(rows), edit_existing=edit_existing)


async def _prompt_fstats_populations(message, context: ContextTypes.DEFAULT_TYPE, *, lang: str) -> None:
    flow = _get_fstats_flow(context)
    if flow is None:
        await show_fstats_dataset_menu(message, context, edit_existing=True, lang=lang)
        return
    flow["awaiting"] = "populations"
    expected = _fstats_arity(flow)
    labels = ", ".join(f"pop{index}" for index in range(1, expected + 1))
    await _show_message(
        message,
        "\n".join(
            [
                "<b>📊 f-statistics · populations</b>",
                "",
                f"Statistic: <code>{html.escape(str(flow.get('statistic')))}</code>",
                f"Нужно: <code>{html.escape(labels)}</code>",
                "",
                "Вставьте labels одним сообщением.",
            ]
        ),
        InlineKeyboardMarkup([_footer_row(_cb("at2_fstats_builder"), lang)]),
        edit_existing=True,
    )


def _format_fstats_result(payload: dict[str, Any], *, flow: dict[str, Any], elapsed_seconds: float) -> str:
    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    rows = result.get("rows") if isinstance(result.get("rows"), list) else []
    lines = [
        "<b>📊 f-statistics</b>",
        "",
        f"Dataset: <code>{html.escape(_dataset_label(flow.get('dataset')))}</code>",
        f"Statistic: <code>{html.escape(str(flow.get('statistic')))}</code>",
        f"Status: <code>{html.escape(str(payload.get('status') or 'completed'))}</code>",
        f"Time: <code>{elapsed_seconds:.1f}s</code>",
    ]
    if rows:
        lines.extend(["", "<b>Results</b>"])
    for row in rows[:8]:
        if not isinstance(row, dict):
            continue
        value = row.get("est", row.get("estimate", row.get("f4", row.get("f3", row.get("f2")))))
        se = row.get("se")
        z = row.get("z")
        p = row.get("p")
        bits = [f"value=<code>{html.escape(_num(value))}</code>"]
        if se is not None:
            bits.append(f"se=<code>{html.escape(_num(se))}</code>")
        if z is not None:
            bits.append(f"z=<code>{html.escape(_num(z))}</code>")
        if p is not None:
            bits.append(f"p=<code>{html.escape(_num(p))}</code>")
        lines.append("• " + ", ".join(bits))
    if len(rows) > 8:
        lines.append(f"• ... and {len(rows) - 8} more")
    lines.extend(["", *_fstats_state_lines(flow)])
    return "\n".join(lines)


def _num(value: object) -> str:
    if isinstance(value, list) and value:
        value = value[0]
    try:
        return f"{float(value):.6g}"
    except (TypeError, ValueError):
        return str(value)


async def _run_fstats(message, context: ContextTypes.DEFAULT_TYPE, *, lang: str) -> None:
    flow = _get_fstats_flow(context)
    if flow is None:
        await show_fstats_dataset_menu(message, context, edit_existing=True, lang=lang)
        return
    populations = [str(item) for item in flow.get("populations", []) if str(item)]
    if len(populations) < _fstats_arity(flow):
        await _show_fstats_builder(message, context, edit_existing=True, lang=lang)
        return
    dataset = str(flow.get("dataset") or "")
    dataset_files = _dataset_files(dataset)
    if not dataset_files:
        await _show_message(message, "<b>📊 f-statistics</b>\n\nDataset files не найдены.", InlineKeyboardMarkup([_footer_row(_cb("at2_fstats_builder"), lang)]), edit_existing=True)
        return
    await _show_message(message, "<b>📊 f-statistics</b>\n\nСчитаю ADMIXTOOLS2...", InlineKeyboardMarkup([_footer_row(_cb("at2_fstats_builder"), lang)]), edit_existing=True)
    started = time.monotonic()
    payload = await run_admixtools2_runner(
        {
            "command": "fstats",
            "dataset": dataset,
            "dataset_files": dataset_files,
            "statistic": str(flow.get("statistic") or "f4"),
            "populations": populations,
            "options": {"boot": True},
        },
        timeout_seconds=AT2_FSTATS_TIMEOUT_SECONDS,
    )
    text = _format_fstats_result(payload, flow=flow, elapsed_seconds=time.monotonic() - started)
    await _show_message(message, text, InlineKeyboardMarkup([_footer_row(_cb("at2_fstats_builder"), lang)]), edit_existing=True)


async def admixtools2_text_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if update.message is None or update.message.text is None:
        return False
    flow = _get_fstats_flow(context)
    if flow is None or flow.get("awaiting") != "populations":
        return False
    expected = _fstats_arity(flow)
    flow["populations"] = _parse_populations(update.message.text, expected)
    flow["awaiting"] = None
    lang = get_user_language(context, int(update.effective_user.id) if update.effective_user is not None else None)
    progress = await update.message.reply_text("Populations обновлены.", do_quote=False)
    if update.effective_chat is not None and update.effective_user is not None:
        set_active_main_menu_message(context, update.effective_chat.id, update.effective_user.id, progress.message_id)
    await _show_fstats_builder(progress, context, edit_existing=True, lang=lang)
    return True


async def admixtools2_callback_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    action: str,
    parts: list[str],
    *,
    lang: str,
) -> bool:
    query = update.callback_query
    if query is None or query.message is None:
        return False
    message = query.message

    if action == "at2_f2_cache":
        await show_f2_cache_status(message, context, edit_existing=True, lang=lang)
        return True
    if action == "at2_fstats":
        await show_fstats_dataset_menu(message, context, edit_existing=True, lang=lang)
        return True
    if action == "at2_fstats_ds_pick" and len(parts) >= 3:
        dataset = parts[2]
        if dataset not in DATASET_LABELS:
            await show_fstats_dataset_menu(message, context, edit_existing=True, lang=lang)
            return True
        context.user_data[AT2_FSTATS_FLOW_KEY] = _new_fstats_flow(dataset)
        await _show_fstats_builder(message, context, edit_existing=True, lang=lang)
        return True
    if action == "at2_fstats_builder":
        await _show_fstats_builder(message, context, edit_existing=True, lang=lang)
        return True
    if action == "at2_fstats_type" and len(parts) >= 3:
        flow = _get_fstats_flow(context)
        if flow is not None and parts[2] in FSTAT_ARITIES:
            flow["statistic"] = parts[2]
            flow["populations"] = []
        await _show_fstats_builder(message, context, edit_existing=True, lang=lang)
        return True
    if action == "at2_fstats_pops":
        await _prompt_fstats_populations(message, context, lang=lang)
        return True
    if action == "at2_fstats_run":
        await _run_fstats(message, context, lang=lang)
        return True
    return False
