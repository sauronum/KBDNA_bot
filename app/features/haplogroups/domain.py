from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from g25_core.g25_engine import MISSING_GENOTYPES, RawCall, parse_raw_dna


DEFAULT_Y_SNP_REFERENCE_PATH = Path(__file__).resolve().parent / "data" / "yhaplo" / "isogg.2016.01.04.txt"


@dataclass(frozen=True)
class RawHaplogroupScan:
    haplogroup_type: str
    vendor_hint: str
    target_chromosomes: tuple[str, ...]
    chromosome_counts: dict[str, int]
    genotype_counts: dict[str, int]
    total_markers: int
    called_markers: int
    marker_examples: tuple[RawCall, ...]
    usable_markers: tuple[RawCall, ...]
    status: str
    note: str


@dataclass(frozen=True)
class YSnpReference:
    snp_name: str
    haplogroup: str
    position: int
    ancestral: str
    derived: str
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class YSnpCall:
    snp_name: str
    haplogroup: str
    position: int
    genotype: str
    ancestral: str
    derived: str
    state: str


@dataclass(frozen=True)
class YHaplogroupPrediction:
    haplogroup: str
    terminal_snp: str
    confidence: str
    positive_calls: tuple[YSnpCall, ...]
    negative_calls: tuple[YSnpCall, ...]
    ambiguous_calls: tuple[YSnpCall, ...]
    conflicting_positive_calls: tuple[YSnpCall, ...]
    lineage_counts: tuple[tuple[str, int], ...]
    matched_reference_markers: int
    note: str


@dataclass(frozen=True)
class ImportedHaplogroup:
    haplogroup_type: str
    haplogroup: str
    terminal_snp: str
    source: str
    confidence: str
    evidence: str
    positive_snp_count: int = 0
    matched_snp_count: int = 0
    lineage_votes: tuple[tuple[str, int], ...] = ()
    top_snps: tuple[str, ...] = ()
    conflicting_snps: tuple[str, ...] = ()


@dataclass(frozen=True)
class ImportedYStrProfile:
    marker_values: dict[str, list[int]]
    source: str
    marker_count: int


@dataclass(frozen=True)
class YStrDistanceResult:
    left_name: str
    right_name: str
    compared_markers: int
    distance: int
    differences: tuple[tuple[str, str, str, int], ...]


def scan_raw_haplogroup_markers(raw_path: Path, haplogroup_type: str) -> RawHaplogroupScan:
    normalized_type = haplogroup_type.strip().lower()
    if normalized_type in {"y", "y-dna", "ydna"}:
        label = "Y-DNA"
        target_chromosomes = ("Y", "24")
        low_threshold = 20
        usable_threshold = 200
    elif normalized_type in {"mt", "mtdna", "mtdna", "mt-dna"}:
        label = "mtDNA"
        target_chromosomes = ("M", "MT", "25", "26")
        low_threshold = 10
        usable_threshold = 100
    else:
        label = haplogroup_type
        target_chromosomes = ()
        low_threshold = 1
        usable_threshold = 1

    summary, calls = parse_raw_dna(raw_path)
    target_set = set(target_chromosomes)
    markers = [call for call in calls if call.chromosome in target_set]
    genotype_counts: dict[str, int] = {}
    for call in markers:
        genotype = call.genotype.strip().upper() or "<empty>"
        genotype_counts[genotype] = genotype_counts.get(genotype, 0) + 1
    usable = [
        call
        for call in markers
        if call.genotype.strip().upper() not in MISSING_GENOTYPES and len(call.genotype.strip()) in {1, 2}
    ]
    usable.sort(key=lambda call: (call.chromosome, call.position, call.rsid))

    if not target_chromosomes:
        status = "unsupported"
        note = "Этот тип haplogroup не поддержан."
    elif len(usable) >= usable_threshold:
        status = "markers present"
        note = "В raw есть достаточно маркеров для внешнего haplogroup predictor; локального дерева для финальной ветки пока нет."
    elif len(usable) >= low_threshold:
        status = "limited markers"
        note = "В raw есть маркеры, но их мало для уверенного локального определения ветки."
    elif usable:
        status = "very limited markers"
        note = "Найдено слишком мало маркеров; haplogroup по этому raw ненадёжен."
    else:
        status = "no markers"
        note = "В raw не найдено пригодных маркеров этого типа."

    return RawHaplogroupScan(
        haplogroup_type=label,
        vendor_hint=summary.vendor_hint,
        target_chromosomes=target_chromosomes,
        chromosome_counts=summary.chromosome_counts,
        genotype_counts=dict(sorted(genotype_counts.items(), key=lambda item: (-item[1], item[0]))),
        total_markers=len(markers),
        called_markers=len(usable),
        marker_examples=tuple(markers[:12]),
        usable_markers=tuple(usable),
        status=status,
        note=note,
    )


def parse_haplogroup_result_file(
    path: Path,
    *,
    original_file_name: str = "",
    reference_path: Path = DEFAULT_Y_SNP_REFERENCE_PATH,
) -> tuple[ImportedHaplogroup, ...]:
    text = _read_text_file(path)
    source = _infer_result_source(original_file_name or path.name)
    results: list[ImportedHaplogroup] = []
    seen: set[tuple[str, str, str]] = set()

    for result in _parse_haplogroups_from_tables(text, source):
        key = (result.haplogroup_type, result.haplogroup, result.terminal_snp)
        if key not in seen:
            results.append(result)
            seen.add(key)

    for result in _parse_haplogroups_from_lines(text, source):
        key = (result.haplogroup_type, result.haplogroup, result.terminal_snp)
        if key not in seen:
            results.append(result)
            seen.add(key)

    for result in _parse_y_snp_result_tables(text, source, reference_path):
        key = (result.haplogroup_type, result.haplogroup, result.terminal_snp)
        if key not in seen:
            results.append(result)
            seen.add(key)

    return tuple(results)


def parse_y_str_result_file(path: Path, *, original_file_name: str = "") -> ImportedYStrProfile | None:
    text = _read_text_file(path)
    source = _infer_result_source(original_file_name or path.name)
    for delimiter in ("\t", ",", ";"):
        try:
            rows = list(csv.reader(text.splitlines(), delimiter=delimiter))
        except csv.Error:
            continue
        if len(rows) < 2:
            continue
        headers = [cell.strip().strip('"') for cell in rows[0]]
        marker_indexes = [
            (index, _normalize_str_marker(header))
            for index, header in enumerate(headers)
            if _normalize_str_marker(header)
        ]
        if len(marker_indexes) < 5:
            continue
        for row in rows[1:]:
            markers: dict[str, list[int]] = {}
            for index, marker in marker_indexes:
                if index >= len(row):
                    continue
                values = _parse_str_values(row[index])
                if values:
                    markers[marker] = values
            if len(markers) >= 5:
                return ImportedYStrProfile(marker_values=markers, source=source, marker_count=len(markers))
    return None


def compare_y_str_profiles(
    left_name: str,
    left_markers: dict[str, list[int]],
    right_name: str,
    right_markers: dict[str, list[int]],
) -> YStrDistanceResult:
    differences: list[tuple[str, str, str, int]] = []
    distance = 0
    for marker in sorted(set(left_markers) & set(right_markers), key=_str_marker_sort_key):
        left_values = left_markers[marker]
        right_values = right_markers[marker]
        marker_distance = _str_marker_distance(left_values, right_values)
        if marker_distance:
            differences.append((marker, _format_str_values(left_values), _format_str_values(right_values), marker_distance))
        distance += marker_distance
    return YStrDistanceResult(
        left_name=left_name,
        right_name=right_name,
        compared_markers=len(set(left_markers) & set(right_markers)),
        distance=distance,
        differences=tuple(sorted(differences, key=lambda item: (-item[3], _str_marker_sort_key(item[0])))),
    )


def predict_y_haplogroup_from_raw(
    raw_path: Path,
    *,
    reference_path: Path = DEFAULT_Y_SNP_REFERENCE_PATH,
) -> YHaplogroupPrediction:
    _, calls = parse_raw_dna(raw_path)
    y_calls_by_position: dict[int, RawCall] = {}
    for call in calls:
        if call.chromosome in {"Y", "24"}:
            y_calls_by_position.setdefault(call.position, call)

    positive: list[YSnpCall] = []
    negative: list[YSnpCall] = []
    ambiguous: list[YSnpCall] = []
    matched = 0
    for marker in load_y_snp_reference(reference_path):
        raw_call = y_calls_by_position.get(marker.position)
        if raw_call is None:
            continue
        genotype = raw_call.genotype.strip().upper()
        if genotype in MISSING_GENOTYPES or not genotype:
            continue
        state = _classify_y_snp_state(genotype, marker)
        if state == "unmatched":
            continue
        matched += 1
        call = YSnpCall(
            snp_name=marker.snp_name,
            haplogroup=marker.haplogroup,
            position=marker.position,
            genotype=genotype,
            ancestral=marker.ancestral,
            derived=marker.derived,
            state=state,
        )
        if state == "positive":
            positive.append(call)
        elif state == "negative":
            negative.append(call)
        else:
            ambiguous.append(call)

    positive.sort(key=_ysnp_call_sort_key, reverse=True)
    negative.sort(key=_ysnp_call_sort_key, reverse=True)
    ambiguous.sort(key=_ysnp_call_sort_key, reverse=True)
    usable_positive = [call for call in positive if _is_predictive_haplogroup(call.haplogroup)]
    candidate_positive = [call for call in usable_positive if not _is_upstream_macro_haplogroup(call.haplogroup)]
    lineage_counts = _lineage_counts(candidate_positive)
    if not candidate_positive:
        return YHaplogroupPrediction(
            haplogroup="",
            terminal_snp="",
            confidence="no call",
            positive_calls=(),
            negative_calls=tuple(negative),
            ambiguous_calls=tuple(ambiguous),
            conflicting_positive_calls=(),
            lineage_counts=(),
            matched_reference_markers=matched,
            note="Не найдено usable non-upstream derived Y-SNP из локальной reference table.",
        )

    best_lineage = lineage_counts[0][0]
    supported_positive = [call for call in candidate_positive if _broad_lineage(call.haplogroup) == best_lineage]
    conflicting_positive = [call for call in candidate_positive if _broad_lineage(call.haplogroup) != best_lineage]
    best = supported_positive[0]
    support_count = len(supported_positive)
    conflict_count = sum(1 for call in negative if _same_broad_lineage(call.haplogroup, best.haplogroup))
    positive_conflict_count = len(conflicting_positive)
    if support_count >= 5 and conflict_count <= 2 and positive_conflict_count <= max(2, support_count // 3):
        confidence = "medium"
    elif support_count >= 2 and conflict_count <= 5:
        confidence = "low-medium"
    else:
        confidence = "low"

    return YHaplogroupPrediction(
        haplogroup=best.haplogroup,
        terminal_snp=best.snp_name,
        confidence=confidence,
        positive_calls=tuple(supported_positive),
        negative_calls=tuple(negative),
        ambiguous_calls=tuple(ambiguous),
        conflicting_positive_calls=tuple(conflicting_positive),
        lineage_counts=tuple(lineage_counts),
        matched_reference_markers=matched,
        note="Prediction основан на локальной ISOGG/Yhaplo 2016 reference table и autosomal raw Y-SNP; это не замена Big Y/YFull.",
    )


@lru_cache(maxsize=4)
def load_y_snp_reference(path: Path = DEFAULT_Y_SNP_REFERENCE_PATH) -> tuple[YSnpReference, ...]:
    if not path.exists():
        return ()
    markers: list[YSnpReference] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            snp_name = (row.get("SNP ") or row.get("SNP") or "").strip()
            aliases = _split_snp_aliases(row.get("Other Names ") or row.get("Other Names") or "")
            ref_snp = (row.get("RefSNP ID ") or row.get("RefSNP ID") or "").strip()
            if ref_snp:
                aliases = aliases + (ref_snp,)
            haplogroup = _clean_haplogroup(row.get("Haplogroup ") or row.get("Haplogroup") or "")
            position_text = (row.get("Y-position (GRCh37)") or "").strip()
            mutation = (row.get("Mutation") or "").strip().upper()
            if not snp_name or not haplogroup or "->" not in mutation:
                continue
            ancestral, _, derived = mutation.partition("->")
            if len(ancestral) != 1 or len(derived) != 1:
                continue
            try:
                position = int(position_text)
            except ValueError:
                continue
            markers.append(
                YSnpReference(
                    snp_name=snp_name,
                    haplogroup=haplogroup,
                    position=position,
                    ancestral=ancestral,
                    derived=derived,
                    aliases=aliases,
                )
            )
    return tuple(markers)


def _read_text_file(path: Path) -> str:
    data = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-16", "cp1251", "latin-1"):
        try:
            return data.decode(encoding).replace("\x00", "")
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", errors="ignore").replace("\x00", "")


def _parse_haplogroups_from_tables(text: str, source: str) -> list[ImportedHaplogroup]:
    results: list[ImportedHaplogroup] = []
    for delimiter in ("\t", ",", ";"):
        try:
            rows = list(csv.reader(text.splitlines(), delimiter=delimiter))
        except csv.Error:
            continue
        if len(rows) < 2:
            continue
        headers = [_normalize_label(cell) for cell in rows[0]]
        haplogroup_columns = [
            (index, _haplogroup_type_from_label(label))
            for index, label in enumerate(headers)
            if "haplogroup" in label and _haplogroup_type_from_label(label)
        ]
        if not haplogroup_columns:
            continue
        terminal_columns = {
            _haplogroup_type_from_label(label): index
            for index, label in enumerate(headers)
            if any(token in label for token in ("terminal", "snp", "marker")) and _haplogroup_type_from_label(label)
        }
        for row in rows[1:4]:
            for index, haplogroup_type in haplogroup_columns:
                if index >= len(row):
                    continue
                result = _build_imported_haplogroup(
                    haplogroup_type,
                    row[index],
                    source=source,
                    evidence=rows[0][index] if index < len(rows[0]) else "haplogroup column",
                    terminal_snp=row[terminal_columns[haplogroup_type]] if haplogroup_type in terminal_columns and terminal_columns[haplogroup_type] < len(row) else "",
                )
                if result is not None:
                    results.append(result)
    return results


def _parse_haplogroups_from_lines(text: str, source: str) -> list[ImportedHaplogroup]:
    results: list[ImportedHaplogroup] = []
    parsed_lines: list[tuple[str, str, str]] = []
    terminal_by_type: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        label, value = _split_label_value(line)
        if not label or not value:
            continue
        haplogroup_type = _haplogroup_type_from_label(_normalize_label(label))
        if not haplogroup_type:
            continue
        normalized_label = _normalize_label(label)
        if any(token in normalized_label for token in ("terminal", "snp", "marker")):
            terminal = _extract_terminal_snp(value)
            if terminal:
                terminal_by_type[haplogroup_type] = terminal
        if "haplogroup" not in normalized_label:
            continue
        parsed_lines.append((haplogroup_type, value, line[:180]))

    for haplogroup_type, value, evidence in parsed_lines:
        result = _build_imported_haplogroup(
            haplogroup_type,
            value,
            source=source,
            evidence=evidence,
            terminal_snp=terminal_by_type.get(haplogroup_type, ""),
        )
        if result is not None:
            results.append(result)
    return results


def _parse_y_snp_result_tables(text: str, source: str, reference_path: Path) -> list[ImportedHaplogroup]:
    results: list[ImportedHaplogroup] = []
    for delimiter in ("\t", ",", ";"):
        try:
            rows = list(csv.reader(text.splitlines(), delimiter=delimiter))
        except csv.Error:
            continue
        if len(rows) < 2:
            continue
        headers = [_normalize_label(cell) for cell in rows[0]]
        snp_index = _find_column(headers, ("snp name", "snp", "marker"))
        result_index = _find_column(headers, ("test result", "result", "status"))
        if snp_index is None or result_index is None:
            continue

        positive_names = []
        for row in rows[1:]:
            if snp_index >= len(row) or result_index >= len(row):
                continue
            if _is_positive_snp_result(row[result_index]):
                snp_name = row[snp_index].strip()
                if snp_name:
                    positive_names.append(snp_name)
        result = _import_y_haplogroup_from_positive_snps(positive_names, source, reference_path)
        if result is not None:
            results.append(result)
    return results


def _import_y_haplogroup_from_positive_snps(
    snp_names: list[str],
    source: str,
    reference_path: Path,
) -> ImportedHaplogroup | None:
    if not snp_names:
        return None
    reference_by_name = _y_snp_reference_by_name(reference_path)
    positive: list[YSnpCall] = []
    seen: set[tuple[str, str, int]] = set()
    for snp_name in snp_names:
        for marker in reference_by_name.get(_normalize_snp_name(snp_name), ()):
            key = (marker.snp_name, marker.haplogroup, marker.position)
            if key in seen:
                continue
            seen.add(key)
            positive.append(
                YSnpCall(
                    snp_name=marker.snp_name,
                    haplogroup=marker.haplogroup,
                    position=marker.position,
                    genotype="POS",
                    ancestral=marker.ancestral,
                    derived=marker.derived,
                    state="positive",
                )
            )

    positive.sort(key=_ysnp_call_sort_key, reverse=True)
    candidate_positive = [
        call
        for call in positive
        if _is_predictive_haplogroup(call.haplogroup) and not _is_upstream_macro_haplogroup(call.haplogroup)
    ]
    lineage_counts = _lineage_counts(candidate_positive)
    if not candidate_positive or not lineage_counts:
        return None

    best_lineage = lineage_counts[0][0]
    supported_positive = [call for call in candidate_positive if _broad_lineage(call.haplogroup) == best_lineage]
    best = supported_positive[0]
    evidence = (
        f"FTDNA-like SNP results; positive SNPs in file: {len(snp_names)}; "
        f"matched reference SNPs: {len(positive)}; lineage vote: "
        + ", ".join(f"{lineage}:{count}" for lineage, count in lineage_counts[:6])
    )
    conflicting_positive = [call for call in candidate_positive if _broad_lineage(call.haplogroup) != best_lineage]
    return ImportedHaplogroup(
        haplogroup_type="Y-DNA",
        haplogroup=best.haplogroup,
        terminal_snp=best.snp_name,
        source=source,
        confidence="snp-file",
        evidence=evidence,
        positive_snp_count=len(snp_names),
        matched_snp_count=len(positive),
        lineage_votes=tuple(lineage_counts),
        top_snps=tuple(f"{call.snp_name} {call.haplogroup}" for call in supported_positive[:12]),
        conflicting_snps=tuple(f"{call.snp_name} {call.haplogroup}" for call in conflicting_positive[:12]),
    )


@lru_cache(maxsize=4)
def _y_snp_reference_by_name(path: Path) -> dict[str, tuple[YSnpReference, ...]]:
    index: dict[str, list[YSnpReference]] = {}
    for marker in load_y_snp_reference(path):
        names = (marker.snp_name, *marker.aliases)
        for name in names:
            normalized = _normalize_snp_name(name)
            if normalized:
                index.setdefault(normalized, []).append(marker)
    return {name: tuple(markers) for name, markers in index.items()}


def _find_column(headers: list[str], candidates: tuple[str, ...]) -> int | None:
    for candidate in candidates:
        normalized_candidate = _normalize_label(candidate)
        for index, header in enumerate(headers):
            if header == normalized_candidate:
                return index
    for candidate in candidates:
        normalized_candidate = _normalize_label(candidate)
        for index, header in enumerate(headers):
            if normalized_candidate in header:
                return index
    return None


def _is_positive_snp_result(value: str) -> bool:
    clean = _normalize_label(value)
    return clean in {"positive", "derived", "plus", "pos", "yes", "true", "present", "tested positive"}


def _normalize_str_marker(value: str) -> str:
    clean = value.strip().strip('"').upper()
    clean = clean.replace(" ", "")
    if clean in {"CDY", "YCAII"}:
        return clean
    if re.fullmatch(r"(?:DYS|Y-GATA-|YCAII|CDY|DYF)[A-Z0-9-]+", clean):
        return clean
    return ""


def _parse_str_values(value: str) -> list[int]:
    clean = value.strip().strip('"').replace(" ", "")
    if not clean:
        return []
    values: list[int] = []
    for part in clean.split("-"):
        if not part:
            continue
        try:
            values.append(int(part))
        except ValueError:
            return []
    return values


def _format_str_values(values: list[int]) -> str:
    return "-".join(str(value) for value in values)


def _str_marker_distance(left_values: list[int], right_values: list[int]) -> int:
    left = sorted(left_values)
    right = sorted(right_values)
    distance = sum(abs(left[index] - right[index]) for index in range(min(len(left), len(right))))
    distance += abs(len(left) - len(right))
    return distance


def _str_marker_sort_key(marker: str) -> tuple[str, int, str]:
    match = re.search(r"(\d+)", marker)
    number = int(match.group(1)) if match else 99999
    prefix = marker[: match.start(1)] if match else marker
    return (prefix, number, marker)


def _split_label_value(line: str) -> tuple[str, str]:
    for separator in ("\t", ":", ";", ","):
        if separator in line:
            left, _, right = line.partition(separator)
            return left.strip(), right.strip()
    match = re.search(r"\bhaplogroup\b", line, flags=re.IGNORECASE)
    if match is None:
        return "", ""
    return line[: match.end()].strip(), line[match.end():].strip(" -:\t")


def _build_imported_haplogroup(
    haplogroup_type: str,
    raw_value: str,
    *,
    source: str,
    evidence: str,
    terminal_snp: str = "",
) -> ImportedHaplogroup | None:
    haplogroup = _extract_haplogroup_value(raw_value)
    if not haplogroup:
        return None
    terminal = _extract_terminal_snp(terminal_snp) or _terminal_from_haplogroup(haplogroup)
    return ImportedHaplogroup(
        haplogroup_type=haplogroup_type,
        haplogroup=haplogroup,
        terminal_snp=terminal,
        source=source,
        confidence="file-imported",
        evidence=evidence,
    )


def _extract_haplogroup_value(value: str) -> str:
    clean = value.strip().strip('"').strip("'")
    clean = re.sub(r"\s+", " ", clean)
    clean = re.sub(r"^(predicted|confirmed|terminal|haplogroup)\s+", "", clean, flags=re.IGNORECASE)
    match = re.search(r"\b[A-Z](?:[0-9][A-Za-z0-9]*)?(?:-[A-Z]{1,6}[0-9][A-Za-z0-9]*)?\b", clean)
    return match.group(0) if match else ""


def _extract_terminal_snp(value: str) -> str:
    match = re.search(r"\b(?:[A-Z]{1,6}-)?[A-Z]{1,6}[0-9][A-Za-z0-9]*\b", value.strip().upper())
    return match.group(0) if match else ""


def _terminal_from_haplogroup(value: str) -> str:
    if "-" not in value:
        return ""
    _, _, terminal = value.partition("-")
    return terminal.strip().upper()


def _split_snp_aliases(value: str) -> tuple[str, ...]:
    aliases = []
    for item in re.split(r"[,;/\s]+", value.strip()):
        clean = item.strip()
        if clean:
            aliases.append(clean)
    return tuple(dict.fromkeys(aliases))


def _normalize_snp_name(value: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "", value.strip().upper())


def _normalize_label(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.strip().lower()).strip()


def _haplogroup_type_from_label(label: str) -> str:
    if any(token in label for token in ("mtdna", "mt dna", "maternal", "mitochondrial")):
        return "mtDNA"
    if any(token in label for token in ("y dna", "ydna", "paternal", "y haplogroup")):
        return "Y-DNA"
    return ""


def _infer_result_source(file_name: str) -> str:
    clean = file_name.lower()
    if "ftdna" in clean or "family" in clean:
        return "FTDNA file"
    if "snp_results" in clean or "snp results" in clean:
        return "FTDNA SNP Results"
    if "yfull" in clean:
        return "YFull file"
    if "23andme" in clean or "23and" in clean:
        return "23andMe file"
    if "myheritage" in clean:
        return "MyHeritage file"
    return "uploaded file"


def _classify_y_snp_state(genotype: str, marker: YSnpReference) -> str:
    alleles = set(genotype)
    has_derived = marker.derived in alleles
    has_ancestral = marker.ancestral in alleles
    if has_derived and not has_ancestral:
        return "positive"
    if has_ancestral and not has_derived:
        return "negative"
    if has_derived and has_ancestral:
        return "ambiguous"
    return "unmatched"


def _clean_haplogroup(value: str) -> str:
    clean = value.strip()
    if "(" in clean:
        clean = clean.split("(", 1)[0].strip()
    return clean


def _is_predictive_haplogroup(value: str) -> bool:
    clean = value.strip().lower()
    if not clean:
        return False
    blocked_tokens = (
        "removed",
        "investigation",
        "notes",
        "private",
        "withdrawn",
        "provisional",
        "null",
        "not listed",
    )
    return not any(token in clean for token in blocked_tokens)


def _is_upstream_macro_haplogroup(value: str) -> bool:
    clean = value.strip().upper()
    if not clean:
        return True
    macro_labels = {
        "ROOT",
        "A0-T",
        "BT",
        "CT",
        "CF",
        "DE",
        "F",
        "GHIJK",
        "HIJK",
        "IJK",
        "IJ",
        "K",
        "K2",
        "K2B",
        "K2B1",
        "K2B2",
        "NO",
        "NO1",
        "NO2",
        "P",
        "P1",
        "LT",
    }
    return clean in macro_labels


def _same_broad_lineage(left: str, right: str) -> bool:
    return bool(left and right and left[0] == right[0])


def _broad_lineage(value: str) -> str:
    return value[:1] if value else ""


def _lineage_counts(calls: list[YSnpCall]) -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    for call in calls:
        lineage = _broad_lineage(call.haplogroup)
        if not lineage:
            continue
        counts[lineage] = counts.get(lineage, 0) + 1
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))


def _ysnp_call_sort_key(call: YSnpCall) -> tuple[int, int, str]:
    return (len(call.haplogroup), len(call.snp_name), call.snp_name)
