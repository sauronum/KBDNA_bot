from __future__ import annotations

from pathlib import Path

from .domain import DNAPassportData
from .render_visual import DNAPassportVisualPage, render_dna_passport_pages
from .visual_pages import render_overview_page


def render_dna_passport_visual_png(data: DNAPassportData, output_path: Path) -> Path:
    """Compatibility wrapper for the old single-preview entrypoint."""
    return render_overview_page(data, output_path, page_number=1, total_pages=5)


__all__ = [
    "DNAPassportVisualPage",
    "render_dna_passport_pages",
    "render_dna_passport_visual_png",
]
