from __future__ import annotations

import html
import logging
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from app.i18n import t
from app.features.my_data.storage import CoordinateAsset, MyDataStore

from .ready_models_rendering import build_rendered_source_fit_card
from .ready_models_runtime import SourceFitResult, format_fit_quality, run_source_fitting
from .ready_model_sets import ReadyModelSet, get_source_set, list_source_sets, source_set_is_runnable


READY_MODELS_FLOW_STORE_KEY = "vahaduo_ready_models_flow_store"
VAHADUO_CALLBACK_PREFIX = "vahaduo"
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReadyModelScreen:
    text: str
    reply_markup: InlineKeyboardMarkup


@dataclass(frozen=True)
class ReadyModelTarget:
    coordinate_id: str
    title: str
    g25_line: str


class ReadyModelsFlowStore:
    def __init__(self) -> None:
        self._payloads: dict[str, dict[str, object]] = {}

    def create(self, *, user_id: int, payload: dict[str, object]) -> str:
        token = uuid4().hex[:8]
        self._payloads[token] = {"user_id": int(user_id), **payload}
        return token

    def get(self, token: str, user_id: int) -> dict[str, object] | None:
        payload = self._payloads.get(token)
        if payload is None or int(payload.get("user_id", -1)) != int(user_id):
            return None
        return dict(payload)

    def update(self, token: str, user_id: int, payload: dict[str, object]) -> dict[str, object] | None:
        current = self.get(token, user_id)
        if current is None:
            return None
        current.update(payload)
        self._payloads[token] = {"user_id": int(user_id), **current}
        return dict(self._payloads[token])


def flow_store(context: ContextTypes.DEFAULT_TYPE) -> ReadyModelsFlowStore:
    store = context.application.bot_data.get(READY_MODELS_FLOW_STORE_KEY)
    if isinstance(store, ReadyModelsFlowStore):
        return store
    store = ReadyModelsFlowStore()
    context.application.bot_data[READY_MODELS_FLOW_STORE_KEY] = store
    return store


def ready_models_targets_text(targets: list[ReadyModelTarget], lang: str = "ru") -> str:
    lines = [
        "<b>📚 Ready models</b>",
        "",
        "Готовые G25-модели источников.",
        "",
        "Выберите G25-профиль.",
    ]
    if not targets:
        lines.extend(["", "Нет сохранённых G25-профилей."])
    return "\n".join(lines)


def build_ready_models_targets_keyboard(targets: list[ReadyModelTarget], lang: str = "ru") -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(f"{index}. {target.title}", callback_data=f"{VAHADUO_CALLBACK_PREFIX}:ready_model_target:{target.coordinate_id}")]
        for index, target in enumerate(targets, start=1)
    ]
    rows.append(_footer_row(f"{VAHADUO_CALLBACK_PREFIX}:vahaduo_full", lang))
    return InlineKeyboardMarkup(rows)


def ready_models_sets_text(profile_name: str, source_sets: list[ReadyModelSet], lang: str = "ru") -> str:
    lines = [
        "<b>📚 Ready models</b>",
        "",
        f"G25-профиль: {html.escape(profile_name)}",
        "",
        "Выберите модель.",
    ]
    if not source_sets:
        lines.extend(["", "Каталог ready models пока пуст."])
    return "\n".join(lines)


def build_ready_models_sets_keyboard(source_sets: list[ReadyModelSet], token: str, lang: str = "ru") -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(source_set.title, callback_data=f"{VAHADUO_CALLBACK_PREFIX}:ready_model_set:{token}:{source_set.id}")]
        for source_set in source_sets
    ]
    rows.append(_footer_row(f"{VAHADUO_CALLBACK_PREFIX}:ready_models", lang))
    return InlineKeyboardMarkup(rows)


def ready_model_confirmation_text(profile_name: str, source_set: ReadyModelSet, lang: str = "ru") -> str:
    lines = [
        "<b>📚 Ready model</b>",
        "",
        f"G25-профиль: {html.escape(profile_name)}",
        f"Модель: {html.escape(source_set.short_title)}",
        "",
        html.escape(source_set.description),
        "",
        "Источники:",
    ]
    lines.extend(f"{html.escape(source.emoji)} {html.escape(source.label)}" for source in source_set.sources)
    lines.extend(
        [
            "",
            "Это G25-fit модель, не qpAdm.",
            "Компоненты являются proxy-источниками.",
        ]
    )
    return "\n".join(lines)


def build_ready_model_confirmation_keyboard(token: str, lang: str = "ru") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("▶️ Запустить модель", callback_data=f"{VAHADUO_CALLBACK_PREFIX}:ready_model_run:{token}")],
            _footer_row(f"{VAHADUO_CALLBACK_PREFIX}:ready_model_sets:{token}", lang),
        ]
    )


def ready_model_result_text(result: SourceFitResult, source_set: ReadyModelSet, lang: str = "ru") -> str:
    lines = [
        "<b>📚 Ready models</b>",
        "",
        f"G25-профиль: {html.escape(result.target_name)}",
        f"Модель: {html.escape(result.source_set_title)}",
        "",
    ]
    if result.status == "ok":
        lines.extend(
            [
                f"Fit: {format_fit_quality(result.distance)}",
                f"Distance: {float(result.distance or 0.0):.4f}",
                "",
            ]
        )
        lines.extend(
            f"{html.escape(component.emoji)} {html.escape(component.label)} — {component.percent:.1f}%"
            for component in result.components
        )
        lines.extend(["", "Это G25-fit модель, не qpAdm.", "Компоненты являются proxy-источниками."])
        return "\n".join(lines)

    lines.extend(["Не удалось запустить модель.", ""])
    if result.status == "source_missing":
        lines.append("Не найдены источники:")
        lines.extend(f"- {html.escape(source_name)}" for source_name in result.missing_sources)
        lines.append("")
    elif result.status == "draft":
        lines.extend(["Эта модель пока в черновике.", ""])
    elif result.message:
        lines.extend([html.escape(result.message), ""])
    lines.append("Это G25-fit модель, не qpAdm.")
    return "\n".join(lines)


def build_ready_model_result_keyboard(token: str, lang: str = "ru") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🔁 Проверить другую модель", callback_data=f"{VAHADUO_CALLBACK_PREFIX}:ready_model_result_models:{token}")],
            _footer_row(f"{VAHADUO_CALLBACK_PREFIX}:ready_model_result_back:{token}", lang),
        ]
    )


def get_ready_model_confirmation_screen(context: ContextTypes.DEFAULT_TYPE, user_id: int, token: str, lang: str = "ru") -> ReadyModelScreen:
    flow = flow_store(context).get(token, user_id)
    if flow is None:
        return ReadyModelScreen(
            "<b>📚 Ready models</b>\n\nСессия устарела. Откройте Ready models заново.",
            _back_to_ready_models_keyboard(lang),
        )
    target = _get_g25_target(context, user_id, str(flow.get("coordinate_id") or ""))
    source_set = get_source_set(str(flow.get("source_set_id") or ""))
    if target is None or source_set is None:
        return ReadyModelScreen(
            "<b>📚 Ready models</b>\n\nНе удалось открыть выбранную модель.",
            _back_to_ready_models_keyboard(lang),
        )
    return ReadyModelScreen(
        ready_model_confirmation_text(target.title, source_set, lang),
        build_ready_model_confirmation_keyboard(token, lang),
    )


def get_ready_models_sets_screen(context: ContextTypes.DEFAULT_TYPE, user_id: int, token: str, lang: str = "ru") -> ReadyModelScreen:
    flow = flow_store(context).get(token, user_id)
    target = _get_g25_target(context, user_id, str((flow or {}).get("coordinate_id") or "")) if flow else None
    if target is None:
        targets = _list_g25_targets(context, user_id)
        return ReadyModelScreen(
            ready_models_targets_text(targets, lang),
            build_ready_models_targets_keyboard(targets, lang),
        )
    source_sets = list_source_sets()
    return ReadyModelScreen(
        ready_models_sets_text(target.title, source_sets, lang),
        build_ready_models_sets_keyboard(source_sets, token, lang),
    )


async def show_ready_models_targets_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    edit_existing: bool = True,
    lang: str = "ru",
) -> None:
    targets = _list_g25_targets(context, user_id)
    await _show_message(
        message,
        ready_models_targets_text(targets, lang),
        build_ready_models_targets_keyboard(targets, lang),
        edit_existing=edit_existing,
    )


async def show_ready_models_sets_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    coordinate_id: str,
    *,
    edit_existing: bool = True,
    lang: str = "ru",
) -> None:
    target = _get_g25_target(context, user_id, coordinate_id)
    if target is None:
        await _show_message(
            message,
            "<b>📚 Ready models</b>\n\nG25-профиль не найден.",
            _back_to_ready_models_keyboard(lang),
            edit_existing=edit_existing,
        )
        return
    token = flow_store(context).create(user_id=user_id, payload={"coordinate_id": coordinate_id})
    await _show_ready_models_sets_by_token(message, context, user_id, token, edit_existing=edit_existing, lang=lang)


async def show_ready_models_sets_by_token(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    token: str,
    *,
    edit_existing: bool = True,
    lang: str = "ru",
) -> None:
    await _show_ready_models_sets_by_token(message, context, user_id, token, edit_existing=edit_existing, lang=lang)


async def _show_ready_models_sets_by_token(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    token: str,
    *,
    edit_existing: bool = True,
    lang: str = "ru",
) -> None:
    screen = get_ready_models_sets_screen(context, user_id, token, lang)
    await _show_message(
        message,
        screen.text,
        screen.reply_markup,
        edit_existing=edit_existing,
    )


async def show_ready_model_confirmation_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    token: str,
    *,
    source_set_id: str | None = None,
    edit_existing: bool = True,
    lang: str = "ru",
) -> None:
    if source_set_id:
        flow_store(context).update(token, user_id, {"source_set_id": source_set_id})
    screen = get_ready_model_confirmation_screen(context, user_id, token, lang)
    await _show_message(message, screen.text, screen.reply_markup, edit_existing=edit_existing)


async def show_ready_model_result_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    token: str,
    *,
    edit_existing: bool = True,
    lang: str = "ru",
) -> object | bool:
    flow = flow_store(context).get(token, user_id)
    if flow is None:
        await _show_message(
            message,
            "<b>📚 Ready models</b>\n\nСессия устарела. Откройте Ready models заново.",
            _back_to_ready_models_keyboard(lang),
            edit_existing=edit_existing,
        )
        return False
    target = _get_g25_target(context, user_id, str(flow.get("coordinate_id") or ""))
    source_set = get_source_set(str(flow.get("source_set_id") or ""))
    if target is None or source_set is None:
        await _show_message(
            message,
            "<b>📚 Ready models</b>\n\nНе удалось открыть выбранную модель.",
            _back_to_ready_models_keyboard(lang),
            edit_existing=edit_existing,
        )
        return False
    if not source_set_is_runnable(source_set):
        await _show_message(
            message,
            "<b>📚 Ready models</b>\n\nЭта модель пока в черновике.",
            _footer_markup(f"{VAHADUO_CALLBACK_PREFIX}:ready_model_confirm:{token}", lang),
            edit_existing=edit_existing,
        )
        return False
    result = run_source_fitting(target.title, target.g25_line, source_set)
    if result.status == "ok":
        try:
            rendered = build_rendered_source_fit_card(result)
            photo = BytesIO(rendered.image_bytes)
            photo.name = "vahaduo_ready_model.png"
            sent = await message.reply_photo(
                photo=photo,
                caption=rendered.caption,
                reply_markup=build_ready_model_result_keyboard(token, lang),
                do_quote=False,
            )
            try:
                await message.delete()
            except Exception:
                logger.exception("Could not delete Ready models confirmation after photo result")
            return sent
        except Exception:
            logger.exception("Could not render/send Ready models result")
    await _show_message(
        message,
        ready_model_result_text(result, source_set, lang),
        _footer_markup(f"{VAHADUO_CALLBACK_PREFIX}:ready_model_confirm:{token}", lang),
        edit_existing=edit_existing,
    )
    return result.status == "ok"


def _back_to_ready_models_keyboard(lang: str) -> InlineKeyboardMarkup:
    return _footer_markup(f"{VAHADUO_CALLBACK_PREFIX}:ready_models", lang)


def _footer_markup(back_callback: str, lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([_footer_row(back_callback, lang)])


def _footer_row(back_callback: str, lang: str = "ru") -> list[InlineKeyboardButton]:
    return [
        InlineKeyboardButton("⬅️ Back" if lang == "en" else "⬅️ Назад", callback_data=back_callback),
        InlineKeyboardButton(t("nav.cancel", lang), callback_data=f"{VAHADUO_CALLBACK_PREFIX}:cancel"),
    ]


async def _show_message(message, text: str, reply_markup: InlineKeyboardMarkup, *, edit_existing: bool = True) -> None:
    if edit_existing:
        await message.edit_text(text, reply_markup=reply_markup, parse_mode="HTML")
        return
    await message.reply_text(text, reply_markup=reply_markup, parse_mode="HTML", do_quote=False)


def _my_data_store(context: ContextTypes.DEFAULT_TYPE) -> MyDataStore:
    store = context.application.bot_data.get("my_data_store")
    if isinstance(store, MyDataStore):
        return store
    store = MyDataStore(Path(__file__).resolve().parents[3] / "storage" / "my_data")
    context.application.bot_data["my_data_store"] = store
    return store


def _list_g25_targets(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> list[ReadyModelTarget]:
    store = _my_data_store(context)
    targets: list[ReadyModelTarget] = []
    seen_ids: set[str] = set()
    try:
        for sample in store.list_samples(user_id):
            coords = [
                coord
                for coord in store.list_sample_coordinates(user_id, sample.asset_id)
                if _is_g25_coordinate(coord)
            ]
            for coord in coords:
                title = sample.display_name if len(coords) == 1 else f"{sample.display_name} - {coord.display_name}"
                targets.append(ReadyModelTarget(coord.asset_id, title, coord.g25_line.strip()))
                seen_ids.add(coord.asset_id)
        for coord in store.list_coordinates(user_id):
            if coord.asset_id in seen_ids or not _is_g25_coordinate(coord):
                continue
            targets.append(ReadyModelTarget(coord.asset_id, coord.display_name, coord.g25_line.strip()))
    except Exception:
        logger.exception("Failed to load G25 targets for Vahaduo ready models")
        return []
    return targets


def _get_g25_target(context: ContextTypes.DEFAULT_TYPE, user_id: int, coordinate_id: str) -> ReadyModelTarget | None:
    for target in _list_g25_targets(context, user_id):
        if target.coordinate_id == coordinate_id:
            return target
    return None


def _is_g25_coordinate(coord: CoordinateAsset) -> bool:
    return coord.coordinate_type.strip().lower() == "g25" and bool(coord.g25_line.strip())
