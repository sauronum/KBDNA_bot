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

CUSTOM_PANEL_SOURCE_DEFS = [
    ("maikop", "Maikop", "Maikop.txt"),
    ("steppe_sintashta", "Steppe Sintashta", "Steppe_Sintashta.txt"),
    ("ulaanzhukh", "Ulaanzhukh", "Ulaanzhukh.txt"),
    ("yamnaya", "Yamnaya", "Yamnaya.txt"),
    ("yellowriver", "Yellow River", "YellowRiver.txt"),
    ("anatolia_ba", "Anatolia BA", "Anatolia_BA.txt"),
    ("baltic_ba", "Baltic BA", "Baltic_BA.txt"),
    ("bmac", "BMAC", "BMAC.txt"),
    ("khovsgol", "Khovsgol", "Khovsgol.txt"),
    ("kuraaraxes", "KuraAraxes", "KuraAraxes.txt"),
]

PANEL2_SOURCE_DEFS = [
    ("ulaanzuukh_culture_ba", "Ulaanzuukh culture BA", "Ulaanzuukh_culture_BA", "Ulaanzuukh_culture_BA.txt"),
    ("khovsgol_ba", "Khovsgol BA", "Khovsgol_BA", "Khovsgol_BA.txt"),
    ("yellow_river_ln", "Yellow River LN", "Yellow_River_LN", "Yellow_River_LN.txt"),
    ("bmac_or_oxus_civilization", "BMAC or Oxus Civilization", "BMAC_or_Oxus_Civilization", "BMAC_or_Oxus_Civilization.txt"),
    ("helmandculture", "Helmandculture", "Helmandculture", "Helmandculture.txt"),
    ("steppe_mlba", "Steppe MLBA", "Steppe_MLBA", "Steppe_MLBA.txt"),
    ("rus_angara_river_ba", "RUS Angara River BA", "RUS_Angara_River_BA", "RUS_Angara_River_BA.txt"),
]

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
    "Ulaanzuukh_culture_BA": "\U0001F43A",
    "Khovsgol_BA": "\U0001F3DE\uFE0F",
    "Yellow_River_LN": "\u26E9\uFE0F",
    "BMAC_or_Oxus_Civilization": "\u2600\uFE0F",
    "Helmandculture": "\U0001F331",
    "Steppe_MLBA": "\U0001F40E",
    "RUS_Angara_River_BA": "\U0001F3F9",
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
        self.custom_sources_dir = self.panel_dir / "custom_sources"
        self.panel2_sources_dir = self.panel_dir / "panel2_sources"
        self.custom_source_defs = [
            {"key": key, "label": label, "file_name": file_name, "path": self.custom_sources_dir / file_name}
            for key, label, file_name in CUSTOM_PANEL_SOURCE_DEFS
        ]
        self.panel2_source_defs = [
            {
                "key": key,
                "label": label,
                "group_name": group_name,
                "file_name": file_name,
                "path": self.panel2_sources_dir / file_name,
                "emoji": group_emoji(group_name),
            }
            for key, label, group_name, file_name in PANEL2_SOURCE_DEFS
        ]
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
            raise G25CommandError(
                "Не удалось обработать файл. Проверьте, что это raw-файл DNA или txt/csv с G25-координатами, "
                "и попробуйте еще раз."
            ) from exc

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

    def extract_coordinates_from_file(
        self,
        input_path: Path | str,
        sample_name: str,
        coordinate_type: str = "g25",
    ) -> G25CoordinatesResult:
        input_path = Path(input_path)
        coordinate_type = coordinate_type.strip().lower() or "g25"
        run_dir = self.create_run_dir(coordinate_type, sample_name)
        working_input = run_dir / input_path.name
        if input_path.resolve() != working_input.resolve():
            working_input.write_bytes(input_path.read_bytes())
        working_input = self._expand_archive_if_needed(working_input, run_dir)

        if coordinate_type == "g25":
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
                "Для raw-файлов на сервере должен быть установлен admix. Сейчас можно использовать G25-координаты."
            ) from exc
        except Exception as exc:
            raise G25CommandError(
                "Не удалось обработать файл. Проверьте, что это raw-файл DNA или txt/csv с координатами, "
                "и попробуйте еще раз."
            ) from exc

        if coordinate_type == "k36":
            k36_summary = raw_payload.get("k36_summary") or {}
            k36_line = str(k36_summary.get("canonical_line") or "").strip()
            if not k36_line:
                raise G25CommandError("Не удалось извлечь K36-координаты из файла.")
            return G25CoordinatesResult(
                target_name=str(k36_summary.get("sample_name") or raw_payload.get("target_name") or sample_name),
                simulated_g25_line=k36_line,
                input_mode="raw-file-k36",
            )

        g25_line = str(raw_payload.get("simulated_g25_line", "")).strip()
        if not g25_line:
            raise G25CommandError("Не удалось извлечь G25-координаты из файла.")

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

    def list_custom_sources(self) -> list[dict[str, Path | str]]:
        return [dict(item) for item in self.custom_source_defs]

    def list_panel2_sources(self) -> list[dict[str, Path | str]]:
        return [dict(item) for item in self.panel2_source_defs]

    def run_custom_from_text(self, selected_keys: list[str], body: str, sample_name: str) -> G25RunResult:
        if not body.strip():
            raise G25CommandError("\u041d\u0435 \u0432\u0438\u0436\u0443 \u0432\u0445\u043e\u0434\u043d\u044b\u0445 \u0434\u0430\u043d\u043d\u044b\u0445. \u041e\u0442\u043f\u0440\u0430\u0432\u044c\u0442\u0435 raw-\u0444\u0430\u0439\u043b \u0438\u043b\u0438 G25-\u043a\u043e\u043e\u0440\u0434\u0438\u043d\u0430\u0442\u044b.")

        run_dir = self.create_run_dir("panel", sample_name)
        references_path, manifest_path, label = self._prepare_custom_panel(selected_keys, run_dir)
        g25_line, target_name = self._parse_g25_input(body, sample_name)
        target_path = run_dir / "target.g25"
        target_path.write_text(g25_line + "\n", encoding="utf-8")
        return self._run_panel_paths(label, references_path, manifest_path, target_path, run_dir, "g25-text", g25_line, target_name, "panel")

    def run_panel2_from_text(self, selected_keys: list[str], body: str, sample_name: str) -> G25RunResult:
        if not body.strip():
            raise G25CommandError("\u041d\u0435 \u0432\u0438\u0436\u0443 \u0432\u0445\u043e\u0434\u043d\u044b\u0445 \u0434\u0430\u043d\u043d\u044b\u0445. \u041e\u0442\u043f\u0440\u0430\u0432\u044c\u0442\u0435 raw-\u0444\u0430\u0439\u043b \u0438\u043b\u0438 G25-\u043a\u043e\u043e\u0440\u0434\u0438\u043d\u0430\u0442\u044b.")

        run_dir = self.create_run_dir("panel2", sample_name)
        references_path, manifest_path, label = self._prepare_panel2(selected_keys, run_dir)
        g25_line, target_name = self._parse_g25_input(body, sample_name)
        target_path = run_dir / "target.g25"
        target_path.write_text(g25_line + "\n", encoding="utf-8")
        return self._run_panel_paths(label, references_path, manifest_path, target_path, run_dir, "g25-text", g25_line, target_name, "panel2")

    def run_custom_from_file(self, selected_keys: list[str], input_path: Path | str, sample_name: str) -> G25RunResult:
        input_path = Path(input_path)
        run_dir = self.create_run_dir("panel", sample_name)
        references_path, manifest_path, label = self._prepare_custom_panel(selected_keys, run_dir)
        working_input = run_dir / input_path.name
        if input_path.resolve() != working_input.resolve():
            working_input.write_bytes(input_path.read_bytes())
        working_input = self._expand_archive_if_needed(working_input, run_dir)

        text_in = self._read_text_if_possible(working_input)
        if text_in:
            try:
                g25_line, target_name = self._parse_g25_input(text_in, sample_name)
            except G25CommandError:
                pass
            else:
                target_path = run_dir / "target.g25"
                target_path.write_text(g25_line + "\n", encoding="utf-8")
                return self._run_panel_paths(label, references_path, manifest_path, target_path, run_dir, "g25-file", g25_line, target_name, "panel")

        try:
            raw_payload = analyze_raw_to_g25(working_input, run_dir, sample_name=sample_name)
        except FileNotFoundError as exc:
            raise G25CommandError("\u0414\u043b\u044f raw-\u0444\u0430\u0439\u043b\u043e\u0432 \u043d\u0430 \u0441\u0435\u0440\u0432\u0435\u0440\u0435 \u0434\u043e\u043b\u0436\u0435\u043d \u0431\u044b\u0442\u044c \u0443\u0441\u0442\u0430\u043d\u043e\u0432\u043b\u0435\u043d admix. \u0421\u0435\u0439\u0447\u0430\u0441 \u043c\u043e\u0436\u043d\u043e \u0438\u0441\u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u044c G25-\u043a\u043e\u043e\u0440\u0434\u0438\u043d\u0430\u0442\u044b.") from exc
        except Exception as exc:
            raise G25CommandError(
                "Не удалось обработать файл. Проверьте, что это raw-файл DNA или txt/csv с G25-координатами, "
                "и попробуйте еще раз."
            ) from exc

        target_path = Path(raw_payload["simulated_g25_path"])
        return self._run_panel_paths(
            label,
            references_path,
            manifest_path,
            target_path,
            run_dir,
            "raw-file",
            raw_payload.get("simulated_g25_line"),
            raw_payload.get("target_name") or sample_name,
            "panel",
        )

    def run_panel2_from_file(self, selected_keys: list[str], input_path: Path | str, sample_name: str) -> G25RunResult:
        input_path = Path(input_path)
        run_dir = self.create_run_dir("panel2", sample_name)
        references_path, manifest_path, label = self._prepare_panel2(selected_keys, run_dir)
        working_input = run_dir / input_path.name
        if input_path.resolve() != working_input.resolve():
            working_input.write_bytes(input_path.read_bytes())
        working_input = self._expand_archive_if_needed(working_input, run_dir)

        text_in = self._read_text_if_possible(working_input)
        if text_in:
            try:
                g25_line, target_name = self._parse_g25_input(text_in, sample_name)
            except G25CommandError:
                pass
            else:
                target_path = run_dir / "target.g25"
                target_path.write_text(g25_line + "\n", encoding="utf-8")
                return self._run_panel_paths(label, references_path, manifest_path, target_path, run_dir, "g25-file", g25_line, target_name, "panel2")

        try:
            raw_payload = analyze_raw_to_g25(working_input, run_dir, sample_name=sample_name)
        except FileNotFoundError as exc:
            raise G25CommandError("\u0414\u043b\u044f raw-\u0444\u0430\u0439\u043b\u043e\u0432 \u043d\u0430 \u0441\u0435\u0440\u0432\u0435\u0440\u0435 \u0434\u043e\u043b\u0436\u0435\u043d \u0431\u044b\u0442\u044c \u0443\u0441\u0442\u0430\u043d\u043e\u0432\u043b\u0435\u043d admix. \u0421\u0435\u0439\u0447\u0430\u0441 \u043c\u043e\u0436\u043d\u043e \u0438\u0441\u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u044c G25-\u043a\u043e\u043e\u0440\u0434\u0438\u043d\u0430\u0442\u044b.") from exc
        except Exception as exc:
            raise G25CommandError(
                "Не удалось обработать файл. Проверьте, что это raw-файл DNA или txt/csv с G25-координатами, "
                "и попробуйте еще раз."
            ) from exc

        target_path = Path(raw_payload["simulated_g25_path"])
        return self._run_panel_paths(
            label,
            references_path,
            manifest_path,
            target_path,
            run_dir,
            "raw-file",
            raw_payload.get("simulated_g25_line"),
            raw_payload.get("target_name") or sample_name,
            "panel2",
        )

    def _prepare_custom_panel(self, selected_keys: list[str], run_dir: Path) -> tuple[Path, Path, str]:
        selected = [item for item in self.custom_source_defs if item["key"] in set(selected_keys)]
        if not selected:
            raise G25CommandError("\u0421\u043d\u0430\u0447\u0430\u043b\u0430 \u0432\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u0445\u043e\u0442\u044f \u0431\u044b \u043e\u0434\u0438\u043d \u0434\u0440\u0435\u0432\u043d\u0438\u0439 \u0438\u0441\u0442\u043e\u0447\u043d\u0438\u043a.")

        missing = [str(item["path"]) for item in selected if not Path(item["path"]).exists()]
        if missing:
            raise G25CommandError("\u041d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d\u044b \u0444\u0430\u0439\u043b\u044b \u043f\u0430\u043d\u0435\u043b\u0438: " + ", ".join(missing))

        references_lines: list[str] = []
        manifest_lines = ["standard_name\tgroup\tpanel_name"]
        panel_label = "Custom panel"

        for item in selected:
            source_path = Path(item["path"])
            source_text = self._read_text_if_possible(source_path).strip()
            if source_text:
                references_lines.extend(line.strip() for line in source_text.splitlines() if line.strip())
            for reference in g25_engine.load_g25_entries(source_path):
                group = self._extract_group_name(reference.name)
                manifest_lines.append(f"{reference.name}\t{group}\t{panel_label}")

        references_path = run_dir / "custom_panel.txt"
        manifest_path = run_dir / "custom_panel_manifest.tsv"
        references_path.write_text("\n".join(references_lines) + "\n", encoding="utf-8")
        manifest_path.write_text("\n".join(manifest_lines) + "\n", encoding="utf-8")
        return references_path, manifest_path, panel_label

    def _prepare_panel2(self, selected_keys: list[str], run_dir: Path) -> tuple[Path, Path, str]:
        selected = [item for item in self.panel2_source_defs if item["key"] in set(selected_keys)]
        if not selected:
            raise G25CommandError("\u0421\u043d\u0430\u0447\u0430\u043b\u0430 \u0432\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u0445\u043e\u0442\u044f \u0431\u044b \u043e\u0434\u0438\u043d \u0434\u0440\u0435\u0432\u043d\u0438\u0439 \u0438\u0441\u0442\u043e\u0447\u043d\u0438\u043a.")
        missing = [str(item["path"]) for item in selected if not Path(item["path"]).exists()]
        if missing:
            raise G25CommandError("\u041d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d\u044b \u0444\u0430\u0439\u043b\u044b \u043f\u0430\u043d\u0435\u043b\u0438: " + ", ".join(missing))

        panel_label = "Panel 2"
        manifest_lines = ["standard_name\tgroup\tpanel_name"]
        references_lines: list[str] = []

        for item in selected:
            source_path = Path(item["path"])
            source_text = self._read_text_if_possible(source_path).strip()
            if source_text:
                references_lines.extend(line.strip() for line in source_text.splitlines() if line.strip())
            for reference in g25_engine.load_g25_entries(source_path):
                group = self._extract_group_name(reference.name)
                manifest_lines.append(f"{reference.name}\t{group}\t{panel_label}")

        if not references_lines:
            raise G25CommandError("\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u0441\u043e\u0431\u0440\u0430\u0442\u044c \u043f\u0430\u043d\u0435\u043b\u044c \u0438\u0437 \u0432\u044b\u0431\u0440\u0430\u043d\u043d\u044b\u0445 \u0438\u0441\u0442\u043e\u0447\u043d\u0438\u043a\u043e\u0432.")

        references_path = run_dir / "panel2.txt"
        manifest_path = run_dir / "panel2_manifest.tsv"
        references_path.write_text("\n".join(references_lines) + "\n", encoding="utf-8")
        manifest_path.write_text("\n".join(manifest_lines) + "\n", encoding="utf-8")
        return references_path, manifest_path, panel_label

    def _run_panel_paths(
        self,
        panel_label: str,
        references_path: Path,
        manifest_path: Path,
        target_path: Path,
        run_dir: Path,
        input_mode: str,
        simulated_g25_line: str | None,
        target_name: str,
        command: str,
    ) -> G25RunResult:
        started_at = time.perf_counter()
        output_json = run_dir / f"{panel_label}_fit.json"
        output_png = run_dir / f"{panel_label}_fit.png"
        output_svg = run_dir / f"{panel_label}_fit.svg"

        payload = panel_fit_target(
            target_g25_path=target_path,
            references_path=references_path,
            manifest_path=manifest_path,
            group_column="group",
            iterations=250,
            top_references=12,
            output_json_path=output_json,
        )
        group_items = sorted(payload["groups"].items(), key=lambda item: group_sort_key(item[0]))
        render_svg(payload["target"], float(payload["distance"]), int(payload["sources"]), group_items, output_svg)
        render_png(payload["target"], float(payload["distance"]), int(payload["sources"]), group_items, output_png)
        elapsed = time.perf_counter() - started_at
        return G25RunResult(
            command=command,
            panel_name=panel_label,
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
        return self._run_panel_paths(
            config["label"],
            config["references_path"],
            config["manifest_path"],
            target_path,
            run_dir,
            input_mode,
            simulated_g25_line,
            target_name,
            command,
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
        cleaned = head.strip() if sep else reference_name.strip()
        return G25CommandService._clean_combined_group_name(cleaned)

    @staticmethod
    def _clean_combined_group_name(value: str) -> str:
        cleaned = re.sub(r"^[^A-Za-z0-9_]+", "", value.strip())
        return cleaned.strip()

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
