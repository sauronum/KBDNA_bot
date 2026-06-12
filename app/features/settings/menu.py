from __future__ import annotations

import json
import logging
import shutil
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputFile, Update
from telegram.ext import Application, ContextTypes

from app.features.coordinate_space.reports import CoordinateSpaceReportStore
from app.i18n import LANGUAGE_NAMES, SUPPORTED_LANGUAGES, get_user_language, language_name, t
from app.main_menu import ensure_active_main_menu, set_active_main_menu_message
from app.features.my_data.handlers import (
    PRIVACY_G25_BACK_KEY,
    PRIVACY_REPORTS_BACK_KEY,
    PRIVACY_ROOT_BACK_KEY,
    PRIVACY_SAMPLES_BACK_KEY,
    show_sample_reports_menu,
    show_view_coordinates_menu,
    show_view_samples_menu,
)
from app.features.reports.menu import show_reports_menu

from .storage import (
    CARD_FORMAT_MOBILE,
    CARD_FORMAT_WIDE,
    RESULT_MODE_ADVANCED,
    RESULT_MODE_SIMPLE,
    SEARCH_BASE_ABAZA,
    SEARCH_BASE_ABKHAZ,
    SEARCH_BASE_ADYGHE,
    SEARCH_BASE_KBDNA,
    SEARCH_BASES,
    SUPPORTED_CARD_FORMATS,
    SUPPORTED_RESULT_MODES,
    UserSettingsStore,
    normalize_card_format,
    normalize_result_mode,
    normalize_search_base,
)


SETTINGS_CALLBACK_PREFIX = "settings"
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PrivacyDataSummary:
    samples: int = 0
    raw_files: int = 0
    g25_profiles: int = 0
    saved_reports: int = 0


def _safe_count(callback) -> int:
    try:
        return len(callback())
    except Exception:
        return 0


def register_settings_services(application: Application, settings) -> None:
    application.bot_data["user_settings_store"] = UserSettingsStore(settings.root_dir / "storage" / "user_settings")


def _settings_store(context: ContextTypes.DEFAULT_TYPE) -> UserSettingsStore:
    store = context.application.bot_data.get("user_settings_store")
    if isinstance(store, UserSettingsStore):
        return store
    store = UserSettingsStore(context.application.bot_data["my_data_store"].root_dir.parent / "user_settings")
    context.application.bot_data["user_settings_store"] = store
    return store


def _storage_base_dir(context: ContextTypes.DEFAULT_TYPE) -> Path:
    my_data_store = context.application.bot_data.get("my_data_store")
    root_dir = getattr(my_data_store, "root_dir", None)
    if root_dir is not None:
        return Path(root_dir).parent
    return _settings_store(context).root_dir.parent


def _store_user_dir(store, user_id: int) -> Path | None:
    root_dir = getattr(store, "root_dir", None)
    if root_dir is None:
        return None
    return Path(root_dir) / "users" / str(int(user_id))


def _settings_path(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> Path | None:
    try:
        return _settings_store(context).root_dir / f"{int(user_id)}.json"
    except Exception:
        return None


def _existing_user_data_paths(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> list[tuple[str, Path]]:
    bot_data = context.application.bot_data
    paths: list[tuple[str, Path]] = []
    store_labels = [
        ("my_data", "my_data_store"),
        ("coordinate_space_reports", "coordinate_space_report_store"),
        ("admixture_reports", "admixture_report_store"),
        ("matching_reports", "matching_store"),
        ("trait_reports", "traits_report_store"),
        ("haplogroup_reports", "haplogroup_store"),
    ]
    for label, key in store_labels:
        path = _store_user_dir(bot_data.get(key), user_id)
        if path is not None and path.exists():
            paths.append((label, path))

    settings_path = _settings_path(context, user_id)
    if settings_path is not None and settings_path.exists():
        paths.append(("settings", settings_path))
    return paths


def _iter_vahaduo_user_files(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> list[tuple[str, Path]]:
    items: list[tuple[str, Path]] = []
    for key, path_field, label in [
        ("dna_lab_vahaduo_saved_store", "source_path", "vahaduo_sources"),
        ("dna_lab_vahaduo_target_store", "target_path", "vahaduo_targets"),
    ]:
        store = context.application.bot_data.get(key)
        if store is None or not hasattr(store, "list_for_user"):
            continue
        try:
            records = store.list_for_user(user_id)
        except TypeError:
            try:
                records = store.list_for_user(user_id, None)
            except Exception:
                records = []
        except Exception:
            records = []
        for record in records:
            path = Path(str(record.get(path_field) or ""))
            if path.exists():
                items.append((label, path))
    return items


def _delete_vahaduo_user_data(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> None:
    for key in ["dna_lab_vahaduo_saved_store", "dna_lab_vahaduo_target_store"]:
        store = context.application.bot_data.get(key)
        if store is None or not hasattr(store, "list_for_user") or not hasattr(store, "delete_for_user"):
            continue
        try:
            records = store.list_for_user(user_id)
        except TypeError:
            try:
                records = store.list_for_user(user_id, None)
            except Exception:
                records = []
        except Exception:
            records = []
        for record in records:
            try:
                store.delete_for_user(user_id, int(record.get("id")))
            except Exception:
                continue


def export_user_data_archive(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> Path:
    summary = privacy_data_summary(context, user_id)
    export_dir = _storage_base_dir(context) / "_exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    archive_path = export_dir / f"kbdna_user_{int(user_id)}_{timestamp}.zip"
    manifest = {
        "user_id": int(user_id),
        "generated_at_utc": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "summary": {
            "samples": summary.samples,
            "raw_files": summary.raw_files,
            "g25_profiles": summary.g25_profiles,
            "saved_reports": summary.saved_reports,
        },
    }

    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        for label, path in _existing_user_data_paths(context, user_id):
            if path.is_file():
                archive.write(path, f"{label}/{path.name}")
                continue
            for item in sorted(path.rglob("*")):
                if item.is_file():
                    archive.write(item, f"{label}/{item.relative_to(path).as_posix()}")
        for label, path in _iter_vahaduo_user_files(context, user_id):
            archive.write(path, f"{label}/{path.name}")
    return archive_path


def delete_user_data(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> PrivacyDataSummary:
    summary = privacy_data_summary(context, user_id)
    for _label, path in _existing_user_data_paths(context, user_id):
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        else:
            try:
                path.unlink()
            except FileNotFoundError:
                pass
    _delete_vahaduo_user_data(context, user_id)
    for key in [
        PRIVACY_ROOT_BACK_KEY,
        PRIVACY_SAMPLES_BACK_KEY,
        PRIVACY_G25_BACK_KEY,
        PRIVACY_REPORTS_BACK_KEY,
        "reports_back_callback",
        "reports_my_dna_callback",
        "reports_sample_callback_template",
    ]:
        context.user_data.pop(key, None)
    return summary


def set_user_language(context: ContextTypes.DEFAULT_TYPE, user_id: int, language: str) -> bool:
    if language not in SUPPORTED_LANGUAGES:
        return False
    _settings_store(context).set_language(user_id, language)
    return True


def get_user_card_format(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> str:
    return _settings_store(context).get_card_format(user_id)


def set_user_card_format(context: ContextTypes.DEFAULT_TYPE, user_id: int, card_format: str) -> bool:
    if card_format not in SUPPORTED_CARD_FORMATS:
        return False
    _settings_store(context).set_card_format(user_id, card_format)
    return True


def get_user_result_mode(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> str:
    return _settings_store(context).get_result_mode(user_id)


def set_user_result_mode(context: ContextTypes.DEFAULT_TYPE, user_id: int, result_mode: str) -> bool:
    if result_mode not in SUPPORTED_RESULT_MODES:
        return False
    _settings_store(context).set_result_mode(user_id, result_mode)
    return True


def get_user_search_base(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> str:
    return _settings_store(context).get_search_base(user_id)


def set_user_search_base(context: ContextTypes.DEFAULT_TYPE, user_id: int, search_base: str) -> bool:
    if search_base not in SEARCH_BASES:
        return False
    _settings_store(context).set_search_base(user_id, search_base)
    return True


def get_user_notifications_enabled(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> bool:
    return _settings_store(context).get_notifications_enabled(user_id)


def set_user_notifications_enabled(context: ContextTypes.DEFAULT_TYPE, user_id: int, enabled: bool) -> bool:
    _settings_store(context).set_notifications_enabled(user_id, enabled)
    return True


def card_format_label(card_format: str, lang: str) -> str:
    normalized = normalize_card_format(card_format)
    if lang == "en":
        labels = {
            CARD_FORMAT_WIDE: "🖥 Wide",
            CARD_FORMAT_MOBILE: "📱 Mobile",
        }
    else:
        labels = {
            CARD_FORMAT_WIDE: "🖥 Широкий",
            CARD_FORMAT_MOBILE: "📱 Мобильный",
        }
    return labels[normalized]


def result_mode_label(result_mode: str, lang: str) -> str:
    normalized = normalize_result_mode(result_mode)
    if lang == "en":
        labels = {
            RESULT_MODE_SIMPLE: "✨ Simple",
            RESULT_MODE_ADVANCED: "🧪 Advanced",
        }
    else:
        labels = {
            RESULT_MODE_SIMPLE: "✨ Обычный",
            RESULT_MODE_ADVANCED: "🧪 Расширенный",
        }
    return labels[normalized]


def search_base_label(search_base: str, lang: str) -> str:
    normalized = normalize_search_base(search_base)
    labels = {
        SEARCH_BASE_KBDNA: "KBDNA",
        SEARCH_BASE_ADYGHE: "Адыгская",
        SEARCH_BASE_ABKHAZ: "Абхазская",
        SEARCH_BASE_ABAZA: "Абазинская",
    }
    if lang == "en" and normalized == SEARCH_BASE_KBDNA:
        return "KBDNA"
    return labels[normalized]


def notifications_status_label(enabled: bool, lang: str) -> str:
    if lang == "en":
        return "enabled" if enabled else "disabled"
    return "включены" if enabled else "выключены"


def privacy_data_summary(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> PrivacyDataSummary:
    store = context.application.bot_data.get("my_data_store")
    if store is None:
        return PrivacyDataSummary()

    samples = []
    try:
        samples = list(store.list_samples(user_id))
    except Exception:
        samples = []

    raw_files = _safe_count(lambda: store.list_raw_files(user_id))
    g25_profiles = _safe_count(lambda: store.list_coordinates(user_id))
    saved_reports = 0

    coordinate_store = context.application.bot_data.get("coordinate_space_report_store")
    admixture_store = context.application.bot_data.get("admixture_report_store")
    matching_store = context.application.bot_data.get("matching_store")
    traits_store = context.application.bot_data.get("traits_report_store")
    haplogroup_store = context.application.bot_data.get("haplogroup_store")

    for sample in samples:
        sample_id = str(getattr(sample, "asset_id", "") or "")
        if not sample_id:
            continue
        if isinstance(coordinate_store, CoordinateSpaceReportStore):
            saved_reports += _safe_count(lambda sample_id=sample_id: coordinate_store.list_results(user_id, sample_id))
        if admixture_store is not None:
            saved_reports += _safe_count(lambda sample_id=sample_id: admixture_store.list_reports(user_id, sample_id))
        if matching_store is not None:
            saved_reports += _safe_count(lambda sample_id=sample_id: matching_store.list_matches_for_sample(user_id, sample_id))
        if traits_store is not None:
            saved_reports += _safe_count(lambda sample_id=sample_id: traits_store.list_reports(user_id, sample_id))
        if haplogroup_store is not None:
            saved_reports += _safe_count(lambda sample_id=sample_id: haplogroup_store.list_sample_records(user_id, sample_id))

    return PrivacyDataSummary(
        samples=len(samples),
        raw_files=raw_files,
        g25_profiles=g25_profiles,
        saved_reports=saved_reports,
    )


def footer_keyboard_row(lang: str, back_callback: str, cancel_callback: str) -> list[InlineKeyboardButton]:
    return [
        InlineKeyboardButton(f"⬅️ {t('nav.back', lang)}", callback_data=back_callback),
        InlineKeyboardButton(t("nav.cancel", lang), callback_data=cancel_callback),
    ]


def settings_text(
    lang: str,
    card_format: str = CARD_FORMAT_WIDE,
    result_mode: str = RESULT_MODE_SIMPLE,
) -> str:
    if lang == "en":
        return "<b>⚙️ Settings</b>"
    return "<b>⚙️ Настройки</b>"


def build_settings_keyboard(
    lang: str,
    *,
    callback_prefix: str = SETTINGS_CALLBACK_PREFIX,
    back_callback: str = "main:root",
    cancel_callback: str = "main:cancel",
) -> InlineKeyboardMarkup:
    card_format_button = "🖼 Card format" if lang == "en" else "🖼 Формат карточек"
    result_mode_button = "✨ Result mode" if lang == "en" else "✨ Режим результатов"
    language_button = "🌐 Language" if lang == "en" else "🌐 Язык"
    search_base_button = "🌍 Search base" if lang == "en" else "🌍 База поиска"
    notifications_button = "🔔 Notifications" if lang == "en" else "🔔 Уведомления"
    privacy_button = "🗑 Data and privacy" if lang == "en" else "🗑 Данные и приватность"
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(language_button, callback_data=f"{callback_prefix}:language")],
            [InlineKeyboardButton(card_format_button, callback_data=f"{callback_prefix}:card_format")],
            [InlineKeyboardButton(result_mode_button, callback_data=f"{callback_prefix}:result_mode")],
            [InlineKeyboardButton(search_base_button, callback_data=f"{callback_prefix}:search_base")],
            [InlineKeyboardButton(notifications_button, callback_data=f"{callback_prefix}:notifications")],
            [InlineKeyboardButton(privacy_button, callback_data=f"{callback_prefix}:privacy")],
            [InlineKeyboardButton(t("nav.cancel", lang), callback_data=cancel_callback)],
        ]
    )


def card_format_text(lang: str, card_format: str) -> str:
    current_card_format = card_format_label(card_format, lang)
    if lang == "en":
        return "\n".join(
            [
                "<b>🖼 Card format</b>",
                "",
                f"<b>Current format:</b> {current_card_format}",
            ]
        )
    return "\n".join(
        [
            "<b>🖼 Формат карточек</b>",
            "",
            f"<b>Текущий формат:</b> {current_card_format}",
        ]
    )


def build_card_format_keyboard(
    lang: str,
    card_format: str,
    *,
    callback_prefix: str = SETTINGS_CALLBACK_PREFIX,
    back_callback: str = f"{SETTINGS_CALLBACK_PREFIX}:root",
    cancel_callback: str = "main:cancel",
) -> InlineKeyboardMarkup:
    current = normalize_card_format(card_format)
    rows: list[list[InlineKeyboardButton]] = []
    for option in SUPPORTED_CARD_FORMATS:
        suffix = " ✅" if option == current else ""
        rows.append(
            [
                InlineKeyboardButton(
                    f"{card_format_label(option, lang)}{suffix}",
                    callback_data=f"{callback_prefix}:set_card_format:{option}",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(f"⬅️ {t('nav.back', lang)}", callback_data=back_callback),
            InlineKeyboardButton(t("nav.cancel", lang), callback_data=cancel_callback),
        ]
    )
    return InlineKeyboardMarkup(rows)


def result_mode_text(lang: str, result_mode: str) -> str:
    current_result_mode = result_mode_label(result_mode, lang)
    if lang == "en":
        return "\n".join(
            [
                "<b>✨ Result mode</b>",
                "",
                f"<b>Current mode:</b> {current_result_mode}",
            ]
        )
    return "\n".join(
        [
            "<b>✨ Режим результатов</b>",
            "",
            f"<b>Текущий режим:</b> {current_result_mode}",
        ]
    )


def build_result_mode_keyboard(
    lang: str,
    result_mode: str,
    *,
    callback_prefix: str = SETTINGS_CALLBACK_PREFIX,
    back_callback: str = f"{SETTINGS_CALLBACK_PREFIX}:root",
    cancel_callback: str = "main:cancel",
) -> InlineKeyboardMarkup:
    current = normalize_result_mode(result_mode)
    rows: list[list[InlineKeyboardButton]] = []
    for option in SUPPORTED_RESULT_MODES:
        suffix = " ✅" if option == current else ""
        rows.append(
            [
                InlineKeyboardButton(
                    f"{result_mode_label(option, lang)}{suffix}",
                    callback_data=f"{callback_prefix}:set_result_mode:{option}",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(f"⬅️ {t('nav.back', lang)}", callback_data=back_callback),
            InlineKeyboardButton(t("nav.cancel", lang), callback_data=cancel_callback),
        ]
    )
    return InlineKeyboardMarkup(rows)


def search_base_text(lang: str, search_base: str) -> str:
    current_search_base = search_base_label(search_base, lang)
    if lang == "en":
        return "\n".join(
            [
                "<b>🌍 Search base</b>",
                "",
                "This setting affects only surname search and base analytics.",
                "",
                f"<b>Current base:</b> {current_search_base}",
            ]
        )
    return "\n".join(
        [
            "<b>🌍 База поиска</b>",
            "",
            "Эта настройка влияет только на поиск по фамилии и аналитику базы.",
            "",
            f"<b>Текущая база:</b> {current_search_base}",
        ]
    )


def build_search_base_keyboard(
    lang: str,
    search_base: str,
    *,
    callback_prefix: str = SETTINGS_CALLBACK_PREFIX,
    back_callback: str = f"{SETTINGS_CALLBACK_PREFIX}:root",
    cancel_callback: str = "main:cancel",
) -> InlineKeyboardMarkup:
    current = normalize_search_base(search_base)
    rows: list[list[InlineKeyboardButton]] = []
    for option in SEARCH_BASES:
        suffix = " ✅" if option == current else ""
        rows.append(
            [
                InlineKeyboardButton(
                    f"{search_base_label(option, lang)}{suffix}",
                    callback_data=f"{callback_prefix}:set_search_base:{option}",
                )
            ]
        )
    rows.append(footer_keyboard_row(lang, back_callback, cancel_callback))
    return InlineKeyboardMarkup(rows)


def notifications_text(lang: str, enabled: bool) -> str:
    status = notifications_status_label(enabled, lang)
    if lang == "en":
        return "\n".join(
            [
                "<b>🔔 Notifications</b>",
                "",
                "Notifications about important bot events.",
                "",
                f"<b>Current status:</b> {status}",
            ]
        )
    return "\n".join(
        [
            "<b>🔔 Уведомления</b>",
            "",
            "Уведомления о важных событиях бота.",
            "",
            f"<b>Текущий статус:</b> {status}",
        ]
    )


def build_notifications_keyboard(
    lang: str,
    enabled: bool,
    *,
    callback_prefix: str = SETTINGS_CALLBACK_PREFIX,
    back_callback: str = f"{SETTINGS_CALLBACK_PREFIX}:root",
    cancel_callback: str = "main:cancel",
) -> InlineKeyboardMarkup:
    on_suffix = " ✅" if enabled else ""
    off_suffix = " ✅" if not enabled else ""
    on_label = "🔔 Enabled" if lang == "en" else "🔔 Включены"
    off_label = "🔕 Disabled" if lang == "en" else "🔕 Выключены"
    rows = [
        [InlineKeyboardButton(f"{on_label}{on_suffix}", callback_data=f"{callback_prefix}:set_notifications:on")],
        [InlineKeyboardButton(f"{off_label}{off_suffix}", callback_data=f"{callback_prefix}:set_notifications:off")],
        footer_keyboard_row(lang, back_callback, cancel_callback),
    ]
    return InlineKeyboardMarkup(rows)


def privacy_text(lang: str, summary: PrivacyDataSummary | None = None) -> str:
    data = summary or PrivacyDataSummary()
    if lang == "en":
        return "\n".join(
            [
                "<b>🗑 Data and privacy</b>",
                "",
                "Here you can see what is stored in My DNA and open the relevant sections.",
                "",
                f"Samples: {data.samples}",
                f"Raw files: {data.raw_files}",
                f"G25 profiles: {data.g25_profiles}",
                f"Saved reports: {data.saved_reports}",
            ]
        )
    return "\n".join(
        [
            "<b>🗑 Данные и приватность</b>",
            "",
            "Здесь видно, что сохранено в My DNA, и можно открыть нужный раздел.",
            "",
            f"Образцы: {data.samples}",
            f"Raw-файлы: {data.raw_files}",
            f"G25-профили: {data.g25_profiles}",
            f"Сохранённые отчёты: {data.saved_reports}",
        ]
    )


def build_privacy_keyboard(
    lang: str,
    *,
    callback_prefix: str = SETTINGS_CALLBACK_PREFIX,
    back_callback: str = f"{SETTINGS_CALLBACK_PREFIX}:root",
    cancel_callback: str = "main:cancel",
) -> InlineKeyboardMarkup:
    if lang == "en":
        rows = [
            [InlineKeyboardButton("📁 Samples", callback_data=f"{callback_prefix}:privacy_samples")],
            [InlineKeyboardButton("📍 G25 profiles", callback_data=f"{callback_prefix}:privacy_g25")],
            [InlineKeyboardButton("📊 Reports", callback_data=f"{callback_prefix}:privacy_reports")],
            [InlineKeyboardButton("📦 Export my data", callback_data=f"{callback_prefix}:export_data")],
            [InlineKeyboardButton("🗑 Delete all my data", callback_data=f"{callback_prefix}:delete_data")],
            [InlineKeyboardButton("ℹ️ How data is stored", callback_data=f"{callback_prefix}:privacy_info")],
        ]
    else:
        rows = [
            [InlineKeyboardButton("📁 Образцы", callback_data=f"{callback_prefix}:privacy_samples")],
            [InlineKeyboardButton("📍 G25-профили", callback_data=f"{callback_prefix}:privacy_g25")],
            [InlineKeyboardButton("📊 Отчёты", callback_data=f"{callback_prefix}:privacy_reports")],
            [InlineKeyboardButton("📦 Экспорт моих данных", callback_data=f"{callback_prefix}:export_data")],
            [InlineKeyboardButton("🗑 Удалить все мои данные", callback_data=f"{callback_prefix}:delete_data")],
            [InlineKeyboardButton("ℹ️ Как хранятся данные", callback_data=f"{callback_prefix}:privacy_info")],
        ]
    rows.append(footer_keyboard_row(lang, back_callback, cancel_callback))
    return InlineKeyboardMarkup(rows)


def privacy_placeholder_text(action: str, lang: str) -> str:
    if lang == "en":
        return "\n".join(
            [
                "<b>ℹ️ How data is stored</b>",
                "",
                "My DNA stores uploaded raw files, samples, G25 profiles, and saved reports. This data is used only for bot features.",
            ]
        )
    return "\n".join(
        [
            "<b>ℹ️ Как хранятся данные</b>",
            "",
            "В My DNA хранятся загруженные raw-файлы, samples, G25-профили и сохранённые отчёты. Эти данные используются только для функций бота.",
        ]
    )


def build_privacy_placeholder_keyboard(
    lang: str,
    *,
    back_callback: str = f"{SETTINGS_CALLBACK_PREFIX}:privacy",
    cancel_callback: str = "main:cancel",
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([footer_keyboard_row(lang, back_callback, cancel_callback)])


def privacy_export_text(lang: str, summary: PrivacyDataSummary) -> str:
    if lang == "en":
        return "\n".join(
            [
                "<b>📦 Export my data</b>",
                "",
                "Download a zip archive with your stored My DNA data and reports.",
                "The file will be sent as a separate message in this chat.",
                "",
                f"Samples: {summary.samples}",
                f"Raw files: {summary.raw_files}",
                f"G25 profiles: {summary.g25_profiles}",
                f"Saved reports: {summary.saved_reports}",
            ]
        )
    return "\n".join(
        [
            "<b>📦 Экспорт моих данных</b>",
            "",
            "Скачать zip-архив с сохранёнными My DNA данными и отчётами.",
            "Файл придёт отдельным сообщением в этот же чат.",
            "",
            f"Samples: {summary.samples}",
            f"Raw-файлы: {summary.raw_files}",
            f"G25-профили: {summary.g25_profiles}",
            f"Сохранённые отчёты: {summary.saved_reports}",
        ]
    )


def build_privacy_export_keyboard(
    lang: str,
    *,
    callback_prefix: str = SETTINGS_CALLBACK_PREFIX,
    back_callback: str = f"{SETTINGS_CALLBACK_PREFIX}:privacy",
    cancel_callback: str = "main:cancel",
) -> InlineKeyboardMarkup:
    export_label = "📦 Export" if lang == "en" else "📦 Экспортировать"
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(export_label, callback_data=f"{callback_prefix}:export_data_run")],
            footer_keyboard_row(lang, back_callback, cancel_callback),
        ]
    )


def privacy_delete_confirm_text(lang: str, summary: PrivacyDataSummary) -> str:
    if lang == "en":
        return "\n".join(
            [
                "<b>🗑 Delete all my data</b>",
                "",
                "This will delete:",
                f"Samples: {summary.samples}",
                f"Raw files: {summary.raw_files}",
                f"G25 profiles: {summary.g25_profiles}",
                f"Saved reports: {summary.saved_reports}",
                "",
                "This action cannot be undone.",
            ]
        )
    return "\n".join(
        [
            "<b>🗑 Удалить все мои данные</b>",
            "",
            "Будет удалено:",
            f"Samples: {summary.samples}",
            f"Raw-файлы: {summary.raw_files}",
            f"G25-профили: {summary.g25_profiles}",
            f"Сохранённые отчёты: {summary.saved_reports}",
            "",
            "Это действие нельзя отменить.",
        ]
    )


def privacy_delete_done_text(lang: str, summary: PrivacyDataSummary) -> str:
    if lang == "en":
        return "\n".join(
            [
                "<b>🗑 Data deleted</b>",
                "",
                "Deleted:",
                f"Samples: {summary.samples}",
                f"Raw files: {summary.raw_files}",
                f"G25 profiles: {summary.g25_profiles}",
                f"Saved reports: {summary.saved_reports}",
            ]
        )
    return "\n".join(
        [
            "<b>🗑 Данные удалены</b>",
            "",
            "Удалено:",
            f"Samples: {summary.samples}",
            f"Raw-файлы: {summary.raw_files}",
            f"G25-профили: {summary.g25_profiles}",
            f"Сохранённые отчёты: {summary.saved_reports}",
        ]
    )


def privacy_export_done_text(lang: str, summary: PrivacyDataSummary, archive_name: str | None = None) -> str:
    if lang == "en":
        file_line = f"File: {archive_name}" if archive_name else "The zip should appear as a separate message in this chat."
        return "\n".join(
            [
                "<b>📦 Export my data</b>",
                "",
                "The zip was sent as a separate message in this chat.",
                file_line,
                "",
                f"Samples: {summary.samples}",
                f"Raw files: {summary.raw_files}",
                f"G25 profiles: {summary.g25_profiles}",
                f"Saved reports: {summary.saved_reports}",
            ]
        )
    file_line = f"Файл: {archive_name}" if archive_name else "Zip должен появиться отдельным сообщением в этом же чате."
    return "\n".join(
        [
            "<b>📦 Экспорт моих данных</b>",
            "",
            "Zip отправлен отдельным сообщением в этот же чат.",
            file_line,
            "",
            f"Samples: {summary.samples}",
            f"Raw-файлы: {summary.raw_files}",
            f"G25-профили: {summary.g25_profiles}",
            f"Сохранённые отчёты: {summary.saved_reports}",
        ]
    )


def privacy_export_progress_text(lang: str) -> str:
    if lang == "en":
        return "\n".join(["<b>📦 Export my data</b>", "", "Preparing archive. This may take a little time."])
    return "\n".join(["<b>📦 Экспорт моих данных</b>", "", "Готовлю архив. Это может занять немного времени."])


def privacy_export_error_text(lang: str) -> str:
    if lang == "en":
        return "\n".join(
            [
                "<b>📦 Export my data</b>",
                "",
                "Could not prepare or send the archive.",
                "Try again later or export sections separately.",
            ]
        )
    return "\n".join(
        [
            "<b>📦 Экспорт моих данных</b>",
            "",
            "Не удалось подготовить или отправить архив.",
            "Попробуйте позже или выгрузите данные по разделам.",
        ]
    )


def build_privacy_delete_confirm_keyboard(
    lang: str,
    *,
    callback_prefix: str = SETTINGS_CALLBACK_PREFIX,
    back_callback: str = f"{SETTINGS_CALLBACK_PREFIX}:privacy",
    cancel_callback: str = "main:cancel",
) -> InlineKeyboardMarkup:
    confirm_label = "✅ Yes, delete all" if lang == "en" else "✅ Да, удалить всё"
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(confirm_label, callback_data=f"{callback_prefix}:delete_data_confirm")],
            footer_keyboard_row(lang, back_callback, cancel_callback),
        ]
    )


def language_text(lang: str) -> str:
    if lang == "en":
        return "\n".join(
            [
                "<b>🌐 Language</b>",
                "",
                f"<b>Current language:</b> {language_name(lang)}",
                "",
                "Choose the interface language.",
            ]
        )
    return "\n".join(
        [
            "<b>🌐 Язык</b>",
            "",
            f"<b>Текущий язык:</b> {language_name(lang)}",
            "",
            "Выберите язык интерфейса.",
        ]
    )


def build_language_keyboard(
    lang: str,
    *,
    callback_prefix: str = SETTINGS_CALLBACK_PREFIX,
    back_callback: str = f"{SETTINGS_CALLBACK_PREFIX}:root",
    cancel_callback: str = "main:cancel",
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for option in SUPPORTED_LANGUAGES:
        suffix = " ✅" if option == lang else ""
        rows.append(
            [
                InlineKeyboardButton(
                    f"{LANGUAGE_NAMES[option]}{suffix}",
                    callback_data=f"{callback_prefix}:set_language:{option}",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(t("nav.back", lang), callback_data=back_callback),
            InlineKeyboardButton(t("nav.cancel", lang), callback_data=cancel_callback),
        ]
    )
    return InlineKeyboardMarkup(rows)


async def show_settings_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    edit_existing: bool = False,
) -> None:
    lang = get_user_language(context, user_id)
    card_format = get_user_card_format(context, user_id)
    result_mode = get_user_result_mode(context, user_id)
    if edit_existing:
        await message.edit_text(
            settings_text(lang, card_format, result_mode),
            reply_markup=build_settings_keyboard(lang),
            parse_mode="HTML",
        )
    else:
        await message.reply_text(
            settings_text(lang, card_format, result_mode),
            reply_markup=build_settings_keyboard(lang),
            parse_mode="HTML",
            do_quote=False,
        )


async def show_language_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    edit_existing: bool = False,
) -> None:
    lang = get_user_language(context, user_id)
    if edit_existing:
        await message.edit_text(language_text(lang), reply_markup=build_language_keyboard(lang), parse_mode="HTML")
    else:
        await message.reply_text(language_text(lang), reply_markup=build_language_keyboard(lang), parse_mode="HTML", do_quote=False)


async def show_card_format_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    edit_existing: bool = False,
) -> None:
    lang = get_user_language(context, user_id)
    card_format = get_user_card_format(context, user_id)
    if edit_existing:
        await message.edit_text(
            card_format_text(lang, card_format),
            reply_markup=build_card_format_keyboard(lang, card_format),
            parse_mode="HTML",
        )
    else:
        await message.reply_text(
            card_format_text(lang, card_format),
            reply_markup=build_card_format_keyboard(lang, card_format),
            parse_mode="HTML",
            do_quote=False,
        )


async def show_result_mode_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    edit_existing: bool = False,
) -> None:
    lang = get_user_language(context, user_id)
    result_mode = get_user_result_mode(context, user_id)
    if edit_existing:
        await message.edit_text(
            result_mode_text(lang, result_mode),
            reply_markup=build_result_mode_keyboard(lang, result_mode),
            parse_mode="HTML",
        )
    else:
        await message.reply_text(
            result_mode_text(lang, result_mode),
            reply_markup=build_result_mode_keyboard(lang, result_mode),
            parse_mode="HTML",
            do_quote=False,
        )


async def show_search_base_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    edit_existing: bool = False,
) -> None:
    lang = get_user_language(context, user_id)
    search_base = get_user_search_base(context, user_id)
    if edit_existing:
        await message.edit_text(
            search_base_text(lang, search_base),
            reply_markup=build_search_base_keyboard(lang, search_base),
            parse_mode="HTML",
        )
    else:
        await message.reply_text(
            search_base_text(lang, search_base),
            reply_markup=build_search_base_keyboard(lang, search_base),
            parse_mode="HTML",
            do_quote=False,
        )


async def show_notifications_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    edit_existing: bool = False,
) -> None:
    lang = get_user_language(context, user_id)
    enabled = get_user_notifications_enabled(context, user_id)
    if edit_existing:
        await message.edit_text(
            notifications_text(lang, enabled),
            reply_markup=build_notifications_keyboard(lang, enabled),
            parse_mode="HTML",
        )
    else:
        await message.reply_text(
            notifications_text(lang, enabled),
            reply_markup=build_notifications_keyboard(lang, enabled),
            parse_mode="HTML",
            do_quote=False,
        )


async def show_privacy_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    edit_existing: bool = False,
) -> None:
    lang = get_user_language(context, user_id)
    summary = privacy_data_summary(context, user_id)
    if edit_existing:
        await message.edit_text(
            privacy_text(lang, summary),
            reply_markup=build_privacy_keyboard(lang),
            parse_mode="HTML",
        )
    else:
        await message.reply_text(
            privacy_text(lang, summary),
            reply_markup=build_privacy_keyboard(lang),
            parse_mode="HTML",
            do_quote=False,
        )


async def show_privacy_placeholder(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    action: str,
    *,
    edit_existing: bool = False,
) -> None:
    lang = get_user_language(context, user_id)
    if edit_existing:
        await message.edit_text(
            privacy_placeholder_text(action, lang),
            reply_markup=build_privacy_placeholder_keyboard(lang),
            parse_mode="HTML",
        )
    else:
        await message.reply_text(
            privacy_placeholder_text(action, lang),
            reply_markup=build_privacy_placeholder_keyboard(lang),
            parse_mode="HTML",
            do_quote=False,
        )


async def show_privacy_export_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    callback_prefix: str = SETTINGS_CALLBACK_PREFIX,
    back_callback: str = f"{SETTINGS_CALLBACK_PREFIX}:privacy",
    cancel_callback: str = "main:cancel",
    edit_existing: bool = False,
) -> None:
    lang = get_user_language(context, user_id)
    summary = privacy_data_summary(context, user_id)
    text = privacy_export_text(lang, summary)
    markup = build_privacy_export_keyboard(
        lang,
        callback_prefix=callback_prefix,
        back_callback=back_callback,
        cancel_callback=cancel_callback,
    )
    if edit_existing:
        await message.edit_text(text, reply_markup=markup, parse_mode="HTML")
    else:
        await message.reply_text(text, reply_markup=markup, parse_mode="HTML", do_quote=False)


async def show_privacy_export_result(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    callback_prefix: str = SETTINGS_CALLBACK_PREFIX,
    back_callback: str = f"{SETTINGS_CALLBACK_PREFIX}:privacy",
    cancel_callback: str = "main:cancel",
    edit_existing: bool = False,
) -> None:
    lang = get_user_language(context, user_id)
    markup = build_privacy_placeholder_keyboard(lang, back_callback=back_callback, cancel_callback=cancel_callback)
    if edit_existing:
        await message.edit_text(privacy_export_progress_text(lang), reply_markup=markup, parse_mode="HTML")
    else:
        await message.reply_text(privacy_export_progress_text(lang), reply_markup=markup, parse_mode="HTML", do_quote=False)

    summary = PrivacyDataSummary()
    archive_path: Path | None = None
    try:
        summary = privacy_data_summary(context, user_id)
        archive_path = export_user_data_archive(context, user_id)
        with archive_path.open("rb") as handle:
            await context.bot.send_document(
                chat_id=message.chat_id,
                document=InputFile(handle, filename=archive_path.name),
                caption="KBDNA data export",
            )
        text = privacy_export_done_text(lang, summary, archive_path.name)
    except Exception:
        logger.exception("Could not export user data")
        text = privacy_export_error_text(lang)
    finally:
        if archive_path is not None:
            try:
                archive_path.unlink()
            except FileNotFoundError:
                pass

    if edit_existing:
        await message.edit_text(text, reply_markup=markup, parse_mode="HTML")
    else:
        await message.reply_text(text, reply_markup=markup, parse_mode="HTML", do_quote=False)


async def show_privacy_delete_confirm(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    callback_prefix: str = SETTINGS_CALLBACK_PREFIX,
    back_callback: str = f"{SETTINGS_CALLBACK_PREFIX}:privacy",
    cancel_callback: str = "main:cancel",
    edit_existing: bool = False,
) -> None:
    lang = get_user_language(context, user_id)
    summary = privacy_data_summary(context, user_id)
    markup = build_privacy_delete_confirm_keyboard(
        lang,
        callback_prefix=callback_prefix,
        back_callback=back_callback,
        cancel_callback=cancel_callback,
    )
    text = privacy_delete_confirm_text(lang, summary)
    if edit_existing:
        await message.edit_text(text, reply_markup=markup, parse_mode="HTML")
    else:
        await message.reply_text(text, reply_markup=markup, parse_mode="HTML", do_quote=False)


async def show_privacy_delete_done(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    back_callback: str = f"{SETTINGS_CALLBACK_PREFIX}:root",
    cancel_callback: str = "main:cancel",
    edit_existing: bool = False,
) -> None:
    lang = get_user_language(context, user_id)
    summary = delete_user_data(context, user_id)
    markup = build_privacy_placeholder_keyboard(lang, back_callback=back_callback, cancel_callback=cancel_callback)
    text = privacy_delete_done_text(lang, summary)
    if edit_existing:
        await message.edit_text(text, reply_markup=markup, parse_mode="HTML")
    else:
        await message.reply_text(text, reply_markup=markup, parse_mode="HTML", do_quote=False)


async def settings_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None or query.message is None:
        return
    if not query.data.startswith(f"{SETTINGS_CALLBACK_PREFIX}:"):
        return
    if not await ensure_active_main_menu(update, context):
        return
    if update.effective_user is None:
        return

    await query.answer()
    user_id = int(update.effective_user.id)
    parts = query.data.split(":")
    action = parts[1] if len(parts) > 1 else "root"

    if action == "root":
        await show_settings_menu(query.message, context, user_id, edit_existing=True)
        return
    if action == "language":
        await show_language_menu(query.message, context, user_id, edit_existing=True)
        return
    if action == "card_format":
        await show_card_format_menu(query.message, context, user_id, edit_existing=True)
        return
    if action == "result_mode":
        await show_result_mode_menu(query.message, context, user_id, edit_existing=True)
        return
    if action == "search_base":
        await show_search_base_menu(query.message, context, user_id, edit_existing=True)
        return
    if action == "notifications":
        await show_notifications_menu(query.message, context, user_id, edit_existing=True)
        return
    if action == "privacy":
        await show_privacy_menu(query.message, context, user_id, edit_existing=True)
        return
    if action == "privacy_samples":
        context.user_data[PRIVACY_ROOT_BACK_KEY] = f"{SETTINGS_CALLBACK_PREFIX}:privacy"
        context.user_data[PRIVACY_SAMPLES_BACK_KEY] = f"{SETTINGS_CALLBACK_PREFIX}:privacy_samples"
        set_active_main_menu_message(context, query.message.chat_id, user_id, query.message.message_id)
        await show_view_samples_menu(
            query.message,
            context,
            user_id,
            edit_existing=True,
            back_callback=f"{SETTINGS_CALLBACK_PREFIX}:privacy",
        )
        return
    if action == "privacy_g25":
        context.user_data[PRIVACY_ROOT_BACK_KEY] = f"{SETTINGS_CALLBACK_PREFIX}:privacy"
        context.user_data[PRIVACY_G25_BACK_KEY] = f"{SETTINGS_CALLBACK_PREFIX}:privacy_g25"
        set_active_main_menu_message(context, query.message.chat_id, user_id, query.message.message_id)
        await show_view_coordinates_menu(
            query.message,
            context,
            user_id,
            edit_existing=True,
            back_callback=f"{SETTINGS_CALLBACK_PREFIX}:privacy",
        )
        return
    if action == "privacy_reports":
        context.user_data[PRIVACY_ROOT_BACK_KEY] = f"{SETTINGS_CALLBACK_PREFIX}:privacy"
        context.user_data[PRIVACY_REPORTS_BACK_KEY] = f"{SETTINGS_CALLBACK_PREFIX}:privacy_reports"
        context.user_data["reports_back_callback"] = f"{SETTINGS_CALLBACK_PREFIX}:privacy"
        context.user_data["reports_my_dna_callback"] = f"{SETTINGS_CALLBACK_PREFIX}:privacy"
        context.user_data["reports_sample_callback_template"] = f"{SETTINGS_CALLBACK_PREFIX}:privacy_sample_reports:{{sample_id}}"
        set_active_main_menu_message(context, query.message.chat_id, user_id, query.message.message_id)
        lang = get_user_language(context, user_id)
        await show_reports_menu(
            query.message,
            context,
            user_id,
            edit_existing=True,
            lang=lang,
            back_callback=f"{SETTINGS_CALLBACK_PREFIX}:privacy",
            my_dna_callback=f"{SETTINGS_CALLBACK_PREFIX}:privacy",
            show_my_dna_shortcut=False,
            sample_callback_template=f"{SETTINGS_CALLBACK_PREFIX}:privacy_sample_reports:{{sample_id}}",
        )
        return
    if action == "privacy_sample_reports":
        sample_id = parts[2] if len(parts) > 2 else ""
        context.user_data[PRIVACY_ROOT_BACK_KEY] = f"{SETTINGS_CALLBACK_PREFIX}:privacy"
        context.user_data[PRIVACY_REPORTS_BACK_KEY] = f"{SETTINGS_CALLBACK_PREFIX}:privacy_reports"
        set_active_main_menu_message(context, query.message.chat_id, user_id, query.message.message_id)
        await show_sample_reports_menu(
            query.message,
            context,
            user_id,
            sample_id,
            edit_existing=True,
            back_callback=f"{SETTINGS_CALLBACK_PREFIX}:privacy_reports",
        )
        return
    if action == "export_data":
        await show_privacy_export_menu(
            query.message,
            context,
            user_id,
            callback_prefix=SETTINGS_CALLBACK_PREFIX,
            edit_existing=True,
            back_callback=f"{SETTINGS_CALLBACK_PREFIX}:privacy",
            cancel_callback="main:cancel",
        )
        return
    if action == "export_data_run":
        await show_privacy_export_result(
            query.message,
            context,
            user_id,
            edit_existing=True,
            back_callback=f"{SETTINGS_CALLBACK_PREFIX}:privacy",
            cancel_callback="main:cancel",
        )
        return
    if action == "delete_data":
        await show_privacy_delete_confirm(
            query.message,
            context,
            user_id,
            edit_existing=True,
            callback_prefix=SETTINGS_CALLBACK_PREFIX,
            back_callback=f"{SETTINGS_CALLBACK_PREFIX}:privacy",
            cancel_callback="main:cancel",
        )
        return
    if action == "delete_data_confirm":
        await show_privacy_delete_done(
            query.message,
            context,
            user_id,
            edit_existing=True,
            back_callback=f"{SETTINGS_CALLBACK_PREFIX}:root",
            cancel_callback="main:cancel",
        )
        return
    if action == "privacy_info":
        await show_privacy_placeholder(query.message, context, user_id, action, edit_existing=True)
        return
    if action == "set_language":
        selected = parts[2] if len(parts) > 2 else ""
        set_user_language(context, user_id, selected)
        await show_settings_menu(query.message, context, user_id, edit_existing=True)
        return
    if action == "set_card_format":
        selected = parts[2] if len(parts) > 2 else ""
        if not set_user_card_format(context, user_id, selected):
            await query.answer("Не удалось сохранить формат.", show_alert=True)
            return
        await show_card_format_menu(query.message, context, user_id, edit_existing=True)
        return
    if action == "set_result_mode":
        selected = parts[2] if len(parts) > 2 else ""
        if not set_user_result_mode(context, user_id, selected):
            await query.answer("Не удалось сохранить режим.", show_alert=True)
            return
        await show_result_mode_menu(query.message, context, user_id, edit_existing=True)
        return
    if action == "set_search_base":
        selected = parts[2] if len(parts) > 2 else ""
        if not set_user_search_base(context, user_id, selected):
            await query.answer("Не удалось сохранить базу.", show_alert=True)
            return
        await show_search_base_menu(query.message, context, user_id, edit_existing=True)
        return
    if action == "set_notifications":
        selected = parts[2] if len(parts) > 2 else ""
        set_user_notifications_enabled(context, user_id, selected == "on")
        await show_notifications_menu(query.message, context, user_id, edit_existing=True)
        return
