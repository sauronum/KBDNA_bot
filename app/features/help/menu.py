from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.i18n import get_user_language, t
from app.main_menu import ensure_active_main_menu


HELP_CALLBACK_PREFIX = "help"


HELP_SECTIONS: dict[str, tuple[str, str]] = {
    "start": (
        "🚀 Быстрый старт",
        (
            "🚀 Быстрый старт\n\n"
            "DNA Lab устроен вокруг одной простой идеи: сначала вы сохраняете свои данные в 📁 My DNA, "
            "а затем используете их в расчетных разделах.\n\n"
            "1. Откройте 📁 My DNA.\n"
            "2. Загрузите raw-файл и создайте sample.\n"
            "3. Получите или добавьте G25-профиль для sample.\n"
            "4. Используйте sample в Coordinate spaces, Vahaduo Lab, Matching, Traits и других разделах.\n\n"
            "Если нужно быстро посчитать чужие или временные координаты, их не обязательно сохранять: "
            "в 🧪 Vahaduo Lab можно вставить target текстом или загрузить файлом и сразу получить результат."
        ),
    ),
    "mydna": (
        "📁 My DNA",
        (
            "📁 My DNA\n\n"
            "Это личная библиотека пользователя. Здесь хранятся sample, raw-файлы, G25-профили "
            "и сохраненные результаты расчетов.\n\n"
            "Sample - основная рабочая карточка. Обычно один sample соответствует одному человеку или одному образцу. "
            "К sample можно привязать исходный raw-файл, координаты и отчеты.\n\n"
            "Отдельные G25-профили тоже можно хранить без создания sample. Это удобно для временных target, "
            "сравнения родственников, публичных координат или данных, которые не хочется оформлять как полноценную карточку.\n\n"
            "Практическое правило: если данные ваши и будут использоваться регулярно, создавайте sample. "
            "Если координаты нужны для одного-двух расчетов, можно держать их как G25-профили или не сохранять вовсе."
        ),
    ),
    "vahaduo": (
        "🧪 Vahaduo Lab",
        (
            "🧪 Vahaduo Lab\n\n"
            "Раздел для расчетов в стиле Vahaduo: Distance, Single и Multi.\n\n"
            "Distance ищет ближайшие популяции к target в выбранной базе. Сейчас доступны modern и ancestry.\n\n"
            "Single считает один target по выбранному source-набору и показывает доли компонентов.\n\n"
            "Multi позволяет прогнать несколько target по одному source-набору и получить сводную визуализацию.\n\n"
            "Target можно выбрать из 📁 My DNA: отдельно из Samples или из G25-профилей. "
            "Также можно вставить координаты текстом или загрузить файл без сохранения.\n\n"
            "Source-наборы в Vahaduo отделены от My DNA. Это reference panels, а не личные данные пользователя."
        ),
    ),
    "coordinate": (
        "🧭 Coordinate spaces",
        (
            "🧭 Coordinate spaces\n\n"
            "Раздел оставлен как набор готовых региональных пространств. "
            "Он нужен, когда важно быстро увидеть положение sample относительно выбранного региона, "
            "кластера или списка популяций.\n\n"
            "Типичный сценарий: выбрать ready-made регион, выбрать sample с G25 и получить визуализацию."
        ),
    ),
    "admixture": (
        "🧬 Admixture / AdmixLab",
        (
            "🧬 Admixture и 🧱 AdmixLab\n\n"
            "Admixture - раздел для компонентных профилей и интерпретации долей. "
            "Он полезен, когда нужно быстро получить структурированное описание ancestry-профиля, включая K36 и raw calculators.\n\n"
            "AdmixLab - слой для формальных моделей: qpAdm, qpWave, sources и outgroups. "
            "Его лучше использовать тогда, когда важна проверка конкретной гипотезы происхождения.\n\n"
            "Главная разница: Admixture отвечает на вопрос 'из чего состоит профиль по выбранной схеме', "
            "а AdmixLab - 'проходит ли формальная модель для этого sample'."
        ),
    ),
    "matching": (
        "🧩 Matching",
        (
            "🧩 Matching\n\n"
            "Matching предназначен для сравнения sample между собой. "
            "Раздел полезен, когда нужно увидеть близость, похожие профили, возможные кластеры или повторяющиеся паттерны.\n\n"
            "Лучший вход для Matching - сохраненные sample с координатами в 📁 My DNA. "
            "Так результаты можно связать с конкретными карточками и потом открыть их из Reports.\n\n"
            "Matching не заменяет генеалогическую проверку родства, но помогает быстро находить похожие autosomal-профили."
        ),
    ),
    "traits": (
        "🧾 Traits / Haplogroups",
        (
            "🧾 Traits и 🌿 Haplogroups\n\n"
            "Traits - раздел для отчетов по признакам. Он работает вокруг сохраненных sample и raw/координат, "
            "если соответствующие данные доступны.\n\n"
            "Haplogroups - отдельный блок для Y/mtDNA-направления и связанных справочных отчетов. "
            "Его результаты также логично хранить рядом с sample.\n\n"
            "Эти разделы лучше рассматривать как справочно-аналитические. Они помогают организовать данные, "
            "но не должны использоваться как медицинское, юридическое или окончательное генеалогическое заключение."
        ),
    ),
    "reports": (
        "📊 Reports",
        (
            "📊 Reports\n\n"
            "Reports - общий вход к сохраненным результатам. Раздел показывает samples, у которых уже есть отчеты, "
            "и открывает карточку Reports внутри конкретного sample.\n\n"
            "Сюда попадают сохраненные результаты из Coordinate spaces, Admixture, Matching, Traits и Haplogroups. "
            "Если расчет был просто просмотрен и не сохранен, он не появится в Reports.\n\n"
            "Практическое правило: сохраняйте только те результаты, к которым хотите вернуться позже."
        ),
    ),
    "privacy": (
        "🔒 Данные и приватность",
        (
            "🔒 Данные и приватность\n\n"
            "Raw-файлы и координаты - чувствительные генетические данные. Загружайте только те файлы, "
            "которые вы имеете право обрабатывать.\n\n"
            "Рекомендуется не пересылать чужие raw-файлы без согласия владельца. "
            "Для разовых расчетов используйте режим без сохранения, особенно если координаты не должны оставаться в библиотеке.\n\n"
            "Удаление sample удаляет карточку sample, но отдельные связанные данные могут иметь собственные записи. "
            "Проверяйте 📁 My DNA, если нужно полностью очистить библиотеку.\n\n"
            "Результаты DNA Lab являются аналитическими и справочными. Они зависят от выбранных reference panels, "
            "качества исходных данных и методики расчета."
        ),
    ),
}


HELP_SECTIONS_EN: dict[str, tuple[str, str]] = {
    "start": (
        "🚀 Quick Start",
        (
            "🚀 Quick Start\n\n"
            "DNA Lab is built around one flow: save your data in 📁 My DNA, then use it in analysis sections.\n\n"
            "1. Open 📁 My DNA.\n"
            "2. Upload a raw file and create a sample.\n"
            "3. Add or generate a G25 profile for the sample.\n"
            "4. Use the sample in Coordinate spaces, Vahaduo Lab, Matching, Traits, and other sections.\n\n"
            "For temporary coordinates, use 🧪 Vahaduo Lab without saving a new sample."
        ),
    ),
    "mydna": (
        "📁 My DNA",
        (
            "📁 My DNA\n\n"
            "This is the user's personal library. It stores samples, raw files, G25 profiles, "
            "and saved calculation results.\n\n"
            "A sample is the main working card. Usually one sample represents one person or one specimen. "
            "You can attach a source raw file, coordinates, and reports to a sample.\n\n"
            "Separate G25 profiles can also be stored without creating a sample. This is useful for temporary targets, "
            "relative comparisons, public coordinates, or data you do not want to turn into a full card.\n\n"
            "Practical rule: if the data is yours and you will use it regularly, create a sample. "
            "If coordinates are needed for one or two calculations, keep them as G25 profiles or do not save them."
        ),
    ),
    "vahaduo": (
        "🧪 Vahaduo Lab",
        (
            "🧪 Vahaduo Lab\n\n"
            "A section for Vahaduo-style calculations: Distance, Single, and Multi.\n\n"
            "Distance finds the closest populations to a target in the selected database. Modern and ancestry sets are available.\n\n"
            "Single models one target against the selected source set and shows component shares.\n\n"
            "Multi runs several targets against one source set and produces a summary visualization.\n\n"
            "Targets can be selected from 📁 My DNA: from Samples or from G25 profiles. "
            "You can also paste coordinates as text or upload a file without saving it.\n\n"
            "Vahaduo source sets are separate from My DNA. They are reference panels, not personal user data."
        ),
    ),
    "coordinate": (
        "🧭 Coordinate spaces",
        (
            "🧭 Coordinate spaces\n\n"
            "A set of ready-made regional coordinate spaces. It is useful when you want a quick view of where a sample sits "
            "relative to a selected region, cluster, or population list.\n\n"
            "Typical flow: choose a ready-made region, choose a sample or G25 profile, and get a visualization."
        ),
    ),
    "admixture": (
        "🧬 Admixture / AdmixLab",
        (
            "🧬 Admixture and 🧱 AdmixLab\n\n"
            "Admixture is for component profiles and interpretation of component shares. "
            "It is useful when you want a structured ancestry-profile summary, including K36 and raw calculators.\n\n"
            "AdmixLab is for formal models: qpAdm, qpWave, sources, and outgroups. "
            "Use it when the question is testing a specific ancestry hypothesis.\n\n"
            "The simple difference: Admixture answers 'what does the profile contain under this scheme', "
            "while AdmixLab answers 'does the formal model pass for this sample'."
        ),
    ),
    "matching": (
        "🧩 Matching",
        (
            "🧩 Matching\n\n"
            "Matching compares samples with each other. It is useful when you want to see similarity, related-looking profiles, "
            "possible clusters, or repeated patterns.\n\n"
            "The best input for Matching is saved samples with coordinates in 📁 My DNA. "
            "That way results can be tied to concrete cards and opened later from Reports.\n\n"
            "Matching does not replace genealogical relationship verification, but it helps quickly find similar autosomal profiles."
        ),
    ),
    "traits": (
        "🧾 Traits / Haplogroups",
        (
            "🧾 Traits and 🌿 Haplogroups\n\n"
            "Traits is for trait reports. It works around saved samples and raw files or coordinates when the required data is available.\n\n"
            "Haplogroups is a separate block for Y-DNA/mtDNA directions and related reference-style reports. "
            "Its results also belong next to the relevant sample.\n\n"
            "Treat these sections as analytical references. They help organize and interpret data, "
            "but should not be used as medical, legal, or final genealogical conclusions."
        ),
    ),
    "reports": (
        "📊 Reports",
        (
            "📊 Reports\n\n"
            "Reports is the shared entry point for saved results. It shows samples that already have reports "
            "and opens the Reports card inside a specific sample.\n\n"
            "Saved results from Coordinate spaces, Admixture, Matching, Traits, and Haplogroups appear here. "
            "If a calculation was only previewed and not saved, it will not appear in Reports.\n\n"
            "Practical rule: save only the results you want to return to later."
        ),
    ),
    "privacy": (
        "🔒 Data & Privacy",
        (
            "🔒 Data & Privacy\n\n"
            "Raw files and coordinates are sensitive genetic data. Upload only data you are allowed to process.\n\n"
            "Avoid forwarding other people's raw files without their consent. "
            "For one-off calculations, use an unsaved flow, especially when coordinates should not remain in the library.\n\n"
            "Deleting a sample deletes the sample card, but some separately stored linked data may have its own records. "
            "Check 📁 My DNA if you need to fully clean the library.\n\n"
            "DNA Lab results are analytical references. They depend on selected reference panels, input quality, and calculation method."
        ),
    ),
}


def _help_sections(lang: str) -> dict[str, tuple[str, str]]:
    return HELP_SECTIONS_EN if lang == "en" else HELP_SECTIONS


def help_text(lang: str = "ru") -> str:
    if lang == "en":
        return (
            "📖 Help\n\n"
            "DNA Lab is a workspace for storing DNA data and running calculations around samples, coordinates, and reference panels.\n\n"
            "Main sections:\n"
            "📁 My DNA - samples, raw files, G25 profiles, and reports.\n"
            "🧭 Coordinate spaces - ready-made regional coordinate views.\n"
            "🧪 Vahaduo Lab - Distance, Single, Multi, and G25 calculations.\n"
            "🧬 Admixture - component profiles.\n"
            "🧱 AdmixLab - formal qpAdm/qpWave workflows.\n"
            "🧩 Matching - sample-to-sample comparison.\n"
            "🧾 Traits - trait reports.\n"
            "🌿 Haplogroups - Y-DNA, mtDNA, and related records.\n"
            "📊 Reports - saved reports.\n\n"
            "Choose a topic below."
        )
    return (
        "📖 Справка\n\n"
        "DNA Lab - рабочая среда для хранения DNA-данных и запуска расчетов по sample, координатам и reference panels.\n\n"
        "Основные разделы:\n"
        "📁 My DNA - личная библиотека sample, raw-файлов, G25-профилей и отчетов.\n"
        "🧭 Coordinate spaces - готовые региональные coordinate views.\n"
        "🧪 Vahaduo Lab - Distance, Single, Multi и быстрые расчеты по G25.\n"
        "🧬 Admixture - компонентные профили.\n"
        "🧱 AdmixLab - формальные qpAdm/qpWave модели.\n"
        "🧩 Matching - сравнение sample между собой.\n"
        "🧾 Traits - отчеты по признакам.\n"
        "🌿 Haplogroups - Y/mtDNA и связанные справочные блоки.\n\n"
        "📊 Reports - общий вход к сохраненным отчетам.\n"
        "\n"
        "Выберите тему ниже, чтобы открыть подробное описание."
    )


def build_help_keyboard(lang: str = "ru") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(label, callback_data=f"{HELP_CALLBACK_PREFIX}:{key}")]
            for key, (label, _) in _help_sections(lang).items()
        ]
        + [[InlineKeyboardButton(t("nav.back", lang), callback_data="main:root"), InlineKeyboardButton(t("nav.cancel", lang), callback_data="main:cancel")]]
    )


def build_help_section_keyboard(lang: str = "ru") -> InlineKeyboardMarkup:
    topics_label = "Help topics" if lang == "en" else "К разделам справки"
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(topics_label, callback_data=f"{HELP_CALLBACK_PREFIX}:root")],
            [InlineKeyboardButton(t("nav.main_menu", lang), callback_data="main:root"), InlineKeyboardButton(t("nav.cancel", lang), callback_data="main:cancel")],
        ]
    )


async def show_help_menu(message, context: ContextTypes.DEFAULT_TYPE, user_id: int, *, edit_existing: bool = False) -> None:
    lang = get_user_language(context, user_id)
    if edit_existing:
        await message.edit_text(help_text(lang), reply_markup=build_help_keyboard(lang))
    else:
        await message.reply_text(help_text(lang), reply_markup=build_help_keyboard(lang), do_quote=False)


async def help_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None or query.message is None:
        return
    if not query.data.startswith(f"{HELP_CALLBACK_PREFIX}:"):
        return
    if not await ensure_active_main_menu(update, context):
        return
    if update.effective_user is None:
        return

    await query.answer()
    user_id = int(update.effective_user.id)
    lang = get_user_language(context, user_id)
    action = query.data.split(":", 1)[1]
    if action == "root":
        await show_help_menu(query.message, context, user_id, edit_existing=True)
        return
    section = _help_sections(lang).get(action)
    if section is None:
        await query.answer("Help section not found." if lang == "en" else "Раздел справки не найден.", show_alert=True)
        return
    _, text = section
    await query.message.edit_text(text, reply_markup=build_help_section_keyboard(lang))
