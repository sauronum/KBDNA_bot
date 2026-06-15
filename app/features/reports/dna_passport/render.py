from __future__ import annotations

import html
import re
from datetime import datetime

from .domain import DNAPassportData, DNAPassportInterestingSnpItem, DNAPassportTraitItem


MAX_TELEGRAM_TEXT_LENGTH = 4096
INTERESTING_SNP_PREVIEW_LIMIT = 5

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

_REGION_LABELS_RU = {
    "Caucasus": "Кавказ",
    "Caucasus_North": "Северный Кавказ",
    "North Caucasus": "Северный Кавказ",
    "West Eurasia": "Западная Евразия",
    "WestEurasia": "Западная Евразия",
    "Europe": "Европа",
    "East Eurasia": "Восточная Евразия",
    "Central Asia": "Центральная Азия",
    "South Asia": "Южная Азия",
    "Near East": "Ближний Восток",
    "Middle East": "Ближний Восток",
    "Steppe": "Степь",
}

_REGION_SUMMARY_RU = {
    "Кавказ": "к кавказскому генетическому пространству",
    "Северный Кавказ": "к северокавказскому генетическому пространству",
    "Западная Евразия": "к западноевразийскому генетическому пространству",
    "Восточная Евразия": "к восточноевразийскому генетическому пространству",
    "Центральная Азия": "к центральноазиатскому генетическому пространству",
    "Южная Азия": "к южноазиатскому генетическому пространству",
    "Ближний Восток": "к ближневосточному генетическому пространству",
    "Степь": "к степному генетическому пространству",
}

_POPULATION_LABELS_RU = {
    "Abazin": "Абазины",
    "Abkhazian": "Абхазы",
    "Adygei": "Адыгейцы",
    "Armenian": "Армяне",
    "Avar": "Аварцы",
    "Balkar": "Балкарцы",
    "Chechen": "Чеченцы",
    "Cherkes": "Черкесы",
    "Circassian": "Черкесы",
    "Dargin": "Даргинцы",
    "Georgian": "Грузины",
    "Ingush": "Ингуши",
    "Kabardin": "Кабардинцы",
    "Karachay": "Карачаевцы",
    "Kumyk": "Кумыки",
    "Lak": "Лакцы",
    "Lezgin": "Лезгины",
    "Nogai": "Ногайцы",
    "Ossetian": "Осетины",
    "Russian": "Русские",
    "Tabasaran": "Табасаранцы",
    "Turkish": "Турки",
}

_PROVIDER_LABELS_RU = {
    "23andMe": "23andMe",
    "FTDNA": "FamilyTreeDNA",
    "FamilyTreeDNA": "FamilyTreeDNA",
    "MyHeritage": "MyHeritage",
    "AncestryDNA": "AncestryDNA",
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
    lines.extend(["", *_interesting_snps_block_ru(data)])
    lines.extend(["", *_lineage_block_ru(data)])
    lines.extend(["", *_summary_block_ru(data)])
    lines.extend(["", *_recommendations_block_ru(data)])
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
    lines.extend(["", *_interesting_snps_block_ru(data)])
    lines.extend(["", *_lineage_block_ru(data)])
    lines.extend(["", *_summary_block_ru(data)])
    lines.extend(["", *_recommendations_block_ru(data)])
    lines.extend(["", *_important_block_ru()])
    return "\n".join(lines).strip()


def _raw_block_ru(data: DNAPassportData) -> list[str]:
    raw = data.raw
    lines = ["<b>📁 Исходные данные</b>", ""]
    if raw is None or raw.status == "unavailable":
        lines.append("Autosomal raw не прикреплён.")
        return lines
    if raw.status == "error":
        lines.append("Не удалось рассчитать этот раздел.")
        return lines
    provider = _display_provider(raw.provider_hint)
    lines.extend(
        [
            f"Файл: {_escape(raw.original_file_name or raw.display_name)}",
            f"Провайдер: {_escape(provider)}" if provider else "Формат: autosomal raw",
            f"Прочитано SNP: {_format_int(raw.called_snps)}",
            f"Качество чтения: {_format_percent(raw.call_rate)}",
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
    lines.extend(
        [
            f"Генетическое пространство: {_escape(_display_region(g25.region) or 'не определено')}",
            "",
            "Ближайшие референсные популяции:",
            "",
        ]
    )
    for index, item in enumerate(g25.top_modern[:3], start=1):
        lines.append(f"{index}. {_escape(_display_population(item.name))} — {_format_distance(item.distance)}")
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


def _interesting_snps_block_ru(data: DNAPassportData) -> list[str]:
    snps = data.interesting_snps
    lines = ["<b>🧪 Интересные SNP</b>", ""]
    if snps is None or snps.status == "unavailable":
        lines.append("Недоступны без autosomal raw.")
        return lines
    if snps.status == "error":
        lines.append("Не удалось рассчитать этот блок.")
        return lines
    items = _dedupe_interesting_snp_items(snps.items)
    if snps.status == "no_matches" or not items:
        lines.append("Готовых пользовательских трактовок не найдено.")
        return lines

    for item in items[:INTERESTING_SNP_PREVIEW_LIMIT]:
        lines.append(f"• {_interesting_snp_line(item)}")
    return lines


def _lineage_block_ru(data: DNAPassportData) -> list[str]:
    lineage = data.lineage
    lines = ["<b>🌿 Прямые линии</b>", ""]
    if lineage is None or lineage.status != "ok":
        lines.append("Недоступны без autosomal raw.")
        return lines
    lines.extend(
        [
            f"Отцовская линия: {_lineage_status(lineage.y_count, kind='y')}",
            f"Материнская линия: {_lineage_status(lineage.mtdna_count, kind='mtdna')}",
            "",
            "Для точного определения прямых линий нужны специализированные Y-DNA и mtDNA-тесты.",
        ]
    )
    return lines


def _summary_block_ru(data: DNAPassportData) -> list[str]:
    summary: list[str] = []
    if data.raw and data.raw.status == "ok":
        summary.append("Autosomal raw подходит для анализа происхождения и базовых генетических признаков.")
    if data.g25 and data.g25.status == "ok":
        region = _display_region(data.g25.region)
        populations = [_display_population(item.name).lower() for item in data.g25.top_modern[:3]]
        if region:
            region_phrase = _REGION_SUMMARY_RU.get(region, f"к генетическому пространству «{region}»")
            if populations:
                summary.append(
                    f"По G25 образец относится {region_phrase}. "
                    f"Наиболее близкие референсные популяции — {_join_ru(populations)}."
                )
            else:
                summary.append(f"По G25 образец относится {region_phrase}.")
    if not summary:
        summary.append("Для этого образца пока недостаточно данных для содержательного вывода.")
    if data.lineage and data.lineage.status == "ok":
        paternal = _lineage_status(data.lineage.y_count, kind="y")
        maternal = _lineage_status(data.lineage.mtdna_count, kind="mtdna")
        if "недоступна" in paternal or "ограниченные" in paternal or "недоступна" in maternal or "ограниченные" in maternal:
            summary.append("Для надёжного определения прямых отцовской и материнской линий нужны специализированные тесты.")
    return ["<b>📌 Краткий итог</b>", "", *(_escape(item) for item in summary)]


def _recommendations_block_ru(data: DNAPassportData) -> list[str]:
    recommendations: list[str] = []
    region = _display_region(data.g25.region) if data.g25 and data.g25.status == "ok" else ""
    if region in {"Кавказ", "Северный Кавказ"}:
        recommendations.append("Уточнить положение внутри Кавказа")
    if data.g25 and data.g25.status == "ok":
        recommendations.append("Провести расширенное исследование происхождения")
    elif not (data.g25 and data.g25.status == "ok"):
        recommendations.append("Добавить G25-профиль")
    if data.traits and data.traits.traits:
        recommendations.append("Изучить полный портрет признаков")
    if data.lineage and data.lineage.status == "ok":
        paternal = _lineage_status(data.lineage.y_count, kind="y")
        maternal = _lineage_status(data.lineage.mtdna_count, kind="mtdna")
        if "недоступна" in paternal or "ограниченные" in paternal or "недоступна" in maternal or "ограниченные" in maternal:
            recommendations.append("Уточнить прямые линии специализированными тестами")
    if not (data.raw and data.raw.status == "ok"):
        recommendations.append("Добавить autosomal raw")

    unique = []
    for item in recommendations:
        if item not in unique:
            unique.append(item)
    return ["<b>➡️ Что исследовать дальше</b>", "", *(f"• {_escape(item)}" for item in unique[:3])]


def _important_block_ru() -> list[str]:
    return [
        "<b>ℹ️ Важно</b>",
        "",
        "Близость к референсным популяциям показывает генетическое сходство, но не определяет национальность или точные доли происхождения.",
        "",
        "Проценты признаков показывают положение результата относительно референсной панели, а не вероятность наличия признака.",
        "",
        "Результаты генетических признаков не являются медицинским заключением.",
    ]


def _trait_line(item: DNAPassportTraitItem) -> str:
    label = _escape(_trait_label(item))
    if item.percentile is None:
        return f"{label} — недостаточно данных"
    return f"{label} — {_format_trait_percent(item.percentile)} · {_confidence_stars(item.confidence)}"


def _interesting_snp_line(item: DNAPassportInterestingSnpItem) -> str:
    title = _escape(item.title or item.rsid)
    genotype = _escape(item.genotype or "н/д")
    interpretation = _escape(_shorten(item.interpretation, limit=72))
    return f"{title}: {genotype} — {interpretation}"


def _dedupe_interesting_snp_items(items: tuple[DNAPassportInterestingSnpItem, ...]) -> tuple[DNAPassportInterestingSnpItem, ...]:
    result: list[DNAPassportInterestingSnpItem] = []
    seen: set[str] = set()
    for item in items:
        key = _interesting_snp_topic_key(item)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return tuple(result)


def _interesting_snp_topic_key(item: DNAPassportInterestingSnpItem) -> str:
    title = str(item.title or "").strip().lower()
    if ":" in title:
        title = title.split(":", 1)[0].strip()
    title = re.sub(r"\s+", " ", title)
    return title or str(item.rsid or "").strip().lower()


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
    return f"{value * 100:.1f}%".replace(".", ",")


def _format_trait_percent(value: float) -> str:
    return f"{round(float(value))}%"


def _format_distance(value: float | None) -> str:
    if value is None:
        return "н/д"
    return f"{float(value) * 100:.2f}".replace(".", ",")


def _confidence_stars(value: str) -> str:
    normalized = (value or "").strip().lower()
    if normalized == "high":
        return "★★★"
    if normalized == "medium":
        return "★★☆"
    return "★☆☆"


def _lineage_status(count: int, *, kind: str) -> str:
    value = max(0, int(count or 0))
    if value <= 0:
        return "недоступна по этому файлу"
    threshold = 50 if kind == "y" else 200
    if value < threshold:
        return "ограниченные данные"
    return "данные обнаружены"


def _display_provider(value: str) -> str:
    normalized = str(value or "").strip()
    if "/" in normalized or "like" in normalized.lower():
        return ""
    return _PROVIDER_LABELS_RU.get(normalized, normalized if normalized in set(_PROVIDER_LABELS_RU.values()) else "")


def _display_region(value: str) -> str:
    normalized = " ".join(str(value or "").replace("_", " ").split())
    return _REGION_LABELS_RU.get(value, _REGION_LABELS_RU.get(normalized, normalized))


def _display_population(value: str) -> str:
    raw = str(value or "").strip()
    base = re.split(r"[:;,]", raw, maxsplit=1)[0].strip()
    base = re.sub(r"_(?:average|modern|scaled)$", "", base, flags=re.I)
    label = _POPULATION_LABELS_RU.get(base)
    if label:
        return label
    cleaned = " ".join(raw.replace("_", " ").split())
    return cleaned or raw


def _join_ru(items: list[str]) -> str:
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} и {items[1]}"
    return f"{', '.join(items[:-1])} и {items[-1]}"


def _shorten(value: object, *, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _escape(value: object) -> str:
    return html.escape(str(value or ""), quote=False)
