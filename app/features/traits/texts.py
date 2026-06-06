from __future__ import annotations


SUPPORTED_LANGUAGES = {"ru", "en"}
DEFAULT_LANGUAGE = "ru"


_TEXTS = {
    "ru": {
        "back": "Назад",
        "cancel": "Отмена",
        "pager_prev": "Назад",
        "pager_next": "Далее",
        "traits_title": "Traits",
        "trait_label": "Признак",
        "open_catalog": "Открыть весь каталог",
        "open_sections": "Открыть разделы",
        "open_saved_reports": "Сохраненные отчеты",
        "about_limitations": "ℹ️ О разделе",
        "start_trait_report": "🧬 Новый отчёт",
        "sections_title": "Разделы",
        "sections_hint": "Сначала выберите раздел, затем конкретный признак.",
        "sections_hint_sample": "Сначала выберите раздел для этого образца, затем конкретный признак.",
        "catalog_title": "Каталог признаков",
        "catalog_title_sample": "Каталог признаков для образца: {sample_name}",
        "group_catalog_title": "Раздел: {group_name}",
        "group_catalog_title_sample": "Раздел: {group_name}\nОбразец: {sample_name}",
        "page": "Страница {current} из {total}",
        "no_traits": "Сейчас нет доступных признаков.",
        "no_traits_in_group": "В этом разделе пока нет доступных признаков.",
        "choose_trait": "Выберите признак:",
        "choose_section": "Выберите раздел:",
        "available_traits": "Доступно признаков: {count}",
        "consumer_ready_traits": "Готово для выдачи: {count}",
        "usable_traits": "Готово к расчету: {count}",
        "traits_root_hint": "Выберите sample с raw-файлом, затем раздел и признак.",
        "trait_id": "ID признака",
        "pgs_id": "ID PGS",
        "group": "Группа",
        "status": "Статус",
        "description_source_note": "Описание ниже пока берется из metadata traits.",
        "what_it_measures": "Что измеряет",
        "reference_included": "В референсной панели",
        "reference_total": "Всего в референсной панели",
        "sample": "Образец",
        "run_trait": "Расчет признака: {trait_name}",
        "no_samples": "Пока нет сохраненных образцов. Сначала создайте образец в My DNA.",
        "choose_sample": "🧬 Выберите sample",
        "open_my_data": "Открыть My DNA",
        "trait_result": "Результат расчета",
        "saved_sample_not_found": "Сохраненный образец не найден.",
        "source_raw_not_found": "У этого образца не найден исходный raw-файл.",
        "source_raw_missing_on_disk": "Исходный raw-файл отсутствует на диске.",
        "running_calculation": "Запускаю расчет...",
        "could_not_run_trait": "Не удалось выполнить расчет признака.",
        "open_saved_report": "Открыть сохраненный отчет",
        "save_trait_report": "💾 Сохранить отчёт",
        "result_not_saved": "Результат еще не сохранен. Если он нужен в My DNA, нажмите «💾 Сохранить отчёт».",
        "result_saved": "Отчет сохранен.",
        "sample_trait_reports": "📊 Traits-отчёты",
        "trait_reports_title": "Отчеты traits",
        "saved_reports": "Сохранено отчетов: {count}",
        "no_saved_reports": "Для этого образца пока нет сохраненных отчетов traits.",
        "choose_saved_or_run_new": "Выберите сохраненный отчет или запустите новый расчет.",
        "run_new_trait_report": "Запустить новый расчет",
        "saved_report_not_found": "Сохраненный отчет не найден.",
        "run_trait_again": "Запустить расчет заново",
        "saved_at": "Сохранено",
        "confidence": "Надежность оценки",
        "percentile": "Процентиль",
        "matched_variants": "Совпавшие варианты",
        "overlap": "Покрытие",
        "product_status": "Статус результата",
        "could_not_open_screen": "Не удалось открыть этот экран.",
        "choose_sample_and_run": "Выбрать образец и запустить",
        "run_for_this_sample": "Запустить для этого образца",
        "trait_info": "ℹ️ О признаке",
        "traits_in_group": "{group_name}: {count}",
    },
    "en": {
        "back": "Back",
        "cancel": "Cancel",
        "pager_prev": "Prev",
        "pager_next": "Next",
        "traits_title": "Traits",
        "trait_label": "Trait",
        "open_catalog": "Open all traits",
        "open_sections": "Open sections",
        "open_saved_reports": "Saved reports",
        "about_limitations": "ℹ️ About",
        "start_trait_report": "🧬 New report",
        "sections_title": "Trait sections",
        "sections_hint": "Choose a section first, then a specific trait.",
        "sections_hint_sample": "Choose a trait section for this sample first, then a specific trait.",
        "catalog_title": "Trait catalog",
        "catalog_title_sample": "Trait catalog for sample: {sample_name}",
        "group_catalog_title": "Section: {group_name}",
        "group_catalog_title_sample": "Section: {group_name}\nSample: {sample_name}",
        "page": "Page {current} of {total}",
        "no_traits": "No traits are available.",
        "no_traits_in_group": "No traits are available in this section.",
        "choose_trait": "Choose a trait:",
        "choose_section": "Choose a section:",
        "available_traits": "Available traits: {count}",
        "consumer_ready_traits": "Consumer-ready: {count}",
        "usable_traits": "Usable: {count}",
        "traits_root_hint": "Choose a sample with a raw file, then a section and trait.",
        "trait_id": "Trait ID",
        "pgs_id": "PGS ID",
        "group": "Group",
        "status": "Status",
        "description_source_note": "Description below currently comes from trait metadata.",
        "what_it_measures": "What it measures",
        "reference_included": "Reference panel included",
        "reference_total": "Reference panel total",
        "sample": "Sample",
        "run_trait": "Run trait: {trait_name}",
        "no_samples": "No saved samples yet. Create a sample in My DNA first.",
        "choose_sample": "🧬 Choose sample",
        "open_my_data": "Open My DNA",
        "trait_result": "Trait result",
        "saved_sample_not_found": "Saved sample not found.",
        "source_raw_not_found": "Source raw file not found for this sample.",
        "source_raw_missing_on_disk": "Source raw file is missing on disk.",
        "running_calculation": "Running calculation...",
        "could_not_run_trait": "Could not run trait.",
        "open_saved_report": "Open saved report",
        "save_trait_report": "💾 Save report",
        "result_not_saved": "This result is not saved yet. Use Save report if you want to keep it in My DNA.",
        "result_saved": "Report saved.",
        "sample_trait_reports": "📊 Trait reports",
        "trait_reports_title": "Trait reports",
        "saved_reports": "Saved reports: {count}",
        "no_saved_reports": "No saved trait reports for this sample yet.",
        "choose_saved_or_run_new": "Choose a saved report or run a new trait.",
        "run_new_trait_report": "Run new trait report",
        "saved_report_not_found": "Saved report not found.",
        "run_trait_again": "Run trait again",
        "saved_at": "Saved",
        "confidence": "Confidence",
        "percentile": "Percentile",
        "matched_variants": "Matched variants",
        "overlap": "Overlap",
        "product_status": "Product status",
        "could_not_open_screen": "Could not open this screen.",
        "choose_sample_and_run": "Choose sample and run",
        "run_for_this_sample": "Run for this sample",
        "trait_info": "ℹ️ About this trait",
        "traits_in_group": "{group_name}: {count}",
    },
}


_CONFIDENCE_LABELS = {
    "ru": {
        "high": "высокая",
        "medium": "средняя",
        "low": "низкая",
        "unknown": "неизвестно",
    },
    "en": {
        "high": "high",
        "medium": "medium",
        "low": "low",
        "unknown": "unknown",
    },
}


_STATUS_LABELS = {
    "ru": {
        "usable": "готов",
        "experimental": "экспериментальный",
        "smoke-test": "smoke-test",
        "deprecated": "устаревший",
    },
    "en": {
        "usable": "ready",
        "experimental": "experimental",
        "smoke-test": "smoke-test",
        "deprecated": "deprecated",
    },
}


_GROUP_LABELS = {
    "ru": {
        "appearance": "Внешность",
        "body": "Тело",
        "nutrition": "Питание",
        "lifestyle": "Образ жизни",
        "mind": "Психика и поведение",
        "health_research": "Здоровье",
        "sensitive_research": "🔬 Исследовательские",
        "internal": "Внутренние",
    },
    "en": {
        "appearance": "Appearance",
        "body": "Body",
        "nutrition": "Nutrition",
        "lifestyle": "Lifestyle",
        "mind": "Mind and behavior",
        "health_research": "Health Research",
        "sensitive_research": "Sensitive research",
        "internal": "Internal",
    },
}


_PRODUCT_STATUS_LABELS = {
    "ru": {
        "product_ready": "готов к показу",
        "consumer_trait": "пользовательский признак",
        "cautious": "осторожная интерпретация",
        "limited": "ограниченный",
        "experimental": "экспериментальный",
        "smoke-test": "smoke-test",
        "deprecated": "устаревший",
        "working_real_trait": "рабочий признак",
    },
    "en": {
        "product_ready": "ready to show",
        "consumer_trait": "consumer trait",
        "cautious": "cautious interpretation",
        "limited": "limited",
        "experimental": "experimental",
        "smoke-test": "smoke-test",
        "deprecated": "deprecated",
        "working_real_trait": "working trait",
    },
}


_INTERPRETATION_LABELS = {
    "ru": {
        "Well below the reference mean.": "Значительно ниже среднего по референсной панели.",
        "Below the reference mean.": "Ниже среднего по референсной панели.",
        "Within the reference range.": "В пределах референсной панели.",
        "Above the reference mean.": "Выше среднего по референсной панели.",
        "Well above the reference mean.": "Значительно выше среднего по референсной панели.",
        "Inspection only; reference normalization was skipped.": "Только технический просмотр: нормализация по референсной панели не выполнялась.",
        "Reference distribution is invalid; z-score and percentile were not computed.": "Референсное распределение некорректно, поэтому z-score и процентиль не рассчитаны.",
    },
    "en": {},
}


_TRAIT_NAME_LABELS = {
    "ru": {
        "pgs003835_height": "Рост",
        "pgs000841_bmi": "Склонность к ИМТ",
        "pgs001123_coffee": "Потребление кофе",
        "pgs000336_chronotype": "Склонность к хронотипу",
        "pgs001150_sleep_duration": "Склонность к длительности сна",
        "pgs001075_walking_pace": "Склонность к обычному темпу ходьбы",
        "pgs000984_computer_games_frequency": "Склонность к частоте компьютерных игр",
        "pgs001000_daytime_nap": "Склонность к дневному сну",
        "pgs001019_gym_sports_club_attendance": "Склонность к посещению спортзала или спортклуба",
        "pgs001073_duration_of_walks": "Склонность к длительности прогулок",
        "pgs001074_other_exercise_types": "Склонность к другим видам упражнений",
        "pgs001119_left_hand_grip_strength": "Склонность к силе хвата левой руки",
        "pgs001120_right_hand_grip_strength": "Склонность к силе хвата правой руки",
        "pgs001397_walking_for_pleasure_frequency": "Склонность к прогулкам ради удовольствия",
        "pgs001927_mean_hand_grip_strength": "Склонность к средней силе хвата",
        "pgs001932_sleeplessness_insomnia": "Склонность к бессоннице",
        "pgs001923_screen_time_tv_computer": "Склонность к времени за ТВ или компьютером",
        "pgs001080_tiredness_lethargy": "Склонность к усталости и вялости",
        "pgs002254_self_reported_physical_activity": "Склонность к самооцененной физической активности",
        "pgs002255_measured_physical_activity": "Склонность к измеренной физической активности",
        "pgs001232_fluid_intelligence_score": "Полигенный сигнал fluid intelligence",
        "pgs001022_embarrassment_worry": "Склонность долго переживать неловкие ситуации",
        "pgs001920_foreboding_feelings": "Склонность к ощущениям тревожного предчувствия",
        "pgs001936_general_happiness": "Полигенный сигнал общей удовлетворенности",
        "pgs001049_risk_taking_behaviour": "Склонность к рискованному поведению",
        "pgs001016_sensitivity_hurt_feelings": "Склонность к эмоциональной чувствительности",
        "pgs001396_unenthusiasm_disinterest": "Склонность к снижению интереса и энтузиазма",
        "pgs001021_worry_anxiety_feelings": "Склонность к ощущениям тревоги и беспокойства",
        "pgs000660_hdl_cholesterol": "Исследовательский сигнал HDL холестерина",
        "pgs000661_ldl_cholesterol": "Исследовательский сигнал LDL холестерина",
        "pgs000658_total_cholesterol": "Исследовательский сигнал общего холестерина",
        "pgs000659_triglycerides": "Исследовательский сигнал триглицеридов",
        "pgs000301_systolic_blood_pressure": "Исследовательский сигнал систолического давления",
        "pgs000302_diastolic_blood_pressure": "Исследовательский сигнал диастолического давления",
        "pgs000300_heart_rate": "Исследовательский сигнал частоты пульса",
        "pgs000304_hba1c": "Исследовательский сигнал HbA1c",
        "pgs000305_fasting_glucose": "Исследовательский сигнал глюкозы натощак",
        "pgs000877_insulin_resistance": "Исследовательский сигнал инсулинорезистентности",
        "pgs000832_type2_diabetes": "Исследовательский сигнал сахарного диабета 2 типа",
        "pgs003565_neuroticism": "Склонность к нейротизму",
        "pgs001091_loneliness": "Склонность к одиночеству",
        "pgs001373_age_started_wearing_glasses": "Полигенный сигнал возраста начала ношения очков",
        "pgs001924_glasses_contact_lenses": "Склонность носить очки или контактные линзы",
        "pgs001099_left_eye_spherical_power": "Полигенный сигнал сферической силы левого глаза",
        "pgs001100_right_eye_spherical_power": "Полигенный сигнал сферической силы правого глаза",
        "pgs000842_waist_hip_ratio": "Склонность к соотношению талии и бедер",
        "pgs000843_whr_adjusted_bmi": "Склонность к соотношению талии и бедер с поправкой на ИМТ",
        "pgs001227_waist_circumference": "Склонность к окружности талии",
        "pgs001162_hip_circumference": "Склонность к окружности бедер",
        "pgs001230_body_weight": "Склонность к массе тела",
        "pgs001987_male_pattern_baldness": "Склонность к андрогенетическому облысению",
        "pgs001897_skin_pigmentation": "Склонность к пигментации кожи",
        "pgs001169_lean_body_mass": "Склонность к безжировой массе тела",
        "pgs005315_appendicular_lean_mass": "Склонность к безжировой массе конечностей",
        "pgs005316_body_fat_mass": "Склонность к жировой массе тела",
        "pgs002812_gluteofemoral_adipose_tissue_volume": "Склонность к глютеофеморальному жиру",
        "pgs002813_visceral_adipose_tissue_volume": "Склонность к висцеральному жиру",
        "pgs001101_body_fat_percentage": "Склонность к проценту жира в теле",
        "pgs002011_water_intake": "Склонность к потреблению воды",
        "pgs000991_never_eat_sugar": "Склонность к избеганию сахара",
        "pgs000993_oily_fish_intake": "Склонность к потреблению жирной рыбы",
        "pgs000994_tea_consumption": "Склонность к потреблению чая",
        "pgs001064_skimmed_milk_consumption": "Склонность к потреблению обезжиренного молока",
        "pgs001058_biscuit_cereal_consumption": "Склонность к потреблению злаковых хлопьев/бисквита",
        "pgs001059_other_cereal_consumption": "Склонность к потреблению других злаков",
        "pgs001061_cooked_vegetable_consumption": "Склонность к потреблению вареных овощей",
        "pgs001067_processed_meat_intake": "Склонность к потреблению обработанного мяса",
        "pgs000978_bread_intake": "Склонность к потреблению хлеба",
        "pgs001389_dried_fruit_intake": "Склонность к потреблению сухофруктов",
        "pgs001125_instant_coffee_consumption": "Склонность к потреблению растворимого кофе",
        "pgs001126_coffee_intake": "Склонность к большему потреблению кофе",
        "pgs001034_salt_added_to_food": "Склонность добавлять соль в еду",
        "pgs001044_glucosamine_intake": "Склонность к приёму глюкозамина",
        "pgs001056_beef_intake": "Склонность к потреблению говядины",
        "pgs001057_cereal_consumption": "Склонность к потреблению злаков",
        "pgs001060_cheese_intake": "Склонность к потреблению сыра",
        "pgs001062_fresh_fruit_intake": "Склонность к потреблению свежих фруктов",
        "pgs001066_poultry_intake": "Склонность к потреблению птицы",
        "pgs001068_variation_in_diet": "Склонность к разнообразию диеты",
        "pgs001069_water_intake": "Склонность к большему потреблению воды",
        "pgs001124_ground_coffee_consumption": "Склонность к потреблению молотого кофе",
        "pgs001518_portion_size": "Склонность к большему размеру порции",
        "pgs001018_social_leisure_activities": "Склонность к социальной/досуговой активности",
        "pgs001020_adult_education_class_attendance": "Склонность посещать образовательные занятия",
        "pgs001398_friendship_satisfaction": "Склонность к удовлетворенности дружбой",
        "pgs000969_sitting_height": "Склонность к росту сидя",
        "pgs000998_childhood_height": "Склонность к росту в детстве",
        "pgs001002_whole_body_water_mass": "Склонность к водной массе тела",
        "pgs001006_weight_change_one_year": "Склонность к изменению веса за год",
        "pgs001102_left_arm_body_fat_percentage": "Склонность к проценту жира левой руки",
        "pgs001103_left_leg_body_fat_percentage": "Склонность к проценту жира левой ноги",
        "pgs001104_right_leg_body_fat_percentage": "Склонность к проценту жира правой ноги",
        "pgs001105_trunk_body_fat_percentage": "Склонность к проценту жира туловища",
        "pgs001106_right_arm_body_fat_percentage": "Склонность к проценту жира правой руки",
        "pgs001144_left_arm_fat_mass": "Склонность к жировой массе левой руки",
        "pgs001145_right_arm_fat_mass": "Склонность к жировой массе правой руки",
        "pgs001146_right_arm_fat_free_mass": "Склонность к безжировой массе правой руки",
        "pgs001147_right_leg_fat_mass": "Склонность к жировой массе правой ноги",
        "pgs001148_trunk_fat_mass": "Склонность к жировой массе туловища",
        "pgs001149_whole_body_fat_mass": "Склонность к жировой массе тела",
        "pgs001154_left_arm_impedance": "Склонность к импедансу левой руки",
        "pgs001155_left_leg_impedance": "Склонность к импедансу левой ноги",
        "pgs001156_right_arm_impedance": "Склонность к импедансу правой руки",
        "pgs001157_right_leg_impedance": "Склонность к импедансу правой ноги",
        "pgs001158_left_leg_mass": "Склонность к массе левой ноги",
        "pgs001159_right_leg_mass": "Склонность к массе правой ноги",
        "pgs001160_trunk_mass": "Склонность к массе туловища",
        "pgs001161_whole_body_impedance": "Склонность к импедансу всего тела",
        "pgs001165_left_arm_fat_free_mass": "Склонность к безжировой массе левой руки",
        "pgs001166_left_leg_fat_free_mass": "Склонность к безжировой массе левой ноги",
        "pgs001167_right_leg_fat_free_mass": "Склонность к безжировой массе правой ноги",
        "pgs001168_trunk_fat_free_mass": "Склонность к безжировой массе туловища",
        "pgs001226_birth_weight": "Склонность к весу при рождении",
        "pgs001379_body_surface_area": "Склонность к площади поверхности тела",
        "pgs001234_left_arm_mass": "Склонность к массе левой руки",
        "pgs001235_right_arm_mass": "Склонность к массе правой руки",
        "pgs001245_moderate_skin_tanning": "Склонность к умеренному загару",
        "pgs001246_very_tanned_skin": "Склонность сильно загорать",
        "pgs001247_never_tan_only_burn": "Склонность обгорать без загара",
        "pgs002012_years_of_education": "Склонность к большему числу лет образования",
        "pgs001141_facial_aging_younger": "Склонность выглядеть моложе по лицу",
        "pgs001071_facial_aging_about_age": "Склонность выглядеть на свой возраст по лицу",
        "pgs001072_facial_aging_older": "Склонность выглядеть старше по лицу",
        "pgs003504_cannabis_use": "Полигенный сигнал употребления каннабиса",
        "pgs003497_depression_episode": "Полигенный сигнал депрессивного эпизода",
        "pgs000763_hearing": "Использование слухового аппарата",
        "pgs004243_colorectal_cancer": "Полигенный сигнал колоректального рака",
        "pgs001253_hearing_difficulty": "Полигенный сигнал трудностей со слухом",
        "pgs001252_hearing_difficulty_and_deafness": "Полигенный сигнал нарушений слуха и глухоты",
        "pgs001630_hippocampal_volume": "Полигенный сигнал объема левого гиппокампа",
        "pgs003664_right_hippocampal_volume": "Полигенный сигнал объема правого гиппокампа",
        "pgs001609_right_thalamus_volume": "Полигенный сигнал объема правого таламуса",
        "pgs001635_left_putamen_volume": "Полигенный сигнал объема левой скорлупы",
        "pgs001594_right_putamen_grey_matter_volume": "Полигенный сигнал объема серого вещества правой скорлупы",
        "pgs001631_left_pallidum_volume": "Полигенный сигнал объема левого бледного шара",
        "pgs001632_right_pallidum_volume": "Полигенный сигнал объема правого бледного шара",
        "pgs001537_left_accumbens_volume": "Полигенный сигнал объема левого прилежащего ядра",
        "pgs001538_right_accumbens_volume": "Полигенный сигнал объема правого прилежащего ядра",
        "pgs001542_left_caudate_volume": "Полигенный сигнал объема левого хвостатого ядра",
        "pgs001543_right_caudate_volume": "Полигенный сигнал объема правого хвостатого ядра",
        "pgs001244_tanning": "Склонность к загару кожи",
        "pgs001092_hair_black": "Склонность к черным волосам",
        "pgs001093_hair_blonde": "Склонность к светлым волосам",
        "pgs001094_hair_brown": "Склонность к каштановым волосам",
        "pgs001095_hair_dark_brown": "Склонность к темно-каштановым волосам",
        "pgs001098_hair_red": "Склонность к рыжим волосам",
        "pgs001097_hair_other": "Склонность к другому цвету волос",
        "pgs001096_hair_light_brown": "Склонность к светло-каштановым волосам",
    },
    "en": {},
}


def resolve_language(lang: str | None) -> str:
    if lang in SUPPORTED_LANGUAGES:
        return str(lang)
    return DEFAULT_LANGUAGE


def text(key: str, *, lang: str | None = None, **kwargs) -> str:
    language = resolve_language(lang)
    template = _TEXTS.get(language, {}).get(key) or _TEXTS["en"].get(key) or key
    return template.format(**kwargs)


def localize_confidence(value: str, *, lang: str | None = None) -> str:
    language = resolve_language(lang)
    normalized = (value or "unknown").strip().lower()
    return _CONFIDENCE_LABELS.get(language, {}).get(normalized, normalized)


def localize_status(value: str, *, lang: str | None = None) -> str:
    language = resolve_language(lang)
    normalized = (value or "").strip().lower()
    if not normalized:
        return ""
    return _STATUS_LABELS.get(language, {}).get(normalized, normalized)


def localize_group(value: str, *, lang: str | None = None) -> str:
    language = resolve_language(lang)
    normalized = (value or "").strip().lower()
    if not normalized:
        return ""
    return _GROUP_LABELS.get(language, {}).get(normalized, normalized)


def localize_product_status(value: str, *, lang: str | None = None) -> str:
    language = resolve_language(lang)
    normalized = (value or "").strip().lower()
    if not normalized:
        return ""
    return _PRODUCT_STATUS_LABELS.get(language, {}).get(normalized, normalized)


def localize_interpretation(value: str, *, lang: str | None = None) -> str:
    language = resolve_language(lang)
    clean_value = (value or "").strip()
    if not clean_value:
        return ""
    return _INTERPRETATION_LABELS.get(language, {}).get(clean_value, clean_value)


def localize_trait_name(trait_id: str | None, fallback: str, *, lang: str | None = None) -> str:
    language = resolve_language(lang)
    normalized_trait_id = str(trait_id or "").strip()
    if normalized_trait_id:
        translated = _TRAIT_NAME_LABELS.get(language, {}).get(normalized_trait_id)
        if translated:
            return translated
    return fallback
