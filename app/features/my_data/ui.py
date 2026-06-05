from __future__ import annotations

import html
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.i18n import t
from app.features.coordinate_space.reports import CoordinateSpaceResult
from app.features.matching.storage import MatchingRecord, MatchingRecordSummary

from .storage import CoordinateAsset, RawFileAsset, SampleAsset


MY_DATA_CALLBACK_PREFIX = "my_data"
MY_DNA_ENTRY_CALLBACK = "mydna:root"
SAMPLE_PAGE_SIZE = 10
COORD_REPORT_OPEN_ACTION = "scr"
COORD_REPORT_DELETE_PROMPT_ACTION = "scrdp"
COORD_REPORT_DELETE_CONFIRM_ACTION = "scrdc"


_COORDINATE_SPACE_VISIBLE_TITLES = {
    "Global": "🌍 Global",
    "West Eurasia": "🧭 West Eurasia",
    "Europe": "🇪🇺 Europe",
    "Caucasus / Steppe": "⛰ Caucasus / Steppe",
    "South Asia": "🌿 South Asia",
    "East Eurasia": "🌏 East Eurasia",
}


def _footer_rows(back_callback: str, *, lang: str = "ru") -> list[list[InlineKeyboardButton]]:
    return [
        [
            InlineKeyboardButton(t("nav.back", lang), callback_data=back_callback),
            InlineKeyboardButton(t("nav.cancel", lang), callback_data="main:cancel"),
        ]
    ]


def _add_data_footer_rows(back_callback: str) -> list[list[InlineKeyboardButton]]:
    return [[
        InlineKeyboardButton("⬅️ Назад", callback_data=back_callback),
        InlineKeyboardButton("Отмена", callback_data=f"{MY_DATA_CALLBACK_PREFIX}:cancel"),
    ]]


def my_data_text(*, lang: str = "ru") -> str:
    if lang == "en":
        return (
            "🧬 My DNA\n\n"
            "Your samples and G25 profiles."
        )
    return (
        "🧬 My DNA\n\n"
        "Ваши samples и G25-профили."
    )


def build_my_data_keyboard(*, lang: str = "ru") -> InlineKeyboardMarkup:
    g25_label = "G25 profiles" if lang == "en" else "G25-профили"
    reports_label = "Reports"
    raw_upload_label = "Upload raw" if lang == "en" else "Загрузить raw"
    g25_from_raw_label = "Get G25 coordinates" if lang == "en" else "Получить G25 координаты"
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Samples", callback_data=f"{MY_DATA_CALLBACK_PREFIX}:samples_view")],
            [InlineKeyboardButton(g25_label, callback_data=f"{MY_DATA_CALLBACK_PREFIX}:coordinates_view")],
            [InlineKeyboardButton(reports_label, callback_data="reports:root")],
            [InlineKeyboardButton(raw_upload_label, callback_data=f"{MY_DATA_CALLBACK_PREFIX}:raw_files_upload:root")],
            [InlineKeyboardButton(g25_from_raw_label, callback_data="mydna:get_g25_raw")],
        ]
    )


def samples_text(samples: list[SampleAsset] | None = None, *, lang: str = "ru") -> str:
    items = samples or []
    if lang == "en":
        lines = ["Samples", "", f"Saved samples: {len(items)}"]
        if not items:
            lines.extend(["", "No saved samples yet. Upload a raw file and create a sample."])
        else:
            lines.extend(["", "Each sample is a person/specimen built around one source raw file."])
        return "\n".join(lines)
    lines = ["Samples", "", f"Сохранено samples: {len(items)}"]
    if not items:
        lines.extend(["", "Пока нет сохраненных samples. Загрузите raw-файл и создайте sample."])
    else:
        lines.extend(["", "Каждый sample — это человек/образец, построенный вокруг одного исходного raw file."])
    return "\n".join(lines)


def build_samples_keyboard(*, lang: str = "ru") -> InlineKeyboardMarkup:
    create_label = "Upload raw" if lang == "en" else "Загрузить raw"
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("View samples", callback_data=f"{MY_DATA_CALLBACK_PREFIX}:samples_view")],
            [InlineKeyboardButton(create_label, callback_data=f"{MY_DATA_CALLBACK_PREFIX}:raw_files_upload")],
            *_footer_rows(MY_DNA_ENTRY_CALLBACK, lang=lang),
        ]
    )


def _sample_page_count(samples: list[SampleAsset]) -> int:
    return max(1, (len(samples) + SAMPLE_PAGE_SIZE - 1) // SAMPLE_PAGE_SIZE)


def _sample_page_bounds(samples: list[SampleAsset], page: int) -> tuple[int, int, int]:
    page_count = _sample_page_count(samples)
    safe_page = min(max(int(page), 0), page_count - 1)
    start = safe_page * SAMPLE_PAGE_SIZE
    end = min(start + SAMPLE_PAGE_SIZE, len(samples))
    return safe_page, start, end


def view_samples_text(samples: list[SampleAsset], page: int = 0, *, lang: str = "ru") -> str:
    if lang == "en":
        lines = ["<b>📁 My DNA</b>", "", f"<b>Samples:</b> {len(samples)}"]
        if not samples:
            lines.extend(["", "No saved samples yet. Upload a raw file and create a sample."])
            return "\n".join(lines)
        safe_page, start, end = _sample_page_bounds(samples, page)
        lines.extend(["", "Choose a sample below."])
        if len(samples) > SAMPLE_PAGE_SIZE:
            lines.extend(["", f"Showing {start + 1}-{end} of {len(samples)}. Page {safe_page + 1}/{_sample_page_count(samples)}."])
        return "\n".join(lines)

    lines = ["Сохраненные samples", "", f"Сохранено samples: {len(samples)}"]
    if not samples:
        lines.extend(["", "Пока нет сохраненных samples. Загрузите raw file и создайте из него sample."])
        return "\n".join(lines)
    safe_page, start, end = _sample_page_bounds(samples, page)
    lines.extend(["", "Выберите запись ниже."])
    if len(samples) > SAMPLE_PAGE_SIZE:
        lines.extend(["", f"Показаны {start + 1}-{end} из {len(samples)}. Страница {safe_page + 1}/{_sample_page_count(samples)}."])
    return "\n".join(lines)


def build_view_samples_keyboard(*, lang: str = "ru", back_callback: str = MY_DNA_ENTRY_CALLBACK) -> InlineKeyboardMarkup:
    create_label = "➕ New sample" if lang == "en" else "➕ Новый sample"
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(create_label, callback_data=f"{MY_DATA_CALLBACK_PREFIX}:raw_files_upload")],
            *_footer_rows(back_callback, lang=lang),
        ]
    )


def build_sample_items_keyboard(
    samples: list[SampleAsset],
    page: int = 0,
    *,
    lang: str = "ru",
    back_callback: str = MY_DNA_ENTRY_CALLBACK,
) -> InlineKeyboardMarkup:
    base_keyboard = build_view_samples_keyboard(lang=lang, back_callback=back_callback).inline_keyboard
    rows: list[list[InlineKeyboardButton]] = [base_keyboard[0]]
    safe_page, start, end = _sample_page_bounds(samples, page)
    for index, item in enumerate(samples[start:end], start=start + 1):
        rows.append(
            [InlineKeyboardButton(f"{index}. {item.display_name}", callback_data=f"{MY_DATA_CALLBACK_PREFIX}:sample_item:{item.asset_id}")]
        )
    if len(samples) > SAMPLE_PAGE_SIZE:
        nav_row: list[InlineKeyboardButton] = []
        if safe_page > 0:
            previous_label = "← Back" if lang == "en" else "← Назад"
            nav_row.append(InlineKeyboardButton(previous_label, callback_data=f"{MY_DATA_CALLBACK_PREFIX}:samples_page:{safe_page - 1}"))
        if end < len(samples):
            next_label = "Next →" if lang == "en" else "Далее →"
            nav_row.append(InlineKeyboardButton(next_label, callback_data=f"{MY_DATA_CALLBACK_PREFIX}:samples_page:{safe_page + 1}"))
        if nav_row:
            rows.append(nav_row)
    rows.extend(base_keyboard[1:])
    return InlineKeyboardMarkup(rows)


def create_sample_text(raw_file: RawFileAsset, *, lang: str = "ru") -> str:
    if lang == "en":
        return (
            "Create sample from raw\n\n"
            f"Source raw: {raw_file.display_name}\n"
            f"File name: {raw_file.original_file_name}\n\n"
            "Send the sample name in one message."
        )
    return (
        "Создание sample из raw\n\n"
        f"Исходный raw: {raw_file.display_name}\n"
        f"Имя файла: {raw_file.original_file_name}\n\n"
        "Пришлите имя sample одним сообщением."
    )


def build_create_sample_keyboard(raw_file_id: str, *, lang: str = "ru") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(_footer_rows(f"{MY_DATA_CALLBACK_PREFIX}:raw_file_item:{raw_file_id}", lang=lang))


def _count_text(value: int, *, lang: str = "ru") -> str:
    return ("none" if lang == "en" else "нет") if value == 0 else str(value)


def _report_count_text(value: object) -> str:
    try:
        return str(int(value or 0))
    except (TypeError, ValueError):
        return "0"


def _report_count_value(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _sample_status(value: int) -> str:
    return "✅" if value > 0 else "—"


def format_sample_created_at(value: str) -> str:
    try:
        return datetime.fromisoformat(value).strftime("%d.%m.%Y")
    except Exception:
        return value


def _short_button_label(value: str, *, max_length: int = 34) -> str:
    clean_value = " ".join((value or "").split()) or "G25-профиль"
    if len(clean_value) <= max_length:
        return clean_value
    tail_length = min(10, max_length // 3)
    head_length = max_length - tail_length - 3
    return f"{clean_value[:head_length]}...{clean_value[-tail_length:]}"


def sample_detail_text(
    asset: SampleAsset,
    *,
    raw_file: RawFileAsset | None,
    coordinate_count: int,
    report_count: int = 0,
    report_counts: dict[str, int] | None = None,
    lang: str = "ru",
) -> str:
    missing_raw = ("raw file not found" if lang == "en" else "raw-файл не найден") if asset.raw_file_id else ("none" if lang == "en" else "нет")
    raw_name = html.escape(raw_file.display_name if raw_file is not None else missing_raw)
    sample_name = html.escape(asset.display_name)
    counts = report_counts or {}
    total_reports = sum(_report_count_value(value) for value in counts.values()) if counts else _report_count_value(report_count)
    coordinate_reports = _report_count_text(counts.get("coordinate_spaces", 0))
    admixture_reports = _report_count_text(counts.get("admixture", 0))
    matching_reports = _report_count_text(counts.get("matching", 0))
    traits_reports = _report_count_text(counts.get("traits", 0))
    haplogroups_reports = _report_count_text(counts.get("haplogroups", 0))
    total_reports_text = _report_count_text(total_reports)
    if lang == "en":
        return (
            f"<b>🧬 Sample · {sample_name}</b>\n\n"
            f"<b>Created:</b> {format_sample_created_at(asset.created_at)}\n"
            "\n"
            "━━━━━━━━━━━━━━\n"
            "<b>🧬 Data</b>\n"
            "\n"
            f"{'✅' if raw_file is not None else '—'} Source raw: {raw_name}\n"
            f"{_sample_status(coordinate_count)} G25 profiles: {_count_text(coordinate_count, lang=lang)}\n"
            "\n"
            "━━━━━━━━━━━━━━\n"
            "<b>📊 Reports</b>\n"
            "\n"
            f"🧭 Coordinate spaces: {coordinate_reports}\n"
            f"🧬 Admixture: {admixture_reports}\n"
            f"🧩 Matching: {matching_reports}\n"
            f"🧾 Traits: {traits_reports}\n"
            f"🌿 Haplogroups: {haplogroups_reports}\n"
            "\n"
            f"<b>Total reports:</b> {total_reports_text}"
        )
    return (
        f"<b>🧬 Sample · {sample_name}</b>\n\n"
        f"<b>Создан:</b> {format_sample_created_at(asset.created_at)}\n"
        "\n"
        "━━━━━━━━━━━━━━\n"
        "<b>🧬 Данные</b>\n"
        "\n"
        f"{'✅' if raw_file is not None else '—'} Raw-файл: {raw_name}\n"
        f"{_sample_status(coordinate_count)} G25-профили: {_count_text(coordinate_count, lang=lang)}\n"
        "\n"
        "━━━━━━━━━━━━━━\n"
        "<b>📊 Отчёты</b>\n"
        "\n"
        f"🧭 Coordinate spaces: {coordinate_reports}\n"
        f"🧬 Admixture: {admixture_reports}\n"
        f"🧩 Matching: {matching_reports}\n"
        f"🧾 Traits: {traits_reports}\n"
        f"🌿 Haplogroups: {haplogroups_reports}\n"
        "\n"
        f"<b>Всего отчётов:</b> {total_reports_text}"
    )


def build_sample_detail_keyboard(
    asset: SampleAsset,
    *,
    lang: str = "ru",
    back_callback: str = f"{MY_DATA_CALLBACK_PREFIX}:samples_view",
) -> InlineKeyboardMarkup:
    source_raw = "🧬 Source raw" if lang == "en" else "🧬 Source raw"
    snp_lookup = "🔎 SNP lookup" if lang == "en" else "🔎 Поиск SNP"
    coordinates = "📍 Coordinates" if lang == "en" else "📍 Coordinates"
    rename = "✏️ Rename" if lang == "en" else "✏️ Rename"
    delete = "🗑 Delete" if lang == "en" else "🗑 Delete"
    rows = [[InlineKeyboardButton("📊 Reports", callback_data=f"{MY_DATA_CALLBACK_PREFIX}:sample_reports:{asset.asset_id}")]]
    if asset.raw_file_id:
        rows.append([InlineKeyboardButton(source_raw, callback_data=f"{MY_DATA_CALLBACK_PREFIX}:sfr:{asset.asset_id}")])
    rows.extend(
        [
            [InlineKeyboardButton(snp_lookup, callback_data=f"{MY_DATA_CALLBACK_PREFIX}:snp:{asset.asset_id}")],
            [InlineKeyboardButton(coordinates, callback_data=f"{MY_DATA_CALLBACK_PREFIX}:sample_view_coords:{asset.asset_id}")],
            [InlineKeyboardButton(rename, callback_data=f"{MY_DATA_CALLBACK_PREFIX}:sample_rename:{asset.asset_id}")],
            [InlineKeyboardButton(delete, callback_data=f"{MY_DATA_CALLBACK_PREFIX}:sample_delete_prompt:{asset.asset_id}")],
            *_footer_rows(back_callback, lang=lang),
        ]
    )
    return InlineKeyboardMarkup(rows)


def sample_snp_lookup_input_text(asset: SampleAsset, *, lang: str = "ru") -> str:
    sample_name = html.escape(asset.display_name)
    if lang == "en":
        return (
            "<b>🔎 SNP lookup</b>\n\n"
            f"Sample: <b>{sample_name}</b>\n\n"
            "Enter an rsID, for example:\n"
            "<code>rs2455144</code>"
        )
    return (
        "<b>🔎 Поиск SNP</b>\n\n"
        f"Sample: <b>{sample_name}</b>\n\n"
        "Введите rsID, например:\n"
        "<code>rs2455144</code>"
    )


def sample_snp_lookup_invalid_text(*, lang: str = "ru") -> str:
    if lang == "en":
        return (
            "<b>🔎 SNP lookup</b>\n\n"
            "Enter an rsID in the format rs123456."
        )
    return (
        "<b>🔎 Поиск SNP</b>\n\n"
        "Введите rsID в формате rs123456."
    )


def sample_snp_lookup_no_raw_text(asset: SampleAsset, *, lang: str = "ru") -> str:
    sample_name = html.escape(asset.display_name)
    if lang == "en":
        return (
            "<b>🔎 SNP lookup</b>\n\n"
            f"Sample: <b>{sample_name}</b>\n\n"
            "This sample has no raw file."
        )
    return (
        "<b>🔎 Поиск SNP</b>\n\n"
        f"Sample: <b>{sample_name}</b>\n\n"
        "У этого sample нет raw-файла."
    )


def sample_snp_lookup_result_text(asset: SampleAsset, result: object, *, lang: str = "ru") -> str:
    sample_name = html.escape(asset.display_name)
    rsid = html.escape(str(getattr(result, "rsid", "") or ""))
    genotype = html.escape(str(getattr(result, "genotype", "--") or "--"))
    chromosome = getattr(result, "chromosome", None)
    position = getattr(result, "position", None)
    found = bool(getattr(result, "found", False))
    error = str(getattr(result, "error", "") or "")

    if lang == "en":
        lines = ["<b>🔎 SNP lookup</b>", "", f"Sample: <b>{sample_name}</b>", f"SNP: <b>{rsid}</b>", ""]
        if error:
            lines.extend(["Could not read the raw file.", "", "Try again later or upload the raw file again."])
        elif found:
            lines.extend(
                [
                    f"Genotype: <b>{genotype}</b>",
                    f"Chromosome: {html.escape(str(chromosome or ''))}",
                    f"Position: {html.escape(str(position or ''))}",
                    "",
                    "Source: sample raw file.",
                ]
            )
        else:
            lines.extend(
                [
                    "SNP was not found in the raw file.",
                    "",
                    "This can depend on the chip, test version, or raw format.",
                ]
            )
        return "\n".join(lines)

    lines = ["<b>🔎 Поиск SNP</b>", "", f"Sample: <b>{sample_name}</b>", f"SNP: <b>{rsid}</b>", ""]
    if error:
        lines.extend(["Не удалось прочитать raw-файл.", "", "Попробуйте позже или загрузите raw-файл заново."])
    elif found:
        lines.extend(
            [
                f"Genotype: <b>{genotype}</b>",
                f"Chromosome: {html.escape(str(chromosome or ''))}",
                f"Position: {html.escape(str(position or ''))}",
                "",
                "Источник: raw-файл sample.",
            ]
        )
    else:
        lines.extend(
            [
                "SNP не найден в raw-файле.",
                "",
                "Это может зависеть от чипа, версии теста или формата raw.",
            ]
        )
    return "\n".join(lines)


def build_sample_snp_lookup_input_keyboard(sample_id: str, *, lang: str = "ru") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(_footer_rows(f"{MY_DATA_CALLBACK_PREFIX}:sample_item:{sample_id}", lang=lang))


def build_sample_snp_lookup_result_keyboard(sample_id: str, *, lang: str = "ru") -> InlineKeyboardMarkup:
    retry_label = "🔁 Check another SNP" if lang == "en" else "🔁 Проверить другой SNP"
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(retry_label, callback_data=f"{MY_DATA_CALLBACK_PREFIX}:snp:{sample_id}")],
            *_footer_rows(f"{MY_DATA_CALLBACK_PREFIX}:sample_item:{sample_id}", lang=lang),
        ]
    )


def sample_reports_text(asset: SampleAsset, *, lang: str = "ru") -> str:
    if lang == "en":
        return (
            "📊 Reports\n\n"
            f"Sample: {asset.display_name}\n\n"
            "Saved reports for this sample."
        )
    return (
        "📊 Reports\n\n"
        f"Sample: {asset.display_name}\n\n"
        "Сохранённые отчёты по этому sample."
    )


def build_sample_reports_keyboard(
    sample_id: str,
    *,
    lang: str = "ru",
    back_callback: str | None = None,
) -> InlineKeyboardMarkup:
    coordinate_label = "🧭 Coordinate spaces"
    admixture_label = "🧬 Admixture"
    matching_label = "🧩 Matching"
    modeling_label = "🧱 AdmixLab"
    traits_label = "🧾 Traits"
    haplogroups_label = "🌿 Haplogroups"
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(coordinate_label, callback_data=f"{MY_DATA_CALLBACK_PREFIX}:sample_pca_results:{sample_id}")],
            [InlineKeyboardButton(admixture_label, callback_data=f"{MY_DATA_CALLBACK_PREFIX}:sample_admixture:{sample_id}")],
            [InlineKeyboardButton(matching_label, callback_data=f"{MY_DATA_CALLBACK_PREFIX}:sample_matching:{sample_id}")],
            [InlineKeyboardButton(modeling_label, callback_data=f"{MY_DATA_CALLBACK_PREFIX}:sample_modeling:{sample_id}")],
            [InlineKeyboardButton(traits_label, callback_data=f"{MY_DATA_CALLBACK_PREFIX}:sample_traits:{sample_id}")],
            [InlineKeyboardButton(haplogroups_label, callback_data=f"{MY_DATA_CALLBACK_PREFIX}:sample_haplogroups:{sample_id}")],
            *_footer_rows(back_callback or f"{MY_DATA_CALLBACK_PREFIX}:sample_item:{sample_id}", lang=lang),
        ]
    )


def sample_saved_section_text(asset: SampleAsset, section_title: str, description: str, *, lang: str = "ru") -> str:
    sample_label = "Sample" if lang == "en" else "Sample"
    return (
        f"{section_title}\n\n"
        f"{sample_label}: {asset.display_name}\n\n"
        f"{description}"
    )


def build_sample_saved_section_keyboard(sample_id: str, *, lang: str = "ru") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(_footer_rows(f"{MY_DATA_CALLBACK_PREFIX}:sample_reports:{sample_id}", lang=lang))


def sample_matching_reports_text(asset: SampleAsset, matches: list[MatchingRecordSummary], *, lang: str = "ru") -> str:
    if lang == "en":
        lines = [
            "Matching reports",
            "",
            f"Sample: {asset.display_name}",
            f"Saved matches: {len(matches)}",
        ]
        if matches:
            lines.extend(["", "Saved pairwise matches involving this sample."])
        else:
            lines.extend(["", "No saved matching reports for this sample yet."])
        return "\n".join(lines)
    lines = [
        "Matching reports",
        "",
        f"Sample: {asset.display_name}",
        f"Saved matches: {len(matches)}",
    ]
    if matches:
        lines.extend(["", "Показаны сохраненные pairwise matches, где участвует этот sample."])
    else:
        lines.extend(["", "Пока нет сохраненных matching reports для этого sample."])
    return "\n".join(lines)


def build_sample_matching_reports_keyboard(sample_id: str, matches: list[MatchingRecordSummary], *, lang: str = "ru") -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for index, match in enumerate(matches[:10], start=1):
        rows.append([
            InlineKeyboardButton(
                f"{index}. {matching_report_button_label(sample_id, match)}",
                callback_data=f"{MY_DATA_CALLBACK_PREFIX}:sample_match:{match.match_id}",
            )
        ])
    rows.extend(_footer_rows(f"{MY_DATA_CALLBACK_PREFIX}:sample_reports:{sample_id}", lang=lang))
    return InlineKeyboardMarkup(rows)


def build_sample_matching_detail_keyboard(record: MatchingRecord, *, lang: str = "ru") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(
                f"Matches: {record.summary.left_sample_name}",
                callback_data=f"{MY_DATA_CALLBACK_PREFIX}:sample_matching:{record.summary.left_sample_id}",
            )],
            [InlineKeyboardButton(
                f"Matches: {record.summary.right_sample_name}",
                callback_data=f"{MY_DATA_CALLBACK_PREFIX}:sample_matching:{record.summary.right_sample_id}",
            )],
            *_footer_rows(f"{MY_DATA_CALLBACK_PREFIX}:sample_reports:{record.summary.left_sample_id}", lang=lang),
        ]
    )


def matching_report_button_label(sample_id: str, match: MatchingRecordSummary) -> str:
    other_name = match.right_sample_name if match.left_sample_id == sample_id else match.left_sample_name
    return f"{other_name}: {match.total_estimated_cm:.1f} cM"


def _coordinate_space_visible_title(title: object) -> str:
    clean_title = str(title or "").strip()
    if not clean_title:
        return "🧭 Coordinate spaces"
    if clean_title[:1] and not clean_title[:1].isascii():
        return clean_title
    return _COORDINATE_SPACE_VISIBLE_TITLES.get(clean_title, clean_title)


def _coordinate_report_mode_label(mode: object) -> str:
    return "популяционный обзор" if str(mode or "").strip() in {"all_populations", "populations"} else "региональный обзор"


def _coordinate_report_created_at(value: object) -> str:
    raw_value = str(value or "").strip()
    if not raw_value:
        return ""
    try:
        parsed = datetime.fromisoformat(raw_value.replace("Z", "+00:00"))
    except ValueError:
        return raw_value
    return parsed.strftime("%d.%m.%Y, %H:%M")


def _summary_value(lines: list[str], *prefixes: str) -> str:
    for line in lines:
        clean_line = str(line or "").strip()
        for prefix in prefixes:
            if clean_line.lower().startswith(prefix.lower()):
                return clean_line[len(prefix):].strip()
    return ""


def sample_coordinate_space_reports_text(asset: SampleAsset, reports: list[CoordinateSpaceResult], *, lang: str = "ru") -> str:
    if lang == "en":
        lines = [
            "🧭 Coordinate spaces",
            "",
            f"Sample: {asset.display_name}",
        ]
        if not reports:
            lines.extend(["No reports yet.", "", "Save a result from DNA Lab → Coordinates."])
        else:
            lines.extend([f"Reports: {len(reports)}", "", "Choose a saved report."])
        return "\n".join(lines)
    lines = [
        "🧭 Coordinate spaces",
        "",
        f"Sample: {asset.display_name}",
    ]
    if not reports:
        lines.extend([
            "Отчётов пока нет.",
            "",
            "Сохраните результат из раздела DNA Lab → Coordinates.",
        ])
    else:
        lines.extend([
            f"Отчётов: {len(reports)}",
            "",
            "Выберите сохранённый отчёт.",
        ])
    return "\n".join(lines)


def build_sample_coordinate_space_reports_keyboard(
    sample_id: str,
    reports: list[CoordinateSpaceResult],
    *,
    lang: str = "ru",
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for index, report in enumerate(reports[:10], start=1):
        rows.append([
            InlineKeyboardButton(
                f"{index}. {_coordinate_space_visible_title(report.title)}",
                callback_data=f"{MY_DATA_CALLBACK_PREFIX}:{COORD_REPORT_OPEN_ACTION}:{report.result_id}",
            )
        ])
    rows.extend(_footer_rows(f"{MY_DATA_CALLBACK_PREFIX}:sample_reports:{sample_id}", lang=lang))
    return InlineKeyboardMarkup(rows)


def coordinate_space_report_not_found_text(*, lang: str = "ru") -> str:
    if lang == "en":
        return "🧭 Coordinate spaces\n\nReport not found. Refresh the list."
    return "🧭 Coordinate spaces\n\nОтчёт не найден. Обновите список."


def build_coordinate_space_report_not_found_keyboard(*, lang: str = "ru") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(_footer_rows(f"{MY_DATA_CALLBACK_PREFIX}:root", lang=lang))


def coordinate_space_report_visual_caption(report: CoordinateSpaceResult) -> str:
    caption = str(getattr(report, "caption", "") or "").strip()
    if caption:
        return caption
    return coordinate_space_report_detail_text(report)


def coordinate_space_report_detail_text(report: CoordinateSpaceResult) -> str:
    summary_lines = list(report.summary_lines or [])
    sample_name = _summary_value(summary_lines, "Sample:")
    created_at = _coordinate_report_created_at(report.created_at)
    is_population = str(report.mode or "").strip() in {"all_populations", "populations"}
    lines = [_coordinate_space_visible_title(report.title), ""]
    if sample_name:
        lines.append(f"Sample: {sample_name}")
    lines.append(f"Тип: {_coordinate_report_mode_label(report.mode)}")
    if report.coordinate_system:
        lines.append(f"Система: {report.coordinate_system}")
    if created_at:
        lines.append(f"Создан: {created_at}")

    details: list[str] = []
    if is_population:
        if report.top_populations:
            details.append(f"Ближайшая популяция: {report.top_populations[0]}")
        region = _summary_value(summary_lines, "Closest cluster:", "Closest region:", "Region:")
        if region:
            details.append(f"Регион: {region}")
    else:
        closest = _summary_value(summary_lines, "Closest region:", "Closest cluster:", "Closest zone:")
        if closest:
            details.append(f"Ближайшая зона: {closest}")
    if details:
        lines.extend(["", *details])
    return "\n".join(lines)


def coordinate_space_report_delete_prompt_text() -> str:
    return "Удалить этот отчёт?"


def build_coordinate_space_report_detail_keyboard(
    report_id: str,
    sample_id: str,
    *,
    lang: str = "ru",
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🗑 Удалить отчёт", callback_data=f"{MY_DATA_CALLBACK_PREFIX}:{COORD_REPORT_DELETE_PROMPT_ACTION}:{report_id}")],
            *_footer_rows(f"{MY_DATA_CALLBACK_PREFIX}:sample_pca_results:{sample_id}", lang=lang),
        ]
    )


def build_coordinate_space_report_delete_prompt_keyboard(
    report_id: str,
    *,
    lang: str = "ru",
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ Да, удалить", callback_data=f"{MY_DATA_CALLBACK_PREFIX}:{COORD_REPORT_DELETE_CONFIRM_ACTION}:{report_id}")],
            [
                InlineKeyboardButton(t("nav.back", lang), callback_data=f"{MY_DATA_CALLBACK_PREFIX}:{COORD_REPORT_OPEN_ACTION}:{report_id}"),
                InlineKeyboardButton(t("nav.cancel", lang), callback_data="main:cancel"),
            ],
        ]
    )


def sample_coordinates_menu_text(asset: SampleAsset, *, raw_file: RawFileAsset | None, lang: str = "ru") -> str:
    raw_name = raw_file.display_name if raw_file is not None else ("raw file not found" if lang == "en" else "raw-файл не найден")
    if lang == "en":
        return (
            "Sample coordinates\n\n"
            f"Sample: {asset.display_name}\n"
            f"Source raw: {raw_name}\n\n"
            "Choose how to get coordinates for this sample."
        )
    return (
        "Координаты sample\n\n"
        f"Sample: {asset.display_name}\n"
        f"Исходный raw: {raw_name}\n\n"
        "Выберите, как получить координаты для этого sample."
    )


def build_sample_coordinates_menu_keyboard(sample_id: str, *, lang: str = "ru") -> InlineKeyboardMarkup:
    extract_label = "Extract from source raw" if lang == "en" else "Извлечь из исходного raw"
    add_label = "Add manually" if lang == "en" else "Добавить вручную"
    pick_label = "Choose from library" if lang == "en" else "Выбрать из библиотеки"
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(extract_label, callback_data=f"{MY_DATA_CALLBACK_PREFIX}:scx:{sample_id}")],
            [InlineKeyboardButton(add_label, callback_data=f"{MY_DATA_CALLBACK_PREFIX}:scm:{sample_id}")],
            [InlineKeyboardButton(pick_label, callback_data=f"{MY_DATA_CALLBACK_PREFIX}:scl:{sample_id}")],
            *_footer_rows(f"{MY_DATA_CALLBACK_PREFIX}:sample_item:{sample_id}", lang=lang),
        ]
    )


def sample_extract_coordinates_type_text(asset: SampleAsset, *, raw_file: RawFileAsset | None, lang: str = "ru") -> str:
    raw_name = raw_file.display_name if raw_file is not None else ("raw file not found" if lang == "en" else "raw-файл не найден")
    if lang == "en":
        return (
            "Extract coordinates from raw\n\n"
            f"Sample: {asset.display_name}\n"
            f"Source raw: {raw_name}\n\n"
            "Choose the coordinate type to extract."
        )
    return (
        "Извлечение координат из raw\n\n"
        f"Sample: {asset.display_name}\n"
        f"Исходный raw: {raw_name}\n\n"
        "Выберите тип координат, который нужно извлечь."
    )


def build_sample_extract_coordinates_type_keyboard(sample_id: str, *, lang: str = "ru") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("G25", callback_data=f"{MY_DATA_CALLBACK_PREFIX}:scxt:g25|{sample_id}")],
            *_footer_rows(f"{MY_DATA_CALLBACK_PREFIX}:sample_attach_coords:{sample_id}", lang=lang),
        ]
    )


def _format_coordinate_type_name(value: str) -> str:
    return format_coordinate_type(value)


def sample_add_coordinates_type_text(asset: SampleAsset, *, lang: str = "ru") -> str:
    if lang == "en":
        return (
            "Add coordinates to sample\n\n"
            f"Sample: {asset.display_name}\n\n"
            "Choose the coordinate type."
        )
    return (
        "Добавление координат к sample\n\n"
        f"Sample: {asset.display_name}\n\n"
        "Выберите тип координат."
    )


def build_sample_add_coordinates_type_keyboard(sample_id: str, *, lang: str = "ru") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("G25", callback_data=f"{MY_DATA_CALLBACK_PREFIX}:scmt:g25|{sample_id}")],
            *_footer_rows(f"{MY_DATA_CALLBACK_PREFIX}:sample_attach_coords:{sample_id}", lang=lang),
        ]
    )


def sample_add_coordinates_text(asset: SampleAsset, coordinate_type: str, *, lang: str = "ru") -> str:
    type_name = _format_coordinate_type_name(coordinate_type)
    if lang == "en":
        return (
            f"Add {type_name} to sample\n\n"
            f"Sample: {asset.display_name}\n\n"
            f"Send the {type_name} coordinates in one text message. "
            "I will save them to the library and attach them to this sample."
        )
    return (
        f"Добавление {type_name} к sample\n\n"
        f"Sample: {asset.display_name}\n\n"
        f"Пришлите {type_name}-координаты одним текстовым сообщением. "
        "Я сохраню их в библиотеке и сразу привяжу к этому sample."
    )


def build_sample_add_coordinates_keyboard(sample_id: str, *, lang: str = "ru") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(_footer_rows(f"{MY_DATA_CALLBACK_PREFIX}:sample_attach_coords:{sample_id}", lang=lang))


def sample_delete_prompt_text(asset: SampleAsset, *, lang: str = "ru") -> str:
    if lang == "en":
        return (
            "Delete sample\n\n"
            f'Delete sample "{asset.display_name}"?\n'
            "This cannot be undone."
        )
    return (
        "Удаление sample\n\n"
        f'Удалить sample "{asset.display_name}"?\n'
        "Это действие нельзя отменить."
    )


def build_sample_delete_prompt_keyboard(asset_id: str, *, lang: str = "ru") -> InlineKeyboardMarkup:
    delete_label = "Delete permanently" if lang == "en" else "Удалить навсегда"
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(delete_label, callback_data=f"{MY_DATA_CALLBACK_PREFIX}:sample_delete_confirm:{asset_id}")],
            *_footer_rows(f"{MY_DATA_CALLBACK_PREFIX}:sample_item:{asset_id}", lang=lang),
        ]
    )


def sample_rename_text(asset: SampleAsset, *, lang: str = "ru") -> str:
    if lang == "en":
        return (
            "Rename sample\n\n"
            f"Current name: {asset.display_name}\n\n"
            "Send the new name in one message."
        )
    return (
        "Переименование sample\n\n"
        f"Текущее имя: {asset.display_name}\n\n"
        "Пришлите новое имя одним сообщением."
    )


def build_sample_rename_keyboard(asset_id: str, *, lang: str = "ru") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(_footer_rows(f"{MY_DATA_CALLBACK_PREFIX}:sample_item:{asset_id}", lang=lang))


def sample_attach_coordinates_picker_text(asset: SampleAsset, coordinates: list[CoordinateAsset], *, lang: str = "ru") -> str:
    if lang == "en":
        lines = ["Choose coordinates from library", "", f"Sample: {asset.display_name}", ""]
        if not coordinates:
            lines.append("No available coordinates in the library.")
        else:
            lines.append("Choose coordinates to attach to this sample.")
        return "\n".join(lines)
    lines = ["Выбор координат из библиотеки", "", f"Sample: {asset.display_name}", ""]
    if not coordinates:
        lines.append("Нет доступных координат в библиотеке.")
    else:
        lines.append("Выберите координаты, которые нужно привязать к sample.")
    return "\n".join(lines)


def build_sample_attach_coordinates_picker_keyboard(sample_id: str, coordinates: list[CoordinateAsset], *, lang: str = "ru") -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for index, item in enumerate(coordinates[:10], start=1):
        rows.append(
            [
                InlineKeyboardButton(
                    f"{index}. {item.display_name} [{format_coordinate_type(item.coordinate_type)}]",
                    callback_data=f"{MY_DATA_CALLBACK_PREFIX}:sample_attach_coord_choose:{item.asset_id}",
                )
            ]
        )
    rows.extend(_footer_rows(f"{MY_DATA_CALLBACK_PREFIX}:sample_attach_coords:{sample_id}", lang=lang))
    return InlineKeyboardMarkup(rows)


def sample_attached_coordinates_text(asset: SampleAsset, coordinates: list[CoordinateAsset], *, lang: str = "ru") -> str:
    if lang == "en":
        lines = ["Sample coordinates", "", f"Sample: {asset.display_name}", ""]
        if not coordinates:
            lines.append("No coordinates are attached to this sample yet.")
            return "\n".join(lines)
        lines.append(f"Attached coordinates: {len(coordinates)}")
        lines.extend(["", "Choose a record below."])
        return "\n".join(lines)
    lines = ["Координаты sample", "", f"Sample: {asset.display_name}", ""]
    if not coordinates:
        lines.append("К этому sample пока не привязаны координаты.")
        return "\n".join(lines)
    lines.append(f"Привязано координат: {len(coordinates)}")
    lines.extend(["", "Выберите запись ниже."])
    return "\n".join(lines)


def build_sample_attached_coordinates_keyboard(sample_id: str, coordinates: list[CoordinateAsset], *, lang: str = "ru") -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for index, item in enumerate(coordinates[:10], start=1):
        rows.append(
            [
                InlineKeyboardButton(
                    f"{index}. {item.display_name} [{format_coordinate_type(item.coordinate_type)}]",
                    callback_data=f"{MY_DATA_CALLBACK_PREFIX}:sci:{item.asset_id}",
                )
            ]
        )
    rows.extend(
        [
            [InlineKeyboardButton("Get coordinates" if lang == "en" else "Получить координаты", callback_data=f"{MY_DATA_CALLBACK_PREFIX}:sample_attach_coords:{sample_id}")],
            *_footer_rows(f"{MY_DATA_CALLBACK_PREFIX}:sample_item:{sample_id}", lang=lang),
        ]
    )
    return InlineKeyboardMarkup(rows)


def quick_g25_result_text(target_name: str, g25_line: str, *, lang: str = "ru") -> str:
    safe_target = html.escape(target_name.strip() or "Target")
    safe_line = html.escape(g25_line.strip())
    if lang == "en":
        return f"G25 profile is ready\n\nTarget: {safe_target}\n\n<code>{safe_line}</code>"
    return f"G25-профиль готов\n\nTarget: {safe_target}\n\n<code>{safe_line}</code>"


def build_quick_g25_result_keyboard(*, lang: str = "ru") -> InlineKeyboardMarkup:
    create_sample_label = "Create Sample" if lang == "en" else "Создать Sample"
    save_vahaduo_label = "Save G25 profile" if lang == "en" else "Сохранить G25-профиль"
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(create_sample_label, callback_data=f"{MY_DATA_CALLBACK_PREFIX}:qg25_create_sample")],
            [InlineKeyboardButton(save_vahaduo_label, callback_data=f"{MY_DATA_CALLBACK_PREFIX}:qg25_save_g25_library")],
        ]
    )


def quick_g25_saved_text(target_name: str, g25_line: str, *, sample_name: str | None = None, g25_title: str | None = None, lang: str = "ru") -> str:
    safe_target = html.escape(target_name.strip() or "Target")
    safe_line = html.escape(g25_line.strip())
    if sample_name:
        safe_sample = html.escape(sample_name)
        if lang == "en":
            return f"Sample created from raw and G25\n\nSample: {safe_sample}\nTarget: {safe_target}\n\n<code>{safe_line}</code>"
        return f"Sample создан из raw и G25\n\nSample: {safe_sample}\nTarget: {safe_target}\n\n<code>{safe_line}</code>"
    if g25_title:
        safe_title = html.escape(g25_title)
        if lang == "en":
            return f"G25 profile saved\n\nTitle: {safe_title}\nTarget: {safe_target}\n\n<code>{safe_line}</code>"
        return f"G25-профиль сохранен\n\nНазвание: {safe_title}\nTarget: {safe_target}\n\n<code>{safe_line}</code>"
    if lang == "en":
        return f"G25 profile is ready\n\nTarget: {safe_target}\n\n<code>{safe_line}</code>"
    return f"G25-профиль готов\n\nTarget: {safe_target}\n\n<code>{safe_line}</code>"


def build_sample_coordinate_detail_keyboard(back_callback: str, *, lang: str = "ru") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(_footer_rows(back_callback, lang=lang))


def raw_files_text(raw_files: list[RawFileAsset] | None = None, *, lang: str = "ru") -> str:
    items = raw_files or []
    if lang == "en":
        lines = ["Raw files", "", f"Saved raw files: {len(items)}"]
        if not items:
            lines.extend(["", "No saved raw files yet."])
        return "\n".join(lines)
    lines = ["Raw files", "", f"Сохранено raw-файлов: {len(items)}"]
    if not items:
        lines.extend(["", "Пока нет сохраненных raw-файлов."])
    return "\n".join(lines)


def build_raw_files_keyboard(*, lang: str = "ru") -> InlineKeyboardMarkup:
    view_label = "Saved raw files" if lang == "en" else "Сохраненные raw-файлы"
    upload_label = "Upload raw file" if lang == "en" else "Загрузить raw-файл"
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(view_label, callback_data=f"{MY_DATA_CALLBACK_PREFIX}:raw_files_view")],
            [InlineKeyboardButton(upload_label, callback_data=f"{MY_DATA_CALLBACK_PREFIX}:raw_files_upload")],
            *_footer_rows(MY_DNA_ENTRY_CALLBACK, lang=lang),
        ]
    )


def view_raw_files_text(raw_files: list[RawFileAsset], *, lang: str = "ru") -> str:
    if lang == "en":
        lines = ["Saved raw files", "", f"Saved raw files: {len(raw_files)}"]
        if not raw_files:
            lines.extend(["", "No saved raw files yet."])
            return "\n".join(lines)
        lines.extend(["", "Choose a record below."])
        if len(raw_files) > 10:
            lines.extend(["", f"Showing the first 10 of {len(raw_files)}."])
        return "\n".join(lines)
    lines = ["Сохраненные raw-файлы", "", f"Сохранено raw-файлов: {len(raw_files)}"]
    if not raw_files:
        lines.extend(["", "Пока нет сохраненных raw-файлов."])
        return "\n".join(lines)
    lines.extend(["", "Выберите запись ниже."])
    if len(raw_files) > 10:
        lines.extend(["", f"Показаны первые 10 из {len(raw_files)}."])
    return "\n".join(lines)


def build_view_raw_files_keyboard(*, lang: str = "ru") -> InlineKeyboardMarkup:
    upload_label = "Upload raw file" if lang == "en" else "Загрузить raw-файл"
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(upload_label, callback_data=f"{MY_DATA_CALLBACK_PREFIX}:raw_files_upload")],
            *_footer_rows(MY_DNA_ENTRY_CALLBACK, lang=lang),
        ]
    )


def build_raw_file_items_keyboard(raw_files: list[RawFileAsset], *, lang: str = "ru") -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for index, item in enumerate(raw_files[:10], start=1):
        rows.append(
            [InlineKeyboardButton(f"{index}. {item.display_name}", callback_data=f"{MY_DATA_CALLBACK_PREFIX}:raw_file_item:{item.asset_id}")]
        )
    rows.extend(build_view_raw_files_keyboard(lang=lang).inline_keyboard)
    return InlineKeyboardMarkup(rows)


def upload_raw_text(*, lang: str = "ru") -> str:
    if lang == "en":
        return (
            "🧬 Upload raw\n\n"
            "Send the raw file as a document.\n"
            "I will save it to your My DNA library.\n\n"
            "If it is larger than 20 MB, send a ZIP or GZ containing the raw file."
        )
    return (
        "🧬 Загрузить raw\n\n"
        "Пришлите raw-файл документом.\n"
        "Я сохраню его в вашей библиотеке My DNA.\n\n"
        "Если файл больше 20 MB, пришлите ZIP или GZ с raw-файлом внутри."
    )


def build_upload_raw_keyboard(*, back_callback: str = f"{MY_DATA_CALLBACK_PREFIX}:samples_view", add_data_flow: bool = False, lang: str = "ru") -> InlineKeyboardMarkup:
    rows = _add_data_footer_rows(back_callback) if add_data_flow else _footer_rows(back_callback, lang=lang)
    return InlineKeyboardMarkup(rows)


def coordinates_text(coordinates: list[CoordinateAsset] | None = None, *, lang: str = "ru") -> str:
    items = coordinates or []
    if lang == "en":
        lines = ["📍 G25 profiles", "", f"Standalone coordinates: {len(items)}"]
        if not items:
            lines.extend(["", "No standalone G25 profiles yet."])
        else:
            lines.extend(["", "These G25 profiles are not attached to a sample."])
        return "\n".join(lines)
    lines = ["📍 G25-профили", "", f"Отдельные координаты: {len(items)}"]
    if not items:
        lines.extend(["", "Пока нет отдельных G25-профилей."])
    else:
        lines.extend(["", "Здесь хранятся G25-профили, не привязанные к sample."])
    return "\n".join(lines)


def build_coordinates_keyboard(*, lang: str = "ru") -> InlineKeyboardMarkup:
    view_label = "G25 profiles" if lang == "en" else "G25-профили"
    add_label = "Paste G25 manually" if lang == "en" else "Вставить G25 вручную"
    extract_label = "Get G25 coordinates" if lang == "en" else "Получить G25 координаты"
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(view_label, callback_data=f"{MY_DATA_CALLBACK_PREFIX}:coordinates_view")],
            [InlineKeyboardButton(add_label, callback_data=f"{MY_DATA_CALLBACK_PREFIX}:coordinates_add_root")],
            [InlineKeyboardButton(extract_label, callback_data=f"{MY_DATA_CALLBACK_PREFIX}:coordinates_extract_root")],
            *_footer_rows(MY_DNA_ENTRY_CALLBACK, lang=lang),
        ]
    )


def view_coordinates_text(coordinates: list[CoordinateAsset], *, lang: str = "ru") -> str:
    if lang == "en":
        lines = ["📍 G25 profiles", "", f"Standalone coordinates: {len(coordinates)}"]
        if not coordinates:
            lines.extend(["", "No standalone G25 profiles yet."])
            return "\n".join(lines)
        lines.extend(["", "These G25 profiles are not attached to a sample."])
        if len(coordinates) > 10:
            lines.extend(["", f"Showing the first 10 of {len(coordinates)}."])
        return "\n".join(lines)
    lines = ["📍 G25-профили", "", f"Отдельные координаты: {len(coordinates)}"]
    if not coordinates:
        lines.extend(["", "Пока нет отдельных G25-профилей."])
        return "\n".join(lines)
    lines.extend(["", "Здесь хранятся G25-профили, не привязанные к sample."])
    if len(coordinates) > 10:
        lines.extend(["", f"Показаны первые 10 из {len(coordinates)}."])
    return "\n".join(lines)


def build_view_coordinates_keyboard(*, lang: str = "ru", back_callback: str = MY_DNA_ENTRY_CALLBACK) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(_footer_rows(back_callback, lang=lang))


def new_g25_profile_text(*, lang: str = "ru") -> str:
    if lang == "en":
        return "➕ New G25 profile\n\nChoose how to add it:"
    return "➕ Новый G25-профиль\n\nВыберите способ добавления:"


def build_new_g25_profile_keyboard(*, lang: str = "ru") -> InlineKeyboardMarkup:
    manual_label = "✍️ Paste G25 manually" if lang == "en" else "✍️ Вставить G25 вручную"
    extract_label = "🧬 Get G25 coordinates" if lang == "en" else "🧬 Получить G25 координаты"
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(manual_label, callback_data=f"{MY_DATA_CALLBACK_PREFIX}:coordinates_add_type:g25:g25_profiles")],
            [InlineKeyboardButton(extract_label, callback_data=f"{MY_DATA_CALLBACK_PREFIX}:coordinates_extract_quick:g25_profiles")],
            *_add_data_footer_rows(f"{MY_DATA_CALLBACK_PREFIX}:coordinates_view"),
        ]
    )


def build_coordinate_items_keyboard(
    coordinates: list[CoordinateAsset],
    *,
    lang: str = "ru",
    back_callback: str = MY_DNA_ENTRY_CALLBACK,
) -> InlineKeyboardMarkup:
    new_label = "➕ New G25 profile" if lang == "en" else "➕ Новый G25-профиль"
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(new_label, callback_data=f"{MY_DATA_CALLBACK_PREFIX}:coordinates_new_profile")]
    ]
    for index, item in enumerate(coordinates[:10], start=1):
        label = _short_button_label(item.display_name)
        rows.append(
            [
                InlineKeyboardButton(
                    f"{index}. {label}",
                    callback_data=f"{MY_DATA_CALLBACK_PREFIX}:coordinate_item:{item.asset_id}",
                )
            ]
        )
    rows.extend(build_view_coordinates_keyboard(lang=lang, back_callback=back_callback).inline_keyboard)
    return InlineKeyboardMarkup(rows)


def add_coordinates_type_text(*, lang: str = "ru") -> str:
    if lang == "en":
        return (
            "Add coordinates\n\n"
            "Choose the coordinate type."
        )
    return (
        "Добавление координат\n\n"
        "Выберите тип координат."
    )


def build_add_coordinates_type_keyboard(*, lang: str = "ru") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("G25", callback_data=f"{MY_DATA_CALLBACK_PREFIX}:coordinates_add_type:g25")],
            *_footer_rows(f"{MY_DATA_CALLBACK_PREFIX}:coordinates_view", lang=lang),
        ]
    )


def add_coordinates_text(coordinate_type: str, *, lang: str = "ru") -> str:
    type_name = _format_coordinate_type_name(coordinate_type)
    if lang == "en":
        if type_name == "G25":
            return (
                "✍️ Paste G25 manually\n\n"
                "Send the G25 coordinates in one text message.\n"
                "I will save them as a standalone G25 profile."
            )
        return (
            f"Add {type_name} coordinates\n\n"
            f"Send the {type_name} coordinates in one text message. I will save them to your library."
        )
    if type_name == "G25":
        return (
            "✍️ Вставить G25 вручную\n\n"
            "Пришлите G25-координаты одним текстовым сообщением.\n"
            "Я сохраню их как отдельный G25-профиль."
        )
    return (
        f"Добавление {type_name} координат\n\n"
        f"Пришлите {type_name}-координаты одним текстовым сообщением. Я сохраню их в вашей библиотеке."
    )


def build_add_coordinates_keyboard(*, back_callback: str = f"{MY_DATA_CALLBACK_PREFIX}:coordinates_add_root", add_data_flow: bool = False, lang: str = "ru") -> InlineKeyboardMarkup:
    rows = _add_data_footer_rows(back_callback) if add_data_flow else _footer_rows(back_callback, lang=lang)
    return InlineKeyboardMarkup(rows)


def extract_coordinates_type_text(*, lang: str = "ru") -> str:
    if lang == "en":
        return (
            "Extract coordinates from raw\n\n"
            "Choose the coordinate type. Raw extraction is currently available only for G25."
        )
    return (
        "Извлечение координат из raw\n\n"
        "Выберите тип координат. Сейчас извлечение из raw доступно только для G25."
    )


def build_extract_coordinates_type_keyboard(*, lang: str = "ru") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("G25", callback_data=f"{MY_DATA_CALLBACK_PREFIX}:coordinates_extract_type:g25")],
            *_footer_rows(f"{MY_DATA_CALLBACK_PREFIX}:coordinates_view", lang=lang),
        ]
    )


def extract_coordinates_text(coordinate_type: str, *, lang: str = "ru") -> str:
    type_name = _format_coordinate_type_name(coordinate_type)
    if lang == "en":
        if type_name == "G25":
            return (
                "🧬 Get G25 coordinates\n\n"
                "Send the raw file as a document.\n"
                "I will extract G25 coordinates and show the result."
            )
        return (
            f"Extract {type_name} from raw\n\n"
            f"Send the raw file as a document. I will extract and return the {type_name} coordinate line."
        )
    if type_name == "G25":
        return (
            "🧬 Получить G25 координаты\n\n"
            "Пришлите raw-файл документом.\n"
            "Я извлеку G25-координаты и покажу результат."
        )
    return (
        f"Извлечение {type_name} из raw\n\n"
        f"Пришлите raw-файл документом. Я извлеку и верну строку {type_name}-координат."
    )


def build_extract_coordinates_keyboard(*, back_callback: str = f"{MY_DATA_CALLBACK_PREFIX}:coordinates_extract_root", add_data_flow: bool = False, lang: str = "ru") -> InlineKeyboardMarkup:
    rows = _add_data_footer_rows(back_callback) if add_data_flow else _footer_rows(back_callback, lang=lang)
    return InlineKeyboardMarkup(rows)


def results_text(*, lang: str = "ru") -> str:
    if lang == "en":
        return "Reports\n\nSaved reports are now grouped by sample."
    return "Reports\n\nСохраненные отчеты теперь сгруппированы по samples."


def build_results_keyboard(*, lang: str = "ru") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Admixture profiles", callback_data=f"{MY_DATA_CALLBACK_PREFIX}:results_admixture")],
            [InlineKeyboardButton("Haplogroups", callback_data=f"{MY_DATA_CALLBACK_PREFIX}:results_haplogroups")],
            [InlineKeyboardButton("Matches", callback_data=f"{MY_DATA_CALLBACK_PREFIX}:results_matches")],
            [InlineKeyboardButton("Reports", callback_data=f"{MY_DATA_CALLBACK_PREFIX}:results_reports")],
            *_footer_rows(MY_DNA_ENTRY_CALLBACK, lang=lang),
        ]
    )


def admixture_profiles_text(*, lang: str = "ru") -> str:
    if lang == "en":
        return "Admixture profiles\n\nSaved user admixture results will be shown here."
    return "Admixture profiles\n\nЗдесь будут сохраненные admixture-результаты пользователя."


def haplogroup_results_text(*, lang: str = "ru") -> str:
    if lang == "en":
        return "Haplogroups\n\nSaved user haplogroup results will be shown here."
    return "Haplogroups\n\nЗдесь будут сохраненные haplogroup-результаты пользователя."


def match_results_text(*, lang: str = "ru") -> str:
    if lang == "en":
        return "Matches\n\nSaved user matching results will be shown here."
    return "Matches\n\nЗдесь будут сохраненные matching-результаты пользователя."


def report_results_text(*, lang: str = "ru") -> str:
    if lang == "en":
        return "Reports\n\nSaved user reports will be shown here."
    return "Reports\n\nЗдесь будут сохраненные reports пользователя."


def build_results_leaf_keyboard(*, lang: str = "ru") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(_footer_rows(f"{MY_DATA_CALLBACK_PREFIX}:results", lang=lang))


def format_created_at(value: str) -> str:
    try:
        return datetime.fromisoformat(value).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return value


def format_coordinate_type(value: str) -> str:
    clean_value = value.strip().lower()
    if clean_value == "g25":
        return "G25"
    return clean_value.upper() if clean_value else "UNKNOWN"


def raw_file_detail_text(asset: RawFileAsset, *, linked_sample: SampleAsset | None = None, lang: str = "ru") -> str:
    size_kb = asset.size_bytes / 1024.0
    linked_sample_text = linked_sample.display_name if linked_sample is not None else ("not created" if lang == "en" else "не создан")
    if lang == "en":
        return (
            "Raw file\n\n"
            f"Name: {asset.display_name}\n"
            f"Source file: {asset.original_file_name}\n"
            f"Sample: {linked_sample_text}\n"
            f"Created: {format_created_at(asset.created_at)}\n"
            f"Size: {size_kb:.1f} KB"
        )
    return (
        "Raw-файл\n\n"
        f"Имя: {asset.display_name}\n"
        f"Исходный файл: {asset.original_file_name}\n"
        f"Sample: {linked_sample_text}\n"
        f"Создан: {format_created_at(asset.created_at)}\n"
        f"Размер: {size_kb:.1f} KB"
    )


def build_raw_file_detail_keyboard(
    asset_id: str,
    *,
    sample_id: str | None = None,
    back_callback: str | None = None,
    show_sample_link: bool = True,
    lang: str = "ru",
) -> InlineKeyboardMarkup:
    send_label = "Send file" if lang == "en" else "Отправить файл"
    open_sample_label = "Open sample" if lang == "en" else "Открыть sample"
    create_sample_label = "Create sample" if lang == "en" else "Создать sample"
    rename_label = "Rename" if lang == "en" else "Переименовать"
    delete_label = "Delete" if lang == "en" else "Удалить"
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(send_label, callback_data=f"{MY_DATA_CALLBACK_PREFIX}:raw_file_send:{asset_id}")],
    ]
    if sample_id and show_sample_link:
        rows.append([InlineKeyboardButton(open_sample_label, callback_data=f"{MY_DATA_CALLBACK_PREFIX}:sample_item:{sample_id}")])
    elif sample_id is None:
        rows.append([InlineKeyboardButton(create_sample_label, callback_data=f"{MY_DATA_CALLBACK_PREFIX}:raw_file_create_sample:{asset_id}")])
    rows.extend(
        [
            [InlineKeyboardButton(rename_label, callback_data=f"{MY_DATA_CALLBACK_PREFIX}:raw_file_rename:{asset_id}")],
            [InlineKeyboardButton(delete_label, callback_data=f"{MY_DATA_CALLBACK_PREFIX}:raw_file_delete_prompt:{asset_id}")],
            *_footer_rows(back_callback or f"{MY_DATA_CALLBACK_PREFIX}:samples_view", lang=lang),
        ]
    )
    return InlineKeyboardMarkup(rows)


def raw_file_delete_prompt_text(asset: RawFileAsset, *, linked_sample: SampleAsset | None = None, lang: str = "ru") -> str:
    if lang == "en":
        lines = ["Delete raw file", "", f'Delete raw file "{asset.display_name}"?']
        if linked_sample is not None:
            lines.extend(["", f"Cannot delete this raw file while it is attached to sample: {linked_sample.display_name}."])
        else:
            lines.extend(["", "This cannot be undone."])
        return "\n".join(lines)
    lines = ["Удаление raw-файла", "", f'Удалить raw-файл "{asset.display_name}"?']
    if linked_sample is not None:
        lines.extend(["", f"Нельзя удалить raw file, пока он привязан к sample: {linked_sample.display_name}."])
    else:
        lines.extend(["", "Это действие нельзя отменить."])
    return "\n".join(lines)


def build_raw_file_delete_prompt_keyboard(asset_id: str, *, allow_delete: bool, lang: str = "ru") -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if allow_delete:
        rows.append([InlineKeyboardButton("Delete permanently" if lang == "en" else "Удалить навсегда", callback_data=f"{MY_DATA_CALLBACK_PREFIX}:raw_file_delete_confirm:{asset_id}")])
    rows.extend(_footer_rows(f"{MY_DATA_CALLBACK_PREFIX}:raw_file_item:{asset_id}", lang=lang))
    return InlineKeyboardMarkup(rows)


def raw_file_rename_text(asset: RawFileAsset, *, lang: str = "ru") -> str:
    if lang == "en":
        return (
            "Rename raw file\n\n"
            f"Current name: {asset.display_name}\n\n"
            "Send the new name in one message."
        )
    return (
        "Переименование raw-файла\n\n"
        f"Текущее имя: {asset.display_name}\n\n"
        "Пришлите новое имя одним сообщением."
    )


def build_raw_file_rename_keyboard(asset_id: str, *, lang: str = "ru") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(_footer_rows(f"{MY_DATA_CALLBACK_PREFIX}:raw_file_item:{asset_id}", lang=lang))


def coordinate_detail_text(asset: CoordinateAsset, *, lang: str = "ru") -> str:
    display_name = html.escape(asset.display_name)
    target_name = html.escape(asset.target_name)
    input_mode = html.escape(asset.input_mode)
    created_at = html.escape(format_sample_created_at(asset.created_at))
    coordinate_line = html.escape(asset.g25_line)
    if lang == "en":
        return (
            f"<b>📍 G25 profile · {display_name}</b>\n\n"
            f"Target: {target_name}\n"
            f"Source: {input_mode}\n"
            f"Created: {created_at}\n\n"
            "━━━━━━━━━━━━━━\n"
            "<b>🧬 Coordinates</b>\n\n"
            f"<code>{coordinate_line}</code>"
        )
    return (
        f"<b>📍 G25-профиль · {display_name}</b>\n\n"
        f"Target: {target_name}\n"
        f"Источник: {input_mode}\n"
        f"Создан: {created_at}\n\n"
        "━━━━━━━━━━━━━━\n"
        "<b>🧬 Координаты</b>\n\n"
        f"<code>{coordinate_line}</code>"
    )


def build_coordinate_detail_keyboard(
    asset_id: str,
    *,
    lang: str = "ru",
    back_callback: str = f"{MY_DATA_CALLBACK_PREFIX}:coordinates_view",
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Rename" if lang == "en" else "Переименовать", callback_data=f"{MY_DATA_CALLBACK_PREFIX}:coordinate_rename:{asset_id}")],
            [InlineKeyboardButton("Delete" if lang == "en" else "Удалить", callback_data=f"{MY_DATA_CALLBACK_PREFIX}:coordinate_delete_prompt:{asset_id}")],
            *_footer_rows(back_callback, lang=lang),
        ]
    )


def coordinate_delete_prompt_text(asset: CoordinateAsset, *, lang: str = "ru") -> str:
    if lang == "en":
        return (
            "Delete coordinates\n\n"
            f'Delete coordinates "{asset.display_name}"?\n'
            "This cannot be undone."
        )
    return (
        "Удаление координат\n\n"
        f'Удалить координаты "{asset.display_name}"?\n'
        "Это действие нельзя отменить."
    )


def build_coordinate_delete_prompt_keyboard(asset_id: str, *, lang: str = "ru") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Delete permanently" if lang == "en" else "Удалить навсегда", callback_data=f"{MY_DATA_CALLBACK_PREFIX}:coordinate_delete_confirm:{asset_id}")],
            *_footer_rows(f"{MY_DATA_CALLBACK_PREFIX}:coordinate_item:{asset_id}", lang=lang),
        ]
    )


def coordinate_rename_text(asset: CoordinateAsset, *, lang: str = "ru") -> str:
    if lang == "en":
        return (
            "Rename coordinates\n\n"
            f"Current name: {asset.display_name}\n\n"
            "Send the new name in one text message."
        )
    return (
        "Переименование координат\n\n"
        f"Текущее имя: {asset.display_name}\n\n"
        "Пришлите новое имя одним текстовым сообщением."
    )


def build_coordinate_rename_keyboard(asset_id: str, *, lang: str = "ru") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(_footer_rows(f"{MY_DATA_CALLBACK_PREFIX}:coordinate_item:{asset_id}", lang=lang))
