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
    lineage_status,
    main_summary_lines,
    save_page,
    snp_display_result,
    snp_title,
    trait_label,
    trait_percent,
    visual_snp_items,
)


def render_overview_page(data: DNAPassportData, output_path: Path, *, page_number: int, total_pages: int) -> Path:
    image, draw, fonts = create_page(data, page_title="Обложка", page_number=page_number, total_pages=total_pages)
    _draw_overview_source_data(draw, fonts, data)
    _draw_overview_conclusion(draw, fonts, data)
    _draw_overview_lineage(draw, fonts, data)
    return save_page(image, output_path)


def render_ancestry_page(data: DNAPassportData, output_path: Path, *, page_number: int, total_pages: int) -> Path:
    image, draw, fonts = create_page(data, page_title="Краткое происхождение", page_number=page_number, total_pages=total_pages)
    _draw_ancestry_topline(draw, fonts, data)
    _draw_ancestry_coordinate_space(draw, fonts, data)
    _draw_bottom_note(
        draw,
        fonts,
        "Близость к референсным популяциям показывает генетическое сходство и не определяет национальность или точные доли происхождения.",
    )
    return save_page(image, output_path)


def render_traits_page(data: DNAPassportData, output_path: Path, *, page_number: int, total_pages: int) -> Path:
    image, draw, fonts = create_page(data, page_title="Базовые признаки", page_number=page_number, total_pages=total_pages)
    _draw_traits_grid(draw, fonts, data)
    _draw_bottom_note(draw, fonts, "Проценты показывают положение относительно референсной панели. Звёзды отражают качество расчёта по доступным данным.")
    return save_page(image, output_path)


def render_snps_page(data: DNAPassportData, output_path: Path, *, page_number: int, total_pages: int) -> Path:
    image, draw, fonts = create_page(data, page_title="Интересные SNP", page_number=page_number, total_pages=total_pages)
    _draw_snp_cards(draw, fonts, data)
    _draw_bottom_note(draw, fonts, "Отдельные SNP дают упрощённые генетические подсказки и не описывают признак полностью.")
    return save_page(image, output_path)


def render_lines_page(data: DNAPassportData, output_path: Path, *, page_number: int, total_pages: int) -> Path:
    image, draw, fonts = create_page(data, page_title="Следующие шаги", page_number=page_number, total_pages=total_pages)
    _draw_lineage_cards(draw, fonts, data)
    _draw_next_steps(draw, fonts, data)
    _draw_bottom_note(draw, fonts, "Для точного определения прямых линий нужны специализированные Y-DNA и mtDNA-тесты.")
    return save_page(image, output_path)


def _draw_overview_source_data(draw: ImageDraw.ImageDraw, fonts: dict[str, ImageFont.ImageFont], data: DNAPassportData) -> None:
    top = 286
    draw_section_label(draw, fonts, MARGIN, top, "Исходные данные", accent=MINT)
    box = (MARGIN, top + 74, WIDTH - MARGIN, top + 540)
    draw_card(draw, box, radius=34, fill=PANEL, outline=BORDER)
    x1, y1, x2, y2 = box
    raw = data.raw
    if raw is None or raw.status != "ok":
        draw.text((x1 + 44, y1 + 50), "autosomal raw", font=fonts["title"], fill=(*TEXT, 255))
        draw.text((x1 + 44, y1 + 130), "Исходный файл не прикреплён", font=fonts["body_bold"], fill=(*MUTED, 255))
        draw_wrapped(draw, "Добавьте raw-файл, чтобы заполнить сведения об образце.", fonts["body"], x1 + 44, y1 + 190, x2 - x1 - 88, max_lines=2, fill=MUTED)
        return

    draw.text((x1 + 44, y1 + 38), "ТИП ДАННЫХ", font=fonts["small_bold"], fill=(*MUTED, 255))
    draw.text((x1 + 44, y1 + 78), "autosomal raw", font=fonts["title"], fill=(*TEXT, 255))
    provider = clean(raw.provider_hint)
    if provider:
        draw_pill(draw, fonts, x1 + 44, y1 + 144, provider, accent=MINT)

    draw.text((x2 - 44, y1 + 38), "ПРОЧИТАНО", font=fonts["small_bold"], fill=(*MUTED, 255), anchor="ra")
    draw.text((x2 - 44, y1 + 82), f"{format_int(raw.called_snps)} SNP", font=fonts["metric_big"], fill=(*TEXT, 255), anchor="ra")
    draw.line((x1 + 44, y1 + 208, x2 - 44, y1 + 208), fill=(*BORDER, 180), width=2)

    quality = _raw_quality_label(raw.call_rate)
    draw.text((x1 + 44, y1 + 238), "Качество чтения", font=fonts["card_label"], fill=(*MUTED, 255))
    draw.text((x1 + 360, y1 + 228), quality, font=fonts["metric"], fill=(*TEXT, 255))
    quality_value = float(raw.call_rate or 0)
    if quality_value > 1:
        quality_value /= 100
    draw_progress(draw, (x1 + 540, y1 + 253, x2 - 44, y1 + 275), quality_value, color=MINT, background=(37, 55, 78))

    metrics = (
        ("Аутосомы", raw.autosomal_count, CYAN),
        ("X", raw.x_count, BLUE),
        ("Y", raw.y_count, VIOLET),
        ("mtDNA", raw.mtdna_count, ROSE),
    )
    gap = 16
    metric_w = (x2 - x1 - 88 - gap * 3) // 4
    metric_top = y1 + 316
    for index, (label, value, accent) in enumerate(metrics):
        left = x1 + 44 + index * (metric_w + gap)
        draw_card(draw, (left, metric_top, left + metric_w, y2 - 34), radius=22, fill=PANEL_SOFT, outline=BORDER_SOFT)
        draw.rounded_rectangle((left + 22, metric_top + 24, left + 38, metric_top + 40), radius=5, fill=(*accent, 255))
        draw.text((left + 52, metric_top + 17), label, font=fonts["small_bold"], fill=(*MUTED, 255))
        draw.text((left + 22, metric_top + 56), format_int(value), font=fonts["metric"], fill=(*TEXT, 255))


def _raw_quality_label(call_rate: float | None) -> str:
    if call_rate is None:
        return "н/д"
    value = float(call_rate)
    if value <= 1:
        value *= 100
    return f"{max(0.0, min(100.0, value)):.1f}%".replace(".", ",")


def _draw_overview_conclusion(draw: ImageDraw.ImageDraw, fonts: dict[str, ImageFont.ImageFont], data: DNAPassportData) -> None:
    top = 892
    draw_section_label(draw, fonts, MARGIN, top, "Краткий итог", accent=CYAN)
    box = (MARGIN, top + 72, WIDTH - MARGIN, top + 300)
    draw_card(draw, box, radius=34, fill=PANEL_DEEP, outline=BORDER)
    y = top + 112
    for line in main_summary_lines(data)[:2]:
        draw.rounded_rectangle((MARGIN + 38, y + 9, MARGIN + 54, y + 25), radius=5, fill=(*CYAN, 245))
        y = draw_wrapped(draw, line, fonts["body"], MARGIN + 78, y, CONTENT_WIDTH - 124, max_lines=2, fill=TEXT, line_gap=10) + 18


def _draw_overview_lineage(draw: ImageDraw.ImageDraw, fonts: dict[str, ImageFont.ImageFont], data: DNAPassportData) -> None:
    top = 1260
    draw_section_label(draw, fonts, MARGIN, top, "Прямые линии", accent=VIOLET)
    lineage = data.lineage
    y_count = int(getattr(lineage, "y_count", 0) or 0) if lineage is not None and lineage.status == "ok" else 0
    mt_count = int(getattr(lineage, "mtdna_count", 0) or 0) if lineage is not None and lineage.status == "ok" else 0
    gap = 24
    card_w = (CONTENT_WIDTH - gap) // 2
    items = (
        ("Отцовская линия", lineage_status(y_count, kind="y"), CYAN),
        ("Материнская линия", lineage_status(mt_count, kind="mtdna"), MINT),
    )
    for index, (title, status, accent) in enumerate(items):
        left = MARGIN + index * (card_w + gap)
        y1 = top + 76
        draw_card(draw, (left, y1, left + card_w, y1 + 190), radius=28, fill=PANEL_SOFT, outline=BORDER)
        draw.rounded_rectangle((left + 30, y1 + 30, left + 50, y1 + 50), radius=6, fill=(*accent, 255))
        draw.text((left + 68, y1 + 22), title, font=fonts["card_label"], fill=(*MUTED, 255))
        draw_wrapped(draw, status, fonts["list_title"], left + 30, y1 + 90, card_w - 60, max_lines=2, fill=TEXT)


def _draw_ancestry_topline(draw: ImageDraw.ImageDraw, fonts: dict[str, ImageFont.ImageFont], data: DNAPassportData) -> None:
    top = 286
    draw_section_label(draw, fonts, MARGIN, top, "Генетическое пространство", accent=BLUE)
    region = "Недоступно"
    if data.g25 and data.g25.status == "ok":
        region = display_region(data.g25.region) or "Не определено"
    refs = list(getattr(data.g25, "top_modern", ())[:3]) if data.g25 and data.g25.status == "ok" else []
    left_w = 492
    gap = 28
    card_top = top + 78
    draw_card(draw, (MARGIN, card_top, MARGIN + left_w, card_top + 242), radius=34, fill=PANEL_DEEP, outline=BORDER)
    draw.text((MARGIN + 42, card_top + 42), "итог по G25", font=fonts["card_label"], fill=(*MUTED, 255))
    draw.text((MARGIN + 42, card_top + 96), ellipsize(draw, region, fonts["metric_big"], left_w - 84), font=fonts["metric_big"], fill=(*TEXT, 255))
    draw_pill(draw, fonts, MARGIN + 42, card_top + 174, "расчёт по полному G25-вектору", accent=BLUE)

    right_x = MARGIN + left_w + gap
    draw_card(draw, (right_x, card_top, WIDTH - MARGIN, card_top + 242), radius=34, fill=PANEL, outline=BORDER_SOFT)
    draw.text((right_x + 38, card_top + 36), "Top-3 референсы", font=fonts["card_label"], fill=(*TEXT, 255))
    if not refs:
        draw.text((right_x + 38, card_top + 120), "G25-профиль не найден", font=fonts["body_bold"], fill=(*MUTED, 255))
        return
    for index, item in enumerate(refs, start=1):
        y = card_top + 84 + (index - 1) * 46
        distance = float(item.distance or 0)
        draw.text((right_x + 40, y), f"{index}", font=fonts["body_bold"], fill=(*BLUE, 255))
        draw.text((right_x + 92, y), ellipsize(draw, display_population(item.name), fonts["body_bold"], 378), font=fonts["body_bold"], fill=(*TEXT, 255))
        draw.text((WIDTH - MARGIN - 36, y), format_distance(distance), font=fonts["body_bold"], fill=(*MUTED, 255), anchor="ra")


def _draw_ancestry_coordinate_space(draw: ImageDraw.ImageDraw, fonts: dict[str, ImageFont.ImageFont], data: DNAPassportData) -> None:
    top = 666
    draw_section_label(draw, fonts, MARGIN, top, "Схема генетической близости", accent=VIOLET)
    box = (MARGIN, top + 78, WIDTH - MARGIN, top + 752)
    draw_card(draw, box, radius=36, fill=PANEL_DEEP, outline=BORDER)
    x1, y1, x2, y2 = box
    refs = list(getattr(data.g25, "top_modern", ())[:3]) if data.g25 and data.g25.status == "ok" else []
    plot = (x1 + 78, y1 + 72, x2 - 78, y2 - 112)
    _draw_distance_scheme(draw, fonts, plot, refs)
    draw_wrapped(
        draw,
        "Схема отображает относительные G25-дистанции. Ранжирование рассчитано по полному G25-вектору.",
        fonts["small"],
        x1 + 42,
        y2 - 62,
        x2 - x1 - 84,
        max_lines=2,
        fill=MUTED,
    )


def _draw_distance_scheme(draw: ImageDraw.ImageDraw, fonts: dict[str, ImageFont.ImageFont], plot: tuple[int, int, int, int], refs) -> None:
    x1, y1, x2, y2 = plot
    draw.rounded_rectangle(plot, radius=26, fill=(8, 18, 34, 120), outline=(*BORDER_SOFT, 170), width=1)
    cx = x1 + (x2 - x1) // 2
    cy = y1 + (y2 - y1) // 2
    for radius in (120, 220, 320):
        draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), outline=(*BLUE, 34), width=2)
    draw.line((x1 + 42, cy, x2 - 42, cy), fill=(*CYAN, 52), width=1)
    draw.line((cx, y1 + 42, cx, y2 - 42), fill=(*CYAN, 52), width=1)

    draw.ellipse((cx - 50, cy - 50, cx + 50, cy + 50), outline=(*GOLD, 62), width=7)
    draw.ellipse((cx - 30, cy - 30, cx + 30, cy + 30), fill=(*GOLD, 255), outline=(*TEXT, 230), width=3)
    draw.text((cx, cy + 50), "образец", font=fonts["body_bold"], fill=(*TEXT, 255), anchor="ma")

    if not refs:
        draw.text((cx, cy - 118), "G25-профиль не найден", font=fonts["body_bold"], fill=(*MUTED, 255), anchor="ma")
        return

    layout = _radial_reference_layout(plot, refs)
    for index, (item, sx, sy, lx, ly, anchor) in enumerate(layout):
        accent = (BLUE, CYAN, VIOLET)[index % 3]
        draw.line((cx, cy, sx, sy), fill=(*accent, 118), width=3)
        draw.ellipse((sx - 18, sy - 18, sx + 18, sy + 18), fill=(*accent, 255), outline=(*TEXT, 120), width=2)
        draw.line((sx, sy, lx, ly + 14), fill=(*accent, 95), width=2)
        label = f"{display_population(item.name)} · {format_distance(float(item.distance or 0))}"
        label_w = min(420, int(draw.textlength(label, font=fonts["small_bold"])) + 70)
        label_h = 44
        if anchor == "ra":
            lx = max(x1 + 34 + label_w, min(x2 - 34, lx))
            label_box = (lx - label_w, ly, lx, ly + label_h)
            text_x = lx - 17
        else:
            lx = max(x1 + 34, min(x2 - 34 - label_w, lx))
            label_box = (lx, ly, lx + label_w, ly + label_h)
            text_x = lx + 17
        draw.rounded_rectangle(label_box, radius=15, fill=(*PANEL_SOFT, 235), outline=(*accent, 110), width=1)
        draw.text((text_x, ly + 11), ellipsize(draw, label, fonts["small_bold"], label_w - 34), font=fonts["small_bold"], fill=(*TEXT, 255), anchor=anchor)


def _radial_reference_layout(plot: tuple[int, int, int, int], refs) -> list[tuple[object, int, int, int, int, str]]:
    x1, y1, x2, y2 = plot
    cx = x1 + (x2 - x1) // 2
    cy = y1 + (y2 - y1) // 2
    distances = [float(getattr(item, "distance", 0) or 0) for item in refs]
    min_d = min(distances) if distances else 0.0
    max_d = max(distances) if distances else min_d
    span = max(0.0001, max_d - min_d)
    angles = (-82, 34, 154)
    label_offsets = ((-214, -92, "ra"), (56, 18, "la"), (-56, 20, "ra"))
    layout: list[tuple[object, int, int, int, int, str]] = []
    for index, item in enumerate(refs[:3]):
        distance = float(getattr(item, "distance", 0) or 0)
        normalized = (distance - min_d) / span if max_d > min_d else index / max(1, len(refs))
        radius = 150 + int(normalized * 210)
        angle = math.radians(angles[index % len(angles)])
        sx = cx + int(math.cos(angle) * radius)
        sy = cy + int(math.sin(angle) * radius)
        dx, dy, anchor = label_offsets[index % len(label_offsets)]
        lx = max(x1 + 34, min(x2 - 34, sx + dx))
        ly = max(y1 + 34, min(y2 - 80, sy + dy))
        layout.append((item, sx, sy, lx, ly, anchor))
    return layout


def _draw_coordinate_grid(draw: ImageDraw.ImageDraw, plot: tuple[int, int, int, int]) -> None:
    x1, y1, x2, y2 = plot
    draw.rounded_rectangle(plot, radius=26, fill=(8, 18, 34, 120), outline=(*BORDER_SOFT, 170), width=1)
    for step in range(1, 6):
        x = x1 + int((x2 - x1) * step / 6)
        y = y1 + int((y2 - y1) * step / 6)
        draw.line((x, y1 + 12, x, y2 - 12), fill=(*BORDER, 50), width=1)
        draw.line((x1 + 12, y, x2 - 12, y), fill=(*BORDER, 50), width=1)
    cx = x1 + (x2 - x1) // 2
    cy = y1 + (y2 - y1) // 2
    draw.line((x1 + 20, cy, x2 - 20, cy), fill=(*CYAN, 74), width=2)
    draw.line((cx, y1 + 20, cx, y2 - 20), fill=(*CYAN, 74), width=2)
    for radius in (96, 182, 268):
        draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), outline=(*BLUE, 34), width=2)


def _plot_point(plot: tuple[int, int, int, int], x: float, y: float) -> tuple[int, int]:
    x1, y1, x2, y2 = plot
    scale = 0.78
    sx = x1 + (x2 - x1) * (0.5 + max(-1.0, min(1.0, x * scale)) / 2)
    sy = y1 + (y2 - y1) * (0.5 - max(-1.0, min(1.0, y * scale)) / 2)
    return int(sx), int(sy)


def _reference_coordinate(index: int, distance: float) -> tuple[float, float]:
    distance = max(0.008, min(0.055, distance or 0.026))
    rank_radius = 0.18 + distance * 8.4
    angle = math.radians((24, 154, -112, 78, -48)[index % 5])
    return math.cos(angle) * rank_radius, math.sin(angle) * rank_radius


def _reference_cloud_points(refs) -> list[tuple[str, float, float, float, tuple[int, int, int]]]:
    points: list[tuple[str, float, float, float, tuple[int, int, int]]] = []
    for index, item in enumerate(refs):
        distance = float(item.distance or 0)
        x, y = _reference_coordinate(index, distance)
        points.append((display_population(item.name), x, y, distance, (BLUE, CYAN, VIOLET)[index % 3]))
    cloud_angles = [12, 54, 96, 138, 188, 230, 276, 318, 342, 72, 250, 164]
    for index, angle_value in enumerate(cloud_angles):
        radius = 0.46 + (index % 4) * 0.095
        angle = math.radians(angle_value)
        color = (MINT, BLUE, VIOLET, ROSE)[index % 4]
        points.append(("", math.cos(angle) * radius, math.sin(angle) * radius, 0.05, color))
    return points


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
    gap_y = 16
    card_w = CONTENT_WIDTH
    card_h = 126
    y0 = top + 78
    for index, item in enumerate(items):
        left = MARGIN
        y = y0 + index * (card_h + gap_y)
        _draw_trait_card(draw, fonts, item, (left, y, left + card_w, y + card_h))


def _draw_trait_card(draw: ImageDraw.ImageDraw, fonts: dict[str, ImageFont.ImageFont], item: DNAPassportTraitItem | None, box: tuple[int, int, int, int]) -> None:
    x1, y1, x2, y2 = box
    accent = _trait_accent(item)
    draw_card(draw, box, radius=24, fill=PANEL_SOFT, outline=BORDER)
    draw.rounded_rectangle((x1, y1, x1 + 11, y2), radius=8, fill=(*accent, 235))
    if item is None:
        draw.text((x1 + 34, y1 + 22), "Признак", font=fonts["list_title"], fill=(*MUTED, 255))
        draw.text((x2 - 44, y1 + 36), "н/д", font=fonts["metric"], fill=(*FAINT, 255), anchor="ra")
        draw_progress(draw, (x1 + 34, y1 + 84, x2 - 270, y1 + 104), 0, color=FAINT)
        return
    label = trait_label(item)
    value = trait_percent(item)
    draw.text((x1 + 34, y1 + 20), ellipsize(draw, label, fonts["list_title"], 720), font=fonts["list_title"], fill=(*TEXT, 255))
    if value is None:
        draw.text((x1 + 34, y1 + 76), "недостаточно данных", font=fonts["small"], fill=(*MUTED, 255))
        draw.text((x2 - 44, y1 + 36), "н/д", font=fonts["metric"], fill=(*FAINT, 255), anchor="ra")
        draw_progress(draw, (x1 + 360, y1 + 84, x2 - 270, y1 + 104), 0, color=FAINT)
        return
    draw_progress(draw, (x1 + 34, y1 + 84, x2 - 270, y1 + 104), value / 100, color=accent, background=(42, 61, 86))
    draw.text((x2 - 42, y1 + 25), f"{value}%", font=fonts["metric"], fill=(*TEXT, 255), anchor="ra")
    _draw_confidence_stars(draw, x2 - 166, y1 + 96, item.confidence)


def _trait_accent(item: DNAPassportTraitItem | None) -> tuple[int, int, int]:
    palette = (CYAN, VIOLET, GOLD, BLUE, MINT, ROSE, (126, 202, 148), (239, 159, 105))
    if item is None:
        return FAINT
    ordered_ids = (
        "pgs003835_height",
        "pgs000336_chronotype",
        "pgs001123_coffee",
        "pgs001150_sleep_duration",
        "pgs001927_mean_hand_grip_strength",
        "pgs001075_walking_pace",
        "pgs001897_skin_pigmentation",
        "pgs002011_water_intake",
    )
    try:
        return palette[ordered_ids.index(item.trait_id)]
    except ValueError:
        return CYAN


def _draw_snp_cards(draw: ImageDraw.ImageDraw, fonts: dict[str, ImageFont.ImageFont], data: DNAPassportData) -> None:
    top = 286
    draw_section_label(draw, fonts, MARGIN, top, "Выбранные маркеры", accent=ROSE)
    items = list(visual_snp_items(tuple(getattr(getattr(data, "interesting_snps", None), "items", ()) or ()))[:5])
    if not items:
        draw_card(draw, (MARGIN, top + 78, WIDTH - MARGIN, top + 368), radius=34, fill=PANEL, outline=BORDER_SOFT)
        draw.text((MARGIN + 48, top + 194), "Готовых пользовательских трактовок не найдено", font=fonts["body_bold"], fill=(*MUTED, 255))
        return
    gap = 24
    card_w = CONTENT_WIDTH
    y0 = top + 78
    available = HEIGHT - 356 - y0
    card_h = int(min(230, max(166, (available - gap * (len(items) - 1)) / len(items))))
    for index, item in enumerate(items):
        left = MARGIN
        y = y0 + index * (card_h + gap)
        _draw_snp_card(draw, fonts, item, (left, y, left + card_w, y + card_h))


def _draw_snp_card(draw: ImageDraw.ImageDraw, fonts: dict[str, ImageFont.ImageFont], item: DNAPassportInterestingSnpItem, box: tuple[int, int, int, int]) -> None:
    x1, y1, x2, y2 = box
    draw_card(draw, box, radius=26, fill=PANEL_SOFT, outline=BORDER)
    draw.rounded_rectangle((x1, y1, x1 + 11, y2), radius=8, fill=(*ROSE, 235))
    draw.text((x1 + 34, y1 + 22), ellipsize(draw, snp_title(item), fonts["list_title"], 760), font=fonts["list_title"], fill=(*TEXT, 255))
    draw.text((x2 - 34, y1 + 30), clean(item.category or "маркер"), font=fonts["small"], fill=(*MUTED, 255), anchor="ra")
    draw.line((x1 + 34, y1 + 70, x2 - 34, y1 + 70), fill=(*BORDER_SOFT, 190), width=1)
    draw_wrapped(draw, snp_display_result(item), fonts["result"], x1 + 34, y1 + 92, x2 - x1 - 390, max_lines=2, fill=TEXT, line_gap=7)
    marker = " · ".join(part for part in (clean(item.genotype), clean(item.gene)) if part)
    if marker:
        marker = ellipsize(draw, marker, fonts["small_bold"], 250)
        pill_w = int(draw.textlength(marker, font=fonts["small_bold"])) + 48
        draw_pill(draw, fonts, x2 - pill_w - 34, y1 + 96, marker, accent=ROSE)


def _draw_lineage_cards(draw: ImageDraw.ImageDraw, fonts: dict[str, ImageFont.ImageFont], data: DNAPassportData) -> None:
    top = 286
    draw_section_label(draw, fonts, MARGIN, top, "Прямые линии", accent=MINT)
    lineage = data.lineage
    y_count = int(getattr(lineage, "y_count", 0) or 0) if lineage is not None and lineage.status == "ok" else 0
    mt_count = int(getattr(lineage, "mtdna_count", 0) or 0) if lineage is not None and lineage.status == "ok" else 0
    gap = 28
    card_w = (CONTENT_WIDTH - gap) // 2
    _draw_lineage_card(
        draw,
        fonts,
        (MARGIN, top + 82, MARGIN + card_w, top + 282),
        "Отцовская линия",
        lineage_status(y_count, kind="y"),
        f"Y-маркеры в raw: {format_int(y_count)}",
        CYAN,
    )
    _draw_lineage_card(
        draw,
        fonts,
        (MARGIN + card_w + gap, top + 82, WIDTH - MARGIN, top + 282),
        "Материнская линия",
        lineage_status(mt_count, kind="mtdna"),
        f"mtDNA-маркеры в raw: {format_int(mt_count)}",
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
    draw_wrapped(draw, status, fonts["list_title"], x1 + 36, y1 + 92, x2 - x1 - 72, max_lines=2, fill=TEXT)
    draw.text((x1 + 36, y2 - 44), detail, font=fonts["small"], fill=(*MUTED, 255))


def _draw_next_steps(draw: ImageDraw.ImageDraw, fonts: dict[str, ImageFont.ImageFont], data: DNAPassportData) -> None:
    top = 650
    draw_section_label(draw, fonts, MARGIN, top, "Что можно изучить дальше", accent=GOLD)
    region = display_region(data.g25.region) if data.g25 and data.g25.status == "ok" else ""
    first = "Региональное исследование Кавказа" if region in {"Кавказ", "Северный Кавказ"} else "Региональное исследование происхождения"
    steps = [
        (first, "Локальные современные и древние референсы"),
        ("Портрет происхождения", "Современные связи и модели происхождения"),
        ("Древние корни", "Ближайшие древние образцы и эпохи"),
        ("Портрет признаков", "Расширенный набор генетических особенностей"),
        ("Семейное сравнение", "Родство и общие сегменты между образцами"),
        ("Отцовская и материнская линии", "Отдельное исследование Y-DNA и mtDNA"),
    ]
    gap_x = 22
    gap_y = 20
    card_w = (CONTENT_WIDTH - gap_x) // 2
    card_h = 220
    for index, (title, subtitle) in enumerate(steps, start=1):
        col = (index - 1) % 2
        row = (index - 1) // 2
        left = MARGIN + col * (card_w + gap_x)
        y = top + 82 + row * (card_h + gap_y)
        draw_card(draw, (left, y, left + card_w, y + card_h), radius=28, fill=PANEL_SOFT, outline=BORDER)
        draw.ellipse((left + 30, y + 30, left + 80, y + 80), fill=(*GOLD, 255))
        draw.text((left + 55, y + 40), str(index), font=fonts["small_bold"], fill=(*PANEL_DEEP, 255), anchor="ma")
        draw_wrapped(draw, title, fonts["list_title"], left + 98, y + 24, card_w - 126, max_lines=2, fill=TEXT, line_gap=6)
        draw_wrapped(draw, subtitle, fonts["small"], left + 30, y + 132, card_w - 60, max_lines=2, fill=MUTED, line_gap=6)


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
