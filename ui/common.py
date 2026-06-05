from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup


BOTTOM_BUTTON_HELP = "ℹ️ Инструкция"
BOTTOM_BUTTON_STATS = "📊 Аналитика"
BOTTOM_BUTTON_DNA_LAB = "🧪 DNA Lab"
BOTTOM_BUTTON_LAB = "🧪 Лаборатория"
BOTTOM_BUTTON_GET_G25 = "🧬 Получить G25 координаты"
BOTTOM_BUTTON_SETTINGS = "⚙️ Настройки"
BOTTOM_BUTTON_YSTR = "🧬 Y-STR анализ"
BOTTOM_BUTTON_SOZLUK = "📚 Словарь"
BOTTOM_BUTTON_SUPPORT = "📚 Справка"
BOTTOM_BUTTON_LOOKUP = "🔎 Поиск по фамилии"
BOTTOM_BUTTON_MORE = "🧩 Прочее"
BOTTOM_BUTTON_MY_DNA = "🧬 My DNA"
BOTTOM_BUTTON_COORDINATE_SPACES = "🧭 Coordinate spaces"
BOTTOM_BUTTON_VAHADUO = "📐 Vahaduo Lab"
BOTTOM_BUTTON_MATCHING = "🧩 Matching"
BOTTOM_BUTTON_MODELING = "🧱 AdmixLab"
BOTTOM_BUTTON_TRAITS = "✨ Traits"
MORE_BUTTON_ADMIXTURE = "🧬 Admixture"
MORE_BUTTON_HAPLOGROUPS = "🌿 Haplogroups"
BOTTOM_BUTTON_BACK = "Назад"
BOTTOM_BUTTON_CANCEL = "Отмена"
LAB_BUTTON_COORDINATES = "🧭 Coordinates"
LAB_BUTTON_ADMIXTURE = "🧬 Admixture"
LAB_BUTTON_MODELING = "🧱 AdmixLab"
LAB_BUTTON_GET_G25 = "🧬 Получить G25"
MY_DNA_BUTTON_SAMPLES = "📁 Samples"
MY_DNA_BUTTON_G25_PROFILES = "📍 G25-профили"
MY_DNA_BUTTON_REPORTS = "📊 Reports"
MY_DNA_BUTTON_ADD_DATA = "➕ Добавить данные"
MY_DNA_BUTTON_ADD_RAW = "📤 Загрузить raw"
MY_DNA_BUTTON_GET_G25_FROM_RAW = "🧬 Получить G25 координаты"
MY_DNA_BUTTON_ADD_G25_MANUAL = "✍️ Вставить G25 вручную"
MY_DNA_BUTTON_ADD_HAPLOGROUP = "🌿 Добавить гаплогруппу"
MY_DNA_BUTTON_BACK = "⬅️ Назад"
HELP_BUTTON_RAW = "🧬 Что такое raw?"
HELP_BUTTON_G25 = "📍 Что такое G25?"
HELP_BUTTON_QPADM = "🛠 Что такое qpAdm?"
HELP_BUTTON_PGS = "🧾 Что такое PGS?"


def build_lookup_start_text(build_id: str) -> str:
    return (
        "<b>KBDNA</b>\n"
        "Поиск по фамилиям, аналитика базы и DNA-инструменты.\n\n"
        "<b>Быстрый вход</b>\n"
        "• напишите фамилию одним сообщением;\n"
        "• откройте <b>DNA Lab</b> для My DNA, Vahaduo, AdmixLab, Traits, SNP Report и Matching;\n"
        "• откройте <b>Аналитику</b> для гаплогрупп, субкладов и Y-STR;\n"
        "• <b>Справка</b> объясняет raw, G25, SNP, qpAdm и ограничения.\n\n"
        "В личном чате используйте кнопки ниже.\n"
        "В группе: <code>/menu</code>, поиск: <code>/f Фамилия</code>.\n\n"
        f"<code>{build_id}</code>"
    )


def build_lookup_suggestions_keyboard(lookup_callback_prefix: str, names: list[str]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(name, callback_data=f"{lookup_callback_prefix}:s:{index}")] for index, name in enumerate(names)]
    )


def build_lookup_result_keyboard(
    lookup_callback_prefix: str,
    records: list[dict[str, str]],
    remaining_indexes: list[int] | None = None,
) -> InlineKeyboardMarkup:
    indexes = remaining_indexes if remaining_indexes is not None else list(range(len(records)))
    rows = [
        [InlineKeyboardButton(records[index]["button_label"], callback_data=f"{lookup_callback_prefix}:r:{index}")]
        for index in indexes
    ]
    if len(indexes) > 1:
        rows.append([InlineKeyboardButton("Показать все", callback_data=f"{lookup_callback_prefix}:a:all")])
    return InlineKeyboardMarkup(rows)


LOOKUP_HELP_TEXT = (
    "<b>Инструкция KBDNA</b>\n\n"
    "<b>🔎 Найти фамилию</b>\n"
    "Напишите фамилию одним сообщением.\n\n"
    "Можно также использовать команду:\n"
    "<code>/f Фамилия</code>\n\n"
    "Бот покажет найденные записи, происхождение, гаплогруппу и близкие совпадения по той же ветви.\n\n"
    "<b>📊 Посмотреть аналитику</b>\n"
    "Нажмите <b>Аналитика</b>.\n\n"
    "Там есть два раздела:\n"
    "• <b>Y-ДНК</b> — мужские линии.\n"
    "• <b>МтДНК</b> — материнские линии.\n\n"
    "В диаграммах можно посмотреть распределение групп. "
    "В навигаторе можно пройти от группы к субкладу и увидеть связанные фамилии или записи. "
    "В разделе <b>Y-ДНК → STR-маркеры</b> можно работать с мужскими STR-маркерами.\n\n"
    "<b>🧬 Y-STR анализ</b>\n"
    "Откройте <b>Аналитика → Y-ДНК → STR-маркеры</b>, если хотите работать с мужскими STR-маркерами.\n\n"
    "В разделе можно:\n"
    "• найти ближайшие STR-совпадения;\n"
    "• посмотреть данные одного теста;\n"
    "• сравнить две записи из KBDNA;\n"
    "• загрузить свои маркеры текстом или .txt/.csv файлом.\n\n"
    "Чем больше общих маркеров, тем надежнее сравнение. Оценка поколений, если она показана, является приблизительным STR-ориентиром.\n\n"
    "<b>🧭 PCA и G25</b>\n"
    "Откройте <b>DNA Lab → Coordinates</b>, если хотите сравнить свои координаты с древними или современными популяциями.\n\n"
    "Если у вас уже есть G25-координаты, отправляйте их текстом или файлом.\n"
    "Если G25 еще нет, откройте <b>My DNA → Получить G25 координаты</b> и отправьте raw-файл документом.\n\n"
    "Raw-файл — это файл с ДНК-данными из 23andMe, Ancestry, MyHeritage, FTDNA и похожих сервисов.\n\n"
    "<b>📚 Найти слово в словаре</b>\n"
    "Нажмите <b>Справка → Словарь</b> и отправьте слово.\n\n"
    "В группах используйте команду:\n"
    "<code>/s слово</code>\n\n"
    "Словарь ищет точное слово сразу в двух направлениях: русский ↔ карачаево-балкарский.\n\n"
    "<b>👥 В группах</b>\n"
    "Откройте меню командой:\n"
    "<code>/menu</code>\n\n"
    "Если бот просит файл, координаты или маркеры, отправляйте их ответом на сообщение бота. "
    "Так бот поймет, к какому действию относится файл.\n\n"
    "По всем вопросам: @jb_cc"
)

HELP_ROOT_TEXT = (
    "<b>ℹ️ Справка KBDNA</b>\n\n"
    "Это справочник по основным разделам бота: поиск по базе, аналитика, My DNA, G25, словарь и настройки.\n\n"
    "Выберите тему ниже. Каждый раздел открывается отдельным экраном, чтобы не листать одну длинную инструкцию."
)

HELP_SECTIONS: dict[str, tuple[str, str]] = {
    "lookup": (
        "🔎 Поиск по фамилии",
        (
            "<b>🔎 Поиск по фамилии</b>\n\n"
            "Основной поиск работает по базе KBDNA. В приватном чате можно просто отправить фамилию одним сообщением. "
            "В группе используйте команду <code>/f Фамилия</code>.\n\n"
            "Бот показывает найденные записи, происхождение, гаплогруппу, субклад и близкие совпадения по той же ветви, "
            "если такие данные есть в базе.\n\n"
            "<b>Если фамилия не найдена</b>\n"
            "Проверьте написание, попробуйте вариант без окончания или другой вариант транслитерации. "
            "Для редких фамилий база может пока не содержать записи."
        ),
    ),
    "analytics": (
        "📊 Аналитика",
        (
            "<b>📊 Аналитика</b>\n\n"
            "Раздел для просмотра структуры KBDNA по Y-ДНК, мтДНК, субкладам и STR-маркерам.\n\n"
            "<b>Y-ДНК</b> показывает мужские линии: распределение гаплогрупп, переход от крупной ветви к субкладам, "
            "связанные фамилии и тесты.\n\n"
            "<b>МтДНК</b> показывает материнские линии и их распределение по образцам.\n\n"
            "<b>Y-STR анализ</b> нужен для работы с мужскими STR-маркерами: ближайшие совпадения, карточка теста, "
            "сравнение двух записей и загрузка своих маркеров текстом или файлом."
        ),
    ),
    "dna_lab": (
        "🧬 DNA-разделы",
        (
            "<b>🧬 DNA-разделы</b>\n\n"
            "Рабочие разделы для raw/G25 данных и расчетов вокруг sample теперь вынесены напрямую в меню.\n\n"
            "<b>📁 My DNA</b> хранит samples, raw-файлы, G25-профили и сохраненные отчеты.\n\n"
            "<b>🧭 Coordinate spaces</b> показывает положение sample в готовых региональных пространствах.\n\n"
            "<b>📐 Vahaduo Lab</b> считает Distance, Single и Multi по target/source наборам.\n\n"
            "<b>🧬 Admixture</b> и <b>🧱 AdmixLab</b> помогают разбирать компонентные профили и формальные модели.\n\n"
            "<b>🧩 Matching</b>, <b>✨ Traits</b> и <b>🌿 Haplogroups</b> работают с сохраненными sample и отчетами.\n\n"
            "Практическое правило: если данные будут использоваться регулярно, сначала создайте sample в My DNA."
        ),
    ),
    "g25": (
        "🧬 G25 и PCA",
        (
            "<b>🧬 G25 и PCA</b>\n\n"
            "<b>Получить G25 координаты</b> находится прямо в <b>My DNA</b>. Туда отправляют raw-файл документом, "
            "а бот возвращает строку G25. По умолчанию это быстрый режим: координаты не сохраняются автоматически.\n\n"
            "После расчета можно создать sample или сохранить координаты в <b>My DNA → G25-профили</b>.\n\n"
            "<b>PCA/Coordinate spaces</b> теперь открывается через <b>DNA Lab → Coordinates</b>. "
            "Там выбирается готовое пространство, затем sample или G25-профиль.\n\n"
            "Raw-файл - это файл с ДНК-данными из 23andMe, Ancestry, MyHeritage, FTDNA и похожих сервисов."
        ),
    ),
    "dictionary": (
        "📚 Словарь",
        (
            "<b>📚 Словарь</b>\n\n"
            "Словарь ищет точные слова в двух направлениях: русский ↔ карачаево-балкарский.\n\n"
            "В приватном чате нажмите <b>Справка → Словарь</b> и отправьте слово. "
            "В группе используйте команду <code>/s слово</code>.\n\n"
            "Если слово не найдено, попробуйте другую форму, написание без дефиса или более короткую основу."
        ),
    ),
    "settings": (
        "⚙️ Настройки",
        (
            "<b>⚙️ Настройки</b>\n\n"
            "Настройки находятся в основном меню и в reply-клавиатуре. Сейчас главный параметр - язык интерфейса.\n\n"
            "Выбранный язык общий для KBDNA/DNA Lab: меню, подписи и часть рабочих экранов будут открываться на выбранном языке.\n\n"
            "Если старое сообщение меню осталось на другом языке, откройте новое меню через <code>/menu</code> или кнопку reply."
        ),
    ),
    "privacy": (
        "🔒 Данные и приватность",
        (
            "<b>🔒 Данные и приватность</b>\n\n"
            "Raw-файлы и G25-координаты относятся к чувствительным генетическим данным. "
            "Загружайте только данные, которые вы имеете право обрабатывать.\n\n"
            "Для разовых расчетов используйте быстрый режим без сохранения. Для регулярной работы создавайте sample в My DNA.\n\n"
            "Результаты расчетов являются справочно-аналитическими. Они зависят от качества исходных данных, выбранных reference panels "
            "и метода расчета; это не медицинское, юридическое или окончательное генеалогическое заключение."
        ),
    ),
}


def build_help_keyboard(menu_callback_prefix: str) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(label, callback_data=f"{menu_callback_prefix}:help:{key}")] for key, (label, _) in HELP_SECTIONS.items()]
    rows.append([
        InlineKeyboardButton(BOTTOM_BUTTON_BACK, callback_data=f"{menu_callback_prefix}:support"),
        InlineKeyboardButton(BOTTOM_BUTTON_CANCEL, callback_data=f"{menu_callback_prefix}:cancel"),
    ])
    return InlineKeyboardMarkup(rows)


def build_help_section_keyboard(menu_callback_prefix: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("К разделам справки", callback_data=f"{menu_callback_prefix}:help")],
        [
            InlineKeyboardButton(BOTTOM_BUTTON_BACK, callback_data=f"{menu_callback_prefix}:support"),
            InlineKeyboardButton(BOTTOM_BUTTON_CANCEL, callback_data=f"{menu_callback_prefix}:cancel"),
        ],
    ])


def help_section_text(section_key: str) -> str | None:
    section = HELP_SECTIONS.get(section_key)
    return section[1] if section is not None else None


def build_group_sections_keyboard(menu_callback_prefix: str, include_g25: bool = False) -> InlineKeyboardMarkup:
    rows = [[
        InlineKeyboardButton(BOTTOM_BUTTON_LOOKUP, callback_data=f"{menu_callback_prefix}:lookup"),
        InlineKeyboardButton(BOTTOM_BUTTON_STATS, callback_data=f"{menu_callback_prefix}:stats"),
    ]]
    rows.extend([
        [
            InlineKeyboardButton(BOTTOM_BUTTON_MY_DNA, callback_data=f"{menu_callback_prefix}:my_data"),
            InlineKeyboardButton(BOTTOM_BUTTON_DNA_LAB, callback_data=f"{menu_callback_prefix}:lab"),
        ],
        [
            InlineKeyboardButton(BOTTOM_BUTTON_SUPPORT, callback_data=f"{menu_callback_prefix}:support"),
            InlineKeyboardButton(BOTTOM_BUTTON_SETTINGS, callback_data=f"{menu_callback_prefix}:settings"),
        ],
        [InlineKeyboardButton(BOTTOM_BUTTON_CANCEL, callback_data=f"{menu_callback_prefix}:cancel")],
    ])
    return InlineKeyboardMarkup(rows)


def build_laboratory_inline_keyboard(lab_callback_prefix: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(BOTTOM_BUTTON_TRAITS, callback_data=f"{lab_callback_prefix}:traits")],
        [InlineKeyboardButton(LAB_BUTTON_COORDINATES, callback_data=f"{lab_callback_prefix}:coordinates")],
        [InlineKeyboardButton(BOTTOM_BUTTON_VAHADUO, callback_data=f"{lab_callback_prefix}:vahaduo")],
        [InlineKeyboardButton(BOTTOM_BUTTON_MATCHING, callback_data=f"{lab_callback_prefix}:matching")],
        [InlineKeyboardButton(LAB_BUTTON_ADMIXTURE, callback_data=f"{lab_callback_prefix}:admixture")],
        [InlineKeyboardButton(LAB_BUTTON_MODELING, callback_data=f"{lab_callback_prefix}:modeling")],
        [InlineKeyboardButton(MORE_BUTTON_HAPLOGROUPS, callback_data=f"{lab_callback_prefix}:haplogroups")],
        [InlineKeyboardButton(BOTTOM_BUTTON_CANCEL, callback_data=f"{lab_callback_prefix}:cancel")],
    ])


def build_my_dna_inline_keyboard(my_dna_callback_prefix: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(MY_DNA_BUTTON_SAMPLES, callback_data="my_data:samples_view")],
        [InlineKeyboardButton(MY_DNA_BUTTON_G25_PROFILES, callback_data="my_data:coordinates_view")],
        [InlineKeyboardButton(MY_DNA_BUTTON_REPORTS, callback_data="reports:root")],
        [InlineKeyboardButton(MY_DNA_BUTTON_ADD_RAW, callback_data="my_data:raw_files_upload:root")],
        [InlineKeyboardButton(MY_DNA_BUTTON_GET_G25_FROM_RAW, callback_data=f"{my_dna_callback_prefix}:get_g25_raw")],
    ])


def build_my_dna_add_data_keyboard(my_dna_callback_prefix: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(MY_DNA_BUTTON_ADD_RAW, callback_data="my_data:raw_files_upload:add_data")],
        [InlineKeyboardButton(MY_DNA_BUTTON_GET_G25_FROM_RAW, callback_data=f"{my_dna_callback_prefix}:get_g25_raw")],
        [InlineKeyboardButton(MY_DNA_BUTTON_ADD_G25_MANUAL, callback_data="my_data:coordinates_add_type:g25:add_data")],
        [InlineKeyboardButton(MY_DNA_BUTTON_ADD_HAPLOGROUP, callback_data="haplogroups:manual_add_data")],
        [
            InlineKeyboardButton(MY_DNA_BUTTON_BACK, callback_data=f"{my_dna_callback_prefix}:root"),
            InlineKeyboardButton(BOTTOM_BUTTON_CANCEL, callback_data="my_data:cancel"),
        ],
    ])


def build_help_inline_keyboard(help_callback_prefix: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 Быстрый старт", callback_data=f"{help_callback_prefix}:quick_start")],
        [InlineKeyboardButton("🔎 Поиск по фамилиям", callback_data=f"{help_callback_prefix}:surname_search")],
        [InlineKeyboardButton("📊 Аналитика KBDNA", callback_data=f"{help_callback_prefix}:analytics")],
        [InlineKeyboardButton("🧬 Данные: raw, G25, SNP", callback_data=f"{help_callback_prefix}:data_formats")],
        [InlineKeyboardButton("🧪 Разделы DNA Lab", callback_data=f"{help_callback_prefix}:dna_lab_sections")],
        [InlineKeyboardButton("🧱 AdmixLab / qpAdm", callback_data=f"{help_callback_prefix}:admixlab")],
        [InlineKeyboardButton("📖 Термины DNA", callback_data=f"{help_callback_prefix}:terms")],
        [InlineKeyboardButton("🛡 Ограничения", callback_data=f"{help_callback_prefix}:limitations")],
        [InlineKeyboardButton("📚 КБ словарь", callback_data=f"{help_callback_prefix}:dictionary")],
        [
            InlineKeyboardButton(MY_DNA_BUTTON_BACK, callback_data=f"{help_callback_prefix}:back"),
            InlineKeyboardButton(BOTTOM_BUTTON_CANCEL, callback_data=f"{help_callback_prefix}:cancel"),
        ],
    ])


def build_bottom_menu_keyboard(include_requests: bool = False, include_g25: bool = False) -> ReplyKeyboardMarkup:
    rows = [
        [BOTTOM_BUTTON_LOOKUP, BOTTOM_BUTTON_STATS],
        [BOTTOM_BUTTON_MY_DNA, BOTTOM_BUTTON_DNA_LAB],
        [BOTTOM_BUTTON_SUPPORT, BOTTOM_BUTTON_SETTINGS],
    ]

    return ReplyKeyboardMarkup(
        rows,
        resize_keyboard=True,
        is_persistent=True,
    )


def build_stats_root_keyboard(haplo_callback_prefix: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Отмена", callback_data=f"{haplo_callback_prefix}:cancel"),
        ],
    ])
