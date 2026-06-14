from __future__ import annotations

import asyncio
import copy
import html
import json
import os
import time
from pathlib import Path
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.features.modeling.datasets import DATASET_LABELS, dataset_choices, dataset_label
from app.features.modeling.navigation import nav_back_callback, nav_enter, nav_reset
from app.features.modeling.saved_models import register_pending_save
from app.features.modeling.ui import footer_row as _footer_row
from app.features.modeling.ui import modeling_cb as _cb
from app.features.modeling.ui import page_nav_row
from app.features.modeling.ui import show_message as _show_message
from app.features.modeling.visuals import render_admixtools2_qpgraph_result
from app.heavy_runtime import heavy_command
from app.i18n import get_user_language
from app.main_menu import set_active_main_menu_message


AT2_FSTATS_FLOW_KEY = "admixtools2_fstats_flow"
AT2_QPGRAPH_FLOW_KEY = "admixtools2_qpgraph_flow"

DNA_PLATFORM_ROOT = Path(os.getenv("DNA_PLATFORM_ROOT", "/srv/dna_platform"))
DNA_PLATFORM_PYTHON = os.getenv("DNA_PLATFORM_PYTHON", "python3")
ADMIXLAB_BIN_DIR = Path(os.getenv("ADMIXLAB_BIN_DIR", "/srv/dna_platform/tools/admixtools/bin"))
ADMIXLAB_RAW_MERGE_CONFIG = os.getenv("ADMIXLAB_RAW_MERGE_CONFIG", "/etc/admixlab/raw_merge_config.json")
BOT_AT2_OUTPUT_DIR = Path(os.getenv("KBDNA_AT2_OUTPUT_DIR", str(DNA_PLATFORM_ROOT / "output" / "admixlab" / "bot" / "at2")))
AT2_QPADM_CONFIG = Path(os.getenv("ADMIXLAB_QPADM_ADMIXTOOLS2_BACKEND_CONFIG", "/etc/admixlab/qpadm_backend_config.admixtools2.json"))
AT2_RUNNER = Path(__file__).with_name("admixtools2_runner.R")
AT2_TIMEOUT_SECONDS = int(os.getenv("KBDNA_AT2_TIMEOUT_SECONDS", "7200"))
AT2_FSTATS_TIMEOUT_SECONDS = int(os.getenv("KBDNA_AT2_FSTATS_TIMEOUT_SECONDS", "1800"))
AT2_QPGRAPH_TIMEOUT_SECONDS = int(os.getenv("KBDNA_AT2_QPGRAPH_TIMEOUT_SECONDS", "7200"))
AT2_RAW_MATERIALIZE_TIMEOUT_SECONDS = int(os.getenv("KBDNA_AT2_RAW_MATERIALIZE_TIMEOUT_SECONDS", "1800"))
AT2_F2_CACHE_WARM_TIMEOUT_SECONDS = int(os.getenv("KBDNA_AT2_F2_CACHE_WARM_TIMEOUT_SECONDS", "7200"))
AT2_QPGRAPH_SAMPLE_PAGE_SIZE = 8

FSTAT_ARITIES = {"f2": 2, "f3": 3, "f4": 4}
F2_CACHE_READY_MARKERS = (
    "block_lengths",
    "block_lengths_f2.rds",
    "block_lengths_ap.rds",
    "block_lengths_fst.rds",
)
F2_CACHE_WARM_PRESETS: dict[str, dict[str, list[str]]] = {
    "v62_1240k_public": {
        "left": ["Mbuti.DG", "Han.DG"],
        "right": ["PapuaNewGuinea.DG", "Russia_UstIshim_IUP.DG"],
    },
    "human_origins": {
        "left": ["Mbuti.DG", "Han.DG"],
        "right": ["PapuaNewGuinea.DG", "Russia_UstIshim_IUP.DG"],
    },
    "v66p1_1240k_public": {
        "left": ["Mbuti", "Han"],
        "right": ["Papuan", "Russia_UstIshim_IUP"],
    },
    "v66p1_human_origins": {
        "left": ["Mbuti", "Han"],
        "right": ["Papuan", "Russia_UstIshim_IUP"],
    },
}


def _dataset_label(dataset: object) -> str:
    return dataset_label(dataset)


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


def _population_index_path(dataset_files: dict[str, Any]) -> Path | None:
    for key in ("ind", "ind_file", "ind_path"):
        value = str(dataset_files.get(key) or "").strip()
        if value:
            return Path(value)
    geno_prefix = str(dataset_files.get("geno_prefix") or "").strip()
    if geno_prefix:
        return Path(f"{geno_prefix}.ind")
    return None


def _load_population_ids(dataset_files: dict[str, Any]) -> set[str] | None:
    ind_path = _population_index_path(dataset_files)
    if ind_path is None or not ind_path.exists() or not ind_path.is_file():
        return None
    populations: set[str] = set()
    try:
        with ind_path.open("r", encoding="utf-8", errors="replace") as handle:
            for raw_line in handle:
                parts = raw_line.strip().split()
                if len(parts) >= 3:
                    populations.add(parts[-1])
    except OSError:
        return None
    return populations


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


def _cache_entry_ready(path: Path) -> bool:
    return path.is_dir() and any((path / marker).exists() for marker in F2_CACHE_READY_MARKERS)


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
        building_entries = 0
        ready_entries = 0
        stale_entries = 0
        latest_mtime = None
        if cache_dir.exists():
            try:
                children = [item for item in cache_dir.iterdir() if item.is_dir()]
            except OSError:
                children = []
            entries = [
                item
                for item in children
                if item.name.startswith("f2_") and ".tmp." not in item.name and not item.name.endswith(".lock")
            ]
            building_entries = sum(
                1
                for item in children
                if item.name.startswith("f2_") and (".tmp." in item.name or item.name.endswith(".lock"))
            )
            for entry in entries:
                if _cache_entry_ready(entry):
                    ready_entries += 1
                else:
                    stale_entries += 1
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
                "ready_entries": ready_entries,
                "stale_entries": stale_entries,
                "building_entries": building_entries,
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
        if not row.get("exists"):
            status = "missing"
        elif int(row.get("ready_entries") or 0) > 0:
            status = "ready"
        elif int(row.get("building_entries") or 0) > 0:
            status = "building"
        elif int(row.get("stale_entries") or 0) > 0:
            status = "stale"
        else:
            status = "empty"
        lines.extend(
            [
                f"• <b>{html.escape(_dataset_label(row.get('dataset')))}</b> · <code>{status}</code>",
                f"  caches: <code>{int(row.get('ready_entries') or 0)} ready</code>, <code>{int(row.get('building_entries') or 0)} building</code>, <code>{int(row.get('stale_entries') or 0)} stale</code>, total: <code>{int(row.get('entries') or 0)}</code>",
                f"  size: <code>{_format_bytes(int(row.get('size') or 0))}</code>, files: <code>{int(row.get('file_count') or 0)}</code>",
                f"  latest: <code>{html.escape(latest)}</code>",
            ]
        )
        if status == "empty":
            lines.append("  note: <code>first run builds this cache automatically; it can be slow</code>")
        elif status == "building":
            lines.append("  note: <code>cache is being built; wait or refresh later</code>")
        elif status == "missing":
            lines.append("  note: <code>cache directory is missing or not mounted</code>")
    return "\n".join(lines)


def _cache_warm_preset(dataset: object) -> dict[str, list[str]] | None:
    preset = F2_CACHE_WARM_PRESETS.get(str(dataset or ""))
    if preset is None:
        return None
    return {"left": list(preset.get("left") or []), "right": list(preset.get("right") or [])}


def _cache_warm_buttons(lang: str = "ru") -> list[list[InlineKeyboardButton]]:
    rows: list[list[InlineKeyboardButton]] = []
    for dataset, _label in dataset_choices():
        if dataset not in F2_CACHE_WARM_PRESETS:
            continue
        rows.append(
            [
                InlineKeyboardButton(
                    f"Warm smoke: {_dataset_label(dataset)}",
                    callback_data=_cb("at2_f2_warm", dataset),
                )
            ]
        )
    return rows


def _format_cache_warm_result(
    payload: dict[str, Any],
    *,
    dataset: str,
    preset: dict[str, list[str]],
    elapsed_seconds: float,
) -> str:
    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    data_source = result.get("data_source") if isinstance(result.get("data_source"), dict) else {}
    ranks = result.get("ranks") if isinstance(result.get("ranks"), list) else []
    lines = [
        "<b>f2 cache · warm smoke</b>",
        "",
        f"Dataset: <code>{html.escape(_dataset_label(dataset))}</code>",
        f"Status: <code>{html.escape(str(payload.get('status') or 'completed'))}</code>",
        f"Cache: <code>{html.escape(str(data_source.get('cache_status') or 'unknown'))}</code>",
        f"Time: <code>{elapsed_seconds:.1f}s</code>",
        "",
        "<b>Preset</b>",
        f"Left: <code>{html.escape(', '.join(preset.get('left') or []))}</code>",
        f"Right: <code>{html.escape(', '.join(preset.get('right') or []))}</code>",
    ]
    cache_path = str(data_source.get("path") or "").strip()
    if cache_path:
        lines.extend(["", f"Path: <code>{html.escape(cache_path)}</code>"])
    if ranks:
        best = ranks[0] if isinstance(ranks[0], dict) else {}
        lines.append(f"qpWave p: <code>{html.escape(_num(best.get('tail')))}</code>")
    return "\n".join(lines)


def _format_cache_warm_error(exc: Exception, *, dataset: str, preset: dict[str, list[str]], elapsed_seconds: float) -> str:
    return "\n".join(
        [
            "<b>f2 cache · warm smoke failed</b>",
            "",
            f"Dataset: <code>{html.escape(_dataset_label(dataset))}</code>",
            f"Time: <code>{elapsed_seconds:.1f}s</code>",
            "",
            "<b>Error</b>",
            f"<code>{html.escape(str(exc) or exc.__class__.__name__)}</code>",
            "",
            "<b>Preset</b>",
            f"Left: <code>{html.escape(', '.join(preset.get('left') or []))}</code>",
            f"Right: <code>{html.escape(', '.join(preset.get('right') or []))}</code>",
        ]
    )


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
            *_cache_warm_buttons(lang),
            _footer_row(nav_back_callback(), lang),
        ]
    )
    await _show_message(message, _format_cache_status(lang), markup, edit_existing=edit_existing)


async def warm_f2_cache_smoke(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    dataset: str,
    *,
    lang: str = "ru",
) -> None:
    if dataset not in DATASET_LABELS:
        await show_f2_cache_status(message, context, edit_existing=True, lang=lang)
        return
    preset = _cache_warm_preset(dataset)
    dataset_files = _dataset_files(dataset)
    if preset is None or not dataset_files:
        await _show_message(
            message,
            "\n".join(
                [
                    "<b>f2 cache</b>",
                    "",
                    f"Dataset: <code>{html.escape(_dataset_label(dataset))}</code>",
                    "Warm preset or dataset files are not configured.",
                ]
            ),
            InlineKeyboardMarkup([_footer_row(_cb("at2_f2_cache"), lang)]),
            edit_existing=True,
        )
        return
    await _show_message(
        message,
        "\n".join(
            [
                "<b>f2 cache · warm smoke</b>",
                "",
                f"Dataset: <code>{html.escape(_dataset_label(dataset))}</code>",
                "Running a small ADMIXTOOLS2 qpWave smoke to prepare/reuse this cache entry.",
                "The first run can be slow on a new dataset.",
            ]
        ),
        InlineKeyboardMarkup([_footer_row(_cb("at2_f2_cache"), lang)]),
        edit_existing=True,
    )
    started = time.monotonic()
    try:
        payload = await run_admixtools2_runner(
            {
                "command": "qpwave",
                "dataset": dataset,
                "dataset_files": dataset_files,
                "left": preset["left"],
                "right": preset["right"],
                "options": {"auto_only": True, "afprod": True},
            },
            timeout_seconds=AT2_F2_CACHE_WARM_TIMEOUT_SECONDS,
        )
        text = _format_cache_warm_result(payload, dataset=dataset, preset=preset, elapsed_seconds=time.monotonic() - started)
    except Exception as exc:
        text = _format_cache_warm_error(exc, dataset=dataset, preset=preset, elapsed_seconds=time.monotonic() - started)
    await _show_message(
        message,
        text,
        InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("Refresh f2 cache", callback_data=_cb("at2_f2_cache"))],
                _footer_row(_cb("at2_f2_cache"), lang),
            ]
        ),
        edit_existing=True,
    )


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


def _platform_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PATH"] = f"{ADMIXLAB_BIN_DIR}:{env.get('PATH', '')}"
    env["ADMIXLAB_QPADM_BACKEND_CONFIG"] = str(AT2_QPADM_CONFIG)
    env["ADMIXLAB_RAW_MERGE_CONFIG"] = ADMIXLAB_RAW_MERGE_CONFIG
    return env


async def run_dna_platform_json(args: list[str], *, timeout_seconds: int) -> tuple[int, dict[str, Any], str]:
    proc = await asyncio.create_subprocess_exec(
        *heavy_command([DNA_PLATFORM_PYTHON, "dna_platform.py", *args]),
        cwd=str(DNA_PLATFORM_ROOT),
        env=_platform_env(),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        raise RuntimeError("dna_platform command timed out")
    stdout = stdout_bytes.decode("utf-8", errors="replace")
    stderr = stderr_bytes.decode("utf-8", errors="replace")
    try:
        payload = json.loads(stdout)
    except Exception as exc:
        detail = (stderr or stdout).strip().splitlines()[-12:]
        raise RuntimeError("\n".join(detail) or f"dna_platform emitted invalid JSON: {exc}")
    if not isinstance(payload, dict):
        raise RuntimeError("dna_platform emitted a non-object JSON response")
    return int(proc.returncode or 0), payload, stderr


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


def _format_fstats_error(exc: Exception, *, flow: dict[str, Any] | None, elapsed_seconds: float) -> str:
    lines = [
        "<b>📊 f-statistics · не прошел</b>",
        "",
        f"Time: <code>{elapsed_seconds:.1f}s</code>",
        "",
        "<b>Ошибка</b>",
        f"<code>{html.escape(str(exc) or exc.__class__.__name__)}</code>",
    ]
    if flow is not None:
        lines.extend(["", *_fstats_state_lines(flow)])
    return "\n".join(lines)


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
            *[
                [InlineKeyboardButton(label, callback_data=_cb("at2_fstats_ds_pick", dataset))]
                for dataset, label in dataset_choices()
            ],
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
    selected_stat = str(flow.get("statistic") or "f4")
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(("✓ " if selected_stat == "f2" else "") + "f2", callback_data=_cb("at2_fstats_type", "f2")),
            InlineKeyboardButton(("✓ " if selected_stat == "f3" else "") + "f3", callback_data=_cb("at2_fstats_type", "f3")),
            InlineKeyboardButton(("✓ " if selected_stat == "f4" else "") + "f4", callback_data=_cb("at2_fstats_type", "f4")),
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


def _num_float(value: object, default: float = 0.0) -> float:
    if isinstance(value, list) and value:
        value = value[0]
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


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
    try:
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
    except Exception as exc:
        text = _format_fstats_error(exc, flow=flow, elapsed_seconds=time.monotonic() - started)
        await _show_message(message, text, InlineKeyboardMarkup([_footer_row(_cb("at2_fstats_builder"), lang)]), edit_existing=True)
        return
    text = _format_fstats_result(payload, flow=flow, elapsed_seconds=time.monotonic() - started)
    await _show_message(message, text, InlineKeyboardMarkup([_footer_row(_cb("at2_fstats_builder"), lang)]), edit_existing=True)


def _new_qpgraph_flow(dataset: str) -> dict[str, Any]:
    return {"dataset": dataset, "graph_text": "", "awaiting": None, "raw_sample": None}


def _get_qpgraph_flow(context: ContextTypes.DEFAULT_TYPE) -> dict[str, Any] | None:
    flow = context.user_data.get(AT2_QPGRAPH_FLOW_KEY)
    return flow if isinstance(flow, dict) else None


def _qpgraph_raw_sample(flow: dict[str, Any]) -> dict[str, Any] | None:
    raw_sample = flow.get("raw_sample")
    return raw_sample if isinstance(raw_sample, dict) else None


def _qpgraph_raw_token(sample_id: object, label: object = "") -> str:
    base = _safe_name(sample_id or label or "sample").replace("-", "_")
    return f"raw_{base}"


def _qpgraph_raw_aliases(flow: dict[str, Any]) -> list[str]:
    raw_sample = _qpgraph_raw_sample(flow)
    if raw_sample is None:
        return []
    aliases = [str(raw_sample.get("token") or "").strip()]
    label = str(raw_sample.get("label") or "").strip()
    if label and not any(char.isspace() for char in label):
        aliases.append(label)
    result: list[str] = []
    seen: set[str] = set()
    for alias in aliases:
        if alias and alias not in seen:
            result.append(alias)
            seen.add(alias)
    return result


def _parse_qpgraph_graph_text(text: str) -> str:
    lines: list[str] = []
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        lines.append(line)
    return "\n".join(lines)


def _qpgraph_edge_pairs(graph_text: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for line in str(graph_text or "").splitlines():
        parts = line.strip().split()
        if len(parts) >= 3 and parts[0].lower() in {"edge", "ledge", "redge"}:
            pairs.append((parts[1], parts[2]))
    return pairs


def _qpgraph_leaf_populations(graph_text: str) -> list[str]:
    pairs = _qpgraph_edge_pairs(graph_text)
    if not pairs:
        return []
    sources = {source for source, _target in pairs}
    leaves: list[str] = []
    seen: set[str] = set()
    for _source, target in pairs:
        if target not in sources and target not in seen:
            leaves.append(target)
            seen.add(target)
    return leaves


def _qpgraph_preflight(flow: dict[str, Any], dataset_files: dict[str, Any]) -> dict[str, Any]:
    graph_text = str(flow.get("graph_text") or "").strip()
    leaves = _qpgraph_leaf_populations(graph_text)
    if len(leaves) < 3:
        return {
            "can_run": False,
            "status": "invalid_graph",
            "errors": [
                {
                    "code": "invalid_graph",
                    "message": "qpGraph needs at least 3 sampled leaf populations. Check edge lines in graphfile.",
                    "details": {"leaves": leaves},
                }
            ],
        }
    raw_aliases = _qpgraph_raw_aliases(flow)
    raw_graph_label = next((leaf for leaf in leaves if leaf in raw_aliases), "")
    if raw_aliases and not raw_graph_label:
        return {
            "can_run": False,
            "status": "raw_leaf_not_found",
            "errors": [
                {
                    "code": "raw_leaf_not_found",
                    "message": "Selected raw sample is not used as a qpGraph leaf.",
                    "details": {"raw_token": raw_aliases[0], "raw_aliases": raw_aliases, "leaves": leaves},
                }
            ],
        }
    population_ids = _load_population_ids(dataset_files)
    if population_ids is None:
        return {
            "can_run": True,
            "status": "population_index_unavailable",
            "warnings": [],
            "errors": [],
            "details": {"leaves": leaves, "raw_graph_label": raw_graph_label},
        }
    missing = [item for item in leaves if item != raw_graph_label and item not in population_ids]
    if not missing:
        return {
            "can_run": True,
            "status": "ok",
            "warnings": [],
            "errors": [],
            "details": {"leaves": leaves, "raw_graph_label": raw_graph_label},
        }
    return {
        "can_run": False,
        "status": "population_not_found",
        "errors": [
            {
                "code": "population_not_found",
                "message": "One or more qpGraph leaf populations are not available in the selected dataset.",
                "details": {
                    "dataset": str(flow.get("dataset") or ""),
                    "missing": missing,
                    "leaves": leaves,
                    "raw_graph_label": raw_graph_label,
                },
            }
        ],
    }


def _format_qpgraph_preflight(payload: dict[str, Any], *, flow: dict[str, Any]) -> str:
    lines = [
        "<b>🕸 ADMIXTOOLS2 qpGraph 2 · проверка</b>",
        "",
        f"Dataset: <code>{html.escape(_dataset_label(flow.get('dataset')))}</code>",
        f"Status: <code>{html.escape(str(payload.get('status') or 'failed'))}</code>",
    ]
    errors = payload.get("errors") if isinstance(payload.get("errors"), list) else []
    for error in errors[:3]:
        if not isinstance(error, dict):
            continue
        message = str(error.get("message") or "").strip()
        if message:
            lines.extend(["", "<b>Ошибка</b>", html.escape(message)])
        details = error.get("details") if isinstance(error.get("details"), dict) else {}
        raw_token = str(details.get("raw_token") or "").strip()
        if raw_token:
            lines.extend(["", "<b>Raw token</b>", f"<code>{html.escape(raw_token)}</code>"])
        missing = details.get("missing") if isinstance(details.get("missing"), list) else []
        if missing:
            lines.append("")
            lines.append("<b>Нет в dataset</b>")
            lines.extend(f"• <code>{html.escape(str(item))}</code>" for item in missing[:12])
            if len(missing) > 12:
                lines.append(f"• ... и еще {len(missing) - 12}")
        leaves = details.get("leaves") if isinstance(details.get("leaves"), list) else []
        if leaves:
            lines.append("")
            lines.append("<b>Leaf populations</b>")
            lines.append("<code>" + html.escape(", ".join(str(item) for item in leaves[:16])) + "</code>")
    return "\n".join(lines)


def _qpgraph_state_lines(flow: dict[str, Any]) -> list[str]:
    graph_text = str(flow.get("graph_text") or "").strip()
    graph_lines = [line for line in graph_text.splitlines() if line.strip()]
    lines = [
        f"Dataset: <code>{html.escape(_dataset_label(flow.get('dataset')))}</code>",
        f"Graph lines: <code>{len(graph_lines)}</code>",
    ]
    raw_sample = _qpgraph_raw_sample(flow)
    if raw_sample is not None:
        lines.append(f"Raw sample: <code>{html.escape(str(raw_sample.get('label') or 'selected'))}</code>")
        lines.append(f"Raw graph token: <code>{html.escape(str(raw_sample.get('token') or ''))}</code>")
    return lines


async def show_qpgraph_dataset_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE | None,
    *,
    edit_existing: bool = True,
    lang: str = "ru",
) -> None:
    if context is not None:
        context.user_data.pop(AT2_QPGRAPH_FLOW_KEY, None)
        nav_enter(context, _cb("at2_qpgraph_ds"))
    markup = InlineKeyboardMarkup(
        [
            *[
                [InlineKeyboardButton(label, callback_data=_cb("at2_qpgraph_ds_pick", dataset))]
                for dataset, label in dataset_choices()
            ],
            _footer_row(nav_back_callback(), lang),
        ]
    )
    await _show_message(message, "<b>🕸 qpGraph 2</b>\n\nВыберите dataset для graph-модели.", markup, edit_existing=edit_existing)


async def _show_qpgraph_builder(message, context: ContextTypes.DEFAULT_TYPE, *, edit_existing: bool = True, lang: str = "ru") -> None:
    flow = _get_qpgraph_flow(context)
    if flow is None:
        await show_qpgraph_dataset_menu(message, context, edit_existing=edit_existing, lang=lang)
        return
    nav_enter(context, _cb("at2_qpgraph_builder"))
    graph_text = str(flow.get("graph_text") or "").strip()
    raw_sample = _qpgraph_raw_sample(flow)
    raw_button = "My raw sample"
    if raw_sample is not None:
        raw_button = f"Raw: {str(raw_sample.get('label') or 'selected')[:28]}"
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(raw_button, callback_data=_cb("at2_qpgraph_raw"))],
        [InlineKeyboardButton("📝 Graphfile", callback_data=_cb("at2_qpgraph_graph"))],
    ]
    if graph_text:
        rows.append([InlineKeyboardButton("🚀 Run qpGraph 2", callback_data=_cb("at2_qpgraph_run"))])
    rows.extend([[InlineKeyboardButton("Начать заново", callback_data=_cb("at2_qpgraph"))], _footer_row(nav_back_callback(), lang)])
    lines = [
        "<b>🕸 qpGraph 2</b>",
        "",
        *_qpgraph_state_lines(flow),
        "",
        "Вставьте graphfile в формате ADMIXTOOLS: <code>edge</code>, <code>admix</code>, <code>lock</code>, <code>label</code>.",
    ]
    if raw_sample is not None:
        lines.extend(["", "Raw leaf token for graphfile:", f"<code>{html.escape(str(raw_sample.get('token') or ''))}</code>"])
    if graph_text:
        preview = "\n".join(graph_text.splitlines()[:6])
        lines.extend(["", "<b>Graph preview</b>", f"<code>{html.escape(preview)}</code>"])
    await _show_message(message, "\n".join(lines), InlineKeyboardMarkup(rows), edit_existing=edit_existing)


async def _prompt_qpgraph_graph(message, context: ContextTypes.DEFAULT_TYPE, *, lang: str) -> None:
    flow = _get_qpgraph_flow(context)
    if flow is None:
        await show_qpgraph_dataset_menu(message, context, edit_existing=True, lang=lang)
        return
    flow["awaiting"] = "graph_text"
    text = "\n".join(
        [
            "<b>🕸 qpGraph 2 · graphfile</b>",
            "",
            "Вставьте graphfile одним сообщением.",
            "",
            "<code>edge R Mbuti.DG",
            "edge R N1",
            "edge N1 Han.DG",
            "edge N1 Papuan.DG</code>",
        ]
    )
    await _show_message(message, text, InlineKeyboardMarkup([_footer_row(_cb("at2_qpgraph_builder"), lang)]), edit_existing=True)


def _clip_text(value: object, limit: int = 38) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)] + "…"


async def _show_qpgraph_raw_menu(
    message,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    lang: str,
    page: int = 0,
) -> None:
    flow = _get_qpgraph_flow(context)
    if flow is None:
        await show_qpgraph_dataset_menu(message, context, edit_existing=True, lang=lang)
        return
    user_id = int(update.effective_user.id) if update.effective_user is not None else 0
    store = context.application.bot_data.get("my_data_store")
    samples = []
    if store is not None:
        samples = [sample for sample in store.list_samples(user_id) if getattr(sample, "raw_file_id", "")]

    nav_enter(context, _cb("at2_qpgraph_raw_page", page))
    if not samples:
        text = "\n".join(
            [
                "<b>qpGraph 2 · raw sample</b>",
                "",
                "В My DNA пока нет sample с raw-файлом.",
                "Добавьте raw в My DNA или запустите qpGraph только на dataset populations.",
            ]
        )
        await _show_message(message, text, InlineKeyboardMarkup([_footer_row(nav_back_callback(), lang)]), edit_existing=True)
        return

    page_count = max(1, (len(samples) + AT2_QPGRAPH_SAMPLE_PAGE_SIZE - 1) // AT2_QPGRAPH_SAMPLE_PAGE_SIZE)
    page = min(max(0, page), page_count - 1)
    start = page * AT2_QPGRAPH_SAMPLE_PAGE_SIZE
    end = min(len(samples), start + AT2_QPGRAPH_SAMPLE_PAGE_SIZE)
    rows = [
        [
            InlineKeyboardButton(
                _clip_text(getattr(sample, "display_name", sample.asset_id), 38),
                callback_data=_cb("at2_qpgraph_raw_pick", sample.asset_id),
            )
        ]
        for sample in samples[start:end]
    ]
    if page_count > 1:
        rows.append(page_nav_row(page, page_count, lambda value: _cb("at2_qpgraph_raw_page", value)))
    rows.append(_footer_row(nav_back_callback(), lang))
    text = "\n".join(
        [
            "<b>qpGraph 2 · raw sample</b>",
            "",
            f"Dataset: <code>{html.escape(_dataset_label(flow.get('dataset')))}</code>",
            f"Shown: <code>{start + 1}-{end}</code> / <code>{len(samples)}</code>",
            "Выберите raw sample, затем используйте его token в graphfile как leaf population.",
        ]
    )
    await _show_message(message, text, InlineKeyboardMarkup(rows), edit_existing=True)


async def _select_qpgraph_raw_sample(
    message,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    sample_id: str,
    *,
    lang: str,
) -> None:
    flow = _get_qpgraph_flow(context)
    user_id = int(update.effective_user.id) if update.effective_user is not None else 0
    store = context.application.bot_data.get("my_data_store")
    if flow is None or store is None:
        await show_qpgraph_dataset_menu(message, context, edit_existing=True, lang=lang)
        return
    sample = store.get_sample(user_id, sample_id)
    if sample is None or not getattr(sample, "raw_file_id", ""):
        await _show_qpgraph_raw_menu(message, update, context, lang=lang)
        return
    raw_file = store.get_raw_file(user_id, sample.raw_file_id)
    if raw_file is None:
        await _show_qpgraph_raw_menu(message, update, context, lang=lang)
        return
    raw_path = store.resolve_raw_file_path(raw_file)
    label = str(getattr(sample, "display_name", "") or sample_id)
    flow["raw_sample"] = {
        "sample_id": sample_id,
        "raw_file_id": sample.raw_file_id,
        "path": str(raw_path),
        "label": label,
        "token": _qpgraph_raw_token(sample_id, label),
    }
    await _show_qpgraph_builder(message, context, edit_existing=True, lang=lang)


def _format_qpgraph_error(exc: Exception, *, flow: dict[str, Any] | None, elapsed_seconds: float) -> str:
    lines = [
        "<b>🕸 qpGraph 2 · не прошел</b>",
        "",
        f"Time: <code>{elapsed_seconds:.1f}s</code>",
        "",
        "<b>Ошибка</b>",
        f"<code>{html.escape(str(exc) or exc.__class__.__name__)}</code>",
    ]
    if flow is not None:
        lines.extend(["", *_qpgraph_state_lines(flow)])
    return "\n".join(lines)


def _qpgraph_result_markup(lang: str, pending_save_id: str | None = None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton("🕸 Новый qpGraph", callback_data=_cb("at2_qpgraph"))],
        [InlineKeyboardButton("📝 Graphfile", callback_data=_cb("at2_qpgraph_graph"))],
    ]
    if pending_save_id:
        rows.append([InlineKeyboardButton("💾 Сохранить результат", callback_data=_cb("saved_save", pending_save_id))])
    rows.append(_footer_row(_cb("at2_qpgraph_builder"), lang))
    return InlineKeyboardMarkup(rows)


def _format_qpgraph_result(payload: dict[str, Any], *, flow: dict[str, Any], elapsed_seconds: float) -> str:
    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    edges = result.get("edges") if isinstance(result.get("edges"), list) else []
    f3_rows = result.get("f3") if isinstance(result.get("f3"), list) else []
    leaves = result.get("leaf_populations") if isinstance(result.get("leaf_populations"), list) else []
    data_source = result.get("data_source") if isinstance(result.get("data_source"), dict) else {}
    lines = [
        "<b>🕸 ADMIXTOOLS2 qpGraph 2</b>",
        "",
        f"Dataset: <code>{html.escape(_dataset_label(flow.get('dataset')))}</code>",
        f"Status: <code>{html.escape(str(payload.get('status') or 'completed'))}</code>",
        f"Time: <code>{elapsed_seconds:.1f}s</code>",
        f"Fit score: <code>{html.escape(_num(result.get('score')))}</code>",
        f"Worst |z|: <code>{html.escape(_num(result.get('worst_residual')))}</code>",
    ]
    if result.get("p_value") is not None:
        lines.append(f"p-value: <code>{html.escape(_num(result.get('p_value')))}</code>")
    if leaves:
        lines.extend(["", "<b>Leaves</b>", "<code>" + html.escape(", ".join(str(item) for item in leaves[:16])) + "</code>"])
    if edges:
        lines.extend(["", "<b>Edges</b>"])
    for row in edges[:12]:
        if not isinstance(row, dict):
            continue
        weight = row.get("weight")
        edge_type = str(row.get("type") or "edge")
        edge_label = "mix" if edge_type == "admix" else "w"
        lines.append(
            "• "
            f"<code>{html.escape(str(row.get('from') or '?'))}</code> → "
            f"<code>{html.escape(str(row.get('to') or '?'))}</code> "
            f"{edge_label}=<code>{html.escape(_num(weight))}</code>"
        )
    if len(edges) > 12:
        lines.append(f"• ... and {len(edges) - 12} more")
    if f3_rows:
        lines.extend(["", "<b>Top f3 residuals</b>"])
    sorted_f3 = sorted(
        [row for row in f3_rows if isinstance(row, dict)],
        key=lambda row: abs(_num_float(row.get("z"))),
        reverse=True,
    )
    for row in sorted_f3[:5]:
        pops = [str(row.get(key) or "") for key in ("pop1", "pop2", "pop3")]
        lines.append(f"• <code>{html.escape('/'.join(pops))}</code>: z=<code>{html.escape(_num(row.get('z')))}</code>")
    source_path = str(data_source.get("path") or "").strip()
    if source_path:
        lines.extend(["", f"Data: <code>{html.escape(str(data_source.get('type') or 'f2'))}</code>"])
    return "\n".join(lines)


def _format_qpgraph_caption(payload: dict[str, Any], *, flow: dict[str, Any], elapsed_seconds: float) -> str:
    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    return "\n".join(
        [
            "<b>🕸 ADMIXTOOLS2 qpGraph 2</b>",
            f"Dataset: <code>{html.escape(_dataset_label(flow.get('dataset')))}</code>",
            f"Score: <code>{html.escape(_num(result.get('score')))}</code>",
            f"Worst |z|: <code>{html.escape(_num(result.get('worst_residual')))}</code>",
            f"Time: <code>{elapsed_seconds:.1f}s</code>",
        ]
    )


async def _send_qpgraph_result(
    message,
    update: Update | None,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    text: str,
    markup: InlineKeyboardMarkup,
    caption: str | None = None,
    visual_path: Path | None = None,
) -> None:
    if visual_path is None or not visual_path.exists():
        await _show_message(message, text, markup, edit_existing=True)
        return
    try:
        with visual_path.open("rb") as image_file:
            sent = await message.reply_photo(
                photo=image_file,
                caption=caption or text[:900],
                reply_markup=markup,
                parse_mode="HTML",
                do_quote=False,
            )
        try:
            await message.delete()
        except Exception:
            pass
        if update is not None and update.effective_user is not None:
            set_active_main_menu_message(context, sent.chat_id, update.effective_user.id, sent.message_id)
    except Exception:
        await _show_message(message, text, markup, edit_existing=True)


def _qpgraph_save_payload(
    payload: dict[str, Any],
    *,
    flow: dict[str, Any],
    text: str,
    caption: str = "",
    visual_path: Path | None = None,
    visual_error: str | None = None,
) -> dict[str, Any]:
    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    graph_text = str(flow.get("graph_text") or "").strip()
    leaves = result.get("leaf_populations") if isinstance(result.get("leaf_populations"), list) else []
    title_bits = ["ADMIXTOOLS2 qpGraph 2", _dataset_label(flow.get("dataset"))]
    if leaves:
        title_bits.append(", ".join(str(item) for item in leaves[:3]))
    return {
        "kind": "qpgraph_admixtools2",
        "title": " · ".join(title_bits),
        "dataset": str(flow.get("dataset") or ""),
        "engine": "admixtools2_qpgraph",
        "engine_label": "ADMIXTOOLS2 qpGraph 2",
        "graph_text": graph_text,
        "score": result.get("score"),
        "worst_residual": result.get("worst_residual"),
        "leaves": leaves,
        "edges": result.get("edges") if isinstance(result.get("edges"), list) else [],
        "f3": result.get("f3") if isinstance(result.get("f3"), list) else [],
        "result_payload": payload,
        "result_text": text,
        "caption_text": caption,
        "visual_path": str(visual_path or ""),
        "visual_error": visual_error,
    }


def _replace_qpgraph_token(graph_text: str, old: str, new: str) -> str:
    lines: list[str] = []
    for line in str(graph_text or "").splitlines():
        parts = line.split()
        if not parts:
            continue
        replaced = [new if part == old else part for part in parts]
        lines.append(" ".join(replaced))
    return "\n".join(lines)


def _alias_qpgraph_payload(payload: dict[str, Any], aliases: dict[str, str]) -> dict[str, Any]:
    if not aliases:
        return payload
    cloned = copy.deepcopy(payload)
    result = cloned.get("result") if isinstance(cloned.get("result"), dict) else {}

    def alias(value: object) -> object:
        text = str(value)
        return aliases.get(text, value)

    leaves = result.get("leaf_populations")
    if isinstance(leaves, list):
        result["leaf_populations"] = [alias(item) for item in leaves]
    edges = result.get("edges")
    if isinstance(edges, list):
        for row in edges:
            if not isinstance(row, dict):
                continue
            for key in ("from", "to"):
                if key in row:
                    row[key] = alias(row.get(key))
    f3_rows = result.get("f3")
    if isinstance(f3_rows, list):
        for row in f3_rows:
            if not isinstance(row, dict):
                continue
            for key in ("pop1", "pop2", "pop3"):
                if key in row:
                    row[key] = alias(row.get(key))
    return cloned


def _materialization_error(payload: dict[str, Any], stderr: str = "") -> str:
    errors = payload.get("errors") if isinstance(payload.get("errors"), list) else []
    messages = [str(item.get("message")) for item in errors if isinstance(item, dict) and item.get("message")]
    if messages:
        return "\n".join(messages)
    status = str(payload.get("status") or "").strip()
    if status:
        return f"raw materialization failed: {status}"
    return (stderr or "raw materialization failed").strip()


async def _prepare_qpgraph_runtime(
    flow: dict[str, Any],
    *,
    graph_text: str,
    dataset_files: dict[str, Any],
    preflight: dict[str, Any],
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    raw_sample = _qpgraph_raw_sample(flow)
    if raw_sample is None:
        return graph_text, dataset_files, {}
    details = preflight.get("details") if isinstance(preflight.get("details"), dict) else {}
    raw_graph_label = str(details.get("raw_graph_label") or "").strip()
    if not raw_graph_label:
        raise RuntimeError("Selected raw sample is not used in graphfile.")
    leaves = details.get("leaves") if isinstance(details.get("leaves"), list) else _qpgraph_leaf_populations(graph_text)
    dataset_leaves = [str(item) for item in leaves if str(item) != raw_graph_label]
    output_path = BOT_AT2_OUTPUT_DIR / f"qpgraph_raw_materialized_{_safe_name(raw_sample.get('sample_id'))}_{int(time.time() * 1000)}.json"
    args = [
        "admixlab-materialize-raw-eigenstrat",
        "--dataset",
        str(flow.get("dataset") or ""),
        "--target",
        str(raw_sample.get("path") or ""),
        "--output",
        str(output_path),
    ]
    for leaf in dataset_leaves:
        args.extend(["--leaf-population", leaf])
    returncode, payload, stderr = await run_dna_platform_json(args, timeout_seconds=AT2_RAW_MATERIALIZE_TIMEOUT_SECONDS)
    if returncode != 0 or payload.get("status") != "completed" or payload.get("can_run") is not True:
        raise RuntimeError(_materialization_error(payload, stderr))
    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    materialized_files = result.get("dataset_files") if isinstance(result.get("dataset_files"), dict) else {}
    raw_population_id = str(result.get("raw_population_id") or "").strip()
    if not materialized_files or not raw_population_id:
        raise RuntimeError("raw materialization did not return a usable geno_prefix")
    runtime_graph_text = _replace_qpgraph_token(graph_text, raw_graph_label, raw_population_id)
    runtime = {
        "raw_graph_label": raw_graph_label,
        "raw_population_id": raw_population_id,
        "display_aliases": {raw_population_id: str(raw_sample.get("label") or raw_graph_label)},
        "materialization": payload,
    }
    return runtime_graph_text, dict(materialized_files), runtime


async def _run_qpgraph(message, update: Update | None, context: ContextTypes.DEFAULT_TYPE, *, lang: str) -> None:
    flow = _get_qpgraph_flow(context)
    if flow is None:
        await show_qpgraph_dataset_menu(message, context, edit_existing=True, lang=lang)
        return
    graph_text = str(flow.get("graph_text") or "").strip()
    if not graph_text:
        await _show_qpgraph_builder(message, context, edit_existing=True, lang=lang)
        return
    dataset = str(flow.get("dataset") or "")
    dataset_files = _dataset_files(dataset)
    if not dataset_files:
        await _show_message(message, "<b>🕸 qpGraph 2</b>\n\nDataset files не найдены.", InlineKeyboardMarkup([_footer_row(_cb("at2_qpgraph_builder"), lang)]), edit_existing=True)
        return
    preflight = _qpgraph_preflight(flow, dataset_files)
    if not bool(preflight.get("can_run")):
        await _show_message(message, _format_qpgraph_preflight(preflight, flow=flow), _qpgraph_result_markup(lang), edit_existing=True)
        return
    await _show_message(message, "<b>🕸 qpGraph 2</b>\n\nСчитаю ADMIXTOOLS2...", InlineKeyboardMarkup([_footer_row(_cb("at2_qpgraph_builder"), lang)]), edit_existing=True)
    runtime: dict[str, Any] = {}
    runtime_graph_text = graph_text
    runtime_dataset_files = dataset_files
    if _qpgraph_raw_sample(flow) is not None:
        await _show_message(
            message,
            "<b>qpGraph 2</b>\n\nPreparing raw sample for ADMIXTOOLS2...",
            InlineKeyboardMarkup([_footer_row(_cb("at2_qpgraph_builder"), lang)]),
            edit_existing=True,
        )
        try:
            runtime_graph_text, runtime_dataset_files, runtime = await _prepare_qpgraph_runtime(
                flow,
                graph_text=graph_text,
                dataset_files=dataset_files,
                preflight=preflight,
            )
        except Exception as exc:
            text = _format_qpgraph_error(exc, flow=flow, elapsed_seconds=0.0)
            await _show_message(message, text, InlineKeyboardMarkup([_footer_row(_cb("at2_qpgraph_builder"), lang)]), edit_existing=True)
            return
        await _show_message(
            message,
            "<b>qpGraph 2</b>\n\nRunning ADMIXTOOLS2...",
            InlineKeyboardMarkup([_footer_row(_cb("at2_qpgraph_builder"), lang)]),
            edit_existing=True,
        )
    started = time.monotonic()
    try:
        payload = await run_admixtools2_runner(
            {
                "command": "qpgraph",
                "dataset": dataset,
                "dataset_files": runtime_dataset_files,
                "graph_text": runtime_graph_text,
                "options": {"afprod": False, "return_fstats": "f3", "numstart": 10},
            },
            timeout_seconds=AT2_QPGRAPH_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        text = _format_qpgraph_error(exc, flow=flow, elapsed_seconds=time.monotonic() - started)
        await _show_message(message, text, InlineKeyboardMarkup([_footer_row(_cb("at2_qpgraph_builder"), lang)]), edit_existing=True)
        return
    elapsed = time.monotonic() - started
    display_aliases = runtime.get("display_aliases") if isinstance(runtime.get("display_aliases"), dict) else {}
    payload = _alias_qpgraph_payload(payload, {str(key): str(value) for key, value in display_aliases.items()})
    if runtime:
        result = payload.setdefault("result", {})
        if isinstance(result, dict):
            materialization = runtime.get("materialization")
            result["raw_runtime"] = {
                "raw_graph_label": runtime.get("raw_graph_label"),
                "raw_population_id": runtime.get("raw_population_id"),
                "materialization_status": materialization.get("status") if isinstance(materialization, dict) else None,
            }
    text = _format_qpgraph_result(payload, flow=flow, elapsed_seconds=elapsed)
    caption = _format_qpgraph_caption(payload, flow=flow, elapsed_seconds=elapsed)
    visual_path: Path | None = None
    visual_error: str | None = None
    try:
        visual_path = render_admixtools2_qpgraph_result(payload, flow=flow, elapsed_seconds=elapsed, output_dir=BOT_AT2_OUTPUT_DIR)
    except Exception as exc:
        visual_error = str(exc)
    pending_save_id: str | None = None
    if update is not None and update.effective_user is not None:
        pending_save_id = register_pending_save(
            context,
            int(update.effective_user.id),
            _qpgraph_save_payload(payload, flow=flow, text=text, caption=caption, visual_path=visual_path, visual_error=visual_error),
        )
    await _send_qpgraph_result(
        message,
        update,
        context,
        text=text,
        markup=_qpgraph_result_markup(lang, pending_save_id),
        caption=caption,
        visual_path=visual_path,
    )


async def admixtools2_text_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if update.message is None or update.message.text is None:
        return False
    flow = _get_fstats_flow(context)
    if flow is not None and flow.get("awaiting") == "populations":
        expected = _fstats_arity(flow)
        flow["populations"] = _parse_populations(update.message.text, expected)
        flow["awaiting"] = None
        lang = get_user_language(context, int(update.effective_user.id) if update.effective_user is not None else None)
        progress = await update.message.reply_text("Populations обновлены.", do_quote=False)
        if update.effective_chat is not None and update.effective_user is not None:
            set_active_main_menu_message(context, update.effective_chat.id, update.effective_user.id, progress.message_id)
        await _show_fstats_builder(progress, context, edit_existing=True, lang=lang)
        return True
    graph_flow = _get_qpgraph_flow(context)
    if graph_flow is None or graph_flow.get("awaiting") != "graph_text":
        return False
    graph_flow["graph_text"] = _parse_qpgraph_graph_text(update.message.text)
    graph_flow["awaiting"] = None
    lang = get_user_language(context, int(update.effective_user.id) if update.effective_user is not None else None)
    progress = await update.message.reply_text("Graphfile обновлен.", do_quote=False)
    if update.effective_chat is not None and update.effective_user is not None:
        set_active_main_menu_message(context, update.effective_chat.id, update.effective_user.id, progress.message_id)
    await _show_qpgraph_builder(progress, context, edit_existing=True, lang=lang)
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
    if action == "at2_f2_warm" and len(parts) >= 3:
        await warm_f2_cache_smoke(message, context, parts[2], lang=lang)
        return True
    if action == "at2_qpgraph":
        nav_reset(context, _cb("at2"))
        await show_qpgraph_dataset_menu(message, context, edit_existing=True, lang=lang)
        return True
    if action == "at2_qpgraph_ds":
        await show_qpgraph_dataset_menu(message, context, edit_existing=True, lang=lang)
        return True
    if action == "at2_qpgraph_ds_pick" and len(parts) >= 3:
        dataset = parts[2]
        if dataset not in DATASET_LABELS:
            await show_qpgraph_dataset_menu(message, context, edit_existing=True, lang=lang)
            return True
        context.user_data[AT2_QPGRAPH_FLOW_KEY] = _new_qpgraph_flow(dataset)
        await _show_qpgraph_builder(message, context, edit_existing=True, lang=lang)
        return True
    if action == "at2_qpgraph_builder":
        await _show_qpgraph_builder(message, context, edit_existing=True, lang=lang)
        return True
    if action == "at2_qpgraph_raw":
        await _show_qpgraph_raw_menu(message, update, context, lang=lang, page=0)
        return True
    if action == "at2_qpgraph_raw_page" and len(parts) >= 3:
        try:
            page = max(0, int(parts[2]))
        except (TypeError, ValueError):
            page = 0
        await _show_qpgraph_raw_menu(message, update, context, lang=lang, page=page)
        return True
    if action == "at2_qpgraph_raw_pick" and len(parts) >= 3:
        await _select_qpgraph_raw_sample(message, update, context, parts[2], lang=lang)
        return True
    if action == "at2_qpgraph_graph":
        await _prompt_qpgraph_graph(message, context, lang=lang)
        return True
    if action == "at2_qpgraph_run":
        await _run_qpgraph(message, update, context, lang=lang)
        return True
    if action == "at2_fstats":
        nav_reset(context, _cb("at2"))
        await show_fstats_dataset_menu(message, context, edit_existing=True, lang=lang)
        return True
    if action == "at2_fstats_ds":
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
