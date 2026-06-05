from __future__ import annotations

import html

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.features.my_data.storage import SampleAsset
from app.i18n import t

from .domain import RawHaplogroupScan, YHaplogroupPrediction, YStrDistanceResult
from .storage import HaplogroupRecord, YStrProfile


def _copy(lang: str, ru: str, en: str) -> str:
    return en if lang == "en" else ru


def _back_label(lang: str) -> str:
    return "⬅️ Назад" if lang != "en" else "⬅️ Back"


def _cancel_label(lang: str) -> str:
    return t("nav.cancel", lang)


def build_markup(rows: list[list[InlineKeyboardButton]], back_callback: str, *, lang: str = "ru") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        rows
        + [[
            InlineKeyboardButton(_back_label(lang), callback_data=back_callback),
            InlineKeyboardButton(_cancel_label(lang), callback_data="haplogroups:cancel"),
        ]]
    )


def haplogroups_root_text(lang: str = "ru") -> str:
    return "\n".join(
        [
            "<b>🌿 Haplogroups</b>",
            "",
            f"<b>{_copy(lang, 'Разделы', 'Sections')}</b>",
            "🧬 Y-DNA",
            "🧬 mtDNA",
            "🧮 Y-STR distance",
            "📚 Saved by sample",
        ]
    )


def lineage_menu_text(haplogroup_type: str, lang: str = "ru") -> str:
    if haplogroup_type == "Y-DNA":
        body = _copy(
            lang,
            "Y-SNP/raw prediction, импорт FTDNA SNP Results и сохранённые Y-DNA ветки.",
            "Y-SNP/raw prediction, FTDNA SNP Results import and saved Y-DNA branches.",
        )
    else:
        body = _copy(
            lang,
            "Проверка mtDNA-маркеров в raw, импорт внешнего результата и сохранённые mtDNA ветки.",
            "mtDNA marker scan from raw data, external result import and saved mtDNA branches.",
        )
    return "\n".join([f"<b>🧬 {html.escape(haplogroup_type)}</b>", "", f"<b>{_copy(lang, 'Что доступно', 'What you can do')}</b>", body])


def saved_samples_text(samples: list[SampleAsset], lang: str = "ru") -> str:
    lines = [
        "<b>📚 Saved by sample</b>",
        "",
        _copy(lang, "Выберите sample, чтобы открыть связанные Y-DNA/mtDNA записи.", "Choose a sample to open linked Y-DNA/mtDNA records."),
        "",
        f"<b>Samples:</b> {len(samples)}",
    ]
    if not samples:
        lines.extend(["", _copy(lang, "Пока нет sample. Сначала создайте sample в My DNA.", "No samples yet. Create a sample in My DNA first.")])
    return "\n".join(lines)


def upload_result_text(samples: list[SampleAsset], lang: str = "ru") -> str:
    lines = [
        "<b>📤 Upload test result</b>",
        "",
        _copy(lang, "Выберите sample для внешнего Y-DNA, mtDNA или Y-STR/DYS файла.", "Choose sample for an external Y-DNA, mtDNA or Y-STR/DYS result file."),
        "",
        f"<b>Samples:</b> {len(samples)}",
    ]
    if not samples:
        lines.extend(["", _copy(lang, "Пока нет sample. Сначала создайте sample в My DNA.", "No samples yet. Create a sample in My DNA first.")])
    return "\n".join(lines)


def upload_result_prompt_text(sample: SampleAsset, lang: str = "ru") -> str:
    return "\n".join(
        [
            "<b>📤 Upload test result</b>",
            "",
            f"Sample: <b>{html.escape(sample.display_name)}</b>",
            "",
            _copy(
                lang,
                "Пришлите .txt, .csv или .tsv файл с haplogroup-полями или FTDNA SNP Results.",
                "Send a .txt, .csv or .tsv result file with haplogroup fields or FTDNA SNP Results.",
            ),
            "",
            _copy(lang, "Поддерживаемые примеры:", "Supported examples:"),
            "<pre>Y-DNA Haplogroup: J2a1a2a",
            "Y-DNA Terminal SNP: PF5116",
            "mtDNA Haplogroup: H13a1a",
            "",
            "SNP Name,Test Results,Test Type",
            "PF5116,Positive,Family Finder",
            "",
            "DYS393,DYS390,DYS19",
            "14,22,15</pre>",
        ]
    )


def imported_records_text(sample: SampleAsset, records: list[HaplogroupRecord], lang: str = "ru") -> str:
    lines = [
        f"<b>✅ {_copy(lang, 'Haplogroup-файл импортирован', 'Haplogroup file imported')}</b>",
        "",
        f"Sample: <b>{html.escape(sample.display_name)}</b>",
        f"{_copy(lang, 'Сохранено записей', 'Records saved')}: {len(records)}",
    ]
    for record in records:
        label = f"{record.haplogroup_type}: {record.haplogroup}"
        if record.terminal_snp:
            label += f" ({record.terminal_snp})"
        lines.append(html.escape(label))
        if record.note:
            lines.append(html.escape(record.note.replace("\n", " | ")[:220]))
    return "\n".join(lines)


def imported_str_profile_text(sample: SampleAsset, profile: YStrProfile, lang: str = "ru") -> str:
    return "\n".join(
        [
            f"<b>✅ {_copy(lang, 'Y-STR профиль импортирован', 'Y-STR profile imported')}</b>",
            "",
            f"Sample: <b>{html.escape(sample.display_name)}</b>",
            f"{_copy(lang, 'Сохранено маркеров', 'Markers saved')}: {profile.marker_count}",
            f"{_copy(lang, 'Источник', 'Source')}: {html.escape(profile.source)}",
            "",
            _str_marker_table(profile),
        ]
    )


def str_profiles_text(profiles: list[YStrProfile], lang: str = "ru") -> str:
    lines = [
        "<b>🧮 Y-STR distance</b>",
        "",
        f"{_copy(lang, 'Сохранено профилей', 'Saved profiles')}: {len(profiles)}",
    ]
    if len(profiles) >= 2:
        lines.extend(["", _copy(lang, "Выберите два профиля, чтобы сравнить STR distance по маркерам.", "Choose two profiles to compare marker-by-marker STR distance.")])
    elif len(profiles) == 1:
        lines.extend(["", _copy(lang, "Сохранён один профиль. Загрузите ещё один Y-STR/DYS результат для сравнения.", "One profile is saved. Upload another Y-STR/DYS result to compare distance.")])
    else:
        lines.extend(["", _copy(lang, "Y-STR/DYS профилей пока нет. Сначала загрузите FTDNA Y-DNA DYS CSV.", "No Y-STR/DYS profiles yet. Upload an FTDNA Y-DNA DYS CSV first.")])
    return "\n".join(lines)


def str_profile_detail_text(profile: YStrProfile, lang: str = "ru") -> str:
    return "\n".join(
        [
            "<b>📈 Y-STR profile</b>",
            "",
            f"Sample: <b>{html.escape(profile.sample_name)}</b>",
            f"{_copy(lang, 'Маркеры', 'Markers')}: {profile.marker_count}",
            f"{_copy(lang, 'Источник', 'Source')}: {html.escape(profile.source)}",
            f"{_copy(lang, 'Сохранено', 'Saved')}: {html.escape(profile.created_at)}",
            "",
            _str_marker_table(profile),
        ]
    )


def str_compare_picker_text(profiles: list[YStrProfile], left: YStrProfile | None = None, lang: str = "ru") -> str:
    lines = [
        "<b>🧮 Compare Y-STR distance</b>",
        "",
    ]
    if left is None:
        lines.append(_copy(lang, "Выберите профиль A.", "Choose A profile."))
    else:
        lines.append(f"A: <b>{html.escape(left.sample_name)}</b>")
        lines.append(_copy(lang, "Выберите профиль B.", "Choose B profile."))
    lines.append(f"{_copy(lang, 'Профили', 'Profiles')}: {len(profiles)}")
    return "\n".join(lines)


def str_distance_text(result: YStrDistanceResult, lang: str = "ru") -> str:
    lines = [
        "<b>🧮 Y-STR distance</b>",
        "",
        f"A: <b>{html.escape(result.left_name)}</b>",
        f"B: <b>{html.escape(result.right_name)}</b>",
        f"{_copy(lang, 'Сравнено маркеров', 'Compared markers')}: {result.compared_markers}",
        f"{_copy(lang, 'Генетическая дистанция', 'Genetic distance')}: <b>{result.distance}</b>",
    ]
    if result.differences:
        lines.extend(["", f"<b>{_copy(lang, 'Отличающиеся маркеры', 'Different markers')}</b>", _str_difference_table(result)])
    else:
        lines.extend(["", _copy(lang, "В общих маркерах отличий нет.", "No differences in shared markers.")])
    return "\n".join(lines)


def raw_detect_type_text(lang: str = "ru") -> str:
    return "\n".join(
        [
            "<b>🧬 Detect from raw</b>",
            "",
            _copy(lang, "Выберите, какие маркеры искать в raw-файле sample.", "Choose which markers to scan in the sample raw file."),
        ]
    )


def manual_type_text(lang: str = "ru") -> str:
    return "\n".join(
        [
            f"<b>{_copy(lang, '🌿 Добавить гаплогруппу', '🌿 Add haplogroup')}</b>",
            "",
            _copy(lang, "Выберите тип линии:", "Choose the lineage type:"),
        ]
    )


def sample_picker_text(samples: list[SampleAsset], haplogroup_type: str, *, mode: str = "manual", lang: str = "ru") -> str:
    title = f"🧬 Raw {haplogroup_type} scan" if mode == "detect" else _copy(lang, f"🌿 Добавить {haplogroup_type}", f"🌿 Add {haplogroup_type}")
    lines = [
        f"<b>{html.escape(title)}</b>",
        "",
        _copy(lang, "Выберите sample.", "Choose a sample."),
        "",
        f"<b>Samples:</b> {len(samples)}",
    ]
    if not samples:
        lines.extend(["", _copy(lang, "Пока нет sample. Сначала создайте sample в My DNA.", "No samples yet. Create a sample in My DNA first.")])
    return "\n".join(lines)


def haplogroup_input_text(sample: SampleAsset, haplogroup_type: str, lang: str = "ru") -> str:
    return "\n".join(
        [
            f"<b>{_copy(lang, '🌿 Добавить гаплогруппу', '🌿 Add haplogroup')}</b>",
            "",
            f"Sample: <b>{html.escape(sample.display_name)}</b>",
            "",
            _copy(lang, "Пришлите ветку текстом.", "Send the branch as text."),
            "",
            _copy(lang, "Пример:", "Example:"),
            "<pre>J2a1a1b2",
            "terminal: J-Y12345",
            "source: FTDNA",
            "confidence: confirmed",
            "note: Big Y result</pre>",
        ]
    )


def records_list_text(
    records: list[HaplogroupRecord],
    *,
    sample: SampleAsset | None = None,
    haplogroup_type: str | None = None,
    lang: str = "ru",
) -> str:
    title = "🌿 Haplogroup reports" if sample is not None else "💾 Saved haplogroups"
    lines = [
        f"<b>{title}</b>",
        "",
    ]
    if sample is not None:
        lines.append(f"Sample: <b>{html.escape(sample.display_name)}</b>")
    if haplogroup_type:
        lines.append(f"Type: {html.escape(haplogroup_type)}")
    lines.append(f"{_copy(lang, 'Сохранено записей', 'Saved records')}: {len(records)}")
    if records:
        lines.extend(["", _copy(lang, "Выберите запись.", "Choose a record.")])
    else:
        lines.extend(["", _copy(lang, "Пока нет сохранённых haplogroup-записей.", "There are no saved haplogroup records yet.")])
    return "\n".join(lines)


def record_button_label(record: HaplogroupRecord, *, include_sample: bool = False) -> str:
    label = f"{record.haplogroup_type}: {record.haplogroup}"
    if record.terminal_snp:
        label += f" ({record.terminal_snp})"
    if include_sample:
        label = f"{record.sample_name}: {label}"
    return label[:60]


def record_saved_text(record: HaplogroupRecord, lang: str = "ru") -> str:
    return "\n".join(
        [
            f"<b>✅ {_copy(lang, 'Haplogroup сохранён', 'Haplogroup saved')}</b>",
            "",
            f"Sample: <b>{html.escape(record.sample_name)}</b>",
            f"Type: {html.escape(record.haplogroup_type)}",
            f"Haplogroup: <b>{html.escape(record.haplogroup)}</b>",
            *([f"Terminal SNP: {html.escape(record.terminal_snp)}"] if record.terminal_snp else []),
            *([f"Source: {html.escape(record.source)}"] if record.source else []),
            f"Confidence: {html.escape(record.confidence)}",
        ]
    )


def record_detail_text(record: HaplogroupRecord, lang: str = "ru") -> str:
    lines = [
        "<b>🌿 Haplogroup report</b>",
        "",
        f"Sample: <b>{html.escape(record.sample_name)}</b>",
        f"Type: {html.escape(record.haplogroup_type)}",
        f"Haplogroup: <b>{html.escape(record.haplogroup)}</b>",
    ]
    if record.terminal_snp:
        lines.append(f"Terminal SNP: {html.escape(record.terminal_snp)}")
    if record.source:
        lines.append(f"Source: {html.escape(record.source)}")
    lines.append(f"Confidence: {html.escape(record.confidence)}")
    if record.note:
        lines.extend(["", html.escape(record.note)])
    lines.extend(["", f"{_copy(lang, 'Сохранено', 'Saved')}: {html.escape(record.created_at)}"])
    return "\n".join(lines)


def error_text(title: str, message: str) -> str:
    return f"<b>{html.escape(title)}</b>\n\n{html.escape(message)}"


def raw_scan_result_text(sample: SampleAsset, scan: RawHaplogroupScan, *, lang: str = "ru") -> str:
    lines = [
        f"<b>🧬 Raw {html.escape(scan.haplogroup_type)} scan</b>",
        "",
        f"Sample: <b>{html.escape(sample.display_name)}</b>",
        f"Vendor hint: {html.escape(scan.vendor_hint)}",
        f"Chromosomes checked: {', '.join(scan.target_chromosomes)}",
        f"Markers in raw: {scan.total_markers}",
        f"Called markers: {scan.called_markers}",
        f"Status: {html.escape(scan.status)}",
        "",
        html.escape(_haplogroup_note(scan.note, lang=lang)),
    ]
    counts = _interesting_chromosome_counts(scan)
    if counts:
        lines.extend(["", f"Raw chromosome counts: {html.escape(counts)}"])
    genotype_counts = _target_genotype_counts(scan)
    if genotype_counts:
        lines.append(f"Target genotype counts: {html.escape(genotype_counts)}")
    if scan.usable_markers:
        lines.extend(["", "<b>Example markers</b>", _marker_table(scan)])
    elif scan.marker_examples:
        lines.extend(["", "<b>Raw marker examples</b>", _marker_table(scan, called_only=False)])
    return "\n".join(lines)


def y_prediction_text(sample: SampleAsset, prediction: YHaplogroupPrediction, *, lang: str = "ru") -> str:
    lines = [
        "<b>🧬 Y-DNA prediction</b>",
        "",
        f"Sample: <b>{html.escape(sample.display_name)}</b>",
        f"Matched reference markers: {prediction.matched_reference_markers}",
        f"Positive SNPs: {len(prediction.positive_calls)}",
        f"Conflicting positives: {len(prediction.conflicting_positive_calls)}",
        f"Negative SNPs: {len(prediction.negative_calls)}",
        f"Ambiguous SNPs: {len(prediction.ambiguous_calls)}",
    ]
    if prediction.haplogroup:
        lines.extend(
            [
                "",
                f"Likely haplogroup: <b>{html.escape(prediction.haplogroup)}</b>",
                f"Deepest positive SNP: <b>{html.escape(prediction.terminal_snp)}</b>",
                f"Confidence: {html.escape(prediction.confidence)}",
            ]
        )
    else:
        lines.extend(["", "Likely haplogroup: no call", f"Confidence: {html.escape(prediction.confidence)}"])
    lines.extend(["", html.escape(_haplogroup_note(prediction.note, lang=lang))])
    if prediction.lineage_counts:
        lines.extend(["", f"Lineage vote: {html.escape(_lineage_vote_text(prediction))}"])
    if prediction.positive_calls:
        lines.extend(["", "<b>Top positive SNPs</b>", _ysnp_table(prediction.positive_calls)])
    if prediction.conflicting_positive_calls:
        lines.extend(["", "<b>Conflicting positives</b>", _ysnp_table(prediction.conflicting_positive_calls)])
    if prediction.ambiguous_calls:
        lines.extend(["", "<b>Ambiguous SNPs</b>", _ysnp_table(prediction.ambiguous_calls)])
    return "\n".join(lines)


def _marker_table(scan: RawHaplogroupScan, *, called_only: bool = True) -> str:
    rows = [("rsid", "chr", "pos", "gt")]
    markers = scan.usable_markers if called_only else scan.marker_examples
    for call in markers[:12]:
        rows.append((call.rsid[:16], call.chromosome, str(call.position), call.genotype))
    widths = [max(len(row[index]) for row in rows) for index in range(len(rows[0]))]
    rendered = []
    for row in rows:
        rendered.append("  ".join(value.ljust(widths[index]) for index, value in enumerate(row)))
    return "<pre>" + html.escape("\n".join(rendered)) + "</pre>"


def _interesting_chromosome_counts(scan: RawHaplogroupScan) -> str:
    keys = ("X", "23", "Y", "24", "M", "MT", "25", "26")
    parts = [
        f"{key}:{scan.chromosome_counts[key]}"
        for key in keys
        if scan.chromosome_counts.get(key)
    ]
    return ", ".join(parts)


def _target_genotype_counts(scan: RawHaplogroupScan) -> str:
    parts = [
        f"{genotype}:{count}"
        for genotype, count in list(scan.genotype_counts.items())[:6]
    ]
    return ", ".join(parts)


def _haplogroup_note(note: str, *, lang: str = "ru") -> str:
    if lang != "en":
        return note
    translations = {
        "Этот тип haplogroup не поддержан.": "This haplogroup type is not supported.",
        "В raw есть достаточно маркеров для внешнего haplogroup predictor; локального дерева для финальной ветки пока нет.": "The raw file has enough markers for an external haplogroup predictor; a local tree for the final branch is not available yet.",
        "В raw есть маркеры, но их мало для уверенного локального определения ветки.": "The raw file has markers, but too few for a confident local branch call.",
        "Найдено слишком мало маркеров; haplogroup по этому raw ненадёжен.": "Too few markers were found; a haplogroup call from this raw file is unreliable.",
        "В raw не найдено пригодных маркеров этого типа.": "No usable markers of this type were found in the raw file.",
        "Не найдено usable non-upstream derived Y-SNP из локальной reference table.": "No usable non-upstream derived Y-SNP was found in the local reference table.",
        "Prediction основан на локальной ISOGG/Yhaplo 2016 reference table и autosomal raw Y-SNP; это не замена Big Y/YFull.": "Prediction is based on a local ISOGG/Yhaplo 2016 reference table and autosomal raw Y-SNPs; it is not a replacement for Big Y/YFull.",
    }
    return translations.get(note, note)


def _ysnp_table(calls) -> str:
    rows = [("SNP", "Hg", "pos", "gt", "mut")]
    for call in calls[:12]:
        rows.append(
            (
                call.snp_name[:14],
                call.haplogroup[:14],
                str(call.position),
                call.genotype,
                f"{call.ancestral}>{call.derived}",
            )
        )
    widths = [max(len(row[index]) for row in rows) for index in range(len(rows[0]))]
    rendered = []
    for row in rows:
        rendered.append("  ".join(value.ljust(widths[index]) for index, value in enumerate(row)))
    return "<pre>" + html.escape("\n".join(rendered)) + "</pre>"


def _str_marker_table(profile: YStrProfile) -> str:
    rows = [("Marker", "Value")]
    for marker, values in list(sorted(profile.marker_values.items()))[:30]:
        rows.append((marker, "-".join(str(value) for value in values)))
    widths = [max(len(row[index]) for row in rows) for index in range(len(rows[0]))]
    rendered = ["  ".join(value.ljust(widths[index]) for index, value in enumerate(row)) for row in rows]
    return "<pre>" + html.escape("\n".join(rendered)) + "</pre>"


def _str_difference_table(result: YStrDistanceResult) -> str:
    rows = [("Marker", "A", "B", "d")]
    for marker, left, right, distance in result.differences[:30]:
        rows.append((marker, left, right, str(distance)))
    widths = [max(len(row[index]) for row in rows) for index in range(len(rows[0]))]
    rendered = ["  ".join(value.ljust(widths[index]) for index, value in enumerate(row)) for row in rows]
    return "<pre>" + html.escape("\n".join(rendered)) + "</pre>"


def _lineage_vote_text(prediction: YHaplogroupPrediction) -> str:
    return ", ".join(f"{lineage}:{count}" for lineage, count in prediction.lineage_counts[:6])
