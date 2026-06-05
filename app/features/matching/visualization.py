from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Tuple

from PIL import Image, ImageDraw, ImageFont


Color = Tuple[int, int, int]

_WIDTH = 1280
_HEIGHT = 800
_BG: Color = (11, 17, 27)
_PLOT: Color = (16, 23, 35)
_PANEL_SOFT: Color = (27, 39, 57)
_TEXT: Color = (239, 244, 250)
_MUTED: Color = (155, 169, 190)
_FAINT: Color = (92, 108, 132)
_GRID: Color = (51, 65, 87)
_GOLD: Color = (255, 191, 92)
_ORANGE: Color = (236, 141, 88)
_CYAN: Color = (99, 205, 215)
_GREEN: Color = (111, 216, 166)
_PINK: Color = (230, 112, 151)
_BLUE: Color = (132, 170, 255)

_PALETTE: Tuple[Color, ...] = (
    _ORANGE,
    _CYAN,
    _GOLD,
    _GREEN,
    _PINK,
    _BLUE,
    (185, 135, 246),
    (154, 207, 103),
)

_CHROMOSOME_LENGTHS: dict[str, int] = {
    "1": 249_250_621,
    "2": 243_199_373,
    "3": 198_022_430,
    "4": 191_154_276,
    "5": 180_915_260,
    "6": 171_115_067,
    "7": 159_138_663,
    "8": 146_364_022,
    "9": 141_213_431,
    "10": 135_534_747,
    "11": 135_006_516,
    "12": 133_851_895,
    "13": 115_169_878,
    "14": 107_349_540,
    "15": 102_531_392,
    "16": 90_354_753,
    "17": 81_195_210,
    "18": 78_077_248,
    "19": 59_128_983,
    "20": 63_025_520,
    "21": 48_129_895,
    "22": 51_304_566,
}


@dataclass(frozen=True)
class SegmentVisual:
    chromosome: str
    start: int
    end: int
    snp_count: int
    identical_snps: int
    estimated_cm: float


@dataclass(frozen=True)
class PairEntry:
    left_name: str
    right_name: str
    total_cm: float
    longest_cm: float
    segment_count: int
    genetic_map_used: bool


def render_pairwise_match_png(
    output_path: Path,
    *,
    left_name: str,
    right_name: str,
    result: object,
    status_label: str = "PAIRWISE",
) -> None:
    segments = _segments_from_result(result)
    total_cm = _float(_result_value(result, "total_estimated_cm"))
    longest_cm = _float(_result_value(result, "longest_estimated_cm"))
    overlap_snps = int(_float(_result_value(result, "overlap_snps")))
    shared_snps = int(_float(_result_value(result, "half_identical_snps", "shared_snps")))
    identical_snps = int(_float(_result_value(result, "identical_snps")))
    genetic_map_used = bool(_result_value(result, "genetic_map_used"))

    image = _base_image()
    draw = ImageDraw.Draw(image, "RGBA")
    fonts = _fonts()
    pair_name = f"{left_name} vs {right_name}"
    _draw_header(draw, fonts, eyebrow="MATCHING", title="PAIRWISE AUTOSOMAL MATCH", sample_name=pair_name, pill=status_label)
    _draw_chromosome_panel(
        draw,
        fonts,
        (40, 116, 820, 540),
        segments=segments,
        total_cm=total_cm,
    )
    _draw_pairwise_side_panel(
        draw,
        fonts,
        (894, 116, 346, 540),
        total_cm=total_cm,
        longest_cm=longest_cm,
        segments=segments,
        overlap_snps=overlap_snps,
        shared_snps=shared_snps,
        identical_snps=identical_snps,
        genetic_map_used=genetic_map_used,
    )
    _draw_footer(
        draw,
        fonts,
        left=f"A: {left_name}",
        middle=f"B: {right_name}     Map: {'GRCh37' if genetic_map_used else 'fallback'}",
        right=f"Total {total_cm:.2f} cM     Longest {longest_cm:.2f} cM",
        note="Shared segments are estimated from half-identical SNP runs; relationship calls still need context.",
    )
    image.save(output_path)


def render_all_pairs_match_png(
    output_path: Path,
    *,
    results: Sequence[tuple[object, object, object]],
    sample_count: int,
    status_label: str = "OVERVIEW",
) -> None:
    entries = _pair_entries(results)
    sorted_entries = sorted(entries, key=lambda item: item.total_cm, reverse=True)
    visible = [item for item in sorted_entries if item.total_cm > 0.0][:12]
    if not visible:
        visible = sorted_entries[:12]

    image = _base_image()
    draw = ImageDraw.Draw(image, "RGBA")
    fonts = _fonts()
    _draw_header(
        draw,
        fonts,
        eyebrow="MATCHING",
        title="ALL PAIRS OVERVIEW",
        sample_name=f"{sample_count} samples",
        pill=status_label,
        sample_label="SAMPLES",
    )
    _draw_pair_ranking_panel(
        draw,
        fonts,
        (40, 116, 820, 540),
        entries=visible,
    )
    _draw_all_pairs_side_panel(
        draw,
        fonts,
        (894, 116, 346, 540),
        entries=entries,
        sample_count=sample_count,
    )
    best = sorted_entries[0] if sorted_entries else None
    _draw_footer(
        draw,
        fonts,
        left=f"Samples: {sample_count}",
        middle=f"Compared pairs: {len(entries)}",
        right=f"Best: {_pair_label(best, 30) if best else '-'}",
        note="All-vs-all is a screening view. Open a pairwise match for chromosome-level detail.",
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
    eyebrow: str,
    title: str,
    sample_name: str,
    pill: str,
    sample_label: str = "PAIR",
) -> None:
    draw.text((42, 36), eyebrow.upper(), fill=(*_MUTED, 255), font=fonts["label"])
    draw.text((42, 58), _ellipsize(title.upper(), fonts["title"], 800, draw), fill=(*_TEXT, 255), font=fonts["title"])
    right_edge = _WIDTH - 72
    pill_text = pill.upper()
    pill_width = int(draw.textlength(pill_text, font=fonts["label"])) + 28
    pill_box = (right_edge - pill_width, 44, right_edge, 70)
    draw.rounded_rectangle(pill_box, radius=8, fill=(31, 44, 62, 235), outline=(70, 88, 111, 220), width=1)
    draw.text((pill_box[0] + 14, pill_box[1] + 8), pill_text, fill=(*_MUTED, 255), font=fonts["label"])

    sample = _ellipsize(sample_name, fonts["small"], 370, draw)
    label = sample_label.upper()
    label_width = int(draw.textlength(label, font=fonts["label"]))
    sample_width = int(draw.textlength(sample, font=fonts["small"]))
    start_x = right_edge - label_width - 10 - sample_width
    draw.text((start_x, 84), label, fill=(*_MUTED, 255), font=fonts["label"])
    draw.text((start_x + label_width + 10, 82), sample, fill=(*_TEXT, 255), font=fonts["small"])


def _draw_chromosome_panel(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, ImageFont.ImageFont],
    rect: tuple[int, int, int, int],
    *,
    segments: Sequence[SegmentVisual],
    total_cm: float,
) -> None:
    _panel(draw, rect)
    x, y, w, h = rect
    draw.text((x + 22, y + 20), "Chromosome segment map", fill=(*_TEXT, 255), font=fonts["section"])
    draw.text((x + 22, y + 50), "autosomal shared segments, scaled by chromosome position", fill=(*_MUTED, 255), font=fonts["tiny"])

    by_chr: dict[str, list[SegmentVisual]] = {str(index): [] for index in range(1, 23)}
    for segment in segments:
        if segment.chromosome in by_chr:
            by_chr[segment.chromosome].append(segment)

    plot_x = x + 72
    plot_w = w - 118
    start_y = y + 88
    row_h = 17
    longest = max(segments, key=lambda item: item.estimated_cm, default=None)
    max_cm = max((segment.estimated_cm for segment in segments), default=1.0)
    for index in range(1, 23):
        chromosome = str(index)
        yy = start_y + (index - 1) * row_h
        length = _CHROMOSOME_LENGTHS[chromosome]
        track_y = yy + 7
        track_w = max(34, int(plot_w * (length / _CHROMOSOME_LENGTHS["1"])))
        draw.text((x + 24, yy + 1), chromosome.rjust(2), fill=(*_MUTED, 255), font=fonts["mono"])
        draw.rounded_rectangle(
            (plot_x, track_y, plot_x + track_w, track_y + 8),
            radius=4,
            fill=(37, 48, 66, 205),
            outline=(62, 77, 101, 90),
            width=1,
        )
        for segment in sorted(by_chr[chromosome], key=lambda item: item.start):
            sx = plot_x + int(max(0, min(length, segment.start)) / length * track_w)
            ex = plot_x + int(max(0, min(length, segment.end)) / length * track_w)
            if ex < sx:
                sx, ex = ex, sx
            ex = max(ex, sx + 4)
            color = _segment_color(segment.estimated_cm, max_cm=max_cm)
            if longest is not None and segment == longest:
                draw.rounded_rectangle((sx - 3, track_y - 4, ex + 3, track_y + 12), radius=7, fill=(*_GOLD, 50))
                draw.rounded_rectangle((sx - 1, track_y - 2, ex + 1, track_y + 10), radius=5, outline=(*_GOLD, 230), width=1)
            draw.rounded_rectangle((sx, track_y - 1, ex, track_y + 9), radius=5, fill=(*color, 235))

    if not segments:
        _empty_state(draw, fonts, (x + 210, y + 230, 400, 90), "No significant shared segments")
    else:
        top = sorted(segments, key=lambda item: item.estimated_cm, reverse=True)[:5]
        label_y = y + h - 58
        label_text = "TOP SEGMENTS"
        draw.text((x + 24, label_y), label_text, fill=(*_FAINT, 255), font=fonts["label"])
        label_width = int(draw.textlength(label_text, font=fonts["label"]))
        cursor = x + 24 + label_width + 24
        for segment in top:
            label = f"chr{segment.chromosome} {segment.estimated_cm:.1f}cM"
            color = _segment_color(segment.estimated_cm, max_cm=max_cm)
            label_w = int(draw.textlength(label, font=fonts["tiny"])) + 20
            if cursor + label_w > x + w - 24:
                break
            draw.rounded_rectangle((cursor, label_y - 3, cursor + label_w, label_y + 19), radius=7, fill=(*color, 45), outline=(*color, 160), width=1)
            draw.text((cursor + 10, label_y + 2), label, fill=(*_TEXT, 255), font=fonts["tiny"])
            cursor += label_w + 10
    draw.text((x + 24, y + h - 28), f"Total shared segment signal: {total_cm:.2f} cM", fill=(*_MUTED, 255), font=fonts["tiny"])


def _draw_pairwise_side_panel(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, ImageFont.ImageFont],
    rect: tuple[int, int, int, int],
    *,
    total_cm: float,
    longest_cm: float,
    segments: Sequence[SegmentVisual],
    overlap_snps: int,
    shared_snps: int,
    identical_snps: int,
    genetic_map_used: bool,
) -> None:
    _panel(draw, rect)
    x, y, w, h = rect
    draw.text((x + 22, y + 20), "Relationship signal", fill=(*_TEXT, 255), font=fonts["section"])
    draw.text(
        (x + 22, y + 50),
        _relationship_level(
            total_cm,
            longest_cm,
        ),
        fill=(*_MUTED, 255),
        font=fonts["tiny"],
    )
    _draw_signal_bar(draw, fonts, (x + 24, y + 88, w - 48, 46), total_cm=total_cm)

    _metric_card(draw, fonts, (x + 24, y + 154, w - 48, 72), "Total cM", f"{total_cm:.2f}", _GOLD)
    _metric_card(draw, fonts, (x + 24, y + 240, w - 48, 72), "Longest segment", f"{longest_cm:.2f} cM", _CYAN)
    small_y = y + 332
    rows = [
        ("Segments", str(len(segments))),
        ("Shared SNPs", f"{shared_snps:,}"),
        ("Identical SNPs", f"{identical_snps:,}"),
        ("Overlap SNPs", f"{overlap_snps:,}"),
        ("Map", "GRCh37" if genetic_map_used else "fallback"),
    ]
    for index, (label, value) in enumerate(rows):
        yy = small_y + index * 25
        draw.text((x + 24, yy), label.upper(), fill=(*_FAINT, 255), font=fonts["label"])
        draw.text((x + w - 24 - draw.textlength(value, font=fonts["mono"]), yy - 1), value, fill=(*_TEXT, 255), font=fonts["mono"])

    top_y = y + h - 88
    draw.text((x + 24, top_y), "BEST SEGMENT", fill=(*_FAINT, 255), font=fonts["label"])
    best = max(segments, key=lambda item: item.estimated_cm, default=None)
    if best is None:
        draw.text((x + 24, top_y + 26), "-", fill=(*_MUTED, 255), font=fonts["small"])
    else:
        mb_start = best.start / 1_000_000
        mb_end = best.end / 1_000_000
        text = f"chr{best.chromosome}: {mb_start:.1f}-{mb_end:.1f} Mb"
        draw.text((x + 24, top_y + 26), _ellipsize(text, fonts["small"], w - 48, draw), fill=(*_TEXT, 255), font=fonts["small"])
        draw.text((x + 24, top_y + 52), f"{best.estimated_cm:.2f} cM · {best.snp_count:,} SNPs", fill=(*_GOLD, 255), font=fonts["tiny"])


def _draw_signal_bar(draw: ImageDraw.ImageDraw, fonts: dict[str, ImageFont.ImageFont], rect: tuple[int, int, int, int], *, total_cm: float) -> None:
    x, y, w, _h = rect
    draw.rounded_rectangle((x, y + 15, x + w, y + 29), radius=7, fill=(38, 49, 68, 220))
    bands = [
        (0.0, 20.0, _FAINT),
        (20.0, 60.0, _CYAN),
        (60.0, 200.0, _GREEN),
        (200.0, 550.0, _GOLD),
        (550.0, 1_300.0, _ORANGE),
        (1_300.0, 3_500.0, _PINK),
    ]
    for start, end, color in bands:
        sx = x + int(_cm_scale(start) * w)
        ex = x + int(_cm_scale(end) * w)
        draw.rounded_rectangle((sx, y + 15, max(ex, sx + 3), y + 29), radius=7, fill=(*color, 180))
    marker_x = x + int(_cm_scale(total_cm) * w)
    draw.line((marker_x, y + 7, marker_x, y + 37), fill=(*_TEXT, 255), width=2)
    draw.polygon([(marker_x, y + 3), (marker_x - 6, y + 11), (marker_x + 6, y + 11)], fill=(*_TEXT, 255))
    for label, cm in (("20", 20), ("200", 200), ("550", 550), ("2300", 2300)):
        tx = x + int(_cm_scale(cm) * w)
        label_w = draw.textlength(label, font=fonts["tiny"])
        draw.text((tx - label_w / 2, y + 34), label, fill=(*_FAINT, 255), font=fonts["tiny"])


def _draw_pair_ranking_panel(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, ImageFont.ImageFont],
    rect: tuple[int, int, int, int],
    *,
    entries: Sequence[PairEntry],
) -> None:
    _panel(draw, rect)
    x, y, w, h = rect
    draw.text((x + 22, y + 20), "Top pairwise matches", fill=(*_TEXT, 255), font=fonts["section"])
    draw.text((x + 22, y + 50), "sorted by total estimated shared cM", fill=(*_MUTED, 255), font=fonts["tiny"])
    if not entries:
        _empty_state(draw, fonts, (x + 210, y + 230, 400, 90), "No comparable pairs")
        return

    max_total = max((entry.total_cm for entry in entries), default=0.0)
    scale_total = max(max_total, 1.0)
    row_h = 38
    start_y = y + 92
    bar_x = x + 300
    bar_w = w - 440
    for index, entry in enumerate(entries[:12]):
        row_y = start_y + index * row_h
        if row_y + row_h > y + h - 36:
            break
        color = _segment_color(entry.total_cm, max_cm=scale_total)
        draw.text((x + 24, row_y + 5), f"{index + 1:02d}", fill=(*_MUTED, 255), font=fonts["mono"])
        draw.text((x + 68, row_y + 5), _pair_label(entry, 25), fill=(*_TEXT, 255), font=fonts["small"])
        draw.rounded_rectangle((bar_x, row_y + 9, bar_x + bar_w, row_y + 23), radius=7, fill=(38, 48, 66, 210))
        fill_w = 0 if entry.total_cm <= 0.0 else max(4, int((entry.total_cm / scale_total) * bar_w))
        if fill_w:
            draw.rounded_rectangle((bar_x, row_y + 9, bar_x + fill_w, row_y + 23), radius=7, fill=(*color, 230))
        draw.text((bar_x + bar_w + 18, row_y + 4), f"{entry.total_cm:.1f}", fill=(*_GOLD, 255), font=fonts["mono"])
        draw.text((x + w - 86, row_y + 4), f"{entry.segment_count} seg", fill=(*_MUTED, 255), font=fonts["tiny"])


def _draw_all_pairs_side_panel(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, ImageFont.ImageFont],
    rect: tuple[int, int, int, int],
    *,
    entries: Sequence[PairEntry],
    sample_count: int,
) -> None:
    _panel(draw, rect)
    x, y, w, h = rect
    significant = [entry for entry in entries if entry.total_cm > 0.0]
    best = max(entries, key=lambda item: item.total_cm, default=None)
    map_label = "GRCh37" if any(entry.genetic_map_used for entry in entries) else "fallback"
    draw.text((x + 22, y + 20), "Run summary", fill=(*_TEXT, 255), font=fonts["section"])
    draw.text((x + 22, y + 50), "all samples with raw files", fill=(*_MUTED, 255), font=fonts["tiny"])
    cards = [
        ("Samples", str(sample_count), _CYAN),
        ("Pairs", str(len(entries)), _GOLD),
        ("With signal", str(len(significant)), _GREEN),
        ("Map", map_label, _BLUE),
    ]
    for index, (label, value, color) in enumerate(cards):
        cx = x + 24 + (index % 2) * ((w - 64) // 2 + 16)
        cy = y + 92 + (index // 2) * 92
        _metric_card(draw, fonts, (cx, cy, (w - 64) // 2, 70), label, value, color)

    draw.text((x + 24, y + 308), "BEST MATCH", fill=(*_FAINT, 255), font=fonts["label"])
    if best is not None:
        draw.text((x + 24, y + 336), _ellipsize(_pair_label(best, 28), fonts["small"], w - 48, draw), fill=(*_TEXT, 255), font=fonts["small"])
        draw.text((x + 24, y + 362), f"{best.total_cm:.2f} cM · longest {best.longest_cm:.2f} · {best.segment_count} segments", fill=(*_GOLD, 255), font=fonts["tiny"])
        _draw_signal_bar(draw, fonts, (x + 24, y + 402, w - 48, 46), total_cm=best.total_cm)
        draw.text((x + 24, y + 476), _relationship_level(best.total_cm, best.longest_cm), fill=(*_MUTED, 255), font=fonts["tiny"])
    else:
        draw.text((x + 24, y + 336), "-", fill=(*_MUTED, 255), font=fonts["small"])
    draw.text((x + 24, y + h - 42), "Run a pairwise match for chromosome-level segment detail.", fill=(*_FAINT, 255), font=fonts["tiny"])


def _metric_card(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, ImageFont.ImageFont],
    rect: tuple[int, int, int, int],
    label: str,
    value: str,
    accent: Color,
) -> None:
    x, y, w, h = rect
    draw.rounded_rectangle((x, y, x + w, y + h), radius=8, fill=(*_PANEL_SOFT, 220), outline=(54, 69, 90, 160), width=1)
    draw.rectangle((x, y, x + 4, y + h), fill=(*accent, 210))
    draw.text((x + 18, y + 12), label.upper(), fill=(*_MUTED, 255), font=fonts["label"])
    draw.text((x + 18, y + 36), _ellipsize(value, fonts["small"], w - 34, draw), fill=(*_TEXT, 255), font=fonts["small"])


def _draw_footer(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, ImageFont.ImageFont],
    *,
    left: str,
    middle: str,
    right: str,
    note: str,
) -> None:
    y = 692
    draw.rounded_rectangle((40, y, _WIDTH - 40, 762), radius=8, fill=(26, 37, 54, 235), outline=(65, 82, 108, 190), width=1)
    draw.text((62, y + 18), _ellipsize(left, fonts["small"], 320, draw), fill=(*_TEXT, 255), font=fonts["small"])
    draw.text((410, y + 18), _ellipsize(middle, fonts["small"], 450, draw), fill=(*_MUTED, 255), font=fonts["small"])
    draw.text((884, y + 18), _ellipsize(right, fonts["small"], 334, draw), fill=(*_GOLD, 255), font=fonts["small"])
    draw.text((62, y + 44), _ellipsize(note, fonts["tiny"], 1120, draw), fill=(*_FAINT, 255), font=fonts["tiny"])


def _panel(draw: ImageDraw.ImageDraw, rect: tuple[int, int, int, int]) -> None:
    x, y, w, h = rect
    draw.rounded_rectangle((x, y, x + w, y + h), radius=8, fill=(*_PLOT, 235), outline=(64, 80, 104, 210), width=1)
    for index in range(1, 5):
        yy = y + int((h * index) / 5)
        draw.line((x + 12, yy, x + w - 12, yy), fill=(*_GRID, 52), width=1)


def _empty_state(draw: ImageDraw.ImageDraw, fonts: dict[str, ImageFont.ImageFont], rect: tuple[int, int, int, int], text: str) -> None:
    x, y, w, h = rect
    draw.rounded_rectangle((x, y, x + w, y + h), radius=8, fill=(30, 40, 56, 210), outline=(63, 78, 102, 150), width=1)
    text_w = draw.textlength(text, font=fonts["small"])
    draw.text((x + (w - text_w) / 2, y + h / 2 - 10), text, fill=(*_MUTED, 255), font=fonts["small"])


def _segment_color(value: float, *, max_cm: float) -> Color:
    if max_cm <= 0.0:
        return _CYAN
    score = max(0.0, min(1.0, value / max_cm))
    if value >= 60.0:
        return _PINK
    if value >= 20.0:
        return _ORANGE
    if score >= 0.70:
        return _GOLD
    if score >= 0.38:
        return _GREEN
    return _CYAN


def _cm_scale(value: float) -> float:
    clamped = max(0.0, min(3_500.0, float(value)))
    return math.log10(clamped + 1.0) / math.log10(3_500.0 + 1.0)


def _relationship_level(
    total_cm: float,
    longest_cm: float,
) -> str:
    if total_cm >= 3300:
        return "near-complete match"
    if total_cm >= 2300:
        return "close family range"
    if total_cm >= 1300:
        return "close relationship range"
    if total_cm >= 550:
        return "first-cousin-like range"
    if total_cm >= 200:
        return "medium relationship range"
    if total_cm >= 60:
        return "distant relationship range"
    if total_cm >= 20 or longest_cm >= 7:
        return "small distant shared segment"
    return "no significant segment signal"


def _segments_from_result(result: object) -> list[SegmentVisual]:
    raw_segments = _result_value(result, "segments", default=()) or ()
    segments: list[SegmentVisual] = []
    for item in raw_segments:
        chromosome = str(_item_value(item, "chromosome") or "").strip().replace("chr", "")
        if chromosome not in _CHROMOSOME_LENGTHS:
            continue
        start = int(_float(_item_value(item, "start")))
        end = int(_float(_item_value(item, "end")))
        if start <= 0 and end <= 0:
            continue
        if end < start:
            start, end = end, start
        segments.append(
            SegmentVisual(
                chromosome=chromosome,
                start=start,
                end=end,
                snp_count=int(_float(_item_value(item, "snp_count"))),
                identical_snps=int(_float(_item_value(item, "identical_snps"))),
                estimated_cm=_float(_item_value(item, "estimated_cm")),
            )
        )
    return sorted(segments, key=lambda item: item.estimated_cm, reverse=True)


def _pair_entries(results: Sequence[tuple[object, object, object]]) -> list[PairEntry]:
    entries: list[PairEntry] = []
    for left, right, result in results:
        entries.append(
            PairEntry(
                left_name=str(getattr(left, "display_name", left)),
                right_name=str(getattr(right, "display_name", right)),
                total_cm=_float(_result_value(result, "total_estimated_cm")),
                longest_cm=_float(_result_value(result, "longest_estimated_cm")),
                segment_count=len(_segments_from_result(result)),
                genetic_map_used=bool(_result_value(result, "genetic_map_used")),
            )
        )
    return entries


def _pair_label(entry: PairEntry | None, max_chars: int) -> str:
    if entry is None:
        return "-"
    label = f"{entry.left_name} - {entry.right_name}"
    return label if len(label) <= max_chars else label[: max_chars - 3] + "..."


def _result_value(result: object, *names: str, default: object = 0.0) -> object:
    if isinstance(result, Mapping):
        for name in names:
            if name in result:
                return result[name]
        return default
    for name in names:
        if hasattr(result, name):
            return getattr(result, name)
    return default


def _item_value(item: object, name: str, default: object = 0.0) -> object:
    if isinstance(item, Mapping):
        return item.get(name, default)
    return getattr(item, name, default)


def _ellipsize(text: str, font: ImageFont.ImageFont, max_width: int, draw: ImageDraw.ImageDraw) -> str:
    text = str(text)
    if draw.textlength(text, font=font) <= max_width:
        return text
    suffix = "..."
    while text and draw.textlength(text + suffix, font=font) > max_width:
        text = text[:-1]
    return (text + suffix) if text else suffix


def _float(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _fonts() -> dict[str, ImageFont.ImageFont]:
    return {
        "title": _font(30, bold=True),
        "section": _font(20, bold=True),
        "label": _font(13, bold=True),
        "small": _font(16),
        "tiny": _font(12),
        "mono": _font(13),
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
