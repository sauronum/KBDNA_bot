from __future__ import annotations

import json
import struct
import zlib
from pathlib import Path
from typing import Iterable, Tuple

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


def _write_png(path: Path, width: int, height: int, rgb_data: bytearray) -> None:
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
    path.write_bytes(png)


def render_png(
    target: str,
    distance: float,
    sources: int,
    groups: Iterable[Tuple[str, float]],
    output_path: Path,
) -> None:
    group_list = list(groups)
    width = 982
    height = 86 + (len(group_list) * 28)
    buffer = bytearray(bytes(BG) * width * height)

    _draw_text(buffer, width, height, 16, 18, f"Target: {target}", FG, scale=2)
    meta = f"Distance: {distance:.6f} | Sources: {sources}"
    _draw_text(buffer, width, height, 16, 42, meta, SMALL, scale=2)

    label_x = 82
    bar_x = 282
    bar_w = 680
    start_y = 70
    row_gap = 28

    for index, (raw_name, value) in enumerate(group_list):
        y = start_y + (index * row_gap)
        percent = f"{value * 100.0:.1f}"
        _draw_text(buffer, width, height, 16, y + 2, percent, FG, scale=2)
        _draw_text(buffer, width, height, label_x, y + 2, display_name(raw_name), FG, scale=2)
        _put_rect(buffer, width, height, bar_x, y, bar_w, 12, BAR_BG)
        _put_rect(buffer, width, height, bar_x, y, int(bar_w * value), 12, BAR)

    _write_png(output_path, width, height, buffer)
