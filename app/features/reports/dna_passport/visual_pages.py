from __future__ import annotations

import math
from pathlib import Path

from PIL import ImageDraw, ImageFont

from .domain import DNAPassportData, DNAPassportInterestingSnpItem, DNAPassportTraitItem
from .visual_style import (
    BLUE,
    BORDER,
    BORDER_SOFT,
    CONTENT_WIDTH,
    CYAN,
    FAINT,
    GOLD,
    HEIGHT,
    MARGIN,
    MINT,
    MUTED,
    PANEL,
    PANEL_DEEP,
    PANEL_SOFT,
    ROSE,
    TEXT,
    VIOLET,
    WIDTH,
    clean,
    create_page,
    dedupe_snp_items,
    display_population,
    display_region,
    draw_card,
    draw_pill,
    draw_progress,
    draw_section_label,
    draw_wrapped,
    ellipsize,
    format_distance,
    format_int,
    g25_metric,
    lineage_status,
    main_summary_lines,
    raw_metric,
    save_page,
    snp_metric,
    snp_title,
    strongest_trait,
    trait_label,
    trait_percent,
    traits_metric,
)


def render_overview_page(data: DNAPassportData, output_path: Path, *, page_number: int, total_pages: int) -> Path:
    image, draw, fonts = create_page(data, page_title="Обложка", page_number=page_number, total_pages=total_pages)
    _draw_overview_summary_cards(draw, fonts, data)
    _draw_overview_conclusion(draw, fonts, data)
    _draw_overview_key_cards(draw, fonts, data)
    return save_page(image, output_path)


def render_ancestry_page(data: DNAPassportData, output_path: Path, *, page_number: int, total_pages: int) -> Path:
    image, draw, fonts = create_page(data, page_title="Краткое происхождение", page_number=page_number, total_pages=total_pages)
    _draw_ancestry_region(draw, fonts, data)
    _draw_ancestry_references(draw, fonts, data)
    _draw_ancestry_scheme(draw, fonts, data)
    _draw_bottom_note(
        draw,
        fonts,
        "Близость к референсным популяциям показывает генетическое сходство и не определяет национальность или точные доли происхождения.",
    )
    return save_page(image, output_path)


def render_traits_page(data: DNAPassportData, output_path: Path, *, page_number: int, total_pages: int) -> Path:
    image, draw, fonts = create_page(data, page_title="Базовые признаки", page_number=page_number, total_pages=total_pages)
    _draw_traits_grid(draw, fonts, data)
    _draw_bottom_note(draw, fonts, "Проценты показывают положение результата относительно референсной панели.")
    return save_page(image, output_path)


def render_snps_page(data: DNAPassportData, output_path: Path, *, page_number: int, total_pages: int) -> Path:
    image, draw, fonts = create_page(data, page_title="Интересные SNP", page_number=page_number, total_pages=total_pages)
    _draw_snp_cards(draw, fonts, data)
    _draw_bottom_note(draw, fonts, "Отдельные SNP дают упрощённые генетические подсказки и не описывают признак полностью.")
    return save_page(image, output_path)


def render_lines_page(data: DNAPassportData, output_path: Path, *, page_number: int, total_pages: int) -> Path:
    image, draw, fonts = create_page(data, page_title="Прямые линии", page_number=page_number, total_pages=total_pages)
    _draw_lineage_cards(draw, fonts, data)
    _draw_next_steps(draw, fonts, data)
    _draw_bottom_note(draw, fonts, "Для точного определения прямых линий нужны специализированные Y-DNA и mtDNA-тесты.")
    return save_page(image, output_path)


def _draw_overview_summary_cards(draw: ImageDraw.ImageDraw, fonts: dict[str, ImageFont.ImageFont], data: DNAPassportData) -> None:
    y = 286
    gap = 26
    card_w = (CONTENT_WIDTH - gap) // 2
    card_h = 178
    cards = [
        ("RAW", raw_metric(data), "исходный файл", MINT),
        ("G25", g25_metric(data), "краткое происхождение", BLUE),
        ("TRAITS", traits_metric(data), "базовая панель", GOLD),
        ("SNP", snp_metric(data), "интересные маркеры", ROSE),
    ]
    for index, (label, value, sub, accent) in enumerate(cards):
        col = index % 2
        row = index // 2
        left = MARGIN + col * (card_w + gap)
        top = y + row * (card_h + gap)
        draw_card(draw, (left, top, left + card_w, top + card_h), radius=30, fill=PANEL_SOFT, outline=BORDER_SOFT)
        draw.rounded_rectangle((left + 28, top + 32, left + 50, top + 54), radius=7, fill=(*accent, 255))
        draw.text((left + 68, top + 25), label, font=fonts["card_label"], fill=(*MUTED, 255))
        draw.text((left + 28, top + 72), ellipsize(draw, value, fonts["metric"], card_w - 56), font=fonts["metric"], fill=(*TEXT, 255))
        draw.text((left + 30, top + 132), sub, font=fonts["small"], fill=(*MUTED, 255))


def _draw_overview_conclusion(draw: ImageDraw.ImageDraw, fonts: dict[str, ImageFont.ImageFont], data: DNAPassportData) -> None:
    top = 710
    draw_section_label(draw, fonts, MARGIN, top, "Краткий итог", accent=CYAN)
    box = (MARGIN, top + 72, WIDTH - MARGIN, top + 360)
    draw_card(draw, box, radius=34, fill=PANEL_DEEP, outline=BORDER)
    y = top + 112
    for line in main_summary_lines(data):
        draw.rounded_rectangle((MARGIN + 38, y + 9, MARGIN + 54, y + 25), radius=5, fill=(*CYAN, 245))
        y = draw_wrapped(draw, line, fonts["body"], MARGIN + 78, y, CONTENT_WIDTH - 124, max_lines=2, fill=TEXT, line_gap=10) + 18


def _draw_overview_key_cards(draw: ImageDraw.ImageDraw, fonts: dict[str, ImageFont.ImageFont], data: DNAPassportData) -> None:
    top = 1148
    draw_section_label(draw, fonts, MARGIN, top, "Главные ориентиры", accent=GOLD)
    gap = 24
    card_w = (CONTENT_WIDTH - gap * 2) // 3
    first_ref = "нет данных"
    if data.g25 and data.g25.status == "ok" and data.g25.top_modern:
        first_ref = display_population(data.g25.top_modern[0].name)
    trait = strongest_trait(data)
    trait_value = "нет данных"
    if trait is not None and trait.percentile is not None:
        trait_value = f"{trait_label(trait)} {trait_percent(trait)}%"
    lineage = "нет raw"
    if data.lineage and data.lineage.status == "ok":
        statuses = [lineage_status(data.lineage.y_count, kind="y"), lineage_status(data.lineage.mtdna_count, kind="mtdna")]
        lineage = "ограниченные данные" if any("Огранич" in item or "Недоступ" in item for item in statuses) else "маркеры есть"
    cards = [
        ("Ближайший референс", first_ref, BLUE),
        ("Самый выраженный признак", trait_value, GOLD),
        ("Прямые линии", lineage, MINT),
    ]
    for index, (label, value, accent) in enumerate(cards):
        left = MARGIN + index * (card_w + gap)
        y = top + 78
        draw_card(draw, (left, y, left + card_w, y + 250), radius=28, fill=PANEL_SOFT, outline=BORDER_SOFT)
        draw_pill(draw, fonts, left + 28, y + 28, label, accent=accent)
        draw_wrapped(draw, value, fonts["title"], left + 28, y + 98, card_w - 56, max_lines=3, fill=TEXT, line_gap=7)


def _draw_ancestry_region(draw: ImageDraw.ImageDraw, fonts: dict[str, ImageFont.ImageFont], data: DNAPassportData) -> None:
    top = 286
    draw_section_label(draw, fonts, MARGIN, top, "Генетическое пространство", accent=BLUE)
    region = "Недоступно"
    if data.g25 and data.g25.status == "ok":
        region = display_region(data.g25.region) or "Не определено"
    draw_card(draw, (MARGIN, top + 78, WIDTH - MARGIN, top + 320), radius=36, fill=PANEL_DEEP, outline=BORDER)
    draw.text((MARGIN + 52, top + 126), "итог по G25", font=fonts["card_label"], fill=(*MUTED, 255))
    draw.text((MARGIN + 52, top + 174), ellipsize(draw, region, fonts["metric_big"], CONTENT_WIDTH - 104), font=fonts["metric_big"], fill=(*TEXT, 255))


def _draw_ancestry_references(draw: ImageDraw.ImageDraw, fonts: dict[str, ImageFont.ImageFont], data: DNAPassportData) -> None:
    top = 680
    draw_section_label(draw, fonts, MARGIN, top, "Top-3 референсные популяции", accent=CYAN)
    refs = list(getattr(data.g25, "top_modern", ())[:3]) if data.g25 and data.g25.status == "ok" else []
    draw_card(draw, (MARGIN, top + 78, WIDTH - MARGIN, top + 386), radius=32, fill=PANEL, outline=BORDER_SOFT)
    if not refs:
        draw.text((MARGIN + 46, top + 186), "G25-профиль не найден", font=fonts["body_bold"], fill=(*MUTED, 255))
        return
    distances = [float(item.distance or 0) for item in refs]
    min_distance = min(distances, default=0.0)
    max_distance = max(distances, default=0.03) or 0.03
    span = max(max_distance - min_distance, 0.0001)
    for index, item in enumerate(refs, start=1):
        y = top + 118 + (index - 1) * 82
        distance = float(item.distance or 0)
        draw.text((MARGIN + 48, y), f"{index}", font=fonts["title"], fill=(*BLUE, 255))
        draw.text((MARGIN + 104, y + 5), ellipsize(draw, display_population(item.name), fonts["body_bold"], 440), font=fonts["body_bold"], fill=(*TEXT, 255))
        closeness = 0.55 + 0.45 * ((max_distance - distance) / span)
        draw_progress(draw, (MARGIN + 580, y + 20, WIDTH - MARGIN - 170, y + 40), closeness, color=BLUE)
        draw.text((WIDTH - MARGIN - 126, y + 2), format_distance(distance), font=fonts["body_bold"], fill=(*MUTED, 255))


def _draw_ancestry_scheme(draw: ImageDraw.ImageDraw, fonts: dict[str, ImageFont.ImageFont], data: DNAPassportData) -> None:
    top = 1128
    draw_section_label(draw, fonts, MARGIN, top, "Схема близости", accent=VIOLET)
    box = (MARGIN, top + 78, WIDTH - MARGIN, top + 430)
    draw_card(draw, box, radius=34, fill=PANEL_DEEP, outline=BORDER)
    x1, y1, x2, y2 = box
    cx = (x1 + x2) // 2
    cy = y1 + 174
    for radius in (52, 98, 144):
        draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), outline=(*BORDER, 105), width=2)
    draw.line((x1 + 68, cy, x2 - 68, cy), fill=(*BORDER, 75), width=1)
    draw.line((cx, y1 + 58, cx, y2 - 70), fill=(*BORDER, 75), width=1)

    refs = list(getattr(data.g25, "top_modern", ())[:3]) if data.g25 and data.g25.status == "ok" else []
    max_distance = max((float(item.distance or 0) for item in refs), default=0.03) or 0.03
    angles = [-30, 205, -100]
    for index, item in enumerate(refs):
        distance = float(item.distance or 0)
        radius = 64 + min(distance / max_distance, 1.0) * 70
        angle = math.radians(angles[index])
        px = int(cx + math.cos(angle) * radius)
        py = int(cy + math.sin(angle) * radius)
        draw.line((cx, cy, px, py), fill=(*BLUE, 115), width=3)
        draw.ellipse((px - 18, py - 18, px + 18, py + 18), fill=(*BLUE, 255), outline=(*TEXT, 190), width=2)
        label = display_population(item.name)
        if px < cx:
            draw.text((px - 26, py - 18), ellipsize(draw, label, fonts["small_bold"], 270), font=fonts["small_bold"], fill=(*TEXT, 255), anchor="ra")
        else:
            draw.text((px + 26, py - 18), ellipsize(draw, label, fonts["small_bold"], 270), font=fonts["small_bold"], fill=(*TEXT, 255))
    draw.ellipse((cx - 28, cy - 28, cx + 28, cy + 28), fill=(*GOLD, 255), outline=(*TEXT, 220), width=3)
    draw.text((cx, cy + 48), "образец", font=fonts["small_bold"], fill=(*TEXT, 255), anchor="ma")
    draw.text((x1 + 42, y2 - 56), "Иллюстрация основана на уже посчитанном ранжировании G25.", font=fonts["small"], fill=(*MUTED, 255))


def _draw_traits_grid(draw: ImageDraw.ImageDraw, fonts: dict[str, ImageFont.ImageFont], data: DNAPassportData) -> None:
    top = 286
    draw_section_label(draw, fonts, MARGIN, top, "8 базовых признаков", accent=GOLD)
    traits = list(getattr(getattr(data, "traits", None), "traits", ()) or ())
    failures = list(getattr(getattr(data, "traits", None), "failures", ()) or ())
    by_id = {item.trait_id: item for item in traits + failures}
    ordered_ids = [
        "pgs003835_height",
        "pgs000336_chronotype",
        "pgs001123_coffee",
        "pgs001150_sleep_duration",
        "pgs001927_mean_hand_grip_strength",
        "pgs001075_walking_pace",
        "pgs001897_skin_pigmentation",
        "pgs002011_water_intake",
    ]
    items = [by_id.get(trait_id) for trait_id in ordered_ids]
    gap_x = 24
    gap_y = 24
    card_w = (CONTENT_WIDTH - gap_x) // 2
    card_h = 268
    y0 = top + 78
    for index, item in enumerate(items):
        col = index % 2
        row = index // 2
        left = MARGIN + col * (card_w + gap_x)
        y = y0 + row * (card_h + gap_y)
        _draw_trait_card(draw, fonts, item, (left, y, left + card_w, y + card_h))


def _draw_trait_card(draw: ImageDraw.ImageDraw, fonts: dict[str, ImageFont.ImageFont], item: DNAPassportTraitItem | None, box: tuple[int, int, int, int]) -> None:
    x1, y1, x2, y2 = box
    draw_card(draw, box, radius=28, fill=PANEL_SOFT, outline=BORDER_SOFT)
    if item is None:
        draw.text((x1 + 34, y1 + 34), "Признак", font=fonts["card_label"], fill=(*MUTED, 255))
        draw.text((x1 + 34, y1 + 108), "н/д", font=fonts["metric_big"], fill=(*FAINT, 255))
        draw_progress(draw, (x1 + 34, y2 - 70, x2 - 34, y2 - 50), 0, color=FAINT)
        return
    label = trait_label(item)
    value = trait_percent(item)
    draw.text((x1 + 34, y1 + 30), ellipsize(draw, label, fonts["card_label"], x2 - x1 - 68), font=fonts["card_label"], fill=(*TEXT, 255))
    if value is None:
        draw.text((x1 + 34, y1 + 104), "н/д", font=fonts["metric_big"], fill=(*FAINT, 255))
        draw.text((x1 + 34, y1 + 184), "недостаточно данных", font=fonts["small"], fill=(*MUTED, 255))
        draw_progress(draw, (x1 + 34, y2 - 70, x2 - 34, y2 - 50), 0, color=FAINT)
        return
    draw.text((x1 + 34, y1 + 92), f"{value}%", font=fonts["metric_big"], fill=(*TEXT, 255))
    _draw_confidence_stars(draw, x2 - 148, y1 + 126, item.confidence)
    draw_progress(draw, (x1 + 34, y2 - 72, x2 - 34, y2 - 50), value / 100, color=CYAN)


def _draw_snp_cards(draw: ImageDraw.ImageDraw, fonts: dict[str, ImageFont.ImageFont], data: DNAPassportData) -> None:
    top = 286
    draw_section_label(draw, fonts, MARGIN, top, "Содержательные маркеры", accent=ROSE)
    items = list(dedupe_snp_items(tuple(getattr(getattr(data, "interesting_snps", None), "items", ()) or ()))[:5])
    if not items:
        draw_card(draw, (MARGIN, top + 78, WIDTH - MARGIN, top + 368), radius=34, fill=PANEL, outline=BORDER_SOFT)
        draw.text((MARGIN + 48, top + 194), "Готовых пользовательских трактовок не найдено", font=fonts["body_bold"], fill=(*MUTED, 255))
        return
    gap = 24
    card_w = (CONTENT_WIDTH - gap) // 2
    card_h = 286
    y0 = top + 78
    for index, item in enumerate(items):
        col = index % 2
        row = index // 2
        left = MARGIN + col * (card_w + gap)
        y = y0 + row * (card_h + gap)
        if index == 4:
            left = MARGIN + card_w // 2 + gap // 2
        _draw_snp_card(draw, fonts, item, (left, y, left + card_w, y + card_h))


def _draw_snp_card(draw: ImageDraw.ImageDraw, fonts: dict[str, ImageFont.ImageFont], item: DNAPassportInterestingSnpItem, box: tuple[int, int, int, int]) -> None:
    x1, y1, x2, y2 = box
    draw_card(draw, box, radius=28, fill=PANEL_SOFT, outline=BORDER_SOFT)
    draw.text((x1 + 32, y1 + 28), ellipsize(draw, snp_title(item), fonts["card_label"], x2 - x1 - 64), font=fonts["card_label"], fill=(*MUTED, 255))
    draw_wrapped(draw, clean(item.interpretation or "результат найден"), fonts["title"], x1 + 32, y1 + 78, x2 - x1 - 64, max_lines=2, fill=TEXT, line_gap=7)
    marker = " · ".join(part for part in (clean(item.genotype), clean(item.gene or item.rsid)) if part)
    draw_pill(draw, fonts, x1 + 32, y2 - 70, marker or clean(item.rsid), accent=ROSE)


def _draw_lineage_cards(draw: ImageDraw.ImageDraw, fonts: dict[str, ImageFont.ImageFont], data: DNAPassportData) -> None:
    top = 286
    draw_section_label(draw, fonts, MARGIN, top, "Техническая готовность", accent=MINT)
    lineage = data.lineage
    y_count = int(getattr(lineage, "y_count", 0) or 0) if lineage is not None and lineage.status == "ok" else 0
    mt_count = int(getattr(lineage, "mtdna_count", 0) or 0) if lineage is not None and lineage.status == "ok" else 0
    gap = 28
    card_w = (CONTENT_WIDTH - gap) // 2
    _draw_lineage_card(
        draw,
        fonts,
        (MARGIN, top + 82, MARGIN + card_w, top + 372),
        "Отцовская линия",
        lineage_status(y_count, kind="y"),
        f"Y-маркеры: {format_int(y_count)}",
        CYAN,
    )
    _draw_lineage_card(
        draw,
        fonts,
        (MARGIN + card_w + gap, top + 82, WIDTH - MARGIN, top + 372),
        "Материнская линия",
        lineage_status(mt_count, kind="mtdna"),
        f"mtDNA-маркеры: {format_int(mt_count)}",
        MINT,
    )


def _draw_lineage_card(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, ImageFont.ImageFont],
    box: tuple[int, int, int, int],
    title: str,
    status: str,
    detail: str,
    accent: tuple[int, int, int],
) -> None:
    x1, y1, x2, y2 = box
    draw_card(draw, box, radius=32, fill=PANEL_DEEP, outline=BORDER)
    draw.rounded_rectangle((x1 + 36, y1 + 40, x1 + 62, y1 + 66), radius=8, fill=(*accent, 255))
    draw.text((x1 + 82, y1 + 34), title, font=fonts["card_label"], fill=(*TEXT, 255))
    draw_wrapped(draw, status, fonts["title"], x1 + 36, y1 + 104, x2 - x1 - 72, max_lines=2, fill=TEXT)
    draw.text((x1 + 36, y2 - 62), detail, font=fonts["small"], fill=(*MUTED, 255))


def _draw_next_steps(draw: ImageDraw.ImageDraw, fonts: dict[str, ImageFont.ImageFont], data: DNAPassportData) -> None:
    top = 780
    draw_section_label(draw, fonts, MARGIN, top, "Что исследовать дальше", accent=GOLD)
    region = display_region(data.g25.region) if data.g25 and data.g25.status == "ok" else ""
    first = "Региональное исследование Кавказа" if region in {"Кавказ", "Северный Кавказ"} else "Региональное исследование происхождения"
    steps = [
        (first, "уточнить положение внутри ближайшего пространства"),
        ("Расширенный портрет происхождения", "собрать более глубокую карту совпадений"),
        ("Полный портрет признаков", "развернуть базовую панель в отдельный отчёт"),
    ]
    for index, (title, subtitle) in enumerate(steps, start=1):
        y = top + 82 + (index - 1) * 202
        draw_card(draw, (MARGIN, y, WIDTH - MARGIN, y + 166), radius=28, fill=PANEL_SOFT, outline=BORDER_SOFT)
        draw.ellipse((MARGIN + 42, y + 45, MARGIN + 100, y + 103), fill=(*GOLD, 255))
        draw.text((MARGIN + 71, y + 57), str(index), font=fonts["body_bold"], fill=(*PANEL_DEEP, 255), anchor="ma")
        draw.text((MARGIN + 132, y + 38), title, font=fonts["body_bold"], fill=(*TEXT, 255))
        draw.text((MARGIN + 132, y + 88), subtitle, font=fonts["body"], fill=(*MUTED, 255))


def _draw_bottom_note(draw: ImageDraw.ImageDraw, fonts: dict[str, ImageFont.ImageFont], text: str) -> None:
    box = (MARGIN, HEIGHT - 260, WIDTH - MARGIN, HEIGHT - 156)
    draw_card(draw, box, radius=24, fill=PANEL_DEEP, outline=BORDER_SOFT)
    draw_wrapped(draw, text, fonts["small"], MARGIN + 36, HEIGHT - 226, CONTENT_WIDTH - 72, max_lines=2, fill=MUTED)


def _draw_confidence_stars(draw: ImageDraw.ImageDraw, x: int, y: int, confidence: str) -> None:
    filled = {"high": 3, "medium": 2}.get(clean(confidence).lower(), 1)
    for index in range(3):
        cx = x + index * 42
        points = _star_points(cx, y, outer=15, inner=7)
        if index < filled:
            draw.polygon(points, fill=(*GOLD, 255))
        else:
            draw.polygon(points, outline=(*GOLD, 210), fill=(0, 0, 0, 0))


def _star_points(cx: int, cy: int, *, outer: int, inner: int) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for step in range(10):
        radius = outer if step % 2 == 0 else inner
        angle = math.radians(-90 + step * 36)
        points.append((cx + math.cos(angle) * radius, cy + math.sin(angle) * radius))
    return points
