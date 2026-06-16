from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)

_ROOT_DIR = Path(__file__).resolve().parents[3]
_READY_MODELS_PATH = _ROOT_DIR / "data" / "vahaduo" / "ready_models.json"
_PANELS_DIR = _ROOT_DIR / "g25_core" / "panels"
_VALID_STATUSES = {"ready", "draft"}
_VALID_TYPES = {"g25_source_fit"}


@dataclass(frozen=True)
class ReadyModelSource:
    label: str
    emoji: str
    g25_name: str
    source_path: str = ""


@dataclass(frozen=True)
class ReadyModelSet:
    id: str
    title: str
    short_title: str
    status: str
    type: str
    description: str
    interpretation_note: str
    sources: tuple[ReadyModelSource, ...]
    space: str = "G25"


def load_source_sets(path: Path | None = None) -> list[ReadyModelSet]:
    source_path = path or _READY_MODELS_PATH
    try:
        payload = json.loads(source_path.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("Could not load Vahaduo ready models from %s", source_path)
        return []

    try:
        return _parse_source_sets(payload)
    except Exception:
        logger.exception("Invalid Vahaduo ready models in %s", source_path)
        return []


def list_source_sets() -> list[ReadyModelSet]:
    return load_source_sets()


def list_runnable_source_sets() -> list[ReadyModelSet]:
    return [source_set for source_set in list_source_sets() if source_set_is_runnable(source_set)]


def get_source_set(set_id: str) -> ReadyModelSet | None:
    normalized = str(set_id or "").strip()
    for source_set in list_source_sets():
        if source_set.id == normalized:
            return source_set
    return None


def source_set_is_runnable(source_set: ReadyModelSet | None) -> bool:
    if (
        source_set is None
        or source_set.status != "ready"
        or source_set.type not in _VALID_TYPES
        or not source_set.sources
    ):
        return False
    return all(_catalog_source_path_exists(source.source_path) for source in source_set.sources)


def _catalog_source_path_exists(source_path: str) -> bool:
    candidate = _resolve_catalog_source_path(source_path)
    return bool(candidate and candidate.is_file())


def _resolve_catalog_source_path(source_path: str) -> Path | None:
    cleaned = str(source_path or "").replace("\\", "/").strip().lstrip("/")
    if not cleaned:
        return None
    candidate = (_PANELS_DIR / cleaned).resolve()
    panels_root = _PANELS_DIR.resolve()
    if candidate == panels_root or panels_root not in candidate.parents:
        return None
    return candidate


def _parse_source_sets(payload: Any) -> list[ReadyModelSet]:
    if not isinstance(payload, dict):
        raise ValueError("source_sets payload must be an object")
    if int(payload.get("version") or 0) <= 0:
        raise ValueError("source_sets payload needs version")
    raw_sets = payload.get("sets")
    if not isinstance(raw_sets, list):
        raise ValueError("source_sets payload needs sets list")
    space = str(payload.get("space") or "G25").strip() or "G25"

    seen: set[str] = set()
    items: list[ReadyModelSet] = []
    for raw_item in raw_sets:
        if not isinstance(raw_item, dict):
            raise ValueError("source set must be an object")
        item_id = _required_str(raw_item, "id")
        if item_id in seen:
            raise ValueError(f"duplicate source set id: {item_id}")
        seen.add(item_id)

        status = _required_str(raw_item, "status")
        if status not in _VALID_STATUSES:
            raise ValueError(f"invalid source set status: {status}")
        item_type = _required_str(raw_item, "type")
        if item_type not in _VALID_TYPES:
            raise ValueError(f"invalid source set type: {item_type}")

        raw_sources = raw_item.get("sources")
        if not isinstance(raw_sources, list) or not raw_sources:
            raise ValueError(f"source set {item_id} needs sources")
        sources = tuple(_parse_source(source) for source in raw_sources)

        items.append(
            ReadyModelSet(
                id=item_id,
                title=_required_str(raw_item, "title"),
                short_title=str(raw_item.get("short_title") or raw_item.get("title") or item_id).strip(),
                status=status,
                type=item_type,
                description=_required_str(raw_item, "description"),
                interpretation_note=_required_str(raw_item, "interpretation_note"),
                sources=sources,
                space=str(raw_item.get("space") or space).strip() or space,
            )
        )
    return items


def _parse_source(payload: Any) -> ReadyModelSource:
    if not isinstance(payload, dict):
        raise ValueError("source must be an object")
    return ReadyModelSource(
        label=_required_str(payload, "label"),
        emoji=_required_str(payload, "emoji"),
        g25_name=_required_str(payload, "g25_name"),
        source_path=str(payload.get("source_path") or "").strip(),
    )


def _required_str(payload: dict[str, Any], key: str) -> str:
    value = str(payload.get(key) or "").strip()
    if not value:
        raise ValueError(f"missing required field: {key}")
    return value
