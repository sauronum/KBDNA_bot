from __future__ import annotations

import csv
import math
import re
from dataclasses import dataclass
from pathlib import Path

from g25_core.g25_engine import K36_COMPONENTS
from g25_core.vendor.admix import admix_models


@dataclass(frozen=True)
class OracleReferenceSource:
    model: str
    filename: str
    title: str
    url: str
    unofficial: bool = False


@dataclass(frozen=True)
class OraclePopulation:
    name: str
    source: str
    values: dict[str, float]


@dataclass(frozen=True)
class OracleReferenceSet:
    source: OracleReferenceSource
    populations: tuple[OraclePopulation, ...]


@dataclass(frozen=True)
class OracleMatch:
    population: str
    source: str
    distance: float


@dataclass(frozen=True)
class OracleMixMatch:
    populations: tuple[str, ...]
    sources: tuple[str, ...]
    percents: tuple[int, ...]
    distance: float

    @property
    def population_a(self) -> str:
        return self.populations[0] if len(self.populations) > 0 else ""

    @property
    def source_a(self) -> str:
        return self.sources[0] if len(self.sources) > 0 else ""

    @property
    def percent_a(self) -> int:
        return self.percents[0] if len(self.percents) > 0 else 0

    @property
    def population_b(self) -> str:
        return self.populations[1] if len(self.populations) > 1 else ""

    @property
    def source_b(self) -> str:
        return self.sources[1] if len(self.sources) > 1 else ""

    @property
    def percent_b(self) -> int:
        return self.percents[1] if len(self.percents) > 1 else 0


ORACLE_REFERENCE_SOURCES: dict[str, OracleReferenceSource] = {
    "K13": OracleReferenceSource(
        model="K13",
        filename="K13.source.csv",
        title="Eurogenes K13 population spreadsheet",
        url="https://docs.google.com/spreadsheets/d/1dCZldTIfd-EPjDlpQiFNcHwOtZus9Qdll3pB48zdQG0/edit",
    ),
    "K36": OracleReferenceSource(
        model="K36",
        filename="K36.source.csv",
        title="Eurogenes K36 averages",
        url="https://www.exploreyourdna.com/liste/103/eurogenes-k36-averages.htm?action=csv",
        unofficial=True,
    ),
    "K7b": OracleReferenceSource(
        model="K7b",
        filename="K7b.source.csv",
        title="Dodecad K7b spreadsheet",
        url="https://docs.google.com/spreadsheets/d/1Me2vweYJN2mNtnDaypabv31sy2-kSWVhNJvanIsWtJU/edit",
    ),
    "K12b": OracleReferenceSource(
        model="K12b",
        filename="K12b.source.csv",
        title="Dodecad K12b spreadsheet",
        url="https://docs.google.com/spreadsheets/d/1GWhNZcfTQ2hMSK9Ni1IqG7aXHB00SRE5L6ED2osPs9M/edit",
    ),
    "HarappaWorld": OracleReferenceSource(
        model="HarappaWorld",
        filename="HarappaWorld.source.csv",
        title="HarappaWorld admixture spreadsheet",
        url="https://docs.google.com/spreadsheets/d/1l87nGSIYTP-h7m-VKjB-BZcuEoWdz765nU4f_krOdd4/edit",
    ),
}


def oracle_reference_dir(root_dir: Path) -> Path:
    return root_dir / "g25_core" / "vendor" / "admix" / "oracle_references"


def available_oracle_models(reference_dir: Path) -> set[str]:
    return {
        model
        for model, source in ORACLE_REFERENCE_SOURCES.items()
        if (reference_dir / source.filename).exists()
    }


def load_oracle_references(reference_dir: Path, model: str) -> OracleReferenceSet | None:
    source = ORACLE_REFERENCE_SOURCES.get(model)
    if source is None:
        return None
    path = reference_dir / source.filename
    if not path.exists():
        return None
    rows = _read_rows(path)
    if not rows:
        return None
    if model == "K36":
        populations = _parse_k36_rows(rows)
    elif model == "HarappaWorld":
        populations = _parse_harappa_rows(rows)
    elif model in {"K7b", "K12b"}:
        populations = _parse_source_n_rows(rows)
    elif model == "K13":
        populations = _parse_k13_rows(rows)
    else:
        populations = ()
    return OracleReferenceSet(source=source, populations=populations)


def similar_populations(
    payload: dict[str, object],
    reference_set: OracleReferenceSet,
    *,
    top: int = 15,
) -> list[OracleMatch]:
    sample = _component_map(payload)
    matches: list[OracleMatch] = []
    for population in reference_set.populations:
        component_keys = set(sample) | set(population.values)
        if not component_keys:
            continue
        distance = math.sqrt(
            sum((sample.get(key, 0.0) - population.values.get(key, 0.0)) ** 2 for key in component_keys)
        )
        matches.append(
            OracleMatch(
                population=population.name,
                source=population.source,
                distance=round(distance, 4),
            )
        )
    return sorted(matches, key=lambda item: (item.distance, item.population))[:top]


def two_way_oracle_mixes(
    payload: dict[str, object],
    reference_set: OracleReferenceSet,
    *,
    candidate_limit: int = 40,
    step: int = 5,
    top: int = 15,
) -> list[OracleMixMatch]:
    sample = _component_map(payload)
    if not sample:
        return []
    candidate_names = {
        match.population
        for match in similar_populations(payload, reference_set, top=candidate_limit)
    }
    candidates = [population for population in reference_set.populations if population.name in candidate_names]
    matches: list[OracleMixMatch] = []
    for left_index, left in enumerate(candidates):
        for right in candidates[left_index + 1:]:
            best_distance: float | None = None
            best_percent = 50
            for percent in range(step, 100, step):
                weight = percent / 100.0
                component_keys = set(sample) | set(left.values) | set(right.values)
                distance = math.sqrt(
                    sum(
                        (
                            sample.get(key, 0.0)
                            - (left.values.get(key, 0.0) * weight + right.values.get(key, 0.0) * (1.0 - weight))
                        )
                        ** 2
                        for key in component_keys
                    )
                )
                if best_distance is None or distance < best_distance:
                    best_distance = distance
                    best_percent = percent
            if best_distance is None:
                continue
            matches.append(
                OracleMixMatch(
                    populations=(left.name, right.name),
                    sources=(left.source, right.source),
                    percents=(best_percent, 100 - best_percent),
                    distance=round(best_distance, 4),
                )
            )
    return sorted(
        matches,
        key=lambda item: (item.distance, item.populations),
    )[:top]


def three_way_oracle_mixes(
    payload: dict[str, object],
    reference_set: OracleReferenceSet,
    *,
    candidate_limit: int = 18,
    step: int = 10,
    top: int = 15,
) -> list[OracleMixMatch]:
    sample = _component_map(payload)
    if not sample:
        return []
    candidate_names = {
        match.population
        for match in similar_populations(payload, reference_set, top=candidate_limit)
    }
    candidates = [population for population in reference_set.populations if population.name in candidate_names]
    matches: list[OracleMixMatch] = []
    for left_index, left in enumerate(candidates):
        for middle_index in range(left_index + 1, len(candidates)):
            middle = candidates[middle_index]
            for right in candidates[middle_index + 1:]:
                best_distance: float | None = None
                best_percents = (40, 30, 30)
                for left_percent in range(step, 100, step):
                    for middle_percent in range(step, 100 - left_percent, step):
                        right_percent = 100 - left_percent - middle_percent
                        if right_percent <= 0:
                            continue
                        weights = (left_percent / 100.0, middle_percent / 100.0, right_percent / 100.0)
                        component_keys = set(sample) | set(left.values) | set(middle.values) | set(right.values)
                        distance = math.sqrt(
                            sum(
                                (
                                    sample.get(key, 0.0)
                                    - (
                                        left.values.get(key, 0.0) * weights[0]
                                        + middle.values.get(key, 0.0) * weights[1]
                                        + right.values.get(key, 0.0) * weights[2]
                                    )
                                )
                                ** 2
                                for key in component_keys
                            )
                        )
                        if best_distance is None or distance < best_distance:
                            best_distance = distance
                            best_percents = (left_percent, middle_percent, right_percent)
                if best_distance is None:
                    continue
                matches.append(
                    OracleMixMatch(
                        populations=(left.name, middle.name, right.name),
                        sources=(left.source, middle.source, right.source),
                        percents=best_percents,
                        distance=round(best_distance, 4),
                    )
                )
    return sorted(
        matches,
        key=lambda item: (item.distance, item.populations),
    )[:top]


def _parse_k13_rows(rows: list[list[str]]) -> tuple[OraclePopulation, ...]:
    headers = rows[0][1:]
    populations: list[OraclePopulation] = []
    for row in rows[1:]:
        if len(row) < len(headers) + 1 or not row[0].strip():
            continue
        populations.append(
            OraclePopulation(
                name=row[0].strip(),
                source="",
                values=_values_from_columns(headers, row[1:]),
            )
        )
    return tuple(populations)


def _parse_source_n_rows(rows: list[list[str]]) -> tuple[OraclePopulation, ...]:
    headers = rows[0][3:]
    populations: list[OraclePopulation] = []
    for row in rows[1:]:
        if len(row) < len(headers) + 3 or not row[0].strip():
            continue
        populations.append(
            OraclePopulation(
                name=row[0].strip(),
                source=row[1].strip(),
                values=_values_from_columns(headers, row[3:]),
            )
        )
    return tuple(populations)


def _parse_harappa_rows(rows: list[list[str]]) -> tuple[OraclePopulation, ...]:
    component_names = [name for name, _zh in admix_models.populations("HarappaWorld")]
    populations: list[OraclePopulation] = []
    for row in rows[2:]:
        if len(row) < len(component_names) + 3 or not row[0].strip():
            continue
        populations.append(
            OraclePopulation(
                name=row[0].strip(),
                source=row[1].strip(),
                values=_values_from_columns(component_names, row[3:]),
            )
        )
    return tuple(populations)


def _parse_k36_rows(rows: list[list[str]]) -> tuple[OraclePopulation, ...]:
    populations: list[OraclePopulation] = []
    for row in rows:
        if len(row) < len(K36_COMPONENTS) + 1 or not row[0].strip():
            continue
        populations.append(
            OraclePopulation(
                name=row[0].strip(),
                source="unofficial",
                values=_values_from_columns(K36_COMPONENTS, row[1:]),
            )
        )
    return tuple(populations)


def _values_from_columns(headers: list[str] | tuple[str, ...], cells: list[str]) -> dict[str, float]:
    result: dict[str, float] = {}
    for header, cell in zip(headers, cells):
        key = _component_key(header)
        if not key:
            continue
        result[key] = _float(cell)
    return result


def _component_map(payload: dict[str, object]) -> dict[str, float]:
    result: dict[str, float] = {}
    for item in payload.get("components") or []:
        if not isinstance(item, dict):
            continue
        key = _component_key(str(item.get("name") or ""))
        if not key:
            continue
        result[key] = _float(item.get("value"))
    return result


def _component_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.strip().lower())


def _float(value: object) -> float:
    text = str(value or "0").strip().replace("%", "")
    if not text:
        return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def _read_rows(path: Path) -> list[list[str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [row for row in csv.reader(handle) if any(cell.strip() for cell in row)]
