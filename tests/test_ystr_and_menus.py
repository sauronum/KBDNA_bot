from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import bot
from app.features.settings import menu as settings_menu
from features import ystr as ystr_feature
from ui import analytics as analytics_ui
from ui import ystr as ystr_ui


def _reply_text_rows(markup) -> list[list[str]]:
    return [[button.text for button in row] for row in markup.keyboard]


def _inline_text_rows(markup) -> list[list[str]]:
    return [[button.text for button in row] for row in markup.inline_keyboard]


def _inline_callback_rows(markup) -> list[list[str]]:
    return [[button.callback_data for button in row] for row in markup.inline_keyboard]


def _inline_url_rows(markup) -> list[list[str | None]]:
    return [[button.url for button in row] for row in markup.inline_keyboard]


class YstrParserTests(unittest.TestCase):
    def test_parses_vertical_marker_text_and_adjusts_dys389ii(self) -> None:
        text = "\n".join(
            [
                "DYS393 13",
                "DYS390 24",
                "DYS19 15",
                "DYS385 11-14",
                "DYS426 12",
                "DYS388 12",
                "DYS439 11",
                "DYS389I 13",
                "DYS389II 29",
            ]
        )

        markers = ystr_feature.parse_ystr_markers_from_text(text)

        self.assertEqual(markers["DYS393"], [13])
        self.assertEqual(markers["DYS385"], [11, 14])
        self.assertEqual(markers["DYS389i"], [13])
        self.assertEqual(markers["DYS389ii"], [16])

    def test_parses_horizontal_ftdna_csv_export(self) -> None:
        text = (
            "DYS393,DYS390,DYS19,DYS391,DYS385,DYS426,DYS388,DYS439,"
            "DYS389I,DYS392,DYS389II,DYS458,DYS459,DYS455,DYS454,DYS447,"
            "DYS437,DYS448,DYS449,DYS464,DYS460,Y-GATA-H4,YCAII,DYS456,"
            "DYS607,DYS576,DYS570,CDY,DYS442,DYS438\n"
            '" 14"," 22"," 15"," 10"," 14-16"," 11"," 12"," 12",'
            '" 12"," 10"," 29"," 17"," 9-9-9"," 11"," 11"," 24",'
            '" 16"," 21"," 28"," 13-13-13-13-14-14"," 10"," 9",'
            '" 20-21"," 14"," 14"," 18"," 21"," 36-38-39"," 12"," 9"\n'
        )

        markers = ystr_feature.parse_ystr_markers_from_text(text)

        self.assertEqual(len(markers), 30)
        self.assertEqual(markers["DYS393"], [14])
        self.assertEqual(markers["DYS385"], [14, 16])
        self.assertEqual(markers["DYS389i"], [12])
        self.assertEqual(markers["DYS389ii"], [17])
        self.assertEqual(markers["CDY"], [36, 38, 39])

    def test_distance_panel_and_closeness_helpers(self) -> None:
        self.assertEqual(ystr_feature.ystr_marker_distance([14, 16], [14, 17]), 1)
        self.assertEqual(ystr_feature.ystr_panel_label(30), "37")
        self.assertEqual(ystr_feature.ystr_closeness_label(1, 30), "очень близко")

    def test_make_uploaded_entry_uses_marker_count_and_user_source(self) -> None:
        entry = ystr_feature.make_uploaded_ystr_entry({"DYS393": [13], "DYS390": [24]})

        self.assertEqual(entry["entry_index"], -1)
        self.assertEqual(entry["source"], "Пользователь")
        self.assertEqual(entry["marker_count"], 2)

    def test_compare_entries_counts_common_markers_and_gd(self) -> None:
        left = {
            "markers": {
                "DYS393": [13],
                "DYS390": [24],
                "DYS19": [15],
                "DYS391": [10],
                "DYS385": [11, 14],
                "DYS426": [12],
                "DYS388": [12],
                "DYS439": [11],
                "DYS389i": [13],
                "DYS392": [11],
                "DYS389ii": [16],
                "CDY": [36, 38, 39],
            }
        }
        right = {
            "markers": {
                "DYS393": [13],
                "DYS390": [25],
                "DYS19": [15],
                "DYS391": [10],
                "DYS385": [11, 15],
                "DYS426": [12],
                "DYS388": [12],
                "DYS439": [11],
                "DYS389i": [13],
                "DYS392": [11],
                "DYS389ii": [16],
                "CDY": [36, 38, 40],
            }
        }

        comparison = ystr_feature.compare_ystr_entries(left, right)

        self.assertEqual(comparison["common"], 12)
        self.assertEqual(comparison["gd"], 3)
        self.assertEqual(comparison["panel"], "12")
        self.assertEqual(
            {item["marker"]: item["distance"] for item in comparison["differences"]},
            {"CDY": 1, "DYS385": 1, "DYS390": 1},
        )

    def test_find_matches_sorts_by_distance_and_filters_other_haplogroups(self) -> None:
        base_markers = {
            "DYS393": [13],
            "DYS390": [24],
            "DYS19": [15],
            "DYS391": [10],
            "DYS385": [11, 14],
            "DYS426": [12],
            "DYS388": [12],
            "DYS439": [11],
        }
        query = {
            "entry_index": 1,
            "name": "Исходный",
            "display_general": "G2a1",
            "markers": base_markers,
        }
        exact = {
            "entry_index": 2,
            "name": "Близкий",
            "display_general": "G2a1",
            "markers": dict(base_markers),
        }
        near = {
            "entry_index": 3,
            "name": "Второй",
            "display_general": "G2a1",
            "markers": {**base_markers, "DYS390": [25]},
        }
        other_haplo = {
            "entry_index": 4,
            "name": "Другая ветвь",
            "display_general": "R1a",
            "markers": dict(base_markers),
        }

        matches = ystr_feature.find_ystr_matches(query, [query, near, other_haplo, exact], min_common=8)

        self.assertEqual([item["entry"]["name"] for item in matches], ["Близкий", "Второй"])
        self.assertEqual([item["comparison"]["gd"] for item in matches], [0, 1])

    def test_nearest_matches_include_ataul_when_available(self) -> None:
        query = {
            "name": "Эркенов",
            "display_general": "G2a1",
            "display_subclade": "FGC1053",
            "ancestor": "Карачай (Атаул Къайсынлары)",
            "marker_count": 37,
        }
        match = {
            "name": "Биджиев",
            "display_general": "G2a1",
            "display_subclade": "FGC1053",
            "ancestor": "Карачай (Атаул Биджилери)",
            "marker_count": 37,
        }
        comparison = {
            "panel": "37",
            "gd": 0,
            "common": 30,
            "differences": [],
            "closeness": "очень близко",
        }

        text = ystr_ui.format_ystr_matches_text(query, [{"entry": match, "comparison": comparison}])

        self.assertIn("Карачай (Атаул Биджилери)", text)
        self.assertIn("30/30 совпало", text)

    def test_uploaded_summary_and_comparison_text_are_formatted(self) -> None:
        left = {
            "name": "Первый",
            "display_general": "G2a1",
            "display_subclade": "FGC1053",
            "ancestor": "Карачай (Атаул Первый)",
            "marker_count": 37,
            "markers": {"DYS393": [13], "DYS390": [24]},
        }
        right = {
            "name": "Второй",
            "display_general": "G2a1",
            "display_subclade": "FGC1053",
            "ancestor": "Карачай (Атаул Второй)",
            "marker_count": 37,
            "markers": {"DYS393": [13], "DYS390": [25]},
        }
        comparison = ystr_feature.compare_ystr_entries(left, right)

        summary = ystr_ui.format_ystr_uploaded_summary_text(left)
        comparison_text = ystr_ui.format_ystr_comparison_text(left, right, comparison)

        self.assertIn("Распознано маркеров: <b>37</b>", summary)
        self.assertIn("Генетическая дистанция: 1", comparison_text)
        self.assertIn("<pre>", comparison_text)
        self.assertIn("DYS390", comparison_text)


class MenuKeyboardTests(unittest.TestCase):
    def test_reply_menu_order_matches_main_layout(self) -> None:
        rows = _reply_text_rows(bot._build_bottom_menu_keyboard(include_requests=True, include_g25=True))

        self.assertEqual(
            rows,
            [
                ["🔎 Поиск по фамилии", "📊 Аналитика"],
                ["🧬 My DNA", "🧪 DNA Lab"],
                ["📚 Справка", "⚙️ Настройки"],
            ],
        )

    def test_start_text_points_g25_to_dna_lab_engine(self) -> None:
        text = bot.LOOKUP_START_TEXT

        self.assertIn("Получать и сохранять G25-профили", text)
        self.assertIn("My DNA", text)
        self.assertNotIn("старая pca", text.lower())

    def test_ystr_root_keyboard_has_optional_menu_back(self) -> None:
        rows = _inline_text_rows(ystr_ui.build_ystr_root_keyboard(bot.YSTR_CALLBACK_PREFIX, f"{bot.MENU_CALLBACK_PREFIX}:root"))
        callbacks = _inline_callback_rows(ystr_ui.build_ystr_root_keyboard(bot.YSTR_CALLBACK_PREFIX, f"{bot.MENU_CALLBACK_PREFIX}:root"))

        self.assertEqual(rows[-1], ["Назад", "Отмена"])
        self.assertEqual(callbacks[-1], [f"{bot.MENU_CALLBACK_PREFIX}:root", f"{bot.YSTR_CALLBACK_PREFIX}:cancel"])

    def test_ydna_menu_contains_str_markers_entry(self) -> None:
        rows = _inline_text_rows(analytics_ui.build_haplo_mode_keyboard(bot.HAPLO_CALLBACK_PREFIX))
        callbacks = _inline_callback_rows(analytics_ui.build_haplo_mode_keyboard(bot.HAPLO_CALLBACK_PREFIX))

        self.assertIn(["STR-маркеры"], rows)
        self.assertIn([f"{bot.HAPLO_CALLBACK_PREFIX}:ystr"], callbacks)

    def test_ystr_test_data_keyboard_back_changes_when_showing_all_markers(self) -> None:
        collapsed = ystr_ui.build_ystr_test_data_keyboard(bot.YSTR_CALLBACK_PREFIX, 42, show_all=False, has_more=True)
        expanded = ystr_ui.build_ystr_test_data_keyboard(bot.YSTR_CALLBACK_PREFIX, 42, show_all=True, has_more=False)

        self.assertEqual(_inline_text_rows(collapsed)[0], ["Показать все маркеры"])
        self.assertEqual(_inline_callback_rows(collapsed)[-1], [f"{bot.YSTR_CALLBACK_PREFIX}:databack", f"{bot.YSTR_CALLBACK_PREFIX}:cancel"])
        self.assertEqual(_inline_callback_rows(expanded)[-1], [f"{bot.YSTR_CALLBACK_PREFIX}:data:42", f"{bot.YSTR_CALLBACK_PREFIX}:cancel"])

    def test_ystr_candidate_keyboard_uses_entry_label_and_pick_callback(self) -> None:
        candidates = [
            {
                "name": "Эркенов",
                "display_general": "G2a1",
                "display_subclade": "FGC1053",
                "marker_count": 37,
            }
        ]

        keyboard = ystr_ui.build_ystr_candidates_keyboard(bot.YSTR_CALLBACK_PREFIX, candidates)

        self.assertEqual(_inline_text_rows(keyboard)[0], ["Эркенов · G2a1-FGC1053 · 37"])
        self.assertEqual(_inline_callback_rows(keyboard)[0], [f"{bot.YSTR_CALLBACK_PREFIX}:pick:0"])

    def test_group_menu_order_matches_reply_layout(self) -> None:
        rows = _inline_text_rows(bot._build_group_sections_keyboard(include_g25=True))

        self.assertEqual(
            rows,
            [
                ["🔎 Поиск по фамилии", "📊 Аналитика"],
                ["🧬 My DNA", "🧪 DNA Lab"],
                ["📚 Справка", "⚙️ Настройки"],
                ["Отмена"],
            ],
        )

    def test_lab_menu_contains_analysis_sections_only(self) -> None:
        rows = _inline_text_rows(bot._build_laboratory_inline_keyboard())
        callbacks = _inline_callback_rows(bot._build_laboratory_inline_keyboard())

        self.assertIn("🧪 <b>DNA Lab</b>", bot._laboratory_entry_text())
        self.assertIn("Выберите инструмент.", bot._laboratory_entry_text())
        self.assertNotIn("Modeling", bot._laboratory_entry_text())
        self.assertEqual(
            rows,
            [
                ["✨ Traits"],
                ["🧭 Coordinates"],
                ["📐 Vahaduo Lab"],
                ["🧩 Matching"],
                ["🧬 Admixture"],
                ["🧱 AdmixLab"],
                ["🌿 Haplogroups"],
                ["Отмена"],
            ],
        )
        self.assertTrue(any("🧱 AdmixLab" in row for row in rows))
        self.assertFalse(any("Modeling" in label for row in rows for label in row))
        self.assertEqual(
            callbacks,
            [
                [f"{bot.LAB_CALLBACK_PREFIX}:traits"],
                [f"{bot.LAB_CALLBACK_PREFIX}:coordinates"],
                [f"{bot.LAB_CALLBACK_PREFIX}:vahaduo"],
                [f"{bot.LAB_CALLBACK_PREFIX}:matching"],
                [f"{bot.LAB_CALLBACK_PREFIX}:admixture"],
                [f"{bot.LAB_CALLBACK_PREFIX}:modeling"],
                [f"{bot.LAB_CALLBACK_PREFIX}:haplogroups"],
                [f"{bot.LAB_CALLBACK_PREFIX}:cancel"],
            ],
        )

    def test_my_dna_entry_and_add_data_menus(self) -> None:
        rows = _inline_text_rows(bot._build_my_dna_inline_keyboard())
        callbacks = _inline_callback_rows(bot._build_my_dna_inline_keyboard())
        add_rows = _inline_text_rows(bot._build_my_dna_add_data_keyboard())
        add_callbacks = _inline_callback_rows(bot._build_my_dna_add_data_keyboard())

        self.assertEqual(
            rows,
            [
                ["📁 Samples"],
                ["📍 G25-профили"],
                ["📊 Reports"],
                ["📤 Загрузить raw"],
                ["🧬 Получить G25 координаты"],
            ],
        )
        self.assertEqual(
            callbacks,
            [
                ["my_data:samples_view"],
                ["my_data:coordinates_view"],
                ["reports:root"],
                ["my_data:raw_files_upload:root"],
                [f"{bot.MY_DNA_CALLBACK_PREFIX}:get_g25_raw"],
            ],
        )
        self.assertEqual(
            add_rows,
            [
                ["📤 Загрузить raw"],
                ["🧬 Получить G25 координаты"],
                ["✍️ Вставить G25 вручную"],
                ["🌿 Добавить гаплогруппу"],
                ["⬅️ Назад", "Отмена"],
            ],
        )
        self.assertEqual(
            add_callbacks,
            [
                ["my_data:raw_files_upload:add_data"],
                [f"{bot.MY_DNA_CALLBACK_PREFIX}:get_g25_raw"],
                ["my_data:coordinates_add_type:g25:add_data"],
                ["haplogroups:manual_add_data"],
                [f"{bot.MY_DNA_CALLBACK_PREFIX}:root", "my_data:cancel"],
            ],
        )

    def test_support_menu_is_documentation_root(self) -> None:
        rows = _inline_text_rows(bot._build_help_inline_keyboard())
        callbacks = _inline_callback_rows(bot._build_help_inline_keyboard())

        self.assertIn("📚 <b>Справка</b>", bot._help_entry_text())
        self.assertIn("Данные, разделы и ограничения.", bot._help_entry_text())
        self.assertIn("Основные пояснения по KBDNA.", bot._help_entry_text())
        self.assertEqual(
            rows,
            [
                ["🚀 Быстрый старт"],
                ["🔎 Поиск по фамилиям"],
                ["📊 Аналитика KBDNA"],
                ["🧬 Данные: raw, G25, SNP"],
                ["🧪 Разделы DNA Lab"],
                ["🧱 AdmixLab / qpAdm"],
                ["📖 Термины DNA"],
                ["🛡 Ограничения"],
                ["📚 КБ словарь"],
                ["⬅️ Назад", "Отмена"],
            ],
        )
        self.assertEqual(
            callbacks,
            [
                [f"{bot.HELP_CALLBACK_PREFIX}:quick_start"],
                [f"{bot.HELP_CALLBACK_PREFIX}:surname_search"],
                [f"{bot.HELP_CALLBACK_PREFIX}:analytics"],
                [f"{bot.HELP_CALLBACK_PREFIX}:data_formats"],
                [f"{bot.HELP_CALLBACK_PREFIX}:dna_lab_sections"],
                [f"{bot.HELP_CALLBACK_PREFIX}:admixlab"],
                [f"{bot.HELP_CALLBACK_PREFIX}:terms"],
                [f"{bot.HELP_CALLBACK_PREFIX}:limitations"],
                [f"{bot.HELP_CALLBACK_PREFIX}:dictionary"],
                [f"{bot.HELP_CALLBACK_PREFIX}:back", f"{bot.HELP_CALLBACK_PREFIX}:cancel"],
            ],
        )
        root_labels = [label for row in rows for label in row]
        self.assertNotIn("🧬 Что такое raw?", root_labels)
        self.assertNotIn("📍 Что такое G25?", root_labels)
        self.assertNotIn("🛠 Что такое qpAdm?", root_labels)
        self.assertNotIn("🧾 Что такое PGS?", root_labels)
        self.assertNotIn("ℹ️ Инструкция", root_labels)

    def test_support_topic_footer_uses_back_and_cancel(self) -> None:
        self.assertEqual(_inline_text_rows(bot._build_help_topic_keyboard()), [["⬅️ Назад", "Отмена"]])

    def test_surname_search_help_has_final_copy(self) -> None:
        text = bot._help_topic_text("surname_search")

        self.assertIn("🔎 <b>Поиск по фамилиям</b>", text)
        self.assertIn("самый быстрый вход в базу KBDNA", text)
        self.assertIn("<b>Как искать</b>", text)
        self.assertIn("<code>/f Фамилия</code>", text)
        self.assertIn("<b>Что показывает результат</b>", text)
        self.assertIn("• найденные записи по фамилии;", text)
        self.assertIn("<b>Если фамилия не найдена</b>", text)
        self.assertIn("не заменяет генеалогическую проверку", text)
        self.assertNotIn("Раздел будет дополнен.", text)

    def test_analytics_help_has_final_copy(self) -> None:
        text = bot._help_topic_text("analytics")

        self.assertIn("📊 <b>Аналитика KBDNA</b>", text)
        self.assertIn("общую картину по базе проекта", text)
        self.assertIn("<b>Что можно смотреть</b>", text)
        self.assertIn("• распределение Y-ДНК и мтДНК гаплогрупп;", text)
        self.assertIn("• STR-маркеры и ближайшие STR-совпадения;", text)
        self.assertIn("<b>Как использовать</b>", text)
        self.assertIn("1. Начните с общего распределения.", text)
        self.assertIn("Аналитика показывает структуру базы KBDNA", text)
        self.assertNotIn("Раздел будет дополнен.", text)

    def test_data_formats_help_has_final_copy(self) -> None:
        text = bot._help_topic_text("data_formats")

        self.assertIn("🧬 <b>Данные: raw, G25, SNP</b>", text)
        self.assertIn("не заменяют друг друга", text)
        self.assertIn("<b>🧾 Raw-файл</b>", text)
        self.assertIn("23andMe, Ancestry, MyHeritage, FTDNA", text)
        self.assertIn("<b>📍 G25</b>", text)
        self.assertIn("Coordinate spaces, Vahaduo Lab", text)
        self.assertIn("<b>🧬 SNP</b>", text)
        self.assertIn("<b>🧪 PGS</b>", text)
        self.assertIn("<b>Как начать</b>", text)
        self.assertNotIn("Раздел будет дополнен.", text)

    def test_dna_lab_sections_help_has_final_copy(self) -> None:
        text = bot._help_topic_text("dna_lab_sections")

        self.assertIn("🧪 <b>Разделы DNA Lab</b>", text)
        self.assertIn("рабочая зона для ваших samples", text)
        self.assertIn("<b>🧬 My DNA</b>", text)
        self.assertIn("<b>📐 Vahaduo Lab</b>", text)
        self.assertIn("<b>🧩 Matching</b>", text)
        self.assertIn("<b>🧱 AdmixLab</b>", text)
        self.assertIn("сначала создать sample в My DNA", text)
        self.assertNotIn("Раздел будет дополнен.", text)

    def test_admixlab_help_has_final_copy(self) -> None:
        text = bot._help_topic_text("admixlab")

        self.assertIn("🧱 <b>AdmixLab / qpAdm</b>", text)
        self.assertIn("не про готовые G25-fit модели", text)
        self.assertIn("<b>🏛 qpAdm</b>", text)
        self.assertIn("<b>〰️ qpWave</b>", text)
        self.assertIn("<b>📚 Source sets</b>", text)
        self.assertIn("Набор sources/outgroups влияет на результат", text)
        self.assertNotIn("Раздел будет дополнен.", text)

    def test_terms_help_has_final_copy(self) -> None:
        text = bot._help_topic_text("terms")

        self.assertIn("📖 <b>Термины DNA</b>", text)
        self.assertIn("<b>Raw</b>", text)
        self.assertIn("<b>G25</b>", text)
        self.assertIn("<b>SNP</b>", text)
        self.assertIn("<b>Outgroup</b>", text)
        self.assertIn("<b>Sample</b>", text)
        self.assertNotIn("Раздел будет дополнен.", text)

    def test_limitations_help_has_final_copy(self) -> None:
        text = bot._help_topic_text("limitations")

        self.assertIn("🛡 <b>Ограничения</b>", text)
        self.assertIn("у каждого расчёта есть границы", text)
        self.assertIn("• результаты зависят от качества raw-файла", text)
        self.assertIn("KBDNA не ставит медицинские диагнозы", text)
        self.assertIn("не определяет национальность", text)
        self.assertNotIn("Раздел будет дополнен.", text)

    def test_quick_start_has_final_user_flow_copy(self) -> None:
        text = bot._help_topic_text("quick_start")

        self.assertIn("🚀 <b>Быстрый старт</b>", text)
        self.assertIn("KBDNA можно использовать двумя способами", text)
        self.assertIn("<b>1. 🔎 Поиск по фамилиям</b>", text)
        self.assertIn("<b>2. 📊 Аналитика</b>", text)
        self.assertIn("<b>3. 🧬 My DNA</b>", text)
        self.assertIn("<b>4. 🧪 DNA Lab</b>", text)
        self.assertIn("Sample — это отдельный профиль человека или образца.", text)
        self.assertIn("результаты KBDNA — это расчёты и модели", text)
        self.assertNotIn("Раздел будет дополнен.", text)

    def test_legacy_support_callbacks_redirect_to_new_placeholders(self) -> None:
        self.assertIn("📖 <b>Термины DNA</b>", bot._help_topic_text("raw"))
        self.assertIn("📖 <b>Термины DNA</b>", bot._help_topic_text("g25"))
        self.assertIn("📖 <b>Термины DNA</b>", bot._help_topic_text("pgs"))
        self.assertIn("🧱 <b>AdmixLab / qpAdm</b>", bot._help_topic_text("qpadm"))
        self.assertIn("🚀 <b>Быстрый старт</b>", bot._help_topic_text("instruction"))

    def test_help_menu_has_full_topics(self) -> None:
        rows = _inline_text_rows(bot._build_help_keyboard())
        callbacks = _inline_callback_rows(bot._build_help_keyboard())

        self.assertIn(["🧬 DNA-разделы"], rows)
        self.assertIn(["🧬 G25 и PCA"], rows)
        self.assertIn(["🔒 Данные и приватность"], rows)
        self.assertIn([f"{bot.MENU_CALLBACK_PREFIX}:help:dna_lab"], callbacks)
        self.assertEqual(callbacks[-1], [f"{bot.MENU_CALLBACK_PREFIX}:support", f"{bot.MENU_CALLBACK_PREFIX}:cancel"])

    def test_lab_and_help_callbacks_are_registered(self) -> None:
        source = Path("bot.py").read_text(encoding="utf-8")

        self.assertIn("laboratory_callback_handler, pattern=r\"^lab:\"", source)
        self.assertIn("my_dna_entry_callback_handler, pattern=r\"^(?:mydna:|my_data:root$)\"", source)
        self.assertIn("help_entry_callback_handler, pattern=r\"^help:\"", source)
        self.assertIn("dna_lab_main_navigation_callback_handler, pattern=fr\"^{DNA_LAB_MAIN_CALLBACK_PREFIX}:\"", source)

    def test_navigation_roots_do_not_render_reply_main_inside_private_inline(self) -> None:
        source = Path("bot.py").read_text(encoding="utf-8")

        self.assertIn('if _is_private_chat(update):\n            _forget_active_reply_menu', source)
        self.assertIn('await query.message.edit_text("Главное меню доступно внизу.")', source)
        self.assertIn("await query.message.edit_text(\n            _laboratory_entry_text()", source)
        self.assertIn('back_callback=f"{MENU_CALLBACK_PREFIX}:cancel"', source)

    def test_bottom_menu_handler_runs_before_dna_lab_pending_text_handlers(self) -> None:
        source = Path("bot.py").read_text(encoding="utf-8")

        self.assertIn("private_bottom_menu_handler,\n        ),\n        group=-6", source)
        self.assertIn("dna_lab_my_data_text_input_handler), group=-5", source)
        self.assertIn("dna_lab_vahaduo_text_input_handler), group=-4", source)
        self.assertIn("dna_lab_modeling_text_input_handler), group=-1", source)
        self.assertLess(
            source.index("dna_lab_modeling_text_input_handler), group=-1"),
            source.index("MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, text_lookup_command)"),
        )

    def test_global_settings_keyboard_reuses_dna_lab_settings_ui(self) -> None:
        keyboard = settings_menu.build_settings_keyboard(
            "ru",
            callback_prefix=bot.MENU_CALLBACK_PREFIX,
            back_callback=f"{bot.MENU_CALLBACK_PREFIX}:root",
            cancel_callback=f"{bot.MENU_CALLBACK_PREFIX}:cancel",
        )
        rows = _inline_text_rows(keyboard)
        callbacks = _inline_callback_rows(keyboard)

        self.assertEqual(
            rows,
            [
                ["🌐 Язык"],
                ["🖼 Формат карточек"],
                ["✨ Режим результатов"],
                ["🌍 База поиска"],
                ["🔔 Уведомления"],
                ["🗑 Данные и приватность"],
                ["Отмена"],
            ],
        )
        self.assertEqual(
            callbacks,
            [
                [f"{bot.MENU_CALLBACK_PREFIX}:language"],
                [f"{bot.MENU_CALLBACK_PREFIX}:card_format"],
                [f"{bot.MENU_CALLBACK_PREFIX}:result_mode"],
                [f"{bot.MENU_CALLBACK_PREFIX}:search_base"],
                [f"{bot.MENU_CALLBACK_PREFIX}:notifications"],
                [f"{bot.MENU_CALLBACK_PREFIX}:privacy"],
                [f"{bot.MENU_CALLBACK_PREFIX}:cancel"],
            ],
        )

    def test_card_format_keyboard_marks_current_format(self) -> None:
        keyboard = settings_menu.build_card_format_keyboard(
            "ru",
            "wide",
            callback_prefix=bot.MENU_CALLBACK_PREFIX,
            back_callback=f"{bot.MENU_CALLBACK_PREFIX}:settings",
            cancel_callback=f"{bot.MENU_CALLBACK_PREFIX}:cancel",
        )
        rows = _inline_text_rows(keyboard)
        callbacks = _inline_callback_rows(keyboard)

        self.assertEqual(rows, [["🖥 Широкий ✅"], ["📱 Мобильный"], ["⬅️ Назад", "Отмена"]])
        self.assertEqual(
            callbacks,
            [
                [f"{bot.MENU_CALLBACK_PREFIX}:set_card_format:wide"],
                [f"{bot.MENU_CALLBACK_PREFIX}:set_card_format:mobile"],
                [f"{bot.MENU_CALLBACK_PREFIX}:settings", f"{bot.MENU_CALLBACK_PREFIX}:cancel"],
            ],
        )

    def test_result_mode_keyboard_marks_current_mode(self) -> None:
        keyboard = settings_menu.build_result_mode_keyboard(
            "ru",
            "advanced",
            callback_prefix=bot.MENU_CALLBACK_PREFIX,
            back_callback=f"{bot.MENU_CALLBACK_PREFIX}:settings",
            cancel_callback=f"{bot.MENU_CALLBACK_PREFIX}:cancel",
        )
        rows = _inline_text_rows(keyboard)
        callbacks = _inline_callback_rows(keyboard)

        self.assertEqual(rows, [["✨ Обычный"], ["🧪 Расширенный ✅"], ["⬅️ Назад", "Отмена"]])
        self.assertEqual(
            callbacks,
            [
                [f"{bot.MENU_CALLBACK_PREFIX}:set_result_mode:simple"],
                [f"{bot.MENU_CALLBACK_PREFIX}:set_result_mode:advanced"],
                [f"{bot.MENU_CALLBACK_PREFIX}:settings", f"{bot.MENU_CALLBACK_PREFIX}:cancel"],
            ],
        )

    def test_search_base_keyboard_marks_current_base(self) -> None:
        keyboard = settings_menu.build_search_base_keyboard(
            "ru",
            "abkhaz",
            callback_prefix=bot.MENU_CALLBACK_PREFIX,
            back_callback=f"{bot.MENU_CALLBACK_PREFIX}:settings",
            cancel_callback=f"{bot.MENU_CALLBACK_PREFIX}:cancel",
        )
        rows = _inline_text_rows(keyboard)
        callbacks = _inline_callback_rows(keyboard)

        self.assertEqual(
            rows,
            [
                ["KBDNA"],
                ["Адыгская"],
                ["Абхазская ✅"],
                ["Абазинская"],
                ["⬅️ Назад", "Отмена"],
            ],
        )
        self.assertEqual(
            callbacks,
            [
                [f"{bot.MENU_CALLBACK_PREFIX}:set_search_base:kbdna"],
                [f"{bot.MENU_CALLBACK_PREFIX}:set_search_base:adyghe"],
                [f"{bot.MENU_CALLBACK_PREFIX}:set_search_base:abkhaz"],
                [f"{bot.MENU_CALLBACK_PREFIX}:set_search_base:abaza"],
                [f"{bot.MENU_CALLBACK_PREFIX}:settings", f"{bot.MENU_CALLBACK_PREFIX}:cancel"],
            ],
        )

    def test_notifications_keyboard_marks_current_status(self) -> None:
        keyboard = settings_menu.build_notifications_keyboard(
            "ru",
            False,
            callback_prefix=bot.MENU_CALLBACK_PREFIX,
            back_callback=f"{bot.MENU_CALLBACK_PREFIX}:settings",
            cancel_callback=f"{bot.MENU_CALLBACK_PREFIX}:cancel",
        )
        rows = _inline_text_rows(keyboard)
        callbacks = _inline_callback_rows(keyboard)

        self.assertEqual(rows, [["🔔 Включены"], ["🔕 Выключены ✅"], ["⬅️ Назад", "Отмена"]])
        self.assertEqual(
            callbacks,
            [
                [f"{bot.MENU_CALLBACK_PREFIX}:set_notifications:on"],
                [f"{bot.MENU_CALLBACK_PREFIX}:set_notifications:off"],
                [f"{bot.MENU_CALLBACK_PREFIX}:settings", f"{bot.MENU_CALLBACK_PREFIX}:cancel"],
            ],
        )

    def test_privacy_keyboard_uses_real_data_actions(self) -> None:
        text = settings_menu.privacy_text(
            "ru",
            settings_menu.PrivacyDataSummary(samples=3, raw_files=2, g25_profiles=4, saved_reports=1),
        )
        keyboard = settings_menu.build_privacy_keyboard(
            "ru",
            callback_prefix=bot.MENU_CALLBACK_PREFIX,
            back_callback=f"{bot.MENU_CALLBACK_PREFIX}:settings",
            cancel_callback=f"{bot.MENU_CALLBACK_PREFIX}:cancel",
        )
        rows = _inline_text_rows(keyboard)
        callbacks = _inline_callback_rows(keyboard)

        self.assertIn("<b>🗑 Данные и приватность</b>", text)
        self.assertIn("Samples: 3", text)
        self.assertIn("Raw-файлы: 2", text)
        self.assertIn("G25-профили: 4", text)
        self.assertIn("Сохранённые отчёты: 1", text)
        self.assertEqual(
            rows,
            [
                ["📁 Samples"],
                ["📍 G25-профили"],
                ["📊 Reports"],
                ["📦 Экспорт моих данных"],
                ["🗑 Удалить все мои данные"],
                ["ℹ️ Как хранятся данные"],
                ["⬅️ Назад", "Отмена"],
            ],
        )
        self.assertEqual(
            callbacks,
            [
                [f"{bot.MENU_CALLBACK_PREFIX}:privacy_samples"],
                [f"{bot.MENU_CALLBACK_PREFIX}:privacy_g25"],
                [f"{bot.MENU_CALLBACK_PREFIX}:privacy_reports"],
                [f"{bot.MENU_CALLBACK_PREFIX}:export_data"],
                [f"{bot.MENU_CALLBACK_PREFIX}:delete_data"],
                [f"{bot.MENU_CALLBACK_PREFIX}:privacy_info"],
                [f"{bot.MENU_CALLBACK_PREFIX}:settings", f"{bot.MENU_CALLBACK_PREFIX}:cancel"],
            ],
        )
        export_text = settings_menu.privacy_export_text(
            "ru",
            settings_menu.PrivacyDataSummary(samples=3, raw_files=2, g25_profiles=4, saved_reports=1),
        )
        export_keyboard = settings_menu.build_privacy_export_keyboard(
            "ru",
            callback_prefix=bot.MENU_CALLBACK_PREFIX,
            back_callback=f"{bot.MENU_CALLBACK_PREFIX}:privacy",
            cancel_callback=f"{bot.MENU_CALLBACK_PREFIX}:cancel",
        )
        self.assertIn("Файл придёт отдельным сообщением в этот же чат.", export_text)
        self.assertEqual(_inline_text_rows(export_keyboard), [["📦 Экспортировать"], ["⬅️ Назад", "Отмена"]])
        self.assertEqual(
            _inline_callback_rows(export_keyboard),
            [[f"{bot.MENU_CALLBACK_PREFIX}:export_data_run"], [f"{bot.MENU_CALLBACK_PREFIX}:privacy", f"{bot.MENU_CALLBACK_PREFIX}:cancel"]],
        )
        delete_text = settings_menu.privacy_delete_confirm_text(
            "ru",
            settings_menu.PrivacyDataSummary(samples=3, raw_files=2, g25_profiles=4, saved_reports=1),
        )
        delete_keyboard = settings_menu.build_privacy_delete_confirm_keyboard(
            "ru",
            callback_prefix=bot.MENU_CALLBACK_PREFIX,
            back_callback=f"{bot.MENU_CALLBACK_PREFIX}:privacy",
            cancel_callback=f"{bot.MENU_CALLBACK_PREFIX}:cancel",
        )
        self.assertIn("Будет удалено:", delete_text)
        self.assertIn("Это действие нельзя отменить.", delete_text)
        self.assertEqual(_inline_text_rows(delete_keyboard), [["✅ Да, удалить всё"], ["⬅️ Назад", "Отмена"]])
        self.assertEqual(
            _inline_callback_rows(delete_keyboard),
            [[f"{bot.MENU_CALLBACK_PREFIX}:delete_data_confirm"], [f"{bot.MENU_CALLBACK_PREFIX}:privacy", f"{bot.MENU_CALLBACK_PREFIX}:cancel"]],
        )

    def test_global_language_keyboard_marks_current_language(self) -> None:
        keyboard = settings_menu.build_language_keyboard(
            "en",
            callback_prefix=bot.MENU_CALLBACK_PREFIX,
            back_callback=f"{bot.MENU_CALLBACK_PREFIX}:settings",
            cancel_callback=f"{bot.MENU_CALLBACK_PREFIX}:cancel",
        )
        rows = _inline_text_rows(keyboard)
        callbacks = _inline_callback_rows(keyboard)

        self.assertEqual(rows, [["Русский"], ["English ✅"], ["Back", "Cancel"]])
        self.assertEqual(
            callbacks,
            [
                [f"{bot.MENU_CALLBACK_PREFIX}:set_language:ru"],
                [f"{bot.MENU_CALLBACK_PREFIX}:set_language:en"],
                [f"{bot.MENU_CALLBACK_PREFIX}:settings", f"{bot.MENU_CALLBACK_PREFIX}:cancel"],
            ],
        )

    def test_stats_menu_is_compact_and_uses_same_section_order(self) -> None:
        rows = _inline_text_rows(bot._build_stats_root_keyboard())

        self.assertEqual(
            rows,
            [
                ["🔎 Поиск по фамилии", "✅ Качество"],
                ["Отмена"],
            ],
        )

    def test_pending_text_router_prefers_active_sozluk_state(self) -> None:
        context = SimpleNamespace(
            user_data={
                "sozluk_pending": {"chat_id": 10, "direction": 0},
                "ystr_pending": {"chat_id": 10, "mode": "nearest_name"},
            }
        )

        self.assertEqual(bot._pending_text_target(context, 10), "sozluk")
        self.assertIsNone(bot._pending_text_target(context, 11))

    def test_pending_text_router_detects_ystr_state(self) -> None:
        context = SimpleNamespace(user_data={"ystr_pending": {"chat_id": 10, "mode": "nearest_name"}})

        self.assertEqual(bot._pending_text_target(context, 10), "ystr")
        self.assertIsNone(bot._pending_text_target(context, 11))

    def test_bottom_menu_navigation_can_clear_matching_text_pending(self) -> None:
        class _Store:
            def __init__(self) -> None:
                self.cleared = []

            def clear_pending(self, chat_id: int, user_id: int) -> None:
                self.cleared.append((chat_id, user_id))

        store = _Store()
        context = SimpleNamespace(application=SimpleNamespace(bot_data={"matching_flow_store": store}))

        bot._clear_matching_pending(context, 10, 1)

        self.assertEqual(store.cleared, [(10, 1)])


class UsageStoreTests(unittest.TestCase):
    def test_ystr_summary_counts_commands_by_section(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = bot.UsageStore(Path(tmp_dir) / "usage.sqlite3")
            update = SimpleNamespace(
                effective_user=SimpleNamespace(id=100, username="tester", first_name="Test", last_name="User"),
                effective_chat=SimpleNamespace(id=200, type="private"),
            )

            store.record_ystr(update, "nearest", query="A")
            store.record_ystr(update, "upload_nearest", query="B")
            store.record_ystr(update, "compare", query="C")
            store.record_ystr(update, "upload", query="markers.csv", input_mode="file")

            summary = store.get_summary()

            self.assertEqual(summary["ystr_total"], 4)
            self.assertEqual(summary["ystr_success"], 4)
            self.assertEqual(summary["ystr_nearest"], 2)
            self.assertEqual(summary["ystr_compare"], 1)
            self.assertEqual(summary["ystr_upload"], 1)
            self.assertEqual(summary["ystr_unique_users"], 1)


if __name__ == "__main__":
    unittest.main()
