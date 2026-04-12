from __future__ import annotations

import html
import json
import logging
import os
import re
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional

import gspread
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, ApplicationHandlerStop, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters
from g25_feature.command_service import G25CommandError, G25CommandService

BUILD_ID = "build-2026-04-09-1950"
LOCAL_DB_PATH = Path("haplogroup_info_ru.json")
EMOJI_MAP_PATH = Path("haplogroup_emoji_map.json")
YFULL_LINKS_PATH = Path("yfull_links.json")
USAGE_DB_PATH = Path("usage_stats.sqlite3")
G25_ACCESS_PATH = Path("g25_access.json")
PANEL_COMMAND = "panel"
PANEL_CALLBACK_PREFIX = "panel"
PANEL2_COMMAND = "panel2"
PANEL2_CALLBACK_PREFIX = "panel2"
G25MENU_COMMAND = "g25menu"
G25MENU_CALLBACK_PREFIX = "g25menu"

LOOKUP_START_TEXT = (
    "Привет! Я ищу фамилии в базе KBDNA.\n\n"
    "Отправьте фамилию одним сообщением или используйте <code>/f Фамилия</code>.\n"
    "В ответ я покажу найденные совпадения и данные по ним.\n\n"
    f"Версия: {BUILD_ID}"
)

KIT_GROUP_PREFIXES = (
    "G2A2B2A",
    "G2A2B",
    "G2A2",
    "G2A1A",
    "G2A1",
    "G2A",
    "C2",
    "E1B",
    "H1A",
    "I2A2B",
    "I2A2A",
    "I2A1A",
    "I2B",
    "I",
    "J2A1B",
    "J2A1",
    "J2A",
    "J2B",
    "J2",
    "J1",
    "L",
    "N1A1",
    "N1B",
    "O",
    "Q1A1B",
    "Q1A",
    "R1B1",
    "R1B",
    "R1A",
    "T1A",
    "T",
)


logging.basicConfig(
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


class SheetsClient:
    def __init__(self, creds_path: str, spreadsheet_id: str, worksheet_name: str = "") -> None:
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
        self.local_db = self._load_json(LOCAL_DB_PATH)
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

    @staticmethod
    def _normalize_key(value: str) -> str:
        return value.strip().upper()

    @staticmethod
    def _find_col_index(headers: list[str], aliases: tuple[str, ...]) -> Optional[int]:
        normalized = [h.strip().lower() for h in headers]
        for alias in aliases:
            a = alias.strip().lower()
            if a in normalized:
                return normalized.index(a)
        return None

    @staticmethod
    def _parse_group_path(text: str) -> tuple[str, str]:
        cleaned = " ".join(text.strip().split())
        if not cleaned:
            return "", ""

        match = re.match(r"^([A-Za-z][A-Za-z0-9-]*)\b\s*(.*)$", cleaned)
        if not match:
            return "", ""

        general = match.group(1).strip()
        rest = match.group(2).strip()
        return general, rest

    @staticmethod
    def _kit_value_starts_group(value: str) -> bool:
        normalized = " ".join(value.strip().split()).upper()
        if not normalized:
            return False
        return any(
            normalized == prefix
            or normalized.startswith(f"{prefix} ")
            or normalized.startswith(f"{prefix}-")
            for prefix in KIT_GROUP_PREFIXES
        )

    @classmethod
    def _extract_group_from_kit(cls, kit_value: str) -> tuple[str, str]:
        value = " ".join(kit_value.strip().split())
        if not value or not cls._kit_value_starts_group(value):
            return "", ""
        return cls._parse_group_path(value)

    @classmethod
    def _extract_group_from_row(cls, row: list[str], kit_idx: Optional[int]) -> tuple[str, str]:
        if kit_idx is None or len(row) <= kit_idx:
            return "", ""
        return cls._extract_group_from_kit(row[kit_idx])

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
        candidates = [
            self._normalize_key(personal_haplo),
            self._normalize_key(general_group),
            self._first_letter_group(general_group or personal_haplo),
        ]
        for key in candidates:
            if key and key in self.emoji_map:
                return self.emoji_map[key]
        return "?"

    @staticmethod
    def _normalize_subclade_key(value: str) -> str:
        return " ".join(value.strip().upper().split())

    @staticmethod
    def _extract_terminal_snp(value: str) -> str:
        cleaned = " ".join(value.strip().split())
        if not cleaned:
            return ""

        parts = [part.strip() for part in cleaned.split(">") if part.strip() and part.strip() != "..."]
        for part in reversed(parts):
            base = re.split(r"\s*\(", part, maxsplit=1)[0].strip()
            if base and not re.fullmatch(r"[xX][A-Za-z0-9-]+", base):
                return base.split()[-1]

        tokens = re.findall(r"[A-Za-z][A-Za-z0-9-]*", cleaned)
        for token in reversed(tokens):
            if not re.fullmatch(r"[xX][A-Za-z0-9-]+", token):
                return token
        return ""

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

    def _get_yfull_link(self, general_group: str, subclade: str) -> str:
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

        terminal_snp = self._normalize_subclade_key(self._extract_terminal_snp(subclade))
        if terminal_snp and terminal_snp in by_terminal:
            return by_terminal[terminal_snp]

        return ""

    @staticmethod
    def _looks_russian(text: str) -> bool:
        return bool(re.search(r"[А-Яа-яЁё]", text))

    def _wiki_summary_ru(self, title: str) -> str:
        encoded = urllib.parse.quote(title)
        url = f"https://ru.wikipedia.org/api/rest_v1/page/summary/{encoded}"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "KBDNA-bot/1.0 (haplogroup lookup)"},
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
                text = str(payload.get("extract", "")).strip()
                return text if self._looks_russian(text) else ""
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            return ""

    @staticmethod
    def _first_letter_group(value: str) -> str:
        match = re.match(r"^([A-Za-z])", value.strip())
        return match.group(1).upper() if match else ""

    @staticmethod
    def _shorten(text: str, max_len: int = 520) -> str:
        clean = " ".join(text.split())
        return clean if len(clean) <= max_len else clean[: max_len - 3] + "..."

    def _get_local_info(self, personal_haplo: str, general_group: str) -> str:
        keys = [
            self._normalize_key(personal_haplo),
            self._normalize_key(general_group),
            self._normalize_key((general_group or personal_haplo)[:1]),
        ]
        for key in keys:
            if key and key in self.local_db:
                return self.local_db[key]
        return ""

    def _get_haplogroup_info(self, personal_haplo: str, general_group: str) -> str:
        local = self._get_local_info(personal_haplo, general_group)
        if local:
            return self._shorten(local)

        # Fallback only to Russian web source.
        letter = self._first_letter_group(general_group or personal_haplo)
        candidates = []
        if general_group:
            candidates.append(f"Гаплогруппа {general_group}")
        if letter:
            candidates.append(f"Гаплогруппа {letter}")

        for title in candidates:
            summary = self._wiki_summary_ru(title)
            if summary:
                return self._shorten(summary)

        target = general_group or personal_haplo
        return (
            f"Для ветви {target} пока нет готового описания в локальной базе. "
            "Добавьте текст в haplogroup_info_ru.json."
        )

    def get_groups_by_name(self, name: str) -> list[str]:
        rows = self.worksheet.get_all_values()
        if not rows:
            return ["Таблица пуста."]

        headers = rows[0]
        name_idx = self._find_col_index(headers, ("name", "имя", "фамилия"))
        haplo_idx = self._find_col_index(headers, ("гаплогруппа", "haplogroup"))
        kit_idx = self._find_col_index(headers, ("kit number", "kit", "номер кита"))
        ancestor_idx = self._find_col_index(
            headers,
            (
                "paternal ancestor name",
                "paternal ancestor",
                "предок по отцовской линии",
                "отцовский предок",
                "происхождение",
            ),
        )

        if name_idx is None or haplo_idx is None:
            return ["Не найдены нужные колонки: Name/Имя/Фамилия и/или Гаплогруппа."]

        current_general = ""
        current_subclade = ""
        entries: list[dict[str, str]] = []

        for row in rows[1:]:
            row_name = row[name_idx].strip() if len(row) > name_idx else ""
            row_haplo = row[haplo_idx].strip() if len(row) > haplo_idx else ""
            row_ancestor = row[ancestor_idx].strip() if ancestor_idx is not None and len(row) > ancestor_idx else "-"

            group_general, group_subclade = self._extract_group_from_row(row, kit_idx)
            if group_general:
                current_general = group_general
                current_subclade = group_subclade
                continue

            entries.append(
                {
                    "name": row_name,
                    "haplo": row_haplo,
                    "ancestor": row_ancestor,
                    "general": current_general,
                    "subclade": current_subclade,
                    "group_key": f"{current_general}|{current_subclade}",
                }
            )

        input_name = self._normalize(name)
        targets = [entry for entry in entries if self._normalize(entry["name"]) == input_name]
        if not targets:
            return []

        grouped_targets: dict[str, list[dict[str, str]]] = {}
        for target in targets:
            merge_key = target["subclade"]
            grouped_targets.setdefault(merge_key, []).append(target)

        results: list[str] = []
        for group in grouped_targets.values():
            target = group[0]
            if not target["haplo"]:
                results.append("Найдено имя, но в таблице пустое поле 'гаплогруппа'.")
                continue

            haplo_with_group = target["haplo"]
            if target["general"]:
                haplo_with_group = f"{target['haplo']} ({target['general']})"

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

            seen: set[str] = set()
            same_group: list[str] = []
            for entry in entries:
                if entry["group_key"] != target["group_key"]:
                    continue
                if self._normalize(entry["name"]) == input_name:
                    continue
                if self._is_placeholder(entry["name"]):
                    continue

                key = self._normalize(entry["name"])
                if key in seen:
                    continue
                seen.add(key)
                same_group.append(entry["name"])

            haplo_emoji = self._emoji_for_haplogroup(target["haplo"], target["general"])
            terminal_snp = self._extract_terminal_snp(target["subclade"])
            haplo_label = target["general"] or target["haplo"]
            if terminal_snp:
                haplo_label = f"{haplo_label} ({terminal_snp})"
            haplo_display = f"{haplo_emoji} {haplo_label}".strip()
            yfull_link = self._get_yfull_link(target["general"], target["subclade"])

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
                    f"<blockquote>{html.escape(', '.join(same_group))}</blockquote>\n"
                )

            results.append(result)

        return results



class UsageStore:
    @staticmethod
    def _looks_like_surname_query(value: str) -> bool:
        query = (value or "").strip()
        if not query:
            return False
        if len(query) > 40:
            return False
        if "," in query or "\n" in query:
            return False
        if any(ch.isdigit() for ch in query):
            return False
        if not re.fullmatch(r"[A-Za-zА-Яа-яЁё\-\s]+", query):
            return False
        return True

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _existing_columns(self) -> set[str]:
        with self._connect() as conn:
            rows = conn.execute("PRAGMA table_info(usage_events)").fetchall()
        return {row[1] for row in rows}

    def _ensure_column(self, name: str, sql_type: str, default_sql: str | None = None) -> None:
        columns = self._existing_columns()
        if name in columns:
            return

        default_clause = f" DEFAULT {default_sql}" if default_sql is not None else ""
        with self._connect() as conn:
            conn.execute(f"ALTER TABLE usage_events ADD COLUMN {name} {sql_type}{default_clause}")

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS usage_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    user_id INTEGER,
                    username TEXT,
                    full_name TEXT,
                    chat_id INTEGER,
                    chat_type TEXT,
                    query TEXT,
                    success INTEGER NOT NULL
                )
                """
            )
        self._ensure_column("event_type", "TEXT", "'lookup'")
        self._ensure_column("command", "TEXT")
        self._ensure_column("input_mode", "TEXT")

    def record_lookup(self, update: Update, query: str, success: bool) -> None:
        self.record_event(
            update=update,
            query=query,
            success=success,
            event_type="lookup",
            command="f",
            input_mode="text",
        )

    def record_g25(
        self,
        update: Update,
        command: str,
        input_mode: str,
        success: bool,
        query: str | None = None,
    ) -> None:
        self.record_event(
            update=update,
            query=query or "",
            success=success,
            event_type="g25",
            command=command,
            input_mode=input_mode,
        )

    def record_event(
        self,
        update: Update,
        query: str,
        success: bool,
        event_type: str,
        command: str | None = None,
        input_mode: str | None = None,
    ) -> None:
        user = update.effective_user
        chat = update.effective_chat
        full_name = " ".join(
            part for part in [getattr(user, "first_name", "") or "", getattr(user, "last_name", "") or ""] if part
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO usage_events (
                    user_id, username, full_name, chat_id, chat_type, query, success, event_type, command, input_mode
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    getattr(user, "id", None),
                    getattr(user, "username", None),
                    full_name or None,
                    getattr(chat, "id", None),
                    getattr(chat, "type", None),
                    query,
                    1 if success else 0,
                    event_type,
                    command,
                    input_mode,
                ),
            )

    def get_summary(self) -> dict[str, object]:
        with self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) FROM usage_events").fetchone()[0]
            success = conn.execute("SELECT COUNT(*) FROM usage_events WHERE success = 1").fetchone()[0]
            unique_users = conn.execute(
                "SELECT COUNT(DISTINCT user_id) FROM usage_events WHERE user_id IS NOT NULL"
            ).fetchone()[0]
            today = conn.execute(
                "SELECT COUNT(*) FROM usage_events WHERE date(created_at, 'localtime') = date('now', 'localtime')"
            ).fetchone()[0]
            last_7_days = conn.execute(
                """
                SELECT COUNT(*) FROM usage_events
                WHERE datetime(created_at, 'localtime') >= datetime('now', '-6 days', 'localtime')
                """
            ).fetchone()[0]
            lookup_total = conn.execute(
                "SELECT COUNT(*) FROM usage_events WHERE event_type = 'lookup'"
            ).fetchone()[0]
            lookup_success = conn.execute(
                "SELECT COUNT(*) FROM usage_events WHERE event_type = 'lookup' AND success = 1"
            ).fetchone()[0]
            lookup_today = conn.execute(
                """
                SELECT COUNT(*) FROM usage_events
                WHERE event_type = 'lookup' AND date(created_at, 'localtime') = date('now', 'localtime')
                """
            ).fetchone()[0]
            lookup_last_7_days = conn.execute(
                """
                SELECT COUNT(*) FROM usage_events
                WHERE event_type = 'lookup' AND datetime(created_at, 'localtime') >= datetime('now', '-6 days', 'localtime')
                """
            ).fetchone()[0]
            lookup_unique_users = conn.execute(
                "SELECT COUNT(DISTINCT user_id) FROM usage_events WHERE event_type = 'lookup' AND user_id IS NOT NULL"
            ).fetchone()[0]
            g25_total = conn.execute(
                "SELECT COUNT(*) FROM usage_events WHERE event_type = 'g25'"
            ).fetchone()[0]
            g25_success = conn.execute(
                "SELECT COUNT(*) FROM usage_events WHERE event_type = 'g25' AND success = 1"
            ).fetchone()[0]
            g25_today = conn.execute(
                """
                SELECT COUNT(*) FROM usage_events
                WHERE event_type = 'g25' AND date(created_at, 'localtime') = date('now', 'localtime')
                """
            ).fetchone()[0]
            g25_last_7_days = conn.execute(
                """
                SELECT COUNT(*) FROM usage_events
                WHERE event_type = 'g25' AND datetime(created_at, 'localtime') >= datetime('now', '-6 days', 'localtime')
                """
            ).fetchone()[0]
            g25_unique_users = conn.execute(
                "SELECT COUNT(DISTINCT user_id) FROM usage_events WHERE event_type = 'g25' AND user_id IS NOT NULL"
            ).fetchone()[0]
            g25_3 = conn.execute(
                "SELECT COUNT(*) FROM usage_events WHERE event_type = 'g25' AND command = '3'"
            ).fetchone()[0]
            g25_4 = conn.execute(
                "SELECT COUNT(*) FROM usage_events WHERE event_type = 'g25' AND command = '4'"
            ).fetchone()[0]
            g25_extract = conn.execute(
                "SELECT COUNT(*) FROM usage_events WHERE event_type = 'g25' AND command = 'g25'"
            ).fetchone()[0]
            g25_steppe = conn.execute(
                "SELECT COUNT(*) FROM usage_events WHERE event_type = 'g25' AND command = 'steppe'"
            ).fetchone()[0]
            g25_panel = conn.execute(
                "SELECT COUNT(*) FROM usage_events WHERE event_type = 'g25' AND command = 'panel'"
            ).fetchone()[0]
            g25_panel2 = conn.execute(
                "SELECT COUNT(*) FROM usage_events WHERE event_type = 'g25' AND command = 'panel2'"
            ).fetchone()[0]
            g25_raw = conn.execute(
                "SELECT COUNT(*) FROM usage_events WHERE event_type = 'g25' AND input_mode = 'raw-file'"
            ).fetchone()[0]
            g25_text = conn.execute(
                "SELECT COUNT(*) FROM usage_events WHERE event_type = 'g25' AND input_mode IN ('g25-text', 'g25-file')"
            ).fetchone()[0]
            top_queries = conn.execute(
                """
                SELECT query, COUNT(*) AS cnt
                FROM usage_events
                WHERE event_type = 'lookup' AND query IS NOT NULL AND TRIM(query) <> ''
                GROUP BY query
                ORDER BY cnt DESC, query COLLATE NOCASE ASC
                LIMIT 10
                """
            ).fetchall()

        success_rate = round((success / total) * 100, 1) if total else 0.0
        lookup_success_rate = round((lookup_success / lookup_total) * 100, 1) if lookup_total else 0.0
        g25_success_rate = round((g25_success / g25_total) * 100, 1) if g25_total else 0.0
        return {
            "total": total,
            "success": success,
            "success_rate": success_rate,
            "unique_users": unique_users,
            "today": today,
            "last_7_days": last_7_days,
            "lookup_total": lookup_total,
            "lookup_success": lookup_success,
            "lookup_success_rate": lookup_success_rate,
            "lookup_today": lookup_today,
            "lookup_last_7_days": lookup_last_7_days,
            "lookup_unique_users": lookup_unique_users,
            "g25_total": g25_total,
            "g25_success": g25_success,
            "g25_success_rate": g25_success_rate,
            "g25_today": g25_today,
            "g25_last_7_days": g25_last_7_days,
            "g25_unique_users": g25_unique_users,
            "g25_3": g25_3,
            "g25_4": g25_4,
            "g25_extract": g25_extract,
            "g25_steppe": g25_steppe,
            "g25_panel": g25_panel,
            "g25_panel2": g25_panel2,
            "g25_raw": g25_raw,
            "g25_text": g25_text,
            "top_queries": [(row[0], row[1]) for row in top_queries],
        }



class G25AccessStore:
    def __init__(self, path: Path, admin_ids: set[int] | None = None, admin_usernames: set[str] | None = None) -> None:
        self.path = path
        self.admin_ids = set(admin_ids or set())
        self.admin_usernames = {self._normalize_username(item) for item in (admin_usernames or set()) if item}
        self._ensure_file()

    @staticmethod
    def _normalize_username(value: str | None) -> str:
        if not value:
            return ""
        return value.strip().lstrip("@").lower()

    def _ensure_file(self) -> None:
        if self.path.exists():
            return
        payload = {"allowed_user_ids": [], "allowed_usernames": []}
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')

    def _load(self) -> dict[str, list]:
        self._ensure_file()
        try:
            data = json.loads(self.path.read_text(encoding='utf-8'))
        except Exception:
            data = {}
        return {
            "allowed_user_ids": [int(x) for x in data.get("allowed_user_ids", []) if str(x).strip()],
            "allowed_usernames": [self._normalize_username(x) for x in data.get("allowed_usernames", []) if str(x).strip()],
        }

    def _save(self, data: dict[str, list]) -> None:
        payload = {
            "allowed_user_ids": sorted({int(x) for x in data.get("allowed_user_ids", [])}),
            "allowed_usernames": sorted({self._normalize_username(x) for x in data.get("allowed_usernames", []) if x}),
        }
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')

    def has_rules(self) -> bool:
        data = self._load()
        return bool(data["allowed_user_ids"] or data["allowed_usernames"])

    def is_admin(self, update: Update) -> bool:
        user = update.effective_user
        if user is None:
            return False
        username = self._normalize_username(getattr(user, "username", None))
        return getattr(user, "id", None) in self.admin_ids or username in self.admin_usernames

    def is_allowed(self, update: Update) -> bool:
        user = update.effective_user
        if user is None:
            return False
        if self.is_admin(update):
            return True
        data = self._load()
        if not data["allowed_user_ids"] and not data["allowed_usernames"]:
            return True
        username = self._normalize_username(getattr(user, "username", None))
        return getattr(user, "id", None) in data["allowed_user_ids"] or username in data["allowed_usernames"]

    def allow_username(self, username: str) -> str:
        data = self._load()
        normalized = self._normalize_username(username)
        if normalized and normalized not in data["allowed_usernames"]:
            data["allowed_usernames"].append(normalized)
            self._save(data)
        return f"@{normalized}"

    def allow_user_id(self, user_id: int) -> str:
        data = self._load()
        if user_id not in data["allowed_user_ids"]:
            data["allowed_user_ids"].append(user_id)
            self._save(data)
        return str(user_id)

    def deny_username(self, username: str) -> str:
        data = self._load()
        normalized = self._normalize_username(username)
        data["allowed_usernames"] = [item for item in data["allowed_usernames"] if item != normalized]
        self._save(data)
        return f"@{normalized}"

    def deny_user_id(self, user_id: int) -> str:
        data = self._load()
        data["allowed_user_ids"] = [item for item in data["allowed_user_ids"] if int(item) != int(user_id)]
        self._save(data)
        return str(user_id)

    def format_list(self) -> str:
        data = self._load()
        usernames = ", ".join(f"@{item}" for item in data["allowed_usernames"]) or "-"
        ids = ", ".join(str(item) for item in data["allowed_user_ids"]) or "-"
        mode = "\u043e\u0442\u043a\u0440\u044b\u0442 \u0432\u0441\u0435\u043c" if not self.has_rules() else "\u0442\u043e\u043b\u044c\u043a\u043e \u043f\u043e \u0441\u043f\u0438\u0441\u043a\u0443"
        lines = [
            "<b>G25 \u0434\u043e\u0441\u0442\u0443\u043f</b>",
            "",
            f"\u0420\u0435\u0436\u0438\u043c: {mode}",
            f"Usernames: {usernames}",
            f"User IDs: {ids}",
        ]
        return "\n".join(lines)

def get_required_env(name: str, *aliases: str) -> str:
    value = os.getenv(name)
    if not value:
        value = os.getenv(f"\ufeff{name}")
    if not value:
        for alias in aliases:
            value = os.getenv(alias)
            if value:
                break
    if not value:
        names = ", ".join((name, *aliases))
        raise RuntimeError(f"Environment variable {names} is required")
    return value


class CustomPanelStore:
    def __init__(self) -> None:
        self._states: dict[tuple[int, int], dict[str, object]] = {}

    @staticmethod
    def _key(chat_id: int, user_id: int) -> tuple[int, int]:
        return (int(chat_id), int(user_id))

    def open(self, chat_id: int, user_id: int) -> dict[str, object]:
        key = self._key(chat_id, user_id)
        current = self._states.get(key, {})
        state = {
            "selected": list(current.get("selected", [])),
            "awaiting_input": False,
            "message_id": current.get("message_id"),
        }
        self._states[key] = state
        return state

    def set_message_id(self, chat_id: int, user_id: int, message_id: int) -> None:
        key = self._key(chat_id, user_id)
        state = self._states.setdefault(key, {"selected": [], "awaiting_input": False, "message_id": None})
        state["message_id"] = int(message_id)

    def get(self, chat_id: int, user_id: int) -> dict[str, object] | None:
        return self._states.get(self._key(chat_id, user_id))

    def get_selected(self, chat_id: int, user_id: int) -> list[str]:
        state = self.get(chat_id, user_id)
        if not state:
            return []
        return list(state.get("selected", []))

    def toggle(self, chat_id: int, user_id: int, source_key: str) -> list[str]:
        key = self._key(chat_id, user_id)
        state = self._states.setdefault(key, {"selected": [], "awaiting_input": False, "message_id": None})
        selected = list(state.get("selected", []))
        if source_key in selected:
            selected.remove(source_key)
        else:
            selected.append(source_key)
        state["selected"] = selected
        state["awaiting_input"] = False
        return selected

    def clear(self, chat_id: int, user_id: int) -> None:
        key = self._key(chat_id, user_id)
        state = self._states.setdefault(key, {"selected": [], "awaiting_input": False, "message_id": None})
        state["selected"] = []
        state["awaiting_input"] = False

    def finish(self, chat_id: int, user_id: int) -> list[str]:
        key = self._key(chat_id, user_id)
        state = self._states.setdefault(key, {"selected": [], "awaiting_input": False, "message_id": None})
        state["awaiting_input"] = True
        return list(state.get("selected", []))

    def has_pending(self, chat_id: int, user_id: int) -> bool:
        state = self.get(chat_id, user_id)
        return bool(state and state.get("awaiting_input"))

    def clear_pending(self, chat_id: int, user_id: int) -> None:
        state = self.get(chat_id, user_id)
        if state:
            state["awaiting_input"] = False

    def cancel(self, chat_id: int, user_id: int) -> None:
        self._states.pop(self._key(chat_id, user_id), None)


def _panel_source_emoji(source_key: str) -> str:
    return {
        "maikop": "\U0001F3D4\uFE0F",
        "steppe_sintashta": "\U0001F40E",
        "ulaanzhukh": "\U0001F3F9",
        "yamnaya": "\U0001F40E",
        "yellowriver": "\u26E9\uFE0F",
        "anatolia_ba": "\U0001F3FA",
        "baltic_ba": "\U0001F332",
        "bmac": "\u2600\uFE0F",
        "khovsgol": "\U0001F3F9",
        "kuraaraxes": "\U0001F3D4\uFE0F",
    }.get(source_key, "")


def _build_panel_keyboard(service: G25CommandService, selected_keys: list[str]) -> InlineKeyboardMarkup:
    source_defs = service.list_custom_sources()
    rows: list[list[InlineKeyboardButton]] = []
    for idx in range(0, len(source_defs), 2):
        row: list[InlineKeyboardButton] = []
        for item in source_defs[idx: idx + 2]:
            checked = "[x] " if item["key"] in selected_keys else ""
            emoji = _panel_source_emoji(str(item["key"]))
            prefix = f"{emoji} " if emoji else ""
            row.append(
                InlineKeyboardButton(
                    text=f"{checked}{prefix}{item['label']}",
                    callback_data=f"{PANEL_CALLBACK_PREFIX}:toggle:{item['key']}",
                )
            )
        rows.append(row)
    rows.append(
        [
            InlineKeyboardButton("\u0413\u043e\u0442\u043e\u0432\u043e", callback_data=f"{PANEL_CALLBACK_PREFIX}:done"),
            InlineKeyboardButton("\u041e\u0447\u0438\u0441\u0442\u0438\u0442\u044c", callback_data=f"{PANEL_CALLBACK_PREFIX}:clear"),
        ]
    )
    rows.append(
        [
            InlineKeyboardButton("\u041d\u0430\u0437\u0430\u0434 \u043a \u043f\u0430\u043d\u0435\u043b\u044f\u043c", callback_data=f"{G25MENU_CALLBACK_PREFIX}:panels"),
            InlineKeyboardButton("\u041e\u0442\u043c\u0435\u043d\u0430", callback_data=f"{PANEL_CALLBACK_PREFIX}:cancel"),
        ]
    )
    return InlineKeyboardMarkup(rows)
def _format_panel_selection(service: G25CommandService, selected_keys: list[str]) -> str:
    labels: list[str] = []
    for item in service.list_custom_sources():
        if item["key"] not in selected_keys:
            continue
        emoji = _panel_source_emoji(str(item["key"]))
        prefix = f"{emoji} " if emoji else ""
        labels.append(f"{prefix}{item['label']}")
    if not labels:
        return "- \u043f\u043e\u043a\u0430 \u043d\u0438\u0447\u0435\u0433\u043e"
    return "\n".join(f"- {label}" for label in labels)


def _panel_builder_text(service: G25CommandService, selected_keys: list[str], ready: bool = False) -> str:
    chosen = _format_panel_selection(service, selected_keys)
    lines = [
        "Конструктор панели",
        "",
        "Выберите древние источники кнопками ниже.",
        "",
        "Выбрано:",
        chosen,
    ]
    if ready:
        lines.extend([
            "",
            "Теперь отправьте raw-файл или G25-координаты следующим сообщением.",
            "Если вы в группе, отправляйте их ответом на это сообщение.",
        ])
    return "\n".join(lines)
def _build_panel_ready_keyboard(prefix: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[
            InlineKeyboardButton("\u041d\u0430\u0437\u0430\u0434 \u043a \u043f\u0430\u043d\u0435\u043b\u044f\u043c", callback_data=f"{G25MENU_CALLBACK_PREFIX}:panels"),
            InlineKeyboardButton("\u041e\u0442\u043c\u0435\u043d\u0430", callback_data=f"{prefix}:cancel"),
        ]]
    )


def _build_panel2_keyboard(service: G25CommandService, selected_keys: list[str]) -> InlineKeyboardMarkup:
    source_defs = service.list_panel2_sources()
    rows: list[list[InlineKeyboardButton]] = []
    for idx in range(0, len(source_defs), 2):
        row: list[InlineKeyboardButton] = []
        for item in source_defs[idx: idx + 2]:
            checked = "[x] " if item["key"] in selected_keys else ""
            emoji = f"{item.get('emoji', '')} " if item.get("emoji") else ""
            row.append(
                InlineKeyboardButton(
                    text=f"{checked}{emoji}{item['label']}",
                    callback_data=f"{PANEL2_CALLBACK_PREFIX}:toggle:{item['key']}",
                )
            )
        rows.append(row)
    rows.append(
        [
            InlineKeyboardButton("\u0413\u043e\u0442\u043e\u0432\u043e", callback_data=f"{PANEL2_CALLBACK_PREFIX}:done"),
            InlineKeyboardButton("\u041e\u0447\u0438\u0441\u0442\u0438\u0442\u044c", callback_data=f"{PANEL2_CALLBACK_PREFIX}:clear"),
        ]
    )
    rows.append(
        [
            InlineKeyboardButton("\u041d\u0430\u0437\u0430\u0434 \u043a \u043f\u0430\u043d\u0435\u043b\u044f\u043c", callback_data=f"{G25MENU_CALLBACK_PREFIX}:panels"),
            InlineKeyboardButton("\u041e\u0442\u043c\u0435\u043d\u0430", callback_data=f"{PANEL2_CALLBACK_PREFIX}:cancel"),
        ]
    )
    return InlineKeyboardMarkup(rows)
def _format_panel2_selection(service: G25CommandService, selected_keys: list[str]) -> str:
    labels: list[str] = []
    for item in service.list_panel2_sources():
        if item["key"] not in selected_keys:
            continue
        emoji = f"{item.get('emoji', '')} " if item.get("emoji") else ""
        labels.append(f"{emoji}{item['label']}")
    if not labels:
        return "- \u043f\u043e\u043a\u0430 \u043d\u0438\u0447\u0435\u0433\u043e"
    return "\n".join(f"- {label}" for label in labels)


def _panel2_builder_text(service: G25CommandService, selected_keys: list[str], ready: bool = False) -> str:
    chosen = _format_panel2_selection(service, selected_keys)
    lines = [
        "Конструктор панели 2",
        "",
        "Выберите древние источники кнопками ниже.",
        "",
        "Выбрано:",
        chosen,
    ]
    if ready:
        lines.extend([
            "",
            "Теперь отправьте raw-файл или G25-координаты следующим сообщением.",
            "Если вы в группе, отправляйте их ответом на это сообщение.",
        ])
    return "\n".join(lines)
def _build_g25menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Панели", callback_data=f"{G25MENU_CALLBACK_PREFIX}:panels"),
            InlineKeyboardButton("Координаты", callback_data=f"{G25MENU_CALLBACK_PREFIX}:coords"),
        ],
        [
            InlineKeyboardButton("Отмена", callback_data=f"{G25MENU_CALLBACK_PREFIX}:cancel"),
        ],
    ])
def _g25menu_text() -> str:
    return "\U0001F9EC \u0412\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u0440\u0435\u0436\u0438\u043c G25:"


def _build_g25panels_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Panel", callback_data=f"{G25MENU_CALLBACK_PREFIX}:panel"),
            InlineKeyboardButton("Panel 2", callback_data=f"{G25MENU_CALLBACK_PREFIX}:panel2"),
        ],
        [
            InlineKeyboardButton("Назад", callback_data=f"{G25MENU_CALLBACK_PREFIX}:root"),
            InlineKeyboardButton("Отмена", callback_data=f"{G25MENU_CALLBACK_PREFIX}:cancel"),
        ],
    ])
def _g25panels_text() -> str:
    return "\U0001F9EC \u0412\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u043f\u0430\u043d\u0435\u043b\u044c:"


def _build_g25coords_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Получить G25", callback_data=f"{G25MENU_CALLBACK_PREFIX}:coords_sim"),
        ],
        [
            InlineKeyboardButton("Назад", callback_data=f"{G25MENU_CALLBACK_PREFIX}:root"),
            InlineKeyboardButton("Отмена", callback_data=f"{G25MENU_CALLBACK_PREFIX}:cancel"),
        ],
    ])
def _g25coords_menu_text() -> str:
    return "\U0001F9EC \u0412\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u0442\u0438\u043f \u043a\u043e\u043e\u0440\u0434\u0438\u043d\u0430\u0442:"


def _build_g25coords_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("\u041d\u0430\u0437\u0430\u0434", callback_data=f"{G25MENU_CALLBACK_PREFIX}:coords"),
            InlineKeyboardButton("\u041e\u0442\u043c\u0435\u043d\u0430", callback_data=f"{G25MENU_CALLBACK_PREFIX}:coords_cancel"),
        ],
    ])


def _g25coords_text() -> str:
    return (
        "\U0001F9EC Получение G25\n\n"
        "Пришлите raw-файл документом. Я извлеку из него G25-координаты.\n"
        "Если вы в группе, отправляйте файл ответом на это сообщение."
    )
async def _send_panel_builder_message(
    *,
    message,
    context: ContextTypes.DEFAULT_TYPE,
    panel_name: str,
    chat_id: int,
    user_id: int,
    edit_existing: bool = False,
) -> None:
    service: G25CommandService = context.application.bot_data["g25_service"]
    if panel_name == "panel":
        panel_store: CustomPanelStore = context.application.bot_data["panel_store"]
        state = panel_store.open(chat_id, user_id)
        selected = list(state.get("selected", []))
        builder_text = _panel_builder_text(service, selected)
        builder_markup = _build_panel_keyboard(service, selected)
        if edit_existing:
            await message.edit_text(builder_text, reply_markup=builder_markup)
            panel_store.set_message_id(chat_id, user_id, message.message_id)
        else:
            sent = await message.reply_text(
                builder_text,
                reply_markup=builder_markup,
                do_quote=False,
            )
            panel_store.set_message_id(chat_id, user_id, sent.message_id)
        return

    panel_store = context.application.bot_data["panel2_store"]
    state = panel_store.open(chat_id, user_id)
    selected = list(state.get("selected", []))
    builder_text = _panel2_builder_text(service, selected)
    builder_markup = _build_panel2_keyboard(service, selected)
    if edit_existing:
        await message.edit_text(builder_text, reply_markup=builder_markup)
        panel_store.set_message_id(chat_id, user_id, message.message_id)
    else:
        sent = await message.reply_text(
            builder_text,
            reply_markup=builder_markup,
            do_quote=False,
        )
        panel_store.set_message_id(chat_id, user_id, sent.message_id)


def _clear_g25_pending_states(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int) -> None:
    panel_store: CustomPanelStore = context.application.bot_data["panel_store"]
    panel2_store: CustomPanelStore = context.application.bot_data["panel2_store"]
    coords_store: CustomPanelStore = context.application.bot_data["coords_store"]
    panel_store.clear_pending(chat_id, user_id)
    panel2_store.clear_pending(chat_id, user_id)
    coords_store.clear_pending(chat_id, user_id)


def _cancel_g25_menu(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int) -> None:
    panel_store: CustomPanelStore = context.application.bot_data["panel_store"]
    panel2_store: CustomPanelStore = context.application.bot_data["panel2_store"]
    coords_store: CustomPanelStore = context.application.bot_data["coords_store"]
    panel_store.cancel(chat_id, user_id)
    panel2_store.cancel(chat_id, user_id)
    coords_store.cancel(chat_id, user_id)
async def g25menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.effective_user is None:
        return

    access_store: G25AccessStore = context.application.bot_data["g25_access_store"]
    if not access_store.is_allowed(update):
        await update.message.reply_text("G25-\u0444\u0443\u043d\u043a\u0446\u0438\u044f \u0434\u043e\u0441\u0442\u0443\u043f\u043d\u0430 \u0442\u043e\u043b\u044c\u043a\u043e \u0434\u043b\u044f \u0440\u0430\u0437\u0440\u0435\u0448\u0435\u043d\u043d\u044b\u0445 \u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u0435\u0439.", do_quote=False)
        return

    await update.message.reply_text(
        _g25menu_text(),
        reply_markup=_build_g25menu_keyboard(),
        do_quote=False,
    )


async def g25menu_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None or query.message is None:
        return
    if not query.data.startswith(f"{G25MENU_CALLBACK_PREFIX}:"):
        return

    await query.answer()
    if update.effective_chat is None or update.effective_user is None:
        return

    access_store: G25AccessStore = context.application.bot_data["g25_access_store"]
    if not access_store.is_allowed(update):
        await query.answer("Нет доступа к G25.", show_alert=True)
        return

    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    action = query.data.split(":", 1)[1]

    if action == "root":
        _clear_g25_pending_states(context, chat_id, user_id)
        await query.edit_message_text(_g25menu_text(), reply_markup=_build_g25menu_keyboard())
        return

    if action == "panels":
        _clear_g25_pending_states(context, chat_id, user_id)
        await query.edit_message_text(_g25panels_text(), reply_markup=_build_g25panels_keyboard())
        return

    if action == "coords":
        _clear_g25_pending_states(context, chat_id, user_id)
        await query.edit_message_text(_g25coords_menu_text(), reply_markup=_build_g25coords_menu_keyboard())
        return

    if action == "coords_sim":
        _clear_g25_pending_states(context, chat_id, user_id)
        coords_store: CustomPanelStore = context.application.bot_data["coords_store"]
        coords_store.open(chat_id, user_id)
        coords_store.set_message_id(chat_id, user_id, query.message.message_id)
        coords_store.finish(chat_id, user_id)
        await query.edit_message_text(_g25coords_text(), reply_markup=_build_g25coords_keyboard())
        return

    if action in {"coords_cancel", "cancel"}:
        _cancel_g25_menu(context, chat_id, user_id)
        await query.edit_message_text("G25 меню закрыто.")
        return

    if action not in {"panel", "panel2"}:
        return

    _clear_g25_pending_states(context, chat_id, user_id)
    await _send_panel_builder_message(
        message=query.message,
        context=context,
        panel_name=action,
        chat_id=chat_id,
        user_id=user_id,
        edit_existing=True,
    )
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return

    await update.message.reply_text(
        LOOKUP_START_TEXT,
        parse_mode="HTML",
        do_quote=False,
    )



async def build_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    await update.message.reply_text(BUILD_ID, do_quote=False)


async def handle_lookup(update: Update, context: ContextTypes.DEFAULT_TYPE, name: str) -> None:
    sheets: SheetsClient = context.application.bot_data["sheets"]
    usage_store: UsageStore = context.application.bot_data["usage_store"]
    normalized_name = " ".join(name.split())

    try:
        values = sheets.get_groups_by_name(name)
    except Exception:
        logger.exception("Sheets read error")
        usage_store.record_lookup(update, normalized_name, success=False)
        await update.message.reply_text(
            "Не удалось получить данные из таблицы. Попробуйте чуть позже.",
            do_quote=False,
        )
        return

    if not values:
        usage_store.record_lookup(update, normalized_name, success=False)
        await update.message.reply_text(
            (
                f"Фамилия <b>{html.escape(normalized_name)}</b> не найдена в текущей базе.\n"
                "Проверьте написание и попробуйте другой вариант."
            ),
            parse_mode="HTML",
            do_quote=False,
        )
        return

    usage_store.record_lookup(update, normalized_name, success=True)

    for value in values:
        await update.message.reply_text(value, parse_mode="HTML", do_quote=False)



async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return

    usage_store: UsageStore = context.application.bot_data["usage_store"]
    stats = usage_store.get_summary()
    top_queries = stats["top_queries"]
    top_lines = [f"{idx}. {query} - {count}" for idx, (query, count) in enumerate(top_queries, start=1)]
    top_block = "\n".join(top_lines) if top_lines else "\u041f\u043e\u043a\u0430 \u043d\u0435\u0442 \u0434\u0430\u043d\u043d\u044b\u0445"

    if update.effective_chat is None or update.effective_chat.type != "private":
        lines = [
            "\U0001F50E <b>\u0421\u0442\u0430\u0442\u0438\u0441\u0442\u0438\u043a\u0430 \u043f\u043e \u0444\u0430\u043c\u0438\u043b\u0438\u044f\u043c</b>",
            "",
            top_block,
        ]
        await update.message.reply_text("\n".join(lines), parse_mode="HTML", do_quote=False)
        return

    lines = [
        "\U0001F50E <b>\u0421\u0442\u0430\u0442\u0438\u0441\u0442\u0438\u043a\u0430 \u043f\u043e \u0444\u0430\u043c\u0438\u043b\u0438\u044f\u043c</b>",
        "",
        f"\u0412\u0441\u0435\u0433\u043e \u0437\u0430\u043f\u0440\u043e\u0441\u043e\u0432: {stats['lookup_total']}",
        f"\u0423\u0441\u043f\u0435\u0448\u043d\u044b\u0445: {stats['lookup_success']} ({stats['lookup_success_rate']}%)",
        f"\u0417\u0430 \u0441\u0435\u0433\u043e\u0434\u043d\u044f: {stats['lookup_today']}",
        f"\u0417\u0430 7 \u0434\u043d\u0435\u0439: {stats['lookup_last_7_days']}",
        f"\u0423\u043d\u0438\u043a\u0430\u043b\u044c\u043d\u044b\u0445 \u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u0435\u0439: {stats['lookup_unique_users']}",
        "",
        f"\U0001F3F7 \u0422\u043e\u043f \u0444\u0430\u043c\u0438\u043b\u0438\u0439\n{top_block}",
    ]
    await update.message.reply_text("\n".join(lines), parse_mode="HTML", do_quote=False)


async def g25stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return

    access_store: G25AccessStore = context.application.bot_data["g25_access_store"]
    if not access_store.is_admin(update):
        await update.message.reply_text("\u041a\u043e\u043c\u0430\u043d\u0434\u0430 \u0434\u043e\u0441\u0442\u0443\u043f\u043d\u0430 \u0442\u043e\u043b\u044c\u043a\u043e \u0430\u0434\u043c\u0438\u043d\u0438\u0441\u0442\u0440\u0430\u0442\u043e\u0440\u0443 G25.", do_quote=False)
        return

    usage_store: UsageStore = context.application.bot_data["usage_store"]
    stats = usage_store.get_summary()

    lines = [
        "\U0001F9EC <b>\u0421\u0442\u0430\u0442\u0438\u0441\u0442\u0438\u043a\u0430 G25</b>",
        "",
        f"\u0412\u0441\u0435\u0433\u043e \u0437\u0430\u043f\u0440\u043e\u0441\u043e\u0432: {stats['g25_total']}",
        f"\u0423\u0441\u043f\u0435\u0448\u043d\u044b\u0445: {stats['g25_success']} ({stats['g25_success_rate']}%)",
        f"\u0417\u0430 \u0441\u0435\u0433\u043e\u0434\u043d\u044f: {stats['g25_today']}",
        f"\u0417\u0430 7 \u0434\u043d\u0435\u0439: {stats['g25_last_7_days']}",
        f"\u0423\u043d\u0438\u043a\u0430\u043b\u044c\u043d\u044b\u0445 \u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u0435\u0439: {stats['g25_unique_users']}",
        "",
        f"/3: {stats['g25_3']}",
        f"/4: {stats['g25_4']}",
        f"/g25: {stats['g25_extract']}",
        f"/steppe: {stats['g25_steppe']}",
        f"/panel: {stats['g25_panel']}",
        f"/panel2: {stats['g25_panel2']}",
        f"raw-\u0444\u0430\u0439\u043b\u044b: {stats['g25_raw']}",
        f"\u0433\u043e\u0442\u043e\u0432\u044b\u0435 G25: {stats['g25_text']}",
    ]
    await update.message.reply_text("\n".join(lines), parse_mode="HTML", do_quote=False)

async def find_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return

    if not context.args:
        await update.message.reply_text("\u0423\u043a\u0430\u0436\u0438\u0442\u0435 \u0444\u0430\u043c\u0438\u043b\u0438\u044e: /f <\u0424\u0430\u043c\u0438\u043b\u0438\u044f>", do_quote=False)
        return

    name = " ".join(context.args).strip()
    await handle_lookup(update, context, name)



def _build_g25_sample_name(update: Update, fallback_name: str = "") -> str:
    fallback_name = fallback_name.strip()
    if fallback_name:
        return fallback_name

    user = update.effective_user
    if user is not None:
        full_name = " ".join(
            part for part in [getattr(user, "first_name", "") or "", getattr(user, "last_name", "") or ""] if part
        ).strip()
        if full_name:
            return full_name
        if getattr(user, "username", None):
            return user.username
    return "Target"


async def g25_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return

    access_store: G25AccessStore = context.application.bot_data["g25_access_store"]
    if not access_store.is_allowed(update):
        await update.message.reply_text("G25-\u0444\u0443\u043d\u043a\u0446\u0438\u044f \u0434\u043e\u0441\u0442\u0443\u043f\u043d\u0430 \u0442\u043e\u043b\u044c\u043a\u043e \u0434\u043b\u044f \u0440\u0430\u0437\u0440\u0435\u0448\u0435\u043d\u043d\u044b\u0445 \u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u0435\u0439.", do_quote=False)
        return

    service: G25CommandService = context.application.bot_data["g25_service"]
    usage_store: UsageStore = context.application.bot_data["usage_store"]
    command_source = update.message.caption if update.message.document is not None else update.message.text
    parsed = service.extract_command_payload(command_source)
    if parsed is None:
        return

    command, body = parsed
    status_message = None
    reply_message = update.message.reply_to_message
    source_document = update.message.document
    reply_text_used = False
    if source_document is None and reply_message is not None:
        source_document = reply_message.document
        if source_document is None:
            reply_attachment = getattr(reply_message, "effective_attachment", None)
            if getattr(reply_attachment, "file_id", None) and hasattr(reply_attachment, "get_file"):
                source_document = reply_attachment
        if source_document is None and not body:
            reply_body = (reply_message.text or reply_message.caption or "").strip()
            if reply_body:
                body = reply_body
                reply_text_used = True

    requested_input_mode = (
        "document"
        if update.message.document is not None
        else ("reply-document" if source_document is not None else ("reply-text" if reply_text_used else "text"))
    )
    usage_query = body[:120].strip() if body else ""

    try:
        if source_document is not None:
            status_text = "\u0424\u0430\u0439\u043b \u043f\u043e\u043b\u0443\u0447\u0435\u043d, \u0438\u0437\u0432\u043b\u0435\u043a\u0430\u044e \u043a\u043e\u043e\u0440\u0434\u0438\u043d\u0430\u0442\u044b..." if command == "g25" else "\u0424\u0430\u0439\u043b \u043f\u043e\u043b\u0443\u0447\u0435\u043d, \u0441\u0442\u0440\u043e\u044e \u043c\u043e\u0434\u0435\u043b\u044c..."
            status_message = await update.message.reply_text(status_text, do_quote=False)
            document = source_document
            file_name = document.file_name or f"input_{command}.txt"
            usage_query = file_name
            sample_name = _build_g25_sample_name(update, Path(file_name).stem)
            run_dir = service.create_run_dir(command, sample_name)
            input_path = run_dir / file_name
            telegram_file = await document.get_file()
            await telegram_file.download_to_drive(custom_path=str(input_path))
            if command == "g25":
                result = service.extract_coordinates_from_file(input_path, sample_name)
            else:
                result = service.run_from_file(command, input_path, sample_name)
        else:
            sample_name = _build_g25_sample_name(update)
            usage_query = sample_name
            if command == "g25":
                result = service.extract_coordinates_from_text(body, sample_name)
            else:
                result = service.run_from_text(command, body, sample_name)
    except G25CommandError as exc:
        usage_store.record_g25(update, command=command, input_mode=requested_input_mode, success=False, query=usage_query)
        await update.message.reply_text(str(exc), do_quote=False)
        return
    except Exception:
        logger.exception("G25 command failed")
        usage_store.record_g25(update, command=command, input_mode=requested_input_mode, success=False, query=usage_query)
        await update.message.reply_text(
            "\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u043e\u0431\u0440\u0430\u0431\u043e\u0442\u0430\u0442\u044c \u0437\u0430\u043f\u0440\u043e\u0441. \u041f\u0440\u043e\u0432\u0435\u0440\u044c\u0442\u0435 \u0444\u0430\u0439\u043b \u0438\u043b\u0438 G25-\u043a\u043e\u043e\u0440\u0434\u0438\u043d\u0430\u0442\u044b \u0438 \u043f\u043e\u043f\u0440\u043e\u0431\u0443\u0439\u0442\u0435 \u0435\u0449\u0435 \u0440\u0430\u0437.",
            do_quote=False,
        )
        return

    usage_store.record_g25(
        update,
        command=command,
        input_mode=result.input_mode,
        success=True,
        query=result.target_name,
    )

    if command == "g25":
        await update.message.reply_text(
            f"G25 \u043a\u043e\u043e\u0440\u0434\u0438\u043d\u0430\u0442\u044b\n<code>{html.escape(result.simulated_g25_line)}</code>",
            parse_mode="HTML",
            do_quote=False,
        )
    else:
        with result.png_path.open("rb") as handle:
            await update.message.reply_photo(
                photo=handle,
                caption=result.summary_text,
                do_quote=False,
            )
        if source_document is not None and result.simulated_g25_line:
            await update.message.reply_text(
                f"G25 \u043a\u043e\u043e\u0440\u0434\u0438\u043d\u0430\u0442\u044b\n<code>{html.escape(result.simulated_g25_line)}</code>",
                parse_mode="HTML",
                do_quote=False,
            )

    if status_message is not None:
        try:
            done_text = "\u041a\u043e\u043e\u0440\u0434\u0438\u043d\u0430\u0442\u044b \u0433\u043e\u0442\u043e\u0432\u044b." if command == "g25" else "\u041c\u043e\u0434\u0435\u043b\u044c \u0433\u043e\u0442\u043e\u0432\u0430."
            await status_message.edit_text(done_text)
        except Exception:
            logger.debug("Failed to update G25 status message", exc_info=True)


def _parse_g25_admin_ids(raw: str) -> set[int]:
    values = set()
    for token in re.split(r"[,\s]+", raw.strip()):
        if not token:
            continue
        try:
            values.add(int(token))
        except ValueError:
            continue
    return values

def _parse_g25_admin_usernames(raw: str) -> set[str]:
    values = set()
    for token in re.split(r"[,\s]+", raw.strip()):
        normalized = G25AccessStore._normalize_username(token)
        if normalized:
            values.add(normalized)
    return values

def _extract_access_target(update: Update, context: ContextTypes.DEFAULT_TYPE) -> tuple[str, str | int] | None:
    if context.args:
        raw = context.args[0].strip()
        if raw.startswith("@"):
            normalized = G25AccessStore._normalize_username(raw)
            return ("username", normalized) if normalized else None
        try:
            return ("id", int(raw))
        except ValueError:
            normalized = G25AccessStore._normalize_username(raw)
            return ("username", normalized) if normalized else None

    if update.message and update.message.reply_to_message and update.message.reply_to_message.from_user:
        replied_user = update.message.reply_to_message.from_user
        if getattr(replied_user, "username", None):
            return ("username", G25AccessStore._normalize_username(replied_user.username))
        if getattr(replied_user, "id", None):
            return ("id", int(replied_user.id))
    return None

async def g25allow_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return

    access_store: G25AccessStore = context.application.bot_data["g25_access_store"]
    if not access_store.is_admin(update):
        await update.message.reply_text("\u041a\u043e\u043c\u0430\u043d\u0434\u0430 \u0434\u043e\u0441\u0442\u0443\u043f\u043d\u0430 \u0442\u043e\u043b\u044c\u043a\u043e \u0430\u0434\u043c\u0438\u043d\u0438\u0441\u0442\u0440\u0430\u0442\u043e\u0440\u0443 G25.", do_quote=False)
        return

    target = _extract_access_target(update, context)
    if target is None:
        await update.message.reply_text("\u0418\u0441\u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u043d\u0438\u0435: /g25allow @username \u0438\u043b\u0438 /g25allow 123456789", do_quote=False)
        return

    kind, value = target
    if kind == "username":
        saved = access_store.allow_username(str(value))
    else:
        saved = access_store.allow_user_id(int(value))
    await update.message.reply_text(f"\u0414\u043e\u0441\u0442\u0443\u043f \u043a G25 \u0432\u044b\u0434\u0430\u043d: {saved}", do_quote=False)

async def g25deny_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return

    access_store: G25AccessStore = context.application.bot_data["g25_access_store"]
    if not access_store.is_admin(update):
        await update.message.reply_text("\u041a\u043e\u043c\u0430\u043d\u0434\u0430 \u0434\u043e\u0441\u0442\u0443\u043f\u043d\u0430 \u0442\u043e\u043b\u044c\u043a\u043e \u0430\u0434\u043c\u0438\u043d\u0438\u0441\u0442\u0440\u0430\u0442\u043e\u0440\u0443 G25.", do_quote=False)
        return

    target = _extract_access_target(update, context)
    if target is None:
        await update.message.reply_text("\u0418\u0441\u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u043d\u0438\u0435: /g25deny @username \u0438\u043b\u0438 /g25deny 123456789", do_quote=False)
        return

    kind, value = target
    if kind == "username":
        removed = access_store.deny_username(str(value))
    else:
        removed = access_store.deny_user_id(int(value))
    await update.message.reply_text(f"\u0414\u043e\u0441\u0442\u0443\u043f \u043a G25 \u0441\u043d\u044f\u0442: {removed}", do_quote=False)

async def g25list_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return

    access_store: G25AccessStore = context.application.bot_data["g25_access_store"]
    if not access_store.is_admin(update):
        await update.message.reply_text("\u041a\u043e\u043c\u0430\u043d\u0434\u0430 \u0434\u043e\u0441\u0442\u0443\u043f\u043d\u0430 \u0442\u043e\u043b\u044c\u043a\u043e \u0430\u0434\u043c\u0438\u043d\u0438\u0441\u0442\u0440\u0430\u0442\u043e\u0440\u0443 G25.", do_quote=False)
        return

    await update.message.reply_text(access_store.format_list(), parse_mode="HTML", do_quote=False)

async def panel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.effective_chat is None or update.effective_user is None:
        return

    access_store: G25AccessStore = context.application.bot_data["g25_access_store"]
    if not access_store.is_allowed(update):
        await update.message.reply_text("G25-\u0444\u0443\u043d\u043a\u0446\u0438\u044f \u0434\u043e\u0441\u0442\u0443\u043f\u043d\u0430 \u0442\u043e\u043b\u044c\u043a\u043e \u0434\u043b\u044f \u0440\u0430\u0437\u0440\u0435\u0448\u0435\u043d\u043d\u044b\u0445 \u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u0435\u0439.", do_quote=False)
        return

    await _send_panel_builder_message(
        message=update.message,
        context=context,
        panel_name="panel",
        chat_id=update.effective_chat.id,
        user_id=update.effective_user.id,
    )
async def panel_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None:
        return
    if not query.data.startswith(f"{PANEL_CALLBACK_PREFIX}:"):
        return

    await query.answer()
    if update.effective_chat is None or update.effective_user is None or query.message is None:
        return

    access_store: G25AccessStore = context.application.bot_data["g25_access_store"]
    if not access_store.is_allowed(update):
        await query.answer("Нет доступа к G25.", show_alert=True)
        return

    service: G25CommandService = context.application.bot_data["g25_service"]
    panel_store: CustomPanelStore = context.application.bot_data["panel_store"]
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    state = panel_store.get(chat_id, user_id)
    if not state or state.get("message_id") != query.message.message_id:
        await query.answer("Это меню не для вас. Вызовите /panel сами.", show_alert=True)
        return

    parts = query.data.split(":", 2)
    action = parts[1] if len(parts) > 1 else ""
    source_key = parts[2] if len(parts) > 2 else ""

    if action == "toggle":
        selected = panel_store.toggle(chat_id, user_id, source_key)
        await query.edit_message_text(
            _panel_builder_text(service, selected),
            reply_markup=_build_panel_keyboard(service, selected),
        )
        return

    if action == "clear":
        panel_store.clear(chat_id, user_id)
        await query.edit_message_text(
            _panel_builder_text(service, []),
            reply_markup=_build_panel_keyboard(service, []),
        )
        return

    if action == "back":
        panel_store.cancel(chat_id, user_id)
        await query.edit_message_text(_g25menu_text(), reply_markup=_build_g25menu_keyboard())
        return

    if action == "cancel":
        _cancel_g25_menu(context, chat_id, user_id)
        await query.edit_message_text("G25 меню закрыто.")
        return

    if action == "done":
        selected = panel_store.finish(chat_id, user_id)
        if not selected:
            await query.answer("Сначала выберите хотя бы один источник.", show_alert=True)
            return
        await query.edit_message_text(
            _panel_builder_text(service, selected, ready=True),
            reply_markup=_build_panel_ready_keyboard(PANEL_CALLBACK_PREFIX),
        )
        return
async def _run_custom_panel_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    body: str = "",
) -> None:
    if update.message is None or update.effective_chat is None or update.effective_user is None:
        return

    service: G25CommandService = context.application.bot_data["g25_service"]
    usage_store: UsageStore = context.application.bot_data["usage_store"]
    panel_store: CustomPanelStore = context.application.bot_data["panel_store"]
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    selected_keys = panel_store.get_selected(chat_id, user_id)
    source_document = update.message.document
    status_message = None
    usage_query = body[:120].strip() if body else ""

    try:
        if source_document is not None:
            status_message = await update.message.reply_text("\u0424\u0430\u0439\u043b \u043f\u043e\u043b\u0443\u0447\u0435\u043d, \u0441\u0442\u0440\u043e\u044e \u043c\u043e\u0434\u0435\u043b\u044c...", do_quote=False)
            file_name = source_document.file_name or "input_panel.txt"
            usage_query = file_name
            sample_name = _build_g25_sample_name(update, Path(file_name).stem)
            temp_dir = service.create_run_dir("panel_input", sample_name)
            input_path = temp_dir / file_name
            telegram_file = await source_document.get_file()
            await telegram_file.download_to_drive(custom_path=str(input_path))
            result = service.run_custom_from_file(selected_keys, input_path, sample_name)
        else:
            sample_name = _build_g25_sample_name(update)
            usage_query = sample_name
            result = service.run_custom_from_text(selected_keys, body, sample_name)
    except G25CommandError as exc:
        usage_store.record_g25(update, command="panel", input_mode=("document" if source_document is not None else "text"), success=False, query=usage_query)
        await update.message.reply_text(str(exc), do_quote=False)
        raise ApplicationHandlerStop
    except Exception:
        logger.exception("Custom panel command failed")
        usage_store.record_g25(update, command="panel", input_mode=("document" if source_document is not None else "text"), success=False, query=usage_query)
        await update.message.reply_text("\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u043e\u0431\u0440\u0430\u0431\u043e\u0442\u0430\u0442\u044c \u0434\u0430\u043d\u043d\u044b\u0435. \u041f\u0440\u043e\u0432\u0435\u0440\u044c\u0442\u0435 \u0444\u0430\u0439\u043b \u0438\u043b\u0438 G25-\u043a\u043e\u043e\u0440\u0434\u0438\u043d\u0430\u0442\u044b \u0438 \u043f\u043e\u043f\u0440\u043e\u0431\u0443\u0439\u0442\u0435 \u0435\u0449\u0435 \u0440\u0430\u0437.", do_quote=False)
        raise ApplicationHandlerStop

    usage_store.record_g25(update, command="panel", input_mode=result.input_mode, success=True, query=result.target_name)

    with result.png_path.open("rb") as handle:
        await update.message.reply_photo(photo=handle, caption=result.summary_text, do_quote=False)
    if source_document is not None and result.simulated_g25_line:
        await update.message.reply_text(
            f"G25 \u043a\u043e\u043e\u0440\u0434\u0438\u043d\u0430\u0442\u044b\n<code>{html.escape(result.simulated_g25_line)}</code>",
            parse_mode="HTML",
            do_quote=False,
        )

    panel_store.clear_pending(chat_id, user_id)
    if status_message is not None:
        try:
            await status_message.edit_text("\u0420\u0430\u0441\u0447\u0435\u0442 \u0433\u043e\u0442\u043e\u0432.")
        except Exception:
            logger.debug("Failed to update custom panel status message", exc_info=True)
    raise ApplicationHandlerStop


async def _run_g25coords_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    body: str = "",
) -> None:
    if update.message is None or update.effective_chat is None or update.effective_user is None:
        return

    service: G25CommandService = context.application.bot_data["g25_service"]
    usage_store: UsageStore = context.application.bot_data["usage_store"]
    coords_store: CustomPanelStore = context.application.bot_data["coords_store"]
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    source_document = update.message.document
    status_message = None
    usage_query = body[:120].strip() if body else ""

    try:
        if source_document is not None:
            status_message = await update.message.reply_text("\u0424\u0430\u0439\u043b \u043f\u043e\u043b\u0443\u0447\u0435\u043d, \u0438\u0437\u0432\u043b\u0435\u043a\u0430\u044e \u043a\u043e\u043e\u0440\u0434\u0438\u043d\u0430\u0442\u044b...", do_quote=False)
            file_name = source_document.file_name or "input_g25.txt"
            usage_query = file_name
            sample_name = _build_g25_sample_name(update, Path(file_name).stem)
            run_dir = service.create_run_dir("g25", sample_name)
            input_path = run_dir / file_name
            telegram_file = await source_document.get_file()
            await telegram_file.download_to_drive(custom_path=str(input_path))
            result = service.extract_coordinates_from_file(input_path, sample_name)
        else:
            sample_name = _build_g25_sample_name(update)
            usage_query = sample_name
            result = service.extract_coordinates_from_text(body, sample_name)
    except G25CommandError as exc:
        usage_store.record_g25(update, command="g25", input_mode=("document" if source_document is not None else "text"), success=False, query=usage_query)
        await update.message.reply_text(str(exc), do_quote=False)
        raise ApplicationHandlerStop
    except Exception:
        logger.exception("G25 coords menu command failed")
        usage_store.record_g25(update, command="g25", input_mode=("document" if source_document is not None else "text"), success=False, query=usage_query)
        await update.message.reply_text(
            "\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u043e\u0431\u0440\u0430\u0431\u043e\u0442\u0430\u0442\u044c \u0437\u0430\u043f\u0440\u043e\u0441. \u041f\u0440\u043e\u0432\u0435\u0440\u044c\u0442\u0435 \u0444\u0430\u0439\u043b \u0438\u043b\u0438 G25-\u043a\u043e\u043e\u0440\u0434\u0438\u043d\u0430\u0442\u044b \u0438 \u043f\u043e\u043f\u0440\u043e\u0431\u0443\u0439\u0442\u0435 \u0435\u0449\u0435 \u0440\u0430\u0437.",
            do_quote=False,
        )
        raise ApplicationHandlerStop

    usage_store.record_g25(update, command="g25", input_mode=result.input_mode, success=True, query=result.target_name)
    await update.message.reply_text(
        f"G25 \u043a\u043e\u043e\u0440\u0434\u0438\u043d\u0430\u0442\u044b\n<code>{html.escape(result.simulated_g25_line)}</code>",
        parse_mode="HTML",
        do_quote=False,
    )

    coords_store.clear_pending(chat_id, user_id)
    if status_message is not None:
        try:
            await status_message.edit_text("\u041a\u043e\u043e\u0440\u0434\u0438\u043d\u0430\u0442\u044b \u0433\u043e\u0442\u043e\u0432\u044b.")
        except Exception:
            logger.debug("Failed to update G25 coords status message", exc_info=True)
    raise ApplicationHandlerStop


async def panel_document_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.message.document is None or update.effective_chat is None or update.effective_user is None:
        return

    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    coords_store: CustomPanelStore = context.application.bot_data["coords_store"]
    if coords_store.has_pending(chat_id, user_id):
        await _run_g25coords_input(update, context)
        return

    panel_store: CustomPanelStore = context.application.bot_data["panel_store"]
    if not panel_store.has_pending(chat_id, user_id):
        return

    await _run_custom_panel_input(update, context)


async def panel_text_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.message.text is None or update.effective_chat is None or update.effective_user is None:
        return

    body = update.message.text.strip()
    if not body or body.startswith("/"):
        return

    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    coords_store: CustomPanelStore = context.application.bot_data["coords_store"]
    if coords_store.has_pending(chat_id, user_id):
        await update.message.reply_text("В режиме получения G25 отправьте raw-файл документом.", do_quote=False)
        raise ApplicationHandlerStop

    panel_store: CustomPanelStore = context.application.bot_data["panel_store"]
    if not panel_store.has_pending(chat_id, user_id):
        return

    await _run_custom_panel_input(update, context, body=body)
async def panel2_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.effective_chat is None or update.effective_user is None:
        return

    access_store: G25AccessStore = context.application.bot_data["g25_access_store"]
    if not access_store.is_allowed(update):
        await update.message.reply_text("G25-\u0444\u0443\u043d\u043a\u0446\u0438\u044f \u0434\u043e\u0441\u0442\u0443\u043f\u043d\u0430 \u0442\u043e\u043b\u044c\u043a\u043e \u0434\u043b\u044f \u0440\u0430\u0437\u0440\u0435\u0448\u0435\u043d\u043d\u044b\u0445 \u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u0435\u0439.", do_quote=False)
        return

    await _send_panel_builder_message(
        message=update.message,
        context=context,
        panel_name="panel2",
        chat_id=update.effective_chat.id,
        user_id=update.effective_user.id,
    )
async def panel2_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None:
        return
    if not query.data.startswith(f"{PANEL2_CALLBACK_PREFIX}:"):
        return

    await query.answer()
    if update.effective_chat is None or update.effective_user is None or query.message is None:
        return

    access_store: G25AccessStore = context.application.bot_data["g25_access_store"]
    if not access_store.is_allowed(update):
        await query.answer("Нет доступа к G25.", show_alert=True)
        return

    service: G25CommandService = context.application.bot_data["g25_service"]
    panel_store: CustomPanelStore = context.application.bot_data["panel2_store"]
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    state = panel_store.get(chat_id, user_id)
    if not state or state.get("message_id") != query.message.message_id:
        await query.answer("Это меню не для вас. Вызовите /panel2 сами.", show_alert=True)
        return

    parts = query.data.split(":", 2)
    action = parts[1] if len(parts) > 1 else ""
    source_key = parts[2] if len(parts) > 2 else ""

    if action == "toggle":
        selected = panel_store.toggle(chat_id, user_id, source_key)
        await query.edit_message_text(
            _panel2_builder_text(service, selected),
            reply_markup=_build_panel2_keyboard(service, selected),
        )
        return

    if action == "clear":
        panel_store.clear(chat_id, user_id)
        await query.edit_message_text(
            _panel2_builder_text(service, []),
            reply_markup=_build_panel2_keyboard(service, []),
        )
        return

    if action == "back":
        panel_store.cancel(chat_id, user_id)
        await query.edit_message_text(_g25menu_text(), reply_markup=_build_g25menu_keyboard())
        return

    if action == "cancel":
        _cancel_g25_menu(context, chat_id, user_id)
        await query.edit_message_text("G25 меню закрыто.")
        return

    if action == "done":
        selected = panel_store.finish(chat_id, user_id)
        if not selected:
            await query.answer("Сначала выберите хотя бы один источник.", show_alert=True)
            return
        await query.edit_message_text(
            _panel2_builder_text(service, selected, ready=True),
            reply_markup=_build_panel_ready_keyboard(PANEL2_CALLBACK_PREFIX),
        )
        return
async def _run_custom_panel2_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    body: str = "",
) -> None:
    if update.message is None or update.effective_chat is None or update.effective_user is None:
        return

    service: G25CommandService = context.application.bot_data["g25_service"]
    usage_store: UsageStore = context.application.bot_data["usage_store"]
    panel_store: CustomPanelStore = context.application.bot_data["panel2_store"]
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    selected_keys = panel_store.get_selected(chat_id, user_id)
    source_document = update.message.document
    status_message = None
    usage_query = body[:120].strip() if body else ""

    try:
        if source_document is not None:
            status_message = await update.message.reply_text("Файл получен, строю модель...", do_quote=False)
            file_name = source_document.file_name or "input_panel2.txt"
            usage_query = file_name
            sample_name = _build_g25_sample_name(update, Path(file_name).stem)
            temp_dir = service.create_run_dir("panel2_input", sample_name)
            input_path = temp_dir / file_name
            telegram_file = await source_document.get_file()
            await telegram_file.download_to_drive(custom_path=str(input_path))
            result = service.run_panel2_from_file(selected_keys, input_path, sample_name)
        else:
            sample_name = _build_g25_sample_name(update)
            usage_query = sample_name
            result = service.run_panel2_from_text(selected_keys, body, sample_name)
    except G25CommandError as exc:
        usage_store.record_g25(update, command="panel2", input_mode=("document" if source_document is not None else "text"), success=False, query=usage_query)
        await update.message.reply_text(str(exc), do_quote=False)
        raise ApplicationHandlerStop
    except Exception:
        logger.exception("Custom panel2 command failed")
        usage_store.record_g25(update, command="panel2", input_mode=("document" if source_document is not None else "text"), success=False, query=usage_query)
        await update.message.reply_text("Не удалось обработать данные. Проверьте файл или G25-координаты и попробуйте еще раз.", do_quote=False)
        raise ApplicationHandlerStop

    usage_store.record_g25(update, command="panel2", input_mode=result.input_mode, success=True, query=result.target_name)

    with result.png_path.open("rb") as handle:
        await update.message.reply_photo(photo=handle, caption=result.summary_text, do_quote=False)
    if source_document is not None and result.simulated_g25_line:
        await update.message.reply_text(
            f"G25 координаты\n<code>{html.escape(result.simulated_g25_line)}</code>",
            parse_mode="HTML",
            do_quote=False,
        )

    panel_store.clear_pending(chat_id, user_id)
    if status_message is not None:
        try:
            await status_message.edit_text("Расчет готов.")
        except Exception:
            logger.debug("Failed to update custom panel2 status message", exc_info=True)
    raise ApplicationHandlerStop


async def panel2_document_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.message.document is None or update.effective_chat is None or update.effective_user is None:
        return

    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    coords_store: CustomPanelStore = context.application.bot_data["coords_store"]
    if coords_store.has_pending(chat_id, user_id):
        await _run_g25coords_input(update, context)
        return

    panel2_store: CustomPanelStore = context.application.bot_data["panel2_store"]
    if panel2_store.has_pending(chat_id, user_id):
        await _run_custom_panel2_input(update, context)
        return

    panel_store: CustomPanelStore = context.application.bot_data["panel_store"]
    if panel_store.has_pending(chat_id, user_id):
        await _run_custom_panel_input(update, context)
        return


async def panel2_text_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.message.text is None or update.effective_chat is None or update.effective_user is None:
        return

    body = update.message.text.strip()
    if not body or body.startswith("/"):
        return

    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    coords_store: CustomPanelStore = context.application.bot_data["coords_store"]
    if coords_store.has_pending(chat_id, user_id):
        await update.message.reply_text("В режиме получения G25 отправьте raw-файл документом.", do_quote=False)
        raise ApplicationHandlerStop

    panel2_store: CustomPanelStore = context.application.bot_data["panel2_store"]
    if panel2_store.has_pending(chat_id, user_id):
        await _run_custom_panel2_input(update, context, body=body)
        return

    panel_store: CustomPanelStore = context.application.bot_data["panel_store"]
    if panel_store.has_pending(chat_id, user_id):
        await _run_custom_panel_input(update, context, body=body)
        return
async def text_lookup_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.message.text is None:
        return

    if update.effective_chat is None or update.effective_chat.type != "private":
        return

    name = update.message.text.strip()
    if not name:
        return

    await handle_lookup(update, context, name)


def main() -> None:
    load_dotenv()

    bot_token = get_required_env("BOT_TOKEN")
    spreadsheet_id = get_required_env("GOOGLE_SHEETS_ID", "GOOGLE_SHETS_ID")
    worksheet_name = os.getenv("GOOGLE_SHEETS_WORKSHEET", "").strip()
    creds_path = get_required_env("GOOGLE_CREDENTIALS_PATH")
    g25_admin_ids = _parse_g25_admin_ids(os.getenv("G25_ADMIN_IDS", ""))
    g25_admin_usernames = _parse_g25_admin_usernames(os.getenv("G25_ADMIN_USERNAMES", ""))

    sheets = SheetsClient(
        creds_path=creds_path,
        spreadsheet_id=spreadsheet_id,
        worksheet_name=worksheet_name,
    )
    g25_service = G25CommandService()
    usage_store = UsageStore(USAGE_DB_PATH)
    g25_access_store = G25AccessStore(G25_ACCESS_PATH, admin_ids=g25_admin_ids, admin_usernames=g25_admin_usernames)
    panel_store = CustomPanelStore()
    panel2_store = CustomPanelStore()
    coords_store = CustomPanelStore()

    app = Application.builder().token(bot_token).build()
    app.bot_data["sheets"] = sheets
    app.bot_data["g25_service"] = g25_service
    app.bot_data["usage_store"] = usage_store
    app.bot_data["g25_access_store"] = g25_access_store
    app.bot_data["panel_store"] = panel_store
    app.bot_data["panel2_store"] = panel2_store
    app.bot_data["coords_store"] = coords_store

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("build", build_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("g25stats", g25stats_command))
    app.add_handler(CommandHandler("g25allow", g25allow_command))
    app.add_handler(CommandHandler("g25deny", g25deny_command))
    app.add_handler(CommandHandler("g25list", g25list_command))
    app.add_handler(CommandHandler(G25MENU_COMMAND, g25menu_command))
    app.add_handler(CommandHandler(PANEL_COMMAND, panel_command))
    app.add_handler(CommandHandler(PANEL2_COMMAND, panel2_command))
    app.add_handler(CallbackQueryHandler(panel_callback_handler, pattern=r"^panel:"))
    app.add_handler(CallbackQueryHandler(panel2_callback_handler, pattern=r"^panel2:"))
    app.add_handler(CallbackQueryHandler(g25menu_callback_handler, pattern=r"^g25menu:"))
    app.add_handler(CommandHandler("find", find_command))
    app.add_handler(CommandHandler("f", find_command))
    app.add_handler(MessageHandler(filters.Document.ALL, panel2_document_input_handler), group=-1)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, panel2_text_input_handler), group=-1)
    app.add_handler(MessageHandler(filters.Document.ALL, panel_document_input_handler), group=-1)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, panel_text_input_handler), group=-1)
    app.add_handler(
        MessageHandler(
            (filters.TEXT & filters.Regex(r"^/(?:3|4|g25|steppe)(?:@\w+)?(?:\s|$)"))
            | (filters.Document.ALL & filters.CaptionRegex(r"^/(?:3|4|g25|steppe)(?:@\w+)?(?:\s|$)")),
            g25_command_handler,
        )
    )
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, text_lookup_command))

    logger.info("Bot started: %s", BUILD_ID)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()



