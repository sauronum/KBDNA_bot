from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Optional

from . import g25_engine
from . import render_fit_svg


DEFAULT_JS_PATH = Path(__file__).resolve().parent / "data" / "support" / "K36vertical.js"


def analyze_raw_to_g25(
    input_path: Path | str,
    output_dir: Path | str,
    sample_name: Optional[str] = None,
    vendor: Optional[str] = None,
    js_path: Optional[Path | str] = None,
) -> dict:
    input_path = Path(input_path)
    output_dir = Path(output_dir)
    sample_name = sample_name or input_path.stem
    sample_slug = g25_engine.safe_ascii_slug(sample_name)
    output_dir.mkdir(parents=True, exist_ok=True)

    raw_summary, _ = g25_engine.parse_raw_dna(input_path)
    raw_summary_path = output_dir / "raw_summary.json"
    g25_engine.write_json_file(raw_summary_path, asdict(raw_summary))

    staged_input = g25_engine.stage_input_for_external_tool(input_path, output_dir, sample_slug)
    vendor_candidates = [vendor] if vendor else g25_engine.infer_admix_vendor_candidates(raw_summary, input_path)
    k36_summary, admix_output_path, selected_vendor, vendor_attempts = g25_engine.run_admix_k36_auto(
        staged_input,
        sample_name,
        output_dir,
        vendor_candidates,
    )

    regression_path = Path(js_path) if js_path else DEFAULT_JS_PATH
    regression = g25_engine.load_k36_regression(regression_path)
    coords = g25_engine.compute_g25_from_k36(k36_summary.values, regression)
    target = g25_engine.G25Entry(name=sample_name, coords=coords)
    g25_line = g25_engine.g25_line_from_coords(sample_name, coords)

    g25_path = output_dir / f"{sample_slug}_simulated_g25.g25"
    g25_path.write_text(g25_line + "\n", encoding="utf-8")

    payload = {
        "sample_name": sample_name,
        "sample_slug": sample_slug,
        "input_path": str(input_path),
        "output_dir": str(output_dir),
        "raw_summary": asdict(raw_summary),
        "raw_summary_path": str(raw_summary_path),
        "staged_input_path": str(staged_input),
        "selected_vendor": selected_vendor,
        "vendor_attempts": vendor_attempts,
        "admix_output_path": str(admix_output_path),
        "k36_summary": asdict(k36_summary),
        "js_path": str(regression_path),
        "simulated_g25_path": str(g25_path),
        "simulated_g25_line": g25_line,
        "target_name": target.name,
        "target_coords": list(target.coords),
    }
    return payload


def route_target(
    target_g25_path: Path | str,
    references_path: Path | str,
    manifest_path: Path | str,
    group_column: str,
    top: int = 12,
    top_groups: int = 5,
    output_json_path: Optional[Path | str] = None,
) -> dict:
    targets = g25_engine.load_g25_entries(Path(target_g25_path))
    if len(targets) != 1:
        raise ValueError("route_target expects exactly one target row.")

    payload = g25_engine.route_single_target(
        targets[0],
        Path(references_path),
        Path(manifest_path),
        group_column,
        top,
        top_groups,
    )
    if output_json_path:
        g25_engine.write_json_file(Path(output_json_path), payload)
    return payload


def panel_fit_target(
    target_g25_path: Path | str,
    references_path: Path | str,
    manifest_path: Path | str,
    group_column: str,
    iterations: int = 250,
    top_references: int = 10,
    output_json_path: Optional[Path | str] = None,
    output_svg_path: Optional[Path | str] = None,
) -> dict:
    targets = g25_engine.load_g25_entries(Path(target_g25_path))
    if len(targets) != 1:
        raise ValueError("panel_fit_target expects exactly one target row.")

    references = g25_engine.load_g25_entries(Path(references_path))
    manifest = g25_engine.load_reference_manifest(Path(manifest_path))
    payload = g25_engine.summarize_panel_fit(
        targets[0],
        references,
        manifest,
        group_column,
        iterations,
        top_references,
    )

    if output_json_path:
        g25_engine.write_json_file(Path(output_json_path), payload)
    if output_svg_path:
        group_items = [(name, value) for name, value in payload["groups"].items()]
        render_fit_svg.render_svg(
            payload["target"],
            float(payload["distance"]),
            int(payload["sources"]),
            group_items,
            Path(output_svg_path),
        )
    return payload
