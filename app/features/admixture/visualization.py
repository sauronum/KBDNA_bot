from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Sequence, Tuple

from PIL import Image, ImageDraw, ImageFont

from .oracle import OracleMatch, OracleMixMatch, OracleReferenceSet


Color = Tuple[int, int, int]

_WIDTH = 1280
_HEIGHT = 800
_BG: Color = (12, 17, 28)
_PANEL: Color = (22, 30, 44)
_PANEL_SOFT: Color = (28, 39, 56)
_PLOT: Color = (16, 23, 35)
_GRID: Color = (49, 62, 82)
_TEXT: Color = (239, 244, 250)
_MUTED: Color = (155, 169, 190)
_FAINT: Color = (92, 108, 132)
_GOLD: Color = (255, 191, 92)
_ORANGE: Color = (232, 139, 88)
_CYAN: Color = (97, 205, 215)
_GREEN: Color = (112, 213, 158)
_PINK: Color = (230, 112, 151)

_PALETTE: Tuple[Color, ...] = (
    (232, 139, 88),
    (97, 205, 215),
    (255, 214, 104),
    (116, 218, 166),
    (229, 117, 157),
    (139, 173, 255),
    (185, 135, 246),
    (154, 207, 103),
    (238, 164, 204),
    (121, 185, 255),
)


def render_profile_png(
    output_path: Path,
    *,
    sample_name: str,
    coordinate_name: str,
    payload: dict[str, object],
    status_label: str = "PROFILE",
) -> None:
    model = str(payload.get("model") or "Admixture")
    components = _visible_components(payload)
    macro_groups = _macro_groups(payload, 8)
    total = _float(payload.get("total"))

    image = _base_image()
    draw = ImageDraw.Draw(image, "RGBA")
    fonts = _fonts()
    _draw_header(draw, fonts, eyebrow="ADMIXTURE", title=f"{model} PROFILE", sample_name=sample_name, pill=status_label)
    _draw_bar_panel(
        draw,
        fonts,
        (40, 116, 760, 540),
        title="Components",
        subtitle="all components >= 0.10%",
        items=components,
        value_suffix="%",
        allow_columns=True,
    )
    if macro_groups:
        _draw_bar_panel(
            draw,
            fonts,
            (800, 116, 440, 540),
            title="Macro signal",
            subtitle="grouped K36 components",
            items=macro_groups,
            value_suffix="%",
            compact=True,
        )
    else:
        _draw_profile_metrics_panel(draw, fonts, (800, 116, 440, 540), payload=payload)
    strongest = components[0] if components else ("profile", 0.0)
    _draw_footer(
        draw,
        fonts,
        left=f"Sample: {sample_name}",
        middle=f"Model: {model}     Coordinates: {coordinate_name}",
        right=f"Top: {_display_name(strongest[0])} {strongest[1]:.2f}%     Total: {total:.2f}",
    )
    image.save(output_path)


def render_compare_png(
    output_path: Path,
    *,
    left_name: str,
    right_name: str,
    comparison: dict[str, object],
) -> None:
    model = str(comparison.get("model") or "Admixture")
    differences = [
        item for item in comparison.get("differences") or []
        if isinstance(item, dict)
    ][:12]
    image = _base_image()
    draw = ImageDraw.Draw(image, "RGBA")
    fonts = _fonts()
    _draw_header(draw, fonts, eyebrow="ADMIXTURE", title=f"COMPARE {model}", sample_name=f"{left_name} vs {right_name}", pill="COMPARE")

    chart = (40, 126, 870, 548)
    _panel(draw, chart)
    x, y, w, h = chart
    draw.text((x + 22, y + 20), "Largest differences", fill=(*_TEXT, 255), font=fonts["section"])
    draw.text((x + 22, y + 50), "component values and absolute difference", fill=(*_MUTED, 255), font=fonts["tiny"])

    name_x = x + 24
    left_value_x = x + 246
    bar_left = x + 350
    bar_width = 306
    center = bar_left + bar_width // 2
    right_value_x = x + 688
    delta_x = x + 782
    top_y = y + 82
    bottom_y = y + h - 30
    draw.line((bar_left, top_y, bar_left, bottom_y), fill=(*_GRID, 115), width=1)
    draw.line((center, top_y, center, bottom_y), fill=(*_GRID, 210), width=2)
    draw.line((bar_left + bar_width, top_y, bar_left + bar_width, bottom_y), fill=(*_GRID, 115), width=1)
    draw.text((left_value_x, y + 74), _ellipsize(left_name, fonts["tiny"], 88, draw), fill=(*_ORANGE, 255), font=fonts["tiny"])
    draw.text((right_value_x, y + 74), _ellipsize(right_name, fonts["tiny"], 88, draw), fill=(*_CYAN, 255), font=fonts["tiny"])
    draw.text((delta_x, y + 74), "Δ", fill=(*_MUTED, 255), font=fonts["tiny"])

    max_delta = max((_float(item.get("abs_delta")) for item in differences), default=1.0)
    max_delta = max(max_delta, 1.0)
    row_y = y + 104
    row_h = 34
    for index, item in enumerate(differences):
        name = _display_name(str(item.get("name") or "component"))
        delta = _float(item.get("delta"))
        left_value = _float(item.get("left"))
        right_value = _float(item.get("right"))
        current_y = row_y + index * row_h
        if current_y + row_h > y + h - 24:
            break
        scaled_width = int((abs(delta) / max_delta) * ((bar_width // 2) - 8))
        color = _ORANGE if delta >= 0 else _CYAN
        if index and index % 3 == 0:
            draw.line((x + 12, current_y - 8, x + w - 12, current_y - 8), fill=(*_GRID, 70), width=1)
        draw.text((name_x, current_y + 3), _ellipsize(name, fonts["tiny"], 200, draw), fill=(*_TEXT, 255), font=fonts["tiny"])
        draw.text((left_value_x, current_y + 3), f"{left_value:.2f}", fill=(*_MUTED, 255), font=fonts["mono"])
        draw.text((right_value_x, current_y + 3), f"{right_value:.2f}", fill=(*_MUTED, 255), font=fonts["mono"])
        if delta >= 0:
            rect = (center - scaled_width, current_y + 7, center, current_y + 20)
        else:
            rect = (center, current_y + 7, center + scaled_width, current_y + 20)
        draw.rounded_rectangle(rect, radius=6, fill=(*color, 230))
        draw.text((delta_x, current_y + 3), f"{delta:+.2f}", fill=(*color, 255), font=fonts["mono"])

    _draw_compare_metrics_panel(draw, fonts, (932, 126, 308, 548), comparison=comparison)
    _draw_footer(
        draw,
        fonts,
        left=f"Left: {left_name}",
        middle=f"Right: {right_name}",
        right=f"Total difference: {_float(comparison.get('total_absolute_difference')):.2f}",
    )
    image.save(output_path)


def render_oracle_png(
    output_path: Path,
    *,
    sample_name: str,
    model: str,
    reference_set: OracleReferenceSet,
    matches: Sequence[OracleMatch],
) -> None:
    image = _base_image()
    draw = ImageDraw.Draw(image, "RGBA")
    fonts = _fonts()
    _draw_header(draw, fonts, eyebrow="ADMIXTURE", title=f"{model} SIMILAR POPULATIONS", sample_name=sample_name, pill="SIMILAR")
    _draw_distance_panel(
        draw,
        fonts,
        (40, 116, 800, 540),
        title="Closest populations",
        subtitle="Euclidean distance between admixture percentages",
        matches=matches[:12],
    )
    _draw_oracle_side_panel(draw, fonts, (912, 116, 328, 540), reference_set=reference_set, matches=matches)
    best = matches[0] if matches else None
    _draw_footer(
        draw,
        fonts,
        left=f"Sample: {sample_name}",
        middle=f"Reference: {reference_set.source.title}",
        right=f"Closest: {best.population if best else '-'}     Distance: {best.distance:.4f}" if best else "Closest: -",
    )
    image.save(output_path)


def render_oracle_mix_png(
    output_path: Path,
    *,
    sample_name: str,
    model: str,
    mode_label: str,
    reference_set: OracleReferenceSet,
    single_matches: Sequence[OracleMatch],
    mix_matches: Sequence[OracleMixMatch],
) -> None:
    image = _base_image()
    draw = ImageDraw.Draw(image, "RGBA")
    fonts = _fonts()
    _draw_header(draw, fonts, eyebrow="ADMIXTURE", title=f"{model} ORACLE MIX", sample_name=sample_name, pill=mode_label.upper())
    _draw_mix_panel(draw, fonts, (40, 116, 800, 540), mode_label=mode_label, matches=mix_matches[:9])
    _draw_mix_side_panel(
        draw,
        fonts,
        (912, 116, 328, 540),
        reference_set=reference_set,
        single_matches=single_matches,
        mix_matches=mix_matches,
        mode_label=mode_label,
    )
    best = mix_matches[0] if mix_matches else None
    _draw_footer(
        draw,
        fonts,
        left=f"Sample: {sample_name}",
        middle=f"Reference: {reference_set.source.title}",
        right=f"Best {mode_label}: {_mix_inline(best) if best else '-'}",
    )
    image.save(output_path)


def _base_image() -> Image.Image:
    image = Image.new("RGB", (_WIDTH, _HEIGHT), _BG)
    draw = ImageDraw.Draw(image, "RGBA")
    for y in range(_HEIGHT):
        tint = int(16 + 18 * (y / _HEIGHT))
        draw.line((0, y, _WIDTH, y), fill=(11, tint, 27 + tint // 3, 255))
    draw.rounded_rectangle((24, 24, _WIDTH - 24, _HEIGHT - 24), radius=8, outline=(54, 70, 91, 220), width=1)
    return image


def _draw_header(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, ImageFont.ImageFont],
    *,
    eyebrow: str,
    title: str,
    sample_name: str,
    pill: str,
) -> None:
    draw.text((42, 36), eyebrow.upper(), fill=(*_MUTED, 255), font=fonts["label"])
    draw.text((42, 58), _ellipsize(title.upper(), fonts["title"], 780, draw), fill=(*_TEXT, 255), font=fonts["title"])
    pill_text = pill.upper()
    pill_width = int(draw.textlength(pill_text, font=fonts["label"])) + 28
    right_edge = _WIDTH - 72
    pill_box = (right_edge - pill_width, 44, right_edge, 70)
    draw.rounded_rectangle(pill_box, radius=8, fill=(31, 44, 62, 235), outline=(70, 88, 111, 220), width=1)
    draw.text((pill_box[0] + 14, pill_box[1] + 8), pill_text, fill=(*_MUTED, 255), font=fonts["label"])
    sample = _ellipsize(sample_name, fonts["small"], 330, draw)
    label = "SAMPLE"
    label_width = int(draw.textlength(label, font=fonts["label"]))
    sample_width = int(draw.textlength(sample, font=fonts["small"]))
    start_x = right_edge - label_width - 10 - sample_width
    draw.text((start_x, 84), label, fill=(*_MUTED, 255), font=fonts["label"])
    draw.text((start_x + label_width + 10, 82), sample, fill=(*_TEXT, 255), font=fonts["small"])


def _draw_bar_panel(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, ImageFont.ImageFont],
    rect: tuple[int, int, int, int],
    *,
    title: str,
    subtitle: str,
    items: Sequence[tuple[str, float]],
    value_suffix: str,
    compact: bool = False,
    allow_columns: bool = False,
) -> None:
    _panel(draw, rect)
    x, y, w, h = rect
    draw.text((x + 22, y + 20), title, fill=(*_TEXT, 255), font=fonts["section"])
    draw.text((x + 22, y + 48), subtitle, fill=(*_MUTED, 255), font=fonts["tiny"])
    max_value = max((value for _, value in items), default=1.0)
    max_value = max(max_value, 1.0)
    if allow_columns and len(items) > 12:
        _draw_multi_column_bars(
            draw,
            fonts,
            rect,
            items=items,
            value_suffix=value_suffix,
            max_value=max_value,
        )
        return
    row_h = 40 if compact else 42
    start_y = y + 84
    bar_x = x + (190 if compact else 250)
    bar_w = w - (260 if compact else 355)
    for index, (name, value) in enumerate(items):
        row_y = start_y + index * row_h
        if row_y + row_h > y + h - 26:
            break
        color = _PALETTE[index % len(_PALETTE)]
        label = _ellipsize(_display_name(name), fonts["small"], 160 if compact else 210, draw)
        draw.text((x + 22, row_y + 3), label, fill=(*_TEXT, 255), font=fonts["small"])
        bg_rect = (bar_x, row_y + 7, bar_x + bar_w, row_y + 22)
        draw.rounded_rectangle(bg_rect, radius=7, fill=(38, 48, 66, 210))
        fill_w = max(4, int((value / max_value) * bar_w))
        draw.rounded_rectangle((bar_x, row_y + 7, bar_x + fill_w, row_y + 22), radius=7, fill=(*color, 230))
        value_text = f"{value:.2f}{value_suffix}"
        draw.text((bar_x + bar_w + 18, row_y + 2), value_text, fill=(*_MUTED, 255), font=fonts["mono"])


def _draw_multi_column_bars(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, ImageFont.ImageFont],
    rect: tuple[int, int, int, int],
    *,
    items: Sequence[tuple[str, float]],
    value_suffix: str,
    max_value: float,
) -> None:
    x, y, w, h = rect
    columns = 2
    rows_per_column = max(1, (len(items) + columns - 1) // columns)
    start_y = y + 84
    bottom_y = y + h - 28
    available_h = max(1, bottom_y - start_y)
    row_h = max(20, min(31, available_h // rows_per_column))
    label_font = fonts["tiny"] if row_h < 27 else fonts["small"]
    value_font = fonts["tiny"] if row_h < 25 else fonts["mono"]
    column_gap = 22
    column_w = (w - 44 - column_gap) // columns
    label_w = 126 if row_h < 27 else 142
    value_w = 52
    for index, (name, value) in enumerate(items):
        column = index // rows_per_column
        row = index % rows_per_column
        if column >= columns:
            break
        row_y = start_y + row * row_h
        if row_y + row_h > bottom_y:
            break
        column_x = x + 22 + column * (column_w + column_gap)
        bar_x = column_x + label_w + 10
        bar_w = max(46, column_w - label_w - value_w - 20)
        bar_h = 11 if row_h < 24 else 13
        color = _PALETTE[index % len(_PALETTE)]
        label = _ellipsize(_display_name(name), label_font, label_w, draw)
        draw.text((column_x, row_y + 1), label, fill=(*_TEXT, 255), font=label_font)
        bg_rect = (bar_x, row_y + 5, bar_x + bar_w, row_y + 5 + bar_h)
        draw.rounded_rectangle(bg_rect, radius=6, fill=(38, 48, 66, 210))
        fill_w = max(4, int((value / max_value) * bar_w))
        draw.rounded_rectangle((bar_x, row_y + 5, bar_x + fill_w, row_y + 5 + bar_h), radius=6, fill=(*color, 230))
        draw.text((bar_x + bar_w + 10, row_y), f"{value:.2f}{value_suffix}", fill=(*_MUTED, 255), font=value_font)


def _draw_profile_metrics_panel(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, ImageFont.ImageFont],
    rect: tuple[int, int, int, int],
    *,
    payload: dict[str, object],
) -> None:
    _panel(draw, rect)
    x, y, w, _h = rect
    components = _components(payload)
    metrics = [
        ("Components", str(len(components))),
        ("Total", f"{_float(payload.get('total')):.2f}"),
        ("Vendor", str(payload.get("vendor") or "raw")),
    ]
    draw.text((x + 22, y + 20), "Run summary", fill=(*_TEXT, 255), font=fonts["section"])
    draw.text((x + 22, y + 48), "raw calculator output", fill=(*_MUTED, 255), font=fonts["tiny"])
    card_y = y + 92
    for index, (label, value) in enumerate(metrics):
        yy = card_y + index * 86
        draw.rounded_rectangle((x + 22, yy, x + w - 22, yy + 64), radius=8, fill=(*_PANEL_SOFT, 220), outline=(54, 69, 90, 160), width=1)
        draw.text((x + 44, yy + 12), label.upper(), fill=(*_MUTED, 255), font=fonts["label"])
        draw.text((x + 44, yy + 34), _ellipsize(value, fonts["small"], w - 90, draw), fill=(*_TEXT, 255), font=fonts["small"])
    draw.text((x + 22, y + 382), "Profile percentages are model-relative, not literal ancestry shares.", fill=(*_FAINT, 255), font=fonts["tiny"])


def _draw_compare_metrics_panel(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, ImageFont.ImageFont],
    rect: tuple[int, int, int, int],
    *,
    comparison: dict[str, object],
) -> None:
    _panel(draw, rect)
    x, y, w, h = rect
    metrics = [
        ("Components", f"{int(comparison.get('component_count') or 0)}"),
        ("Total diff", f"{_float(comparison.get('total_absolute_difference')):.2f}"),
        ("Avg diff", f"{_float(comparison.get('average_absolute_difference')):.2f}"),
    ]
    draw.text((x + 22, y + 20), "Comparison", fill=(*_TEXT, 255), font=fonts["section"])
    draw.text((x + 22, y + 48), "absolute component differences", fill=(*_MUTED, 255), font=fonts["tiny"])
    for index, (label, value) in enumerate(metrics):
        yy = y + 96 + index * 86
        draw.rounded_rectangle((x + 22, yy, x + w - 22, yy + 64), radius=8, fill=(*_PANEL_SOFT, 220), outline=(54, 69, 90, 160), width=1)
        draw.text((x + 44, yy + 12), label.upper(), fill=(*_MUTED, 255), font=fonts["label"])
        draw.text((x + 44, yy + 34), value, fill=(*_TEXT, 255), font=fonts["small"])
    draw.text(
        (x + 22, y + h - 52),
        _ellipsize("Model-relative absolute differences.", fonts["tiny"], w - 44, draw),
        fill=(*_FAINT, 255),
        font=fonts["tiny"],
    )


def _draw_distance_panel(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, ImageFont.ImageFont],
    rect: tuple[int, int, int, int],
    *,
    title: str,
    subtitle: str,
    matches: Sequence[OracleMatch],
) -> None:
    _panel(draw, rect)
    x, y, w, h = rect
    draw.text((x + 22, y + 20), title, fill=(*_TEXT, 255), font=fonts["section"])
    draw.text((x + 22, y + 48), subtitle, fill=(*_MUTED, 255), font=fonts["tiny"])
    distances = [float(match.distance) for match in matches]
    best = min(distances) if distances else 0.0
    worst = max(distances) if distances else 1.0
    spread = max(worst - best, 0.001)
    row_h = 40
    for index, match in enumerate(matches):
        row_y = y + 88 + index * row_h
        if row_y + row_h > y + h - 28:
            break
        color = _PALETTE[index % len(_PALETTE)]
        score = 1.0 - ((float(match.distance) - best) / spread)
        score = max(0.08, min(1.0, score))
        draw.text((x + 24, row_y + 4), f"{index + 1:02d}", fill=(*_MUTED, 255), font=fonts["mono"])
        label = _ellipsize(_display_name(match.population), fonts["small"], 300, draw)
        draw.text((x + 78, row_y + 3), label, fill=(*_TEXT, 255), font=fonts["small"])
        bar_x = x + 420
        bar_w = 230
        draw.rounded_rectangle((bar_x, row_y + 8, bar_x + bar_w, row_y + 22), radius=7, fill=(38, 48, 66, 210))
        draw.rounded_rectangle((bar_x, row_y + 8, bar_x + int(score * bar_w), row_y + 22), radius=7, fill=(*color, 230))
        draw.text((x + w - 112, row_y + 3), f"{match.distance:.4f}", fill=(*_MUTED, 255), font=fonts["mono"])


def _draw_oracle_side_panel(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, ImageFont.ImageFont],
    rect: tuple[int, int, int, int],
    *,
    reference_set: OracleReferenceSet,
    matches: Sequence[OracleMatch],
) -> None:
    _panel(draw, rect)
    x, y, w, h = rect
    best = matches[0] if matches else None
    second = matches[1] if len(matches) > 1 else None
    lead = (second.distance - best.distance) if best is not None and second is not None else 0.0
    draw.text((x + 22, y + 20), "Nearest", fill=(*_TEXT, 255), font=fonts["section"])
    draw.text((x + 22, y + 48), "reference population", fill=(*_MUTED, 255), font=fonts["tiny"])
    if best is not None:
        _metric_card(draw, fonts, (x + 22, y + 92, w - 44, 82), "Closest", best.population, _GOLD)
        _metric_card(draw, fonts, (x + 22, y + 190, w - 44, 82), "Distance", f"{best.distance:.4f}", _CYAN)
        _metric_card(draw, fonts, (x + 22, y + 288, w - 44, 82), "Lead over #2", f"{lead:.4f}", _GREEN)
    draw.text((x + 22, y + h - 78), f"References: {len(reference_set.populations)}", fill=(*_MUTED, 255), font=fonts["tiny"])
    draw.text((x + 22, y + h - 54), _ellipsize(reference_set.source.title, fonts["tiny"], w - 44, draw), fill=(*_FAINT, 255), font=fonts["tiny"])


def _draw_mix_panel(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, ImageFont.ImageFont],
    rect: tuple[int, int, int, int],
    *,
    mode_label: str,
    matches: Sequence[OracleMixMatch],
) -> None:
    _panel(draw, rect)
    x, y, w, h = rect
    draw.text((x + 22, y + 20), f"Best {mode_label} fits", fill=(*_TEXT, 255), font=fonts["section"])
    draw.text((x + 22, y + 48), "mathematical mixtures of reference populations", fill=(*_MUTED, 255), font=fonts["tiny"])
    row_h = 54
    for index, match in enumerate(matches):
        row_y = y + 88 + index * row_h
        if row_y + row_h > y + h - 28:
            break
        draw.text((x + 24, row_y + 12), f"{index + 1:02d}", fill=(*_MUTED, 255), font=fonts["mono"])
        bar_x = x + 78
        bar_y = row_y + 12
        bar_w = 330
        offset = 0
        for part_index, percent in enumerate(match.percents):
            segment_w = max(5, int((percent / 100.0) * bar_w))
            color = _PALETTE[part_index % len(_PALETTE)]
            draw.rounded_rectangle(
                (bar_x + offset, bar_y, bar_x + offset + segment_w, bar_y + 16),
                radius=7,
                fill=(*color, 225),
            )
            offset += segment_w
        mix_text = _ellipsize(_mix_inline(match), fonts["small"], 440, draw)
        draw.text((bar_x, row_y + 30), mix_text, fill=(*_TEXT, 255), font=fonts["small"])
        draw.text((x + w - 112, row_y + 20), f"{match.distance:.4f}", fill=(*_MUTED, 255), font=fonts["mono"])


def _draw_mix_side_panel(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, ImageFont.ImageFont],
    rect: tuple[int, int, int, int],
    *,
    reference_set: OracleReferenceSet,
    single_matches: Sequence[OracleMatch],
    mix_matches: Sequence[OracleMixMatch],
    mode_label: str,
) -> None:
    _panel(draw, rect)
    x, y, w, h = rect
    best_single = single_matches[0] if single_matches else None
    best_mix = mix_matches[0] if mix_matches else None
    improvement = 0.0
    if best_single is not None and best_mix is not None:
        improvement = best_single.distance - best_mix.distance
    draw.text((x + 22, y + 20), "Fit summary", fill=(*_TEXT, 255), font=fonts["section"])
    draw.text((x + 22, y + 48), "lower distance is closer", fill=(*_MUTED, 255), font=fonts["tiny"])
    if best_single is not None:
        _metric_card(draw, fonts, (x + 22, y + 92, w - 44, 82), "Best single", f"{best_single.population} {best_single.distance:.4f}", _GOLD)
    if best_mix is not None:
        _metric_card(draw, fonts, (x + 22, y + 190, w - 44, 104), f"Best {mode_label}", _mix_inline(best_mix), _CYAN)
        _metric_card(draw, fonts, (x + 22, y + 314, w - 44, 82), "Improvement", f"{improvement:.4f}", _GREEN)
    draw.text((x + 22, y + h - 78), f"References: {len(reference_set.populations)}", fill=(*_MUTED, 255), font=fonts["tiny"])
    draw.text((x + 22, y + h - 54), "A fit is descriptive, not literal ancestry.", fill=(*_FAINT, 255), font=fonts["tiny"])


def _metric_card(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, ImageFont.ImageFont],
    rect: tuple[int, int, int, int],
    label: str,
    value: str,
    accent: Color,
) -> None:
    x, y, w, h = rect
    draw.rounded_rectangle((x, y, x + w, y + h), radius=8, fill=(*_PANEL_SOFT, 220), outline=(54, 69, 90, 160), width=1)
    draw.rectangle((x, y, x + 4, y + h), fill=(*accent, 210))
    draw.text((x + 22, y + 14), label.upper(), fill=(*_MUTED, 255), font=fonts["label"])
    draw.text((x + 22, y + 42), _ellipsize(_display_name(value), fonts["small"], w - 46, draw), fill=(*_TEXT, 255), font=fonts["small"])


def _draw_footer(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, ImageFont.ImageFont],
    *,
    left: str,
    middle: str,
    right: str,
) -> None:
    y = 692
    draw.rounded_rectangle((40, y, _WIDTH - 40, 762), radius=8, fill=(26, 37, 54, 235), outline=(65, 82, 108, 190), width=1)
    draw.text((62, y + 18), _ellipsize(left, fonts["small"], 320, draw), fill=(*_TEXT, 255), font=fonts["small"])
    draw.text((424, y + 18), _ellipsize(middle, fonts["small"], 440, draw), fill=(*_MUTED, 255), font=fonts["small"])
    draw.text((886, y + 18), _ellipsize(right, fonts["small"], 330, draw), fill=(*_GOLD, 255), font=fonts["small"])
    draw.text((62, y + 44), "Admixture components are model-relative descriptors.", fill=(*_FAINT, 255), font=fonts["tiny"])


def _panel(draw: ImageDraw.ImageDraw, rect: tuple[int, int, int, int]) -> None:
    x, y, w, h = rect
    draw.rounded_rectangle((x, y, x + w, y + h), radius=8, fill=(*_PLOT, 235), outline=(64, 80, 104, 210), width=1)
    for index in range(1, 5):
        yy = y + int((h * index) / 5)
        draw.line((x + 12, yy, x + w - 12, yy), fill=(*_GRID, 70), width=1)


def _visible_components(payload: dict[str, object], threshold: float = 0.1) -> list[tuple[str, float]]:
    items = [
        item
        for item in _as_name_values(payload.get("components") or [])
        if item[1] >= threshold
    ]
    if not items:
        items = [item for item in _as_name_values(payload.get("components") or []) if item[1] > 0.0]
    if not items:
        items = _as_name_values(payload.get("top_components") or [])
    return sorted(items, key=lambda item: item[1], reverse=True)


def _macro_groups(payload: dict[str, object], limit: int) -> list[tuple[str, float]]:
    return _as_name_values(payload.get("macro_groups") or [])[:limit]


def _components(payload: dict[str, object]) -> list[tuple[str, float]]:
    return _as_name_values(payload.get("components") or [])


def _as_name_values(items: object) -> list[tuple[str, float]]:
    result: list[tuple[str, float]] = []
    if not isinstance(items, Iterable):
        return result
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        result.append((name, _float(item.get("value"))))
    return result


def _mix_inline(match: OracleMixMatch | None) -> str:
    if match is None:
        return "-"
    return " + ".join(
        f"{percent}% {_display_name(population)}"
        for percent, population in zip(match.percents, match.populations)
    )


def _display_name(value: str) -> str:
    return str(value).replace("_", " ").strip()


def _ellipsize(text: str, font: ImageFont.ImageFont, max_width: int, draw: ImageDraw.ImageDraw) -> str:
    if draw.textlength(text, font=font) <= max_width:
        return text
    suffix = "..."
    while text and draw.textlength(text + suffix, font=font) > max_width:
        text = text[:-1]
    return (text + suffix) if text else suffix


def _float(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _fonts() -> dict[str, ImageFont.ImageFont]:
    return {
        "title": _font(30, bold=True),
        "section": _font(20, bold=True),
        "label": _font(13, bold=True),
        "small": _font(16),
        "tiny": _font(12),
        "mono": _font(13),
    }


def _font(size: int, *, bold: bool = False) -> ImageFont.ImageFont:
    candidates = [
        Path("C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf"),
        Path("C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default()
