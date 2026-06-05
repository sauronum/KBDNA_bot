from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from g25_core import g25_engine

from .ready_model_sets import ReadyModelSet


logger = logging.getLogger(__name__)

_ROOT_DIR = Path(__file__).resolve().parents[3]
_PANELS_DIR = _ROOT_DIR / "g25_core" / "panels"
_SOURCE_DIRS = (
    _PANELS_DIR / "custom_sources",
    _PANELS_DIR / "panel2_sources",
)
_SOURCE_ALIASES = {
    "Steppe": "Steppe_Sintashta",
    "Sintashta": "Steppe_Sintashta",
    "YR": "YellowRiver",
    "Yellow_River": "YellowRiver",
    "Angara_River": "AngaraRiver",
}


@dataclass(frozen=True)
class SourceFitComponent:
    label: str
    emoji: str
    source_name: str
    percent: float


@dataclass(frozen=True)
class SourceFitResult:
    status: str
    target_name: str
    source_set_id: str
    source_set_title: str
    distance: float | None = None
    components: tuple[SourceFitComponent, ...] = ()
    missing_sources: tuple[str, ...] = ()
    message: str = ""


def format_fit_quality(distance: float | None) -> str:
    if distance is None:
        return "неизвестно"
    if distance <= 0.0200:
        return "хороший"
    if distance <= 0.0300:
        return "средний"
    return "слабый"


def run_source_fitting(target_name: str, target_g25: str, source_set: ReadyModelSet) -> SourceFitResult:
    target_name = target_name.strip() or "G25-профиль"
    if source_set.status != "ready":
        return SourceFitResult(
            status="draft",
            target_name=target_name,
            source_set_id=source_set.id,
            source_set_title=source_set.short_title,
            message="Эта модель пока в черновике.",
        )

    source_paths = _resolve_source_paths(source_set)
    missing = tuple(source.g25_name for source, path in source_paths if path is None)
    if missing:
        logger.warning("Vahaduo ready model %s has missing sources: %s", source_set.id, ", ".join(missing))
        return SourceFitResult(
            status="source_missing",
            target_name=target_name,
            source_set_id=source_set.id,
            source_set_title=source_set.short_title,
            missing_sources=missing,
            message="Не найдены источники.",
        )

    try:
        target = g25_engine.parse_g25_line(target_g25)
        references: list[g25_engine.G25Entry] = []
        manifest: dict[str, dict[str, str]] = {}
        source_by_name = {source.g25_name: source for source in source_set.sources}
        for source, path in source_paths:
            entries = g25_engine.load_g25_entries(path)  # type: ignore[arg-type]
            references.extend(entries)
            for entry in entries:
                manifest[entry.name] = {
                    "group": source.g25_name,
                    "panel_name": source_set.short_title,
                }
        if not references:
            return SourceFitResult(
                status="source_missing",
                target_name=target_name,
                source_set_id=source_set.id,
                source_set_title=source_set.short_title,
                missing_sources=tuple(source.g25_name for source in source_set.sources),
                message="В источниках нет G25-строк.",
            )

        fit = g25_engine.summarize_panel_fit(target, references, manifest, "group", 250, 12)
        components: list[SourceFitComponent] = []
        for source_name, weight in dict(fit.get("groups") or {}).items():
            source = source_by_name.get(str(source_name))
            if source is None:
                continue
            components.append(
                SourceFitComponent(
                    label=source.label,
                    emoji=source.emoji,
                    source_name=source.g25_name,
                    percent=round(float(weight) * 100.0, 1),
                )
            )
        return SourceFitResult(
            status="ok",
            target_name=target_name,
            source_set_id=source_set.id,
            source_set_title=source_set.short_title,
            distance=float(fit["distance"]),
            components=tuple(components),
        )
    except Exception as exc:
        logger.exception("Vahaduo ready model fit failed for %s", source_set.id)
        return SourceFitResult(
            status="fit_failed",
            target_name=target_name,
            source_set_id=source_set.id,
            source_set_title=source_set.short_title,
            message=str(exc) or "Не удалось рассчитать модель.",
        )


def _resolve_source_paths(source_set: ReadyModelSet) -> list[tuple[object, Path | None]]:
    return [(source, _find_source_path(source.g25_name)) for source in source_set.sources]


def _find_source_path(source_name: str) -> Path | None:
    candidates = [source_name, _SOURCE_ALIASES.get(source_name, "")]
    for candidate in candidates:
        if not candidate:
            continue
        for directory in _SOURCE_DIRS:
            path = directory / f"{candidate}.txt"
            if path.exists():
                return path
    return None
