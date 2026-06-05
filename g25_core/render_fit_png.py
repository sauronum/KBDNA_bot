from __future__ import annotations

import math
import json
import struct
import zlib
from pathlib import Path
from typing import Iterable, Tuple

from PIL import Image, ImageDraw, ImageFont

from .render_fit_svg import display_name, group_sort_key, VISUAL_GROUP_EXCLUSIONS


FONT_5X7 = {
    " ": [0, 0, 0, 0, 0, 0, 0],
    "%": [0b11001, 0b11010, 0b00100, 0b01000, 0b10110, 0b00110, 0],
    ".": [0, 0, 0, 0, 0, 0b01100, 0b01100],
    ":": [0, 0b01100, 0b01100, 0, 0b01100, 0b01100, 0],
    "-": [0, 0, 0, 0b11111, 0, 0, 0],
    "/": [0b00001, 0b00010, 0b00100, 0b01000, 0b10000, 0, 0],
    "0": [0b01110, 0b10001, 0b10011, 0b10101, 0b11001, 0b10001, 0b01110],
    "1": [0b00100, 0b01100, 0b00100, 0b00100, 0b00100, 0b00100, 0b01110],
    "2": [0b01110, 0b10001, 0b00001, 0b00010, 0b00100, 0b01000, 0b11111],
    "3": [0b11110, 0b00001, 0b00001, 0b01110, 0b00001, 0b00001, 0b11110],
    "4": [0b00010, 0b00110, 0b01010, 0b10010, 0b11111, 0b00010, 0b00010],
    "5": [0b11111, 0b10000, 0b10000, 0b11110, 0b00001, 0b00001, 0b11110],
    "6": [0b00110, 0b01000, 0b10000, 0b11110, 0b10001, 0b10001, 0b01110],
    "7": [0b11111, 0b00001, 0b00010, 0b00100, 0b01000, 0b01000, 0b01000],
    "8": [0b01110, 0b10001, 0b10001, 0b01110, 0b10001, 0b10001, 0b01110],
    "9": [0b01110, 0b10001, 0b10001, 0b01111, 0b00001, 0b00010, 0b11100],
    "A": [0b01110, 0b10001, 0b10001, 0b11111, 0b10001, 0b10001, 0b10001],
    "B": [0b11110, 0b10001, 0b10001, 0b11110, 0b10001, 0b10001, 0b11110],
    "C": [0b01110, 0b10001, 0b10000, 0b10000, 0b10000, 0b10001, 0b01110],
    "D": [0b11100, 0b10010, 0b10001, 0b10001, 0b10001, 0b10010, 0b11100],
    "E": [0b11111, 0b10000, 0b10000, 0b11110, 0b10000, 0b10000, 0b11111],
    "F": [0b11111, 0b10000, 0b10000, 0b11110, 0b10000, 0b10000, 0b10000],
    "G": [0b01110, 0b10001, 0b10000, 0b10111, 0b10001, 0b10001, 0b01110],
    "H": [0b10001, 0b10001, 0b10001, 0b11111, 0b10001, 0b10001, 0b10001],
    "I": [0b01110, 0b00100, 0b00100, 0b00100, 0b00100, 0b00100, 0b01110],
    "J": [0b00001, 0b00001, 0b00001, 0b00001, 0b10001, 0b10001, 0b01110],
    "K": [0b10001, 0b10010, 0b10100, 0b11000, 0b10100, 0b10010, 0b10001],
    "L": [0b10000, 0b10000, 0b10000, 0b10000, 0b10000, 0b10000, 0b11111],
    "M": [0b10001, 0b11011, 0b10101, 0b10101, 0b10001, 0b10001, 0b10001],
    "N": [0b10001, 0b11001, 0b10101, 0b10011, 0b10001, 0b10001, 0b10001],
    "O": [0b01110, 0b10001, 0b10001, 0b10001, 0b10001, 0b10001, 0b01110],
    "P": [0b11110, 0b10001, 0b10001, 0b11110, 0b10000, 0b10000, 0b10000],
    "Q": [0b01110, 0b10001, 0b10001, 0b10001, 0b10101, 0b10010, 0b01101],
    "R": [0b11110, 0b10001, 0b10001, 0b11110, 0b10100, 0b10010, 0b10001],
    "S": [0b01111, 0b10000, 0b10000, 0b01110, 0b00001, 0b00001, 0b11110],
    "T": [0b11111, 0b00100, 0b00100, 0b00100, 0b00100, 0b00100, 0b00100],
    "U": [0b10001, 0b10001, 0b10001, 0b10001, 0b10001, 0b10001, 0b01110],
    "V": [0b10001, 0b10001, 0b10001, 0b10001, 0b10001, 0b01010, 0b00100],
    "W": [0b10001, 0b10001, 0b10001, 0b10101, 0b10101, 0b10101, 0b01010],
    "X": [0b10001, 0b10001, 0b01010, 0b00100, 0b01010, 0b10001, 0b10001],
    "Y": [0b10001, 0b10001, 0b01010, 0b00100, 0b00100, 0b00100, 0b00100],
    "Z": [0b11111, 0b00001, 0b00010, 0b00100, 0b01000, 0b10000, 0b11111],
    "_": [0, 0, 0, 0, 0, 0, 0b11111],
}

BG = (78, 78, 78)
FG = (255, 255, 255)
SMALL = (232, 232, 232)
BAR = (255, 138, 31)
BAR_BG = (106, 106, 106)

ICON_COLORS = {
    "mountain": (121, 200, 120),
    "horse": (224, 176, 72),
    "temple": (220, 84, 64),
    "sun": (244, 205, 80),
    "leaf": (114, 205, 110),
    "wolf": (214, 214, 214),
    "snow": (180, 225, 255),
    "forest": (89, 181, 111),
}

ICON_PATTERNS = {
    "mountain": [
        "...#...",
        "..###..",
        ".#####.",
        "#######",
        "..###..",
        ".#####.",
        ".......",
    ],
    "horse": [
        "..###..",
        ".#####.",
        ".##.#..",
        ".#####.",
        "..#.##.",
        ".##.##.",
        "##...##",
    ],
    "temple": [
        "..###..",
        ".#####.",
        "#######",
        "..###..",
        "..###..",
        "#.#.#.#",
        "#######",
    ],
    "sun": [
        "..###..",
        ".#.#.#.",
        "#######",
        ".#####.",
        "#######",
        ".#.#.#.",
        "..###..",
    ],
    "leaf": [
        "...#...",
        "...#...",
        "..###..",
        ".#.#...",
        "...#.#.",
        "..#.#..",
        "...#...",
    ],
    "wolf": [
        ".#...#.",
        ".#####.",
        "#######",
        "#######",
        ".#####.",
        "..###..",
        "...#...",
    ],
    "snow": [
        "#..#..#",
        ".#.#.#.",
        "..###..",
        "#######",
        "..###..",
        ".#.#.#.",
        "#..#..#",
    ],
    "forest": [
        "...#...",
        "..###..",
        ".#####.",
        "...#...",
        "..###..",
        ".#####.",
        "..#.#..",
    ],
}

ICON_IDS = {
    "Maikop": "mountain",
    "KuraAraxes": "mountain",
    "Steppe": "horse",
    "Yamnaya": "horse",
    "Afanasievo": "horse",
    "Anatolia_BA": "temple",
    "Baltic_BA": "forest",
    "Khovsgol": "mountain",
    "AngaraRiver_BA": "snow",
    "Ulaanzukh": "horse",
    "Ulaanzhukh": "horse",
    "YellowRiver": "temple",
    "Yellow River": "temple",
    "Yellow_River": "temple",
    "YR": "temple",
    "BMAK": "sun",
    "Ulaanzuukh_culture_BA": "wolf",
    "Khovsgol_BA": "mountain",
    "Yellow_River_LN": "temple",
    "BMAC_or_Oxus_Civilization": "sun",
    "Helmandculture": "leaf",
    "Steppe_MLBA": "horse",
    "RUS_Angara_River_BA": "snow",
}


def load_groups(json_path: Path, zero_threshold: float) -> Tuple[str, float, int, list[Tuple[str, float]]]:
    data = json.loads(json_path.read_text(encoding="utf-8-sig"))
    groups = [
        (name, float(value))
        for name, value in data["groups"].items()
        if name not in VISUAL_GROUP_EXCLUSIONS and float(value) > zero_threshold
    ]
    groups.sort(key=lambda item: group_sort_key(item[0]))
    if not groups:
        raise ValueError(f"{json_path}: no non-zero groups to render.")
    return data["target"], float(data["distance"]), int(data["sources"]), groups


def _normalized_icon_id(raw_name: str) -> str | None:
    normalized = raw_name[: -len("_Cluster")] if raw_name.endswith("_Cluster") else raw_name
    return ICON_IDS.get(normalized)


def _put_rect(buffer: bytearray, width: int, height: int, x: int, y: int, rect_w: int, rect_h: int, color: tuple[int, int, int]) -> None:
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


def _draw_char(buffer: bytearray, width: int, height: int, x: int, y: int, char: str, color: tuple[int, int, int], scale: int = 2) -> None:
    glyph = FONT_5X7.get(char.upper(), FONT_5X7[" "])
    for gy, row in enumerate(glyph):
        for gx in range(5):
            if row & (1 << (4 - gx)):
                _put_rect(buffer, width, height, x + gx * scale, y + gy * scale, scale, scale, color)


def _draw_text(buffer: bytearray, width: int, height: int, x: int, y: int, text: str, color: tuple[int, int, int], scale: int = 2) -> None:
    cursor_x = x
    for char in text:
        _draw_char(buffer, width, height, cursor_x, y, char, color, scale)
        cursor_x += 6 * scale


def _text_width(text: str, scale: int = 2) -> int:
    return len(text) * 6 * scale


def _draw_icon(buffer: bytearray, width: int, height: int, x: int, y: int, raw_name: str, scale: int = 2) -> int:
    icon_id = _normalized_icon_id(raw_name)
    if not icon_id:
        return 0
    pattern = ICON_PATTERNS.get(icon_id)
    color = ICON_COLORS.get(icon_id, FG)
    if not pattern:
        return 0
    for py, row in enumerate(pattern):
        for px, cell in enumerate(row):
            if cell == '#':
                _put_rect(buffer, width, height, x + px * scale, y + py * scale, scale, scale, color)
    return len(pattern[0]) * scale


def _encode_png(width: int, height: int, rgb_data: bytearray) -> bytes:
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


def _write_png(path: Path, width: int, height: int, rgb_data: bytearray) -> None:
    png = _encode_png(width, height, rgb_data)
    path.write_bytes(png)


CYRILLIC_TO_LATIN = {
    "А": "A", "Б": "B", "В": "V", "Г": "G", "Д": "D", "Е": "E", "Ё": "E",
    "Ж": "ZH", "З": "Z", "И": "I", "Й": "Y", "К": "K", "Л": "L", "М": "M",
    "Н": "N", "О": "O", "П": "P", "Р": "R", "С": "S", "Т": "T", "У": "U",
    "Ф": "F", "Х": "KH", "Ц": "TS", "Ч": "CH", "Ш": "SH", "Щ": "SCH",
    "Ъ": "", "Ы": "Y", "Ь": "", "Э": "E", "Ю": "YU", "Я": "YA",
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def _ascii_text(text: str, fallback: str = "ITEM") -> str:
    transliterated = "".join(CYRILLIC_TO_LATIN.get(char, char if 32 <= ord(char) < 127 else " ") for char in text)
    collapsed = " ".join(transliterated.split())
    return collapsed or fallback


def _mix_color(left: tuple[int, int, int], right: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    clamped = max(0.0, min(1.0, t))
    return tuple(
        int(round(a + (b - a) * clamped))
        for a, b in zip(left, right)
    )


def render_stats_chart_png(
    title: str,
    series: Iterable[Tuple[str, int]],
    *,
    subtitle: str = "LAST 7 DAYS",
) -> bytes:
    points = list(series)
    if not points:
        raise ValueError("No series data to render.")

    dense = len(points) > 14
    width = 1080 if dense else max(760, 72 + len(points) * 92)
    height = 460 if dense else 300

    bg = (15, 23, 42)
    card = (17, 24, 39)
    fg = (248, 250, 252)
    muted = (148, 163, 184)
    grid = (39, 51, 71)
    accent_low = (59, 130, 246)
    accent_high = (249, 115, 22)
    accent_text = (15, 23, 42)

    buffer = bytearray(width * height * 3)
    _put_rect(buffer, width, height, 0, 0, width, height, bg)
    _put_rect(buffer, width, height, 18, 18, width - 36, height - 36, card)

    title_text = _ascii_text(title, fallback="STATS").upper()
    subtitle_text = _ascii_text(subtitle, fallback="LAST 7 DAYS").upper()
    _draw_text(buffer, width, height, 34, 34, title_text, fg, scale=3)
    _draw_text(buffer, width, height, 36, 68, subtitle_text, muted, scale=2)

    chart_x = 66
    chart_y = 118 if dense else 104
    chart_w = width - chart_x - 46
    chart_h = 240 if dense else 126
    baseline_y = chart_y + chart_h
    max_value = max(1, max(int(value) for _, value in points))

    for step in range(5):
        y = chart_y + int(chart_h * step / 4)
        _put_rect(buffer, width, height, chart_x, y, chart_w, 2, grid)

    bar_gap = 5 if dense else 18
    min_bar_w = 14 if dense else 34
    bar_w = max(min_bar_w, int((chart_w - bar_gap * (len(points) - 1)) / max(1, len(points))))
    step_w = bar_w + bar_gap
    value_scale = 1 if dense else 2
    label_scale = 1 if dense else 2

    for index, (label, value) in enumerate(points):
        x = chart_x + index * step_w
        bar_h = int(round(chart_h * (float(value) / max_value))) if max_value else 0
        bar_y = baseline_y - bar_h
        fill = _mix_color(accent_low, accent_high, float(value) / max_value if max_value else 0.0)
        _put_rect(buffer, width, height, x, bar_y, bar_w, bar_h, fill)

        value_text = str(int(value))
        value_x = x + max(0, (bar_w - _text_width(value_text, scale=value_scale)) // 2)
        value_y = max(chart_y - 22, bar_y - (10 if dense else 18))
        _draw_text(buffer, width, height, value_x, value_y, value_text, fg, scale=value_scale)

        label_text = _ascii_text(label, fallback="DAY").upper()
        label_x = x + max(0, (bar_w - _text_width(label_text, scale=label_scale)) // 2)
        _draw_text(buffer, width, height, label_x, baseline_y + 18, label_text, muted, scale=label_scale)

    return _encode_png(width, height, buffer)


def _compact_multi_label(raw_name: str) -> str:
    label = display_name(raw_name)
    overrides = {
        "BMAC or Oxus Civilization": "BMAC/Oxus",
        "Ulaanzuukh culture BA": "Ulaanzuukh BA",
        "RUS Angara River BA": "RUS Angara BA",
        "Yellow River LN": "Yellow River LN",
        "Anatolia BA": "Anatolia BA",
        "Baltic BA": "Baltic BA",
        "Khovsgol BA": "Khovsgol BA",
        "Steppe Sintashta": "Steppe Sint.",
    }
    if label in overrides:
        return overrides[label]
    compact = label.replace(" Civilization", "").replace(" culture ", " ").replace(" River ", " R ")
    if len(compact) <= 14:
        return compact
    words = compact.split()
    if len(words) >= 2:
        rebuilt = [words[0]]
        for word in words[1:]:
            candidate = " ".join(rebuilt + [word])
            if len(candidate) <= 14:
                rebuilt.append(word)
            else:
                rebuilt.append(word[:1] + ".")
        compact = " ".join(rebuilt)
    if len(compact) > 14:
        compact = compact[:14].rstrip(" .") + "."
    return compact


def _multi_heat_color(value: float, max_value: float) -> tuple[int, int, int]:
    if value <= 1e-12 or max_value <= 1e-12:
        return (72, 76, 96)
    t = min(1.0, value / max_value)
    return _mix_color((72, 76, 96), (85, 157, 255), math.sqrt(t))


def _single_source_label(raw_label: str) -> str:
    label = raw_label.split(":", 1)[0].strip()
    normalized = label.lower().replace(" ", "_")
    if normalized == "steppe_russia":
        return "Steppe / Russia"
    if normalized == "eba":
        return "EBA"
    return label or "My sources"


def _single_visible_groups(groups: Iterable[Tuple[str, float]], *, zero_threshold: float = 1e-9) -> list[Tuple[str, float]]:
    return [(name, float(value)) for name, value in groups if float(value) > zero_threshold]


def _multi_panel_title(panel_label: str) -> str:
    label = panel_label.split(":", 1)[0].strip()
    normalized = label.lower().replace(" ", "_")
    if normalized == "steppe_russia":
        return "STEPPE / RUSSIA"
    if normalized == "eba":
        return "EBA"
    return (display_name(label) if label else "MY SOURCES").replace("_", " ").upper()


def _multi_component_header(raw_name: str) -> str:
    return display_name(raw_name).replace("_", " ").strip().upper()


def _multi_font(size: int, *, bold: bool = False) -> ImageFont.ImageFont:
    candidates = [
        Path("C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf"),
        Path("C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default()


def _multi_text_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> int:
    return int(draw.textlength(text, font=font))


def _multi_ellipsize(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> str:
    if _multi_text_width(draw, text, font) <= max_width:
        return text
    suffix = "..."
    while text and _multi_text_width(draw, text + suffix, font) > max_width:
        text = text[:-1].rstrip()
    return text + suffix if text else suffix


def _multi_pil_heat_color(value: float, max_value: float) -> tuple[int, int, int]:
    if value <= 1e-12 or max_value <= 1e-12:
        return (28, 38, 52)
    t = min(1.0, value / max_value)
    return _mix_color((29, 47, 70), (82, 148, 242), math.sqrt(t))


def _distance_dataset_label(dataset_label: str) -> str:
    normalized = dataset_label.strip().lower()
    if normalized == "modern":
        return "MODERN"
    if normalized in {"ancestry", "origin", "ancient"}:
        return "ANCIENT"
    return (display_name(dataset_label) if dataset_label.strip() else "DISTANCE").replace("_", " ").upper()


def _distance_score_color(distance: float, min_distance: float, max_distance: float) -> tuple[int, int, int]:
    if max_distance <= min_distance:
        return (183, 211, 46)
    t = max(0.0, min(1.0, (distance - min_distance) / (max_distance - min_distance)))
    if t <= 0.58:
        return _mix_color((183, 211, 46), (213, 189, 44), t / 0.58)
    return _mix_color((213, 189, 44), (224, 142, 42), (t - 0.58) / 0.42)


def render_single_card_png(
    source_label: str,
    target: str,
    distance: float,
    sources: int,
    groups: Iterable[Tuple[str, float]],
    output_path: Path,
) -> None:
    group_list = _single_visible_groups(groups)
    display_labels = [display_name(name) for name, _ in group_list]
    max_label_chars = max((len(label) for label in display_labels), default=20)

    width = max(1160, 650 + int(max_label_chars * 12.4) + 460)
    row_h = 42
    table_y = 220
    footer = 34
    height = max(430, table_y + max(1, len(group_list)) * row_h + footer)
    bg = (18, 22, 29)
    card = (24, 29, 38)
    border = (66, 74, 86)
    fg = (248, 250, 252)
    muted = (154, 164, 178)
    accent = (255, 145, 36)
    bar_bg = (52, 59, 69)
    grid = (36, 43, 54)

    buffer = bytearray(bytes(bg) * width * height)
    _put_rect(buffer, width, height, 18, 18, width - 36, height - 36, card)

    _draw_text(buffer, width, height, 42, 42, f"Source: {_ascii_text(_single_source_label(source_label), 'SOURCE')}", fg, scale=2)

    top_y = 92
    target_x = 42
    distance_x = max(360, int(width * 0.34))
    sources_x = max(distance_x + 360, int(width * 0.74))
    _draw_text(buffer, width, height, target_x, top_y, "Target", muted, scale=2)
    _draw_text(buffer, width, height, target_x, top_y + 28, _ascii_text(target, "TARGET"), fg, scale=3)
    _draw_text(buffer, width, height, distance_x, top_y, "Distance", muted, scale=2)
    _draw_text(buffer, width, height, distance_x, top_y + 28, f"{distance * 100.0:.4f}%", accent, scale=3)
    _draw_text(buffer, width, height, distance_x + 230, top_y + 38, f"/ {distance:.6f}", muted, scale=2)
    _draw_text(buffer, width, height, sources_x, top_y, "Sources", muted, scale=2)
    _draw_text(buffer, width, height, sources_x, top_y + 28, str(int(sources)), accent, scale=3)

    _put_rect(buffer, width, height, 42, 184, width - 84, 2, border)

    name_x = 42
    percent_x = max(320, int(max_label_chars * 12.4) + 92)
    bar_x = percent_x + 124
    bar_w = max(360, width - bar_x - 54)
    if not group_list:
        _draw_text(buffer, width, height, name_x, table_y + 8, "No non-zero components", muted, scale=2)
    for index, (raw_name, value) in enumerate(group_list):
        y = table_y + index * row_h
        if index:
            _put_rect(buffer, width, height, name_x, y - 8, width - name_x - 42, 1, grid)
        icon_w = _draw_icon(buffer, width, height, name_x, y + 4, raw_name, scale=3)
        label_x = name_x + icon_w + (10 if icon_w else 0)
        _draw_text(buffer, width, height, label_x, y + 8, _ascii_text(display_name(raw_name), "SOURCE"), fg, scale=2)
        _draw_text(buffer, width, height, percent_x, y + 8, f"{value * 100.0:.1f}%", accent, scale=2)
        _put_rect(buffer, width, height, bar_x, y + 9, bar_w, 16, bar_bg)
        fill_w = int(round(bar_w * max(0.0, min(1.0, value))))
        if fill_w > 0:
            _put_rect(buffer, width, height, bar_x, y + 9, max(2, fill_w), 16, accent)

    _write_png(output_path, width, height, buffer)


def render_multi_heatmap_png(
    panel_label: str,
    rows: Iterable[dict[str, object]],
    columns: Iterable[str],
    average_distance: float,
    average_groups: dict[str, float],
    output_path: Path,
) -> None:
    row_list = list(rows)
    column_list = list(columns)
    if not row_list:
        raise ValueError("No target rows to render.")
    if not column_list:
        raise ValueError("No source groups to render.")

    title = _multi_panel_title(panel_label)
    row_labels = [str(row.get("target") or f"Target {index + 1}").strip().upper() for index, row in enumerate(row_list)]
    row_labels.append("AVERAGE")
    header_labels = [_multi_component_header(name) for name in column_list]

    column_count = len(column_list)
    compact_columns = True
    medium_columns = False
    header_font_size = 13 if compact_columns else (19 if medium_columns else 21)
    number_font_size = 17 if compact_columns else (20 if medium_columns else 21)
    fonts = {
        "title": _multi_font(36, bold=True),
        "meta": _multi_font(24, bold=True),
        "header": _multi_font(header_font_size, bold=True),
        "cell": _multi_font(22),
        "cell_bold": _multi_font(22, bold=True),
        "number": _multi_font(number_font_size),
        "number_bold": _multi_font(number_font_size, bold=True),
    }
    probe = Image.new("RGB", (1, 1))
    probe_draw = ImageDraw.Draw(probe)

    margin = 42
    target_min = 260 if compact_columns else 300
    target_max = 360 if compact_columns else 430
    target_col_w = max(target_min, min(target_max, max(_multi_text_width(probe_draw, label, fonts["cell_bold"]) for label in row_labels) + 34))
    distance_col_w = 188 if compact_columns else (204 if medium_columns else 220)
    value_min = 96 if compact_columns else (148 if medium_columns else 190)
    value_max = 106 if compact_columns else (206 if medium_columns else 320)
    value_pad = 0 if compact_columns else (26 if medium_columns else 42)
    value_col_w = max(value_min, min(value_max, max(_multi_text_width(probe_draw, label, fonts["header"]) for label in header_labels) + value_pad))
    row_h = 42
    header_h = 48
    top = 30
    header_y = 120
    table_y = header_y + header_h
    table_w = target_col_w + distance_col_w + len(column_list) * value_col_w
    width = margin * 2 + table_w
    height = table_y + (len(row_list) + 1) * row_h + 42

    bg = (11, 16, 24)
    panel = (19, 27, 38)
    header_fill = (28, 38, 52)
    target_fill = (31, 40, 50)
    distance_fill = (24, 31, 40)
    zero_fill = (25, 36, 50)
    average_label_fill = (42, 59, 78)
    average_fill = (30, 43, 58)
    grid = (58, 70, 86)
    border = (61, 76, 96)
    fg = (250, 250, 250)
    muted = (228, 230, 234)
    faint = (194, 200, 208)

    image = Image.new("RGB", (width, height), bg)
    draw = ImageDraw.Draw(image, "RGBA")
    draw.rounded_rectangle((14, 14, width - 14, height - 14), radius=22, fill=(*panel, 255), outline=(*border, 215), width=2)
    draw.text((margin + 8, top), title, fill=fg, font=fonts["title"])
    draw.text((margin + 8, top + 48), f"TARGETS: {len(row_list)}    SOURCES: {len(column_list)}", fill=muted, font=fonts["meta"])

    target_x = margin
    distance_x = target_x + target_col_w
    groups_x = distance_x + distance_col_w
    table_bottom = table_y + (len(row_list) + 1) * row_h
    draw.rounded_rectangle((target_x, header_y, target_x + table_w, table_bottom), radius=7, outline=(*border, 210), width=1)

    def cell_rect(x: int, y: int, w: int, h: int, fill: tuple[int, int, int]) -> None:
        draw.rectangle((x, y, x + w, y + h), fill=(*fill, 255))

    def draw_text_left(text: str, x: int, y: int, w: int, font: ImageFont.ImageFont, fill: tuple[int, int, int]) -> None:
        shown = _multi_ellipsize(draw, text, font, max(20, w - 26))
        bbox = draw.textbbox((0, 0), shown, font=font)
        text_h = bbox[3] - bbox[1]
        text_y = y + (row_h - text_h) // 2 - bbox[1]
        draw.text((x + 14, text_y), shown, fill=fill, font=font)

    def draw_text_center(text: str, x: int, y: int, w: int, font: ImageFont.ImageFont, fill: tuple[int, int, int]) -> None:
        shown = _multi_ellipsize(draw, text, font, max(20, w - 20))
        bbox = draw.textbbox((0, 0), shown, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        text_x = x + (w - text_w) // 2 - bbox[0]
        text_y = y + (row_h - text_h) // 2 - bbox[1]
        draw.text((text_x, text_y), shown, fill=fill, font=font)

    cell_rect(target_x, header_y, target_col_w, header_h, header_fill)
    cell_rect(distance_x, header_y, distance_col_w, header_h, header_fill)
    draw_text_left("TARGET", target_x, header_y + 3, target_col_w, fonts["header"], fg)
    draw_text_center("DISTANCE", distance_x, header_y + 3, distance_col_w, fonts["header"], fg)
    for index, label in enumerate(header_labels):
        x = groups_x + index * value_col_w
        cell_rect(x, header_y, value_col_w, header_h, header_fill)
        draw_text_center(label, x, header_y + 3, value_col_w, fonts["header"], fg)

    max_group_value = max(
        [float(average_groups.get(name, 0.0)) for name in column_list]
        + [float(row.get("groups", {}).get(name, 0.0)) for row in row_list for name in column_list]
        + [0.0]
    )

    def draw_row(row_index: int, label: str, distance: float, groups: dict[str, float], *, average: bool = False) -> None:
        y = table_y + row_index * row_h
        label_fill = average_label_fill if average else target_fill
        data_fill = average_fill if average else distance_fill
        text_font = fonts["cell_bold"] if average else fonts["cell"]
        number_font = fonts["number_bold"] if average else fonts["number"]
        cell_rect(target_x, y, target_col_w, row_h, label_fill)
        cell_rect(distance_x, y, distance_col_w, row_h, data_fill)
        draw_text_left(label, target_x, y, target_col_w, text_font, fg)
        draw_text_center(f"{distance:.7f}", distance_x, y, distance_col_w, number_font, fg if average else muted)
        for col_index, name in enumerate(column_list):
            x = groups_x + col_index * value_col_w
            value = float(groups.get(name, 0.0))
            if average:
                fill = average_fill
                text_fill = fg
                value_text = "—" if value <= 1e-12 else f"{value * 100.0:.1f}"
            else:
                fill = zero_fill if value <= 1e-12 else _multi_pil_heat_color(value, max_group_value)
                text_fill = faint if value <= 1e-12 else fg
                value_text = "—" if value <= 1e-12 else f"{value * 100.0:.1f}"
            cell_rect(x, y, value_col_w, row_h, fill)
            draw_text_center(value_text, x, y, value_col_w, number_font, text_fill)

    for index, row in enumerate(row_list):
        draw_row(
            index,
            row_labels[index],
            float(row.get("distance") or 0.0),
            {str(key): float(value) for key, value in dict(row.get("groups") or {}).items()},
        )
    draw_row(len(row_list), "AVERAGE", average_distance, average_groups, average=True)

    for x in [target_x, distance_x, groups_x, *[groups_x + index * value_col_w for index in range(1, len(column_list))], target_x + table_w]:
        draw.line((x, header_y, x, table_bottom), fill=(*grid, 210), width=1)
    for index in range(len(row_list) + 2):
        y = header_y + header_h if index == 0 else table_y + index * row_h
        if y <= table_bottom:
            draw.line((target_x, y, target_x + table_w, y), fill=(*grid, 190), width=1)
    average_y = table_y + len(row_list) * row_h
    draw.line((target_x, average_y, target_x + table_w, average_y), fill=(105, 124, 148, 230), width=2)

    image.save(output_path, format="PNG")


def render_png(
    target: str,
    distance: float,
    sources: int,
    groups: Iterable[Tuple[str, float]],
    output_path: Path,
) -> None:
    group_list = list(groups)
    display_labels = [display_name(name).upper() for name, _ in group_list]
    max_label_chars = max((len(label) for label in display_labels), default=0)

    width = max(982, 360 + int(max_label_chars * 12.4) + 680)
    height = 86 + (len(group_list) * 28)
    buffer = bytearray(bytes(BG) * width * height)

    _draw_text(buffer, width, height, 16, 18, f"Target: {target}", FG, scale=2)
    meta = f"Distance: {distance:.6f} | Sources: {sources}"
    _draw_text(buffer, width, height, 16, 42, meta, SMALL, scale=2)

    percent_x = 16
    text_x = 104
    label_area_w = max(220, int(max_label_chars * 12.4))
    bar_x = text_x + label_area_w + 18
    bar_w = max(520, width - bar_x - 20)
    start_y = 70
    row_gap = 28

    for index, (raw_name, value) in enumerate(group_list):
        y = start_y + (index * row_gap)
        percent = f"{value * 100.0:.1f}"
        _draw_text(buffer, width, height, percent_x, y + 2, percent, FG, scale=2)
        _draw_text(buffer, width, height, text_x, y + 2, display_name(raw_name), FG, scale=2)
        _put_rect(buffer, width, height, bar_x, y, bar_w, 12, BAR_BG)
        _put_rect(buffer, width, height, bar_x, y, int(bar_w * value), 12, BAR)

    _write_png(output_path, width, height, buffer)


def render_distance_png(
    dataset_label: str,
    target: str,
    matches: Iterable[Tuple[float, str]],
    output_path: Path,
) -> None:
    match_list = list(matches)
    if not match_list:
        raise ValueError("No matches to render.")

    dataset_text = _distance_dataset_label(dataset_label)
    target_text = str(target or "Target").strip().upper()
    label_texts = [display_name(name).replace("_", " ").upper() for _, name in match_list]
    value_texts = [f"{distance:.7f}" for distance, _ in match_list]
    rank_texts = [f"{index}." for index in range(1, len(match_list) + 1)]

    fonts = {
        "title": _multi_font(34, bold=True),
        "dataset": _multi_font(20, bold=True),
        "meta": _multi_font(20, bold=True),
        "rank": _multi_font(20, bold=True),
        "value": _multi_font(20, bold=True),
        "label": _multi_font(20, bold=True),
    }
    probe = Image.new("RGB", (1, 1))
    probe_draw = ImageDraw.Draw(probe)

    margin = 42
    rank_w = max(48, max(_multi_text_width(probe_draw, rank, fonts["rank"]) for rank in rank_texts) + 22)
    value_w = max(154, max(_multi_text_width(probe_draw, value, fonts["value"]) for value in value_texts) + 34)
    label_w = max(470, min(760, max(_multi_text_width(probe_draw, label, fonts["label"]) for label in label_texts) + 34))
    row_h = 31
    row_gap = 4
    table_y = 144
    table_w = rank_w + value_w + label_w
    width = max(760, margin * 2 + table_w)
    height = max(360, table_y + len(match_list) * (row_h + row_gap) + 42)

    bg = (11, 16, 24)
    panel = (19, 27, 38)
    row_fill = (30, 41, 59)
    rank_fill = (28, 38, 52)
    grid = (58, 70, 86)
    border = (61, 76, 96)
    fg = (250, 250, 250)
    muted = (223, 226, 230)
    accent = (183, 211, 46)
    score_text = (36, 38, 30)

    image = Image.new("RGB", (width, height), bg)
    draw = ImageDraw.Draw(image, "RGBA")
    draw.rounded_rectangle((14, 14, width - 14, height - 14), radius=22, fill=(*panel, 255), outline=(*border, 215), width=2)
    draw.text((margin + 8, 32), "DISTANCE PCA", fill=fg, font=fonts["title"])
    draw.text((margin + 10, 78), dataset_text, fill=accent, font=fonts["dataset"])
    draw.text((margin + 10, 104), f"TARGET: {target_text}", fill=muted, font=fonts["meta"])

    rank_x = margin
    value_x = rank_x + rank_w
    label_x = value_x + value_w
    min_distance = min(float(distance) for distance, _ in match_list)
    max_distance = max(float(distance) for distance, _ in match_list)

    def draw_center(text: str, x: int, y: int, w: int, font: ImageFont.ImageFont, fill: tuple[int, int, int]) -> None:
        shown = _multi_ellipsize(draw, text, font, max(20, w - 16))
        bbox = draw.textbbox((0, 0), shown, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        draw.text((x + (w - text_w) // 2 - bbox[0], y + (row_h - text_h) // 2 - bbox[1]), shown, fill=fill, font=font)

    def draw_left(text: str, x: int, y: int, w: int, font: ImageFont.ImageFont, fill: tuple[int, int, int]) -> None:
        shown = _multi_ellipsize(draw, text, font, max(20, w - 22))
        bbox = draw.textbbox((0, 0), shown, font=font)
        text_h = bbox[3] - bbox[1]
        draw.text((x + 12, y + (row_h - text_h) // 2 - bbox[1]), shown, fill=fill, font=font)

    for index, ((distance, _), rank, value, label) in enumerate(zip(match_list, rank_texts, value_texts, label_texts)):
        y = table_y + index * (row_h + row_gap)
        color = _distance_score_color(float(distance), min_distance, max_distance)
        draw.rectangle((rank_x, y, rank_x + rank_w, y + row_h), fill=(*rank_fill, 255))
        draw.rectangle((value_x, y, value_x + value_w, y + row_h), fill=(*color, 255))
        draw.rectangle((label_x, y, label_x + label_w, y + row_h), fill=(*row_fill, 255))
        draw_center(rank, rank_x, y, rank_w, fonts["rank"], muted)
        draw_center(value, value_x, y, value_w, fonts["value"], score_text)
        draw_left(label, label_x, y, label_w, fonts["label"], fg)
        draw.line((rank_x, y + row_h, label_x + label_w, y + row_h), fill=(*grid, 185), width=1)
        draw.line((value_x, y, value_x, y + row_h), fill=(*grid, 185), width=1)
        draw.line((label_x, y, label_x, y + row_h), fill=(*grid, 185), width=1)

    image.save(output_path, format="PNG")
