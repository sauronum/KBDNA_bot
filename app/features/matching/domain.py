from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from g25_core.g25_engine import AUTOSOMES, MISSING_GENOTYPES, RawCall, RawSummary, parse_raw_dna

from .genetic_map import GeneticMap, default_genetic_map


CM_ESTIMATE_BP = 1_000_000
DEFAULT_MIN_ESTIMATED_CM = 7.0
DEFAULT_MIN_SHARED_SNPS = 500
DEFAULT_MAX_GAP_BP = 3_000_000


@dataclass(frozen=True)
class MatchSegment:
    chromosome: str
    start: int
    end: int
    snp_count: int
    identical_snps: int
    estimated_cm: float


@dataclass(frozen=True)
class PairwiseMatchResult:
    left_summary: RawSummary
    right_summary: RawSummary
    overlap_snps: int
    half_identical_snps: int
    identical_snps: int
    segments: tuple[MatchSegment, ...]
    total_estimated_cm: float
    longest_estimated_cm: float
    relationship_hint: str
    genetic_map_used: bool
    ibs0_snps: int = 0
    shared_ratio: float = 0.0
    identical_ratio: float = 0.0
    ibs0_ratio: float = 0.0


@dataclass(frozen=True)
class RawAutosomalProfile:
    summary: RawSummary
    calls_by_chromosome: dict[str, dict[str, tuple[int, str]]]


@dataclass(frozen=True)
class SnpLookupResult:
    rsid: str
    chromosome: str | None
    position: int | None
    genotype: str
    found: bool
    error: str | None = None


def compare_raw_autosomal_match(
    left_path: Path,
    right_path: Path,
    *,
    min_estimated_cm: float = DEFAULT_MIN_ESTIMATED_CM,
    min_shared_snps: int = DEFAULT_MIN_SHARED_SNPS,
    max_gap_bp: int = DEFAULT_MAX_GAP_BP,
    genetic_map: GeneticMap | None = None,
    use_default_genetic_map: bool = True,
) -> PairwiseMatchResult:
    left_summary, left_calls = parse_raw_dna(left_path)
    right_summary, right_calls = parse_raw_dna(right_path)
    return compare_raw_autosomal_calls(
        left_summary,
        left_calls,
        right_summary,
        right_calls,
        min_estimated_cm=min_estimated_cm,
        min_shared_snps=min_shared_snps,
        max_gap_bp=max_gap_bp,
        genetic_map=genetic_map,
        use_default_genetic_map=use_default_genetic_map,
    )


def load_raw_autosomal_data(path: Path) -> tuple[RawSummary, list[RawCall]]:
    return parse_raw_dna(path)


def load_raw_autosomal_profile(path: Path) -> RawAutosomalProfile:
    summary, calls = parse_raw_dna(path)
    return prepare_raw_autosomal_profile(summary, calls)


def lookup_snp_in_raw(path: Path, rsid: str) -> SnpLookupResult:
    normalized_rsid = rsid.strip().lower()
    try:
        _summary, calls = parse_raw_dna(path)
    except Exception:
        return SnpLookupResult(
            rsid=normalized_rsid,
            chromosome=None,
            position=None,
            genotype="ошибка чтения raw",
            found=False,
            error="read_error",
        )

    for call in calls:
        if call.rsid.strip().lower() == normalized_rsid:
            return SnpLookupResult(
                rsid=normalized_rsid,
                chromosome=call.chromosome,
                position=call.position,
                genotype=call.genotype or "--",
                found=True,
            )
    return SnpLookupResult(
        rsid=normalized_rsid,
        chromosome=None,
        position=None,
        genotype="--",
        found=False,
    )


def prepare_raw_autosomal_profile(summary: RawSummary, calls: list[RawCall]) -> RawAutosomalProfile:
    calls_by_chromosome: dict[str, dict[str, tuple[int, str]]] = {}
    for call in calls:
        if call.chromosome not in AUTOSOMES:
            continue
        genotype = _canonical_genotype(call.genotype)
        if not genotype:
            continue
        calls_by_chromosome.setdefault(call.chromosome, {}).setdefault(call.rsid, (call.position, genotype))
    return RawAutosomalProfile(summary=summary, calls_by_chromosome=calls_by_chromosome)


def compare_raw_autosomal_calls(
    left_summary: RawSummary,
    left_calls: list[RawCall],
    right_summary: RawSummary,
    right_calls: list[RawCall],
    *,
    min_estimated_cm: float = DEFAULT_MIN_ESTIMATED_CM,
    min_shared_snps: int = DEFAULT_MIN_SHARED_SNPS,
    max_gap_bp: int = DEFAULT_MAX_GAP_BP,
    genetic_map: GeneticMap | None = None,
    use_default_genetic_map: bool = True,
) -> PairwiseMatchResult:
    return compare_raw_autosomal_profiles(
        prepare_raw_autosomal_profile(left_summary, left_calls),
        prepare_raw_autosomal_profile(right_summary, right_calls),
        min_estimated_cm=min_estimated_cm,
        min_shared_snps=min_shared_snps,
        max_gap_bp=max_gap_bp,
        genetic_map=genetic_map,
        use_default_genetic_map=use_default_genetic_map,
    )


def compare_raw_autosomal_profiles(
    left_profile: RawAutosomalProfile,
    right_profile: RawAutosomalProfile,
    *,
    min_estimated_cm: float = DEFAULT_MIN_ESTIMATED_CM,
    min_shared_snps: int = DEFAULT_MIN_SHARED_SNPS,
    max_gap_bp: int = DEFAULT_MAX_GAP_BP,
    genetic_map: GeneticMap | None = None,
    use_default_genetic_map: bool = True,
) -> PairwiseMatchResult:
    cm_map = genetic_map if genetic_map is not None else (default_genetic_map() if use_default_genetic_map else GeneticMap.empty())
    by_chromosome: dict[str, list[tuple[int, str, str]]] = defaultdict(list)
    half_identical_snps = 0
    identical_snps = 0
    ibs0_snps = 0
    shared_chromosomes = set(left_profile.calls_by_chromosome) & set(right_profile.calls_by_chromosome)
    for chromosome in shared_chromosomes:
        left_calls = left_profile.calls_by_chromosome[chromosome]
        right_calls = right_profile.calls_by_chromosome[chromosome]
        if len(left_calls) <= len(right_calls):
            iterator = left_calls.items()
            for rsid, (position, left_genotype) in iterator:
                right_item = right_calls.get(rsid)
                if right_item is None:
                    continue
                right_genotype = right_item[1]
                if _shares_allele(left_genotype, right_genotype):
                    half_identical_snps += 1
                else:
                    ibs0_snps += 1
                if left_genotype == right_genotype:
                    identical_snps += 1
                by_chromosome[chromosome].append((position, left_genotype, right_genotype))
        else:
            iterator = right_calls.items()
            for rsid, (_right_position, right_genotype) in iterator:
                left_item = left_calls.get(rsid)
                if left_item is None:
                    continue
                position, left_genotype = left_item
                if _shares_allele(left_genotype, right_genotype):
                    half_identical_snps += 1
                else:
                    ibs0_snps += 1
                if left_genotype == right_genotype:
                    identical_snps += 1
                by_chromosome[chromosome].append((position, left_genotype, right_genotype))

    overlap_snps = sum(len(items) for items in by_chromosome.values())
    shared_ratio = half_identical_snps / overlap_snps if overlap_snps else 0.0
    identical_ratio = identical_snps / overlap_snps if overlap_snps else 0.0
    ibs0_ratio = ibs0_snps / overlap_snps if overlap_snps else 0.0
    segments: list[MatchSegment] = []
    for chromosome in sorted(by_chromosome, key=lambda value: int(value) if value.isdigit() else 99):
        rows = sorted(by_chromosome[chromosome], key=lambda item: item[0])
        segments.extend(
            _find_shared_segments(
                chromosome,
                rows,
                min_estimated_cm=min_estimated_cm,
                min_shared_snps=min_shared_snps,
                max_gap_bp=max_gap_bp,
                genetic_map=cm_map,
            )
        )

    segments.sort(key=lambda segment: segment.estimated_cm, reverse=True)
    total_estimated_cm = round(sum(segment.estimated_cm for segment in segments), 2)
    longest_estimated_cm = round(max((segment.estimated_cm for segment in segments), default=0.0), 2)
    return PairwiseMatchResult(
        left_summary=left_profile.summary,
        right_summary=right_profile.summary,
        overlap_snps=overlap_snps,
        half_identical_snps=half_identical_snps,
        identical_snps=identical_snps,
        segments=tuple(segments),
        total_estimated_cm=total_estimated_cm,
        longest_estimated_cm=longest_estimated_cm,
        relationship_hint=relationship_hint(total_estimated_cm, longest_estimated_cm),
        genetic_map_used=cm_map.is_loaded,
        ibs0_snps=ibs0_snps,
        shared_ratio=shared_ratio,
        identical_ratio=identical_ratio,
        ibs0_ratio=ibs0_ratio,
    )


def relationship_hint(
    total_cm: float,
    longest_cm: float,
    *,
    lang: str = "ru",
) -> str:
    if total_cm >= 3300:
        return "Very close match / possibly the same person or a twin" if lang == "en" else "Очень близкое совпадение / возможно тот же человек или близнец"
    if total_cm >= 2300:
        return "Close family: parent-child, full sibling, or a similar level" if lang == "en" else "Близкое родство: родитель-ребенок, full sibling или похожий уровень"
    if total_cm >= 1300:
        return "Close relationship: grandparent, aunt/uncle, half sibling, or a similar level" if lang == "en" else "Близкое родство: grandparent, aunt/uncle, half sibling или похожий уровень"
    if total_cm >= 550:
        return "Likely close branch: first cousin or a similar level" if lang == "en" else "Вероятно близкая ветка: first cousin или похожий уровень"
    if total_cm >= 200:
        return "Medium match: roughly second cousin range" if lang == "en" else "Среднее совпадение: примерно second cousin range"
    if total_cm >= 60:
        return "Distant match: roughly third cousin range" if lang == "en" else "Дальнее совпадение: примерно third cousin range"
    if total_cm >= 20 or longest_cm >= 7:
        return "Small distant match" if lang == "en" else "Небольшое дальнее совпадение"
    return "No significant segments above the threshold" if lang == "en" else "Значимых сегментов выше порога не найдено"


def _autosomal_call_map(calls: list[RawCall]) -> dict[str, RawCall]:
    items: dict[str, RawCall] = {}
    for call in calls:
        if call.chromosome not in AUTOSOMES:
            continue
        if not _canonical_genotype(call.genotype):
            continue
        items.setdefault(call.rsid, call)
    return items


def _canonical_genotype(value: str) -> str:
    genotype = value.strip().upper()
    if genotype in MISSING_GENOTYPES or len(genotype) != 2:
        return ""
    return "".join(sorted(genotype))


def _shares_allele(left: str, right: str) -> bool:
    return bool(set(left) & set(right))


def _find_shared_segments(
    chromosome: str,
    rows: list[tuple[int, str, str]],
    *,
    min_estimated_cm: float,
    min_shared_snps: int,
    max_gap_bp: int,
    genetic_map: GeneticMap,
) -> list[MatchSegment]:
    segments: list[MatchSegment] = []
    start: int | None = None
    end: int | None = None
    snp_count = 0
    identical_snps = 0
    previous_position: int | None = None

    def close_segment() -> None:
        nonlocal start, end, snp_count, identical_snps
        if start is None or end is None:
            return
        map_cm = genetic_map.cm_between(chromosome, start, end)
        estimated_cm = round(map_cm if map_cm is not None else max(0, end - start) / CM_ESTIMATE_BP, 2)
        if snp_count >= min_shared_snps and estimated_cm >= min_estimated_cm:
            segments.append(
                MatchSegment(
                    chromosome=chromosome,
                    start=start,
                    end=end,
                    snp_count=snp_count,
                    identical_snps=identical_snps,
                    estimated_cm=estimated_cm,
                )
            )
        start = None
        end = None
        snp_count = 0
        identical_snps = 0

    for position, left_genotype, right_genotype in rows:
        shared = _shares_allele(left_genotype, right_genotype)
        gap_too_large = previous_position is not None and position - previous_position > max_gap_bp
        if gap_too_large:
            close_segment()
        if shared:
            if start is None:
                start = position
            end = position
            snp_count += 1
            if left_genotype == right_genotype:
                identical_snps += 1
        else:
            close_segment()
        previous_position = position

    close_segment()
    return segments
