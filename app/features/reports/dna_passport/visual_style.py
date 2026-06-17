from __future__ import annotations

import re
import math
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .domain import DNAPassportData, DNAPassportInterestingSnpItem, DNAPassportTraitItem


WIDTH = 1440
HEIGHT = 1800
MARGIN = 72
CONTENT_WIDTH = WIDTH - MARGIN * 2

BG_TOP = (6, 10, 24)
BG_BOTTOM = (9, 42, 54)
PANEL = (18, 29, 47)
PANEL_SOFT = (24, 39, 62)
PANEL_DEEP = (10, 21, 38)
BORDER = (58, 82, 112)
BORDER_SOFT = (39, 58, 83)
TEXT = (242, 247, 252)
MUTED = (162, 178, 201)
FAINT = (94, 114, 139)
CYAN = (94, 211, 221)
BLUE = (124, 168, 255)
VIOLET = (160, 132, 255)
GOLD = (246, 193, 91)
MINT = (107, 220, 177)
ROSE = (227, 126, 166)
INK = (4, 9, 18)

TRAIT_LABELS_RU = {
    "pgs003835_height": "Рост",
    "pgs000336_chronotype": "Хронотип",
    "pgs001123_coffee": "Потребление кофе",
    "pgs001150_sleep_duration": "Длительность сна",
    "pgs001927_mean_hand_grip_strength": "Сила хвата",
    "pgs001075_walking_pace": "Темп ходьбы",
    "pgs001897_skin_pigmentation": "Пигментация кожи",
    "pgs002011_water_intake": "Потребление воды",
}

REGION_LABELS_RU = {
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

REGION_SUMMARY_RU = {
    "Кавказ": "кавказскому пространству",
    "Северный Кавказ": "северокавказскому пространству",
    "Западная Евразия": "западноевразийскому пространству",
    "Восточная Евразия": "восточноевразийскому пространству",
    "Центральная Азия": "центральноазиатскому пространству",
    "Южная Азия": "южноазиатскому пространству",
    "Ближний Восток": "ближневосточному пространству",
    "Степь": "степному пространству",
}

POPULATION_LABELS_RU = {
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


def create_page(data: DNAPassportData, *, page_title: str, page_number: int, total_pages: int) -> tuple[Image.Image, ImageDraw.ImageDraw, dict[str, ImageFont.ImageFont]]:
    image = Image.new("RGB", (WIDTH, HEIGHT), BG_TOP)
    draw = ImageDraw.Draw(image, "RGBA")
    fonts = load_fonts()
    draw_background(draw)
    draw_header(draw, fonts, data, page_title=page_title, page_number=page_number, total_pages=total_pages)
    draw_footer(draw, fonts, page_number=page_number, total_pages=total_pages)
    return image, draw, fonts


def save_page(image: Image.Image, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, format="PNG", optimize=True)
    return output_path


def draw_background(draw: ImageDraw.ImageDraw) -> None:
    for y in range(HEIGHT):
        t = y / max(1, HEIGHT - 1)
        color = tuple(int(BG_TOP[i] * (1 - t) + BG_BOTTOM[i] * t) for i in range(3))
        draw.line((0, y, WIDTH, y), fill=color)

    draw.polygon(((-180, 0), (268, 0), (92, HEIGHT), (-260, HEIGHT)), fill=(*CYAN, 14))
    draw.polygon(((1030, 0), (WIDTH, 0), (WIDTH + 110, HEIGHT), (1220, HEIGHT)), fill=(*VIOLET, 16))
    draw.polygon(((0, 1140), (WIDTH, 760), (WIDTH, 1068), (0, 1468)), fill=(*BLUE, 9))

    for x in range(-260, WIDTH + 260, 118):
        draw.line((x, 0, x + 520, HEIGHT), fill=(82, 137, 171, 16), width=1)
    for y in range(120, HEIGHT, 135):
        draw.line((0, y, WIDTH, y + 22), fill=(71, 113, 145, 12), width=1)
    for x in range(MARGIN, WIDTH - MARGIN + 1, 96):
        draw.line((x, 236, x, HEIGHT - 146), fill=(61, 94, 125, 8), width=1)

    draw.line((MARGIN, 214, WIDTH - MARGIN, 214), fill=(*BORDER, 90), width=1)
    draw.line((MARGIN, HEIGHT - 126, WIDTH - MARGIN, HEIGHT - 126), fill=(*BORDER, 80), width=1)

    _draw_helix_trace(draw)


def _draw_helix_trace(draw: ImageDraw.ImageDraw) -> None:
    left = WIDTH - 238
    top = 296
    height = 900
    prev_a: tuple[int, int] | None = None
    prev_b: tuple[int, int] | None = None
    for step in range(30):
        y = top + int(height * step / 29)
        phase = step / 29 * 6.3
        x_a = left + int(math.sin(phase) * 42)
        x_b = left + int(math.sin(phase + math.pi) * 42)
        alpha = 32 if step % 2 else 46
        draw.line((x_a, y, x_b, y), fill=(*CYAN, alpha), width=2)
        draw.ellipse((x_a - 4, y - 4, x_a + 4, y + 4), fill=(*MINT, alpha + 30))
        draw.ellipse((x_b - 4, y - 4, x_b + 4, y + 4), fill=(*ROSE, alpha + 20))
        if prev_a is not None and prev_b is not None:
            draw.line((prev_a[0], prev_a[1], x_a, y), fill=(*BLUE, 38), width=2)
            draw.line((prev_b[0], prev_b[1], x_b, y), fill=(*VIOLET, 35), width=2)
        prev_a = (x_a, y)
        prev_b = (x_b, y)


def draw_header(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, ImageFont.ImageFont],
    data: DNAPassportData,
    *,
    page_title: str,
    page_number: int,
    total_pages: int,
) -> None:
    sample = clean(getattr(getattr(data, "sample", None), "display_name", "") or "Образец")
    date = format_date(getattr(data, "generated_at", ""))
    draw.text((MARGIN, 54), "KBDNA / MY DNA", font=fonts["eyebrow"], fill=(*CYAN, 255))
    draw.text((MARGIN, 93), "DNA-паспорт", font=fonts["hero"], fill=(*TEXT, 255))
    draw.text((MARGIN, 166), f"{ellipsize(draw, sample, fonts['subtitle'], 640)} · {date}", font=fonts["subtitle"], fill=(*MUTED, 255))

    badge_text = f"{page_number:02d}/{total_pages:02d}"
    badge_w = int(draw.textlength(badge_text, font=fonts["badge"])) + 64
    right = WIDTH - MARGIN
    draw.rounded_rectangle((right - badge_w, 62, right, 122), radius=20, fill=(*PANEL_SOFT, 235), outline=(*BORDER, 190), width=1)
    draw.text((right - badge_w + 32, 78), badge_text, font=fonts["badge"], fill=(*TEXT, 255))
    draw.text((right, 154), ellipsize(draw, page_title, fonts["page_title"], 520), font=fonts["page_title"], fill=(*TEXT, 255), anchor="ra")


def draw_footer(draw: ImageDraw.ImageDraw, fonts: dict[str, ImageFont.ImageFont], *, page_number: int, total_pages: int) -> None:
    draw.text((MARGIN, HEIGHT - 94), "Визуальная версия. Подробности и ограничения доступны в текстовом отчёте.", font=fonts["small"], fill=(*MUTED, 255))
    draw.text((WIDTH - MARGIN, HEIGHT - 94), f"стр. {page_number}/{total_pages}", font=fonts["small_bold"], fill=(*MUTED, 255), anchor="ra")


def draw_card(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    *,
    radius: int = 28,
    fill: tuple[int, int, int] = PANEL,
    outline: tuple[int, int, int] = BORDER_SOFT,
    width: int = 1,
) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=(*fill, 238), outline=(*outline, 205), width=width)


def draw_section_label(draw: ImageDraw.ImageDraw, fonts: dict[str, ImageFont.ImageFont], x: int, y: int, title: str, accent: tuple[int, int, int] = CYAN) -> None:
    draw.rounded_rectangle((x, y + 9, x + 18, y + 35), radius=7, fill=(*accent, 255))
    draw.text((x + 34, y), title, font=fonts["section"], fill=(*TEXT, 255))


def draw_pill(draw: ImageDraw.ImageDraw, fonts: dict[str, ImageFont.ImageFont], x: int, y: int, text: str, *, accent: tuple[int, int, int] = CYAN) -> int:
    label = clean(text)
    width = int(draw.textlength(label, font=fonts["small_bold"])) + 48
    draw.rounded_rectangle((x, y, x + width, y + 44), radius=15, fill=(*PANEL_SOFT, 245), outline=(*accent, 120), width=1)
    draw.text((x + 24, y + 11), label, font=fonts["small_bold"], fill=(*TEXT, 255))
    return width


def draw_wrapped(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    x: int,
    y: int,
    max_width: int,
    *,
    max_lines: int,
    fill: tuple[int, int, int] = TEXT,
    line_gap: int = 8,
) -> int:
    lines = wrap(draw, text, font, max_width, max_lines=max_lines)
    line_h = text_size(draw, "Ag", font)[1] + line_gap
    for index, line in enumerate(lines):
        draw.text((x, y + index * line_h), line, font=font, fill=(*fill, 255))
    return y + len(lines) * line_h


def draw_progress(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    value: float,
    *,
    color: tuple[int, int, int] = CYAN,
    background: tuple[int, int, int] = (39, 54, 75),
) -> None:
    x1, y1, x2, y2 = box
    value = max(0.0, min(1.0, float(value)))
    draw.rounded_rectangle(box, radius=(y2 - y1) // 2, fill=(*background, 255))
    fill_w = max(y2 - y1, int((x2 - x1) * value))
    draw.rounded_rectangle((x1, y1, x1 + fill_w, y2), radius=(y2 - y1) // 2, fill=(*color, 255))


def wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int, *, max_lines: int) -> list[str]:
    words = clean(text).split()
    if not words:
        return [""]
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
    if len(lines) == max_lines:
        lines[-1] = ellipsize(draw, lines[-1], font, max_width)
    return lines


def ellipsize(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> str:
    value = clean(text)
    if draw.textlength(value, font=font) <= max_width:
        return value
    suffix = "..."
    while value and draw.textlength(value + suffix, font=font) > max_width:
        value = value[:-1].rstrip()
    return value + suffix if value else suffix


def text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> tuple[int, int]:
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0], box[3] - box[1]


def raw_metric(data: DNAPassportData) -> str:
    raw = data.raw
    if raw is None or raw.status != "ok":
        return "нет raw"
    return f"{format_int(raw.called_snps)} SNP"


def g25_metric(data: DNAPassportData) -> str:
    g25 = data.g25
    if g25 is None or g25.status != "ok":
        return "нет G25"
    return display_region(g25.region) or "G25 готов"


def traits_metric(data: DNAPassportData) -> str:
    traits = data.traits
    if traits is None or traits.status in {"unavailable", "error"}:
        return "нет raw"
    count = len(getattr(traits, "traits", ()) or ())
    return f"{count} признаков" if count else "н/д"


def snp_metric(data: DNAPassportData) -> str:
    items = dedupe_snp_items(tuple(getattr(getattr(data, "interesting_snps", None), "items", ()) or ()))
    return f"{len(items)} SNP" if items else "н/д"


def main_summary_lines(data: DNAPassportData) -> list[str]:
    lines: list[str] = []
    if data.raw and data.raw.status == "ok":
        lines.append("Файл подходит для анализа происхождения и базовых признаков.")
    else:
        lines.append("Для полной версии паспорта нужен autosomal raw.")
    if data.g25 and data.g25.status == "ok":
        region = display_region(data.g25.region)
        if region:
            phrase = REGION_SUMMARY_RU.get(region, f"пространству «{region}»")
            lines.append(f"По G25 образец относится к {phrase}.")
    else:
        lines.append("Краткое происхождение появится после добавления G25.")
    if data.lineage and data.lineage.status == "ok":
        paternal = lineage_status(data.lineage.y_count, kind="y")
        maternal = lineage_status(data.lineage.mtdna_count, kind="mtdna")
        if "огранич" in paternal.lower() or "недоступ" in paternal.lower() or "огранич" in maternal.lower() or "недоступ" in maternal.lower():
            lines.append("Прямые линии ограничены данными autosomal raw.")
        else:
            lines.append("Для прямых линий показана техническая готовность маркеров.")
    return lines[:3]


def strongest_trait(data: DNAPassportData) -> DNAPassportTraitItem | None:
    items = [item for item in getattr(getattr(data, "traits", None), "traits", ()) if item.percentile is not None]
    if not items:
        return None
    return max(items, key=lambda item: float(item.percentile or 0))


def trait_label(item: DNAPassportTraitItem) -> str:
    return TRAIT_LABELS_RU.get(item.trait_id, item.display_name or "Признак")


def trait_percent(item: DNAPassportTraitItem) -> int | None:
    if item.percentile is None:
        return None
    return max(0, min(100, int(round(float(item.percentile)))))


def confidence_stars(value: str) -> str:
    normalized = (value or "").strip().lower()
    if normalized == "high":
        return "★★★"
    if normalized == "medium":
        return "★★☆"
    return "★☆☆"


def lineage_status(count: int, *, kind: str) -> str:
    value = max(0, int(count or 0))
    if value <= 0:
        return "Недоступна по autosomal raw"
    threshold = 50 if kind == "y" else 200
    if value < threshold:
        return "Ограниченные данные"
    return "Маркеры обнаружены"


def dedupe_snp_items(items: tuple[DNAPassportInterestingSnpItem, ...]) -> tuple[DNAPassportInterestingSnpItem, ...]:
    result: list[DNAPassportInterestingSnpItem] = []
    seen: set[str] = set()
    for item in items:
        key = snp_topic_key(item)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return tuple(result)


def snp_topic_key(item: DNAPassportInterestingSnpItem) -> str:
    title = str(item.title or "").strip().lower()
    if ":" in title:
        title = title.split(":", 1)[0].strip()
    title = re.sub(r"\s+", " ", title)
    return title or str(item.rsid or "").strip().lower()


def snp_title(item: DNAPassportInterestingSnpItem) -> str:
    title = clean(item.title or item.rsid or "SNP")
    if ":" in title:
        return title.split(":", 1)[0].strip()
    return title


def display_region(value: str) -> str:
    normalized = " ".join(str(value or "").replace("_", " ").split())
    return REGION_LABELS_RU.get(value, REGION_LABELS_RU.get(normalized, normalized))


def display_population(value: str) -> str:
    raw = str(value or "").strip()
    base = re.split(r"[:;,]", raw, maxsplit=1)[0].strip()
    base = re.sub(r"_(?:average|modern|scaled)$", "", base, flags=re.I)
    label = POPULATION_LABELS_RU.get(base)
    if label:
        return label
    return " ".join(raw.replace("_", " ").split()) or raw


def format_date(value: str) -> str:
    try:
        return datetime.fromisoformat(str(value or "").replace("Z", "+00:00")).strftime("%d.%m.%Y")
    except Exception:
        return clean(value)


def format_int(value: int) -> str:
    return f"{int(value or 0):,}".replace(",", " ")


def format_distance(value: float | None) -> str:
    if value is None:
        return "н/д"
    return f"{float(value) * 100:.2f}".replace(".", ",")


def clean(value: object) -> str:
    return " ".join(str(value or "").strip().split())


def load_fonts() -> dict[str, ImageFont.ImageFont]:
    return {
        "eyebrow": font(25, bold=True),
        "hero": font(70, bold=True),
        "subtitle": font(30),
        "page_title": font(34, bold=True),
        "section": font(38, bold=True),
        "card_label": font(25, bold=True),
        "metric": font(48, bold=True),
        "metric_big": font(68, bold=True),
        "title": font(46, bold=True),
        "body": font(29),
        "body_bold": font(29, bold=True),
        "small": font(23),
        "small_bold": font(23, bold=True),
        "badge": font(25, bold=True),
    }


def font(size: int, *, bold: bool = False) -> ImageFont.ImageFont:
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
