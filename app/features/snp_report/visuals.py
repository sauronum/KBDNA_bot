from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .domain import SnpCategorySummary
from .storage import SnpReportRecord


_BG_TOP = (9, 22, 38)
_BG_BOTTOM = (17, 44, 68)
_PANEL = (18, 32, 49)
_PANEL_2 = (22, 41, 62)
_BORDER = (58, 92, 124)
_TEXT = (241, 247, 255)
_MUTED = (166, 184, 205)
_BLUE = (82, 177, 255)
_GREEN = (72, 211, 141)
_YELLOW = (255, 199, 73)
_RED = (255, 92, 99)
_GRAY = (144, 161, 178)


def render_category_load_png(
    record: SnpReportRecord,
    output_path: Path,
    *,
    lang: str = "ru",
    top_limit: int = 10,
) -> Path:
    categories = [
        SnpCategorySummary(**item)
        for item in record.payload.get("categories", [])
        if isinstance(item, dict)
    ][:top_limit]
    summary = record.summary
    width = 1440
    row_h = 66
    table_top = 270
    table_header_h = 44
    table_bottom = table_top + table_header_h + max(1, len(categories)) * row_h
    height = table_bottom + 58

    image = Image.new("RGB", (width, height), _BG_TOP)
    draw = ImageDraw.Draw(image)
    _draw_vertical_gradient(draw, width, height)

    margin = 48
    draw.rounded_rectangle((margin, 34, width - margin, height - 34), radius=28, fill=_PANEL, outline=_BORDER, width=2)

    title_font = _font(42, bold=True)
    subtitle_font = _font(24)
    metric_label_font = _font(18)
    metric_value_font = _font(28, bold=True)
    label_font = _font(22, bold=True)
    small_font = _font(19)
    percent_font = _font(23, bold=True)

    x = margin + 38
    y = 70
    draw.text((x, y), "SNP Lab", font=subtitle_font, fill=_BLUE)
    draw.text((x, y + 32), "Нагрузка по категориям", font=title_font, fill=_TEXT)

    found = max(0, summary.total_rules - summary.missing)
    subtitle = f"Sample: {summary.sample_name}   •   найдено {found} из {summary.total_rules} SNP"
    draw.text((x, y + 86), subtitle, font=subtitle_font, fill=_MUTED)

    strip_top = 190
    _draw_summary_strip(
        draw,
        (x, strip_top, width - margin - 38, strip_top + 54),
        (
            ("Норма", summary.ok, _GREEN),
            ("Гетеро", summary.warn, _YELLOW),
            ("Гомо", summary.bad, _RED),
            ("Нет данных", summary.missing, _GRAY),
        ),
        metric_label_font,
        metric_value_font,
    )

    table_left = x
    table_right = width - margin - 38
    _draw_compact_table_header(draw, table_left, table_top, table_right, table_header_h, small_font)

    start_y = table_top + table_header_h
    if not categories:
        draw.text((x, start_y + 26), "Категории не найдены.", font=label_font, fill=_TEXT)
    for index, item in enumerate(categories, start=1):
        row_top = start_y + (index - 1) * row_h
        _draw_compact_category_row(draw, item, index, x, row_top, table_right, row_h, label_font, small_font, percent_font)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, format="PNG", optimize=True)
    return output_path


def _draw_vertical_gradient(draw: ImageDraw.ImageDraw, width: int, height: int) -> None:
    for y in range(height):
        t = y / max(1, height - 1)
        color = tuple(int(_BG_TOP[i] * (1 - t) + _BG_BOTTOM[i] * t) for i in range(3))
        draw.line((0, y, width, y), fill=color)


def _draw_card(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    label: str,
    value: int,
    color: tuple[int, int, int],
    label_font: ImageFont.ImageFont,
    value_font: ImageFont.ImageFont,
) -> None:
    draw.rounded_rectangle(box, radius=18, fill=_PANEL_2, outline=(45, 73, 99), width=1)
    x1, y1, _x2, _y2 = box
    draw.ellipse((x1 + 18, y1 + 20, x1 + 34, y1 + 36), fill=color)
    draw.text((x1 + 44, y1 + 16), label, font=label_font, fill=_MUTED)
    draw.text((x1 + 18, y1 + 42), str(value), font=value_font, fill=_TEXT)


def _draw_summary_strip(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    items: tuple[tuple[str, int, tuple[int, int, int]], ...],
    label_font: ImageFont.ImageFont,
    value_font: ImageFont.ImageFont,
) -> None:
    x1, y1, x2, y2 = box
    draw.rounded_rectangle(box, radius=16, fill=_PANEL_2, outline=(45, 73, 99), width=1)
    cell_w = (x2 - x1) / max(1, len(items))
    for index, (label, value, color) in enumerate(items):
        left = x1 + int(index * cell_w)
        if index:
            draw.line((left, y1 + 10, left, y2 - 10), fill=(45, 73, 99), width=1)
        dot_x = left + 24
        dot_y = y1 + 19
        draw.ellipse((dot_x, dot_y, dot_x + 14, dot_y + 14), fill=color)
        draw.text((dot_x + 22, y1 + 14), label, font=label_font, fill=_MUTED)
        value_text = str(value)
        value_w, value_h = _text_size(draw, value_text, value_font)
        draw.text((left + int(cell_w) - value_w - 24, y1 + (y2 - y1 - value_h) / 2 - 1), value_text, font=value_font, fill=_TEXT)


def _draw_compact_table_header(
    draw: ImageDraw.ImageDraw,
    left: int,
    top: int,
    right: int,
    height: int,
    font: ImageFont.ImageFont,
) -> None:
    draw.rounded_rectangle((left, top, right, top + height), radius=14, fill=(12, 26, 42), outline=(37, 66, 91), width=1)
    y = top + 12
    draw.text((left + 22, y), "#", font=font, fill=_MUTED)
    draw.text((left + 74, y), "Категория", font=font, fill=_MUTED)
    draw.text((left + 474, y), "Нагрузка", font=font, fill=_MUTED)
    for label, center in _count_columns(right):
        label_w = _text_size(draw, label, font)[0]
        draw.text((center - label_w / 2, y), label, font=font, fill=_MUTED)


def _draw_compact_category_row(
    draw: ImageDraw.ImageDraw,
    item: SnpCategorySummary,
    index: int,
    left: int,
    top: int,
    right: int,
    row_h: int,
    label_font: ImageFont.ImageFont,
    small_font: ImageFont.ImageFont,
    percent_font: ImageFont.ImageFont,
) -> None:
    bottom = top + row_h
    fill = (14, 29, 46) if index % 2 else (16, 33, 51)
    draw.rounded_rectangle((left, top + 5, right, bottom - 5), radius=10, fill=fill, outline=(30, 54, 77), width=1)

    row_mid = top + row_h // 2
    number = str(index)
    number_w, number_h = _text_size(draw, number, small_font)
    draw.text((left + 26 - number_w / 2, row_mid - number_h / 2 - 1), number, font=small_font, fill=_MUTED)

    label_left = left + 74
    bar_left = left + 470
    bar_right = right - 460
    label_max_width = max(280, bar_left - label_left - 32)
    label_font_for_row, label_lines = _fit_label_lines(draw, item.category, size=22, min_size=17, max_width=label_max_width)
    line_h = _text_size(draw, "Ag", label_font_for_row)[1] + 4
    label_y = row_mid - (len(label_lines) * line_h) / 2 - 1
    for offset, line in enumerate(label_lines):
        draw.text((label_left, label_y + offset * line_h), line, font=label_font_for_row, fill=_TEXT)

    percent = max(0, min(100, item.risk_percent))
    bar_top = row_mid - 8
    bar_bottom = row_mid + 8
    draw.rounded_rectangle((bar_left, bar_top, bar_right, bar_bottom), radius=8, fill=(42, 55, 72))
    fill_right = bar_left + int((bar_right - bar_left) * percent / 100)
    if fill_right > bar_left:
        draw.rounded_rectangle((bar_left, bar_top, fill_right, bar_bottom), radius=8, fill=_risk_color(percent))
    percent_text = f"{percent}%"
    draw.text((bar_right + 16, row_mid - 17), percent_text, font=percent_font, fill=_risk_color(percent))

    _draw_compact_counts(draw, item, right, row_mid, percent_font)


def _draw_compact_counts(
    draw: ImageDraw.ImageDraw,
    item: SnpCategorySummary,
    right: int,
    row_mid: int,
    font: ImageFont.ImageFont,
) -> None:
    values = (
        (item.ok, _GREEN, right - 328),
        (item.warn, _YELLOW, right - 230),
        (item.bad, _RED, right - 132),
        (item.missing, _GRAY, right - 44),
    )
    for value, color, center in values:
        value_text = str(value)
        value_w, value_h = _text_size(draw, value_text, font)
        draw.text((center - value_w / 2, row_mid - value_h / 2 - 2), value_text, font=font, fill=color)


def _count_columns(right: int) -> tuple[tuple[str, int], ...]:
    return (
        ("Норма", right - 328),
        ("Гетеро", right - 230),
        ("Гомо", right - 132),
        ("Н/д", right - 44),
    )


def _draw_table_header(
    draw: ImageDraw.ImageDraw,
    left: int,
    top: int,
    right: int,
    height: int,
    font: ImageFont.ImageFont,
) -> None:
    draw.rounded_rectangle((left, top, right, top + height), radius=18, fill=(12, 26, 42), outline=(37, 66, 91), width=1)
    y = top + 12
    draw.text((left + 72, y), "Категория", font=font, fill=_MUTED)
    draw.text((left + 430, y), "Процент", font=font, fill=_MUTED)
    for label, center in (("Гомо", right - 224), ("Гетеро", right - 134), ("Н/д", right - 52)):
        label_w = _text_size(draw, label, font)[0]
        draw.text((center - label_w / 2, y), label, font=font, fill=_MUTED)


def _draw_category_row(
    draw: ImageDraw.ImageDraw,
    item: SnpCategorySummary,
    index: int,
    left: int,
    top: int,
    right: int,
    row_h: int,
    label_font: ImageFont.ImageFont,
    small_font: ImageFont.ImageFont,
    percent_font: ImageFont.ImageFont,
) -> None:
    bottom = top + row_h
    draw.rounded_rectangle((left, top, right, bottom), radius=12, fill=(14, 29, 46), outline=(32, 57, 80), width=1)
    badge = f"{index}"
    row_mid = top + row_h // 2
    draw.rounded_rectangle((left + 18, row_mid - 17, left + 52, row_mid + 17), radius=10, fill=(31, 73, 107))
    _draw_centered_text(draw, badge, (left + 18, row_mid - 17, left + 52, row_mid + 17), small_font, _TEXT)

    label_left = left + 72
    bar_left = left + 360
    bar_right = right - 350
    label_max_width = max(240, bar_left - label_left - 26)
    label_font_for_row, label_lines = _fit_label_lines(draw, item.category, size=24, min_size=18, max_width=label_max_width)
    line_h = _text_size(draw, "Ag", label_font_for_row)[1] + 4
    label_y = row_mid - (len(label_lines) * line_h) / 2 - 1
    for offset, line in enumerate(label_lines):
        draw.text((label_left, label_y + offset * line_h), line, font=label_font_for_row, fill=_TEXT)

    percent = max(0, min(100, item.risk_percent))
    bar_top = row_mid - 7
    bar_bottom = bar_top + 14
    draw.rounded_rectangle((bar_left, bar_top, bar_right, bar_bottom), radius=7, fill=(42, 55, 72))
    fill_right = bar_left + int((bar_right - bar_left) * percent / 100)
    if fill_right > bar_left:
        draw.rounded_rectangle((bar_left, bar_top, fill_right, bar_bottom), radius=7, fill=_risk_color(percent))

    percent_text = f"{percent}%"
    draw.text((bar_right + 18, row_mid - 18), percent_text, font=percent_font, fill=_risk_color(percent))

    _draw_count_values(draw, item, right, row_mid, percent_font)


def _draw_count_values(
    draw: ImageDraw.ImageDraw,
    item: SnpCategorySummary,
    right: int,
    row_mid: int,
    font: ImageFont.ImageFont,
) -> None:
    values = (
        (item.bad, right - 224),
        (item.warn, right - 134),
        (item.missing, right - 52),
    )
    for value, center in values:
        value_text = str(value)
        value_w, value_h = _text_size(draw, value_text, font)
        draw.text((center - value_w / 2, row_mid - value_h / 2 - 2), value_text, font=font, fill=_TEXT)


def _risk_color(percent: int) -> tuple[int, int, int]:
    if percent >= 60:
        return _RED
    if percent >= 35:
        return _YELLOW
    return _GREEN


def _draw_centered_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    box: tuple[int, int, int, int],
    font: ImageFont.ImageFont,
    fill: tuple[int, int, int],
) -> None:
    text_w, text_h = _text_size(draw, text, font)
    x1, y1, x2, y2 = box
    draw.text((x1 + (x2 - x1 - text_w) / 2, y1 + (y2 - y1 - text_h) / 2 - 1), text, font=font, fill=fill)


def _fit_label_lines(
    draw: ImageDraw.ImageDraw,
    text: str,
    *,
    size: int,
    min_size: int,
    max_width: int,
) -> tuple[ImageFont.ImageFont, list[str]]:
    clean = " ".join(str(text).split())
    for candidate_size in range(size, min_size - 1, -1):
        font = _font(candidate_size, bold=True)
        lines = _wrap_lines(draw, clean, font, max_width, max_lines=2)
        if lines:
            return font, lines
    return _font(min_size, bold=True), [clean]


def _wrap_lines(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    max_width: int,
    *,
    max_lines: int,
) -> list[str]:
    if _text_size(draw, text, font)[0] <= max_width:
        return [text]
    words = text.split()
    if not words:
        return [text]
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = word if not current else f"{current} {word}"
        if _text_size(draw, candidate, font)[0] <= max_width:
            current = candidate
            continue
        if not current:
            return []
        lines.append(current)
        current = word
        if len(lines) >= max_lines:
            return []
    if current:
        lines.append(current)
    if len(lines) > max_lines or any(_text_size(draw, line, font)[0] > max_width for line in lines):
        return []
    return lines


def _text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> tuple[int, int]:
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0], box[3] - box[1]


def _font(size: int, *, bold: bool = False) -> ImageFont.ImageFont:
    candidates = [
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    return ImageFont.load_default()
