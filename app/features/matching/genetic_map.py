from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


DEFAULT_GENETIC_MAP_PATH = Path(__file__).resolve().parent / "data" / "genetic_map" / "plink.GRCh37.map"


@dataclass(frozen=True)
class GeneticMapPoint:
    bp: int
    cm: float


class GeneticMap:
    def __init__(self, points_by_chromosome: dict[str, tuple[GeneticMapPoint, ...]]) -> None:
        self._points = points_by_chromosome
        self._positions = {
            chromosome: tuple(point.bp for point in points)
            for chromosome, points in points_by_chromosome.items()
        }

    @property
    def is_loaded(self) -> bool:
        return bool(self._points)

    @classmethod
    def empty(cls) -> "GeneticMap":
        return cls({})

    @classmethod
    def from_plink_map(cls, path: Path) -> "GeneticMap":
        if not path.exists():
            return cls.empty()

        grouped: dict[str, list[GeneticMapPoint]] = {}
        for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            fields = line.split()
            if len(fields) < 4:
                continue
            chromosome = _normalize_chromosome(fields[0])
            if chromosome is None:
                continue
            try:
                cm = float(fields[2])
                bp = int(fields[3])
            except ValueError:
                continue
            grouped.setdefault(chromosome, []).append(GeneticMapPoint(bp=bp, cm=cm))

        return cls(
            {
                chromosome: tuple(sorted(points, key=lambda point: point.bp))
                for chromosome, points in grouped.items()
                if points
            }
        )

    def has_chromosome(self, chromosome: str) -> bool:
        return _normalize_chromosome(chromosome) in self._points

    def cm_at(self, chromosome: str, position_bp: int) -> float | None:
        chrom = _normalize_chromosome(chromosome)
        if chrom is None:
            return None
        points = self._points.get(chrom)
        positions = self._positions.get(chrom)
        if not points or not positions:
            return None

        index = bisect_left(positions, position_bp)
        if index < len(points) and points[index].bp == position_bp:
            return points[index].cm
        if index == 0 or index >= len(points):
            return None

        left = points[index - 1]
        right = points[index]
        span = right.bp - left.bp
        if span <= 0:
            return left.cm
        fraction = (position_bp - left.bp) / span
        return left.cm + ((right.cm - left.cm) * fraction)

    def cm_between(self, chromosome: str, start_bp: int, end_bp: int) -> float | None:
        start_cm = self.cm_at(chromosome, start_bp)
        end_cm = self.cm_at(chromosome, end_bp)
        if start_cm is None or end_cm is None:
            return None
        return max(0.0, end_cm - start_cm)


@lru_cache(maxsize=1)
def default_genetic_map() -> GeneticMap:
    return GeneticMap.from_plink_map(DEFAULT_GENETIC_MAP_PATH)


def _normalize_chromosome(value: str) -> str | None:
    chromosome = value.strip().replace("chr", "").replace("CHR", "").upper()
    if chromosome in {str(index) for index in range(1, 23)}:
        return chromosome
    return None
