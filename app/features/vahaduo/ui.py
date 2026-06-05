from __future__ import annotations

import html
import logging
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.i18n import t
from g25_core.command_service import G25CommandService, group_emoji
from g25_core.render_fit_svg import display_name

G25MENU_CALLBACK_PREFIX = "vahaduo"
MENU_CALLBACK_PREFIX = "main"

logger = logging.getLogger(__name__)


def _en(lang: str) -> bool:
    return lang == "en"


def _copy(lang: str, ru: str, en: str) -> str:
    return en if _en(lang) else ru


def _back_label(lang: str) -> str:
    return t("nav.back", lang)


def _cancel_label(lang: str) -> str:
    return t("nav.cancel", lang)


def _done_label(lang: str) -> str:
    return _copy(lang, "✅ Готово", "✅ Done")


def _clear_label(lang: str) -> str:
    return _copy(lang, "🧹 Очистить", "🧹 Clear")


def _all_label(lang: str) -> str:
    return _copy(lang, "✅ Выбрать все", "✅ Select all")


def _other_g25_label(lang: str) -> str:
    return _copy(lang, "G25-профили", "G25 profiles")


def _my_g25_label(lang: str) -> str:
    return _copy(lang, "G25-профили", "G25 profiles")


def _panel_source_emoji(source_key: str) -> str:
    return {
        "maikop": "\U0001F3D4\uFE0F",
        "steppe_sintashta": "\U0001F40E",
        "afanasievo": "\U0001F40E",
        "ulaanzhukh": "\U0001F3F9",
        "angara_river": "\U0001F3F9",
        "yamnaya": "\U0001F40E",
        "yellowriver": "\u26E9\uFE0F",
        "anatolia_ba": "\U0001F3FA",
        "baltic_ba": "\U0001F332",
        "bmac": "\u2600\uFE0F",
        "khovsgol": "\U0001F3F9",
        "kuraaraxes": "\U0001F3D4\uFE0F",
    }.get(source_key, "")


def _build_g25vahaduo_full_keyboard(*, lang: str = "ru") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(_copy(lang, "📚 Мои источники", "📚 My sources"), callback_data=f"{G25MENU_CALLBACK_PREFIX}:vahaduo_data"),
        ],
        [
            InlineKeyboardButton("📏 Distance", callback_data=f"{G25MENU_CALLBACK_PREFIX}:vahaduo_mode_distance"),
        ],
        [
            InlineKeyboardButton("🧬 Single", callback_data=f"{G25MENU_CALLBACK_PREFIX}:vahaduo_mode_single"),
        ],
        [
            InlineKeyboardButton("🧩 Multi", callback_data=f"{G25MENU_CALLBACK_PREFIX}:vahaduo_mode_multi"),
        ],
        [
            InlineKeyboardButton("📚 Ready models", callback_data=f"{G25MENU_CALLBACK_PREFIX}:ready_models"),
        ],
        [
            InlineKeyboardButton(_copy(lang, "⬅️ Назад", "⬅️ Back"), callback_data=f"{MENU_CALLBACK_PREFIX}:root"),
            InlineKeyboardButton(_cancel_label(lang), callback_data=f"{G25MENU_CALLBACK_PREFIX}:cancel"),
        ],
    ])


def _g25vahaduo_full_text(*, lang: str = "ru") -> str:
    return "\n".join([
        "<b>📐 Vahaduo Lab</b>",
        "",
        _copy(lang, "G25-инструменты", "G25 tools"),
    ])


def _vahaduo_mode_label(mode: str) -> str:
    if mode == "single":
        return "Single"
    if mode == "multi":
        return "Multi"
    return "Distance"


def _vahaduo_mode_title(mode: str) -> str:
    if mode == "single":
        return "🧬 Single"
    if mode == "multi":
        return "🧩 Multi"
    return "📏 Distance"


def _vahaduo_source_set_label(raw_label: str, *, lang: str = "ru") -> str:
    label = raw_label.strip()
    normalized = label.lower().replace(" ", "_")
    if normalized in {"panel1", "single_panel1", "steppe_russia"}:
        return "🐎 Steppe / Russia"
    if normalized in {"panel2", "single_panel2", "eba"}:
        return "🏺 EBA"
    if not label:
        return _copy(lang, "📚 Мои источники", "📚 My sources")
    if label.startswith(("📚", "🐎", "🏺")):
        return label
    return f"📚 {label}"


def _vahaduo_short_source_list(items: list[str], *, lang: str = "ru") -> str:
    cleaned = [item.strip() for item in items if item.strip()]
    if not cleaned:
        return ""
    visible = cleaned[:3]
    if len(cleaned) > 3:
        visible.append(_copy(lang, f"+ ещё {len(cleaned) - 3}", f"+ {len(cleaned) - 3} more"))
    return " · ".join(visible)


def _vahaduo_result_component_emoji(raw_name: str) -> str:
    name = raw_name.strip()
    shown = display_name(name)
    aliases = {
        "Steppe Sintashta": "🐎",
        "Steppe_Sintashta": "🐎",
        "Ulaanzhukh": "🦌",
        "Ulaanzukh": "🦌",
        "Yellow River": "⛩️",
        "Yellow_River": "⛩️",
        "YellowRiver": "⛩️",
        "BMAC": "☀️",
    }
    return group_emoji(name) or aliases.get(name, "") or aliases.get(shown, "")


def _vahaduo_single_model_lines(state: dict[str, object], *, include_count: bool = False, lang: str = "ru") -> list[str]:
    raw_label = str(state.get("source_label") or "").strip()
    source_key = str(state.get("source_key") or "").strip()
    panel_label = raw_label
    raw_sources = ""
    if ":" in raw_label:
        panel_label, raw_sources = raw_label.split(":", 1)
    elif source_key in {"single_panel1", "panel1"}:
        panel_label = "Steppe_Russia"
    elif source_key in {"single_panel2", "panel2"}:
        panel_label = "EBA"
    sources = [part.strip() for part in raw_sources.split(",") if part.strip()]
    lines = [f"{_copy(lang, 'Набор', 'Set')}: {_vahaduo_source_set_label(panel_label, lang=lang)}"]
    source_text = _vahaduo_short_source_list(sources, lang=lang)
    if source_text:
        lines.append(f"{_copy(lang, 'Источники', 'Sources')}: {source_text}")
    if include_count:
        source_count = int(state.get("source_count") or 0)
        if source_count:
            lines.append(f"{_copy(lang, 'Популяций', 'Populations')}: {source_count}")
    return lines


def _vahaduo_model_context_lines(state: dict[str, object], *, include_count: bool = False, lang: str = "ru") -> list[str]:
    mode = str(state.get("mode") or "distance")
    if mode in {"single", "multi"}:
        return _vahaduo_single_model_lines(state, include_count=include_count, lang=lang)
    lines = [f"{_copy(lang, 'Источник', 'Source')}: {_vahaduo_source_display_label(state, lang=lang)}"]
    if include_count:
        lines.append(f"{_copy(lang, 'Популяций', 'Populations')}: {int(state.get('source_count') or 0)}")
    return lines


def _vahaduo_source_button_label(item: dict[str, object]) -> str:
    key = str(item.get("key") or "").strip().lower()
    label = str(item.get("label") or "").strip()
    if key == "modern" or label.lower() == "modern":
        return "🌍 Modern"
    if key in {"origin", "ancestry", "ancient"} or label.lower() in {"ancestry", "ancient"}:
        return "🏺 Ancient"
    if key in {"panel1", "panel2"} or label.lower() in {"steppe_russia", "eba"}:
        return _vahaduo_source_set_label(label or key)
    return label


def _vahaduo_source_display_label(state: dict[str, object], *, lang: str = "ru") -> str:
    key = str(state.get("source_key") or "").strip().lower()
    label = str(state.get("source_label") or "").strip()
    input_mode = str(state.get("source_input_mode") or "").strip().lower()
    label_lower = label.lower()
    if key == "modern" or label_lower == "modern":
        return "🌍 Modern"
    if key in {"origin", "ancestry", "ancient"} or label_lower in {"origin", "ancestry", "ancient"}:
        return "🏺 Ancient"
    if key.startswith("saved_") or input_mode in {"saved", "source-text", "source-file"}:
        return _copy(lang, "📚 Мои источники", "📚 My sources")
    return label or _copy(lang, "📚 Мои источники", "📚 My sources")


def _vahaduo_target_section_label(source: str, *, lang: str = "ru") -> str:
    if source == "samples":
        return "🧬 Samples"
    return _copy(lang, "📍 G25-профили", "📍 G25 profiles")


def _build_g25vahaduo_source_menu_keyboard(
    service: G25CommandService,
    state: dict[str, object],
    *,
    lang: str = "ru",
) -> InlineKeyboardMarkup:
    mode = str(state.get("mode") or "distance")
    rows = [
        [
            InlineKeyboardButton(
                _vahaduo_source_button_label(item),
                callback_data=f"{G25MENU_CALLBACK_PREFIX}:vahaduo_preset:{item['key']}",
            )
        ]
        for item in service.list_vahaduo_preset_sources(mode)
    ]
    rows.append([
        InlineKeyboardButton(_copy(lang, "📚 Мои источники", "📚 My sources"), callback_data=f"{G25MENU_CALLBACK_PREFIX}:vahaduo_data_from_sources"),
    ])
    rows.append([
        InlineKeyboardButton(_copy(lang, "⬅️ Назад", "⬅️ Back"), callback_data=f"{G25MENU_CALLBACK_PREFIX}:vahaduo_full"),
        InlineKeyboardButton(_cancel_label(lang), callback_data=f"{G25MENU_CALLBACK_PREFIX}:cancel"),
    ])
    return InlineKeyboardMarkup(rows)


def _g25vahaduo_source_menu_text(state: dict[str, object], *, lang: str = "ru") -> str:
    mode = str(state.get("mode") or "distance")
    return f"{_vahaduo_mode_title(mode)}\n\n{_copy(lang, 'Выберите источники', 'Choose sources')}"


def _build_g25vahaduo_data_mode_keyboard(*, lang: str = "ru") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(_my_g25_label(lang), callback_data=f"{G25MENU_CALLBACK_PREFIX}:vahaduo_targets"),
        ],
        [
            InlineKeyboardButton(_copy(lang, "Мои источники для Distance", "My sources for Distance"), callback_data=f"{G25MENU_CALLBACK_PREFIX}:vahaduo_data_mode_distance"),
        ],
        [
            InlineKeyboardButton(_copy(lang, "Мои источники для Single / Multi", "My sources for Single / Multi"), callback_data=f"{G25MENU_CALLBACK_PREFIX}:vahaduo_data_mode_single"),
        ],
        [
            InlineKeyboardButton(_back_label(lang), callback_data=f"{G25MENU_CALLBACK_PREFIX}:vahaduo_full"),
            InlineKeyboardButton(_cancel_label(lang), callback_data=f"{G25MENU_CALLBACK_PREFIX}:cancel"),
        ],
    ])


def _g25vahaduo_data_mode_text(*, lang: str = "ru") -> str:
    return f"\U0001F9EC Vahaduo Lab\n\n{_copy(lang, 'Мои источники', 'My sources')}"


def _is_vahaduo_data_only(state: dict[str, object] | None) -> bool:
    return bool(state and str(state.get("data_back") or "") == "vahaduo_data")


def _g25vahaduo_data_back_action(state: dict[str, object] | None) -> str:
    action = str((state or {}).get("data_back") or "vahaduo_data")
    if action not in {"vahaduo_data", "vahaduo_sources"}:
        action = "vahaduo_data"
    return action


def _build_g25vahaduo_data_source_keyboard(state: dict[str, object], *, lang: str = "ru") -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    input_mode = str(state.get("source_input_mode") or "")
    saved_id = int(state.get("source_saved_id") or 0)
    if input_mode in {"source-text", "source-file"} and not saved_id:
        rows.append([InlineKeyboardButton(_copy(lang, "Сохранить source", "Save source"), callback_data=f"{G25MENU_CALLBACK_PREFIX}:vahaduo_save_source")])
    if saved_id:
        rows.append([InlineKeyboardButton(_copy(lang, "Удалить source", "Delete source"), callback_data=f"{G25MENU_CALLBACK_PREFIX}:vahaduo_delete:{saved_id}")])
    rows.append([
        InlineKeyboardButton(_back_label(lang), callback_data=f"{G25MENU_CALLBACK_PREFIX}:vahaduo_saved"),
        InlineKeyboardButton(_cancel_label(lang), callback_data=f"{G25MENU_CALLBACK_PREFIX}:cancel"),
    ])
    return InlineKeyboardMarkup(rows)


def _g25vahaduo_data_source_text(state: dict[str, object], prefix: str = "", *, lang: str = "ru") -> str:
    source_label = str(state.get("source_label") or "source")
    source_count = int(state.get("source_count") or 0)
    mode = _vahaduo_mode_label(str(state.get("mode") or ""))
    saved_id = int(state.get("source_saved_id") or 0)
    lines = [
        "\U0001F9EC Vahaduo Lab",
        "",
        _copy(lang, "Мои источники", "My sources"),
        "",
    ]
    if prefix:
        lines.extend([prefix, ""])
    lines.extend([
        f"SOURCE: {source_label}",
        f"{_copy(lang, 'Популяций', 'Populations')}: {source_count}",
        f"{_copy(lang, 'Режим', 'Mode')}: {mode}",
        "",
    ])
    if saved_id:
        lines.append(_copy(lang, f"Набор сохранен в ваших source для {mode}.", f"This set is saved in your {mode} sources."))
    else:
        lines.append(_copy(lang, "Набор проверен. Его можно сохранить в ваши source.", "The set is validated. You can save it to your sources."))
    return "\n".join(lines)


def _single_component_emoji(item: dict[str, object]) -> str:
    key = str(item.get("key") or "")
    emoji = str(item.get("emoji") or "")
    if emoji:
        return emoji
    return _panel_source_emoji(key)


def _build_g25vahaduo_single_components_keyboard(
    service: G25CommandService,
    panel_key: str,
    selected_keys: list[str],
    *,
    mode: str = "single",
    lang: str = "ru",
) -> InlineKeyboardMarkup:
    source_defs = service.list_vahaduo_single_components(panel_key)
    rows: list[list[InlineKeyboardButton]] = []
    for idx in range(0, len(source_defs), 2):
        row: list[InlineKeyboardButton] = []
        for item in source_defs[idx: idx + 2]:
            key = str(item["key"])
            checked = "[x] " if key in selected_keys else ""
            emoji = _single_component_emoji(item)
            prefix = f"{emoji} " if emoji else ""
            row.append(
                InlineKeyboardButton(
                    text=f"{checked}{prefix}{item['label']}",
                    callback_data=f"{G25MENU_CALLBACK_PREFIX}:vahaduo_single_toggle:{panel_key}:{key}",
                )
            )
        rows.append(row)
    rows.append([InlineKeyboardButton(_all_label(lang), callback_data=f"{G25MENU_CALLBACK_PREFIX}:vahaduo_single_all:{panel_key}")])
    rows.append([
        InlineKeyboardButton(_done_label(lang), callback_data=f"{G25MENU_CALLBACK_PREFIX}:vahaduo_single_done:{panel_key}"),
        InlineKeyboardButton(_clear_label(lang), callback_data=f"{G25MENU_CALLBACK_PREFIX}:vahaduo_single_clear:{panel_key}"),
    ])
    rows.append([
        InlineKeyboardButton(_back_label(lang), callback_data=f"{G25MENU_CALLBACK_PREFIX}:vahaduo_sources"),
        InlineKeyboardButton(_cancel_label(lang), callback_data=f"{G25MENU_CALLBACK_PREFIX}:cancel"),
    ])
    return InlineKeyboardMarkup(rows)


def _g25vahaduo_single_components_text(
    service: G25CommandService,
    panel_key: str,
    selected_keys: list[str],
    *,
    mode: str = "single",
    lang: str = "ru",
) -> str:
    panel_label = "EBA" if panel_key == "panel2" else "Steppe_Russia"
    selected_set = set(selected_keys)
    labels: list[str] = []
    for item in service.list_vahaduo_single_components(panel_key):
        if item["key"] not in selected_set:
            continue
        emoji = _single_component_emoji(item)
        prefix = f"{emoji} " if emoji else ""
        labels.append(f"{prefix}{item['label']}")
    chosen = "\n".join(f"- {label}" for label in labels) if labels else _copy(lang, "- пока ничего", "- nothing yet")
    return (
        f"{_vahaduo_mode_title(mode)}\n\n"
        f"{_copy(lang, 'Набор', 'Set')}: {_vahaduo_source_set_label(panel_label, lang=lang)}\n\n"
        f"{_copy(lang, 'Выберите источники модели.', 'Choose model sources.')}\n\n"
        f"{_copy(lang, 'Выбрано', 'Selected')}:\n{chosen}"
    )


def _build_g25vahaduo_saved_components_keyboard(
    groups: list[dict[str, object]],
    selected_indices: list[int],
    *,
    lang: str = "ru",
) -> InlineKeyboardMarkup:
    selected_set = set(selected_indices)
    rows: list[list[InlineKeyboardButton]] = []
    for idx in range(0, len(groups), 2):
        row: list[InlineKeyboardButton] = []
        for offset, item in enumerate(groups[idx: idx + 2]):
            group_index = idx + offset
            checked = "[x] " if group_index in selected_set else ""
            emoji = str(item.get("emoji") or "")
            prefix = f"{emoji} " if emoji else ""
            row.append(
                InlineKeyboardButton(
                    f"{checked}{prefix}{item.get('label') or item.get('key')}",
                    callback_data=f"{G25MENU_CALLBACK_PREFIX}:vahaduo_saved_group_toggle:{group_index}",
                )
            )
        rows.append(row)
    rows.append([InlineKeyboardButton(_all_label(lang), callback_data=f"{G25MENU_CALLBACK_PREFIX}:vahaduo_saved_group_all")])
    rows.append([
        InlineKeyboardButton(_done_label(lang), callback_data=f"{G25MENU_CALLBACK_PREFIX}:vahaduo_saved_group_done"),
        InlineKeyboardButton(_clear_label(lang), callback_data=f"{G25MENU_CALLBACK_PREFIX}:vahaduo_saved_group_clear"),
    ])
    rows.append([
        InlineKeyboardButton(_back_label(lang), callback_data=f"{G25MENU_CALLBACK_PREFIX}:vahaduo_saved"),
        InlineKeyboardButton(_cancel_label(lang), callback_data=f"{G25MENU_CALLBACK_PREFIX}:cancel"),
    ])
    return InlineKeyboardMarkup(rows)


def _g25vahaduo_saved_components_text(
    state: dict[str, object],
    groups: list[dict[str, object]],
    selected_indices: list[int],
    *,
    lang: str = "ru",
) -> str:
    source_label = str(state.get("source_label") or "")
    selected_set = set(selected_indices)
    labels: list[str] = []
    for idx, item in enumerate(groups):
        if idx not in selected_set:
            continue
        emoji = str(item.get("emoji") or "")
        prefix = f"{emoji} " if emoji else ""
        labels.append(f"{prefix}{item.get('label') or item.get('key')}")
    chosen = "\n".join(f"- {label}" for label in labels) if labels else _copy(lang, "- пока ничего", "- nothing yet")
    return (
        f"{_vahaduo_mode_title(str(state.get('mode') or 'single'))}\n\n"
        f"{_copy(lang, 'Набор', 'Set')}: {_vahaduo_source_set_label(source_label, lang=lang)}\n\n"
        f"{_copy(lang, 'Выберите источники модели.', 'Choose model sources.')}\n\n"
        f"{_copy(lang, 'Выбрано', 'Selected')}:\n{chosen}"
    )


def _vahaduo_saved_group_state(state: dict[str, object]) -> tuple[list[dict[str, object]], list[int]]:
    groups = [dict(item) for item in list(state.get("saved_source_groups") or []) if isinstance(item, dict)]
    raw_selected = list(state.get("saved_group_selected") or [])
    selected: list[int] = []
    for value in raw_selected:
        try:
            index = int(value)
        except (TypeError, ValueError):
            continue
        if 0 <= index < len(groups) and index not in selected:
            selected.append(index)
    return groups, selected


def _build_g25vahaduo_saved_keyboard(
    items: list[dict[str, object]],
    *,
    delete_mode: bool = False,
    back_action: str | None = None,
    include_upload: bool = False,
    lang: str = "ru",
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for item in items:
        title = str(item.get("title") or "source")
        count = int(item.get("source_count") or 0)
        source_id = int(item.get("id") or 0)
        action = "vahaduo_delete" if delete_mode else "vahaduo_saved_select"
        rows.append([
            InlineKeyboardButton(
                f"{title} · {count}",
                callback_data=f"{G25MENU_CALLBACK_PREFIX}:{action}:{source_id}",
            )
        ])
    if include_upload and not delete_mode:
        rows.append([InlineKeyboardButton(_copy(lang, "Загрузить source файлом", "Upload source file"), callback_data=f"{G25MENU_CALLBACK_PREFIX}:vahaduo_source_file")])
    if back_action is None:
        back_action = "vahaduo_saved" if delete_mode else "vahaduo_data"
    rows.append([
        InlineKeyboardButton(_back_label(lang), callback_data=f"{G25MENU_CALLBACK_PREFIX}:{back_action}"),
        InlineKeyboardButton(_cancel_label(lang), callback_data=f"{G25MENU_CALLBACK_PREFIX}:cancel"),
    ])
    return InlineKeyboardMarkup(rows)


def _g25vahaduo_saved_text(items: list[dict[str, object]], mode: str, *, delete_mode: bool = False, lang: str = "ru") -> str:
    if not items:
        return f"\U0001F9EC Vahaduo Lab\n\n{_copy(lang, 'Режим', 'Mode')}: {_vahaduo_mode_label(mode)}\n\n{_copy(lang, 'У вас пока нет сохраненных наборов для этого режима.', 'You do not have saved sets for this mode yet.')}"
    if delete_mode:
        return f"\U0001F9EC Vahaduo Lab\n\n{_copy(lang, 'Режим', 'Mode')}: {_vahaduo_mode_label(mode)}\n\n{_copy(lang, 'Выберите набор, который нужно удалить:', 'Choose the set to delete:')}"
    return f"\U0001F9EC Vahaduo Lab\n\n{_copy(lang, 'Режим', 'Mode')}: {_vahaduo_mode_label(mode)}\n\n{_copy(lang, 'Ваши сохраненные SOURCE-наборы:', 'Your saved SOURCE sets:')}"


def _build_g25vahaduo_target_library_keyboard(*, for_run: bool = False, lang: str = "ru") -> InlineKeyboardMarkup:
    samples_action = "vahaduo_targets_samples_for_run" if for_run else "vahaduo_targets_samples"
    other_action = "vahaduo_targets_other_for_run" if for_run else "vahaduo_targets_other"
    back_action = "vahaduo_target" if for_run else "vahaduo_data"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🧬 Samples", callback_data=f"{G25MENU_CALLBACK_PREFIX}:{samples_action}")],
        [InlineKeyboardButton(_copy(lang, "📍 G25-профили", "📍 G25 profiles"), callback_data=f"{G25MENU_CALLBACK_PREFIX}:{other_action}")],
        [
            InlineKeyboardButton(_copy(lang, "⬅️ Назад", "⬅️ Back"), callback_data=f"{G25MENU_CALLBACK_PREFIX}:{back_action}"),
            InlineKeyboardButton(_cancel_label(lang), callback_data=f"{G25MENU_CALLBACK_PREFIX}:cancel"),
        ],
    ])


def _g25vahaduo_target_library_text(
    *,
    for_run: bool = False,
    state: dict[str, object] | None = None,
    lang: str = "ru",
) -> str:
    if for_run:
        current_state = state or {}
        mode = str(current_state.get("mode") or "distance")
        return (
            f"{_vahaduo_mode_title(mode)}\n\n"
            f"{chr(10).join(_vahaduo_model_context_lines(current_state, lang=lang))}\n\n"
            f"{_copy(lang, 'Выберите G25-профили.', 'Choose G25 profiles.') if mode == 'multi' else _copy(lang, 'Выберите G25-профиль.', 'Choose a G25 profile.')}"
        )
    return f"<b>{_copy(lang, '📍 G25-профили', '📍 G25 profiles')}</b>\n\n{_copy(lang, 'Выберите раздел G25-профилей.', 'Choose a G25 profile section.')}"


def _build_g25vahaduo_targets_keyboard(
    items: list[dict[str, object]],
    *,
    for_run: bool = False,
    delete_mode: bool = False,
    source: str = "other",
    lang: str = "ru",
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for index, item in enumerate(items):
        title = str(item.get("title") or "target")
        token = str(item.get("callback_id") or index)
        callback_data = _target_item_callback_data(item, token, for_run=for_run, delete_mode=delete_mode, source=source)
        rows.append([
            InlineKeyboardButton(
                f"{index + 1}. {title}",
                callback_data=callback_data,
            )
        ])
    if source != "samples" and not for_run and not delete_mode:
        rows.append([InlineKeyboardButton(_copy(lang, "Добавить target", "Add target"), callback_data=f"{G25MENU_CALLBACK_PREFIX}:vahaduo_target_text")])
    back_action = "vahaduo_targets_other" if delete_mode else ("vahaduo_targets_for_run" if for_run else "vahaduo_targets")
    rows.append([
        InlineKeyboardButton(_copy(lang, "⬅️ Назад", "⬅️ Back"), callback_data=f"{G25MENU_CALLBACK_PREFIX}:{back_action}"),
        InlineKeyboardButton(_cancel_label(lang), callback_data=f"{G25MENU_CALLBACK_PREFIX}:cancel"),
    ])
    return InlineKeyboardMarkup(rows)


def _target_item_callback_data(
    item: dict[str, object],
    token: str,
    *,
    for_run: bool,
    delete_mode: bool,
    source: str,
) -> str:
    target_id = str(item.get("id") or "")
    if target_id:
        if delete_mode:
            direct_action = "vmod"
        elif source == "samples":
            direct_action = "vmsr" if for_run else "vms"
        else:
            direct_action = "vmor" if for_run else "vmo"
        direct_callback = f"{G25MENU_CALLBACK_PREFIX}:{direct_action}:{target_id}"
        if len(direct_callback.encode("utf-8")) <= 64:
            return direct_callback

    if delete_mode:
        action = "vahaduo_target_delete_pick"
    else:
        action = "vahaduo_target_pick_run" if for_run else "vahaduo_target_pick"
    return f"{G25MENU_CALLBACK_PREFIX}:{action}:{token}"


def _g25vahaduo_targets_text(
    items: list[dict[str, object]],
    *,
    for_run: bool = False,
    delete_mode: bool = False,
    source: str = "other",
    state: dict[str, object] | None = None,
    lang: str = "ru",
) -> str:
    section = _vahaduo_target_section_label(source, lang=lang)
    if for_run:
        current_state = state or {}
        mode = str(current_state.get("mode") or "distance")
        if not items:
            tail = _copy(lang, "В этом разделе пока нет G25-профилей.", "There are no G25 profiles in this section yet.")
        else:
            tail = _copy(lang, "Выберите G25-профиль.", "Choose a G25 profile.")
        return (
            f"{_vahaduo_mode_title(mode)}\n\n"
            f"{chr(10).join(_vahaduo_model_context_lines(current_state, lang=lang))}\n"
            f"{section}\n\n"
            f"{tail}"
        )
    if not items:
        tail = _copy(lang, "В этом разделе пока нет G25-координат.", "There are no G25 coordinates in this section yet.")
        return f"<b>🧪 Vahaduo Lab</b>\n\n<b>🧬 {_my_g25_label(lang)}</b>\n\n<b>{section}</b>\n\n{tail}"
    if delete_mode:
        return f"<b>🧪 Vahaduo Lab</b>\n\n<b>🧬 {_my_g25_label(lang)}</b>\n\n<b>{_vahaduo_target_section_label('other', lang=lang)}</b>\n\n{_copy(lang, 'Выберите G25-профиль для удаления:', 'Choose the G25 profile to delete:')}"
    return f"<b>🧪 Vahaduo Lab</b>\n\n<b>🧬 {_my_g25_label(lang)}</b>\n\n<b>{section}</b>\n\n{_copy(lang, 'Выберите G25-профиль:', 'Choose a G25 profile:')}"


def _vahaduo_multi_target_selection(state: dict[str, object], items: list[dict[str, object]]) -> list[str]:
    valid_ids = {str(item.get("id") or "") for item in items}
    selected: list[str] = []
    for value in list(state.get("multi_target_selected") or []):
        target_id = str(value)
        if target_id in valid_ids and target_id not in selected:
            selected.append(target_id)
    return selected


def _build_g25vahaduo_multi_targets_keyboard(
    items: list[dict[str, object]],
    selected_ids: list[str],
    *,
    back_action: str = "vahaduo_targets_for_run",
    lang: str = "ru",
) -> InlineKeyboardMarkup:
    selected_set = set(selected_ids)
    rows: list[list[InlineKeyboardButton]] = []
    for index, item in enumerate(items):
        target_id = str(item.get("id") or "")
        token = str(item.get("callback_id") or index)
        title = str(item.get("title") or "target")
        checked = "[x] " if target_id in selected_set else ""
        rows.append([
            InlineKeyboardButton(
                f"{checked}{index + 1}. {title}",
                callback_data=f"{G25MENU_CALLBACK_PREFIX}:vahaduo_multi_target_toggle:{token}",
            )
        ])
    rows.append([InlineKeyboardButton(_all_label(lang), callback_data=f"{G25MENU_CALLBACK_PREFIX}:vahaduo_multi_target_all")])
    rows.append([
        InlineKeyboardButton(_done_label(lang), callback_data=f"{G25MENU_CALLBACK_PREFIX}:vahaduo_multi_target_done"),
        InlineKeyboardButton(_clear_label(lang), callback_data=f"{G25MENU_CALLBACK_PREFIX}:vahaduo_multi_target_clear"),
    ])
    rows.append([
        InlineKeyboardButton(_copy(lang, "⬅️ Назад", "⬅️ Back"), callback_data=f"{G25MENU_CALLBACK_PREFIX}:{back_action}"),
        InlineKeyboardButton(_cancel_label(lang), callback_data=f"{G25MENU_CALLBACK_PREFIX}:cancel"),
    ])
    return InlineKeyboardMarkup(rows)


def _g25vahaduo_multi_targets_text(
    items: list[dict[str, object]],
    selected_ids: list[str],
    *,
    state: dict[str, object] | None = None,
    source: str = "other",
    lang: str = "ru",
) -> str:
    current_state = state or {}
    mode = str(current_state.get("mode") or "multi")
    section = _vahaduo_target_section_label(source, lang=lang)
    if not items:
        return (
            f"{_vahaduo_mode_title(mode)}\n\n"
            f"{chr(10).join(_vahaduo_model_context_lines(current_state, lang=lang))}\n"
            f"{section}\n\n"
            f"{_copy(lang, 'В этом разделе пока нет G25-профилей.', 'There are no G25 profiles in this section yet.')}"
        )
    return (
        f"{_vahaduo_mode_title(mode)}\n\n"
        f"{chr(10).join(_vahaduo_model_context_lines(current_state, lang=lang))}\n"
        f"{section}\n\n"
        f"{_copy(lang, 'Выберите G25-профили.', 'Choose G25 profiles.')}\n\n"
        f"{_copy(lang, 'Выбрано', 'Selected')}: {len(selected_ids)} {_copy(lang, 'профилей', 'profiles')}"
    )


def _build_g25vahaduo_target_add_keyboard(*, lang: str = "ru") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(_copy(lang, "Вставить target текстом", "Paste target as text"), callback_data=f"{G25MENU_CALLBACK_PREFIX}:vahaduo_target_text"),
        ],
        [
            InlineKeyboardButton(_back_label(lang), callback_data=f"{G25MENU_CALLBACK_PREFIX}:vahaduo_targets"),
            InlineKeyboardButton(_cancel_label(lang), callback_data=f"{G25MENU_CALLBACK_PREFIX}:cancel"),
        ],
    ])


def _g25vahaduo_target_add_text(*, lang: str = "ru") -> str:
    return (
        "\U0001F9EC Vahaduo Lab\n\n"
        f"{_copy(lang, 'Мои target-координаты', 'My target coordinates')}\n\n"
        f"{_copy(lang, 'Добавьте индивидуальные G25 координаты. После проверки их можно сохранить и выбирать в расчетах.', 'Add individual G25 coordinates. After validation, you can save them and use them in calculations.')}"
    )


def _build_g25vahaduo_target_input_keyboard(*, lang: str = "ru") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(_back_label(lang), callback_data=f"{G25MENU_CALLBACK_PREFIX}:vahaduo_targets"),
            InlineKeyboardButton(_cancel_label(lang), callback_data=f"{G25MENU_CALLBACK_PREFIX}:cancel"),
        ],
    ])


def _g25vahaduo_target_input_text(input_mode: str, *, lang: str = "ru") -> str:
    if input_mode == "file":
        hint = _copy(lang, "Отправьте target G25 файлом.\nЕсли G25 еще нет, можно отправить raw-файл.", "Send the target G25 as a file.\nIf you do not have G25 yet, you can send a raw file.")
    else:
        hint = _copy(lang, "Вставьте target G25 текстом: имя и 25 координат.", "Paste the target G25 as text: name and 25 coordinates.")
    return (
        "\U0001F9EC Vahaduo Lab\n\n"
        f"{hint}\n\n"
        f"{_copy(lang, 'В группе отправьте файл или текст ответом на это сообщение.', 'In a group, send the file or text as a reply to this message.')}\n\n"
        f"{_copy(lang, 'Формат строки:', 'Line format:')}\n"
        "Name,0.0123,...,0.0456"
    )


def _build_g25vahaduo_run_target_input_keyboard(*, lang: str = "ru") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(_back_label(lang), callback_data=f"{G25MENU_CALLBACK_PREFIX}:vahaduo_target"),
            InlineKeyboardButton(_cancel_label(lang), callback_data=f"{G25MENU_CALLBACK_PREFIX}:cancel"),
        ],
    ])


def _g25vahaduo_run_target_input_text(input_mode: str, mode: str, *, lang: str = "ru") -> str:
    if mode == "multi":
        if input_mode == "file":
            hint = _copy(lang, "Отправьте target G25 файлом: txt/csv с одной или несколькими строками.", "Send target G25 as a file: txt/csv with one or more rows.")
        else:
            hint = _copy(lang, "Вставьте один или несколько target строками G25: имя и 25 координат.", "Paste one or more target G25 rows: name and 25 coordinates.")
    else:
        if input_mode == "file":
            hint = _copy(lang, "Отправьте target G25 файлом.\nЕсли G25 еще нет, можно отправить raw-файл.", "Send the target G25 as a file.\nIf you do not have G25 yet, you can send a raw file.")
        else:
            hint = _copy(lang, "Вставьте target G25 текстом: имя и 25 координат.", "Paste the target G25 as text: name and 25 coordinates.")
    return (
        "\U0001F9EC Vahaduo Lab\n\n"
        f"{hint}\n\n"
        f"{_copy(lang, 'В группе отправьте файл или текст ответом на это сообщение.', 'In a group, send the file or text as a reply to this message.')}\n\n"
        f"{_copy(lang, 'Формат строки:', 'Line format:')}\n"
        "Name,0.0123,...,0.0456"
    )


def _build_g25vahaduo_data_target_keyboard(state: dict[str, object], *, lang: str = "ru") -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    read_only = bool(state.get("target_readonly"))
    saved_id = int(state.get("target_saved_id") or 0)
    if saved_id and not read_only:
        rows.append([InlineKeyboardButton(_copy(lang, "Удалить target", "Delete target"), callback_data=f"{G25MENU_CALLBACK_PREFIX}:vahaduo_target_delete:{saved_id}")])
    coordinate_id = str(state.get("target_coordinate_id") or "")
    if coordinate_id and not read_only:
        rows.append([InlineKeyboardButton(_copy(lang, "Удалить target", "Delete target"), callback_data=f"{G25MENU_CALLBACK_PREFIX}:vahaduo_mydata_target_delete:{coordinate_id}")])
    rows.append([
        InlineKeyboardButton(_back_label(lang), callback_data=f"{G25MENU_CALLBACK_PREFIX}:vahaduo_targets"),
        InlineKeyboardButton(_cancel_label(lang), callback_data=f"{G25MENU_CALLBACK_PREFIX}:cancel"),
    ])
    return InlineKeyboardMarkup(rows)


def _g25vahaduo_data_target_text(state: dict[str, object], prefix: str = "", *, lang: str = "ru") -> str:
    target_label = str(state.get("target_label") or "target")
    target_line = str(state.get("target_line") or "")
    target_path_value = str(state.get("target_path") or "")
    if not target_line and target_path_value:
        try:
            target_lines = [
                line.strip()
                for line in Path(target_path_value).read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            target_line = target_lines[0] if target_lines else ""
        except OSError:
            logger.debug("Failed to read saved Vahaduo target line", exc_info=True)

    lines = [
        "\U0001F9EC Vahaduo Lab",
        "",
        _copy(lang, "Мои target-координаты", "My target coordinates"),
        "",
    ]
    if prefix:
        lines.extend([html.escape(prefix), ""])
    lines.extend([
        f"TARGET: {html.escape(target_label)}",
        "",
    ])
    if target_line:
        lines.extend([
            _copy(lang, "Координаты:", "Coordinates:"),
            f"<code>{html.escape(target_line)}</code>",
            "",
        ])
    else:
        lines.extend([
            _copy(lang, "Координаты: файл не найден.", "Coordinates: file not found."),
            "",
        ])
    lines.extend([
        _copy(lang, "Этот target можно сохранить или выбрать из списка для Distance и Single.", "You can save this target or choose it from the list for Distance and Single."),
    ])
    return "\n".join(lines)


def _build_g25vahaduo_target_save_name_keyboard(*, lang: str = "ru") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(_back_label(lang), callback_data=f"{G25MENU_CALLBACK_PREFIX}:vahaduo_data_target"),
            InlineKeyboardButton(_cancel_label(lang), callback_data=f"{G25MENU_CALLBACK_PREFIX}:cancel"),
        ],
    ])


def _g25vahaduo_target_save_name_text(state: dict[str, object], *, lang: str = "ru") -> str:
    target_label = str(state.get("target_label") or "target")
    return (
        "\U0001F9EC Vahaduo Lab\n\n"
        f"TARGET: {target_label}\n\n"
        f"{_copy(lang, 'Введите название, под которым сохранить target.', 'Enter the name to save this target under.')}"
    )


def _build_g25vahaduo_target_delete_confirm_keyboard(target_id: int, back_action: str = "vahaduo_targets", *, lang: str = "ru") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(_copy(lang, "Удалить", "Delete"), callback_data=f"{G25MENU_CALLBACK_PREFIX}:vahaduo_target_delete_confirm:{target_id}"),
            InlineKeyboardButton(_back_label(lang), callback_data=f"{G25MENU_CALLBACK_PREFIX}:{back_action}"),
        ],
        [
            InlineKeyboardButton(_cancel_label(lang), callback_data=f"{G25MENU_CALLBACK_PREFIX}:cancel"),
        ],
    ])


def _build_g25vahaduo_mydata_target_delete_confirm_keyboard(target_id: str, back_action: str = "vahaduo_targets", *, lang: str = "ru") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(_copy(lang, "Удалить", "Delete"), callback_data=f"{G25MENU_CALLBACK_PREFIX}:vahaduo_mydata_target_delete_confirm:{target_id}"),
            InlineKeyboardButton(_back_label(lang), callback_data=f"{G25MENU_CALLBACK_PREFIX}:{back_action}"),
        ],
        [
            InlineKeyboardButton(_cancel_label(lang), callback_data=f"{G25MENU_CALLBACK_PREFIX}:cancel"),
        ],
    ])


def _g25vahaduo_target_delete_confirm_text(item: dict[str, object], *, lang: str = "ru") -> str:
    title = str(item.get("title") or "target")
    target_name = str(item.get("target_name") or title)
    return (
        "\U0001F9EC Vahaduo Lab\n\n"
        f"{_copy(lang, 'Удалить target', 'Delete target')} «{title}»?\n"
        f"TARGET: {target_name}"
    )


def _build_g25vahaduo_delete_confirm_keyboard(source_id: int, back_action: str = "vahaduo_saved", *, lang: str = "ru") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(_copy(lang, "Удалить", "Delete"), callback_data=f"{G25MENU_CALLBACK_PREFIX}:vahaduo_delete_confirm:{source_id}"),
            InlineKeyboardButton(_back_label(lang), callback_data=f"{G25MENU_CALLBACK_PREFIX}:{back_action}"),
        ],
        [
            InlineKeyboardButton(_cancel_label(lang), callback_data=f"{G25MENU_CALLBACK_PREFIX}:cancel"),
        ],
    ])


def _g25vahaduo_delete_confirm_text(item: dict[str, object], *, lang: str = "ru") -> str:
    title = str(item.get("title") or "source")
    count = int(item.get("source_count") or 0)
    return (
        "\U0001F9EC Vahaduo Lab\n\n"
        f"{_copy(lang, 'Удалить набор', 'Delete set')} «{title}»?\n"
        f"{_copy(lang, 'Популяций', 'Populations')}: {count}"
    )


def _build_g25vahaduo_source_input_keyboard(*, lang: str = "ru") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(_back_label(lang), callback_data=f"{G25MENU_CALLBACK_PREFIX}:vahaduo_saved"),
            InlineKeyboardButton(_cancel_label(lang), callback_data=f"{G25MENU_CALLBACK_PREFIX}:cancel"),
        ],
    ])


def _g25vahaduo_source_input_text(input_mode: str, *, lang: str = "ru") -> str:
    if input_mode == "file":
        hint = _copy(lang, "Пришлите txt/csv-файл со строками G25. Название файла станет названием source-набора.", "Send a txt/csv file with G25 rows. The file name will become the source set name.")
    else:
        hint = _copy(lang, "Вставьте source текстом: каждая строка - название и 25 координат.", "Paste the source as text: each row is a name and 25 coordinates.")
    return (
        "\U0001F9EC Vahaduo Lab\n\n"
        f"{hint}\n\n"
        f"{_copy(lang, 'Формат строки:', 'Line format:')}\n"
        "Population,0.0123,...,0.0456"
    )


def _g25vahaduo_target_back_action(state: dict[str, object]) -> str:
    action = str(state.get("target_back") or "vahaduo_sources")
    if action.startswith("vahaduo_single_components:"):
        return action
    if action in {
        "vahaduo_presets",
        "vahaduo_saved",
        "vahaduo_sources",
        "vahaduo_data",
        "vahaduo_data_menu",
        "vahaduo_saved_components",
        "vahaduo_source_file",
        "vahaduo_source_text",
    }:
        return action
    return "vahaduo_sources"


def _build_g25vahaduo_target_keyboard(state: dict[str, object], *, lang: str = "ru") -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    rows.append([InlineKeyboardButton(_copy(lang, "📍 G25-профили", "📍 G25 profiles"), callback_data=f"{G25MENU_CALLBACK_PREFIX}:vahaduo_targets_for_run")])
    input_mode = str(state.get("source_input_mode") or "")
    saved_id = int(state.get("source_saved_id") or 0)
    if input_mode in {"source-text", "source-file"} and not saved_id:
        rows.append([InlineKeyboardButton(_copy(lang, "Сохранить source", "Save source"), callback_data=f"{G25MENU_CALLBACK_PREFIX}:vahaduo_save_source")])
    rows.append([
        InlineKeyboardButton(_copy(lang, "⬅️ Назад", "⬅️ Back"), callback_data=f"{G25MENU_CALLBACK_PREFIX}:{_g25vahaduo_target_back_action(state)}"),
        InlineKeyboardButton(_cancel_label(lang), callback_data=f"{G25MENU_CALLBACK_PREFIX}:cancel"),
    ])
    return InlineKeyboardMarkup(rows)


def _g25vahaduo_target_text(state: dict[str, object], *, lang: str = "ru") -> str:
    mode = str(state.get("mode") or "distance")
    return (
        f"{_vahaduo_mode_title(mode)}\n\n"
        f"{chr(10).join(_vahaduo_model_context_lines(state, include_count=True, lang=lang))}\n"
        "\n"
        f"{_copy(lang, 'Отправьте G25 текстом или файлом.', 'Send G25 as text or a file.')}\n"
        f"{_copy(lang, 'Или выберите сохранённый профиль.', 'Or choose a saved profile.')}"
    )


def _g25vahaduo_distance_result_caption(state: dict[str, object], target_name: str | None = None, *, lang: str = "ru") -> str:
    clean_target = (target_name or "").strip() or _copy(lang, "введён вручную", "entered manually")
    source_label = _vahaduo_source_display_label(state, lang=lang)
    return (
        "📏 Distance\n\n"
        f"{_copy(lang, 'G25-профиль', 'G25 profile')}: {clean_target}\n"
        f"{_copy(lang, 'Источник', 'Source')}: {source_label}"
    )


def _g25vahaduo_single_result_caption(state: dict[str, object], result, *, lang: str = "ru") -> str:
    target_name = str(getattr(result, "target_name", "") or "").strip() or _copy(lang, "введён вручную", "entered manually")
    panel_label = str(getattr(result, "panel_name", "") or str(state.get("source_label") or "").split(":", 1)[0]).strip()
    lines = [
        f"Source: {_vahaduo_source_set_label(panel_label, lang=lang)}",
        f"Target: {target_name}",
        f"Distance: {float(getattr(result, 'distance', 0.0) or 0.0) * 100:.4f}% / {float(getattr(result, 'distance', 0.0) or 0.0):.6f}",
        (
            f"Sources: {int(getattr(result, 'sources', 0) or 0)} | "
            f"Cycles: {int(getattr(result, 'iterations', 0) or 0)} | "
            f"Time: {float(getattr(result, 'elapsed_seconds', 0.0) or 0.0):.3f} s"
        ),
        "",
    ]
    for name, weight in list(getattr(result, "groups", []) or []):
        percent = float(weight) * 100.0
        emoji = _vahaduo_result_component_emoji(str(name))
        prefix = f"{emoji} " if emoji else ""
        lines.append(f"{prefix}{percent:.1f}%  {display_name(str(name))}")
    return "\n".join(lines).rstrip()


def _g25vahaduo_multi_result_caption(state: dict[str, object], result, *, lang: str = "ru") -> str:
    panel_label = str(getattr(result, "panel_name", "") or str(state.get("source_label") or "").split(":", 1)[0]).strip()
    return "\n".join([
        f"Source: {_vahaduo_source_set_label(panel_label, lang=lang)}",
        f"Targets: {int(getattr(result, 'target_count', 0) or 0)}",
        (
            "Average distance: "
            f"{float(getattr(result, 'average_distance', 0.0) or 0.0) * 100:.4f}% / "
            f"{float(getattr(result, 'average_distance', 0.0) or 0.0):.7f}"
        ),
        (
            f"Sources: {int(getattr(result, 'sources', 0) or 0)} | "
            f"Cycles: {int(getattr(result, 'iterations', 0) or 0)} | "
            f"Time: {float(getattr(result, 'elapsed_seconds', 0.0) or 0.0):.3f} s"
        ),
    ])


def _build_g25vahaduo_distance_result_keyboard(*, lang: str = "ru") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(_copy(lang, "⬅️ Назад", "⬅️ Back"), callback_data=f"{G25MENU_CALLBACK_PREFIX}:vahaduo_result_back"),
        InlineKeyboardButton(_cancel_label(lang), callback_data=f"{G25MENU_CALLBACK_PREFIX}:cancel"),
    ]])


def _build_g25vahaduo_single_result_keyboard(*, lang: str = "ru") -> InlineKeyboardMarkup:
    return _build_g25vahaduo_distance_result_keyboard(lang=lang)


def _build_g25vahaduo_multi_result_keyboard(*, lang: str = "ru") -> InlineKeyboardMarkup:
    return _build_g25vahaduo_distance_result_keyboard(lang=lang)


def _build_g25vahaduo_save_name_keyboard(state: dict[str, object] | None = None, *, lang: str = "ru") -> InlineKeyboardMarkup:
    back_action = "vahaduo_data_source" if _is_vahaduo_data_only(state) else "vahaduo_target"
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(_back_label(lang), callback_data=f"{G25MENU_CALLBACK_PREFIX}:{back_action}"),
            InlineKeyboardButton(_cancel_label(lang), callback_data=f"{G25MENU_CALLBACK_PREFIX}:cancel"),
        ],
    ])


def _g25vahaduo_save_name_text(state: dict[str, object], *, lang: str = "ru") -> str:
    source_label = str(state.get("source_label") or "source")
    source_count = int(state.get("source_count") or 0)
    return (
        "\U0001F9EC Vahaduo Lab\n\n"
        f"SOURCE: {source_label}\n"
        f"{_copy(lang, 'Популяций', 'Populations')}: {source_count}\n\n"
        f"{_copy(lang, 'Введите название, под которым сохранить набор.', 'Enter the name to save this set under.')}"
    )
