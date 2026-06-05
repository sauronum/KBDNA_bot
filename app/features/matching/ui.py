from __future__ import annotations

import html

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.features.my_data.storage import SampleAsset

from .domain import PairwiseMatchResult
from .storage import MatchingRecord, MatchingRecordSummary


def _copy(lang: str, ru: str, en: str) -> str:
    return en if lang == "en" else ru


def build_markup(rows: list[list[InlineKeyboardButton]], back_callback: str, *, lang: str = "ru") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        rows
        + [[
            InlineKeyboardButton(_copy(lang, "⬅️ Назад", "⬅️ Back"), callback_data=back_callback),
            InlineKeyboardButton(_copy(lang, "Отмена", "Cancel"), callback_data="main:cancel"),
        ]]
    )


def matching_root_text(*, lang: str = "ru") -> str:
    if lang == "en":
        return "\n".join(
            [
                "<b>🧩 Matching</b>",
                "",
                "Sample closeness and matches.",
            ]
        )
    return "\n".join(
        [
            "<b>🧩 Matching</b>",
            "",
            "Близость и совпадения sample’ов.",
        ]
    )


def sample_picker_text(samples: list[SampleAsset], *, side: str, left_sample: SampleAsset | None = None, lang: str = "ru") -> str:
    if side == "right" and left_sample is not None:
        title = "🧬 Pairwise match"
        prompt = "\n\n".join(
            [
                f"{_copy(lang, 'Первый sample', 'First sample')}: <b>{html.escape(left_sample.display_name)}</b>",
                _copy(lang, "Выберите второй sample.", "Choose the second sample."),
            ]
        )
    else:
        title = "🧬 Pairwise match"
        prompt = _copy(lang, "Выберите первый sample.", "Choose the first sample.")
    lines = [
        f"<b>{title}</b>",
        "",
        prompt,
        "",
        f"{_copy(lang, 'Sample с raw-файлом', 'Samples with raw files')}: <b>{len(samples)}</b>",
    ]
    if not samples:
        lines.extend(["", _copy(lang, "Пока нет sample с raw-файлами. Добавьте raw в My DNA.", "There are no samples with raw files yet. Add raw files in My DNA.")])
    return "\n".join(lines)


def matching_running_text(left: SampleAsset, right: SampleAsset, *, lang: str = "ru") -> str:
    return "\n".join(
        [
            "<b>🧬 Pairwise match</b>",
            "",
            f"<b>{html.escape(left.display_name)} × {html.escape(right.display_name)}</b>",
            "",
            _copy(lang, "Считаю общие аутосомные сегменты...", "Calculating shared autosomal segments..."),
        ]
    )


def all_pairs_running_text(samples: list[SampleAsset], *, completed_pairs: int = 0, total_pairs: int | None = None, lang: str = "ru") -> str:
    pair_count = total_pairs if total_pairs is not None else len(samples) * (len(samples) - 1) // 2
    lines = [
        "<b>Compare all samples</b>",
        "",
        f"Samples with raw: {len(samples)}",
        f"Pairs: {pair_count}",
    ]
    if completed_pairs:
        lines.append(f"Done: {completed_pairs} / {pair_count}")
    lines.extend(["", _copy(lang, "Считаю попарные autosomal matches...", "Calculating pairwise autosomal matches...")])
    return "\n".join(lines)


def all_pairs_confirm_text(samples: list[SampleAsset], *, lang: str = "ru") -> str:
    pair_count = len(samples) * (len(samples) - 1) // 2
    if lang == "en":
        lines = [
            "<b>📊 Compare all samples</b>",
            "",
            "<b>Calculation</b>",
            f"Samples with raw: {len(samples)}",
            f"Pairs to compare: {pair_count}",
            "Map: GRCh37",
            "",
            "This is an all-vs-all run. With 10 samples, that is already 45 pairwise comparisons.",
            "Run it when you are ready to wait a bit.",
        ]
        if len(samples) > 15:
            lines.extend(["", "⚠️ More than 15 samples: the calculation can take a while."])
        return "\n".join(lines)

    lines = [
        "<b>📊 Сравнить все sample</b>",
        "",
        f"Sample с raw-файлом: {len(samples)}",
        f"Пар для сравнения: {pair_count}",
        "Карта: GRCh37",
        "",
        "Это общий all-vs-all расчёт.",
        "Для 10 sample это уже 45 попарных сравнений.",
    ]
    if len(samples) > 15:
        lines.extend(["", "⚠️ Если sample больше 15, расчёт может занять заметное время."])
    return "\n".join(lines)


def selected_samples_picker_text(selected_count: int, *, lang: str = "ru") -> str:
    pair_count = selected_count * (selected_count - 1) // 2
    if lang == "en":
        lines = [
            "<b>✅ Compare selected samples</b>",
            "",
            "Choose samples to compare.",
            "",
            f"Selected: <b>{selected_count} samples</b>",
            f"Pairs to compare: <b>{pair_count}</b>",
        ]
        if selected_count > 15:
            lines.extend(["", "⚠️ More than 15 samples: the calculation can take a while."])
        return "\n".join(lines)

    lines = [
        "<b>✅ Сравнить выбранные sample</b>",
        "",
        "Выберите sample для сравнения.",
        "",
        f"Выбрано: <b>{selected_count} sample</b>",
        f"Пар для сравнения: <b>{pair_count}</b>",
    ]
    if selected_count > 15:
        lines.extend(["", "⚠️ Если sample больше 15, расчёт может занять заметное время."])
    return "\n".join(lines)


def snp_input_text(*, lang: str = "ru") -> str:
    if lang == "en":
        return "\n".join(
            [
                "<b>🔎 Compare SNP</b>",
                "",
                "Enter an rsID, for example:",
                "",
                "<code>rs2455144</code>",
            ]
        )
    return "\n".join(
        [
            "<b>🔎 Сравнить SNP</b>",
            "",
            "Введите rsID, например:",
            "",
            "<code>rs2455144</code>",
        ]
    )


def snp_sample_picker_text(rsid: str, selected_count: int, *, lang: str = "ru") -> str:
    if lang == "en":
        return "\n".join(
            [
                "<b>🔎 Compare SNP</b>",
                "",
                f"SNP: <b>{html.escape(rsid)}</b>",
                "",
                "Choose samples to compare.",
                "",
                f"Selected: <b>{selected_count} samples</b>",
            ]
        )
    return "\n".join(
        [
            "<b>🔎 Сравнить SNP</b>",
            "",
            f"SNP: <b>{html.escape(rsid)}</b>",
            "",
            "Выберите sample для сравнения.",
            "",
            f"Выбрано: <b>{selected_count} sample</b>",
        ]
    )


def selected_samples_running_text(sample_count: int, *, completed_pairs: int = 0, total_pairs: int | None = None, lang: str = "ru") -> str:
    pair_count = total_pairs if total_pairs is not None else sample_count * (sample_count - 1) // 2
    if lang == "en":
        lines = [
            "<b>✅ Compare selected samples</b>",
            "",
            f"Samples: <b>{sample_count}</b>",
            f"Pairs to compare: <b>{pair_count}</b>",
        ]
        if completed_pairs:
            lines.append(f"Done: {completed_pairs} / {pair_count}")
        lines.extend(["", "Calculating pairwise matches..."])
        return "\n".join(lines)

    lines = [
        "<b>✅ Сравнить выбранные sample</b>",
        "",
        f"Sample: <b>{sample_count}</b>",
        f"Пар для сравнения: <b>{pair_count}</b>",
    ]
    if completed_pairs:
        lines.append(f"Готово: {completed_pairs} / {pair_count}")
    lines.extend(["", "Считаю попарные совпадения..."])
    return "\n".join(lines)


def pairwise_result_text(left: SampleAsset, right: SampleAsset, result: PairwiseMatchResult, *, lang: str = "ru") -> str:
    lines = [
        "<b>🧬 Pairwise autosomal match</b>",
        "",
        f"A: <b>{html.escape(left.display_name)}</b>",
        f"B: <b>{html.escape(right.display_name)}</b>",
        "",
        "<b>📊 Summary</b>",
        f"Total estimated cM: <b>{result.total_estimated_cm:.2f}</b>",
        f"Longest estimated cM: {result.longest_estimated_cm:.2f}",
        f"Segments: {len(result.segments)}",
        f"Map: {'GRCh37' if result.genetic_map_used else 'fallback'}",
        "",
        _interpretation_block(result, lang=lang),
        "",
        "<b>🔎 Evidence</b>",
        f"Overlap SNPs: {result.overlap_snps}",
        f"Shared SNPs: {result.half_identical_snps}",
        f"Identical SNPs: {result.identical_snps}",
    ]
    if result.segments:
        lines.extend(["", "<b>🧬 Top segments</b>", _segments_table(result)])
    return "\n".join(lines)


def pairwise_visual_caption(left: SampleAsset, right: SampleAsset, result: PairwiseMatchResult, *, lang: str = "ru") -> str:
    lines = [
        "<b>🧬 Pairwise match</b>",
        "",
        f"<b>{html.escape(left.display_name)} × {html.escape(right.display_name)}</b>",
        f"Total: <b>{result.total_estimated_cm:.2f} cM</b> · Longest: {result.longest_estimated_cm:.2f} cM · Segments: {len(result.segments)}",
        "",
    ]
    lines.extend(_relationship_caption_lines(result, lang=lang))
    return "\n".join(lines)


def all_pairs_result_text(results: list[tuple[SampleAsset, SampleAsset, PairwiseMatchResult]], sample_count: int, *, lang: str = "ru") -> str:
    sorted_results = sorted(results, key=lambda item: item[2].total_estimated_cm, reverse=True)
    significant = [item for item in sorted_results if item[2].total_estimated_cm > 0]
    visible = significant[:15] if significant else sorted_results[:15]
    map_label = "GRCh37" if any(result.genetic_map_used for _left, _right, result in results) else "fallback"
    lines = [
        "<b>Compare all samples</b>",
        "",
        f"Samples with raw: {sample_count}",
        f"Compared pairs: {len(results)}",
        f"Map: {map_label}",
    ]
    if not results:
        lines.extend(["", _copy(lang, "Нужно минимум два sample с raw-файлами.", "At least two samples with raw files are required.")])
        return "\n".join(lines)
    if not significant:
        lines.extend(["", _copy(lang, "Значимых сегментов выше порога не найдено.", "No significant segments above the threshold were found.")])
        return "\n".join(lines)

    lines.extend(["", "<b>Top matches</b>", _all_pairs_table(visible)])
    lines.extend(["", "<b>Best hints</b>"])
    for index, (left, right, result) in enumerate(visible[:5], start=1):
        pair = f"{left.display_name} - {right.display_name}"
        lines.append(f"{index}. {html.escape(pair)}: {html.escape(_relationship_hint_text(result.relationship_hint, result.total_estimated_cm, result.longest_estimated_cm, lang=lang))}")
    return "\n".join(lines)


def all_pairs_visual_caption(results: list[tuple[SampleAsset, SampleAsset, PairwiseMatchResult]], sample_count: int, *, lang: str = "ru") -> str:
    sorted_results = sorted(results, key=lambda item: item[2].total_estimated_cm, reverse=True)
    significant = [item for item in sorted_results if item[2].total_estimated_cm > 0]
    best = sorted_results[0] if sorted_results else None
    if best is None:
        best_line = _copy(lang, "Best: -", "Best: -")
    else:
        left, right, result = best
        pair = _short_pair_name(left.display_name, right.display_name)
        best_line = f"Best: {html.escape(pair)} · {result.total_estimated_cm:.2f} cM"
    return "\n".join(
        [
            "<b>Matching overview</b>",
            f"Samples: {sample_count} · Pairs: {len(results)} · With signal: {len(significant)}",
            best_line,
        ]
    )


def selected_samples_visual_caption(results: list[tuple[SampleAsset, SampleAsset, PairwiseMatchResult]], sample_count: int, *, lang: str = "ru") -> str:
    pair_count = len(results)
    map_label = "GRCh37" if any(result.genetic_map_used for _left, _right, result in results) else "fallback"
    best = max(results, key=lambda item: item[2].total_estimated_cm, default=None)
    if lang == "en":
        lines = [
            "<b>✅ Compare selected samples</b>",
            "",
            f"Samples: {sample_count}",
            f"Pairs: {pair_count}",
            f"Map: {map_label}",
        ]
        if best is not None:
            left, right, result = best
            lines.extend(["", f"Best match: {html.escape(left.display_name)} × {html.escape(right.display_name)} · {result.total_estimated_cm:.1f} cM"])
        return "\n".join(lines)

    lines = [
        "<b>✅ Сравнить выбранные sample</b>",
        "",
        f"Sample: {sample_count}",
        f"Пар: {pair_count}",
        f"Карта: {map_label}",
    ]
    if best is not None:
        left, right, result = best
        lines.extend(["", f"Лучшее совпадение: {html.escape(left.display_name)} × {html.escape(right.display_name)} · {result.total_estimated_cm:.1f} cM"])
    return "\n".join(lines)


def snp_result_text(rsid: str, rows: list[tuple[SampleAsset, object]], *, lang: str = "ru") -> str:
    found_positions = [
        (getattr(result, "chromosome", None), getattr(result, "position", None))
        for _sample, result in rows
        if getattr(result, "found", False) and getattr(result, "chromosome", None) and getattr(result, "position", None)
    ]
    any_found = any(bool(getattr(result, "found", False)) for _sample, result in rows)
    any_missing = any(str(getattr(result, "genotype", "")) == "--" for _sample, result in rows)

    title = "<b>🔎 Compare SNP</b>" if lang == "en" else "<b>🔎 Сравнить SNP</b>"
    lines = [title, "", f"<b>{html.escape(rsid)}</b>"]
    if found_positions:
        chromosome, position = found_positions[0]
        lines.append(_copy(lang, f"Позиция: chr{html.escape(str(chromosome))}:{int(position):,}", f"Position: chr{html.escape(str(chromosome))}:{int(position):,}"))
    lines.append("")

    if not any_found:
        if lang == "en":
            lines.extend(
                [
                    "SNP was not found in the selected raw files.",
                    "",
                    "Check the rsID or choose other samples.",
                ]
            )
        else:
            lines.extend(
                [
                    "SNP не найден в выбранных raw-файлах.",
                    "",
                    "Проверьте rsID или выберите другие sample.",
                ]
            )
        return "\n".join(lines)

    for sample, result in rows:
        genotype = html.escape(str(getattr(result, "genotype", "--") or "--"))
        lines.append(f"{html.escape(sample.display_name)} — {genotype}")
    if any_missing:
        lines.extend(["", _copy(lang, "Обозначение:\n-- = SNP не найден в raw", "Legend:\n-- = SNP not found in raw")])
    return "\n".join(lines)


def matching_error_text(title: str, message: str) -> str:
    return f"<b>{html.escape(title)}</b>\n\n{html.escape(message)}"


def match_saved_text(record: MatchingRecord, *, lang: str = "ru") -> str:
    summary = record.summary
    return "\n".join(
        [
            "<b>💾 Matching saved</b>",
            "",
            f"A: <b>{html.escape(summary.left_sample_name)}</b>",
            f"B: <b>{html.escape(summary.right_sample_name)}</b>",
            f"Total estimated cM: {summary.total_estimated_cm:.2f}",
            f"Segments: {summary.segment_count}",
            f"Hint: {html.escape(_relationship_hint_text(summary.relationship_hint, summary.total_estimated_cm, 0.0, lang=lang))}",
        ]
    )


def saved_matches_text(matches: list[MatchingRecordSummary], *, lang: str = "ru") -> str:
    if lang == "en":
        lines = [
            "<b>💾 Saved matches</b>",
            "",
            f"<b>Saved:</b> {len(matches)}",
        ]
        if matches:
            lines.extend(["", "Choose a saved pairwise comparison."])
        else:
            lines.extend(["", "There are no saved matching results yet."])
        return "\n".join(lines)

    lines = [
        "<b>💾 Сохранённые matches</b>",
        "",
        f"Сохранено: <b>{len(matches)}</b>",
    ]
    if matches:
        lines.extend(["", "Выберите сохранённое сравнение."])
    else:
        lines.extend(["", "Пока нет сохранённых matching результатов."])
    return "\n".join(lines)


def saved_match_detail_text(record: MatchingRecord, *, lang: str = "ru") -> str:
    summary = record.summary
    payload = record.payload
    lines = [
        "<b>💾 Saved pairwise match</b>",
        "",
        f"A: <b>{html.escape(summary.left_sample_name)}</b>",
        f"B: <b>{html.escape(summary.right_sample_name)}</b>",
        "",
        "<b>📊 Summary</b>",
        f"Total estimated cM: <b>{_float(payload.get('total_estimated_cm')):.2f}</b>",
        f"Longest estimated cM: {_float(payload.get('longest_estimated_cm')):.2f}",
        f"Segments: {summary.segment_count}",
        f"Map: {'GRCh37' if payload.get('genetic_map_used') else 'fallback'}",
        "",
        f"<b>🧭 Interpretation</b>\n{html.escape(_relationship_hint_text(summary.relationship_hint, summary.total_estimated_cm, _float(payload.get('longest_estimated_cm')), lang=lang))}",
        "",
        "<b>🔎 Evidence</b>",
        f"Overlap SNPs: {int(_float(payload.get('overlap_snps')))}",
        f"Shared SNPs: {int(_float(payload.get('shared_snps')))}",
        f"Identical SNPs: {int(_float(payload.get('identical_snps')))}",
    ]
    segments = [item for item in payload.get("segments") or [] if isinstance(item, dict)]
    if segments:
        lines.extend(["", "<b>🧬 Top segments</b>", _segments_payload_table(segments)])
    return "\n".join(lines)


def saved_match_visual_caption(record: MatchingRecord, *, lang: str = "ru") -> str:
    summary = record.summary
    payload = record.payload
    longest_cm = _float(payload.get("longest_estimated_cm"))
    hint = _relationship_hint_text(summary.relationship_hint, summary.total_estimated_cm, longest_cm, lang=lang)
    return "\n".join(
        [
            f"<b>{html.escape(summary.left_sample_name)} × {html.escape(summary.right_sample_name)}</b>",
            f"Total: <b>{summary.total_estimated_cm:.2f} cM</b> · Longest: {longest_cm:.2f} · Segments: {summary.segment_count}",
            f"Hint: {html.escape(hint)}",
        ]
    )


def saved_match_button_label(summary: MatchingRecordSummary) -> str:
    return (
        f"{summary.left_sample_name} × {summary.right_sample_name} · "
        f"{summary.total_estimated_cm:.1f} cM"
    )


def _segments_table(result: PairwiseMatchResult) -> str:
    rows = [("Chr", "Start", "End", "cM", "SNPs")]
    for segment in result.segments[:12]:
        rows.append(
            (
                segment.chromosome,
                str(segment.start),
                str(segment.end),
                f"{segment.estimated_cm:.2f}",
                str(segment.snp_count),
            )
        )
    widths = [max(len(row[index]) for row in rows) for index in range(len(rows[0]))]
    rendered = []
    for row in rows:
        rendered.append("  ".join(value.ljust(widths[index]) for index, value in enumerate(row)))
    return "<pre>" + html.escape("\n".join(rendered)) + "</pre>"


def _segments_payload_table(segments: list[dict[str, object]]) -> str:
    rows = [("Chr", "Start", "End", "cM", "SNPs")]
    for segment in segments[:12]:
        rows.append(
            (
                str(segment.get("chromosome") or ""),
                str(int(_float(segment.get("start")))),
                str(int(_float(segment.get("end")))),
                f"{_float(segment.get('estimated_cm')):.2f}",
                str(int(_float(segment.get("snp_count")))),
            )
        )
    widths = [max(len(row[index]) for row in rows) for index in range(len(rows[0]))]
    rendered = []
    for row in rows:
        rendered.append("  ".join(value.ljust(widths[index]) for index, value in enumerate(row)))
    return "<pre>" + html.escape("\n".join(rendered)) + "</pre>"


def _all_pairs_table(results: list[tuple[SampleAsset, SampleAsset, PairwiseMatchResult]]) -> str:
    rows = [("Pair", "cM", "Long", "Segs")]
    for left, right, result in results:
        rows.append(
            (
                _short_pair_name(left.display_name, right.display_name),
                f"{result.total_estimated_cm:.1f}",
                f"{result.longest_estimated_cm:.1f}",
                str(len(result.segments)),
            )
        )
    widths = [max(len(row[index]) for row in rows) for index in range(len(rows[0]))]
    rendered = []
    for row in rows:
        rendered.append("  ".join(value.ljust(widths[index]) for index, value in enumerate(row)))
    return "<pre>" + html.escape("\n".join(rendered)) + "</pre>"


def _short_pair_name(left: str, right: str) -> str:
    label = f"{left.strip()} - {right.strip()}"
    return label[:24]


def _interpretation_block(result: PairwiseMatchResult, *, lang: str = "ru") -> str:
    level, possible = _relationship_level(result.total_estimated_cm, result.longest_estimated_cm, lang=lang)
    evidence = _relationship_evidence(result)
    lines = [
        "<b>🧭 Interpretation</b>",
        f"Level: {html.escape(level)}",
        f"Possible: {html.escape(possible)}",
    ]
    lines.extend(
        [
            f"Note: {html.escape(_copy(lang, 'это диапазон родства, не точное определение без родословной/фазирования.', 'this is a relationship range, not an exact call without genealogy or phasing.'))}",
            f"Evidence: {html.escape(evidence)}",
        ]
    )
    return "\n".join(lines)


def _relationship_level(total_cm: float, longest_cm: float, *, lang: str = "ru") -> tuple[str, str]:
    if total_cm >= 3300:
        return ("very close / near-complete match", "same person, identical twin, or a very close level") if lang == "en" else ("очень близко / почти полный матч", "тот же человек, однояйцевый близнец или очень близкий уровень")
    if total_cm >= 2300:
        return ("close family", "parent-child or full sibling; more context is needed to separate them") if lang == "en" else ("близкая семья", "родитель-ребенок или родные брат/сестра; точнее без контекста не разделяем")
    if total_cm >= 1300:
        return ("close relationship", "grandparent, aunt/uncle, half sibling, or a similar level") if lang == "en" else ("близкое родство", "grandparent, aunt/uncle, half sibling или похожий уровень")
    if total_cm >= 550:
        return ("close branch", "first cousin or a similar level") if lang == "en" else ("близкая ветка", "first cousin или похожий уровень")
    if total_cm >= 200:
        return ("medium match", "roughly second cousin range") if lang == "en" else ("среднее совпадение", "примерно second cousin range")
    if total_cm >= 60:
        return ("distant match", "roughly third cousin range") if lang == "en" else ("дальнее совпадение", "примерно third cousin range")
    if total_cm >= 20 or longest_cm >= 7:
        return ("small distant match", "distant relationship or a shared segment") if lang == "en" else ("небольшое дальнее совпадение", "дальнее родство или общий участок")
    return ("no significant match", "no segments above the threshold were found") if lang == "en" else ("нет значимого совпадения", "сегменты выше порога не найдены")


def _relationship_hint_text(value: str, total_cm: float, longest_cm: float, *, lang: str = "ru") -> str:
    if lang != "en":
        return value
    translations = {
        "Очень близкое совпадение / возможно тот же человек или близнец": "Very close match / possibly the same person or a twin",
        "Близкое родство: родитель-ребенок, full sibling или похожий уровень": "Close family: parent-child, full sibling, or a similar level",
        "Близкое родство: grandparent, aunt/uncle, half sibling или похожий уровень": "Close relationship: grandparent, aunt/uncle, half sibling, or a similar level",
        "Вероятно близкая ветка: first cousin или похожий уровень": "Likely close branch: first cousin or a similar level",
        "Среднее совпадение: примерно second cousin range": "Medium match: roughly second cousin range",
        "Дальнее совпадение: примерно third cousin range": "Distant match: roughly third cousin range",
        "Небольшое дальнее совпадение": "Small distant match",
        "Значимых сегментов выше порога не найдено": "No significant segments above the threshold",
    }
    if value in translations:
        return translations[value]
    if any("а" <= char.lower() <= "я" or char.lower() == "ё" for char in value):
        return _relationship_level(total_cm, longest_cm, lang=lang)[0]
    return value


def _relationship_caption_lines(result: PairwiseMatchResult, *, lang: str = "ru") -> list[str]:
    hint = _relationship_hint_text(result.relationship_hint or "", result.total_estimated_cm, result.longest_estimated_cm, lang=lang).strip()
    if not hint:
        return []

    signal, separator, details = hint.partition(":")
    signal = _sentence_lower(signal.strip())
    label = "Signal" if lang == "en" else "Сигнал"
    lines = [f"{label}: {html.escape(signal)}"]

    details = _relationship_range_label(details.strip(), lang=lang) if separator else ""
    if details:
        range_label = "Range" if lang == "en" else "Диапазон"
        lines.append(f"{range_label}: {html.escape(details)}")
    return lines


def _sentence_lower(value: str) -> str:
    if not value:
        return value
    return value[:1].lower() + value[1:]


def _relationship_range_label(value: str, *, lang: str = "ru") -> str:
    if not value:
        return ""
    if lang == "en":
        replacements = {
            "parent-child, full sibling, or a similar level": "parent-child / full sibling / similar level",
            "grandparent, aunt/uncle, half sibling, or a similar level": "grandparent / aunt/uncle / half sibling / similar level",
            "first cousin or a similar level": "first cousin / similar level",
        }
        return replacements.get(value, value)

    replacements = {
        "родитель-ребенок, full sibling или похожий уровень": "родитель–ребёнок / полные сиблинги / близкий уровень",
        "grandparent, aunt/uncle, half sibling или похожий уровень": "grandparent / aunt/uncle / half sibling / похожий уровень",
        "first cousin или похожий уровень": "first cousin / похожий уровень",
    }
    return replacements.get(value, value)


def _relationship_evidence(result: PairwiseMatchResult) -> str:
    parts = [
        f"total {result.total_estimated_cm:.0f} cM",
        f"longest {result.longest_estimated_cm:.0f} cM",
        f"segments {len(result.segments)}",
    ]
    if result.overlap_snps:
        identical_share = result.identical_snps / result.overlap_snps
        parts.append(f"identical SNP share {identical_share:.0%}")
    return ", ".join(parts)


def _float(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
