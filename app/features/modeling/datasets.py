from __future__ import annotations

from typing import Iterator


MODELING_DATASETS: tuple[dict[str, str], ...] = (
    {
        "id": "v62_1240k_public",
        "label": "v62 1240k public",
        "button": "v62 / 1240k public",
    },
    {
        "id": "human_origins",
        "label": "Human Origins",
        "button": "Human Origins",
    },
    {
        "id": "v66p1_1240k_public",
        "label": "v66.p1 1240K public",
        "button": "v66.p1 / 1240K public",
    },
    {
        "id": "v66p1_human_origins",
        "label": "v66.p1 Human Origins",
        "button": "v66.p1 Human Origins",
    },
)

DATASET_LABELS = {item["id"]: item["label"] for item in MODELING_DATASETS}


def dataset_label(dataset: object) -> str:
    value = str(dataset or "")
    return DATASET_LABELS.get(value, value or "not selected")


def dataset_choices() -> Iterator[tuple[str, str]]:
    for item in MODELING_DATASETS:
        yield item["id"], item["button"]
