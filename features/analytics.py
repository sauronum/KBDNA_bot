from __future__ import annotations

import re
from collections.abc import Callable


KIT_GROUP_PREFIXES = (
    "G2A2B2A",
    "G2A2B",
    "G2A2",
    "G2A1A",
    "G2A1",
    "G2A",
    "C2",
    "E1B",
    "H1A",
    "I2A2B",
    "I2A2A",
    "I2A1A",
    "I2B",
    "I",
    "J2A1B",
    "J2A1",
    "J2A",
    "J2B",
    "J2",
    "J1",
    "L",
    "N1A1",
    "N1B",
    "O",
    "Q1A1B",
    "Q1A",
    "R1B1",
    "R1B",
    "R1A",
    "T1A",
    "T",
)

R1A_SUBCLADE_ROLLUP_LABELS = {
    "YP451": "YP451",
    "Y57": "Y57",
    "Z2123": "Z2123",
    "M458": "M458",
    "Z93": "Z93",
    "F1345": "F1345",
    "Y7094": "Y7094",
    "CTS1211": "CTS1211",
    "Y15121": "Y15121",
    "BY30764": "BY30764",
    "Z2125": "Z2125",
    "YP6420": "YP6420",
    "Z2122": "Z2122",
    "Z92": "Z92",
    "BY149647": "BY149647",
    "FT287785": "FT287785",
    "S23592": "S23592",
}

G2A1_SUBCLADE_ROLLUP_LABELS = {
    "Z31459": "Z31459",
    "Z7943": "Z7943",
    "FGC1160": "FGC1160",
    "Z6638": "Z6638+",
    "FGC1053": "FGC1053",
    "Z6654": "Z6652+",
    "FT103489": "FT103489",
    "Y36036": "Y36036",
    "Y177943": "Y177943",
    "FT187743": "FT187743",
    "GG330": "GG330",
    "FTB14662": "FTB14662",
    "FT23146": "FT23146",
    "BY144524": "BY144524",
    "FTB51554": "FTB51554",
    "Y173523": "Y173523",
}

G2A2_SUBCLADE_ROLLUP_LABELS = {
    "FT8419": "FT8419",
    "L1264": "L1264",
    "M406": "M406",
    "PH1780": "PH1780",
    "M485": "M485",
    "U1": "U1",
    "L1266": "L1266",
    "Z6922": "Z6922",
    "L13": "L13",
}

J2_SUBCLADE_ROLLUP_LABELS = {
    "Y30811": "Y30811",
    "BY139400": "Y30811",
    "Y99599": "Y30811",
    "V2639": "V2639",
    "M67": "M67*",
    "M12": "M12",
    "SK1313": "SK1313",
    "Z39973": "Z39973",
    "PH1795": "PH1795",
    "Z2229": "Z2229*",
    "Z6050": "Z6050",
    "M92": "M92",
    "M47": "M47",
}

MTDNA_KNOWN_MAJOR_HAPLOGROUPS = {
    "A", "B", "C", "D", "E", "F", "G", "H", "HV", "I", "J", "K", "L", "M",
    "N", "R", "R0", "T", "U", "V", "W", "X", "Y", "Z",
}


def normalize_text(value: str) -> str:
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


def is_placeholder(value: str) -> bool:
    stripped = str(value or "").strip()
    if not stripped:
        return True
    return bool(re.fullmatch(r"[-–—_~.\s]+", stripped))


def parse_group_path(text: str) -> tuple[str, str]:
    cleaned = " ".join(str(text or "").strip().split())
    if not cleaned:
        return "", ""

    match = re.match(r"^([A-Za-z][A-Za-z0-9-]*)\b\s*(.*)$", cleaned)
    if not match:
        return "", ""

    return match.group(1).strip(), match.group(2).strip()


def kit_value_starts_group(value: str) -> bool:
    normalized = " ".join(str(value or "").strip().split()).upper()
    if not normalized:
        return False
    return any(
        normalized == prefix
        or normalized.startswith(f"{prefix} ")
        or normalized.startswith(f"{prefix}-")
        for prefix in KIT_GROUP_PREFIXES
    )


def extract_group_from_kit(kit_value: str) -> tuple[str, str]:
    value = " ".join(str(kit_value or "").strip().split())
    if not value or not kit_value_starts_group(value):
        return "", ""
    return parse_group_path(value)


def extract_group_from_row(row: list[str], kit_idx: int | None) -> tuple[str, str]:
    if kit_idx is None or len(row) <= kit_idx:
        return "", ""
    return extract_group_from_kit(row[kit_idx])


def normalize_subclade_key(value: str) -> str:
    return " ".join(str(value or "").strip().upper().split())


def extract_terminal_snp(value: str) -> str:
    cleaned = " ".join(str(value or "").strip().split())
    if not cleaned:
        return ""

    parts = [part.strip() for part in cleaned.split(">") if part.strip() and part.strip() != "..."]
    for part in reversed(parts):
        base = re.split(r"\s*\(", part, maxsplit=1)[0].strip()
        if base and not re.fullmatch(r"[xX][A-Za-z0-9-]+", base):
            return base.split()[-1]

    tokens = re.findall(r"[A-Za-z][A-Za-z0-9-]*", cleaned)
    for token in reversed(tokens):
        if not re.fullmatch(r"[xX][A-Za-z0-9-]+", token):
            return token
    return ""


def extract_subclade_tokens(value: str) -> list[str]:
    cleaned = " ".join(str(value or "").strip().split())
    if not cleaned:
        return []

    tokens: list[str] = []
    for part in cleaned.split(">"):
        base = re.split(r"\s*\(", part, maxsplit=1)[0]
        base = base.replace("…", " ").replace("*", " ")
        for token in re.findall(r"[A-Za-z][A-Za-z0-9-]*", base):
            if not re.fullmatch(r"[xX][A-Za-z0-9-]+", token):
                tokens.append(token.upper())
    return tokens


def r1a_rollup_label(subclade: str) -> str:
    for token in reversed(extract_subclade_tokens(subclade)):
        if token in R1A_SUBCLADE_ROLLUP_LABELS:
            return R1A_SUBCLADE_ROLLUP_LABELS[token]
    return ""


def g2a1_rollup_label(subclade: str) -> str:
    for token in reversed(extract_subclade_tokens(subclade)):
        if token in G2A1_SUBCLADE_ROLLUP_LABELS:
            return G2A1_SUBCLADE_ROLLUP_LABELS[token]
    return ""


def g2a2_rollup_label(subclade: str) -> str:
    tokens = extract_subclade_tokens(subclade)
    if not tokens:
        return ""

    if "FT8419" in tokens or "Z724" in tokens:
        return "FT8419"
    if "PH1780" in tokens:
        return "PH1780"
    if "Z6922" in tokens:
        return "Z6922"
    if "L13" in tokens:
        return "L13"
    if "L1264" in tokens:
        return "L1264"
    if "L1266" in tokens:
        return "L1266"
    if "M406" in tokens:
        return "M406"
    if "M485" in tokens:
        return "M485"
    if "U1" in tokens:
        return "U1"

    for token in reversed(tokens):
        if token in G2A2_SUBCLADE_ROLLUP_LABELS:
            return G2A2_SUBCLADE_ROLLUP_LABELS[token]
    return ""


def j2_rollup_label(subclade: str) -> str:
    normalized_subclade = str(subclade or "").replace("Ì67", "M67").replace("М67", "M67")
    tokens = extract_subclade_tokens(normalized_subclade)
    if not tokens:
        return ""

    sk1313_markers = {
        "SK1313", "321250", "K17", "B91", "B239", "K78", "B114", "Y12599",
        "Y12618", "BY84499", "Y47679", "Y27964", "Y26651", "Y26654", "Y26650",
        "Y523131", "Y156116", "BY175871", "Y156120", "Y156154", "CLUSTER",
        "IN77268", "355992", "IN84061",
    }
    if any(token in sk1313_markers for token in tokens):
        return "SK1313"

    if any(token in {"Y30811", "BY139400", "Y99599"} for token in tokens):
        return "Y30811"

    for key in ("V2639", "Z39973", "PH1795", "Z2229", "Z6050", "M92", "M47", "SK1313", "M12", "M67"):
        if key in tokens:
            return J2_SUBCLADE_ROLLUP_LABELS[key]
    return ""


def first_letter_group(value: str) -> str:
    match = re.match(r"^([A-Za-z])", str(value or "").strip())
    return match.group(1).upper() if match else ""


def distribution_group_label(entry: dict[str, str]) -> str:
    label = " ".join((entry.get("general") or entry.get("haplo") or "").split())
    if not label:
        label = first_letter_group(entry.get("haplo", ""))

    normalized = label.upper()
    if normalized == "G2A1A":
        return "G2a1"
    if normalized in {"G2A2B", "G2A2B2A"}:
        return "G2a2"
    if normalized in {"I2A2B", "I2A1A", "I2A2A"}:
        return "I2"
    if normalized in {"J2A", "J2A1", "J2A1B", "J2B"}:
        return "J2"
    if normalized in {"N1A1", "N1B"}:
        return "N1"
    if normalized == "Q1A1B":
        return "Q1a"
    if normalized == "R1B1":
        return "R1b"
    if normalized == "T1A":
        return "T"
    return label


def subclade_distribution_label(entry: dict[str, str]) -> str:
    subclade = " ".join((entry.get("subclade") or "").split())
    group = distribution_group_label(entry)
    if group == "R1a":
        rolled_up = r1a_rollup_label(subclade)
        if rolled_up:
            return rolled_up
    if group == "G2a1":
        rolled_up = g2a1_rollup_label(subclade)
        if rolled_up:
            return rolled_up
    if group == "G2a2":
        rolled_up = g2a2_rollup_label(subclade)
        if rolled_up:
            return rolled_up
    if group == "I2":
        for token in reversed(extract_subclade_tokens(subclade)):
            if token in {"Y32090", "PH908", "Y16419", "A427"}:
                return token
    if group == "E1b":
        for token in reversed(extract_subclade_tokens(subclade)):
            if token in {"Z830", "M84", "V13", "M34"}:
                return token
    if group == "Q1a":
        tokens = extract_subclade_tokens(subclade)
        if "FT142706" in tokens or "BZ181" in tokens:
            return "BZ181"
    if group == "J1":
        if "P58" in extract_subclade_tokens(subclade):
            return "P58"
    if group == "J2":
        rolled_up = j2_rollup_label(subclade)
        if rolled_up:
            return rolled_up
    if group == "R1b":
        tokens = extract_subclade_tokens(subclade)
        if "BY120333" in tokens or "U106" in tokens:
            return "U106"
        if "Y91288" in tokens or "M478" in tokens:
            return "M478"
        if "Y4362" in tokens:
            return "Y4362"
        if "L584" in tokens:
            return "L584"
        if "Z2106" in tokens:
            return "Z2106"
        if "Z2105" in tokens:
            return "Z2105*"

    terminal = extract_terminal_snp(subclade)
    if terminal:
        if group == "I" and terminal == "M170":
            return "I*"
        if group == "J1" and terminal == "J-M267":
            return "J1*"
        return terminal

    haplo = " ".join((entry.get("haplo") or "").split())
    if haplo:
        if group == "J1" and haplo == "J-M267":
            return "J1*"
        return haplo
    return group


def _ordered_limited_items(counts: dict[str, int], top_n: int) -> tuple[list[tuple[str, int]], int]:
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    total = sum(value for _, value in ordered)
    if len(ordered) > top_n:
        top_items = ordered[:top_n]
        other_total = sum(value for _, value in ordered[top_n:])
        if other_total:
            top_items.append(("Прочее", other_total))
        ordered = top_items
    return ordered, total


def haplogroup_distribution(
    entries: list[dict[str, str]],
    mode: str,
    *,
    top_n: int = 10,
    emoji_getter: Callable[[str], str] | None = None,
) -> dict[str, object]:
    counts: dict[str, int] = {}
    if mode == "families":
        grouped_names: dict[str, set[str]] = {}
        for entry in entries:
            label = distribution_group_label(entry)
            if not label:
                continue
            grouped_names.setdefault(label, set()).add(normalize_text(entry["name"]))
        counts = {label: len(names) for label, names in grouped_names.items() if names}
    else:
        for entry in entries:
            label = distribution_group_label(entry)
            if not label:
                continue
            counts[label] = counts.get(label, 0) + 1

    ordered, total = _ordered_limited_items(counts, top_n)
    return {
        "mode": mode,
        "items": [
            {"label": label, "count": value, "emoji": emoji_getter(label) if emoji_getter else ""}
            for label, value in ordered
        ],
        "total": total,
    }


def available_haplogroups(entries: list[dict[str, str]], *, limit: int = 12) -> list[str]:
    counts: dict[str, int] = {}
    for entry in entries:
        label = distribution_group_label(entry)
        if label:
            counts[label] = counts.get(label, 0) + 1
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [label for label, _ in ordered[:limit]]


def subclade_distribution(
    entries: list[dict[str, str]],
    group: str,
    mode: str,
    *,
    top_n: int = 10,
    emoji_getter: Callable[[str], str] | None = None,
) -> dict[str, object]:
    group_entries = [entry for entry in entries if distribution_group_label(entry) == group]
    counts: dict[str, int] = {}
    if mode == "families":
        grouped_names: dict[str, set[str]] = {}
        for entry in group_entries:
            label = subclade_distribution_label(entry)
            if not label:
                continue
            grouped_names.setdefault(label, set()).add(normalize_text(entry["name"]))
        counts = {label: len(names) for label, names in grouped_names.items() if names}
    else:
        for entry in group_entries:
            label = subclade_distribution_label(entry)
            if not label:
                continue
            counts[label] = counts.get(label, 0) + 1

    ordered, total = _ordered_limited_items(counts, top_n)
    return {
        "group": group,
        "mode": mode,
        "items": [
            {"label": label, "count": value, "emoji": emoji_getter(group) if emoji_getter else ""}
            for label, value in ordered
        ],
        "total": total,
    }


def unique_navigation_counts(
    entries: list[dict[str, str]],
    key_getter: Callable[[dict[str, str]], str],
) -> dict[str, int]:
    grouped_names: dict[str, set[str]] = {}
    for entry in entries:
        label = key_getter(entry)
        if not label:
            continue
        name = " ".join((entry.get("name") or "").split())
        if is_placeholder(name):
            continue
        grouped_names.setdefault(label, set()).add(normalize_text(name))
    return {label: len(names) for label, names in grouped_names.items() if names}


def navigation_groups(entries: list[dict[str, str]], *, limit: int = 16) -> list[dict[str, object]]:
    counts = unique_navigation_counts(entries, distribution_group_label)
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [{"label": label, "count": count} for label, count in ordered[:limit]]


def navigation_subclades(entries: list[dict[str, str]], group: str, *, limit: int = 20) -> list[dict[str, object]]:
    group_entries = [entry for entry in entries if distribution_group_label(entry) == group]
    counts = unique_navigation_counts(group_entries, subclade_distribution_label)
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [{"label": label, "count": count} for label, count in ordered[:limit]]


def surnames_in_subclade(entries: list[dict[str, str]], group: str, subclade: str) -> list[str]:
    seen: set[str] = set()
    names: list[str] = []
    for entry in entries:
        if distribution_group_label(entry) != group:
            continue
        if subclade_distribution_label(entry) != subclade:
            continue
        name = " ".join((entry.get("name") or "").split())
        if is_placeholder(name):
            continue
        key = normalize_text(name)
        if key in seen:
            continue
        seen.add(key)
        names.append(name)
    return sorted(names, key=normalize_text)


def normalize_mtdna_haplogroup(value: str) -> str:
    cleaned = " ".join(str(value or "").replace("\u00a0", " ").split())
    if not cleaned:
        return ""
    cleaned = re.sub(r"(?i)\b(?:mt[-\s]?dna|mtdna|haplogroup|hg|мтднк|митоднк)\b", " ", cleaned)
    cleaned = cleaned.replace(";", " ").replace(",", " ")
    for match in re.finditer(r"\b[A-Za-z]{1,4}[0-9]?[A-Za-z0-9]*(?:[-+*]?)\b", cleaned):
        token = match.group(0).upper().rstrip("+")
        if is_placeholder(token) or len(token) > 20:
            continue
        if mtdna_major_haplogroup(token) in MTDNA_KNOWN_MAJOR_HAPLOGROUPS:
            return token
    return ""


def mtdna_major_haplogroup(label: str) -> str:
    label = str(label or "").upper().strip()
    if not label:
        return ""
    if label.startswith("HV"):
        return "HV"
    if label.startswith("R0"):
        return "R0"
    match = re.match(r"^([A-Z]+)", label)
    if not match:
        return label
    letters = match.group(1)
    return letters[:1] if letters else label


def mtdna_haplogroup_score(value: str) -> int:
    haplo = normalize_mtdna_haplogroup(value)
    if not haplo:
        return 0
    score = 1
    if len(haplo) > 1:
        score += 2
    if any(char.isdigit() for char in haplo):
        score += 4
    if haplo in MTDNA_KNOWN_MAJOR_HAPLOGROUPS:
        score -= 1
    return max(score, 1)


def mtdna_distribution(entries: list[dict[str, object]], kind: str, *, top_n: int = 10) -> dict[str, object]:
    counts: dict[str, int] = {}
    for entry in entries:
        haplo = str(entry["haplo"])
        label = mtdna_major_haplogroup(haplo) if kind == "groups" else haplo
        if not label:
            continue
        counts[label] = counts.get(label, 0) + 1

    ordered, total = _ordered_limited_items(counts, top_n)
    return {
        "kind": kind,
        "items": [{"label": label, "count": value, "emoji": ""} for label, value in ordered],
        "total": total,
    }


def mtdna_navigation_count_by_label(
    entries: list[dict[str, object]],
    label_getter: Callable[[dict[str, object]], str],
) -> dict[str, int]:
    grouped_names: dict[str, set[str]] = {}
    sample_counts: dict[str, int] = {}
    for index, entry in enumerate(entries, start=1):
        label = label_getter(entry)
        if not label:
            continue
        sample_counts[label] = sample_counts.get(label, 0) + 1
        name = " ".join(str(entry.get("name") or "").split())
        if is_placeholder(name):
            continue
        grouped_names.setdefault(label, set()).add(normalize_text(name))

    counts: dict[str, int] = {}
    for label, sample_count in sample_counts.items():
        names = grouped_names.get(label)
        counts[label] = len(names) if names else sample_count
    return counts


def mtdna_navigation_groups(
    entries: list[dict[str, object]],
    *,
    limit: int = 16,
    description_getter: Callable[[str], str] | None = None,
) -> list[dict[str, object]]:
    counts = mtdna_navigation_count_by_label(
        entries,
        lambda entry: mtdna_major_haplogroup(str(entry.get("haplo") or "")),
    )
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [
        {
            "label": label,
            "count": count,
            "description": description_getter(label) if description_getter else "",
        }
        for label, count in ordered[:limit]
    ]


def mtdna_navigation_subclades(
    entries: list[dict[str, object]],
    group: str,
    *,
    limit: int = 20,
    description_getter: Callable[[str], str] | None = None,
) -> list[dict[str, object]]:
    group = str(group or "").upper().strip()
    filtered = [
        entry
        for entry in entries
        if mtdna_major_haplogroup(str(entry.get("haplo") or "")) == group
    ]
    counts = mtdna_navigation_count_by_label(filtered, lambda entry: str(entry.get("haplo") or ""))
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [
        {
            "label": label,
            "count": count,
            "description": description_getter(label) if description_getter else "",
        }
        for label, count in ordered[:limit]
    ]


def mtdna_entries_in_subclade(entries: list[dict[str, object]], group: str, subclade: str) -> list[dict[str, object]]:
    group = str(group or "").upper().strip()
    normalized_subclade = normalize_mtdna_haplogroup(subclade)
    seen: set[tuple[str, str, tuple[str, ...]]] = set()
    result: list[dict[str, object]] = []
    for entry in entries:
        haplo = str(entry.get("haplo") or "")
        if mtdna_major_haplogroup(haplo) != group or haplo != normalized_subclade:
            continue
        name = " ".join(str(entry.get("name") or "").split())
        links = entry.get("links") or []
        link_keys = tuple(str(link.get("url") or "") for link in links if isinstance(link, dict))
        key = (normalize_text(name), haplo, link_keys)
        if key in seen:
            continue
        seen.add(key)
        result.append({"name": name, "haplo": haplo, "links": links})
    return sorted(
        result,
        key=lambda entry: (
            0 if " ".join(str(entry.get("name") or "").split()) else 1,
            normalize_text(str(entry.get("name") or "")),
            str(entry.get("haplo") or ""),
        ),
    )
