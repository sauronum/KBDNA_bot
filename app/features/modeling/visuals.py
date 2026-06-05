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


def _dataset_label(dataset: object) -> str:
    value = str(dataset or "")
    return DATASET_LABELS.get(value, value or "not selected")


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


def _target_display(flow: dict[str, Any]) -> str:
    return str(flow.get("target_label") or flow.get("target") or "unknown")


def _canvas(height: int, *, width: int = 1200) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGB", (width, max(820, height)), "#10141b")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((28, 28, image.width - 28, image.height - 28), radius=24, fill="#1d2630")
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
) -> None:
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
            color = PALETTE[index % len(PALETTE)]
            segment_draw.rectangle((cursor, y, min(x + width, cursor + segment_w), y + height), fill=color)
            cursor += segment_w

    image.paste(segments, (0, 0), mask)
    draw.line(points + [points[0]], fill="#405066", width=2)


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


def _draw_footer(image: Image.Image, draw: ImageDraw.ImageDraw, *, product: str, version: str = "v2.1") -> None:
    footer_font = _font(20)
    badge_font = _font(16, bold=True)
    y = image.height - 68
    right = image.width - 64
    draw.line((64, y - 22, right, y - 22), fill="#334155", width=1)
    _draw_dna_icon(draw, 64, y - 3, "#22d3ee")
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
    draw.rounded_rectangle((badge_x, badge_y, badge_x + badge_w, badge_y + badge_h), radius=7, outline="#405066", width=1)
    draw.text((badge_x + 12, badge_y + 3), badge_text, font=badge_font, fill="#8fa0b5")


def _save(image: Image.Image, output_dir: Path, prefix: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{prefix}_{int(time.time())}_{uuid4().hex[:8]}.png"
    image.save(path, "PNG", optimize=True)
    return path


def render_qpadm_result(summary: dict[str, Any], *, flow: dict[str, Any], elapsed_seconds: float, output_dir: Path) -> Path:
    weights = summary.get("weights") if isinstance(summary.get("weights"), list) else []
    fit = summary.get("fit") if isinstance(summary.get("fit"), dict) else {}
    feasibility = summary.get("feasibility") if isinstance(summary.get("feasibility"), dict) else {}
    references = [str(item) for item in flow.get("references", []) if str(item)]
    ref_row_height = 30
    height = 520 + len(weights) * 38 + max(1, len(references)) * ref_row_height
    qpadm_width = 940
    content_left = 64
    content_right = qpadm_width - 64
    image, draw = _canvas(height, width=qpadm_width)

    title_font = _font(42, bold=True)
    h_font = _font(26, bold=True)
    text_font = _font(24)
    value_font = _font(24, bold=True)
    pvalue_font = _font(34, bold=True)
    mono_font = _font(22)
    small_font = _font(20)

    y = 62
    draw.text((64, y), "qpAdm classic", font=title_font, fill="#f8fafc")
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
        value_color = "#5eead4"
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
    _draw_segment_bar(image, draw, x=bar_x, y=bar_y, width=bar_w, height=bar_h, weights=[weight for _, weight, _ in positives])
    y += 76

    weight_x = content_right - 216
    source_text_width = weight_x - 120
    for index, (source, weight, stderr) in enumerate(positives):
        color = PALETTE[index % len(PALETTE)]
        draw.rounded_rectangle((content_left, y + 7, content_left + 22, y + 29), radius=5, fill=color)
        draw.text((100, y), _fit_text(draw, source, mono_font, source_text_width), font=mono_font, fill="#5eead4")
        draw.text((weight_x, y), f"{_format_number(weight, percent=True)} ± {_format_number(stderr, percent=True)}", font=mono_font, fill="#f8fafc")
        y += 38

    y += 14
    draw.text((content_left, y), "References", font=h_font, fill="#f8fafc")
    y += 36
    for index, ref in enumerate(references):
        ref_y = y + index * ref_row_height
        x = content_left
        draw.text((x, ref_y), "•", font=small_font, fill="#94a3b8")
        draw.text((x + 24, ref_y), _fit_text(draw, ref, small_font, content_right - x - 24), font=small_font, fill="#5eead4")

    _draw_footer(image, draw, product="qpAdm classic", version="v2.1")

    return _save(image, output_dir, "qpadm_result")


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
