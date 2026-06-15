from __future__ import annotations

import math
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .ready_models_runtime import SourceFitComponent, SourceFitResult, format_fit_quality


CANVAS_WIDTH = 1400
MIN_CANVAS_HEIGHT = 525
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

_ACCENTS = (
    (52, 196, 216),
    (107, 136, 221),
    (200, 114, 164),
    (217, 172, 91),
    (78, 187, 146),
    (80, 146, 195),
    (203, 114, 102),
    (132, 177, 106),
)


@dataclass(frozen=True)
class RenderedSourceFitCard:
    image_bytes: bytes
    caption: str
    result: SourceFitResult


def render_source_fit_card(result: SourceFitResult, *, lang: str = "ru") -> bytes:
    components = [component for component in result.components if component.percent >= 0.1]
    row_h = 70
    components_top = 205
    footer_h = 85
    height = max(MIN_CANVAS_HEIGHT, components_top + len(components) * row_h + footer_h)
    width = CANVAS_WIDTH
    margin = 54

    image = _gradient_background(width, height)
    draw = ImageDraw.Draw(image)
    fonts = _fonts()

    _draw_grid(draw, width, height)
    _draw_glow_blob(image, (1120, 80), 280, (66, 84, 186), 48)
    _draw_glow_blob(image, (1090, 284), 220, (39, 164, 185), 25)
    _draw_glow_blob(image, (220, height - 100), 250, (208, 133, 68), 18)
    _glow_rect(image, (24, 24, width - 24, height - 24), 30, (52, 191, 255), 46)
    draw.rounded_rectangle((24, 24, width - 24, height - 24), radius=30, fill=(8, 18, 32), outline=(73, 104, 138), width=2)

    draw.text((margin, 49), "READY MODEL" if lang == "en" else "ГОТОВАЯ МОДЕЛЬ", font=fonts["title"], fill=(244, 247, 251))
    context_line = f"{result.source_set_title}  ·  {result.target_name}"
    draw.text((margin, 106), _ellipsize(context_line, fonts["context"], 800, draw), font=fonts["context"], fill=(147, 169, 194))
    draw.line((margin, 148, width - margin, 148), fill=(39, 59, 81), width=1)

    card_top = 49
    card_gap = 16
    card_h = 88
    card_w = 205
    x_fit = width - margin - (card_w * 2) - card_gap
    x_distance = x_fit + card_w + card_gap
    _draw_info_card(
        image,
        fonts,
        (x_fit, card_top, x_fit + card_w, card_top + card_h),
        "FIT" if lang == "en" else "КАЧЕСТВО",
        _title_case(_fit_quality(result.distance, lang)),
        _fit_color(result.distance),
        "fit",
    )
    _draw_info_card(
        image,
        fonts,
        (x_distance, card_top, x_distance + card_w, card_top + card_h),
        "DISTANCE" if lang == "en" else "ДИСТАНЦИЯ",
        f"{float(result.distance or 0.0):.4f}",
        _ACCENTS[3],
        "distance",
    )

    section_y = components_top - 40
    draw.text((margin, section_y), "COMPONENTS" if lang == "en" else "КОМПОНЕНТЫ", font=fonts["section"], fill=(246, 250, 255))
    for index, component in enumerate(components):
        row_top = components_top + index * row_h
        _draw_component_row(
            image,
            fonts,
            component,
            index=index,
            rect=(margin, row_top, width - margin, row_top + 50),
            accent=_ACCENTS[index % len(_ACCENTS)],
        )

    footer_y = height - 70
    draw.line((margin, footer_y - 15, width - margin, footer_y - 15), fill=(38, 58, 78), width=1)
    footer = "G25-fit model · not qpAdm    ·    Proxy sources" if lang == "en" else "G25-fit модель · не qpAdm    ·    proxy-источники"
    _draw_centered_text(draw, footer, (margin, footer_y + 4, width - margin, footer_y + 36), fonts["footer"], (132, 151, 173))

    buffer = BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def source_fit_caption(result: SourceFitResult, *, lang: str = "ru") -> str:
    if lang == "en":
        return "\n".join(
            [
                "📚 Ready models",
                f"G25 profile: {result.target_name}",
                f"Model: {result.source_set_title}",
                f"Distance: {float(result.distance or 0.0):.4f}",
                "",
                "G25-fit model, not qpAdm.",
            ]
        )
    return "\n".join(
        [
            "📚 Готовые модели",
            f"G25-профиль: {result.target_name}",
            f"Модель: {result.source_set_title}",
            f"Дистанция: {float(result.distance or 0.0):.4f}",
            "",
            "Это G25-fit модель, не qpAdm.",
        ]
    )


def _fit_quality(distance: float | None, lang: str = "ru") -> str:
    if lang != "en":
        return format_fit_quality(distance)
    if distance is None:
        return "unknown"
    if distance <= 0.0200:
        return "good"
    if distance <= 0.0300:
        return "medium"
    return "weak"


def build_rendered_source_fit_card(result: SourceFitResult, *, lang: str = "ru") -> RenderedSourceFitCard:
    return RenderedSourceFitCard(
        image_bytes=render_source_fit_card(result, lang=lang),
        caption=source_fit_caption(result, lang=lang),
        result=result,
    )


def _gradient_background(width: int, height: int) -> Image.Image:
    image = Image.new("RGB", (width, height))
    pixels = image.load()
    for y in range(height):
        t = y / max(1, height - 1)
        for x in range(width):
            s = x / max(1, width - 1)
            r = int(5 + 7 * t + 4 * s)
            g = int(11 + 11 * t + 4 * s)
            b = int(24 + 22 * t + 12 * s)
            pixels[x, y] = (r, g, b)
    return image


def _draw_grid(draw: ImageDraw.ImageDraw, width: int, height: int) -> None:
    for x in range(70, width, 70):
        draw.line((x, 38, x, height - 38), fill=(20, 39, 60), width=1)
    for y in range(70, height, 70):
        draw.line((38, y, width - 38, y), fill=(18, 35, 55), width=1)
    for x in range(76, width - 60, 168):
        for y in range(92, height - 70, 126):
            draw.ellipse((x - 2, y - 2, x + 2, y + 2), fill=(36, 82, 109))


def _draw_glow_blob(image: Image.Image, center: tuple[int, int], radius: int, color: tuple[int, int, int], alpha: int) -> None:
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    x, y = center
    odraw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=(*color, alpha))
    overlay = overlay.filter(ImageFilter.GaussianBlur(radius // 2))
    _composite_overlay(image, overlay)


def _draw_dna_pattern(draw: ImageDraw.ImageDraw, origin: tuple[int, int], width: int, height: int) -> None:
    x0, y0 = origin
    steps = 12
    points_a: list[tuple[float, float]] = []
    points_b: list[tuple[float, float]] = []
    for i in range(steps + 1):
        t = i / steps
        y = y0 + t * height
        wave = math.sin(t * math.tau * 1.8)
        ax = x0 + width * 0.45 + wave * 44
        bx = x0 + width * 0.45 - wave * 44
        points_a.append((ax, y))
        points_b.append((bx, y))
        draw.line((ax, y, bx, y), fill=(40, 91, 125), width=1)
        draw.ellipse((ax - 4, y - 4, ax + 4, y + 4), fill=(70, 221, 255))
        draw.ellipse((bx - 4, y - 4, bx + 4, y + 4), fill=(146, 112, 255))
    draw.line(points_a, fill=(52, 158, 225), width=2)
    draw.line(points_b, fill=(116, 89, 217), width=2)


def _draw_info_card(
    image: Image.Image,
    fonts: dict[str, ImageFont.ImageFont],
    rect: tuple[int, int, int, int],
    label: str,
    value: str,
    accent: tuple[int, int, int],
    icon_kind: str,
) -> None:
    draw = ImageDraw.Draw(image)
    _glow_rect(image, rect, 20, accent, 26)
    draw.rounded_rectangle(rect, radius=18, fill=(17, 29, 45), outline=_mix(accent, (114, 130, 148), 0.34), width=1)
    x0, y0, x1, y1 = rect
    draw.rectangle((x0 + 20, y0 + 18, x0 + 55, y0 + 21), fill=accent)
    draw.text((x0 + 20, y0 + 29), label, font=fonts["label"], fill=(129, 147, 169))
    _draw_metric_icon(draw, icon_kind, (x1 - 43, y0 + 33), accent)
    draw.text((x0 + 20, y0 + 54), _ellipsize(value, fonts["metric"], x1 - x0 - 70, draw), font=fonts["metric"], fill=(244, 247, 251))


def _draw_component_row(
    image: Image.Image,
    fonts: dict[str, ImageFont.ImageFont],
    component: SourceFitComponent,
    *,
    index: int,
    rect: tuple[int, int, int, int],
    accent: tuple[int, int, int],
) -> None:
    draw = ImageDraw.Draw(image)
    x0, y0, x1, y1 = rect
    row_fill = (15, 26, 41) if index % 2 == 0 else (12, 23, 37)
    draw.rounded_rectangle(rect, radius=13, fill=row_fill, outline=(29, 46, 65), width=1)
    marker_x = x0 + 30
    marker_y = y0 + 25
    _glow_circle(image, (marker_x, marker_y), 12, accent, 22)
    draw.rounded_rectangle((marker_x - 4, marker_y - 16, marker_x + 4, marker_y + 16), radius=4, fill=accent)

    label_x = x0 + 64
    pct_w = 126
    bar_x0 = x0 + 405
    bar_x1 = x1 - pct_w - 34
    label_max = bar_x0 - label_x - 24
    draw.text((label_x, y0 + 10), _ellipsize(component.label, fonts["body"], label_max, draw), font=fonts["body"], fill=(239, 244, 250))

    bar_y = y0 + 16
    bar_h = 17
    draw.rounded_rectangle((bar_x0, bar_y, bar_x1, bar_y + bar_h), radius=7, fill=(33, 48, 70))
    fill_w = int(max(2, (bar_x1 - bar_x0) * min(100.0, max(0.0, component.percent)) / 100.0))
    _glow_rect(image, (bar_x0, bar_y, bar_x0 + fill_w, bar_y + bar_h), 7, accent, 18)
    draw.rounded_rectangle((bar_x0, bar_y, bar_x0 + fill_w, bar_y + bar_h), radius=7, fill=accent)

    pct = f"{component.percent:.1f}%"
    draw.text((x1 - pct_w, y0 + 6), pct, font=fonts["percent"], fill=_mix(accent, (255, 255, 255), 0.28))


def _draw_metric_icon(draw: ImageDraw.ImageDraw, kind: str, center: tuple[int, int], accent: tuple[int, int, int]) -> None:
    x, y = center
    if kind == "profile":
        draw.arc((x - 11, y - 13, x + 5, y + 13), 275, 85, fill=accent, width=2)
        draw.arc((x - 5, y - 13, x + 11, y + 13), 95, 265, fill=accent, width=2)
        draw.line((x - 4, y - 7, x + 4, y - 7), fill=accent, width=2)
        draw.line((x - 5, y + 3, x + 5, y + 3), fill=accent, width=2)
    elif kind == "model":
        for px, py in ((x - 10, y + 7), (x, y - 9), (x + 11, y + 6)):
            draw.ellipse((px - 3, py - 3, px + 3, py + 3), fill=accent)
        draw.line((x - 8, y + 5, x - 1, y - 6), fill=accent, width=2)
        draw.line((x + 2, y - 6, x + 9, y + 4), fill=accent, width=2)
    elif kind == "fit":
        draw.ellipse((x - 13, y - 13, x + 13, y + 13), outline=accent, width=2)
        draw.line((x - 7, y, x - 2, y + 6), fill=accent, width=3)
        draw.line((x - 2, y + 6, x + 8, y - 6), fill=accent, width=3)
    else:
        draw.arc((x - 13, y - 12, x + 13, y + 14), 190, 350, fill=accent, width=2)
        draw.line((x, y + 2, x + 8, y - 5), fill=accent, width=3)
        draw.ellipse((x - 2, y, x + 2, y + 4), fill=accent)


def _glow_rect(image: Image.Image, rect: tuple[int, int, int, int], radius: int, color: tuple[int, int, int], alpha: int) -> None:
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    for spread, spread_alpha in ((16, alpha // 3), (8, alpha // 2), (3, alpha)):
        expanded = (rect[0] - spread, rect[1] - spread, rect[2] + spread, rect[3] + spread)
        odraw.rounded_rectangle(expanded, radius=radius + spread, outline=(*color, spread_alpha), width=max(1, spread // 3))
    overlay = overlay.filter(ImageFilter.GaussianBlur(8))
    _composite_overlay(image, overlay)


def _glow_circle(image: Image.Image, center: tuple[int, int], radius: int, color: tuple[int, int, int], alpha: int) -> None:
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    x, y = center
    odraw.ellipse((x - radius * 2, y - radius * 2, x + radius * 2, y + radius * 2), fill=(*color, alpha))
    overlay = overlay.filter(ImageFilter.GaussianBlur(radius))
    _composite_overlay(image, overlay)


def _composite_overlay(image: Image.Image, overlay: Image.Image) -> None:
    merged = Image.alpha_composite(image.convert("RGBA"), overlay)
    image.paste(merged.convert("RGB"))


def _draw_centered_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    rect: tuple[int, int, int, int],
    font: ImageFont.ImageFont,
    fill: tuple[int, int, int],
) -> None:
    x0, y0, x1, y1 = rect
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    draw.text((x0 + (x1 - x0 - text_w) / 2, y0 + (y1 - y0 - text_h) / 2 - 1), text, font=font, fill=fill)


def _fit_color(distance: float | None) -> tuple[int, int, int]:
    quality = format_fit_quality(distance)
    if quality == "хороший":
        return (72, 232, 170)
    if quality == "средний":
        return (255, 184, 78)
    return (255, 104, 124)


def _mix(a: tuple[int, int, int], b: tuple[int, int, int], amount: float) -> tuple[int, int, int]:
    return tuple(int(a[i] * (1 - amount) + b[i] * amount) for i in range(3))


def _title_case(label: str) -> str:
    return label[:1].upper() + label[1:] if label else label


def _ellipsize(text: str, font: ImageFont.ImageFont, max_width: int, draw: ImageDraw.ImageDraw) -> str:
    if _text_width(draw, text, font) <= max_width:
        return text
    suffix = "..."
    current = text
    while current and _text_width(draw, current + suffix, font) > max_width:
        current = current[:-1]
    return (current.rstrip() + suffix) if current else suffix


def _text_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> int:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0]


def _fonts() -> dict[str, ImageFont.ImageFont]:
    return {
        "title": _font(48, bold=True),
        "context": _font(23),
        "section": _font(32, bold=True),
        "metric": _font(30, bold=True),
        "body": _font(25),
        "percent": _font(27, bold=True),
        "label": _font(18, bold=True),
        "tiny": _font(15, bold=True),
        "footer": _font(21, bold=True),
    }


def _font(size: int, *, bold: bool = False) -> ImageFont.ImageFont:
    names = ("arialbd.ttf", "DejaVuSans-Bold.ttf") if bold else ("arial.ttf", "DejaVuSans.ttf")
    roots = [
        Path("C:/Windows/Fonts"),
        Path("/usr/share/fonts/truetype/dejavu"),
        Path("/usr/share/fonts/truetype/liberation"),
    ]
    for root in roots:
        for name in names:
            candidate = root / name
            if candidate.exists():
                return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default()
