from __future__ import annotations

import logging
import re
import sqlite3
from pathlib import Path

from telegram import Update

logger = logging.getLogger(__name__)


class G25AccessStore:
    def __init__(self, path: Path, admin_ids: set[int] | None = None, admin_usernames: set[str] | None = None) -> None:
        self.admin_ids = set(admin_ids or set())
        self.admin_usernames = {self._normalize_username(item) for item in (admin_usernames or set()) if item}

    @staticmethod
    def _normalize_username(value: str | None) -> str:
        if not value:
            return ""
        return value.strip().lstrip("@").lower()

    def is_admin(self, update: Update) -> bool:
        user = update.effective_user
        if user is None:
            return False
        username = self._normalize_username(getattr(user, "username", None))
        return getattr(user, "id", None) in self.admin_ids or username in self.admin_usernames

    def format_admin_list(self) -> str:
        usernames = ", ".join(f"@{item}" for item in sorted(self.admin_usernames)) or "-"
        ids = ", ".join(str(item) for item in sorted(self.admin_ids)) or "-"
        lines = [
            "<b>Доступ к статистике</b>",
            "",
            f"Usernames: {usernames}",
            f"User IDs: {ids}",
        ]
        return "\n".join(lines)


class VahaduoSavedSourceStore:
    def __init__(self, db_path: Path, sources_dir: Path) -> None:
        self.db_path = db_path
        self.sources_dir = sources_dir
        self.sources_dir.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS vahaduo_saved_sources (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    user_id INTEGER NOT NULL,
                    username TEXT,
                    source_kind TEXT NOT NULL DEFAULT 'both',
                    title TEXT NOT NULL,
                    source_path TEXT NOT NULL,
                    source_count INTEGER NOT NULL,
                    source_label TEXT,
                    source_input_mode TEXT
                )
                """
            )
            self._ensure_column(conn, "source_kind", "TEXT", "'both'")
            conn.execute("DROP INDEX IF EXISTS idx_vahaduo_saved_sources_user_title")
            conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_vahaduo_saved_sources_user_kind_title
                ON vahaduo_saved_sources(user_id, source_kind, title)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_vahaduo_saved_sources_user
                ON vahaduo_saved_sources(user_id, updated_at DESC)
                """
            )

    @staticmethod
    def _ensure_column(conn: sqlite3.Connection, name: str, sql_type: str, default_sql: str | None = None) -> None:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(vahaduo_saved_sources)").fetchall()}
        if name in columns:
            return
        default_clause = f" DEFAULT {default_sql}" if default_sql is not None else ""
        conn.execute(f"ALTER TABLE vahaduo_saved_sources ADD COLUMN {name} {sql_type}{default_clause}")

    @staticmethod
    def _clean_title(title: str) -> str:
        cleaned = " ".join(title.strip().split())
        if not cleaned:
            raise ValueError("Название не должно быть пустым.")
        if len(cleaned) > 48:
            cleaned = cleaned[:48].rstrip()
        return cleaned

    @staticmethod
    def _safe_slug(value: str) -> str:
        slug = re.sub(r"[^\w.-]+", "_", value, flags=re.U).strip("._-")
        return slug or "source"

    @staticmethod
    def _clean_source_kind(source_kind: str) -> str:
        cleaned = (source_kind or "both").strip().lower()
        if cleaned == "multi":
            cleaned = "single"
        if cleaned not in {"distance", "single", "both"}:
            cleaned = "both"
        return cleaned

    @staticmethod
    def _source_kind_aliases(source_kind: str) -> tuple[str, ...]:
        cleaned = VahaduoSavedSourceStore._clean_source_kind(source_kind)
        if cleaned == "single":
            return ("single", "multi")
        return (cleaned,)

    def list_for_user(self, user_id: int, source_kind: str | None = None) -> list[dict[str, object]]:
        params: tuple[object, ...]
        where = "user_id = ?"
        params = (int(user_id),)
        if source_kind:
            cleaned_kind = self._clean_source_kind(source_kind)
            allowed_kinds = list(dict.fromkeys([*self._source_kind_aliases(cleaned_kind), "both"]))
            placeholders = ", ".join("?" for _ in allowed_kinds)
            where += f" AND source_kind IN ({placeholders})"
            params = (int(user_id), *allowed_kinds)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT id, title, source_path, source_count, source_label, source_input_mode, source_kind, updated_at
                FROM vahaduo_saved_sources
                WHERE {where}
                ORDER BY updated_at DESC, id DESC
                """,
                params,
            ).fetchall()
        items = [dict(row) for row in rows]
        if not source_kind:
            return items
        deduped: list[dict[str, object]] = []
        seen_titles: set[str] = set()
        for item in items:
            title_key = str(item.get("title") or "").casefold()
            if title_key and title_key in seen_titles:
                continue
            if title_key:
                seen_titles.add(title_key)
            deduped.append(item)
        return deduped

    def get_for_user(self, user_id: int, source_id: int, source_kind: str | None = None) -> dict[str, object] | None:
        params: tuple[object, ...]
        where = "user_id = ? AND id = ?"
        params = (int(user_id), int(source_id))
        if source_kind:
            cleaned_kind = self._clean_source_kind(source_kind)
            allowed_kinds = list(dict.fromkeys([*self._source_kind_aliases(cleaned_kind), "both"]))
            placeholders = ", ".join("?" for _ in allowed_kinds)
            where += f" AND source_kind IN ({placeholders})"
            params = (int(user_id), int(source_id), *allowed_kinds)
        with self._connect() as conn:
            row = conn.execute(
                f"""
                SELECT id, title, source_path, source_count, source_label, source_input_mode, source_kind
                FROM vahaduo_saved_sources
                WHERE {where}
                """,
                params,
            ).fetchone()
        return dict(row) if row else None

    def save_for_user(
        self,
        update: Update,
        *,
        title: str,
        source_path: Path,
        source_count: int,
        source_label: str,
        source_input_mode: str,
        source_kind: str,
    ) -> dict[str, object]:
        user = update.effective_user
        if user is None or getattr(user, "id", None) is None:
            raise ValueError("Не удалось определить пользователя.")
        user_id = int(user.id)
        title = self._clean_title(title)
        source_kind = self._clean_source_kind(source_kind)
        source_path = Path(source_path)
        if not source_path.exists():
            raise ValueError("Source-файл больше не найден.")

        username = getattr(user, "username", None)
        with self._connect() as conn:
            lookup_kinds = self._source_kind_aliases(source_kind)
            placeholders = ", ".join("?" for _ in lookup_kinds)
            row = conn.execute(
                f"""
                SELECT id FROM vahaduo_saved_sources
                WHERE user_id = ? AND title = ? AND source_kind IN ({placeholders})
                ORDER BY CASE source_kind WHEN ? THEN 0 ELSE 1 END, updated_at DESC, id DESC
                LIMIT 1
                """,
                (user_id, title, *lookup_kinds, source_kind),
            ).fetchone()
            if row:
                source_id = int(row["id"])
            else:
                cursor = conn.execute(
                    """
                    INSERT INTO vahaduo_saved_sources (
                        user_id, username, source_kind, title, source_path, source_count, source_label, source_input_mode
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (user_id, username, source_kind, title, "", int(source_count), source_label, source_input_mode),
                )
                source_id = int(cursor.lastrowid)

            user_dir = self.sources_dir / str(user_id)
            user_dir.mkdir(parents=True, exist_ok=True)
            stored_path = user_dir / f"{source_id}_{source_kind}_{self._safe_slug(title)}.txt"
            stored_path.write_bytes(source_path.read_bytes())
            conn.execute(
                """
                UPDATE vahaduo_saved_sources
                SET username = ?, source_kind = ?, title = ?, source_path = ?, source_count = ?,
                    source_label = ?, source_input_mode = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND user_id = ?
                """,
                (
                    username,
                    source_kind,
                    title,
                    str(stored_path),
                    int(source_count),
                    source_label,
                    source_input_mode,
                    source_id,
                    user_id,
                ),
            )

        saved = self.get_for_user(user_id, source_id)
        if saved is None:
            raise ValueError("Не удалось сохранить набор.")
        return saved

    def delete_for_user(self, user_id: int, source_id: int) -> bool:
        item = self.get_for_user(user_id, source_id)
        if item is None:
            return False
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM vahaduo_saved_sources WHERE user_id = ? AND id = ?",
                (int(user_id), int(source_id)),
            )
        source_path = Path(str(item.get("source_path") or ""))
        try:
            if source_path.exists() and self.sources_dir.resolve() in source_path.resolve().parents:
                source_path.unlink()
        except OSError:
            logger.debug("Failed to delete saved Vahaduo source file", exc_info=True)
        return True


class VahaduoSavedTargetStore:
    def __init__(self, db_path: Path, targets_dir: Path) -> None:
        self.db_path = db_path
        self.targets_dir = targets_dir
        self.targets_dir.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS vahaduo_saved_targets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    user_id INTEGER NOT NULL,
                    username TEXT,
                    title TEXT NOT NULL,
                    target_name TEXT,
                    target_path TEXT NOT NULL,
                    target_input_mode TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_vahaduo_saved_targets_user_title
                ON vahaduo_saved_targets(user_id, title)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_vahaduo_saved_targets_user
                ON vahaduo_saved_targets(user_id, updated_at DESC)
                """
            )

    @staticmethod
    def _clean_title(title: str) -> str:
        cleaned = " ".join(title.strip().split())
        if not cleaned:
            raise ValueError("Название не должно быть пустым.")
        if len(cleaned) > 48:
            cleaned = cleaned[:48].rstrip()
        return cleaned

    @staticmethod
    def _safe_slug(value: str) -> str:
        slug = re.sub(r"[^\w.-]+", "_", value, flags=re.U).strip("._-")
        return slug or "target"

    def list_for_user(self, user_id: int) -> list[dict[str, object]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, title, target_name, target_path, target_input_mode, updated_at
                FROM vahaduo_saved_targets
                WHERE user_id = ?
                ORDER BY updated_at DESC, id DESC
                """,
                (int(user_id),),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_for_user(self, user_id: int, target_id: int) -> dict[str, object] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, title, target_name, target_path, target_input_mode
                FROM vahaduo_saved_targets
                WHERE user_id = ? AND id = ?
                """,
                (int(user_id), int(target_id)),
            ).fetchone()
        return dict(row) if row else None

    def save_for_user(
        self,
        update: Update,
        *,
        title: str,
        target_name: str,
        target_path: Path,
        target_input_mode: str,
    ) -> dict[str, object]:
        user = update.effective_user
        if user is None or getattr(user, "id", None) is None:
            raise ValueError("Не удалось определить пользователя.")
        user_id = int(user.id)
        title = self._clean_title(title)
        target_path = Path(target_path)
        if not target_path.exists():
            raise ValueError("Target-файл больше не найден.")

        username = getattr(user, "username", None)
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id FROM vahaduo_saved_targets
                WHERE user_id = ? AND title = ?
                """,
                (user_id, title),
            ).fetchone()
            if row:
                target_id = int(row["id"])
            else:
                cursor = conn.execute(
                    """
                    INSERT INTO vahaduo_saved_targets (
                        user_id, username, title, target_name, target_path, target_input_mode
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (user_id, username, title, target_name, "", target_input_mode),
                )
                target_id = int(cursor.lastrowid)

            user_dir = self.targets_dir / str(user_id)
            user_dir.mkdir(parents=True, exist_ok=True)
            stored_path = user_dir / f"{target_id}_{self._safe_slug(title)}.g25"
            stored_path.write_bytes(target_path.read_bytes())
            conn.execute(
                """
                UPDATE vahaduo_saved_targets
                SET username = ?, title = ?, target_name = ?, target_path = ?,
                    target_input_mode = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND user_id = ?
                """,
                (
                    username,
                    title,
                    target_name,
                    str(stored_path),
                    target_input_mode,
                    target_id,
                    user_id,
                ),
            )

        saved = self.get_for_user(user_id, target_id)
        if saved is None:
            raise ValueError("Не удалось сохранить target.")
        return saved

    def delete_for_user(self, user_id: int, target_id: int) -> bool:
        item = self.get_for_user(user_id, target_id)
        if item is None:
            return False
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM vahaduo_saved_targets WHERE user_id = ? AND id = ?",
                (int(user_id), int(target_id)),
            )
        target_path = Path(str(item.get("target_path") or ""))
        try:
            if target_path.exists() and self.targets_dir.resolve() in target_path.resolve().parents:
                target_path.unlink()
        except OSError:
            logger.debug("Failed to delete saved Vahaduo target file", exc_info=True)
        return True


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

    def set_selected(self, chat_id: int, user_id: int, selected_keys: list[str]) -> list[str]:
        key = self._key(chat_id, user_id)
        state = self._states.setdefault(key, {"selected": [], "awaiting_input": False, "message_id": None})
        state["selected"] = list(selected_keys)
        state["awaiting_input"] = False
        return list(state["selected"])

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


class VahaduoFullStore:
    def __init__(self) -> None:
        self._states: dict[tuple[int, int], dict[str, object]] = {}

    @staticmethod
    def _key(chat_id: int, user_id: int) -> tuple[int, int]:
        return (int(chat_id), int(user_id))

    @staticmethod
    def _blank_state() -> dict[str, object]:
        return {
            "message_id": None,
            "source_key": "",
            "source_label": "",
            "source_path": "",
            "source_manifest_path": "",
            "source_count": 0,
            "source_input_mode": "",
            "source_saved_id": 0,
            "target_label": "",
            "target_path": "",
            "target_line": "",
            "target_coordinate_id": "",
            "target_readonly": False,
            "target_input_mode": "",
            "target_saved_id": 0,
            "mode": "",
            "awaiting": "",
        }

    def open(self, chat_id: int, user_id: int) -> dict[str, object]:
        state = self._blank_state()
        self._states[self._key(chat_id, user_id)] = state
        return state

    def get(self, chat_id: int, user_id: int) -> dict[str, object] | None:
        return self._states.get(self._key(chat_id, user_id))

    def set_message_id(self, chat_id: int, user_id: int, message_id: int) -> None:
        state = self._states.setdefault(self._key(chat_id, user_id), self._blank_state())
        state["message_id"] = int(message_id)

    def set_source(
        self,
        chat_id: int,
        user_id: int,
        *,
        source_key: str,
        source_label: str,
        source_path: Path,
        source_count: int,
        source_input_mode: str,
        source_saved_id: int = 0,
        source_manifest_path: Path | None = None,
    ) -> dict[str, object]:
        state = self._states.setdefault(self._key(chat_id, user_id), self._blank_state())
        state["source_key"] = source_key
        state["source_label"] = source_label
        state["source_path"] = str(source_path)
        state["source_manifest_path"] = str(source_manifest_path) if source_manifest_path is not None else ""
        state["source_count"] = int(source_count)
        state["source_input_mode"] = source_input_mode
        state["source_saved_id"] = int(source_saved_id)
        state["awaiting"] = ""
        return state

    def mark_source_saved(self, chat_id: int, user_id: int, source_id: int, title: str, source_path: Path) -> dict[str, object]:
        state = self._states.setdefault(self._key(chat_id, user_id), self._blank_state())
        state["source_key"] = f"saved_{int(source_id)}"
        state["source_label"] = title
        state["source_path"] = str(source_path)
        state["source_manifest_path"] = ""
        state["source_saved_id"] = int(source_id)
        state["source_input_mode"] = "saved"
        state["awaiting"] = ""
        return state

    def set_target(
        self,
        chat_id: int,
        user_id: int,
        *,
        target_label: str,
        target_path: Path,
        target_input_mode: str,
        target_saved_id: int = 0,
    ) -> dict[str, object]:
        state = self._states.setdefault(self._key(chat_id, user_id), self._blank_state())
        state["target_label"] = target_label
        state["target_path"] = str(target_path)
        state["target_line"] = ""
        state["target_coordinate_id"] = ""
        state["target_readonly"] = False
        state["target_input_mode"] = target_input_mode
        state["target_saved_id"] = int(target_saved_id)
        state["awaiting"] = ""
        return state

    def mark_target_saved(self, chat_id: int, user_id: int, target_id: int, title: str, target_path: Path) -> dict[str, object]:
        state = self._states.setdefault(self._key(chat_id, user_id), self._blank_state())
        state["target_label"] = title
        state["target_path"] = str(target_path)
        state["target_line"] = ""
        state["target_coordinate_id"] = ""
        state["target_readonly"] = False
        state["target_saved_id"] = int(target_id)
        state["target_input_mode"] = "saved"
        state["awaiting"] = ""
        return state

    def set_mode(self, chat_id: int, user_id: int, mode: str, *, awaiting: str = "target") -> dict[str, object]:
        state = self._states.setdefault(self._key(chat_id, user_id), self._blank_state())
        state["mode"] = mode
        state["awaiting"] = awaiting
        return state

    def set_awaiting(self, chat_id: int, user_id: int, step: str) -> dict[str, object]:
        state = self._states.setdefault(self._key(chat_id, user_id), self._blank_state())
        state["awaiting"] = step
        return state

    def set_value(self, chat_id: int, user_id: int, key: str, value: object) -> dict[str, object]:
        state = self._states.setdefault(self._key(chat_id, user_id), self._blank_state())
        state[key] = value
        return state

    def toggle_single_component(self, chat_id: int, user_id: int, panel_key: str, source_key: str) -> list[str]:
        state = self._states.setdefault(self._key(chat_id, user_id), self._blank_state())
        current_panel = str(state.get("single_panel") or "")
        selected = list(state.get("single_selected") or []) if current_panel == panel_key else []
        if source_key in selected:
            selected.remove(source_key)
        else:
            selected.append(source_key)
        state["single_panel"] = panel_key
        state["single_selected"] = selected
        state["awaiting"] = ""
        return selected

    def clear_single_components(self, chat_id: int, user_id: int, panel_key: str) -> list[str]:
        state = self._states.setdefault(self._key(chat_id, user_id), self._blank_state())
        state["single_panel"] = panel_key
        state["single_selected"] = []
        state["awaiting"] = ""
        return []

    def has_pending(self, chat_id: int, user_id: int, step: str | None = None) -> bool:
        state = self.get(chat_id, user_id)
        if not state:
            return False
        awaiting = str(state.get("awaiting") or "")
        return bool(awaiting) if step is None else awaiting == step

    def clear_pending(self, chat_id: int, user_id: int) -> None:
        state = self.get(chat_id, user_id)
        if state:
            state["awaiting"] = ""

    def cancel(self, chat_id: int, user_id: int) -> None:
        self._states.pop(self._key(chat_id, user_id), None)


