from __future__ import annotations

import argparse
from collections import Counter
import csv
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import unicodedata
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np


K36_COMPONENTS: Tuple[str, ...] = (
    "Amerindian",
    "Arabian",
    "Armenian",
    "Basque",
    "Central_African",
    "Central_Euro",
    "East_African",
    "East_Asian",
    "East_Balkan",
    "East_Central_Asian",
    "East_Central_Euro",
    "East_Med",
    "Eastern_Euro",
    "Fennoscandian",
    "French",
    "Iberian",
    "Indo-Chinese",
    "Italian",
    "Malayan",
    "Near_Eastern",
    "North_African",
    "North_Atlantic",
    "North_Caucasian",
    "North_Sea",
    "Northeast_African",
    "Oceanian",
    "Omotic",
    "Pygmy",
    "Siberian",
    "South_Asian",
    "South_Central_Asian",
    "South_Chinese",
    "Volga-Ural",
    "West_African",
    "West_Caucasian",
    "West_Med",
)

AUTOSOMES = {str(i) for i in range(1, 23)}
MISSING_GENOTYPES = {"", "--", "00", "0", "-", "NC", "NN", "??"}


@dataclass
class RawCall:
    rsid: str
    chromosome: str
    position: int
    genotype: str


@dataclass
class RawSummary:
    file: str
    vendor_hint: str
    total_rows: int
    autosomal_rows: int
    autosomal_called_rows: int
    skipped_rows: int
    call_rate: float
    chromosome_counts: dict


@dataclass
class K36Summary:
    file: str
    detected_format: str
    sample_name: str
    component_count: int
    total: float
    values: Tuple[float, ...]
    non_zero_components: dict
    canonical_line: str


@dataclass
class G25Entry:
    name: str
    coords: Tuple[float, ...]


SCRIPT_ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT_ROOT = SCRIPT_ROOT / "output"
DEFAULT_DATA_ROOT = SCRIPT_ROOT / "data"
DEFAULT_BOOTSTRAP_GLOBAL_DIR = DEFAULT_DATA_ROOT / "bootstrap_global"
DEFAULT_SUPPORT_DATA_DIR = DEFAULT_DATA_ROOT / "support"
DEFAULT_VERIFIED_BACKBONE_DIR = DEFAULT_DATA_ROOT / "verified_backbone"
DEFAULT_VERIFIED_VAHADUO_DIR = DEFAULT_VERIFIED_BACKBONE_DIR / "downloads" / "vahaduo"
DEFAULT_LOCAL_CUSTOM_DIR = DEFAULT_DATA_ROOT / "local_custom"
DEFAULT_BOOTSTRAP_MODERN_GLOBAL_REF = DEFAULT_BOOTSTRAP_GLOBAL_DIR / "Modern_Global_v1.txt"
DEFAULT_BOOTSTRAP_MODERN_GLOBAL_MANIFEST = DEFAULT_BOOTSTRAP_GLOBAL_DIR / "Modern_Global_v1_manifest.tsv"
DEFAULT_BOOTSTRAP_ANCIENT_GLOBAL_REF = DEFAULT_BOOTSTRAP_GLOBAL_DIR / "Ancient_Global_v1.txt"
DEFAULT_BOOTSTRAP_ANCIENT_GLOBAL_MANIFEST = DEFAULT_BOOTSTRAP_GLOBAL_DIR / "Ancient_Global_v1_manifest.tsv"
DEFAULT_MODERN_GLOBAL_REF = DEFAULT_VERIFIED_BACKBONE_DIR / "harmonized" / "Modern_Verified_Backbone_v1.txt"
DEFAULT_MODERN_GLOBAL_MANIFEST = DEFAULT_VERIFIED_BACKBONE_DIR / "manifests" / "Modern_Verified_Backbone_v1_manifest.tsv"
DEFAULT_ANCIENT_GLOBAL_REF = DEFAULT_VERIFIED_BACKBONE_DIR / "harmonized" / "Ancient_Verified_Backbone_v1.txt"
DEFAULT_ANCIENT_GLOBAL_MANIFEST = DEFAULT_VERIFIED_BACKBONE_DIR / "manifests" / "Ancient_Verified_Backbone_v1_manifest.tsv"
DEFAULT_VERIFIED_REGIONAL_DIR = DEFAULT_VERIFIED_BACKBONE_DIR / "regions"
DEFAULT_VERIFIED_WEST_EURASIA_DIR = DEFAULT_VERIFIED_REGIONAL_DIR / "west_eurasia"
DEFAULT_VERIFIED_MODERN_WEST_REF = DEFAULT_VERIFIED_WEST_EURASIA_DIR / "Modern_WestEurasia_Verified_v1.txt"
DEFAULT_VERIFIED_MODERN_WEST_MANIFEST = DEFAULT_VERIFIED_WEST_EURASIA_DIR / "Modern_WestEurasia_Verified_v1_manifest.tsv"
DEFAULT_VERIFIED_ANCIENT_WEST_REF = DEFAULT_VERIFIED_WEST_EURASIA_DIR / "Ancient_WestEurasia_Verified_v1.txt"
DEFAULT_VERIFIED_ANCIENT_WEST_MANIFEST = DEFAULT_VERIFIED_WEST_EURASIA_DIR / "Ancient_WestEurasia_Verified_v1_manifest.tsv"
DEFAULT_VERIFIED_VOLGA_URAL_DIR = DEFAULT_VERIFIED_REGIONAL_DIR / "volga_ural_north_eurasia"
DEFAULT_VERIFIED_MODERN_VOLGA_URAL_REF = DEFAULT_VERIFIED_VOLGA_URAL_DIR / "Modern_VolgaUralNorthEurasia_Verified_v1.txt"
DEFAULT_VERIFIED_MODERN_VOLGA_URAL_MANIFEST = DEFAULT_VERIFIED_VOLGA_URAL_DIR / "Modern_VolgaUralNorthEurasia_Verified_v1_manifest.tsv"
DEFAULT_VERIFIED_ANCIENT_VOLGA_URAL_REF = DEFAULT_VERIFIED_VOLGA_URAL_DIR / "Ancient_VolgaUralNorthEurasia_Verified_v1.txt"
DEFAULT_VERIFIED_ANCIENT_VOLGA_URAL_MANIFEST = DEFAULT_VERIFIED_VOLGA_URAL_DIR / "Ancient_VolgaUralNorthEurasia_Verified_v1_manifest.tsv"
DEFAULT_VERIFIED_SOUTH_ASIA_DIR = DEFAULT_VERIFIED_REGIONAL_DIR / "south_asia"
DEFAULT_VERIFIED_MODERN_SOUTH_ASIA_REF = DEFAULT_VERIFIED_SOUTH_ASIA_DIR / "Modern_SouthAsia_Verified_v1.txt"
DEFAULT_VERIFIED_MODERN_SOUTH_ASIA_MANIFEST = DEFAULT_VERIFIED_SOUTH_ASIA_DIR / "Modern_SouthAsia_Verified_v1_manifest.tsv"
DEFAULT_VERIFIED_ANCIENT_SOUTH_ASIA_REF = DEFAULT_VERIFIED_SOUTH_ASIA_DIR / "Ancient_SouthAsia_Verified_v1.txt"
DEFAULT_VERIFIED_ANCIENT_SOUTH_ASIA_MANIFEST = DEFAULT_VERIFIED_SOUTH_ASIA_DIR / "Ancient_SouthAsia_Verified_v1_manifest.tsv"
DEFAULT_LEGACY_RUNTIME_DIR = SCRIPT_ROOT / "archive" / "legacy_runtime_assets" / "panels"
DEFAULT_MODERN_WEST_REF = DEFAULT_LEGACY_RUNTIME_DIR / "Modern_WestEurasia_v1.txt"
DEFAULT_MODERN_WEST_MANIFEST = DEFAULT_LEGACY_RUNTIME_DIR / "Modern_WestEurasia_v1_manifest.tsv"
DEFAULT_ANCIENT_WEST_REF = DEFAULT_LEGACY_RUNTIME_DIR / "Ancient_WestEurasia_v1.txt"
DEFAULT_ANCIENT_WEST_MANIFEST = DEFAULT_LEGACY_RUNTIME_DIR / "Ancient_WestEurasia_v1_manifest.tsv"
DEFAULT_BACKBONE_METHOD_DIR = SCRIPT_ROOT / "backbone_method_v1"
DEFAULT_BACKBONE_MACROREGION_REGISTRY = DEFAULT_BACKBONE_METHOD_DIR / "macroregion_registry.tsv"
DEFAULT_BACKBONE_ROUTING_POLICY = DEFAULT_BACKBONE_METHOD_DIR / "routing_policy.json"


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def normalize_chromosome(value: str) -> str:
    chrom = value.strip()
    if chrom.lower().startswith("chr"):
        chrom = chrom[3:]
    chrom = chrom.upper()
    if chrom == "MT":
        return "M"
    return chrom


def normalize_genotype(value: str) -> str:
    genotype = value.strip().replace("/", "").replace(" ", "").upper()
    return genotype


def split_row(line: str) -> List[str]:
    if "\t" in line:
        return next(csv.reader([line.rstrip("\n")], delimiter="\t"))
    if "," in line:
        return next(csv.reader([line.rstrip("\n")], delimiter=","))
    return re.split(r"\s+", line.strip())


def infer_vendor_hint(comments: Iterable[str], data_width: Optional[int]) -> str:
    joined = " ".join(comments).lower()
    if "23andme" in joined:
        return "23andMe"
    if "ancestry" in joined:
        return "AncestryDNA"
    if "family tree dna" in joined or "ftdna" in joined:
        return "FTDNA"
    if "myheritage" in joined:
        return "MyHeritage"
    if data_width == 5:
        return "Ancestry-like"
    if data_width == 4:
        return "23andMe/FTDNA/MyHeritage-like"
    return "unknown"


def parse_raw_dna(path: Path) -> Tuple[RawSummary, List[RawCall]]:
    comments: List[str] = []
    calls: List[RawCall] = []
    chromosome_counts = {}
    total_rows = 0
    autosomal_rows = 0
    autosomal_called_rows = 0
    skipped_rows = 0
    data_width: Optional[int] = None
    header_seen = False

    for raw_line in read_text(path).splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            comments.append(line)
            continue

        fields = split_row(line)
        if not fields:
            continue

        lower_fields = [field.lower() for field in fields]
        if not header_seen and lower_fields[:3] == ["rsid", "chromosome", "position"]:
            header_seen = True
            data_width = len(fields)
            continue

        header_seen = True
        total_rows += 1
        data_width = len(fields)

        try:
            if len(fields) >= 5:
                rsid, chromosome, position, allele1, allele2 = fields[:5]
                genotype = normalize_genotype(allele1 + allele2)
            elif len(fields) >= 4:
                rsid, chromosome, position, genotype = fields[:4]
                genotype = normalize_genotype(genotype)
            else:
                skipped_rows += 1
                continue

            chromosome = normalize_chromosome(chromosome)
            position_int = int(position)
        except ValueError:
            skipped_rows += 1
            continue

        call = RawCall(
            rsid=rsid,
            chromosome=chromosome,
            position=position_int,
            genotype=genotype,
        )
        calls.append(call)
        chromosome_counts[chromosome] = chromosome_counts.get(chromosome, 0) + 1

        if chromosome in AUTOSOMES:
            autosomal_rows += 1
            if genotype not in MISSING_GENOTYPES:
                autosomal_called_rows += 1

    call_rate = 0.0
    if autosomal_rows:
        call_rate = autosomal_called_rows / autosomal_rows

    summary = RawSummary(
        file=str(path),
        vendor_hint=infer_vendor_hint(comments, data_width),
        total_rows=total_rows,
        autosomal_rows=autosomal_rows,
        autosomal_called_rows=autosomal_called_rows,
        skipped_rows=skipped_rows,
        call_rate=call_rate,
        chromosome_counts=dict(sorted(chromosome_counts.items(), key=lambda item: item[0])),
    )
    return summary, calls


def write_normalized_raw(calls: Sequence[RawCall], output_path: Path, autosomal_only: bool) -> int:
    rows = []
    for call in calls:
        if autosomal_only and call.chromosome not in AUTOSOMES:
            continue
        rows.append(f"{call.rsid}\t{call.chromosome}\t{call.position}\t{call.genotype}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output = "rsid\tchromosome\tposition\tgenotype\n" + "\n".join(rows) + "\n"
    output_path.write_text(output, encoding="utf-8")
    return len(rows)


def is_number(value: str) -> bool:
    try:
        float(value)
        return True
    except ValueError:
        return False


def parse_k36_horizontal(lines: Sequence[str], sample_name: Optional[str]) -> Optional[Tuple[str, List[float]]]:
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "," in stripped:
            parts = [part.strip() for part in stripped.split(",")]
        else:
            parts = [part.strip() for part in stripped.split()]

        if len(parts) == 37 and all(is_number(value) for value in parts[1:]):
            return parts[0], [float(value) for value in parts[1:]]
        if len(parts) == 36 and all(is_number(value) for value in parts):
            return sample_name or "sample", [float(value) for value in parts]
    return None


def normalize_component_key(value: str) -> str:
    return re.sub(r"[_\-\s]+", "", value.strip().lower())


def parse_k36_admix_output(text: str, sample_name: Optional[str]) -> Optional[Tuple[str, List[float]]]:
    key_to_index = {
        normalize_component_key(component): index
        for index, component in enumerate(K36_COMPONENTS)
    }
    values = [0.0] * len(K36_COMPONENTS)
    matched = 0
    in_k36_block = False

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            if in_k36_block and matched:
                break
            continue

        if line.upper() == "K36":
            in_k36_block = True
            continue
        if line.upper().startswith("K47") and in_k36_block:
            break
        if not in_k36_block or ":" not in line:
            continue

        name, percent = [part.strip() for part in line.split(":", 1)]
        key = normalize_component_key(name)
        if key not in key_to_index:
            continue

        match = re.search(r"-?\d+(?:\.\d+)?", percent)
        if not match:
            continue

        values[key_to_index[key]] = float(match.group(0))
        matched += 1

    if matched:
        return sample_name or "sample", values
    return None


def parse_k36_vertical_blob(text: str, sample_name: Optional[str]) -> Tuple[str, List[float]]:
    compact = " ".join(text.replace("\r", " ").split())
    positions: List[int] = []
    cursor = 0

    for component in K36_COMPONENTS:
        idx = compact.find(component, cursor)
        if idx == -1:
            raise ValueError(
                "РќРµ СѓРґР°Р»РѕСЃСЊ РЅР°Р№С‚Рё РІСЃРµ 36 РєРѕРјРїРѕРЅРµРЅС‚ K36 РІ РІРµСЂС‚РёРєР°Р»СЊРЅРѕРј С‚РµРєСЃС‚Рµ. "
                "РЎРєРѕРїРёСЂСѓР№С‚Рµ РїРѕР»РЅС‹Р№ Р±Р»РѕРє Gedmatch/Allelocator."
            )
        positions.append(idx)
        cursor = idx + len(component)

    values: List[float] = []
    for index, component in enumerate(K36_COMPONENTS):
        start = positions[index] + len(component)
        end = positions[index + 1] if index + 1 < len(positions) else len(compact)
        chunk = compact[start:end]
        match = re.search(r"-?\d+(?:\.\d+)?", chunk)
        values.append(float(match.group(0)) if match else 0.0)

    return sample_name or "sample", values


def parse_k36(path: Path, sample_name: Optional[str]) -> K36Summary:
    text = read_text(path)
    lines = text.splitlines()
    horizontal = parse_k36_horizontal(lines, sample_name)
    if horizontal is not None:
        name, values = horizontal
        detected_format = "horizontal"
    else:
        admix_output = parse_k36_admix_output(text, sample_name)
        if admix_output is not None:
            name, values = admix_output
            detected_format = "admix-output"
        else:
            name, values = parse_k36_vertical_blob(text, sample_name)
            detected_format = "vertical"

    if len(values) != 36:
        raise ValueError(f"РћР¶РёРґР°Р»РѕСЃСЊ 36 РєРѕРјРїРѕРЅРµРЅС‚ K36, РїРѕР»СѓС‡РµРЅРѕ {len(values)}.")

    canonical_values = ",".join(f"{value:.6f}" for value in values)
    canonical_line = f"{name},{canonical_values}"
    non_zero_components = {
        component: round(value, 6)
        for component, value in zip(K36_COMPONENTS, values)
        if abs(value) > 1e-12
    }
    return K36Summary(
        file=str(path),
        detected_format=detected_format,
        sample_name=name,
        component_count=len(values),
        total=round(sum(values), 6),
        values=tuple(values),
        non_zero_components=non_zero_components,
        canonical_line=canonical_line,
    )


def parse_g25_line(line: str) -> G25Entry:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        raise ValueError("skip")
    if stripped.lower().startswith(",pc1"):
        raise ValueError("skip")

    delimiter = "," if "," in stripped else "\t"
    parts = [part.strip() for part in stripped.split(delimiter)]
    if len(parts) != 26:
        raise ValueError("РљР°Р¶РґР°СЏ СЃС‚СЂРѕРєР° G25 РґРѕР»Р¶РЅР° СЃРѕРґРµСЂР¶Р°С‚СЊ РёРјСЏ Рё 25 РєРѕРѕСЂРґРёРЅР°С‚.")

    name = parts[0]
    coords = tuple(float(value) for value in parts[1:])
    return G25Entry(name=name, coords=coords)


def load_g25_entries(path: Path) -> List[G25Entry]:
    entries: List[G25Entry] = []
    for line in read_text(path).splitlines():
        try:
            entries.append(parse_g25_line(line))
        except ValueError as exc:
            if str(exc) == "skip":
                continue
            raise ValueError(f"{path}: {exc}")
    if not entries:
        raise ValueError(f"{path}: РЅРµ РЅР°Р№РґРµРЅРѕ РЅРё РѕРґРЅРѕР№ РІР°Р»РёРґРЅРѕР№ СЃС‚СЂРѕРєРё G25.")
    return entries


def load_reference_manifest(path: Path) -> Dict[str, Dict[str, str]]:
    lines = [
        line
        for line in read_text(path).splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if not lines:
        raise ValueError(f"{path}: manifest is empty.")

    delimiter = "\t" if "\t" in lines[0] else ","
    rows = list(csv.reader(lines, delimiter=delimiter))
    if not rows:
        raise ValueError(f"{path}: manifest is empty.")

    headers = [header.strip() for header in rows[0]]
    if "standard_name" not in headers:
        raise ValueError(f"{path}: manifest must contain a 'standard_name' column.")

    records: Dict[str, Dict[str, str]] = {}
    for row_number, row in enumerate(rows[1:], start=2):
        if not row:
            continue
        if len(row) != len(headers):
            raise ValueError(f"{path}: malformed manifest row at line {row_number}.")
        record = {header: value.strip() for header, value in zip(headers, row)}
        standard_name = record.get("standard_name", "")
        if not standard_name:
            raise ValueError(f"{path}: manifest row {row_number} has empty standard_name.")
        records[standard_name] = record

    if not records:
        raise ValueError(f"{path}: manifest has no data rows.")
    return records


def load_verified_vahaduo_bridge(path: Path) -> List[dict]:
    rows = load_tsv_rows(path)
    required = {"standard_name", "source_table", "source_label", "match_type"}
    if not rows:
        raise ValueError(f"{path}: bridge is empty.")
    missing = sorted(required.difference(rows[0].keys()))
    if missing:
        raise ValueError(f"{path}: bridge is missing required columns: {', '.join(missing)}.")
    return rows


def build_verified_coordinate_import_from_vahaduo_bridge(
    bridge_path: Path,
    downloads_dir: Path,
    output_path: Path,
    output_json: Optional[Path] = None,
) -> dict:
    bridge_rows = load_verified_vahaduo_bridge(bridge_path)
    standard_names = [row["standard_name"] for row in bridge_rows]
    duplicate_standard_names = sorted(
        name for name, count in Counter(standard_names).items() if count > 1
    )
    if duplicate_standard_names:
        raise ValueError(
            f"{bridge_path}: duplicate standard_name rows found: {', '.join(duplicate_standard_names)}."
        )

    table_cache: Dict[str, Dict[str, G25Entry]] = {}
    missing_tables: List[str] = []
    missing_labels: List[dict] = []
    output_entries: List[G25Entry] = []
    match_type_counts: Counter = Counter()
    table_counts: Counter = Counter()

    for row in bridge_rows:
        source_table = row["source_table"].strip()
        source_label = row["source_label"].strip()
        if not source_table or not source_label:
            raise ValueError(f"{bridge_path}: bridge row for {row['standard_name']} has empty source_table/source_label.")

        source_path = downloads_dir / source_table
        if not source_path.exists():
            if source_table not in missing_tables:
                missing_tables.append(source_table)
            continue

        if source_table not in table_cache:
            table_cache[source_table] = {entry.name: entry for entry in load_g25_entries(source_path)}

        source_entry = table_cache[source_table].get(source_label)
        if source_entry is None:
            missing_labels.append(
                {
                    "standard_name": row["standard_name"],
                    "source_table": source_table,
                    "source_label": source_label,
                }
            )
            continue

        output_entries.append(G25Entry(name=row["standard_name"], coords=source_entry.coords))
        match_type_counts[row["match_type"].strip() or "unspecified"] += 1
        table_counts[source_table] += 1

    if missing_tables or missing_labels:
        problems = []
        if missing_tables:
            problems.append(f"missing_tables={len(missing_tables)}")
        if missing_labels:
            problems.append(f"missing_labels={len(missing_labels)}")
        raise ValueError(
            f"Unable to build verified coordinate import from {bridge_path}: "
            + ", ".join(problems)
            + "."
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        "\n".join(g25_line_from_coords(entry.name, entry.coords) for entry in output_entries) + "\n",
        encoding="utf-8",
    )

    payload = {
        "bridge_path": str(bridge_path),
        "downloads_dir": str(downloads_dir),
        "output_path": str(output_path),
        "rows_written": len(output_entries),
        "source_tables_used": sorted(table_counts),
        "source_table_counts": dict(sorted(table_counts.items())),
        "match_type_counts": dict(sorted(match_type_counts.items())),
        "missing_tables": missing_tables,
        "missing_labels": missing_labels,
        "first_rows": [entry.name for entry in output_entries[:5]],
    }
    if output_json:
        write_json_file(output_json, payload)
        payload["output_json"] = str(output_json)
    return payload


def load_k36_regression(js_path: Path) -> List[Tuple[float, List[float]]]:
    text = read_text(js_path)
    equations: List[Tuple[float, List[float]]] = []
    pattern = re.compile(r"v(\d+)\s*=\s*([^;]+);")
    coefficient_pattern = re.compile(
        r"com(\d+)\s*\*\s*([+\-]?\d+(?:\.\d+)?(?:E[+\-]?\d+)?)",
        re.IGNORECASE,
    )

    for _, expression in pattern.findall(text):
        intercept_match = re.match(r"\s*([+\-]?\d+(?:\.\d+)?(?:E[+\-]?\d+)?)", expression, re.IGNORECASE)
        if not intercept_match:
            continue
        intercept = float(intercept_match.group(1))
        coeffs = [0.0] * len(K36_COMPONENTS)
        for component_index, coefficient in coefficient_pattern.findall(expression):
            coeffs[int(component_index) - 1] = float(coefficient)
        equations.append((intercept, coeffs))

    if len(equations) != 25:
        raise ValueError(f"{js_path}: expected 25 regression equations, found {len(equations)}.")
    return equations


def compute_g25_from_k36(values: Sequence[float], regression: Sequence[Tuple[float, Sequence[float]]]) -> Tuple[float, ...]:
    coords = []
    for intercept, coeffs in regression:
        total = intercept
        for value, coefficient in zip(values, coeffs):
            total += value * coefficient
        coords.append(total)
    return tuple(coords)


def g25_line_from_coords(name: str, coords: Sequence[float]) -> str:
    return name + "," + ",".join(f"{value:.8f}" for value in coords)


def euclidean_distance(a: Sequence[float], b: Sequence[float]) -> float:
    return math.sqrt(sum((left - right) ** 2 for left, right in zip(a, b)))


def nearest_entries(target: G25Entry, references: Sequence[G25Entry], top: int) -> List[Tuple[float, G25Entry]]:
    results = [(euclidean_distance(target.coords, ref.coords), ref) for ref in references]
    results.sort(key=lambda item: item[0])
    return results[:top]


def summarize_grouped_nearest(
    nearest: Sequence[Tuple[float, G25Entry]],
    manifest: Dict[str, Dict[str, str]],
    group_column: str,
    top_groups: int,
) -> List[dict]:
    weighted_totals: Dict[str, float] = {}
    hit_counts: Dict[str, int] = {}
    best_hits: Dict[str, Tuple[float, str]] = {}
    epsilon = 1e-9

    for distance, ref in nearest:
        metadata = manifest.get(ref.name, {})
        group_name = metadata.get(group_column) or "Unassigned"
        weight = 1.0 / max(distance, epsilon)
        weighted_totals[group_name] = weighted_totals.get(group_name, 0.0) + weight
        hit_counts[group_name] = hit_counts.get(group_name, 0) + 1

        best_distance, _ = best_hits.get(group_name, (float("inf"), ""))
        if distance < best_distance:
            best_hits[group_name] = (distance, ref.name)

    total_weight = sum(weighted_totals.values())
    results = []
    for group_name, weight in sorted(weighted_totals.items(), key=lambda item: item[1], reverse=True)[:top_groups]:
        best_distance, best_reference = best_hits[group_name]
        routing_score = 0.0 if total_weight == 0 else weight / total_weight
        results.append(
            {
                "group": group_name,
                "routing_score": round(routing_score, 6),
                "hits": hit_counts[group_name],
                "best_reference": best_reference,
                "best_distance": round(best_distance, 6),
            }
        )
    return results


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def best_two_way_models(
    target: G25Entry,
    references: Sequence[G25Entry],
    top: int,
) -> List[Tuple[float, str, float, str, float]]:
    results: List[Tuple[float, str, float, str, float]] = []
    for index, left in enumerate(references):
        for right in references[index + 1 :]:
            vector = [a - b for a, b in zip(left.coords, right.coords)]
            denom = sum(value * value for value in vector)
            if denom == 0:
                continue
            numerator = sum(
                (target_value - right_value) * delta
                for target_value, right_value, delta in zip(target.coords, right.coords, vector)
            )
            weight_left = clamp(numerator / denom, 0.0, 1.0)
            weight_right = 1.0 - weight_left
            mixed = tuple(
                (weight_left * left_value) + (weight_right * right_value)
                for left_value, right_value in zip(left.coords, right.coords)
            )
            distance = euclidean_distance(target.coords, mixed)
            results.append((distance, left.name, weight_left, right.name, weight_right))

    results.sort(key=lambda item: item[0])
    return results[:top]


def dot_product(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(left * right for left, right in zip(a, b))


def scale_vector(values: Sequence[float], scalar: float) -> Tuple[float, ...]:
    return tuple(value * scalar for value in values)


def add_vectors(a: Sequence[float], b: Sequence[float]) -> Tuple[float, ...]:
    return tuple(left + right for left, right in zip(a, b))


def subtract_vectors(a: Sequence[float], b: Sequence[float]) -> Tuple[float, ...]:
    return tuple(left - right for left, right in zip(a, b))


def frank_wolfe_panel_fit(
    target: G25Entry,
    references: Sequence[G25Entry],
    iterations: int,
    tolerance: float = 1e-12,
) -> Tuple[List[float], Tuple[float, ...], int]:
    if not references:
        raise ValueError("Panel fit requires at least one reference.")

    start_index = min(range(len(references)), key=lambda index: euclidean_distance(target.coords, references[index].coords))
    weights = [0.0] * len(references)
    weights[start_index] = 1.0
    mixed = tuple(references[start_index].coords)
    completed_iterations = 0

    for step in range(iterations):
        residual = subtract_vectors(mixed, target.coords)
        best_index = min(
            range(len(references)),
            key=lambda index: dot_product(residual, references[index].coords),
        )
        direction = subtract_vectors(references[best_index].coords, mixed)
        denom = dot_product(direction, direction)
        if denom <= tolerance:
            completed_iterations = step
            break

        gamma = clamp(-dot_product(residual, direction) / denom, 0.0, 1.0)
        if gamma <= tolerance:
            completed_iterations = step
            break

        shrink = 1.0 - gamma
        weights = [weight * shrink for weight in weights]
        weights[best_index] += gamma
        mixed = add_vectors(scale_vector(mixed, shrink), scale_vector(references[best_index].coords, gamma))
        completed_iterations = step + 1

    return weights, mixed, completed_iterations


def _solve_equality_constrained_weights(
    reference_matrix: np.ndarray,
    target_vector: np.ndarray,
    active_indices: Sequence[int],
) -> Tuple[np.ndarray, float]:
    active = sorted(active_indices)
    active_matrix = reference_matrix[:, active]
    gram = active_matrix.T @ active_matrix
    linear = active_matrix.T @ target_vector
    size = len(active)
    kkt = np.zeros((size + 1, size + 1), dtype=float)
    kkt[:size, :size] = gram
    kkt[:size, size] = 1.0
    kkt[size, :size] = 1.0
    rhs = np.concatenate([linear, np.array([1.0])])
    try:
        solution = np.linalg.solve(kkt, rhs)
    except np.linalg.LinAlgError:
        solution = np.linalg.lstsq(kkt, rhs, rcond=None)[0]

    weights = np.zeros(reference_matrix.shape[1], dtype=float)
    weights[active] = solution[:size]
    return weights, float(solution[size])


def _normalize_simplex_weights(weights: np.ndarray, fallback_index: int, tolerance: float) -> np.ndarray:
    cleaned = np.maximum(weights, 0.0)
    total = float(cleaned.sum())
    if total <= tolerance:
        cleaned = np.zeros_like(weights)
        cleaned[fallback_index] = 1.0
        return cleaned
    return cleaned / total


def simplex_least_squares_panel_fit(
    target: G25Entry,
    references: Sequence[G25Entry],
    iterations: int,
    tolerance: float = 1e-12,
) -> Tuple[List[float], Tuple[float, ...], int]:
    if not references:
        raise ValueError("Panel fit requires at least one reference.")

    dimension = len(target.coords)
    if any(len(reference.coords) != dimension for reference in references):
        raise ValueError("Panel fit references must have the same dimension as the target.")
    if len(references) == 1:
        return [1.0], tuple(references[0].coords), 0

    reference_matrix = np.array([reference.coords for reference in references], dtype=float).T
    target_vector = np.array(target.coords, dtype=float)
    nearest_index = int(np.argmin(np.linalg.norm(reference_matrix - target_vector[:, None], axis=0)))
    active: set[int] = set(range(len(references)))
    completed_iterations = 0
    weights = np.zeros(len(references), dtype=float)
    lagrange_multiplier = 0.0
    max_iterations = max(int(iterations), len(references) * 4, 50)

    for step in range(max_iterations):
        completed_iterations = step + 1
        if not active:
            active.add(nearest_index)

        weights, lagrange_multiplier = _solve_equality_constrained_weights(
            reference_matrix,
            target_vector,
            sorted(active),
        )
        negative_indices = [index for index in active if weights[index] < -tolerance]
        if negative_indices:
            for index in negative_indices:
                active.discard(index)
            continue

        weights = _normalize_simplex_weights(weights, nearest_index, tolerance)
        residual = reference_matrix @ weights - target_vector
        gradient = reference_matrix.T @ residual
        inactive = [index for index in range(len(references)) if index not in active]
        if inactive:
            violation, candidate = min((gradient[index] + lagrange_multiplier, index) for index in inactive)
            if violation < -tolerance:
                active.add(candidate)
                continue
        break

    weights = _normalize_simplex_weights(weights, nearest_index, tolerance)
    mixed_array = reference_matrix @ weights
    return weights.tolist(), tuple(float(value) for value in mixed_array), completed_iterations


def summarize_panel_fit(
    target: G25Entry,
    references: Sequence[G25Entry],
    manifest: Dict[str, Dict[str, str]],
    group_column: str,
    iterations: int,
    top_references: int,
) -> dict:
    weights, mixed, completed_iterations = simplex_least_squares_panel_fit(target, references, iterations)

    grouped_weights: Dict[str, float] = {}
    reference_rows = []
    for weight, ref in zip(weights, references):
        if weight <= 1e-12:
            continue
        metadata = manifest.get(ref.name, {})
        group_name = metadata.get(group_column) or "Unassigned"
        grouped_weights[group_name] = grouped_weights.get(group_name, 0.0) + weight
        reference_rows.append(
            {
                "reference": ref.name,
                "group": group_name,
                "weight": round(weight, 6),
            }
        )

    panel_name = None
    for ref in references:
        metadata = manifest.get(ref.name)
        if metadata and metadata.get("panel_name"):
            panel_name = metadata["panel_name"]
            break

    reference_rows.sort(key=lambda row: row["weight"], reverse=True)
    ordered_groups = {
        group_name: round(weight, 6)
        for group_name, weight in sorted(grouped_weights.items(), key=lambda item: item[1], reverse=True)
    }
    return {
        "target": target.name,
        "panel_name": panel_name,
        "group_column": group_column,
        "distance": round(euclidean_distance(target.coords, mixed), 6),
        "sources": len(references),
        "iterations": completed_iterations,
        "groups": ordered_groups,
        "top_references": reference_rows[:top_references],
    }


def select_adaptive_groups(
    grouped_weights: Dict[str, float],
    min_groups: int,
    max_groups: int,
    min_weight: float,
) -> List[str]:
    ordered = list(grouped_weights.items())
    selected = [group for group, weight in ordered if weight >= min_weight]
    if len(selected) < min_groups:
        selected = [group for group, _ in ordered[:min_groups]]
    return selected[:max_groups]


def filter_panel_by_groups(
    references: Sequence[G25Entry],
    manifest: Dict[str, Dict[str, str]],
    group_column: str,
    selected_groups: Sequence[str],
) -> List[G25Entry]:
    selected_set = set(selected_groups)
    return [
        ref
        for ref in references
        if (manifest.get(ref.name, {}).get(group_column) or "Unassigned") in selected_set
    ]


def print_json(data: object) -> None:
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    try:
        print(payload)
    except UnicodeEncodeError:
        sys.stdout.buffer.write(payload.encode("utf-8", errors="replace") + b"\n")


def write_json_file(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def safe_ascii_slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", ascii_only).strip("._-")
    return slug or "sample"


def resolve_admix_binary() -> Path:
    env_path = os.environ.get("ADMIX_BINARY", "").strip()
    if env_path:
        candidate = Path(env_path)
        if candidate.exists():
            return candidate

    candidates = [
        SCRIPT_ROOT / "vendor" / "run_admix.py",
        SCRIPT_ROOT / ".venv" / "Scripts" / "admix.exe",
        SCRIPT_ROOT / ".venv" / "Scripts" / "admix",
        SCRIPT_ROOT / ".venv" / "bin" / "admix",
        SCRIPT_ROOT.parent / ".venv" / "Scripts" / "admix.exe",
        SCRIPT_ROOT.parent / ".venv" / "Scripts" / "admix",
        SCRIPT_ROOT.parent / ".venv" / "bin" / "admix",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate

    which = shutil.which("admix")
    if which:
        return Path(which)

    raise FileNotFoundError("Не найден binary admix. Ожидался .venv/Scripts/admix.exe или admix в PATH.")


def infer_admix_vendor_candidates(summary: RawSummary, input_path: Path) -> List[str]:
    name = input_path.name.lower()
    extension = input_path.suffix.lower()
    candidates: List[str] = []

    if "myheritage" in name:
        candidates.append("myheritage")
    if "23andme" in name:
        candidates.append("23andme")
    if "ancestry" in name:
        candidates.append("ancestry")
    if "ftdna" in name or "familytreedna" in name:
        candidates.append("ftdna")

    if summary.vendor_hint == "MyHeritage":
        candidates.append("myheritage")
    elif summary.vendor_hint == "23andMe":
        candidates.append("23andme")
    elif summary.vendor_hint == "AncestryDNA":
        candidates.append("ancestry")
    elif summary.vendor_hint == "FTDNA":
        candidates.extend(["ftdna", "myheritage"])
    elif summary.vendor_hint == "Ancestry-like":
        candidates.append("ancestry")
    elif summary.vendor_hint == "23andMe/FTDNA/MyHeritage-like":
        if extension == ".csv":
            candidates.extend(["myheritage", "ftdna", "23andme", "ancestry"])
        else:
            candidates.extend(["23andme", "ftdna", "myheritage", "ancestry"])

    if not candidates:
        if extension == ".csv":
            candidates.extend(["myheritage", "ftdna", "ancestry", "23andme"])
        else:
            candidates.extend(["23andme", "ftdna", "myheritage", "ancestry"])

    return list(dict.fromkeys(candidates))


def k36_is_informative(summary: K36Summary) -> bool:
    values = list(summary.values)
    spread = max(values) - min(values)
    peak = max(values)
    non_zero = sum(1 for value in values if abs(value) > 1e-12)
    unique_rounded = len({round(value, 2) for value in values})
    if spread < 1.0:
        return False
    if peak < 4.0:
        return False
    if non_zero >= 20 and unique_rounded <= 3:
        return False
    return True


def top_k36_components(summary: K36Summary, top: int) -> List[dict]:
    ranked = sorted(
        (
            {"component": component, "value": round(value, 6)}
            for component, value in zip(K36_COMPONENTS, summary.values)
            if abs(value) > 1e-12
        ),
        key=lambda item: item["value"],
        reverse=True,
    )
    return ranked[:top]


def stage_input_for_external_tool(input_path: Path, run_dir: Path, sample_slug: str) -> Path:
    staged_dir = run_dir / "staged"
    staged_dir.mkdir(parents=True, exist_ok=True)
    suffix = input_path.suffix or ".txt"
    staged_path = staged_dir / f"{sample_slug}_input{suffix}"
    shutil.copyfile(input_path, staged_path)
    return staged_path


def run_admix_k36_auto(
    input_path: Path,
    sample_name: str,
    run_dir: Path,
    vendor_candidates: Sequence[str],
) -> Tuple[K36Summary, Path, str, List[dict]]:
    admix_binary = resolve_admix_binary()
    attempts: List[dict] = []

    for vendor in vendor_candidates:
        output_path = run_dir / f"admix_k36_{vendor}.txt"
        command = [str(admix_binary), "-f", str(input_path), "-m", "K36", "-v", vendor, "--ignore-zeros"]
        if admix_binary.suffix.lower() == ".py":
            command = [sys.executable, *command]
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
        )
        output_text = completed.stdout or ""
        if completed.stderr:
            output_text = output_text + ("\n" if output_text else "") + completed.stderr
        output_path.write_text(output_text, encoding="utf-8")

        attempt = {
            "vendor": vendor,
            "returncode": completed.returncode,
            "output_path": str(output_path),
        }

        if completed.returncode != 0:
            attempt["status"] = "command_error"
            attempt["stderr"] = (completed.stderr or "").strip()
            attempts.append(attempt)
            continue

        try:
            summary = parse_k36(output_path, sample_name)
        except Exception as exc:
            attempt["status"] = "parse_error"
            attempt["error"] = str(exc)
            attempts.append(attempt)
            continue

        peak = top_k36_components(summary, 1)
        attempt["status"] = "ok"
        attempt["informative"] = k36_is_informative(summary)
        attempt["total"] = round(summary.total, 6)
        attempt["top_component"] = peak[0] if peak else None
        attempts.append(attempt)

        if attempt["informative"]:
            return summary, output_path, vendor, attempts

    raise ValueError(
        "Не удалось автоматически получить информативный K36 через admix. "
        f"Проверенные vendor-кандидаты: {', '.join(vendor_candidates)}."
    )


def build_route_payload(
    target: G25Entry,
    references: Sequence[G25Entry],
    manifest: Dict[str, Dict[str, str]],
    group_column: str,
    top: int,
    top_groups: int,
) -> dict:
    nearest = nearest_entries(target, references, top)
    group_results = summarize_grouped_nearest(nearest, manifest, group_column, top_groups)
    predicted_group = group_results[0]["group"] if group_results else None
    return {
        "target": target.name,
        "predicted_group": predicted_group,
        "group_column": group_column,
        "group_results": group_results,
        "nearest": [
            {
                "distance": round(distance, 6),
                "reference": ref.name,
                "group": manifest.get(ref.name, {}).get(group_column, "Unassigned"),
            }
            for distance, ref in nearest
        ],
    }


def route_single_target(
    target: G25Entry,
    references_path: Path,
    manifest_path: Path,
    group_column: str,
    top: int,
    top_groups: int,
) -> dict:
    references = load_g25_entries(references_path)
    manifest = load_reference_manifest(manifest_path)
    return build_route_payload(target, references, manifest, group_column, top, top_groups)


def run_west_eurasia_branch(
    target: G25Entry,
    modern_refs: Path,
    modern_manifest: Path,
    ancient_refs: Path,
    ancient_manifest: Path,
    top: int,
    top_groups: int,
) -> dict:
    modern_cluster = route_single_target(
        target,
        modern_refs,
        modern_manifest,
        "west_cluster",
        top,
        top_groups,
    )
    ancient_family = route_single_target(
        target,
        ancient_refs,
        ancient_manifest,
        "west_family",
        top,
        top_groups,
    )
    ancient_core = route_single_target(
        target,
        ancient_refs,
        ancient_manifest,
        "west_core_group",
        top,
        max(top_groups, 8),
    )
    return {
        "modern_cluster": modern_cluster,
        "ancient_family": ancient_family,
        "ancient_core": ancient_core,
    }


def run_volga_ural_north_eurasia_branch(
    target: G25Entry,
    modern_refs: Path,
    modern_manifest: Path,
    ancient_refs: Path,
    ancient_manifest: Path,
    top: int,
    top_groups: int,
) -> dict:
    modern_cluster = route_single_target(
        target,
        modern_refs,
        modern_manifest,
        "volga_cluster",
        top,
        top_groups,
    )
    ancient_family = route_single_target(
        target,
        ancient_refs,
        ancient_manifest,
        "volga_family",
        top,
        top_groups,
    )
    ancient_core = route_single_target(
        target,
        ancient_refs,
        ancient_manifest,
        "volga_core_group",
        top,
        max(top_groups, 8),
    )
    return {
        "modern_cluster": modern_cluster,
        "ancient_family": ancient_family,
        "ancient_core": ancient_core,
    }


def run_south_asia_branch(
    target: G25Entry,
    modern_refs: Path,
    modern_manifest: Path,
    ancient_refs: Path,
    ancient_manifest: Path,
    top: int,
    top_groups: int,
) -> dict:
    modern_cluster = route_single_target(
        target,
        modern_refs,
        modern_manifest,
        "south_cluster",
        top,
        top_groups,
    )
    ancient_family = route_single_target(
        target,
        ancient_refs,
        ancient_manifest,
        "south_family",
        top,
        top_groups,
    )
    ancient_core = route_single_target(
        target,
        ancient_refs,
        ancient_manifest,
        "south_core_group",
        top,
        max(top_groups, 8),
    )
    return {
        "modern_cluster": modern_cluster,
        "ancient_family": ancient_family,
        "ancient_core": ancient_core,
    }


def recommend_west_eurasia_detail(modern_west: dict, ancient_west_core: dict) -> dict:
    modern_cluster = modern_west.get("predicted_group") or ""
    ancient_core = ancient_west_core.get("predicted_group") or ""

    if modern_cluster.startswith("Caucasus_") or ancient_core in {"Caucasus_Maikop", "Caucasus_KuraAraxes"}:
        return {
            "primary": "CaucasusSteppe_Detail_Candidate",
            "secondary": "WestEurasia_Extended_Candidate",
            "reason": "West Eurasia branch narrows to a caucasus-heavy profile.",
        }

    if modern_cluster.startswith("Europe_"):
        return {
            "primary": "WestEurasia_Extended_Candidate",
            "secondary": "CaucasusSteppe_Detail_Candidate",
            "reason": "Modern West Eurasia routing leans toward a European subcluster.",
        }

    return {
        "primary": "WestEurasia_Extended_Candidate",
        "secondary": None,
        "reason": "West Eurasia branch triggered, but no narrower implemented panel matched decisively.",
    }


def recommend_volga_ural_detail(modern_volga: dict, ancient_volga_core: dict, ancient_volga_family: dict) -> dict:
    modern_cluster = modern_volga.get("predicted_group") or ""
    ancient_core = ancient_volga_core.get("predicted_group") or ""
    ancient_family = ancient_volga_family.get("predicted_group") or ""

    if modern_cluster in {"UralSiberian", "Steppe_Turkic"} or ancient_family == "NorthEurasia":
        return {
            "primary": "VolgaUralNorthEurasia_Detail_Candidate",
            "secondary": "NorthEurasia_Boundary_Candidate",
            "reason": "Volga-Ural branch shows a clear north-eurasian or ural-siberian pull.",
        }

    if modern_cluster in {"VolgaUral_Turkic", "VolgaUral_FinnoPermic"} or ancient_core in {
        "Steppe_MLBA",
        "ForestSteppe_BA",
        "WestSiberian",
    }:
        return {
            "primary": "VolgaUralNorthEurasia_Detail_Candidate",
            "secondary": "SteppeNorthEurasia_Detail_Candidate",
            "reason": "Volga-Ural branch narrows to the core Volga-Ural boundary zone.",
        }

    return {
        "primary": "VolgaUralNorthEurasia_Detail_Candidate",
        "secondary": None,
        "reason": "Volga-Ural branch triggered, but no narrower implemented panel matched decisively.",
    }


def recommend_south_asia_detail(modern_south: dict, ancient_south_core: dict, ancient_south_family: dict) -> dict:
    modern_cluster = modern_south.get("predicted_group") or ""
    ancient_core = ancient_south_core.get("predicted_group") or ""
    ancient_family = ancient_south_family.get("predicted_group") or ""

    if modern_cluster in {"Himalayan_IndoAryan", "Himalayan_TibetoBurman"} or ancient_family == "Himalayan_East":
        return {
            "primary": "SouthAsia_Himalaya_Boundary_Candidate",
            "secondary": "SouthAsia_Regional_Detail_Candidate",
            "reason": "South Asia branch shows a strong Himalayan or eastern boundary pull.",
        }

    if modern_cluster == "DeepSouth_AASIShifted" or ancient_family == "AASI_Proxy":
        return {
            "primary": "SouthAsia_AASI_Shifted_Candidate",
            "secondary": "SouthAsia_Regional_Detail_Candidate",
            "reason": "South Asia branch shows a deep-south or AASI-shifted profile.",
        }

    if modern_cluster in {"Northwest_IndoIranian", "Indus_West"} or ancient_core in {"Indus_Periphery", "BMAC_Turan", "Steppe_MLBA"}:
        return {
            "primary": "SouthAsia_IndusSteppe_Candidate",
            "secondary": "SouthAsia_Regional_Detail_Candidate",
            "reason": "South Asia branch narrows toward an Indus-northwest-steppe profile.",
        }

    return {
        "primary": "SouthAsia_Regional_Detail_Candidate",
        "secondary": "SouthAsia_IndusSteppe_Candidate",
        "reason": "South Asia branch triggered, but no narrower implemented panel matched decisively.",
    }


def read_json_file(path: Path) -> dict:
    return json.loads(read_text(path))


def load_tsv_rows(path: Path) -> List[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        return [dict(row) for row in reader]


def compute_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def pilot_source_bundle_key(row: dict) -> str:
    family = safe_ascii_slug(row["source_family"])
    collection = safe_ascii_slug(row["source_collection"])
    layer = safe_ascii_slug(row["backbone_layer"])
    return f"{layer}_{family}_{collection}"


def build_pilot_provenance_record(template: dict, row: dict, raw_dir: Path, provenance_dir: Path) -> dict:
    dataset_id = row["pilot_item_id"]
    bundle_name = pilot_source_bundle_key(row)
    local_raw_dir = raw_dir / bundle_name
    artifact_stub = provenance_dir / f"{dataset_id}.json"
    record = json.loads(json.dumps(template))
    record["dataset_id"] = dataset_id
    record["source_id"] = row["source_family"]
    record["official_url"] = ""
    record["retrieval_date"] = ""
    record["version_label"] = row["source_collection"]
    record["local_raw_path"] = str(local_raw_dir)
    record["license_or_access_notes"] = "Planned pilot source bundle. Fill after official retrieval."
    record["processing_steps"] = [
        {
            "step_id": "source_capture",
            "description": "Stage the official source subset for the pilot item.",
            "input": row["source_collection"],
            "output": str(local_raw_dir),
        },
        {
            "step_id": "harmonization",
            "description": "Transform the pilot source subset into the shared verified-backbone comparison space.",
            "input": str(local_raw_dir),
            "output": row["target_artifact"],
        },
    ]
    record["runtime_artifacts"] = [
        {
            "artifact_path": str(artifact_stub),
            "artifact_type": "provenance_record",
        }
    ]
    record["status"] = "planned"
    return record


def initialize_official_source_ingestion_pilot(
    pilot_manifest: Path,
    provenance_template: Path,
    raw_root: Path,
    provenance_root: Path,
    pilot_output_dir: Path,
) -> dict:
    rows = [row for row in load_tsv_rows(pilot_manifest) if row.get("include_in_pilot", "").lower() == "true"]
    template = read_json_file(provenance_template)

    raw_root.mkdir(parents=True, exist_ok=True)
    provenance_root.mkdir(parents=True, exist_ok=True)
    pilot_output_dir.mkdir(parents=True, exist_ok=True)

    dataset_records = []
    bundle_rows: Dict[str, List[dict]] = {}
    bundle_dirs: Dict[str, Path] = {}

    for row in rows:
        bundle_name = pilot_source_bundle_key(row)
        bundle_dir = raw_root / bundle_name
        bundle_dir.mkdir(parents=True, exist_ok=True)
        bundle_dirs[bundle_name] = bundle_dir
        bundle_rows.setdefault(bundle_name, []).append(row)

        record = build_pilot_provenance_record(template, row, raw_root, provenance_root)
        provenance_path = provenance_root / f"{row['pilot_item_id']}.json"
        write_json_file(provenance_path, record)

        dataset_records.append(
            {
                "pilot_item_id": row["pilot_item_id"],
                "backbone_layer": row["backbone_layer"],
                "source_family": row["source_family"],
                "source_collection": row["source_collection"],
                "standard_name": row["standard_name"],
                "macro_group": row["macro_group"],
                "pilot_role": row["pilot_role"],
                "bundle_key": bundle_name,
                "raw_bundle_dir": str(bundle_dir),
                "provenance_record": str(provenance_path),
                "status": "planned",
            }
        )

    bundle_manifest_path = pilot_output_dir / "official_source_ingestion_pilot_bundles.tsv"
    with bundle_manifest_path.open("w", encoding="utf-8", newline="") as handle:
        fieldnames = [
            "bundle_key",
            "source_family",
            "source_collection",
            "backbone_layer",
            "item_count",
            "raw_bundle_dir",
            "status",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        for bundle_name, bundle_items in sorted(bundle_rows.items()):
            sample = bundle_items[0]
            writer.writerow(
                {
                    "bundle_key": bundle_name,
                    "source_family": sample["source_family"],
                    "source_collection": sample["source_collection"],
                    "backbone_layer": sample["backbone_layer"],
                    "item_count": len(bundle_items),
                    "raw_bundle_dir": str(bundle_dirs[bundle_name]),
                    "status": "planned",
                }
            )

    dataset_manifest_path = pilot_output_dir / "official_source_ingestion_pilot_items.tsv"
    with dataset_manifest_path.open("w", encoding="utf-8", newline="") as handle:
        fieldnames = [
            "pilot_item_id",
            "backbone_layer",
            "source_family",
            "source_collection",
            "standard_name",
            "macro_group",
            "pilot_role",
            "bundle_key",
            "raw_bundle_dir",
            "provenance_record",
            "status",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        writer.writerows(dataset_records)

    provenance_index_path = pilot_output_dir / "official_source_ingestion_pilot_provenance_index.tsv"
    with provenance_index_path.open("w", encoding="utf-8", newline="") as handle:
        fieldnames = [
            "dataset_id",
            "source_id",
            "version_label",
            "retrieval_date",
            "checksum",
            "local_raw_path",
            "status",
            "notes",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "dataset_id": row["pilot_item_id"],
                    "source_id": row["source_family"],
                    "version_label": row["source_collection"],
                    "retrieval_date": "",
                    "checksum": "",
                    "local_raw_path": str(raw_root / pilot_source_bundle_key(row)),
                    "status": "planned",
                    "notes": "Pilot provenance stub; fill after official retrieval.",
                }
            )

    notes_path = pilot_output_dir / "README.md"
    notes_path.write_text(
        "\n".join(
            [
                "# Official Source Ingestion Pilot Runtime Scaffold",
                "",
                "This folder was generated from the pilot manifest.",
                "",
                "It contains:",
                "- one staged raw-source bundle directory per source-family/source-collection pair",
                "- one provenance stub per pilot item",
                "- bundle and item manifests for the pilot run",
                "",
                "Nothing here is harmonized or runtime-ready yet.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    summary = {
        "pilot_manifest": str(pilot_manifest),
        "raw_root": str(raw_root),
        "provenance_root": str(provenance_root),
        "pilot_output_dir": str(pilot_output_dir),
        "items": len(dataset_records),
        "bundles": len(bundle_rows),
        "layers": sorted({row["backbone_layer"] for row in rows}),
        "source_families": sorted({row["source_family"] for row in rows}),
        "artifacts": {
            "bundle_manifest": str(bundle_manifest_path),
            "item_manifest": str(dataset_manifest_path),
            "provenance_index": str(provenance_index_path),
            "notes": str(notes_path),
        },
        "status": "planned",
    }
    summary_path = pilot_output_dir / "official_source_ingestion_pilot_status.json"
    write_json_file(summary_path, summary)
    summary["artifacts"]["status"] = str(summary_path)
    summary["status_sha256"] = compute_sha256(summary_path)
    write_json_file(summary_path, summary)
    return summary


def write_tsv_rows(path: Path, fieldnames: Sequence[str], rows: Sequence[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def refresh_official_source_ingestion_pilot_status(
    item_manifest_path: Path,
    provenance_index_path: Path,
    status_path: Path,
) -> dict:
    items = load_tsv_rows(item_manifest_path)
    provenance_rows = load_tsv_rows(provenance_index_path)
    existing = read_json_file(status_path) if status_path.exists() else {}
    captured_items = sum(1 for row in provenance_rows if row.get("status") == "captured")
    planned_items = sum(1 for row in provenance_rows if row.get("status") == "planned")
    pending_items = len(provenance_rows) - captured_items

    summary = {
        "pilot_manifest": existing.get("pilot_manifest", ""),
        "raw_root": existing.get("raw_root", ""),
        "provenance_root": existing.get("provenance_root", ""),
        "pilot_output_dir": str(status_path.parent),
        "items": len(items),
        "bundles": len({row["bundle_key"] for row in items}),
        "layers": sorted({row["backbone_layer"] for row in items}),
        "source_families": sorted({row["source_family"] for row in items}),
        "artifacts": {
            "bundle_manifest": str(status_path.parent / "official_source_ingestion_pilot_bundles.tsv"),
            "item_manifest": str(item_manifest_path),
            "provenance_index": str(provenance_index_path),
            "notes": str(status_path.parent / "README.md"),
            "status": str(status_path),
        },
        "status": "captured_partial" if captured_items and pending_items else ("captured_complete" if captured_items else "planned"),
        "captured_items": captured_items,
        "planned_items": planned_items,
        "pending_items": pending_items,
    }
    write_json_file(status_path, summary)
    summary["status_sha256"] = compute_sha256(status_path)
    write_json_file(status_path, summary)
    return summary


def register_official_source_for_pilot(
    pilot_item_id: str,
    source_file: Path,
    official_url: str,
    item_manifest_path: Path,
    provenance_index_path: Path,
    status_path: Path,
    retrieval_date: Optional[str] = None,
    version_label: Optional[str] = None,
) -> dict:
    item_rows = load_tsv_rows(item_manifest_path)
    target_row = next((row for row in item_rows if row["pilot_item_id"] == pilot_item_id), None)
    if target_row is None:
        raise ValueError(f"Pilot item not found: {pilot_item_id}")

    provenance_path = Path(target_row["provenance_record"])
    bundle_dir = Path(target_row["raw_bundle_dir"])
    bundle_dir.mkdir(parents=True, exist_ok=True)
    staged_path = bundle_dir / source_file.name
    if source_file.resolve() != staged_path.resolve():
        shutil.copy2(source_file, staged_path)

    checksum = compute_sha256(staged_path)
    effective_date = retrieval_date or date.today().isoformat()

    provenance = read_json_file(provenance_path)
    provenance["official_url"] = official_url
    provenance["retrieval_date"] = effective_date
    provenance["version_label"] = version_label or provenance.get("version_label", "")
    provenance["local_raw_path"] = str(staged_path)
    provenance["checksum"] = {
        "algorithm": "sha256",
        "value": checksum,
    }
    provenance["status"] = "captured"
    write_json_file(provenance_path, provenance)

    provenance_rows = load_tsv_rows(provenance_index_path)
    updated = False
    for row in provenance_rows:
        if row["dataset_id"] == pilot_item_id:
            row["source_id"] = target_row["source_family"]
            row["version_label"] = version_label or target_row["source_collection"]
            row["retrieval_date"] = effective_date
            row["checksum"] = checksum
            row["local_raw_path"] = str(staged_path)
            row["status"] = "captured"
            row["notes"] = "Official source captured into pilot bundle."
            updated = True
            break
    if not updated:
        provenance_rows.append(
            {
                "dataset_id": pilot_item_id,
                "source_id": target_row["source_family"],
                "version_label": version_label or target_row["source_collection"],
                "retrieval_date": effective_date,
                "checksum": checksum,
                "local_raw_path": str(staged_path),
                "status": "captured",
                "notes": "Official source captured into pilot bundle.",
            }
        )
    write_tsv_rows(
        provenance_index_path,
        ["dataset_id", "source_id", "version_label", "retrieval_date", "checksum", "local_raw_path", "status", "notes"],
        provenance_rows,
    )

    status_summary = refresh_official_source_ingestion_pilot_status(item_manifest_path, provenance_index_path, status_path)
    return {
        "pilot_item_id": pilot_item_id,
        "source_file": str(source_file),
        "staged_file": str(staged_path),
        "official_url": official_url,
        "retrieval_date": effective_date,
        "checksum": checksum,
        "provenance_record": str(provenance_path),
        "status_summary": status_summary,
    }


def derive_population_code_from_standard_name(standard_name: str) -> str:
    return standard_name.strip().split("_")[-1]


def load_igsr_panel_rows(path: Path) -> List[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        rows = []
        for row in reader:
            cleaned = {key.strip(): (value or "").strip() for key, value in row.items() if key is not None}
            if cleaned.get("sample"):
                rows.append(cleaned)
        return rows


def load_sgdp_metadata_rows(path: Path) -> List[dict]:
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        rows = []
        for row in reader:
            cleaned = {key.strip(): (value or "").strip() for key, value in row.items() if key is not None}
            if cleaned.get("SGDP_ID"):
                rows.append(cleaned)
        return rows


def derive_sgdp_population_id_from_standard_name(standard_name: str) -> str:
    mapping = {
        "Oceania_IndigenousAustralians_SGDP": "Australian",
        "Oceania_NewGuineans_SGDP": "Papuan",
    }
    if standard_name in mapping:
        return mapping[standard_name]
    return standard_name.strip().split("_")[-1]


def build_modern_pilot_inventory_from_igsr(
    panel_path: Path,
    pilot_manifest_path: Path,
    output_tsv: Path,
    output_json: Optional[Path] = None,
) -> dict:
    panel_rows = load_igsr_panel_rows(panel_path)
    pilot_rows = [
        row
        for row in load_tsv_rows(pilot_manifest_path)
        if row.get("backbone_layer") == "modern" and row.get("source_family") == "IGSR" and row.get("include_in_pilot", "").lower() == "true"
    ]

    grouped: Dict[str, List[dict]] = {}
    for row in panel_rows:
        grouped.setdefault(row.get("pop", ""), []).append(row)

    inventory_rows = []
    for row in pilot_rows:
        pop_code = derive_population_code_from_standard_name(row["standard_name"])
        matches = grouped.get(pop_code, [])
        super_pops = sorted({match.get("super_pop", "") for match in matches if match.get("super_pop")})
        genders = {
            "male": sum(1 for match in matches if match.get("gender", "").lower() == "male"),
            "female": sum(1 for match in matches if match.get("gender", "").lower() == "female"),
        }
        inventory_rows.append(
            {
                "pilot_item_id": row["pilot_item_id"],
                "standard_name": row["standard_name"],
                "population_code": pop_code,
                "macro_group": row["macro_group"],
                "sample_count": len(matches),
                "super_pops": ";".join(super_pops),
                "male_count": genders["male"],
                "female_count": genders["female"],
                "first_samples": ";".join(match["sample"] for match in matches[:5]),
                "status": "confirmed" if matches else "missing",
            }
        )

    write_tsv_rows(
        output_tsv,
        [
            "pilot_item_id",
            "standard_name",
            "population_code",
            "macro_group",
            "sample_count",
            "super_pops",
            "male_count",
            "female_count",
            "first_samples",
            "status",
        ],
        inventory_rows,
    )

    payload = {
        "panel_path": str(panel_path),
        "pilot_manifest": str(pilot_manifest_path),
        "output_tsv": str(output_tsv),
        "populations": len(inventory_rows),
        "confirmed": sum(1 for row in inventory_rows if row["status"] == "confirmed"),
        "missing": sum(1 for row in inventory_rows if row["status"] == "missing"),
        "results": inventory_rows,
    }
    if output_json:
        write_json_file(output_json, payload)
        payload["output_json"] = str(output_json)
    return payload


def build_modern_pilot_inventory_from_sgdp(
    metadata_path: Path,
    pilot_manifest_path: Path,
    output_tsv: Path,
    output_json: Optional[Path] = None,
) -> dict:
    metadata_rows = load_sgdp_metadata_rows(metadata_path)
    pilot_rows = [
        row
        for row in load_tsv_rows(pilot_manifest_path)
        if row.get("backbone_layer") == "modern" and row.get("source_family") == "SGDP" and row.get("include_in_pilot", "").lower() == "true"
    ]

    grouped: Dict[str, List[dict]] = {}
    for row in metadata_rows:
        grouped.setdefault(row.get("Population_ID", ""), []).append(row)

    inventory_rows = []
    for row in pilot_rows:
        population_code = derive_sgdp_population_id_from_standard_name(row["standard_name"])
        matches = grouped.get(population_code, [])
        region_values = sorted({match.get("Region", "") for match in matches if match.get("Region")})
        genders = {
            "male": sum(1 for match in matches if match.get("Gender", "").upper() == "M"),
            "female": sum(1 for match in matches if match.get("Gender", "").upper() == "F"),
        }
        inventory_rows.append(
            {
                "pilot_item_id": row["pilot_item_id"],
                "standard_name": row["standard_name"],
                "population_code": population_code,
                "macro_group": row["macro_group"],
                "sample_count": len(matches),
                "super_pops": ";".join(region_values),
                "male_count": genders["male"],
                "female_count": genders["female"],
                "first_samples": ";".join(match["SGDP_ID"] for match in matches[:5]),
                "status": "confirmed" if matches else "missing",
            }
        )

    write_tsv_rows(
        output_tsv,
        [
            "pilot_item_id",
            "standard_name",
            "population_code",
            "macro_group",
            "sample_count",
            "super_pops",
            "male_count",
            "female_count",
            "first_samples",
            "status",
        ],
        inventory_rows,
    )

    payload = {
        "metadata_path": str(metadata_path),
        "pilot_manifest": str(pilot_manifest_path),
        "output_tsv": str(output_tsv),
        "populations": len(inventory_rows),
        "confirmed": sum(1 for row in inventory_rows if row["status"] == "confirmed"),
        "missing": sum(1 for row in inventory_rows if row["status"] == "missing"),
        "results": inventory_rows,
    }
    if output_json:
        write_json_file(output_json, payload)
        payload["output_json"] = str(output_json)
    return payload


def build_source_confirmed_modern_pilot_manifest(
    candidate_manifest_path: Path,
    inventory_path: Path,
    output_tsv: Path,
    output_json: Optional[Path] = None,
    additional_inventory_paths: Optional[Sequence[Path]] = None,
) -> dict:
    candidate_rows = load_tsv_rows(candidate_manifest_path)
    inventory_rows = load_tsv_rows(inventory_path)
    for extra_path in additional_inventory_paths or []:
        inventory_rows.extend(load_tsv_rows(extra_path))
    inventory_by_name = {row["standard_name"]: row for row in inventory_rows}

    selected_rows = []
    for row in candidate_rows:
        inventory = inventory_by_name.get(row["standard_name"])
        if not inventory:
            continue
        enriched = dict(row)
        enriched["source_status"] = "source_confirmed_pilot"
        enriched["coordinate_status"] = "source_confirmed_pending_harmonization"
        enriched["pilot_population_code"] = inventory["population_code"]
        enriched["pilot_sample_count"] = inventory["sample_count"]
        enriched["pilot_super_pops"] = inventory["super_pops"]
        enriched["pilot_male_count"] = inventory["male_count"]
        enriched["pilot_female_count"] = inventory["female_count"]
        enriched["pilot_first_samples"] = inventory["first_samples"]
        enriched["pilot_inventory_status"] = inventory["status"]
        enriched["pilot_inventory_source_family"] = row["source_family"]
        selected_rows.append(enriched)

    fieldnames = [
        "standard_name",
        "macro_group",
        "subregion",
        "source_family",
        "source_collection",
        "router_role",
        "source_status",
        "include_in_default_router",
        "coordinate_status",
        "dedup_cluster",
        "pilot_population_code",
        "pilot_sample_count",
        "pilot_super_pops",
        "pilot_male_count",
        "pilot_female_count",
        "pilot_first_samples",
        "pilot_inventory_status",
        "pilot_inventory_source_family",
        "notes",
    ]
    write_tsv_rows(output_tsv, fieldnames, selected_rows)

    payload = {
        "candidate_manifest": str(candidate_manifest_path),
        "inventory_path": str(inventory_path),
        "output_tsv": str(output_tsv),
        "rows": len(selected_rows),
        "default_router_rows": sum(1 for row in selected_rows if row["include_in_default_router"].lower() == "true"),
        "results": selected_rows,
    }
    if output_json:
        write_json_file(output_json, payload)
        payload["output_json"] = str(output_json)
    return payload


def load_aadr_dataset_files(path: Path) -> List[dict]:
    payload = read_json_file(path)
    files = payload.get("data", {}).get("latestVersion", {}).get("files", [])
    rows = []
    for file_row in files:
        data_file = dict(file_row.get("dataFile", {}))
        if not data_file:
            continue
        rows.append(
            {
                "label": file_row.get("label", ""),
                "restricted": str(file_row.get("restricted", False)).lower(),
                "file_id": str(data_file.get("id", "")),
                "filename": data_file.get("filename", ""),
                "content_type": data_file.get("contentType", ""),
                "friendly_type": data_file.get("friendlyType", ""),
                "filesize": str(data_file.get("filesize", "")),
                "md5": data_file.get("md5", ""),
                "publication_date": data_file.get("publicationDate", ""),
                "creation_date": data_file.get("creationDate", ""),
                "last_update_time": data_file.get("lastUpdateTime", ""),
                "file_access_request": str(data_file.get("fileAccessRequest", False)).lower(),
            }
        )
    return rows


def build_ancient_aadr_file_inventory(
    dataset_json_path: Path,
    output_tsv: Path,
    output_json: Optional[Path] = None,
) -> dict:
    file_rows = load_aadr_dataset_files(dataset_json_path)
    file_rows.sort(key=lambda row: row["filename"])
    write_tsv_rows(
        output_tsv,
        [
            "label",
            "restricted",
            "file_id",
            "filename",
            "content_type",
            "friendly_type",
            "filesize",
            "md5",
            "publication_date",
            "creation_date",
            "last_update_time",
            "file_access_request",
        ],
        file_rows,
    )

    payload = {
        "dataset_json": str(dataset_json_path),
        "output_tsv": str(output_tsv),
        "files": len(file_rows),
        "results": file_rows,
    }
    if output_json:
        write_json_file(output_json, payload)
        payload["output_json"] = str(output_json)
    return payload


def build_source_confirmed_ancient_pilot_manifest(
    candidate_manifest_path: Path,
    inventory_path: Path,
    source_filename: str,
    output_tsv: Path,
    output_json: Optional[Path] = None,
) -> dict:
    candidate_rows = load_tsv_rows(candidate_manifest_path)
    inventory_rows = load_tsv_rows(inventory_path)
    inventory_by_filename = {row["filename"]: row for row in inventory_rows}
    source_row = inventory_by_filename.get(source_filename)
    if not source_row:
        raise ValueError(f"Source filename not found in AADR inventory: {source_filename}")

    selected_rows = []
    for row in candidate_rows:
        enriched = dict(row)
        enriched["source_status"] = "source_confirmed_pilot"
        enriched["coordinate_status"] = "source_confirmed_pending_harmonization"
        enriched["pilot_source_filename"] = source_row["filename"]
        enriched["pilot_source_label"] = source_row["label"]
        enriched["pilot_source_file_id"] = source_row["file_id"]
        enriched["pilot_source_filesize"] = source_row["filesize"]
        enriched["pilot_source_md5"] = source_row["md5"]
        enriched["pilot_source_restricted"] = source_row["restricted"]
        enriched["pilot_source_access_request"] = source_row["file_access_request"]
        selected_rows.append(enriched)

    fieldnames = [
        "standard_name",
        "macro_group",
        "subregion",
        "source_family",
        "source_collection",
        "router_role",
        "source_status",
        "include_in_default_router",
        "coordinate_status",
        "dedup_cluster",
        "pilot_source_filename",
        "pilot_source_label",
        "pilot_source_file_id",
        "pilot_source_filesize",
        "pilot_source_md5",
        "pilot_source_restricted",
        "pilot_source_access_request",
        "notes",
    ]
    write_tsv_rows(output_tsv, fieldnames, selected_rows)

    payload = {
        "candidate_manifest": str(candidate_manifest_path),
        "inventory_path": str(inventory_path),
        "source_filename": source_filename,
        "output_tsv": str(output_tsv),
        "rows": len(selected_rows),
        "default_router_rows": sum(1 for row in selected_rows if row["include_in_default_router"].lower() == "true"),
        "results": selected_rows,
    }
    if output_json:
        write_json_file(output_json, payload)
        payload["output_json"] = str(output_json)
    return payload


def load_aadr_ind_rows(path: Path) -> List[dict]:
    rows = []
    with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            parts = stripped.split(maxsplit=2)
            if len(parts) < 3:
                continue
            sample_id, sex, population_label = parts
            rows.append(
                {
                    "sample_id": sample_id,
                    "sex": sex,
                    "population_label": population_label,
                }
            )
    return rows


def build_ancient_population_inventory_from_aadr_ind(
    ind_path: Path,
    output_tsv: Path,
    output_json: Optional[Path] = None,
) -> dict:
    ind_rows = load_aadr_ind_rows(ind_path)
    grouped: Dict[str, List[dict]] = {}
    for row in ind_rows:
        grouped.setdefault(row["population_label"], []).append(row)

    inventory_rows = []
    for population_label, matches in sorted(grouped.items()):
        inventory_rows.append(
            {
                "population_label": population_label,
                "sample_count": len(matches),
                "male_count": sum(1 for match in matches if match["sex"] == "M"),
                "female_count": sum(1 for match in matches if match["sex"] == "F"),
                "unknown_sex_count": sum(1 for match in matches if match["sex"] not in {"M", "F"}),
                "first_samples": ";".join(match["sample_id"] for match in matches[:5]),
            }
        )

    write_tsv_rows(
        output_tsv,
        [
            "population_label",
            "sample_count",
            "male_count",
            "female_count",
            "unknown_sex_count",
            "first_samples",
        ],
        inventory_rows,
    )

    payload = {
        "ind_path": str(ind_path),
        "output_tsv": str(output_tsv),
        "populations": len(inventory_rows),
        "samples": len(ind_rows),
        "results": inventory_rows,
    }
    if output_json:
        write_json_file(output_json, payload)
        payload["output_json"] = str(output_json)
    return payload


def build_verified_pilot_harmonization_queue(
    modern_manifest_path: Path,
    ancient_manifest_path: Path,
    ancient_anchor_candidates_path: Path,
    output_tsv: Path,
    output_json: Optional[Path] = None,
) -> dict:
    modern_rows = load_tsv_rows(modern_manifest_path)
    ancient_rows = load_tsv_rows(ancient_manifest_path)
    candidate_rows = load_tsv_rows(ancient_anchor_candidates_path) if ancient_anchor_candidates_path.exists() else []

    candidate_by_name: Dict[str, List[dict]] = {}
    for row in candidate_rows:
        candidate_by_name.setdefault(row["standard_name"], []).append(row)
    for rows in candidate_by_name.values():
        rows.sort(key=lambda row: (int(row.get("priority", "999")), row.get("aadr_population_label", "")))

    queue_rows = []
    for row in modern_rows:
        queue_rows.append(
            {
                "backbone_layer": "modern",
                "standard_name": row["standard_name"],
                "macro_group": row["macro_group"],
                "source_family": row["source_family"],
                "source_collection": row["source_collection"],
                "source_artifact": row.get("pilot_inventory_source_family", row["source_family"]),
                "selector_type": "population_code",
                "selector_value": row.get("pilot_population_code", ""),
                "selector_notes": row.get("pilot_first_samples", ""),
                "harmonization_status": "ready_for_selector_mapping" if row.get("pilot_population_code") else "missing_selector",
                "priority": "1",
            }
        )

    for row in ancient_rows:
        candidates = candidate_by_name.get(row["standard_name"], [])
        primary = candidates[0] if candidates else None
        queue_rows.append(
            {
                "backbone_layer": "ancient",
                "standard_name": row["standard_name"],
                "macro_group": row["macro_group"],
                "source_family": row["source_family"],
                "source_collection": row["source_collection"],
                "source_artifact": row.get("pilot_source_filename", ""),
                "selector_type": "population_label" if primary else "",
                "selector_value": primary["aadr_population_label"] if primary else "",
                "selector_notes": primary["notes"] if primary else "No concrete AADR population label selected yet.",
                "harmonization_status": "ready_for_label_selection" if primary else "needs_anchor_mapping",
                "priority": primary.get("priority", "999") if primary else "999",
            }
        )

    queue_rows.sort(key=lambda row: (row["backbone_layer"], row["macro_group"], int(row["priority"]), row["standard_name"]))
    write_tsv_rows(
        output_tsv,
        [
            "backbone_layer",
            "standard_name",
            "macro_group",
            "source_family",
            "source_collection",
            "source_artifact",
            "selector_type",
            "selector_value",
            "selector_notes",
            "harmonization_status",
            "priority",
        ],
        queue_rows,
    )

    payload = {
        "modern_manifest": str(modern_manifest_path),
        "ancient_manifest": str(ancient_manifest_path),
        "ancient_anchor_candidates": str(ancient_anchor_candidates_path),
        "output_tsv": str(output_tsv),
        "rows": len(queue_rows),
        "modern_rows": len(modern_rows),
        "ancient_rows": len(ancient_rows),
        "ready_modern": sum(1 for row in queue_rows if row["backbone_layer"] == "modern" and row["harmonization_status"] == "ready_for_selector_mapping"),
        "ready_ancient": sum(1 for row in queue_rows if row["backbone_layer"] == "ancient" and row["harmonization_status"] == "ready_for_label_selection"),
        "unresolved_ancient": sum(1 for row in queue_rows if row["backbone_layer"] == "ancient" and row["harmonization_status"] == "needs_anchor_mapping"),
        "results": queue_rows,
    }
    if output_json:
        write_json_file(output_json, payload)
        payload["output_json"] = str(output_json)
    return payload


def build_verified_pilot_transformation_manifest(
    queue_path: Path,
    modern_manifest_path: Path,
    ancient_manifest_path: Path,
    output_tsv: Path,
    output_json: Optional[Path] = None,
) -> dict:
    queue_rows = load_tsv_rows(queue_path)
    modern_rows = {row["standard_name"]: row for row in load_tsv_rows(modern_manifest_path)}
    ancient_rows = {row["standard_name"]: row for row in load_tsv_rows(ancient_manifest_path)}

    manifest_rows = []
    for row in queue_rows:
        if row["backbone_layer"] == "modern":
            source_row = modern_rows.get(row["standard_name"], {})
            ready = row["harmonization_status"] == "ready_for_selector_mapping"
            target_artifact = "Modern_Verified_Backbone_v1"
        else:
            source_row = ancient_rows.get(row["standard_name"], {})
            ready = row["harmonization_status"] == "ready_for_label_selection"
            target_artifact = "Ancient_Verified_Backbone_v1"

        include_in_default_router = str(source_row.get("include_in_default_router", "")).lower() == "true"
        router_role = source_row.get("router_role", "")
        dedup_cluster = source_row.get("dedup_cluster", "")
        subregion = source_row.get("subregion", "")
        default_router_tier = "default_router" if include_in_default_router else "support_only"
        coordinate_ingest_required = "true"
        transformation_status = "ready_for_coordinate_ingest" if ready else "blocked_pending_selector_resolution"

        manifest_rows.append(
            {
                "backbone_layer": row["backbone_layer"],
                "standard_name": row["standard_name"],
                "macro_group": row["macro_group"],
                "subregion": subregion,
                "router_role": router_role,
                "default_router_tier": default_router_tier,
                "dedup_cluster": dedup_cluster,
                "source_family": row["source_family"],
                "source_collection": row["source_collection"],
                "source_artifact": row["source_artifact"],
                "selector_type": row["selector_type"],
                "selector_value": row["selector_value"],
                "selector_notes": row["selector_notes"],
                "planned_transformation_mode": "selector_to_validated_runtime_coordinate",
                "coordinate_ingest_required": coordinate_ingest_required,
                "transformation_status": transformation_status,
                "target_artifact": target_artifact,
                "target_row_name": row["standard_name"],
                "priority": row["priority"],
            }
        )

    manifest_rows.sort(key=lambda row: (row["backbone_layer"], row["macro_group"], int(row["priority"]), row["standard_name"]))
    write_tsv_rows(
        output_tsv,
        [
            "backbone_layer",
            "standard_name",
            "macro_group",
            "subregion",
            "router_role",
            "default_router_tier",
            "dedup_cluster",
            "source_family",
            "source_collection",
            "source_artifact",
            "selector_type",
            "selector_value",
            "selector_notes",
            "planned_transformation_mode",
            "coordinate_ingest_required",
            "transformation_status",
            "target_artifact",
            "target_row_name",
            "priority",
        ],
        manifest_rows,
    )

    payload = {
        "queue_path": str(queue_path),
        "modern_manifest": str(modern_manifest_path),
        "ancient_manifest": str(ancient_manifest_path),
        "output_tsv": str(output_tsv),
        "rows": len(manifest_rows),
        "ready_for_coordinate_ingest": sum(1 for row in manifest_rows if row["transformation_status"] == "ready_for_coordinate_ingest"),
        "blocked_rows": sum(1 for row in manifest_rows if row["transformation_status"] != "ready_for_coordinate_ingest"),
        "results": manifest_rows,
    }
    if output_json:
        write_json_file(output_json, payload)
        payload["output_json"] = str(output_json)
    return payload


def build_verified_runtime_manifests(
    transformation_manifest_path: Path,
    modern_output_tsv: Path,
    ancient_output_tsv: Path,
    output_json: Optional[Path] = None,
) -> dict:
    rows = load_tsv_rows(transformation_manifest_path)

    modern_rows = []
    ancient_rows = []
    for row in rows:
        manifest_row = {
            "standard_name": row["standard_name"],
            "macro_group": row["macro_group"],
            "subregion": row["subregion"],
            "source_family": row["source_family"],
            "source_collection": row["source_collection"],
            "router_role": row["router_role"],
            "source_status": "transformation_manifest_ready",
            "include_in_default_router": "true" if row["default_router_tier"] == "default_router" else "false",
            "coordinate_status": "pending_verified_ingest",
            "dedup_cluster": row["dedup_cluster"],
            "notes": f"{row['selector_notes']} [selector: {row['selector_type']}={row['selector_value']}; transformation_status={row['transformation_status']}]",
        }
        if row["backbone_layer"] == "modern":
            modern_rows.append(manifest_row)
        else:
            ancient_rows.append(manifest_row)

    modern_rows.sort(key=lambda row: (row["macro_group"], row["subregion"], row["standard_name"]))
    ancient_rows.sort(key=lambda row: (row["macro_group"], row["subregion"], row["standard_name"]))
    manifest_fields = [
        "standard_name",
        "macro_group",
        "subregion",
        "source_family",
        "source_collection",
        "router_role",
        "source_status",
        "include_in_default_router",
        "coordinate_status",
        "dedup_cluster",
        "notes",
    ]
    write_tsv_rows(modern_output_tsv, manifest_fields, modern_rows)
    write_tsv_rows(ancient_output_tsv, manifest_fields, ancient_rows)

    payload = {
        "transformation_manifest": str(transformation_manifest_path),
        "modern_output_tsv": str(modern_output_tsv),
        "ancient_output_tsv": str(ancient_output_tsv),
        "modern_rows": len(modern_rows),
        "ancient_rows": len(ancient_rows),
        "modern_default_router_rows": sum(1 for row in modern_rows if row["include_in_default_router"] == "true"),
        "ancient_default_router_rows": sum(1 for row in ancient_rows if row["include_in_default_router"] == "true"),
    }
    if output_json:
        write_json_file(output_json, payload)
        payload["output_json"] = str(output_json)
    return payload


def validate_verified_coordinate_import(
    coordinates_path: Path,
    manifest_path: Path,
    output_json: Optional[Path] = None,
) -> dict:
    manifest = load_reference_manifest(manifest_path)
    entries = load_g25_entries(coordinates_path)
    names = [entry.name for entry in entries]
    counts = Counter(names)
    duplicates = sorted(name for name, count in counts.items() if count > 1)
    manifest_names = list(manifest.keys())
    manifest_name_set = set(manifest_names)
    coordinate_name_set = set(names)
    missing = [name for name in manifest_names if name not in coordinate_name_set]
    unexpected = sorted(name for name in coordinate_name_set if name not in manifest_name_set)

    payload = {
        "coordinates_path": str(coordinates_path),
        "manifest_path": str(manifest_path),
        "coordinate_rows": len(entries),
        "manifest_rows": len(manifest_names),
        "matched_rows": sum(1 for name in manifest_names if name in coordinate_name_set),
        "missing_rows": missing,
        "unexpected_rows": unexpected,
        "duplicate_rows": duplicates,
        "is_valid_import": not missing and not unexpected and not duplicates,
    }
    if output_json:
        write_json_file(output_json, payload)
        payload["output_json"] = str(output_json)
    return payload


def assemble_verified_backbone_reference(
    coordinates_path: Path,
    manifest_path: Path,
    output_path: Path,
    output_json: Optional[Path] = None,
) -> dict:
    validation = validate_verified_coordinate_import(coordinates_path, manifest_path)
    if not validation["is_valid_import"]:
        raise ValueError(
            "Coordinate import is not valid for verified backbone assembly: "
            f"missing={len(validation['missing_rows'])}, "
            f"unexpected={len(validation['unexpected_rows'])}, "
            f"duplicates={len(validation['duplicate_rows'])}."
        )

    manifest = load_reference_manifest(manifest_path)
    entries = load_g25_entries(coordinates_path)
    entry_by_name = {entry.name: entry for entry in entries}
    ordered_entries = [entry_by_name[name] for name in manifest.keys()]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        "\n".join(g25_line_from_coords(entry.name, entry.coords) for entry in ordered_entries) + "\n",
        encoding="utf-8",
    )

    payload = {
        "coordinates_path": str(coordinates_path),
        "manifest_path": str(manifest_path),
        "output_path": str(output_path),
        "rows_written": len(ordered_entries),
        "first_rows": [entry.name for entry in ordered_entries[:5]],
    }
    if output_json:
        write_json_file(output_json, payload)
        payload["output_json"] = str(output_json)
    return payload


def split_semicolon_values(value: str) -> List[str]:
    return [item.strip() for item in value.split(";") if item.strip()]


def load_macroregion_registry(path: Path) -> List[dict]:
    rows: List[dict] = []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="	")
        for row in reader:
            row = dict(row)
            row["global_modern_gate_list"] = split_semicolon_values(row.get("global_modern_gate", ""))
            row["global_ancient_gate_list"] = split_semicolon_values(row.get("global_ancient_gate", ""))
            rows.append(row)
    return rows


def retained_route_groups(route_payload: dict, second_score_threshold: float, margin_threshold: float) -> List[dict]:
    groups = list(route_payload.get("group_results", []))
    if not groups:
        return []

    retained = [groups[0]]
    if len(groups) > 1:
        top1 = groups[0].get("routing_score", 0.0)
        top2 = groups[1].get("routing_score", 0.0)
        if top2 >= second_score_threshold or (top1 - top2) <= margin_threshold:
            retained.append(groups[1])
    return retained


def determine_backbone_routing(
    global_modern: dict,
    global_ancient: dict,
    macroregion_registry_path: Path,
    routing_policy_path: Path,
) -> dict:
    policy = read_json_file(routing_policy_path)
    registry = load_macroregion_registry(macroregion_registry_path)

    second_score_threshold = policy["dual_region_rules"]["enable_if_top2_score_gte"]
    margin_threshold = policy["dual_region_rules"]["enable_if_top1_minus_top2_margin_lte"]
    max_regions_preserved = policy["dual_region_rules"]["max_regions_preserved"]

    retained_modern = retained_route_groups(global_modern, second_score_threshold, margin_threshold)
    retained_ancient = retained_route_groups(global_ancient, second_score_threshold, margin_threshold)
    retained_modern_groups = [item["group"] for item in retained_modern]
    retained_ancient_groups = [item["group"] for item in retained_ancient]

    reasoning_flags: List[str] = []
    if len(retained_modern_groups) > 1:
        reasoning_flags.append("modern_top2_retained")
    if len(retained_ancient_groups) > 1:
        reasoning_flags.append("ancient_top2_retained")

    selected_regions: List[dict] = []
    for row in registry:
        modern_hits = [group for group in retained_modern_groups if group in row["global_modern_gate_list"]]
        ancient_hits = [group for group in retained_ancient_groups if group in row["global_ancient_gate_list"]]
        if modern_hits and ancient_hits:
            selected_regions.append(
                {
                    "region_id": row["region_id"],
                    "label": row["label"],
                    "modern_hits": modern_hits,
                    "ancient_hits": ancient_hits,
                    "routing_status": row.get("routing_status"),
                    "regional_rebuild_status": row.get("regional_rebuild_status"),
                }
            )

    if not selected_regions:
        mode = "unresolved"
        reasoning_flags.append("no_macroregion_overlap")
    elif len(selected_regions) == 1:
        mode = "single_region_mode"
    else:
        mode = "multi_region_mode"
        reasoning_flags.append("multi_region_candidate_set")

    return {
        "policy_id": policy["policy_id"],
        "mode": mode,
        "selected_regions": selected_regions[:max_regions_preserved],
        "retained_groups": {
            "modern": retained_modern,
            "ancient": retained_ancient,
        },
        "reasoning_flags": reasoning_flags,
        "registry_path": str(macroregion_registry_path),
        "policy_path": str(routing_policy_path),
    }


def cmd_inspect_raw(args: argparse.Namespace) -> int:
    summary, _ = parse_raw_dna(Path(args.input))
    print_json(asdict(summary))
    return 0


def cmd_normalize_raw(args: argparse.Namespace) -> int:
    summary, calls = parse_raw_dna(Path(args.input))
    output_path = Path(args.output)
    written_rows = write_normalized_raw(calls, output_path, autosomal_only=not args.keep_all_chromosomes)
    print_json(
        {
            "input": summary.file,
            "output": str(output_path),
            "vendor_hint": summary.vendor_hint,
            "written_rows": written_rows,
            "autosomal_only": not args.keep_all_chromosomes,
        }
    )
    return 0


def cmd_parse_k36(args: argparse.Namespace) -> int:
    summary = parse_k36(Path(args.input), args.name)
    payload = asdict(summary)
    print_json(payload)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(summary.canonical_line + "\n", encoding="utf-8")
    return 0


def cmd_k36_to_g25(args: argparse.Namespace) -> int:
    summary = parse_k36(Path(args.input), args.name)
    regression = load_k36_regression(Path(args.js))
    coords = compute_g25_from_k36(summary.values, regression)
    line = g25_line_from_coords(summary.sample_name, coords)
    payload = {
        "input": summary.file,
        "detected_format": summary.detected_format,
        "sample_name": summary.sample_name,
        "g25_line": line,
    }
    print_json(payload)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(line + "\n", encoding="utf-8")
    return 0


def cmd_distance(args: argparse.Namespace) -> int:
    targets = load_g25_entries(Path(args.target))
    references = load_g25_entries(Path(args.references))
    payload = []
    for target in targets:
        nearest = nearest_entries(target, references, args.top)
        payload.append(
            {
                "target": target.name,
                "results": [
                    {"distance": round(distance, 6), "reference": ref.name}
                    for distance, ref in nearest
                ],
            }
        )
    print_json(payload)
    return 0


def cmd_route(args: argparse.Namespace) -> int:
    targets = load_g25_entries(Path(args.target))
    references = load_g25_entries(Path(args.references))
    manifest = load_reference_manifest(Path(args.manifest))
    payload = []
    for target in targets:
        payload.append(build_route_payload(target, references, manifest, args.group_column, args.top, args.top_groups))
    print_json(payload)
    return 0


def cmd_analyze(args: argparse.Namespace) -> int:
    input_path = Path(args.input)
    sample_name = args.name or input_path.stem
    sample_slug = safe_ascii_slug(sample_name)
    run_dir = Path(args.output_dir) if args.output_dir else (DEFAULT_OUTPUT_ROOT / "analysis" / sample_slug)
    run_dir.mkdir(parents=True, exist_ok=True)

    raw_summary, _ = parse_raw_dna(input_path)
    raw_summary_path = run_dir / "raw_summary.json"
    write_json_file(raw_summary_path, asdict(raw_summary))

    staged_input = stage_input_for_external_tool(input_path, run_dir, sample_slug)
    vendor_candidates = [args.vendor] if args.vendor else infer_admix_vendor_candidates(raw_summary, input_path)
    k36_summary, admix_output_path, selected_vendor, vendor_attempts = run_admix_k36_auto(
        staged_input,
        sample_name,
        run_dir,
        vendor_candidates,
    )

    regression = load_k36_regression(Path(args.js))
    coords = compute_g25_from_k36(k36_summary.values, regression)
    target = G25Entry(name=sample_name, coords=coords)
    g25_line = g25_line_from_coords(sample_name, coords)
    g25_path = run_dir / f"{sample_slug}_simulated_g25.g25"
    g25_path.write_text(g25_line + "\n", encoding="utf-8")

    global_modern = route_single_target(
        target,
        Path(args.modern_global_refs),
        Path(args.modern_global_manifest),
        "macro_group",
        args.top,
        args.top_groups,
    )
    global_ancient = route_single_target(
        target,
        Path(args.ancient_global_refs),
        Path(args.ancient_global_manifest),
        "macro_group",
        args.top,
        args.top_groups,
    )
    write_json_file(run_dir / "route_modern_global.json", global_modern)
    write_json_file(run_dir / "route_ancient_global.json", global_ancient)

    routing_decision = determine_backbone_routing(
        global_modern,
        global_ancient,
        Path(args.backbone_macroregion_registry),
        Path(args.backbone_routing_policy),
    )
    routing_decision_path = run_dir / "routing_decision.json"
    write_json_file(routing_decision_path, routing_decision)

    regional_backbone = {}
    regional_legacy = {}
    selected_backbone_branch = None
    selected_legacy_branch = None
    legacy_fallback_enabled = args.enable_legacy_regional and not args.disable_legacy_regional
    legacy_fallback_used = False
    recommended_next_panel = {
        "primary": None,
        "secondary": None,
        "reason": "No implemented regional branch matched the global routing gates.",
    }

    selected_region_id = None
    if routing_decision["mode"] == "single_region_mode" and routing_decision["selected_regions"]:
        selected_region_id = routing_decision["selected_regions"][0]["region_id"]

    branch_rules = []
    if selected_region_id == "west_eurasia":
        branch_rules = [
            {
                "name": "modern_global_west_eurasia_gate",
                "passed": global_modern["predicted_group"] in {"Europe", "Caucasus_NearEast_NorthAfrica"},
                "predicted_group": global_modern["predicted_group"],
            },
            {
                "name": "ancient_global_west_eurasia_gate",
                "passed": global_ancient["predicted_group"] == "WestEurasia",
                "predicted_group": global_ancient["predicted_group"],
            },
        ]
    elif selected_region_id == "volga_ural_north_eurasia":
        branch_rules = [
            {
                "name": "modern_global_volga_ural_gate",
                "passed": global_modern["predicted_group"] in {"Europe", "SouthAsia_CentralAsia", "EastAsia_SoutheastAsia_Siberia"},
                "predicted_group": global_modern["predicted_group"],
            },
            {
                "name": "ancient_global_volga_ural_gate",
                "passed": global_ancient["predicted_group"] in {"WestEurasia", "NorthEurasia"},
                "predicted_group": global_ancient["predicted_group"],
            },
        ]
    elif selected_region_id == "south_asia":
        branch_rules = [
            {
                "name": "modern_global_south_asia_gate",
                "passed": global_modern["predicted_group"] == "SouthAsia_CentralAsia",
                "predicted_group": global_modern["predicted_group"],
            },
            {
                "name": "ancient_global_south_asia_gate",
                "passed": global_ancient["predicted_group"] in {"WestEurasia", "NorthEurasia", "EastAsia"},
                "predicted_group": global_ancient["predicted_group"],
            },
        ]

    if selected_region_id == "west_eurasia" and all(rule["passed"] for rule in branch_rules):
        selected_backbone_branch = "west_eurasia"
        west_branch = run_west_eurasia_branch(
            target,
            Path(args.modern_west_refs),
            Path(args.modern_west_manifest),
            Path(args.ancient_west_refs),
            Path(args.ancient_west_manifest),
            args.top,
            args.top_groups,
        )
        write_json_file(run_dir / "route_modern_west_eurasia.json", west_branch["modern_cluster"])
        write_json_file(run_dir / "route_ancient_west_family.json", west_branch["ancient_family"])
        write_json_file(run_dir / "route_ancient_west_core.json", west_branch["ancient_core"])

        recommended_next_panel = recommend_west_eurasia_detail(
            west_branch["modern_cluster"],
            west_branch["ancient_core"],
        )
        regional_backbone["west_eurasia"] = west_branch
    elif selected_region_id == "volga_ural_north_eurasia" and all(rule["passed"] for rule in branch_rules):
        selected_backbone_branch = "volga_ural_north_eurasia"
        volga_branch = run_volga_ural_north_eurasia_branch(
            target,
            Path(args.modern_volga_ural_refs),
            Path(args.modern_volga_ural_manifest),
            Path(args.ancient_volga_ural_refs),
            Path(args.ancient_volga_ural_manifest),
            args.top,
            args.top_groups,
        )
        write_json_file(run_dir / "route_modern_volga_ural_north_eurasia.json", volga_branch["modern_cluster"])
        write_json_file(run_dir / "route_ancient_volga_ural_family.json", volga_branch["ancient_family"])
        write_json_file(run_dir / "route_ancient_volga_ural_core.json", volga_branch["ancient_core"])

        recommended_next_panel = recommend_volga_ural_detail(
            volga_branch["modern_cluster"],
            volga_branch["ancient_core"],
            volga_branch["ancient_family"],
        )
        regional_backbone["volga_ural_north_eurasia"] = volga_branch
    elif selected_region_id == "south_asia" and all(rule["passed"] for rule in branch_rules):
        selected_backbone_branch = "south_asia"
        south_branch = run_south_asia_branch(
            target,
            Path(args.modern_south_asia_refs),
            Path(args.modern_south_asia_manifest),
            Path(args.ancient_south_asia_refs),
            Path(args.ancient_south_asia_manifest),
            args.top,
            args.top_groups,
        )
        write_json_file(run_dir / "route_modern_south_asia.json", south_branch["modern_cluster"])
        write_json_file(run_dir / "route_ancient_south_asia_family.json", south_branch["ancient_family"])
        write_json_file(run_dir / "route_ancient_south_asia_core.json", south_branch["ancient_core"])

        recommended_next_panel = recommend_south_asia_detail(
            south_branch["modern_cluster"],
            south_branch["ancient_core"],
            south_branch["ancient_family"],
        )
        regional_backbone["south_asia"] = south_branch
    elif legacy_fallback_enabled and selected_region_id == "west_eurasia" and all(rule["passed"] for rule in branch_rules):
        selected_legacy_branch = "west_eurasia"
        west_branch_legacy = run_west_eurasia_branch(
            target,
            DEFAULT_MODERN_WEST_REF,
            DEFAULT_MODERN_WEST_MANIFEST,
            DEFAULT_ANCIENT_WEST_REF,
            DEFAULT_ANCIENT_WEST_MANIFEST,
            args.top,
            args.top_groups,
        )
        write_json_file(run_dir / "route_modern_west_eurasia_legacy.json", west_branch_legacy["modern_cluster"])
        write_json_file(run_dir / "route_ancient_west_family_legacy.json", west_branch_legacy["ancient_family"])
        write_json_file(run_dir / "route_ancient_west_core_legacy.json", west_branch_legacy["ancient_core"])

        recommended_next_panel = recommend_west_eurasia_detail(
            west_branch_legacy["modern_cluster"],
            west_branch_legacy["ancient_core"],
        )
        legacy_fallback_used = True
        regional_legacy["west_eurasia"] = west_branch_legacy

    if selected_backbone_branch is None and selected_legacy_branch is None:
        if routing_decision["mode"] == "multi_region_mode":
            recommended_next_panel = {
                "primary": "multi_region_review",
                "secondary": None,
                "reason": "Backbone routing preserved more than one candidate region; no generic multi-region runtime branch is implemented yet.",
            }
        elif routing_decision["mode"] == "single_region_mode" and routing_decision["selected_regions"]:
            region_label = routing_decision["selected_regions"][0]["label"]
            recommended_next_panel = {
                "primary": "regional_branch_rebuild_required",
                "secondary": None,
                "reason": f"Backbone routing selected {region_label}, but no backbone-native runtime regional branch is implemented yet.",
            }

    payload = {
        "input": str(input_path),
        "sample_name": sample_name,
        "sample_slug": sample_slug,
        "run_dir": str(run_dir),
        "artifacts": {
            "raw_summary": str(raw_summary_path),
            "staged_input": str(staged_input),
            "admix_k36": str(admix_output_path),
            "simulated_g25": str(g25_path),
            "routing_decision": str(routing_decision_path),
        },
        "runtime": {
            "method_id": "backbone_method_v1",
            "backbone_regional_branch_used": selected_backbone_branch,
            "legacy_regional_fallback_enabled": legacy_fallback_enabled,
            "legacy_regional_fallback_used": legacy_fallback_used,
        },
        "raw_summary": asdict(raw_summary),
        "admix": {
            "selected_vendor": selected_vendor,
            "vendor_candidates": vendor_candidates,
            "vendor_attempts": vendor_attempts,
            "k36_total": round(k36_summary.total, 6),
            "top_components": top_k36_components(k36_summary, 10),
        },
        "simulated_g25": {
            "path": str(g25_path),
            "line": g25_line,
        },
        "routing": {
            "global": {
                "modern_macro": global_modern,
                "ancient_macro": global_ancient,
            },
            "decision": routing_decision,
            "regional_branch_rules": branch_rules,
            "selected_backbone_branch": selected_backbone_branch,
            "regional_backbone": regional_backbone,
            "selected_legacy_branch": selected_legacy_branch,
            "regional_legacy": regional_legacy,
        },
        "recommended_next_panel": recommended_next_panel,
    }

    if selected_backbone_branch == "west_eurasia":
        payload["artifacts"]["route_modern_west_eurasia"] = str(run_dir / "route_modern_west_eurasia.json")
        payload["artifacts"]["route_ancient_west_family"] = str(run_dir / "route_ancient_west_family.json")
        payload["artifacts"]["route_ancient_west_core"] = str(run_dir / "route_ancient_west_core.json")
    if selected_backbone_branch == "volga_ural_north_eurasia":
        payload["artifacts"]["route_modern_volga_ural_north_eurasia"] = str(run_dir / "route_modern_volga_ural_north_eurasia.json")
        payload["artifacts"]["route_ancient_volga_ural_family"] = str(run_dir / "route_ancient_volga_ural_family.json")
        payload["artifacts"]["route_ancient_volga_ural_core"] = str(run_dir / "route_ancient_volga_ural_core.json")
    if selected_backbone_branch == "south_asia":
        payload["artifacts"]["route_modern_south_asia"] = str(run_dir / "route_modern_south_asia.json")
        payload["artifacts"]["route_ancient_south_asia_family"] = str(run_dir / "route_ancient_south_asia_family.json")
        payload["artifacts"]["route_ancient_south_asia_core"] = str(run_dir / "route_ancient_south_asia_core.json")
    if selected_legacy_branch == "west_eurasia":
        payload["artifacts"]["route_modern_west_eurasia_legacy"] = str(run_dir / "route_modern_west_eurasia_legacy.json")
        payload["artifacts"]["route_ancient_west_family_legacy"] = str(run_dir / "route_ancient_west_family_legacy.json")
        payload["artifacts"]["route_ancient_west_core_legacy"] = str(run_dir / "route_ancient_west_core_legacy.json")

    analysis_path = run_dir / "analysis.json"
    payload["artifacts"]["analysis"] = str(analysis_path)
    write_json_file(analysis_path, payload)
    print_json(payload)
    return 0


def cmd_init_verified_pilot(args: argparse.Namespace) -> int:
    pilot_manifest = Path(args.pilot_manifest)
    provenance_template = Path(args.provenance_template)
    raw_root = Path(args.raw_root)
    provenance_root = Path(args.provenance_root)
    output_dir = Path(args.output_dir)

    payload = initialize_official_source_ingestion_pilot(
        pilot_manifest,
        provenance_template,
        raw_root,
        provenance_root,
        output_dir,
    )
    print_json(payload)
    return 0


def cmd_register_pilot_source(args: argparse.Namespace) -> int:
    payload = register_official_source_for_pilot(
        args.pilot_item_id,
        Path(args.source_file),
        args.official_url,
        Path(args.item_manifest),
        Path(args.provenance_index),
        Path(args.status_path),
        retrieval_date=args.retrieval_date,
        version_label=args.version_label,
    )
    print_json(payload)
    return 0


def cmd_build_modern_pilot_inventory(args: argparse.Namespace) -> int:
    output_json = Path(args.output_json) if args.output_json else None
    payload = build_modern_pilot_inventory_from_igsr(
        Path(args.panel_file),
        Path(args.pilot_manifest),
        Path(args.output_tsv),
        output_json,
    )
    print_json(payload)
    return 0


def cmd_build_modern_sgdp_pilot_inventory(args: argparse.Namespace) -> int:
    output_json = Path(args.output_json) if args.output_json else None
    payload = build_modern_pilot_inventory_from_sgdp(
        Path(args.metadata_file),
        Path(args.pilot_manifest),
        Path(args.output_tsv),
        output_json,
    )
    print_json(payload)
    return 0


def cmd_build_modern_pilot_manifest(args: argparse.Namespace) -> int:
    output_json = Path(args.output_json) if args.output_json else None
    additional = []
    if args.sgdp_inventory_tsv:
        additional.append(Path(args.sgdp_inventory_tsv))
    payload = build_source_confirmed_modern_pilot_manifest(
        Path(args.candidate_manifest),
        Path(args.inventory_tsv),
        Path(args.output_tsv),
        output_json,
        additional_inventory_paths=additional,
    )
    print_json(payload)
    return 0


def cmd_build_ancient_aadr_inventory(args: argparse.Namespace) -> int:
    output_json = Path(args.output_json) if args.output_json else None
    payload = build_ancient_aadr_file_inventory(
        Path(args.dataset_json),
        Path(args.output_tsv),
        output_json,
    )
    print_json(payload)
    return 0


def cmd_build_ancient_pilot_manifest(args: argparse.Namespace) -> int:
    output_json = Path(args.output_json) if args.output_json else None
    payload = build_source_confirmed_ancient_pilot_manifest(
        Path(args.candidate_manifest),
        Path(args.inventory_tsv),
        args.source_filename,
        Path(args.output_tsv),
        output_json,
    )
    print_json(payload)
    return 0


def cmd_build_ancient_population_inventory(args: argparse.Namespace) -> int:
    output_json = Path(args.output_json) if args.output_json else None
    payload = build_ancient_population_inventory_from_aadr_ind(
        Path(args.ind_file),
        Path(args.output_tsv),
        output_json,
    )
    print_json(payload)
    return 0


def cmd_build_verified_pilot_harmonization_queue(args: argparse.Namespace) -> int:
    output_json = Path(args.output_json) if args.output_json else None
    payload = build_verified_pilot_harmonization_queue(
        Path(args.modern_manifest),
        Path(args.ancient_manifest),
        Path(args.ancient_anchor_candidates),
        Path(args.output_tsv),
        output_json,
    )
    print_json(payload)
    return 0


def cmd_build_verified_pilot_transformation_manifest(args: argparse.Namespace) -> int:
    output_json = Path(args.output_json) if args.output_json else None
    payload = build_verified_pilot_transformation_manifest(
        Path(args.queue_tsv),
        Path(args.modern_manifest),
        Path(args.ancient_manifest),
        Path(args.output_tsv),
        output_json,
    )
    print_json(payload)
    return 0


def cmd_build_verified_runtime_manifests(args: argparse.Namespace) -> int:
    output_json = Path(args.output_json) if args.output_json else None
    payload = build_verified_runtime_manifests(
        Path(args.transformation_manifest),
        Path(args.modern_output_tsv),
        Path(args.ancient_output_tsv),
        output_json,
    )
    print_json(payload)
    return 0


def cmd_validate_verified_coordinate_import(args: argparse.Namespace) -> int:
    output_json = Path(args.output_json) if args.output_json else None
    payload = validate_verified_coordinate_import(
        Path(args.coordinates),
        Path(args.manifest),
        output_json,
    )
    print_json(payload)
    return 0


def cmd_assemble_verified_backbone_reference(args: argparse.Namespace) -> int:
    output_json = Path(args.output_json) if args.output_json else None
    payload = assemble_verified_backbone_reference(
        Path(args.coordinates),
        Path(args.manifest),
        Path(args.output),
        output_json,
    )
    print_json(payload)
    return 0


def cmd_build_verified_coordinate_import_from_vahaduo(args: argparse.Namespace) -> int:
    output_json = Path(args.output_json) if args.output_json else None
    payload = build_verified_coordinate_import_from_vahaduo_bridge(
        Path(args.bridge),
        Path(args.downloads_dir),
        Path(args.output),
        output_json,
    )
    print_json(payload)
    return 0


def cmd_two_way(args: argparse.Namespace) -> int:
    targets = load_g25_entries(Path(args.target))
    references = load_g25_entries(Path(args.references))
    payload = []
    for target in targets:
        models = best_two_way_models(target, references, args.top)
        payload.append(
            {
                "target": target.name,
                "results": [
                    {
                        "distance": round(distance, 6),
                        "left": left,
                        "left_weight": round(left_weight, 6),
                        "right": right,
                        "right_weight": round(right_weight, 6),
                    }
                    for distance, left, left_weight, right, right_weight in models
                ],
            }
        )
    print_json(payload)
    return 0


def cmd_panel_fit(args: argparse.Namespace) -> int:
    targets = load_g25_entries(Path(args.target))
    if len(targets) != 1:
        raise ValueError("panel-fit currently expects exactly one target row.")

    references = load_g25_entries(Path(args.references))
    manifest = load_reference_manifest(Path(args.manifest))
    payload = summarize_panel_fit(
        targets[0],
        references,
        manifest,
        args.group_column,
        args.iterations,
        args.top_references,
    )
    print_json(payload)
    if args.output:
        write_json_file(Path(args.output), payload)
    return 0


def cmd_adaptive_panel_fit(args: argparse.Namespace) -> int:
    targets = load_g25_entries(Path(args.target))
    if len(targets) != 1:
        raise ValueError("adaptive-panel-fit currently expects exactly one target row.")

    target = targets[0]
    references = load_g25_entries(Path(args.references))
    manifest = load_reference_manifest(Path(args.manifest))

    broad_fit = summarize_panel_fit(
        target,
        references,
        manifest,
        args.group_column,
        args.iterations,
        args.top_references,
    )
    selected_groups = select_adaptive_groups(
        broad_fit["groups"],
        args.min_groups,
        args.max_groups,
        args.min_group_weight,
    )
    reduced_references = filter_panel_by_groups(references, manifest, args.group_column, selected_groups)
    reduced_fit = summarize_panel_fit(
        target,
        reduced_references,
        manifest,
        args.group_column,
        args.iterations,
        args.top_references,
    )

    payload = {
        "target": target.name,
        "panel_name": broad_fit.get("panel_name"),
        "group_column": args.group_column,
        "selection": {
            "min_groups": args.min_groups,
            "max_groups": args.max_groups,
            "min_group_weight": args.min_group_weight,
            "selected_groups": selected_groups,
        },
        "broad_fit": broad_fit,
        "reduced_fit": reduced_fit,
    }
    print_json(payload)
    if args.output:
        write_json_file(Path(args.output), payload)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Minimal local MVP for autosomal raw DNA preparation and G25-style modeling."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_raw = subparsers.add_parser("inspect-raw", help="Inspect a raw DNA file.")
    inspect_raw.add_argument("input", help="Path to raw DNA file.")
    inspect_raw.set_defaults(func=cmd_inspect_raw)

    normalize_raw = subparsers.add_parser("normalize-raw", help="Normalize raw DNA into a TSV.")
    normalize_raw.add_argument("input", help="Path to raw DNA file.")
    normalize_raw.add_argument("output", help="Where to write the normalized TSV.")
    normalize_raw.add_argument(
        "--keep-all-chromosomes",
        action="store_true",
        help="Keep X/Y/MT rows too. By default only autosomes 1-22 are written.",
    )
    normalize_raw.set_defaults(func=cmd_normalize_raw)

    parse_k36_cmd = subparsers.add_parser("parse-k36", help="Normalize K36 text into a canonical line.")
    parse_k36_cmd.add_argument("input", help="Path to pasted K36 text or csv line.")
    parse_k36_cmd.add_argument("--name", help="Override sample name.", default=None)
    parse_k36_cmd.add_argument("--output", help="Optional path for canonical K36 line.", default=None)
    parse_k36_cmd.set_defaults(func=cmd_parse_k36)

    k36_to_g25_cmd = subparsers.add_parser(
        "k36-to-g25",
        help="Convert K36 input into simulated G25 using Allelocator regression JS.",
    )
    k36_to_g25_cmd.add_argument("input", help="Path to K36 text, canonical line, or admix output file.")
    k36_to_g25_cmd.add_argument(
        "--js",
        default=str(DEFAULT_SUPPORT_DATA_DIR / "K36vertical.js"),
        help="Path to the downloaded Allelocator K36vertical.js file.",
    )
    k36_to_g25_cmd.add_argument("--name", help="Override sample name.", default=None)
    k36_to_g25_cmd.add_argument("--output", help="Optional path for simulated G25 line.", default=None)
    k36_to_g25_cmd.set_defaults(func=cmd_k36_to_g25)

    distance_cmd = subparsers.add_parser("distance", help="Find nearest G25 references.")
    distance_cmd.add_argument("target", help="Target G25 file.")
    distance_cmd.add_argument("references", help="Reference G25 file.")
    distance_cmd.add_argument("--top", type=int, default=10, help="How many rows to return.")
    distance_cmd.set_defaults(func=cmd_distance)

    route_cmd = subparsers.add_parser(
        "route",
        help="Summarize nearest references by manifest group for global or regional routing.",
    )
    route_cmd.add_argument("target", help="Target G25 file.")
    route_cmd.add_argument("references", help="Reference G25 file.")
    route_cmd.add_argument("manifest", help="Manifest TSV/CSV with at least standard_name and group columns.")
    route_cmd.add_argument("--group-column", default="macro_group", help="Manifest column to aggregate by.")
    route_cmd.add_argument("--top", type=int, default=12, help="How many nearest references to inspect.")
    route_cmd.add_argument("--top-groups", type=int, default=5, help="How many grouped results to return.")
    route_cmd.set_defaults(func=cmd_route)

    analyze_cmd = subparsers.add_parser(
        "analyze",
        help="Run the full raw -> K36 -> simulated G25 -> routing pipeline with automatic branch selection.",
    )
    analyze_cmd.add_argument("input", help="Path to raw DNA file.")
    analyze_cmd.add_argument("--name", help="Optional sample name override.", default=None)
    analyze_cmd.add_argument("--vendor", help="Optional admix vendor override.", default=None)
    analyze_cmd.add_argument("--output-dir", help="Optional run directory override.", default=None)
    analyze_cmd.add_argument(
        "--js",
        default=str(DEFAULT_SUPPORT_DATA_DIR / "K36vertical.js"),
        help="Path to Allelocator K36vertical.js.",
    )
    analyze_cmd.add_argument(
        "--modern-global-refs",
        default=str(DEFAULT_MODERN_GLOBAL_REF),
        help="Path to Modern_Global reference file.",
    )
    analyze_cmd.add_argument(
        "--modern-global-manifest",
        default=str(DEFAULT_MODERN_GLOBAL_MANIFEST),
        help="Path to Modern_Global manifest.",
    )
    analyze_cmd.add_argument(
        "--ancient-global-refs",
        default=str(DEFAULT_ANCIENT_GLOBAL_REF),
        help="Path to Ancient_Global reference file.",
    )
    analyze_cmd.add_argument(
        "--ancient-global-manifest",
        default=str(DEFAULT_ANCIENT_GLOBAL_MANIFEST),
        help="Path to Ancient_Global manifest.",
    )
    analyze_cmd.add_argument(
        "--modern-west-refs",
        default=str(DEFAULT_VERIFIED_MODERN_WEST_REF),
        help="Path to backbone-native Modern_WestEurasia reference file.",
    )
    analyze_cmd.add_argument(
        "--modern-west-manifest",
        default=str(DEFAULT_VERIFIED_MODERN_WEST_MANIFEST),
        help="Path to backbone-native Modern_WestEurasia manifest.",
    )
    analyze_cmd.add_argument(
        "--ancient-west-refs",
        default=str(DEFAULT_VERIFIED_ANCIENT_WEST_REF),
        help="Path to backbone-native Ancient_WestEurasia reference file.",
    )
    analyze_cmd.add_argument(
        "--ancient-west-manifest",
        default=str(DEFAULT_VERIFIED_ANCIENT_WEST_MANIFEST),
        help="Path to backbone-native Ancient_WestEurasia manifest.",
    )
    analyze_cmd.add_argument(
        "--modern-volga-ural-refs",
        default=str(DEFAULT_VERIFIED_MODERN_VOLGA_URAL_REF),
        help="Path to backbone-native Modern_VolgaUralNorthEurasia reference file.",
    )
    analyze_cmd.add_argument(
        "--modern-volga-ural-manifest",
        default=str(DEFAULT_VERIFIED_MODERN_VOLGA_URAL_MANIFEST),
        help="Path to backbone-native Modern_VolgaUralNorthEurasia manifest.",
    )
    analyze_cmd.add_argument(
        "--ancient-volga-ural-refs",
        default=str(DEFAULT_VERIFIED_ANCIENT_VOLGA_URAL_REF),
        help="Path to backbone-native Ancient_VolgaUralNorthEurasia reference file.",
    )
    analyze_cmd.add_argument(
        "--ancient-volga-ural-manifest",
        default=str(DEFAULT_VERIFIED_ANCIENT_VOLGA_URAL_MANIFEST),
        help="Path to backbone-native Ancient_VolgaUralNorthEurasia manifest.",
    )
    analyze_cmd.add_argument(
        "--modern-south-asia-refs",
        default=str(DEFAULT_VERIFIED_MODERN_SOUTH_ASIA_REF),
        help="Path to backbone-native Modern_SouthAsia reference file.",
    )
    analyze_cmd.add_argument(
        "--modern-south-asia-manifest",
        default=str(DEFAULT_VERIFIED_MODERN_SOUTH_ASIA_MANIFEST),
        help="Path to backbone-native Modern_SouthAsia manifest.",
    )
    analyze_cmd.add_argument(
        "--ancient-south-asia-refs",
        default=str(DEFAULT_VERIFIED_ANCIENT_SOUTH_ASIA_REF),
        help="Path to backbone-native Ancient_SouthAsia reference file.",
    )
    analyze_cmd.add_argument(
        "--ancient-south-asia-manifest",
        default=str(DEFAULT_VERIFIED_ANCIENT_SOUTH_ASIA_MANIFEST),
        help="Path to backbone-native Ancient_SouthAsia manifest.",
    )
    analyze_cmd.add_argument(
        "--backbone-macroregion-registry",
        default=str(DEFAULT_BACKBONE_MACROREGION_REGISTRY),
        help="Path to backbone macroregion registry TSV.",
    )
    analyze_cmd.add_argument(
        "--backbone-routing-policy",
        default=str(DEFAULT_BACKBONE_ROUTING_POLICY),
        help="Path to backbone routing policy JSON.",
    )
    analyze_cmd.add_argument(
        "--enable-legacy-regional",
        action="store_true",
        help="Allow archived legacy regional fallback branches after backbone routing.",
    )
    analyze_cmd.add_argument(
        "--disable-legacy-regional",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    analyze_cmd.add_argument("--top", type=int, default=12, help="How many nearest references to inspect per stage.")
    analyze_cmd.add_argument("--top-groups", type=int, default=5, help="How many grouped results to keep per stage.")
    analyze_cmd.set_defaults(func=cmd_analyze)

    init_verified_pilot_cmd = subparsers.add_parser(
        "init-verified-pilot",
        help="Create a filesystem scaffold and provenance stubs for the official-source ingestion pilot.",
    )
    init_verified_pilot_cmd.add_argument(
        "--pilot-manifest",
        default=str(DEFAULT_VERIFIED_BACKBONE_DIR / "pilots" / "official_source_ingestion_pilot_manifest.tsv"),
        help="Path to the official-source ingestion pilot manifest.",
    )
    init_verified_pilot_cmd.add_argument(
        "--provenance-template",
        default=str(DEFAULT_VERIFIED_BACKBONE_DIR / "provenance" / "provenance_template.json"),
        help="Path to the provenance template JSON.",
    )
    init_verified_pilot_cmd.add_argument(
        "--raw-root",
        default=str(DEFAULT_VERIFIED_BACKBONE_DIR / "raw_sources" / "pilot_source_bundle"),
        help="Directory where pilot raw-source bundle folders should be created.",
    )
    init_verified_pilot_cmd.add_argument(
        "--provenance-root",
        default=str(DEFAULT_VERIFIED_BACKBONE_DIR / "provenance" / "pilot_items"),
        help="Directory where per-item pilot provenance stubs should be written.",
    )
    init_verified_pilot_cmd.add_argument(
        "--output-dir",
        default=str(DEFAULT_VERIFIED_BACKBONE_DIR / "pilots" / "runtime_scaffold"),
        help="Directory for pilot bundle/item manifests and pilot status output.",
    )
    init_verified_pilot_cmd.set_defaults(func=cmd_init_verified_pilot)

    register_pilot_source_cmd = subparsers.add_parser(
        "register-pilot-source",
        help="Stage one official source file into the pilot scaffold and update provenance.",
    )
    register_pilot_source_cmd.add_argument("pilot_item_id", help="Pilot item id from the pilot manifest.")
    register_pilot_source_cmd.add_argument("source_file", help="Local path to the downloaded official source file.")
    register_pilot_source_cmd.add_argument("--official-url", required=True, help="Official source URL for provenance.")
    register_pilot_source_cmd.add_argument(
        "--retrieval-date",
        default=None,
        help="Retrieval date in YYYY-MM-DD. Defaults to today.",
    )
    register_pilot_source_cmd.add_argument(
        "--version-label",
        default=None,
        help="Optional version or release label override.",
    )
    register_pilot_source_cmd.add_argument(
        "--item-manifest",
        default=str(DEFAULT_VERIFIED_BACKBONE_DIR / "pilots" / "runtime_scaffold" / "official_source_ingestion_pilot_items.tsv"),
        help="Path to the pilot item manifest.",
    )
    register_pilot_source_cmd.add_argument(
        "--provenance-index",
        default=str(DEFAULT_VERIFIED_BACKBONE_DIR / "pilots" / "runtime_scaffold" / "official_source_ingestion_pilot_provenance_index.tsv"),
        help="Path to the pilot provenance index TSV.",
    )
    register_pilot_source_cmd.add_argument(
        "--status-path",
        default=str(DEFAULT_VERIFIED_BACKBONE_DIR / "pilots" / "runtime_scaffold" / "official_source_ingestion_pilot_status.json"),
        help="Path to the pilot status JSON.",
    )
    register_pilot_source_cmd.set_defaults(func=cmd_register_pilot_source)

    build_modern_pilot_inventory_cmd = subparsers.add_parser(
        "build-modern-pilot-inventory",
        help="Build a small population inventory for IGSR-backed modern pilot items from the official panel file.",
    )
    build_modern_pilot_inventory_cmd.add_argument(
        "--panel-file",
        default=str(DEFAULT_VERIFIED_BACKBONE_DIR / "raw_sources" / "pilot_source_bundle" / "modern_IGSR_1000G_Phase3" / "integrated_call_samples_v3.20130502.ALL.panel"),
        help="Path to the official IGSR/1000G panel file captured for the pilot.",
    )
    build_modern_pilot_inventory_cmd.add_argument(
        "--pilot-manifest",
        default=str(DEFAULT_VERIFIED_BACKBONE_DIR / "pilots" / "official_source_ingestion_pilot_manifest.tsv"),
        help="Path to the pilot manifest.",
    )
    build_modern_pilot_inventory_cmd.add_argument(
        "--output-tsv",
        default=str(DEFAULT_VERIFIED_BACKBONE_DIR / "pilots" / "runtime_scaffold" / "modern_igsr_pilot_population_inventory.tsv"),
        help="Where to write the pilot population inventory TSV.",
    )
    build_modern_pilot_inventory_cmd.add_argument(
        "--output-json",
        default=str(DEFAULT_VERIFIED_BACKBONE_DIR / "pilots" / "runtime_scaffold" / "modern_igsr_pilot_population_inventory.json"),
        help="Optional JSON summary output path.",
    )
    build_modern_pilot_inventory_cmd.set_defaults(func=cmd_build_modern_pilot_inventory)

    build_modern_sgdp_pilot_inventory_cmd = subparsers.add_parser(
        "build-modern-sgdp-pilot-inventory",
        help="Build a small population inventory for SGDP-backed modern pilot items from the official SGDP metadata file.",
    )
    build_modern_sgdp_pilot_inventory_cmd.add_argument(
        "--metadata-file",
        default=str(DEFAULT_VERIFIED_BACKBONE_DIR / "downloads" / "SGDP_metainformation_update.txt"),
        help="Path to the official SGDP metadata file captured for the pilot.",
    )
    build_modern_sgdp_pilot_inventory_cmd.add_argument(
        "--pilot-manifest",
        default=str(DEFAULT_VERIFIED_BACKBONE_DIR / "pilots" / "official_source_ingestion_pilot_manifest.tsv"),
        help="Path to the pilot manifest.",
    )
    build_modern_sgdp_pilot_inventory_cmd.add_argument(
        "--output-tsv",
        default=str(DEFAULT_VERIFIED_BACKBONE_DIR / "pilots" / "runtime_scaffold" / "modern_sgdp_pilot_population_inventory.tsv"),
        help="Where to write the SGDP-derived pilot population inventory TSV.",
    )
    build_modern_sgdp_pilot_inventory_cmd.add_argument(
        "--output-json",
        default=str(DEFAULT_VERIFIED_BACKBONE_DIR / "pilots" / "runtime_scaffold" / "modern_sgdp_pilot_population_inventory.json"),
        help="Optional JSON summary output path.",
    )
    build_modern_sgdp_pilot_inventory_cmd.set_defaults(func=cmd_build_modern_sgdp_pilot_inventory)

    build_modern_pilot_manifest_cmd = subparsers.add_parser(
        "build-modern-pilot-manifest",
        help="Build a source-confirmed modern pilot manifest by merging candidate rows with IGSR-derived pilot inventory.",
    )
    build_modern_pilot_manifest_cmd.add_argument(
        "--candidate-manifest",
        default=str(DEFAULT_VERIFIED_BACKBONE_DIR / "manifests" / "Modern_Verified_Backbone_v1_candidate_manifest.tsv"),
        help="Path to the verified modern candidate manifest.",
    )
    build_modern_pilot_manifest_cmd.add_argument(
        "--inventory-tsv",
        default=str(DEFAULT_VERIFIED_BACKBONE_DIR / "pilots" / "runtime_scaffold" / "modern_igsr_pilot_population_inventory.tsv"),
        help="Path to the IGSR-derived modern pilot inventory TSV.",
    )
    build_modern_pilot_manifest_cmd.add_argument(
        "--sgdp-inventory-tsv",
        default=str(DEFAULT_VERIFIED_BACKBONE_DIR / "pilots" / "runtime_scaffold" / "modern_sgdp_pilot_population_inventory.tsv"),
        help="Optional SGDP-derived modern pilot inventory TSV to merge into the manifest.",
    )
    build_modern_pilot_manifest_cmd.add_argument(
        "--output-tsv",
        default=str(DEFAULT_VERIFIED_BACKBONE_DIR / "pilots" / "runtime_scaffold" / "Modern_Verified_Backbone_v1_pilot_manifest.tsv"),
        help="Where to write the source-confirmed modern pilot manifest.",
    )
    build_modern_pilot_manifest_cmd.add_argument(
        "--output-json",
        default=str(DEFAULT_VERIFIED_BACKBONE_DIR / "pilots" / "runtime_scaffold" / "Modern_Verified_Backbone_v1_pilot_manifest.json"),
        help="Optional JSON summary output path.",
    )
    build_modern_pilot_manifest_cmd.set_defaults(func=cmd_build_modern_pilot_manifest)

    build_ancient_aadr_inventory_cmd = subparsers.add_parser(
        "build-ancient-aadr-inventory",
        help="Build an AADR file inventory from the official Harvard Dataverse dataset metadata JSON.",
    )
    build_ancient_aadr_inventory_cmd.add_argument(
        "--dataset-json",
        default=str(DEFAULT_VERIFIED_BACKBONE_DIR / "downloads" / "aadr_dataverse_dataset.json"),
        help="Path to the downloaded AADR Harvard Dataverse dataset metadata JSON.",
    )
    build_ancient_aadr_inventory_cmd.add_argument(
        "--output-tsv",
        default=str(DEFAULT_VERIFIED_BACKBONE_DIR / "pilots" / "runtime_scaffold" / "aadr_dataset_file_inventory.tsv"),
        help="Where to write the AADR file inventory TSV.",
    )
    build_ancient_aadr_inventory_cmd.add_argument(
        "--output-json",
        default=str(DEFAULT_VERIFIED_BACKBONE_DIR / "pilots" / "runtime_scaffold" / "aadr_dataset_file_inventory.json"),
        help="Optional JSON summary output path.",
    )
    build_ancient_aadr_inventory_cmd.set_defaults(func=cmd_build_ancient_aadr_inventory)

    build_ancient_pilot_manifest_cmd = subparsers.add_parser(
        "build-ancient-pilot-manifest",
        help="Build a source-confirmed ancient pilot manifest using an official AADR file inventory row.",
    )
    build_ancient_pilot_manifest_cmd.add_argument(
        "--candidate-manifest",
        default=str(DEFAULT_VERIFIED_BACKBONE_DIR / "manifests" / "Ancient_Verified_Backbone_v1_candidate_manifest.tsv"),
        help="Path to the verified ancient candidate manifest.",
    )
    build_ancient_pilot_manifest_cmd.add_argument(
        "--inventory-tsv",
        default=str(DEFAULT_VERIFIED_BACKBONE_DIR / "pilots" / "runtime_scaffold" / "aadr_dataset_file_inventory.tsv"),
        help="Path to the AADR-derived ancient file inventory TSV.",
    )
    build_ancient_pilot_manifest_cmd.add_argument(
        "--source-filename",
        default="v62.0_HO_public.ind",
        help="AADR source filename to attach to every ancient pilot row.",
    )
    build_ancient_pilot_manifest_cmd.add_argument(
        "--output-tsv",
        default=str(DEFAULT_VERIFIED_BACKBONE_DIR / "pilots" / "runtime_scaffold" / "Ancient_Verified_Backbone_v1_pilot_manifest.tsv"),
        help="Where to write the source-confirmed ancient pilot manifest.",
    )
    build_ancient_pilot_manifest_cmd.add_argument(
        "--output-json",
        default=str(DEFAULT_VERIFIED_BACKBONE_DIR / "pilots" / "runtime_scaffold" / "Ancient_Verified_Backbone_v1_pilot_manifest.json"),
        help="Optional JSON summary output path.",
    )
    build_ancient_pilot_manifest_cmd.set_defaults(func=cmd_build_ancient_pilot_manifest)

    build_ancient_population_inventory_cmd = subparsers.add_parser(
        "build-ancient-population-inventory",
        help="Build a population-label inventory from an official AADR .ind file.",
    )
    build_ancient_population_inventory_cmd.add_argument(
        "--ind-file",
        default=str(DEFAULT_VERIFIED_BACKBONE_DIR / "downloads" / "v62.0_HO_public.ind"),
        help="Path to the downloaded AADR .ind file.",
    )
    build_ancient_population_inventory_cmd.add_argument(
        "--output-tsv",
        default=str(DEFAULT_VERIFIED_BACKBONE_DIR / "pilots" / "runtime_scaffold" / "aadr_ind_population_inventory.tsv"),
        help="Where to write the AADR population inventory TSV.",
    )
    build_ancient_population_inventory_cmd.add_argument(
        "--output-json",
        default=str(DEFAULT_VERIFIED_BACKBONE_DIR / "pilots" / "runtime_scaffold" / "aadr_ind_population_inventory.json"),
        help="Optional JSON summary output path.",
    )
    build_ancient_population_inventory_cmd.set_defaults(func=cmd_build_ancient_population_inventory)

    build_verified_pilot_harmonization_queue_cmd = subparsers.add_parser(
        "build-verified-pilot-harmonization-queue",
        help="Build the next-step harmonization queue from source-confirmed pilot manifests.",
    )
    build_verified_pilot_harmonization_queue_cmd.add_argument(
        "--modern-manifest",
        default=str(DEFAULT_VERIFIED_BACKBONE_DIR / "pilots" / "runtime_scaffold" / "Modern_Verified_Backbone_v1_pilot_manifest.tsv"),
        help="Path to the source-confirmed modern pilot manifest.",
    )
    build_verified_pilot_harmonization_queue_cmd.add_argument(
        "--ancient-manifest",
        default=str(DEFAULT_VERIFIED_BACKBONE_DIR / "pilots" / "runtime_scaffold" / "Ancient_Verified_Backbone_v1_pilot_manifest.tsv"),
        help="Path to the source-confirmed ancient pilot manifest.",
    )
    build_verified_pilot_harmonization_queue_cmd.add_argument(
        "--ancient-anchor-candidates",
        default=str(DEFAULT_VERIFIED_BACKBONE_DIR / "pilots" / "runtime_scaffold" / "Ancient_Verified_Backbone_v1_anchor_candidates.tsv"),
        help="Path to the provisional ancient anchor candidate map.",
    )
    build_verified_pilot_harmonization_queue_cmd.add_argument(
        "--output-tsv",
        default=str(DEFAULT_VERIFIED_BACKBONE_DIR / "pilots" / "runtime_scaffold" / "Verified_Backbone_v1_pilot_harmonization_queue.tsv"),
        help="Where to write the harmonization queue TSV.",
    )
    build_verified_pilot_harmonization_queue_cmd.add_argument(
        "--output-json",
        default=str(DEFAULT_VERIFIED_BACKBONE_DIR / "pilots" / "runtime_scaffold" / "Verified_Backbone_v1_pilot_harmonization_queue.json"),
        help="Optional JSON summary output path.",
    )
    build_verified_pilot_harmonization_queue_cmd.set_defaults(func=cmd_build_verified_pilot_harmonization_queue)

    build_verified_pilot_transformation_manifest_cmd = subparsers.add_parser(
        "build-verified-pilot-transformation-manifest",
        help="Build the first-pass transformation manifest from the verified pilot harmonization queue.",
    )
    build_verified_pilot_transformation_manifest_cmd.add_argument(
        "--queue-tsv",
        default=str(DEFAULT_VERIFIED_BACKBONE_DIR / "pilots" / "runtime_scaffold" / "Verified_Backbone_v1_pilot_harmonization_queue.tsv"),
        help="Path to the harmonization queue TSV.",
    )
    build_verified_pilot_transformation_manifest_cmd.add_argument(
        "--modern-manifest",
        default=str(DEFAULT_VERIFIED_BACKBONE_DIR / "pilots" / "runtime_scaffold" / "Modern_Verified_Backbone_v1_pilot_manifest.tsv"),
        help="Path to the source-confirmed modern pilot manifest.",
    )
    build_verified_pilot_transformation_manifest_cmd.add_argument(
        "--ancient-manifest",
        default=str(DEFAULT_VERIFIED_BACKBONE_DIR / "pilots" / "runtime_scaffold" / "Ancient_Verified_Backbone_v1_pilot_manifest.tsv"),
        help="Path to the source-confirmed ancient pilot manifest.",
    )
    build_verified_pilot_transformation_manifest_cmd.add_argument(
        "--output-tsv",
        default=str(DEFAULT_VERIFIED_BACKBONE_DIR / "pilots" / "runtime_scaffold" / "Verified_Backbone_v1_pilot_transformation_manifest.tsv"),
        help="Where to write the transformation manifest TSV.",
    )
    build_verified_pilot_transformation_manifest_cmd.add_argument(
        "--output-json",
        default=str(DEFAULT_VERIFIED_BACKBONE_DIR / "pilots" / "runtime_scaffold" / "Verified_Backbone_v1_pilot_transformation_manifest.json"),
        help="Optional JSON summary output path.",
    )
    build_verified_pilot_transformation_manifest_cmd.set_defaults(func=cmd_build_verified_pilot_transformation_manifest)

    build_verified_runtime_manifests_cmd = subparsers.add_parser(
        "build-verified-runtime-manifests",
        help="Build provisional verified runtime manifests from the pilot transformation manifest.",
    )
    build_verified_runtime_manifests_cmd.add_argument(
        "--transformation-manifest",
        default=str(DEFAULT_VERIFIED_BACKBONE_DIR / "pilots" / "runtime_scaffold" / "Verified_Backbone_v1_pilot_transformation_manifest.tsv"),
        help="Path to the pilot transformation manifest TSV.",
    )
    build_verified_runtime_manifests_cmd.add_argument(
        "--modern-output-tsv",
        default=str(DEFAULT_VERIFIED_BACKBONE_DIR / "manifests" / "Modern_Verified_Backbone_v1_manifest.tsv"),
        help="Where to write the provisional modern verified runtime manifest.",
    )
    build_verified_runtime_manifests_cmd.add_argument(
        "--ancient-output-tsv",
        default=str(DEFAULT_VERIFIED_BACKBONE_DIR / "manifests" / "Ancient_Verified_Backbone_v1_manifest.tsv"),
        help="Where to write the provisional ancient verified runtime manifest.",
    )
    build_verified_runtime_manifests_cmd.add_argument(
        "--output-json",
        default=str(DEFAULT_VERIFIED_BACKBONE_DIR / "harmonized" / "Verified_Backbone_v1_runtime_manifest_build.json"),
        help="Optional JSON summary output path.",
    )
    build_verified_runtime_manifests_cmd.set_defaults(func=cmd_build_verified_runtime_manifests)

    validate_verified_coordinate_import_cmd = subparsers.add_parser(
        "validate-verified-coordinate-import",
        help="Validate a coordinate file against one verified backbone runtime manifest.",
    )
    validate_verified_coordinate_import_cmd.add_argument(
        "coordinates",
        help="Input coordinate file in G25-style 25-coordinate format.",
    )
    validate_verified_coordinate_import_cmd.add_argument(
        "manifest",
        help="Verified runtime manifest TSV that the coordinate file must match.",
    )
    validate_verified_coordinate_import_cmd.add_argument(
        "--output-json",
        default=None,
        help="Optional JSON validation summary path.",
    )
    validate_verified_coordinate_import_cmd.set_defaults(func=cmd_validate_verified_coordinate_import)

    assemble_verified_backbone_reference_cmd = subparsers.add_parser(
        "assemble-verified-backbone-reference",
        help="Assemble a verified backbone reference file from a validated coordinate import.",
    )
    assemble_verified_backbone_reference_cmd.add_argument(
        "coordinates",
        help="Input coordinate file in G25-style 25-coordinate format.",
    )
    assemble_verified_backbone_reference_cmd.add_argument(
        "manifest",
        help="Verified runtime manifest TSV that the coordinate file must match.",
    )
    assemble_verified_backbone_reference_cmd.add_argument(
        "output",
        help="Output harmonized verified backbone reference file.",
    )
    assemble_verified_backbone_reference_cmd.add_argument(
        "--output-json",
        default=None,
        help="Optional JSON assembly summary path.",
    )
    assemble_verified_backbone_reference_cmd.set_defaults(func=cmd_assemble_verified_backbone_reference)

    build_verified_coordinate_import_from_vahaduo_cmd = subparsers.add_parser(
        "build-verified-coordinate-import-from-vahaduo",
        help="Build a verified coordinate import file from one Vahaduo bridge TSV.",
    )
    build_verified_coordinate_import_from_vahaduo_cmd.add_argument(
        "bridge",
        help="Bridge TSV mapping verified standard_name rows to Vahaduo table labels.",
    )
    build_verified_coordinate_import_from_vahaduo_cmd.add_argument(
        "output",
        help="Output coordinate import file in G25-style 25-coordinate format.",
    )
    build_verified_coordinate_import_from_vahaduo_cmd.add_argument(
        "--downloads-dir",
        default=str(DEFAULT_VERIFIED_VAHADUO_DIR),
        help="Directory containing downloaded Vahaduo coordinate tables.",
    )
    build_verified_coordinate_import_from_vahaduo_cmd.add_argument(
        "--output-json",
        default=None,
        help="Optional JSON build summary path.",
    )
    build_verified_coordinate_import_from_vahaduo_cmd.set_defaults(func=cmd_build_verified_coordinate_import_from_vahaduo)

    two_way_cmd = subparsers.add_parser("two-way", help="Find best 2-way G25 mixtures.")
    two_way_cmd.add_argument("target", help="Target G25 file.")
    two_way_cmd.add_argument("references", help="Reference G25 file.")
    two_way_cmd.add_argument("--top", type=int, default=10, help="How many rows to return.")
    two_way_cmd.set_defaults(func=cmd_two_way)

    panel_fit_cmd = subparsers.add_parser(
        "panel-fit",
        help="Fit one target against an individual-level panel and aggregate weights by group.",
    )
    panel_fit_cmd.add_argument("target", help="Target G25 file with exactly one row.")
    panel_fit_cmd.add_argument("references", help="Panel reference G25 file.")
    panel_fit_cmd.add_argument("manifest", help="Panel manifest with standard_name and group columns.")
    panel_fit_cmd.add_argument("--group-column", default="panel_group", help="Manifest column to aggregate by.")
    panel_fit_cmd.add_argument("--iterations", type=int, default=1500, help="Maximum Frank-Wolfe iterations.")
    panel_fit_cmd.add_argument("--top-references", type=int, default=10, help="How many individual contributors to keep.")
    panel_fit_cmd.add_argument("--output", help="Optional JSON output path.", default=None)
    panel_fit_cmd.set_defaults(func=cmd_panel_fit)

    adaptive_panel_fit_cmd = subparsers.add_parser(
        "adaptive-panel-fit",
        help="Run a broad panel, select top groups, then refit a reduced 3-4 group panel.",
    )
    adaptive_panel_fit_cmd.add_argument("target", help="Target G25 file with exactly one row.")
    adaptive_panel_fit_cmd.add_argument("references", help="Broad panel reference G25 file.")
    adaptive_panel_fit_cmd.add_argument("manifest", help="Broad panel manifest with standard_name and group columns.")
    adaptive_panel_fit_cmd.add_argument("--group-column", default="panel_group", help="Manifest column to aggregate by.")
    adaptive_panel_fit_cmd.add_argument("--iterations", type=int, default=2000, help="Maximum Frank-Wolfe iterations.")
    adaptive_panel_fit_cmd.add_argument("--top-references", type=int, default=12, help="How many individual contributors to keep per fit.")
    adaptive_panel_fit_cmd.add_argument("--min-groups", type=int, default=3, help="Minimum number of groups in reduced panel.")
    adaptive_panel_fit_cmd.add_argument("--max-groups", type=int, default=4, help="Maximum number of groups in reduced panel.")
    adaptive_panel_fit_cmd.add_argument("--min-group-weight", type=float, default=0.03, help="Keep groups at or above this broad-fit weight before clamping to min/max groups.")
    adaptive_panel_fit_cmd.add_argument("--output", help="Optional JSON output path.", default=None)
    adaptive_panel_fit_cmd.set_defaults(func=cmd_adaptive_panel_fit)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())


