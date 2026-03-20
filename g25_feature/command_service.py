from __future__ import annotations

import gzip
import re
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from . import g25_engine
from .bridge import analyze_raw_to_g25, panel_fit_target
from .render_fit_png import render_png
from .render_fit_svg import display_name, group_sort_key, render_svg


G25_NUMBER_RE = re.compile(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")
COMMAND_RE = re.compile(r"^/(?P<command>steppe|g25|[34])(?:@\w+)?(?:\s+(?P<body>.*))?$", re.I | re.S)
PANEL_DIR = Path(__file__).resolve().parent / "panels"
RUNS_DIR = Path(__file__).resolve().parent / "runs"

GROUP_EMOJI_ALIASES = {
    "Maikop": "\U0001F3D4\uFE0F",
    "KuraAraxes": "\U0001F3D4\uFE0F",
    "Steppe": "\U0001F40E",
    "Yamnaya": "\U0001F40E",
    "Anatolia_BA": "\U0001F3FA",
    "Baltic_BA": "\U0001F332",
    "Afanasievo": "\U0001F40E",
    "Khovsgol": "\U0001F3F9",
    "AngaraRiver_BA": "\U0001F3F9",
    "Ulaanzukh": "\U0001F3F9",
    "YellowRiver": "\u26E9\uFE0F",
    "YR": "\u26E9\uFE0F",
    "BMAK": "\u2600\uFE0F",
}


def group_emoji(raw_name: str) -> str:
    normalized = raw_name[: -len("_Cluster")] if raw_name.endswith("_Cluster") else raw_name
    return GROUP_EMOJI_ALIASES.get(normalized, "")


class G25CommandError(Exception):
    pass


@dataclass
class G25RunResult:
    command: str
    panel_name: str
    target_name: str
    distance: float
    sources: int
    iterations: int
    elapsed_seconds: float
    groups: list[tuple[str, float]]
    png_path: Path
    svg_path: Path
    json_path: Path
    input_mode: str
    simulated_g25_line: str | None = None

    @property
    def summary_text(self) -> str:
        lines = [
            f"{self.panel_name} model",
            f"Target: {self.target_name}",
            f"Distance: {self.distance * 100:.4f}% / {self.distance:.7f}",
            f"Sources: {self.sources} | Cycles: {self.iterations} | Time: {self.elapsed_seconds:.3f} s",
            "",
        ]
        for name, weight in self.groups:
            percent = weight * 100.0
            emoji = group_emoji(name)
            prefix = f"{emoji} " if emoji else ""
            lines.append(f"{prefix}{percent:.1f}%  {display_name(name)}")
        return "\n".join(lines)


@dataclass
class G25CoordinatesResult:
    target_name: str
    simulated_g25_line: str
    input_mode: str


class G25CommandService:
    def __init__(self, root_dir: Path | str | None = None) -> None:
        self.root_dir = Path(root_dir) if root_dir else Path(__file__).resolve().parent
        self.panel_dir = self.root_dir / "panels"
        self.runs_dir = self.root_dir / "runs"
        self.panel_configs = {
            "3": {
                "label": "3-way",
                "references_path": self.panel_dir / "3-way.txt",
                "manifest_path": self.panel_dir / "3-way_manifest.tsv",
            },
            "4": {
                "label": "4-way",
                "references_path": self.panel_dir / "4-way.txt",
                "manifest_path": self.panel_dir / "4-way_manifest.tsv",
            },
            "steppe": {
                "label": "Steppe",
                "references_path": self.panel_dir / "steppe.txt",
                "manifest_path": self.panel_dir / "steppe_manifest.tsv",
            },
        }
        self._ensure_manifests()

    @staticmethod
    def extract_command_payload(text: str | None) -> tuple[str, str] | None:
        if not text:
            return None
        match = COMMAND_RE.match(text.strip())
        if not match:
            return None
        return match.group("command").lower(), (match.group("body") or "").strip()

    def build_usage_hint(self, command: str) -> str:
        return (
            f"Отправьте /{command} и сразу приложите raw-файл или G25-координаты в этом же сообщении."
        )

    def create_run_dir(self, command: str, sample_name: str) -> Path:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        slug = g25_engine.safe_ascii_slug(sample_name)
        run_dir = self.runs_dir / f"{timestamp}_{command}_{slug}"
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir

    def run_from_text(self, command: str, body: str, sample_name: str) -> G25RunResult:
        if command not in self.panel_configs:
            raise G25CommandError("Неизвестная модель.")
        if not body.strip():
            raise G25CommandError(self.build_usage_hint(command))

        run_dir = self.create_run_dir(command, sample_name)
        g25_line, target_name = self._parse_g25_input(body, sample_name)
        target_path = run_dir / "target.g25"
        target_path.write_text(g25_line + "\n", encoding="utf-8")
        return self._run_panel(command, target_path, run_dir, "g25-text", g25_line, target_name)

    def run_from_file(self, command: str, input_path: Path | str, sample_name: str) -> G25RunResult:
        if command not in self.panel_configs:
            raise G25CommandError("Неизвестная модель.")

        input_path = Path(input_path)
        run_dir = self.create_run_dir(command, sample_name)
        working_input = run_dir / input_path.name
        if input_path.resolve() != working_input.resolve():
            working_input.write_bytes(input_path.read_bytes())
        working_input = self._expand_archive_if_needed(working_input, run_dir)

        text = self._read_text_if_possible(working_input)
        if text:
            try:
                g25_line, target_name = self._parse_g25_input(text, sample_name)
            except G25CommandError:
                pass
            else:
                target_path = run_dir / "target.g25"
                target_path.write_text(g25_line + "\n", encoding="utf-8")
                return self._run_panel(command, target_path, run_dir, "g25-file", g25_line, target_name)

        try:
            raw_payload = analyze_raw_to_g25(working_input, run_dir, sample_name=sample_name)
        except FileNotFoundError as exc:
            raise G25CommandError(
                "Для raw-файлов на сервере должен быть установлен admix. "
                "Сейчас можно использовать G25-координаты."
            ) from exc
        except Exception as exc:
            raise G25CommandError(f"Не удалось обработать файл: {exc}") from exc

        target_path = Path(raw_payload["simulated_g25_path"])
        return self._run_panel(
            command,
            target_path,
            run_dir,
            "raw-file",
            raw_payload.get("simulated_g25_line"),
            raw_payload.get("target_name") or sample_name,
        )

    def extract_coordinates_from_text(self, body: str, sample_name: str) -> G25CoordinatesResult:
        if not body.strip():
            raise G25CommandError(self.build_usage_hint("g25"))

        g25_line, target_name = self._parse_g25_input(body, sample_name)
        return G25CoordinatesResult(
            target_name=target_name,
            simulated_g25_line=g25_line,
            input_mode="g25-text",
        )

    def extract_coordinates_from_file(self, input_path: Path | str, sample_name: str) -> G25CoordinatesResult:
        input_path = Path(input_path)
        run_dir = self.create_run_dir("g25", sample_name)
        working_input = run_dir / input_path.name
        if input_path.resolve() != working_input.resolve():
            working_input.write_bytes(input_path.read_bytes())
        working_input = self._expand_archive_if_needed(working_input, run_dir)

        text = self._read_text_if_possible(working_input)
        if text:
            try:
                g25_line, target_name = self._parse_g25_input(text, sample_name)
            except G25CommandError:
                pass
            else:
                return G25CoordinatesResult(
                    target_name=target_name,
                    simulated_g25_line=g25_line,
                    input_mode="g25-file",
                )

        try:
            raw_payload = analyze_raw_to_g25(working_input, run_dir, sample_name=sample_name)
        except FileNotFoundError as exc:
            raise G25CommandError(
                "??? raw-?????? ?? ??????? ?????? ???? ?????????? admix. ?????? ????? ???????????? G25-??????????."
            ) from exc
        except Exception as exc:
            raise G25CommandError(f"?? ??????? ?????????? ????: {exc}") from exc

        g25_line = str(raw_payload.get("simulated_g25_line", "")).strip()
        if not g25_line:
            raise G25CommandError("?? ??????? ??????? G25-?????????? ?? ?????.")

        return G25CoordinatesResult(
            target_name=str(raw_payload.get("target_name") or sample_name),
            simulated_g25_line=g25_line,
            input_mode="raw-file",
        )

    def _expand_archive_if_needed(self, input_path: Path, run_dir: Path) -> Path:
        suffix = input_path.suffix.lower()

        if suffix == ".gz":
            extracted_name = input_path.stem or "extracted_input"
            extracted_path = run_dir / extracted_name
            with gzip.open(input_path, "rb") as src, extracted_path.open("wb") as dst:
                dst.write(src.read())
            return extracted_path

        if suffix == ".zip":
            with zipfile.ZipFile(input_path) as archive:
                file_names = [name for name in archive.namelist() if not name.endswith("/")]
                if not file_names:
                    raise G25CommandError("Архив пустой. Пришлите raw-файл или G25-координаты.")

                member_name = sorted(file_names, key=self._archive_member_priority)[0]
                extracted_name = Path(member_name).name or "extracted_input"
                extracted_path = run_dir / extracted_name
                with archive.open(member_name) as src, extracted_path.open("wb") as dst:
                    dst.write(src.read())
                return extracted_path

        return input_path

    @staticmethod
    def _archive_member_priority(member_name: str) -> tuple[int, str]:
        suffix = Path(member_name).suffix.lower()
        rank = {
            ".csv": 0,
            ".txt": 1,
            ".g25": 2,
            ".tsv": 3,
        }.get(suffix, 9)
        return (rank, member_name.lower())

    def _run_panel(
        self,
        command: str,
        target_path: Path,
        run_dir: Path,
        input_mode: str,
        simulated_g25_line: str | None,
        target_name: str,
    ) -> G25RunResult:
        config = self.panel_configs[command]
        started_at = time.perf_counter()
        output_json = run_dir / f"{config['label']}_fit.json"
        output_png = run_dir / f"{config['label']}_fit.png"
        output_svg = run_dir / f"{config['label']}_fit.svg"

        payload = panel_fit_target(
            target_g25_path=target_path,
            references_path=config["references_path"],
            manifest_path=config["manifest_path"],
            group_column="group",
            iterations=250,
            top_references=12,
            output_json_path=output_json,
        )
        group_items = sorted(payload["groups"].items(), key=lambda item: group_sort_key(item[0]))
        render_svg(
            payload["target"],
            float(payload["distance"]),
            int(payload["sources"]),
            group_items,
            output_svg,
        )
        render_png(
            payload["target"],
            float(payload["distance"]),
            int(payload["sources"]),
            group_items,
            output_png,
        )
        elapsed = time.perf_counter() - started_at
        return G25RunResult(
            command=command,
            panel_name=config["label"],
            target_name=target_name,
            distance=float(payload["distance"]),
            sources=int(payload["sources"]),
            iterations=int(payload["iterations"]),
            elapsed_seconds=elapsed,
            groups=[(name, float(value)) for name, value in group_items],
            png_path=output_png,
            svg_path=output_svg,
            json_path=output_json,
            input_mode=input_mode,
            simulated_g25_line=simulated_g25_line,
        )

    def _ensure_manifests(self) -> None:
        for config in self.panel_configs.values():
            references_path = config["references_path"]
            manifest_path = config["manifest_path"]
            if (
                manifest_path.exists()
                and manifest_path.stat().st_mtime >= references_path.stat().st_mtime
            ):
                continue
            self._build_manifest(references_path, manifest_path, config["label"])

    @staticmethod
    def _build_manifest(references_path: Path, manifest_path: Path, panel_name: str) -> None:
        references = g25_engine.load_g25_entries(references_path)
        lines = ["standard_name\tgroup\tpanel_name"]
        for reference in references:
            group = G25CommandService._extract_group_name(reference.name)
            lines.append(f"{reference.name}\t{group}\t{panel_name}")
        manifest_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    @staticmethod
    def _extract_group_name(reference_name: str) -> str:
        head, sep, _ = reference_name.partition(":")
        return head.strip() if sep else reference_name.strip()

    @staticmethod
    def _read_text_if_possible(path: Path) -> str:
        for encoding in ("utf-8-sig", "utf-8", "cp1251", "latin-1"):
            try:
                return path.read_text(encoding=encoding)
            except UnicodeDecodeError:
                continue
        return ""

    @staticmethod
    def _clean_g25_body(text: str) -> str:
        cleaned = text.strip()
        if cleaned.startswith("```") and cleaned.endswith("```"):
            cleaned = cleaned[3:-3].strip()
        cleaned = cleaned.replace("`", "").strip()
        return cleaned

    @classmethod
    def _parse_g25_input(cls, text: str, sample_name: str) -> tuple[str, str]:
        cleaned = cls._clean_g25_body(text)
        if not cleaned:
            raise G25CommandError("Не вижу координат. Отправьте G25-координаты одним сообщением.")

        lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
        for line in lines:
            try:
                parsed = g25_engine.parse_g25_line(line)
            except Exception:
                continue
            return g25_engine.g25_line_from_coords(parsed.name, parsed.coords), parsed.name

        numbers = G25_NUMBER_RE.findall(cleaned)
        if len(numbers) != 25:
            raise G25CommandError(
                "Не удалось распознать G25-координаты. Отправьте 25 координат или raw-файл."
            )

        coords = tuple(float(value) for value in numbers)
        target_name = sample_name.strip() or "Target"
        return g25_engine.g25_line_from_coords(target_name, coords), target_name
