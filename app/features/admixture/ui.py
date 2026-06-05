from __future__ import annotations

import html
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.features.my_data.storage import CoordinateAsset, SampleAsset
from app.i18n import t

from .model_catalog import RawAdmixtureModel, RawAdmixtureProject
from .oracle import OracleMatch, OracleMixMatch, OracleReferenceSet
from .storage import AdmixtureReportRecord, AdmixtureReportSummary


def _copy(lang: str, ru: str, en: str) -> str:
    return en if lang == "en" else ru


def build_markup(rows: list[list[InlineKeyboardButton]], back_callback: str, *, lang: str = "ru") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        rows
        + [[
            InlineKeyboardButton(t("nav.back", lang), callback_data=back_callback),
            InlineKeyboardButton(t("nav.cancel", lang), callback_data="main:cancel"),
        ]]
    )


def admixture_root_text(lang: str = "ru") -> str:
    return "\n".join(
        [
            "<b>🧬 Admixture</b>",
            "",
            _copy(lang, "Компоненты, похожие популяции и oracle mix.", "Components, similar populations, and oracle mix."),
        ]
    )


def placeholder_feature_text(title: str, description: str, lang: str = "ru") -> str:
    return "\n".join(
        [
            f"<b>{html.escape(title)}</b>",
            "",
            html.escape(description),
            "",
            _copy(lang, "Функция пока не реализована.", "This feature is not implemented yet."),
        ]
    )


def raw_calculators_text(projects: list[RawAdmixtureProject], lang: str = "ru") -> str:
    models = [model for project in projects for model in project.models]
    installed_count = sum(1 for model in models if model.installed)
    return "\n".join(
        [
            "<b>🧮 Raw calculators</b>",
            "",
            f"{_copy(lang, 'Установлено', 'Installed')}: <b>{installed_count}</b> / {len(models)}",
            _copy(lang, "Выберите проект калькулятора.", "Choose a calculator project."),
        ]
    )


def raw_project_models_text(project: RawAdmixtureProject, lang: str = "ru") -> str:
    installed_count = sum(1 for model in project.models if model.installed)
    return "\n".join(
        [
            f"<b>{html.escape(project.title)}</b>",
            "",
            f"{_copy(lang, 'Установлено', 'Installed')}: {installed_count} / {len(project.models)}",
            _copy(lang, "Выберите модель.", "Choose a model."),
        ]
    )


def raw_model_detail_text(model: RawAdmixtureModel, lang: str = "ru") -> str:
    status = "installed" if model.installed else "not installed"
    lines = [
        f"<b>{html.escape(model.name)}</b>",
        "",
        f"Status: {status}",
        f"Components: {model.population_count}",
    ]
    if not model.installed:
        lines.extend(
            [
                "",
                _copy(lang, "Для запуска этой модели нужны reference data:", "This model needs reference data to run:"),
                html.escape(model.allele_file),
                html.escape(model.frequency_file),
            ]
        )
    return "\n".join(lines)


def raw_model_sample_picker_text(model_name: str, samples: list[SampleAsset], lang: str = "ru") -> str:
    model = str(model_name or "Admixture").strip() or "Admixture"
    lines = [
        f"<b>🧮 {html.escape(model)} profile</b>",
        "",
        _copy(lang, f"Выберите sample для {html.escape(model)}-профиля.", f"Choose a sample for the {html.escape(model)} profile."),
        "",
        _copy(lang, "Если профиль уже сохранён, откроется сохранённый результат.", "If the profile is already saved, the saved result will open."),
        "",
        f"{_copy(lang, 'Sample с raw-файлом', 'Samples with raw files')}: <b>{len(samples)}</b>",
    ]
    if not samples:
        lines.extend(["", _copy(lang, "Пока нет samples. Сначала создайте sample в My DNA.", "No samples yet. Create a sample in My DNA first.")])
    return "\n".join(lines)


def k36_sample_picker_text(samples: list[SampleAsset], lang: str = "ru") -> str:
    return raw_model_sample_picker_text("K36", samples, lang)


def sample_admixture_reports_text(
    sample: SampleAsset,
    reports: list[AdmixtureReportSummary],
    k36_coordinates: list[CoordinateAsset],
    lang: str = "ru",
) -> str:
    lines = [
        "<b>🧮 K36 profile</b>",
        "",
        f"<b>Sample:</b> {html.escape(sample.display_name)}",
        "",
        f"<b>{_copy(lang, 'Данные', 'Data')}</b>",
        f"{_copy(lang, 'Сохранено профилей', 'Saved profiles')}: {len(reports)}",
        f"K36 coordinates: {len(k36_coordinates)}",
    ]
    if reports:
        lines.extend(["", _copy(lang, "Выберите сохранённый профиль.", "Choose a saved profile.")])
    elif k36_coordinates:
        lines.extend(["", _copy(lang, "K36-координаты уже есть. Можно открыть K36 profile и сохранить отчёт вручную.", "K36 coordinates already exist. You can open the K36 profile and save the report manually.")])
    else:
        lines.extend(["", _copy(lang, "K36-координат пока нет. Их можно извлечь из исходного raw-файла.", "There are no K36 coordinates yet. They can be extracted from the source raw file.")])
    return "\n".join(lines)


def k36_coordinate_picker_text(sample: SampleAsset, coordinates: list[CoordinateAsset], lang: str = "ru") -> str:
    lines = [
        "<b>K36 profile</b>",
        "",
        f"<b>Sample:</b> {html.escape(sample.display_name)}",
        "",
        _copy(lang, "Выберите K36-координаты для отчета.", "Choose K36 coordinates for the report."),
    ]
    if len(coordinates) > 10:
        lines.extend(["", _copy(lang, f"Показаны первые 10 из {len(coordinates)}.", f"Showing the first 10 of {len(coordinates)}.")])
    return "\n".join(lines)


def running_k36_text(sample: SampleAsset, lang: str = "ru") -> str:
    return (
        "<b>K36 profile</b>\n\n"
        f"Sample: <b>{html.escape(sample.display_name)}</b>\n"
        + _copy(lang, "Строю admixture report...", "Building admixture report...")
    )


def extracting_k36_text(sample: SampleAsset, lang: str = "ru") -> str:
    return (
        "<b>K36 extraction</b>\n\n"
        f"Sample: <b>{html.escape(sample.display_name)}</b>\n"
        + _copy(lang, "Извлекаю K36 из исходного raw-файла...", "Extracting K36 from the source raw file...")
    )


def report_saved_text(record: AdmixtureReportRecord, lang: str = "ru") -> str:
    summary = record.summary
    return (
        f"<b>{_copy(lang, 'Admixture report сохранен', 'Admixture report saved')}</b>\n\n"
        f"Sample: <b>{html.escape(summary.sample_name)}</b>\n"
        f"Model: {html.escape(summary.model)}\n"
        f"Top component: {html.escape(summary.strongest_component)} {summary.strongest_component_value:.2f}%\n"
        f"Macro signal: {html.escape(summary.macro_summary)}"
    )


def profile_visual_caption(sample: SampleAsset, payload: dict[str, object], lang: str = "ru") -> str:
    return _profile_caption(
        title=f"{str(payload.get('model') or 'Admixture')} profile",
        sample_name=sample.display_name,
        payload=payload,
    )


def saved_report_visual_caption(record: AdmixtureReportRecord, lang: str = "ru") -> str:
    return _profile_caption(
        title=record.summary.title,
        sample_name=record.summary.sample_name,
        payload=record.product_payload,
    )


def report_detail_visual_caption(record: AdmixtureReportRecord, lang: str = "ru") -> str:
    return _profile_caption(
        title=record.summary.title,
        sample_name=record.summary.sample_name,
        payload=record.product_payload,
    )


def profile_preview_text(sample: SampleAsset, coordinate: CoordinateAsset, payload: dict[str, object], lang: str = "ru") -> str:
    lines = [
        f"<b>{html.escape(str(payload.get('model') or 'Admixture'))} profile</b>",
        "",
        f"Sample: <b>{html.escape(sample.display_name)}</b>",
        f"Coordinates: {html.escape(coordinate.display_name)}",
        _copy(lang, "Status: not saved", "Status: not saved"),
    ]
    lines.extend(_profile_lines(payload, lang))
    return "\n".join(lines)


def report_detail_text(record: AdmixtureReportRecord, lang: str = "ru") -> str:
    summary = record.summary
    payload = record.product_payload
    lines = [
        f"<b>{html.escape(summary.title)}</b>",
        "",
        f"Sample: <b>{html.escape(summary.sample_name)}</b>",
        f"Coordinates: {html.escape(summary.coordinate_name)}",
        f"Saved: {_format_created_at(summary.created_at)}",
    ]
    lines.extend(_profile_lines(payload, lang))
    return "\n".join(lines)


def compare_profiles_text(model_counts: list[tuple[str, int]], lang: str = "ru") -> str:
    lines = [
        "<b>⚖️ Compare profiles</b>",
        "",
        _copy(lang, "Сравнение сохранённых admixture-профилей.", "Compare saved admixture profiles."),
        "",
        _copy(lang, "Выберите проект.", "Choose a project."),
    ]
    if not model_counts:
        lines.extend(["", _copy(lang, "Пока нет проектов с двумя сохраненными reports одной модели.", "There are no projects with two saved reports from one model yet.")])
    return "\n".join(lines)


def compare_project_models_text(project: RawAdmixtureProject, model_counts: list[tuple[str, int]], lang: str = "ru") -> str:
    lines = [
        f"<b>⚖️ {html.escape(project.title)}</b>",
        "",
        _copy(lang, "Выберите модель для сравнения.", "Choose a model to compare."),
    ]
    if not model_counts:
        lines.extend(["", _copy(lang, "В этом проекте пока нет моделей с двумя сохраненными reports.", "This project has no models with two saved reports yet.")])
    return "\n".join(lines)


def compare_report_picker_text(
    model: str,
    reports: list[AdmixtureReportSummary],
    *,
    side: str,
    first_report: AdmixtureReportSummary | None = None,
    lang: str = "ru",
) -> str:
    title = f"<b>⚖️ {html.escape(model)} comparison</b>"
    if side == "left":
        return "\n".join(
            [
                title,
                "",
                _copy(lang, "Выберите первый профиль.", "Choose the first profile."),
                "",
                f"{_copy(lang, 'Сохранённых профилей', 'Saved profiles')}: {len(reports)}",
            ]
        )
    first_name = html.escape(first_report.sample_name) if first_report is not None else _copy(lang, "выбран", "selected")
    return "\n".join(
        [
            title,
            "",
            _copy(lang, f"Первый профиль: {first_name}", f"First profile: {first_name}"),
            "",
            _copy(lang, "Выберите второй профиль.", "Choose the second profile."),
            "",
            f"{_copy(lang, 'Доступно для сравнения', 'Available to compare')}: {len(reports)}",
        ]
    )


def compare_result_text(left: AdmixtureReportRecord, right: AdmixtureReportRecord, comparison: dict[str, object]) -> str:
    left_label = _escape_pre(_sample_table_label(left.summary.sample_name))
    right_label = _escape_pre(_sample_table_label(right.summary.sample_name))
    model = html.escape(str(comparison.get("model") or left.summary.model))
    lines = [
        f"<b>⚖️ {model} comparison</b>",
        "",
        f"<b>{html.escape(left.summary.sample_name)}</b> × <b>{html.escape(right.summary.sample_name)}</b>",
        f"Components: {int(comparison.get('component_count') or 0)}",
        f"Общая разница: {_float(comparison.get('total_absolute_difference')):.2f}",
        f"Средняя разница: {_float(comparison.get('average_absolute_difference')):.2f}",
        "",
        "<b>Top differences</b>",
        f"<pre>{'Component':<22} {left_label:>6}  {right_label:>6}       Δ",
    ]
    for item in comparison.get("differences") or []:
        if not isinstance(item, dict):
            continue
        delta = _float(item.get("delta"))
        name = _escape_pre(_short_component_name(str(item.get("name") or "")))
        lines.append(f"{name:<22} {_float(item.get('left')):>6.2f}  {_float(item.get('right')):>6.2f}  {delta:>+7.2f}")
    lines.append("</pre>")
    return "\n".join(lines)


def compare_visual_caption(left: AdmixtureReportRecord, right: AdmixtureReportRecord, comparison: dict[str, object]) -> str:
    model = html.escape(str(comparison.get("model") or left.summary.model))
    return "\n".join(
        [
            f"<b>⚖️ {model} comparison</b>",
            f"{html.escape(left.summary.sample_name)} × {html.escape(right.summary.sample_name)}",
            f"Общая разница: {_float(comparison.get('total_absolute_difference')):.2f}",
            f"Средняя разница: {_float(comparison.get('average_absolute_difference')):.2f}",
        ]
    )


def oracle_projects_text(project_counts: list[tuple[str, int]], lang: str = "ru") -> str:
    lines = [
        "<b>🧭 Similar populations</b>",
        "",
        _copy(lang, "Поиск ближайших популяций по сохранённому admixture-профилю.", "Find closest populations from a saved admixture profile."),
        "",
        _copy(lang, "Выберите проект.", "Choose a project."),
    ]
    if not project_counts:
        lines.extend(["", _copy(lang, "Пока нет установленных Oracle/reference таблиц.", "No Oracle/reference tables are installed yet.")])
    return "\n".join(lines)


def oracle_project_models_text(project: RawAdmixtureProject, model_counts: list[tuple[str, int]], lang: str = "ru") -> str:
    lines = [
        f"<b>🧭 {html.escape(project.title)}</b>",
        "",
        _copy(lang, "Выберите модель для поиска похожих популяций.", "Choose a model to find similar populations."),
    ]
    if not model_counts:
        lines.extend(["", _copy(lang, "В этом проекте пока нет моделей с Oracle/reference таблицей.", "This project has no models with an Oracle/reference table yet.")])
    return "\n".join(lines)


def oracle_report_picker_text(model: str, reports: list[AdmixtureReportSummary], reference_count: int, lang: str = "ru") -> str:
    lines = [
        f"<b>🧭 {html.escape(model)} similar populations</b>",
        "",
        f"{_copy(lang, 'Референсных популяций', 'Reference populations')}: {reference_count}",
        f"{_copy(lang, 'Сохранённых профилей', 'Saved profiles')}: {len(reports)}",
    ]
    if reports:
        lines.extend(["", _copy(lang, "Выберите профиль.", "Choose a profile.")])
    else:
        lines.extend(["", _copy(lang, "Сначала посчитайте и сохраните profile этой модели.", "Run and save a profile for this model first.")])
    return "\n".join(lines)


def oracle_result_text(record: AdmixtureReportRecord, reference_set: OracleReferenceSet, matches: list[OracleMatch]) -> str:
    lines = [
        f"<b>🧭 {html.escape(record.summary.model)} similar populations</b>",
        "",
        f"Sample: <b>{html.escape(record.summary.sample_name)}</b>",
        f"Референсных популяций: {len(reference_set.populations)}",
    ]
    if reference_set.source.unofficial:
        lines.append("Status: unofficial reference")
    lines.extend(["", "<b>Ближайшие популяции</b>", "<pre>Population                 Distance"])
    for match in matches:
        label = _escape_pre(_short_population_name(match.population))
        source = _escape_pre(f" ({match.source})") if match.source and not reference_set.source.unofficial else ""
        lines.append(f"{label:<24} {match.distance:>8.4f}{source}")
    lines.append("</pre>")
    lines.extend([
        "",
        "Distance is Euclidean distance between your admixture percentages and reference population averages. Lower is closer.",
    ])
    return "\n".join(lines)


def oracle_visual_caption(record: AdmixtureReportRecord, matches: list[OracleMatch]) -> str:
    best = matches[0] if matches else None
    lines = [
        f"<b>🧭 {html.escape(record.summary.model)} similar populations</b>",
        f"Sample: <b>{html.escape(record.summary.sample_name)}</b>",
    ]
    if best is not None:
        lines.extend(
            [
                f"Ближайшая популяция: {html.escape(best.population)}",
                f"Дистанция: {best.distance:.4f}",
            ]
        )
        if len(matches) > 1:
            lines.append(f"Отрыв от #2: {matches[1].distance - best.distance:.4f}")
    return "\n".join(lines)


def oracle_mix_projects_text(project_counts: list[tuple[str, int]], lang: str = "ru") -> str:
    lines = [
        "<b>🧬 Oracle mix</b>",
        "",
        _copy(lang, "Подбор смеси популяций по сохранённому admixture-профилю.", "Fit population mixtures from a saved admixture profile."),
        "",
        _copy(lang, "Выберите проект.", "Choose a project."),
    ]
    if not project_counts:
        lines.extend(["", _copy(lang, "Пока нет установленных Oracle/reference таблиц.", "No Oracle/reference tables are installed yet.")])
    return "\n".join(lines)


def oracle_mix_project_models_text(project: RawAdmixtureProject, model_counts: list[tuple[str, int]], lang: str = "ru") -> str:
    lines = [
        f"<b>🧬 {html.escape(project.title)}</b>",
        "",
        _copy(lang, "Выберите модель для oracle mix.", "Choose a model for oracle mix."),
    ]
    if not model_counts:
        lines.extend(["", _copy(lang, "В этом проекте пока нет моделей с Oracle/reference таблицей.", "This project has no models with an Oracle/reference table yet.")])
    return "\n".join(lines)


def oracle_mix_mode_text(model: str, reference_count: int, report_count: int, lang: str = "ru") -> str:
    lines = [
        f"<b>🧬 {html.escape(model)} oracle mix</b>",
        "",
        f"{_copy(lang, 'Референсных популяций', 'Reference populations')}: {reference_count}",
        f"{_copy(lang, 'Сохранённых профилей', 'Saved profiles')}: {report_count}",
        "",
        _copy(lang, "Выберите режим смеси.", "Choose a mixture mode."),
    ]
    if not report_count:
        lines.extend(["", _copy(lang, "Сначала посчитайте и сохраните profile этой модели.", "Run and save a profile for this model first.")])
    return "\n".join(lines)


def oracle_mix_report_picker_text(model: str, mode: str, reports: list[AdmixtureReportSummary], reference_count: int, lang: str = "ru") -> str:
    mode_label = _oracle_mix_caption_mode(mode)
    lines = [
        f"<b>🧬 {html.escape(model)} oracle mix</b>",
        "",
        f"{_copy(lang, 'Режим', 'Mode')}: {html.escape(mode_label)}",
        f"{_copy(lang, 'Референсных популяций', 'Reference populations')}: {reference_count}",
        f"{_copy(lang, 'Сохранённых профилей', 'Saved profiles')}: {len(reports)}",
    ]
    if reports:
        lines.extend(["", _copy(lang, "Выберите профиль.", "Choose a profile.")])
    else:
        lines.extend(["", _copy(lang, "Сначала посчитайте и сохраните profile этой модели.", "Run and save a profile for this model first.")])
    return "\n".join(lines)


def oracle_mix_result_text(
    record: AdmixtureReportRecord,
    reference_set: OracleReferenceSet,
    mode: str,
    single_matches: list[OracleMatch],
    mix_matches: list[OracleMixMatch],
) -> str:
    best_single = single_matches[0] if single_matches else None
    best_mix = mix_matches[0] if mix_matches else None
    mode_label = _oracle_mix_caption_mode(mode)
    lines = [
        f"<b>🧬 {html.escape(record.summary.model)} oracle mix</b>",
        "",
        f"Sample: <b>{html.escape(record.summary.sample_name)}</b>",
        f"Режим: {html.escape(mode_label)}",
        f"Референсных популяций: {len(reference_set.populations)}",
    ]
    if reference_set.source.unofficial:
        lines.append("Status: unofficial reference")
    if best_single is not None:
        lines.extend(["", f"Best single: {html.escape(best_single.population)} {best_single.distance:.3f}"])
    if best_mix is not None:
        lines.append(f"Лучшая смесь: {_format_mix_inline(best_mix)}")
        lines.append(f"Дистанция: {best_mix.distance:.4f}")
        if best_single is not None:
            lines.append(f"Improvement: {best_single.distance - best_mix.distance:.3f}")
    lines.extend(["", f"<b>Best {html.escape(mode)} fits</b>", "<pre>Mix                                      Dist"])
    for match in mix_matches:
        lines.append(f"{_format_mix_table(match):<40} {match.distance:>6.3f}")
    lines.append("</pre>")
    lines.extend([
        "",
        "This is a mathematical fit between admixture percentages and reference averages, not literal ancestry.",
    ])
    return "\n".join(lines)


def oracle_mix_visual_caption(record: AdmixtureReportRecord, mode: str, mix_matches: list[OracleMixMatch]) -> str:
    best = mix_matches[0] if mix_matches else None
    lines = [
        f"<b>🧬 {html.escape(record.summary.model)} oracle mix</b>",
        f"Sample: <b>{html.escape(record.summary.sample_name)}</b>",
        f"Режим: {html.escape(_oracle_mix_caption_mode(mode))}",
    ]
    if best is not None:
        lines.extend(
            [
                f"Лучшая смесь: {_format_mix_inline(best)}",
                f"Дистанция: {best.distance:.4f}",
            ]
        )
    return "\n".join(lines)


def _profile_lines(payload: dict[str, object], lang: str = "ru") -> list[str]:
    model = str(payload.get("model") or "Admixture")
    components = [item for item in payload.get("components") or [] if isinstance(item, dict)]
    macro_groups = [item for item in payload.get("macro_groups") or [] if isinstance(item, dict)]
    total = _float(payload.get("total"))
    lines = [
        f"Total: {total:.2f}",
        "",
        f"<b>{html.escape(model)} components</b>",
    ]
    for item in components:
        lines.append(f"{html.escape(str(item.get('name') or ''))}: {_float(item.get('value')):.2f}%")
    if macro_groups:
        lines.extend(["", "<b>Macro groups</b>"])
        for item in macro_groups[:6]:
            lines.append(f"{html.escape(str(item.get('name') or ''))}: {_float(item.get('value')):.2f}%")
    lines.extend([
        "",
        _copy(
            lang,
            f"{html.escape(model)}-компоненты описательные: это профиль относительно конкретной модели, а не буквальные проценты происхождения.",
            f"{html.escape(model)} components are descriptive: this is a profile relative to a specific model, not literal ancestry percentages.",
        ),
    ])
    return lines


def _profile_caption(*, title: str, sample_name: str, payload: dict[str, object]) -> str:
    top = _first_top_component(payload)
    total = _float(payload.get("total"))
    clean_title = str(title or "Admixture profile").strip() or "Admixture profile"
    if not clean_title.startswith("🧮"):
        clean_title = f"🧮 {clean_title}"
    top_text = f"{html.escape(top[0])} — {top[1]:.2f}%" if top is not None else "-"
    return "\n".join(
        [
            f"<b>{html.escape(clean_title)}</b>",
            f"Sample: <b>{html.escape(sample_name)}</b>",
            f"Top: {top_text}",
            f"Total: {total:.2f}",
        ]
    )


def _first_top_component(payload: dict[str, object]) -> tuple[str, float] | None:
    for item in payload.get("top_components") or payload.get("components") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if name:
            return name.replace("_", " "), _float(item.get("value"))
    return None


def report_button_label(item: AdmixtureReportSummary) -> str:
    component = item.strongest_component or "profile"
    return f"{item.model}: {component} {item.strongest_component_value:.1f}%"


def compare_report_button_label(item: AdmixtureReportSummary) -> str:
    component = (item.strongest_component or "profile").replace("_", " ")
    return f"{item.sample_name} · {component} {item.strongest_component_value:.1f}%"


def similar_report_button_label(item: AdmixtureReportSummary) -> str:
    component = (item.strongest_component or "profile").replace("_", " ")
    return f"{item.sample_name} · {component} {item.strongest_component_value:.1f}%"


def oracle_mix_report_button_label(item: AdmixtureReportSummary) -> str:
    component = (item.strongest_component or "profile").replace("_", " ")
    return f"{item.sample_name} · {component} {item.strongest_component_value:.1f}%"


def error_text(title: str, message: str, *, details: str | None = None) -> str:
    lines = [f"<b>{html.escape(title)}</b>", "", html.escape(message)]
    if details:
        lines.extend(["", html.escape(details)])
    return "\n".join(lines)


def _format_created_at(value: str) -> str:
    try:
        return datetime.fromisoformat(value).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return value


def _float(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _escape_pre(value: str) -> str:
    return html.escape(value, quote=False)


def _short_component_name(value: str) -> str:
    cleaned = value.replace("_", " ").strip()
    return cleaned[:22]


def _short_population_name(value: str) -> str:
    cleaned = value.replace("_", " ").strip()
    return cleaned[:24]


def _short_mix_population_name(value: str) -> str:
    cleaned = value.replace("_", " ").strip()
    return cleaned[:13]


def _format_mix_inline(match: OracleMixMatch) -> str:
    return " + ".join(
        f"{percent}% {html.escape(population)}"
        for percent, population in zip(match.percents, match.populations)
    )


def _oracle_mix_caption_mode(mode: str) -> str:
    clean = str(mode or "").strip() or "mix"
    return clean if clean.lower().endswith("mix") else f"{clean} mix"


def _format_mix_table(match: OracleMixMatch) -> str:
    return " + ".join(
        f"{percent}% {_escape_pre(_short_mix_population_name(population))}"
        for percent, population in zip(match.percents, match.populations)
    )


def _sample_table_label(value: str) -> str:
    cleaned = value.strip() or "S"
    return cleaned[:6]
