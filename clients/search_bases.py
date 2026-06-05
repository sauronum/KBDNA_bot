from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from app.features.settings.storage import (
    SEARCH_BASE_ABAZA,
    SEARCH_BASE_ABKHAZ,
    SEARCH_BASE_ADYGHE,
    SEARCH_BASE_KBDNA,
    normalize_search_base,
)
from clients.sheets import SheetsClient

logger = logging.getLogger(__name__)

_PNG_SCOPE_TITLES = {
    SEARCH_BASE_KBDNA: "KARACHAY-BALKARS",
    SEARCH_BASE_ADYGHE: "ADYGHE",
    SEARCH_BASE_ABKHAZ: "ABKHAZ",
    SEARCH_BASE_ABAZA: "ABAZA",
}

_CAPTION_LABELS = {
    SEARCH_BASE_KBDNA: "KBDNA",
    SEARCH_BASE_ADYGHE: "Адыгская база",
    SEARCH_BASE_ABKHAZ: "Абхазская база",
    SEARCH_BASE_ABAZA: "Абазинская база",
}


def search_base_for_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    if update.effective_user is None:
        return SEARCH_BASE_KBDNA
    store = context.application.bot_data.get("user_settings_store")
    if store is None or not hasattr(store, "get_search_base"):
        return SEARCH_BASE_KBDNA
    try:
        return normalize_search_base(store.get_search_base(int(update.effective_user.id)))
    except Exception:
        return SEARCH_BASE_KBDNA


def sheets_client_for_search_base(context: ContextTypes.DEFAULT_TYPE, search_base: str) -> SheetsClient:
    normalized = normalize_search_base(search_base)
    sheets_by_search_base = context.application.bot_data.get("sheets_by_search_base")
    if isinstance(sheets_by_search_base, dict):
        candidate = sheets_by_search_base.get(normalized)
        if isinstance(candidate, SheetsClient):
            return candidate
        if normalized != SEARCH_BASE_KBDNA:
            logger.warning("Search base %s is selected, but no SheetsClient is configured; falling back to KBDNA", normalized)
    return context.application.bot_data["sheets"]


def sheets_client_for_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> SheetsClient:
    return sheets_client_for_search_base(context, search_base_for_update(update, context))


def search_base_png_scope_title(search_base: str) -> str:
    return _PNG_SCOPE_TITLES.get(normalize_search_base(search_base), "KBDNA")


def search_base_caption_label(search_base: str) -> str:
    return _CAPTION_LABELS.get(normalize_search_base(search_base), "KBDNA")
