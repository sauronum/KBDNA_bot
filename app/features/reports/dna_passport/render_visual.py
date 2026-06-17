from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .domain import DNAPassportData
from .visual_pages import (
    render_ancestry_page,
    render_lines_page,
    render_overview_page,
    render_snps_page,
    render_traits_page,
)


VisualRenderer = Callable[[DNAPassportData, Path], Path]


@dataclass(frozen=True)
class DNAPassportVisualPage:
    slug: str
    title: str
    page_number: int
    path: Path


_PAGE_RENDERERS: tuple[tuple[str, str, Callable[..., Path]], ...] = (
    ("overview", "Обложка", render_overview_page),
    ("ancestry", "Краткое происхождение", render_ancestry_page),
    ("traits", "Базовые признаки", render_traits_page),
    ("snps", "Интересные SNP", render_snps_page),
    ("lines", "Прямые линии", render_lines_page),
)


def render_dna_passport_pages(data: DNAPassportData, output_dir: Path) -> list[DNAPassportVisualPage]:
    output_dir.mkdir(parents=True, exist_ok=True)
    pages: list[DNAPassportVisualPage] = []
    total_pages = len(_PAGE_RENDERERS)
    for index, (slug, title, renderer) in enumerate(_PAGE_RENDERERS, start=1):
        path = output_dir / f"{index:02d}_{slug}.png"
        renderer(data, path, page_number=index, total_pages=total_pages)
        pages.append(DNAPassportVisualPage(slug=slug, title=title, page_number=index, path=path))
    return pages


def visual_page_order() -> tuple[str, ...]:
    return tuple(slug for slug, _title, _renderer in _PAGE_RENDERERS)
