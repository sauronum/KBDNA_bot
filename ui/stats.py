from __future__ import annotations

import html

from g25_core.render_fit_png import render_stats_chart_png
from stores.usage import UsageStore
from ui.stats_visual import render_stats_summary_png


SECTION_LABELS = {
    "lookup": "Фамилии",
    "sozluk": "Словарь",
    "ystr": "Y-STR",
    "analytics": "Аналитика",
    "dna_lab": "DNA Lab",
    "g25": "Vahaduo Lab",
}

DNA_LAB_SECTION_ORDER = (
    "my_data",
    "coordinate_space",
    "vahaduo",
    "admixture",
    "modeling",
    "matching",
    "traits",
    "snp_report",
    "haplogroups",
)

DNA_LAB_SECTION_LABELS = {
    "my_data": "My DNA",
    "coordinate_space": "Coordinate spaces",
    "admixture": "Admixture",
    "modeling": "AdmixLab",
    "matching": "Matching",
    "traits": "Traits",
    "snp_report": "SNP Lab",
    "haplogroups": "Haplogroups",
    "vahaduo": "Vahaduo Lab",
    "unknown": "Unknown",
}

SUMMARY_SECTION_ORDER = (
    "lookup",
    "analytics",
    "my_data",
    "coordinate_space",
    "vahaduo",
    "admixture",
    "modeling",
    "matching",
    "traits",
    "snp_report",
    "haplogroups",
    "sozluk",
)

ACTION_LABELS = {
    "root": "Открытие раздела",
    "open": "Открытие",
    "samples_view": "Просмотр samples",
    "samples_create": "Создание sample",
    "sample_create": "Sample сохранен",
    "sample_item": "Карточка sample",
    "sample_reports": "Отчеты sample",
    "sample_pca_results": "PCA отчеты sample",
    "sample_admixture": "Admixture отчеты sample",
    "sample_matching": "Matching отчеты sample",
    "sample_traits": "Traits отчеты sample",
    "sample_haplogroups": "Haplogroups sample",
    "raw_upload": "Загрузка raw",
    "coordinates_view": "G25-профили",
    "coordinates_add_root": "Добавление G25",
    "coordinates_add_type": "Ручной ввод G25",
    "coordinate_add": "Координаты сохранены",
    "coordinates_extract_root": "Извлечение G25",
    "coordinates_extract_type": "Raw -> G25",
    "coordinate_extract": "Координаты извлечены",
    "coordinate_item": "Карточка G25",
    "qg25_create_sample": "My DNA -> sample",
    "qg25_save_g25_library": "My DNA -> библиотека",
    "vahaduo_mode": "Выбор режима",
    "vahaduo_source": "Выбор source",
    "vahaduo_target": "Выбор target",
    "vahaduo_run": "Расчет",
}


def _event_label(event_type: object) -> str:
    key = str(event_type or "unknown")
    return SECTION_LABELS.get(key, _humanize_key(key))


def _dna_lab_section_label(section: object) -> str:
    key = str(section or "unknown")
    if key == "quick_g25":
        key = "my_data"
    return DNA_LAB_SECTION_LABELS.get(key, _humanize_key(key))


def _action_label(action: object) -> str:
    key = str(action or "unknown")
    return ACTION_LABELS.get(key, _humanize_key(key))


def _command_label(event_type: object, command: object) -> str:
    if str(event_type or "") == "dna_lab":
        return _dna_lab_section_label(command)
    return _action_label(command)


def _summary_section_label(section: object) -> str:
    key = str(section or "unknown")
    if key in SECTION_LABELS:
        return SECTION_LABELS[key]
    return _dna_lab_section_label(key)


def _humanize_key(value: str) -> str:
    cleaned = str(value or "unknown").strip().replace("_", " ")
    if not cleaned:
        return "Unknown"
    return cleaned[:1].upper() + cleaned[1:]


def _format_count_lines(rows: list[tuple[object, int]], *, empty: str = "Пока нет данных", limit: int = 10) -> str:
    lines = [
        f"{idx}. {html.escape(str(label))} - {int(count)}"
        for idx, (label, count) in enumerate(rows[:limit], start=1)
    ]
    return "\n".join(lines) if lines else empty


def _stats_summary_rows(stats: dict[str, object]) -> list[tuple[str, int, int, int, int]]:
    section_map = {
        str(section): (int(total), int(last_7_days), int(today), int(unique_users))
        for section, total, last_7_days, today, unique_users, _success in (stats.get("summary_section_rows") or [])
    }
    ordered_sections = list(SUMMARY_SECTION_ORDER)
    ordered_sections.extend(
        sorted(
            (section for section in section_map if section not in SUMMARY_SECTION_ORDER and section_map[section][0] > 0),
            key=lambda section: (-section_map[section][0], _summary_section_label(section).casefold()),
        )
    )
    return [
        (
            _summary_section_label(section),
            *section_map.get(section, (0, 0, 0, 0)),
        )
        for section in ordered_sections
    ]


def _stats_summary_table(rows: list[tuple[str, int, int, int, int]]) -> str:
    lines = [f"{'Раздел':<18} {'Всего':>5} {'7д':>4} {'Сегодня':>7} {'Польз.':>6}"]
    for label, total, last_7_days, today, unique_users in rows:
        lines.append(f"{label:<18} {total:>5} {last_7_days:>4} {today:>7} {unique_users:>6}")
    return "<pre>" + "\n".join(lines) + "</pre>"


def build_stats_summary_text(usage_store: UsageStore) -> str:
    stats = usage_store.get_summary()
    rows = _stats_summary_rows(stats)
    failed_total = int(stats["total"]) - int(stats["success"])
    return "\n".join([
        "📈 <b>Статистика</b>",
        "",
        f"Всего событий: {stats['total']}",
        f"Успешность: {stats['success_rate']}% · ошибок: {failed_total}",
        f"За 30 дней: {stats['last_30_days']} · за 7 дней: {stats['last_7_days']} · сегодня: {stats['today']}",
        f"Пользователей: {stats['unique_users']} · за 7 дней: {stats['unique_users_last_7_days']}",
        "",
        _stats_summary_table(rows),
        "",
        "Подробно по разделам:",
    ])


def build_lookup_stats_text(usage_store: UsageStore, *, is_private: bool, show_details: bool) -> str:
    stats = usage_store.get_summary()
    top_queries = stats["top_queries"][:25]
    top_lines = [f"{idx}. {html.escape(str(query))} - {count}" for idx, (query, count) in enumerate(top_queries, start=1)]
    top_block = "\n".join(top_lines) if top_lines else "Пока нет данных"

    return "\n".join([
        "🔎 <b>Статистика по фамилиям</b>",
        "",
        top_block,
    ])


def build_g25_stats_text(usage_store: UsageStore) -> str:
    stats = usage_store.get_summary()
    return "\n".join([
        "🧪 <b>Vahaduo Lab</b>",
        "",
        f"Всего расчетов G25/Vahaduo: {stats['g25_menu_total']}",
        f"Успешных: {stats['g25_menu_success']} ({stats['g25_menu_success_rate']}%)",
        f"За сегодня: {stats['g25_menu_today']}",
        f"За 7 дней: {stats['g25_menu_last_7_days']}",
        f"Уникальных пользователей: {stats['g25_menu_unique_users']}",
        "",
        f"Получить G25 координаты: {stats['g25_extract']}",
        f"Vahaduo Lab: {stats['g25_vahaduo_total']}",
        f"  Distance: {stats['g25_vahaduo_distance']}",
        f"  Single: {stats['g25_vahaduo_single']}",
        f"  Multi: {stats['g25_vahaduo_multi']}",
        "",
        f"raw-файлы: {stats['g25_menu_raw']}",
        f"готовые G25: {stats['g25_menu_text']}",
    ])


def build_dna_lab_stats_text(usage_store: UsageStore) -> str:
    stats = usage_store.get_summary()
    section_map = {
        str(section): int(total)
        for section, total, _last_7_days, _today, _unique_users, _success in stats["dna_lab_section_rows"]
    }
    ordered_sections = list(DNA_LAB_SECTION_ORDER)
    ordered_sections.extend(
        sorted(section for section in section_map if section not in DNA_LAB_SECTION_ORDER)
    )
    section_rows = [
        (_dna_lab_section_label(section), section_map.get(section, 0))
        for section in ordered_sections
    ]
    action_rows = [
        (
            f"{_dna_lab_section_label(section)} · {_action_label(action)}",
            int(count),
        )
        for section, action, count in stats["dna_lab_top_actions"]
        if str(section) not in {"main", "reports", "settings"}
    ]
    return "\n".join([
        "🧬 <b>DNA Lab</b>",
        "",
        "Разделы DNA Lab в общей статистике считаются отдельно.",
        "",
        "Разделы:",
        _format_count_lines(section_rows, limit=20),
        "",
        "My DNA G25:",
        f"Получение G25: {stats['g25_extract']}",
        "",
        "Vahaduo Lab расчеты:",
        f"Всего Vahaduo: {stats['g25_menu_total']}",
        f"Distance: {stats['g25_vahaduo_distance']}",
        f"Single: {stats['g25_vahaduo_single']}",
        f"Multi: {stats['g25_vahaduo_multi']}",
        "",
        "Топ действий:",
        _format_count_lines(action_rows),
    ])


def build_quality_stats_text(usage_store: UsageStore) -> str:
    stats = usage_store.get_summary()
    failed_total = int(stats["total"]) - int(stats["success"])
    failure_rows = [
        (
            f"{_event_label(event_type)} · {_command_label(event_type, command)}",
            int(count),
        )
        for event_type, command, count in stats["failure_breakdown"]
        if not (str(event_type) == "dna_lab" and str(command) in {"main", "reports", "settings"})
    ]
    command_rows = [
        (
            f"{_event_label(event_type)} · {_command_label(event_type, command)}",
            int(count),
        )
        for event_type, command, count in stats["command_breakdown"]
        if not (str(event_type) == "dna_lab" and str(command) in {"main", "reports", "settings"})
    ]
    user_rows = [
        (
            f"{label} ({int(active_days)} дн.)",
            int(count),
        )
        for label, count, active_days in stats["top_users"]
    ]
    return "\n".join([
        "✅ <b>Качество и нагрузка</b>",
        "",
        f"Всего событий: {stats['total']}",
        f"Успешных: {stats['success']} ({stats['success_rate']}%)",
        f"Ошибок: {failed_total}",
        f"Сегодня: {stats['today']} · за 7 дней: {stats['last_7_days']}",
        f"Private: {stats['private_events']} · группы: {stats['group_events']}",
        f"Уникальных пользователей: {stats['unique_users']} · за 7 дней: {stats['unique_users_last_7_days']}",
        "",
        "Проблемные места:",
        _format_count_lines(failure_rows),
        "",
        "Самые частые команды:",
        _format_count_lines(command_rows),
        "",
        "Активные пользователи:",
        _format_count_lines(user_rows),
    ])


def build_sozluk_stats_text(usage_store: UsageStore) -> str:
    stats = usage_store.get_summary()
    return "\n".join([
        "📚 <b>Словарь</b>",
        "",
        f"Сегодня: {stats['sozluk_today']}",
        f"За 7 дней: {stats['sozluk_last_7_days']}",
        f"Всего: {stats['sozluk_total']}",
        f"Успешность: {stats['sozluk_success_rate']}%",
    ])


def build_ystr_stats_text(usage_store: UsageStore) -> str:
    stats = usage_store.get_summary()
    return "\n".join([
        "🧬 <b>Y-STR анализ</b>",
        "",
        f"Сегодня: {stats['ystr_today']}",
        f"За 7 дней: {stats['ystr_last_7_days']}",
        f"Всего: {stats['ystr_total']}",
        f"Уникальных пользователей: {stats['ystr_unique_users']}",
        "",
        f"Найти ближайших: {stats['ystr_nearest']}",
        f"Данные теста: {stats['ystr_testdata']}",
        f"Сравнения: {stats['ystr_compare']}",
        f"Загрузки маркеров: {stats['ystr_upload']}",
    ])


def build_analytics_stats_text(usage_store: UsageStore) -> str:
    stats = usage_store.get_summary()
    ydna_diagrams = stats["analytics_haplo_families"] + stats["analytics_haplo_tests"]
    ydna_navigator = (
        stats["analytics_navigator"]
        + stats["analytics_nav_group"]
        + stats["analytics_nav_subclade"]
    )
    ydna_subclades = stats["analytics_subclade_group_select"]
    ydna_total = ydna_diagrams + ydna_navigator + ydna_subclades
    mtdna_diagrams = stats["analytics_mtdna_groups"] + stats["analytics_mtdna_subclades"]
    mtdna_navigator = (
        stats["analytics_mtdna_navigator"]
        + stats["analytics_mtdna_nav_group"]
        + stats["analytics_mtdna_nav_subclade"]
    )
    mtdna_total = mtdna_diagrams + mtdna_navigator
    return "\n".join([
        "📊 <b>Аналитика</b>",
        "",
        f"Сегодня: {stats['analytics_with_ystr_today']}",
        f"За 7 дней: {stats['analytics_with_ystr_last_7_days']}",
        f"Всего: {stats['analytics_with_ystr_total']}",
        f"Уникальных пользователей: {stats['analytics_with_ystr_unique_users']}",
        "",
        f"Y-ДНК: {ydna_total}",
        f"• Диаграммы: {ydna_diagrams}",
        f"• Навигатор: {ydna_navigator}",
        f"• Субклады: {ydna_subclades}",
        f"• STR-маркеры: {stats['ystr_total']}",
        "",
        f"МтДНК: {mtdna_total}",
        f"• Диаграммы: {mtdna_diagrams}",
        f"• Навигатор: {mtdna_navigator}",
        "",
        f"Y-STR · найти ближайших: {stats['ystr_nearest']}",
        f"Y-STR · данные теста: {stats['ystr_testdata']}",
        f"Y-STR · сравнения: {stats['ystr_compare']}",
        f"Y-STR · загрузки маркеров: {stats['ystr_upload']}",
    ])


def build_stats_chart_payload(usage_store: UsageStore, stats_kind: str) -> tuple[bytes, str]:
    if stats_kind != "summary":
        raise ValueError(f"Unknown stats kind: {stats_kind}")

    title = "STATS"
    series = usage_store.get_last_7_days_series("all", days=30)
    filename = "stats_summary_30d.png"
    return render_stats_chart_png(title, series, subtitle="LAST 30 DAYS"), filename


def build_stats_visual_payload(usage_store: UsageStore) -> tuple[bytes, str]:
    stats = usage_store.get_summary()
    section_rows = _stats_summary_rows(stats)
    lookup_rows = [(str(query), int(count)) for query, count in stats["top_queries"][:25]]
    user_rows = [
        (f"{label} ({int(active_days)} дн.)", int(count))
        for label, count, active_days in stats["top_users"][:25]
    ]
    recent_rows = [
        (str(user_label), _summary_section_label(section_key))
        for user_label, section_key, _event_type, _command, _action, _time_label in stats.get("recent_activity", [])[:25]
    ]
    png_bytes = render_stats_summary_png(
        stats=stats,
        series=usage_store.get_last_7_days_series("all", days=30),
        section_rows=section_rows,
        lookup_rows=lookup_rows,
        user_rows=user_rows,
        recent_rows=recent_rows,
    )
    return png_bytes, "stats_summary_full_30d.png"


def build_stats_detail_text(usage_store: UsageStore, stats_kind: str, *, is_private: bool) -> str:
    if stats_kind == "lookup":
        return build_lookup_stats_text(usage_store, is_private=is_private, show_details=True)
    if stats_kind == "sozluk":
        return build_sozluk_stats_text(usage_store)
    if stats_kind == "ystr":
        return build_ystr_stats_text(usage_store)
    if stats_kind == "analytics":
        return build_analytics_stats_text(usage_store)
    if stats_kind == "dna_lab":
        return build_dna_lab_stats_text(usage_store)
    if stats_kind == "g25":
        return build_g25_stats_text(usage_store)
    if stats_kind == "quality":
        return build_quality_stats_text(usage_store)
    raise ValueError(f"Unknown stats kind: {stats_kind}")
