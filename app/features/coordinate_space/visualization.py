from __future__ import annotations

import math
from pathlib import Path
from typing import Callable, Mapping, Sequence, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from g25_core import g25_engine


Color = Tuple[int, int, int]
Point = Tuple[float, float]


_WIDTH = 1280
_HEIGHT = 800
_BG: Color = (13, 18, 27)
_PANEL: Color = (22, 30, 43)
_PANEL_SOFT: Color = (26, 37, 52)
_PLOT: Color = (16, 23, 34)
_GRID: Color = (54, 67, 86)
_TEXT: Color = (238, 244, 250)
_MUTED: Color = (154, 169, 190)
_FAINT: Color = (96, 112, 136)
_GOLD: Color = (255, 190, 92)
_GOLD_DARK: Color = (154, 102, 44)
_WHITE: Color = (250, 253, 255)
_PALETTE: tuple[Color, ...] = (
    (88, 166, 255),
    (111, 219, 169),
    (244, 148, 92),
    (190, 132, 255),
    (255, 215, 105),
    (104, 216, 224),
    (239, 112, 145),
    (162, 205, 102),
    (224, 154, 205),
    (132, 188, 255),
)


def render_coordinate_space_png(
    output_path: Path,
    *,
    title: str,
    g25_line: str,
    reference_profiles: Mapping[str, Sequence[float]],
    mode_label: str,
    summary_lines: Sequence[str] = (),
    group_map: Mapping[str, str] | None = None,
    label_formatter: Callable[[str], str] | None = None,
    top_n: int = 10,
) -> None:
    target = g25_engine.parse_g25_line(g25_line)
    target_name = _summary_value(summary_lines, "Sample") or target.name
    references = _clean_references(reference_profiles, dims=len(target.coords))
    if not references:
        _render_empty(output_path, title=title, target_name=target_name)
        return

    label_formatter = label_formatter or _default_label
    group_map = group_map or {}
    distances = {
        label: math.dist(target.coords, coords)
        for label, coords in references.items()
    }
    ranked_labels = sorted(references, key=lambda label: distances[label])
    ranked_labels = ranked_labels[:max(1, min(top_n, len(ranked_labels)))]
    projection = _project_points(references, target.coords)

    image = Image.new("RGB", (_WIDTH, _HEIGHT), _BG)
    draw = ImageDraw.Draw(image, "RGBA")
    fonts = _fonts()

    plot_rect = (40, 116, 840, 540)
    panel_rect = (912, 116, 328, 540)
    _draw_background(draw)
    _draw_header(draw, fonts, title=title, target_name=target_name, mode_label=mode_label)
    _draw_plot_panel(draw, plot_rect, projection=projection)
    _draw_groups(
        draw,
        plot_rect,
        references=references,
        projection=projection,
        group_map=group_map,
        ranked_labels=ranked_labels[:7],
        fonts=fonts,
        mode_label=mode_label,
    )
    _draw_points(
        draw,
        plot_rect,
        references=references,
        projection=projection,
        group_map=group_map,
        ranked_labels=ranked_labels,
        label_formatter=label_formatter,
        fonts=fonts,
        mode_label=mode_label,
    )
    _draw_nearest_panel(
        draw,
        panel_rect,
        distances=distances,
        ranked_labels=ranked_labels,
        group_map=group_map,
        label_formatter=label_formatter,
        fonts=fonts,
    )
    _draw_footer(
        draw,
        fonts,
        title=title,
        target_name=target_name,
        closest_label=label_formatter(ranked_labels[0]),
        closest_group=_closest_group_label(ranked_labels[0], group_map, mode_label=mode_label),
        closest_distance=distances[ranked_labels[0]],
        reference_count=len(references),
        explained=projection["explained"],
    )
    image.save(output_path)


def _clean_references(
    reference_profiles: Mapping[str, Sequence[float]],
    *,
    dims: int,
) -> dict[str, tuple[float, ...]]:
    cleaned: dict[str, tuple[float, ...]] = {}
    for label, coords in reference_profiles.items():
        values = tuple(float(value) for value in coords)
        if len(values) == dims:
            cleaned[str(label)] = values
    return cleaned


def _project_points(
    references: Mapping[str, Sequence[float]],
    target_coords: Sequence[float],
) -> dict[str, object]:
    labels = list(references)
    ref_matrix = np.array([references[label] for label in labels], dtype=float)
    target = np.array(target_coords, dtype=float)
    mean = ref_matrix.mean(axis=0)
    centered = ref_matrix - mean

    if len(labels) >= 2 and centered.shape[1] >= 2:
        try:
            _, singular_values, vt = np.linalg.svd(centered, full_matrices=False)
            components = vt[:2].T
            ref_projected = centered @ components
            target_projected = (target - mean) @ components
            explained = _explained_variance(singular_values)
        except np.linalg.LinAlgError:
            ref_projected, target_projected, explained = _fallback_projection(ref_matrix, target)
    else:
        ref_projected, target_projected, explained = _fallback_projection(ref_matrix, target)

    ref_projected, target_projected = _orient_projection(ref_matrix, ref_projected, target_projected)
    points = {label: (float(ref_projected[index, 0]), float(ref_projected[index, 1])) for index, label in enumerate(labels)}
    points["__target__"] = (float(target_projected[0]), float(target_projected[1]))
    bounds = _projection_bounds(tuple(points.values()))
    return {"points": points, "bounds": bounds, "explained": explained}


def _explained_variance(singular_values: np.ndarray) -> tuple[float, float]:
    if singular_values.size == 0:
        return (0.0, 0.0)
    variances = singular_values ** 2
    total = float(variances.sum())
    if total <= 0:
        return (0.0, 0.0)
    first = float(variances[0] / total) if variances.size > 0 else 0.0
    second = float(variances[1] / total) if variances.size > 1 else 0.0
    return (first, second)


def _fallback_projection(ref_matrix: np.ndarray, target: np.ndarray) -> tuple[np.ndarray, np.ndarray, tuple[float, float]]:
    x_index = 0
    y_index = 1 if ref_matrix.shape[1] > 1 else 0
    ref_projected = np.column_stack((ref_matrix[:, x_index], ref_matrix[:, y_index]))
    target_projected = np.array((target[x_index], target[y_index]), dtype=float)
    return ref_projected, target_projected, (0.0, 0.0)


def _orient_projection(
    ref_matrix: np.ndarray,
    ref_projected: np.ndarray,
    target_projected: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    oriented_refs = ref_projected.copy()
    oriented_target = target_projected.copy()
    for axis, source_axis in enumerate((0, 1)):
        if ref_matrix.shape[1] <= source_axis:
            continue
        source = ref_matrix[:, source_axis]
        projected = oriented_refs[:, axis]
        if float(np.std(source)) == 0.0 or float(np.std(projected)) == 0.0:
            continue
        correlation = float(np.corrcoef(source, projected)[0, 1])
        if correlation < 0:
            oriented_refs[:, axis] *= -1
            oriented_target[axis] *= -1
    return oriented_refs, oriented_target


def _projection_bounds(points: Sequence[Point]) -> tuple[float, float, float, float]:
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    if math.isclose(min_x, max_x):
        min_x -= 0.01
        max_x += 0.01
    if math.isclose(min_y, max_y):
        min_y -= 0.01
        max_y += 0.01
    pad_x = (max_x - min_x) * 0.12
    pad_y = (max_y - min_y) * 0.12
    return (min_x - pad_x, min_y - pad_y, max_x + pad_x, max_y + pad_y)


def _draw_background(draw: ImageDraw.ImageDraw) -> None:
    for y in range(_HEIGHT):
        tint = int(16 + 20 * (y / _HEIGHT))
        draw.line((0, y, _WIDTH, y), fill=(11, tint, 28 + tint // 4, 255))
    draw.rounded_rectangle((24, 24, _WIDTH - 24, _HEIGHT - 24), radius=8, outline=(53, 68, 89, 220), width=1)


def _draw_header(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, ImageFont.ImageFont],
    *,
    title: str,
    target_name: str,
    mode_label: str,
) -> None:
    draw.text((42, 34), "COORDINATE SPACE", fill=(*_MUTED, 255), font=fonts["label"])
    draw.text((42, 56), title.upper(), fill=(*_TEXT, 255), font=fonts["title"])
    pill = f"{mode_label.upper()} VIEW"
    right_edge = _WIDTH - 72
    pill_width = int(draw.textlength(pill, font=fonts["label"])) + 28
    pill_box = (right_edge - pill_width, 44, right_edge, 70)
    draw.rounded_rectangle(pill_box, radius=8, fill=(31, 44, 62, 235), outline=(70, 88, 111, 220), width=1)
    draw.text((pill_box[0] + 14, pill_box[1] + 8), pill, fill=(*_MUTED, 255), font=fonts["label"])
    target = _ellipsize(target_name, fonts["small"], 260, draw)
    target_label = "TARGET"
    label_width = int(draw.textlength(target_label, font=fonts["label"]))
    target_width = int(draw.textlength(target, font=fonts["small"]))
    target_x = right_edge - label_width - 10 - target_width
    draw.text((target_x, 84), target_label, fill=(*_MUTED, 255), font=fonts["label"])
    draw.text((target_x + label_width + 10, 82), target, fill=(*_TEXT, 255), font=fonts["small"])


def _draw_plot_panel(
    draw: ImageDraw.ImageDraw,
    plot_rect: tuple[int, int, int, int],
    *,
    projection: Mapping[str, object],
) -> None:
    x, y, w, h = plot_rect
    draw.rounded_rectangle((x, y, x + w, y + h), radius=8, fill=(*_PLOT, 250), outline=(63, 80, 103, 230), width=1)
    for index in range(1, 6):
        gx = x + int(w * index / 6)
        gy = y + int(h * index / 6)
        draw.line((gx, y + 12, gx, y + h - 12), fill=(*_GRID, 80), width=1)
        draw.line((x + 12, gy, x + w - 12, gy), fill=(*_GRID, 80), width=1)
    explained = projection["explained"]
    if isinstance(explained, tuple):
        note = f"LOCAL PCA  PC1 {explained[0] * 100:.0f}%  PC2 {explained[1] * 100:.0f}%"
    else:
        note = "LOCAL PCA"
    draw.text((x + 18, y + 16), note, fill=(*_FAINT, 255), font=_fonts()["tiny"])


def _draw_groups(
    draw: ImageDraw.ImageDraw,
    plot_rect: tuple[int, int, int, int],
    *,
    references: Mapping[str, Sequence[float]],
    projection: Mapping[str, object],
    group_map: Mapping[str, str],
    ranked_labels: Sequence[str],
    fonts: dict[str, ImageFont.ImageFont],
    mode_label: str,
) -> None:
    grouped: dict[str, list[tuple[int, int]]] = {}
    for label in references:
        group = group_map.get(label, label)
        grouped.setdefault(group, []).append(_screen_point(projection, plot_rect, label))

    for index, (group, points) in enumerate(grouped.items()):
        color = _group_color(group, index)
        if len(points) < 2:
            continue
        xs = np.array([point[0] for point in points], dtype=float)
        ys = np.array([point[1] for point in points], dtype=float)
        cx = float(xs.mean())
        cy = float(ys.mean())
        x_low, x_high = np.percentile(xs, [14, 86])
        y_low, y_high = np.percentile(ys, [14, 86])
        sx = min(150.0, max(42.0, float(x_high - x_low) * 0.58 + 22.0))
        sy = min(96.0, max(30.0, float(y_high - y_low) * 0.58 + 20.0))
        px, py, pw, ph = plot_rect
        box = (
            max(px + 14, int(round(cx - sx))),
            max(py + 14, int(round(cy - sy))),
            min(px + pw - 14, int(round(cx + sx))),
            min(py + ph - 14, int(round(cy + sy))),
        )
        draw.ellipse(box, fill=(*color, 8), outline=(*color, 34), width=1)

    if mode_label.lower() == "population":
        _draw_population_group_labels(
            draw,
            plot_rect,
            grouped=grouped,
            target_point=_screen_point(projection, plot_rect, "__target__"),
            protected_points=[_screen_point(projection, plot_rect, label) for label in ranked_labels if label in references],
            fonts=fonts,
        )


def _draw_population_group_labels(
    draw: ImageDraw.ImageDraw,
    plot_rect: tuple[int, int, int, int],
    *,
    grouped: Mapping[str, Sequence[tuple[int, int]]],
    target_point: tuple[int, int],
    protected_points: Sequence[tuple[int, int]],
    fonts: dict[str, ImageFont.ImageFont],
) -> None:
    used_boxes: list[tuple[int, int, int, int]] = [
        (target_point[0] - 132, target_point[1] - 68, target_point[0] + 132, target_point[1] + 68)
    ]
    for point in protected_points:
        used_boxes.append((point[0] - 96, point[1] - 30, point[0] + 96, point[1] + 30))
    ordered_groups = sorted(
        grouped.items(),
        key=lambda item: len(item[1]),
        reverse=True,
    )
    for index, (group, points) in enumerate(ordered_groups):
        if len(points) < 3:
            continue
        color = _group_color(group, index)
        xs = np.array([point[0] for point in points], dtype=float)
        ys = np.array([point[1] for point in points], dtype=float)
        center = (int(round(float(np.median(xs)))), int(round(float(np.median(ys)))))
        label = _faint_group_label(group)
        font = fonts["small"]
        box = _text_box(draw, (center[0], center[1]), label, font, pad_x=4, pad_y=2)
        box = (
            center[0] - (box[2] - box[0]) // 2,
            center[1] - (box[3] - box[1]) // 2,
            center[0] + (box[2] - box[0] + 1) // 2,
            center[1] + (box[3] - box[1] + 1) // 2,
        )
        box = _place_group_label_box(box, plot_rect, used_boxes)
        if box is None:
            continue
        draw.text((box[0] + 4, box[1] + 2), label.upper(), fill=(*color, 42), font=font)
        used_boxes.append(box)


def _faint_group_label(group: str) -> str:
    label = group.replace(" / ", " / ").replace("_", " ")
    replacements = {
        "Mesopotamia / Iran": "Meso / Iran",
        "Northwest South Asia": "NW South Asia",
        "Gangetic / North India": "Gangetic",
        "East India / Bengal": "E. India / Bengal",
        "Siberia / Inner Asia": "Siberia / Inner Asia",
        "Northeast Asia": "NE Asia",
    }
    return replacements.get(label, label)


def _place_group_label_box(
    box: tuple[int, int, int, int],
    plot_rect: tuple[int, int, int, int],
    used_boxes: Sequence[tuple[int, int, int, int]],
) -> tuple[int, int, int, int] | None:
    offsets = ((0, 0), (0, -48), (0, 48), (72, 0), (-72, 0), (72, -42), (-72, 42), (116, -56), (-116, 56))
    for dx, dy in offsets:
        candidate = (box[0] + dx, box[1] + dy, box[2] + dx, box[3] + dy)
        candidate = _clamp_box(candidate, plot_rect)
        if any(_intersects(candidate, used) for used in used_boxes):
            continue
        return candidate
    return None


def _draw_points(
    draw: ImageDraw.ImageDraw,
    plot_rect: tuple[int, int, int, int],
    *,
    references: Mapping[str, Sequence[float]],
    projection: Mapping[str, object],
    group_map: Mapping[str, str],
    ranked_labels: Sequence[str],
    label_formatter: Callable[[str], str],
    fonts: dict[str, ImageFont.ImageFont],
    mode_label: str,
) -> None:
    top_set = set(ranked_labels[: min(7, len(ranked_labels))])
    labels_to_show = set(references) if len(references) <= 12 else top_set
    groups = _ordered_groups(references, group_map)
    target_point = _screen_point(projection, plot_rect, "__target__")

    for label in ranked_labels[:3]:
        ref_point = _screen_point(projection, plot_rect, label)
        draw.line((*target_point, *ref_point), fill=(255, 190, 92, 105), width=2)

    for label in references:
        group = group_map.get(label, label)
        color = _group_color(group, groups.index(group) if group in groups else 0)
        x, y = _screen_point(projection, plot_rect, label)
        radius = 4 if label not in top_set else 6
        fill_alpha = 180 if label not in top_set else 255
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=(*color, fill_alpha), outline=(247, 252, 255, 180), width=1)

    used_boxes: list[tuple[int, int, int, int]] = [
        (target_point[0] - 42, target_point[1] - 42, target_point[0] + 42, target_point[1] + 42)
    ]
    for label in [item for item in ranked_labels if item in labels_to_show]:
        point = _screen_point(projection, plot_rect, label)
        group = group_map.get(label, label)
        color = _group_color(group, groups.index(group) if group in groups else 0)
        display = _ellipsize(label_formatter(label), fonts["small"], 190, draw)
        _draw_label(draw, point, display, fonts["small"], color=color, used_boxes=used_boxes, plot_rect=plot_rect)

    _draw_sample_marker(draw, target_point)
    _draw_label(draw, target_point, "SAMPLE", fonts["label"], color=_GOLD, used_boxes=used_boxes, plot_rect=plot_rect, force_above=True)

    legend_x = plot_rect[0] + 18
    legend_y = plot_rect[1] + plot_rect[3] - 34
    draw.text((legend_x, legend_y), "RANKING: FULL 25D G25 DISTANCE", fill=(*_FAINT, 255), font=fonts["tiny"])
    reference_note = "COLORS: REGIONAL GROUPS" if mode_label.lower() == "population" else "DOTS: REGION REFERENCES"
    draw.text((legend_x + 246, legend_y), reference_note, fill=(*_FAINT, 255), font=fonts["tiny"])


def _draw_nearest_panel(
    draw: ImageDraw.ImageDraw,
    panel_rect: tuple[int, int, int, int],
    *,
    distances: Mapping[str, float],
    ranked_labels: Sequence[str],
    group_map: Mapping[str, str],
    label_formatter: Callable[[str], str],
    fonts: dict[str, ImageFont.ImageFont],
) -> None:
    x, y, w, h = panel_rect
    draw.rounded_rectangle((x, y, x + w, y + h), radius=8, fill=(*_PANEL, 248), outline=(63, 80, 103, 235), width=1)
    draw.text((x + 22, y + 20), "NEAREST REFERENCES", fill=(*_TEXT, 255), font=fonts["section"])
    draw.text((x + 22, y + 48), "full 25D Euclidean distance", fill=(*_MUTED, 255), font=fonts["tiny"])

    best = distances[ranked_labels[0]]
    worst = distances[ranked_labels[-1]]
    spread = max(1e-9, worst - best)
    groups = _ordered_groups({label: () for label in distances}, group_map)
    row_y = y + 82
    for index, label in enumerate(ranked_labels, start=1):
        distance = distances[label]
        group = group_map.get(label, label)
        color = _group_color(group, groups.index(group) if group in groups else index)
        row_h = 34
        row_box = (x + 18, row_y, x + w - 18, row_y + row_h)
        row_fill = (31, 42, 58, 245) if index == 1 else (25, 34, 48, 220)
        draw.rounded_rectangle(row_box, radius=7, fill=row_fill)
        score = 1.0 - ((distance - best) / spread)
        bar_w = max(8, int((w - 152) * max(0.08, score)))
        draw.rounded_rectangle((x + 74, row_y + row_h - 8, x + 74 + bar_w, row_y + row_h - 4), radius=2, fill=(*color, 210))
        draw.text((x + 30, row_y + 8), f"{index:02d}", fill=(*_MUTED, 255), font=fonts["mono"])
        label_text = _ellipsize(label_formatter(label), fonts["small"], 150, draw)
        draw.text((x + 74, row_y + 6), label_text, fill=(*_TEXT, 255), font=fonts["small"])
        draw.text((x + w - 94, row_y + 6), f"{distance:.5f}", fill=(*_MUTED, 255), font=fonts["mono"])
        row_y += row_h + 7

    if len(ranked_labels) > 1:
        lead = distances[ranked_labels[1]] - best
        lead_text = f"Lead over #2: {lead:.5f}"
        draw.text((x + 22, y + h - 42), lead_text, fill=(*_GOLD, 255), font=fonts["small"])


def _draw_footer(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, ImageFont.ImageFont],
    *,
    title: str,
    target_name: str,
    closest_label: str,
    closest_group: str,
    closest_distance: float,
    reference_count: int,
    explained: object,
) -> None:
    y = 692
    draw.rounded_rectangle((40, y, 1240, 760), radius=8, fill=(*_PANEL_SOFT, 236), outline=(60, 78, 100, 180), width=1)
    target = _ellipsize(target_name, fonts["small"], 260, draw)
    closest = _ellipsize(closest_label, fonts["small"], 250, draw)
    draw.text((62, y + 18), f"Target: {target}", fill=(*_TEXT, 255), font=fonts["small"])
    draw.text((342, y + 18), f"Closest: {closest}", fill=(*_TEXT, 255), font=fonts["small"])
    distance_x = 742
    if closest_group:
        region = _ellipsize(closest_group, fonts["small"], 190, draw)
        draw.text((612, y + 18), f"Region: {region}", fill=(*_TEXT, 255), font=fonts["small"])
        distance_x = 846
    draw.text((distance_x, y + 18), f"Distance: {closest_distance:.5f}", fill=(*_GOLD, 255), font=fonts["small"])
    if isinstance(explained, tuple):
        pca_text = f"Local PCA: PC1 {explained[0] * 100:.0f}% / PC2 {explained[1] * 100:.0f}%"
    else:
        pca_text = "Local PCA"
    draw.text((62, y + 43), f"{title} refs: {reference_count}     {pca_text}     Ranking uses all 25 G25 coordinates.", fill=(*_MUTED, 255), font=fonts["tiny"])


def _closest_group_label(
    closest_label: str,
    group_map: Mapping[str, str],
    *,
    mode_label: str,
) -> str:
    if mode_label.lower() != "population":
        return ""
    group = group_map.get(closest_label, "").strip()
    if not group or group == closest_label:
        return ""
    return _faint_group_label(group)


def _draw_sample_marker(draw: ImageDraw.ImageDraw, point: tuple[int, int]) -> None:
    x, y = point
    draw.ellipse((x - 25, y - 25, x + 25, y + 25), fill=(*_GOLD_DARK, 72))
    draw.ellipse((x - 14, y - 14, x + 14, y + 14), fill=(*_GOLD, 245), outline=(*_WHITE, 245), width=2)
    draw.polygon(((x, y - 8), (x + 8, y), (x, y + 8), (x - 8, y)), fill=(47, 55, 69, 255), outline=(*_WHITE, 210))


def _draw_label(
    draw: ImageDraw.ImageDraw,
    point: tuple[int, int],
    text: str,
    font: ImageFont.ImageFont,
    *,
    color: Color,
    used_boxes: list[tuple[int, int, int, int]],
    plot_rect: tuple[int, int, int, int],
    force_above: bool = False,
) -> None:
    offsets = ((16, -34), (16, 14), (-16, -34), (-16, 14), (0, -52), (0, 30), (34, -10), (-34, -10))
    if force_above:
        offsets = ((-22, -44),)
    for dx, dy in offsets:
        box = _text_box(draw, (point[0] + dx, point[1] + dy), text, font, pad_x=7, pad_y=4)
        if dx < 0:
            box = (point[0] + dx - (box[2] - box[0]), box[1], point[0] + dx, box[3])
        box = _clamp_box(box, plot_rect)
        if force_above or not any(_intersects(box, used) for used in used_boxes):
            draw.rounded_rectangle(box, radius=5, fill=(13, 18, 27, 218), outline=(*color, 150), width=1)
            draw.text((box[0] + 7, box[1] + 4), text, fill=(*_TEXT, 255), font=font)
            used_boxes.append(box)
            return


def _screen_point(
    projection: Mapping[str, object],
    plot_rect: tuple[int, int, int, int],
    label: str,
) -> tuple[int, int]:
    points = projection["points"]
    bounds = projection["bounds"]
    if not isinstance(points, dict) or not isinstance(bounds, tuple):
        return (plot_rect[0] + plot_rect[2] // 2, plot_rect[1] + plot_rect[3] // 2)
    min_x, min_y, max_x, max_y = bounds
    x, y = points[label]
    px, py, pw, ph = plot_rect
    inner = 44
    sx = px + inner + ((x - min_x) / (max_x - min_x)) * (pw - inner * 2)
    sy = py + inner + (1.0 - ((y - min_y) / (max_y - min_y))) * (ph - inner * 2)
    return (int(round(sx)), int(round(sy)))


def _ordered_groups(references: Mapping[str, object], group_map: Mapping[str, str]) -> list[str]:
    groups: list[str] = []
    for label in references:
        group = group_map.get(label, label)
        if group not in groups:
            groups.append(group)
    return groups


def _group_color(group: str, fallback_index: int) -> Color:
    if not group:
        return _PALETTE[fallback_index % len(_PALETTE)]
    index = sum((position + 1) * ord(char) for position, char in enumerate(group)) % len(_PALETTE)
    return _PALETTE[index]


def _convex_hull(points: Sequence[tuple[int, int]]) -> list[tuple[int, int]]:
    unique = sorted(set(points))
    if len(unique) <= 1:
        return list(unique)

    def cross(origin: tuple[int, int], left: tuple[int, int], right: tuple[int, int]) -> int:
        return (left[0] - origin[0]) * (right[1] - origin[1]) - (left[1] - origin[1]) * (right[0] - origin[0])

    lower: list[tuple[int, int]] = []
    for point in unique:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], point) <= 0:
            lower.pop()
        lower.append(point)
    upper: list[tuple[int, int]] = []
    for point in reversed(unique):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], point) <= 0:
            upper.pop()
        upper.append(point)
    hull = lower[:-1] + upper[:-1]
    if len(hull) < 3:
        return list(unique)
    cx = sum(point[0] for point in hull) / len(hull)
    cy = sum(point[1] for point in hull) / len(hull)
    return [
        (int(round(cx + (point[0] - cx) * 1.08)), int(round(cy + (point[1] - cy) * 1.08)))
        for point in hull
    ]


def _summary_value(summary_lines: Sequence[str], key: str) -> str:
    wanted = key.strip().lower()
    for line in summary_lines:
        if ":" not in line:
            continue
        raw_key, value = line.split(":", 1)
        if raw_key.strip().lower() == wanted:
            return value.strip()
    return ""


def _text_box(
    draw: ImageDraw.ImageDraw,
    origin: tuple[int, int],
    text: str,
    font: ImageFont.ImageFont,
    *,
    pad_x: int,
    pad_y: int,
) -> tuple[int, int, int, int]:
    x, y = origin
    bbox = draw.textbbox((x, y), text, font=font)
    return (x, y, x + (bbox[2] - bbox[0]) + pad_x * 2, y + (bbox[3] - bbox[1]) + pad_y * 2)


def _clamp_box(
    box: tuple[int, int, int, int],
    plot_rect: tuple[int, int, int, int],
) -> tuple[int, int, int, int]:
    px, py, pw, ph = plot_rect
    min_x, min_y, max_x, max_y = px + 8, py + 8, px + pw - 8, py + ph - 8
    width = box[2] - box[0]
    height = box[3] - box[1]
    x = max(min_x, min(max_x - width, box[0]))
    y = max(min_y, min(max_y - height, box[1]))
    return (x, y, x + width, y + height)


def _intersects(left: tuple[int, int, int, int], right: tuple[int, int, int, int]) -> bool:
    return not (left[2] < right[0] or right[2] < left[0] or left[3] < right[1] or right[3] < left[1])


def _ellipsize(text: str, font: ImageFont.ImageFont, max_width: int, draw: ImageDraw.ImageDraw) -> str:
    if draw.textlength(text, font=font) <= max_width:
        return text
    suffix = "..."
    while text and draw.textlength(text + suffix, font=font) > max_width:
        text = text[:-1]
    return (text.rstrip() + suffix) if text else suffix


def _default_label(label: str) -> str:
    return label.replace("_", " ")


def _fonts() -> dict[str, ImageFont.ImageFont]:
    return {
        "title": _font(30, bold=True),
        "section": _font(18, bold=True),
        "label": _font(13, bold=True),
        "small": _font(15),
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


def _render_empty(output_path: Path, *, title: str, target_name: str) -> None:
    image = Image.new("RGB", (_WIDTH, _HEIGHT), _BG)
    draw = ImageDraw.Draw(image)
    fonts = _fonts()
    draw.text((42, 56), title.upper(), fill=_TEXT, font=fonts["title"])
    draw.text((42, 112), f"Target: {target_name}", fill=_MUTED, font=fonts["small"])
    draw.text((42, 148), "No compatible G25 references were found for this view.", fill=_TEXT, font=fonts["section"])
    image.save(output_path)
