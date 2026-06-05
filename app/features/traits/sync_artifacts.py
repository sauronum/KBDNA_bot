from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    from .import_artifacts import FEATURE_ROOT, import_trait_artifacts
except ImportError:  # Allow running this file directly during local maintenance.
    sys.path.append(str(Path(__file__).resolve().parents[3]))
    from app.features.traits.import_artifacts import FEATURE_ROOT, import_trait_artifacts


def sync_traits_artifacts(source_root: Path) -> int:
    import_trait_artifacts(source_root, target_root=FEATURE_ROOT, all_traits=True)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Sync traits artifacts from dna_platform into the bot feature.")
    parser.add_argument("source_root", type=Path, help="Path to the dna_platform project root")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return sync_traits_artifacts(args.source_root)


if __name__ == "__main__":
    raise SystemExit(main())
