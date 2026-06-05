from __future__ import annotations

import html
import json
import logging
import re
import sqlite3
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional


DEFAULT_SOZLUK_API_BASE = "https://elbrusoid.org/dictionary"
logger = logging.getLogger(__name__)


class SozlukClient:
    DIRECTIONS = {
        1: "Русский → карачаево-балкарский",
        2: "Карачаево-балкарский → русский",
    }

    def __init__(self, db_path: Path, api_base: str = DEFAULT_SOZLUK_API_BASE) -> None:
        self.db_path = db_path
        self.api_base = api_base.rstrip("/")
        self._init_db()

    @staticmethod
    def normalize_query(value: str) -> str:
        return " ".join(str(value or "").strip().lower().replace("\u00a0", " ").split())

    @staticmethod
    def plain_text_from_html(value: str) -> str:
        text = str(value or "")
        text = re.sub(r"(?i)<\s*br\s*/?\s*>", "\n", text)
        text = re.sub(r"(?i)</\s*(p|div|li)\s*>", "\n", text)
        text = re.sub(r"<[^>]+>", "", text)
        text = html.unescape(text)
        text = text.replace("\u00ad", "")
        text = text.replace("\u00a0", " ")
        text = re.sub(r"[ \t\r\f\v]+", " ", text)
        text = re.sub(r"\n\s+", "\n", text)
        return "\n".join(line.strip() for line in text.splitlines() if line.strip()).strip()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sozluk_cache (
                    query TEXT NOT NULL,
                    direction INTEGER NOT NULL,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (query, direction)
                )
                """
            )

    def _get_cached(self, query: str, direction: int) -> Optional[list[dict[str, object]]]:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT payload FROM sozluk_cache WHERE query = ? AND direction = ?",
                (query, direction),
            ).fetchone()
        if row is None:
            return None
        try:
            payload = json.loads(row[0])
        except (TypeError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, list) else None

    def _store_cached(self, query: str, direction: int, payload: list[dict[str, object]]) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO sozluk_cache (query, direction, payload, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(query, direction) DO UPDATE SET
                    payload = excluded.payload,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (query, direction, json.dumps(payload, ensure_ascii=False)),
            )

    def _fetch(self, query: str, direction: int) -> list[dict[str, object]]:
        url = (
            f"{self.api_base}/get_word.php?"
            f"q={urllib.parse.quote(query)}&direction={int(direction)}"
        )
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "KBDNA-bot/1.0 (sozluk lookup)"},
        )
        with urllib.request.urlopen(request, timeout=12) as response:
            raw = response.read().decode("utf-8", errors="replace")
        data = json.loads(raw)
        if not isinstance(data, list):
            return []

        items: list[dict[str, object]] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            word = " ".join(str(item.get("word") or "").split())
            desc = self.plain_text_from_html(str(item.get("desc") or ""))
            if not word or not desc:
                continue
            try:
                item_direction = int(item.get("direction") or direction)
            except (TypeError, ValueError):
                item_direction = direction
            items.append(
                {
                    "id": str(item.get("id") or ""),
                    "word": word,
                    "desc": desc,
                    "direction": item_direction,
                }
            )
        return items

    def lookup(self, query: str, direction: int, *, use_cache: bool = True) -> list[dict[str, object]]:
        normalized = self.normalize_query(query)
        if len(normalized) < 2 or direction not in self.DIRECTIONS:
            return []
        if use_cache:
            cached = self._get_cached(normalized, direction)
            if cached is not None:
                return cached
        try:
            payload = self._fetch(normalized, direction)
        except Exception:
            logger.exception("Sozluk lookup failed: direction=%s query=%r", direction, normalized)
            if use_cache:
                cached = self._get_cached(normalized, direction)
                if cached is not None:
                    return cached
            raise
        self._store_cached(normalized, direction, payload)
        return payload

    def lookup_all(self, query: str) -> list[dict[str, object]]:
        combined: list[dict[str, object]] = []
        for direction in (1, 2):
            combined.extend(self.lookup(query, direction))
        return combined


def filter_exact_sozluk_items(query: str, items: list[dict[str, object]]) -> list[dict[str, object]]:
    normalized_query = SozlukClient.normalize_query(query)
    return [
        item
        for item in items
        if SozlukClient.normalize_query(str(item.get("word") or "")) == normalized_query
    ]
