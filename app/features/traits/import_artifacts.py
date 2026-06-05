from __future__ import annotations

import argparse
import json
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

try:
    from .domain.catalog import TraitCatalog, TraitCatalogError
except ImportError:  # Allow running this file directly during local maintenance.
    sys.path.append(str(Path(__file__).resolve().parents[3]))
    from app.features.traits.domain.catalog import TraitCatalog, TraitCatalogError


FEATURE_ROOT = Path(__file__).resolve().parent
REGISTRY_RELATIVE_PATH = Path("data") / "pgs" / "trait_registry.json"


class TraitArtifactImportError(ValueError):
    pass


@dataclass(frozen=True)
class TraitArtifactImportResult:
    imported_trait_ids: list[str]
    copied_files: list[Path]
    registry_path: Path
    dry_run: bool = False


def import_trait_artifacts(
    source_root: Path,
    *,
    trait_ids: Sequence[str] = (),
    pgs_ids: Sequence[str] = (),
    target_root: Path = FEATURE_ROOT,
    usable_only: bool = False,
    all_traits: bool = False,
    dry_run: bool = False,
) -> TraitArtifactImportResult:
    source_root = source_root.resolve()
    target_root = target_root.resolve()
    source_registry_path = source_root / REGISTRY_RELATIVE_PATH
    target_registry_path = target_root / REGISTRY_RELATIVE_PATH

    source_registry = _load_registry(source_registry_path)
    selected = _select_traits(
        source_registry.get("traits", []),
        trait_ids=trait_ids,
        pgs_ids=pgs_ids,
        usable_only=usable_only,
        all_traits=all_traits,
    )
    if not selected:
        raise TraitArtifactImportError("No traits matched the requested import selector.")

    copied_files: list[Path] = []
    for trait in selected:
        for relative_path in _artifact_paths_for_trait(trait):
            source_path = _resolve_relative(source_root, relative_path)
            if not source_path.exists():
                raise TraitArtifactImportError(
                    f"Referenced trait artifact does not exist: {relative_path}"
                )
            destination_path = _resolve_relative(target_root, relative_path)
            copied_files.append(destination_path)
            if not dry_run:
                destination_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_path, destination_path)

    if not dry_run:
        target_registry = _load_or_empty_registry(target_registry_path)
        merged_registry = _merge_registry(target_registry, source_registry, selected)
        target_registry_path.parent.mkdir(parents=True, exist_ok=True)
        target_registry_path.write_text(
            json.dumps(merged_registry, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        _validate_imported_traits(target_registry_path, [str(item["trait_id"]) for item in selected])

    return TraitArtifactImportResult(
        imported_trait_ids=[str(item["trait_id"]) for item in selected],
        copied_files=copied_files,
        registry_path=target_registry_path,
        dry_run=dry_run,
    )


def _load_registry(path: Path) -> dict[str, object]:
    if not path.exists():
        raise FileNotFoundError(f"Trait registry not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("traits"), list):
        raise TraitArtifactImportError(f"Invalid trait registry: {path}")
    return payload


def _load_or_empty_registry(path: Path) -> dict[str, object]:
    if path.exists():
        return _load_registry(path)
    return {"version": 1, "traits": []}


def _select_traits(
    traits: object,
    *,
    trait_ids: Sequence[str],
    pgs_ids: Sequence[str],
    usable_only: bool,
    all_traits: bool,
) -> list[dict[str, object]]:
    entries = [item for item in traits if isinstance(item, dict)]
    requested_trait_ids = {str(item).strip() for item in trait_ids if str(item).strip()}
    requested_pgs_ids = {str(item).strip().upper() for item in pgs_ids if str(item).strip()}

    if not all_traits and not requested_trait_ids and not requested_pgs_ids and not usable_only:
        raise TraitArtifactImportError("Pass --trait-id, --pgs-id, --usable-only, or --all.")

    selected: list[dict[str, object]] = []
    seen: set[str] = set()
    for item in entries:
        trait_id = str(item.get("trait_id") or "")
        pgs_id = str(item.get("pgs_id") or "").upper()
        status = str(item.get("status") or "").lower()
        include = all_traits or trait_id in requested_trait_ids or pgs_id in requested_pgs_ids
        if usable_only:
            include = include or status == "usable"
        if include and trait_id and trait_id not in seen:
            selected.append(dict(item))
            seen.add(trait_id)

    missing_traits = sorted(requested_trait_ids - seen)
    missing_pgs = sorted(
        pgs_id
        for pgs_id in requested_pgs_ids
        if pgs_id not in {str(item.get("pgs_id") or "").upper() for item in selected}
    )
    if missing_traits:
        raise TraitArtifactImportError(f"Unknown trait_id in source registry: {', '.join(missing_traits)}")
    if missing_pgs:
        raise TraitArtifactImportError(f"Unknown pgs_id in source registry: {', '.join(missing_pgs)}")
    return selected


def _artifact_paths_for_trait(trait: dict[str, object]) -> Iterable[Path]:
    for key in ("scoring_file_path", "reference_file_path", "metadata_path", "notes_path"):
        value = str(trait.get(key) or "").strip()
        if value:
            yield Path(value)


def _resolve_relative(root: Path, relative_path: Path) -> Path:
    if relative_path.is_absolute():
        raise TraitArtifactImportError(f"Trait artifact path must be relative: {relative_path}")
    resolved = (root / relative_path).resolve()
    root_resolved = root.resolve()
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise TraitArtifactImportError(f"Trait artifact path escapes project root: {relative_path}") from exc
    return resolved


def _merge_registry(
    target_registry: dict[str, object],
    source_registry: dict[str, object],
    selected_traits: Sequence[dict[str, object]],
) -> dict[str, object]:
    existing_traits = [
        dict(item)
        for item in target_registry.get("traits", [])
        if isinstance(item, dict) and item.get("trait_id")
    ]
    selected_by_id = {str(item["trait_id"]): dict(item) for item in selected_traits}
    merged: list[dict[str, object]] = []
    used: set[str] = set()

    for item in existing_traits:
        trait_id = str(item.get("trait_id") or "")
        if trait_id in selected_by_id:
            merged.append(selected_by_id[trait_id])
            used.add(trait_id)
        else:
            merged.append(item)

    for item in selected_traits:
        trait_id = str(item.get("trait_id") or "")
        if trait_id and trait_id not in used:
            merged.append(dict(item))
            used.add(trait_id)

    version = max(int(target_registry.get("version", 1)), int(source_registry.get("version", 1)))
    return {"version": version, "traits": merged}


def _validate_imported_traits(registry_path: Path, trait_ids: Sequence[str]) -> None:
    catalog = TraitCatalog(registry_path=registry_path)
    errors: list[str] = []
    for trait_id in trait_ids:
        try:
            entry = catalog.get_trait(trait_id)
        except TraitCatalogError as exc:
            errors.append(f"{trait_id}: {exc}")
            continue
        if not entry.scoring_file_path.exists():
            errors.append(f"{trait_id}: scoring file missing after import")
        if entry.reference_file_path is None or not entry.reference_file_path.exists():
            errors.append(f"{trait_id}: reference file missing after import")
    if errors:
        raise TraitArtifactImportError("Imported trait validation failed:\n" + "\n".join(errors))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Import selected PGS trait artifacts into the bot Traits feature.")
    parser.add_argument("source_root", type=Path, help="Project root that contains data/pgs/trait_registry.json.")
    parser.add_argument("--trait-id", action="append", default=[], help="Trait id to import. Can be repeated.")
    parser.add_argument("--pgs-id", action="append", default=[], help="PGS id to import. Can be repeated.")
    parser.add_argument("--usable-only", action="store_true", help="Import every source trait marked usable.")
    parser.add_argument("--all", action="store_true", help="Import every source registry trait.")
    parser.add_argument("--target-root", type=Path, default=FEATURE_ROOT, help="Bot traits feature root. Defaults to this package.")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be imported without writing files.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    result = import_trait_artifacts(
        args.source_root,
        trait_ids=args.trait_id,
        pgs_ids=args.pgs_id,
        target_root=args.target_root,
        usable_only=args.usable_only,
        all_traits=args.all,
        dry_run=args.dry_run,
    )
    mode = "DRY RUN" if result.dry_run else "IMPORTED"
    print(f"{mode}: {len(result.imported_trait_ids)} trait(s)")
    for trait_id in result.imported_trait_ids:
        print(f"- {trait_id}")
    print(f"Registry: {result.registry_path}")
    print(f"Artifacts: {len(result.copied_files)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
