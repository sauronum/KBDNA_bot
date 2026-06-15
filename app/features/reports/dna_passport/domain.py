from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class DNAPassportSampleSummary:
    status: str
    sample_id: str = ""
    display_name: str = ""
    created_at: str = ""
    error: str = ""


@dataclass(frozen=True)
class DNAPassportRawSummary:
    status: str
    raw_file_id: str = ""
    display_name: str = ""
    original_file_name: str = ""
    provider_hint: str = ""
    total_records: int = 0
    called_snps: int = 0
    autosomal_count: int = 0
    x_count: int = 0
    y_count: int = 0
    mtdna_count: int = 0
    call_rate: float | None = None
    skipped_invalid_count: int = 0
    error: str = ""


@dataclass(frozen=True)
class DNAPassportG25Population:
    name: str
    distance: float


@dataclass(frozen=True)
class DNAPassportG25Summary:
    status: str
    source: str = ""
    coordinate_id: str = ""
    display_name: str = ""
    target_name: str = ""
    region: str = ""
    top_modern: tuple[DNAPassportG25Population, ...] = ()
    first_distance: float | None = None
    first_second_gap: float | None = None
    error: str = ""


@dataclass(frozen=True)
class DNAPassportTraitItem:
    trait_id: str
    display_name: str
    status: str
    percentile: float | None = None
    confidence: str = ""
    overlap: float | None = None
    qc_flags: tuple[str, ...] = ()
    error: str = ""


@dataclass(frozen=True)
class DNAPassportTraitsSummary:
    status: str
    requested_count: int = 0
    completed_count: int = 0
    failed_count: int = 0
    traits: tuple[DNAPassportTraitItem, ...] = ()
    failures: tuple[DNAPassportTraitItem, ...] = ()
    error: str = ""


@dataclass(frozen=True)
class DNAPassportInterestingSnpItem:
    rsid: str
    title: str
    category: str
    gene: str
    genotype: str
    interpretation: str


@dataclass(frozen=True)
class DNAPassportInterestingSnpsSummary:
    status: str
    total: int = 0
    found: int = 0
    missing: int = 0
    unsupported: int = 0
    items: tuple[DNAPassportInterestingSnpItem, ...] = ()
    error: str = ""


@dataclass(frozen=True)
class DNAPassportLineageReadiness:
    status: str
    y_markers_detected: bool = False
    y_count: int = 0
    mtdna_markers_detected: bool = False
    mtdna_count: int = 0
    error: str = ""


@dataclass(frozen=True)
class DNAPassportData:
    sample: DNAPassportSampleSummary | None = None
    raw: DNAPassportRawSummary | None = None
    g25: DNAPassportG25Summary | None = None
    traits: DNAPassportTraitsSummary | None = None
    interesting_snps: DNAPassportInterestingSnpsSummary | None = None
    lineage: DNAPassportLineageReadiness | None = None
    warnings: tuple[str, ...] = field(default_factory=tuple)
    generated_at: str = ""
