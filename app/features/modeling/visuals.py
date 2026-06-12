from __future__ import annotations

import math
import re
import textwrap
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from PIL import Image, ImageDraw, ImageFont


DATASET_LABELS = {
    "v62_1240k_public": "v62 1240k public",
    "human_origins": "Human Origins",
}
PALETTE = [
    "#4cc9f0",
    "#80ed99",
    "#ffd166",
    "#f72585",
    "#a78bfa",
    "#f97316",
    "#2dd4bf",
    "#e879f9",
]
QPADM_ENGINE_ADMIXTOOLS2 = "admixtools2_qpadm"
QPADM_CLASSIC_VISUAL = {
    "title": "qpAdm classic",
    "product": "qpAdm classic",
    "version": "v2.1",
    "prefix": "qpadm_result",
    "background": "#10141b",
    "panel": "#1d2630",
    "accent": "#5eead4",
    "outline": "#405066",
    "palette": PALETTE,
}
QPADM_ADMIXTOOLS2_VISUAL = {
    "title": "ADMIXTOOLS2 qpAdm",
    "product": "ADMIXTOOLS2 qpAdm",
    "version": "AT2",
    "prefix": "qpadm_admixtools2_result",
    "background": "#0b1117",
    "panel": "#171d22",
    "accent": "#f5b942",
    "outline": "#33424e",
    "palette": ["#33d6d6", "#ff9f4a", "#f9e879", "#4ade80", "#a78bfa", "#79e5bd", "#75a7ff", "#fbbf24"],
}


def _dataset_label(dataset: object) -> str:
    value = str(dataset or "")
    return DATASET_LABELS.get(value, value or "not selected")


def _qpadm_engine(value: object) -> str:
    raw = str(value or "").strip().casefold()
    if raw in {"admixtools2", QPADM_ENGINE_ADMIXTOOLS2}:
        return QPADM_ENGINE_ADMIXTOOLS2
    return "classic_qpadm"


def _qpadm_visual_profile(flow: dict[str, Any], summary: dict[str, Any] | None = None) -> dict[str, Any]:
    summary = summary or {}
    engine = _qpadm_engine(flow.get("engine") or summary.get("engine"))
    return QPADM_ADMIXTOOLS2_VISUAL if engine == QPADM_ENGINE_ADMIXTOOLS2 else QPADM_CLASSIC_VISUAL


def _font(size: int, *, bold: bool = False) -> ImageFont.ImageFont:
    names = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
    ]
    for name in names:
        try:
            return ImageFont.truetype(name, size=size)
        except Exception:
            continue
    return ImageFont.load_default()


def _format_number(value: object, *, percent: bool = False) -> str:
    if value is None:
        return "n/a"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    suffix = "%" if percent else ""
    if not percent and number != 0 and abs(number) < 0.001:
        return f"{number:.2e}"
    text = f"{number:.3f}".rstrip("0").rstrip(".")
    if text == "-0":
        text = "0"
    return f"{text}{suffix}"


def _wrap(value: object, width: int) -> list[str]:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if not text:
        return [""]
    return textwrap.wrap(text, width=width, break_long_words=False, break_on_hyphens=False) or [text]


def _line(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, font: ImageFont.ImageFont, fill: str = "#f8fafc") -> int:
    draw.text(xy, text, font=font, fill=fill)
    bbox = draw.textbbox(xy, text, font=font)
    return bbox[3] - bbox[1]


def _fit_text(draw: ImageDraw.ImageDraw, text: object, font: ImageFont.ImageFont, max_width: int) -> str:
    value = str(text or "")
    bbox = draw.textbbox((0, 0), value, font=font)
    if bbox[2] - bbox[0] <= max_width:
        return value
    suffix = "..."
    while value:
        bbox = draw.textbbox((0, 0), value + suffix, font=font)
        if bbox[2] - bbox[0] <= max_width:
            break
        value = value[:-1]
    return value.rstrip() + suffix if value else suffix


def _number(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _weight_percent(item: dict[str, Any]) -> float:
    percent = _number(item.get("weight_percent"))
    if percent is not None:
        return percent
    weight = _number(item.get("weight"))
    return weight * 100.0 if weight is not None else 0.0


def _stderr_percent(item: dict[str, Any]) -> float:
    percent = _number(item.get("stderr_percent"))
    if percent is not None:
        return percent
    stderr = _number(item.get("stderr"))
    return stderr * 100.0 if stderr is not None else 0.0


def _format_weight_percent(value: float) -> str:
    return _format_number(value, percent=True)


def _source_z_value(item: dict[str, Any], weight_percent: float, stderr_percent: float) -> float | None:
    z_value = _number(item.get("z"))
    if z_value is not None:
        return z_value
    if stderr_percent:
        return weight_percent / stderr_percent
    return None


def _target_display(flow: dict[str, Any]) -> str:
    return str(flow.get("target_label") or flow.get("target") or "unknown")


def _target_mode_label(flow: dict[str, Any]) -> str:
    target_type = str(flow.get("target_type") or "").strip()
    if target_type == "raw_file":
        return "raw sample mode"
    if target_type == "dataset_sample":
        return "dataset sample mode"
    return "dataset population mode"


def _canvas(
    height: int,
    *,
    width: int = 1200,
    background: str = "#10141b",
    panel: str = "#1d2630",
) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGB", (width, max(820, height)), background)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((28, 28, image.width - 28, image.height - 28), radius=24, fill=panel)
    return image, draw


def _chamfer_points(x: int, y: int, width: int, height: int, cut: int = 10) -> list[tuple[int, int]]:
    return [
        (x + cut, y),
        (x + width - cut, y),
        (x + width, y + cut),
        (x + width, y + height - cut),
        (x + width - cut, y + height),
        (x + cut, y + height),
        (x, y + height - cut),
        (x, y + cut),
    ]


def _draw_segment_bar(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    *,
    x: int,
    y: int,
    width: int,
    height: int,
    weights: list[float],
    palette: list[str] | None = None,
    outline: str = "#405066",
) -> None:
    palette = palette or PALETTE
    points = _chamfer_points(x, y, width, height, cut=10)
    mask = Image.new("L", image.size, 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.polygon(points, fill=255)

    segments = Image.new("RGB", image.size, "#111827")
    segment_draw = ImageDraw.Draw(segments)
    cursor = x
    total = sum(max(0.0, value) for value in weights)
    if total > 0:
        for index, weight in enumerate(weights):
            segment_w = int(round(width * max(0.0, weight) / total))
            color = palette[index % len(palette)]
            segment_draw.rectangle((cursor, y, min(x + width, cursor + segment_w), y + height), fill=color)
            cursor += segment_w

    image.paste(segments, (0, 0), mask)
    draw.line(points + [points[0]], fill=outline, width=2)


def _draw_dna_icon(draw: ImageDraw.ImageDraw, x: int, y: int, color: str) -> None:
    left: list[tuple[int, int]] = []
    right: list[tuple[int, int]] = []
    for step in range(22):
        yy = y + step
        offset = int(math.sin(step / 21 * math.pi * 2) * 5)
        left.append((x + 8 + offset, yy))
        right.append((x + 8 - offset, yy))
    draw.line(left, fill=color, width=2)
    draw.line(right, fill=color, width=2)
    for step in range(2, 21, 5):
        lx = x + 8 + int(math.sin(step / 21 * math.pi * 2) * 5)
        rx = x + 8 - int(math.sin(step / 21 * math.pi * 2) * 5)
        yy = y + step
        draw.line((lx, yy, rx, yy), fill="#2dd4bf", width=1)


def _draw_footer(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    *,
    product: str,
    version: str = "v2.1",
    accent: str = "#22d3ee",
    outline: str = "#405066",
) -> None:
    footer_font = _font(20)
    badge_font = _font(16, bold=True)
    y = image.height - 68
    right = image.width - 64
    draw.line((64, y - 22, right, y - 22), fill=outline, width=1)
    _draw_dna_icon(draw, 64, y - 3, accent)
    draw.text((94, y), "KBDNA · DNA Lab", font=footer_font, fill="#9aa8bb")

    badge_text = version
    badge_bbox = draw.textbbox((0, 0), badge_text, font=badge_font)
    badge_w = badge_bbox[2] - badge_bbox[0] + 24
    badge_h = 26
    badge_x = right - badge_w
    badge_y = y - 1
    product_bbox = draw.textbbox((0, 0), product, font=footer_font)
    product_w = product_bbox[2] - product_bbox[0]
    draw.text((badge_x - product_w - 18, y), product, font=footer_font, fill="#a8b3c5")
    draw.rounded_rectangle((badge_x, badge_y, badge_x + badge_w, badge_y + badge_h), radius=7, outline=outline, width=1)
    draw.text((badge_x + 12, badge_y + 3), badge_text, font=badge_font, fill="#8fa0b5")


def _save(image: Image.Image, output_dir: Path, prefix: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{prefix}_{int(time.time())}_{uuid4().hex[:8]}.png"
    image.save(path, "PNG", optimize=True)
    return path


def render_admixtools2_qpadm_result(summary: dict[str, Any], *, flow: dict[str, Any], elapsed_seconds: float, output_dir: Path) -> Path:
    weights = summary.get("weights") if isinstance(summary.get("weights"), list) else []
    fit = summary.get("fit") if isinstance(summary.get("fit"), dict) else {}
    feasibility = summary.get("feasibility") if isinstance(summary.get("feasibility"), dict) else {}
    references = [str(item) for item in flow.get("references", []) if str(item)]
    rows: list[dict[str, Any]] = []
    for item in weights:
        if not isinstance(item, dict):
            continue
        weight_percent = _weight_percent(item)
        stderr_percent = _stderr_percent(item)
        rows.append(
            {
                "source": str(item.get("source") or "unknown"),
                "weight": weight_percent,
                "stderr": stderr_percent,
                "z": _source_z_value(item, weight_percent, stderr_percent),
            }
        )

    width = 1080
    ref_rows = max(1, (len(references) + 1) // 2)
    detail_rows = max(1, len(rows))
    height = 597 + detail_rows * 78 + ref_rows * 38
    image, draw = _canvas(height, width=width, background=str(QPADM_ADMIXTOOLS2_VISUAL["background"]), panel=str(QPADM_ADMIXTOOLS2_VISUAL["panel"]))
    content_left = 64
    content_right = width - 64
    accent = str(QPADM_ADMIXTOOLS2_VISUAL["accent"])
    palette = list(QPADM_ADMIXTOOLS2_VISUAL["palette"])
    outline = "#33424e"
    title_font = _font(44, bold=True)
    subtitle_font = _font(21)
    metric_label_font = _font(16, bold=True)
    metric_value_font = _font(24, bold=True)
    h_font = _font(27, bold=True)
    row_font = _font(20)
    info_font = _font(22)
    small_font = _font(17)
    detail_font = _font(16)
    detail_bold_font = _font(16, bold=True)

    def draw_centered(cx: int, yy: int, text: str, font: ImageFont.ImageFont, fill: str) -> None:
        bbox = draw.textbbox((0, 0), text, font=font)
        draw.text((cx - (bbox[2] - bbox[0]) // 2, yy), text, font=font, fill=fill)

    y = 58
    draw.text((content_left, y), "ADMIXTOOLS2 qpAdm", font=title_font, fill="#f8fafc")
    draw.text((content_left, y + 54), f"signed source weights / {_target_mode_label(flow)}", font=subtitle_font, fill="#99a8b5")
    status = str(summary.get("status", "unknown"))
    status_color = "#22c55e" if status == "completed" else "#f97316"
    badge = f" {status.upper()} "
    badge_bbox = draw.textbbox((0, 0), badge, font=metric_label_font)
    badge_w = badge_bbox[2] - badge_bbox[0] + 20
    draw.rounded_rectangle((content_right - badge_w, y + 12, content_right, y + 42), radius=8, fill="#202a32", outline=status_color, width=1)
    draw.text((content_right - badge_w + 10, y + 19), badge, font=metric_label_font, fill=status_color)

    y += 114
    draw.rounded_rectangle((content_left, y, content_right, y + 58), radius=10, fill="#10171d", outline="#2b3742", width=1)
    info_y = y + 17
    draw.text((content_left + 18, info_y + 2), "Dataset", font=metric_label_font, fill="#8fa0b5")
    draw.text((content_left + 116, info_y - 1), _fit_text(draw, _dataset_label(flow.get("dataset")), info_font, 250), font=info_font, fill="#e5edf5")
    draw.text((content_left + 396, info_y + 2), "Target", font=metric_label_font, fill="#8fa0b5")
    draw.text((content_left + 480, info_y - 1), _fit_text(draw, _target_display(flow), info_font, content_right - content_left - 500), font=info_font, fill=accent)

    y += 86
    metrics = [
        ("p-value", _format_number(fit.get("p_value"))),
        ("chisq", _format_number(fit.get("chisq"))),
        ("dof", _format_number(fit.get("dof"))),
        ("rank", _format_number(fit.get("rankdrop", fit.get("f4rank")))),
        ("fit", str(feasibility.get("status", "unknown"))),
        ("time", f"{elapsed_seconds:.1f}s"),
    ]
    tile_gap = 12
    tile_w = (content_right - content_left - tile_gap * (len(metrics) - 1)) // len(metrics)
    for index, (label, value) in enumerate(metrics):
        x = content_left + index * (tile_w + tile_gap)
        draw.rounded_rectangle((x, y, x + tile_w, y + 82), radius=10, fill="#202830", outline="#33424e", width=1)
        draw.text((x + 14, y + 13), label.upper(), font=metric_label_font, fill="#8fa0b5")
        value_color = accent
        if label == "fit" and str(value).upper() == "PASS":
            value_color = "#22c55e"
        elif label == "fit" and str(value).upper() in {"FAIL", "WARNING"}:
            value_color = "#fb7185"
        value_font = _font(21, bold=True) if label == "fit" and len(str(value)) > 4 else metric_value_font
        draw.text((x + 14, y + 38), _fit_text(draw, value, value_font, tile_w - 28), font=value_font, fill=value_color)

    y += 118
    draw.text((content_left, y), "Sources", font=h_font, fill="#f8fafc")
    y += 44
    if not rows:
        draw.rounded_rectangle((content_left, y, content_right, y + 46), radius=9, fill="#10171d", outline="#2b3742", width=1)
        draw.text((content_left + 18, y + 13), "No source weights returned.", font=row_font, fill="#a8b3c5")
        y += 70
    else:
        bar_left = content_left
        bar_right = content_right - 232
        bar_w = bar_right - bar_left
        row_h = 78
        bar_h = 16
        weight_x = bar_right + 38
        se_x = bar_right + 120
        z_x = bar_right + 192
        draw.text((bar_left, y), "Source", font=metric_label_font, fill="#8fa0b5")
        draw_centered(weight_x, y, "Weight", metric_label_font, "#8fa0b5")
        draw_centered(se_x, y, "SE", metric_label_font, "#8fa0b5")
        draw_centered(z_x, y, "z", metric_label_font, "#8fa0b5")
        y += 30
        for index, row in enumerate(rows):
            row_y = y + index * row_h
            weight = float(row["weight"])
            z_value = row.get("z")
            is_negative = weight < 0
            is_overflow = weight > 100
            is_outlier = is_negative or is_overflow
            color = "#fb7185" if is_outlier else palette[index % len(palette)]
            label = _fit_text(draw, row["source"], detail_bold_font, bar_right - bar_left)
            draw.text((bar_left, row_y), label, font=detail_bold_font, fill="#e5edf5")
            baseline_y = row_y + 38
            draw.line((bar_left, baseline_y, bar_right, baseline_y), fill="#2b3742", width=2)
            fill_percent = min(100.0, max(0.0, abs(weight)))
            fill_w = int(round(bar_w * fill_percent / 100.0))
            if fill_w == 0 and weight:
                fill_w = 3
            if fill_w:
                if is_negative:
                    draw.rounded_rectangle((bar_right - fill_w, baseline_y - bar_h // 2, bar_right, baseline_y + bar_h // 2), radius=8, fill=color)
                else:
                    draw.rounded_rectangle((bar_left, baseline_y - bar_h // 2, bar_left + fill_w, baseline_y + bar_h // 2), radius=8, fill=color)
            draw_centered(weight_x, baseline_y - 12, _format_weight_percent(weight), detail_bold_font, color)
            draw_centered(se_x, baseline_y - 12, _format_number(float(row["stderr"]), percent=True), detail_font, "#cbd5e1")
            draw_centered(z_x, baseline_y - 12, _format_number(z_value), detail_font, "#cbd5e1")
        y += len(rows) * row_h + 10

    draw.text((content_left, y), "References", font=h_font, fill="#f8fafc")
    y += 42
    pill_w = (content_right - content_left - 16) // 2
    for index, ref in enumerate(references or ["none"]):
        col = 0 if index < ref_rows else 1
        row = index if col == 0 else index - ref_rows
        x = content_left + col * (pill_w + 16)
        yy = y + row * 38
        draw.rounded_rectangle((x, yy, x + pill_w, yy + 28), radius=8, fill="#10171d", outline="#2b3742", width=1)
        draw.text((x + 12, yy + 5), _fit_text(draw, ref, small_font, pill_w - 24), font=small_font, fill="#cbd5e1")

    _draw_footer(image, draw, product="ADMIXTOOLS2 qpAdm", version="AT2", accent=accent, outline="#33424e")
    return _save(image, output_dir, str(QPADM_ADMIXTOOLS2_VISUAL["prefix"]))


def render_admixtools2_qpadm_batch_result(
    batch_payload: dict[str, Any],
    *,
    flow: dict[str, Any],
    elapsed_seconds: float,
    output_dir: Path,
) -> Path:
    results = [item for item in batch_payload.get("results", []) if isinstance(item, dict)]
    sources = [str(item) for item in flow.get("sources", []) if str(item)]
    if not sources:
        sources = [str(item) for item in batch_payload.get("sources", []) if str(item)]
    palette = list(QPADM_ADMIXTOOLS2_VISUAL["palette"])
    source_colors = {source: palette[index % len(palette)] for index, source in enumerate(sources)}

    completed_results = [item for item in results if item.get("status") == "completed"]
    warning_results = [
        item
        for item in completed_results
        if str(_batch_fit_status(item)).upper() != "PASS" or (_number(_batch_p_value(item)) is not None and float(_batch_p_value(item)) < 0.05)
    ]
    p_values = [_number(_batch_p_value(item)) for item in completed_results]
    p_values = [value for value in p_values if value is not None]
    best_item = max(completed_results, key=lambda item: _number(_batch_p_value(item)) if _number(_batch_p_value(item)) is not None else -1.0, default=None)
    width = 1440
    legend_rows = max(1, math.ceil(max(1, len(sources)) / 5))
    row_h = 88
    table_h = 166 + max(1, len(results)) * row_h + legend_rows * 34
    metrics_h = 190
    height = 320 + table_h + metrics_h + 120
    image, draw = _canvas(height, width=width, background="#071019", panel="#111820")

    content_left = 56
    content_right = width - 56
    accent = str(QPADM_ADMIXTOOLS2_VISUAL["accent"])
    outline = "#263543"
    title_font = _font(48, bold=True)
    subtitle_font = _font(24)
    meta_label_font = _font(17, bold=True)
    meta_value_font = _font(20)
    h_font = _font(25, bold=True)
    row_font = _font(19, bold=True)
    small_font = _font(16)
    value_font = _font(21, bold=True)
    percent_font = _font(17, bold=True)

    y = 54
    draw.text((content_left, y), "ADMIXTOOLS2 qpAdm", font=title_font, fill="#f8fafc")
    draw.text((content_left, y + 62), "multi-target comparison / signed source weights", font=subtitle_font, fill="#9aa8bb")
    status = str(batch_payload.get("status") or "unknown").upper()
    status_color = "#22c55e" if status == "COMPLETED" else "#f59e0b"
    badge = f" {status} "
    badge_bbox = draw.textbbox((0, 0), badge, font=value_font)
    badge_w = badge_bbox[2] - badge_bbox[0] + 26
    draw.rounded_rectangle((content_right - badge_w, y + 14, content_right, y + 52), radius=9, fill="#0f1d27", outline=status_color, width=1)
    draw.text((content_right - badge_w + 13, y + 21), badge, font=value_font, fill=status_color)

    y += 120
    draw.rounded_rectangle((content_left, y, content_right, y + 58), radius=10, fill="#0d151c", outline=outline, width=1)
    draw.text((content_left + 24, y + 17), "Dataset", font=meta_label_font, fill="#90a0b3")
    draw.text((content_left + 132, y + 14), _fit_text(draw, _dataset_label(flow.get("dataset")), meta_value_font, 360), font=meta_value_font, fill="#e5edf5")
    draw.text((content_left + 680, y + 17), "Run mode", font=meta_label_font, fill="#90a0b3")
    draw.text((content_left + 802, y + 14), "Multi-target comparison", font=meta_value_font, fill=accent)

    y += 82
    panel_top = y
    panel_bottom = y + table_h
    draw.rounded_rectangle((content_left, panel_top, content_right, panel_bottom), radius=12, fill="#0d151c", outline=outline, width=1)
    draw.text((content_left + 22, y + 24), "Source weight comparison across targets", font=h_font, fill="#f8fafc")
    draw.text((content_right - 258, y + 31), "p, min |z|, max SE", font=small_font, fill="#9aa8bb")

    legend_y = y + 76
    legend_x = content_left + 180
    legend_col_w = 220
    for index, source in enumerate(sources[:15]):
        row = index // 5
        col = index % 5
        x = legend_x + col * legend_col_w
        yy = legend_y + row * 34
        color = source_colors[source]
        draw.rounded_rectangle((x, yy + 4, x + 18, yy + 22), radius=4, fill=color)
        draw.text((x + 30, yy + 2), _fit_text(draw, source, small_font, 168), font=small_font, fill="#dbe5ef")

    header_y = legend_y + legend_rows * 34 + 22
    draw.line((content_left, header_y, content_right, header_y), fill=outline, width=1)
    draw.text((content_left + 22, header_y + 24), "Target", font=small_font, fill="#9aa8bb")
    draw.text((content_left + 390, header_y + 24), "Source weights (%)", font=small_font, fill="#9aa8bb")
    draw.text((content_right - 348, header_y + 24), "P-VALUE", font=small_font, fill="#9aa8bb")
    draw.text((content_right - 232, header_y + 24), "MIN |Z|", font=small_font, fill="#9aa8bb")
    draw.text((content_right - 112, header_y + 24), "FIT", font=small_font, fill="#9aa8bb")
    row_start_y = header_y + 60
    bar_x = content_left + 210
    bar_w = content_right - bar_x - 430
    p_x = content_right - 348
    z_x = content_right - 232
    fit_x = content_right - 112

    if not results:
        draw.text((content_left + 22, row_start_y + 18), "No batch results returned.", font=row_font, fill="#a8b3c5")
    for row_index, item in enumerate(results):
        row_y = row_start_y + row_index * row_h
        draw.line((content_left, row_y, content_right, row_y), fill="#1d2a35", width=1)
        target_label = _batch_target_label(item)
        draw.text((content_left + 22, row_y + 28), _fit_text(draw, target_label, row_font, 172), font=row_font, fill=accent)

        if item.get("status") != "completed":
            error = _fit_text(draw, str(item.get("error") or "failed"), small_font, bar_w + 150)
            draw.text((bar_x, row_y + 30), error, font=small_font, fill="#fb7185")
            continue

        weight_map = _batch_weight_map(item)
        negative_items = [(source, weight_map.get(source, 0.0)) for source in sources if weight_map.get(source, 0.0) < 0]
        tag_y = row_y + 8
        tag_x = bar_x
        for source, raw_weight in negative_items[:2]:
            tag_text = f"{raw_weight:+.1f}% {_fit_text(draw, source, small_font, 120)}"
            tag_bbox = draw.textbbox((0, 0), tag_text, font=small_font)
            tag_w = min(190, tag_bbox[2] - tag_bbox[0] + 18)
            draw.rounded_rectangle((tag_x, tag_y, tag_x + tag_w, tag_y + 24), radius=6, fill="#34151a", outline="#fb7185", width=1)
            draw.text((tag_x + 9, tag_y + 4), _fit_text(draw, tag_text, small_font, tag_w - 18), font=small_font, fill="#fb7185")
            tag_x += tag_w + 8
        if len(negative_items) > 2:
            draw.text((tag_x, tag_y + 4), f"+{len(negative_items) - 2} negative", font=small_font, fill="#fb7185")

        bar_y = row_y + (38 if negative_items else 26)
        draw.rounded_rectangle((bar_x, bar_y, bar_x + bar_w, bar_y + 35), radius=7, fill="#071019", outline="#1d2a35", width=1)
        cursor = bar_x
        positive_total = sum(max(0.0, weight_map.get(source, 0.0)) for source in sources)
        positive_scale = positive_total if positive_total > 0 else 100.0
        positive_sources = [source for source in sources if weight_map.get(source, 0.0) > 0]
        if positive_sources:
            for index, source in enumerate(sources):
                raw_weight = weight_map.get(source, 0.0)
                if raw_weight <= 0:
                    continue
                if source == positive_sources[-1]:
                    segment_right = bar_x + bar_w
                else:
                    segment_w = int(round(bar_w * raw_weight / positive_scale))
                    if segment_w <= 0:
                        continue
                    segment_right = min(bar_x + bar_w, cursor + segment_w)
                color = source_colors[source]
                draw.rectangle((cursor, bar_y, segment_right, bar_y + 35), fill=color)
                percent_text = f"{raw_weight:.1f}%"
                visible_w = segment_right - cursor
                if visible_w > 58:
                    text_bbox = draw.textbbox((0, 0), percent_text, font=percent_font)
                    text_w = text_bbox[2] - text_bbox[0]
                    draw.text((cursor + max(6, (visible_w - text_w) // 2), bar_y + 8), percent_text, font=percent_font, fill="#071019")
                cursor = segment_right
        draw.rounded_rectangle((bar_x, bar_y, bar_x + bar_w, bar_y + 35), radius=7, outline="#223241", width=1)

        p_text = _format_number(_batch_p_value(item))
        min_abs_z, max_se = _batch_weight_diagnostics(item)
        fit_text = str(_batch_fit_status(item)).upper()
        fit_color = "#22c55e" if fit_text == "PASS" else "#f59e0b"
        draw.text((p_x, row_y + 28), p_text, font=value_font, fill=accent)
        draw.text((z_x, row_y + 23), _format_number(min_abs_z), font=value_font, fill="#dbe5ef")
        if max_se is not None:
            draw.text((z_x, row_y + 51), f"SE {_format_number(max_se, percent=True)}", font=_font(12), fill="#9aa8bb")
        draw.rounded_rectangle((fit_x, row_y + 22, fit_x + 110, row_y + 56), radius=7, fill="#10231b" if fit_text == "PASS" else "#2a210c", outline=fit_color, width=1)
        draw.text((fit_x + 13, row_y + 29), _fit_text(draw, fit_text, small_font, 84), font=small_font, fill=fit_color)
        reason = _batch_warning_reason(item)
        if fit_text != "PASS" and reason:
            draw.text((fit_x + 2, row_y + 60), _fit_text(draw, reason, _font(12), 116), font=_font(12), fill="#9aa8bb")

    y = panel_bottom + 26
    draw.rounded_rectangle((content_left, y, content_right, y + metrics_h - 34), radius=12, fill="#0d151c", outline=outline, width=1)
    draw.text((content_left + 22, y + 22), "Top-line metrics", font=h_font, fill="#f8fafc")
    metric_y = y + 70
    metric_gap = 20
    metric_w = (content_right - content_left - 44 - metric_gap * 3) // 4
    avg_p = sum(p_values) / len(p_values) if p_values else None
    metrics = [
        ("HIGHEST P-VALUE", _batch_target_label(best_item) if best_item else "n/a", f"p = {_format_number(_batch_p_value(best_item))}" if best_item else ""),
        ("AVERAGE P-VALUE", _format_number(avg_p), f"across {len(p_values)} completed"),
        ("TOTAL TARGETS", str(len(results)), f"{len(completed_results)} completed"),
        ("WARNINGS", str(len(warning_results) + (len(results) - len(completed_results))), f"of {len(results)} targets"),
    ]
    for index, (label, value, subvalue) in enumerate(metrics):
        x = content_left + 22 + index * (metric_w + metric_gap)
        draw.rounded_rectangle((x, metric_y, x + metric_w, metric_y + 94), radius=9, fill="#111b24", outline=outline, width=1)
        draw.text((x + 18, metric_y + 16), label, font=small_font, fill="#b8c4d6")
        draw.text((x + 18, metric_y + 44), _fit_text(draw, value, value_font, metric_w - 36), font=value_font, fill="#f8fafc")
        if subvalue:
            draw.text((x + 18, metric_y + 70), _fit_text(draw, subvalue, small_font, metric_w - 36), font=small_font, fill=accent if index == 0 else "#9aa8bb")

    _draw_footer(image, draw, product="ADMIXTOOLS2 qpAdm", version="AT2", accent="#d4af37", outline=outline)
    return _save(image, output_dir, "qpadm_admixtools2_batch")


def _batch_summary(item: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {}
    summary = item.get("summary")
    return summary if isinstance(summary, dict) else {}


def _batch_fit(item: dict[str, Any] | None) -> dict[str, Any]:
    summary = _batch_summary(item)
    fit = summary.get("fit")
    return fit if isinstance(fit, dict) else {}


def _batch_feasibility(item: dict[str, Any] | None) -> dict[str, Any]:
    summary = _batch_summary(item)
    feasibility = summary.get("feasibility")
    return feasibility if isinstance(feasibility, dict) else {}


def _batch_p_value(item: dict[str, Any] | None) -> object:
    return _batch_fit(item).get("p_value")


def _batch_fit_status(item: dict[str, Any] | None) -> str:
    value = _batch_feasibility(item).get("status")
    return str(value or "unknown")


def _batch_warning_reason(item: dict[str, Any] | None) -> str:
    reason = str(_batch_feasibility(item).get("reason") or "").strip()
    lowered = reason.casefold()
    if "negative" in lowered:
        return "negative"
    if "z < 2" in lowered or "z<2" in lowered:
        return "weak source"
    if "p_value" in lowered or "p-value" in lowered:
        return "low p"
    return reason


def _batch_target_label(item: dict[str, Any] | None) -> str:
    if not isinstance(item, dict):
        return "n/a"
    return str(item.get("target_label") or item.get("target") or "unknown")


def _batch_weight_rows(item: dict[str, Any] | None) -> list[dict[str, Any]]:
    summary = _batch_summary(item)
    weights = summary.get("weights") if isinstance(summary.get("weights"), list) else []
    return [row for row in weights if isinstance(row, dict)]


def _batch_weight_map(item: dict[str, Any]) -> dict[str, float]:
    result: dict[str, float] = {}
    for row in _batch_weight_rows(item):
        source = str(row.get("source") or row.get("backend_id") or "")
        if not source:
            continue
        result[source] = _weight_percent(row)
    return result


def _batch_weight_diagnostics(item: dict[str, Any] | None) -> tuple[float | None, float | None]:
    z_values: list[float] = []
    se_values: list[float] = []
    for row in _batch_weight_rows(item):
        weight_percent = _weight_percent(row)
        stderr_percent = _stderr_percent(row)
        z_value = _source_z_value(row, weight_percent, stderr_percent)
        if z_value is not None:
            z_values.append(abs(z_value))
        if stderr_percent:
            se_values.append(abs(stderr_percent))
    min_abs_z = min(z_values) if z_values else None
    max_se = max(se_values) if se_values else None
    return min_abs_z, max_se


def render_qpadm_result(summary: dict[str, Any], *, flow: dict[str, Any], elapsed_seconds: float, output_dir: Path) -> Path:
    if _qpadm_engine(flow.get("engine") or summary.get("engine")) == QPADM_ENGINE_ADMIXTOOLS2:
        return render_admixtools2_qpadm_result(summary, flow=flow, elapsed_seconds=elapsed_seconds, output_dir=output_dir)

    profile = _qpadm_visual_profile(flow, summary)
    weights = summary.get("weights") if isinstance(summary.get("weights"), list) else []
    fit = summary.get("fit") if isinstance(summary.get("fit"), dict) else {}
    feasibility = summary.get("feasibility") if isinstance(summary.get("feasibility"), dict) else {}
    references = [str(item) for item in flow.get("references", []) if str(item)]
    ref_row_height = 30
    height = 520 + len(weights) * 38 + max(1, len(references)) * ref_row_height
    qpadm_width = 940
    content_left = 64
    content_right = qpadm_width - 64
    image, draw = _canvas(
        height,
        width=qpadm_width,
        background=str(profile["background"]),
        panel=str(profile["panel"]),
    )

    title_font = _font(42, bold=True)
    h_font = _font(26, bold=True)
    text_font = _font(24)
    value_font = _font(24, bold=True)
    pvalue_font = _font(34, bold=True)
    mono_font = _font(22)
    small_font = _font(20)

    y = 62
    draw.text((64, y), str(profile["title"]), font=title_font, fill="#f8fafc")
    y += 62
    meta = [
        ("Dataset", _dataset_label(flow.get("dataset"))),
        ("Target", _target_display(flow)),
        ("Status", str(summary.get("status", "unknown"))),
        ("Fit", str(feasibility.get("status", "unknown"))),
        ("p-value", _format_number(fit.get("p_value"))),
        ("Time", f"{elapsed_seconds:.1f}s"),
    ]
    x1, x2 = 68, 500
    for index, (label, value) in enumerate(meta):
        x = x1 if index % 2 == 0 else x2
        row_y = y + (index // 2) * 40
        value_color = str(profile["accent"])
        font = value_font
        value_y = row_y
        if label == "p-value":
            value_color = "#ffd166"
            font = pvalue_font
            value_y = row_y - 8
        elif label == "Fit" and str(value).upper() == "PASS":
            value_color = "#80ed99"
        elif label == "Fit" and str(value).upper() == "FAIL":
            value_color = "#fb7185"
        draw.text((x, row_y), f"{label}: ", font=text_font, fill="#a8b3c5")
        max_value_width = content_right - (x + 132)
        draw.text((x + 132, value_y), _fit_text(draw, value, font, max_value_width), font=font, fill=value_color)
    y += 132

    draw.text((content_left, y), "Sources", font=h_font, fill="#f8fafc")
    y += 42
    positives: list[tuple[str, float, float]] = []
    for item in weights:
        if not isinstance(item, dict):
            continue
        source = str(item.get("source") or "unknown")
        weight = max(0.0, float(item.get("weight_percent") or 0.0))
        stderr = float(item.get("stderr_percent") or 0.0)
        positives.append((source, weight, stderr))
    bar_x, bar_y, bar_w, bar_h = content_left, y, content_right - content_left, 58
    _draw_segment_bar(
        image,
        draw,
        x=bar_x,
        y=bar_y,
        width=bar_w,
        height=bar_h,
        weights=[weight for _, weight, _ in positives],
        palette=list(profile["palette"]),
        outline=str(profile["outline"]),
    )
    y += 76

    weight_x = content_right - 216
    source_text_width = weight_x - 120
    for index, (source, weight, stderr) in enumerate(positives):
        palette = list(profile["palette"])
        color = palette[index % len(palette)]
        draw.rounded_rectangle((content_left, y + 7, content_left + 22, y + 29), radius=5, fill=color)
        draw.text((100, y), _fit_text(draw, source, mono_font, source_text_width), font=mono_font, fill=str(profile["accent"]))
        draw.text((weight_x, y), f"{_format_number(weight, percent=True)} ± {_format_number(stderr, percent=True)}", font=mono_font, fill="#f8fafc")
        y += 38

    y += 14
    draw.text((content_left, y), "References", font=h_font, fill="#f8fafc")
    y += 36
    for index, ref in enumerate(references):
        ref_y = y + index * ref_row_height
        x = content_left
        draw.text((x, ref_y), "•", font=small_font, fill="#94a3b8")
        draw.text((x + 24, ref_y), _fit_text(draw, ref, small_font, content_right - x - 24), font=small_font, fill=str(profile["accent"]))

    _draw_footer(
        image,
        draw,
        product=str(profile["product"]),
        version=str(profile["version"]),
        accent=str(profile["accent"]),
        outline=str(profile["outline"]),
    )

    return _save(image, output_dir, str(profile["prefix"]))


def render_qpwave_result(
    *,
    ranks: list[dict[str, Any]],
    flow: dict[str, Any],
    elapsed_seconds: float,
    output_dir: Path,
) -> Path:
    left = [str(item) for item in flow.get("left", []) if str(item)]
    right = [str(item) for item in flow.get("right", []) if str(item)]
    height = 670 + len(ranks) * 48 + max(len(left), len(right), 1) * 34
    image, draw = _canvas(height)
    title_font = _font(42, bold=True)
    h_font = _font(26, bold=True)
    text_font = _font(24)
    mono_font = _font(22)
    small_font = _font(20)

    y = 62
    draw.text((64, y), "qpWave", font=title_font, fill="#f8fafc")
    y += 62
    meta = [
        ("Dataset", _dataset_label(flow.get("dataset"))),
        ("Status", "completed"),
        ("Left", str(len(left))),
        ("Right", str(len(right))),
        ("Time", f"{elapsed_seconds:.1f}s"),
    ]
    for index, (label, value) in enumerate(meta):
        x = 68 if index % 2 == 0 else 610
        row_y = y + (index // 2) * 40
        draw.text((x, row_y), f"{label}: ", font=text_font, fill="#a8b3c5")
        draw.text((x + 132, row_y), value, font=text_font, fill="#5eead4")
    y += 142

    draw.text((64, y), "Rank tests", font=h_font, fill="#f8fafc")
    y += 48
    draw.rounded_rectangle((64, y, 1136, y + 46), radius=10, fill="#111827")
    headers = [("rank", 90), ("p-value", 300), ("chisq", 560), ("dof", 800)]
    for label, x in headers:
        draw.text((x, y + 10), label, font=small_font, fill="#94a3b8")
    y += 56
    for item in ranks:
        p_value = float(item.get("tail") or 0.0)
        color = "#80ed99" if p_value >= 0.05 else "#fb7185"
        draw.text((90, y), str(item.get("rank", "")), font=mono_font, fill="#f8fafc")
        draw.text((300, y), _format_number(p_value), font=mono_font, fill=color)
        draw.text((560, y), _format_number(item.get("chisq")), font=mono_font, fill="#f8fafc")
        draw.text((800, y), _format_number(item.get("dof")), font=mono_font, fill="#f8fafc")
        y += 42

    y += 32
    draw.text((64, y), "Left", font=h_font, fill="#f8fafc")
    draw.text((610, y), "Right", font=h_font, fill="#f8fafc")
    y += 44
    max_rows = max(len(left), len(right))
    for index in range(max_rows):
        row_y = y + index * 34
        if index < len(left):
            draw.text((64, row_y), _fit_text(draw, f"• {left[index]}", small_font, 500), font=small_font, fill="#5eead4")
        if index < len(right):
            draw.text((610, row_y), _fit_text(draw, f"• {right[index]}", small_font, 526), font=small_font, fill="#5eead4")

    _draw_footer(image, draw, product="qpWave", version="v2.1")
    return _save(image, output_dir, "qpwave_result")
