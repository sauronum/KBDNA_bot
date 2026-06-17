from __future__ import annotations

import html

from .yfull import YFullLookupResult


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
    version = f"YFull YTree v{branch.tree_version}" if branch.tree_version else "YFull YTree"
    if branch.release_date:
        version += f" · {branch.release_date}"
    lines.extend([html.escape(version), ""])

    if branch.parent:
        lines.append(f"{_copy(lang, 'Родитель', 'Parent')}: <code>{html.escape(branch.parent)}</code>")
    if branch.path:
        path = _compact_path(branch.path)
        lines.append(f"{_copy(lang, 'Путь', 'Path')}: <code>{html.escape(' › '.join(path))}</code>")
    if branch.snps:
        lines.append(f"SNP: <code>{html.escape(_compact_values(branch.snps, 8))}</code>")
    if branch.formed_ybp is not None:
        lines.append(f"{_copy(lang, 'Сформировалась', 'Formed')}: {_format_age(branch.formed_ybp, lang)}")
    if branch.tmrca_ybp is not None:
        lines.append(f"TMRCA: {_format_age(branch.tmrca_ybp, lang)}")

    lines.extend(["", f"{_copy(lang, 'Публичных образцов в поддереве', 'Public samples in subtree')}: {branch.public_sample_count}"])
    if branch.geographies:
        lines.append(f"{_copy(lang, 'География', 'Geography')}: {html.escape(_compact_values(branch.geographies, 6))}")

    lines.extend(["", f"<b>{_copy(lang, 'Ближайшие дочерние ветви', 'Immediate child branches')}</b>"])
    if branch.children:
        for child in branch.children[:8]:
            label = f"• <code>{html.escape(child.name)}</code>"
            if child.tmrca_ybp is not None:
                label += f" · TMRCA {_format_age(child.tmrca_ybp, lang)}"
            lines.append(label)
        if len(branch.children) > 8:
            lines.append(_copy(lang, f"…и ещё {len(branch.children) - 8}", f"…and {len(branch.children) - 8} more"))
    else:
        lines.append(_copy(lang, "Дочерние ветви не показаны.", "No child branches are shown."))

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
    if len(path) <= 9:
        return path
    return (path[0], "…", *path[-7:])


def _compact_values(values: tuple[str, ...], limit: int) -> str:
    shown = list(values[:limit])
    if len(values) > limit:
        shown.append(f"+{len(values) - limit}")
    return ", ".join(shown)


def _format_age(value: int, lang: str) -> str:
    formatted = f"{value:,}".replace(",", " ")
    return f"{formatted} {_copy(lang, 'лет назад', 'ybp')}"
