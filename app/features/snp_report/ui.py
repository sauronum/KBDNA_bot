from __future__ import annotations

import html
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

try:
    from telegram import CopyTextButton
except ImportError:  # pragma: no cover - depends on python-telegram-bot version
    CopyTextButton = None  # type: ignore[assignment]

from app.features.my_data.storage import SampleAsset

from .domain import SnpCategorySummary, SnpReportResult, SnpRule
from .storage import SnpReportRecord


PAGE_SIZE = 8
SNP_PAGE_SIZE = 10
CATEGORY_PAGE_SIZE = 9


def lab_root_text(samples: list[SampleAsset], rules: tuple[SnpRule, ...], *, lang: str = "ru") -> str:
    categories = _category_names(rules)
    if lang == "en":
        return "\n".join(
            [
                "🧬 <b>SNP Lab</b>",
                "",
                "Single SNP lookup, a compact SNP reference base, and HTML reports for your raw files.",
                "",
                f"Samples with raw files: <b>{len(samples)}</b>",
                f"SNP in panel: <b>{len(rules)}</b>",
                f"Categories: <b>{len(categories)}</b>",
            ]
        )
    return "\n".join(
        [
            "🧬 <b>SNP Lab</b>",
            "",
            "Поиск SNP, справочная база и отчёты по raw-файлам.",
            "",
            f"Sample с raw-файлом: <b>{len(samples)}</b>",
            f"SNP в панели: <b>{len(rules)}</b>",
            f"Разделов базы: <b>{len(categories)}</b>",
        ]
    )


def build_lab_root_keyboard(*, lang: str = "ru") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🔎 Поиск SNP", callback_data="snp_report:search")],
            [InlineKeyboardButton("📚 База SNP", callback_data="snp_report:db")],
            [InlineKeyboardButton("🧾 SNP отчёт", callback_data="snp_report:report")],
            _dna_lab_footer_row(),
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


def search_picker_text(samples: list[SampleAsset], *, lang: str = "ru", page: int = 0) -> str:
    total_pages = _total_pages(samples, PAGE_SIZE)
    page = _clamp_page(page, total_pages)
    if lang == "en":
        lines = [
            "🔎 <b>Поиск SNP</b>",
            "",
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
        "Выберите sample, в котором нужно проверить SNP.",
    ]
    if samples:
        lines.append(f"Страница {page + 1}/{total_pages}.")
    else:
        lines.extend(["", "Пока нет sample с raw-файлом."])
    return "\n".join(lines)


def build_search_picker_keyboard(samples: list[SampleAsset], *, lang: str = "ru", page: int = 0) -> InlineKeyboardMarkup:
    return _sample_picker_keyboard(
        samples,
        action="search_sample",
        page_action="search_page",
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


def search_result_text(sample: SampleAsset, result: object, *, lang: str = "ru") -> str:
    rsid = html.escape(str(getattr(result, "rsid", "") or ""))
    genotype = html.escape(str(getattr(result, "genotype", "") or "--"))
    chromosome = getattr(result, "chromosome", None)
    position = getattr(result, "position", None)
    found = bool(getattr(result, "found", False))
    error = getattr(result, "error", None)
    sample_name = html.escape(sample.display_name)

    if lang == "en":
        lines = ["🔎 <b>Поиск SNP</b>", "", f"Sample: <b>{sample_name}</b>", f"SNP: <b>{rsid}</b>", ""]
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
            lines.extend(["SNP was not found in the raw file.", "", "This can depend on the chip, test version, or raw format."])
        return "\n".join(lines)

    lines = ["🔎 <b>Поиск SNP</b>", "", f"Sample: <b>{sample_name}</b>", f"SNP: <b>{rsid}</b>", ""]
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
        lines.extend(["SNP не найден в raw-файле.", "", "Это может зависеть от чипа, версии теста или формата raw."])
    return "\n".join(lines)


def build_search_input_keyboard(sample_id: str, *, lang: str = "ru") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            _back_cancel_row("snp_report:search"),
        ]
    )


def build_search_result_keyboard(sample_id: str, *, lang: str = "ru") -> InlineKeyboardMarkup:
    retry_label = "🔁 Check another SNP" if lang == "en" else "🔁 Проверить другой SNP"
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(retry_label, callback_data=f"snp_report:search_sample:{sample_id}")],
            [InlineKeyboardButton("👤 Другой sample", callback_data="snp_report:search")],
            _back_cancel_row("snp_report:root"),
        ]
    )


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
                "Choose a category.",
            ]
        )
    return "\n".join(
        [
            "📚 <b>SNP база</b>",
            "",
            f"SNP в панели: <b>{len(rules)}</b>",
            f"Разделов: <b>{len(categories)}</b>",
            "",
            "Выберите раздел.",
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
        [InlineKeyboardButton(rule.rsid, callback_data=f"snp_report:dbsnp:{rule_index}:{category_index}:{page}")]
        for rule_index, rule in visible
    ]
    _append_page_nav(rows, page=page, total_pages=total_pages, callback_prefix=f"snp_report:dbcat:{category_index}")
    rows.append(_back_cancel_row("snp_report:db"))
    return InlineKeyboardMarkup(rows)


def db_rule_text(rule: SnpRule, *, lang: str = "ru") -> str:
    if lang == "en":
        return "\n".join(
            [
                "📚 <b>SNP база</b>",
                "",
                f"rsID: <code>{html.escape(rule.rsid)}</code>",
                f"Category: <b>{html.escape(rule.category)}</b>",
                f"Panel norm: <code>{html.escape(rule.normal_genotype)}</code>",
                "",
                "This is a reference card from the current panel. It does not interpret medical risk.",
            ]
        )
    return "\n".join(
        [
            "📚 <b>SNP база</b>",
            "",
            f"rsID: <code>{html.escape(rule.rsid)}</code>",
            f"Раздел: <b>{html.escape(rule.category)}</b>",
            f"Норма панели: <code>{html.escape(rule.normal_genotype)}</code>",
            "",
            "Это справочная карточка из текущей панели. Она не является медицинской интерпретацией.",
        ]
    )


def build_db_rule_keyboard(rule: SnpRule, category_index: int, page: int, *, lang: str = "ru") -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    copy_button = _copy_rsid_button(rule.rsid)
    if copy_button is not None:
        rows.append([copy_button])
    rows.append(_back_cancel_row(f"snp_report:dbcat:{category_index}:{page}"))
    return InlineKeyboardMarkup(rows)


def running_text(sample: SampleAsset, *, lang: str = "ru") -> str:
    if lang == "en":
        return f"🧾 SNP отчёт\n\nCalculating report for: <b>{html.escape(sample.display_name)}</b>"
    return f"🧾 SNP отчёт\n\nСчитаю отчёт для: <b>{html.escape(sample.display_name)}</b>"


def result_text(record: SnpReportRecord, *, lang: str = "ru") -> str:
    summary = record.summary
    categories = [
        SnpCategorySummary(**item)
        for item in record.payload.get("categories", [])
        if isinstance(item, dict)
    ]
    top = categories[:7]
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
    if top:
        lines.extend(["", "<b>Топ категорий по нагрузке:</b>"])
        for item in top:
            lines.append(
                f"• {html.escape(item.category)} — <b>{item.risk_percent}%</b> "
                f"(🔴 {item.bad}, 🟡 {item.warn}, ⚪ {item.missing})"
            )
    lines.extend(["", "HTML-файл готов. Его можно скачать кнопкой ниже."])
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
                <thead><tr><th>SNP</th><th>Ваши аллели</th><th>Норма</th><th>Статус</th></tr></thead>
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
    count = sum(1 for rule in rules if rule.category == category)
    return f"{category} · {count}"


def _category_names(rules: tuple[SnpRule, ...]) -> list[str]:
    seen: dict[str, None] = {}
    for rule in rules:
        seen.setdefault(rule.category, None)
    return sorted(seen, key=str.casefold)


def _copy_rsid_button(rsid: str) -> InlineKeyboardButton | None:
    if CopyTextButton is None:
        return None
    kwargs: dict[str, Any] = {"text": "📋 Скопировать rsID", "copy_text": CopyTextButton(text=rsid)}
    return InlineKeyboardButton(**kwargs)


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
