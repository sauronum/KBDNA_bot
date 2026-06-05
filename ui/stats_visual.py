from __future__ import annotations

from collections.abc import Sequence
from io import BytesIO
from pathlib import Path
from typing import Tuple

from PIL import Image, ImageDraw, ImageFont


Color = Tuple[int, int, int]

_WIDTH = 1080
_HEIGHT = 1920
_BG: Color = (12, 18, 31)
_PANEL: Color = (17, 24, 39)
_PANEL_SOFT: Color = (24, 34, 52)
_TEXT: Color = (244, 248, 252)
_MUTED: Color = (151, 164, 186)
_GRID: Color = (47, 61, 84)
_CYAN: Color = (70, 217, 224)
_BLUE: Color = (92, 145, 245)
_ORANGE: Color = (249, 115, 22)
_GOLD: Color = (255, 198, 105)
_GREEN: Color = (102, 220, 157)
_PINK: Color = (235, 112, 154)


def render_stats_summary_png(
    *,
    stats: dict[str, object],
    series: Sequence[tuple[str, int]],
    section_rows: Sequence[tuple[str, int, int, int, int]],
    lookup_rows: Sequence[tuple[str, int]],
    user_rows: Sequence[tuple[str, int]],
    recent_rows: Sequence[tuple[str, str]] = (),
) -> bytes:
    row_h = 31
    chart_y = 326
    chart_h = 320
    table_y = chart_y + chart_h + 36
    table_h = 118 + max(1, len(section_rows)) * row_h + _section_group_gap_count(section_rows) * 18
    bottom_y = table_y + table_h + 34
    bottom_h = max(560, _HEIGHT - bottom_y - 92)
    height = _HEIGHT

    image = Image.new("RGB", (_WIDTH, height), _BG)
    draw = ImageDraw.Draw(image, "RGBA")
    fonts = _fonts()

    _draw_background(draw, height)
    _draw_header(draw, fonts)
    _draw_metric_cards(draw, fonts, stats)
    _draw_chart(draw, fonts, (42, chart_y, _WIDTH - 84, chart_h), series)
    _draw_sections_table(draw, fonts, (42, table_y, _WIDTH - 84, table_h), section_rows)
    bottom_gap = 18
    bottom_left_w = 292
    bottom_middle_w = 330
    bottom_right_w = _WIDTH - 84 - bottom_gap * 2 - bottom_left_w - bottom_middle_w
    _draw_bottom_lists(
        draw,
        fonts,
        (42, bottom_y, bottom_left_w, bottom_h),
        (42 + bottom_left_w + bottom_gap, bottom_y, bottom_middle_w, bottom_h),
        (42 + bottom_left_w + bottom_gap + bottom_middle_w + bottom_gap, bottom_y, bottom_right_w, bottom_h),
        lookup_rows,
        user_rows,
        recent_rows,
    )
    _draw_footer(draw, fonts, height)

    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _draw_background(draw: ImageDraw.ImageDraw, height: int) -> None:
    for y in range(height):
        t = y / max(1, height - 1)
        r = int(10 + 8 * t)
        g = int(16 + 13 * t)
        b = int(30 + 21 * t)
        draw.line((0, y, _WIDTH, y), fill=(r, g, b, 255))
    _soft_glow(draw, (165, 88), 250, (*_CYAN, 28))
    _soft_glow(draw, (_WIDTH - 120, 210), 270, (*_ORANGE, 18))
    _soft_glow(draw, (_WIDTH - 210, height - 180), 260, (*_BLUE, 20))
    draw.rounded_rectangle((22, 22, _WIDTH - 22, height - 22), radius=18, outline=(62, 80, 110, 150), width=1)


def _draw_header(draw: ImageDraw.ImageDraw, fonts: dict[str, ImageFont.ImageFont]) -> None:
    draw.text((42, 40), "STATS", fill=(*_TEXT, 255), font=fonts["title"])
    draw.text((44, 88), "LAST 30 DAYS", fill=(*_MUTED, 255), font=fonts["small_caps"])
    draw.rounded_rectangle((_WIDTH - 256, 42, _WIDTH - 42, 92), radius=16, fill=(18, 28, 44, 230), outline=(*_GOLD, 180), width=1)
    draw.text((_WIDTH - 218, 56), "KBDNA", fill=(*_GOLD, 255), font=fonts["button"])


def _draw_metric_cards(draw: ImageDraw.ImageDraw, fonts: dict[str, ImageFont.ImageFont], stats: dict[str, object]) -> None:
    failed_total = int(stats["total"]) - int(stats["success"])
    cards = [
        ("Всего", str(stats["total"]), _CYAN),
        ("Успешность", f"{stats['success_rate']}%", _GREEN),
        ("Ошибок", str(failed_total), _PINK),
        ("Сегодня", str(stats["today"]), _GOLD),
        ("7 дней", str(stats["last_7_days"]), _BLUE),
        ("Пользователи", str(stats["unique_users"]), _ORANGE),
    ]
    gap = 14
    card_w = (_WIDTH - 84 - gap * 2) // 3
    card_h = 76
    for index, (label, value, color) in enumerate(cards):
        col = index % 3
        row = index // 3
        x = 42 + col * (card_w + gap)
        y = 128 + row * (card_h + gap)
        draw.rounded_rectangle((x, y, x + card_w, y + card_h), radius=12, fill=(*_PANEL, 235), outline=(*_GRID, 180), width=1)
        draw.rounded_rectangle((x, y, x + 7, y + card_h), radius=4, fill=(*color, 255))
        draw.text((x + 22, y + 13), label.upper(), fill=(*_MUTED, 255), font=fonts["label"])
        draw.text((x + 22, y + 34), value, fill=(*_TEXT, 255), font=fonts["metric"])


def _draw_chart(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, ImageFont.ImageFont],
    rect: tuple[int, int, int, int],
    series: Sequence[tuple[str, int]],
) -> None:
    x, y, w, h = rect
    _panel(draw, rect)
    draw.text((x + 22, y + 18), "Активность за месяц", fill=(*_TEXT, 255), font=fonts["section"])
    draw.text((x + 24, y + 48), "события по дням", fill=(*_MUTED, 255), font=fonts["tiny"])

    chart_x = x + 42
    chart_y = y + 88
    chart_w = w - 74
    chart_h = h - 140
    baseline = chart_y + chart_h
    points = list(series)
    max_value = max(1, max((int(value) for _, value in points), default=1))

    for step in range(5):
        yy = chart_y + int(chart_h * step / 4)
        draw.line((chart_x, yy, chart_x + chart_w, yy), fill=(*_GRID, 170), width=1)

    if not points:
        draw.text((chart_x, chart_y + 78), "Нет данных", fill=(*_MUTED, 255), font=fonts["small"])
        return

    gap = 5
    bar_w = max(10, int((chart_w - gap * (len(points) - 1)) / len(points)))
    for index, (label, value) in enumerate(points):
        value = int(value)
        bx = chart_x + index * (bar_w + gap)
        bar_h = int(round(chart_h * (value / max_value)))
        by = baseline - bar_h
        fill = _mix(_BLUE, _ORANGE, value / max_value if max_value else 0.0)
        draw.rounded_rectangle((bx, by, bx + bar_w, baseline), radius=3, fill=(*fill, 245))
        value_text = str(value)
        tw = draw.textlength(value_text, font=fonts["chart_value"])
        draw.text((bx + max(0, (bar_w - tw) / 2), max(chart_y - 16, by - 18)), value_text, fill=(*_TEXT, 255), font=fonts["chart_value"])
        label_text = str(label)
        if index % 2 == 0 or len(points) <= 18:
            tw = draw.textlength(label_text, font=fonts["chart_label"])
            draw.text((bx + max(0, (bar_w - tw) / 2), baseline + 14), label_text, fill=(*_MUTED, 255), font=fonts["chart_label"])


def _draw_sections_table(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, ImageFont.ImageFont],
    rect: tuple[int, int, int, int],
    rows: Sequence[tuple[str, int, int, int, int]],
) -> None:
    x, y, w, h = rect
    _panel(draw, rect)
    draw.text((x + 22, y + 18), "Разделы", fill=(*_TEXT, 255), font=fonts["section"])
    header_y = y + 56
    cols = [
        (x + 24, "Раздел"),
        (x + w - 360, "Всего"),
        (x + w - 262, "7д"),
        (x + w - 174, "Сегодня"),
        (x + w - 76, "Польз."),
    ]
    for cx, label in cols:
        anchor = "ra" if label != "Раздел" else None
        draw.text((cx, header_y), label, fill=(*_MUTED, 255), font=fonts["label"], anchor=anchor)
    draw.line((x + 22, header_y + 28, x + w - 22, header_y + 28), fill=(*_GRID, 190), width=1)

    if not rows:
        draw.text((x + 24, header_y + 54), "Нет данных", fill=(*_MUTED, 255), font=fonts["small"])
        return

    row_y = header_y + 42
    max_total = max(1, max(int(row[1]) for row in rows))
    bar_x = x + 392
    bar_w_max = 170
    current_y = row_y
    for index, (label, total, last_7_days, today, users) in enumerate(rows):
        if index > 0 and str(label) == "Словарь":
            draw.line((x + 22, current_y - 4, x + w - 22, current_y - 4), fill=(*_GRID, 210), width=1)
            current_y += 18
        yy = current_y
        if index % 2 == 0:
            draw.rounded_rectangle((x + 18, yy - 5, x + w - 18, yy + 25), radius=7, fill=(23, 33, 50, 120))
        color = (_CYAN, _GOLD, _BLUE, _GREEN, _ORANGE, _PINK)[index % 6]
        draw.rounded_rectangle((x + 24, yy + 5, x + 30, yy + 17), radius=3, fill=(*color, 255))
        label_fill = _TEXT if str(label) not in {"Фамилии", "Аналитика", "Словарь"} else _GOLD
        draw.text((x + 40, yy), _ellipsize(draw, str(label), fonts["small"], 330), fill=(*label_fill, 255), font=fonts["small"])
        bar_w = int(bar_w_max * int(total) / max_total)
        draw.rounded_rectangle((bar_x, yy + 6, bar_x + bar_w_max, yy + 16), radius=5, fill=(44, 57, 78, 200))
        draw.rounded_rectangle((bar_x, yy + 6, bar_x + bar_w, yy + 16), radius=5, fill=(*color, 220))
        for cx, value in ((x + w - 360, total), (x + w - 262, last_7_days), (x + w - 174, today), (x + w - 76, users)):
            draw.text((cx, yy), str(int(value)), fill=(*_TEXT, 255), font=fonts["small"], anchor="ra")
        current_y += 31
        if str(label) == "Аналитика":
            draw.line((x + 22, current_y + 2, x + w - 22, current_y + 2), fill=(*_GRID, 210), width=1)
            current_y += 18


def _draw_bottom_lists(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, ImageFont.ImageFont],
    left_rect: tuple[int, int, int, int],
    middle_rect: tuple[int, int, int, int],
    right_rect: tuple[int, int, int, int],
    lookup_rows: Sequence[tuple[str, int]],
    user_rows: Sequence[tuple[str, int]],
    recent_rows: Sequence[tuple[str, str]],
) -> None:
    _draw_list_panel(draw, fonts, left_rect, "Топ фамилий", lookup_rows, _GOLD)
    _draw_list_panel(draw, fonts, middle_rect, "Активные пользователи", user_rows, _CYAN)
    _draw_activity_panel(draw, fonts, right_rect, "Последние активности", recent_rows, _GREEN)


def _draw_list_panel(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, ImageFont.ImageFont],
    rect: tuple[int, int, int, int],
    title: str,
    rows: Sequence[tuple[str, int]],
    accent: Color,
) -> None:
    x, y, w, h = rect
    _panel(draw, rect)
    draw.text((x + 22, y + 18), _ellipsize(draw, title, fonts["bottom_section"], w - 44), fill=(*_TEXT, 255), font=fonts["bottom_section"])
    if not rows:
        draw.text((x + 22, y + 62), "Нет данных", fill=(*_MUTED, 255), font=fonts["small"])
        return
    visible_rows = list(rows[:25])
    row_gap = max(19, min(24, (h - 64) // max(1, len(visible_rows))))
    for index, (label, count) in enumerate(visible_rows, start=1):
        yy = y + 56 + (index - 1) * row_gap
        draw.text((x + 18, yy), f"{index:>2}.", fill=(*accent, 255), font=fonts["list_bold"])
        draw.text((x + 52, yy), _ellipsize(draw, str(label), fonts["list"], w - 122), fill=(*_TEXT, 255), font=fonts["list"])
        draw.text((x + w - 22, yy), str(int(count)), fill=(*_MUTED, 255), font=fonts["list_bold"], anchor="ra")


def _draw_activity_panel(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, ImageFont.ImageFont],
    rect: tuple[int, int, int, int],
    title: str,
    rows: Sequence[tuple[str, str]],
    accent: Color,
) -> None:
    x, y, w, h = rect
    _panel(draw, rect)
    draw.text((x + 22, y + 18), _ellipsize(draw, title, fonts["bottom_section"], w - 44), fill=(*_TEXT, 255), font=fonts["bottom_section"])
    if not rows:
        draw.text((x + 22, y + 62), "Нет данных", fill=(*_MUTED, 255), font=fonts["small"])
        return

    visible_rows = list(rows[:25])
    row_gap = max(19, min(24, (h - 64) // max(1, len(visible_rows))))
    section_w = 126
    for index, (user_label, section_label) in enumerate(visible_rows, start=1):
        yy = y + 56 + (index - 1) * row_gap
        draw.text((x + 18, yy), f"{index:>2}.", fill=(*accent, 255), font=fonts["list_bold"])
        draw.text(
            (x + 52, yy),
            _ellipsize(draw, str(user_label), fonts["list"], max(70, w - section_w - 78)),
            fill=(*_TEXT, 255),
            font=fonts["list"],
        )
        draw.text(
            (x + w - 22, yy),
            _ellipsize(draw, str(section_label), fonts["list_bold"], section_w),
            fill=(*accent, 255),
            font=fonts["list_bold"],
            anchor="ra",
        )


def _draw_footer(draw: ImageDraw.ImageDraw, fonts: dict[str, ImageFont.ImageFont], height: int) -> None:
    draw.line((42, height - 58, _WIDTH - 42, height - 58), fill=(*_GRID, 160), width=1)
    draw.text((42, height - 40), "KBDNA · usage statistics", fill=(*_MUTED, 255), font=fonts["tiny"])


def _panel(draw: ImageDraw.ImageDraw, rect: tuple[int, int, int, int]) -> None:
    x, y, w, h = rect
    draw.rounded_rectangle((x, y, x + w, y + h), radius=14, fill=(*_PANEL, 235), outline=(61, 78, 105, 190), width=1)


def _soft_glow(draw: ImageDraw.ImageDraw, center: tuple[int, int], radius: int, color: tuple[int, int, int, int]) -> None:
    cx, cy = center
    r, g, b, alpha = color
    for step in range(8, 0, -1):
        current = int(radius * step / 8)
        a = int(alpha * (step / 8) ** 2)
        draw.ellipse((cx - current, cy - current, cx + current, cy + current), fill=(r, g, b, a))


def _mix(left: Color, right: Color, t: float) -> Color:
    clamped = max(0.0, min(1.0, float(t)))
    return tuple(int(round(a + (b - a) * clamped)) for a, b in zip(left, right))


def _section_group_gap_count(rows: Sequence[tuple[str, int, int, int, int]]) -> int:
    labels = [str(row[0]) for row in rows]
    count = 0
    if "Аналитика" in labels and labels.index("Аналитика") < len(labels) - 1:
        count += 1
    if "Словарь" in labels and labels.index("Словарь") > 0:
        count += 1
    return count


def _ellipsize(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> str:
    text = str(text)
    if draw.textlength(text, font=font) <= max_width:
        return text
    suffix = "..."
    while text and draw.textlength(text + suffix, font=font) > max_width:
        text = text[:-1]
    return text.rstrip() + suffix if text else suffix


def _fonts() -> dict[str, ImageFont.ImageFont]:
    return {
        "title": _font(44, bold=True),
        "button": _font(26, bold=True),
        "metric": _font(24, bold=True),
        "section": _font(22, bold=True),
        "bottom_section": _font(18, bold=True),
        "small_caps": _font(17, bold=True),
        "small": _font(18),
        "small_bold": _font(18, bold=True),
        "list": _font(16),
        "list_bold": _font(16, bold=True),
        "label": _font(14, bold=True),
        "tiny": _font(13),
        "chart_value": _font(13, bold=True),
        "chart_label": _font(11),
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
