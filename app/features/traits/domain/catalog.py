from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


FEATURE_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = FEATURE_ROOT / "data" / "pgs" / "trait_registry.json"

TRAIT_STATUSES = (
    "usable",
    "experimental",
    "smoke-test",
    "deprecated",
)

PASSPORT_SCHEMA_VERSION = 1
PASSPORT_REQUIRED_FIELDS = {
    "schema_version",
    "trait_id",
    "pgs_id",
    "display_name",
    "short_name",
    "group",
    "category",
    "status",
    "consumer_ready",
    "short_description",
    "summary_note",
    "what_it_measures",
    "result_summary_template",
    "interpretation_template",
    "caution_text",
    "limitations",
    "confidence_note",
    "reference_note",
}
TRAIT_GROUPS = (
    "appearance",
    "body",
    "nutrition",
    "lifestyle",
    "mind",
    "health_research",
    "sensitive_research",
    "internal",
)


class TraitCatalogError(ValueError):
    pass


def validate_trait_status(status: str) -> str:
    normalized = (status or "").strip().lower()
    if normalized not in TRAIT_STATUSES:
        allowed = ", ".join(TRAIT_STATUSES)
        raise TraitCatalogError(f"Unsupported trait status '{status}'. Allowed statuses: {allowed}")
    return normalized


def validate_trait_passport(trait_entry: dict[str, object], passport: dict[str, object]) -> dict[str, object]:
    trait_id = str(trait_entry.get("trait_id", ""))
    status = validate_trait_status(str(passport.get("status") or trait_entry.get("status") or "experimental"))
    missing = sorted(field for field in PASSPORT_REQUIRED_FIELDS if field not in passport)
    if missing and status == "usable":
        raise TraitCatalogError(
            f"Usable trait passport '{trait_id}' is missing required fields: {', '.join(missing)}"
        )

    schema_version = int(passport.get("schema_version", 0))
    if schema_version != PASSPORT_SCHEMA_VERSION:
        raise TraitCatalogError(
            f"Trait passport '{trait_id}' uses unsupported schema_version={schema_version}."
        )
    if passport.get("trait_id") != trait_id:
        raise TraitCatalogError(
            f"Trait passport '{trait_id}' has mismatched trait_id '{passport.get('trait_id')}'."
        )
    if trait_entry.get("pgs_id") and passport.get("pgs_id") != trait_entry.get("pgs_id"):
        raise TraitCatalogError(
            f"Trait passport '{trait_id}' has mismatched pgs_id '{passport.get('pgs_id')}'."
        )

    normalized = dict(passport)
    normalized["status"] = status
    normalized["group"] = str(passport.get("group", "")).strip()
    if normalized["group"] and normalized["group"] not in TRAIT_GROUPS:
        raise TraitCatalogError(
            f"Trait passport '{trait_id}' uses unsupported group '{normalized['group']}'."
        )
    normalized["consumer_ready"] = bool(passport.get("consumer_ready", False))
    normalized["limitations"] = list(passport.get("limitations", []))
    normalized["tags"] = list(passport.get("tags", []))
    return normalized


def load_reference_panel_summary(reference_path: Optional[Path]) -> Optional[dict[str, object]]:
    if reference_path is None or not reference_path.exists():
        return None
    payload = json.loads(reference_path.read_text(encoding="utf-8"))
    included = payload.get("sample_count_included", payload.get("reference_sample_count"))
    total = payload.get("sample_count_total", payload.get("reference_sample_count"))
    return {
        "reference_type": payload.get("reference_type"),
        "valid": payload.get("valid", True),
        "sample_count_included": included,
        "sample_count_total": total,
        "warnings": payload.get("warnings", []),
    }


@dataclass(frozen=True)
class TraitCatalogEntry:
    trait_id: str
    pgs_id: str
    display_name: str
    short_name: str
    group: str
    category: str
    status: str
    consumer_ready: bool
    short_description: str
    summary_note: str
    what_it_measures: str
    caution_text: str
    tags: list[str]
    scoring_file_path: Path
    reference_file_path: Optional[Path]
    metadata_path: Path
    notes_path: Optional[Path]
    registry_entry: dict[str, object]
    passport: dict[str, object]
    reference_panel: Optional[dict[str, object]]


@dataclass(frozen=True)
class TraitDetail:
    entry: TraitCatalogEntry
    notes_markdown: str


class TraitCatalog:
    def __init__(self, registry_path: Path = REGISTRY_PATH) -> None:
        self.registry_path = registry_path

    def registry_version(self) -> int:
        registry = self._load_registry()
        return int(registry.get("version", 1))

    def list_traits(self) -> list[TraitCatalogEntry]:
        registry = self._load_registry()
        items = [self._build_entry(item) for item in registry["traits"]]
        return sorted(items, key=lambda item: (item.group, item.display_name.lower(), item.trait_id))

    def usable_traits(self) -> list[TraitCatalogEntry]:
        return [item for item in self.list_traits() if item.status == "usable"]

    def get_trait(self, trait_id: str) -> TraitCatalogEntry:
        registry = self._load_registry()
        for item in registry["traits"]:
            if str(item.get("trait_id")) == trait_id:
                return self._build_entry(item)
        available = ", ".join(sorted(str(item.get("trait_id")) for item in registry["traits"]))
        raise TraitCatalogError(f"Unknown trait_id '{trait_id}'. Available trait_ids: {available}")

    def get_trait_detail(self, trait_id: str) -> TraitDetail:
        entry = self.get_trait(trait_id)
        notes_markdown = ""
        if entry.notes_path is not None and entry.notes_path.exists():
            notes_markdown = entry.notes_path.read_text(encoding="utf-8").strip()
        return TraitDetail(entry=entry, notes_markdown=notes_markdown)

    def counts(self) -> dict[str, int]:
        traits = self.list_traits()
        return {
            "trait_count": len(traits),
            "consumer_ready_trait_count": sum(1 for item in traits if item.consumer_ready),
            "usable_trait_count": sum(1 for item in traits if item.status == "usable"),
        }

    def _load_registry(self) -> dict[str, object]:
        if not self.registry_path.exists():
            raise TraitCatalogError(f"Trait registry file not found: {self.registry_path}")
        payload = json.loads(self.registry_path.read_text(encoding="utf-8"))
        traits = payload.get("traits", [])
        if not isinstance(traits, list):
            raise TraitCatalogError("Trait registry is invalid: 'traits' must be a list.")
        for entry in traits:
            if not isinstance(entry, dict):
                raise TraitCatalogError("Trait registry is invalid: each trait entry must be an object.")
            entry["status"] = validate_trait_status(str(entry.get("status", "experimental")))
        return {
            "version": payload.get("version", 1),
            "traits": traits,
        }

    def _registry_root(self) -> Path:
        return self.registry_path.resolve().parents[2]

    def _resolve_relative(self, relative_path: str | None) -> Optional[Path]:
        if not relative_path:
            return None
        return self._registry_root() / relative_path

    def _build_entry(self, registry_entry: dict[str, object]) -> TraitCatalogEntry:
        metadata_path = self._resolve_relative(str(registry_entry.get("metadata_path") or ""))
        if metadata_path is None or not metadata_path.exists():
            raise TraitCatalogError(f"Trait metadata file not found for {registry_entry.get('trait_id')}.")
        passport = validate_trait_passport(
            registry_entry,
            json.loads(metadata_path.read_text(encoding="utf-8")),
        )
        reference_path = self._resolve_relative(str(registry_entry.get("reference_file_path") or ""))
        return TraitCatalogEntry(
            trait_id=str(registry_entry.get("trait_id") or ""),
            pgs_id=str(passport.get("pgs_id") or registry_entry.get("pgs_id") or ""),
            display_name=str(passport.get("display_name") or registry_entry.get("display_name") or ""),
            short_name=str(passport.get("short_name") or passport.get("display_name") or ""),
            group=str(passport.get("group") or registry_entry.get("group") or ""),
            category=str(passport.get("category") or ""),
            status=str(passport.get("status") or registry_entry.get("status") or "experimental"),
            consumer_ready=bool(passport.get("consumer_ready", False)),
            short_description=str(passport.get("short_description") or registry_entry.get("short_description") or ""),
            summary_note=str(passport.get("summary_note") or ""),
            what_it_measures=str(passport.get("what_it_measures") or ""),
            caution_text=str(passport.get("caution_text") or registry_entry.get("caution_text") or ""),
            tags=list(passport.get("tags", [])),
            scoring_file_path=self._resolve_relative(str(registry_entry.get("scoring_file_path") or "")) or Path(),
            reference_file_path=reference_path,
            metadata_path=metadata_path,
            notes_path=self._resolve_relative(str(registry_entry.get("notes_path") or "")),
            registry_entry=dict(registry_entry),
            passport=passport,
            reference_panel=load_reference_panel_summary(reference_path),
        )
