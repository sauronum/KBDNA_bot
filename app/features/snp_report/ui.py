from __future__ import annotations

import html

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.features.my_data.storage import SampleAsset

from .domain import SnpCategorySummary, SnpReportResult, SnpRule
from .interesting import InterestingSnpAnalysis, InterestingSnpDefinition, InterestingSnpResult
from .storage import SnpReportRecord


PAGE_SIZE = 8
SNP_PAGE_SIZE = 10
CATEGORY_PAGE_SIZE = 9


def lab_root_text(samples: list[SampleAsset], rules: tuple[SnpRule, ...], *, lang: str = "ru", page: int = 0) -> str:
    categories = _category_names(rules)
    if lang == "en":
        return "\n".join(
            [
                "🧬 <b>SNP Lab</b>",
                "",
                "Choose what you want to do: check a marker, browse the SNP base, or build a category report.",
                "",
                f"Samples with raw files: <b>{len(samples)}</b>",
                f"SNP in report panel: <b>{len(rules)}</b>",
                f"Base sections: <b>{len(categories)}</b>",
            ]
        )
    return "\n".join(
        [
            "🧬 <b>SNP Lab</b>",
            "",
            "Выберите действие: быстро посмотреть интересные SNP, проверить rsID, открыть базу или собрать отчёт по категориям.",
            "",
            f"Sample с raw-файлом: <b>{len(samples)}</b>",
            f"SNP в панели отчёта: <b>{len(rules)}</b>",
            f"Разделов базы: <b>{len(categories)}</b>",
        ]
    )


def build_lab_root_keyboard(samples: list[SampleAsset], *, lang: str = "ru", page: int = 0) -> InlineKeyboardMarkup:
    if lang == "en":
        rows = [
            [InlineKeyboardButton("🧪 Interesting SNP", callback_data="snp_report:interesting")],
            [InlineKeyboardButton("🔎 Check rsID in sample", callback_data="snp_report:search")],
            [InlineKeyboardButton("📚 SNP base", callback_data="snp_report:db")],
            [InlineKeyboardButton("📊 Category report", callback_data="snp_report:report")],
            _dna_lab_footer_row(),
        ]
    else:
        rows = [
            [InlineKeyboardButton("🧪 Интересные SNP", callback_data="snp_report:interesting")],
            [InlineKeyboardButton("🔎 Проверить rsID в sample", callback_data="snp_report:search")],
            [InlineKeyboardButton("📚 База SNP", callback_data="snp_report:db")],
            [InlineKeyboardButton("📊 Отчёт по категориям", callback_data="snp_report:report")],
            _dna_lab_footer_row(),
        ]
    return InlineKeyboardMarkup(rows)


def sample_home_text(
    sample: SampleAsset,
    *,
    interesting_found: int | None = None,
    interesting_total: int | None = None,
    panel_found: int | None = None,
    panel_total: int | None = None,
    raw_records: int | None = None,
    provider_hint: str = "",
    lang: str = "ru",
) -> str:
    provider = provider_hint if provider_hint and provider_hint != "unknown" else "autosomal raw"
    if lang == "en":
        lines = [
            "🧬 <b>SNP Lab</b>",
            "",
            f"Sample: <b>{html.escape(sample.display_name)}</b>",
            "Raw file is connected.",
        ]
        if raw_records is not None:
            lines.extend([f"Raw format: <b>{html.escape(provider)}</b>", f"Records in raw: <b>{raw_records}</b>"])
        if interesting_found is not None and interesting_total is not None and panel_found is not None and panel_total is not None:
            lines.extend(["", f"Interesting SNP: <b>{interesting_found}</b> / {interesting_total}", f"Category panel: <b>{panel_found}</b> / {panel_total}"])
        lines.extend(["", "Choose an action."])
        return "\n".join(lines)

    lines = [
            "🧬 <b>SNP Lab</b>",
            "",
            f"Sample: <b>{html.escape(sample.display_name)}</b>",
            "Raw-файл подключен.",
    ]
    if raw_records is not None:
        lines.extend([f"Формат raw: <b>{html.escape(provider)}</b>", f"Записей в raw: <b>{raw_records}</b>"])
    if interesting_found is not None and interesting_total is not None and panel_found is not None and panel_total is not None:
        lines.extend(["", f"Интересные SNP: <b>{interesting_found}</b> из {interesting_total}", f"Панель категорий: <b>{panel_found}</b> из {panel_total}"])
    lines.extend(["", "Выберите действие для этого sample."])
    return "\n".join(lines)


def build_sample_home_keyboard(sample_id: str, *, lang: str = "ru") -> InlineKeyboardMarkup:
    interesting_label = "🧪 Interesting SNP" if lang == "en" else "🧪 Интересные SNP"
    search_label = "🔎 Check rsID in sample" if lang == "en" else "🔎 Проверить rsID в sample"
    report_label = "📊 Category report" if lang == "en" else "📊 Отчёт по категориям"
    db_label = "📚 Open SNP base" if lang == "en" else "📚 Открыть базу SNP"
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(interesting_label, callback_data=f"snp_report:interesting_sample:{sample_id}")],
            [InlineKeyboardButton(search_label, callback_data=f"snp_report:search_sample:{sample_id}")],
            [InlineKeyboardButton(report_label, callback_data=f"snp_report:run:{sample_id}")],
            [InlineKeyboardButton(db_label, callback_data="snp_report:db")],
            _back_cancel_row("snp_report:root"),
        ]
    )


def report_picker_text(samples: list[SampleAsset], *, lang: str = "ru", page: int = 0) -> str:
    total_pages = _total_pages(samples, PAGE_SIZE)
    page = _clamp_page(page, total_pages)
    if lang == "en":
        lines = [
            "🧾 <b>SNP отчёт</b>",
            "",
            "Choose a sample with a raw file.",
        ]
        if samples:
            lines.append(f"Page {page + 1}/{total_pages}.")
        else:
            lines.extend(["", "No samples with raw files yet."])
        return "\n".join(lines)

    lines = [
        "🧾 <b>SNP отчёт</b>",
        "",
        "Выберите sample с raw-файлом.",
    ]
    if samples:
        lines.append(f"Страница {page + 1}/{total_pages}.")
    else:
        lines.extend(["", "Пока нет sample с raw-файлом."])
    return "\n".join(lines)


def build_report_picker_keyboard(samples: list[SampleAsset], *, lang: str = "ru", page: int = 0) -> InlineKeyboardMarkup:
    return _sample_picker_keyboard(samples, action="run", page_action="report_page", page=page, back_callback="snp_report:root")


def interesting_picker_text(panel: tuple[InterestingSnpDefinition, ...], *, lang: str = "ru", page: int = 0) -> str:
    total_pages = _total_pages(panel, PAGE_SIZE)
    page = _clamp_page(page, total_pages)
    if lang == "en":
        lines = [
            "🧪 <b>Interesting SNP</b>",
            "",
            "Choose a topic first, then choose a sample.",
            "The result will show this sample's genotype and a short interpretation.",
        ]
        if panel:
            lines.append(f"Page {page + 1}/{total_pages}.")
        else:
            lines.extend(["", "No ready interesting SNP yet."])
        return "\n".join(lines)

    lines = [
        "🧪 <b>Интересные SNP</b>",
        "",
        "Сначала выберите интересный SNP, потом sample.",
        "Так сразу понятно, какой признак вы смотрите и какой генотип найден.",
    ]
    if panel:
        lines.append(f"Страница {page + 1}/{total_pages}.")
    else:
        lines.extend(["", "Пока нет готовых интересных SNP."])
    return "\n".join(lines)


def build_interesting_picker_keyboard(panel: tuple[InterestingSnpDefinition, ...], *, lang: str = "ru", page: int = 0) -> InlineKeyboardMarkup:
    total_pages = _total_pages(panel, PAGE_SIZE)
    page = _clamp_page(page, total_pages)
    start = page * PAGE_SIZE
    visible_items = panel[start:start + PAGE_SIZE]
    rows = [
        [InlineKeyboardButton(_interesting_definition_button_label(item), callback_data=f"snp_report:interesting_snp:{item.rsid}")]
        for item in visible_items
    ]
    _append_page_nav(rows, page=page, total_pages=total_pages, callback_prefix="snp_report:interesting_page")
    rows.append(_back_cancel_row("snp_report:root"))
    return InlineKeyboardMarkup(rows)


def interesting_sample_picker_text(definition: InterestingSnpDefinition, samples: list[SampleAsset], *, lang: str = "ru", page: int = 0) -> str:
    total_pages = _total_pages(samples, PAGE_SIZE)
    page = _clamp_page(page, total_pages)
    if lang == "en":
        lines = [
            "🧪 <b>Interesting SNP</b>",
            "",
            f"<code>{html.escape(definition.rsid)}</code> · <b>{html.escape(definition.title)}</b>",
            f"Gene/locus: <b>{html.escape(definition.gene)}</b>",
            f"Category: <b>{html.escape(definition.category)}</b>",
            "",
            "Choose a sample with a raw file.",
        ]
        if samples:
            lines.append(f"Page {page + 1}/{total_pages}.")
        else:
            lines.extend(["", "No samples with raw files yet."])
        return "\n".join(lines)

    lines = [
        "🧪 <b>Интересные SNP</b>",
        "",
        f"<code>{html.escape(definition.rsid)}</code> · <b>{html.escape(definition.title)}</b>",
        f"Gene/locus: <b>{html.escape(definition.gene)}</b>",
        f"Категория: <b>{html.escape(definition.category)}</b>",
        "",
        "Выберите sample с raw-файлом.",
    ]
    if samples:
        lines.append(f"Страница {page + 1}/{total_pages}.")
    else:
        lines.extend(["", "Пока нет sample с raw-файлом."])
    return "\n".join(lines)


def build_interesting_sample_picker_keyboard(definition: InterestingSnpDefinition, samples: list[SampleAsset], *, lang: str = "ru", page: int = 0) -> InlineKeyboardMarkup:
    return _sample_picker_keyboard(
        samples,
        action=f"interesting_snp_sample:{definition.rsid}",
        page_action=f"interesting_snp_page:{definition.rsid}",
        page=page,
        back_callback="snp_report:interesting",
    )


def interesting_running_text(sample: SampleAsset, *, lang: str = "ru") -> str:
    if lang == "en":
        return f"🧪 Interesting SNP\n\nAnalyzing: <b>{html.escape(sample.display_name)}</b>"
    return f"🧪 Интересные SNP\n\nАнализирую: <b>{html.escape(sample.display_name)}</b>"


def interesting_result_text(analysis: InterestingSnpAnalysis, *, lang: str = "ru") -> str:
    category_lines = _interesting_category_lines(analysis.results, lang=lang)
    if lang == "en":
        lines = [
            "🧪 <b>Interesting SNP</b>",
            "",
            f"Sample: <b>{html.escape(analysis.sample_name)}</b>",
            f"Interpreted: <b>{analysis.found}</b> / {analysis.total}",
        ]
        if analysis.unsupported:
            lines.append(f"Found without interpretation: <b>{analysis.unsupported}</b>")
        if analysis.missing:
            lines.append(f"Not found in raw: <b>{analysis.missing}</b>")
        if category_lines:
            lines.extend(["", "<b>By section</b>", *category_lines])
        lines.extend(["", "<b>Found</b>"])
        lines.extend(_interesting_result_lines(analysis.results, lang=lang))
        lines.append("Open cards for descriptions, limits, and sources.")
        return "\n".join(lines)

    lines = [
        "🧪 <b>Интересные SNP</b>",
        "",
        f"Sample: <b>{html.escape(analysis.sample_name)}</b>",
        f"С трактовкой: <b>{analysis.found}</b> из {analysis.total}",
    ]
    if analysis.unsupported:
        lines.append(f"Найдено без трактовки: <b>{analysis.unsupported}</b>")
    if analysis.missing:
        lines.append(f"Не найдено в raw: <b>{analysis.missing}</b>")
    if category_lines:
        lines.extend(["", "<b>По разделам</b>", *category_lines])
    lines.extend(["", "<b>Найдено</b>"])
    lines.extend(_interesting_result_lines(analysis.results, lang=lang))
    lines.append("Карточки ниже: описание, ограничения и источники.")
    return "\n".join(lines)


def build_interesting_result_keyboard(*, lang: str = "ru") -> InlineKeyboardMarkup:
    another_label = "👤 Another sample" if lang == "en" else "👤 Другой sample"
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(another_label, callback_data="snp_report:interesting")],
            _back_cancel_row("snp_report:root"),
        ]
    )


def build_interesting_result_keyboard_for_analysis(analysis: InterestingSnpAnalysis, *, lang: str = "ru") -> InlineKeyboardMarkup:
    detail_items = [item for item in analysis.results if item.status == "ok"]
    rows = []
    if detail_items:
        details_label = f"▶️ Cards ({len(detail_items)})" if lang == "en" else f"▶️ Смотреть карточки ({len(detail_items)})"
        rows.append([InlineKeyboardButton(details_label, callback_data=f"snp_report:intdetail:{analysis.sample_id}:{detail_items[0].rsid}")])
    another_label = "👤 Another sample" if lang == "en" else "👤 Другой sample"
    db_label = "📚 SNP base" if lang == "en" else "📚 База SNP"
    rows.extend(
        [
            [InlineKeyboardButton(db_label, callback_data="snp_report:db")],
            [InlineKeyboardButton(another_label, callback_data="snp_report:interesting")],
            _back_cancel_row(f"snp_report:sample:{analysis.sample_id}"),
        ]
    )
    return InlineKeyboardMarkup(rows)


def build_interesting_single_result_keyboard(
    sample_id: str,
    rsid: str,
    *,
    rule_index: int | None = None,
    lang: str = "ru",
) -> InlineKeyboardMarkup:
    rows = []
    other_sample_label = "👤 Another sample" if lang == "en" else "👤 Другой sample"
    other_snp_label = "🧪 Other SNP" if lang == "en" else "🧪 Другой SNP"
    rows.append([InlineKeyboardButton(other_sample_label, callback_data=f"snp_report:interesting_rsid:{rsid}")])
    rows.append([InlineKeyboardButton(other_snp_label, callback_data="snp_report:interesting")])
    if rule_index is not None:
        db_label = "📚 Open in SNP base" if lang == "en" else "📚 Открыть в базе SNP"
        rows.append([InlineKeyboardButton(db_label, callback_data=f"snp_report:dbsnp:{rule_index}:0:0")])
    rows.append(_back_cancel_row(f"snp_report:interesting_rsid:{rsid}"))
    return InlineKeyboardMarkup(rows)


def interesting_detail_text(
    item: InterestingSnpResult,
    sample_name: str,
    *,
    position: int | None = None,
    total: int | None = None,
    lang: str = "ru",
) -> str:
    progress = _interesting_detail_progress(position, total)
    if lang == "en":
        lines = [
            "🧪 <b>Interesting SNP</b>",
            "",
            f"<code>{html.escape(item.rsid)}</code> · <b>{html.escape(item.title)}</b>",
            f"Gene/locus: <b>{html.escape(item.gene)}</b>",
            f"Category: <b>{html.escape(item.category)}</b>",
            f"Sample: <b>{html.escape(sample_name)}</b>",
        ]
        if progress:
            lines.append(f"Card: <b>{progress}</b>")
        lines.extend(
            [
                "",
                f"Genotype: <b>{html.escape(item.genotype)}</b>",
                f"Result: <b>{html.escape(item.interpretation)}</b>",
            ]
        )
        if item.description:
            lines.extend(["", "<b>What it means</b>", html.escape(item.description)])
        if item.limitations:
            lines.extend(["", f"Limit: {html.escape(item.limitations)}"])
        if item.source_notes:
            lines.extend(["", html.escape(item.source_notes)])
        if item.sources:
            lines.append("")
            lines.append("Sources:")
            for source in item.sources[:3]:
                title = html.escape(source.title or source.url)
                url = html.escape(source.url, quote=True)
                lines.append(f'• <a href="{url}">{title}</a>')
        return "\n".join(lines)

    lines = [
        "🧪 <b>Интересные SNP</b>",
        "",
        f"<code>{html.escape(item.rsid)}</code> · <b>{html.escape(item.title)}</b>",
        f"Gene/locus: <b>{html.escape(item.gene)}</b>",
        f"Категория: <b>{html.escape(item.category)}</b>",
        f"Sample: <b>{html.escape(sample_name)}</b>",
    ]
    if progress:
        lines.append(f"Карточка: <b>{progress}</b>")
    lines.extend(
        [
            "",
            f"Генотип sample: <b>{html.escape(item.genotype)}</b>",
            f"Итог: <b>{html.escape(item.interpretation)}</b>",
        ]
    )
    if item.description:
        lines.extend(["", "<b>Что это значит</b>", html.escape(item.description)])
    if item.limitations:
        lines.extend(["", f"Ограничение: {html.escape(item.limitations)}"])
    if item.source_notes:
        lines.extend(["", html.escape(item.source_notes)])
    if item.sources:
        lines.append("")
        lines.append("Источники:")
        for source in item.sources[:3]:
            title = html.escape(source.title or source.url)
            url = html.escape(source.url, quote=True)
            lines.append(f'• <a href="{url}">{title}</a>')
    return "\n".join(lines)


def build_interesting_detail_keyboard(
    sample_id: str,
    rsid: str,
    *,
    rule_index: int | None = None,
    previous_rsid: str | None = None,
    next_rsid: str | None = None,
    lang: str = "ru",
) -> InlineKeyboardMarkup:
    rows = []
    nav_row = []
    if previous_rsid:
        nav_row.append(InlineKeyboardButton("◀️ Previous" if lang == "en" else "◀️ Предыдущая", callback_data=f"snp_report:intdetail:{sample_id}:{previous_rsid}"))
    if next_rsid:
        nav_row.append(InlineKeyboardButton("Next ▶️" if lang == "en" else "Следующая ▶️", callback_data=f"snp_report:intdetail:{sample_id}:{next_rsid}"))
    if nav_row:
        rows.append(nav_row)
    summary_label = "↩️ Summary" if lang == "en" else "↩️ Сводка"
    rows.append([InlineKeyboardButton(summary_label, callback_data=f"snp_report:interesting_sample:{sample_id}")])
    if rule_index is not None:
        db_label = "📚 Open in SNP base" if lang == "en" else "📚 Открыть в базе SNP"
        rows.append([InlineKeyboardButton(db_label, callback_data=f"snp_report:dbsnp:{rule_index}:0:0")])
    other_label = "👤 Check another sample" if lang == "en" else "👤 Проверить в другом sample"
    rows.append([InlineKeyboardButton(other_label, callback_data=f"snp_report:interesting_rsid:{rsid}")])
    rows.append(_back_cancel_row(f"snp_report:sample:{sample_id}"))
    return InlineKeyboardMarkup(rows)


def search_picker_text(samples: list[SampleAsset], *, lang: str = "ru", page: int = 0, prefill_rsid: str = "") -> str:
    total_pages = _total_pages(samples, PAGE_SIZE)
    page = _clamp_page(page, total_pages)
    if lang == "en":
        lines = [
            "🔎 <b>Поиск SNP</b>",
            "",
            f"Choose the sample where <code>{html.escape(prefill_rsid)}</code> should be checked."
            if prefill_rsid else
            "Choose the sample where SNP should be checked.",
        ]
        if samples:
            lines.append(f"Page {page + 1}/{total_pages}.")
        else:
            lines.extend(["", "No samples with raw files yet."])
        return "\n".join(lines)

    lines = [
        "🔎 <b>Поиск SNP</b>",
        "",
        f"Выберите sample, в котором нужно проверить <code>{html.escape(prefill_rsid)}</code>."
        if prefill_rsid else
        "Выберите sample, в котором нужно проверить SNP.",
    ]
    if samples:
        lines.append(f"Страница {page + 1}/{total_pages}.")
    else:
        lines.extend(["", "Пока нет sample с raw-файлом."])
    return "\n".join(lines)


def build_search_picker_keyboard(samples: list[SampleAsset], *, lang: str = "ru", page: int = 0, prefill_rsid: str = "") -> InlineKeyboardMarkup:
    action = f"search_rsid_sample:{prefill_rsid}" if prefill_rsid else "search_sample"
    page_action = f"search_rsid_page:{prefill_rsid}" if prefill_rsid else "search_page"
    return _sample_picker_keyboard(
        samples,
        action=action,
        page_action=page_action,
        page=page,
        back_callback="snp_report:root",
    )


def search_input_text(sample: SampleAsset, *, lang: str = "ru") -> str:
    if lang == "en":
        return "\n".join(
            [
                "🔎 <b>Поиск SNP</b>",
                "",
                f"Sample: <b>{html.escape(sample.display_name)}</b>",
                "",
                "Send rsID in one message, for example: <code>rs4988235</code>",
            ]
        )
    return "\n".join(
        [
            "🔎 <b>Поиск SNP</b>",
            "",
            f"Sample: <b>{html.escape(sample.display_name)}</b>",
            "",
            "Пришлите rsID одним сообщением, например: <code>rs4988235</code>",
        ]
    )


def search_invalid_text(*, lang: str = "ru") -> str:
    if lang == "en":
        return "🔎 <b>Поиск SNP</b>\n\nSend rsID in the format <code>rs4988235</code>."
    return "🔎 <b>Поиск SNP</b>\n\nПришлите rsID в формате <code>rs4988235</code>."


def search_no_raw_text(sample: SampleAsset, *, lang: str = "ru") -> str:
    if lang == "en":
        return f"🔎 <b>Поиск SNP</b>\n\nSample <b>{html.escape(sample.display_name)}</b> has no raw file."
    return f"🔎 <b>Поиск SNP</b>\n\nУ sample <b>{html.escape(sample.display_name)}</b> нет raw-файла."


def search_result_text(sample: SampleAsset, result: object, *, rule: SnpRule | None = None, lang: str = "ru") -> str:
    rsid = html.escape(str(getattr(result, "rsid", "") or ""))
    genotype = html.escape(str(getattr(result, "genotype", "") or "--"))
    chromosome = getattr(result, "chromosome", None)
    position = getattr(result, "position", None)
    found = bool(getattr(result, "found", False))
    error = getattr(result, "error", None)
    sample_name = html.escape(sample.display_name)
    rule_title = _rule_title(rule) if rule is not None else ""
    status = _panel_status_for_genotype(str(getattr(result, "genotype", "") or ""), rule.normal_genotype) if rule is not None and found else ""

    if lang == "en":
        lines = ["🔎 <b>SNP in sample</b>", ""]
        if rule is not None:
            lines.extend([f"<code>{rsid}</code> · <b>{html.escape(rule_title)}</b>"])
            if rule.gene:
                lines.append(f"Gene/locus: <b>{html.escape(rule.gene)}</b>")
            lines.append(f"Section: <b>{html.escape(rule.category)}</b>")
        else:
            lines.append(f"SNP: <b>{rsid}</b>")
        lines.extend([f"Sample: <b>{sample_name}</b>", ""])
        if error:
            lines.extend(["Could not read the raw file.", "", "Try again later or upload the raw file again."])
        elif found:
            lines.extend(
                [
                    f"Genotype: <b>{genotype}</b>",
                ]
            )
            if rule is not None:
                lines.extend(
                    [
                        f"Panel norm: <code>{html.escape(rule.normal_genotype)}</code>",
                        f"Panel status: <b>{html.escape(_panel_status_label(status, lang=lang))}</b>",
                    ]
                )
            if chromosome or position:
                lines.extend(["", f"Chromosome: {html.escape(str(chromosome or ''))}", f"Position: {html.escape(str(position or ''))}"])
        else:
            if rule is not None:
                lines.extend(["This SNP has a base card, but it was not found in this sample raw file.", "", "This can depend on the chip, test version, or raw format."])
            else:
                lines.extend(["SNP was not found in the raw file.", "", "This can depend on the chip, test version, or raw format."])
        return "\n".join(lines)

    lines = ["🔎 <b>SNP в sample</b>", ""]
    if rule is not None:
        lines.extend([f"<code>{rsid}</code> · <b>{html.escape(rule_title)}</b>"])
        if rule.gene:
            lines.append(f"Gene/locus: <b>{html.escape(rule.gene)}</b>")
        lines.append(f"Раздел: <b>{html.escape(rule.category)}</b>")
    else:
        lines.append(f"SNP: <b>{rsid}</b>")
    lines.extend([f"Sample: <b>{sample_name}</b>", ""])
    if error:
        lines.extend(["Не удалось прочитать raw-файл.", "", "Попробуйте позже или загрузите raw-файл заново."])
    elif found:
        lines.extend(
            [
                f"Генотип sample: <b>{genotype}</b>",
            ]
        )
        if rule is not None:
            lines.extend(
                [
                    f"Норма панели: <code>{html.escape(rule.normal_genotype)}</code>",
                    f"Статус в панели: <b>{html.escape(_panel_status_label(status, lang=lang))}</b>",
                ]
            )
        if chromosome or position:
            lines.extend(["", f"Chromosome: {html.escape(str(chromosome or ''))}", f"Position: {html.escape(str(position or ''))}"])
    else:
        if rule is not None:
            lines.extend(["Карточка SNP есть в базе, но в raw этого sample rsID не найден.", "", "Это может зависеть от чипа, версии теста или формата raw."])
        else:
            lines.extend(["SNP не найден в raw-файле.", "", "Это может зависеть от чипа, версии теста или формата raw."])
    return "\n".join(lines)


def build_search_input_keyboard(sample_id: str, *, lang: str = "ru") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            _back_cancel_row("snp_report:search"),
        ]
    )


def build_search_result_keyboard(sample_id: str, *, lang: str = "ru") -> InlineKeyboardMarkup:
    return build_search_result_keyboard_for_rule(sample_id, rule_index=None, lang=lang)


def build_search_result_keyboard_for_rule(sample_id: str, *, rule_index: int | None, lang: str = "ru") -> InlineKeyboardMarkup:
    retry_label = "🔁 Check another SNP" if lang == "en" else "🔁 Проверить другой SNP"
    another_label = "👤 Another sample" if lang == "en" else "👤 Другой sample"
    card_label = "📚 Open SNP card" if lang == "en" else "📚 Открыть карточку SNP"
    rows = []
    if rule_index is not None:
        rows.append([InlineKeyboardButton(card_label, callback_data=f"snp_report:dbsnp:{rule_index}:0:0")])
    rows.extend(
        [
            [InlineKeyboardButton(retry_label, callback_data=f"snp_report:search_sample:{sample_id}")],
            [InlineKeyboardButton(another_label, callback_data="snp_report:search")],
            _back_cancel_row("snp_report:root"),
        ]
    )
    return InlineKeyboardMarkup(rows)


def db_root_text(rules: tuple[SnpRule, ...], *, lang: str = "ru") -> str:
    categories = _category_names(rules)
    annotated = sum(1 for rule in rules if rule.description or rule.gene or rule.title)
    if lang == "en":
        return "\n".join(
            [
                "📚 <b>SNP base</b>",
                "",
                f"SNP in panel: <b>{len(rules)}</b>",
                f"Annotated cards: <b>{annotated}</b>",
                f"Categories: <b>{len(categories)}</b>",
                "",
                "Choose a search mode. rsID is exact, gene/locus is broader, categories are for browsing.",
            ]
        )
    return "\n".join(
        [
            "📚 <b>База SNP</b>",
            "",
            f"SNP в панели: <b>{len(rules)}</b>",
            f"Карточек с описанием: <b>{annotated}</b>",
            f"Разделов: <b>{len(categories)}</b>",
            "",
            "Выберите режим поиска. rsID — точный поиск, gene/locus — шире, разделы — для просмотра панели.",
        ]
    )


def build_db_root_keyboard(*, lang: str = "ru") -> InlineKeyboardMarkup:
    rsid_label = "🔎 Find rsID" if lang == "en" else "🔎 Найти rsID"
    gene_label = "🧬 Find gene/locus" if lang == "en" else "🧬 Найти gene/locus"
    cats_label = "📂 Base sections" if lang == "en" else "📂 Разделы базы"
    popular_label = "⭐ Popular SNP" if lang == "en" else "⭐ Популярные SNP"
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(rsid_label, callback_data="snp_report:db_search")],
            [InlineKeyboardButton(gene_label, callback_data="snp_report:db_gene")],
            [InlineKeyboardButton(cats_label, callback_data="snp_report:dbcats")],
            [InlineKeyboardButton(popular_label, callback_data="snp_report:dbpopular")],
            _back_cancel_row("snp_report:root"),
        ]
    )


def db_search_input_text(*, mode: str, lang: str = "ru") -> str:
    if mode == "gene":
        if lang == "en":
            return "🧬 <b>Find gene/locus</b>\n\nSend a gene or locus, for example: <code>COMT</code>, <code>LCT</code>, <code>HLA</code>."
        return "🧬 <b>Поиск по gene/locus</b>\n\nПришлите gene или locus, например: <code>COMT</code>, <code>LCT</code>, <code>HLA</code>."
    if lang == "en":
        return "🔎 <b>Find rsID</b>\n\nSend an exact rsID, for example: <code>rs4988235</code>."
    return "🔎 <b>Поиск по rsID</b>\n\nПришлите точный rsID, например: <code>rs4988235</code>."


def build_db_search_input_keyboard(*, lang: str = "ru") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([_back_cancel_row("snp_report:db")])


def db_gene_results_text(query: str, matches: list[tuple[int, SnpRule]], *, lang: str = "ru", page: int = 0) -> str:
    total_pages = _total_pages(matches, SNP_PAGE_SIZE)
    page = _clamp_page(page, total_pages)
    if lang == "en":
        lines = ["🧬 <b>Find gene/locus</b>", "", f"Query: <code>{html.escape(query)}</code>", f"Found: <b>{len(matches)}</b>"]
        if matches:
            lines.append(f"Page {page + 1}/{total_pages}.")
        else:
            lines.extend(["", "No matching SNP cards. Try another gene/locus or use exact rsID search."])
        return "\n".join(lines)
    lines = ["🧬 <b>Поиск по gene/locus</b>", "", f"Запрос: <code>{html.escape(query)}</code>", f"Найдено: <b>{len(matches)}</b>"]
    if matches:
        lines.append(f"Страница {page + 1}/{total_pages}.")
    else:
        lines.extend(["", "Подходящих SNP-карточек не найдено. Попробуйте другой gene/locus или точный rsID."])
    return "\n".join(lines)


def build_db_gene_results_keyboard(
    query: str,
    matches: list[tuple[int, SnpRule]],
    *,
    lang: str = "ru",
    page: int = 0,
) -> InlineKeyboardMarkup:
    total_pages = _total_pages(matches, SNP_PAGE_SIZE)
    page = _clamp_page(page, total_pages)
    start = page * SNP_PAGE_SIZE
    visible = matches[start:start + SNP_PAGE_SIZE]
    rows = [
        [InlineKeyboardButton(_gene_result_button_label(rule), callback_data=f"snp_report:dbsnp:{rule_index}:0:0")]
        for rule_index, rule in visible
    ]
    _append_page_nav(rows, page=page, total_pages=total_pages, callback_prefix=f"snp_report:dbgene_page:{query}")
    rows.append(_back_cancel_row("snp_report:db"))
    return InlineKeyboardMarkup(rows)


def db_rsid_not_found_text(rsid: str, *, lang: str = "ru") -> str:
    rsid_text = html.escape(rsid)
    if lang == "en":
        return "\n".join(
            [
                "📚 <b>SNP base</b>",
                "",
                f"<code>{rsid_text}</code> was not found in the current SNP base.",
                "",
                "You can still check this rsID in a sample raw file, or try gene/locus search.",
            ]
        )
    return "\n".join(
        [
            "📚 <b>База SNP</b>",
            "",
            f"<code>{rsid_text}</code> не найден в текущей SNP-базе.",
            "",
            "Его всё равно можно проверить в raw sample или попробовать поиск по gene/locus.",
        ]
    )


def build_db_rsid_not_found_keyboard(rsid: str, *, lang: str = "ru") -> InlineKeyboardMarkup:
    check_label = "🧬 Check in sample" if lang == "en" else "🧬 Проверить в sample"
    gene_label = "🧬 Search gene/locus" if lang == "en" else "🧬 Поиск gene/locus"
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(check_label, callback_data=f"snp_report:search_rsid_page:{rsid}:0")],
            [InlineKeyboardButton(gene_label, callback_data="snp_report:db_gene")],
            _back_cancel_row("snp_report:db"),
        ]
    )


def popular_snps_text(*, lang: str = "ru") -> str:
    if lang == "en":
        return "⭐ <b>Popular SNP</b>\n\nSimple, commonly requested SNP cards from the current base."
    return "⭐ <b>Популярные SNP</b>\n\nПростые и часто запрашиваемые SNP-карточки из текущей базы."


def build_popular_snps_keyboard(rules: tuple[SnpRule, ...], *, lang: str = "ru") -> InlineKeyboardMarkup:
    popular = ["rs4988235", "rs17822931", "rs12913832", "rs1426654", "rs1805007", "rs1815739", "rs4680", "rs1801133"]
    by_rsid = {rule.rsid: (index, rule) for index, rule in enumerate(rules)}
    rows = []
    for rsid in popular:
        item = by_rsid.get(rsid)
        if item is None:
            continue
        rule_index, rule = item
        rows.append([InlineKeyboardButton(_gene_result_button_label(rule), callback_data=f"snp_report:dbsnp:{rule_index}:0:0")])
    rows.append(_back_cancel_row("snp_report:db"))
    return InlineKeyboardMarkup(rows)


def db_categories_text(rules: tuple[SnpRule, ...], *, lang: str = "ru") -> str:
    categories = _category_names(rules)
    if lang == "en":
        return "\n".join(
            [
                "📚 <b>SNP база</b>",
                "",
                f"SNP in panel: <b>{len(rules)}</b>",
                f"Categories: <b>{len(categories)}</b>",
                "",
                "Sections with richer cards are shown first.",
            ]
        )
    return "\n".join(
        [
            "📚 <b>SNP база</b>",
            "",
            f"SNP в панели: <b>{len(rules)}</b>",
            f"Разделов: <b>{len(categories)}</b>",
            "",
            "Сначала показаны разделы, где больше полезных карточек.",
        ]
    )


def build_db_categories_keyboard(rules: tuple[SnpRule, ...], *, lang: str = "ru", page: int = 0) -> InlineKeyboardMarkup:
    categories = _category_names(rules)
    total_pages = _total_pages(categories, CATEGORY_PAGE_SIZE)
    page = _clamp_page(page, total_pages)
    start = page * CATEGORY_PAGE_SIZE
    visible = categories[start:start + CATEGORY_PAGE_SIZE]
    rows = [
        [InlineKeyboardButton(_category_button_label(category, rules), callback_data=f"snp_report:dbcat:{start + index}:0")]
        for index, category in enumerate(visible)
    ]
    _append_page_nav(rows, page=page, total_pages=total_pages, callback_prefix="snp_report:db_page")
    rows.append(_back_cancel_row("snp_report:root"))
    return InlineKeyboardMarkup(rows)


def db_category_text(category: str, rules: list[tuple[int, SnpRule]], *, lang: str = "ru", page: int = 0) -> str:
    total_pages = _total_pages(rules, SNP_PAGE_SIZE)
    page = _clamp_page(page, total_pages)
    if lang == "en":
        return "\n".join(
            [
                "📚 <b>SNP база</b>",
                "",
                f"Category: <b>{html.escape(category)}</b>",
                f"SNP: <b>{len(rules)}</b>",
                f"Page {page + 1}/{total_pages}.",
            ]
        )
    return "\n".join(
        [
            "📚 <b>SNP база</b>",
            "",
            f"Раздел: <b>{html.escape(category)}</b>",
            f"SNP: <b>{len(rules)}</b>",
            f"Страница {page + 1}/{total_pages}.",
        ]
    )


def build_db_category_keyboard(
    category_index: int,
    rules: list[tuple[int, SnpRule]],
    *,
    lang: str = "ru",
    page: int = 0,
) -> InlineKeyboardMarkup:
    total_pages = _total_pages(rules, SNP_PAGE_SIZE)
    page = _clamp_page(page, total_pages)
    start = page * SNP_PAGE_SIZE
    visible = rules[start:start + SNP_PAGE_SIZE]
    rows = [
        [InlineKeyboardButton(_gene_result_button_label(rule), callback_data=f"snp_report:dbsnp:{rule_index}:{category_index}:{page}")]
        for rule_index, rule in visible
    ]
    _append_page_nav(rows, page=page, total_pages=total_pages, callback_prefix=f"snp_report:dbcat:{category_index}")
    rows.append(_back_cancel_row("snp_report:db"))
    return InlineKeyboardMarkup(rows)


def db_rule_text(rule: SnpRule, *, lang: str = "ru") -> str:
    title = _rule_title(rule)
    description = str(rule.description or "").strip()
    sources = _rule_sources_line(rule, lang=lang)
    if lang == "en":
        lines = [
            "📚 <b>SNP base</b>",
            "",
            f"<code>{html.escape(rule.rsid)}</code> · <b>{html.escape(title)}</b>",
        ]
        if rule.gene:
            lines.append(f"Gene/locus: <b>{html.escape(rule.gene)}</b>")
        lines.extend(
            [
                f"Topic: <b>{html.escape(rule.category)}</b>",
                "",
                "<b>What is known</b>",
                html.escape(description) if description else "No detailed description has been added yet. This card shows the panel section and reference genotype.",
                "",
                "<b>In the panel</b>",
                f"Reference genotype: <code>{html.escape(rule.normal_genotype)}</code>",
                f"Section: <b>{html.escape(rule.category)}</b>",
                sources,
                "",
                "Reference card, not a medical interpretation.",
            ]
        )
        return "\n".join(lines)
    lines = [
            "📚 <b>SNP база</b>",
            "",
            f"<code>{html.escape(rule.rsid)}</code> · <b>{html.escape(title)}</b>",
    ]
    if rule.gene:
        lines.append(f"Gene/locus: <b>{html.escape(rule.gene)}</b>")
    lines.extend(
        [
            f"Тема: <b>{html.escape(rule.category)}</b>",
            "",
            "<b>Что известно</b>",
            html.escape(description) if description else "Подробного описания для этого SNP пока нет. Карточка показывает раздел панели и норму панели.",
            "",
            "<b>В панели</b>",
            f"Норма: <code>{html.escape(rule.normal_genotype)}</code>",
            f"Раздел: <b>{html.escape(rule.category)}</b>",
            sources,
            "",
            "Справочная карточка, не медицинский вывод.",
        ]
    )
    return "\n".join(lines)


def build_db_rule_keyboard(rule: SnpRule, rule_index: int, category_index: int, page: int, *, lang: str = "ru") -> InlineKeyboardMarkup:
    del rule
    check_label = "🧬 Check in sample" if lang == "en" else "🧬 Проверить в sample"
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(check_label, callback_data=f"snp_report:dbcheck:{rule_index}:{category_index}:{page}:0")],
            _back_cancel_row(f"snp_report:dbcat:{category_index}:{page}"),
        ]
    )


def db_rule_sample_picker_text(
    rule: SnpRule,
    samples: list[SampleAsset],
    *,
    lang: str = "ru",
    page: int = 0,
) -> str:
    total_pages = _total_pages(samples, PAGE_SIZE)
    page = _clamp_page(page, total_pages)
    if lang == "en":
        lines = [
            "🧬 <b>Check SNP in sample</b>",
            "",
            f"SNP: <code>{html.escape(rule.rsid)}</code>",
            f"Name: <b>{html.escape(_rule_title(rule))}</b>",
            "",
            "Choose a sample with a raw file.",
        ]
        if samples:
            lines.append(f"Page {page + 1}/{total_pages}.")
        else:
            lines.extend(["", "No samples with raw files yet."])
        return "\n".join(lines)

    lines = [
        "🧬 <b>Проверка SNP в sample</b>",
        "",
        f"SNP: <code>{html.escape(rule.rsid)}</code>",
        f"Название: <b>{html.escape(_rule_title(rule))}</b>",
        "",
        "Выберите sample с raw-файлом.",
    ]
    if samples:
        lines.append(f"Страница {page + 1}/{total_pages}.")
    else:
        lines.extend(["", "Пока нет sample с raw-файлом."])
    return "\n".join(lines)


def build_db_rule_sample_picker_keyboard(
    samples: list[SampleAsset],
    *,
    rule_index: int,
    category_index: int,
    rule_page: int,
    sample_page: int = 0,
) -> InlineKeyboardMarkup:
    total_pages = _total_pages(samples, PAGE_SIZE)
    sample_page = _clamp_page(sample_page, total_pages)
    start = sample_page * PAGE_SIZE
    visible_samples = samples[start:start + PAGE_SIZE]
    rows = [
        [InlineKeyboardButton(sample.display_name, callback_data=f"snp_report:dbsample:{sample.asset_id}")]
        for sample in visible_samples
    ]
    _append_page_nav(rows, page=sample_page, total_pages=total_pages, callback_prefix="snp_report:dbcheck_page")
    rows.append(_back_cancel_row(f"snp_report:dbsnp:{rule_index}:{category_index}:{rule_page}"))
    return InlineKeyboardMarkup(rows)


def db_rule_lookup_result_text(rule: SnpRule, sample: SampleAsset, result: object, *, lang: str = "ru") -> str:
    return search_result_text(sample, result, rule=rule, lang=lang)


def build_db_rule_lookup_result_keyboard(
    rule_index: int,
    category_index: int,
    rule_page: int,
    *,
    lang: str = "ru",
) -> InlineKeyboardMarkup:
    another_label = "👤 Another sample" if lang == "en" else "👤 Другой sample"
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(another_label, callback_data=f"snp_report:dbcheck:{rule_index}:{category_index}:{rule_page}:0")],
            _back_cancel_row(f"snp_report:dbsnp:{rule_index}:{category_index}:{rule_page}"),
        ]
    )


def running_text(sample: SampleAsset, *, lang: str = "ru") -> str:
    if lang == "en":
        return f"🧾 SNP отчёт\n\nCalculating report for: <b>{html.escape(sample.display_name)}</b>"
    return f"🧾 SNP отчёт\n\nСчитаю отчёт для: <b>{html.escape(sample.display_name)}</b>"


def result_text(record: SnpReportRecord, *, lang: str = "ru", visual: bool = False) -> str:
    summary = record.summary
    if visual:
        return "\n".join(
            [
                "🧾 <b>SNP отчёт</b>",
                f"Sample: <b>{html.escape(summary.sample_name)}</b>",
            ]
        )

    categories = [
        SnpCategorySummary(**item)
        for item in record.payload.get("categories", [])
        if isinstance(item, dict)
    ]
    total = max(1, summary.total_rules)
    found = total - summary.missing
    lines = [
        "🧾 <b>SNP отчёт</b>",
        "",
        f"Sample: <b>{html.escape(summary.sample_name)}</b>",
        f"SNP в панели: <b>{summary.total_rules}</b>",
        f"Найдено в raw: <b>{found}</b>",
        "",
        f"✅ Норма: <b>{summary.ok}</b>",
        f"🟡 Гетеро/вариант: <b>{summary.warn}</b>",
        f"🔴 Гомо/вариант: <b>{summary.bad}</b>",
        f"⚪ Нет данных: <b>{summary.missing}</b>",
    ]
    if categories and not visual:
        lines.extend(["", "📊 PNG-график не отправился. Подробная таблица есть в HTML."])
    return "\n".join(lines)


def build_result_keyboard(report_id: str, *, lang: str = "ru") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📄 Скачать HTML", callback_data=f"snp_report:html:{report_id}")],
            [InlineKeyboardButton("🔁 Новый SNP отчёт", callback_data="snp_report:report")],
            _back_cancel_row("snp_report:root"),
        ]
    )


def error_text(title: str, body: str) -> str:
    return f"⚠️ <b>{html.escape(title)}</b>\n\n{html.escape(body)}"


def build_error_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            _back_cancel_row("snp_report:root"),
        ]
    )


def render_html_report(result: SnpReportResult) -> str:
    categories = list(result.categories)
    rows_by_category: dict[str, list] = {}
    for row in result.rows:
        rows_by_category.setdefault(row.category, []).append(row)
    cards = _html_cards(result)
    nav = "\n".join(
        f'<a class="nav" href="#cat-{index}"><span>{html.escape(item.category)}</span><b>{item.risk_percent}%</b></a>'
        for index, item in enumerate(categories)
    )
    sections = []
    for index, category in enumerate(categories):
        rows = rows_by_category.get(category.category, [])
        table_rows = "\n".join(
            "<tr>"
            f"<td>{html.escape(row.rsid)}</td>"
            f"<td>{html.escape(_row_summary(row))}</td>"
            f"<td><span class='pill {row.status}'>{html.escape(row.user_genotype)}</span></td>"
            f"<td>{html.escape(row.normal_genotype)}</td>"
            f"<td>{_status_label(row.status)}</td>"
            "</tr>"
            for row in rows
        )
        sections.append(
            f"""
            <section id="cat-{index}">
              <div class="head">
                <h2>{html.escape(category.category)}</h2>
                <span class="risk">{category.risk_percent}%</span>
              </div>
              <div class="bar"><i style="width:{category.risk_percent}%"></i></div>
              <table>
                <thead><tr><th>SNP</th><th>Описание</th><th>Ваши аллели</th><th>Норма</th><th>Статус</th></tr></thead>
                <tbody>{table_rows}</tbody>
              </table>
            </section>
            """
        )
    return f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(result.sample_name)} — SNP Lab</title>
<style>
body{{margin:0;background:#0a0d14;color:#d8e0f5;font-family:Inter,Arial,sans-serif}}
header{{padding:34px 42px;background:linear-gradient(135deg,#0d1220,#111827);border-bottom:1px solid #23304a}}
h1{{margin:0 0 8px;font-size:30px}}.sub{{color:#7f8ba8;font-size:13px}}
.cards{{display:flex;gap:12px;flex-wrap:wrap;margin-top:22px}}.card{{background:#111827;border:1px solid #25324d;border-radius:14px;padding:14px 18px;min-width:115px}}
.num{{font-size:27px;font-weight:800}}.ok{{color:#22c55e}}.warn{{color:#eab308}}.bad{{color:#ef4444}}.missing{{color:#64748b}}
.layout{{display:grid;grid-template-columns:260px 1fr;gap:0}}aside{{position:sticky;top:0;height:100vh;overflow:auto;background:#111521;border-right:1px solid #23304a;padding:14px}}
.nav{{display:flex;justify-content:space-between;gap:8px;color:#cbd5e1;text-decoration:none;padding:8px 10px;border-radius:9px;font-size:12px}}.nav:hover{{background:#182037}}
main{{padding:24px 34px}}section{{margin-bottom:34px}}.head{{display:flex;align-items:center;gap:12px;border-bottom:1px solid #23304a;margin-bottom:10px;padding-bottom:10px}}
h2{{font-size:18px;margin:0;flex:1}}.risk{{font-weight:800;color:#93c5fd}}.bar{{height:4px;background:#1e293b;border-radius:4px;margin-bottom:12px;overflow:hidden}}.bar i{{display:block;height:100%;background:#3b82f6}}
table{{width:100%;border-collapse:collapse;background:#0f1423;border:1px solid #23304a;border-radius:12px;overflow:hidden}}th,td{{text-align:left;padding:8px 10px;border-bottom:1px solid rgba(35,48,74,.55);font-size:13px}}th{{font-size:10px;text-transform:uppercase;color:#7f8ba8;letter-spacing:.08em}}
.pill{{display:inline-block;padding:2px 8px;border-radius:99px;font-weight:800}}.pill.ok{{background:#22c55e22}}.pill.warn{{background:#eab30822}}.pill.bad{{background:#ef444422}}.pill.missing{{background:#64748b22}}
@media(max-width:800px){{.layout{{grid-template-columns:1fr}}aside{{position:static;height:auto}}header{{padding:24px}}main{{padding:18px}}}}
</style>
</head>
<body>
<header>
  <div class="sub">KBDNA · SNP Lab</div>
  <h1>{html.escape(result.sample_name)}</h1>
  <div class="sub">{result.total_rules} SNP · rule-based panel · not medical advice</div>
  {cards}
</header>
<div class="layout"><aside>{nav}</aside><main>{''.join(sections)}</main></div>
</body>
</html>"""


def _sample_picker_keyboard(
    samples: list[SampleAsset],
    *,
    action: str,
    page_action: str,
    page: int,
    back_callback: str,
) -> InlineKeyboardMarkup:
    total_pages = _total_pages(samples, PAGE_SIZE)
    page = _clamp_page(page, total_pages)
    start = page * PAGE_SIZE
    visible_samples = samples[start:start + PAGE_SIZE]
    rows = [
        [InlineKeyboardButton(sample.display_name, callback_data=f"snp_report:{action}:{sample.asset_id}")]
        for sample in visible_samples
    ]
    _append_page_nav(rows, page=page, total_pages=total_pages, callback_prefix=f"snp_report:{page_action}")
    rows.append(_back_cancel_row(back_callback))
    return InlineKeyboardMarkup(rows)


def _interesting_result_lines(results: tuple[InterestingSnpResult, ...], *, lang: str) -> list[str]:
    lines: list[str] = []
    unsupported: list[InterestingSnpResult] = []

    for item in results:
        if item.status == "missing":
            continue
        if item.status == "unsupported":
            unsupported.append(item)
            continue

        if lang == "en":
            lines.extend(
                [
                    f"• <b>{html.escape(item.title)}</b> — {html.escape(item.interpretation)}",
                    f"  <code>{html.escape(item.rsid)}</code> · {html.escape(item.gene)} · <b>{html.escape(item.genotype)}</b>",
                ]
            )
        else:
            lines.extend(
                [
                    f"• <b>{html.escape(item.title)}</b> — {html.escape(item.interpretation)}",
                    f"  <code>{html.escape(item.rsid)}</code> · {html.escape(item.gene)} · <b>{html.escape(item.genotype)}</b>",
                ]
            )
        lines.append("")

    if not lines:
        lines.append("No interpreted SNP found in this raw." if lang == "en" else "В этом raw пока нет SNP с готовой трактовкой.")
        lines.append("")

    if unsupported:
        label = "Found but not interpreted yet" if lang == "en" else "Найдено, но пока без трактовки"
        values = ", ".join(f"{item.rsid} ({item.genotype})" for item in unsupported)
        lines.extend([f"<b>{label}</b>", html.escape(values), ""])

    return lines


def _interesting_category_lines(results: tuple[InterestingSnpResult, ...], *, lang: str) -> list[str]:
    counts: dict[str, int] = {}
    for item in results:
        if item.status != "ok":
            continue
        counts[item.category] = counts.get(item.category, 0) + 1
    if not counts:
        return []
    return [
        f"• {html.escape(category)}: <b>{count}</b>"
        for category, count in sorted(counts.items(), key=lambda value: (-value[1], value[0]))
    ]


def _interesting_detail_progress(position: int | None, total: int | None) -> str:
    if position is None or total is None or position <= 0 or total <= 0:
        return ""
    return f"{position}/{total}"


def _interesting_button_label(item: InterestingSnpResult) -> str:
    title = str(item.title or item.rsid).split(":")[0].strip()
    return _short_button_label(f"ℹ️ {title}", limit=28)


def _interesting_definition_button_label(definition: InterestingSnpDefinition) -> str:
    return _short_button_label(f"{definition.title} · {definition.rsid}", limit=60)


def _short_text(value: str, limit: int) -> str:
    clean = " ".join(str(value or "").split())
    if len(clean) <= limit:
        return clean
    return clean[: max(1, limit - 1)].rstrip() + "…"


def _append_page_nav(
    rows: list[list[InlineKeyboardButton]],
    *,
    page: int,
    total_pages: int,
    callback_prefix: str,
) -> None:
    if total_pages <= 1:
        return
    nav_row: list[InlineKeyboardButton] = []
    if page > 0:
        nav_row.append(InlineKeyboardButton("⬅️", callback_data=f"{callback_prefix}:{page - 1}"))
    nav_row.append(InlineKeyboardButton(f"{page + 1}/{total_pages}", callback_data="snp_report:noop"))
    if page + 1 < total_pages:
        nav_row.append(InlineKeyboardButton("➡️", callback_data=f"{callback_prefix}:{page + 1}"))
    rows.append(nav_row)


def _category_button_label(category: str, rules: tuple[SnpRule, ...]) -> str:
    category_rules = [rule for rule in rules if rule.category == category]
    described = sum(1 for rule in category_rules if _rule_has_card_text(rule))
    return _short_button_label(f"{category} · {described}/{len(category_rules)}", limit=60)


def _category_names(rules: tuple[SnpRule, ...]) -> list[str]:
    seen: dict[str, None] = {}
    for rule in rules:
        seen.setdefault(rule.category, None)
    return sorted(seen, key=lambda category: _category_sort_key(category, rules))


def _category_sort_key(category: str, rules: tuple[SnpRule, ...]) -> tuple[int, int, str]:
    category_rules = [rule for rule in rules if rule.category == category]
    described = sum(1 for rule in category_rules if _rule_has_card_text(rule))
    return (-described, -len(category_rules), category.casefold())


def _rule_title(rule: SnpRule) -> str:
    if rule.title:
        return rule.title
    if rule.gene:
        return f"{rule.gene} {rule.rsid}"
    return f"SNP {rule.rsid}"


def _gene_result_button_label(rule: SnpRule) -> str:
    parts = [rule.rsid]
    if rule.gene:
        parts.append(rule.gene)
    title = _rule_title(rule)
    if title and title not in {rule.rsid, rule.gene}:
        parts.append(title)
    return _short_button_label(" · ".join(parts), limit=60)


def _rule_has_card_text(rule: SnpRule) -> bool:
    return bool(rule.description or rule.title or rule.gene)


def _short_button_label(value: str, *, limit: int = 60) -> str:
    clean = " ".join(str(value or "").split())
    if len(clean) <= limit:
        return clean
    return clean[: max(1, limit - 1)].rstrip() + "…"


def _panel_status_for_genotype(user_genotype: str, normal_genotype: str) -> str:
    user = _canonical_genotype(user_genotype)
    normal = _canonical_genotype(normal_genotype)
    if not user or user in {"--", "00"}:
        return "missing"
    if user == normal:
        return "ok"
    if len(user) == 2 and len(normal) == 2:
        normal_alleles = set(normal)
        matched = sum(1 for allele in user if allele in normal_alleles)
        if matched >= 1:
            return "warn"
        return "bad"
    return "warn"


def _panel_status_label(status: str, *, lang: str = "ru") -> str:
    if lang == "en":
        return {
            "ok": "matches panel norm",
            "warn": "heterozygous / variant",
            "bad": "homozygous variant",
            "missing": "no data",
        }.get(status, "variant")
    return {
        "ok": "норма панели",
        "warn": "гетеро / вариант",
        "bad": "гомо-вариант",
        "missing": "нет данных",
    }.get(status, "вариант")


def _canonical_genotype(value: object) -> str:
    genotype = str(value or "").strip().upper()
    if not genotype or genotype in {"-", "--", "N/A", "NA", "NULL", "NONE"}:
        return ""
    for separator in ("/", "\\", "|", " "):
        genotype = genotype.replace(separator, "")
    if len(genotype) == 2 and all(base in "ACGT" for base in genotype):
        return "".join(sorted(genotype))
    return genotype


def _rule_description(rule: SnpRule, *, lang: str = "ru") -> str:
    if rule.description:
        return rule.description
    if lang == "en":
        return "No detailed description has been added yet. This card shows the panel section and reference genotype."
    return "Подробного описания для этого SNP пока нет. Карточка показывает раздел панели и норму панели."


def _rule_sources_line(rule: SnpRule, *, lang: str = "ru") -> str:
    rsid = html.escape(rule.rsid)
    title = "Sources" if lang == "en" else "Источники"
    return (
        f'{title}: <a href="https://www.ncbi.nlm.nih.gov/snp/{rsid}">dbSNP</a> · '
        f'<a href="https://www.snpedia.com/index.php/{rsid.capitalize()}">SNPedia</a>'
    )


def _row_summary(row: object) -> str:
    title = str(getattr(row, "title", "") or "").strip()
    gene = str(getattr(row, "gene", "") or "").strip()
    description = str(getattr(row, "description", "") or "").strip()
    if title and gene:
        head = f"{gene}: {title}"
    else:
        head = title or gene
    if head and description:
        return f"{head}. {description}"
    return head or description or "Справочный SNP панели."


def _dna_lab_footer_row() -> list[InlineKeyboardButton]:
    return [InlineKeyboardButton("⬅️ DNA Lab", callback_data="main:root"), InlineKeyboardButton("Отмена", callback_data="main:cancel")]


def _back_cancel_row(back_callback: str) -> list[InlineKeyboardButton]:
    return [InlineKeyboardButton("⬅️ Назад", callback_data=back_callback), InlineKeyboardButton("Отмена", callback_data="main:cancel")]


def _html_cards(result: SnpReportResult) -> str:
    return (
        "<div class='cards'>"
        f"<div class='card'><div class='num ok'>{result.ok}</div><div>Норма</div></div>"
        f"<div class='card'><div class='num warn'>{result.warn}</div><div>Гетеро</div></div>"
        f"<div class='card'><div class='num bad'>{result.bad}</div><div>Гомо</div></div>"
        f"<div class='card'><div class='num missing'>{result.missing}</div><div>Нет данных</div></div>"
        "</div>"
    )


def _status_label(status: str) -> str:
    return {
        "ok": "Норма",
        "warn": "Гетерозиготный / вариант",
        "bad": "Гомозиготный вариант",
        "missing": "Нет данных",
    }.get(status, status)


def _total_pages(items: list[object], page_size: int) -> int:
    return max(1, (len(items) + page_size - 1) // page_size)


def _clamp_page(page: int, total_pages: int) -> int:
    return max(0, min(int(page), max(0, total_pages - 1)))
