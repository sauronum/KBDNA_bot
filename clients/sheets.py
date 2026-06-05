from __future__ import annotations

import difflib
import html
import json
import logging
import re
from pathlib import Path
from typing import Callable, Optional

try:
    import gspread
    from google.oauth2.service_account import Credentials
except ImportError:
    gspread = None
    Credentials = None

from features import analytics as analytics_feature
from ui.analytics import (
    mtdna_haplogroup_description as mtdna_haplogroup_description_ui,
    mtdna_subclade_description as mtdna_subclade_description_ui,
)
from features.ystr import (
    adjust_ystr_dys389ii,
    compare_ystr_entries as compare_ystr_feature_entries,
    find_ystr_matches as find_ystr_feature_matches,
    is_ystr_marker_header,
    parse_ystr_marker_value,
    ystr_panel_label,
)

EMOJI_MAP_PATH = Path("haplogroup_emoji_map.json")
YFULL_LINKS_PATH = Path("yfull_links.json")
YFULL_LINK_OVERRIDES = {
    "https://www.yfull.com/tree/E-Z21467/": "https://www.yfull.com/tree/E-M34/",
    "https://www.yfull.com/tree/E-FTE31051/": "https://www.yfull.com/tree/E-L241/",
    "https://www.yfull.com/tree/G-BY144524/": "https://www.yfull.com/tree/G-Z31455/",
    "https://www.yfull.com/tree/G-BY210820/": "https://www.yfull.com/tree/G-Z31459/",
    "https://www.yfull.com/tree/G-FTB51554/": "https://www.yfull.com/tree/G-FGC671/",
    "https://www.yfull.com/tree/G-FTD87775/": "https://www.yfull.com/tree/G-Y279353/",
    "https://www.yfull.com/tree/G-FTG50018/": "https://www.yfull.com/tree/G-Y92117/",
    "https://www.yfull.com/tree/G-Z6670/": "",
    "https://www.yfull.com/tree/G-Z6673/": "https://www.yfull.com/tree/G-FGC1144/",
    "https://www.yfull.com/tree/J-BY139400/": "https://www.yfull.com/tree/J-Y30811/",
    "https://www.yfull.com/tree/J-M12/": "",
    "https://www.yfull.com/tree/J-SK1313/": "",
    "https://www.yfull.com/tree/J-Z2229/": "",
    "https://www.yfull.com/tree/R-BY120333/": "https://www.yfull.com/tree/R-U106/",
    "https://www.yfull.com/tree/R-BY30628/": "https://www.yfull.com/tree/R-YP457/",
    "https://www.yfull.com/tree/R-FT267311/": "https://www.yfull.com/tree/R-YP450/",
    "https://www.yfull.com/tree/R-FT354176/": "https://www.yfull.com/tree/R-YP450/",
    "https://www.yfull.com/tree/R-FT363311/": "https://www.yfull.com/tree/R-YP1451/",
    "https://www.yfull.com/tree/R-FTD77954/": "https://www.yfull.com/tree/R-FT91192/",
    "https://www.yfull.com/tree/R-FTG37992/": "https://www.yfull.com/tree/R-YP457/",
    "https://www.yfull.com/tree/R-YP643/": "https://www.yfull.com/tree/R-Y57/",
    "https://www.yfull.com/tree/R-Z2105/": "",
}

logger = logging.getLogger(__name__)


class SheetsClient:
    DEFAULT_NAME_ALIASES = ("name", "имя", "фамилия")
    GROUP_SUBCLADE_ALIASES = ("name", "имя", "фамилия")
    DEFAULT_ORIGIN_ALIASES = (
        "paternal ancestor name",
        "paternal ancestor",
        "предок по отцовской линии",
        "отцовский предок",
        "происхождение",
    )
    RELATED_MATCH_GROUP = "group"
    RELATED_MATCH_HAPLOGROUP = "haplogroup"
    LOOKUP_LABEL_ROLLUP = "rollup"
    LOOKUP_LABEL_TERMINAL_HAPLOGROUP = "terminal_haplogroup"
    MAX_RELATED_NAMES = 40

    def __init__(
        self,
        creds_path: str,
        spreadsheet_id: str,
        worksheet_name: str = "",
        *,
        name_aliases: tuple[str, ...] | None = None,
        origin_aliases: tuple[str, ...] | None = None,
        row_filter: Callable[[list[str], list[str]], bool] | None = None,
        related_match_mode: str = RELATED_MATCH_GROUP,
        lookup_label_mode: str = LOOKUP_LABEL_ROLLUP,
        values_range: str = "",
    ) -> None:
        if gspread is None or Credentials is None:
            raise RuntimeError("Google Sheets dependencies are not installed. Run: pip install -r requirements.txt")
        self.name_aliases = tuple(name_aliases or self.DEFAULT_NAME_ALIASES)
        self.origin_aliases = tuple(origin_aliases or self.DEFAULT_ORIGIN_ALIASES)
        self.row_filter = row_filter
        self.related_match_mode = (
            related_match_mode
            if related_match_mode in {self.RELATED_MATCH_GROUP, self.RELATED_MATCH_HAPLOGROUP}
            else self.RELATED_MATCH_GROUP
        )
        self.lookup_label_mode = (
            lookup_label_mode
            if lookup_label_mode in {self.LOOKUP_LABEL_ROLLUP, self.LOOKUP_LABEL_TERMINAL_HAPLOGROUP}
            else self.LOOKUP_LABEL_ROLLUP
        )
        self.values_range = values_range.strip()
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets.readonly",
            "https://www.googleapis.com/auth/drive.readonly",
        ]
        creds = Credentials.from_service_account_file(creds_path, scopes=scopes)
        client = gspread.authorize(creds)
        spreadsheet = client.open_by_key(spreadsheet_id)
        self.worksheet = (
            spreadsheet.worksheet(worksheet_name) if worksheet_name else spreadsheet.get_worksheet(0)
        )
        self.emoji_map = self._load_json(EMOJI_MAP_PATH)
        self.yfull_links = self._load_yfull_links(YFULL_LINKS_PATH)
        if not self.emoji_map:
            self.emoji_map = self._default_emoji_map()

    @staticmethod
    def _normalize(value: str) -> str:
        cleaned = value.strip().lower()
        cleaned = cleaned.translate(
            str.maketrans(
                {
                    "ё": "е",
                    "–": "-",
                    "—": "-",
                    "−": "-",
                    "‑": "-",
                    "ʼ": "'",
                    "’": "'",
                    "`": "'",
                }
            )
        )
        cleaned = re.sub(r"\s*-\s*", "-", cleaned)
        cleaned = " ".join(cleaned.split())
        return cleaned

    @classmethod
    def _normalize_surname_stem(cls, value: str) -> str:
        cleaned = cls._normalize(value)
        suffixes = (
            "ланы",
            "лени",
            "лары",
            "лери",
            "-ланы",
            "-лени",
            "-лары",
            "-лери",
            "ов",
            "ев",
            "ова",
            "ева",
            "-ов",
            "-ев",
            "-ова",
            "-ева",
        )
        for suffix in suffixes:
            if cleaned.endswith(suffix):
                stem = cleaned[: -len(suffix)].rstrip("-'")
                if len(stem) >= 3:
                    return stem
        return cleaned

    @classmethod
    def _uses_collective_suffix(cls, value: str) -> bool:
        cleaned = cls._normalize(value)
        suffixes = ("ланы", "лени", "лары", "лери", "-ланы", "-лени", "-лары", "-лери")
        return any(cleaned.endswith(suffix) for suffix in suffixes)

    @staticmethod
    def _find_col_index(headers: list[str], aliases: tuple[str, ...]) -> Optional[int]:
        normalized = [h.strip().lower() for h in headers]
        for alias in aliases:
            a = alias.strip().lower()
            if a in normalized:
                return normalized.index(a)
        return None

    @staticmethod
    def _find_col_indexes(headers: list[str], aliases: tuple[str, ...]) -> list[int]:
        normalized = [h.strip().lower() for h in headers]
        indexes: list[int] = []
        for alias in aliases:
            a = alias.strip().lower()
            for index, header in enumerate(normalized):
                if header == a and index not in indexes:
                    indexes.append(index)
        return indexes

    def _find_name_col_index(self, headers: list[str]) -> Optional[int]:
        return self._find_col_index(headers, self.name_aliases)

    def _find_name_col_indexes(self, headers: list[str]) -> list[int]:
        return self._find_col_indexes(headers, self.name_aliases)

    def _row_name_values(self, row: list[str], name_indexes: list[int]) -> list[str]:
        values: list[str] = []
        seen: set[str] = set()
        for index in name_indexes:
            value = row[index].strip() if len(row) > index else ""
            if self._is_placeholder(value):
                continue
            key = self._normalize(value)
            if key in seen:
                continue
            seen.add(key)
            values.append(value)
        return values

    def _row_display_name(self, row: list[str], name_indexes: list[int]) -> str:
        values = self._row_name_values(row, name_indexes)
        return values[0] if values else ""

    def _find_group_subclade_col_index(self, headers: list[str]) -> Optional[int]:
        return self._find_col_index(headers, self.GROUP_SUBCLADE_ALIASES)

    def _find_origin_col_index(self, headers: list[str]) -> Optional[int]:
        return self._find_col_index(headers, getattr(self, "origin_aliases", self.DEFAULT_ORIGIN_ALIASES))

    def _group_from_row(
        self,
        row: list[str],
        kit_idx: Optional[int],
        group_subclade_idx: Optional[int],
    ) -> tuple[str, str]:
        group_general, group_subclade = self._extract_group_from_row(row, kit_idx)
        if group_general and not group_subclade and group_subclade_idx is not None and len(row) > group_subclade_idx:
            group_subclade = " ".join(row[group_subclade_idx].strip().split())
        return group_general, group_subclade

    def _get_all_values(self) -> list[list[str]]:
        values_range = getattr(self, "values_range", "")
        rows = self.worksheet.get(values_range) if values_range else self.worksheet.get_all_values()
        if not rows or self.row_filter is None:
            return rows

        headers = rows[0]
        kit_idx = self._find_col_index(headers, ("kit number", "kit", "номер кита"))
        filtered = [headers]
        pending_group_rows: list[list[str]] = []
        for row in rows[1:]:
            group_general, _group_subclade = self._extract_group_from_row(row, kit_idx)
            if group_general:
                pending_group_rows.append(row)
                continue

            if not self.row_filter(headers, row):
                continue

            if pending_group_rows:
                filtered.extend(pending_group_rows)
                pending_group_rows = []
            filtered.append(row)
        return filtered

    @classmethod
    def _extract_group_from_row(cls, row: list[str], kit_idx: Optional[int]) -> tuple[str, str]:
        return analytics_feature.extract_group_from_row(row, kit_idx)

    @staticmethod
    def _is_placeholder(value: str) -> bool:
        stripped = value.strip()
        if not stripped:
            return True
        return bool(re.fullmatch(r"[-–—_~.\s]+", stripped))

    @staticmethod
    def _load_json(path: Path) -> dict[str, str]:
        if not path.exists():
            return {}
        try:
            raw = json.loads(path.read_text(encoding="utf-8-sig"))
            return {str(k).upper(): str(v) for k, v in raw.items()}
        except Exception as exc:
            logger.warning("Failed to load %s: %s", path, exc)

            return {}
    @staticmethod
    def _load_yfull_links(path: Path) -> dict[str, dict[str, str]]:
        empty = {"by_subclade": {}, "by_terminal": {}}
        if not path.exists():
            return empty
        try:
            raw = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception as exc:
            logger.warning("Failed to load %s: %s", path, exc)
            return empty

        return {
            "by_subclade": {
                " ".join(str(k).strip().upper().split()): str(v)
                for k, v in raw.get("by_subclade", {}).items()
                if str(k).strip() and str(v).strip()
            },
            "by_terminal": {
                " ".join(str(k).strip().upper().split()): str(v)
                for k, v in raw.get("by_terminal", {}).items()
                if str(k).strip() and str(v).strip()
            },
        }

    @staticmethod
    def _default_emoji_map() -> dict[str, str]:
        return {
            "G": "??",
            "R": "??",
            "J": "??",
            "E": "??",
            "I": "??",
            "N": "??",
            "Q": "?",
            "T": "??",
        }

    def _emoji_for_haplogroup(self, personal_haplo: str, general_group: str) -> str:
        return ""

    @staticmethod
    def _normalize_subclade_key(value: str) -> str:
        return analytics_feature.normalize_subclade_key(value)

    @staticmethod
    def _extract_terminal_snp(value: str) -> str:
        return analytics_feature.extract_terminal_snp(value)

    @staticmethod
    def _extract_subclade_tokens(value: str) -> list[str]:
        return analytics_feature.extract_subclade_tokens(value)

    @staticmethod
    def _split_origin_parts(value: str) -> tuple[str, str]:
        cleaned = " ".join(value.strip().split())
        match = re.match(r"^(.+?)\s*\((.+)\)$", cleaned)
        if not match:
            return cleaned, ""
        return match.group(1).strip(), match.group(2).strip()

    @classmethod
    def _format_origins(cls, origins: list[str]) -> str:
        if not origins:
            return "-"

        ordered_bases: list[str] = []
        detailed: dict[str, list[str]] = {}
        plain: list[str] = []
        plain_seen: set[str] = set()

        for origin in origins:
            base, detail = cls._split_origin_parts(origin)
            if not base:
                continue
            if base not in ordered_bases:
                ordered_bases.append(base)
            if detail:
                detailed.setdefault(base, [])
                if detail not in detailed[base]:
                    detailed[base].append(detail)
            else:
                key = cls._normalize(base)
                if key not in plain_seen:
                    plain_seen.add(key)
                    plain.append(base)

        lines: list[str] = []
        used_plain: set[str] = set()
        for base in ordered_bases:
            details = detailed.get(base, [])
            escaped_base = html.escape(base)
            if details:
                escaped_details = ", ".join(html.escape(detail) for detail in details)
                lines.append(f"<b>{escaped_base}:</b> {escaped_details}")
                used_plain.add(cls._normalize(base))
            else:
                key = cls._normalize(base)
                if key not in used_plain and base in plain:
                    lines.append(escaped_base)
                    used_plain.add(key)

        return "\n".join(lines) if lines else "-"

    def _get_yfull_link(self, general_group: str, subclade: str, *, allow_generated: bool = True) -> str:
        if not subclade:
            return ""

        by_subclade = self.yfull_links.get("by_subclade", {})
        by_terminal = self.yfull_links.get("by_terminal", {})

        candidates = [self._normalize_subclade_key(subclade)]
        if general_group:
            candidates.append(self._normalize_subclade_key(f"{general_group} {subclade}"))
            candidates.append(self._normalize_subclade_key(f"{general_group} - {subclade}"))

        for candidate in candidates:
            if candidate and candidate in by_subclade:
                return by_subclade[candidate]

        tokens = self._extract_subclade_tokens(subclade)
        terminal_snp = self._normalize_subclade_key(self._extract_terminal_snp(subclade))
        token_candidates: list[str] = []
        for token in reversed(tokens):
            normalized = self._normalize_subclade_key(token)
            if normalized and normalized not in token_candidates:
                token_candidates.append(normalized)
            cleaned = re.sub(r"[^A-Z0-9-]+$", "", normalized)
            if cleaned and cleaned not in token_candidates:
                token_candidates.append(cleaned)
        if terminal_snp and terminal_snp not in token_candidates:
            token_candidates.insert(0, terminal_snp)

        for candidate in token_candidates:
            if candidate and candidate in by_terminal:
                return by_terminal[candidate]

        haplo_letter = self._first_letter_group(general_group)
        if allow_generated:
            for candidate in token_candidates:
                if candidate and haplo_letter and re.fullmatch(r"[A-Z][A-Z0-9-]*", candidate):
                    return f"https://www.yfull.com/tree/{haplo_letter}-{candidate}/"

        return ""

    @staticmethod
    def _normalize_yfull_link(url: str) -> str:
        return YFULL_LINK_OVERRIDES.get(url, url)

    def _get_best_yfull_link(self, general_group: str, display_subclade: str, raw_subclade: str) -> str:
        display_subclade = " ".join((display_subclade or "").split())
        raw_subclade = " ".join((raw_subclade or "").split())
        if not display_subclade:
            return self._normalize_yfull_link(self._get_yfull_link(general_group, raw_subclade, allow_generated=False))

        raw_terminal = self._normalize_subclade_key(self._extract_terminal_snp(raw_subclade))
        normalized_display = self._normalize_subclade_key(display_subclade)

        if raw_terminal and normalized_display and raw_terminal != normalized_display:
            terminal_link = self._get_yfull_link(general_group, raw_terminal, allow_generated=False)
            if terminal_link:
                return self._normalize_yfull_link(terminal_link)

            tokens = self._extract_subclade_tokens(raw_subclade)
            skipped_terminal = False
            for token in reversed(tokens):
                normalized = self._normalize_subclade_key(token)
                if not normalized:
                    continue
                if not skipped_terminal and normalized == raw_terminal:
                    skipped_terminal = True
                    continue
                link = self._get_yfull_link(general_group, normalized, allow_generated=False)
                if link:
                    return self._normalize_yfull_link(link)

        return self._normalize_yfull_link(self._get_yfull_link(general_group, display_subclade, allow_generated=False))

    def _related_match_key(self, entry: dict[str, str]) -> str:
        related_match_mode = getattr(self, "related_match_mode", self.RELATED_MATCH_GROUP)
        if related_match_mode == self.RELATED_MATCH_HAPLOGROUP:
            haplo_key = self._normalize_subclade_key(entry.get("haplo", ""))
            if haplo_key:
                return f"haplogroup|{haplo_key}"
        return f"group|{entry.get('group_key', '')}"

    def _lookup_display_labels(self, entry: dict[str, str]) -> tuple[str, str]:
        display_general = self._distribution_group_label(entry)
        display_subclade = self._subclade_distribution_label(entry)
        lookup_label_mode = getattr(self, "lookup_label_mode", self.LOOKUP_LABEL_ROLLUP)
        if lookup_label_mode == self.LOOKUP_LABEL_TERMINAL_HAPLOGROUP:
            terminal = self._extract_terminal_snp(entry.get("haplo", ""))
            if terminal:
                haplo_letter = self._first_letter_group(display_general) or self._first_letter_group(entry.get("haplo", ""))
                if haplo_letter and terminal.upper().startswith(f"{haplo_letter}-"):
                    terminal = terminal.split("-", 1)[1]
                display_subclade = terminal
        return display_general, display_subclade

    @classmethod
    def _format_related_names(cls, names: list[str]) -> str:
        visible = names[: cls.MAX_RELATED_NAMES]
        text = ", ".join(visible)
        remaining = len(names) - len(visible)
        if remaining > 0:
            text += f"\nи ещё {remaining}"
        return text

    @staticmethod
    def _first_letter_group(value: str) -> str:
        match = re.match(r"^([A-Za-z])", value.strip())
        return match.group(1).upper() if match else ""

    def find_similar_names(self, name: str, limit: int = 5, cutoff: float = 0.78) -> list[str]:
        query = self._normalize(name)
        if len(query) < 3:
            return []

        query_base = self._normalize_surname_stem(query)
        uses_collective_form = query != query_base
        rows = self._get_all_values()
        if not rows:
            return []

        headers = rows[0]
        name_indexes = self._find_name_col_indexes(headers)
        if not name_indexes:
            return []

        normalized_to_display: dict[str, str] = {}
        candidate_bases: dict[str, str] = {}
        for row in rows[1:]:
            display_name = self._row_display_name(row, name_indexes)
            if not display_name:
                continue
            for raw_name in self._row_name_values(row, name_indexes):
                normalized = self._normalize(raw_name)
                if not normalized or normalized == query:
                    continue
                normalized_to_display.setdefault(normalized, display_name)
                candidate_bases.setdefault(normalized, self._normalize_surname_stem(normalized))

        exact_base_matches = [
            normalized_to_display[candidate]
            for candidate, candidate_base in candidate_bases.items()
            if candidate_base == query_base
        ]
        if exact_base_matches:
            return exact_base_matches[:limit]

        def common_prefix_len(left: str, right: str) -> int:
            prefix = 0
            for left_char, right_char in zip(left, right):
                if left_char != right_char:
                    break
                prefix += 1
            return prefix

        scored: list[tuple[float, str]] = []
        max_length_gap = max(2, len(query_base) // 4)
        relaxed_cutoff = 0.72 if uses_collective_form else cutoff
        for candidate in normalized_to_display:
            candidate_base = candidate_bases[candidate]
            if candidate_base[0] != query_base[0]:
                continue
            if abs(len(candidate_base) - len(query_base)) > max_length_gap + (1 if uses_collective_form else 0):
                continue

            prefix_len = common_prefix_len(query_base, candidate_base)
            ratio = difflib.SequenceMatcher(None, query_base, candidate_base).ratio()
            if ratio < relaxed_cutoff:
                continue
            if prefix_len < (2 if uses_collective_form else 2):
                continue
            if not uses_collective_form and prefix_len < 3 and ratio < 0.84:
                continue

            score = ratio
            score += min(prefix_len, 4) * 0.04
            score -= abs(len(candidate_base) - len(query_base)) * 0.02
            if candidate_base.startswith(query_base) or query_base.startswith(candidate_base):
                score += 0.03
            if candidate_base == query_base:
                score += 0.12
            if uses_collective_form:
                score += 0.04
            scored.append((score, candidate))

        scored.sort(key=lambda item: item[0], reverse=True)
        return [normalized_to_display[candidate] for _, candidate in scored[:limit]]

    def get_group_records(self, name: str) -> list[dict[str, str]]:
        rows = self._get_all_values()
        if not rows:
            return [{"text": "Таблица пуста.", "button_label": "Пусто"}]

        headers = rows[0]
        name_indexes = self._find_name_col_indexes(headers)
        haplo_idx = self._find_col_index(headers, ("гаплогруппа", "haplogroup"))
        kit_idx = self._find_col_index(headers, ("kit number", "kit", "номер кита"))
        group_subclade_idx = self._find_group_subclade_col_index(headers)
        ancestor_idx = self._find_origin_col_index(headers)

        if not name_indexes or haplo_idx is None:
            return [{"text": "Не найдены нужные колонки: Name/Имя/Фамилия и/или Гаплогруппа.", "button_label": "Ошибка"}]

        current_general = ""
        current_subclade = ""
        entries: list[dict[str, str]] = []

        for row in rows[1:]:
            row_name = self._row_display_name(row, name_indexes)
            row_name_variants = self._row_name_values(row, name_indexes)
            row_haplo = row[haplo_idx].strip() if len(row) > haplo_idx else ""
            row_ancestor = row[ancestor_idx].strip() if ancestor_idx is not None and len(row) > ancestor_idx else "-"

            group_general, group_subclade = self._group_from_row(row, kit_idx, group_subclade_idx)
            if group_general:
                current_general = group_general
                current_subclade = group_subclade
                continue

            entries.append(
                {
                    "name": row_name,
                    "name_variants": row_name_variants,
                    "haplo": row_haplo,
                    "ancestor": row_ancestor,
                    "general": current_general,
                    "subclade": current_subclade,
                    "group_key": f"{current_general}|{current_subclade}",
                }
            )

        for entry in entries:
            display_general = self._distribution_group_label(entry)
            display_subclade = self._subclade_distribution_label(entry)
            lookup_general, lookup_subclade = self._lookup_display_labels(entry)
            entry["display_general"] = display_general
            entry["display_subclade"] = display_subclade
            entry["lookup_general"] = lookup_general
            entry["lookup_subclade"] = lookup_subclade
            entry["lookup_key"] = f"{lookup_general}|{lookup_subclade}"

        input_name = self._normalize(name)
        targets = [
            entry
            for entry in entries
            if any(self._normalize(variant) == input_name for variant in entry.get("name_variants", [entry["name"]]))
        ]
        if not targets:
            return []

        grouped_targets: dict[str, list[dict[str, str]]] = {}
        for target in targets:
            merge_key = str(target.get("lookup_key") or target["subclade"])
            grouped_targets.setdefault(merge_key, []).append(target)

        results: list[dict[str, str]] = []
        for group in grouped_targets.values():
            target = group[0]
            if not target["haplo"]:
                results.append(
                    {
                        "text": "Найдено имя, но в таблице пустое поле 'гаплогруппа'.",
                        "button_label": "Без гаплогруппы",
                    }
                )
                continue

            origin_seen: set[str] = set()
            origins: list[str] = []
            for item in group:
                origin = item["ancestor"].strip()
                if self._is_placeholder(origin):
                    continue
                key = self._normalize(origin)
                if key in origin_seen:
                    continue
                origin_seen.add(key)
                origins.append(origin)
            origin_display = self._format_origins(origins)

            related_match_keys = {self._related_match_key(item) for item in group}
            seen: set[str] = set()
            same_group: list[str] = []
            for entry in entries:
                if self._related_match_key(entry) not in related_match_keys:
                    continue
                if any(self._normalize(variant) == input_name for variant in entry.get("name_variants", [entry["name"]])):
                    continue
                if self._is_placeholder(entry["name"]):
                    continue

                key = self._normalize(entry["name"])
                if key in seen:
                    continue
                seen.add(key)
                same_group.append(entry["name"])

            display_general = str(target.get("lookup_general") or target.get("display_general") or target["general"] or target["haplo"])
            display_subclade = str(target.get("lookup_subclade") or target.get("display_subclade") or "")
            haplo_emoji = self._emoji_for_haplogroup(target["haplo"], display_general)
            haplo_label = display_general
            if display_subclade and self._normalize_subclade_key(display_subclade) != self._normalize_subclade_key(display_general):
                haplo_label = f"{display_general} - {display_subclade}"
            haplo_display = f"{haplo_emoji} {haplo_label}".strip()
            test_count = len(group)
            button_label = f"{haplo_label} · {test_count}"
            yfull_link = self._get_best_yfull_link(display_general, display_subclade, str(target.get("subclade") or ""))

            result = (
                f"👤 <b>{html.escape(target['name'].upper())}</b>\n\n"
                f"📍 {origin_display}\n\n"
            )

            if yfull_link:
                result += f'🧬 Гаплогруппа: <a href="{html.escape(yfull_link, quote=True)}"><b>{html.escape(haplo_display)}</b></a>\n\n'
            else:
                result += f"🧬 Гаплогруппа: <b>{html.escape(haplo_display)}</b>\n\n"

            if same_group:
                result += (
                    f"👥 <b>Совпадения</b>\n"
                    f"<blockquote>{html.escape(self._format_related_names(same_group))}</blockquote>\n"
                )

            results.append({
                "text": result,
                "button_label": button_label,
                "visual_name": target["name"],
                "visual_haplogroup": haplo_label,
                "visual_haplo_display": haplo_display,
                "visual_general": display_general,
                "visual_subclade": display_subclade,
                "visual_origins": origins,
                "visual_related": same_group,
                "visual_test_count": str(test_count),
                "visual_yfull_link": yfull_link,
            })

        return results

    def get_groups_by_name(self, name: str) -> list[str]:
        return [item["text"] for item in self.get_group_records(name)]

    def _get_lookup_entries(self) -> list[dict[str, str]]:
        rows = self._get_all_values()
        if not rows:
            return []

        headers = rows[0]
        name_indexes = self._find_name_col_indexes(headers)
        haplo_idx = self._find_col_index(headers, ("гаплогруппа", "haplogroup"))
        kit_idx = self._find_col_index(headers, ("kit number", "kit", "номер кита"))
        group_subclade_idx = self._find_group_subclade_col_index(headers)
        if not name_indexes or haplo_idx is None:
            return []

        current_general = ""
        current_subclade = ""
        entries: list[dict[str, str]] = []
        for row in rows[1:]:
            row_name = self._row_display_name(row, name_indexes)
            row_haplo = row[haplo_idx].strip() if len(row) > haplo_idx else ""

            group_general, group_subclade = self._group_from_row(row, kit_idx, group_subclade_idx)
            if group_general:
                current_general = group_general
                current_subclade = group_subclade
                continue

            if self._is_placeholder(row_name) or self._is_placeholder(row_haplo):
                continue

            entries.append(
                {
                    "name": row_name,
                    "haplo": row_haplo,
                    "general": current_general,
                    "subclade": current_subclade,
                }
            )
        return entries

    @staticmethod
    def _is_ystr_marker_header(header: str) -> bool:
        return is_ystr_marker_header(header)

    @staticmethod
    def _parse_ystr_marker_value(value: str) -> list[int]:
        return parse_ystr_marker_value(value)

    @staticmethod
    def _ystr_panel_label(common_markers: int) -> str:
        return ystr_panel_label(common_markers)

    def get_ystr_entries(self) -> list[dict[str, object]]:
        rows = self._get_all_values()
        if not rows:
            return []

        headers = rows[0]
        name_indexes = self._find_name_col_indexes(headers)
        haplo_idx = self._find_col_index(headers, ("гаплогруппа", "haplogroup"))
        kit_idx = self._find_col_index(headers, ("kit number", "kit", "номер кита"))
        group_subclade_idx = self._find_group_subclade_col_index(headers)
        ancestor_idx = self._find_origin_col_index(headers)
        source_idx = self._find_col_index(headers, ("source", "источник"))
        country_idx = self._find_col_index(headers, ("country", "страна"))
        if not name_indexes or haplo_idx is None or kit_idx is None:
            return []

        marker_columns = [
            (index, " ".join(header.split()))
            for index, header in enumerate(headers)
            if self._is_ystr_marker_header(header)
        ]
        current_general = ""
        current_subclade = ""
        entries: list[dict[str, object]] = []
        entry_index = 0

        for row in rows[1:]:
            group_general, group_subclade = self._group_from_row(row, kit_idx, group_subclade_idx)
            if group_general:
                current_general = group_general
                current_subclade = group_subclade
                continue

            name = self._row_display_name(row, name_indexes)
            haplo = row[haplo_idx].strip() if len(row) > haplo_idx else ""
            if self._is_placeholder(name) or self._is_placeholder(haplo):
                continue

            markers: dict[str, list[int]] = {}
            for col_idx, marker in marker_columns:
                raw_value = row[col_idx].strip() if len(row) > col_idx else ""
                parsed = self._parse_ystr_marker_value(raw_value)
                if parsed:
                    markers[marker] = parsed
            adjust_ystr_dys389ii(markers)
            if not markers:
                continue

            display_general = self._distribution_group_label({
                "general": current_general,
                "haplo": haplo,
                "subclade": current_subclade,
            })
            display_subclade = self._subclade_distribution_label({
                "general": current_general,
                "haplo": haplo,
                "subclade": current_subclade,
            })
            ancestor = row[ancestor_idx].strip() if ancestor_idx is not None and len(row) > ancestor_idx else ""
            source = row[source_idx].strip() if source_idx is not None and len(row) > source_idx else ""
            country = row[country_idx].strip() if country_idx is not None and len(row) > country_idx else ""
            entries.append({
                "entry_index": entry_index,
                "name": name,
                "haplo": haplo,
                "ancestor": ancestor,
                "source": source,
                "country": country,
                "general": current_general,
                "subclade": current_subclade,
                "display_general": display_general,
                "display_subclade": display_subclade,
                "markers": markers,
                "marker_count": len(markers),
            })
            entry_index += 1

        return entries

    def get_ystr_records_by_name(self, name: str) -> list[dict[str, object]]:
        query = self._normalize(name)
        if not query:
            return []
        return [
            entry
            for entry in self.get_ystr_entries()
            if self._normalize(str(entry.get("name") or "")) == query
        ]

    def get_ystr_entry_by_index(self, entry_index: int) -> dict[str, object] | None:
        for entry in self.get_ystr_entries():
            try:
                current_index = int(entry.get("entry_index"))
            except (TypeError, ValueError):
                current_index = -1
            if current_index == entry_index:
                return entry
        return None

    def compare_ystr_entries(self, left: dict[str, object], right: dict[str, object]) -> dict[str, object]:
        return compare_ystr_feature_entries(left, right)

    def find_ystr_matches(self, query_entry: dict[str, object], limit: int = 10, min_common: int = 8) -> list[dict[str, object]]:
        return find_ystr_feature_matches(query_entry, self.get_ystr_entries(), limit=limit, min_common=min_common)

    def _distribution_group_label(self, entry: dict[str, str]) -> str:
        return analytics_feature.distribution_group_label(entry)

    def get_haplogroup_distribution(self, mode: str, top_n: int = 10) -> dict[str, object]:
        return analytics_feature.haplogroup_distribution(
            self._get_lookup_entries(),
            mode,
            top_n=top_n,
            emoji_getter=lambda label: self._emoji_for_haplogroup("", label),
        )

    def _subclade_distribution_label(self, entry: dict[str, str]) -> str:
        return analytics_feature.subclade_distribution_label(entry)

    def get_available_haplogroups(self, limit: int = 12) -> list[str]:
        return analytics_feature.available_haplogroups(self._get_lookup_entries(), limit=limit)

    def get_subclade_distribution(self, group: str, mode: str, top_n: int = 10) -> dict[str, object]:
        return analytics_feature.subclade_distribution(
            self._get_lookup_entries(),
            group,
            mode,
            top_n=top_n,
            emoji_getter=lambda label: self._emoji_for_haplogroup("", label),
        )

    def get_navigation_groups(self, limit: int = 16) -> list[dict[str, object]]:
        return analytics_feature.navigation_groups(self._get_lookup_entries(), limit=limit)

    def get_navigation_subclades(self, group: str, limit: int = 20) -> list[dict[str, object]]:
        return analytics_feature.navigation_subclades(self._get_lookup_entries(), group, limit=limit)

    def get_surnames_in_subclade(self, group: str, subclade: str) -> list[str]:
        return analytics_feature.surnames_in_subclade(self._get_lookup_entries(), group, subclade)


class MtdnaSheetsClient:
    HAPLOGROUP_ALIASES = (
        "mtdna",
        "mt dna",
        "mt-dna",
        "митоднк",
        "мтднк",
        "митохондриальная днк",
        "митохондриальная",
        "гаплогруппа",
        "haplogroup",
    )
    NAME_ALIASES = (
        "name",
        "имя",
        "фамилия",
        "род",
        "народ",
        "этнос",
        "популяция",
        "название",
        "образец",
        "sample",
        "surname",
        "family",
        "population",
        "ethnicity",
    )
    LINK_ALIASES = ("ссылка", "ссылки", "link", "links", "url", "yfull", "genbank", "mitomap", "tree")

    def __init__(self, creds_path: str, spreadsheet_id: str, worksheet_name: str = "") -> None:
        if gspread is None or Credentials is None:
            raise RuntimeError("Google Sheets dependencies are not installed. Run: pip install -r requirements.txt")
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets.readonly",
            "https://www.googleapis.com/auth/drive.readonly",
        ]
        creds = Credentials.from_service_account_file(creds_path, scopes=scopes)
        client = gspread.authorize(creds)
        spreadsheet = client.open_by_key(spreadsheet_id)
        self.worksheet = spreadsheet.worksheet(worksheet_name) if worksheet_name else spreadsheet.get_worksheet(0)

    @staticmethod
    def _normalize(value: str) -> str:
        return SheetsClient._normalize(value)

    @staticmethod
    def _is_placeholder(value: str) -> bool:
        return SheetsClient._is_placeholder(value)

    @staticmethod
    def _find_col_index(headers: list[str], aliases: tuple[str, ...]) -> Optional[int]:
        return SheetsClient._find_col_index(headers, aliases)

    @classmethod
    def _normalize_haplogroup(cls, value: str) -> str:
        return analytics_feature.normalize_mtdna_haplogroup(value)

    @staticmethod
    def _major_haplogroup(label: str) -> str:
        return analytics_feature.mtdna_major_haplogroup(label)

    @classmethod
    def _haplogroup_score(cls, value: str) -> int:
        return analytics_feature.mtdna_haplogroup_score(value)

    def _resolve_columns(self, rows: list[list[str]]) -> tuple[Optional[int], Optional[int], dict[int, int]]:
        headers = rows[0]
        haplo_idx = self._find_col_index(headers, self.HAPLOGROUP_ALIASES)
        name_idx = self._find_col_index(headers, self.NAME_ALIASES)
        scores: dict[int, int] = {}
        if haplo_idx is None:
            max_width = max((len(row) for row in rows[:50]), default=0)
            for col_idx in range(max_width):
                score = 0
                for row in rows[1:50]:
                    value = row[col_idx] if len(row) > col_idx else ""
                    score += self._haplogroup_score(value)
                if score:
                    scores[col_idx] = score
            if scores:
                haplo_idx = max(scores.items(), key=lambda item: item[1])[0]
        return haplo_idx, name_idx, scores

    @classmethod
    def _looks_like_link_header(cls, value: str) -> bool:
        normalized = cls._normalize(value)
        return any(alias in normalized for alias in cls.LINK_ALIASES)

    @staticmethod
    def _extract_links_from_cell(value: str) -> list[str]:
        text = str(value or "").strip()
        if not text:
            return []
        links = re.findall(r"https?://[^\s,;<>]+", text)
        return [link.rstrip(").,;") for link in links]

    @classmethod
    def _link_label(cls, header: str, url: str) -> str:
        normalized_header = cls._normalize(header)
        normalized_url = url.lower()
        if "yfull" in normalized_header or "yfull" in normalized_url:
            return "YFull"
        if "genbank" in normalized_header or "genbank" in normalized_url:
            return "GenBank"
        if "mitomap" in normalized_header or "mitomap" in normalized_url:
            return "MITOMAP"
        label = " ".join(str(header or "").split())
        return label[:24] if label else "Ссылка"

    @classmethod
    def _description_for_group(cls, group: str) -> str:
        return mtdna_haplogroup_description_ui(group)

    @classmethod
    def _description_for_subclade(cls, subclade: str) -> str:
        return mtdna_subclade_description_ui(subclade)

    @classmethod
    def _looks_like_display_name(cls, value: str, haplo: str) -> bool:
        text = " ".join(str(value or "").split())
        if not text or cls._is_placeholder(text):
            return False
        if cls._extract_links_from_cell(text):
            return False
        if cls._normalize_haplogroup(text) == haplo:
            return False
        if len(text) > 80:
            return False
        return any(char.isalpha() for char in text)

    @classmethod
    def _row_display_name(
        cls,
        row: list[str],
        *,
        haplo: str,
        haplo_idx: int,
        name_idx: Optional[int],
        link_columns: set[int],
    ) -> str:
        if name_idx is not None and len(row) > name_idx:
            explicit = " ".join(row[name_idx].strip().split())
            if cls._looks_like_display_name(explicit, haplo):
                return explicit

        for col_idx, value in enumerate(row):
            if col_idx == haplo_idx or col_idx == name_idx or col_idx in link_columns:
                continue
            candidate = " ".join(str(value or "").strip().split())
            if cls._looks_like_display_name(candidate, haplo):
                return candidate
        return ""

    def get_schema_summary(self) -> dict[str, object]:
        rows = self.worksheet.get_all_values()
        if not rows:
            return {"worksheet": getattr(self.worksheet, "title", ""), "headers": [], "rows": 0, "status": "empty"}

        headers = rows[0]
        haplo_idx, name_idx, scores = self._resolve_columns(rows)
        parsed_rows = 0
        if haplo_idx is not None:
            for row in rows[1:]:
                raw_haplo = row[haplo_idx].strip() if len(row) > haplo_idx else ""
                if self._normalize_haplogroup(raw_haplo):
                    parsed_rows += 1

        def column_name(index: Optional[int]) -> str:
            if index is None or index >= len(headers):
                return ""
            return headers[index]

        return {
            "worksheet": getattr(self.worksheet, "title", ""),
            "headers": headers,
            "rows": max(0, len(rows) - 1),
            "parsed_rows": parsed_rows,
            "haplo_column": column_name(haplo_idx),
            "haplo_column_index": haplo_idx,
            "name_column": column_name(name_idx),
            "name_column_index": name_idx,
            "auto_scores": scores,
        }

    def _get_entries(self) -> list[dict[str, object]]:
        rows = self.worksheet.get_all_values()
        if not rows:
            return []

        headers = rows[0]
        haplo_idx, name_idx, _scores = self._resolve_columns(rows)
        if haplo_idx is None:
            return []

        link_columns = {
            index
            for index, header in enumerate(headers)
            if self._looks_like_link_header(header)
        }
        entries: list[dict[str, str]] = []
        for row in rows[1:]:
            raw_haplo = row[haplo_idx].strip() if len(row) > haplo_idx else ""
            haplo = self._normalize_haplogroup(raw_haplo)
            if not haplo:
                continue
            name = self._row_display_name(
                row,
                haplo=haplo,
                haplo_idx=haplo_idx,
                name_idx=name_idx,
                link_columns=link_columns,
            )
            links: list[dict[str, str]] = []
            for col_idx, value in enumerate(row):
                if col_idx == haplo_idx or col_idx == name_idx:
                    continue
                urls = self._extract_links_from_cell(value)
                if not urls:
                    continue
                if col_idx not in link_columns and not any("yfull" in url.lower() for url in urls):
                    continue
                header = headers[col_idx] if col_idx < len(headers) else ""
                for url in urls:
                    links.append({"label": self._link_label(header, url), "url": url})
            entries.append({"name": name, "haplo": haplo, "links": links})
        return entries

    def _navigation_count_by_label(self, entries: list[dict[str, object]], label_getter) -> dict[str, int]:
        return analytics_feature.mtdna_navigation_count_by_label(entries, label_getter)

    def get_distribution(self, kind: str, top_n: int = 10) -> dict[str, object]:
        return analytics_feature.mtdna_distribution(self._get_entries(), kind, top_n=top_n)

    def get_navigation_groups(self, limit: int = 16) -> list[dict[str, object]]:
        return analytics_feature.mtdna_navigation_groups(
            self._get_entries(),
            limit=limit,
            description_getter=self._description_for_group,
        )

    def get_navigation_subclades(self, group: str, limit: int = 20) -> list[dict[str, object]]:
        return analytics_feature.mtdna_navigation_subclades(
            self._get_entries(),
            group,
            limit=limit,
            description_getter=self._description_for_subclade,
        )

    def get_entries_in_subclade(self, group: str, subclade: str) -> list[dict[str, object]]:
        return analytics_feature.mtdna_entries_in_subclade(self._get_entries(), group, subclade)


