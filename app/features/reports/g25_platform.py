from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import uuid4


DEFAULT_REPORT_TIMEOUT_SECONDS = int(os.getenv("KBDNA_G25_REPORT_TIMEOUT_SECONDS", "600"))
DNA_PLATFORM_ROOT_ENV = "DNA_PLATFORM_ROOT"
DNA_PLATFORM_PYTHON_ENV = "DNA_PLATFORM_PYTHON"


class G25PlatformReportError(RuntimeError):
    pass


@dataclass(frozen=True)
class G25PlatformReport:
    sample_name: str
    coordinate_name: str
    output_dir: Path
    analysis_path: Path
    artifact_paths: tuple[Path, ...]
    summary_lines: tuple[str, ...]
    raw_stdout: str = ""
    raw_stderr: str = ""


def choose_sample_g25_coordinate(store: object, user_id: int, sample: object) -> object | None:
    sample_id = str(getattr(sample, "asset_id", "") or "").strip()
    if not sample_id or not hasattr(store, "list_sample_coordinates"):
        return None
    try:
        coordinates = list(store.list_sample_coordinates(user_id, sample_id))
    except Exception:
        return None
    for item in coordinates:
        if str(getattr(item, "coordinate_type", "") or "").strip().lower() == "g25":
            g25_line = str(getattr(item, "g25_line", "") or "").strip()
            if g25_line:
                return item
    return None


def discover_dna_platform_root() -> Path:
    configured = os.getenv(DNA_PLATFORM_ROOT_ENV, "").strip()
    if configured:
        return Path(configured)

    repo_root = Path(__file__).resolve().parents[3]
    candidates = (
        Path("/srv/dna_platform"),
        repo_root.parent / "dna_platform",
        Path.cwd().parent / "dna_platform",
        Path.cwd() / "dna_platform",
    )
    for candidate in candidates:
        if (candidate / "dna_platform.py").exists():
            return candidate
    return Path("/srv/dna_platform")


async def generate_g25_platform_report(
    *,
    storage_root: Path,
    sample: object,
    coordinate: object,
    user_id: int,
    timeout_seconds: int = DEFAULT_REPORT_TIMEOUT_SECONDS,
) -> G25PlatformReport:
    dna_platform_root = discover_dna_platform_root()
    launcher = dna_platform_root / "dna_platform.py"
    if not launcher.exists():
        raise G25PlatformReportError(f"dna_platform.py not found: {launcher}")

    python_bin = os.getenv(DNA_PLATFORM_PYTHON_ENV, "").strip() or _default_python_for_platform(dna_platform_root)
    sample_name = str(getattr(sample, "display_name", "") or "Sample").strip() or "Sample"
    coordinate_name = str(getattr(coordinate, "display_name", "") or getattr(coordinate, "target_name", "") or "G25").strip() or "G25"
    target_name = str(getattr(coordinate, "target_name", "") or coordinate_name).strip() or coordinate_name
    g25_line = str(getattr(coordinate, "g25_line", "") or "").strip()
    if not g25_line:
        raise G25PlatformReportError("Selected G25 profile is empty")

    run_id = datetime.utcnow().strftime("%Y%m%d%H%M%S") + "-" + uuid4().hex[:8]
    output_dir = storage_root / "g25_platform" / "users" / str(int(user_id)) / run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    input_path = output_dir / "input.g25"
    input_path.write_text(g25_line.rstrip() + "\n", encoding="utf-8")

    args = [
        python_bin,
        str(launcher),
        "analyze",
        str(input_path),
        "--input-kind",
        "g25",
        "--name",
        target_name,
        "--output-dir",
        str(output_dir),
        "--runtime-method",
        "v2-hybrid",
        "--distance-top",
        "12",
    ]

    try:
        process = await asyncio.create_subprocess_exec(
            *args,
            cwd=str(dna_platform_root),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = await asyncio.wait_for(process.communicate(), timeout=timeout_seconds)
    except asyncio.TimeoutError as exc:
        raise G25PlatformReportError(f"dna_platform analyze timed out after {timeout_seconds}s") from exc
    except OSError as exc:
        raise G25PlatformReportError(f"Could not start dna_platform analyze: {exc}") from exc

    stdout = stdout_bytes.decode("utf-8", errors="replace").strip()
    stderr = stderr_bytes.decode("utf-8", errors="replace").strip()
    if process.returncode != 0:
        detail = stderr or stdout or f"exit code {process.returncode}"
        raise G25PlatformReportError(f"dna_platform analyze failed: {detail[:800]}")

    analysis_path = output_dir / "analysis.json"
    if not analysis_path.exists():
        raise G25PlatformReportError("dna_platform did not produce analysis.json")

    try:
        analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise G25PlatformReportError("Could not read dna_platform analysis.json") from exc

    return G25PlatformReport(
        sample_name=sample_name,
        coordinate_name=coordinate_name,
        output_dir=output_dir,
        analysis_path=analysis_path,
        artifact_paths=_artifact_paths(analysis, output_dir),
        summary_lines=tuple(build_report_summary_lines(analysis)),
        raw_stdout=stdout,
        raw_stderr=stderr,
    )


def build_report_summary_lines(analysis: dict[str, object]) -> list[str]:
    routing = _dict(analysis.get("routing"))
    global_routing = _dict(routing.get("global"))
    decision = _dict(routing.get("decision"))

    lines: list[str] = []
    sample_name = str(analysis.get("sample_name") or "").strip()
    if sample_name:
        lines.append(f"Target: {sample_name}")

    modern_macro = _dict(global_routing.get("modern_macro"))
    ancient_macro = _dict(global_routing.get("ancient_macro"))
    _append_value(lines, "Modern macro", modern_macro.get("predicted_group"))
    _append_value(lines, "Ancient macro", ancient_macro.get("predicted_group"))

    selected_regions = _list(decision.get("selected_regions"))
    if selected_regions:
        region_labels = [
            str(_dict(item).get("label") or _dict(item).get("region_id") or "").strip()
            for item in selected_regions[:2]
        ]
        region_labels = [item for item in region_labels if item]
        if region_labels:
            lines.append(f"Region: {', '.join(region_labels)}")

    branch = str(routing.get("selected_backbone_branch") or "").strip()
    regional = _dict(_dict(routing.get("regional_backbone")).get(branch))
    if regional:
        _append_value(lines, "Modern cluster", _dict(regional.get("modern_cluster")).get("predicted_group"))
        _append_value(lines, "Ancient family", _dict(regional.get("ancient_family")).get("predicted_group"))
        _append_value(lines, "Ancient core", _dict(regional.get("ancient_core")).get("predicted_group"))

    nearest = _list(modern_macro.get("nearest"))
    if nearest:
        top = _dict(nearest[0])
        reference = str(top.get("reference") or "").strip()
        distance = _format_distance(top.get("distance"))
        if reference:
            lines.append(f"Nearest modern: {reference}{distance}")

    return lines or ["analysis.json generated"]


def _default_python_for_platform(root: Path) -> str:
    if os.name == "nt":
        candidate = root / ".venv" / "Scripts" / "python.exe"
        return str(candidate) if candidate.exists() else "python"
    candidate = root / ".venv" / "bin" / "python"
    return str(candidate) if candidate.exists() else "python3"


def _artifact_paths(analysis: dict[str, object], output_dir: Path) -> tuple[Path, ...]:
    artifacts = _dict(analysis.get("artifacts"))
    keys = ("backbone_summary_svg", "distance_modern_svg", "distance_ancient_svg")
    paths: list[Path] = []
    for key in keys:
        raw_value = str(artifacts.get(key) or "").strip()
        if not raw_value:
            continue
        path = Path(raw_value)
        if not path.is_absolute():
            path = output_dir / path
        if path.exists() and path.suffix.lower() == ".svg":
            paths.append(path)
    return tuple(paths)


def _append_value(lines: list[str], label: str, value: object) -> None:
    text = str(value or "").strip()
    if text:
        lines.append(f"{label}: {text}")


def _format_distance(value: object) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    return f" ({number:.4f})"


def _dict(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def safe_artifact_filename(path: Path) -> str:
    name = re.sub(r"[^A-Za-z0-9_.-]+", "_", path.name).strip("._")
    return name or "g25_report.svg"
