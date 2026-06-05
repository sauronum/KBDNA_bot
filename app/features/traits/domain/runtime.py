from __future__ import annotations

import csv
import gzip
import json
import math
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Optional, Sequence

from .catalog import TraitCatalog, TraitCatalogEntry, TraitDetail, validate_trait_status


AUTOSOMES = {str(index) for index in range(1, 23)}
MISSING_GENOTYPES = {"", "--", "00", "0", "-", "NC", "NN", "??"}
COMPLEMENT = {
    "A": "T",
    "T": "A",
    "C": "G",
    "G": "C",
}

HEADER_ALIASES = {
    "trait": {"trait", "phenotype", "pgs_id", "score_name"},
    "rsid": {"rsid", "snp", "marker", "markername", "rs_id"},
    "chromosome": {"chromosome", "chrom", "chr", "chr_name"},
    "position": {"position", "pos", "bp", "chr_position"},
    "genotype": {"genotype", "result", "call", "alleles"},
    "effect_allele": {"effect_allele", "effectallele", "ea", "effect", "a1"},
    "other_allele": {"other_allele", "otherallele", "nea", "other", "a2"},
    "effect_weight": {"effect_weight", "weight", "beta", "effect_size"},
}

RAW_HEADER_CANONICAL = ["rsid", "chromosome", "position", "genotype"]
RAW_INPUT_FORMATS = {"auto", "ftdna", "23andme", "myheritage"}

QC_FLAG_LOW_OVERLAP = "low_overlap"
QC_FLAG_LOW_MATCHED_VARIANT_COUNT = "low_matched_variant_count"
QC_FLAG_HIGH_AMBIGUOUS_REMOVAL_RATE = "high_ambiguous_removal_rate"
QC_FLAG_MISSING_REFERENCE_DISTRIBUTION = "missing_reference_distribution"
QC_FLAG_INVALID_REFERENCE_SD = "invalid_reference_sd"
QC_FLAG_WEAK_REFERENCE_PANEL = "weak_reference_panel"


class TraitRuntimeError(ValueError):
    def __init__(self, code: str, message: str, details: Optional[dict[str, object]] = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True)
class VariantRecord:
    rsid: str
    chromosome: str
    position: int
    genotype: str


@dataclass(frozen=True)
class RawSummaryRecord:
    file: str
    vendor_hint: str
    total_rows: int
    autosomal_rows: int
    autosomal_called_rows: int
    skipped_rows: int
    call_rate: float
    chromosome_counts: dict[str, int]


@dataclass(frozen=True)
class ScoringVariant:
    trait: str
    effect_allele: str
    other_allele: str
    effect_weight: float
    rsid: str = ""
    chromosome: str = ""
    position: int = 0


@dataclass(frozen=True)
class ReferenceDistribution:
    trait: str
    mean: float
    sd: float
    valid: bool = True
    warnings: list[str] = field(default_factory=list)
    artifact_type: Optional[str] = None
    schema_version: Optional[int] = None
    trait_id: Optional[str] = None
    display_name: Optional[str] = None
    artifact: dict[str, object] = field(default_factory=dict)


@dataclass
class PGSQC:
    total_variants: int
    matched_variants: int
    skipped_variants: int
    overlap_percent: float
    ambiguous_variants_removed: int
    strand_flipped_variants: int
    skip_reasons: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class ExcludedVariantDiagnostic:
    rsid: str
    chromosome: str
    position: int
    reason: str


@dataclass
class PGSResult:
    trait: str
    sample_id: str
    raw_score: float
    z_score: Optional[float]
    percentile: Optional[float]
    interpretation: str
    confidence: str
    qc_summary: PGSQC
    qc_flags: list[str] = field(default_factory=list)
    excluded_variants: list[ExcludedVariantDiagnostic] = field(default_factory=list)
    scoring_model_path: Optional[str] = None
    reference_distribution_path: Optional[str] = None
    reference_artifact: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class TraitRunOutput:
    trait_id: str
    sample_id: str
    display_name: str
    short_name: str
    technical_payload: dict[str, object]
    product_payload: dict[str, object]


def _read_text(path: Path) -> str:
    if path.suffix.lower() == ".gz":
        try:
            with gzip.open(path, "rt", encoding="utf-8-sig") as handle:
                return handle.read()
        except UnicodeDecodeError:
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                return handle.read()
    try:
        return path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8")


def _split_row(line: str) -> list[str]:
    if "\t" in line:
        return next(csv.reader([line.rstrip("\n")], delimiter="\t"))
    if "," in line:
        return next(csv.reader([line.rstrip("\n")], delimiter=","))
    return line.strip().split()


def _detect_delimiter(header_line: str) -> str:
    if "\t" in header_line:
        return "\t"
    if "," in header_line:
        return ","
    return "\t"


def _canonical_header(name: str) -> str:
    compact = name.strip().lower().replace("-", "_").replace(" ", "_")
    for canonical, aliases in HEADER_ALIASES.items():
        if compact in aliases:
            return canonical
    return compact


def _canonicalize_header(fields: list[str]) -> list[str]:
    return [_canonical_header(field) for field in fields]


def inspect_raw_input_format(path: Path) -> dict[str, object]:
    comments: list[str] = []
    header_fields: list[str] = []
    delimiter = ""
    for raw_line in _read_text(path).splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            payload = line.lstrip("#").strip()
            candidate_fields = _split_row(payload)
            if _canonicalize_header(candidate_fields) == RAW_HEADER_CANONICAL:
                header_fields = candidate_fields
                delimiter = _detect_delimiter(payload)
                break
            comments.append(line)
            continue
        header_fields = _split_row(line)
        delimiter = _detect_delimiter(raw_line)
        break

    if not header_fields:
        raise TraitRuntimeError(
            code="unsupported_raw_schema",
            message=f"Raw input file is empty or has no header: {path}",
        )

    normalized_header = _canonicalize_header(header_fields)
    header_ok = normalized_header == RAW_HEADER_CANONICAL
    joined_comments = " ".join(comments).lower()

    if "23andme" in joined_comments:
        detected = "23andme"
    elif "family tree dna" in joined_comments or "ftdna" in joined_comments:
        detected = "ftdna"
    elif "myheritage" in joined_comments:
        detected = "myheritage"
    elif header_ok:
        detected = "generic_4col"
    else:
        detected = "unknown"

    return {
        "path": str(path),
        "comments": comments,
        "header_fields": header_fields,
        "normalized_header": normalized_header,
        "delimiter": delimiter,
        "header_ok": header_ok,
        "detected_format": detected,
    }


def validate_raw_input_format(path: Path, requested_format: str) -> dict[str, object]:
    requested = requested_format.strip().lower()
    if requested not in RAW_INPUT_FORMATS:
        raise TraitRuntimeError(
            code="unsupported_input_format",
            message=f"Unsupported input format: {requested_format}",
            details={"requested_format": requested_format, "allowed_formats": sorted(RAW_INPUT_FORMATS)},
        )

    inspection = inspect_raw_input_format(path)
    if not inspection["header_ok"]:
        raise TraitRuntimeError(
            code="unsupported_raw_schema",
            message=f"Unsupported raw schema in {path}. Expected header: {', '.join(RAW_HEADER_CANONICAL)}.",
            details={"path": str(path), "expected_header": list(RAW_HEADER_CANONICAL)},
        )

    detected = str(inspection["detected_format"])
    if requested != "auto" and detected != requested:
        raise TraitRuntimeError(
            code="input_format_mismatch",
            message=(
                f"Input format mismatch for {path}. Requested '{requested}', but detected '{detected}'. "
                "For explicit formats, the file must contain a matching vendor marker and the canonical 4-column schema."
            ),
            details={"path": str(path), "requested_format": requested, "detected_format": detected},
        )
    return inspection


def _normalize_chromosome(value: str) -> str:
    chromosome = value.strip().replace("chr", "").replace("CHR", "").upper()
    return "M" if chromosome == "MT" else chromosome


def _normalize_genotype(value: str) -> str:
    return value.strip().replace("/", "").replace(" ", "").upper()


def _infer_vendor_hint(comments: Iterable[str], data_width: Optional[int]) -> str:
    joined = " ".join(comments).lower()
    if "23andme" in joined:
        return "23andMe"
    if "family tree dna" in joined or "ftdna" in joined:
        return "FTDNA"
    if "myheritage" in joined:
        return "MyHeritage"
    if data_width == 4:
        return "23andMe/FTDNA/MyHeritage-like"
    return "unknown"


def parse_raw_dna(path: Path) -> tuple[RawSummaryRecord, list[VariantRecord]]:
    comments: list[str] = []
    calls: list[VariantRecord] = []
    chromosome_counts: dict[str, int] = {}
    total_rows = 0
    autosomal_rows = 0
    autosomal_called_rows = 0
    skipped_rows = 0
    data_width: Optional[int] = None
    header_seen = False

    for raw_line in _read_text(path).splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            comments.append(line)
            continue

        fields = _split_row(line)
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
                genotype = _normalize_genotype(allele1 + allele2)
            elif len(fields) >= 4:
                rsid, chromosome, position, genotype = fields[:4]
                genotype = _normalize_genotype(genotype)
            else:
                skipped_rows += 1
                continue
            chromosome_normalized = _normalize_chromosome(chromosome)
            position_value = int(position)
        except ValueError:
            skipped_rows += 1
            continue

        calls.append(
            VariantRecord(
                rsid=rsid,
                chromosome=chromosome_normalized,
                position=position_value,
                genotype=genotype,
            )
        )
        chromosome_counts[chromosome_normalized] = chromosome_counts.get(chromosome_normalized, 0) + 1

        if chromosome_normalized in AUTOSOMES:
            autosomal_rows += 1
            if genotype not in MISSING_GENOTYPES:
                autosomal_called_rows += 1

    call_rate = (autosomal_called_rows / autosomal_rows) if autosomal_rows else 0.0
    summary = RawSummaryRecord(
        file=str(path),
        vendor_hint=_infer_vendor_hint(comments, data_width),
        total_rows=total_rows,
        autosomal_rows=autosomal_rows,
        autosomal_called_rows=autosomal_called_rows,
        skipped_rows=skipped_rows,
        call_rate=call_rate,
        chromosome_counts=dict(sorted(chromosome_counts.items(), key=lambda item: item[0])),
    )
    return summary, calls


def load_scoring_metadata(path: Path) -> dict[str, str]:
    metadata: dict[str, str] = {}
    for line in _read_text(path).splitlines():
        stripped = line.strip()
        if not stripped or not stripped.startswith("#") or "=" not in stripped:
            continue
        payload = stripped.lstrip("#").strip()
        key, value = payload.split("=", 1)
        metadata[key.strip().lower()] = value.strip()
    return metadata


def _iter_dict_rows(path: Path) -> list[dict[str, str]]:
    lines = [line for line in _read_text(path).splitlines() if line.strip()]
    if not lines:
        return []
    data_lines = [line for line in lines if not line.lstrip().startswith("#")]
    if not data_lines:
        return []
    delimiter = _detect_delimiter(data_lines[0])
    reader = csv.DictReader(data_lines, delimiter=delimiter)
    rows: list[dict[str, str]] = []
    for row in reader:
        normalized = {_canonical_header(key): (value or "").strip() for key, value in row.items() if key}
        rows.append(normalized)
    return rows


def load_scoring_variants(path: Path, trait_override: Optional[str] = None) -> list[ScoringVariant]:
    metadata = load_scoring_metadata(path)
    rows = _iter_dict_rows(path)
    if not rows:
        raise TraitRuntimeError(
            code="scoring_file_invalid",
            message=f"Scoring file is empty: {path}",
            details={"path": str(path)},
        )

    variants: list[ScoringVariant] = []
    traits_seen: set[str] = set()
    for index, row in enumerate(rows, start=1):
        rsid = row.get("rsid", "")
        chromosome = row.get("chromosome", "")
        position_text = row.get("position", "")
        effect_allele = row.get("effect_allele", "").upper()
        other_allele = row.get("other_allele", "").upper()
        weight_text = row.get("effect_weight", "")
        if not effect_allele or not weight_text:
            raise TraitRuntimeError(
                code="scoring_file_invalid",
                message=f"Row {index} in scoring file is missing effect_allele or effect_weight.",
                details={"path": str(path), "row_index": index},
            )
        if not rsid and not (chromosome and position_text):
            raise TraitRuntimeError(
                code="scoring_file_invalid",
                message=f"Row {index} in scoring file needs rsid or chromosome+position.",
                details={"path": str(path), "row_index": index},
            )
        position = int(position_text) if position_text else 0
        trait_name = (
            trait_override
            or row.get("trait")
            or metadata.get("trait_reported")
            or metadata.get("pgs_name")
            or metadata.get("pgs_id")
            or path.stem
        )
        traits_seen.add(trait_name)
        variants.append(
            ScoringVariant(
                trait=trait_name,
                rsid=rsid,
                chromosome=chromosome.upper(),
                position=position,
                effect_allele=effect_allele,
                other_allele=other_allele,
                effect_weight=float(weight_text),
            )
        )
    if len(traits_seen) > 1 and not trait_override:
        raise TraitRuntimeError(
            code="scoring_file_invalid",
            message="Scoring file contains multiple traits. Select one trait for scoring.",
            details={"path": str(path), "traits_seen": sorted(traits_seen)},
        )
    return variants


def build_reference_artifact_summary(artifact: dict[str, object], path: Optional[Path] = None) -> dict[str, object]:
    trait_block = artifact.get("trait_block", {}) if isinstance(artifact.get("trait_block"), dict) else {}
    source_dataset = artifact.get("source_dataset", {}) if isinstance(artifact.get("source_dataset"), dict) else {}
    provenance = artifact.get("provenance", {}) if isinstance(artifact.get("provenance"), dict) else {}
    fingerprint = artifact.get("fingerprint", {}) if isinstance(artifact.get("fingerprint"), dict) else {}
    return {
        "path": str(path) if path else None,
        "artifact_type": artifact.get("artifact_type"),
        "reference_schema_version": artifact.get("reference_schema_version"),
        "engine_version": artifact.get("engine_version"),
        "registry_version": artifact.get("registry_version"),
        "reference_type": artifact.get("reference_type"),
        "trait": artifact.get("trait"),
        "trait_id": trait_block.get("trait_id", artifact.get("trait_id")),
        "display_name": trait_block.get("display_name", artifact.get("display_name")),
        "valid": artifact.get("valid", True),
        "warnings": list(artifact.get("warnings", [])) if isinstance(artifact.get("warnings"), list) else [],
        "sample_count_total": artifact.get("sample_count_total"),
        "sample_count_included": artifact.get("sample_count_included"),
        "source_name": source_dataset.get("source_name"),
        "source_dataset_id": source_dataset.get("source_dataset_id"),
        "build_timestamp_utc": provenance.get("build_timestamp_utc"),
        "build_mode": provenance.get("build_mode"),
        "artifact_fingerprint": fingerprint.get("artifact_sha256"),
        "scoring_file_sha256": fingerprint.get("scoring_file_sha256"),
    }


def load_reference_distribution(path: Path, trait: Optional[str], expected_trait_id: Optional[str]) -> ReferenceDistribution:
    payload = json.loads(_read_text(path))
    if not isinstance(payload, dict):
        raise TraitRuntimeError(
            code="reference_distribution_invalid",
            message="Reference JSON must be an object.",
            details={"path": str(path)},
        )

    artifact_trait = str(payload.get("trait") or "").strip()
    if trait and artifact_trait and artifact_trait != trait:
        raise TraitRuntimeError(
            code="reference_distribution_invalid",
            message="Reference artifact trait does not match the selected scoring trait.",
            details={"path": str(path), "reference_trait": artifact_trait, "selected_trait": trait},
        )
    reference_trait_id = str(payload.get("trait_id") or "")
    if expected_trait_id and reference_trait_id and reference_trait_id != expected_trait_id:
        raise TraitRuntimeError(
            code="reference_distribution_invalid",
            message="Reference artifact trait_id does not match the requested registry trait.",
            details={
                "path": str(path),
                "reference_trait_id": reference_trait_id,
                "expected_trait_id": expected_trait_id,
            },
        )

    return ReferenceDistribution(
        trait=artifact_trait or trait or path.stem,
        mean=float(payload["mean"]),
        sd=float(payload["sd"]),
        valid=bool(payload.get("valid", True)),
        warnings=list(payload.get("warnings", [])),
        artifact_type=str(payload.get("artifact_type") or ""),
        schema_version=int(payload.get("reference_schema_version", 0) or 0),
        trait_id=reference_trait_id or None,
        display_name=str(payload.get("display_name") or payload.get("trait") or path.stem),
        artifact=build_reference_artifact_summary(payload, path),
    )


def _normalize_allele(value: str) -> str:
    return value.strip().upper()


def _is_palindromic_pair(effect_allele: str, other_allele: str) -> bool:
    return {effect_allele, other_allele} in ({"A", "T"}, {"C", "G"})


def _match_effect_dosage(genotype: str, effect_allele: str, other_allele: str) -> tuple[Optional[int], str]:
    genotype_value = _normalize_genotype(genotype)
    effect = _normalize_allele(effect_allele)
    other = _normalize_allele(other_allele)

    if len(genotype_value) != 2 or any(base not in COMPLEMENT for base in genotype_value):
        return None, "invalid_genotype"
    if effect not in COMPLEMENT:
        return None, "invalid_scoring_alleles"
    if not other:
        return genotype_value.count(effect), "effect_allele_only"
    if other not in COMPLEMENT or effect == other:
        return None, "invalid_scoring_alleles"
    if _is_palindromic_pair(effect, other):
        return None, "ambiguous_palindromic"

    genotype_alleles = set(genotype_value)
    if genotype_alleles.issubset({effect, other}):
        return genotype_value.count(effect), "direct"

    flipped_effect = COMPLEMENT[effect]
    flipped_other = COMPLEMENT[other]
    if genotype_alleles.issubset({flipped_effect, flipped_other}):
        return genotype_value.count(flipped_effect), "strand_flip"

    return None, "allele_mismatch"


def _interpret_z_score(z_score: float) -> str:
    if z_score <= -2.0:
        return "Well below the reference mean."
    if z_score <= -0.5:
        return "Below the reference mean."
    if z_score < 0.5:
        return "Within the reference range."
    if z_score < 2.0:
        return "Above the reference mean."
    return "Well above the reference mean."


def _percentile_from_z_score(z_score: float) -> float:
    return 50.0 * (1.0 + math.erf(z_score / math.sqrt(2.0)))


def _classify_confidence(
    *,
    matched_variants: int,
    overlap_percent: float,
    reference_missing: bool,
    reference_invalid: bool,
) -> str:
    if reference_missing or reference_invalid:
        return "low"
    if matched_variants >= 20 and overlap_percent >= 60.0:
        return "high"
    if matched_variants >= 10 and overlap_percent >= 30.0:
        return "medium"
    return "low"


def score_polygenic_trait(
    sample_variants: Sequence[VariantRecord],
    scoring_variants: Sequence[ScoringVariant],
    reference_distribution: Optional[ReferenceDistribution],
    sample_id: str,
    scoring_model_path: Path,
    reference_distribution_path: Optional[Path],
) -> PGSResult:
    if not scoring_variants:
        raise TraitRuntimeError(code="scoring_file_invalid", message="No scoring variants were provided.")

    by_rsid = {variant.rsid: variant for variant in sample_variants if variant.rsid}
    by_locus = {
        (variant.chromosome, variant.position): variant
        for variant in sample_variants
        if variant.chromosome and variant.position
    }
    total_variants = len(scoring_variants)
    skip_reasons: Counter[str] = Counter()
    excluded_variants: list[ExcludedVariantDiagnostic] = []
    raw_score = 0.0
    ambiguous_removed = 0
    strand_flipped = 0
    matched_variants = 0

    for scoring_variant in scoring_variants:
        sample_variant = None
        if scoring_variant.rsid:
            sample_variant = by_rsid.get(scoring_variant.rsid)
        if sample_variant is None and scoring_variant.chromosome and scoring_variant.position:
            sample_variant = by_locus.get((scoring_variant.chromosome, scoring_variant.position))
        if sample_variant is None:
            skip_reasons["variant_not_found"] += 1
            excluded_variants.append(
                ExcludedVariantDiagnostic(
                    rsid=scoring_variant.rsid,
                    chromosome=scoring_variant.chromosome,
                    position=scoring_variant.position,
                    reason="variant_not_found",
                )
            )
            continue

        dosage, match_mode = _match_effect_dosage(
            sample_variant.genotype,
            scoring_variant.effect_allele,
            scoring_variant.other_allele,
        )
        if dosage is None:
            skip_reasons[match_mode] += 1
            if match_mode == "ambiguous_palindromic":
                ambiguous_removed += 1
            excluded_variants.append(
                ExcludedVariantDiagnostic(
                    rsid=sample_variant.rsid or scoring_variant.rsid,
                    chromosome=sample_variant.chromosome or scoring_variant.chromosome,
                    position=sample_variant.position or scoring_variant.position,
                    reason=match_mode,
                )
            )
            continue

        if match_mode == "strand_flip":
            strand_flipped += 1

        matched_variants += 1
        raw_score += dosage * scoring_variant.effect_weight

    skipped_variants = total_variants - matched_variants
    overlap_percent = (matched_variants / total_variants * 100.0) if total_variants else 0.0
    qc_flags: list[str] = []
    if overlap_percent < 60.0:
        qc_flags.append(QC_FLAG_LOW_OVERLAP)
    if matched_variants < 10:
        qc_flags.append(QC_FLAG_LOW_MATCHED_VARIANT_COUNT)
    if total_variants and (ambiguous_removed / total_variants) >= 0.2:
        qc_flags.append(QC_FLAG_HIGH_AMBIGUOUS_REMOVAL_RATE)
    if reference_distribution is None:
        qc_flags.append(QC_FLAG_MISSING_REFERENCE_DISTRIBUTION)
    else:
        invalid_reference_sd = not math.isfinite(reference_distribution.sd) or reference_distribution.sd <= 0
        if invalid_reference_sd:
            qc_flags.append(QC_FLAG_INVALID_REFERENCE_SD)
        if "too_few_included_samples" in set(reference_distribution.warnings) or (
            not reference_distribution.valid and not invalid_reference_sd
        ):
            qc_flags.append(QC_FLAG_WEAK_REFERENCE_PANEL)

    if reference_distribution is None:
        z_score = None
        percentile = None
        interpretation = "Inspection only; reference normalization was skipped."
        trait = scoring_variants[0].trait
    elif QC_FLAG_INVALID_REFERENCE_SD in qc_flags:
        z_score = None
        percentile = None
        interpretation = "Reference distribution is invalid; z-score and percentile were not computed."
        trait = reference_distribution.trait
    else:
        z_score = (raw_score - reference_distribution.mean) / reference_distribution.sd
        percentile = _percentile_from_z_score(z_score)
        interpretation = _interpret_z_score(z_score)
        trait = reference_distribution.trait

    confidence = _classify_confidence(
        matched_variants=matched_variants,
        overlap_percent=overlap_percent,
        reference_missing=reference_distribution is None,
        reference_invalid=QC_FLAG_INVALID_REFERENCE_SD in qc_flags or QC_FLAG_WEAK_REFERENCE_PANEL in qc_flags,
    )

    qc_summary = PGSQC(
        total_variants=total_variants,
        matched_variants=matched_variants,
        skipped_variants=skipped_variants,
        overlap_percent=overlap_percent,
        ambiguous_variants_removed=ambiguous_removed,
        strand_flipped_variants=strand_flipped,
        skip_reasons=dict(sorted(skip_reasons.items())),
    )
    return PGSResult(
        trait=trait,
        sample_id=sample_id,
        raw_score=raw_score,
        z_score=z_score,
        percentile=percentile,
        interpretation=interpretation,
        confidence=confidence,
        qc_summary=qc_summary,
        qc_flags=qc_flags,
        excluded_variants=excluded_variants,
        scoring_model_path=str(scoring_model_path),
        reference_distribution_path=str(reference_distribution_path) if reference_distribution_path else None,
        reference_artifact=dict(reference_distribution.artifact) if reference_distribution else {},
    )


def _status_label(status: str) -> str:
    return {
        "usable": "Usable",
        "smoke-test": "Smoke test",
        "experimental": "Experimental",
        "deprecated": "Deprecated",
    }.get(status, status.replace("_", " ").title())


def _derive_product_status(status: str, confidence: str, qc_flags: Sequence[str]) -> str:
    normalized_status = validate_trait_status(status)
    if normalized_status == "deprecated":
        return "deprecated"
    if normalized_status == "smoke-test":
        return "smoke-test"
    if normalized_status == "experimental":
        return "experimental"
    if confidence == "high":
        return "product_ready"
    if confidence == "medium":
        return "cautious"
    return "limited"


def _build_product_payload(
    technical_payload: dict[str, object],
    trait_entry: dict[str, object],
    passport: dict[str, object],
) -> dict[str, object]:
    status = validate_trait_status(str(passport.get("status", trait_entry.get("status", "experimental"))))
    confidence = str(technical_payload.get("confidence", "unknown"))
    interpretation = str(technical_payload.get("interpretation", ""))
    overlap_percent = technical_payload.get("qc_summary", {}).get("overlap_percent")
    matched_variants = technical_payload.get("qc_summary", {}).get("matched_variants")
    total_variants = technical_payload.get("qc_summary", {}).get("total_variants")
    percentile = technical_payload.get("percentile")
    z_score = technical_payload.get("z_score")

    reference_summary = technical_payload.get("reference_artifact")
    if not isinstance(reference_summary, dict) or not reference_summary:
        reference_summary = {}

    context = {
        "display_name": passport["display_name"],
        "short_name": passport["short_name"],
        "interpretation": interpretation,
        "confidence": confidence,
        "overlap_percent": 0.0 if overlap_percent is None else float(overlap_percent),
        "matched_variants": 0 if matched_variants is None else int(matched_variants),
        "total_variants": 0 if total_variants is None else int(total_variants),
        "percentile": "n/a" if percentile is None else f"{float(percentile):.1f}",
        "z_score": "n/a" if z_score is None else f"{float(z_score):.2f}",
    }

    result_summary = str(passport["result_summary_template"]).format(**context).strip()
    rendered_interpretation = str(passport["interpretation_template"]).format(**context).strip()

    return {
        "schema_version": passport["schema_version"],
        "trait_id": trait_entry["trait_id"],
        "pgs_id": passport.get("pgs_id") or trait_entry.get("pgs_id"),
        "display_name": passport["display_name"],
        "short_name": passport["short_name"],
        "short_description": passport["short_description"],
        "group": passport["group"],
        "status": status,
        "status_label": _status_label(status),
        "consumer_ready": passport["consumer_ready"],
        "result_summary": result_summary,
        "interpretation": rendered_interpretation,
        "confidence": confidence,
        "caution_text": passport["caution_text"],
        "percentile": percentile,
        "z_score": z_score,
        "raw_score": technical_payload.get("raw_score"),
        "qc_flags": list(technical_payload.get("qc_flags", [])),
        "key_metrics": {
            "total_variants": total_variants,
            "matched_variants": matched_variants,
            "overlap_percent": overlap_percent,
            "ambiguous_variants_removed": technical_payload.get("qc_summary", {}).get("ambiguous_variants_removed"),
            "strand_flipped_variants": technical_payload.get("qc_summary", {}).get("strand_flipped_variants"),
        },
        "reference_panel": reference_summary,
        "product_status": passport.get("product_status") or _derive_product_status(status, confidence, list(technical_payload.get("qc_flags", []))),
        "category": passport["category"],
        "summary_note": passport["summary_note"],
        "what_it_measures": passport["what_it_measures"],
        "confidence_note": passport["confidence_note"],
        "reference_note": passport["reference_note"],
        "limitations": list(passport.get("limitations", [])),
        "audience": passport.get("audience"),
        "tags": list(passport.get("tags", [])),
    }


class TraitsRuntimeService:
    def __init__(self, catalog: TraitCatalog) -> None:
        self.catalog = catalog

    def score_trait(
        self,
        *,
        trait_id: str,
        raw_path: Path,
        sample_id: str,
        input_format: str = "auto",
        keep_all_chromosomes: bool = False,
    ) -> TraitRunOutput:
        detail = self.catalog.get_trait_detail(trait_id)
        if not detail.entry.scoring_file_path.exists():
            raise TraitRuntimeError(
                code="scoring_file_invalid",
                message=f"Scoring file not found for {trait_id}.",
                details={"trait_id": trait_id, "path": str(detail.entry.scoring_file_path)},
            )
        if detail.entry.reference_file_path is None or not detail.entry.reference_file_path.exists():
            raise TraitRuntimeError(
                code="reference_distribution_invalid",
                message=f"Reference distribution not found for {trait_id}.",
                details={"trait_id": trait_id},
            )

        inspection = validate_raw_input_format(raw_path, input_format)
        raw_summary, calls = parse_raw_dna(raw_path)
        sample_variants = [
            item
            for item in calls
            if keep_all_chromosomes or item.chromosome in AUTOSOMES
        ]
        scoring_variants = load_scoring_variants(detail.entry.scoring_file_path)
        reference_distribution = load_reference_distribution(
            detail.entry.reference_file_path,
            trait=scoring_variants[0].trait,
            expected_trait_id=detail.entry.trait_id,
        )
        result = score_polygenic_trait(
            sample_variants,
            scoring_variants,
            reference_distribution,
            sample_id=sample_id,
            scoring_model_path=detail.entry.scoring_file_path,
            reference_distribution_path=detail.entry.reference_file_path,
        )
        technical_payload = self._build_technical_payload(
            result=result,
            detail=detail,
            raw_path=raw_path,
            raw_summary=raw_summary,
            inspection=inspection,
            input_format=input_format,
            keep_all_chromosomes=keep_all_chromosomes,
        )
        product_payload = _build_product_payload(
            technical_payload,
            detail.entry.registry_entry,
            detail.entry.passport,
        )
        return TraitRunOutput(
            trait_id=detail.entry.trait_id,
            sample_id=sample_id,
            display_name=detail.entry.display_name,
            short_name=detail.entry.short_name,
            technical_payload=technical_payload,
            product_payload=product_payload,
        )

    def run_batch(
        self,
        *,
        raw_path: Path,
        sample_id: str,
        explicit_trait_ids: Sequence[str] = (),
        usable_only: bool = False,
        input_format: str = "auto",
        keep_all_chromosomes: bool = False,
    ) -> dict[str, object]:
        selected: list[TraitCatalogEntry] = []
        seen: set[str] = set()
        if usable_only:
            for entry in self.catalog.usable_traits():
                if entry.trait_id not in seen:
                    selected.append(entry)
                    seen.add(entry.trait_id)
        for trait_id in explicit_trait_ids:
            entry = self.catalog.get_trait(trait_id)
            if entry.trait_id not in seen:
                selected.append(entry)
                seen.add(entry.trait_id)
        if not selected:
            raise TraitRuntimeError(
                code="no_traits_selected",
                message="Provide at least one trait_id or use usable_only.",
            )

        traits_payload: list[dict[str, object]] = []
        failures: list[dict[str, object]] = []
        for entry in selected:
            try:
                scored = self.score_trait(
                    trait_id=entry.trait_id,
                    raw_path=raw_path,
                    sample_id=sample_id,
                    input_format=input_format,
                    keep_all_chromosomes=keep_all_chromosomes,
                )
                product_payload = dict(scored.product_payload)
                product_payload["technical_summary"] = {
                    "sample_id": sample_id,
                    "inspection_only": False,
                    "confidence": scored.technical_payload["confidence"],
                    "qc_flags": list(scored.technical_payload["qc_flags"]),
                    "matched_variants": scored.technical_payload["qc_summary"]["matched_variants"],
                    "total_variants": scored.technical_payload["qc_summary"]["total_variants"],
                    "overlap_percent": scored.technical_payload["qc_summary"]["overlap_percent"],
                }
                traits_payload.append(product_payload)
            except TraitRuntimeError as exc:
                failures.append(
                    {
                        "code": exc.code,
                        "message": exc.message,
                        "details": exc.details,
                        "trait_id": entry.trait_id,
                        "display_name": entry.display_name,
                        "status": entry.status,
                        "hard_failure": True,
                    }
                )

        return {
            "registry_version": self.catalog.registry_version(),
            "sample_id": sample_id,
            "input": str(raw_path),
            "selection_mode": {
                "trait_ids": [item.trait_id for item in selected if item.trait_id in explicit_trait_ids],
                "usable_only": bool(usable_only),
            },
            "run_summary": {
                "requested_trait_count": len(selected),
                "completed_trait_count": len(traits_payload),
                "failed_trait_count": len(failures),
                "usable_trait_count": sum(1 for item in traits_payload if item.get("status") == "usable"),
                "smoke_test_trait_count": sum(1 for item in traits_payload if item.get("status") == "smoke-test"),
            },
            "traits": traits_payload,
            "failures": failures,
        }

    def _build_technical_payload(
        self,
        *,
        result: PGSResult,
        detail: TraitDetail,
        raw_path: Path,
        raw_summary: RawSummaryRecord,
        inspection: dict[str, object],
        input_format: str,
        keep_all_chromosomes: bool,
    ) -> dict[str, object]:
        excluded_preview_limit = 20
        excluded_variants = [asdict(item) for item in result.excluded_variants[:excluded_preview_limit]]
        return {
            "trait": result.trait,
            "trait_id": detail.entry.trait_id,
            "trait_registry_status": detail.entry.status,
            "trait_registry_display_name": detail.entry.display_name,
            "sample_id": result.sample_id,
            "raw_score": result.raw_score,
            "z_score": result.z_score,
            "percentile": result.percentile,
            "interpretation": result.interpretation,
            "confidence": result.confidence,
            "qc_summary": asdict(result.qc_summary),
            "qc_flags": list(result.qc_flags),
            "excluded_variants_count": len(result.excluded_variants),
            "excluded_variants_preview_limit": excluded_preview_limit,
            "excluded_variants": excluded_variants,
            "excluded_variants_truncated": len(result.excluded_variants) > len(excluded_variants),
            "reference_artifact": dict(result.reference_artifact),
            "reference_distribution_path": result.reference_distribution_path,
            "scoring_model_path": result.scoring_model_path,
            "input": str(raw_path),
            "vendor_hint": raw_summary.vendor_hint,
            "input_format_requested": input_format,
            "input_format_detected": inspection["detected_format"],
            "input_format_validated": inspection["header_ok"]
            and (input_format == "auto" or inspection["detected_format"] == input_format),
            "input_schema": {
                "header_ok": inspection["header_ok"],
                "normalized_header": inspection["normalized_header"],
                "delimiter": inspection["delimiter"],
            },
            "inspection_only": False,
            "autosomal_input_rows": raw_summary.autosomal_rows,
            "autosomal_called_rows": raw_summary.autosomal_called_rows,
            "keep_all_chromosomes": bool(keep_all_chromosomes),
        }
