from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from g25_core.g25_engine import MISSING_GENOTYPES, parse_raw_dna


DATA_DIR = Path(__file__).resolve().parent / "data"
DEFAULT_INTERESTING_SNPS_PATH = DATA_DIR / "interesting_snps.json"
COMPLEMENT = str.maketrans("ACGT", "TGCA")


@dataclass(frozen=True)
class InterestingSnpSource:
    title: str
    url: str


@dataclass(frozen=True)
class InterestingSnpDefinition:
    rsid: str
    title: str
    category: str
    gene: str
    build: str
    orientation: str
    medical: bool
    status: str
    genotypes: dict[str, str]
    descriptions: dict[str, str]
    limitations: str
    source_notes: str
    sources: tuple[InterestingSnpSource, ...]


@dataclass(frozen=True)
class InterestingSnpResult:
    rsid: str
    title: str
    category: str
    gene: str
    genotype: str
    normalized_genotype: str
    interpretation: str
    description: str
    limitations: str
    source_notes: str
    sources: tuple[InterestingSnpSource, ...]
    chromosome: str | None
    position: int | None
    status: str


@dataclass(frozen=True)
class InterestingSnpAnalysis:
    sample_id: str
    sample_name: str
    total: int
    found: int
    missing: int
    unsupported: int
    results: tuple[InterestingSnpResult, ...]


def load_interesting_snps(path: Path = DEFAULT_INTERESTING_SNPS_PATH) -> tuple[InterestingSnpDefinition, ...]:
    raw_items = json.loads(path.read_text(encoding="utf-8"))
    definitions: list[InterestingSnpDefinition] = []
    for item in raw_items:
        definition = _definition_from_json(item)
        if definition.status == "ready" and not definition.medical:
            definitions.append(definition)
    return tuple(definitions)


def analyze_interesting_snps(
    raw_path: Path,
    panel: tuple[InterestingSnpDefinition, ...],
    *,
    sample_id: str,
    sample_name: str,
) -> InterestingSnpAnalysis:
    _summary, calls = parse_raw_dna(raw_path)
    calls_by_rsid = {call.rsid.strip().lower(): call for call in calls if call.rsid.strip()}

    results: list[InterestingSnpResult] = []
    for definition in panel:
        call = calls_by_rsid.get(definition.rsid)
        if call is None:
            results.append(_missing_result(definition))
            continue

        raw_genotype = str(call.genotype or "").strip().upper()
        normalized = _canonical_genotype(raw_genotype)
        if not normalized:
            results.append(_missing_result(definition, genotype="--", chromosome=call.chromosome, position=call.position))
            continue

        mapped_genotype = _mapped_genotype(normalized, definition.genotypes)
        if mapped_genotype is None:
            results.append(
                InterestingSnpResult(
                    rsid=definition.rsid,
                    title=definition.title,
                    category=definition.category,
                    gene=definition.gene,
                    genotype=raw_genotype or "--",
                    normalized_genotype=normalized,
                    interpretation="Генотип пока не поддержан в curated-каталоге",
                    description="SNP найден в raw, но для такого аллельного представления нет проверенной пользовательской трактовки.",
                    limitations=definition.limitations,
                    source_notes=definition.source_notes,
                    sources=definition.sources,
                    chromosome=call.chromosome,
                    position=call.position,
                    status="unsupported",
                )
            )
            continue

        results.append(
            InterestingSnpResult(
                rsid=definition.rsid,
                title=definition.title,
                category=definition.category,
                gene=definition.gene,
                genotype=raw_genotype,
                normalized_genotype=mapped_genotype,
                interpretation=definition.genotypes[mapped_genotype],
                description=definition.descriptions.get(mapped_genotype, ""),
                limitations=definition.limitations,
                source_notes=definition.source_notes,
                sources=definition.sources,
                chromosome=call.chromosome,
                position=call.position,
                status="ok",
            )
        )

    return InterestingSnpAnalysis(
        sample_id=sample_id,
        sample_name=sample_name,
        total=len(panel),
        found=sum(1 for item in results if item.status == "ok"),
        missing=sum(1 for item in results if item.status == "missing"),
        unsupported=sum(1 for item in results if item.status == "unsupported"),
        results=tuple(results),
    )


def _definition_from_json(item: dict[str, Any]) -> InterestingSnpDefinition:
    sources = tuple(
        InterestingSnpSource(title=str(source.get("title") or "").strip(), url=str(source.get("url") or "").strip())
        for source in item.get("sources", [])
        if str(source.get("url") or "").strip()
    )
    return InterestingSnpDefinition(
        rsid=str(item.get("rsid") or "").strip().lower(),
        title=str(item.get("title") or "").strip(),
        category=str(item.get("category") or "").strip(),
        gene=str(item.get("gene") or "").strip(),
        build=str(item.get("build") or "").strip(),
        orientation=str(item.get("orientation") or "").strip(),
        medical=bool(item.get("medical", False)),
        status=str(item.get("status") or "").strip(),
        genotypes={_canonical_genotype(key): str(value).strip() for key, value in dict(item.get("genotypes") or {}).items()},
        descriptions={_canonical_genotype(key): str(value).strip() for key, value in dict(item.get("descriptions") or {}).items()},
        limitations=str(item.get("limitations") or "").strip(),
        source_notes=str(item.get("source_notes") or "").strip(),
        sources=sources,
    )


def _missing_result(
    definition: InterestingSnpDefinition,
    *,
    genotype: str = "--",
    chromosome: str | None = None,
    position: int | None = None,
) -> InterestingSnpResult:
    return InterestingSnpResult(
        rsid=definition.rsid,
        title=definition.title,
        category=definition.category,
        gene=definition.gene,
        genotype=genotype,
        normalized_genotype="",
        interpretation="Недостаточно данных",
        description="Этот SNP не найден в raw-файле sample. Это нормально для разных чипов и версий тестов.",
        limitations=definition.limitations,
        source_notes=definition.source_notes,
        sources=definition.sources,
        chromosome=chromosome,
        position=position,
        status="missing",
    )


def _canonical_genotype(value: object) -> str:
    genotype = str(value or "").strip().upper()
    if not genotype or genotype in MISSING_GENOTYPES or genotype in {"-", "--", "N/A", "NA", "NULL", "NONE"}:
        return ""
    for separator in ("/", "\\", "|", " "):
        genotype = genotype.replace(separator, "")
    if len(genotype) == 2 and all(base in "ACGT" for base in genotype):
        return "".join(sorted(genotype))
    return genotype


def _mapped_genotype(genotype: str, supported: dict[str, str]) -> str | None:
    if genotype in supported:
        return genotype
    if len(genotype) == 2 and all(base in "ACGT" for base in genotype):
        flipped = "".join(sorted(genotype.translate(COMPLEMENT)))
        if flipped in supported:
            return flipped
    return None
