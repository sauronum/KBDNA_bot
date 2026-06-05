from __future__ import annotations

from pathlib import Path
from typing import Tuple

from PIL import Image, ImageDraw, ImageFont

from .texts import localize_confidence, localize_trait_name


Color = Tuple[int, int, int]

_WIDTH = 1280
_HEIGHT = 800
_BG: Color = (11, 17, 27)
_PLOT: Color = (16, 24, 37)
_PANEL_SOFT: Color = (27, 39, 57)
_TEXT: Color = (239, 244, 250)
_MUTED: Color = (155, 169, 190)
_FAINT: Color = (92, 108, 132)
_GOLD: Color = (255, 191, 92)
_CYAN: Color = (99, 205, 215)
_GREEN: Color = (111, 216, 166)
_ORANGE: Color = (237, 142, 89)
_PINK: Color = (230, 112, 151)
_BLUE: Color = (132, 170, 255)
_GRID: Color = (51, 65, 87)


def render_trait_result_png(
    output_path: Path,
    *,
    sample_name: str,
    product_payload: dict[str, object],
    technical_payload: dict[str, object],
    lang: str = "ru",
    status_label: str = "RESULT",
) -> None:
    trait_id = str(product_payload.get("trait_id") or technical_payload.get("trait_id") or "")
    display_name = localize_trait_name(trait_id, str(product_payload.get("display_name") or ""), lang=lang)
    percentile = _optional_float(product_payload.get("percentile"))
    z_score = _optional_float(product_payload.get("z_score"))
    raw_score = _optional_float(product_payload.get("raw_score"))
    metrics = dict(product_payload.get("key_metrics") or {})
    qc_summary = dict(technical_payload.get("qc_summary") or {})
    confidence = str(product_payload.get("confidence") or technical_payload.get("confidence") or "unknown")
    group = str(product_payload.get("group") or "")
    pgs_id = str(product_payload.get("pgs_id") or "")
    qc_flags = [str(item) for item in technical_payload.get("qc_flags") or product_payload.get("qc_flags") or []]
    reference_panel = dict(product_payload.get("reference_panel") or technical_payload.get("reference_artifact") or {})

    image = _base_image()
    draw = ImageDraw.Draw(image, "RGBA")
    fonts = _fonts()
    _draw_header(
        draw,
        fonts,
        title=display_name,
        sample_name=sample_name,
        pill=status_label,
    )
    _draw_percentile_panel(
        draw,
        fonts,
        (40, 116, 770, 346),
        percentile=percentile,
        confidence=confidence,
        lang=lang,
    )
    _draw_interpretation_panel(
        draw,
        fonts,
        (40, 486, 770, 170),
        percentile=percentile,
        summary=str(product_payload.get("result_summary") or ""),
        caution=str(product_payload.get("caution_text") or ""),
        lang=lang,
    )
    _draw_metric_panel(
        draw,
        fonts,
        (846, 116, 394, 540),
        percentile=percentile,
        z_score=z_score,
        raw_score=raw_score,
        confidence=confidence,
        metrics=metrics,
        qc_summary=qc_summary,
        qc_flags=qc_flags,
        reference_panel=reference_panel,
        lang=lang,
    )
    _draw_footer(
        draw,
        fonts,
        left=f"Sample: {sample_name}",
        middle=f"Trait: {display_name}",
        right=f"{pgs_id or trait_id}     {group}",
        lang=lang,
    )
    image.save(output_path)


def _base_image() -> Image.Image:
    image = Image.new("RGB", (_WIDTH, _HEIGHT), _BG)
    draw = ImageDraw.Draw(image, "RGBA")
    for y in range(_HEIGHT):
        tint = int(15 + 18 * (y / _HEIGHT))
        draw.line((0, y, _WIDTH, y), fill=(10, tint, 28 + tint // 3, 255))
    draw.rounded_rectangle((24, 24, _WIDTH - 24, _HEIGHT - 24), radius=8, outline=(54, 70, 92, 220), width=1)
    return image


def _draw_header(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, ImageFont.ImageFont],
    *,
    title: str,
    sample_name: str,
    pill: str,
) -> None:
    draw.text((42, 36), "TRAITS", fill=(*_MUTED, 255), font=fonts["label"])
    draw.text((42, 58), _ellipsize(title.upper(), fonts["title"], 820, draw), fill=(*_TEXT, 255), font=fonts["title"])
    pill_text = pill.upper()
    right_edge = _WIDTH - 72
    pill_width = int(draw.textlength(pill_text, font=fonts["label"])) + 28
    pill_box = (right_edge - pill_width, 44, right_edge, 70)
    draw.rounded_rectangle(pill_box, radius=8, fill=(31, 44, 62, 235), outline=(70, 88, 111, 220), width=1)
    draw.text((pill_box[0] + 14, pill_box[1] + 8), pill_text, fill=(*_MUTED, 255), font=fonts["label"])

    sample = _ellipsize(sample_name, fonts["small"], 330, draw)
    label = "SAMPLE"
    label_width = int(draw.textlength(label, font=fonts["label"]))
    sample_width = int(draw.textlength(sample, font=fonts["small"]))
    start_x = right_edge - label_width - 10 - sample_width
    draw.text((start_x, 84), label, fill=(*_MUTED, 255), font=fonts["label"])
    draw.text((start_x + label_width + 10, 82), sample, fill=(*_TEXT, 255), font=fonts["small"])


def _draw_percentile_panel(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, ImageFont.ImageFont],
    rect: tuple[int, int, int, int],
    *,
    percentile: float | None,
    confidence: str,
    lang: str,
) -> None:
    _panel(draw, rect)
    x, y, w, h = rect
    draw.text((x + 24, y + 22), _copy(lang, "Процентиль", "Percentile"), fill=(*_TEXT, 255), font=fonts["section"])
    draw.text((x + 24, y + 52), _copy(lang, "позиция относительно референсной панели", "position relative to the reference panel"), fill=(*_MUTED, 255), font=fonts["tiny"])

    center = (x + 150, y + 188)
    radius = 96
    _draw_percentile_dial(draw, fonts, center, radius, percentile=percentile)

    outcome = _outcome_label(percentile, lang=lang)
    value_text = "n/a" if percentile is None else f"{percentile:.1f}"
    draw.text((x + 292, y + 122), _ellipsize(outcome, fonts["headline"], 380, draw), fill=(*_TEXT, 255), font=fonts["headline"])
    draw.text((x + 296, y + 172), f"{_copy(lang, 'Процентиль', 'Percentile')}: {value_text}", fill=(*_GOLD, 255), font=fonts["section"])
    draw.text(
        (x + 296, y + 210),
        f"{_copy(lang, 'Надежность', 'Confidence')}: {_display_confidence(confidence, lang=lang)}",
        fill=(*_MUTED, 255),
        font=fonts["small"],
    )
    _draw_percentile_rail(draw, fonts, (x + 296, y + 268, w - 340, 42), percentile=percentile)


def _draw_interpretation_panel(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, ImageFont.ImageFont],
    rect: tuple[int, int, int, int],
    *,
    percentile: float | None,
    summary: str,
    caution: str,
    lang: str,
) -> None:
    _panel(draw, rect)
    x, y, w, _h = rect
    draw.text((x + 24, y + 20), _copy(lang, "Как читать", "How to read"), fill=(*_TEXT, 255), font=fonts["section"])
    blurb = _outcome_blurb(percentile, lang=lang) if lang == "ru" else (summary.strip() or _outcome_blurb(percentile, lang=lang))
    caution_text = _copy(
        lang,
        "Это вероятностная генетическая оценка, не диагноз и не прямое физическое измерение.",
        "This is a probabilistic genetic estimate, not a diagnosis or a direct physical measurement.",
    )
    if lang != "ru" and caution.strip():
        caution_text = caution.strip()
    _wrapped_text(draw, (x + 24, y + 58), blurb, fonts["small"], w - 48, fill=_TEXT, max_lines=2)
    _wrapped_text(draw, (x + 24, y + 108), caution_text, fonts["tiny"], w - 48, fill=_MUTED, max_lines=2)


def _draw_metric_panel(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, ImageFont.ImageFont],
    rect: tuple[int, int, int, int],
    *,
    percentile: float | None,
    z_score: float | None,
    raw_score: float | None,
    confidence: str,
    metrics: dict[str, object],
    qc_summary: dict[str, object],
    qc_flags: list[str],
    reference_panel: dict[str, object],
    lang: str,
) -> None:
    _panel(draw, rect)
    x, y, w, h = rect
    draw.text((x + 24, y + 22), _copy(lang, "Метрики", "Metrics"), fill=(*_TEXT, 255), font=fonts["section"])
    draw.text((x + 24, y + 52), _copy(lang, "score, покрытие и QC", "score, coverage, and QC"), fill=(*_MUTED, 255), font=fonts["tiny"])

    matched = _first_number(metrics.get("matched_variants"), qc_summary.get("matched_variants"))
    total = _first_number(metrics.get("total_variants"), qc_summary.get("total_variants"))
    overlap = _first_number(metrics.get("overlap_percent"), qc_summary.get("overlap_percent"))
    ref_count = _first_number(reference_panel.get("sample_count_included"), reference_panel.get("sample_count_total"))

    cards = [
        (_copy(lang, "Процентиль", "Percentile"), "n/a" if percentile is None else f"{percentile:.1f}", _GOLD),
        ("z-score", "n/a" if z_score is None else f"{z_score:+.2f}", _CYAN),
        (_copy(lang, "Raw score", "Raw score"), "n/a" if raw_score is None else f"{raw_score:.4f}", _BLUE),
        (_copy(lang, "Надежность", "Confidence"), _display_confidence(confidence, lang=lang), _confidence_color(confidence)),
    ]
    card_w = (w - 64) // 2
    for index, (label, value, color) in enumerate(cards):
        cx = x + 24 + (index % 2) * (card_w + 16)
        cy = y + 92 + (index // 2) * 94
        _metric_card(draw, fonts, (cx, cy, card_w, 72), label, value, color)

    qc_y = y + 302
    draw.text((x + 24, qc_y), _copy(lang, "Покрытие вариантов", "Variant coverage"), fill=(*_TEXT, 255), font=fonts["small"])
    matched_text = "n/a" if matched is None or total is None else f"{int(matched)} / {int(total)}"
    draw.text((x + w - 124, qc_y), matched_text, fill=(*_MUTED, 255), font=fonts["mono"])
    _draw_coverage_bar(draw, (x + 24, qc_y + 32, w - 48, 16), overlap)
    overlap_text = "n/a" if overlap is None else f"{float(overlap):.1f}%"
    draw.text((x + 24, qc_y + 58), f"{_copy(lang, 'Покрытие', 'Overlap')}: {overlap_text}", fill=(*_MUTED, 255), font=fonts["tiny"])
    if ref_count is not None:
        draw.text((x + 24, qc_y + 82), f"{_copy(lang, 'Референс', 'Reference samples')}: {int(ref_count)}", fill=(*_MUTED, 255), font=fonts["tiny"])

    flag_y = y + h - 82
    flag_text = _format_flags(qc_flags, lang=lang)
    draw.text((x + 24, flag_y), _copy(lang, "QC", "QC"), fill=(*_TEXT, 255), font=fonts["label"])
    _wrapped_text(draw, (x + 24, flag_y + 22), flag_text, fonts["tiny"], w - 48, fill=_FAINT, max_lines=2)


def _draw_percentile_dial(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, ImageFont.ImageFont],
    center: tuple[int, int],
    radius: int,
    *,
    percentile: float | None,
) -> None:
    cx, cy = center
    box = (cx - radius, cy - radius, cx + radius, cy + radius)
    draw.ellipse(box, fill=(26, 37, 54, 220), outline=(65, 82, 108, 190), width=2)
    draw.arc(box, start=145, end=395, fill=(*_GRID, 255), width=16)
    if percentile is not None:
        clamped = max(0.0, min(100.0, percentile))
        end = 145 + int(250 * (clamped / 100.0))
        draw.arc(box, start=145, end=end, fill=(*_color_for_percentile(clamped), 255), width=16)
    value = "n/a" if percentile is None else f"{percentile:.1f}"
    value_width = draw.textlength(value, font=fonts["dial"])
    draw.text((cx - value_width / 2, cy - 34), value, fill=(*_TEXT, 255), font=fonts["dial"])
    label = "PERCENTILE"
    label_width = draw.textlength(label, font=fonts["label"])
    draw.text((cx - label_width / 2, cy + 28), label, fill=(*_MUTED, 255), font=fonts["label"])


def _draw_percentile_rail(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, ImageFont.ImageFont],
    rect: tuple[int, int, int, int],
    *,
    percentile: float | None,
) -> None:
    x, y, w, h = rect
    bands = [
        (0.0, 35.0, _CYAN),
        (35.0, 65.0, _GREEN),
        (65.0, 100.0, _ORANGE),
    ]
    for start, end, color in bands:
        sx = x + int(w * (start / 100.0))
        ex = x + int(w * (end / 100.0))
        draw.rounded_rectangle((sx, y + 12, ex, y + 26), radius=7, fill=(*color, 170))
    for label, px in (("0", x), ("50", x + w // 2), ("100", x + w)):
        label_w = draw.textlength(label, font=fonts["tiny"])
        draw.text((px - label_w / 2, y + 30), label, fill=(*_MUTED, 255), font=fonts["tiny"])
    if percentile is not None:
        marker_x = x + int(w * (max(0.0, min(100.0, percentile)) / 100.0))
        draw.line((marker_x, y + 4, marker_x, y + 32), fill=(*_TEXT, 255), width=2)
        draw.polygon([(marker_x, y), (marker_x - 7, y + 9), (marker_x + 7, y + 9)], fill=(*_TEXT, 255))


def _draw_coverage_bar(draw: ImageDraw.ImageDraw, rect: tuple[int, int, int, int], overlap: float | None) -> None:
    x, y, w, h = rect
    draw.rounded_rectangle((x, y, x + w, y + h), radius=8, fill=(38, 48, 66, 210))
    if overlap is None:
        return
    clamped = max(0.0, min(100.0, float(overlap)))
    color = _GREEN if clamped >= 70.0 else _GOLD if clamped >= 35.0 else _PINK
    draw.rounded_rectangle((x, y, x + max(4, int(w * (clamped / 100.0))), y + h), radius=8, fill=(*color, 230))


def _metric_card(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, ImageFont.ImageFont],
    rect: tuple[int, int, int, int],
    label: str,
    value: str,
    color: Color,
) -> None:
    x, y, w, h = rect
    draw.rounded_rectangle((x, y, x + w, y + h), radius=8, fill=(*_PANEL_SOFT, 220), outline=(54, 69, 90, 160), width=1)
    draw.rectangle((x, y, x + 4, y + h), fill=(*color, 210))
    draw.text((x + 18, y + 12), label.upper(), fill=(*_MUTED, 255), font=fonts["label"])
    draw.text((x + 18, y + 36), _ellipsize(value, fonts["small"], w - 34, draw), fill=(*_TEXT, 255), font=fonts["small"])


def _draw_footer(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, ImageFont.ImageFont],
    *,
    left: str,
    middle: str,
    right: str,
    lang: str,
) -> None:
    y = 692
    draw.rounded_rectangle((40, y, _WIDTH - 40, 762), radius=8, fill=(26, 37, 54, 235), outline=(65, 82, 108, 190), width=1)
    draw.text((62, y + 18), _ellipsize(left, fonts["small"], 320, draw), fill=(*_TEXT, 255), font=fonts["small"])
    draw.text((410, y + 18), _ellipsize(middle, fonts["small"], 430, draw), fill=(*_MUTED, 255), font=fonts["small"])
    draw.text((870, y + 18), _ellipsize(right, fonts["small"], 350, draw), fill=(*_GOLD, 255), font=fonts["small"])
    draw.text(
        (62, y + 44),
        _copy(lang, "Polygenic score зависит от модели и референсной панели.", "Polygenic scores are probabilistic and reference-panel dependent."),
        fill=(*_FAINT, 255),
        font=fonts["tiny"],
    )


def _panel(draw: ImageDraw.ImageDraw, rect: tuple[int, int, int, int]) -> None:
    x, y, w, h = rect
    draw.rounded_rectangle((x, y, x + w, y + h), radius=8, fill=(*_PLOT, 235), outline=(64, 80, 104, 210), width=1)
    for index in range(1, 4):
        yy = y + int((h * index) / 4)
        draw.line((x + 12, yy, x + w - 12, yy), fill=(*_GRID, 56), width=1)


def _wrapped_text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text_value: str,
    font: ImageFont.ImageFont,
    max_width: int,
    *,
    fill: Color,
    max_lines: int,
) -> None:
    x, y = xy
    words = text_value.split()
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
    for index, line in enumerate(lines):
        suffix = "..." if index == max_lines - 1 and words and " ".join(lines) != text_value else ""
        draw.text((x, y + index * 22), _ellipsize(line + suffix, font, max_width, draw), fill=(*fill, 255), font=font)


def _outcome_label(percentile: float | None, *, lang: str) -> str:
    if percentile is None:
        return _copy(lang, "Без уверенного вывода", "No clear summary")
    if percentile < 35.0:
        return _copy(lang, "Ниже среднего", "Below average")
    if percentile <= 65.0:
        return _copy(lang, "Около среднего", "Around average")
    return _copy(lang, "Выше среднего", "Above average")


def _outcome_blurb(percentile: float | None, *, lang: str) -> str:
    outcome = _outcome_label(percentile, lang=lang)
    if lang == "ru":
        lowered = outcome[:1].lower() + outcome[1:] if outcome else outcome
        return f"Ваш генетический результат по этому признаку {lowered} относительно референсной панели."
    return f"Your genetic result for this trait is {outcome.lower()} relative to the reference panel."


def _color_for_percentile(percentile: float) -> Color:
    if percentile < 35.0:
        return _CYAN
    if percentile <= 65.0:
        return _GREEN
    return _ORANGE


def _confidence_color(confidence: str) -> Color:
    normalized = confidence.strip().lower()
    if normalized == "high":
        return _GREEN
    if normalized == "medium":
        return _GOLD
    if normalized == "low":
        return _PINK
    return _BLUE


def _display_confidence(value: str, *, lang: str) -> str:
    localized = localize_confidence(value, lang=lang)
    return localized[:1].upper() + localized[1:] if localized else value


def _format_flags(flags: list[str], *, lang: str) -> str:
    if not flags:
        return _copy(lang, "QC-флаги отсутствуют.", "No QC flags.")
    cleaned = ", ".join(_format_flag(flag, lang=lang) for flag in flags[:4])
    if len(flags) > 4:
        cleaned += ", ..."
    return cleaned


def _format_flag(flag: str, *, lang: str) -> str:
    if lang != "ru":
        return flag.replace("_", " ")
    labels = {
        "low_overlap": "низкое покрытие",
        "low_matched_variant_count": "мало совпавших вариантов",
        "high_ambiguous_removal_rate": "много неоднозначных вариантов",
        "missing_reference_distribution": "нет референсного распределения",
        "invalid_reference_sd": "некорректное SD референса",
        "weak_reference_panel": "слабая референсная панель",
    }
    return labels.get(flag, flag.replace("_", " "))


def _first_number(*values: object) -> float | None:
    for value in values:
        number = _optional_float(value)
        if number is not None:
            return number
    return None


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _copy(lang: str, ru: str, en: str) -> str:
    return en if lang == "en" else ru


def _ellipsize(text: str, font: ImageFont.ImageFont, max_width: int, draw: ImageDraw.ImageDraw) -> str:
    if draw.textlength(text, font=font) <= max_width:
        return text
    suffix = "..."
    while text and draw.textlength(text + suffix, font=font) > max_width:
        text = text[:-1]
    return (text + suffix) if text else suffix


def _fonts() -> dict[str, ImageFont.ImageFont]:
    return {
        "title": _font(30, bold=True),
        "headline": _font(30, bold=True),
        "section": _font(20, bold=True),
        "label": _font(13, bold=True),
        "small": _font(16),
        "tiny": _font(12),
        "mono": _font(13),
        "dial": _font(42, bold=True),
    }


def _font(size: int, *, bold: bool = False) -> ImageFont.ImageFont:
    candidates = [
        Path("C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf"),
        Path("C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default()
