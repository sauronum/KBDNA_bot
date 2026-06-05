from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from g25_core.g25_engine import parse_raw_dna


DATA_DIR = Path(__file__).resolve().parent / "data"
DEFAULT_RULES_PATH = DATA_DIR / "snp_norms.csv"


@dataclass(frozen=True)
class SnpRule:
    rsid: str
    normal_genotype: str
    category: str


@dataclass(frozen=True)
class SnpReportRow:
    rsid: str
    category: str
    normal_genotype: str
    user_genotype: str
    status: str


@dataclass(frozen=True)
class SnpCategorySummary:
    category: str
    total: int
    ok: int
    warn: int
    bad: int
    missing: int
    risk_percent: int


@dataclass(frozen=True)
class SnpReportResult:
    sample_id: str
    sample_name: str
    raw_file_id: str
    total_rules: int
    ok: int
    warn: int
    bad: int
    missing: int
    categories: tuple[SnpCategorySummary, ...]
    rows: tuple[SnpReportRow, ...]


def load_snp_rules(path: Path = DEFAULT_RULES_PATH) -> tuple[SnpRule, ...]:
    rules: list[SnpRule] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        for parts in reader:
            if len(parts) < 3:
                continue
            rsid = parts[0].strip().lower()
            normal = _canonical_genotype(parts[1])
            category = parts[2].strip()
            if rsid.startswith("rs") and normal and category:
                rules.append(SnpRule(rsid=rsid, normal_genotype=normal, category=category))
    return tuple(rules)


def build_snp_report(
    raw_path: Path,
    rules: tuple[SnpRule, ...],
    *,
    sample_id: str,
    sample_name: str,
    raw_file_id: str,
) -> SnpReportResult:
    _summary, calls = parse_raw_dna(raw_path)
    calls_by_rsid: dict[str, str] = {}
    for call in calls:
        rsid = call.rsid.strip().lower()
        if rsid and rsid not in calls_by_rsid:
            calls_by_rsid[rsid] = _canonical_genotype(call.genotype)

    rows: list[SnpReportRow] = []
    for rule in rules:
        user_genotype = calls_by_rsid.get(rule.rsid, "")
        status = _status_for_genotype(user_genotype, rule.normal_genotype)
        rows.append(
            SnpReportRow(
                rsid=rule.rsid,
                category=rule.category,
                normal_genotype=rule.normal_genotype,
                user_genotype=user_genotype or "--",
                status=status,
            )
        )

    category_summaries = _category_summaries(rows)
    return SnpReportResult(
        sample_id=sample_id,
        sample_name=sample_name,
        raw_file_id=raw_file_id,
        total_rules=len(rules),
        ok=sum(1 for row in rows if row.status == "ok"),
        warn=sum(1 for row in rows if row.status == "warn"),
        bad=sum(1 for row in rows if row.status == "bad"),
        missing=sum(1 for row in rows if row.status == "missing"),
        categories=tuple(category_summaries),
        rows=tuple(rows),
    )


def _category_summaries(rows: list[SnpReportRow]) -> list[SnpCategorySummary]:
    grouped: dict[str, list[SnpReportRow]] = {}
    for row in rows:
        grouped.setdefault(row.category, []).append(row)

    summaries: list[SnpCategorySummary] = []
    for category, items in grouped.items():
        ok = sum(1 for item in items if item.status == "ok")
        warn = sum(1 for item in items if item.status == "warn")
        bad = sum(1 for item in items if item.status == "bad")
        missing = sum(1 for item in items if item.status == "missing")
        found = max(1, len(items) - missing)
        risk_percent = int(round(((warn * 0.5) + bad) / found * 100))
        summaries.append(
            SnpCategorySummary(
                category=category,
                total=len(items),
                ok=ok,
                warn=warn,
                bad=bad,
                missing=missing,
                risk_percent=max(0, min(100, risk_percent)),
            )
        )
    return sorted(summaries, key=lambda item: (item.risk_percent, item.bad, item.warn, item.total), reverse=True)


def _status_for_genotype(user_genotype: str, normal_genotype: str) -> str:
    user = _canonical_genotype(user_genotype)
    normal = _canonical_genotype(normal_genotype)
    if not user or user in {"--", "00"}:
        return "missing"
    if user == normal:
        return "ok"
    if len(user) == 2 and len(normal) == 2:
        normal_alleles = set(normal)
        user_alleles = list(user)
        matched = sum(1 for allele in user_alleles if allele in normal_alleles)
        if matched >= 1:
            return "warn"
        return "bad"
    return "warn"


def _canonical_genotype(value: object) -> str:
    genotype = str(value or "").strip().upper()
    if not genotype or genotype in {"-", "--", "N/A", "NA", "NULL", "NONE"}:
        return ""
    for separator in ("/", "\\", "|", " "):
        genotype = genotype.replace(separator, "")
    if len(genotype) == 2 and all(base in "ACGT" for base in genotype):
        return "".join(sorted(genotype))
    return genotype
