from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
ADMIX_DIR = ROOT / "admix"
sys.path.insert(0, str(ADMIX_DIR))

import admix  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(admix.main())
