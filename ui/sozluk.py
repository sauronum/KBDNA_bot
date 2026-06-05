from __future__ import annotations

import html

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from features.sozluk import SozlukClient


def sozluk_direction_label(direction: int) -> str:
    return SozlukClient.DIRECTIONS.get(direction, "Все направления")


def sozluk_source_label(direction: int) -> str:
    if direction == 1:
        return (
            "Русско-карачаево-балкарский словарь : около 35000 слов / "
            "Под ред. Х. И. Суюнчева и И. Х. Урусбиева. - М. : Сов. энциклопедия, 1965"
        )
    if direction == 2:
        return (
            "Карачаево-балкарско-русский словарь : ок. 30000 слов / "
            "С. А. Гочияева, Х. И. Суюнчев; под ред. Э. Р. Тенишева, Х. И. Суюнчева. - М. : Рус. яз., 1989"
        )
    return "Словарь Эльбрусоида."


def format_sozluk_results(query: str, items: list[dict[str, object]], *, limit: int = 8) -> str:
    safe_query = html.escape(query.upper())
    if not items:
        return f"<b>{safe_query}</b>\n<i>Точного совпадения нет.</i>\n\nПопробуйте другую форму слова."

    blocks: list[str] = []
    visible = items[:limit]
    source_by_direction: dict[int, str] = {}
    for index, item in enumerate(visible, start=1):
        word = html.escape(str(item.get("word") or ""))
        desc = html.escape(str(item.get("desc") or ""))
        try:
            direction = int(item.get("direction") or 0)
        except (TypeError, ValueError):
            direction = 0
        direction_label = html.escape(sozluk_direction_label(direction))
        source_by_direction[direction] = sozluk_source_label(direction)
        title = f"<b>{word.upper()}</b>" if len(visible) == 1 else f"{index}. <b>{word.upper()}</b>"
        blocks.append(f"{title}\n<i>({direction_label})</i>\n{desc}")
    if len(items) > len(visible):
        blocks.append(f"... и еще {len(items) - len(visible)}")
    sources = [html.escape(value) for _direction, value in sorted(source_by_direction.items())]
    if sources:
        blocks.append("<i>" + "\n\n".join(sources) + "</i>")
    return "\n\n".join(blocks)


def sozluk_prompt_text() -> str:
    return "📚 <b>Словарь</b>\n\nВведите слово.\n\nБыстрый поиск: <code>/s слово</code>"


def build_sozluk_prompt_keyboard(menu_callback_prefix: str, *, back_action: str = "root") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Назад", callback_data=f"{menu_callback_prefix}:{back_action}"),
            InlineKeyboardButton("Отмена", callback_data=f"{menu_callback_prefix}:cancel"),
        ],
    ])
