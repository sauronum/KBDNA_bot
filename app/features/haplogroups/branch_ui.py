from __future__ import annotations

import html
import re

from .yfull import YFullGeography, YFullLookupResult


_RU_GEOGRAPHY = {
    "Brazil": "Бразилия",
    "Georgia": "Грузия",
    "Lebanon": "Ливан",
    "Puerto Rico": "Пуэрто-Рико",
    "Russia": "Россия",
    "Saudi Arabia": "Саудовская Аравия",
    "Spain": "Испания",
    "Turkey": "Турция",
    "United States": "США",
}

_RU_MONTHS = {
    "January": "января",
    "February": "февраля",
    "March": "марта",
    "April": "апреля",
    "May": "мая",
    "June": "июня",
    "July": "июля",
    "August": "августа",
    "September": "сентября",
    "October": "октября",
    "November": "ноября",
    "December": "декабря",
}


def _copy(lang: str, ru: str, en: str) -> str:
    return en if lang == "en" else ru


def branch_lookup_prompt_text(lang: str = "ru") -> str:
    return "\n".join(
        [
            f"<b>{_copy(lang, 'Поиск ветки Y-DNA', 'Y-DNA branch lookup')}</b>",
            "",
            _copy(
                lang,
                "Пришлите полное название ветки или ссылку на публичную страницу YFull.",
                "Send a full branch name or a public YFull tree URL.",
            ),
            "",
            "<code>G-Z31455</code>",
            "<code>R-Y23968</code>",
            "<code>https://www.yfull.com/tree/R-Y23968/</code>",
        ]
    )


def branch_lookup_loading_text(query: str, lang: str = "ru") -> str:
    return "\n".join(
        [
            f"<b>{_copy(lang, 'Ищу ветку в YFull YTree', 'Looking up the branch in YFull YTree')}</b>",
            "",
            f"<code>{html.escape(query[:120])}</code>",
        ]
    )


def branch_lookup_error_text(reason: str, lang: str = "ru") -> str:
    messages = {
        "invalid_query": _copy(
            lang,
            "Не понял название ветки. Пришлите полный код вроде G-Z31455 или ссылку YFull.",
            "I could not understand the branch name. Send a full code such as G-Z31455 or a YFull URL.",
        ),
        "not_found": _copy(
            lang,
            "Ветка не найдена в публичном YFull YTree. Проверьте код и попробуйте снова.",
            "The branch was not found in the public YFull YTree. Check the code and try again.",
        ),
        "unavailable": _copy(
            lang,
            "YFull сейчас недоступен. Попробуйте повторить поиск немного позже.",
            "YFull is currently unavailable. Try the lookup again a little later.",
        ),
        "response_too_large": _copy(
            lang,
            "Страница ветки оказалась слишком большой для безопасной обработки.",
            "The branch page was too large to process safely.",
        ),
        "parse_error": _copy(
            lang,
            "YFull изменил формат страницы, и ветку пока не удалось разобрать.",
            "YFull changed the page format and the branch could not be parsed.",
        ),
    }
    message = messages.get(reason, messages["unavailable"])
    return "\n".join([f"<b>{_copy(lang, 'Поиск ветки', 'Branch lookup')}</b>", "", message])


def branch_lookup_result_text(result: YFullLookupResult, lang: str = "ru") -> str:
    branch = result.branch
    lines = [f"<b>{html.escape(branch.name)}</b>"]
    version = f"YFull YTree {_short_tree_version(branch.tree_version)}" if branch.tree_version else "YFull YTree"
    if branch.release_date:
        version += f" · {_format_release_date(branch.release_date, lang)}"
    lines.extend([html.escape(version), ""])

    if branch.parent:
        lines.append(f"{_copy(lang, 'Родитель', 'Parent')}: <code>{html.escape(branch.parent)}</code>")
    if branch.path:
        path = _compact_path(branch.path)
        lines.append(f"{_copy(lang, 'Линия', 'Lineage')}: <code>{html.escape(' › '.join(path))}</code>")
    if branch.snps:
        lines.append(f"SNP: <code>{html.escape(_compact_values(branch.snps, 4))}</code>")
    if branch.formed_ybp is not None:
        lines.append(
            f"{_copy(lang, 'Возраст ветви', 'Branch age')}: "
            f"{_format_age_estimate(branch.formed_ybp, branch.formed_ci_ybp, lang)}"
        )
    if branch.tmrca_ybp is not None:
        lines.append(
            f"{_copy(lang, 'Общий предок', 'Common ancestor')}: "
            f"{_format_age_estimate(branch.tmrca_ybp, branch.tmrca_ci_ybp, lang)}"
        )

    lines.extend(["", f"{_copy(lang, 'Публичных образцов', 'Public samples')}: {branch.public_sample_count}"])
    if branch.geographies:
        lines.append(
            f"{_copy(lang, 'Происхождение', 'Origins')}: "
            f"{html.escape(_format_geographies(branch.geographies, lang))}"
        )

    child_count = sum(1 for child in branch.children if not child.name.endswith("*"))
    basal_samples = sum(child.public_sample_count for child in branch.children if child.name.endswith("*"))
    lines.extend(["", f"{_copy(lang, 'Дочерних ветвей', 'Child branches')}: {child_count}"])
    if basal_samples:
        lines.append(f"{_copy(lang, 'Базальных образцов', 'Basal samples')}: {basal_samples}")

    if result.cache_status == "stale":
        lines.extend(
            [
                "",
                _copy(
                    lang,
                    "YFull временно недоступен — показана последняя сохранённая версия.",
                    "YFull is temporarily unavailable — showing the last cached version.",
                ),
            ]
        )
    return "\n".join(lines)


def _compact_path(path: tuple[str, ...]) -> tuple[str, ...]:
    if len(path) <= 6:
        return path
    return (path[0], "…", *path[-4:])


def _compact_values(values: tuple[str, ...], limit: int) -> str:
    shown = list(values[:limit])
    if len(values) > limit:
        shown.append(f"+{len(values) - limit}")
    return ", ".join(shown)


def _format_age_estimate(value: int, interval: tuple[int, int] | None, lang: str) -> str:
    formatted = f"{value:,}".replace(",", " ")
    result = f"≈ {formatted} {_copy(lang, 'лет назад', 'ybp')}"
    if interval is not None:
        low, high = interval
        low_text = f"{low:,}".replace(",", " ")
        high_text = f"{high:,}".replace(",", " ")
        result += f" (95%: {low_text}–{high_text})"
    return result


def _short_tree_version(value: str) -> str:
    return value[:-3] if value.endswith(".00") else value


def _format_release_date(value: str, lang: str) -> str:
    if lang == "en":
        return value
    match = re.fullmatch(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", value.strip())
    if match is None:
        return value
    month = _RU_MONTHS.get(match.group(2), match.group(2))
    return f"{match.group(1)} {month} {match.group(3)}"


def _format_geographies(values: tuple[YFullGeography, ...], lang: str, limit: int = 5) -> str:
    parts = []
    for item in values[:limit]:
        label = _RU_GEOGRAPHY.get(item.label, item.label) if lang != "en" else item.label
        parts.append(f"{label} — {item.count}")
    if len(values) > limit:
        parts.append(f"+{len(values) - limit}")
    return ", ".join(parts)
