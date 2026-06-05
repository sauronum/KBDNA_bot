from __future__ import annotations

import csv
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path

from g25_core import g25_engine
from g25_core.command_service import G25CommandError, G25CommandService, G25CoordinatesResult, G25RunResult, G25_NUMBER_RE, group_emoji
from g25_core.render_fit_png import render_distance_png, render_multi_heatmap_png, render_single_card_png
from g25_core.render_fit_svg import display_name, group_sort_key


CUSTOM_PANEL_SOURCE_DEFS = [
    ("maikop", "Maikop", "Maikop.txt"),
    ("steppe_sintashta", "Steppe Sintashta", "Steppe_Sintashta.txt"),
    ("afanasievo", "Afanasievo", "Afanasievo.txt"),
    ("ulaanzhukh", "Ulaanzhukh", "Ulaanzhukh.txt"),
    ("angara_river", "Angara River", "AngaraRiver.txt"),
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
    ("caucasus_eba", "Caucasus EBA", "Caucasus_EBA", "Caucasus_EBA.txt"),
    ("yellow_river_ln", "Yellow River LN", "Yellow_River_LN", "Yellow_River_LN.txt"),
    ("anatolia_ba", "Anatolia BA", "Anatolia_BA", "Anatolia_BA.txt"),
    ("bmac_or_oxus_civilization", "BMAC or Oxus Civilization", "BMAC_or_Oxus_Civilization", "BMAC_or_Oxus_Civilization.txt"),
    ("helmandculture", "Helmandculture", "Helmandculture", "Helmandculture.txt"),
    ("steppe_mlba", "Steppe MLBA", "Steppe_MLBA", "Steppe_MLBA.txt"),
    ("rus_angara_river_ba", "RUS Angara River BA", "RUS_Angara_River_BA", "RUS_Angara_River_BA.txt"),
]

DISTANCE_SOURCE_DEFS = [
    ("modern", "modern", "Global25_PCA_modern_pop_averages_scaled.txt"),
    ("origin", "ancestry", "Global25_PCA_pop_averages_scaled.txt"),
]


@dataclass
class G25SourceInfo:
    source_key: str
    source_label: str
    references_path: Path
    source_count: int
    input_mode: str
    manifest_path: Path | None = None


@dataclass
class G25DistanceResult:
    dataset_key: str
    dataset_label: str
    target_name: str
    input_mode: str
    matches: list[tuple[float, str]]
    png_path: Path
    text_path: Path
    json_path: Path
    simulated_g25_line: str | None = None

    @property
    def summary_text(self) -> str:
        return (
            f"Distance PCA: {self.dataset_label}\n"
            f"Target: {self.target_name}\n"
            f"Top {len(self.matches)} nearest populations"
        )

    @property
    def detailed_text(self) -> str:
        lines = [self.summary_text, ""]
        for index, (distance, name) in enumerate(self.matches, start=1):
            lines.append(f"{index}. {display_name(name)} - {distance * 100:.4f}% / {distance:.7f}")
        return "\n".join(lines)


@dataclass
class G25MultiResult:
    command: str
    panel_name: str
    target_name: str
    target_count: int
    average_distance: float
    sources: int
    iterations: int
    elapsed_seconds: float
    columns: list[str]
    rows: list[dict[str, object]]
    png_path: Path
    json_path: Path
    csv_path: Path
    input_mode: str
    simulated_g25_line: str | None = None

    @property
    def summary_text(self) -> str:
        return (
            f"Vahaduo Multi: {self.panel_name}\n"
            f"Targets: {self.target_count}\n"
            f"Average distance: {self.average_distance * 100:.4f}% / {self.average_distance:.7f}\n"
            f"Sources: {self.sources} | Cycles: {self.iterations} | Time: {self.elapsed_seconds:.3f} s"
        )


class VahaduoCommandService(G25CommandService):
    def __init__(self, root_dir: Path | str | None = None) -> None:
        super().__init__(root_dir)
        self.distance_sources_dir = self.panel_dir / "distance"
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
        self.distance_source_defs = [
            {"key": key, "label": label, "file_name": file_name, "path": self.distance_sources_dir / file_name}
            for key, label, file_name in DISTANCE_SOURCE_DEFS
        ]

    def list_distance_sets(self) -> list[dict[str, Path | str]]:
        return [dict(item) for item in self.distance_source_defs]

    def list_vahaduo_preset_sources(self, source_kind: str) -> list[dict[str, Path | str]]:
        if source_kind in {"single", "multi"}:
            return [
                {"key": "panel1", "label": "Steppe_Russia"},
                {"key": "panel2", "label": "EBA"},
            ]
        return [dict(item) for item in self.distance_source_defs]

    def list_vahaduo_single_components(self, panel_key: str) -> list[dict[str, Path | str]]:
        if panel_key == "panel2":
            return [dict(item) for item in self.panel2_source_defs if Path(item["path"]).exists()]
        return [dict(item) for item in self.custom_source_defs if Path(item["path"]).exists()]

    def list_vahaduo_source_groups(self, references_path: Path | str) -> list[dict[str, object]]:
        counts: dict[str, int] = {}
        labels: dict[str, str] = {}
        for entry in self._load_source_entries(Path(references_path)):
            group = self._extract_group_name(entry.name) or entry.name
            if group not in counts:
                counts[group] = 0
                labels[group] = display_name(group)
            counts[group] += 1
        return [
            {"key": group, "label": labels[group], "count": count, "emoji": group_emoji(group)}
            for group, count in counts.items()
        ]

    def prepare_vahaduo_single_source(self, panel_key: str, selected_keys: list[str], sample_name: str) -> G25SourceInfo:
        run_dir = self.create_run_dir("vahaduo_single_source", sample_name)
        if panel_key == "panel2":
            source_defs = self.panel2_source_defs
            panel_label = "EBA"
        else:
            source_defs = self.custom_source_defs
            panel_label = "Steppe_Russia"

        selected_set = set(selected_keys)
        selected = [item for item in source_defs if item["key"] in selected_set]
        if not selected:
            raise G25CommandError("Сначала выберите хотя бы один компонент.")

        if panel_key == "panel2":
            references_path, manifest_path, _ = self._prepare_panel2(selected_keys, run_dir)
        else:
            references_path, manifest_path, _ = self._prepare_custom_panel(selected_keys, run_dir)

        selected_labels = [str(item["label"]) for item in selected]
        source_count = len(self._load_source_entries(references_path))
        return G25SourceInfo(
            source_key=f"single_{panel_key}",
            source_label=f"{panel_label}: {', '.join(selected_labels)}",
            references_path=references_path,
            source_count=source_count,
            input_mode="preset",
            manifest_path=manifest_path,
        )

    def prepare_vahaduo_saved_single_source(
        self,
        references_path: Path | str,
        selected_groups: list[str],
        source_label: str,
        sample_name: str,
    ) -> G25SourceInfo:
        references_path = Path(references_path)
        selected_set = {str(group) for group in selected_groups if str(group)}
        if not selected_set:
            raise G25CommandError("Сначала выберите хотя бы один компонент.")

        entries = self._load_source_entries(references_path)
        selected_entries = [
            entry
            for entry in entries
            if (self._extract_group_name(entry.name) or entry.name) in selected_set
        ]
        if not selected_entries:
            raise G25CommandError("В source не найдены выбранные компоненты.")

        run_dir = self.create_run_dir("vahaduo_saved_single_source", sample_name)
        filtered_references_path = run_dir / "source.txt"
        manifest_path = run_dir / "source_manifest.tsv"
        self._write_g25_entries(selected_entries, filtered_references_path)
        manifest_lines = ["standard_name\tgroup\tpanel_name"]
        for entry in selected_entries:
            group = self._extract_group_name(entry.name) or entry.name
            manifest_lines.append(f"{entry.name}\t{group}\t{source_label}")
        manifest_path.write_text("\n".join(manifest_lines) + "\n", encoding="utf-8")
        return G25SourceInfo(
            source_key="saved_single",
            source_label=source_label,
            references_path=filtered_references_path,
            source_count=len(selected_entries),
            input_mode="saved-components",
            manifest_path=manifest_path,
        )

    def get_vahaduo_preset_source(self, source_key: str, source_kind: str = "distance") -> G25SourceInfo:
        if source_kind == "single":
            raise G25CommandError("Для Single сначала выберите набор и компоненты.")
        source = next((item for item in self.list_vahaduo_preset_sources(source_kind) if item["key"] == source_key), None)
        if source is None:
            raise G25CommandError("Неизвестный готовый source.")

        references_path = Path(source["path"])
        entries = self._load_source_entries(references_path)
        return G25SourceInfo(
            source_key=source_key,
            source_label=str(source["label"]),
            references_path=references_path,
            source_count=len(entries),
            input_mode="preset",
        )

    def prepare_vahaduo_source_from_text(self, body: str, sample_name: str) -> G25SourceInfo:
        if not body.strip():
            raise G25CommandError("Не вижу source. Отправьте список популяций в формате Vahaduo.")
        run_dir = self.create_run_dir("vahaduo_source", sample_name)
        references_path = run_dir / "source.txt"
        entries = self._write_canonical_source(body, references_path)
        return G25SourceInfo("custom", "custom source", references_path, len(entries), "source-text")

    def prepare_vahaduo_source_from_file(self, input_path: Path | str, sample_name: str) -> G25SourceInfo:
        input_path = Path(input_path)
        run_dir = self.create_run_dir("vahaduo_source", sample_name)
        working_input = run_dir / input_path.name
        if input_path.resolve() != working_input.resolve():
            working_input.write_bytes(input_path.read_bytes())
        working_input = self._expand_archive_if_needed(working_input, run_dir)
        text = self._read_text_if_possible(working_input)
        if not text.strip():
            raise G25CommandError("Не удалось прочитать source-файл. Пришлите txt/csv со строками G25.")
        references_path = run_dir / "source.txt"
        entries = self._write_canonical_source(text, references_path)
        return G25SourceInfo("custom", input_path.stem or "custom source", references_path, len(entries), "source-file")

    def run_vahaduo_distance_from_text(
        self,
        source_key: str,
        source_label: str,
        references_path: Path | str,
        body: str,
        sample_name: str,
        *,
        top: int = 25,
    ) -> G25DistanceResult:
        coords_result = self.extract_coordinates_from_text(body, sample_name)
        run_dir = self.create_run_dir(f"vahaduo_distance_{source_key}", coords_result.target_name)
        return self._run_distance_paths(source_key, source_label, Path(references_path), coords_result, run_dir, top=top)

    def run_vahaduo_distance_from_file(
        self,
        source_key: str,
        source_label: str,
        references_path: Path | str,
        input_path: Path | str,
        sample_name: str,
        *,
        top: int = 25,
    ) -> G25DistanceResult:
        coords_result = self.extract_coordinates_from_file(input_path, sample_name)
        run_dir = self.create_run_dir(f"vahaduo_distance_{source_key}", coords_result.target_name)
        return self._run_distance_paths(source_key, source_label, Path(references_path), coords_result, run_dir, top=top)

    def run_vahaduo_single_from_text(
        self,
        source_key: str,
        source_label: str,
        references_path: Path | str,
        body: str,
        sample_name: str,
        source_manifest_path: Path | str | None = None,
    ) -> G25RunResult:
        coords_result = self.extract_coordinates_from_text(body, sample_name)
        run_dir = self.create_run_dir(f"vahaduo_single_{source_key}", coords_result.target_name)
        target_path = run_dir / "target.g25"
        target_path.write_text(coords_result.simulated_g25_line + "\n", encoding="utf-8")
        return self._run_vahaduo_single(source_label, Path(references_path), target_path, run_dir, coords_result, source_manifest_path)

    def run_vahaduo_single_from_file(
        self,
        source_key: str,
        source_label: str,
        references_path: Path | str,
        input_path: Path | str,
        sample_name: str,
        source_manifest_path: Path | str | None = None,
    ) -> G25RunResult:
        coords_result = self.extract_coordinates_from_file(input_path, sample_name)
        run_dir = self.create_run_dir(f"vahaduo_single_{source_key}", coords_result.target_name)
        target_path = run_dir / "target.g25"
        target_path.write_text(coords_result.simulated_g25_line + "\n", encoding="utf-8")
        return self._run_vahaduo_single(source_label, Path(references_path), target_path, run_dir, coords_result, source_manifest_path)

    def run_vahaduo_multi_from_text(
        self,
        source_key: str,
        source_label: str,
        references_path: Path | str,
        body: str,
        sample_name: str,
        source_manifest_path: Path | str | None = None,
    ) -> G25MultiResult:
        entries = self._parse_multi_target_text(body, sample_name)
        run_name = sample_name.strip() or (entries[0].name if len(entries) == 1 else "targets")
        run_dir = self.create_run_dir(f"vahaduo_multi_{source_key}", run_name)
        target_path = run_dir / "target.g25"
        self._write_g25_entries(entries, target_path)
        return self._run_vahaduo_multi(source_label, Path(references_path), target_path, run_dir, "g25-text", source_manifest_path)

    def run_vahaduo_multi_from_file(
        self,
        source_key: str,
        source_label: str,
        references_path: Path | str,
        input_path: Path | str,
        sample_name: str,
        source_manifest_path: Path | str | None = None,
    ) -> G25MultiResult:
        input_path = Path(input_path)
        run_dir = self.create_run_dir(f"vahaduo_multi_{source_key}", sample_name)
        working_input = run_dir / input_path.name
        if input_path.resolve() != working_input.resolve():
            working_input.write_bytes(input_path.read_bytes())
        working_input = self._expand_archive_if_needed(working_input, run_dir)
        text = self._read_text_if_possible(working_input)
        if not text.strip():
            raise G25CommandError("Не удалось прочитать target-файл. Пришлите txt/csv со строками G25.")
        entries = self._parse_multi_target_text(text, sample_name)
        target_path = run_dir / "target.g25"
        self._write_g25_entries(entries, target_path)
        return self._run_vahaduo_multi(source_label, Path(references_path), target_path, run_dir, "g25-file", source_manifest_path)

    def _run_vahaduo_single(
        self,
        source_label: str,
        references_path: Path,
        target_path: Path,
        run_dir: Path,
        coords_result: G25CoordinatesResult,
        source_manifest_path: Path | str | None = None,
    ) -> G25RunResult:
        self._load_source_entries(references_path)
        if source_manifest_path is not None:
            manifest_path = Path(source_manifest_path)
            if not manifest_path.exists():
                raise G25CommandError("Manifest для source больше не найден. Выберите source заново.")
        else:
            manifest_path = run_dir / "vahaduo_single_manifest.tsv"
            self._build_vahaduo_manifest(references_path, manifest_path, "Vahaduo Single")
        result = self._run_panel_paths(
            "Vahaduo Single",
            references_path,
            manifest_path,
            target_path,
            run_dir,
            coords_result.input_mode,
            coords_result.simulated_g25_line,
            coords_result.target_name,
            "vahaduo_single",
        )
        result.panel_name = source_label.split(":", 1)[0].strip() or "Single"
        render_single_card_png(source_label, result.target_name, result.distance, result.sources, result.groups, result.png_path)
        return result

    def _run_vahaduo_multi(
        self,
        source_label: str,
        references_path: Path,
        target_path: Path,
        run_dir: Path,
        input_mode: str,
        source_manifest_path: Path | str | None = None,
    ) -> G25MultiResult:
        if source_manifest_path is not None:
            manifest_path = Path(source_manifest_path)
            if not manifest_path.exists():
                raise G25CommandError("Manifest для source больше не найден. Выберите source заново.")
        else:
            manifest_path = run_dir / "vahaduo_multi_manifest.tsv"
            self._build_vahaduo_manifest(references_path, manifest_path, "Vahaduo Multi")

        started_at = time.perf_counter()
        targets = g25_engine.load_g25_entries(target_path)
        if not targets:
            raise G25CommandError("Для Multi пришлите хотя бы один target в формате G25.")
        if len(targets) > 25:
            raise G25CommandError("Для Multi можно считать не больше 25 target за один запуск.")
        references = self._load_source_entries(references_path)
        manifest = g25_engine.load_reference_manifest(manifest_path)
        columns = sorted({(metadata.get("group") or "Unassigned") for metadata in manifest.values()}, key=group_sort_key)
        if not columns:
            raise G25CommandError("Не удалось определить группы source для Multi.")

        rows: list[dict[str, object]] = []
        max_iterations = 0
        for target in targets:
            fit = g25_engine.summarize_panel_fit(target, references, manifest, "group", 250, 12)
            max_iterations = max(max_iterations, int(fit["iterations"]))
            rows.append(
                {
                    "target": target.name,
                    "distance": float(fit["distance"]),
                    "groups": {str(name): float(value) for name, value in fit["groups"].items()},
                    "top_references": list(fit["top_references"]),
                }
            )

        average_distance = round(sum(float(row["distance"]) for row in rows) / len(rows), 6)
        average_groups = {
            name: round(sum(float(dict(row["groups"]).get(name, 0.0)) for row in rows) / len(rows), 6)
            for name in columns
        }
        payload = {
            "mode": "vahaduo_multi",
            "panel_name": source_label,
            "target_count": len(rows),
            "source_count": len(references),
            "group_column": "group",
            "columns": columns,
            "average_distance": average_distance,
            "average_groups": average_groups,
            "targets": rows,
        }
        output_json = run_dir / "Vahaduo Multi_fit.json"
        output_csv = run_dir / "Vahaduo Multi_fit.csv"
        output_png = run_dir / "Vahaduo Multi_fit.png"
        g25_engine.write_json_file(output_json, payload)
        self._write_multi_csv(output_csv, rows, columns, average_distance, average_groups)
        source_name = source_label.split(":", 1)[0].strip() or source_label.strip() or "Multi"
        render_multi_heatmap_png(source_name, rows, columns, average_distance, average_groups, output_png)
        elapsed = time.perf_counter() - started_at
        target_name = targets[0].name if len(targets) == 1 else f"{len(targets)} targets"
        return G25MultiResult(
            command="vahaduo_multi",
            panel_name=source_name,
            target_name=target_name,
            target_count=len(rows),
            average_distance=average_distance,
            sources=len(references),
            iterations=max_iterations,
            elapsed_seconds=elapsed,
            columns=columns,
            rows=rows,
            png_path=output_png,
            json_path=output_json,
            csv_path=output_csv,
            input_mode=input_mode,
        )

    def _run_distance_paths(
        self,
        dataset_key: str,
        dataset_label: str,
        references_path: Path,
        coords_result: G25CoordinatesResult,
        run_dir: Path,
        top: int,
    ) -> G25DistanceResult:
        if not references_path.exists():
            raise G25CommandError(f"Не найден source-файл: {references_path.name}")
        try:
            target_entry = g25_engine.parse_g25_line(coords_result.simulated_g25_line)
            references = self._load_source_entries(references_path)
        except ValueError as exc:
            raise G25CommandError(f"Не удалось подготовить Distance: {exc}") from exc
        matches = [
            (distance, entry.name)
            for distance, entry in g25_engine.nearest_entries(target_entry, references, top=max(1, int(top)))
        ]
        if not matches:
            raise G25CommandError("Не удалось найти популяции для сравнения.")
        result = G25DistanceResult(
            dataset_key=dataset_key,
            dataset_label=dataset_label,
            target_name=coords_result.target_name,
            input_mode=coords_result.input_mode,
            matches=matches,
            png_path=run_dir / f"distance_{dataset_key}.png",
            text_path=run_dir / f"distance_{dataset_key}.txt",
            json_path=run_dir / f"distance_{dataset_key}.json",
            simulated_g25_line=coords_result.simulated_g25_line,
        )
        render_distance_png(result.dataset_label, result.target_name, result.matches, result.png_path)
        result.text_path.write_text(result.detailed_text + "\n", encoding="utf-8")
        result.json_path.write_text(
            json.dumps(
                {
                    "dataset_key": result.dataset_key,
                    "dataset_label": result.dataset_label,
                    "target_name": result.target_name,
                    "input_mode": result.input_mode,
                    "simulated_g25_line": result.simulated_g25_line,
                    "matches": [
                        {"rank": index, "name": name, "distance": distance}
                        for index, (distance, name) in enumerate(result.matches, start=1)
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return result

    def _load_source_entries(self, references_path: Path) -> list[g25_engine.G25Entry]:
        try:
            return g25_engine.load_g25_entries(references_path)
        except ValueError as exc:
            raise G25CommandError(f"Не удалось прочитать source: {exc}") from exc

    @classmethod
    def _parse_g25_source_text(cls, text: str) -> list[g25_engine.G25Entry]:
        cleaned = cls._clean_g25_body(text)
        entries: list[g25_engine.G25Entry] = []
        for line in cleaned.splitlines():
            candidate = line.strip()
            if not candidate:
                continue
            lowered = candidate.lower()
            if "pc1" in lowered and ("pc2" in lowered or lowered.startswith("sample")):
                continue
            try:
                entries.append(g25_engine.parse_g25_line(candidate))
            except ValueError:
                continue
        if not entries:
            raise G25CommandError("В source не найдено ни одной строки G25: имя + 25 координат.")
        return entries

    @classmethod
    def _write_canonical_source(cls, text: str, references_path: Path) -> list[g25_engine.G25Entry]:
        entries = cls._parse_g25_source_text(text)
        cls._write_g25_entries(entries, references_path)
        return entries

    @staticmethod
    def _write_g25_entries(entries: list[g25_engine.G25Entry], output_path: Path) -> None:
        lines = [g25_engine.g25_line_from_coords(entry.name, entry.coords) for entry in entries]
        output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    @staticmethod
    def _build_vahaduo_manifest(references_path: Path, manifest_path: Path, panel_name: str) -> None:
        references = g25_engine.load_g25_entries(references_path)
        lines = ["standard_name\tgroup\tpanel_name"]
        for reference in references:
            group = VahaduoCommandService._extract_group_name(reference.name)
            lines.append(f"{reference.name}\t{group}\t{panel_name}")
        manifest_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    @staticmethod
    def _extract_group_name(reference_name: str) -> str:
        cleaned = re.split(r"[:;]", reference_name, maxsplit=1)[0].strip()
        return VahaduoCommandService._clean_combined_group_name(cleaned)

    @classmethod
    def _parse_multi_target_text(cls, text: str, sample_name: str) -> list[g25_engine.G25Entry]:
        cleaned = cls._clean_g25_body(text)
        if not cleaned:
            raise G25CommandError("Не вижу target-координат. Пришлите строки G25: имя и 25 координат.")
        try:
            return cls._parse_g25_source_text(cleaned)
        except G25CommandError:
            pass
        numbers = G25_NUMBER_RE.findall(cleaned)
        if len(numbers) == 25:
            coords = tuple(float(value) for value in numbers)
            target_name = sample_name.strip() or "Target"
            return [g25_engine.G25Entry(target_name, coords)]
        raise G25CommandError(
            "Не удалось распознать target-строки для Multi. Пришлите txt/csv со строками вида Name,0.0123,...,0.0456."
        )

    @staticmethod
    def _write_multi_csv(
        output_path: Path,
        rows: list[dict[str, object]],
        columns: list[str],
        average_distance: float,
        average_groups: dict[str, float],
    ) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["Target", "Distance", *columns])
            for row in rows:
                groups = {str(key): float(value) for key, value in dict(row.get("groups") or {}).items()}
                writer.writerow(
                    [
                        str(row.get("target") or ""),
                        f"{float(row.get('distance') or 0.0):.7f}",
                        *[f"{groups.get(name, 0.0) * 100.0:.1f}" for name in columns],
                    ]
                )
            writer.writerow(
                [
                    "Average",
                    f"{average_distance:.7f}",
                    *[f"{float(average_groups.get(name, 0.0)) * 100.0:.1f}" for name in columns],
                ]
            )
