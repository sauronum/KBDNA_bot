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

BUILD_ID = "build-2026-03-12-1200"
LOCAL_DB_PATH = Path("haplogroup_info_ru.json")
EMOJI_MAP_PATH = Path("haplogroup_emoji_map.json")
YFULL_LINKS_PATH = Path("yfull_links.json")
USAGE_DB_PATH = Path("usage_stats.sqlite3")
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
            return ["??????? ??????."]

        headers = rows[0]
        name_idx = self._find_col_index(headers, ("name", "???", "???????"))
        haplo_idx = self._find_col_index(headers, ("???????????", "haplogroup"))
        kit_idx = self._find_col_index(headers, ("kit number", "kit", "????? ????"))
        ancestor_idx = self._find_col_index(
            headers,
            (
                "paternal ancestor name",
                "paternal ancestor",
                "?????? ?? ????????? ?????",
                "????????? ??????",
                "?????????????",
            ),
        )

        if name_idx is None or haplo_idx is None:
            return ["?? ??????? ?????? ???????: Name/???/??????? ?/??? ???????????."]

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
                results.append("??????? ???, ?? ? ??????? ?????? ???? '???????????'.")
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
                f"\U0001f464 <b>{html.escape(target['name'])}</b>\n\n"
                f"\U0001f4cd <b>\u041f\u0440\u043e\u0438\u0441\u0445\u043e\u0436\u0434\u0435\u043d\u0438\u0435</b>\n{html.escape(origin_display)}\n\n"
                f"\U0001f9ec <b>\u0413\u0430\u043f\u043b\u043e\u0433\u0440\u0443\u043f\u043f\u0430</b>\n{html.escape(haplo_display)}\n\n"
                f"\U0001f33f <b>\u0421\u0443\u0431\u043a\u043b\u0430\u0434</b>\n<code>{html.escape(target['subclade'] or '-')}</code>\n\n"
            )

            if yfull_link:
                result += (
                    f"\U0001f517 <b>YFull</b>\n"
                    f'<a href="{html.escape(yfull_link, quote=True)}">\u041e\u0442\u043a\u0440\u044b\u0442\u044c \u0432\u0435\u0442\u0432\u044c</a>\n\n'
                )
            else:
                result += "\U0001f517 <b>YFull</b>\n\u041d\u0435\u0442 \u043f\u0440\u044f\u043c\u043e\u0439 \u0441\u0442\u0440\u0430\u043d\u0438\u0446\u044b\n\n"

            if same_group:
                result += f"\U0001f465 <b>\u0421\u043e\u0432\u043f\u0430\u0434\u0435\u043d\u0438\u044f</b>\n{html.escape(', '.join(same_group))}\n"


            results.append(result)

        return results


class UsageStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

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

    def record_lookup(self, update: Update, query: str, success: bool) -> None:
        user = update.effective_user
        chat = update.effective_chat
        full_name = " ".join(
            part for part in [getattr(user, "first_name", "") or "", getattr(user, "last_name", "") or ""] if part
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO usage_events (user_id, username, full_name, chat_id, chat_type, query, success)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    getattr(user, "id", None),
                    getattr(user, "username", None),
                    full_name or None,
                    getattr(chat, "id", None),
                    getattr(chat, "type", None),
                    query,
                    1 if success else 0,
                ),
            )

    def get_summary(self) -> dict[str, int]:
        with self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) FROM usage_events").fetchone()[0]
            success = conn.execute("SELECT COUNT(*) FROM usage_events WHERE success = 1").fetchone()[0]
            unique_users = conn.execute(
                "SELECT COUNT(DISTINCT user_id) FROM usage_events WHERE user_id IS NOT NULL"
            ).fetchone()[0]
            today = conn.execute(
                "SELECT COUNT(*) FROM usage_events WHERE date(created_at, 'localtime') = date('now', 'localtime')"
            ).fetchone()[0]
        return {
            "total": total,
            "success": success,
            "unique_users": unique_users,
            "today": today,
        }


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
        await update.message.reply_text(f"?????? ?????? ???????: {exc}", do_quote=False)
        return

    if not values:
        usage_store.record_lookup(update, name, success=False)
        await update.message.reply_text("\u0424\u0430\u043c\u0438\u043b\u0438\u044f \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d\u0430. \u041f\u043e\u043f\u0440\u043e\u0431\u0443\u0439\u0442\u0435 \u0437\u0430\u043d\u043e\u0432\u043e.", do_quote=False)
        return

    usage_store.record_lookup(update, name, success=True)

    for value in values:
        await update.message.reply_text(value, parse_mode="HTML", do_quote=False)


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return

    usage_store: UsageStore = context.application.bot_data["usage_store"]
    stats = usage_store.get_summary()
    text = (
        "\u0421\u0442\u0430\u0442\u0438\u0441\u0442\u0438\u043a\u0430 \u0431\u043e\u0442\u0430\n\n"
        f"\u0412\u0441\u0435\u0433\u043e \u0437\u0430\u043f\u0440\u043e\u0441\u043e\u0432: {stats['total']}\n"
        f"\u0423\u0441\u043f\u0435\u0448\u043d\u044b\u0445 \u0437\u0430\u043f\u0440\u043e\u0441\u043e\u0432: {stats['success']}\n"
        f"\u0423\u043d\u0438\u043a\u0430\u043b\u044c\u043d\u044b\u0445 \u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u0435\u0439: {stats['unique_users']}\n"
        f"\u0417\u0430\u043f\u0440\u043e\u0441\u043e\u0432 \u0441\u0435\u0433\u043e\u0434\u043d\u044f: {stats['today']}"
    )
    await update.message.reply_text(text, do_quote=False)


async def find_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return

    if not context.args:
        await update.message.reply_text("Укажите фамилию: /f <Фамилия>", do_quote=False)
        return

    name = " ".join(context.args).strip()
    await handle_lookup(update, context, name)


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

    sheets = SheetsClient(
        creds_path=creds_path,
        spreadsheet_id=spreadsheet_id,
        worksheet_name=worksheet_name,
    )

    usage_store = UsageStore(USAGE_DB_PATH)

    app = Application.builder().token(bot_token).build()
    app.bot_data["sheets"] = sheets
    app.bot_data["usage_store"] = usage_store

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("build", build_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("find", find_command))
    app.add_handler(CommandHandler("f", find_command))
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, text_lookup_command))

    logger.info("Bot started: %s", BUILD_ID)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()



