from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import sqlite3
from typing import Any


VISIBLE_G25_STATS_COMMANDS = ("vahaduo_distance", "vahaduo_single", "vahaduo_multi")
USAGE_EXCLUDED_USERNAMES = {"jb_cc"}
VISIBLE_ANALYTICS_COMMANDS = (
    "navigator",
    "haplo_families",
    "haplo_tests",
    "mtdna_groups",
    "mtdna_subclades",
    "mtdna_navigator",
    "mtdna_nav_group",
    "mtdna_nav_subclade",
    "nav_group",
    "nav_subclade",
)
VISIBLE_DNA_LAB_RESULT_ACTIONS = {
    "admixture": (
        "cr",
        "k",
        "mo",
        "mr",
        "o",
        "omr",
        "or",
        "run",
        "save",
        "savem",
        "svx",
        "x",
    ),
    "coordinate_space": (),
    "haplogroups": (
        "dpick",
        "ho",
        "o",
        "strb",
        "yp",
    ),
    "matching": (
        "allrun",
        "b",
        "m",
        "save",
        "snprun",
        "srun",
    ),
    "modeling": (
        "fit_run",
        "qpadm_run",
        "qpwave_run",
        "saved_save",
        "ss_save_current",
    ),
    "my_data": (
        "coordinate_add",
        "coordinate_extract",
        "qg25_create_sample",
        "qg25_save_g25_library",
        "raw_upload",
        "sample_create",
    ),
    "snp_report": (
        "html",
        "lookup",
        "run",
    ),
    "traits": (
        "o",
        "sr",
        "sv",
        "u",
    ),
}
VISIBLE_DNA_LAB_RESULT_LIKE = {
    "coordinate_space": (
        "%_sample",
        "%_save",
        "%_savep",
    ),
}


class UsageStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    @staticmethod
    def _excluded_usernames_sql() -> str:
        return ", ".join("'" + username.replace("'", "''") + "'" for username in sorted(USAGE_EXCLUDED_USERNAMES))

    @staticmethod
    def _sql_in(values: tuple[str, ...]) -> str:
        if not values:
            return "('')"
        return "(" + ", ".join("'" + value.replace("'", "''") + "'" for value in values) + ")"

    @classmethod
    def _visible_dna_lab_events_sql(cls) -> str:
        analytics_commands = cls._sql_in(VISIBLE_ANALYTICS_COMMANDS)
        g25_commands = cls._sql_in(VISIBLE_G25_STATS_COMMANDS)
        dna_lab_sections: list[str] = []
        for section, actions in sorted(VISIBLE_DNA_LAB_RESULT_ACTIONS.items()):
            conditions: list[str] = []
            if actions:
                conditions.append(f"COALESCE(NULLIF(query, ''), 'open') IN {cls._sql_in(actions)}")
            for pattern in VISIBLE_DNA_LAB_RESULT_LIKE.get(section, ()):
                escaped_pattern = pattern.replace("'", "''")
                conditions.append(f"COALESCE(NULLIF(query, ''), 'open') LIKE '{escaped_pattern}'")
            if not conditions:
                continue
            section_sql = section.replace("'", "''")
            dna_lab_sections.append(
                f"(COALESCE(NULLIF(command, ''), 'unknown') = '{section_sql}' AND ({' OR '.join(conditions)}))"
            )
        dna_lab_sql = "\n                    OR ".join(dna_lab_sections) or "0"
        return f"""
                (
                    event_type IN ('lookup', 'sozluk', 'ystr')
                    OR (event_type = 'analytics' AND (
                        command IN {analytics_commands}
                        OR command LIKE 'subclade:%'
                        OR command LIKE 'subclade_group:%'
                    ))
                    OR (event_type = 'g25' AND command IN {g25_commands})
                    OR (event_type = 'dna_lab' AND (
                    {dna_lab_sql}
                    ))
                )
        """

    @staticmethod
    def _summary_section_sql() -> str:
        return """
            CASE
                WHEN event_type = 'lookup' THEN 'lookup'
                WHEN event_type = 'sozluk' THEN 'sozluk'
                WHEN event_type IN ('analytics', 'ystr') THEN 'analytics'
                WHEN event_type = 'g25' THEN 'vahaduo'
                WHEN event_type = 'dna_lab' AND command = 'quick_g25' THEN 'my_data'
                WHEN event_type = 'dna_lab' THEN COALESCE(NULLIF(command, ''), 'unknown')
                ELSE COALESCE(NULLIF(event_type, ''), 'unknown')
            END
        """

    def _prepare_stats_connection(self, conn: sqlite3.Connection) -> None:
        excluded_usernames = self._excluded_usernames_sql()
        visible_dna_lab_events_sql = self._visible_dna_lab_events_sql()
        conn.execute("DROP VIEW IF EXISTS temp.usage_events")
        if not excluded_usernames:
            conn.execute(
                f"""
                CREATE TEMP VIEW usage_events AS
                SELECT *
                FROM main.usage_events
                WHERE {visible_dna_lab_events_sql}
                  AND (
                    event_type <> 'g25'
                    OR command IN ('vahaduo_distance', 'vahaduo_single', 'vahaduo_multi')
                  )
                """
            )
            return
        conn.execute(
            f"""
            CREATE TEMP VIEW usage_events AS
            SELECT *
            FROM main.usage_events
            WHERE {visible_dna_lab_events_sql}
              AND (
                    event_type <> 'g25'
                    OR command IN ('vahaduo_distance', 'vahaduo_single', 'vahaduo_multi')
                )
              AND (
                    username IS NULL
                    OR LOWER(LTRIM(username, '@')) NOT IN ({excluded_usernames})
                )
            """
        )

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

    def record_lookup(self, update: Any, query: str, success: bool) -> None:
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
        update: Any,
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

    def record_analytics(self, update: Any, command: str, success: bool = True) -> None:
        self.record_event(
            update=update,
            query="",
            success=success,
            event_type="analytics",
            command=command,
            input_mode="menu",
        )

    def record_sozluk(self, update: Any, query: str, success: bool, command: str = "lookup") -> None:
        self.record_event(
            update=update,
            query=query,
            success=success,
            event_type="sozluk",
            command=command,
            input_mode="text",
        )

    def record_ystr(self, update: Any, command: str, success: bool = True, query: str | None = None, input_mode: str = "menu") -> None:
        self.record_event(
            update=update,
            query=query or "",
            success=success,
            event_type="ystr",
            command=command,
            input_mode=input_mode,
        )

    def record_dna_lab(
        self,
        update: Any,
        feature: str,
        action: str | None = None,
        success: bool = True,
        input_mode: str = "callback",
    ) -> None:
        self.record_event(
            update=update,
            query=action or "",
            success=success,
            event_type="dna_lab",
            command=feature,
            input_mode=input_mode,
        )

    def record_event(
        self,
        update: Any,
        query: str,
        success: bool,
        event_type: str,
        command: str | None = None,
        input_mode: str | None = None,
    ) -> None:
        user = update.effective_user
        chat = update.effective_chat
        username = (getattr(user, "username", None) or "").strip().lstrip("@").lower()
        if username in USAGE_EXCLUDED_USERNAMES:
            return
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
            self._prepare_stats_connection(conn)
            total = conn.execute("SELECT COUNT(*) FROM usage_events").fetchone()[0]
            success = conn.execute("SELECT COUNT(*) FROM usage_events WHERE success = 1").fetchone()[0]
            unique_users = conn.execute(
                "SELECT COUNT(DISTINCT user_id) FROM usage_events WHERE user_id IS NOT NULL"
            ).fetchone()[0]
            unique_users_last_7_days = conn.execute(
                """
                SELECT COUNT(DISTINCT user_id)
                FROM usage_events
                WHERE user_id IS NOT NULL
                  AND datetime(created_at, 'localtime') >= datetime('now', '-6 days', 'localtime')
                """
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
            last_30_days = conn.execute(
                """
                SELECT COUNT(*) FROM usage_events
                WHERE date(created_at, 'localtime') >= date('now', '-29 days', 'localtime')
                """
            ).fetchone()[0]
            summary_section_sql = self._summary_section_sql()
            summary_section_stats = conn.execute(
                f"""
                SELECT
                    section_key,
                    COUNT(*) AS total,
                    SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) AS success,
                    SUM(CASE WHEN date(created_at, 'localtime') = date('now', 'localtime') THEN 1 ELSE 0 END) AS today,
                    SUM(CASE WHEN datetime(created_at, 'localtime') >= datetime('now', '-6 days', 'localtime') THEN 1 ELSE 0 END) AS last_7_days,
                    COUNT(DISTINCT CASE WHEN user_id IS NOT NULL THEN user_id END) AS unique_users
                FROM (
                    SELECT {summary_section_sql} AS section_key, *
                    FROM usage_events
                )
                GROUP BY section_key
                """
            ).fetchall()
            private_events = conn.execute(
                "SELECT COUNT(*) FROM usage_events WHERE chat_type = 'private'"
            ).fetchone()[0]
            group_events = conn.execute(
                "SELECT COUNT(*) FROM usage_events WHERE chat_type IS NOT NULL AND chat_type <> 'private'"
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
            sozluk_total = conn.execute(
                "SELECT COUNT(*) FROM usage_events WHERE event_type = 'sozluk'"
            ).fetchone()[0]
            sozluk_success = conn.execute(
                "SELECT COUNT(*) FROM usage_events WHERE event_type = 'sozluk' AND success = 1"
            ).fetchone()[0]
            sozluk_today = conn.execute(
                """
                SELECT COUNT(*) FROM usage_events
                WHERE event_type = 'sozluk' AND date(created_at, 'localtime') = date('now', 'localtime')
                """
            ).fetchone()[0]
            sozluk_last_7_days = conn.execute(
                """
                SELECT COUNT(*) FROM usage_events
                WHERE event_type = 'sozluk' AND datetime(created_at, 'localtime') >= datetime('now', '-6 days', 'localtime')
                """
            ).fetchone()[0]
            sozluk_unique_users = conn.execute(
                "SELECT COUNT(DISTINCT user_id) FROM usage_events WHERE event_type = 'sozluk' AND user_id IS NOT NULL"
            ).fetchone()[0]
            sozluk_top_queries = conn.execute(
                """
                SELECT query, COUNT(*) AS cnt
                FROM usage_events
                WHERE event_type = 'sozluk' AND query IS NOT NULL AND TRIM(query) != ''
                GROUP BY LOWER(query)
                ORDER BY cnt DESC, LOWER(query) ASC
                LIMIT 25
                """
            ).fetchall()
            ystr_total = conn.execute(
                "SELECT COUNT(*) FROM usage_events WHERE event_type = 'ystr'"
            ).fetchone()[0]
            ystr_success = conn.execute(
                "SELECT COUNT(*) FROM usage_events WHERE event_type = 'ystr' AND success = 1"
            ).fetchone()[0]
            ystr_today = conn.execute(
                """
                SELECT COUNT(*) FROM usage_events
                WHERE event_type = 'ystr' AND date(created_at, 'localtime') = date('now', 'localtime')
                """
            ).fetchone()[0]
            ystr_last_7_days = conn.execute(
                """
                SELECT COUNT(*) FROM usage_events
                WHERE event_type = 'ystr' AND date(created_at, 'localtime') >= date('now', '-6 days', 'localtime')
                """
            ).fetchone()[0]
            ystr_unique_users = conn.execute(
                "SELECT COUNT(DISTINCT user_id) FROM usage_events WHERE event_type = 'ystr' AND user_id IS NOT NULL"
            ).fetchone()[0]
            ystr_nearest = conn.execute(
                "SELECT COUNT(*) FROM usage_events WHERE event_type = 'ystr' AND command IN ('nearest', 'upload_nearest')"
            ).fetchone()[0]
            ystr_testdata = conn.execute(
                "SELECT COUNT(*) FROM usage_events WHERE event_type = 'ystr' AND command = 'testdata'"
            ).fetchone()[0]
            ystr_compare = conn.execute(
                "SELECT COUNT(*) FROM usage_events WHERE event_type = 'ystr' AND command IN ('compare', 'upload_compare')"
            ).fetchone()[0]
            ystr_upload = conn.execute(
                "SELECT COUNT(*) FROM usage_events WHERE event_type = 'ystr' AND command = 'upload'"
            ).fetchone()[0]
            dna_lab_total = conn.execute(
                "SELECT COUNT(*) FROM usage_events WHERE event_type = 'dna_lab'"
            ).fetchone()[0]
            dna_lab_success = conn.execute(
                "SELECT COUNT(*) FROM usage_events WHERE event_type = 'dna_lab' AND success = 1"
            ).fetchone()[0]
            dna_lab_today = conn.execute(
                """
                SELECT COUNT(*) FROM usage_events
                WHERE event_type = 'dna_lab' AND date(created_at, 'localtime') = date('now', 'localtime')
                """
            ).fetchone()[0]
            dna_lab_last_7_days = conn.execute(
                """
                SELECT COUNT(*) FROM usage_events
                WHERE event_type = 'dna_lab' AND datetime(created_at, 'localtime') >= datetime('now', '-6 days', 'localtime')
                """
            ).fetchone()[0]
            dna_lab_unique_users = conn.execute(
                "SELECT COUNT(DISTINCT user_id) FROM usage_events WHERE event_type = 'dna_lab' AND user_id IS NOT NULL"
            ).fetchone()[0]
            dna_lab_sections = conn.execute(
                """
                SELECT COALESCE(NULLIF(command, ''), 'unknown') AS section, COUNT(*) AS cnt
                FROM usage_events
                WHERE event_type = 'dna_lab'
                GROUP BY section
                ORDER BY cnt DESC, section COLLATE NOCASE ASC
                LIMIT 20
                """
            ).fetchall()
            dna_lab_section_stats = conn.execute(
                """
                SELECT
                    COALESCE(NULLIF(command, ''), 'unknown') AS section,
                    COUNT(*) AS total,
                    SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) AS success,
                    SUM(CASE WHEN date(created_at, 'localtime') = date('now', 'localtime') THEN 1 ELSE 0 END) AS today,
                    SUM(CASE WHEN datetime(created_at, 'localtime') >= datetime('now', '-6 days', 'localtime') THEN 1 ELSE 0 END) AS last_7_days,
                    COUNT(DISTINCT CASE WHEN user_id IS NOT NULL THEN user_id END) AS unique_users
                FROM usage_events
                WHERE event_type = 'dna_lab'
                GROUP BY section
                """
            ).fetchall()
            dna_lab_top_actions = conn.execute(
                """
                SELECT
                    COALESCE(NULLIF(command, ''), 'unknown') AS section,
                    COALESCE(NULLIF(query, ''), 'open') AS action,
                    COUNT(*) AS cnt
                FROM usage_events
                WHERE event_type = 'dna_lab'
                GROUP BY section, action
                ORDER BY cnt DESC, section COLLATE NOCASE ASC, action COLLATE NOCASE ASC
                LIMIT 20
                """
            ).fetchall()
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
            g25_extract_success = conn.execute(
                "SELECT COUNT(*) FROM usage_events WHERE event_type = 'g25' AND command = 'g25' AND success = 1"
            ).fetchone()[0]
            g25_extract_today = conn.execute(
                """
                SELECT COUNT(*) FROM usage_events
                WHERE event_type = 'g25'
                  AND command = 'g25'
                  AND date(created_at, 'localtime') = date('now', 'localtime')
                """
            ).fetchone()[0]
            g25_extract_last_7_days = conn.execute(
                """
                SELECT COUNT(*) FROM usage_events
                WHERE event_type = 'g25'
                  AND command = 'g25'
                  AND datetime(created_at, 'localtime') >= datetime('now', '-6 days', 'localtime')
                """
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
            g25_distance_total = conn.execute(
                "SELECT COUNT(*) FROM usage_events WHERE event_type = 'g25' AND command IN ('distance_modern', 'distance_origin')"
            ).fetchone()[0]
            g25_distance_modern = conn.execute(
                "SELECT COUNT(*) FROM usage_events WHERE event_type = 'g25' AND command = 'distance_modern'"
            ).fetchone()[0]
            g25_distance_ancestry = conn.execute(
                "SELECT COUNT(*) FROM usage_events WHERE event_type = 'g25' AND command = 'distance_origin'"
            ).fetchone()[0]
            g25_raw = conn.execute(
                "SELECT COUNT(*) FROM usage_events WHERE event_type = 'g25' AND input_mode = 'raw-file'"
            ).fetchone()[0]
            g25_text = conn.execute(
                "SELECT COUNT(*) FROM usage_events WHERE event_type = 'g25' AND input_mode IN ('g25-text', 'g25-file')"
            ).fetchone()[0]
            visible_g25_commands = VISIBLE_G25_STATS_COMMANDS
            visible_g25_placeholders = ", ".join("?" for _ in visible_g25_commands)
            g25_menu_total = conn.execute(
                f"SELECT COUNT(*) FROM usage_events WHERE event_type = 'g25' AND command IN ({visible_g25_placeholders})",
                visible_g25_commands,
            ).fetchone()[0]
            g25_menu_success = conn.execute(
                f"SELECT COUNT(*) FROM usage_events WHERE event_type = 'g25' AND success = 1 AND command IN ({visible_g25_placeholders})",
                visible_g25_commands,
            ).fetchone()[0]
            g25_menu_today = conn.execute(
                f"""
                SELECT COUNT(*) FROM usage_events
                WHERE event_type = 'g25'
                  AND date(created_at, 'localtime') = date('now', 'localtime')
                  AND command IN ({visible_g25_placeholders})
                """,
                visible_g25_commands,
            ).fetchone()[0]
            g25_menu_last_7_days = conn.execute(
                f"""
                SELECT COUNT(*) FROM usage_events
                WHERE event_type = 'g25'
                  AND datetime(created_at, 'localtime') >= datetime('now', '-6 days', 'localtime')
                  AND command IN ({visible_g25_placeholders})
                """,
                visible_g25_commands,
            ).fetchone()[0]
            g25_menu_unique_users = conn.execute(
                f"""
                SELECT COUNT(DISTINCT user_id) FROM usage_events
                WHERE event_type = 'g25'
                  AND user_id IS NOT NULL
                  AND command IN ({visible_g25_placeholders})
                """,
                visible_g25_commands,
            ).fetchone()[0]
            g25_menu_raw = conn.execute(
                f"""
                SELECT COUNT(*) FROM usage_events
                WHERE event_type = 'g25'
                  AND input_mode = 'raw-file'
                  AND command IN ({visible_g25_placeholders})
                """,
                visible_g25_commands,
            ).fetchone()[0]
            g25_menu_text = conn.execute(
                f"""
                SELECT COUNT(*) FROM usage_events
                WHERE event_type = 'g25'
                  AND input_mode IN ('g25-text', 'g25-file')
                  AND command IN ({visible_g25_placeholders})
                """,
                visible_g25_commands,
            ).fetchone()[0]
            g25_quick_panel = conn.execute(
                "SELECT COUNT(*) FROM usage_events WHERE event_type = 'g25' AND command = 'panel'"
            ).fetchone()[0]
            g25_vahaduo_distance = conn.execute(
                "SELECT COUNT(*) FROM usage_events WHERE event_type = 'g25' AND command = 'vahaduo_distance'"
            ).fetchone()[0]
            g25_vahaduo_single = conn.execute(
                "SELECT COUNT(*) FROM usage_events WHERE event_type = 'g25' AND command = 'vahaduo_single'"
            ).fetchone()[0]
            g25_vahaduo_multi = conn.execute(
                "SELECT COUNT(*) FROM usage_events WHERE event_type = 'g25' AND command = 'vahaduo_multi'"
            ).fetchone()[0]
            g25_vahaduo_total = g25_vahaduo_distance + g25_vahaduo_single + g25_vahaduo_multi
            dna_lab_vahaduo_combined_unique_users = conn.execute(
                f"""
                SELECT COUNT(DISTINCT user_id)
                FROM usage_events
                WHERE user_id IS NOT NULL
                  AND (
                    (event_type = 'dna_lab' AND command = 'vahaduo')
                    OR (event_type = 'g25' AND command IN ({visible_g25_placeholders}))
                  )
                """,
                visible_g25_commands,
            ).fetchone()[0]
            analytics_total = conn.execute(
                """
                SELECT COUNT(*) FROM usage_events
                WHERE event_type = 'analytics' AND (
                    command = 'navigator'
                    OR command = 'haplo_families'
                    OR command = 'haplo_tests'
                    OR command = 'mtdna_groups'
                    OR command = 'mtdna_subclades'
                    OR command = 'mtdna_navigator'
                    OR command = 'mtdna_nav_group'
                    OR command = 'mtdna_nav_subclade'
                    OR command = 'nav_group'
                    OR command = 'nav_subclade'
                    OR command LIKE 'subclade:%'
                    OR command LIKE 'subclade_group:%'
                )
                """
            ).fetchone()[0]
            analytics_today = conn.execute(
                """
                SELECT COUNT(*) FROM usage_events
                WHERE event_type = 'analytics'
                  AND date(created_at, 'localtime') = date('now', 'localtime')
                  AND (
                    command = 'navigator'
                    OR command = 'haplo_families'
                    OR command = 'haplo_tests'
                    OR command = 'mtdna_groups'
                    OR command = 'mtdna_subclades'
                    OR command = 'mtdna_navigator'
                    OR command = 'mtdna_nav_group'
                    OR command = 'mtdna_nav_subclade'
                    OR command = 'nav_group'
                    OR command = 'nav_subclade'
                    OR command LIKE 'subclade:%'
                    OR command LIKE 'subclade_group:%'
                  )
                """
            ).fetchone()[0]
            analytics_last_7_days = conn.execute(
                """
                SELECT COUNT(*) FROM usage_events
                WHERE event_type = 'analytics'
                  AND date(created_at, 'localtime') >= date('now', '-6 days', 'localtime')
                  AND (
                    command = 'navigator'
                    OR command = 'haplo_families'
                    OR command = 'haplo_tests'
                    OR command = 'mtdna_groups'
                    OR command = 'mtdna_subclades'
                    OR command = 'mtdna_navigator'
                    OR command = 'mtdna_nav_group'
                    OR command = 'mtdna_nav_subclade'
                    OR command = 'nav_group'
                    OR command = 'nav_subclade'
                    OR command LIKE 'subclade:%'
                    OR command LIKE 'subclade_group:%'
                  )
                """
            ).fetchone()[0]
            analytics_unique_users = conn.execute(
                """
                SELECT COUNT(DISTINCT user_id) FROM usage_events
                WHERE event_type = 'analytics'
                  AND user_id IS NOT NULL
                  AND (
                    command = 'navigator'
                    OR command = 'haplo_families'
                    OR command = 'haplo_tests'
                    OR command = 'mtdna_groups'
                    OR command = 'mtdna_subclades'
                    OR command = 'mtdna_navigator'
                    OR command = 'mtdna_nav_group'
                    OR command = 'mtdna_nav_subclade'
                    OR command = 'nav_group'
                    OR command = 'nav_subclade'
                    OR command LIKE 'subclade:%'
                    OR command LIKE 'subclade_group:%'
                  )
                """
            ).fetchone()[0]
            analytics_with_ystr_total = analytics_total + ystr_total
            analytics_with_ystr_today = analytics_today + ystr_today
            analytics_with_ystr_last_7_days = analytics_last_7_days + ystr_last_7_days
            analytics_with_ystr_unique_users = conn.execute(
                """
                SELECT COUNT(DISTINCT user_id) FROM usage_events
                WHERE user_id IS NOT NULL
                  AND (
                    event_type = 'ystr'
                    OR (
                      event_type = 'analytics'
                      AND (
                        command = 'navigator'
                        OR command = 'haplo_families'
                        OR command = 'haplo_tests'
                        OR command = 'mtdna_groups'
                        OR command = 'mtdna_subclades'
                        OR command = 'mtdna_navigator'
                        OR command = 'mtdna_nav_group'
                        OR command = 'mtdna_nav_subclade'
                        OR command = 'nav_group'
                        OR command = 'nav_subclade'
                        OR command LIKE 'subclade:%'
                        OR command LIKE 'subclade_group:%'
                      )
                    )
                  )
                """
            ).fetchone()[0]
            analytics_root = conn.execute(
                "SELECT COUNT(*) FROM usage_events WHERE event_type = 'analytics' AND command = 'root'"
            ).fetchone()[0]
            analytics_diagrams = conn.execute(
                """
                SELECT COUNT(*) FROM usage_events
                WHERE event_type = 'analytics' AND (
                    command = 'diagrams'
                    OR command = 'groupmodes'
                    OR command = 'subclades'
                    OR command = 'haplo_families'
                    OR command = 'haplo_tests'
                    OR command = 'mtdna_groups'
                    OR command = 'mtdna_subclades'
                    OR command LIKE 'subclade:%'
                )
                """
            ).fetchone()[0]
            analytics_navigator = conn.execute(
                "SELECT COUNT(*) FROM usage_events WHERE event_type = 'analytics' AND command = 'navigator'"
            ).fetchone()[0]
            analytics_haplo_families = conn.execute(
                "SELECT COUNT(*) FROM usage_events WHERE event_type = 'analytics' AND command = 'haplo_families'"
            ).fetchone()[0]
            analytics_haplo_tests = conn.execute(
                "SELECT COUNT(*) FROM usage_events WHERE event_type = 'analytics' AND command = 'haplo_tests'"
            ).fetchone()[0]
            analytics_mtdna_groups = conn.execute(
                "SELECT COUNT(*) FROM usage_events WHERE event_type = 'analytics' AND command = 'mtdna_groups'"
            ).fetchone()[0]
            analytics_mtdna_subclades = conn.execute(
                "SELECT COUNT(*) FROM usage_events WHERE event_type = 'analytics' AND command = 'mtdna_subclades'"
            ).fetchone()[0]
            analytics_mtdna_navigator = conn.execute(
                "SELECT COUNT(*) FROM usage_events WHERE event_type = 'analytics' AND command = 'mtdna_navigator'"
            ).fetchone()[0]
            analytics_mtdna_nav_group = conn.execute(
                "SELECT COUNT(*) FROM usage_events WHERE event_type = 'analytics' AND command = 'mtdna_nav_group'"
            ).fetchone()[0]
            analytics_mtdna_nav_subclade = conn.execute(
                "SELECT COUNT(*) FROM usage_events WHERE event_type = 'analytics' AND command = 'mtdna_nav_subclade'"
            ).fetchone()[0]
            analytics_mtdna_total = (
                analytics_mtdna_groups
                + analytics_mtdna_subclades
                + analytics_mtdna_navigator
                + analytics_mtdna_nav_group
                + analytics_mtdna_nav_subclade
            )
            analytics_nav_group = conn.execute(
                "SELECT COUNT(*) FROM usage_events WHERE event_type = 'analytics' AND command = 'nav_group'"
            ).fetchone()[0]
            analytics_nav_subclade = conn.execute(
                "SELECT COUNT(*) FROM usage_events WHERE event_type = 'analytics' AND command = 'nav_subclade'"
            ).fetchone()[0]
            analytics_subclade_group_select = conn.execute(
                """
                SELECT COUNT(*) FROM usage_events
                WHERE event_type = 'analytics' AND (
                    command LIKE 'subclade:%'
                    OR command LIKE 'subclade_group:%'
                )
                """
            ).fetchone()[0]
            analytics_subclade_groups = conn.execute(
                """
                SELECT command, COUNT(*) AS cnt
                FROM usage_events
                WHERE event_type = 'analytics' AND (
                    command LIKE 'subclade:%'
                    OR command LIKE 'subclade_group:%'
                )
                GROUP BY command
                ORDER BY cnt DESC, command COLLATE NOCASE ASC
                """
            ).fetchall()
            failure_breakdown = conn.execute(
                """
                SELECT
                    event_type,
                    COALESCE(NULLIF(command, ''), 'unknown') AS command_name,
                    COUNT(*) AS cnt
                FROM usage_events
                WHERE success = 0
                GROUP BY event_type, command_name
                ORDER BY cnt DESC, event_type COLLATE NOCASE ASC, command_name COLLATE NOCASE ASC
                LIMIT 12
                """
            ).fetchall()
            command_breakdown = conn.execute(
                """
                SELECT
                    event_type,
                    COALESCE(NULLIF(command, ''), 'unknown') AS command_name,
                    COUNT(*) AS cnt
                FROM usage_events
                GROUP BY event_type, command_name
                ORDER BY cnt DESC, event_type COLLATE NOCASE ASC, command_name COLLATE NOCASE ASC
                LIMIT 20
                """
            ).fetchall()
            top_users = conn.execute(
                """
                SELECT
                    COALESCE(NULLIF(username, ''), NULLIF(full_name, ''), CAST(user_id AS TEXT), 'unknown') AS user_label,
                    COUNT(*) AS cnt,
                    COUNT(DISTINCT date(created_at, 'localtime')) AS active_days
                FROM usage_events
                WHERE user_id IS NOT NULL OR username IS NOT NULL OR full_name IS NOT NULL
                GROUP BY user_label
                ORDER BY cnt DESC, active_days DESC, user_label COLLATE NOCASE ASC
                LIMIT 25
                """
            ).fetchall()
            recent_activity = conn.execute(
                f"""
                SELECT
                    COALESCE(NULLIF(username, ''), NULLIF(full_name, ''), CAST(user_id AS TEXT), 'unknown') AS user_label,
                    {summary_section_sql} AS section_key,
                    event_type,
                    COALESCE(NULLIF(command, ''), 'unknown') AS command_name,
                    COALESCE(NULLIF(query, ''), '') AS action_name,
                    strftime('%H:%M', created_at, 'localtime') AS time_label
                FROM usage_events
                WHERE success = 1
                ORDER BY datetime(created_at) DESC, id DESC
                LIMIT 25
                """
            ).fetchall()
            top_queries = conn.execute(
                """
                SELECT query, COUNT(*) AS cnt
                FROM usage_events
                WHERE event_type = 'lookup'
                  AND success = 1
                  AND query IS NOT NULL
                  AND TRIM(query) <> ''
                  AND (
                    username IS NULL
                    OR LOWER(LTRIM(username, '@')) NOT IN ('jb_cc')
                  )
                GROUP BY query
                ORDER BY cnt DESC, query COLLATE NOCASE ASC
                """
            ).fetchall()
            dna_lab_my_data_combined_unique_users = conn.execute(
                """
                SELECT COUNT(DISTINCT user_id)
                FROM usage_events
                WHERE user_id IS NOT NULL
                  AND event_type = 'dna_lab'
                  AND command = 'my_data'
                """
            ).fetchone()[0]
            failed_lookup_queries = conn.execute(
                """
                SELECT query, COUNT(*) AS cnt
                FROM usage_events
                WHERE event_type = 'lookup'
                  AND success = 0
                  AND query IS NOT NULL
                  AND TRIM(query) <> ''
                GROUP BY query
                ORDER BY cnt DESC, query COLLATE NOCASE ASC
                LIMIT 25
                """
            ).fetchall()

        dna_lab_section_summary: dict[str, dict[str, int]] = {}
        for row in dna_lab_section_stats:
            section = str(row[0] or "unknown")
            if section == "quick_g25":
                section = "my_data"
            if section in {"main", "reports", "settings"}:
                continue
            current = dna_lab_section_summary.setdefault(
                section,
                {"total": 0, "success": 0, "today": 0, "last_7_days": 0, "unique_users": 0},
            )
            current["total"] += int(row[1] or 0)
            current["success"] += int(row[2] or 0)
            current["today"] += int(row[3] or 0)
            current["last_7_days"] += int(row[4] or 0)
            current["unique_users"] += int(row[5] or 0)

        if "my_data" in dna_lab_section_summary:
            dna_lab_section_summary["my_data"]["unique_users"] = int(dna_lab_my_data_combined_unique_users)
        vahaduo_section = dna_lab_section_summary.setdefault(
            "vahaduo",
            {"total": 0, "success": 0, "today": 0, "last_7_days": 0, "unique_users": 0},
        )
        vahaduo_section["total"] += int(g25_menu_total)
        vahaduo_section["success"] += int(g25_menu_success)
        vahaduo_section["today"] += int(g25_menu_today)
        vahaduo_section["last_7_days"] += int(g25_menu_last_7_days)
        vahaduo_section["unique_users"] = int(dna_lab_vahaduo_combined_unique_users)
        dna_lab_section_rows = [
            (
                section,
                values["total"],
                values["last_7_days"],
                values["today"],
                values["unique_users"],
                values["success"],
            )
            for section, values in dna_lab_section_summary.items()
            if values["total"] > 0
        ]
        dna_lab_section_rows.sort(key=lambda item: (-item[1], item[0].casefold()))

        success_rate = round((success / total) * 100, 1) if total else 0.0
        lookup_success_rate = round((lookup_success / lookup_total) * 100, 1) if lookup_total else 0.0
        sozluk_success_rate = round((sozluk_success / sozluk_total) * 100, 1) if sozluk_total else 0.0
        ystr_success_rate = round((ystr_success / ystr_total) * 100, 1) if ystr_total else 0.0
        dna_lab_success_rate = round((dna_lab_success / dna_lab_total) * 100, 1) if dna_lab_total else 0.0
        g25_success_rate = round((g25_success / g25_total) * 100, 1) if g25_total else 0.0
        g25_menu_success_rate = round((g25_menu_success / g25_menu_total) * 100, 1) if g25_menu_total else 0.0
        analytics_with_ystr_success = ystr_success + analytics_total
        analytics_with_ystr_success_rate = (
            round((analytics_with_ystr_success / analytics_with_ystr_total) * 100, 1)
            if analytics_with_ystr_total
            else 0.0
        )
        return {
            "total": total,
            "success": success,
            "success_rate": success_rate,
            "unique_users": unique_users,
            "unique_users_last_7_days": unique_users_last_7_days,
            "today": today,
            "last_7_days": last_7_days,
            "last_30_days": last_30_days,
            "private_events": private_events,
            "group_events": group_events,
            "summary_section_rows": [
                (row[0], row[1], row[4], row[3], row[5], row[2])
                for row in summary_section_stats
            ],
            "lookup_total": lookup_total,
            "lookup_success": lookup_success,
            "lookup_success_rate": lookup_success_rate,
            "lookup_today": lookup_today,
            "lookup_last_7_days": lookup_last_7_days,
            "lookup_unique_users": lookup_unique_users,
            "lookup_failed": lookup_total - lookup_success,
            "lookup_failed_queries": self._merge_top_queries([(row[0], row[1]) for row in failed_lookup_queries]),
            "sozluk_total": sozluk_total,
            "sozluk_success": sozluk_success,
            "sozluk_success_rate": sozluk_success_rate,
            "sozluk_today": sozluk_today,
            "sozluk_last_7_days": sozluk_last_7_days,
            "sozluk_unique_users": sozluk_unique_users,
            "sozluk_top_queries": self._merge_top_queries([(row[0], row[1]) for row in sozluk_top_queries]),
            "ystr_total": ystr_total,
            "ystr_success": ystr_success,
            "ystr_success_rate": ystr_success_rate,
            "ystr_today": ystr_today,
            "ystr_last_7_days": ystr_last_7_days,
            "ystr_unique_users": ystr_unique_users,
            "ystr_nearest": ystr_nearest,
            "ystr_testdata": ystr_testdata,
            "ystr_compare": ystr_compare,
            "ystr_upload": ystr_upload,
            "dna_lab_total": dna_lab_total,
            "dna_lab_success": dna_lab_success,
            "dna_lab_success_rate": dna_lab_success_rate,
            "dna_lab_today": dna_lab_today,
            "dna_lab_last_7_days": dna_lab_last_7_days,
            "dna_lab_unique_users": dna_lab_unique_users,
            "dna_lab_sections": [(row[0], row[1]) for row in dna_lab_sections],
            "dna_lab_section_rows": dna_lab_section_rows,
            "dna_lab_top_actions": [(row[0], row[1], row[2]) for row in dna_lab_top_actions],
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
            "g25_distance_total": g25_distance_total,
            "g25_distance_modern": g25_distance_modern,
            "g25_distance_ancestry": g25_distance_ancestry,
            "g25_raw": g25_raw,
            "g25_text": g25_text,
            "g25_menu_total": g25_menu_total,
            "g25_menu_success": g25_menu_success,
            "g25_menu_success_rate": g25_menu_success_rate,
            "g25_menu_today": g25_menu_today,
            "g25_menu_last_7_days": g25_menu_last_7_days,
            "g25_menu_unique_users": g25_menu_unique_users,
            "g25_menu_raw": g25_menu_raw,
            "g25_menu_text": g25_menu_text,
            "g25_quick_panel": g25_quick_panel,
            "g25_vahaduo_total": g25_vahaduo_total,
            "g25_vahaduo_distance": g25_vahaduo_distance,
            "g25_vahaduo_single": g25_vahaduo_single,
            "g25_vahaduo_multi": g25_vahaduo_multi,
            "analytics_total": analytics_total,
            "analytics_today": analytics_today,
            "analytics_last_7_days": analytics_last_7_days,
            "analytics_unique_users": analytics_unique_users,
            "analytics_with_ystr_total": analytics_with_ystr_total,
            "analytics_with_ystr_today": analytics_with_ystr_today,
            "analytics_with_ystr_last_7_days": analytics_with_ystr_last_7_days,
            "analytics_with_ystr_unique_users": analytics_with_ystr_unique_users,
            "analytics_with_ystr_success": analytics_with_ystr_success,
            "analytics_with_ystr_success_rate": analytics_with_ystr_success_rate,
            "analytics_root": analytics_root,
            "analytics_diagrams": analytics_diagrams,
            "analytics_navigator": analytics_navigator,
            "analytics_haplo_families": analytics_haplo_families,
            "analytics_haplo_tests": analytics_haplo_tests,
            "analytics_mtdna_total": analytics_mtdna_total,
            "analytics_mtdna_groups": analytics_mtdna_groups,
            "analytics_mtdna_subclades": analytics_mtdna_subclades,
            "analytics_mtdna_navigator": analytics_mtdna_navigator,
            "analytics_mtdna_nav_group": analytics_mtdna_nav_group,
            "analytics_mtdna_nav_subclade": analytics_mtdna_nav_subclade,
            "analytics_nav_group": analytics_nav_group,
            "analytics_nav_subclade": analytics_nav_subclade,
            "analytics_subclade_group_select": analytics_subclade_group_select,
            "analytics_subclade_groups": [(row[0], row[1]) for row in analytics_subclade_groups],
            "failure_breakdown": [(row[0], row[1], row[2]) for row in failure_breakdown],
            "command_breakdown": [(row[0], row[1], row[2]) for row in command_breakdown],
            "top_users": [(row[0], row[1], row[2]) for row in top_users],
            "recent_activity": [(row[0], row[1], row[2], row[3], row[4], row[5]) for row in recent_activity],
            "top_queries": self._merge_top_queries([(row[0], row[1]) for row in top_queries]),
        }
    @classmethod
    def _format_lookup_query_label(cls, query: str) -> str:
        cleaned = " ".join(str(query or "").split())
        if not cleaned:
            return ""
        return cleaned[:1].upper() + cleaned[1:].lower()

    @classmethod
    def _merge_top_queries(cls, rows: list[tuple[str, int]]) -> list[tuple[str, int]]:
        merged: dict[str, dict[str, object]] = {}
        for query, count in rows:
            label = cls._format_lookup_query_label(str(query or ""))
            if not label:
                continue
            key = label.casefold()
            item = merged.setdefault(key, {"label": label, "count": 0})
            item["count"] = int(item["count"]) + int(count)

        ordered = sorted(
            ((str(item["label"]), int(item["count"])) for item in merged.values()),
            key=lambda item: (-item[1], item[0].casefold()),
        )
        return ordered[:25]

    def get_last_7_days_series(self, stats_key: str, days: int = 7) -> list[tuple[str, int]]:
        days = max(1, int(days))
        days_back = days - 1
        window_modifier = f"-{days_back} days"
        with self._connect() as conn:
            self._prepare_stats_connection(conn)
            if stats_key == "all":
                rows = conn.execute(
                    f"""
                    SELECT date(created_at, 'localtime') AS day, COUNT(*) AS cnt
                    FROM usage_events
                    WHERE date(created_at, 'localtime') >= date('now', '{window_modifier}', 'localtime')
                    GROUP BY day
                    ORDER BY day
                    """
                ).fetchall()
            elif stats_key == "lookup":
                rows = conn.execute(
                    f"""
                    SELECT date(created_at, 'localtime') AS day, COUNT(*) AS cnt
                    FROM usage_events
                    WHERE event_type = 'lookup'
                      AND date(created_at, 'localtime') >= date('now', '{window_modifier}', 'localtime')
                    GROUP BY day
                    ORDER BY day
                    """
                ).fetchall()
            elif stats_key == "sozluk":
                rows = conn.execute(
                    f"""
                    SELECT date(created_at, 'localtime') AS day, COUNT(*) AS cnt
                    FROM usage_events
                    WHERE event_type = 'sozluk'
                      AND date(created_at, 'localtime') >= date('now', '{window_modifier}', 'localtime')
                    GROUP BY day
                    ORDER BY day
                    """
                ).fetchall()
            elif stats_key == "ystr":
                rows = conn.execute(
                    f"""
                    SELECT date(created_at, 'localtime') AS day, COUNT(*) AS cnt
                    FROM usage_events
                    WHERE event_type = 'ystr'
                      AND date(created_at, 'localtime') >= date('now', '{window_modifier}', 'localtime')
                    GROUP BY day
                    ORDER BY day
                    """
                ).fetchall()
            elif stats_key == "analytics":
                rows = conn.execute(
                    f"""
                    SELECT date(created_at, 'localtime') AS day, COUNT(*) AS cnt
                    FROM usage_events
                    WHERE date(created_at, 'localtime') >= date('now', '{window_modifier}', 'localtime')
                      AND (
                        event_type = 'ystr'
                        OR (
                          event_type = 'analytics'
                          AND (
                            command = 'navigator'
                            OR command = 'haplo_families'
                            OR command = 'haplo_tests'
                            OR command = 'mtdna_groups'
                            OR command = 'mtdna_subclades'
                            OR command = 'mtdna_navigator'
                            OR command = 'mtdna_nav_group'
                            OR command = 'mtdna_nav_subclade'
                            OR command = 'nav_group'
                            OR command = 'nav_subclade'
                            OR command LIKE 'subclade:%'
                            OR command LIKE 'subclade_group:%'
                          )
                        )
                      )
                    GROUP BY day
                    ORDER BY day
                    """
                ).fetchall()
            elif stats_key == "dna_lab":
                rows = conn.execute(
                    f"""
                    SELECT date(created_at, 'localtime') AS day, COUNT(*) AS cnt
                    FROM usage_events
                    WHERE event_type = 'dna_lab'
                      AND date(created_at, 'localtime') >= date('now', '{window_modifier}', 'localtime')
                    GROUP BY day
                    ORDER BY day
                    """
                ).fetchall()
            elif stats_key == "g25_menu":
                placeholders = ", ".join("?" for _ in VISIBLE_G25_STATS_COMMANDS)
                rows = conn.execute(
                    f"""
                    SELECT date(created_at, 'localtime') AS day, COUNT(*) AS cnt
                    FROM usage_events
                    WHERE event_type = 'g25'
                      AND date(created_at, 'localtime') >= date('now', '{window_modifier}', 'localtime')
                      AND command IN ({placeholders})
                    GROUP BY day
                    ORDER BY day
                    """,
                    VISIBLE_G25_STATS_COMMANDS,
                ).fetchall()
            else:
                raise ValueError(f"Unknown stats series: {stats_key}")

        counts_by_day = {str(row[0]): int(row[1]) for row in rows if row[0]}
        today = datetime.now().date()
        series: list[tuple[str, int]] = []
        for days_ago in range(days_back, -1, -1):
            day = today - timedelta(days=days_ago)
            series.append((day.strftime("%d.%m"), counts_by_day.get(day.isoformat(), 0)))
        return series
