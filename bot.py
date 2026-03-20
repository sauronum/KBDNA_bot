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
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
from g25_feature.command_service import G25CommandError, G25CommandService

BUILD_ID = "build-2026-03-20-1700"
LOCAL_DB_PATH = Path("haplogroup_info_ru.json")
EMOJI_MAP_PATH = Path("haplogroup_emoji_map.json")
YFULL_LINKS_PATH = Path("yfull_links.json")
USAGE_DB_PATH = Path("usage_stats.sqlite3")
G25_ACCESS_PATH = Path("g25_access.json")
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
        return value.strip().lower()

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
        if parts:
            return parts[-1]
        return cleaned.split()[-1]

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
            origin_display = ", ".join(origins) if origins else "-"

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
            haplo_display = f"{haplo_emoji} {haplo_with_group}".strip()
            yfull_link = self._get_yfull_link(target["general"], target["subclade"])

            result = (
                f"👤 <b>{html.escape(target['name'])}</b>\n\n"
                f"📍 <b>Происхождение</b>\n{html.escape(origin_display)}\n\n"
                f"🧬 <b>Гаплогруппа</b>\n{html.escape(haplo_display)}\n\n"
                f"🌿 <b>Субклад</b>\n<code>{html.escape(target['subclade'] or '-')}</code>\n\n"
            )

            if yfull_link:
                result += (
                    f"🔗 <b>YFull</b>\n"
                    f'<a href="{html.escape(yfull_link, quote=True)}">Открыть ветвь</a>\n\n'
                )
            else:
                result += "🔗 <b>YFull</b>\nНет прямой страницы\n\n"

            if same_group:
                result += f"👥 <b>Совпадения</b>\n{html.escape(', '.join(same_group))}\n"

            results.append(result)

        return results



class UsageStore:
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
            g25_total = conn.execute(
                "SELECT COUNT(*) FROM usage_events WHERE event_type = 'g25'"
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
                LIMIT 5
                """
            ).fetchall()

        success_rate = round((success / total) * 100, 1) if total else 0.0
        return {
            "total": total,
            "success": success,
            "success_rate": success_rate,
            "unique_users": unique_users,
            "today": today,
            "last_7_days": last_7_days,
            "lookup_total": lookup_total,
            "g25_total": g25_total,
            "g25_3": g25_3,
            "g25_4": g25_4,
            "g25_extract": g25_extract,
            "g25_steppe": g25_steppe,
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


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return

    await update.message.reply_text(
        "\u041f\u0440\u0438\u0432\u0435\u0442! \u041c\u043e\u0436\u0435\u0442\u0435 \u043f\u0438\u0441\u0430\u0442\u044c \u0444\u0430\u043c\u0438\u043b\u0438\u044e \u043f\u0440\u043e\u0441\u0442\u043e \u0442\u0435\u043a\u0441\u0442\u043e\u043c \u0438\u043b\u0438 \u0447\u0435\u0440\u0435\u0437 /f <\u0424\u0430\u043c\u0438\u043b\u0438\u044f>.\n"
        "\u042f \u0432\u0435\u0440\u043d\u0443 \u043f\u0440\u043e\u0438\u0441\u0445\u043e\u0436\u0434\u0435\u043d\u0438\u0435, \u0433\u0430\u043f\u043b\u043e\u0433\u0440\u0443\u043f\u043f\u0443 \u0438 \u0441\u0443\u0431\u043a\u043b\u0430\u0434.\n"
        f"Версия: {BUILD_ID}",
        do_quote=False,
    )


async def build_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    await update.message.reply_text(BUILD_ID, do_quote=False)


async def handle_lookup(update: Update, context: ContextTypes.DEFAULT_TYPE, name: str) -> None:
    sheets: SheetsClient = context.application.bot_data["sheets"]
    usage_store: UsageStore = context.application.bot_data["usage_store"]

    try:
        values = sheets.get_groups_by_name(name)
    except Exception as exc:
        logger.exception("Sheets read error")
        usage_store.record_lookup(update, name, success=False)
        await update.message.reply_text(f"Ошибка чтения таблицы: {exc}", do_quote=False)
        return

    if not values:
        usage_store.record_lookup(update, name, success=False)
        await update.message.reply_text("Фамилия не найдена. Попробуйте заново.", do_quote=False)
        return

    usage_store.record_lookup(update, name, success=True)

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

    lines = [
        "<b>\u0421\u0442\u0430\u0442\u0438\u0441\u0442\u0438\u043a\u0430</b>",
        "",
        f"\u0412\u0441\u0435\u0433\u043e \u0441\u043e\u0431\u044b\u0442\u0438\u0439: {stats['total']}",
        f"\u0423\u0441\u043f\u0435\u0448\u043d\u044b\u0445: {stats['success']} ({stats['success_rate']}%)",
        f"\u0417\u0430 \u0441\u0435\u0433\u043e\u0434\u043d\u044f: {stats['today']}",
        f"\u0417\u0430 7 \u0434\u043d\u0435\u0439: {stats['last_7_days']}",
        f"\u0423\u043d\u0438\u043a\u0430\u043b\u044c\u043d\u044b\u0445 \u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u0435\u0439: {stats['unique_users']}",
        "",
        f"G25 \u0432\u0441\u0435\u0433\u043e: {stats['g25_total']}",
        f"/3: {stats['g25_3']}",
        f"/4: {stats['g25_4']}",
        f"/g25: {stats['g25_extract']}",
        f"/steppe: {stats['g25_steppe']}",
        f"raw-\u0444\u0430\u0439\u043b\u044b: {stats['g25_raw']}",
        f"\u0433\u043e\u0442\u043e\u0432\u044b\u0435 G25: {stats['g25_text']}",
        "",
        f"\u041f\u043e\u0438\u0441\u043a \u043f\u043e \u0444\u0430\u043c\u0438\u043b\u0438\u044f\u043c: {stats['lookup_total']}",
        "",
        f"\u0422\u043e\u043f \u0444\u0430\u043c\u0438\u043b\u0438\u0439\n{top_block}",
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

    app = Application.builder().token(bot_token).build()
    app.bot_data["sheets"] = sheets
    app.bot_data["g25_service"] = g25_service
    app.bot_data["usage_store"] = usage_store
    app.bot_data["g25_access_store"] = g25_access_store

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("build", build_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("g25allow", g25allow_command))
    app.add_handler(CommandHandler("g25deny", g25deny_command))
    app.add_handler(CommandHandler("g25list", g25list_command))
    app.add_handler(CommandHandler("find", find_command))
    app.add_handler(CommandHandler("f", find_command))
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



