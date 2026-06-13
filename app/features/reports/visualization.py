from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageDraw, ImageFont

from app.features.reports.g25_platform import G25PlatformReport
from g25_core.render_fit_png import render_distance_png
from g25_core.render_fit_svg import display_name


@dataclass(frozen=True)
class G25ReportVisuals:
    overview_path: Path
    distance_modern_path: Path | None = None
    distance_ancient_path: Path | None = None

    @property
    def paths(self) -> tuple[Path, ...]:
        return tuple(path for path in (self.overview_path, self.distance_modern_path, self.distance_ancient_path) if path is not None)


def build_g25_report_visuals(report: G25PlatformReport) -> G25ReportVisuals:
    analysis = json.loads(report.analysis_path.read_text(encoding="utf-8"))

    overview_path = report.output_dir / "g25_overview.png"
    render_g25_overview_png(
        analysis,
        output_path=overview_path,
        sample_name=report.sample_name,
        coordinate_name=report.coordinate_name,
    )

    modern_path = _render_distance_card(
        analysis,
        report.output_dir,
        artifact_key="distance_modern",
        dataset_label="modern",
        output_name="g25_distance_modern.png",
    )
    ancient_path = _render_distance_card(
        analysis,
        report.output_dir,
        artifact_key="distance_ancient",
        dataset_label="ancient",
        output_name="g25_distance_ancient.png",
    )
    return G25ReportVisuals(
        overview_path=overview_path,
        distance_modern_path=modern_path,
        distance_ancient_path=ancient_path,
    )


def render_g25_overview_png(
    analysis: dict[str, object],
    *,
    output_path: Path,
    sample_name: str,
    coordinate_name: str,
) -> None:
    width = 1280
    height = 1580
    image = Image.new("RGB", (width, height), (10, 15, 23))
    draw = ImageDraw.Draw(image, "RGBA")
    _paint_background(draw, width, height)

    fonts = {
        "brand": _font(24, bold=True),
        "title": _font(54, bold=True),
        "subtitle": _font(28),
        "section": _font(32, bold=True),
        "label": _font(22, bold=True),
        "body": _font(29),
        "body_bold": _font(29, bold=True),
        "small": _font(21),
        "small_bold": _font(21, bold=True),
        "metric": _font(27, bold=True),
    }

    margin = 58
    _rounded_panel(draw, (34, 34, width - 34, height - 34), radius=34, fill=(17, 24, 36), outline=(63, 77, 101))

    sample_display = _clean(sample_name or _str(analysis.get("sample_name")) or "Sample")
    coordinate_display = _clean(coordinate_name or "G25")
    draw.text((margin, 62), "KBDNA · MY DNA REPORTS", fill=(142, 173, 214), font=fonts["brand"])
    draw.text((margin, 100), "Complex G25 Overview", fill=(248, 250, 252), font=fonts["title"])
    draw.text((margin, 170), f"{sample_display} · {coordinate_display}", fill=(202, 210, 222), font=fonts["subtitle"])

    routing = _dict(analysis.get("routing"))
    global_routing = _dict(routing.get("global"))
    decision = _dict(routing.get("decision"))
    branch = _str(routing.get("selected_backbone_branch"))
    regional = _dict(_dict(routing.get("regional_backbone")).get(branch))

    modern_macro = _dict(global_routing.get("modern_macro"))
    ancient_macro = _dict(global_routing.get("ancient_macro"))
    region_label = _selected_region_label(decision)
    nearest_modern = _nearest_label(modern_macro)

    y = 250
    _draw_metric_grid(
        draw,
        fonts,
        x=margin,
        y=y,
        width=width - margin * 2,
        items=[
            ("Modern macro", _str(modern_macro.get("predicted_group"))),
            ("Ancient macro", _str(ancient_macro.get("predicted_group"))),
            ("Region", region_label),
            ("Nearest modern", nearest_modern),
        ],
    )

    y = 535
    _section_header(draw, fonts, margin, y, "Backbone Signals")
    y += 58
    _draw_signal_rows(
        draw,
        fonts,
        x=margin,
        y=y,
        width=width - margin * 2,
        rows=[
            ("Modern cluster", _dict(regional.get("modern_cluster"))),
            ("Ancient family", _dict(regional.get("ancient_family"))),
            ("Ancient core", _dict(regional.get("ancient_core"))),
        ],
    )

    y = 845
    _section_header(draw, fonts, margin, y, "Reduced Model Snapshot")
    y += 64
    reduced = _dict(_dict(routing.get("regional_reduced_models")).get(branch))
    modern_model = _dict(_dict(reduced.get("modern")).get("reduced_fit"))
    ancient_model = _dict(_dict(reduced.get("ancient")).get("reduced_fit"))
    y = _draw_model_block(draw, fonts, margin, y, width - margin * 2, "Modern model", modern_model, accent=(91, 169, 255))
    y += 28
    y = _draw_model_block(draw, fonts, margin, y, width - margin * 2, "Ancient model", ancient_model, accent=(245, 166, 75))

    footer_y = height - 112
    draw.line((margin, footer_y - 26, width - margin, footer_y - 26), fill=(55, 67, 89, 220), width=2)
    draw.text((margin, footer_y), "Prototype visual · generated from dna_platform backbone analysis", fill=(143, 153, 171), font=fonts["small"])
    draw.text((margin, footer_y + 34), "Technical JSON and SVG artifacts are kept on the server.", fill=(103, 116, 138), font=fonts["small"])

    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, format="PNG")


def _render_distance_card(
    analysis: dict[str, object],
    output_dir: Path,
    *,
    artifact_key: str,
    dataset_label: str,
    output_name: str,
) -> Path | None:
    source_path = _artifact_path(analysis, output_dir, artifact_key)
    if source_path is None or not source_path.exists():
        return None
    data = json.loads(source_path.read_text(encoding="utf-8"))
    matches = [
        (float(_dict(item).get("distance")), _str(_dict(item).get("reference")))
        for item in _list(data.get("results"))
        if _str(_dict(item).get("reference"))
    ]
    if not matches:
        return None
    output_path = output_dir / output_name
    render_distance_png(dataset_label, _str(data.get("sample_name")) or _str(analysis.get("sample_name")) or "Sample", matches[:12], output_path)
    return output_path


def _artifact_path(analysis: dict[str, object], output_dir: Path, key: str) -> Path | None:
    raw_value = _str(_dict(analysis.get("artifacts")).get(key))
    if not raw_value:
        return None
    path = Path(raw_value)
    if not path.is_absolute():
        path = output_dir / path
    return path


def _paint_background(draw: ImageDraw.ImageDraw, width: int, height: int) -> None:
    for y in range(height):
        t = y / max(1, height - 1)
        r = int(10 + 9 * t)
        g = int(15 + 18 * t)
        b = int(23 + 22 * t)
        draw.line((0, y, width, y), fill=(r, g, b))
    draw.rectangle((0, 0, width, 310), fill=(16, 27, 43, 130))


def _rounded_panel(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    *,
    radius: int,
    fill: tuple[int, int, int],
    outline: tuple[int, int, int],
) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=(*fill, 238), outline=(*outline, 210), width=2)


def _draw_metric_grid(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, ImageFont.ImageFont],
    *,
    x: int,
    y: int,
    width: int,
    items: list[tuple[str, str]],
) -> None:
    gap = 18
    card_w = (width - gap) // 2
    card_h = 116
    for index, (label, value) in enumerate(items):
        col = index % 2
        row = index // 2
        left = x + col * (card_w + gap)
        top = y + row * (card_h + gap)
        _rounded_panel(draw, (left, top, left + card_w, top + card_h), radius=20, fill=(26, 37, 54), outline=(60, 78, 106))
        draw.text((left + 24, top + 20), label.upper(), fill=(143, 167, 200), font=fonts["label"])
        draw.text((left + 24, top + 55), _ellipsize(draw, _pretty(value), fonts["metric"], card_w - 48), fill=(248, 250, 252), font=fonts["metric"])


def _draw_signal_rows(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, ImageFont.ImageFont],
    *,
    x: int,
    y: int,
    width: int,
    rows: Iterable[tuple[str, dict[str, object]]],
) -> None:
    row_h = 78
    for index, (label, payload) in enumerate(rows):
        top = y + index * (row_h + 12)
        predicted = _pretty(_str(payload.get("predicted_group")))
        nearest = _nearest_label(payload)
        _rounded_panel(draw, (x, top, x + width, top + row_h), radius=18, fill=(22, 32, 48), outline=(53, 67, 90))
        draw.text((x + 24, top + 17), label, fill=(170, 189, 214), font=fonts["body"])
        draw.text((x + 300, top + 17), _ellipsize(draw, predicted, fonts["body_bold"], 380), fill=(248, 250, 252), font=fonts["body_bold"])
        draw.text((x + 710, top + 21), _ellipsize(draw, nearest, fonts["small"], width - 735), fill=(194, 202, 216), font=fonts["small"])


def _draw_model_block(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, ImageFont.ImageFont],
    x: int,
    y: int,
    width: int,
    title: str,
    fit: dict[str, object],
    *,
    accent: tuple[int, int, int],
) -> int:
    groups = _sorted_groups(_dict(fit.get("groups")))
    distance = _format_distance(fit.get("distance"))
    sources = _str(fit.get("sources"))
    block_h = 210 if groups else 116
    _rounded_panel(draw, (x, y, x + width, y + block_h), radius=22, fill=(20, 30, 45), outline=(52, 67, 91))
    draw.text((x + 24, y + 22), title, fill=(248, 250, 252), font=fonts["section"])
    meta = " · ".join(part for part in (f"distance {distance}" if distance else "", f"{sources} sources" if sources else "") if part)
    draw.text((x + 24, y + 62), meta or "model details unavailable", fill=(152, 166, 188), font=fonts["small"])
    if not groups:
        return y + block_h

    bar_x = x + 24
    bar_y = y + 106
    bar_w = width - 48
    bar_h = 24
    cursor = bar_x
    palette = (accent, (128, 214, 172), (220, 204, 91), (176, 139, 235), (237, 112, 112))
    for index, (_, value) in enumerate(groups[:5]):
        segment_w = int(round(bar_w * max(0.0, min(1.0, value))))
        if segment_w <= 0:
            continue
        draw.rounded_rectangle((cursor, bar_y, cursor + segment_w, bar_y + bar_h), radius=8, fill=(*palette[index % len(palette)], 255))
        cursor += segment_w
    if cursor < bar_x + bar_w:
        draw.rounded_rectangle((cursor, bar_y, bar_x + bar_w, bar_y + bar_h), radius=8, fill=(44, 55, 74, 255))

    label_y = y + 148
    col_w = width // 3
    for index, (name, value) in enumerate(groups[:6]):
        col = index % 3
        row = index // 3
        left = x + 24 + col * col_w
        top = label_y + row * 30
        color = palette[index % len(palette)]
        draw.rounded_rectangle((left, top + 6, left + 14, top + 20), radius=4, fill=(*color, 255))
        label = f"{_pretty(name)} {value * 100:.1f}%"
        draw.text((left + 24, top), _ellipsize(draw, label, fonts["small_bold"], col_w - 36), fill=(220, 226, 236), font=fonts["small_bold"])
    return y + block_h


def _section_header(draw: ImageDraw.ImageDraw, fonts: dict[str, ImageFont.ImageFont], x: int, y: int, title: str) -> None:
    draw.text((x, y), title, fill=(248, 250, 252), font=fonts["section"])
    draw.line((x, y + 45, x + 1164, y + 45), fill=(55, 67, 89, 230), width=2)


def _selected_region_label(decision: dict[str, object]) -> str:
    selected = _list(decision.get("selected_regions"))
    if selected:
        region = _dict(selected[0])
        return _str(region.get("label")) or _pretty(_str(region.get("region_id")))
    return _pretty(_str(decision.get("primary_macroregion")))


def _nearest_label(payload: dict[str, object]) -> str:
    nearest = _list(payload.get("nearest"))
    if not nearest:
        return "No nearest match"
    top = _dict(nearest[0])
    reference = _pretty(_str(top.get("reference")))
    distance = _format_distance(top.get("distance"))
    return f"{reference} · {distance}" if distance else reference


def _sorted_groups(groups: dict[str, object]) -> list[tuple[str, float]]:
    parsed: list[tuple[str, float]] = []
    for name, value in groups.items():
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if number > 1e-9:
            parsed.append((str(name), number))
    parsed.sort(key=lambda item: item[1], reverse=True)
    return parsed


def _font(size: int, *, bold: bool = False) -> ImageFont.ImageFont:
    candidates = [
        Path("C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf"),
        Path("C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default()


def _ellipsize(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> str:
    if draw.textlength(text, font=font) <= max_width:
        return text
    suffix = "..."
    text = text.strip()
    while text and draw.textlength(text + suffix, font=font) > max_width:
        text = text[:-1].rstrip()
    return text + suffix if text else suffix


def _format_distance(value: object) -> str:
    try:
        return f"{float(value):.5f}"
    except (TypeError, ValueError):
        return ""


def _pretty(value: str) -> str:
    text = _clean(value)
    if not text:
        return "Unavailable"
    return display_name(text).replace("_", " ")


def _clean(value: str) -> str:
    return " ".join(str(value or "").strip().split())


def _str(value: object) -> str:
    return str(value or "").strip()


def _dict(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _list(value: object) -> list[object]:
    return value if isinstance(value, list) else []
