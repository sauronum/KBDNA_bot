from __future__ import annotations

import math
import struct
import zlib
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

from g25_core.render_fit_png import FONT_5X7


PNG_EXTRA_GLYPHS = {
    "*": [
        0b00100,
        0b10101,
        0b01110,
        0b11111,
        0b01110,
        0b10101,
        0b00100,
    ],
}


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


def _mono_font(size: int, *, bold: bool = False) -> ImageFont.ImageFont:
    names = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "C:/Windows/Fonts/consolab.ttf" if bold else "C:/Windows/Fonts/consola.ttf",
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
    ]
    for name in names:
        try:
            return ImageFont.truetype(name, size=size)
        except Exception:
            continue
    return ImageFont.load_default()


def _fit_text(draw: ImageDraw.ImageDraw, text: object, font: ImageFont.ImageFont, max_width: int) -> str:
    value = str(text or "")
    if draw.textlength(value, font=font) <= max_width:
        return value
    suffix = "..."
    while value and draw.textlength(value + suffix, font=font) > max_width:
        value = value[:-1]
    return value.rstrip() + suffix if value else suffix


def _save_png_bytes(image: Image.Image) -> bytes:
    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


def haplo_mode_title(mode: str) -> str:
    return "По родам" if mode == "families" else "По тестам"


def haplo_png_mode_title(mode: str) -> str:
    return "BY CLANS" if mode == "families" else "BY TESTS"


def haplo_png_scope_title(scope: str | None = None) -> str:
    return str(scope or "KARACHAY-BALKARS").upper()


def haplo_distribution_caption(mode: str, total: int, *, scope_label: str | None = None) -> str:
    parts = ["Распределение гаплогрупп"]
    if scope_label:
        parts.append(scope_label)
    parts.extend([haplo_mode_title(mode).lower(), str(total)])
    return " · ".join(parts)


def haplo_subclade_caption(group_label: str, mode: str, total: int, *, scope_label: str | None = None) -> str:
    subject = f"Субклады {group_label}"
    if scope_label:
        subject = f"{subject} · {scope_label}"
    else:
        subject = f"{subject} у карачаево-балкарцев"
    return f"{subject} · {haplo_mode_title(mode).lower()} · {total}"


def mtdna_distribution_caption(kind: str, total: int) -> str:
    label = "гаплогруппы" if kind == "groups" else "субклады"
    return f"МтДНК · {label} · по образцам · {total}"


def haplo_png_label(label: str) -> str:
    return "OTHER" if label == "Прочее" else label.upper()


def _png_fill(buffer: bytearray, color: tuple[int, int, int]) -> None:
    pixel = bytes(color)
    buffer[:] = pixel * (len(buffer) // 3)


def _png_put_rect(buffer: bytearray, width: int, height: int, x: int, y: int, rect_w: int, rect_h: int, color: tuple[int, int, int]) -> None:
    x0 = max(0, x)
    y0 = max(0, y)
    x1 = min(width, x + rect_w)
    y1 = min(height, y + rect_h)
    if x0 >= x1 or y0 >= y1:
        return
    row_bytes = bytes(color) * (x1 - x0)
    for yy in range(y0, y1):
        start = (yy * width + x0) * 3
        buffer[start:start + len(row_bytes)] = row_bytes


def _png_draw_char(buffer: bytearray, width: int, height: int, x: int, y: int, char: str, color: tuple[int, int, int], scale: int = 2) -> None:
    glyph = FONT_5X7.get(char.upper())
    if glyph is None:
        glyph = PNG_EXTRA_GLYPHS.get(char, FONT_5X7[" "])
    for gy, row in enumerate(glyph):
        for gx in range(5):
            if row & (1 << (4 - gx)):
                _png_put_rect(buffer, width, height, x + gx * scale, y + gy * scale, scale, scale, color)


def _png_draw_text(buffer: bytearray, width: int, height: int, x: int, y: int, text: str, color: tuple[int, int, int], scale: int = 2) -> None:
    cursor_x = x
    for char in text:
        _png_draw_char(buffer, width, height, cursor_x, y, char, color, scale)
        cursor_x += 6 * scale


def _png_text_width(text: str, scale: int = 2) -> int:
    return len(text) * 6 * scale


def _png_text_height(scale: int = 2) -> int:
    return 7 * scale


def _png_draw_text_centered(
    buffer: bytearray,
    width: int,
    height: int,
    center_x: int,
    y: int,
    text: str,
    color: tuple[int, int, int],
    scale: int = 2,
) -> None:
    _png_draw_text(buffer, width, height, center_x - _png_text_width(text, scale) // 2, y, text, color, scale)


def _png_draw_text_right(
    buffer: bytearray,
    width: int,
    height: int,
    right_x: int,
    y: int,
    text: str,
    color: tuple[int, int, int],
    scale: int = 2,
) -> None:
    _png_draw_text(buffer, width, height, right_x - _png_text_width(text, scale), y, text, color, scale)


def _png_draw_panel(
    buffer: bytearray,
    width: int,
    height: int,
    x: int,
    y: int,
    panel_w: int,
    panel_h: int,
    fill: tuple[int, int, int],
    border: tuple[int, int, int],
    corner: tuple[int, int, int],
) -> None:
    _png_put_rect(buffer, width, height, x, y, panel_w, panel_h, fill)
    _png_put_rect(buffer, width, height, x, y, panel_w, 1, border)
    _png_put_rect(buffer, width, height, x, y + panel_h - 1, panel_w, 1, border)
    _png_put_rect(buffer, width, height, x, y, 1, panel_h, border)
    _png_put_rect(buffer, width, height, x + panel_w - 1, y, 1, panel_h, border)
    for px, py in (
        (x + 6, y + 6),
        (x + panel_w - 9, y + 6),
        (x + 6, y + panel_h - 9),
        (x + panel_w - 9, y + panel_h - 9),
    ):
        _png_put_rect(buffer, width, height, px, py, 3, 3, corner)


def _png_draw_segmented_bar(
    buffer: bytearray,
    width: int,
    height: int,
    x: int,
    y: int,
    bar_w: int,
    fill_w: int,
    color: tuple[int, int, int],
    track: tuple[int, int, int],
) -> None:
    _png_put_rect(buffer, width, height, x, y, bar_w, 14, track)
    if fill_w > 0:
        _png_put_rect(buffer, width, height, x, y, min(bar_w, fill_w), 14, color)
    for marker_x in range(x + 12, x + bar_w, 12):
        _png_put_rect(buffer, width, height, marker_x, y, 1, 14, track)


def _png_write_bytes(width: int, height: int, rgb_data: bytearray) -> bytes:
    raw = bytearray()
    stride = width * 3
    for y in range(height):
        raw.append(0)
        raw.extend(rgb_data[y * stride:(y + 1) * stride])
    compressed = zlib.compress(bytes(raw), 9)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack("!I", len(data))
            + tag
            + data
            + struct.pack("!I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack("!IIBBBBB", width, height, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", compressed)
    png += chunk(b"IEND", b"")
    return png


def render_haplo_distribution_png(
    items: list[dict[str, object]],
    total: int,
    mode: str,
    *,
    title: str = "HAPLOGROUPS",
    subtitle: str | None = None,
    scope: str | None = None,
) -> bytes:
    width = 1280
    row_gap = 62
    row_y = 172
    height = max(960, row_y + max(1, len(items)) * row_gap + 120)
    bg = (13, 22, 36)
    fg = (238, 241, 247)
    muted = (160, 171, 192)
    colors = [
        (34, 197, 94),
        (59, 130, 246),
        (245, 158, 11),
        (239, 68, 68),
        (139, 92, 246),
        (6, 182, 212),
        (132, 204, 22),
        (249, 115, 22),
        (34, 197, 94),
        (59, 130, 246),
        (245, 158, 11),
    ]

    buffer = bytearray(width * height * 3)
    _png_fill(buffer, bg)

    header_subtitle = subtitle or haplo_png_mode_title(mode)
    scope_label = haplo_png_scope_title(scope)

    _png_draw_text(buffer, width, height, 74, 72, title.upper(), fg, scale=5)
    _png_draw_text(buffer, width, height, 77, 128, header_subtitle, muted, scale=3)
    _png_draw_text(buffer, width, height, 77, 164, scope_label, muted, scale=2)

    cx = 315
    cy = 535
    outer_r = 218
    inner_r = 126
    segment_limits: list[tuple[float, tuple[int, int, int]]] = []
    running = 0.0
    if total > 0:
        for index, item in enumerate(items):
            count = int(item.get("count") or 0)
            if count <= 0:
                continue
            running += (count / total) * (2 * math.pi)
            segment_limits.append((running, colors[index % len(colors)]))

    inner_sq = inner_r * inner_r
    outer_sq = outer_r * outer_r
    for py in range(cy - outer_r, cy + outer_r + 1):
        if py < 0 or py >= height:
            continue
        dy = py - cy
        for px in range(cx - outer_r, cx + outer_r + 1):
            if px < 0 or px >= width:
                continue
            dx = px - cx
            dist_sq = dx * dx + dy * dy
            if dist_sq < inner_sq or dist_sq > outer_sq:
                continue
            angle = (math.atan2(dy, dx) + math.pi / 2) % (2 * math.pi)
            color = colors[0] if not segment_limits else segment_limits[-1][1]
            for limit, segment_color in segment_limits:
                if angle <= limit:
                    color = segment_color
                    break
            offset = (py * width + px) * 3
            buffer[offset:offset + 3] = bytes(color)

    total_text = str(total)
    total_scale = 6
    label_scale = 3
    center_gap = 18
    center_block_h = _png_text_height(total_scale) + center_gap + _png_text_height(label_scale)
    total_y = cy - center_block_h // 2
    label_y = total_y + _png_text_height(total_scale) + center_gap
    _png_draw_text_centered(buffer, width, height, cx, total_y, total_text, fg, scale=total_scale)
    _png_draw_text_centered(buffer, width, height, cx, label_y, "TOTAL", muted, scale=label_scale)

    swatch_x = 660
    label_x = 698
    count_right = 938
    percent_right = 1130
    for index, item in enumerate(items):
        y = row_y + index * row_gap
        color = colors[index % len(colors)]
        label = haplo_png_label(str(item.get("label") or ""))
        count = int(item.get("count") or 0)
        percent = (count / total * 100) if total else 0.0
        _png_put_rect(buffer, width, height, swatch_x, y + 5, 24, 24, color)
        _png_draw_text(buffer, width, height, label_x, y, label, fg, scale=4)
        _png_draw_text_right(buffer, width, height, count_right, y, str(count), fg, scale=4)
        _png_draw_text_right(buffer, width, height, percent_right, y, f"{percent:.1f}%", fg, scale=4)

    return _png_write_bytes(width, height, buffer)
