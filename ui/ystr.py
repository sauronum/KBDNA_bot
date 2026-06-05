from __future__ import annotations

import html
import re

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from features.ystr import ystr_panel_label


def _normalize_subclade_key(value: str) -> str:
    return " ".join(str(value or "").strip().upper().split())


def is_placeholder(value: str) -> bool:
    stripped = str(value or "").strip()
    if not stripped:
        return True
    return bool(re.fullmatch(r"[-–—_~.\s]+", stripped))


def format_ystr_haplo(entry: dict[str, object]) -> str:
    general = str(entry.get("display_general") or entry.get("general") or entry.get("haplo") or "").strip()
    subclade = str(entry.get("display_subclade") or "").strip()
    if subclade and _normalize_subclade_key(subclade) != _normalize_subclade_key(general):
        return f"{general}-{subclade}"
    return general or str(entry.get("haplo") or "")


def format_ystr_entry_button(entry: dict[str, object]) -> str:
    name = str(entry.get("name") or "")
    haplo = format_ystr_haplo(entry)
    marker_count = int(entry.get("marker_count") or 0)
    panel = ystr_panel_label(marker_count)
    return f"{name} · {haplo} · {panel}"


def format_ystr_entry_line(entry: dict[str, object]) -> str:
    name = html.escape(str(entry.get("name") or ""))
    haplo = html.escape(format_ystr_haplo(entry))
    ancestor = str(entry.get("ancestor") or "").strip()
    marker_count = int(entry.get("marker_count") or 0)
    panel = ystr_panel_label(marker_count)
    line = f"<b>{name}</b>"
    if haplo:
        line += f" · {haplo}"
    line += f" · STR: {panel}"
    if ancestor and not is_placeholder(ancestor):
        line += f"\n{html.escape(ancestor)}"
    return line


def format_ystr_marker_values(entry: dict[str, object], *, limit: int | None = None) -> tuple[str, bool]:
    markers = entry.get("markers") if isinstance(entry.get("markers"), dict) else {}
    items = list(markers.items())
    has_more = limit is not None and len(items) > limit
    if limit is not None:
        items = items[:limit]
    lines = [
        f"{html.escape(str(marker))}: {html.escape('-'.join(str(part) for part in value))}"
        for marker, value in items
    ]
    return "\n".join(lines), has_more


def format_ystr_test_data_text(entry: dict[str, object], *, show_all: bool = False) -> str:
    marker_count = int(entry.get("marker_count") or 0)
    limit = None if show_all or marker_count <= 37 else 37
    marker_text, has_more = format_ystr_marker_values(entry, limit=limit)
    source = str(entry.get("source") or "").strip()
    country = str(entry.get("country") or "").strip()
    lines = [
        "🧬 <b>Y-STR · данные теста</b>",
        "",
        format_ystr_entry_line(entry),
    ]
    meta: list[str] = []
    if country and not is_placeholder(country):
        meta.append(f"Страна: {html.escape(country)}")
    if source and not is_placeholder(source):
        meta.append(f"Источник: {html.escape(source)}")
    meta.append(f"Маркеров: {marker_count}")
    lines.extend(["", "\n".join(meta), "", "<b>Маркеры:</b>"])
    if marker_text:
        lines.append(f"<blockquote>{marker_text}</blockquote>")
    else:
        lines.append("Нет заполненных STR-маркеров.")
    if has_more:
        lines.append(f"<i>Показаны первые 37 из {marker_count}.</i>")
    return "\n".join(lines)


def format_ystr_uploaded_summary_text(entry: dict[str, object]) -> str:
    marker_count = int(entry.get("marker_count") or 0)
    panel = ystr_panel_label(marker_count)
    return (
        "🧬 <b>Y-STR · загруженные маркеры</b>\n\n"
        f"Распознано маркеров: <b>{marker_count}</b>\n"
        f"Уровень: <b>{html.escape(panel)}</b>\n\n"
        "Что сделать?"
    )


def estimate_ystr_generations(genetic_distance: int, common_markers: int) -> str:
    if common_markers < 50:
        return ""
    if genetic_distance <= 0:
        return "до ~6 поколений" if common_markers >= 80 else "до ~8 поколений"

    # Широкий STR-ориентир: скорость мутаций отличается по маркерам, возможны обратные мутации.
    average_mutation_rate = 0.0038
    center = genetic_distance / max(2 * common_markers * average_mutation_rate, 0.001)
    if common_markers >= 80:
        low_factor, high_factor = 0.65, 1.75
    else:
        low_factor, high_factor = 0.70, 1.95
    low = max(1, int(round(center * low_factor)))
    high = max(low + 1, int(round(center * high_factor)))
    if high - low < 4:
        high = low + 4
    return f"~{low}-{high} поколений"


def format_ystr_comparison_text(left: dict[str, object], right: dict[str, object], comparison: dict[str, object]) -> str:
    common = int(comparison.get("common") or 0)
    gd = int(comparison.get("gd") or 0)
    differences = comparison.get("differences") if isinstance(comparison.get("differences"), list) else []
    matched = max(common - len(differences), 0)
    panel = html.escape(str(comparison.get("panel") or common))
    closeness = str(comparison.get("closeness") or "")
    generations = estimate_ystr_generations(gd, common)

    lines = [
        "🧬 <b>Y-STR · сравнение</b>",
        "",
        "<b>Первая запись:</b>",
        format_ystr_entry_line(left),
        "",
        "<b>Вторая запись:</b>",
        format_ystr_entry_line(right),
        "",
        "<b>Итог:</b>",
        f"Уровень: {panel} маркеров",
        f"Общих STR-полей: {common}",
        f"Совпало: {matched}/{common}",
        f"Отличающихся STR-полей: {len(differences)}",
        f"Генетическая дистанция: {gd}",
    ]
    if common >= 20 and closeness and closeness != "мало данных":
        lines.append(f"Оценка: {html.escape(closeness)}")
    if generations:
        lines.append(f"Ориентир: {html.escape(generations)}")
    elif common >= 30:
        lines.append("Ориентир: для поколений лучше 67+ общих маркеров")
    if differences:
        lines.extend(["", "<b>Отличающиеся маркеры:</b>"])
        visible_differences = differences[:15]
        marker_width = max([6] + [len(str(item.get("marker") or "")) for item in visible_differences])
        left_width = max([8] + [len(str(item.get("left") or "")) for item in visible_differences])
        right_width = max([8] + [len(str(item.get("right") or "")) for item in visible_differences])
        table_lines = [
            f"{'Маркер'.ljust(marker_width)}  {'Запись 1'.ljust(left_width)}  {'Запись 2'.ljust(right_width)}"
        ]
        for item in visible_differences:
            marker = str(item.get("marker") or "")
            left_value = str(item.get("left") or "")
            right_value = str(item.get("right") or "")
            table_lines.append(
                f"{marker.ljust(marker_width)}  {left_value.ljust(left_width)}  {right_value.ljust(right_width)}"
            )
        lines.append(f"<pre>{html.escape(chr(10).join(table_lines))}</pre>")
        if len(differences) > 15:
            lines.append(f"<i>Показаны первые 15 отличий из {len(differences)}.</i>")
    else:
        lines.extend(["", "Отличий по общим маркерам нет."])

    footer = "Чем больше общих маркеров, тем надежнее сравнение."
    if generations:
        footer += " Поколения — приблизительный STR-ориентир."
    lines.extend(["", f"<i>{footer}</i>"])
    return "\n".join(lines)


def format_ystr_matches_text(query_entry: dict[str, object], matches: list[dict[str, object]]) -> str:
    lines = [
        "🧬 <b>Y-STR анализ</b>",
        "",
        "<b>Исходная запись:</b>",
        format_ystr_entry_line(query_entry),
        "",
    ]
    if not matches:
        lines.append("Близких совпадений с достаточным числом общих маркеров не найдено.")
        return "\n".join(lines)

    lines.append("<b>Ближайшие совпадения:</b>")
    display_matches = [
        item
        for item in matches
        if str(item["comparison"].get("closeness") or "") != "далеко"
    ] or matches[:3]
    grouped: dict[str, list[dict[str, object]]] = {}
    for item in display_matches:
        panel = str(item["comparison"].get("panel") or "")
        grouped.setdefault(panel, []).append(item)

    def panel_sort_key(panel: str) -> int:
        order = {"102/111": 0, "67": 1, "37": 2, "25": 3, "12": 4}
        return order.get(panel, 99)

    shown = 0
    has_generation_estimate = False
    for panel in sorted(grouped, key=panel_sort_key):
        items = grouped[panel][:5]
        if not items:
            continue
        lines.extend(["", f"<b>{html.escape(panel)} маркеров</b>"])
        for index, item in enumerate(items, 1):
            entry = item["entry"]
            comparison = item["comparison"]
            name = html.escape(str(entry.get("name") or ""))
            haplo = html.escape(format_ystr_haplo(entry))
            ancestor = str(entry.get("ancestor") or "").strip()
            gd = int(comparison.get("gd") or 0)
            common = int(comparison.get("common") or 0)
            differences = comparison.get("differences") if isinstance(comparison.get("differences"), list) else []
            matched = max(common - len(differences), 0)
            closeness = html.escape(str(comparison.get("closeness") or ""))
            generations = estimate_ystr_generations(gd, common)
            line = f"{index}. <b>{name}</b>"
            if haplo:
                line += f" · {haplo}"
            if ancestor and not is_placeholder(ancestor):
                line += f"\n{html.escape(ancestor)}"
            line += f"\n{matched}/{common} совпало"
            if common >= 20 and closeness and closeness != "мало данных":
                line += f" · {closeness}"
            if generations:
                line += f"\n{html.escape(generations)}"
                has_generation_estimate = True
            lines.append(line)
            shown += 1
        if shown >= 10:
            break

    footer = "Чем больше общих маркеров, тем надежнее сравнение."
    if has_generation_estimate:
        footer += " Поколения — приблизительный STR-ориентир."
    lines.extend(["", f"<i>{footer}</i>"])
    return "\n".join(lines)


def build_ystr_root_keyboard(callback_prefix: str, back_callback: str | None = None) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("Найти ближайших", callback_data=f"{callback_prefix}:nearest")],
        [InlineKeyboardButton("Данные теста", callback_data=f"{callback_prefix}:testdata")],
        [InlineKeyboardButton("Сравнить две записи", callback_data=f"{callback_prefix}:compare_help")],
        [InlineKeyboardButton("Загрузить маркеры", callback_data=f"{callback_prefix}:upload")],
        [InlineKeyboardButton("Справка", callback_data=f"{callback_prefix}:help")],
    ]
    footer_row: list[InlineKeyboardButton] = []
    if back_callback:
        footer_row.append(InlineKeyboardButton("Назад", callback_data=back_callback))
    footer_row.append(InlineKeyboardButton("Отмена", callback_data=f"{callback_prefix}:cancel"))
    rows.append(footer_row)
    return InlineKeyboardMarkup(rows)


def build_ystr_prompt_keyboard(callback_prefix: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("Назад", callback_data=f"{callback_prefix}:root"),
        InlineKeyboardButton("Отмена", callback_data=f"{callback_prefix}:cancel"),
    ]])


def build_ystr_compare_prompt_keyboard(callback_prefix: str, back_action: str = "root") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("Назад", callback_data=f"{callback_prefix}:{back_action}"),
        InlineKeyboardButton("Отмена", callback_data=f"{callback_prefix}:cancel"),
    ]])


def build_ystr_candidates_keyboard(callback_prefix: str, candidates: list[dict[str, object]]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for index, entry in enumerate(candidates[:20]):
        rows.append([InlineKeyboardButton(format_ystr_entry_button(entry), callback_data=f"{callback_prefix}:pick:{index}")])
    rows.append([
        InlineKeyboardButton("Назад", callback_data=f"{callback_prefix}:nearest"),
        InlineKeyboardButton("Отмена", callback_data=f"{callback_prefix}:cancel"),
    ])
    return InlineKeyboardMarkup(rows)


def build_ystr_data_candidates_keyboard(callback_prefix: str, candidates: list[dict[str, object]]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for index, entry in enumerate(candidates[:20]):
        rows.append([InlineKeyboardButton(format_ystr_entry_button(entry), callback_data=f"{callback_prefix}:datapick:{index}")])
    rows.append([
        InlineKeyboardButton("Назад", callback_data=f"{callback_prefix}:testdata"),
        InlineKeyboardButton("Отмена", callback_data=f"{callback_prefix}:cancel"),
    ])
    return InlineKeyboardMarkup(rows)


def build_ystr_compare_candidates_keyboard(callback_prefix: str, candidates: list[dict[str, object]], side: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for index, entry in enumerate(candidates[:20]):
        rows.append([InlineKeyboardButton(format_ystr_entry_button(entry), callback_data=f"{callback_prefix}:comparepick:{side}:{index}")])
    back_action = "compare_start" if side == "left" else "compare_left_selected"
    rows.append([
        InlineKeyboardButton("Назад", callback_data=f"{callback_prefix}:{back_action}"),
        InlineKeyboardButton("Отмена", callback_data=f"{callback_prefix}:cancel"),
    ])
    return InlineKeyboardMarkup(rows)


def build_ystr_result_keyboard(callback_prefix: str, back_action: str = "candidates") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("Назад", callback_data=f"{callback_prefix}:{back_action}"),
        InlineKeyboardButton("Отмена", callback_data=f"{callback_prefix}:cancel"),
    ]])


def build_ystr_data_matches_keyboard(callback_prefix: str, entry_index: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("Назад", callback_data=f"{callback_prefix}:data:{entry_index}"),
        InlineKeyboardButton("Отмена", callback_data=f"{callback_prefix}:cancel"),
    ]])


def build_ystr_test_data_keyboard(callback_prefix: str, entry_index: int, *, show_all: bool, has_more: bool) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if has_more and not show_all:
        rows.append([InlineKeyboardButton("Показать все маркеры", callback_data=f"{callback_prefix}:dataall:{entry_index}")])
    rows.append([InlineKeyboardButton("Найти ближайших", callback_data=f"{callback_prefix}:datamatches:{entry_index}")])
    back_action = f"data:{entry_index}" if show_all else "databack"
    rows.append([
        InlineKeyboardButton("Назад", callback_data=f"{callback_prefix}:{back_action}"),
        InlineKeyboardButton("Отмена", callback_data=f"{callback_prefix}:cancel"),
    ])
    return InlineKeyboardMarkup(rows)


def build_ystr_compare_result_keyboard(callback_prefix: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Сравнить другие", callback_data=f"{callback_prefix}:compare_start")],
        [
            InlineKeyboardButton("Назад", callback_data=f"{callback_prefix}:compare_left_selected"),
            InlineKeyboardButton("Отмена", callback_data=f"{callback_prefix}:cancel"),
        ],
    ])


def build_ystr_uploaded_profile_keyboard(callback_prefix: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Найти ближайших", callback_data=f"{callback_prefix}:uploadmatches")],
        [InlineKeyboardButton("Сравнить с тестом KBDNA", callback_data=f"{callback_prefix}:uploadcompare")],
        [InlineKeyboardButton("Показать маркеры", callback_data=f"{callback_prefix}:uploadshow")],
        [
            InlineKeyboardButton("Назад", callback_data=f"{callback_prefix}:upload"),
            InlineKeyboardButton("Отмена", callback_data=f"{callback_prefix}:cancel"),
        ],
    ])


def build_ystr_uploaded_view_keyboard(callback_prefix: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("Назад", callback_data=f"{callback_prefix}:uploaded"),
        InlineKeyboardButton("Отмена", callback_data=f"{callback_prefix}:cancel"),
    ]])


def build_ystr_upload_compare_candidates_keyboard(callback_prefix: str, candidates: list[dict[str, object]]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for index, entry in enumerate(candidates[:20]):
        rows.append([InlineKeyboardButton(format_ystr_entry_button(entry), callback_data=f"{callback_prefix}:uploadpick:{index}")])
    rows.append([
        InlineKeyboardButton("Назад", callback_data=f"{callback_prefix}:uploaded"),
        InlineKeyboardButton("Отмена", callback_data=f"{callback_prefix}:cancel"),
    ])
    return InlineKeyboardMarkup(rows)
