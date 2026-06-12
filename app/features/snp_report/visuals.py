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
    top_limit: int = 7,
) -> Path:
    categories = [
        SnpCategorySummary(**item)
        for item in record.payload.get("categories", [])
        if isinstance(item, dict)
    ][:top_limit]
    summary = record.summary
    width = 1080
    row_h = 112
    height = 330 + max(1, len(categories)) * row_h + 120

    image = Image.new("RGB", (width, height), _BG_TOP)
    draw = ImageDraw.Draw(image)
    _draw_vertical_gradient(draw, width, height)

    margin = 48
    draw.rounded_rectangle((margin, 36, width - margin, height - 36), radius=34, fill=_PANEL, outline=_BORDER, width=2)

    title_font = _font(44, bold=True)
    subtitle_font = _font(24)
    card_label_font = _font(20)
    card_value_font = _font(34, bold=True)
    label_font = _font(27, bold=True)
    small_font = _font(21)
    percent_font = _font(32, bold=True)

    x = margin + 38
    y = 70
    draw.text((x, y), "SNP Lab", font=subtitle_font, fill=_BLUE)
    draw.text((x, y + 34), "Нагрузка по категориям", font=title_font, fill=_TEXT)

    found = max(0, summary.total_rules - summary.missing)
    subtitle = f"Sample: {summary.sample_name}   •   найдено {found} из {summary.total_rules} SNP"
    draw.text((x, y + 92), subtitle, font=subtitle_font, fill=_MUTED)

    card_y = 202
    card_gap = 16
    card_w = (width - 2 * margin - 76 - 3 * card_gap) // 4
    cards = (
        ("Норма", summary.ok, _GREEN),
        ("Гетеро", summary.warn, _YELLOW),
        ("Гомо", summary.bad, _RED),
        ("Нет данных", summary.missing, _GRAY),
    )
    for index, (label, value, color) in enumerate(cards):
        left = x + index * (card_w + card_gap)
        _draw_card(draw, (left, card_y, left + card_w, card_y + 86), label, value, color, card_label_font, card_value_font)

    start_y = 318
    if not categories:
        draw.text((x, start_y + 26), "Категории не найдены.", font=label_font, fill=_TEXT)
    for index, item in enumerate(categories, start=1):
        row_top = start_y + (index - 1) * row_h
        _draw_category_row(draw, item, index, x, row_top, width - margin - 38, label_font, small_font, percent_font)

    footer_y = height - 118
    draw.rounded_rectangle((x, footer_y, width - margin - 38, footer_y + 58), radius=18, fill=(12, 26, 42), outline=(41, 75, 103), width=1)
    footer = "Нагрузка = гомо + ½ гетеро среди найденных SNP. Длиннее полоса — выше нагрузка."
    draw.text((x + 22, footer_y + 17), footer, font=small_font, fill=_MUTED)

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


def _draw_category_row(
    draw: ImageDraw.ImageDraw,
    item: SnpCategorySummary,
    index: int,
    left: int,
    top: int,
    right: int,
    label_font: ImageFont.ImageFont,
    small_font: ImageFont.ImageFont,
    percent_font: ImageFont.ImageFont,
) -> None:
    draw.rounded_rectangle((left, top, right, top + 92), radius=20, fill=(14, 29, 46), outline=(37, 66, 91), width=1)
    badge = f"{index}"
    draw.rounded_rectangle((left + 18, top + 22, left + 54, top + 58), radius=12, fill=(31, 73, 107))
    _draw_centered_text(draw, badge, (left + 18, top + 22, left + 54, top + 58), small_font, _TEXT)

    label = _truncate_to_width(draw, item.category, label_font, 390)
    draw.text((left + 72, top + 18), label, font=label_font, fill=_TEXT)
    detail = f"Гомо {item.bad}   •   Гетеро {item.warn}   •   Нет данных {item.missing}"
    draw.text((left + 72, top + 54), detail, font=small_font, fill=_MUTED)

    percent = max(0, min(100, item.risk_percent))
    percent_text = f"{percent}%"
    percent_w = _text_size(draw, percent_text, percent_font)[0]
    draw.text((right - 36 - percent_w, top + 18), percent_text, font=percent_font, fill=_risk_color(percent))

    bar_left = right - 330
    bar_top = top + 61
    bar_right = right - 36
    bar_bottom = bar_top + 16
    draw.rounded_rectangle((bar_left, bar_top, bar_right, bar_bottom), radius=8, fill=(42, 55, 72))
    fill_right = bar_left + int((bar_right - bar_left) * percent / 100)
    if fill_right > bar_left:
        draw.rounded_rectangle((bar_left, bar_top, fill_right, bar_bottom), radius=8, fill=_risk_color(percent))


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


def _truncate_to_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> str:
    clean = " ".join(str(text).split())
    if _text_size(draw, clean, font)[0] <= max_width:
        return clean
    suffix = "…"
    while clean and _text_size(draw, clean + suffix, font)[0] > max_width:
        clean = clean[:-1].rstrip()
    return (clean or str(text)[:1]) + suffix


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
