from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .domain import DNAPassportData, DNAPassportInterestingSnpItem, DNAPassportTraitItem


WIDTH = 1440
HEIGHT = 1860

_BG_TOP = (10, 16, 28)
_BG_BOTTOM = (19, 42, 55)
_PANEL = (18, 28, 43)
_PANEL_SOFT = (24, 39, 58)
_BORDER = (55, 76, 101)
_TEXT = (242, 247, 252)
_MUTED = (161, 177, 198)
_FAINT = (91, 109, 132)
_CYAN = (93, 205, 215)
_GREEN = (104, 219, 161)
_GOLD = (255, 194, 88)
_PINK = (228, 117, 158)
_BLUE = (126, 170, 255)
_RED = (242, 103, 108)

_TRAIT_LABELS_RU = {
    "pgs003835_height": "Рост",
    "pgs000336_chronotype": "Хронотип",
    "pgs001123_coffee": "Кофе",
    "pgs001150_sleep_duration": "Сон",
    "pgs001927_mean_hand_grip_strength": "Сила хвата",
    "pgs001075_walking_pace": "Темп ходьбы",
    "pgs001897_skin_pigmentation": "Пигментация",
    "pgs002011_water_intake": "Вода",
}

_REGION_LABELS_RU = {
    "Caucasus": "Кавказ",
    "Caucasus_North": "Северный Кавказ",
    "North Caucasus": "Северный Кавказ",
    "West Eurasia": "Западная Евразия",
    "WestEurasia": "Западная Евразия",
    "Europe": "Европа",
    "East Eurasia": "Восточная Евразия",
    "Central Asia": "Центральная Азия",
    "South Asia": "Южная Азия",
    "Near East": "Ближний Восток",
    "Middle East": "Ближний Восток",
    "Steppe": "Степь",
}

_POPULATION_LABELS_RU = {
    "Abazin": "Абазины",
    "Abkhazian": "Абхазы",
    "Adygei": "Адыгейцы",
    "Armenian": "Армяне",
    "Avar": "Аварцы",
    "Balkar": "Балкарцы",
    "Chechen": "Чеченцы",
    "Cherkes": "Черкесы",
    "Circassian": "Черкесы",
    "Dargin": "Даргинцы",
    "Georgian": "Грузины",
    "Ingush": "Ингуши",
    "Kabardin": "Кабардинцы",
    "Karachay": "Карачаевцы",
    "Kumyk": "Кумыки",
    "Lak": "Лакцы",
    "Lezgin": "Лезгины",
    "Nogai": "Ногайцы",
    "Ossetian": "Осетины",
    "Russian": "Русские",
    "Tabasaran": "Табасаранцы",
    "Turkish": "Турки",
}


def render_dna_passport_visual_png(data: DNAPassportData, output_path: Path) -> Path:
    image = Image.new("RGB", (WIDTH, HEIGHT), _BG_TOP)
    draw = ImageDraw.Draw(image, "RGBA")
    _draw_background(draw)
    fonts = _fonts()

    margin = 52
    _panel(draw, (30, 30, WIDTH - 30, HEIGHT - 30), radius=34, fill=_PANEL, outline=_BORDER)
    _draw_header(draw, fonts, data, margin, 64)
    _draw_snapshot_cards(draw, fonts, data, margin, 244, WIDTH - margin * 2)
    _draw_g25_panel(draw, fonts, data, margin, 510, WIDTH - margin * 2)
    _draw_traits_panel(draw, fonts, data, margin, 840, WIDTH - margin * 2)
    _draw_snp_panel(draw, fonts, data, margin, 1198, WIDTH - margin * 2)
    _draw_lineage_panel(draw, fonts, data, margin, 1518, WIDTH - margin * 2)
    _draw_footer(draw, fonts, margin, HEIGHT - 104)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, format="PNG", optimize=True)
    return output_path


def _draw_background(draw: ImageDraw.ImageDraw) -> None:
    for y in range(HEIGHT):
        t = y / max(1, HEIGHT - 1)
        color = tuple(int(_BG_TOP[i] * (1 - t) + _BG_BOTTOM[i] * t) for i in range(3))
        draw.line((0, y, WIDTH, y), fill=color)
    draw.ellipse((-240, -260, 420, 380), fill=(*_CYAN, 28))
    draw.ellipse((1030, 90, 1680, 760), fill=(*_PINK, 24))
    draw.ellipse((930, 1220, 1590, 1960), fill=(*_GOLD, 16))


def _draw_header(draw: ImageDraw.ImageDraw, fonts: dict[str, ImageFont.ImageFont], data: DNAPassportData, x: int, y: int) -> None:
    sample = _clean(getattr(data.sample, "display_name", "") or "Образец")
    draw.text((x, y), "KBDNA / MY DNA", font=fonts["eyebrow"], fill=(*_CYAN, 255))
    draw.text((x, y + 38), "DNA-паспорт", font=fonts["hero"], fill=(*_TEXT, 255))
    draw.text((x, y + 108), _ellipsize(draw, sample, fonts["subtitle"], 680), font=fonts["subtitle"], fill=(*_MUTED, 255))

    date = _format_date(data.generated_at)
    pill_w = int(draw.textlength(date, font=fonts["body_bold"])) + 54
    pill = (WIDTH - x - pill_w, y + 52, WIDTH - x, y + 106)
    draw.rounded_rectangle(pill, radius=16, fill=(*_PANEL_SOFT, 255), outline=(*_BORDER, 220), width=1)
    draw.text((pill[0] + 27, pill[1] + 14), date, font=fonts["body_bold"], fill=(*_TEXT, 255))


def _draw_snapshot_cards(draw: ImageDraw.ImageDraw, fonts: dict[str, ImageFont.ImageFont], data: DNAPassportData, x: int, y: int, width: int) -> None:
    gap = 18
    card_w = (width - gap * 3) // 4
    cards = (
        ("RAW", _raw_value(data), _GREEN if _is_ok(data.raw) else _FAINT),
        ("G25", _g25_value(data), _BLUE if _is_ok(data.g25) else _FAINT),
        ("TRAITS", _traits_value(data), _GOLD if _has_traits(data) else _FAINT),
        ("SNP", _snp_value(data), _PINK if _has_snps(data) else _FAINT),
    )
    for index, (label, value, color) in enumerate(cards):
        left = x + index * (card_w + gap)
        box = (left, y, left + card_w, y + 146)
        _panel(draw, box, radius=22, fill=_PANEL_SOFT, outline=(48, 66, 90))
        draw.rounded_rectangle((left + 24, y + 28, left + 40, y + 44), radius=5, fill=(*color, 255))
        draw.text((left + 54, y + 21), label, font=fonts["label"], fill=(*_MUTED, 255))
        _wrapped_text(draw, value, fonts["metric"], left + 24, y + 66, card_w - 48, 2, fill=_TEXT)


def _draw_g25_panel(draw: ImageDraw.ImageDraw, fonts: dict[str, ImageFont.ImageFont], data: DNAPassportData, x: int, y: int, width: int) -> None:
    _section(draw, fonts, x, y, width, "Краткое происхождение")
    top = y + 76
    _panel(draw, (x, top, x + width, top + 232), radius=24, fill=(16, 30, 47), outline=(50, 74, 103))

    region = "Недоступно"
    if _is_ok(data.g25):
        region = _display_region(data.g25.region) or "Не определено"
    draw.text((x + 28, top + 28), "Генетическое пространство", font=fonts["label"], fill=(*_MUTED, 255))
    draw.text((x + 28, top + 62), _ellipsize(draw, region, fonts["title"], 510), font=fonts["title"], fill=(*_TEXT, 255))

    refs = list(getattr(data.g25, "top_modern", ())[:3]) if _is_ok(data.g25) else []
    right_x = x + 650
    draw.text((right_x, top + 28), "Ближайшие референсы", font=fonts["label"], fill=(*_MUTED, 255))
    if not refs:
        draw.text((right_x, top + 76), "G25-профиль не найден", font=fonts["body"], fill=(*_FAINT, 255))
        return
    max_distance = max((float(item.distance or 0.0) for item in refs), default=0.03) or 0.03
    for index, item in enumerate(refs, start=1):
        row_y = top + 70 + (index - 1) * 46
        name = _display_population(item.name)
        distance = float(item.distance or 0.0)
        draw.text((right_x, row_y), f"{index}. {_ellipsize(draw, name, fonts['body_bold'], 300)}", font=fonts["body_bold"], fill=(*_TEXT, 255))
        bar_x = right_x + 390
        bar_w = 245
        draw.rounded_rectangle((bar_x, row_y + 8, bar_x + bar_w, row_y + 24), radius=8, fill=(45, 58, 78, 255))
        fill_w = max(12, int(bar_w * (1 - min(distance / max_distance, 1.0))))
        draw.rounded_rectangle((bar_x, row_y + 8, bar_x + fill_w, row_y + 24), radius=8, fill=(*_BLUE, 255))
        draw.text((bar_x + bar_w + 20, row_y - 1), _format_distance(distance), font=fonts["small_bold"], fill=(*_MUTED, 255))


def _draw_traits_panel(draw: ImageDraw.ImageDraw, fonts: dict[str, ImageFont.ImageFont], data: DNAPassportData, x: int, y: int, width: int) -> None:
    _section(draw, fonts, x, y, width, "Базовые признаки")
    top = y + 76
    traits = list(getattr(data.traits, "traits", ())[:6]) if data.traits is not None else []
    if not traits:
        _empty_panel(draw, fonts, (x, top, x + width, top + 236), "Недоступны без исходного DNA-файла")
        return
    col_gap = 22
    row_gap = 18
    card_w = (width - col_gap) // 2
    card_h = 72
    for index, item in enumerate(traits):
        col = index % 2
        row = index // 2
        left = x + col * (card_w + col_gap)
        card_top = top + row * (card_h + row_gap)
        _trait_row(draw, fonts, item, (left, card_top, left + card_w, card_top + card_h))


def _draw_snp_panel(draw: ImageDraw.ImageDraw, fonts: dict[str, ImageFont.ImageFont], data: DNAPassportData, x: int, y: int, width: int) -> None:
    _section(draw, fonts, x, y, width, "Интересные SNP")
    top = y + 76
    items = _dedupe_snp_items(tuple(getattr(data.interesting_snps, "items", ()) or ()))[:5]
    if not items:
        _empty_panel(draw, fonts, (x, top, x + width, top + 206), "Готовых пользовательских трактовок не найдено")
        return
    _panel(draw, (x, top, x + width, top + 250), radius=24, fill=(17, 31, 45), outline=(50, 74, 103))
    cols = 2
    chip_w = (width - 76) // cols
    for index, item in enumerate(items):
        col = index % cols
        row = index // cols
        left = x + 28 + col * (chip_w + 20)
        chip_top = top + 28 + row * 68
        _panel(draw, (left, chip_top, left + chip_w, chip_top + 52), radius=16, fill=(25, 42, 60), outline=(54, 79, 106))
        title = _snp_title(item)
        draw.text((left + 18, chip_top + 14), _ellipsize(draw, f"{title}: {item.genotype}", fonts["body_bold"], chip_w - 36), font=fonts["body_bold"], fill=(*_TEXT, 255))


def _draw_lineage_panel(draw: ImageDraw.ImageDraw, fonts: dict[str, ImageFont.ImageFont], data: DNAPassportData, x: int, y: int, width: int) -> None:
    _section(draw, fonts, x, y, width, "Прямые линии")
    top = y + 76
    lineage = data.lineage
    y_value = int(getattr(lineage, "y_count", 0) or 0) if lineage is not None and lineage.status == "ok" else 0
    mt_value = int(getattr(lineage, "mtdna_count", 0) or 0) if lineage is not None and lineage.status == "ok" else 0
    left_w = (width - 22) // 2
    _lineage_card(draw, fonts, (x, top, x + left_w, top + 132), "Отцовская линия", _lineage_status(y_value, y=True), _CYAN if y_value else _FAINT)
    _lineage_card(draw, fonts, (x + left_w + 22, top, x + width, top + 132), "Материнская линия", _lineage_status(mt_value, y=False), _GREEN if mt_value else _FAINT)


def _draw_footer(draw: ImageDraw.ImageDraw, fonts: dict[str, ImageFont.ImageFont], x: int, y: int) -> None:
    draw.line((x, y - 24, WIDTH - x, y - 24), fill=(*_BORDER, 190), width=1)
    draw.text((x, y), "Визуальное превью. Подробности и ограничения — в текстовом отчёте.", font=fonts["small"], fill=(*_MUTED, 255))


def _trait_row(draw: ImageDraw.ImageDraw, fonts: dict[str, ImageFont.ImageFont], item: DNAPassportTraitItem, box: tuple[int, int, int, int]) -> None:
    x1, y1, x2, y2 = box
    _panel(draw, box, radius=18, fill=(24, 39, 57), outline=(47, 67, 91))
    label = _trait_label(item)
    percentile = item.percentile
    draw.text((x1 + 20, y1 + 14), _ellipsize(draw, label, fonts["body_bold"], 240), font=fonts["body_bold"], fill=(*_TEXT, 255))
    if percentile is None:
        draw.text((x2 - 170, y1 + 16), "н/д", font=fonts["body_bold"], fill=(*_FAINT, 255))
        return
    value = max(0, min(100, int(round(float(percentile)))))
    bar_x = x1 + 250
    bar_w = max(90, x2 - bar_x - 92)
    draw.rounded_rectangle((bar_x, y1 + 29, bar_x + bar_w, y1 + 43), radius=7, fill=(48, 60, 78, 255))
    draw.rounded_rectangle((bar_x, y1 + 29, bar_x + int(bar_w * value / 100), y1 + 43), radius=7, fill=(*_trait_color(value), 255))
    draw.text((x2 - 70, y1 + 16), f"{value}%", font=fonts["body_bold"], fill=(*_TEXT, 255))


def _lineage_card(draw: ImageDraw.ImageDraw, fonts: dict[str, ImageFont.ImageFont], box: tuple[int, int, int, int], label: str, value: str, color: tuple[int, int, int]) -> None:
    x1, y1, x2, y2 = box
    _panel(draw, box, radius=22, fill=_PANEL_SOFT, outline=(48, 68, 92))
    draw.rounded_rectangle((x1 + 26, y1 + 30, x1 + 44, y1 + 48), radius=6, fill=(*color, 255))
    draw.text((x1 + 62, y1 + 24), label, font=fonts["body_bold"], fill=(*_TEXT, 255))
    draw.text((x1 + 62, y1 + 66), _ellipsize(draw, value, fonts["body"], x2 - x1 - 96), font=fonts["body"], fill=(*_MUTED, 255))


def _section(draw: ImageDraw.ImageDraw, fonts: dict[str, ImageFont.ImageFont], x: int, y: int, width: int, title: str) -> None:
    draw.text((x, y), title, font=fonts["section"], fill=(*_TEXT, 255))
    draw.line((x, y + 48, x + width, y + 48), fill=(*_BORDER, 190), width=1)


def _empty_panel(draw: ImageDraw.ImageDraw, fonts: dict[str, ImageFont.ImageFont], box: tuple[int, int, int, int], text: str) -> None:
    _panel(draw, box, radius=24, fill=(17, 31, 45), outline=(50, 74, 103))
    x1, y1, x2, y2 = box
    tw, th = _text_size(draw, text, fonts["body"])
    draw.text((x1 + (x2 - x1 - tw) / 2, y1 + (y2 - y1 - th) / 2), text, font=fonts["body"], fill=(*_MUTED, 255))


def _panel(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], *, radius: int, fill: tuple[int, int, int], outline: tuple[int, int, int]) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=(*fill, 244), outline=(*outline, 210), width=1)


def _wrapped_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, x: int, y: int, max_width: int, max_lines: int, *, fill: tuple[int, int, int]) -> None:
    lines = _wrap(draw, text, font, max_width, max_lines)
    line_h = _text_size(draw, "Ag", font)[1] + 7
    for index, line in enumerate(lines):
        draw.text((x, y + index * line_h), line, font=font, fill=(*fill, 255))


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int, max_lines: int) -> list[str]:
    words = _clean(text).split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if not current or draw.textlength(candidate, font=font) <= max_width:
            current = candidate
            continue
        lines.append(current)
        current = word
        if len(lines) >= max_lines:
            break
    if current and len(lines) < max_lines:
        lines.append(current)
    if len(lines) == max_lines and words:
        lines[-1] = _ellipsize(draw, lines[-1], font, max_width)
    return lines or [""]


def _raw_value(data: DNAPassportData) -> str:
    raw = data.raw
    if not _is_ok(raw):
        return "не прикреплён"
    return f"{_format_int(raw.called_snps)} SNP"


def _g25_value(data: DNAPassportData) -> str:
    if not _is_ok(data.g25):
        return "нет профиля"
    return _display_region(data.g25.region) or "G25 готов"


def _traits_value(data: DNAPassportData) -> str:
    traits = data.traits
    if traits is None or traits.status in {"unavailable", "error"}:
        return "нет raw"
    count = len(getattr(traits, "traits", ()) or ())
    return f"{count} признаков" if count else "н/д"


def _snp_value(data: DNAPassportData) -> str:
    snps = data.interesting_snps
    items = _dedupe_snp_items(tuple(getattr(snps, "items", ()) or ())) if snps is not None else ()
    return f"{len(items)} маркеров" if items else "н/д"


def _has_traits(data: DNAPassportData) -> bool:
    return bool(data.traits is not None and getattr(data.traits, "traits", ()))


def _has_snps(data: DNAPassportData) -> bool:
    return bool(data.interesting_snps is not None and getattr(data.interesting_snps, "items", ()))


def _is_ok(value: object) -> bool:
    return value is not None and getattr(value, "status", "") == "ok"


def _trait_label(item: DNAPassportTraitItem) -> str:
    return _TRAIT_LABELS_RU.get(item.trait_id, item.display_name or "Признак")


def _display_region(value: str) -> str:
    normalized = " ".join(str(value or "").replace("_", " ").split())
    return _REGION_LABELS_RU.get(value, _REGION_LABELS_RU.get(normalized, normalized))


def _display_population(value: str) -> str:
    raw = str(value or "").strip()
    base = re.split(r"[:;,]", raw, maxsplit=1)[0].strip()
    base = re.sub(r"_(?:average|modern|scaled)$", "", base, flags=re.I)
    label = _POPULATION_LABELS_RU.get(base)
    if label:
        return label
    return " ".join(raw.replace("_", " ").split()) or raw


def _snp_title(item: DNAPassportInterestingSnpItem) -> str:
    title = str(item.title or item.rsid or "SNP").strip()
    if ":" in title:
        return title.split(":", 1)[0].strip()
    return title


def _dedupe_snp_items(items: tuple[DNAPassportInterestingSnpItem, ...]) -> tuple[DNAPassportInterestingSnpItem, ...]:
    result: list[DNAPassportInterestingSnpItem] = []
    seen: set[str] = set()
    for item in items:
        key = _snp_title(item).lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return tuple(result)


def _lineage_status(count: int, *, y: bool) -> str:
    if count <= 0:
        return "нет данных в raw"
    threshold = 50 if y else 200
    if count < threshold:
        return "ограниченные данные"
    return "данные обнаружены"


def _trait_color(value: int) -> tuple[int, int, int]:
    if value >= 70:
        return _GREEN
    if value >= 35:
        return _GOLD
    return _PINK


def _format_date(value: str) -> str:
    try:
        return datetime.fromisoformat(str(value or "").replace("Z", "+00:00")).strftime("%d.%m.%Y")
    except Exception:
        return _clean(value)


def _format_int(value: int) -> str:
    return f"{int(value or 0):,}".replace(",", " ")


def _format_distance(value: float) -> str:
    return f"{float(value) * 100:.2f}".replace(".", ",")


def _clean(value: object) -> str:
    return " ".join(str(value or "").strip().split())


def _ellipsize(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> str:
    text = _clean(text)
    if draw.textlength(text, font=font) <= max_width:
        return text
    suffix = "..."
    while text and draw.textlength(text + suffix, font=font) > max_width:
        text = text[:-1].rstrip()
    return text + suffix if text else suffix


def _text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> tuple[int, int]:
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0], box[3] - box[1]


def _fonts() -> dict[str, ImageFont.ImageFont]:
    return {
        "eyebrow": _font(25, bold=True),
        "hero": _font(72, bold=True),
        "subtitle": _font(32),
        "title": _font(42, bold=True),
        "section": _font(34, bold=True),
        "label": _font(21, bold=True),
        "metric": _font(31, bold=True),
        "body": _font(26),
        "body_bold": _font(26, bold=True),
        "small": _font(21),
        "small_bold": _font(21, bold=True),
    }


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
