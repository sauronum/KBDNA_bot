from __future__ import annotations

import html
import json
import logging
import os
import re
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

BUILD_ID = "build-2026-03-10-1147"
LOCAL_DB_PATH = Path("haplogroup_info_ru.json")
EMOJI_MAP_PATH = Path("haplogroup_emoji_map.json")
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
            return ["Таблица пустая."]

        headers = rows[0]
        name_idx = self._find_col_index(headers, ("name", "имя", "фамилия"))
        haplo_idx = self._find_col_index(headers, ("гаплогруппа", "haplogroup"))
        kit_idx = self._find_col_index(headers, ("kit number", "kit", "????? ????"))
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

        # Build normalized rows with their current group context, then query.
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

        # Merge entries by subclade only (as requested).
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

            # Merge origins for identical haplogroup+subclade entries.
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

            # Collect other surnames in the same subclade/group; skip placeholders.
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

            result = (
                f"<b>Фамилия:</b> {html.escape(target['name'])}\n"
                f"<b>Происхождение:</b> {html.escape(origin_display)}\n\n"
                f"<b>Гаплогруппа:</b> {html.escape(haplo_display)}\n"
                f"<b>Субклад:</b> {html.escape(target['subclade'] or '-')}\n\n"
            )

            if same_group:
                result += f"<b>Также в этом субкладе:</b> {html.escape(', '.join(same_group))}\n"

            results.append(result)

        return results


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

    try:
        values = sheets.get_groups_by_name(name)
    except Exception as exc:
        logger.exception("Sheets read error")
        await update.message.reply_text(f"Ошибка чтения таблицы: {exc}", do_quote=False)
        return

    if not values:
        await update.message.reply_text("Напишите фамилию на русском", do_quote=False)
        return

    for value in values:
        await update.message.reply_text(value, parse_mode="HTML", do_quote=False)


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

    app = Application.builder().token(bot_token).build()
    app.bot_data["sheets"] = sheets

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("build", build_command))
    app.add_handler(CommandHandler("find", find_command))
    app.add_handler(CommandHandler("f", find_command))
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, text_lookup_command))

    logger.info("Bot started: %s", BUILD_ID)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()



