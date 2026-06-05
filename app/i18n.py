from __future__ import annotations

from typing import Any

from telegram.ext import ContextTypes


DEFAULT_LANGUAGE = "ru"
SUPPORTED_LANGUAGES = ("ru", "en")
LANGUAGE_NAMES = {
    "ru": "Русский",
    "en": "English",
}


_TEXTS: dict[str, dict[str, str]] = {
    "main.choose_section": {
        "ru": "Выберите раздел:",
        "en": "Choose a section:",
    },
    "main.start_hint": {
        "ru": (
            "DNA Lab помогает работать с raw/G25 данными: хранить sample, получать G25, "
            "строить Vahaduo, Coordinate Space, Admixture, Matching и Traits отчеты.\n\n"
            "Проект пока в beta, поэтому некоторые разделы еще будут дорабатываться.\n\n"
            "Нажмите Menu внизу или /menu, чтобы открыть главное меню."
        ),
        "en": (
            "DNA Lab helps you work with raw/G25 data: store samples, extract G25, "
            "and build Vahaduo, Coordinate Space, Admixture, Matching, and Traits reports.\n\n"
            "The project is still in beta, so some sections will keep improving.\n\n"
            "Tap Menu below or /menu to open the main menu."
        ),
    },
    "main.menu_stale_start": {
        "ru": "Меню устарело. Откройте /menu или /start.",
        "en": "This menu is outdated. Open /menu or /start.",
    },
    "main.menu_stale": {
        "ru": "Меню устарело. Откройте /menu.",
        "en": "This menu is outdated. Open /menu.",
    },
    "main.closed": {
        "ru": "Меню закрыто.",
        "en": "Menu closed.",
    },
    "main.my_dna": {
        "ru": "📁 My DNA",
        "en": "📁 My DNA",
    },
    "main.coordinate_spaces": {
        "ru": "🧭 Coordinate spaces",
        "en": "🧭 Coordinate spaces",
    },
    "main.vahaduo": {
        "ru": "📐 Vahaduo Lab",
        "en": "📐 Vahaduo Lab",
    },
    "main.admixture": {
        "ru": "🧬 Admixture",
        "en": "🧬 Admixture",
    },
    "main.modeling": {
        "ru": "🏛 AdmixLab",
        "en": "🏛 AdmixLab",
    },
    "main.matching": {
        "ru": "🧩 Matching",
        "en": "🧩 Matching",
    },
    "main.traits": {
        "ru": "✨ Traits",
        "en": "✨ Traits",
    },
    "main.haplogroups": {
        "ru": "🌿 Haplogroups",
        "en": "🌿 Haplogroups",
    },
    "main.reports": {
        "ru": "📊 Reports",
        "en": "📊 Reports",
    },
    "main.settings": {
        "ru": "⚙️ Настройки",
        "en": "⚙️ Settings",
    },
    "main.help": {
        "ru": "📖 Справка",
        "en": "📖 Help",
    },
    "main.cancel": {
        "ru": "✖️ Отмена",
        "en": "✖️ Cancel",
    },
    "nav.back": {
        "ru": "Назад",
        "en": "Back",
    },
    "nav.cancel": {
        "ru": "Отмена",
        "en": "Cancel",
    },
    "nav.main_menu": {
        "ru": "Главное меню",
        "en": "Main menu",
    },
}


def normalize_language(value: str | None) -> str:
    lang = (value or "").strip().lower().split("-", 1)[0]
    if lang in SUPPORTED_LANGUAGES:
        return lang
    return DEFAULT_LANGUAGE


def get_user_language(
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int | None = None,
    *,
    fallback: str | None = None,
) -> str:
    if user_id is not None:
        store = context.application.bot_data.get("user_settings_store")
        if store is not None and hasattr(store, "get_language"):
            return normalize_language(store.get_language(user_id))
    return normalize_language(fallback)


def language_name(lang: str) -> str:
    return LANGUAGE_NAMES.get(normalize_language(lang), LANGUAGE_NAMES[DEFAULT_LANGUAGE])


def t(key: str, lang: str | None = None, **kwargs: Any) -> str:
    normalized = normalize_language(lang)
    value = _TEXTS.get(key, {}).get(normalized)
    if value is None:
        value = _TEXTS.get(key, {}).get(DEFAULT_LANGUAGE, key)
    return value.format(**kwargs) if kwargs else value
