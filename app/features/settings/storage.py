from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from app.i18n import DEFAULT_LANGUAGE, normalize_language
from app.storage_io import write_json_atomic


CARD_FORMAT_WIDE = "wide"
CARD_FORMAT_MOBILE = "mobile"
SUPPORTED_CARD_FORMATS = (CARD_FORMAT_WIDE, CARD_FORMAT_MOBILE)
RESULT_MODE_SIMPLE = "simple"
RESULT_MODE_ADVANCED = "advanced"
SUPPORTED_RESULT_MODES = (RESULT_MODE_SIMPLE, RESULT_MODE_ADVANCED)
SEARCH_BASE_KBDNA = "kbdna"
SEARCH_BASE_ADYGHE = "adyghe"
SEARCH_BASE_ABKHAZ = "abkhaz"
SEARCH_BASE_ABAZA = "abaza"
SEARCH_BASES = (
    SEARCH_BASE_KBDNA,
    SEARCH_BASE_ADYGHE,
    SEARCH_BASE_ABKHAZ,
    SEARCH_BASE_ABAZA,
)
THEME_DARK = "dark"
THEME_LIGHT = "light"
SUPPORTED_THEMES = (THEME_DARK, THEME_LIGHT)


def normalize_card_format(card_format: str | None) -> str:
    value = str(card_format or "").strip().lower()
    if value in SUPPORTED_CARD_FORMATS:
        return value
    return CARD_FORMAT_WIDE


def normalize_result_mode(result_mode: str | None) -> str:
    value = str(result_mode or "").strip().lower()
    if value in SUPPORTED_RESULT_MODES:
        return value
    return RESULT_MODE_SIMPLE


def normalize_search_base(search_base: str | None) -> str:
    value = str(search_base or "").strip().lower()
    if value in SEARCH_BASES:
        return value
    return SEARCH_BASE_KBDNA


def normalize_theme(theme: str | None) -> str:
    value = str(theme or "").strip().lower()
    if value in SUPPORTED_THEMES:
        return value
    return THEME_DARK


def normalize_notifications_enabled(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"false", "0", "off", "no", "нет", "выключены"}:
            return False
        if normalized in {"true", "1", "on", "yes", "да", "включены"}:
            return True
    return True


@dataclass(frozen=True)
class UserSettings:
    language: str = DEFAULT_LANGUAGE
    card_format: str = CARD_FORMAT_WIDE
    result_mode: str = RESULT_MODE_SIMPLE
    search_base: str = SEARCH_BASE_KBDNA
    notifications_enabled: bool = True
    theme: str = THEME_DARK


class UserSettingsStore:
    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def get(self, user_id: int) -> UserSettings:
        path = self._path(user_id)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return UserSettings()
        if not isinstance(payload, dict):
            return UserSettings()
        return UserSettings(
            language=normalize_language(str(payload.get("language") or DEFAULT_LANGUAGE)),
            card_format=normalize_card_format(payload.get("card_format")),
            result_mode=normalize_result_mode(payload.get("result_mode")),
            search_base=normalize_search_base(payload.get("search_base")),
            notifications_enabled=normalize_notifications_enabled(payload.get("notifications_enabled", True)),
            theme=normalize_theme(payload.get("theme")),
        )

    def get_language(self, user_id: int) -> str:
        return self.get(user_id).language

    def get_card_format(self, user_id: int) -> str:
        return self.get(user_id).card_format

    def get_result_mode(self, user_id: int) -> str:
        return self.get(user_id).result_mode

    def get_search_base(self, user_id: int) -> str:
        return self.get(user_id).search_base

    def get_notifications_enabled(self, user_id: int) -> bool:
        return self.get(user_id).notifications_enabled

    def get_theme(self, user_id: int) -> str:
        return self.get(user_id).theme

    def set_language(self, user_id: int, language: str) -> UserSettings:
        current = self.get(user_id)
        settings = UserSettings(
            language=normalize_language(language),
            card_format=current.card_format,
            result_mode=current.result_mode,
            search_base=current.search_base,
            notifications_enabled=current.notifications_enabled,
            theme=current.theme,
        )
        self._write(user_id, settings)
        return settings

    def set_card_format(self, user_id: int, card_format: str) -> UserSettings:
        current = self.get(user_id)
        settings = UserSettings(
            language=current.language,
            card_format=normalize_card_format(card_format),
            result_mode=current.result_mode,
            search_base=current.search_base,
            notifications_enabled=current.notifications_enabled,
            theme=current.theme,
        )
        self._write(user_id, settings)
        return settings

    def set_result_mode(self, user_id: int, result_mode: str) -> UserSettings:
        current = self.get(user_id)
        settings = UserSettings(
            language=current.language,
            card_format=current.card_format,
            result_mode=normalize_result_mode(result_mode),
            search_base=current.search_base,
            notifications_enabled=current.notifications_enabled,
            theme=current.theme,
        )
        self._write(user_id, settings)
        return settings

    def set_search_base(self, user_id: int, search_base: str) -> UserSettings:
        current = self.get(user_id)
        settings = UserSettings(
            language=current.language,
            card_format=current.card_format,
            result_mode=current.result_mode,
            search_base=normalize_search_base(search_base),
            notifications_enabled=current.notifications_enabled,
            theme=current.theme,
        )
        self._write(user_id, settings)
        return settings

    def set_notifications_enabled(self, user_id: int, enabled: bool) -> UserSettings:
        current = self.get(user_id)
        settings = UserSettings(
            language=current.language,
            card_format=current.card_format,
            result_mode=current.result_mode,
            search_base=current.search_base,
            notifications_enabled=bool(enabled),
            theme=current.theme,
        )
        self._write(user_id, settings)
        return settings

    def set_theme(self, user_id: int, theme: str) -> UserSettings:
        current = self.get(user_id)
        settings = UserSettings(
            language=current.language,
            card_format=current.card_format,
            result_mode=current.result_mode,
            search_base=current.search_base,
            notifications_enabled=current.notifications_enabled,
            theme=normalize_theme(theme),
        )
        self._write(user_id, settings)
        return settings

    def _path(self, user_id: int) -> Path:
        return self.root_dir / f"{int(user_id)}.json"

    def _write(self, user_id: int, settings: UserSettings) -> None:
        write_json_atomic(
            self._path(user_id),
            {
                "language": settings.language,
                "card_format": settings.card_format,
                "result_mode": settings.result_mode,
                "search_base": settings.search_base,
                "notifications_enabled": settings.notifications_enabled,
                "theme": settings.theme,
            },
        )
