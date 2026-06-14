from __future__ import annotations

import html
from datetime import datetime

from .domain import DNAPassportData, DNAPassportTraitItem


MAX_TELEGRAM_TEXT_LENGTH = 4096

_TRAIT_LABELS_RU = {
    "pgs003835_height": "Рост",
    "pgs000336_chronotype": "Хронотип",
    "pgs001123_coffee": "Потребление кофе",
    "pgs001150_sleep_duration": "Длительность сна",
    "pgs001927_mean_hand_grip_strength": "Сила хвата",
    "pgs001075_walking_pace": "Темп ходьбы",
    "pgs001897_skin_pigmentation": "Пигментация кожи",
    "pgs002011_water_intake": "Потребление воды",
}


def render_dna_passport_html(data: DNAPassportData, *, lang: str = "ru") -> str:
    if lang == "en":
        text = _render_en(data)
    else:
        text = _render_ru(data)
    if len(text) <= MAX_TELEGRAM_TEXT_LENGTH:
        return text
    suffix = "\n\n…\n\nℹ️ Отчёт сокращён, чтобы поместиться в лимит Telegram."
    return text[: MAX_TELEGRAM_TEXT_LENGTH - len(suffix)].rstrip() + suffix


def _render_ru(data: DNAPassportData) -> str:
    sample_name = _escape(getattr(data.sample, "display_name", "") or "образец")
    lines = [
        "<b>🧬 DNA-паспорт</b>",
        "",
        f"Образец: <b>{sample_name}</b>",
        f"Сформирован: {_format_date(data.generated_at)}",
        "",
    ]

    if _has_no_source_data(data):
        lines.extend(
            [
                "Для этого образца пока недостаточно данных.",
                "",
                "Добавьте исходный DNA-файл или G25-профиль в разделе My DNA.",
                "",
            ]
        )

    lines.extend(_raw_block_ru(data))
    lines.extend(["", *_g25_block_ru(data)])
    lines.extend(["", *_traits_block_ru(data)])
    lines.extend(["", *_lineage_block_ru(data)])
    lines.extend(["", *_summary_block_ru(data)])
    lines.extend(["", *_important_block_ru()])
    return "\n".join(lines).strip()


def _render_en(data: DNAPassportData) -> str:
    sample_name = _escape(getattr(data.sample, "display_name", "") or "sample")
    lines = [
        "<b>🧬 DNA passport</b>",
        "",
        f"Sample: <b>{sample_name}</b>",
        f"Generated: {_format_date(data.generated_at)}",
        "",
    ]
    lines.extend(_raw_block_ru(data))
    lines.extend(["", *_g25_block_ru(data)])
    lines.extend(["", *_traits_block_ru(data)])
    lines.extend(["", *_lineage_block_ru(data)])
    lines.extend(["", *_summary_block_ru(data)])
    lines.extend(["", *_important_block_ru()])
    return "\n".join(lines).strip()


def _raw_block_ru(data: DNAPassportData) -> list[str]:
    raw = data.raw
    lines = ["<b>📁 DNA-файл</b>", ""]
    if raw is None or raw.status == "unavailable":
        lines.append("Исходный DNA-файл не прикреплён.")
        return lines
    if raw.status == "error":
        lines.append("Не удалось рассчитать этот раздел.")
        return lines
    lines.extend(
        [
            f"Файл: {_escape(raw.original_file_name or raw.display_name)}",
            f"Провайдер: {_escape(raw.provider_hint or 'не определён')}",
            f"Прочитано SNP: {_format_int(raw.called_snps)}",
            f"Call rate: {_format_percent(raw.call_rate)}",
            f"Аутосомы: {_format_int(raw.autosomal_count)}",
            f"X: {_format_int(raw.x_count)}",
            f"Y: {_format_int(raw.y_count)}",
            f"mtDNA: {_format_int(raw.mtdna_count)}",
        ]
    )
    if raw.skipped_invalid_count:
        lines.append(f"Пропущено строк: {_format_int(raw.skipped_invalid_count)}")
    return lines


def _g25_block_ru(data: DNAPassportData) -> list[str]:
    g25 = data.g25
    lines = ["<b>🧭 Краткое происхождение</b>", ""]
    if g25 is None or g25.status == "unavailable":
        lines.extend(
            [
                "G25-профиль не прикреплён.",
                "",
                "Добавьте координаты G25, чтобы получить краткое сравнение с референсными популяциями.",
            ]
        )
        return lines
    if g25.status == "error":
        if g25.source == "calculated_from_raw":
            lines.extend(
                [
                    "Не удалось получить координаты G25 из этого DNA-файла.",
                    "",
                    "Вы можете добавить готовый G25-профиль в My DNA.",
                ]
            )
            return lines
        lines.append("Не удалось рассчитать этот раздел.")
        return lines
    source_text = "G25: рассчитан из DNA-файла" if g25.source == "calculated_from_raw" else "G25: профиль образца"
    lines.extend(
        [
            source_text,
            f"Профиль: {_escape(g25.display_name or g25.target_name)}",
            f"Ближайшая зона: {_escape(g25.region or 'не определена')}",
            "",
        ]
    )
    for index, item in enumerate(g25.top_modern[:3], start=1):
        lines.append(f"{index}. {_escape(item.name)} — {_format_distance(item.distance)}")
    if g25.first_second_gap is not None:
        lines.extend(["", f"Отрыв от второго результата: {_format_distance(g25.first_second_gap)}"])
    return lines


def _traits_block_ru(data: DNAPassportData) -> list[str]:
    traits = data.traits
    lines = ["<b>✨ Базовые признаки</b>", ""]
    if traits is None or traits.status == "unavailable":
        lines.append("Недоступны без исходного DNA-файла.")
        return lines
    if traits.status == "error" and not traits.traits:
        lines.append("Не удалось рассчитать этот раздел.")
        return lines
    shown = 0
    for item in traits.traits:
        lines.append(_trait_line(item))
        shown += 1
    for item in traits.failures:
        lines.append(f"{_escape(_trait_label(item))} — недостаточно данных")
        shown += 1
    if shown == 0:
        lines.append("Недостаточно данных.")
    return lines


def _lineage_block_ru(data: DNAPassportData) -> list[str]:
    lineage = data.lineage
    lines = ["<b>🌿 Прямые линии</b>", ""]
    if lineage is None or lineage.status != "ok":
        lines.append("Недоступны без исходного DNA-файла.")
        return lines
    lines.extend(
        [
            f"Y-маркеры: {_detected(lineage.y_markers_detected)}",
            f"mtDNA-маркеры: {_detected(lineage.mtdna_markers_detected)}",
            "",
            "Аутосомный файл содержит ограниченный набор маркеров прямых линий. Для точного определения нужны специализированные тесты.",
        ]
    )
    return lines


def _summary_block_ru(data: DNAPassportData) -> list[str]:
    available = []
    if data.raw and data.raw.status == "ok":
        available.append("DNA-файл прочитан")
    if data.g25 and data.g25.status == "ok":
        available.append("G25-сравнение рассчитано")
    if data.traits and data.traits.traits:
        available.append("базовые признаки рассчитаны")
    if data.lineage and data.lineage.status == "ok":
        available.append("готовность Y/mtDNA оценена")
    summary = "; ".join(available) if available else "данных пока недостаточно"
    return ["<b>📌 Краткий итог</b>", "", _escape(summary) + "."]


def _important_block_ru() -> list[str]:
    return [
        "<b>ℹ️ Важно</b>",
        "",
        "Близость к референсным популяциям показывает генетическое сходство, но не определяет национальность или точные доли происхождения. Генетические признаки отражают статистические тенденции и не являются медицинским заключением.",
    ]


def _trait_line(item: DNAPassportTraitItem) -> str:
    label = _escape(_trait_label(item))
    if item.percentile is None:
        return f"{label} — недостаточно данных"
    return f"{label} — {_format_percentile(item.percentile)} · {_confidence_stars(item.confidence)}"


def _trait_label(item: DNAPassportTraitItem) -> str:
    return _TRAIT_LABELS_RU.get(item.trait_id, item.display_name or "Признак")


def _has_no_source_data(data: DNAPassportData) -> bool:
    raw_missing = data.raw is None or data.raw.status in {"unavailable", "error"}
    g25_missing = data.g25 is None or data.g25.status in {"unavailable", "error"}
    return raw_missing and g25_missing


def _format_date(value: str) -> str:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime("%d.%m.%Y")
    except Exception:
        return _escape(value or "")


def _format_int(value: int) -> str:
    return f"{int(value):,}".replace(",", " ")


def _format_percent(value: float | None) -> str:
    if value is None:
        return "н/д"
    return f"{value * 100:.1f}%"


def _format_percentile(value: float) -> str:
    return f"{round(float(value))}-й процентиль"


def _format_distance(value: float | None) -> str:
    if value is None:
        return "н/д"
    return f"{float(value) * 100:.2f}"


def _confidence_stars(value: str) -> str:
    normalized = (value or "").strip().lower()
    if normalized == "high":
        return "★★★"
    if normalized == "medium":
        return "★★☆"
    return "★☆☆"


def _detected(value: bool) -> str:
    return "обнаружены" if value else "не обнаружены"


def _escape(value: object) -> str:
    return html.escape(str(value or ""), quote=False)
