from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.i18n import get_user_language, t
from app.main_menu import ensure_active_main_menu


MODELING_CALLBACK_PREFIX = "modeling"

_PLACEHOLDERS: dict[str, tuple[str, str, str, str]] = {
    "qpadm": (
        "🏛 qpAdm",
        "Формальная проверка модели через target, sources и outgroups.",
        "Функция пока не подключена.",
        "Formal model test via target, sources, and outgroups.",
    ),
    "qpwave": (
        "〰️ qpWave",
        "Проверка числа потоков происхождения между группами.",
        "Функция пока не подключена.",
        "Testing the number of ancestry streams between groups.",
    ),
    "source_sets": (
        "📚 Source sets",
        "Наборы sources и outgroups для формальных моделей.",
        "Функция пока не подключена.",
        "Source and outgroup sets for formal models.",
    ),
    "saved": (
        "💾 Saved models",
        "Сохранённые результаты AdmixLab.",
        "Пока нет сохранённых моделей.",
        "Saved AdmixLab results.",
    ),
    "source_fitting": (
        "📚 Ready models",
        "Готовые G25-модели теперь находятся в Vahaduo Lab.",
        "Откройте Vahaduo Lab → Ready models.",
        "Ready G25 models now live in Vahaduo Lab.",
    ),
}


def modeling_text(lang: str = "ru") -> str:
    if lang == "en":
        return "\n".join(
            [
                "<b>🧱 AdmixLab</b>",
                "",
                "Formal models: qpAdm, qpWave, sources, and outgroups.",
            ]
        )
    return "\n".join(
        [
            "<b>🧱 AdmixLab</b>",
            "",
            "Формальные модели: qpAdm, qpWave, sources и outgroups.",
        ]
    )


def modeling_placeholder_text(action: str, lang: str = "ru") -> str:
    title, ru_description, ru_status, en_description = _PLACEHOLDERS.get(action, _PLACEHOLDERS["qpadm"])
    description = en_description if lang == "en" else ru_description
    status = "This feature is not connected yet." if lang == "en" and action != "source_fitting" else ru_status
    return "\n".join(
        [
            f"<b>{title}</b>",
            "",
            description,
            "",
            status,
        ]
    )


def source_sets_text(source_sets: object | None = None, lang: str = "ru") -> str:
    return "\n".join(
        [
            "<b>📚 Source sets</b>",
            "",
            "Наборы sources и outgroups для формальных моделей.",
            "",
            "Функция пока не подключена.",
        ]
    )


def build_modeling_keyboard(lang: str = "ru") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🏛 qpAdm", callback_data=f"{MODELING_CALLBACK_PREFIX}:qpadm")],
            [InlineKeyboardButton("〰️ qpWave", callback_data=f"{MODELING_CALLBACK_PREFIX}:qpwave")],
            [InlineKeyboardButton("📚 Source sets", callback_data=f"{MODELING_CALLBACK_PREFIX}:source_sets")],
            [InlineKeyboardButton("💾 Saved models", callback_data=f"{MODELING_CALLBACK_PREFIX}:saved")],
            [
                InlineKeyboardButton(_back_label(lang), callback_data="main:root"),
                InlineKeyboardButton(t("nav.cancel", lang), callback_data="main:cancel"),
            ],
        ]
    )


def build_modeling_placeholder_keyboard(lang: str = "ru") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([_footer_row(f"{MODELING_CALLBACK_PREFIX}:root", lang)])


def build_source_sets_keyboard(source_sets: object | None = None, lang: str = "ru") -> InlineKeyboardMarkup:
    return build_modeling_placeholder_keyboard(lang)


def _back_label(lang: str) -> str:
    return "⬅️ Back" if lang == "en" else "⬅️ Назад"


def _footer_row(back_callback: str, lang: str = "ru") -> list[InlineKeyboardButton]:
    return [
        InlineKeyboardButton(_back_label(lang), callback_data=back_callback),
        InlineKeyboardButton(t("nav.cancel", lang), callback_data="main:cancel"),
    ]


async def show_modeling_menu(message, *, edit_existing: bool = False, lang: str = "ru"):
    markup = build_modeling_keyboard(lang)
    if edit_existing:
        await message.edit_text(modeling_text(lang), reply_markup=markup, parse_mode="HTML")
        return message
    return await message.reply_text(modeling_text(lang), reply_markup=markup, parse_mode="HTML", do_quote=False)


async def show_source_sets_menu(message, *, edit_existing: bool = True, lang: str = "ru") -> None:
    await _show_message(message, source_sets_text(lang=lang), build_source_sets_keyboard(lang=lang), edit_existing=edit_existing)


async def _show_modeling_placeholder(message, action: str, *, edit_existing: bool = True, lang: str = "ru") -> None:
    await _show_message(
        message,
        modeling_placeholder_text(action, lang),
        build_modeling_placeholder_keyboard(lang),
        edit_existing=edit_existing,
    )


async def _show_message(message, text: str, reply_markup: InlineKeyboardMarkup, *, edit_existing: bool = True) -> None:
    if edit_existing:
        await message.edit_text(text, reply_markup=reply_markup, parse_mode="HTML")
        return
    await message.reply_text(text, reply_markup=reply_markup, parse_mode="HTML", do_quote=False)


async def modeling_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None or query.message is None:
        return
    if not query.data.startswith(f"{MODELING_CALLBACK_PREFIX}:"):
        return
    if not await ensure_active_main_menu(update, context):
        return

    await query.answer()
    parts = query.data.split(":")
    action = parts[1] if len(parts) > 1 and parts[1] else "root"
    user_id = int(update.effective_user.id) if update.effective_user is not None else None
    lang = get_user_language(context, user_id)

    if action == "root":
        await show_modeling_menu(query.message, edit_existing=True, lang=lang)
        return
    if action == "source_sets":
        await show_source_sets_menu(query.message, edit_existing=True, lang=lang)
        return
    if action == "source_fitting" or action.startswith("fit_") or action == "ss":
        await _show_modeling_placeholder(query.message, "source_fitting", edit_existing=True, lang=lang)
        return
    if action in _PLACEHOLDERS:
        await _show_modeling_placeholder(query.message, action, edit_existing=True, lang=lang)
