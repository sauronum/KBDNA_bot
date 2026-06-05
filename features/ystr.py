from __future__ import annotations

import csv
import re


def is_ystr_marker_header(header: str) -> bool:
    value = " ".join((header or "").split()).upper()
    if not value:
        return False
    prefixes = ("DYS", "DYF", "DYG", "YCA", "CDY", "H4", "Y-GATA", "GATA", "Y-GGAAT")
    return value.startswith(prefixes) or bool(re.search(r"\bDYS\d+", value))


def parse_ystr_marker_value(value: str) -> list[int]:
    if not value:
        return []
    return [int(item) for item in re.findall(r"\d+", str(value))]


def ystr_marker_distance(left: list[int], right: list[int]) -> int:
    if not left or not right:
        return 0
    if len(left) == 1 and len(right) == 1:
        return abs(left[0] - right[0])
    left_sorted = sorted(left)
    right_sorted = sorted(right)
    common = min(len(left_sorted), len(right_sorted))
    distance = sum(abs(left_sorted[index] - right_sorted[index]) for index in range(common))
    distance += abs(len(left_sorted) - len(right_sorted))
    return distance


def ystr_panel_label(common_markers: int) -> str:
    if common_markers >= 102:
        return "102/111"
    if common_markers >= 58:
        return "67"
    if common_markers >= 30:
        return "37"
    if common_markers >= 24:
        return "25"
    if common_markers >= 11:
        return "12"
    return str(common_markers)


def ystr_closeness_label(genetic_distance: int, common_markers: int) -> str:
    if common_markers < 11:
        return "мало данных"
    ratio = genetic_distance / max(common_markers, 1)
    if common_markers >= 58:
        if genetic_distance <= 3:
            return "очень близко"
        if genetic_distance <= 7:
            return "близко"
        if ratio <= 0.16:
            return "возможно родство"
        return "далеко"
    if common_markers >= 30:
        if genetic_distance <= 1:
            return "очень близко"
        if genetic_distance <= 4:
            return "близко"
        if ratio <= 0.18:
            return "возможно родство"
        return "далеко"
    if common_markers >= 24:
        if genetic_distance <= 1:
            return "очень близко"
        if genetic_distance <= 3:
            return "близко"
        if ratio <= 0.20:
            return "возможно родство"
        return "далеко"
    if genetic_distance == 0:
        return "совпадение, но маркеров мало"
    if genetic_distance <= 2:
        return "возможно близко, но маркеров мало"
    return "мало данных"


def normalize_ystr_sort_text(value: str) -> str:
    cleaned = str(value or "").strip().lower()
    cleaned = cleaned.translate(
        str.maketrans(
            {
                "ё": "е",
                "–": "-",
                "—": "-",
                "−": "-",
                "‑": "-",
                "ʼ": "'",
                "’": "'",
                "`": "'",
            }
        )
    )
    cleaned = re.sub(r"\s*-\s*", "-", cleaned)
    return " ".join(cleaned.split())


def ystr_haplogroup_match_key(entry: dict[str, object]) -> str:
    label = str(entry.get("display_general") or entry.get("general") or entry.get("haplo") or "")
    normalized = re.sub(r"[^A-Z0-9]", "", label.upper())
    if not normalized:
        return ""
    for prefix_len in (3, 2):
        prefix = normalized[:prefix_len]
        if re.match(r"^[A-Z]\d[A-Z]$", prefix) or re.match(r"^[A-Z]\d$", prefix):
            return prefix
    match = re.match(r"^[A-Z]+", normalized)
    return match.group(0)[:1] if match else ""


def compare_ystr_entries(left: dict[str, object], right: dict[str, object]) -> dict[str, object]:
    left_markers = left.get("markers") if isinstance(left.get("markers"), dict) else {}
    right_markers = right.get("markers") if isinstance(right.get("markers"), dict) else {}
    common = sorted(set(left_markers) & set(right_markers))
    differences: list[dict[str, object]] = []
    genetic_distance = 0
    for marker in common:
        left_value = left_markers.get(marker) or []
        right_value = right_markers.get(marker) or []
        distance = ystr_marker_distance(left_value, right_value)
        genetic_distance += distance
        if distance:
            differences.append({
                "marker": marker,
                "left": "-".join(str(item) for item in left_value),
                "right": "-".join(str(item) for item in right_value),
                "distance": distance,
            })
    common_count = len(common)
    return {
        "common": common_count,
        "panel": ystr_panel_label(common_count),
        "gd": genetic_distance,
        "differences": differences,
        "closeness": ystr_closeness_label(genetic_distance, common_count),
    }


def find_ystr_matches(
    query_entry: dict[str, object],
    entries: list[dict[str, object]],
    *,
    limit: int = 10,
    min_common: int = 8,
) -> list[dict[str, object]]:
    try:
        query_index = int(query_entry.get("entry_index"))
    except (TypeError, ValueError):
        query_index = -1
    query_haplo_key = ystr_haplogroup_match_key(query_entry)
    matches: list[dict[str, object]] = []
    for entry in entries:
        try:
            current_index = int(entry.get("entry_index"))
        except (TypeError, ValueError):
            current_index = -1
        if current_index == query_index:
            continue
        entry_haplo_key = ystr_haplogroup_match_key(entry)
        if query_haplo_key and entry_haplo_key and query_haplo_key != entry_haplo_key:
            continue
        comparison = compare_ystr_entries(query_entry, entry)
        common = int(comparison.get("common") or 0)
        if common < min_common:
            continue
        gd = int(comparison.get("gd") or 0)
        score = gd / max(common, 1)
        if common < 11:
            score += 0.12
        elif common < 24:
            score += 0.06
        elif common < 30:
            score += 0.03
        matches.append({
            "entry": entry,
            "comparison": comparison,
            "score": score,
        })

    matches.sort(key=lambda item: (
        float(item["score"]),
        int(item["comparison"].get("gd") or 0),
        -int(item["comparison"].get("common") or 0),
        normalize_ystr_sort_text(str(item["entry"].get("name") or "")),
    ))
    return matches[:limit]


def normalize_ystr_marker_name(marker: str) -> str:
    value = re.sub(r"[^A-Za-z0-9-]", "", marker.upper())
    aliases = {
        "DYS389I": "DYS389i",
        "DYS3891": "DYS389i",
        "DYS389II": "DYS389ii",
        "DYS3892": "DYS389ii",
        "YGATAH4": "Y-GATA-H4",
        "YGATAA10": "Y-GATA-A10",
        "YGGAAT1B07": "Y-GGAAT-1B07",
    }
    if value in aliases:
        return aliases[value]
    if value.startswith("DYS") or value.startswith("DYF") or value.startswith("DYG"):
        return value[:3] + value[3:].lower().replace("i", "i")
    if value.startswith("YCA"):
        return "YCAII" if value in {"YCAII", "YCA2"} else value
    if value == "CDY":
        return "CDY"
    return value


def adjust_ystr_dys389ii(markers: dict[str, list[int]]) -> dict[str, list[int]]:
    if "DYS389i" in markers and "DYS389ii" in markers and len(markers["DYS389i"]) == 1 and len(markers["DYS389ii"]) == 1:
        adjusted = markers["DYS389ii"][0] - markers["DYS389i"][0]
        if adjusted > 0:
            markers["DYS389ii"] = [adjusted]
    return markers


def make_uploaded_ystr_entry(markers: dict[str, list[int]], label: str = "Пользовательский STR-профиль") -> dict[str, object]:
    return {
        "entry_index": -1,
        "name": label,
        "haplo": "",
        "ancestor": "",
        "source": "Пользователь",
        "country": "",
        "general": "",
        "subclade": "",
        "display_general": "",
        "display_subclade": "",
        "markers": markers,
        "marker_count": len(markers),
    }


def parse_ystr_markers_from_text(text: str) -> dict[str, list[int]]:
    markers: dict[str, list[int]] = {}
    csv_rows = [
        [cell.strip().strip('"') for cell in row]
        for row in csv.reader(text.splitlines())
        if any(str(cell).strip() for cell in row)
    ]

    for row_index, header_row in enumerate(csv_rows[:-1]):
        marker_positions: list[tuple[int, str]] = []
        for col_index, cell in enumerate(header_row):
            if not is_ystr_marker_header(cell):
                continue
            marker_positions.append((col_index, normalize_ystr_marker_name(cell)))
        if len(marker_positions) < 4:
            continue

        for value_row in csv_rows[row_index + 1:]:
            row_markers: dict[str, list[int]] = {}
            for col_index, marker in marker_positions:
                if col_index >= len(value_row):
                    continue
                raw_value = value_row[col_index]
                if is_ystr_marker_header(raw_value):
                    continue
                values = parse_ystr_marker_value(raw_value)
                if values:
                    row_markers[marker] = values
            if len(row_markers) >= 8:
                return adjust_ystr_dys389ii(row_markers)

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = [part.strip() for part in re.split(r"[,;\t]", line) if part.strip()]
        if (
            len(parts) >= 2
            and is_ystr_marker_header(parts[0])
            and not is_ystr_marker_header(parts[1])
        ):
            marker_raw, value_raw = parts[0], parts[1]
        else:
            match = re.match(r"^([A-Za-z0-9-]+)\s*(?:=|:|\s)\s*([0-9][0-9\s./-]*)$", line)
            if not match:
                continue
            marker_raw, value_raw = match.group(1), match.group(2)
        marker = normalize_ystr_marker_name(marker_raw)
        if not is_ystr_marker_header(marker):
            continue
        values = parse_ystr_marker_value(value_raw)
        if values:
            markers[marker] = values

    return adjust_ystr_dys389ii(markers)
