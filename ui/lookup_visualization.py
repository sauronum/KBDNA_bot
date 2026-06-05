from __future__ import annotations

from collections.abc import Mapping, Sequence
from io import BytesIO
from pathlib import Path
from typing import Tuple

from PIL import Image, ImageDraw, ImageFont


Color = Tuple[int, int, int]

_WIDTH = 1280
_HEIGHT = 900
_BG: Color = (12, 17, 27)
_PANEL: Color = (20, 28, 43)
_PANEL_SOFT: Color = (28, 39, 58)
_TEXT: Color = (246, 248, 252)
_MUTED: Color = (157, 170, 191)
_FAINT: Color = (85, 101, 126)
_GRID: Color = (48, 62, 84)
_CYAN: Color = (87, 210, 216)
_GOLD: Color = (255, 193, 105)
_CORAL: Color = (239, 124, 98)
_GREEN: Color = (116, 217, 159)
_BLUE: Color = (134, 169, 255)
_PINK: Color = (229, 118, 157)
_PURPLE: Color = (179, 139, 246)

_ACCENTS: tuple[Color, ...] = (_CYAN, _GOLD, _CORAL, _GREEN, _BLUE, _PINK, _PURPLE)


def render_lookup_record_png(record: Mapping[str, object]) -> bytes:
    name = _clean(record.get("visual_name") or record.get("name") or "")
    haplo_label = _clean(record.get("visual_haplogroup") or record.get("visual_haplo_display") or "")
    general = _clean(record.get("visual_general") or "")
    subclade = _clean(record.get("visual_subclade") or "")
    origins = _as_list(record.get("visual_origins"))
    related = _as_list(record.get("visual_related"))
    test_count = _int(record.get("visual_test_count"), default=len(origins) or 1)
    yfull_link = _clean(record.get("visual_yfull_link") or "")

    if not name or not haplo_label:
        raise ValueError("Lookup record does not contain visual fields.")

    image = _base_image()
    draw = ImageDraw.Draw(image, "RGBA")
    fonts = _fonts()

    _draw_header(
        draw,
        fonts,
        name=name,
        haplo_label=haplo_label,
        test_count=test_count,
        yfull_available=bool(yfull_link),
    )
    _draw_haplogroup_panel(
        draw,
        fonts,
        (40, 134, 760, 236),
        haplo_label=haplo_label,
        general=general,
        subclade=subclade,
        test_count=test_count,
    )
    _draw_origin_panel(
        draw,
        fonts,
        (40, 394, 760, 220),
        origins=origins,
    )
    _draw_related_panel(
        draw,
        fonts,
        (40, 638, 760, 182),
        related=related,
    )
    _draw_side_panel(
        draw,
        fonts,
        (836, 134, 404, 686),
        name=name,
        general=general,
        subclade=subclade,
        origins=origins,
        related=related,
        test_count=test_count,
        yfull_available=bool(yfull_link),
    )
    _draw_footer(
        draw,
        fonts,
        left=f"Фамилия: {name}",
        middle=f"Тестов в ветке: {test_count}",
        right="YFull: есть" if yfull_link else "YFull: нет ссылки",
    )

    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _base_image() -> Image.Image:
    image = Image.new("RGB", (_WIDTH, _HEIGHT), _BG)
    draw = ImageDraw.Draw(image, "RGBA")
    for y in range(_HEIGHT):
        t = y / max(1, _HEIGHT - 1)
        r = int(10 + 10 * t)
        g = int(17 + 20 * t)
        b = int(30 + 18 * t)
        draw.line((0, y, _WIDTH, y), fill=(r, g, b, 255))
    draw.rounded_rectangle((24, 24, _WIDTH - 24, _HEIGHT - 24), radius=14, outline=(61, 76, 101, 210), width=1)
    _soft_glow(draw, (160, 122), 210, (*_CYAN, 28))
    _soft_glow(draw, (1110, 164), 230, (*_CORAL, 24))
    _soft_glow(draw, (1018, 760), 230, (*_GOLD, 22))
    return image


def _draw_header(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, ImageFont.ImageFont],
    *,
    name: str,
    haplo_label: str,
    test_count: int,
    yfull_available: bool,
) -> None:
    draw.text((44, 38), "KBDNA LOOKUP", fill=(*_MUTED, 255), font=fonts["label"])
    draw.text((44, 62), _ellipsize(name.upper(), fonts["title"], 780, draw), fill=(*_TEXT, 255), font=fonts["title"])
    draw.text((46, 106), "поиск по фамилии", fill=(*_MUTED, 255), font=fonts["small"])

    pill = "YFULL LINK" if yfull_available else "LOCAL DATABASE"
    _pill(draw, fonts, (_WIDTH - 238, 42), pill, _CYAN if yfull_available else _FAINT)
    _pill(draw, fonts, (_WIDTH - 238, 82), f"{test_count} TESTS", _GOLD)
    draw.text((_WIDTH - 560, 92), _ellipsize(haplo_label, fonts["small_bold"], 300, draw), fill=(*_TEXT, 255), font=fonts["small_bold"])


def _draw_haplogroup_panel(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, ImageFont.ImageFont],
    rect: tuple[int, int, int, int],
    *,
    haplo_label: str,
    general: str,
    subclade: str,
    test_count: int,
) -> None:
    _panel(draw, rect)
    x, y, w, h = rect
    draw.text((x + 24, y + 22), "Гаплогруппа", fill=(*_TEXT, 255), font=fonts["section"])
    draw.text((x + 24, y + 52), "итоговая ветка для этой фамилии", fill=(*_MUTED, 255), font=fonts["tiny"])

    accent = _ACCENTS[sum(ord(ch) for ch in haplo_label) % len(_ACCENTS)]
    draw.rounded_rectangle((x + 24, y + 92, x + w - 24, y + 154), radius=12, fill=(*_PANEL_SOFT, 235), outline=(*accent, 210), width=2)
    draw.text((x + 46, y + 107), _ellipsize(haplo_label, fonts["headline"], w - 94, draw), fill=(*_TEXT, 255), font=fonts["headline"])

    _mini_metric(draw, fonts, (x + 24, y + 174, 210, 42), "основная", general or "-")
    _mini_metric(draw, fonts, (x + 252, y + 174, 280, 42), "субклад", subclade or "-")
    _mini_metric(draw, fonts, (x + 550, y + 174, 160, 42), "тестов", str(test_count))


def _draw_origin_panel(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, ImageFont.ImageFont],
    rect: tuple[int, int, int, int],
    *,
    origins: Sequence[str],
) -> None:
    _panel(draw, rect)
    x, y, w, _h = rect
    draw.text((x + 24, y + 20), "Происхождение", fill=(*_TEXT, 255), font=fonts["section"])
    draw.text((x + 24, y + 50), f"{len(origins)} уникальных записей по отцовской линии", fill=(*_MUTED, 255), font=fonts["tiny"])
    if not origins:
        _empty_state(draw, fonts, (x + 24, y + 86, w - 48, 90), "В таблице нет заполненного происхождения.")
        return

    wrapped = _join_limited(origins, limit=8)
    _wrapped_text(draw, (x + 24, y + 88), wrapped, fonts["small"], w - 48, fill=_TEXT, line_gap=8, max_lines=5)


def _draw_related_panel(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, ImageFont.ImageFont],
    rect: tuple[int, int, int, int],
    *,
    related: Sequence[str],
) -> None:
    _panel(draw, rect)
    x, y, w, _h = rect
    draw.text((x + 24, y + 18), "Соседние фамилии", fill=(*_TEXT, 255), font=fonts["section"])
    draw.text((x + 24, y + 48), "в той же ветке / субкладе", fill=(*_MUTED, 255), font=fonts["tiny"])
    if not related:
        _empty_state(draw, fonts, (x + 24, y + 78, w - 48, 70), "Для этой ветки соседние фамилии не найдены.")
        return

    visible = list(related[:18])
    col_w = (w - 62) // 3
    for idx, surname in enumerate(visible):
        col = idx // 6
        row = idx % 6
        tx = x + 24 + col * col_w
        ty = y + 78 + row * 19
        color = _ACCENTS[idx % len(_ACCENTS)]
        draw.rounded_rectangle((tx, ty + 6, tx + 7, ty + 13), radius=3, fill=(*color, 255))
        draw.text((tx + 14, ty), _ellipsize(str(surname), fonts["tiny"], col_w - 22, draw), fill=(*_TEXT, 255), font=fonts["tiny"])
    if len(related) > len(visible):
        draw.text((x + w - 130, y + 150), f"+{len(related) - len(visible)} еще", fill=(*_MUTED, 255), font=fonts["tiny"])


def _draw_side_panel(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, ImageFont.ImageFont],
    rect: tuple[int, int, int, int],
    *,
    name: str,
    general: str,
    subclade: str,
    origins: Sequence[str],
    related: Sequence[str],
    test_count: int,
    yfull_available: bool,
) -> None:
    _panel(draw, rect)
    x, y, w, _h = rect
    draw.text((x + 24, y + 22), "Профиль выдачи", fill=(*_TEXT, 255), font=fonts["section"])
    draw.text((x + 24, y + 52), "что реально показал поиск", fill=(*_MUTED, 255), font=fonts["tiny"])

    metrics = [
        ("Фамилия", name),
        ("Группа", general or "-"),
        ("Субклад", subclade or "-"),
        ("Тестов", str(test_count)),
        ("Происхождений", str(len(origins))),
        ("Соседей", str(len(related))),
        ("YFull", "ссылка есть" if yfull_available else "нет ссылки"),
    ]
    cy = y + 92
    for idx, (label, value) in enumerate(metrics):
        color = _ACCENTS[idx % len(_ACCENTS)]
        draw.rounded_rectangle((x + 24, cy, x + w - 24, cy + 56), radius=10, fill=(18, 27, 42, 230), outline=(*_GRID, 190), width=1)
        draw.rounded_rectangle((x + 24, cy, x + 31, cy + 56), radius=4, fill=(*color, 255))
        draw.text((x + 48, cy + 10), label.upper(), fill=(*_MUTED, 255), font=fonts["label"])
        draw.text((x + 48, cy + 29), _ellipsize(value, fonts["small_bold"], w - 90, draw), fill=(*_TEXT, 255), font=fonts["small_bold"])
        cy += 72

    note = "Карточка показывает агрегат по одной найденной ветке. Если у фамилии несколько веток, каждая открывается отдельно."
    _wrapped_text(draw, (x + 24, y + 610), note, fonts["tiny"], w - 48, fill=_MUTED, line_gap=5, max_lines=3)


def _draw_footer(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, ImageFont.ImageFont],
    *,
    left: str,
    middle: str,
    right: str,
) -> None:
    y = _HEIGHT - 58
    draw.line((42, y - 18, _WIDTH - 42, y - 18), fill=(*_GRID, 180), width=1)
    draw.text((44, y), _ellipsize(left, fonts["tiny"], 340, draw), fill=(*_MUTED, 255), font=fonts["tiny"])
    draw.text((450, y), _ellipsize(middle, fonts["tiny"], 340, draw), fill=(*_MUTED, 255), font=fonts["tiny"])
    draw.text((_WIDTH - 300, y), _ellipsize(right, fonts["tiny"], 250, draw), fill=(*_MUTED, 255), font=fonts["tiny"])


def _panel(draw: ImageDraw.ImageDraw, rect: tuple[int, int, int, int]) -> None:
    x, y, w, h = rect
    draw.rounded_rectangle((x, y, x + w, y + h), radius=14, fill=(*_PANEL, 235), outline=(62, 78, 102, 210), width=1)


def _pill(draw: ImageDraw.ImageDraw, fonts: dict[str, ImageFont.ImageFont], xy: tuple[int, int], text: str, color: Color) -> None:
    x, y = xy
    width = int(draw.textlength(text, font=fonts["label"])) + 30
    draw.rounded_rectangle((x, y, x + width, y + 28), radius=9, fill=(23, 34, 51, 245), outline=(*color, 210), width=1)
    draw.text((x + 15, y + 8), text, fill=(*color, 255), font=fonts["label"])


def _mini_metric(draw: ImageDraw.ImageDraw, fonts: dict[str, ImageFont.ImageFont], rect: tuple[int, int, int, int], label: str, value: str) -> None:
    x, y, w, h = rect
    draw.rounded_rectangle((x, y, x + w, y + h), radius=10, fill=(15, 23, 36, 235), outline=(*_GRID, 180), width=1)
    draw.text((x + 14, y + 7), label.upper(), fill=(*_MUTED, 255), font=fonts["label"])
    draw.text((x + 14, y + 23), _ellipsize(value, fonts["tiny_bold"], w - 28, draw), fill=(*_TEXT, 255), font=fonts["tiny_bold"])


def _empty_state(draw: ImageDraw.ImageDraw, fonts: dict[str, ImageFont.ImageFont], rect: tuple[int, int, int, int], text: str) -> None:
    x, y, w, h = rect
    draw.rounded_rectangle((x, y, x + w, y + h), radius=10, fill=(15, 23, 36, 180), outline=(*_GRID, 150), width=1)
    _wrapped_text(draw, (x + 18, y + 24), text, fonts["small"], w - 36, fill=_MUTED, max_lines=2)


def _wrapped_text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    font: ImageFont.ImageFont,
    max_width: int,
    *,
    fill: Color,
    line_gap: int = 6,
    max_lines: int = 4,
) -> None:
    x, y = xy
    words = str(text).split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = word if not current else f"{current} {word}"
        if draw.textlength(candidate, font=font) <= max_width:
            current = candidate
            continue
        if current:
            lines.append(current)
        current = word
        if len(lines) >= max_lines:
            break
    if current and len(lines) < max_lines:
        lines.append(current)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
    line_height = _line_height(font)
    for index, line in enumerate(lines):
        if index == max_lines - 1 and words:
            line = _ellipsize(line, font, max_width, draw)
        draw.text((x, y + index * (line_height + line_gap)), line, fill=(*fill, 255), font=font)


def _soft_glow(draw: ImageDraw.ImageDraw, center: tuple[int, int], radius: int, color: tuple[int, int, int, int]) -> None:
    cx, cy = center
    r, g, b, alpha = color
    for step in range(8, 0, -1):
        current = int(radius * step / 8)
        a = int(alpha * (step / 8) ** 2)
        draw.ellipse((cx - current, cy - current, cx + current, cy + current), fill=(r, g, b, a))


def _join_limited(items: Sequence[str], *, limit: int) -> str:
    visible = [str(item) for item in items[:limit] if str(item).strip()]
    text = "; ".join(visible)
    if len(items) > limit:
        text += f"; +{len(items) - limit} еще"
    return text


def _as_list(value: object) -> list[str]:
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, Sequence):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _int(value: object, *, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _clean(value: object) -> str:
    return " ".join(str(value or "").split())


def _ellipsize(text: str, font: ImageFont.ImageFont, max_width: int, draw: ImageDraw.ImageDraw) -> str:
    text = str(text)
    if draw.textlength(text, font=font) <= max_width:
        return text
    suffix = "..."
    while text and draw.textlength(text + suffix, font=font) > max_width:
        text = text[:-1]
    return (text + suffix) if text else suffix


def _line_height(font: ImageFont.ImageFont) -> int:
    try:
        box = font.getbbox("Ag")
        return max(1, int(box[3] - box[1]))
    except Exception:
        return int(getattr(font, "size", 14))


def _fonts() -> dict[str, ImageFont.ImageFont]:
    return {
        "title": _font(42, bold=True),
        "headline": _font(31, bold=True),
        "section": _font(22, bold=True),
        "label": _font(12, bold=True),
        "small": _font(17),
        "small_bold": _font(17, bold=True),
        "tiny": _font(13),
        "tiny_bold": _font(13, bold=True),
    }


def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        Path("C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf"),
        Path("C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default()
