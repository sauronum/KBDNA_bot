from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def _empty_groups() -> list[dict[str, object]]:
    return [
        {
            "key": "karachay",
            "label": "Къарачай",
            "subtitle": "Карачаевские роды",
            "names": [],
            "confirm_names": [],
        },
        {
            "key": "malkar",
            "label": "Малкьар",
            "subtitle": "Малкъар, Бабугент, Къашхатау, Жемтала, Ташлы-Тала",
            "names": [],
            "confirm_names": [],
        },
        {
            "key": "chegem",
            "label": "Чегем",
            "subtitle": "Чегем, Кёнделен, Быллым",
            "names": [],
            "confirm_names": [],
        },
        {
            "key": "holam",
            "label": "Холам Бызынгы Басхан",
            "subtitle": "Холам, Бызынгы, Басхан",
            "names": [],
            "confirm_names": [],
        },
    ]


_CACHE: dict[Path, list[dict[str, object]]] = {}


def clear_untested_surname_cache() -> None:
    _CACHE.clear()


def load_untested_surname_groups(path: Path = Path("untested_surnames.txt")) -> list[dict[str, object]]:
    cache_key = Path(path)
    if cache_key in _CACHE:
        return _CACHE[cache_key]

    groups = _empty_groups()
    by_key = {str(item["key"]): item for item in groups}
    current_key: str | None = None
    confirm_block = False

    try:
        lines = cache_key.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        logger.warning("Untested surnames file is not available: %s", cache_key)
        _CACHE[cache_key] = groups
        return groups

    for raw_line in lines:
        line = " ".join(raw_line.split())
        if not line:
            continue
        if line.startswith("Список карачаевских"):
            current_key = "karachay"
            confirm_block = False
            continue
        if line.startswith("Список непротестированных балкарских фамилий"):
            if "Чегем" in line:
                current_key = "chegem"
            elif "Холам" in line:
                current_key = "holam"
            else:
                current_key = "malkar"
            confirm_block = False
            continue
        if line.startswith("Фамилии, наличие которых"):
            confirm_block = True
            continue
        if current_key is None:
            continue
        bucket = "confirm_names" if confirm_block else "names"
        by_key[current_key][bucket].append(line)

    _CACHE[cache_key] = groups
    return groups
