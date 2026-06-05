from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from g25_core.g25_engine import (
    K36_COMPONENTS,
    infer_admix_vendor_candidates,
    parse_k36_horizontal,
    parse_raw_dna,
    resolve_admix_binary,
)


@dataclass(frozen=True)
class AdmixtureComponent:
    name: str
    value: float


@dataclass(frozen=True)
class AdmixtureMacroGroup:
    name: str
    value: float
    components: tuple[AdmixtureComponent, ...]


@dataclass(frozen=True)
class AdmixtureProfile:
    sample_name: str
    model: str
    total: float
    components: tuple[AdmixtureComponent, ...]
    top_components: tuple[AdmixtureComponent, ...]
    macro_groups: tuple[AdmixtureMacroGroup, ...]


K36_MACRO_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "North / Central / East Europe",
        (
            "North_Atlantic",
            "North_Sea",
            "Central_Euro",
            "East_Central_Euro",
            "Eastern_Euro",
            "Fennoscandian",
            "Volga-Ural",
            "French",
            "Iberian",
            "Basque",
        ),
    ),
    (
        "Mediterranean / Balkans",
        (
            "West_Med",
            "East_Med",
            "Italian",
            "East_Balkan",
        ),
    ),
    (
        "Caucasus / West Asia",
        (
            "Armenian",
            "North_Caucasian",
            "West_Caucasian",
            "Near_Eastern",
        ),
    ),
    (
        "Arabian / North-East Africa",
        (
            "Arabian",
            "North_African",
            "Northeast_African",
        ),
    ),
    (
        "Central / South Asia",
        (
            "East_Central_Asian",
            "South_Asian",
            "South_Central_Asian",
            "Siberian",
        ),
    ),
    (
        "East / South-East Asia",
        (
            "East_Asian",
            "South_Chinese",
            "Indo-Chinese",
            "Malayan",
        ),
    ),
    (
        "Sub-Saharan Africa",
        (
            "Central_African",
            "East_African",
            "West_African",
            "Omotic",
            "Pygmy",
        ),
    ),
    (
        "Americas / Oceania",
        (
            "Amerindian",
            "Oceanian",
        ),
    ),
)


def build_k36_profile(coordinate_line: str, *, sample_name: str | None = None, top: int = 8) -> AdmixtureProfile:
    parsed = parse_k36_horizontal([coordinate_line], sample_name)
    if parsed is None:
        raise ValueError("Expected a K36 row: sample name and 36 numeric components.")

    parsed_name, values = parsed
    if len(values) != len(K36_COMPONENTS):
        raise ValueError(f"Expected 36 K36 components, got {len(values)}.")

    components = tuple(
        AdmixtureComponent(name=name, value=round(float(value), 6))
        for name, value in zip(K36_COMPONENTS, values)
    )
    top_components = tuple(
        sorted(components, key=lambda item: item.value, reverse=True)[:top]
    )
    macro_groups = tuple(
        sorted(
            (
                _build_macro_group(title, component_names, components)
                for title, component_names in K36_MACRO_GROUPS
            ),
            key=lambda item: item.value,
            reverse=True,
        )
    )
    return AdmixtureProfile(
        sample_name=parsed_name,
        model="K36",
        total=round(sum(values), 6),
        components=components,
        top_components=top_components,
        macro_groups=macro_groups,
    )


def profile_to_payload(profile: AdmixtureProfile) -> dict[str, object]:
    return {
        "sample_name": profile.sample_name,
        "model": profile.model,
        "total": profile.total,
        "components": [
            {"name": item.name, "value": item.value}
            for item in profile.components
        ],
        "top_components": [
            {"name": item.name, "value": item.value}
            for item in profile.top_components
        ],
        "macro_groups": [
            {
                "name": item.name,
                "value": item.value,
                "components": [
                    {"name": component.name, "value": component.value}
                    for component in item.components
                ],
            }
            for item in profile.macro_groups
        ],
    }


def _build_macro_group(
    title: str,
    component_names: tuple[str, ...],
    components: tuple[AdmixtureComponent, ...],
) -> AdmixtureMacroGroup:
    by_name = {item.name: item for item in components}
    grouped = tuple(by_name[name] for name in component_names if name in by_name)
    return AdmixtureMacroGroup(
        name=title,
        value=round(sum(item.value for item in grouped), 6),
        components=tuple(sorted(grouped, key=lambda item: item.value, reverse=True)),
    )


def run_raw_admixture_model(
    input_path: Path,
    *,
    model: str,
    sample_name: str,
    run_dir: Path,
) -> dict[str, object]:
    summary, _calls = parse_raw_dna(input_path)
    vendor_candidates = infer_admix_vendor_candidates(summary, input_path)
    admix_binary = resolve_admix_binary()
    attempts: list[dict[str, object]] = []

    for vendor in vendor_candidates:
        output_path = run_dir / f"admix_{model}_{vendor}.txt"
        command = [str(admix_binary), "-f", str(input_path), "-m", model, "-v", vendor, "--ignore-zeros"]
        if admix_binary.suffix.lower() == ".py":
            command = [sys.executable, *command]
        completed = subprocess.run(command, capture_output=True, text=True)
        output_text = completed.stdout or ""
        if completed.stderr:
            output_text = output_text + ("\n" if output_text else "") + completed.stderr
        output_path.write_text(output_text, encoding="utf-8")

        attempt: dict[str, object] = {
            "vendor": vendor,
            "returncode": completed.returncode,
            "output_path": str(output_path),
        }
        if completed.returncode != 0:
            attempt["status"] = "command_error"
            attempt["stderr"] = (completed.stderr or "").strip()
            attempts.append(attempt)
            continue

        components = _parse_admix_model_output(output_text, model)
        if not components:
            attempt["status"] = "parse_error"
            attempts.append(attempt)
            continue

        attempts.append({
            **attempt,
            "status": "ok",
            "component_count": len(components),
            "total": round(sum(item["value"] for item in components), 6),
        })
        return _raw_model_payload(
            sample_name=sample_name,
            model=model,
            components=components,
            vendor=vendor,
            output_path=output_path,
            attempts=attempts,
        )

    raise ValueError(
        "Could not get a result for model "
        f"{model}. Checked vendor candidates: {', '.join(vendor_candidates)}."
    )


def _parse_admix_model_output(text: str, model: str) -> list[dict[str, object]]:
    components: list[dict[str, object]] = []
    in_model_block = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            if in_model_block and components:
                break
            continue
        if line == model:
            in_model_block = True
            continue
        if not in_model_block or ":" not in line:
            continue
        name, percent = [part.strip() for part in line.split(":", 1)]
        match = re.search(r"-?\d+(?:\.\d+)?", percent)
        if match is None:
            continue
        components.append({"name": name, "value": round(float(match.group(0)), 6)})
    return components


def _raw_model_payload(
    *,
    sample_name: str,
    model: str,
    components: list[dict[str, object]],
    vendor: str,
    output_path: Path,
    attempts: list[dict[str, object]],
) -> dict[str, object]:
    ranked = sorted(components, key=lambda item: float(item["value"]), reverse=True)
    return {
        "sample_name": sample_name,
        "model": model,
        "total": round(sum(float(item["value"]) for item in components), 6),
        "components": components,
        "top_components": ranked[:8],
        "macro_groups": [],
        "vendor": vendor,
        "output_path": str(output_path),
        "attempts": attempts,
    }


def compare_admixture_payloads(
    left_payload: dict[str, object],
    right_payload: dict[str, object],
    *,
    top: int = 12,
) -> dict[str, object]:
    left_components = _component_map(left_payload)
    right_components = _component_map(right_payload)
    names = sorted(set(left_components) | set(right_components))
    differences = [
        {
            "name": name,
            "left": round(left_components.get(name, 0.0), 6),
            "right": round(right_components.get(name, 0.0), 6),
            "delta": round(left_components.get(name, 0.0) - right_components.get(name, 0.0), 6),
            "abs_delta": round(abs(left_components.get(name, 0.0) - right_components.get(name, 0.0)), 6),
        }
        for name in names
    ]
    differences.sort(key=lambda item: (float(item["abs_delta"]), item["name"]), reverse=True)
    distance = sum(float(item["abs_delta"]) for item in differences)
    return {
        "model": str(left_payload.get("model") or right_payload.get("model") or "Admixture"),
        "component_count": len(names),
        "total_absolute_difference": round(distance, 6),
        "average_absolute_difference": round(distance / len(names), 6) if names else 0.0,
        "differences": differences[:top],
    }


def _component_map(payload: dict[str, object]) -> dict[str, float]:
    result: dict[str, float] = {}
    for item in payload.get("components") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        try:
            result[name] = float(item.get("value") or 0.0)
        except (TypeError, ValueError):
            result[name] = 0.0
    return result
