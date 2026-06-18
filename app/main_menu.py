from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from app.i18n import get_user_language, t


MAIN_CALLBACK_PREFIX = "main"
G25_COORDINATES_REPLY_BUTTON_TEXT = "Получить G25 координаты"
ADMIN_STATS_USERNAMES = {"jb_cc"}
ADMIN_STATS_EXCLUDED_USERNAMES = {"jb_cc"}


def _normalize_username(value: str | None) -> str:
    if not value:
        return ""
    return value.strip().lstrip("@").lower()


def _is_stats_admin(update: Update) -> bool:
    user = update.effective_user
    if user is None:
        return False
    return _normalize_username(getattr(user, "username", None)) in ADMIN_STATS_USERNAMES


def _reply_keyboard_kind(update: Update | None) -> str:
    return "user:g25"


def _language_for_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    user = update.effective_user
    return get_user_language(context, int(user.id) if user is not None else None)


def build_reply_menu_keyboard(update: Update | None = None) -> ReplyKeyboardMarkup:
    rows = [["Menu", G25_COORDINATES_REPLY_BUTTON_TEXT]]
    return ReplyKeyboardMarkup(rows, resize_keyboard=True, is_persistent=True)


class MainMenuStore:
    def __init__(self) -> None:
        self._message_ids: dict[tuple[int, int], int] = {}
        self._reply_keyboard_kinds: dict[tuple[int, int], str] = {}

    @staticmethod
    def _key(chat_id: int, user_id: int) -> tuple[int, int]:
        return int(chat_id), int(user_id)

    def get(self, chat_id: int, user_id: int) -> int | None:
        return self._message_ids.get(self._key(chat_id, user_id))

    def set(self, chat_id: int, user_id: int, message_id: int) -> None:
        self._message_ids[self._key(chat_id, user_id)] = int(message_id)

    def clear(self, chat_id: int, user_id: int) -> None:
        self._message_ids.pop(self._key(chat_id, user_id), None)

    def reply_keyboard_kind(self, chat_id: int, user_id: int) -> str | None:
        return self._reply_keyboard_kinds.get(self._key(chat_id, user_id))

    def mark_reply_keyboard_enabled(self, chat_id: int, user_id: int, kind: str) -> None:
        self._reply_keyboard_kinds[self._key(chat_id, user_id)] = kind


def _menu_store(context: ContextTypes.DEFAULT_TYPE) -> MainMenuStore:
    store = context.application.bot_data.get("main_menu_store")
    if isinstance(store, MainMenuStore):
        return store

    store = MainMenuStore()
    context.application.bot_data["main_menu_store"] = store
    return store


def set_active_main_menu_message(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int, message_id: int) -> None:
    _menu_store(context).set(chat_id, user_id, message_id)
    hooks = context.application.bot_data.get("reply_menu_hooks", {})
    remember_active = hooks.get("remember_active_reply_menu")
    if callable(remember_active):
        remember_active(context, chat_id, message_id)
    remember_owner = hooks.get("remember_reply_menu_owner")
    if callable(remember_owner):
        remember_owner(context, chat_id, message_id, user_id)


def clear_active_main_menu_message(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int, message_id: int) -> None:
    _menu_store(context).clear(chat_id, user_id)
    hooks = context.application.bot_data.get("reply_menu_hooks", {})
    forget_active = hooks.get("forget_active_reply_menu")
    if callable(forget_active):
        forget_active(context, chat_id, message_id=message_id)


def _clear_pending_section_input(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int) -> None:
    for key in ("haplogroup_flow_store",):
        store = context.application.bot_data.get(key)
        clear = getattr(store, "clear", None)
        if callable(clear):
            clear(chat_id, user_id)


async def ensure_active_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    query = update.callback_query
    if query is None or query.message is None or update.effective_chat is None or update.effective_user is None:
        return True

    store = _menu_store(context)
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    active_message_id = store.get(chat_id, user_id)

    if active_message_id is None:
        store.set(chat_id, user_id, query.message.message_id)
        return True

    if active_message_id == query.message.message_id:
        return True

    await query.answer(t("main.menu_stale_start", _language_for_update(update, context)))
    return False


def main_menu_text(lang: str = "ru") -> str:
    return t("main.choose_section", lang)


def build_main_menu_keyboard(lang: str = "ru") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(t("main.my_dna", lang), callback_data="my_data:root")],
            [InlineKeyboardButton(t("main.coordinate_spaces", lang), callback_data="coordinate_space:root")],
            [
                InlineKeyboardButton(t("main.modeling", lang), callback_data="modeling:root"),
                InlineKeyboardButton(t("main.matching", lang), callback_data="matching:root"),
            ],
            [InlineKeyboardButton(t("main.vahaduo", lang), callback_data="vahaduo:root")],
            [
                InlineKeyboardButton(t("main.traits", lang), callback_data="traits:s"),
            ],
            [
                InlineKeyboardButton(t("main.admixture", lang), callback_data="admixture:root"),
                InlineKeyboardButton(t("main.haplogroups", lang), callback_data="haplogroups:root"),
            ],
            [InlineKeyboardButton(t("main.cancel", lang), callback_data=f"{MAIN_CALLBACK_PREFIX}:cancel")],
        ]
    )


async def _ensure_reply_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.effective_chat is None or update.effective_user is None:
        return

    store = _menu_store(context)
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    kind = _reply_keyboard_kind(update)
    if store.reply_keyboard_kind(chat_id, user_id) == kind:
        return

    await update.message.reply_text("\u2060", reply_markup=build_reply_menu_keyboard(update), do_quote=False)
    store.mark_reply_keyboard_enabled(chat_id, user_id, kind)


def start_text(lang: str = "ru") -> str:
    return t("main.start_hint", lang)


async def show_start_hint(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return

    lang = _language_for_update(update, context)
    await update.message.reply_text(start_text(lang), reply_markup=build_reply_menu_keyboard(update), do_quote=False)
    if update.effective_chat is not None and update.effective_user is not None:
        store = _menu_store(context)
        store.mark_reply_keyboard_enabled(update.effective_chat.id, update.effective_user.id, _reply_keyboard_kind(update))


async def show_main_menu(message, context: ContextTypes.DEFAULT_TYPE, user_id: int, *, edit_existing: bool = False) -> None:
    lang = get_user_language(context, user_id)
    text = main_menu_text(lang)
    markup = build_main_menu_keyboard(lang)
    if edit_existing:
        await message.edit_text(text, reply_markup=markup)
    else:
        await message.reply_text(text, reply_markup=markup, do_quote=False)


async def _deactivate_main_menu(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int) -> None:
    try:
        await context.bot.edit_message_reply_markup(chat_id=chat_id, message_id=message_id, reply_markup=None)
    except BadRequest:
        return


async def _show_or_replace_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.effective_chat is None or update.effective_user is None:
        return

    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    store = _menu_store(context)
    previous_message_id = store.get(chat_id, user_id)
    lang = get_user_language(context, user_id)
    text = main_menu_text(lang)
    markup = build_main_menu_keyboard(lang)

    sent = await update.message.reply_text(text, reply_markup=markup, do_quote=False)
    store.set(chat_id, user_id, sent.message_id)

    if previous_message_id is not None and previous_message_id != sent.message_id:
        await _deactivate_main_menu(context, chat_id, previous_message_id)


async def main_menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _ensure_reply_menu(update, context)
    await _show_or_replace_main_menu(update, context)


async def main_menu_reply_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _ensure_reply_menu(update, context)
    await _show_or_replace_main_menu(update, context)


def _storage_root(context: ContextTypes.DEFAULT_TYPE) -> Path:
    my_data_store = context.application.bot_data.get("my_data_store")
    root_dir = getattr(my_data_store, "root_dir", None)
    if root_dir is not None:
        return Path(root_dir).parent
    return Path(__file__).resolve().parents[1] / "storage"


def _read_json_list(path: Path) -> list[dict[str, object]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def _user_id_from_storage_path(path: Path) -> str | None:
    parts = path.parts
    try:
        users_index = parts.index("users")
    except ValueError:
        return None
    if users_index + 1 >= len(parts):
        return None
    return parts[users_index + 1]


def _count_index_items(root: Path, pattern: str, *, excluded_user_ids: set[str] | None = None) -> int:
    if not root.exists():
        return 0
    excluded = excluded_user_ids or set()
    total = 0
    for path in root.glob(pattern):
        user_id = _user_id_from_storage_path(path)
        if user_id is not None and user_id in excluded:
            continue
        total += len(_read_json_list(path))
    return total


def _count_sqlite_rows(
    db_path: Path,
    table_name: str,
    *,
    distinct_column: str | None = None,
    excluded_user_ids: set[str] | None = None,
) -> int:
    if not db_path.exists():
        return 0
    expression = f"COUNT(DISTINCT {distinct_column})" if distinct_column else "COUNT(*)"
    excluded = sorted(excluded_user_ids or set())
    where_clause = ""
    params: list[object] = []
    if excluded:
        placeholders = ", ".join("?" for _ in excluded)
        where_clause = f" WHERE CAST(user_id AS TEXT) NOT IN ({placeholders})"
        params.extend(excluded)
    try:
        with sqlite3.connect(db_path) as conn:
            row = conn.execute(f"SELECT {expression} FROM {table_name}{where_clause}", params).fetchone()
    except sqlite3.Error:
        return 0
    return int(row[0]) if row and row[0] is not None else 0


def _sqlite_distinct_values(db_path: Path, table_name: str, column_name: str) -> set[str]:
    if not db_path.exists():
        return set()
    try:
        with sqlite3.connect(db_path) as conn:
            rows = conn.execute(f"SELECT DISTINCT {column_name} FROM {table_name}").fetchall()
    except sqlite3.Error:
        return set()
    return {str(row[0]) for row in rows if row and row[0] is not None}


def _sqlite_user_ids_by_usernames(db_path: Path, table_name: str, usernames: set[str]) -> set[str]:
    if not db_path.exists() or not usernames:
        return set()
    normalized = sorted(_normalize_username(username) for username in usernames if username)
    if not normalized:
        return set()
    placeholders = ", ".join("?" for _ in normalized)
    try:
        with sqlite3.connect(db_path) as conn:
            rows = conn.execute(
                f"""
                SELECT DISTINCT user_id
                FROM {table_name}
                WHERE LOWER(COALESCE(username, '')) IN ({placeholders})
                """,
                normalized,
            ).fetchall()
    except sqlite3.Error:
        return set()
    return {str(row[0]) for row in rows if row and row[0] is not None}


def _json_user_ids_by_usernames(storage_root: Path, usernames: set[str]) -> set[str]:
    normalized = {_normalize_username(username) for username in usernames if username}
    if not storage_root.exists() or not normalized:
        return set()
    user_ids: set[str] = set()
    for path in storage_root.rglob("*.json"):
        items = _read_json_list(path)
        if not items:
            continue
        for item in items:
            username = _normalize_username(str(item.get("username") or ""))
            if username not in normalized:
                continue
            user_id = str(item.get("user_id") or _user_id_from_storage_path(path) or "")
            if user_id:
                user_ids.add(user_id)
    return user_ids


def _excluded_stats_user_ids(storage_root: Path) -> set[str]:
    user_ids = _json_user_ids_by_usernames(storage_root, ADMIN_STATS_EXCLUDED_USERNAMES)
    user_ids |= _sqlite_user_ids_by_usernames(
        storage_root / "vahaduo_sources.sqlite3",
        "vahaduo_saved_sources",
        ADMIN_STATS_EXCLUDED_USERNAMES,
    )
    user_ids |= _sqlite_user_ids_by_usernames(
        storage_root / "vahaduo_targets.sqlite3",
        "vahaduo_saved_targets",
        ADMIN_STATS_EXCLUDED_USERNAMES,
    )
    return user_ids


def _user_ids_from_storage(root: Path, *, excluded_user_ids: set[str] | None = None) -> set[str]:
    users_root = root / "users"
    if not users_root.exists():
        return set()
    excluded = excluded_user_ids or set()
    return {path.name for path in users_root.iterdir() if path.is_dir() and path.name not in excluded}


def _collect_my_dna_stats(my_data_root: Path, *, excluded_user_ids: set[str] | None = None) -> dict[str, int]:
    stats = {
        "users": 0,
        "samples": 0,
        "raw_files": 0,
        "coordinates": 0,
        "g25_coordinates": 0,
        "k36_coordinates": 0,
    }
    users_root = my_data_root / "users"
    if not users_root.exists():
        return stats

    excluded = excluded_user_ids or set()
    for user_dir in users_root.iterdir():
        if not user_dir.is_dir():
            continue
        if user_dir.name in excluded:
            continue
        stats["users"] += 1
        stats["samples"] += len(_read_json_list(user_dir / "samples.json"))
        stats["raw_files"] += len(_read_json_list(user_dir / "raw_files.json"))
        coordinates = _read_json_list(user_dir / "coordinates.json")
        stats["coordinates"] += len(coordinates)
        for item in coordinates:
            coordinate_type = str(item.get("coordinate_type") or item.get("type") or "").lower()
            if "g25" in coordinate_type:
                stats["g25_coordinates"] += 1
            elif "k36" in coordinate_type:
                stats["k36_coordinates"] += 1
    return stats


def _admin_stats_text(context: ContextTypes.DEFAULT_TYPE, *, current_admin_user_id: int | None = None) -> str:
    storage_root = _storage_root(context)
    excluded_user_ids = _excluded_stats_user_ids(storage_root)
    if current_admin_user_id is not None:
        excluded_user_ids.add(str(int(current_admin_user_id)))
    my_dna = _collect_my_dna_stats(storage_root / "my_data", excluded_user_ids=excluded_user_ids)
    my_dna_user_ids = _user_ids_from_storage(storage_root / "my_data", excluded_user_ids=excluded_user_ids)

    coordinate_reports = _count_index_items(
        storage_root / "coordinate_space" / "reports",
        "users/*/samples/*/coordinate_space_reports.json",
        excluded_user_ids=excluded_user_ids,
    )
    admixture_reports = _count_index_items(
        storage_root / "admixture",
        "users/*/samples/*/admixture_reports.json",
        excluded_user_ids=excluded_user_ids,
    )
    matching_records = _count_index_items(
        storage_root / "matching",
        "users/*/matches.json",
        excluded_user_ids=excluded_user_ids,
    )
    trait_reports = _count_index_items(
        storage_root / "traits",
        "users/*/samples/*/trait_reports.json",
        excluded_user_ids=excluded_user_ids,
    )
    haplogroup_records = _count_index_items(
        storage_root / "haplogroups",
        "users/*/haplogroups.json",
        excluded_user_ids=excluded_user_ids,
    )
    y_str_profiles = _count_index_items(
        storage_root / "haplogroups",
        "users/*/y_str_profiles.json",
        excluded_user_ids=excluded_user_ids,
    )
    coordinate_user_ids = _user_ids_from_storage(
        storage_root / "coordinate_space" / "reports",
        excluded_user_ids=excluded_user_ids,
    )
    admixture_user_ids = _user_ids_from_storage(storage_root / "admixture", excluded_user_ids=excluded_user_ids)
    matching_user_ids = _user_ids_from_storage(storage_root / "matching", excluded_user_ids=excluded_user_ids)
    trait_user_ids = _user_ids_from_storage(storage_root / "traits", excluded_user_ids=excluded_user_ids)
    haplogroup_user_ids = _user_ids_from_storage(storage_root / "haplogroups", excluded_user_ids=excluded_user_ids)
    vahaduo_source_user_ids = _sqlite_distinct_values(
        storage_root / "vahaduo_sources.sqlite3",
        "vahaduo_saved_sources",
        "user_id",
    ) - excluded_user_ids
    vahaduo_target_user_ids = _sqlite_distinct_values(
        storage_root / "vahaduo_targets.sqlite3",
        "vahaduo_saved_targets",
        "user_id",
    ) - excluded_user_ids
    vahaduo_sources = _count_sqlite_rows(
        storage_root / "vahaduo_sources.sqlite3",
        "vahaduo_saved_sources",
        excluded_user_ids=excluded_user_ids,
    )
    vahaduo_targets = _count_sqlite_rows(
        storage_root / "vahaduo_targets.sqlite3",
        "vahaduo_saved_targets",
        excluded_user_ids=excluded_user_ids,
    )
    all_user_ids = set().union(
        my_dna_user_ids,
        coordinate_user_ids,
        admixture_user_ids,
        matching_user_ids,
        trait_user_ids,
        haplogroup_user_ids,
        vahaduo_source_user_ids,
        vahaduo_target_user_ids,
    )

    saved_artifacts = (
        my_dna["samples"]
        + my_dna["raw_files"]
        + my_dna["g25_coordinates"]
        + coordinate_reports
        + admixture_reports
        + matching_records
        + trait_reports
        + haplogroup_records
        + y_str_profiles
        + vahaduo_sources
        + vahaduo_targets
    )

    return "\n".join(
        [
            "📊 Статистика DNA Lab",
            "",
            f"👥 Пользователи: {len(all_user_ids)}",
            f"💾 Сохраненные объекты: {saved_artifacts}",
            "",
            "📁 My DNA",
            f"Samples: {my_dna['samples']} · Raw files: {my_dna['raw_files']} · G25: {my_dna['g25_coordinates']}",
            "",
            "🧭 Coordinate spaces",
            f"Reports: {coordinate_reports}",
            "",
            "🧪 Vahaduo Lab",
            f"Sources: {vahaduo_sources} · Targets: {vahaduo_targets}",
            "",
            "🧬 Admixture",
            f"Reports: {admixture_reports}",
            "",
            "🧩 Matching",
            f"Matches: {matching_records}",
            "",
            "🧾 Traits",
            f"Reports: {trait_reports}",
            "",
            "🌿 Haplogroups",
            f"Records: {haplogroup_records} · Y-STR: {y_str_profiles}",
        ]
    )


async def admin_stats_reply_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    if not _is_stats_admin(update):
        return
    await _ensure_reply_menu(update, context)
    user_id = int(update.effective_user.id) if update.effective_user is not None else None
    await update.message.reply_text(_admin_stats_text(context, current_admin_user_id=user_id), do_quote=False)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await show_start_hint(update, context)


async def main_menu_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None or query.message is None:
        return
    if not query.data.startswith(f"{MAIN_CALLBACK_PREFIX}:"):
        return

    if update.effective_chat is not None and update.effective_user is not None:
        store = _menu_store(context)
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        active_message_id = store.get(chat_id, user_id)
        if active_message_id is not None and active_message_id != query.message.message_id:
            await query.answer(t("main.menu_stale", _language_for_update(update, context)))
            return
        store.set(chat_id, user_id, query.message.message_id)

    await query.answer()

    action = query.data.split(":", 1)[1]
    if action == "root":
        if update.effective_chat is not None and update.effective_user is not None:
            _clear_pending_section_input(context, update.effective_chat.id, update.effective_user.id)
        await show_main_menu(query.message, context, update.effective_user.id, edit_existing=True)
        return
    if action == "cancel":
        if update.effective_chat is not None and update.effective_user is not None:
            _clear_pending_section_input(context, update.effective_chat.id, update.effective_user.id)
            clear_active_main_menu_message(
                context,
                update.effective_chat.id,
                update.effective_user.id,
                query.message.message_id,
            )
        await query.edit_message_text(t("main.closed", _language_for_update(update, context)))
        return
