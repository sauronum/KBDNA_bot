from __future__ import annotations

import re
from datetime import datetime
from html import escape

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.features.my_data.storage import SampleAsset

from .domain.catalog import TraitCatalogEntry, TraitDetail
from .storage import TraitReportRecord, TraitReportSummary
from .texts import (
    localize_confidence,
    localize_group,
    localize_interpretation,
    localize_product_status,
    localize_status,
    localize_trait_name,
    text,
)


_UI_COPY = {
    "ru": {
        "overview": "Обзор",
        "flow": "Как это работает",
        "section_hint": "Выберите раздел ниже.",
        "trait_hint": "Выберите признак:",
        "sample_hint": "Выберите образец ниже.",
        "no_raw_samples": "Пока нет sample с raw-файлом.",
        "details": "Кратко",
        "description": "Описание",
        "reference": "Референсная панель",
        "result": "Итог",
        "interpretation": "Как это читать",
        "metrics": "Метрики",
        "technical": "Технические детали",
        "technical_short": "Технически",
        "pgs_id_label": "PGS ID",
        "trait_info_title": "ℹ️ О признаке",
        "group_field": "Раздел",
        "what_it_shows": "Что показывает",
        "important": "Важно",
        "research_warning": "Это исследовательская генетическая оценка. Она не является медицинским диагнозом.",
        "reference_in_calculation": "В расчёте",
        "original_trait_name": "Исходное название",
        "in_progress": "Идет расчет",
        "completed": "Расчет завершен",
        "page": "Страница",
        "not_available": "n/a",
        "available_traits": "Доступно признаков",
        "consumer_ready_traits": "Готово для выдачи",
        "usable_traits": "Готово к расчету",
        "reports_title": "Отчеты по traits",
        "saved_reports": "Сохранено отчетов",
        "overlap": "Покрытие",
        "sample_label": "Образец",
        "saved_at": "Сохранено",
        "status_mode": "Режим выдачи",
        "outcome_very_low": "Заметно ниже среднего",
        "outcome_low": "Ниже среднего",
        "outcome_mid": "Около среднего",
        "outcome_high": "Выше среднего",
        "outcome_very_high": "Заметно выше среднего",
        "outcome_unknown": "Без уверенного вывода",
    },
    "en": {
        "overview": "Overview",
        "flow": "How it works",
        "section_hint": "Choose a section below.",
        "trait_hint": "Choose a trait:",
        "sample_hint": "Choose a sample below.",
        "no_raw_samples": "There are no samples with raw files yet.",
        "details": "Details",
        "description": "Description",
        "reference": "Reference panel",
        "result": "Result",
        "interpretation": "How to read",
        "metrics": "Metrics",
        "technical": "Technical details",
        "technical_short": "Technical",
        "pgs_id_label": "PGS ID",
        "trait_info_title": "ℹ️ About this trait",
        "group_field": "Section",
        "what_it_shows": "What it shows",
        "important": "Important",
        "research_warning": "This is a research genetic estimate. It is not a medical diagnosis.",
        "reference_in_calculation": "In calculation",
        "original_trait_name": "Original name",
        "in_progress": "Calculation in progress",
        "completed": "Calculation completed",
        "page": "Page",
        "not_available": "n/a",
        "available_traits": "Available traits",
        "consumer_ready_traits": "Consumer-ready",
        "usable_traits": "Ready to run",
        "reports_title": "Trait reports",
        "saved_reports": "Saved reports",
        "overlap": "Overlap",
        "sample_label": "Sample",
        "saved_at": "Saved",
        "status_mode": "Delivery mode",
        "outcome_very_low": "Well below average",
        "outcome_low": "Below average",
        "outcome_mid": "Around average",
        "outcome_high": "Above average",
        "outcome_very_high": "Well above average",
        "outcome_unknown": "No clear summary",
    },
}

_RU_SHORT_TRAIT_LABELS = {
    "pgs001071_facial_aging_about_age": "Возраст по лицу",
    "pgs001092_hair_black": "Черные волосы",
    "pgs001093_hair_blonde": "Светлые волосы",
    "pgs001094_hair_brown": "Каштановые волосы",
    "pgs001095_hair_dark_brown": "Темно-каштановые волосы",
    "pgs001096_hair_light_brown": "Светло-каштановые волосы",
    "pgs001373_age_started_wearing_glasses": "Возраст первых очков",
    "pgs001924_glasses_contact_lenses": "Очки/линзы",
    "pgs001099_left_eye_spherical_power": "Левый глаз: сфера",
    "pgs001100_right_eye_spherical_power": "Правый глаз: сфера",
    "pgs001987_male_pattern_baldness": "Андрогенетическое облысение",
    "pgs001072_facial_aging_older": "Выглядеть старше по лицу",
    "pgs001097_hair_other": "Другой цвет волос",
    "pgs001098_hair_red": "Рыжие волосы",
    "pgs001897_skin_pigmentation": "Пигментация кожи",
    "pgs001244_tanning": "Загар кожи",
    "pgs001141_facial_aging_younger": "Выглядеть моложе по лицу",
    "pgs005315_appendicular_lean_mass": "Безжировая масса конечностей",
    "pgs000841_bmi": "ИМТ",
    "pgs000843_whr_adjusted_bmi": "Талия/бедра с поправкой на ИМТ",
    "pgs005316_body_fat_mass": "Жировая масса тела",
    "pgs002812_gluteofemoral_adipose_tissue_volume": "Глютеофеморальный жир",
    "pgs002813_visceral_adipose_tissue_volume": "Висцеральный жир",
    "pgs001101_body_fat_percentage": "Процент жира в теле",
    "pgs001230_body_weight": "Масса тела",
    "pgs001162_hip_circumference": "Окружность бедер",
    "pgs001169_lean_body_mass": "Безжировая масса тела",
    "pgs001227_waist_circumference": "Окружность талии",
    "pgs000842_waist_hip_ratio": "Соотношение талии и бедер",
    "pgs000336_chronotype": "Хронотип",
    "pgs000984_computer_games_frequency": "Компьютерные игры",
    "pgs001019_gym_sports_club_attendance": "Посещение спортзала",
    "pgs001000_daytime_nap": "Дневной сон",
    "pgs001119_left_hand_grip_strength": "Сила хвата левой руки",
    "pgs001927_mean_hand_grip_strength": "Средняя сила хвата",
    "pgs002255_measured_physical_activity": "Измеренная физическая активность",
    "pgs001074_other_exercise_types": "Другие виды упражнений",
    "pgs001120_right_hand_grip_strength": "Сила хвата правой руки",
    "pgs002254_self_reported_physical_activity": "Самооцененная физическая активность",
    "pgs001150_sleep_duration": "Длительность сна",
    "pgs001932_sleeplessness_insomnia": "Бессонница",
    "pgs001923_screen_time_tv_computer": "Экранное время",
    "pgs001080_tiredness_lethargy": "Усталость",
    "pgs001075_walking_pace": "Обычный темп ходьбы",
    "pgs001073_duration_of_walks": "Длительность прогулок",
    "pgs001397_walking_for_pleasure_frequency": "Прогулки ради удовольствия",
    "pgs002011_water_intake": "Потребление воды",
    "pgs000991_never_eat_sugar": "Избегание сахара",
    "pgs000993_oily_fish_intake": "Жирная рыба",
    "pgs000994_tea_consumption": "Потребление чая",
    "pgs001064_skimmed_milk_consumption": "Обезжиренное молоко",
    "pgs001058_biscuit_cereal_consumption": "Злаковые хлопья/бисквит",
    "pgs001059_other_cereal_consumption": "Другие злаки",
    "pgs001061_cooked_vegetable_consumption": "Вареные овощи",
    "pgs001067_processed_meat_intake": "Обработанное мясо",
    "pgs000978_bread_intake": "Потребление хлеба",
    "pgs001389_dried_fruit_intake": "Сухофрукты",
    "pgs001125_instant_coffee_consumption": "Растворимый кофе",
    "pgs001126_coffee_intake": "Количество кофе",
    "pgs001034_salt_added_to_food": "Соль в еде",
    "pgs001044_glucosamine_intake": "Глюкозамин",
    "pgs001056_beef_intake": "Говядина",
    "pgs001057_cereal_consumption": "Злаки/каши",
    "pgs001060_cheese_intake": "Сыр",
    "pgs001062_fresh_fruit_intake": "Свежие фрукты",
    "pgs001066_poultry_intake": "Птица",
    "pgs001068_variation_in_diet": "Разнообразие диеты",
    "pgs001069_water_intake": "Количество воды",
    "pgs001124_ground_coffee_consumption": "Молотый кофе",
    "pgs001518_portion_size": "Размер порции",
    "pgs001018_social_leisure_activities": "Социальная активность",
    "pgs001020_adult_education_class_attendance": "Образовательные занятия",
    "pgs001398_friendship_satisfaction": "Удовлетворенность дружбой",
    "pgs000969_sitting_height": "Рост сидя",
    "pgs000998_childhood_height": "Рост в детстве",
    "pgs001002_whole_body_water_mass": "Водная масса тела",
    "pgs001006_weight_change_one_year": "Изменение веса за год",
    "pgs001102_left_arm_body_fat_percentage": "Жир левой руки",
    "pgs001103_left_leg_body_fat_percentage": "Жир левой ноги",
    "pgs001104_right_leg_body_fat_percentage": "Жир правой ноги",
    "pgs001105_trunk_body_fat_percentage": "Жир туловища",
    "pgs001106_right_arm_body_fat_percentage": "Жир правой руки",
    "pgs001144_left_arm_fat_mass": "Жировая масса левой руки",
    "pgs001145_right_arm_fat_mass": "Жировая масса правой руки",
    "pgs001146_right_arm_fat_free_mass": "Безжировая масса правой руки",
    "pgs001147_right_leg_fat_mass": "Жировая масса правой ноги",
    "pgs001148_trunk_fat_mass": "Жировая масса туловища",
    "pgs001149_whole_body_fat_mass": "Жировая масса тела",
    "pgs001154_left_arm_impedance": "Импеданс левой руки",
    "pgs001155_left_leg_impedance": "Импеданс левой ноги",
    "pgs001156_right_arm_impedance": "Импеданс правой руки",
    "pgs001157_right_leg_impedance": "Импеданс правой ноги",
    "pgs001158_left_leg_mass": "Масса левой ноги",
    "pgs001159_right_leg_mass": "Масса правой ноги",
    "pgs001160_trunk_mass": "Масса туловища",
    "pgs001161_whole_body_impedance": "Импеданс тела",
    "pgs001165_left_arm_fat_free_mass": "Безжировая масса левой руки",
    "pgs001166_left_leg_fat_free_mass": "Безжировая масса левой ноги",
    "pgs001167_right_leg_fat_free_mass": "Безжировая масса правой ноги",
    "pgs001168_trunk_fat_free_mass": "Безжировая масса туловища",
    "pgs001226_birth_weight": "Вес при рождении",
    "pgs001379_body_surface_area": "Площадь поверхности тела",
    "pgs001234_left_arm_mass": "Масса левой руки",
    "pgs001235_right_arm_mass": "Масса правой руки",
    "pgs001245_moderate_skin_tanning": "Умеренный загар",
    "pgs001246_very_tanned_skin": "Сильный загар",
    "pgs001247_never_tan_only_burn": "Не загорает, обгорает",
    "pgs002012_years_of_education": "Годы образования",
    "pgs001232_fluid_intelligence_score": "Fluid intelligence",
    "pgs001091_loneliness": "Одиночество",
    "pgs001022_embarrassment_worry": "Переживание неловкости",
    "pgs001920_foreboding_feelings": "Предчувствие тревоги",
    "pgs001936_general_happiness": "Общая удовлетворенность",
    "pgs003565_neuroticism": "Невротизм",
    "pgs001049_risk_taking_behaviour": "Склонность к риску",
    "pgs001016_sensitivity_hurt_feelings": "Чувствительность",
    "pgs001396_unenthusiasm_disinterest": "Потеря интереса",
    "pgs001021_worry_anxiety_feelings": "Тревожность",
    "pgs000660_hdl_cholesterol": "HDL холестерин",
    "pgs000661_ldl_cholesterol": "LDL холестерин",
    "pgs000658_total_cholesterol": "Общий холестерин",
    "pgs000659_triglycerides": "Триглицериды",
    "pgs000301_systolic_blood_pressure": "Систолическое давление",
    "pgs000302_diastolic_blood_pressure": "Диастолическое давление",
    "pgs000300_heart_rate": "Пульс",
    "pgs000304_hba1c": "HbA1c",
    "pgs000305_fasting_glucose": "Глюкоза натощак",
    "pgs000877_insulin_resistance": "Инсулинорезистентность",
    "pgs000832_type2_diabetes": "Диабет 2 типа",
    "pgs003504_cannabis_use": "Употребление каннабиса",
    "pgs004243_colorectal_cancer": "Колоректальный рак",
    "pgs003497_depression_episode": "Депрессивный эпизод",
    "pgs001253_hearing_difficulty": "Трудности со слухом",
    "pgs001252_hearing_difficulty_and_deafness": "Нарушения слуха и глухоты",
    "pgs001537_left_accumbens_volume": "Объём левого прилежащего ядра",
    "pgs001542_left_caudate_volume": "Объём левого хвостатого ядра",
    "pgs001630_hippocampal_volume": "Объём левого гиппокампа",
    "pgs001631_left_pallidum_volume": "Объём левого бледного шара",
    "pgs001635_left_putamen_volume": "Объём левой скорлупы",
    "pgs001538_right_accumbens_volume": "Объём правого прилежащего ядра",
    "pgs001543_right_caudate_volume": "Объём правого хвостатого ядра",
    "pgs003664_right_hippocampal_volume": "Объём правого гиппокампа",
    "pgs001632_right_pallidum_volume": "Объём правого бледного шара",
    "pgs001594_right_putamen_grey_matter_volume": "Объём серого вещества правой скорлупы",
    "pgs001609_right_thalamus_volume": "Объём правого таламуса",
}

_RU_SHORT_PREFIX_REWRITES = (
    ("Полигенный сигнал употребления ", "Употребление "),
    ("Полигенный сигнал объёма ", "Объём "),
    ("Полигенный сигнал объема ", "Объём "),
    ("Полигенный сигнал нарушений ", "Нарушения "),
    ("Полигенный сигнал к ", ""),
    ("Полигенный сигнал ", ""),
    ("Склонность выглядеть ", "Выглядеть "),
    ("Склонность ко ", ""),
    ("Склонность к ", ""),
)

_TRAIT_BUTTON_LABEL_MAX_LENGTH = 52
_TRAIT_GROUP_EMOJIS = {
    "appearance": "👤",
    "body": "🏃",
    "nutrition": "🥗",
    "lifestyle": "☕",
    "mind": "🧠",
    "health_research": "🧬",
    "sensitive_research": "🔬",
}
_TRAIT_GROUP_LABELS = {
    "ru": {
        "appearance": "Внешность",
        "body": "Тело",
        "nutrition": "Питание",
        "lifestyle": "Образ жизни",
        "mind": "Психика",
        "health_research": "Здоровье",
        "sensitive_research": "Исследовательские",
    },
    "en": {
        "appearance": "Appearance",
        "body": "Body",
        "nutrition": "Nutrition",
        "lifestyle": "Lifestyle",
        "mind": "Mind",
        "health_research": "Health Research",
        "sensitive_research": "Research",
    },
}
_SECTION_SEPARATOR = "━━━━━━━━━━━━━━"


def footer_rows(back_callback: str, *, lang: str = "ru") -> list[list[InlineKeyboardButton]]:
    return [
        [
            InlineKeyboardButton(text("back", lang=lang), callback_data=back_callback),
            InlineKeyboardButton(text("cancel", lang=lang), callback_data="main:cancel"),
        ]
    ]


def pager_row(*, previous_callback: str | None, next_callback: str | None, lang: str = "ru") -> list[list[InlineKeyboardButton]]:
    row: list[InlineKeyboardButton] = []
    if previous_callback:
        row.append(InlineKeyboardButton(text("pager_prev", lang=lang), callback_data=previous_callback))
    if next_callback:
        row.append(InlineKeyboardButton(text("pager_next", lang=lang), callback_data=next_callback))
    return [row] if row else []


def build_markup(rows: list[list[InlineKeyboardButton]], back_callback: str, *, lang: str = "ru") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(rows + footer_rows(back_callback, lang=lang))


def traits_root_text(*, trait_count: int, consumer_ready_trait_count: int, usable_trait_count: int, lang: str = "ru") -> str:
    if lang == "ru":
        lines = [
            "✨ Traits",
            "",
            "PGS-отчёты по raw-файлу.",
            f"Готово к расчёту: {usable_trait_count}",
            "",
            text("traits_root_hint", lang=lang),
        ]
    else:
        lines = [
            "✨ Traits",
            "",
            "PGS reports from a raw file.",
            f"Ready to run: {usable_trait_count}",
            "",
            text("traits_root_hint", lang=lang),
        ]
    return "\n".join(_escaped(line) for line in lines)


def traits_about_text(*, lang: str = "ru") -> str:
    if lang == "ru":
        lines = [
            _title(text("about_limitations", lang=lang)),
            "",
            _section("Что считает раздел"),
            "Traits показывает polygenic score по autosomal raw-файлу и сравнивает результат с локальной reference panel.",
            "",
            _section("Как читать"),
            "• percentile = положение относительно reference panel",
            "• confidence зависит от покрытия SNP и качества raw",
            "• физические признаки не измеряются напрямую",
            "• sensitive/health-related признаки лучше читать как research signal",
            "",
            _section("Ограничения"),
            "Это вероятностная оценка, не диагноз и не медицинская рекомендация. Результат зависит от конкретного PGS, состава reference panel и того, сколько нужных вариантов найдено в raw.",
            "",
            "Сохраняйте только те отчеты, которые хотите видеть в My DNA.",
        ]
    else:
        lines = [
            _title(text("about_limitations", lang=lang)),
            "",
            _section("What this section computes"),
            "Traits runs polygenic scores from an autosomal raw file and compares the result with a local reference panel.",
            "",
            _section("How to read"),
            "• percentile = position relative to the reference panel",
            "• confidence depends on SNP coverage and raw quality",
            "• physical traits are not measured directly",
            "• sensitive/health-related traits should be read as research signals",
            "",
            _section("Limitations"),
            "This is a probabilistic estimate, not a diagnosis or medical advice. Results depend on the specific PGS, the reference panel, and how many required variants are present in the raw file.",
            "",
            "Save only the reports you want to keep in My DNA.",
        ]
    return "\n".join(_escaped(line) if line.startswith("•") else line for line in lines)


def saved_report_samples_text(samples: list[SampleAsset], report_counts: dict[str, int], *, lang: str = "ru") -> str:
    total_reports = sum(report_counts.values())
    lines = [
        _title(text("open_saved_reports", lang=lang)),
        "",
        _field(_copy("saved_reports", lang), total_reports, strong_value=True),
        "",
    ]
    if not samples:
        lines.append(_escaped(text("no_samples", lang=lang)))
    else:
        lines.append(_escaped(_copy("sample_hint", lang)))
    return "\n".join(lines)


def trait_sections_text(*, sample_name: str | None = None, lang: str = "ru") -> str:
    if sample_name is None:
        if lang == "ru":
            return "✨ Traits\n\nКаталог признаков."
        return "✨ Traits\n\nTrait catalog."
    lines = [_title(text("sections_title", lang=lang)), ""]
    lines.extend([_field(_copy("sample_label", lang), sample_name, strong_value=True), ""])
    lines.append(_escaped(_copy("section_hint", lang)))
    return "\n".join(lines)


def trait_button_label(entry: TraitCatalogEntry, *, lang: str = "ru") -> str:
    return short_trait_label(entry.trait_id, entry.display_name, lang=lang)


def short_trait_label(trait_id: str | None, fallback: str, *, lang: str = "ru") -> str:
    label = localize_trait_name(trait_id, fallback, lang=lang)
    if lang == "ru":
        label = _RU_SHORT_TRAIT_LABELS.get(str(trait_id or "")) or _shorten_ru_trait_label(label)
    return _trim_button_label(label)


def trait_catalog_text(
    entries: list[TraitCatalogEntry],
    *,
    page: int,
    total_pages: int,
    sample_name: str | None = None,
    group_name: str | None = None,
    lang: str = "ru",
) -> str:
    if group_name is not None and sample_name is None:
        title = group_name
    elif group_name is not None and sample_name is not None:
        title = group_name
    elif sample_name is None:
        title = text("catalog_title", lang=lang)
    else:
        title = text("catalog_title_sample", lang=lang, sample_name=sample_name)

    lines = [_title(title), ""]
    if group_name is not None and sample_name is not None:
        lines.extend([_field(_copy("sample_label", lang), sample_name, strong_value=True), ""])
    lines.append(_compact_page(page + 1, total_pages, lang=lang))
    if not entries:
        lines.extend(["", _escaped(text("no_traits_in_group", lang=lang) if group_name is not None else text("no_traits", lang=lang))])
        return "\n".join(lines)
    return "\n".join(lines)


def trait_detail_text(detail: TraitDetail, *, sample_name: str | None = None, lang: str = "ru") -> str:
    entry = detail.entry
    short_name = short_trait_label(entry.trait_id, entry.display_name, lang=lang)
    group_label = _trait_group_label(entry.group, lang=lang)
    status_label = localize_status(entry.status, lang=lang) or entry.status
    lines = [
        _title(_copy("trait_info_title", lang)),
        "",
        _title(f"{_TRAIT_GROUP_EMOJIS.get(entry.group, '✨')} {short_name}"),
        "",
        _field(_copy("group_field", lang), group_label),
        _field(text("status", lang=lang), status_label),
        "",
        _escaped(_SECTION_SEPARATOR),
        _section(_copy("what_it_shows", lang)),
        "",
        _escaped(_trait_info_description(short_name, lang=lang)),
    ]

    if entry.group == "sensitive_research":
        lines.extend(
            [
                "",
                _escaped(_SECTION_SEPARATOR),
                _section(_copy("important", lang)),
                "",
                _escaped(_copy("research_warning", lang)),
            ]
        )

    lines.extend(
        [
            "",
            _escaped(_SECTION_SEPARATOR),
            _section(_copy("reference", lang)),
            "",
            _field(_copy("reference_in_calculation", lang), _reference_panel_count(entry.reference_panel, lang=lang)),
            "",
            _escaped(_SECTION_SEPARATOR),
            _section(_copy("technical_short", lang)),
            "",
            _field(_copy("pgs_id_label", lang), entry.pgs_id),
            _field(_copy("original_trait_name", lang), entry.display_name),
        ]
    )
    return "\n".join(lines)


def sample_picker_text(trait_name: str, samples: list[SampleAsset], *, page: int, total_pages: int, lang: str = "ru") -> str:
    if lang == "ru":
        lines = [
            _title(text("choose_sample", lang=lang)),
            "",
            _field(text("trait_label", lang=lang), trait_name, strong_value=True),
            "",
            _escaped("Для расчёта нужен sample с raw-файлом."),
        ]
    else:
        lines = [
            _title(text("choose_sample", lang=lang)),
            "",
            _field(text("trait_label", lang=lang), trait_name, strong_value=True),
            "",
            _escaped("A sample with a raw file is required for calculation."),
        ]
    if not samples:
        lines.extend(["", _escaped(_copy("no_raw_samples", lang))])
    return "\n".join(lines)


def trait_run_sample_picker_text(samples: list[SampleAsset], *, page: int, total_pages: int, lang: str = "ru") -> str:
    if lang == "ru":
        lines = [
            _title(text("choose_sample", lang=lang)),
            "",
            _escaped("Для расчёта нужен sample с raw-файлом."),
        ]
        if samples:
            lines.append(_escaped("Выберите sample, затем раздел и признак."))
        else:
            lines.extend(["", _escaped(_copy("no_raw_samples", lang))])
    else:
        lines = [
            _title(text("choose_sample", lang=lang)),
            "",
            _escaped("A sample with a raw file is required."),
        ]
        if samples:
            lines.append(_escaped("Choose a sample, then a section and trait."))
        else:
            lines.extend(["", _escaped(_copy("no_raw_samples", lang))])
    if total_pages > 1:
        lines.extend(["", _compact_page(page + 1, total_pages, lang=lang)])
    return "\n".join(lines)


def running_trait_text(*, trait_id: str, sample_name: str, lang: str = "ru") -> str:
    return "\n".join(
        [
            _title(text("trait_result", lang=lang)),
            "",
            _section(_copy("in_progress", lang)),
            _field(text("trait_id", lang=lang), trait_id, code_value=True),
            _field(_copy("sample_label", lang), sample_name, strong_value=True),
            "",
            _escaped(text("running_calculation", lang=lang)),
        ]
    )


def report_saved_text(record: TraitReportRecord, *, lang: str = "ru") -> str:
    return _user_result_card(
        trait_id=record.summary.trait_id,
        display_name=record.summary.display_name,
        sample_name=record.summary.sample_name,
        percentile=record.product_payload.get("percentile"),
        confidence=record.summary.confidence,
        interpretation=str(record.technical_payload.get("interpretation") or ""),
        metrics=dict(record.product_payload.get("key_metrics") or {}),
        product_status=record.summary.product_status,
        created_at=None,
        lang=lang,
    )


def trait_visual_caption(
    *,
    sample_name: str,
    technical_payload: dict[str, object],
    product_payload: dict[str, object],
    lang: str = "ru",
) -> str:
    trait_id = str(product_payload.get("trait_id") or technical_payload.get("trait_id") or "")
    display_name = short_trait_label(trait_id, str(product_payload.get("display_name") or ""), lang=lang)
    group = str(product_payload.get("group") or technical_payload.get("group") or "")
    title = f"{_TRAIT_GROUP_EMOJIS.get(group, '✨')} {display_name}"
    percentile = _format_number(product_payload.get("percentile"), digits=1, fallback=_copy("not_available", lang))
    confidence = _caption_confidence(product_payload.get("confidence") or technical_payload.get("confidence"), lang=lang)
    sample_label = "Sample" if lang == "ru" else _copy("sample_label", lang)
    confidence_label = "Надёжность" if lang == "ru" else text("confidence", lang=lang)
    return "\n".join(
        [
            _title(title),
            "",
            f"{_escaped(sample_label)}: {_escaped(sample_name)}",
            f"{_escaped(text('percentile', lang=lang))}: {_escaped(percentile)}",
            f"{_escaped(confidence_label)}: {_escaped(confidence)}",
        ]
    )


def trait_report_visual_caption(record: TraitReportRecord, *, lang: str = "ru") -> str:
    return trait_visual_caption(
        sample_name=record.summary.sample_name,
        technical_payload=record.technical_payload,
        product_payload=record.product_payload,
        lang=lang,
    )


def trait_result_preview_text(
    *,
    sample_name: str,
    technical_payload: dict[str, object],
    product_payload: dict[str, object],
    lang: str = "ru",
) -> str:
    return (
        _user_result_card(
            trait_id=str(product_payload.get("trait_id") or technical_payload.get("trait_id") or ""),
            display_name=str(product_payload.get("display_name") or ""),
            sample_name=sample_name,
            percentile=product_payload.get("percentile"),
            confidence=str(product_payload.get("confidence") or technical_payload.get("confidence") or "unknown"),
            interpretation=str(technical_payload.get("interpretation") or ""),
            metrics=dict(product_payload.get("key_metrics") or {}),
            product_status=str(product_payload.get("product_status") or ""),
            created_at=None,
            lang=lang,
        )
        + "\n\n"
        + _escaped(text("result_not_saved", lang=lang))
    )


def sample_trait_reports_text(sample: SampleAsset, reports: list[TraitReportSummary], *, lang: str = "ru") -> str:
    lines = [
        _title(_copy("reports_title", lang)),
        "",
        _field(_copy("sample_label", lang), sample.display_name, strong_value=True),
        _field(_copy("saved_reports", lang), len(reports), strong_value=True),
        "",
    ]
    if not reports:
        lines.append(_escaped(text("no_saved_reports", lang=lang)))
    else:
        lines.append(_escaped(text("choose_saved_or_run_new", lang=lang)))
    return "\n".join(lines)


def trait_report_text(record: TraitReportRecord, *, lang: str = "ru") -> str:
    return _user_result_card(
        trait_id=record.summary.trait_id,
        display_name=record.summary.display_name,
        sample_name=record.summary.sample_name,
        percentile=record.product_payload.get("percentile"),
        confidence=record.summary.confidence,
        interpretation=str(record.technical_payload.get("interpretation") or ""),
        metrics=dict(record.product_payload.get("key_metrics") or {}),
        product_status=record.summary.product_status,
        created_at=format_created_at(record.summary.created_at),
        lang=lang,
    )


def report_button_label(summary: TraitReportSummary, *, lang: str = "ru") -> str:
    display_name = localize_trait_name(summary.trait_id, summary.display_name, lang=lang)
    outcome = _result_outcome_label(summary.percentile, interpretation="", lang=lang)
    percentile_text = _format_number(summary.percentile, digits=1, fallback=_copy("not_available", lang))
    return f"{display_name} | {outcome} | {percentile_text}"


def _user_result_card(
    *,
    trait_id: str,
    display_name: str,
    sample_name: str,
    percentile: object,
    confidence: str,
    interpretation: str,
    metrics: dict[str, object],
    product_status: str,
    created_at: str | None,
    lang: str,
) -> str:
    localized_name = localize_trait_name(trait_id, display_name, lang=lang)
    localized_interpretation = _finalize_interpretation(localize_interpretation(interpretation, lang=lang), lang=lang)
    outcome = _result_outcome_label(percentile, interpretation=localized_interpretation, lang=lang)
    confidence_text = _display_confidence(confidence, lang=lang)
    percentile_text = _format_number(percentile, digits=1, fallback=_copy("not_available", lang))

    lines = [
        _title(localized_name),
        "",
        _field(_copy("sample_label", lang), sample_name, strong_value=True),
        "",
        _section(_copy("result", lang)),
        f"<b>{_escaped(outcome)}</b>",
        _field(text("percentile", lang=lang), percentile_text, strong_value=True),
        _field(text("confidence", lang=lang), confidence_text, strong_value=True),
        "",
        _section(_copy("interpretation", lang)),
        _escaped(_user_result_blurb(outcome, lang=lang)),
        _escaped(_user_caution_blurb(lang=lang)),
        "",
        _section(_copy("technical", lang)),
        _field(
            text("matched_variants", lang=lang),
            f"{metrics.get('matched_variants', _copy('not_available', lang))} / {metrics.get('total_variants', _copy('not_available', lang))}",
        ),
        _field(_copy("overlap", lang), _format_percent(metrics.get("overlap_percent"), fallback=_copy("not_available", lang))),
    ]

    status_line = _optional_status_line(product_status, lang=lang)
    if status_line:
        lines.append(status_line)
    if created_at:
        lines.append(_field(_copy("saved_at", lang), created_at))
    return "\n".join(lines)


def error_text(title: str, message: str, *, details: str | None = None) -> str:
    lines = [_title(title), "", _escaped(message)]
    if details:
        lines.extend(["", f"<code>{_escaped(details)}</code>"])
    return "\n".join(lines)


def format_created_at(value: str) -> str:
    try:
        return datetime.fromisoformat(value).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return value


def _copy(key: str, lang: str) -> str:
    return _UI_COPY.get(lang, _UI_COPY["en"]).get(key, _UI_COPY["en"].get(key, key))


def _title(value: str) -> str:
    return f"<b>{_escaped(value)}</b>"


def _section(value: str) -> str:
    return f"<b>{_escaped(value)}</b>"


def _field(label: str, value: object, *, strong_value: bool = False, code_value: bool = False) -> str:
    label_html = f"<b>{_escaped(label)}</b>"
    rendered = _render_value(value)
    if code_value:
        rendered = f"<code>{rendered}</code>"
    elif strong_value:
        rendered = f"<b>{rendered}</b>"
    return f"{label_html}: {rendered}"


def _render_value(value: object) -> str:
    if value is None:
        return _escaped("n/a")
    return _escaped(str(value))


def _muted_page(current: int, total: int, *, lang: str) -> str:
    return f"<i>{_escaped(_copy('page', lang))} {current} / {max(total, 1)}</i>"


def _compact_page(current: int, total: int, *, lang: str) -> str:
    return f"<i>{_escaped(_copy('page', lang))} {current}/{max(total, 1)}</i>"


def _shorten_ru_trait_label(label: str) -> str:
    value = str(label or "").strip()
    for prefix, replacement in _RU_SHORT_PREFIX_REWRITES:
        if value.startswith(prefix):
            return _capitalize_first(replacement + value[len(prefix) :])
    return _capitalize_first(value)


def _capitalize_first(value: str) -> str:
    clean = str(value or "").strip()
    if not clean:
        return ""
    return clean[:1].upper() + clean[1:]


def _trim_button_label(label: str, max_length: int = _TRAIT_BUTTON_LABEL_MAX_LENGTH) -> str:
    clean = " ".join(str(label or "").split())
    if len(clean) <= max_length:
        return clean
    trimmed = clean[: max_length - 1].rstrip()
    last_space = trimmed.rfind(" ")
    if last_space >= max_length // 2:
        trimmed = trimmed[:last_space].rstrip()
    return f"{trimmed}…"


def _caption_confidence(value: object, *, lang: str) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if lang == "ru":
        labels = {
            "very_low": "☆☆☆",
            "очень_низкая": "☆☆☆",
            "низкая": "★☆☆",
            "low": "★☆☆",
            "средняя": "★★☆",
            "medium": "★★☆",
            "высокая": "★★★",
            "high": "★★★",
        }
        return labels.get(normalized, "—")

    labels = {
        "very_low": "☆☆☆",
        "low": "★☆☆",
        "medium": "★★☆",
        "high": "★★★",
    }
    return labels.get(normalized, "—")


def _trait_group_label(group: str, *, lang: str) -> str:
    return _TRAIT_GROUP_LABELS.get(lang, _TRAIT_GROUP_LABELS["en"]).get(group) or localize_group(group, lang=lang) or group


def _trait_info_description(short_name: str, *, lang: str) -> str:
    if lang == "ru":
        return f"Генетическая оценка по признаку «{short_name}» относительно локальной референсной панели."
    return f"A genetic estimate for the trait “{short_name}” relative to the local reference panel."


def _reference_panel_count(reference_panel: dict[str, object] | None, *, lang: str) -> str:
    if not reference_panel:
        return "нет данных" if lang == "ru" else "no data"
    included = reference_panel.get("sample_count_included")
    total = reference_panel.get("sample_count_total")
    if included is None or total is None:
        return "нет данных" if lang == "ru" else "no data"
    return f"{included} / {total}"


def _metric_line(label: str, value: object) -> str:
    return f"{_escaped(label)}: <b>{_render_value(value)}</b>"


def _escaped(value: object) -> str:
    return escape(str(value), quote=False)


def _format_number(value: object, *, digits: int, fallback: str) -> str:
    if value is None:
        return fallback
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


def _format_percent(value: object, *, fallback: str) -> str:
    formatted = _format_number(value, digits=1, fallback=fallback)
    if formatted == fallback:
        return fallback
    return f"{formatted}%"


def _result_outcome_label(percentile: object, *, interpretation: str, lang: str) -> str:
    try:
        value = float(percentile)
    except (TypeError, ValueError):
        normalized = interpretation.lower()
        if "ниже среднего" in normalized or "below the reference mean" in normalized:
            return _copy("outcome_low", lang)
        if "в пределах" in normalized or "within the reference range" in normalized:
            return _copy("outcome_mid", lang)
        if "выше среднего" in normalized or "above the reference mean" in normalized:
            return _copy("outcome_high", lang)
        return _copy("outcome_unknown", lang)

    if value < 35.0:
        return _copy("outcome_low", lang)
    if value <= 65.0:
        return _copy("outcome_mid", lang)
    return _copy("outcome_high", lang)


def _user_result_blurb(outcome: str, *, lang: str) -> str:
    if lang == "ru":
        lowered = outcome[:1].lower() + outcome[1:] if outcome else outcome
        return f"Ваш генетический результат по этому признаку {lowered} относительно референсной панели."
    return f"Your genetic result for this trait is {outcome.lower()} relative to the reference panel."


def _user_caution_blurb(*, lang: str) -> str:
    if lang == "ru":
        return "Это вероятностная генетическая оценка, а не диагноз и не прямое физическое измерение."
    return "This is a probabilistic genetic estimate, not a diagnosis or a direct physical measurement."


def _display_confidence(value: str, *, lang: str) -> str:
    localized = localize_confidence(value, lang=lang)
    if not localized:
        return localized
    return localized[:1].upper() + localized[1:]


def _optional_status_line(product_status: str, *, lang: str) -> str | None:
    normalized = (product_status or "").strip().lower()
    if not normalized:
        return None
    if normalized in {"consumer_trait", "product_ready", "working_real_trait", "cautious", "limited"}:
        return None
    return _field(_copy("status_mode", lang), localize_product_status(product_status, lang=lang) or normalized)


def _finalize_interpretation(value: str, *, lang: str) -> str:
    if lang != "ru":
        return value
    return value.replace("reference panel", "референсной панели")


def _localized_measure_text(detail: TraitDetail, *, lang: str) -> str:
    base = _clean_markdown(detail.entry.what_it_measures or "")
    if lang != "ru" or not base:
        return base
    trait_name = localize_trait_name(detail.entry.trait_id, detail.entry.display_name, lang=lang)
    lowered = base.lower()
    if "internal pipeline exercise" in lowered:
        return (
            f"Слабый панель-относительный полигенный сигнал, связанный с признаком «{trait_name}». "
            "Сейчас используется как внутренний пример для проверки расчетного контура."
        )
    if "research inspection only" in lowered:
        return (
            f"Панель-относительный полигенный сигнал, связанный с признаком «{trait_name}». "
            "Текущая версия предназначена для исследовательского просмотра на локальной референсной панели."
        )
    if "meaning lean mass in the arms and legs" in lowered:
        return (
            f"Панель-относительный полигенный сигнал, связанный с признаком «{trait_name}», "
            "то есть с безжировой массой рук и ног, откалиброванный на текущей локальной эмпирической референсной панели."
        )
    if "whole body fat free mass" in lowered:
        return (
            f"Панель-относительный полигенный сигнал, связанный с признаком «{trait_name}», "
            "на основе polygenic score для общей безжировой массы тела, откалиброванный на текущей локальной эмпирической референсной панели."
        )
    return (
        f"Панель-относительный полигенный сигнал, связанный с признаком «{trait_name}», "
        "откалиброванный на текущей локальной эмпирической референсной панели."
    )


def _localized_description_text(detail: TraitDetail, *, lang: str) -> str:
    base = _clean_markdown(detail.entry.short_description or "")
    if lang != "ru" or not base:
        return base
    trait_name = localize_trait_name(detail.entry.trait_id, detail.entry.display_name, lang=lang)
    group_name = localize_group(detail.entry.group, lang=lang) or detail.entry.group
    lowered = base.lower()
    if "not intended for consumer interpretation" in lowered:
        return (
            "Внутренний smoke-test раздела Traits, сохраненный для проверки строгого сценария без импутации. "
            "Не предназначен для пользовательской интерпретации."
        )
    if "not consumer-ready" in lowered:
        return (
            f"Экспериментальный признак для исследовательского просмотра поведения polygenic score по признаку «{trait_name}» "
            "в строгом raw-array сценарии без импутации. Не предназначен для пользовательской выдачи."
        )
    return (
        f"Пользовательский признак из раздела «{group_name}», который показывает осторожный "
        f"панель-относительный сигнал по признаку «{trait_name}» в пределах текущей локальной референсной панели."
    )


def _localized_notes_preview(detail: TraitDetail) -> str:
    entry = detail.entry
    lines = [entry.pgs_id, f"ID в PGS Catalog: {entry.pgs_id}"]
    reported_trait = ""
    pgs_name = ""
    mapped_trait = ""

    for raw_line in (detail.notes_markdown or "").splitlines():
        cleaned = _clean_markdown(raw_line)
        lowered = cleaned.lower()
        if lowered.startswith("reported trait:"):
            reported_trait = cleaned.split(":", 1)[1].strip()
        elif lowered.startswith("pgs name:"):
            pgs_name = cleaned.split(":", 1)[1].strip()
        elif lowered.startswith("mapped trait:"):
            mapped_trait = cleaned.split(":", 1)[1].strip()

    if reported_trait:
        lines.append(f"Исходное название признака: {reported_trait}")
    elif pgs_name:
        lines.append(f"Имя score в источнике: {pgs_name}")
    elif mapped_trait:
        lines.append(f"Mapped trait в источнике данных: {mapped_trait}")

    lines.append(f"Название в боте: {localize_trait_name(entry.trait_id, entry.display_name, lang='ru')}")
    return "\n".join(lines[:4])


def _notes_preview(detail: TraitDetail, *, lang: str) -> str:
    if lang == "ru":
        return _localized_notes_preview(detail)
    notes_markdown = detail.notes_markdown or ""
    lines: list[str] = []
    for raw_line in notes_markdown.splitlines():
        cleaned = _clean_markdown(raw_line)
        if cleaned:
            lines.append(cleaned)
        if len(lines) >= 4:
            break
    return "\n".join(lines)


def _clean_markdown(value: str) -> str:
    text_value = (value or "").strip()
    if not text_value:
        return ""
    text_value = re.sub(r"^#{1,6}\s*", "", text_value)
    text_value = re.sub(r"^[-*+]\s+", "", text_value)
    text_value = re.sub(r"`([^`]*)`", r"\1", text_value)
    text_value = re.sub(r"\*\*([^*]+)\*\*", r"\1", text_value)
    text_value = re.sub(r"__([^_]+)__", r"\1", text_value)
    text_value = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text_value)
    return text_value.strip()


def _reference_included_label(lang: str) -> str:
    if lang == "ru":
        return "В референсной панели"
    return text("reference_included", lang=lang)


def _reference_total_label(lang: str) -> str:
    if lang == "ru":
        return "Всего в референсной панели"
    return text("reference_total", lang=lang)
