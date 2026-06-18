from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from telegram import Update
from telegram.ext import Application, ApplicationHandlerStop, ContextTypes

from app.i18n import get_user_language
from app.features.my_data.storage import MyDataStore
from app.main_menu import ensure_active_main_menu, set_active_main_menu_message
from g25_core.command_service import G25CommandError

from . import ui as vahaduo_ui
from .service import VahaduoCommandService
from .storage import VahaduoFullStore, VahaduoSavedSourceStore, VahaduoSavedTargetStore


VAHADUO_CALLBACK_PREFIX = "vahaduo"
DNA_LAB_VAHADUO_FLOW_STORE_KEY = "dna_lab_vahaduo_store"
DNA_LAB_VAHADUO_SAVED_STORE_KEY = "dna_lab_vahaduo_saved_store"
DNA_LAB_VAHADUO_TARGET_STORE_KEY = "dna_lab_vahaduo_target_store"
DNA_LAB_VAHADUO_SERVICE_KEY = "dna_lab_vahaduo_service"
logger = logging.getLogger(__name__)


def _copy(lang: str, ru: str, en: str) -> str:
    return en if lang == "en" else ru


def _vh_text(lang: str, text: str) -> str:
    if lang != "en":
        return text
    translations = {
        "Сначала выберите режим Distance, Single или Multi.": "Choose Distance, Single, or Multi first.",
        "Сначала выберите режим Single или Multi.": "Choose Single or Multi first.",
        "Сначала выберите режим Multi.": "Choose Multi mode first.",
        "Сначала выберите режим и source.": "Choose a mode and source first.",
        "Сначала выберите хотя бы один компонент.": "Choose at least one component first.",
        "Сначала выберите хотя бы один target.": "Choose at least one target first.",
        "Неизвестный набор компонентов.": "Unknown component set.",
        "Target еще не выбран.": "Target has not been selected yet.",
        "Сначала добавьте target.": "Add a target first.",
        "Этот target уже сохранен в My DNA.": "This target is already saved in My DNA.",
        "Этот target уже сохранен.": "This target is already saved.",
        "Сначала загрузите source.": "Upload a source first.",
        "Этот source уже сохранен.": "This source is already saved.",
        "Source еще не выбран.": "Source has not been selected yet.",
        "Не удалось определить набор.": "Could not identify the set.",
        "Набор не найден.": "Set not found.",
        "Файл набора не найден. Удалите набор и сохраните заново.": "Set file not found. Delete the set and save it again.",
        "Набор уже не найден.": "Set is no longer available.",
        "Не удалось определить компонент.": "Could not identify the component.",
        "Компонент больше не найден. Выберите source заново.": "Component is no longer available. Choose the source again.",
        "Компоненты source больше не найдены. Выберите source заново.": "Source components are no longer available. Choose the source again.",
        "Не удалось определить target.": "Could not identify the target.",
        "Target не найден.": "Target not found.",
        "Target не найден в My DNA.": "Target not found in My DNA.",
        "Target уже не найден.": "Target is no longer available.",
        "Файл target не найден. Удалите target и сохраните заново.": "Target file not found. Delete the target and save it again.",
        "Список устарел. Откройте «G25-профили» заново.": "The list is stale. Open G25 profiles again.",
        "Не удалось определить Sample.": "Could not identify the sample.",
        "G25 для Sample не найден.": "G25 for this sample was not found.",
        "Сохраненный target пустой.": "Saved target is empty.",
        "Один из сохраненных target пустой. Сохраните его заново.": "One of the saved targets is empty. Save it again.",
        "Target выбран, считаю...": "Target selected, calculating...",
        "Targets выбраны, считаю...": "Targets selected, calculating...",
        "Target получен, проверяю G25...": "Target received, checking G25...",
        "Target получен, считаю...": "Target received, calculating...",
        "Source получен, проверяю строки G25...": "Source received, checking G25 rows...",
        "Расчет не выполнен.": "Calculation was not completed.",
        "Расчет готов.": "Calculation complete.",
        "Не удалось показать результат. Попробуйте ещё раз.": "Could not show the result. Please try again.",
        "Target сохранен.": "Target saved.",
        "Source готов.": "Source ready.",
        "Сначала добавьте target в Vahaduo Lab.": "Add a target in Vahaduo Lab first.",
        "Target пустой или файл больше не найден.": "Target is empty or the file is no longer available.",
        "Сначала загрузите source в Vahaduo Lab.": "Upload a source in Vahaduo Lab first.",
        "Набор сохранен.": "Set saved.",
        "Target удален.": "Target deleted.",
        "Набор удален.": "Set deleted.",
        "В source не найдены выбранные компоненты.": "Selected components were not found in the source.",
        "Для Single сначала выберите набор и компоненты.": "For Single, choose a set and components first.",
        "Неизвестный готовый source.": "Unknown preset source.",
        "Не вижу source. Отправьте список популяций в формате Vahaduo.": "I do not see a source. Send a population list in Vahaduo format.",
        "Не удалось прочитать source-файл. Пришлите txt/csv со строками G25.": "Could not read the source file. Send a txt/csv file with G25 rows.",
        "Не удалось прочитать target-файл. Пришлите txt/csv со строками G25.": "Could not read the target file. Send a txt/csv file with G25 rows.",
        "Manifest для source больше не найден. Выберите source заново.": "Source manifest is no longer available. Choose the source again.",
        "Source больше не найден. Выберите или загрузите source заново.": "Source is no longer available. Choose or upload the source again.",
        "Для Multi пришлите хотя бы один target в формате G25.": "For Multi, send at least one target in G25 format.",
        "Для Multi можно считать не больше 25 target за один запуск.": "Multi can process no more than 25 targets per run.",
        "Не удалось определить группы source для Multi.": "Could not identify source groups for Multi.",
        "Не удалось найти популяции для сравнения.": "Could not find populations to compare.",
        "В source не найдено ни одной строки G25: имя + 25 координат.": "No G25 rows were found in the source: name + 25 coordinates.",
        "Не вижу target-координат. Пришлите строки G25: имя и 25 координат.": "I do not see target coordinates. Send G25 rows: name and 25 coordinates.",
        "Не удалось распознать target-строки для Multi. Пришлите txt/csv со строками вида Name,0.0123,...,0.0456.": "Could not parse target rows for Multi. Send txt/csv rows like Name,0.0123,...,0.0456.",
        "Название не должно быть пустым.": "Name must not be empty.",
        "Не удалось определить пользователя.": "Could not identify the user.",
        "Source-файл больше не найден.": "Source file is no longer available.",
        "Не удалось сохранить набор.": "Could not save the set.",
        "Target-файл больше не найден.": "Target file is no longer available.",
        "Не удалось сохранить target.": "Could not save target.",
        "Не удалось обработать сохраненный target. Проверьте G25-координаты и попробуйте еще раз.": "Could not process the saved target. Check the G25 coordinates and try again.",
        "Не удалось обработать выбранные target. Проверьте сохраненные координаты и попробуйте еще раз.": "Could not process the selected targets. Check the saved coordinates and try again.",
        "Не удалось обработать target. Проверьте файл или G25-координаты и попробуйте еще раз.": "Could not process the target. Check the file or G25 coordinates and try again.",
        "Не удалось обработать source. Проверьте формат строк G25 и попробуйте еще раз.": "Could not process the source. Check the G25 row format and try again.",
        "G25 координаты": "G25 coordinates",
    }
    if text in translations:
        return translations[text]
    prefixes = {
        "Не найден source-файл: ": "Source file not found: ",
        "Не удалось подготовить Distance: ": "Could not prepare Distance: ",
        "Не удалось прочитать source: ": "Could not read source: ",
    }
    for ru_prefix, en_prefix in prefixes.items():
        if text.startswith(ru_prefix):
            return en_prefix + text.removeprefix(ru_prefix)
    return text


def _vh_error(lang: str, exc: Exception) -> str:
    return _vh_text(lang, str(exc))


def register_vahaduo_services(application: Application, settings) -> None:
    application.bot_data[DNA_LAB_VAHADUO_FLOW_STORE_KEY] = VahaduoFullStore()
    application.bot_data[DNA_LAB_VAHADUO_SAVED_STORE_KEY] = VahaduoSavedSourceStore(
        settings.root_dir / "storage" / "vahaduo_sources.sqlite3",
        settings.root_dir / "storage" / "vahaduo_sources",
    )
    application.bot_data[DNA_LAB_VAHADUO_TARGET_STORE_KEY] = VahaduoSavedTargetStore(
        settings.root_dir / "storage" / "vahaduo_targets.sqlite3",
        settings.root_dir / "storage" / "vahaduo_targets",
    )
    application.bot_data[DNA_LAB_VAHADUO_SERVICE_KEY] = VahaduoCommandService(settings.root_dir / "g25_core")


def _service(context: ContextTypes.DEFAULT_TYPE) -> VahaduoCommandService:
    service = context.application.bot_data.get(DNA_LAB_VAHADUO_SERVICE_KEY)
    if isinstance(service, VahaduoCommandService):
        return service
    service = VahaduoCommandService(Path(__file__).resolve().parents[3] / "g25_core")
    context.application.bot_data[DNA_LAB_VAHADUO_SERVICE_KEY] = service
    return service


def _record_g25_usage(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    mode: str,
    input_mode: str = "unknown",
    success: bool = True,
    query: str | None = None,
) -> None:
    usage_store = context.application.bot_data.get("usage_store")
    if usage_store is not None and hasattr(usage_store, "record_g25"):
        command = f"vahaduo_{mode}" if mode in {"distance", "single", "multi"} else "vahaduo"
        usage_store.record_g25(update, command=command, input_mode=input_mode, success=success, query=query)


def _record_dna_lab_usage(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    action: str,
    success: bool = True,
    input_mode: str = "callback",
) -> None:
    usage_store = context.application.bot_data.get("usage_store")
    if usage_store is not None and hasattr(usage_store, "record_dna_lab"):
        usage_store.record_dna_lab(update, "vahaduo", action=action, success=success, input_mode=input_mode)


def _flow_store(context: ContextTypes.DEFAULT_TYPE) -> VahaduoFullStore:
    store = context.application.bot_data.get(DNA_LAB_VAHADUO_FLOW_STORE_KEY)
    if isinstance(store, VahaduoFullStore):
        return store
    return context.application.bot_data["vahaduo_store"]


def _saved_store(context: ContextTypes.DEFAULT_TYPE) -> VahaduoSavedSourceStore:
    return context.application.bot_data[DNA_LAB_VAHADUO_SAVED_STORE_KEY]


def _target_store(context: ContextTypes.DEFAULT_TYPE) -> VahaduoSavedTargetStore:
    return context.application.bot_data[DNA_LAB_VAHADUO_TARGET_STORE_KEY]


def _my_data_store(context: ContextTypes.DEFAULT_TYPE) -> MyDataStore:
    store = context.application.bot_data.get("my_data_store")
    if isinstance(store, MyDataStore):
        return store
    store = MyDataStore(Path(__file__).resolve().parents[3] / "storage" / "my_data")
    context.application.bot_data["my_data_store"] = store
    return store


def _coordinate_target_item(asset, *, title: str | None = None, item_id: str | None = None, read_only: bool = False) -> dict[str, object]:
    return {
        "id": item_id or asset.asset_id,
        "coordinate_id": asset.asset_id,
        "title": title or asset.display_name,
        "target_name": asset.target_name,
        "g25_line": asset.g25_line.strip(),
        "target_input_mode": asset.input_mode,
        "read_only": read_only,
    }


def _sample_target_items(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    store = _my_data_store(context)
    try:
        for sample in store.list_samples(user_id):
            coords = [
                coord
                for coord in store.list_sample_coordinates(user_id, sample.asset_id)
                if coord.coordinate_type.strip().lower() == "g25" and coord.g25_line.strip()
            ]
            for coord in coords:
                title = sample.display_name if len(coords) == 1 else f"{sample.display_name} - {coord.display_name}"
                items.append(_coordinate_target_item(coord, title=title, item_id=f"sample|{coord.asset_id}", read_only=True))
    except Exception:
        logger.exception("Failed to load My data sample G25 coordinates for Vahaduo")
    return items


def _attached_coordinate_ids(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> set[str]:
    store = _my_data_store(context)
    attached: set[str] = set()
    try:
        for sample in store.list_samples(user_id):
            attached.update(str(value) for value in sample.coordinate_ids if str(value))
    except Exception:
        logger.exception("Failed to load My data sample attachments for Vahaduo")
    return attached


def _other_target_items(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    attached = _attached_coordinate_ids(context, user_id)
    my_data_store = _my_data_store(context)
    seen_lines: set[str] = set()
    try:
        for asset in my_data_store.list_coordinates(user_id):
            if asset.coordinate_type.strip().lower() != "g25" or not asset.g25_line.strip():
                continue
            if asset.asset_id in attached:
                continue
            seen_lines.add(asset.g25_line.strip())
            items.append(_coordinate_target_item(asset))
    except Exception:
        logger.exception("Failed to load My data G25 coordinates for Vahaduo")
    legacy_store = context.application.bot_data.get(DNA_LAB_VAHADUO_TARGET_STORE_KEY)
    if legacy_store is None or not hasattr(legacy_store, "list_for_user"):
        return items
    try:
        for item in legacy_store.list_for_user(user_id):
            legacy_id = int(item.get("id") or 0)
            if not legacy_id:
                continue
            target_path = Path(str(item.get("target_path") or ""))
            target_body = ""
            if target_path.exists():
                try:
                    target_body = target_path.read_text(encoding="utf-8").strip()
                except OSError:
                    target_body = ""
            if not target_body:
                continue
            if target_body in seen_lines:
                continue
            items.append(
                {
                    "id": f"legacy-{legacy_id}",
                    "title": str(item.get("title") or item.get("target_name") or "target"),
                    "target_name": str(item.get("target_name") or item.get("title") or "target"),
                    "g25_line": target_body,
                    "target_input_mode": str(item.get("target_input_mode") or "saved"),
                    "legacy_target_id": legacy_id,
                }
            )
    except Exception:
        logger.exception("Failed to load legacy Vahaduo targets")
    return items


def _my_data_target_items(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> list[dict[str, object]]:
    return [*_sample_target_items(context, user_id), *_other_target_items(context, user_id)]


def _prepare_target_callback_items(items: list[dict[str, object]]) -> list[dict[str, object]]:
    return [dict(item, callback_id=str(index)) for index, item in enumerate(items)]


def _store_target_callback_items(
    flow: VahaduoFullStore,
    chat_id: int,
    user_id: int,
    *,
    source_kind: str,
    items: list[dict[str, object]],
) -> list[dict[str, object]]:
    prepared = _prepare_target_callback_items(items)
    flow.set_value(chat_id, user_id, "target_list_kind", source_kind)
    flow.set_value(chat_id, user_id, "target_items", prepared)
    return prepared


def _target_item_from_state(state: dict[str, object] | None, token: str) -> dict[str, object] | None:
    if not state:
        return None
    try:
        index = int(token)
    except (TypeError, ValueError):
        return None
    items = list(state.get("target_items") or [])
    if index < 0 or index >= len(items):
        return None
    item = items[index]
    return dict(item) if isinstance(item, dict) else None


def _target_item_from_state_or_rebuilt(
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    state: dict[str, object] | None,
    token: str,
    *,
    default_source: str = "other",
) -> dict[str, object] | None:
    item = _target_item_from_state(state, token)
    if item is not None:
        return item

    try:
        index = int(token)
    except (TypeError, ValueError):
        return None

    sources: list[str] = []
    state_source = str((state or {}).get("target_list_kind") or "")
    for source in (state_source, default_source, "other", "samples"):
        if source in {"other", "samples"} and source not in sources:
            sources.append(source)

    for source in sources:
        items = _sample_target_items(context, user_id) if source == "samples" else _other_target_items(context, user_id)
        if 0 <= index < len(items):
            return dict(items[index])
    return None


def _sample_target_item(context: ContextTypes.DEFAULT_TYPE, user_id: int, asset_id: str) -> dict[str, object] | None:
    if asset_id.startswith("sample|"):
        coordinate_id = asset_id.split("|", 1)[1]
    else:
        coordinate_id = asset_id
    for item in _sample_target_items(context, user_id):
        if str(item.get("coordinate_id") or "") == coordinate_id or str(item.get("id") or "") == asset_id:
            return item
    return None


def _my_data_target_item(context: ContextTypes.DEFAULT_TYPE, user_id: int, asset_id: str) -> dict[str, object] | None:
    if asset_id.startswith("legacy-"):
        try:
            legacy_id = int(asset_id.removeprefix("legacy-"))
        except ValueError:
            return None
        item = _target_store(context).get_for_user(user_id, legacy_id)
        if not item:
            return None
        target_path = Path(str(item.get("target_path") or ""))
        if not target_path.exists():
            return None
        try:
            target_body = target_path.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        if not target_body:
            return None
        return {
            "id": f"legacy-{legacy_id}",
            "title": str(item.get("title") or item.get("target_name") or "target"),
            "target_name": str(item.get("target_name") or item.get("title") or "target"),
            "g25_line": target_body,
            "target_input_mode": str(item.get("target_input_mode") or "saved"),
            "legacy_target_id": legacy_id,
        }
    asset = _my_data_store(context).get_coordinate(user_id, asset_id)
    if asset is None or asset.coordinate_type.strip().lower() != "g25" or not asset.g25_line.strip():
        return None
    return {
        "id": asset.asset_id,
        "title": asset.display_name,
        "target_name": asset.target_name,
        "g25_line": asset.g25_line.strip(),
        "target_input_mode": asset.input_mode,
    }


def _target_body_from_item(item: dict[str, object]) -> str:
    body = str(item.get("g25_line") or "").strip()
    if body:
        return body
    target_path = Path(str(item.get("target_path") or ""))
    if target_path.exists():
        return target_path.read_text(encoding="utf-8").strip()
    return ""


def _target_label_from_item(item: dict[str, object]) -> str:
    return str(item.get("target_name") or item.get("title") or "target")


def _set_my_data_target_state(
    flow: VahaduoFullStore,
    chat_id: int,
    user_id: int,
    item: dict[str, object],
) -> dict[str, object]:
    state = flow.set_value(chat_id, user_id, "target_label", str(item.get("title") or item.get("target_name") or "target"))
    state = flow.set_value(chat_id, user_id, "target_line", str(item.get("g25_line") or ""))
    state = flow.set_value(chat_id, user_id, "target_path", "")
    state = flow.set_value(chat_id, user_id, "target_input_mode", "my-data")
    state = flow.set_value(chat_id, user_id, "target_saved_id", 0)
    state = flow.set_value(chat_id, user_id, "target_coordinate_id", str(item.get("id") or ""))
    state = flow.set_value(chat_id, user_id, "target_readonly", bool(item.get("read_only")))
    flow.clear_pending(chat_id, user_id)
    return state


def _build_sample_name(update: Update, fallback_name: str = "") -> str:
    fallback_name = fallback_name.strip()
    if fallback_name:
        return fallback_name
    user = update.effective_user
    if user is not None:
        full_name = " ".join(
            part for part in [getattr(user, "first_name", "") or "", getattr(user, "last_name", "") or ""] if part
        ).strip()
        if full_name:
            return full_name
        if getattr(user, "username", None):
            return str(user.username)
    return "Target"


async def _delete_message_best_effort(message, *, reason: str) -> None:
    try:
        await message.delete()
    except Exception:
        logger.debug("Could not delete Vahaduo message after %s", reason, exc_info=True)


async def _clear_reply_markup_best_effort(query, *, reason: str) -> None:
    try:
        if hasattr(query, "edit_message_reply_markup"):
            await query.edit_message_reply_markup(reply_markup=None)
            return
        if hasattr(query.message, "edit_reply_markup"):
            await query.message.edit_reply_markup(reply_markup=None)
    except Exception:
        logger.debug("Could not clear Vahaduo reply markup after %s", reason, exc_info=True)


async def _send_distance_result_photo_from_query(
    *,
    query,
    state: dict[str, object],
    result,
    lang: str,
) -> object | None:
    caption = vahaduo_ui._g25vahaduo_distance_result_caption(state, getattr(result, "target_name", ""), lang=lang)
    reply_markup = vahaduo_ui._build_g25vahaduo_distance_result_keyboard(lang=lang)
    try:
        with result.png_path.open("rb") as handle:
            sent = await query.message.reply_photo(photo=handle, caption=caption, reply_markup=reply_markup, do_quote=False)
    except Exception:
        logger.exception("Could not show Vahaduo Distance result photo")
        try:
            await query.message.reply_text(_vh_text(lang, "Не удалось показать результат. Попробуйте ещё раз."), do_quote=False)
        except Exception:
            logger.debug("Could not send Vahaduo Distance result fallback message", exc_info=True)
        return None
    await _delete_message_best_effort(query.message, reason="distance result photo send")
    return sent


async def _send_distance_result_photo_from_message(
    *,
    message,
    state: dict[str, object],
    result,
    lang: str,
) -> object | None:
    caption = vahaduo_ui._g25vahaduo_distance_result_caption(state, getattr(result, "target_name", ""), lang=lang)
    reply_markup = vahaduo_ui._build_g25vahaduo_distance_result_keyboard(lang=lang)
    try:
        with result.png_path.open("rb") as handle:
            return await message.reply_photo(photo=handle, caption=caption, reply_markup=reply_markup, do_quote=False)
    except Exception:
        logger.exception("Could not show Vahaduo Distance result photo")
        try:
            await message.reply_text(_vh_text(lang, "Не удалось показать результат. Попробуйте ещё раз."), do_quote=False)
        except Exception:
            logger.debug("Could not send Vahaduo Distance result fallback message", exc_info=True)
        return None


async def _send_single_result_photo_from_query(
    *,
    query,
    state: dict[str, object],
    result,
    lang: str,
) -> object | None:
    caption = vahaduo_ui._g25vahaduo_single_result_caption(state, result, lang=lang)
    reply_markup = vahaduo_ui._build_g25vahaduo_single_result_keyboard(lang=lang)
    try:
        with result.png_path.open("rb") as handle:
            sent = await query.message.reply_photo(photo=handle, caption=caption, reply_markup=reply_markup, do_quote=False)
    except Exception:
        logger.exception("Could not show Vahaduo Single result photo")
        try:
            await query.message.reply_text(_vh_text(lang, "Не удалось показать результат. Попробуйте ещё раз."), do_quote=False)
        except Exception:
            logger.debug("Could not send Vahaduo Single result fallback message", exc_info=True)
        return None
    await _delete_message_best_effort(query.message, reason="single result photo send")
    return sent


async def _send_single_result_photo_from_message(
    *,
    message,
    state: dict[str, object],
    result,
    lang: str,
) -> object | None:
    caption = vahaduo_ui._g25vahaduo_single_result_caption(state, result, lang=lang)
    reply_markup = vahaduo_ui._build_g25vahaduo_single_result_keyboard(lang=lang)
    try:
        with result.png_path.open("rb") as handle:
            return await message.reply_photo(photo=handle, caption=caption, reply_markup=reply_markup, do_quote=False)
    except Exception:
        logger.exception("Could not show Vahaduo Single result photo")
        try:
            await message.reply_text(_vh_text(lang, "Не удалось показать результат. Попробуйте ещё раз."), do_quote=False)
        except Exception:
            logger.debug("Could not send Vahaduo Single result fallback message", exc_info=True)
        return None


async def _send_multi_result_photo_from_query(
    *,
    query,
    state: dict[str, object],
    result,
    lang: str,
) -> object | None:
    caption = vahaduo_ui._g25vahaduo_multi_result_caption(state, result, lang=lang)
    reply_markup = vahaduo_ui._build_g25vahaduo_multi_result_keyboard(lang=lang)
    try:
        with result.png_path.open("rb") as handle:
            sent = await query.message.reply_photo(photo=handle, caption=caption, reply_markup=reply_markup, do_quote=False)
    except Exception:
        logger.exception("Could not show Vahaduo Multi result photo")
        try:
            await query.message.reply_text(_vh_text(lang, "Не удалось показать результат. Попробуйте ещё раз."), do_quote=False)
        except Exception:
            logger.debug("Could not send Vahaduo Multi result fallback message", exc_info=True)
        return None
    await _delete_message_best_effort(query.message, reason="multi result photo send")
    return sent


async def _send_multi_result_photo_from_message(
    *,
    message,
    state: dict[str, object],
    result,
    lang: str,
) -> object | None:
    caption = vahaduo_ui._g25vahaduo_multi_result_caption(state, result, lang=lang)
    reply_markup = vahaduo_ui._build_g25vahaduo_multi_result_keyboard(lang=lang)
    try:
        with result.png_path.open("rb") as handle:
            return await message.reply_photo(photo=handle, caption=caption, reply_markup=reply_markup, do_quote=False)
    except Exception:
        logger.exception("Could not show Vahaduo Multi result photo")
        try:
            await message.reply_text(_vh_text(lang, "Не удалось показать результат. Попробуйте ещё раз."), do_quote=False)
        except Exception:
            logger.debug("Could not send Vahaduo Multi result fallback message", exc_info=True)
        return None


async def _show_or_replace_vahaduo_screen(
    context: ContextTypes.DEFAULT_TYPE,
    query,
    chat_id: int,
    user_id: int,
    text: str,
    reply_markup,
    *,
    parse_mode: str | None = None,
) -> None:
    flow = _flow_store(context)
    if getattr(query.message, "photo", None):
        sent = await query.message.reply_text(text, reply_markup=reply_markup, parse_mode=parse_mode, do_quote=False)
        await _clear_reply_markup_best_effort(query, reason="result back")
        if getattr(sent, "message_id", None) is not None:
            flow.set_message_id(chat_id, user_id, int(sent.message_id))
            set_active_main_menu_message(context, chat_id, user_id, int(sent.message_id))
        return
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    if getattr(query.message, "message_id", None) is not None:
        flow.set_message_id(chat_id, user_id, int(query.message.message_id))
        set_active_main_menu_message(context, chat_id, user_id, int(query.message.message_id))


def _clear_other_pending(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int) -> None:
    my_data_flow = context.application.bot_data.get("my_data_flow_store")
    if my_data_flow is not None and hasattr(my_data_flow, "clear"):
        my_data_flow.clear(chat_id, user_id)
    for key in ("haplogroup_flow_store",):
        store = context.application.bot_data.get(key)
        if store is not None and hasattr(store, "clear_pending"):
            store.clear_pending(chat_id, user_id)


def _is_safe_vahaduo_target_view_action(action: str) -> bool:
    if action in {"vms", "vmo"}:
        return True
    if action.startswith("vahaduo_target_pick_run"):
        return False
    if action.startswith("vahaduo_target_pick"):
        return True
    if action.startswith("vahaduo_sample_target_run_select"):
        return False
    if action.startswith("vahaduo_sample_target_select"):
        return True
    if action.startswith("vahaduo_mydata_target_run_select"):
        return False
    return action.startswith("vahaduo_mydata_target_select")


async def _reply_with_active_menu(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    reply_markup,
    *,
    parse_mode: str | None = None,
) -> Any:
    if update.message is None:
        return None
    sent = await update.message.reply_text(text, reply_markup=reply_markup, parse_mode=parse_mode, do_quote=False)
    if update.effective_chat is not None and update.effective_user is not None:
        set_active_main_menu_message(context, update.effective_chat.id, update.effective_user.id, sent.message_id)
    return sent


def _source_from_state(state: dict[str, object]) -> tuple[str, str, Path, Path | None]:
    source_key = str(state.get("source_key") or "custom")
    source_label = str(state.get("source_label") or "source")
    source_path = Path(str(state.get("source_path") or ""))
    if not source_path.exists():
        raise G25CommandError("Source больше не найден. Выберите или загрузите source заново.")
    manifest_value = str(state.get("source_manifest_path") or "")
    manifest_path = Path(manifest_value) if manifest_value else None
    if manifest_path is not None and not manifest_path.exists():
        raise G25CommandError("Manifest для source больше не найден. Выберите source заново.")
    return source_key, source_label, source_path, manifest_path


def _message_chat_id(message) -> int | None:
    chat_id = getattr(message, "chat_id", None)
    if chat_id is not None:
        return int(chat_id)
    chat = getattr(message, "chat", None)
    if chat is not None and getattr(chat, "id", None) is not None:
        return int(chat.id)
    return None


async def show_vahaduo_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    lang: str | None = None,
    edit_existing: bool = False,
) -> None:
    lang = lang or get_user_language(context, user_id)
    chat_id = _message_chat_id(message)
    flow = _flow_store(context)
    if chat_id is not None:
        flow.open(chat_id, user_id)

    text = vahaduo_ui._g25vahaduo_full_text(lang=lang)
    markup = vahaduo_ui._build_g25vahaduo_full_keyboard(lang=lang)
    if edit_existing:
        await message.edit_text(text, reply_markup=markup, parse_mode="HTML")
        active_message = message
    else:
        active_message = await message.reply_text(text, reply_markup=markup, parse_mode="HTML", do_quote=False)

    active_chat_id = _message_chat_id(active_message)
    active_message_id = getattr(active_message, "message_id", None)
    if active_chat_id is not None and active_message_id is not None:
        flow.set_message_id(active_chat_id, user_id, int(active_message_id))
        set_active_main_menu_message(context, active_chat_id, user_id, int(active_message_id))


async def vahaduo_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None or query.message is None:
        return
    if not query.data.startswith(f"{VAHADUO_CALLBACK_PREFIX}:"):
        return
    parts = query.data.split(":")
    action = parts[1] if len(parts) > 1 else "root"
    payload = parts[2:] if len(parts) > 2 else []
    stale_safe_target_view = _is_safe_vahaduo_target_view_action(action)
    if not stale_safe_target_view and not await ensure_active_main_menu(update, context):
        return
    if update.effective_chat is None or update.effective_user is None:
        return
    if stale_safe_target_view:
        set_active_main_menu_message(context, update.effective_chat.id, update.effective_user.id, query.message.message_id)

    await query.answer()
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    lang = get_user_language(context, user_id)
    flow = _flow_store(context)
    service = _service(context)

    if action in {"root", "vahaduo_full"}:
        _clear_other_pending(context, chat_id, user_id)
        flow.open(chat_id, user_id)
        flow.set_message_id(chat_id, user_id, query.message.message_id)
        await query.edit_message_text(
            vahaduo_ui._g25vahaduo_full_text(lang=lang),
            reply_markup=vahaduo_ui._build_g25vahaduo_full_keyboard(lang=lang),
            parse_mode="HTML",
        )
        return

    if action == "cancel":
        flow.cancel(chat_id, user_id)
        if getattr(query.message, "photo", None):
            await _clear_reply_markup_best_effort(query, reason="cancel")
            return
        await query.edit_message_text(_copy(lang, "Vahaduo Lab закрыт.", "Vahaduo Lab closed."))
        return

    if action == "vahaduo_data":
        _clear_other_pending(context, chat_id, user_id)
        if flow.get(chat_id, user_id) is None:
            flow.open(chat_id, user_id)
        flow.set_message_id(chat_id, user_id, query.message.message_id)
        await query.edit_message_text(vahaduo_ui._g25vahaduo_data_mode_text(lang=lang), reply_markup=vahaduo_ui._build_g25vahaduo_data_mode_keyboard(lang=lang))
        return

    if action in {"vahaduo_mode_distance", "vahaduo_mode_single", "vahaduo_mode_multi"}:
        mode = {
            "vahaduo_mode_distance": "distance",
            "vahaduo_mode_single": "single",
            "vahaduo_mode_multi": "multi",
        }[action]
        _clear_other_pending(context, chat_id, user_id)
        if flow.get(chat_id, user_id) is None:
            flow.open(chat_id, user_id)
        state = flow.set_mode(chat_id, user_id, mode, awaiting="")
        flow.set_message_id(chat_id, user_id, query.message.message_id)
        await query.edit_message_text(
            vahaduo_ui._g25vahaduo_source_menu_text(state, lang=lang),
            reply_markup=vahaduo_ui._build_g25vahaduo_source_menu_keyboard(service, state, lang=lang),
        )
        return

    if action in {"vahaduo_data_mode_distance", "vahaduo_data_mode_single", "vahaduo_data_mode_multi"}:
        mode = {
            "vahaduo_data_mode_distance": "distance",
            "vahaduo_data_mode_single": "single",
            "vahaduo_data_mode_multi": "multi",
        }[action]
        _clear_other_pending(context, chat_id, user_id)
        if flow.get(chat_id, user_id) is None:
            flow.open(chat_id, user_id)
        state = flow.set_mode(chat_id, user_id, mode, awaiting="")
        state = flow.set_value(chat_id, user_id, "data_back", "vahaduo_data")
        flow.set_message_id(chat_id, user_id, query.message.message_id)
        items = _saved_store(context).list_for_user(user_id, mode)
        await query.edit_message_text(
            vahaduo_ui._g25vahaduo_saved_text(items, mode, lang=lang),
            reply_markup=vahaduo_ui._build_g25vahaduo_saved_keyboard(
                items,
                back_action=vahaduo_ui._g25vahaduo_data_back_action(state),
                include_upload=True,
                lang=lang,
            ),
        )
        return

    if action in {"vahaduo_sources", "vahaduo_modes"}:
        state = flow.get(chat_id, user_id)
        if not state or str(state.get("mode") or "") not in {"distance", "single", "multi"}:
            await query.answer(_copy(lang, "Сначала выберите режим Distance, Single или Multi.", "Choose Distance, Single, or Multi first."), show_alert=True)
            return
        flow.clear_pending(chat_id, user_id)
        await query.edit_message_text(
            vahaduo_ui._g25vahaduo_source_menu_text(state, lang=lang),
            reply_markup=vahaduo_ui._build_g25vahaduo_source_menu_keyboard(service, state, lang=lang),
        )
        return

    if action in {"vahaduo_data_menu", "vahaduo_data_from_sources", "vahaduo_saved"}:
        _clear_other_pending(context, chat_id, user_id)
        state = flow.get(chat_id, user_id)
        mode = str((state or {}).get("mode") or "")
        if mode not in {"distance", "single", "multi"}:
            await query.answer(_vh_text(lang, "Сначала выберите режим Distance, Single или Multi."), show_alert=True)
            return
        if action == "vahaduo_data_from_sources" or not str(state.get("data_back") or ""):
            state = flow.set_value(chat_id, user_id, "data_back", "vahaduo_sources")
        flow.set_message_id(chat_id, user_id, query.message.message_id)
        items = _saved_store(context).list_for_user(user_id, mode)
        await query.edit_message_text(
            vahaduo_ui._g25vahaduo_saved_text(items, mode, lang=lang),
            reply_markup=vahaduo_ui._build_g25vahaduo_saved_keyboard(
                items,
                back_action=vahaduo_ui._g25vahaduo_data_back_action(state),
                include_upload=True,
                lang=lang,
            ),
        )
        return

    if action == "vahaduo_presets":
        _clear_other_pending(context, chat_id, user_id)
        state = flow.get(chat_id, user_id)
        if not state or str(state.get("mode") or "") not in {"distance", "single", "multi"}:
            await query.answer(_copy(lang, "Сначала выберите режим Distance, Single или Multi.", "Choose Distance, Single, or Multi first."), show_alert=True)
            return
        flow.set_message_id(chat_id, user_id, query.message.message_id)
        await query.edit_message_text(
            vahaduo_ui._g25vahaduo_source_menu_text(state, lang=lang),
            reply_markup=vahaduo_ui._build_g25vahaduo_source_menu_keyboard(service, state, lang=lang),
        )
        return

    if action.startswith("vahaduo_preset"):
        source_key = payload[0] if payload else ""
        _clear_other_pending(context, chat_id, user_id)
        state = flow.get(chat_id, user_id)
        mode = str((state or {}).get("mode") or "")
        if mode not in {"distance", "single", "multi"}:
            await query.answer(_copy(lang, "Сначала выберите режим Distance, Single или Multi.", "Choose Distance, Single, or Multi first."), show_alert=True)
            return
        if mode in {"single", "multi"}:
            if source_key not in {"panel1", "panel2"}:
                await query.answer(_copy(lang, "Неизвестный набор компонентов.", "Unknown component set."), show_alert=True)
                return
            selected_keys = list(state.get("single_selected") or []) if str(state.get("single_panel") or "") == source_key else []
            flow.set_value(chat_id, user_id, "single_panel", source_key)
            flow.set_value(chat_id, user_id, "single_selected", selected_keys)
            await query.edit_message_text(
                vahaduo_ui._g25vahaduo_single_components_text(service, source_key, selected_keys, mode=mode, lang=lang),
                reply_markup=vahaduo_ui._build_g25vahaduo_single_components_keyboard(service, source_key, selected_keys, mode=mode, lang=lang),
            )
            return
        try:
            source_info = service.get_vahaduo_preset_source(source_key, mode)
        except G25CommandError as exc:
            await query.answer(_vh_error(lang, exc), show_alert=True)
            return
        state = flow.set_source(
            chat_id,
            user_id,
            source_key=source_info.source_key,
            source_label=source_info.source_label,
            source_path=source_info.references_path,
            source_count=source_info.source_count,
            source_input_mode=source_info.input_mode,
            source_manifest_path=source_info.manifest_path,
        )
        state = flow.set_value(chat_id, user_id, "target_back", "vahaduo_sources")
        state = flow.set_mode(chat_id, user_id, mode)
        flow.set_message_id(chat_id, user_id, query.message.message_id)
        await query.edit_message_text(vahaduo_ui._g25vahaduo_target_text(state, lang=lang), reply_markup=vahaduo_ui._build_g25vahaduo_target_keyboard(state, lang=lang))
        return

    if action.startswith("vahaduo_single_components"):
        panel_key = payload[0] if payload else ""
        state = flow.get(chat_id, user_id)
        mode = str((state or {}).get("mode") or "")
        if not state or mode not in {"single", "multi"}:
            await query.answer(_copy(lang, "Сначала выберите режим Single или Multi.", "Choose Single or Multi first."), show_alert=True)
            return
        selected = list(state.get("single_selected") or []) if str(state.get("single_panel") or "") == panel_key else []
        await query.edit_message_text(
            vahaduo_ui._g25vahaduo_single_components_text(service, panel_key, selected, mode=mode, lang=lang),
            reply_markup=vahaduo_ui._build_g25vahaduo_single_components_keyboard(service, panel_key, selected, mode=mode, lang=lang),
        )
        return

    if action.startswith("vahaduo_single_toggle"):
        panel_key = payload[0] if payload else ""
        source_key = payload[1] if len(payload) > 1 else ""
        state = flow.get(chat_id, user_id)
        mode = str((state or {}).get("mode") or "")
        if not state or mode not in {"single", "multi"}:
            await query.answer(_copy(lang, "Сначала выберите режим Single или Multi.", "Choose Single or Multi first."), show_alert=True)
            return
        selected = flow.toggle_single_component(chat_id, user_id, panel_key, source_key)
        await query.edit_message_text(
            vahaduo_ui._g25vahaduo_single_components_text(service, panel_key, selected, mode=mode, lang=lang),
            reply_markup=vahaduo_ui._build_g25vahaduo_single_components_keyboard(service, panel_key, selected, mode=mode, lang=lang),
        )
        return

    if action.startswith("vahaduo_single_all"):
        panel_key = payload[0] if payload else ""
        state = flow.get(chat_id, user_id)
        mode = str((state or {}).get("mode") or "")
        if not state or mode not in {"single", "multi"}:
            await query.answer(_copy(lang, "Сначала выберите режим Single или Multi.", "Choose Single or Multi first."), show_alert=True)
            return
        source_defs = service.list_vahaduo_single_components(panel_key)
        selected = [str(item["key"]) for item in source_defs]
        flow.set_value(chat_id, user_id, "single_panel", panel_key)
        state = flow.set_value(chat_id, user_id, "single_selected", selected)
        await query.edit_message_text(
            vahaduo_ui._g25vahaduo_single_components_text(service, panel_key, selected, mode=mode, lang=lang),
            reply_markup=vahaduo_ui._build_g25vahaduo_single_components_keyboard(service, panel_key, selected, mode=mode, lang=lang),
        )
        return

    if action.startswith("vahaduo_single_clear"):
        panel_key = payload[0] if payload else ""
        state = flow.get(chat_id, user_id)
        mode = str((state or {}).get("mode") or "")
        if not state or mode not in {"single", "multi"}:
            await query.answer(_vh_text(lang, "Сначала выберите режим Single или Multi."), show_alert=True)
            return
        selected = flow.clear_single_components(chat_id, user_id, panel_key)
        await query.edit_message_text(
            vahaduo_ui._g25vahaduo_single_components_text(service, panel_key, selected, mode=mode, lang=lang),
            reply_markup=vahaduo_ui._build_g25vahaduo_single_components_keyboard(service, panel_key, selected, mode=mode, lang=lang),
        )
        return

    if action.startswith("vahaduo_single_done"):
        panel_key = payload[0] if payload else ""
        state = flow.get(chat_id, user_id)
        mode = str((state or {}).get("mode") or "")
        if not state or mode not in {"single", "multi"}:
            await query.answer(_vh_text(lang, "Сначала выберите режим Single или Multi."), show_alert=True)
            return
        selected = list(state.get("single_selected") or []) if str(state.get("single_panel") or "") == panel_key else []
        if not selected:
            await query.answer(_vh_text(lang, "Сначала выберите хотя бы один компонент."), show_alert=True)
            return
        try:
            source_info = service.prepare_vahaduo_single_source(panel_key, selected, _build_sample_name(update, f"{mode}_{panel_key}"))
        except G25CommandError as exc:
            await query.answer(_vh_error(lang, exc), show_alert=True)
            return
        state = flow.set_source(
            chat_id,
            user_id,
            source_key=source_info.source_key,
            source_label=source_info.source_label,
            source_path=source_info.references_path,
            source_count=source_info.source_count,
            source_input_mode=source_info.input_mode,
            source_manifest_path=source_info.manifest_path,
        )
        state = flow.set_value(chat_id, user_id, "target_back", f"vahaduo_single_components:{panel_key}")
        state = flow.set_mode(chat_id, user_id, mode)
        flow.set_message_id(chat_id, user_id, query.message.message_id)
        await query.edit_message_text(vahaduo_ui._g25vahaduo_target_text(state, lang=lang), reply_markup=vahaduo_ui._build_g25vahaduo_target_keyboard(state, lang=lang))
        return

    if action in {"vahaduo_source_file", "vahaduo_source_text"}:
        _clear_other_pending(context, chat_id, user_id)
        state = flow.get(chat_id, user_id)
        mode = str((state or {}).get("mode") or "")
        if mode not in {"distance", "single", "multi"}:
            await query.answer(_vh_text(lang, "Сначала выберите режим Distance, Single или Multi."), show_alert=True)
            return
        flow.set_message_id(chat_id, user_id, query.message.message_id)
        flow.set_awaiting(chat_id, user_id, "source")
        input_mode = "file" if action == "vahaduo_source_file" else "text"
        await query.edit_message_text(
            vahaduo_ui._g25vahaduo_source_input_text(input_mode, lang=lang),
            reply_markup=vahaduo_ui._build_g25vahaduo_source_input_keyboard(lang=lang),
        )
        return

    if action == "vahaduo_target":
        state = flow.get(chat_id, user_id)
        if not state or not state.get("source_path") or str(state.get("mode") or "") not in {"distance", "single", "multi"}:
            await query.answer(_vh_text(lang, "Сначала выберите режим и source."), show_alert=True)
            return
        state = flow.set_mode(chat_id, user_id, str(state.get("mode") or "distance"))
        await query.edit_message_text(vahaduo_ui._g25vahaduo_target_text(state, lang=lang), reply_markup=vahaduo_ui._build_g25vahaduo_target_keyboard(state, lang=lang))
        return

    if action == "vahaduo_result_back":
        state = flow.get(chat_id, user_id)
        if not state or not state.get("source_path") or str(state.get("mode") or "") not in {"distance", "single", "multi"}:
            await query.answer(_vh_text(lang, "Сначала выберите режим и source."), show_alert=True)
            return
        result_back = str(state.get("result_back") or "target")
        if result_back == "targets":
            source_kind = str(state.get("result_back_source") or state.get("target_list_kind") or "other")
            if source_kind not in {"samples", "other"}:
                source_kind = "other"
            raw_items = _sample_target_items(context, user_id) if source_kind == "samples" else _other_target_items(context, user_id)
            items = _store_target_callback_items(flow, chat_id, user_id, source_kind=source_kind, items=raw_items)
            state = flow.get(chat_id, user_id) or state
            if str(state.get("mode") or "") == "multi":
                selected_ids = vahaduo_ui._vahaduo_multi_target_selection(state, items)
                await _show_or_replace_vahaduo_screen(
                    context,
                    query,
                    chat_id,
                    user_id,
                    vahaduo_ui._g25vahaduo_multi_targets_text(items, selected_ids, state=state, source=source_kind, lang=lang),
                    vahaduo_ui._build_g25vahaduo_multi_targets_keyboard(items, selected_ids, lang=lang),
                )
                return
            await _show_or_replace_vahaduo_screen(
                context,
                query,
                chat_id,
                user_id,
                vahaduo_ui._g25vahaduo_targets_text(items, for_run=True, source=source_kind, state=state, lang=lang),
                vahaduo_ui._build_g25vahaduo_targets_keyboard(items, for_run=True, source=source_kind, lang=lang),
                parse_mode="HTML",
            )
            return
        state = flow.set_mode(chat_id, user_id, str(state.get("mode") or "distance"))
        await _show_or_replace_vahaduo_screen(
            context,
            query,
            chat_id,
            user_id,
            vahaduo_ui._g25vahaduo_target_text(state, lang=lang),
            vahaduo_ui._build_g25vahaduo_target_keyboard(state, lang=lang),
        )
        return

    if action in {"vahaduo_run_target_file", "vahaduo_run_target_text"}:
        _clear_other_pending(context, chat_id, user_id)
        state = flow.get(chat_id, user_id)
        mode = str((state or {}).get("mode") or "")
        if not state or not state.get("source_path") or mode not in {"distance", "single", "multi"}:
            await query.answer(_vh_text(lang, "Сначала выберите режим и source."), show_alert=True)
            return
        flow.set_message_id(chat_id, user_id, query.message.message_id)
        flow.set_awaiting(chat_id, user_id, "target")
        input_mode = "file" if action == "vahaduo_run_target_file" else "text"
        await query.edit_message_text(
            vahaduo_ui._g25vahaduo_run_target_input_text(input_mode, mode, lang=lang),
            reply_markup=vahaduo_ui._build_g25vahaduo_run_target_input_keyboard(lang=lang),
        )
        return

    if action == "vahaduo_targets":
        _clear_other_pending(context, chat_id, user_id)
        if flow.get(chat_id, user_id) is None:
            flow.open(chat_id, user_id)
        flow.set_message_id(chat_id, user_id, query.message.message_id)
        await query.edit_message_text(
            vahaduo_ui._g25vahaduo_target_library_text(lang=lang),
            reply_markup=vahaduo_ui._build_g25vahaduo_target_library_keyboard(lang=lang),
            parse_mode="HTML",
        )
        return

    if action == "vahaduo_targets_for_run":
        _clear_other_pending(context, chat_id, user_id)
        state = flow.get(chat_id, user_id)
        if not state or not state.get("source_path") or str(state.get("mode") or "") not in {"distance", "single", "multi"}:
            await query.answer(_vh_text(lang, "Сначала выберите режим и source."), show_alert=True)
            return
        flow.set_message_id(chat_id, user_id, query.message.message_id)
        await query.edit_message_text(
            vahaduo_ui._g25vahaduo_target_library_text(for_run=True, state=state, lang=lang),
            reply_markup=vahaduo_ui._build_g25vahaduo_target_library_keyboard(for_run=True, lang=lang),
            parse_mode="HTML",
        )
        return

    if action in {"vahaduo_targets_samples", "vahaduo_targets_samples_for_run", "vahaduo_targets_other", "vahaduo_targets_other_for_run"}:
        _clear_other_pending(context, chat_id, user_id)
        for_run = action.endswith("_for_run")
        source_kind = "samples" if "samples" in action else "other"
        if for_run:
            state = flow.get(chat_id, user_id)
            if not state or not state.get("source_path") or str(state.get("mode") or "") not in {"distance", "single", "multi"}:
                await query.answer(_vh_text(lang, "Сначала выберите режим и source."), show_alert=True)
                return
        else:
            state = flow.get(chat_id, user_id)
            if state is None:
                state = flow.open(chat_id, user_id)
        flow.set_message_id(chat_id, user_id, query.message.message_id)
        raw_items = _sample_target_items(context, user_id) if source_kind == "samples" else _other_target_items(context, user_id)
        items = _store_target_callback_items(flow, chat_id, user_id, source_kind=source_kind, items=raw_items)
        if for_run and str((state or {}).get("mode") or "") == "multi":
            selected_ids = vahaduo_ui._vahaduo_multi_target_selection(state, items)
            state = flow.set_value(chat_id, user_id, "multi_target_selected", selected_ids)
            await query.edit_message_text(
                vahaduo_ui._g25vahaduo_multi_targets_text(items, selected_ids, state=state, source=source_kind, lang=lang),
                reply_markup=vahaduo_ui._build_g25vahaduo_multi_targets_keyboard(items, selected_ids, lang=lang),
            )
        else:
            await query.edit_message_text(
                vahaduo_ui._g25vahaduo_targets_text(items, for_run=for_run, source=source_kind, state=state, lang=lang),
                reply_markup=vahaduo_ui._build_g25vahaduo_targets_keyboard(items, for_run=for_run, source=source_kind, lang=lang),
                parse_mode="HTML",
            )
        return

    if action in {"vahaduo_target_text", "vahaduo_target_file"}:
        _clear_other_pending(context, chat_id, user_id)
        if flow.get(chat_id, user_id) is None:
            flow.open(chat_id, user_id)
        flow.set_message_id(chat_id, user_id, query.message.message_id)
        flow.set_awaiting(chat_id, user_id, "target_data")
        input_mode = "file" if action == "vahaduo_target_file" else "text"
        await query.edit_message_text(
            vahaduo_ui._g25vahaduo_target_input_text(input_mode, lang=lang),
            reply_markup=vahaduo_ui._build_g25vahaduo_target_input_keyboard(lang=lang),
        )
        return

    if action == "vahaduo_data_target":
        state = flow.get(chat_id, user_id)
        if not state or (not state.get("target_path") and not state.get("target_line")):
            await query.answer(_vh_text(lang, "Target еще не выбран."), show_alert=True)
            return
        flow.clear_pending(chat_id, user_id)
        await query.edit_message_text(
            vahaduo_ui._g25vahaduo_data_target_text(state, lang=lang),
            reply_markup=vahaduo_ui._build_g25vahaduo_data_target_keyboard(state, lang=lang),
            parse_mode="HTML",
        )
        return

    if action == "vahaduo_save_target":
        _clear_other_pending(context, chat_id, user_id)
        state = flow.get(chat_id, user_id)
        if not state or not state.get("target_path"):
            if not state or not state.get("target_line"):
                await query.answer(_vh_text(lang, "Сначала добавьте target."), show_alert=True)
                return
        if str((state or {}).get("target_coordinate_id") or ""):
            await query.answer(_vh_text(lang, "Этот target уже сохранен в My DNA."), show_alert=True)
            return
        if state and int(state.get("target_saved_id") or 0):
            await query.answer(_vh_text(lang, "Этот target уже сохранен."), show_alert=True)
            return
        if not state or (not state.get("target_path") and not state.get("target_line")):
            await query.answer(_vh_text(lang, "Сначала добавьте target."), show_alert=True)
            return
        flow.set_awaiting(chat_id, user_id, "target_save_name")
        await query.edit_message_text(
            vahaduo_ui._g25vahaduo_target_save_name_text(state, lang=lang),
            reply_markup=vahaduo_ui._build_g25vahaduo_target_save_name_keyboard(lang=lang),
        )
        return

    if action == "vahaduo_save_source":
        _clear_other_pending(context, chat_id, user_id)
        state = flow.get(chat_id, user_id)
        if not state or not state.get("source_path"):
            await query.answer(_vh_text(lang, "Сначала загрузите source."), show_alert=True)
            return
        if int(state.get("source_saved_id") or 0):
            await query.answer(_vh_text(lang, "Этот source уже сохранен."), show_alert=True)
            return
        flow.set_awaiting(chat_id, user_id, "save_name")
        await query.edit_message_text(
            vahaduo_ui._g25vahaduo_save_name_text(state, lang=lang),
            reply_markup=vahaduo_ui._build_g25vahaduo_save_name_keyboard(state, lang=lang),
        )
        return

    if action == "vahaduo_data_source":
        state = flow.get(chat_id, user_id)
        if not vahaduo_ui._is_vahaduo_data_only(state) or not state or not state.get("source_path"):
            await query.answer(_vh_text(lang, "Source еще не выбран."), show_alert=True)
            return
        flow.clear_pending(chat_id, user_id)
        await query.edit_message_text(
            vahaduo_ui._g25vahaduo_data_source_text(state),
            reply_markup=vahaduo_ui._build_g25vahaduo_data_source_keyboard(state),
        )
        return

    if action.startswith("vahaduo_saved_select"):
        await _handle_saved_source_select(update, context, query, payload)
        return

    if action in {"vahaduo_saved_components", "vahaduo_saved_group_all", "vahaduo_saved_group_clear", "vahaduo_saved_group_done"} or action.startswith("vahaduo_saved_group_toggle"):
        await _handle_saved_group_action(update, context, query, action, payload)
        return

    if action == "vahaduo_delete_menu":
        state = flow.get(chat_id, user_id)
        mode = str((state or {}).get("mode") or "")
        if mode not in {"distance", "single", "multi"}:
            await query.answer(_vh_text(lang, "Сначала выберите режим Distance, Single или Multi."), show_alert=True)
            return
        items = _saved_store(context).list_for_user(user_id, mode)
        await query.edit_message_text(
            vahaduo_ui._g25vahaduo_saved_text(items, mode, delete_mode=True),
            reply_markup=vahaduo_ui._build_g25vahaduo_saved_keyboard(items, delete_mode=True),
        )
        return

    if action.startswith("vahaduo_delete"):
        await _handle_source_delete(update, context, query, action, payload)
        return

    if action.startswith("vahaduo_target_pick_run"):
        await _handle_target_item_pick(update, context, query, payload, for_run=True)
        return

    if action.startswith("vahaduo_target_pick"):
        await _handle_target_item_pick(update, context, query, payload, for_run=False)
        return

    if action.startswith("vahaduo_target_delete_pick"):
        await _handle_target_item_delete(update, context, query, payload)
        return

    if action in {"vms", "vmsr"}:
        await _handle_sample_target_select(update, context, query, payload, for_run=action == "vmsr")
        return

    if action in {"vmo", "vmor"}:
        await _handle_my_data_target_select(update, context, query, payload, for_run=action == "vmor")
        return

    if action == "vmod":
        await _handle_my_data_target_delete(update, context, query, "vahaduo_mydata_target_delete", payload)
        return

    if action.startswith("vahaduo_sample_target_run_select"):
        await _handle_sample_target_select(update, context, query, payload, for_run=True)
        return

    if action.startswith("vahaduo_sample_target_select"):
        await _handle_sample_target_select(update, context, query, payload, for_run=False)
        return

    if action.startswith("vahaduo_mydata_target_run_select"):
        await _handle_my_data_target_select(update, context, query, payload, for_run=True)
        return

    if action.startswith("vahaduo_mydata_target_select"):
        await _handle_my_data_target_select(update, context, query, payload, for_run=False)
        return

    if action.startswith("vahaduo_target_select"):
        await _handle_target_select(update, context, query, payload, for_run=False)
        return

    if action.startswith("vahaduo_target_run_select"):
        await _handle_target_select(update, context, query, payload, for_run=True)
        return

    if action in {"vahaduo_multi_target_all", "vahaduo_multi_target_clear", "vahaduo_multi_target_done"} or action.startswith("vahaduo_multi_target_toggle"):
        await _handle_multi_target_action(update, context, query, action, payload)
        return

    if action == "vahaduo_target_delete_menu":
        items = _other_target_items(context, user_id)
        await query.edit_message_text(
            vahaduo_ui._g25vahaduo_targets_text(items, delete_mode=True, source="other"),
            reply_markup=vahaduo_ui._build_g25vahaduo_targets_keyboard(items, delete_mode=True, source="other"),
            parse_mode="HTML",
        )
        return

    if action.startswith("vahaduo_mydata_target_delete"):
        await _handle_my_data_target_delete(update, context, query, action, payload)
        return

    if action.startswith("vahaduo_target_delete"):
        await _handle_target_delete(update, context, query, action, payload)
        return


async def _handle_saved_source_select(update: Update, context: ContextTypes.DEFAULT_TYPE, query, payload: list[str]) -> None:
    if update.effective_chat is None or update.effective_user is None:
        return
    lang = get_user_language(context, update.effective_user.id)
    try:
        source_id = int(payload[0])
    except (IndexError, TypeError, ValueError):
        await query.answer(_vh_text(lang, "Не удалось определить набор."), show_alert=True)
        return
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    flow = _flow_store(context)
    service = _service(context)
    state = flow.get(chat_id, user_id)
    mode = str((state or {}).get("mode") or "")
    if mode not in {"distance", "single", "multi"}:
        await query.answer(_vh_text(lang, "Сначала выберите режим Distance, Single или Multi."), show_alert=True)
        return
    item = _saved_store(context).get_for_user(user_id, source_id, mode)
    if not item:
        await query.answer(_vh_text(lang, "Набор не найден."), show_alert=True)
        return
    source_path = Path(str(item.get("source_path") or ""))
    if not source_path.exists():
        await query.answer(_vh_text(lang, "Файл набора не найден. Удалите набор и сохраните заново."), show_alert=True)
        return
    state = flow.set_source(
        chat_id,
        user_id,
        source_key=f"saved_{source_id}",
        source_label=str(item.get("title") or "source"),
        source_path=source_path,
        source_count=int(item.get("source_count") or 0),
        source_input_mode="saved",
        source_saved_id=source_id,
        source_manifest_path=None,
    )
    state = flow.set_value(chat_id, user_id, "target_back", "vahaduo_saved")
    state = flow.set_value(chat_id, user_id, "saved_source_path", str(source_path))
    state = flow.set_value(chat_id, user_id, "saved_source_title", str(item.get("title") or "source"))
    flow.set_message_id(chat_id, user_id, query.message.message_id)
    if vahaduo_ui._is_vahaduo_data_only(state):
        state = flow.set_mode(chat_id, user_id, mode, awaiting="")
        await query.edit_message_text(
            vahaduo_ui._g25vahaduo_data_source_text(state),
            reply_markup=vahaduo_ui._build_g25vahaduo_data_source_keyboard(state),
        )
        return
    if mode in {"single", "multi"}:
        try:
            groups = service.list_vahaduo_source_groups(source_path)
        except G25CommandError as exc:
            await query.answer(_vh_error(lang, exc), show_alert=True)
            return
        state = flow.set_value(chat_id, user_id, "saved_source_groups", groups)
        state = flow.set_value(chat_id, user_id, "saved_group_selected", [])
        state = flow.set_mode(chat_id, user_id, mode, awaiting="")
        await query.edit_message_text(
            vahaduo_ui._g25vahaduo_saved_components_text(state, groups, []),
            reply_markup=vahaduo_ui._build_g25vahaduo_saved_components_keyboard(groups, []),
        )
        return
    state = flow.set_mode(chat_id, user_id, mode)
    await query.edit_message_text(vahaduo_ui._g25vahaduo_target_text(state), reply_markup=vahaduo_ui._build_g25vahaduo_target_keyboard(state))


async def _handle_saved_group_action(update: Update, context: ContextTypes.DEFAULT_TYPE, query, action: str, payload: list[str]) -> None:
    if update.effective_chat is None or update.effective_user is None:
        return
    lang = get_user_language(context, update.effective_user.id)
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    flow = _flow_store(context)
    state = flow.get(chat_id, user_id)
    mode = str((state or {}).get("mode") or "")
    if not state or mode not in {"single", "multi"}:
        await query.answer(_vh_text(lang, "Сначала выберите режим Single или Multi."), show_alert=True)
        return
    groups, selected = vahaduo_ui._vahaduo_saved_group_state(state)
    if not groups:
        await query.answer(_vh_text(lang, "Компоненты source больше не найдены. Выберите source заново."), show_alert=True)
        return
    if action.startswith("vahaduo_saved_group_toggle"):
        try:
            group_index = int(payload[0])
        except (IndexError, TypeError, ValueError):
            await query.answer(_vh_text(lang, "Не удалось определить компонент."), show_alert=True)
            return
        if group_index < 0 or group_index >= len(groups):
            await query.answer(_vh_text(lang, "Компонент больше не найден. Выберите source заново."), show_alert=True)
            return
        if group_index in selected:
            selected.remove(group_index)
        else:
            selected.append(group_index)
        selected.sort()
        state = flow.set_value(chat_id, user_id, "saved_group_selected", selected)
    elif action == "vahaduo_saved_group_all":
        selected = list(range(len(groups)))
        state = flow.set_value(chat_id, user_id, "saved_group_selected", selected)
    elif action == "vahaduo_saved_group_clear":
        selected = []
        state = flow.set_value(chat_id, user_id, "saved_group_selected", selected)
    elif action == "vahaduo_saved_group_done":
        if not selected:
            await query.answer(_vh_text(lang, "Сначала выберите хотя бы один компонент."), show_alert=True)
            return
        source_path_value = str(state.get("saved_source_path") or state.get("source_path") or "")
        source_path = Path(source_path_value)
        selected_groups = [str(groups[index].get("key") or "") for index in selected]
        try:
            source_info = _service(context).prepare_vahaduo_saved_single_source(
                source_path,
                selected_groups,
                str(state.get("saved_source_title") or state.get("source_label") or "source"),
                _build_sample_name(update, f"saved_{mode}_{int(state.get('source_saved_id') or 0)}"),
            )
        except G25CommandError as exc:
            await query.answer(_vh_error(lang, exc), show_alert=True)
            return
        state = flow.set_source(
            chat_id,
            user_id,
            source_key=source_info.source_key,
            source_label=source_info.source_label,
            source_path=source_info.references_path,
            source_count=source_info.source_count,
            source_input_mode=source_info.input_mode,
            source_saved_id=int(state.get("source_saved_id") or 0),
            source_manifest_path=source_info.manifest_path,
        )
        state = flow.set_value(chat_id, user_id, "target_back", "vahaduo_saved_components")
        state = flow.set_value(chat_id, user_id, "saved_source_path", source_path_value)
        state = flow.set_value(chat_id, user_id, "saved_group_selected", selected)
        state = flow.set_mode(chat_id, user_id, mode)
        flow.set_message_id(chat_id, user_id, query.message.message_id)
        await query.edit_message_text(vahaduo_ui._g25vahaduo_target_text(state), reply_markup=vahaduo_ui._build_g25vahaduo_target_keyboard(state))
        return
    flow.clear_pending(chat_id, user_id)
    await query.edit_message_text(
        vahaduo_ui._g25vahaduo_saved_components_text(state, groups, selected),
        reply_markup=vahaduo_ui._build_g25vahaduo_saved_components_keyboard(groups, selected),
    )


async def _handle_source_delete(update: Update, context: ContextTypes.DEFAULT_TYPE, query, action: str, payload: list[str]) -> None:
    if update.effective_chat is None or update.effective_user is None:
        return
    lang = get_user_language(context, update.effective_user.id)
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    flow = _flow_store(context)
    state = flow.get(chat_id, user_id)
    mode = str((state or {}).get("mode") or "")
    if action == "vahaduo_delete_confirm":
        try:
            source_id = int(payload[0])
        except (IndexError, TypeError, ValueError):
            await query.answer(_vh_text(lang, "Не удалось определить набор."), show_alert=True)
            return
        deleted = _saved_store(context).delete_for_user(user_id, source_id)
        if state and int(state.get("source_saved_id") or 0) == source_id:
            for key in ("source_key", "source_label", "source_path", "source_manifest_path", "source_input_mode", "saved_source_path", "saved_source_title", "saved_source_groups", "saved_group_selected"):
                flow.set_value(chat_id, user_id, key, "")
            flow.set_value(chat_id, user_id, "source_count", 0)
            flow.set_value(chat_id, user_id, "source_saved_id", 0)
        safe_mode = mode if mode in {"distance", "single", "multi"} else "distance"
        items = _saved_store(context).list_for_user(user_id, safe_mode)
        text = _vh_text(lang, "Набор удален.") + "\n\n" + vahaduo_ui._g25vahaduo_saved_text(items, safe_mode, lang=lang) if deleted else vahaduo_ui._g25vahaduo_saved_text(items, safe_mode, lang=lang)
        await query.edit_message_text(
            text,
            reply_markup=vahaduo_ui._build_g25vahaduo_saved_keyboard(
                items,
                back_action=vahaduo_ui._g25vahaduo_data_back_action(state),
                include_upload=True,
                lang=lang,
            ),
        )
        return
    try:
        source_id = int(payload[0])
    except (IndexError, TypeError, ValueError):
        await query.answer(_vh_text(lang, "Не удалось определить набор."), show_alert=True)
        return
    item = _saved_store(context).get_for_user(user_id, source_id, mode if mode in {"distance", "single", "multi"} else None)
    if not item:
        await query.answer(_vh_text(lang, "Набор уже не найден."), show_alert=True)
        return
    back_action = "vahaduo_data_source" if state and int(state.get("source_saved_id") or 0) == source_id else "vahaduo_saved"
    await query.edit_message_text(
        vahaduo_ui._g25vahaduo_delete_confirm_text(item),
        reply_markup=vahaduo_ui._build_g25vahaduo_delete_confirm_keyboard(source_id, back_action=back_action),
    )


async def _handle_target_select(update: Update, context: ContextTypes.DEFAULT_TYPE, query, payload: list[str], *, for_run: bool) -> None:
    if update.effective_chat is None or update.effective_user is None:
        return
    lang = get_user_language(context, update.effective_user.id)
    try:
        target_id = int(payload[0])
    except (IndexError, TypeError, ValueError):
        await query.answer(_vh_text(lang, "Не удалось определить target."), show_alert=True)
        return
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    flow = _flow_store(context)
    item = _target_store(context).get_for_user(user_id, target_id)
    if not item:
        await query.answer(_vh_text(lang, "Target не найден."), show_alert=True)
        return
    target_path = Path(str(item.get("target_path") or ""))
    if not target_path.exists():
        await query.answer(_vh_text(lang, "Файл target не найден. Удалите target и сохраните заново."), show_alert=True)
        return
    if for_run:
        state = flow.get(chat_id, user_id)
        if not state or not state.get("source_path") or str(state.get("mode") or "") not in {"distance", "single", "multi"}:
            await query.answer(_vh_text(lang, "Сначала выберите режим и source."), show_alert=True)
            return
        await _run_saved_target(update, context, query, state, item)
        return
    state = flow.set_target(
        chat_id,
        user_id,
        target_label=str(item.get("title") or item.get("target_name") or "target"),
        target_path=target_path,
        target_input_mode="saved",
        target_saved_id=target_id,
    )
    flow.set_message_id(chat_id, user_id, query.message.message_id)
    await query.edit_message_text(
        vahaduo_ui._g25vahaduo_data_target_text(state, lang=lang),
        reply_markup=vahaduo_ui._build_g25vahaduo_data_target_keyboard(state, lang=lang),
        parse_mode="HTML",
    )


async def _handle_my_data_target_select(update: Update, context: ContextTypes.DEFAULT_TYPE, query, payload: list[str], *, for_run: bool) -> None:
    if update.effective_chat is None or update.effective_user is None:
        return
    lang = get_user_language(context, update.effective_user.id)
    try:
        target_id = str(payload[0])
    except (IndexError, TypeError, ValueError):
        await query.answer(_vh_text(lang, "Не удалось определить target."), show_alert=True)
        return
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    flow = _flow_store(context)
    item = _my_data_target_item(context, user_id, target_id)
    if not item:
        await query.answer(_vh_text(lang, "Target не найден в My DNA."), show_alert=True)
        return
    if for_run:
        state = flow.get(chat_id, user_id)
        if not state or not state.get("source_path") or str(state.get("mode") or "") not in {"distance", "single", "multi"}:
            await query.answer(_vh_text(lang, "Сначала выберите режим и source."), show_alert=True)
            return
        await _run_saved_target(update, context, query, state, item)
        return
    state = _set_my_data_target_state(flow, chat_id, user_id, item)
    flow.set_message_id(chat_id, user_id, query.message.message_id)
    await query.edit_message_text(
        vahaduo_ui._g25vahaduo_data_target_text(state, lang=lang),
        reply_markup=vahaduo_ui._build_g25vahaduo_data_target_keyboard(state, lang=lang),
        parse_mode="HTML",
    )


async def _handle_target_item_pick(update: Update, context: ContextTypes.DEFAULT_TYPE, query, payload: list[str], *, for_run: bool) -> None:
    if update.effective_chat is None or update.effective_user is None:
        return
    lang = get_user_language(context, update.effective_user.id)
    token = str(payload[0]) if payload else ""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    flow = _flow_store(context)
    state = flow.get(chat_id, user_id)
    item = _target_item_from_state_or_rebuilt(context, user_id, state, token, default_source="other")
    if not item:
        await query.answer(_vh_text(lang, "Список устарел. Откройте «G25-профили» заново."), show_alert=True)
        return
    if for_run:
        if not state or not state.get("source_path") or str(state.get("mode") or "") not in {"distance", "single", "multi"}:
            await query.answer(_vh_text(lang, "Сначала выберите режим и source."), show_alert=True)
            return
        await _run_saved_target(update, context, query, state, item)
        return
    state = _set_my_data_target_state(flow, chat_id, user_id, item)
    flow.set_message_id(chat_id, user_id, query.message.message_id)
    await query.edit_message_text(
        vahaduo_ui._g25vahaduo_data_target_text(state, lang=lang),
        reply_markup=vahaduo_ui._build_g25vahaduo_data_target_keyboard(state, lang=lang),
        parse_mode="HTML",
    )


async def _handle_target_item_delete(update: Update, context: ContextTypes.DEFAULT_TYPE, query, payload: list[str]) -> None:
    if update.effective_chat is None or update.effective_user is None:
        return
    lang = get_user_language(context, update.effective_user.id)
    token = str(payload[0]) if payload else ""
    item = _target_item_from_state_or_rebuilt(
        context,
        update.effective_user.id,
        _flow_store(context).get(update.effective_chat.id, update.effective_user.id),
        token,
        default_source="other",
    )
    if not item:
        await query.answer(_vh_text(lang, "Список устарел. Откройте «G25-профили» заново."), show_alert=True)
        return
    target_id = str(item.get("id") or "")
    await _handle_my_data_target_delete(update, context, query, "vahaduo_mydata_target_delete", [target_id])


async def _handle_sample_target_select(update: Update, context: ContextTypes.DEFAULT_TYPE, query, payload: list[str], *, for_run: bool) -> None:
    if update.effective_chat is None or update.effective_user is None:
        return
    lang = get_user_language(context, update.effective_user.id)
    try:
        target_id = str(payload[0])
    except (IndexError, TypeError, ValueError):
        await query.answer(_vh_text(lang, "Не удалось определить Sample."), show_alert=True)
        return
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    flow = _flow_store(context)
    item = _sample_target_item(context, user_id, target_id)
    if not item:
        await query.answer(_vh_text(lang, "G25 для Sample не найден."), show_alert=True)
        return
    if for_run:
        state = flow.get(chat_id, user_id)
        if not state or not state.get("source_path") or str(state.get("mode") or "") not in {"distance", "single", "multi"}:
            await query.answer(_vh_text(lang, "Сначала выберите режим и source."), show_alert=True)
            return
        await _run_saved_target(update, context, query, state, item)
        return
    state = _set_my_data_target_state(flow, chat_id, user_id, item)
    flow.set_message_id(chat_id, user_id, query.message.message_id)
    await query.edit_message_text(
        vahaduo_ui._g25vahaduo_data_target_text(state, lang=lang),
        reply_markup=vahaduo_ui._build_g25vahaduo_data_target_keyboard(state, lang=lang),
        parse_mode="HTML",
    )


async def _handle_multi_target_action(update: Update, context: ContextTypes.DEFAULT_TYPE, query, action: str, payload: list[str]) -> None:
    if update.effective_chat is None or update.effective_user is None:
        return
    lang = get_user_language(context, update.effective_user.id)
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    flow = _flow_store(context)
    state = flow.get(chat_id, user_id)
    if not state or str(state.get("mode") or "") != "multi":
        await query.answer(_vh_text(lang, "Сначала выберите режим Multi."), show_alert=True)
        return
    target_list_kind = str(state.get("target_list_kind") or "other")
    items = _sample_target_items(context, user_id) if target_list_kind == "samples" else _other_target_items(context, user_id)
    selected_ids = vahaduo_ui._vahaduo_multi_target_selection(state, items)
    if action.startswith("vahaduo_multi_target_toggle"):
        item = _target_item_from_state(state, str(payload[0]) if payload else "")
        if not item:
            await query.answer(_vh_text(lang, "Не удалось определить target."), show_alert=True)
            return
        target_id = str(item.get("id") or "")
        if target_id in selected_ids:
            selected_ids.remove(target_id)
        else:
            selected_ids.append(target_id)
        selected_ids.sort()
    elif action == "vahaduo_multi_target_all":
        selected_ids = [str(item.get("id") or "") for item in items if str(item.get("id") or "")]
    elif action == "vahaduo_multi_target_clear":
        selected_ids = []
    elif action == "vahaduo_multi_target_done":
        if not selected_ids:
            await query.answer(_vh_text(lang, "Сначала выберите хотя бы один target."), show_alert=True)
            return
        selected_items = [item for item in items if str(item.get("id") or "") in set(selected_ids)]
        await _run_saved_multi_targets(update, context, query, state, selected_items)
        return
    state = flow.set_value(chat_id, user_id, "multi_target_selected", selected_ids)
    await query.edit_message_text(
        vahaduo_ui._g25vahaduo_multi_targets_text(items, selected_ids, state=state, source=target_list_kind, lang=lang),
        reply_markup=vahaduo_ui._build_g25vahaduo_multi_targets_keyboard(items, selected_ids, lang=lang),
    )


async def _handle_my_data_target_delete(update: Update, context: ContextTypes.DEFAULT_TYPE, query, action: str, payload: list[str]) -> None:
    if update.effective_chat is None or update.effective_user is None:
        return
    lang = get_user_language(context, update.effective_user.id)
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    flow = _flow_store(context)
    try:
        target_id = str(payload[0])
    except (IndexError, TypeError, ValueError):
        await query.answer(_vh_text(lang, "Не удалось определить target."), show_alert=True)
        return
    if action == "vahaduo_mydata_target_delete_confirm":
        if target_id.startswith("legacy-"):
            try:
                legacy_id = int(target_id.removeprefix("legacy-"))
            except ValueError:
                legacy_id = 0
            deleted = _target_store(context).delete_for_user(user_id, legacy_id) if legacy_id else False
        else:
            deleted = _my_data_store(context).delete_coordinate(user_id, target_id)
        state = flow.get(chat_id, user_id)
        if state and str(state.get("target_coordinate_id") or "") == target_id:
            for key in ("target_label", "target_path", "target_input_mode", "target_line", "target_coordinate_id"):
                flow.set_value(chat_id, user_id, key, "")
            flow.set_value(chat_id, user_id, "target_saved_id", 0)
        items = _other_target_items(context, user_id)
        text = _vh_text(lang, "Target удален.") + "\n\n" + vahaduo_ui._g25vahaduo_targets_text(items, source="other", lang=lang) if deleted else vahaduo_ui._g25vahaduo_targets_text(items, source="other", lang=lang)
        await query.edit_message_text(text, reply_markup=vahaduo_ui._build_g25vahaduo_targets_keyboard(items, source="other", lang=lang), parse_mode="HTML")
        return
    item = _my_data_target_item(context, user_id, target_id)
    if not item:
        await query.answer(_vh_text(lang, "Target уже не найден."), show_alert=True)
        return
    state = flow.get(chat_id, user_id)
    back_action = "vahaduo_data_target" if state and str(state.get("target_coordinate_id") or "") == target_id else "vahaduo_targets"
    await query.edit_message_text(
        vahaduo_ui._g25vahaduo_target_delete_confirm_text(item),
        reply_markup=vahaduo_ui._build_g25vahaduo_mydata_target_delete_confirm_keyboard(target_id, back_action=back_action),
    )


async def _handle_target_delete(update: Update, context: ContextTypes.DEFAULT_TYPE, query, action: str, payload: list[str]) -> None:
    if update.effective_chat is None or update.effective_user is None:
        return
    lang = get_user_language(context, update.effective_user.id)
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    flow = _flow_store(context)
    if action == "vahaduo_target_delete_confirm":
        try:
            target_id = int(payload[0])
        except (IndexError, TypeError, ValueError):
            await query.answer(_vh_text(lang, "Не удалось определить target."), show_alert=True)
            return
        deleted = _target_store(context).delete_for_user(user_id, target_id)
        state = flow.get(chat_id, user_id)
        if state and int(state.get("target_saved_id") or 0) == target_id:
            for key in ("target_label", "target_path", "target_input_mode"):
                flow.set_value(chat_id, user_id, key, "")
            flow.set_value(chat_id, user_id, "target_saved_id", 0)
        items = _target_store(context).list_for_user(user_id)
        text = _vh_text(lang, "Target удален.") + "\n\n" + vahaduo_ui._g25vahaduo_targets_text(items, lang=lang) if deleted else vahaduo_ui._g25vahaduo_targets_text(items, lang=lang)
        await query.edit_message_text(text, reply_markup=vahaduo_ui._build_g25vahaduo_targets_keyboard(items, lang=lang), parse_mode="HTML")
        return
    try:
        target_id = int(payload[0])
    except (IndexError, TypeError, ValueError):
        await query.answer(_vh_text(lang, "Не удалось определить target."), show_alert=True)
        return
    item = _target_store(context).get_for_user(user_id, target_id)
    if not item:
        await query.answer(_vh_text(lang, "Target уже не найден."), show_alert=True)
        return
    state = flow.get(chat_id, user_id)
    back_action = "vahaduo_data_target" if state and int(state.get("target_saved_id") or 0) == target_id else "vahaduo_targets"
    await query.edit_message_text(
        vahaduo_ui._g25vahaduo_target_delete_confirm_text(item),
        reply_markup=vahaduo_ui._build_g25vahaduo_target_delete_confirm_keyboard(target_id, back_action=back_action),
    )


async def _run_saved_target(update: Update, context: ContextTypes.DEFAULT_TYPE, query, state: dict[str, object], item: dict[str, object]) -> None:
    if update.effective_chat is None or update.effective_user is None or query.message is None:
        return
    lang = get_user_language(context, update.effective_user.id)
    flow = _flow_store(context)
    mode = str(state.get("mode") or "")
    try:
        source_key, source_label, source_path, manifest_path = _source_from_state(state)
        target_body = _target_body_from_item(item)
        if not target_body:
            raise G25CommandError(_vh_text(lang, "Сохраненный target пустой."))
        sample_name = _target_label_from_item(item)
        if mode == "distance":
            result = _service(context).run_vahaduo_distance_from_text(source_key, source_label, source_path, target_body, sample_name)
        elif mode == "multi":
            result = _service(context).run_vahaduo_multi_from_text(source_key, source_label, source_path, target_body, sample_name, source_manifest_path=manifest_path)
        else:
            result = _service(context).run_vahaduo_single_from_text(source_key, source_label, source_path, target_body, sample_name, source_manifest_path=manifest_path)
    except G25CommandError as exc:
        _record_g25_usage(update, context, mode=mode, input_mode="saved", success=False, query=str(item.get("title") or "saved-target"))
        await query.message.reply_text(_vh_error(lang, exc), do_quote=False)
        return
    except Exception:
        logger.exception("Vahaduo saved target failed")
        _record_g25_usage(update, context, mode=mode, input_mode="saved", success=False, query=str(item.get("title") or "saved-target"))
        await query.message.reply_text(_vh_text(lang, "Не удалось обработать сохраненный target. Проверьте G25-координаты и попробуйте еще раз."), do_quote=False)
        return
    if str(item.get("g25_line") or "").strip():
        _set_my_data_target_state(flow, update.effective_chat.id, update.effective_user.id, item)
    else:
        flow.set_target(
            update.effective_chat.id,
            update.effective_user.id,
            target_label=str(item.get("title") or result.target_name),
            target_path=Path(str(item.get("target_path") or "")),
            target_input_mode="saved",
            target_saved_id=int(item.get("id") or 0),
        )
    if mode == "distance":
        source_kind = str(state.get("target_list_kind") or "other")
        flow.set_value(update.effective_chat.id, update.effective_user.id, "result_back", "targets")
        flow.set_value(update.effective_chat.id, update.effective_user.id, "result_back_source", source_kind if source_kind in {"samples", "other"} else "other")
        sent = await _send_distance_result_photo_from_query(query=query, state=flow.get(update.effective_chat.id, update.effective_user.id) or state, result=result, lang=lang)
        if sent is None:
            return
        if getattr(sent, "message_id", None) is not None:
            flow.set_message_id(update.effective_chat.id, update.effective_user.id, int(sent.message_id))
            set_active_main_menu_message(context, update.effective_chat.id, update.effective_user.id, int(sent.message_id))
        flow.clear_pending(update.effective_chat.id, update.effective_user.id)
        _record_g25_usage(update, context, mode=mode, input_mode=getattr(result, "input_mode", "saved"), success=True, query=result.target_name)
        return
    if mode == "single":
        source_kind = str(state.get("target_list_kind") or "other")
        flow.set_value(update.effective_chat.id, update.effective_user.id, "result_back", "targets")
        flow.set_value(update.effective_chat.id, update.effective_user.id, "result_back_source", source_kind if source_kind in {"samples", "other"} else "other")
        sent = await _send_single_result_photo_from_query(query=query, state=flow.get(update.effective_chat.id, update.effective_user.id) or state, result=result, lang=lang)
        if sent is None:
            return
        if getattr(sent, "message_id", None) is not None:
            flow.set_message_id(update.effective_chat.id, update.effective_user.id, int(sent.message_id))
            set_active_main_menu_message(context, update.effective_chat.id, update.effective_user.id, int(sent.message_id))
        flow.clear_pending(update.effective_chat.id, update.effective_user.id)
        _record_g25_usage(update, context, mode=mode, input_mode=getattr(result, "input_mode", "saved"), success=True, query=result.target_name)
        return
    if mode == "multi":
        source_kind = str(state.get("target_list_kind") or "other")
        flow.set_value(update.effective_chat.id, update.effective_user.id, "result_back", "targets")
        flow.set_value(update.effective_chat.id, update.effective_user.id, "result_back_source", source_kind if source_kind in {"samples", "other"} else "other")
        sent = await _send_multi_result_photo_from_query(query=query, state=flow.get(update.effective_chat.id, update.effective_user.id) or state, result=result, lang=lang)
        if sent is None:
            return
        if getattr(sent, "message_id", None) is not None:
            flow.set_message_id(update.effective_chat.id, update.effective_user.id, int(sent.message_id))
            set_active_main_menu_message(context, update.effective_chat.id, update.effective_user.id, int(sent.message_id))
        flow.clear_pending(update.effective_chat.id, update.effective_user.id)
    _record_g25_usage(update, context, mode=mode, input_mode=getattr(result, "input_mode", "saved"), success=True, query=result.target_name)


async def _run_saved_multi_targets(update: Update, context: ContextTypes.DEFAULT_TYPE, query, state: dict[str, object], items: list[dict[str, object]]) -> None:
    if update.effective_chat is None or update.effective_user is None or query.message is None:
        return
    lang = get_user_language(context, update.effective_user.id)
    try:
        source_key, source_label, source_path, manifest_path = _source_from_state(state)
        target_lines: list[str] = []
        for item in items:
            body = _target_body_from_item(item)
            lines = [line.strip() for line in body.splitlines() if line.strip()]
            if not lines:
                raise G25CommandError(_vh_text(lang, "Один из сохраненных target пустой. Сохраните его заново."))
            target_lines.extend(lines)
        result = _service(context).run_vahaduo_multi_from_text(
            source_key,
            source_label,
            source_path,
            "\n".join(target_lines),
            _build_sample_name(update, "multi_targets"),
            source_manifest_path=manifest_path,
        )
    except G25CommandError as exc:
        _record_g25_usage(update, context, mode="multi", input_mode="saved", success=False, query="multi_targets")
        await query.message.reply_text(_vh_error(lang, exc), do_quote=False)
        return
    except Exception:
        logger.exception("Vahaduo saved multi-target run failed")
        _record_g25_usage(update, context, mode="multi", input_mode="saved", success=False, query="multi_targets")
        await query.message.reply_text(_vh_text(lang, "Не удалось обработать выбранные target. Проверьте сохраненные координаты и попробуйте еще раз."), do_quote=False)
        return
    flow = _flow_store(context)
    selected_ids = [str(item.get("id") or "") for item in items if str(item.get("id") or "")]
    flow.set_value(update.effective_chat.id, update.effective_user.id, "multi_target_selected", selected_ids)
    source_kind = str(state.get("target_list_kind") or "other")
    flow.set_value(update.effective_chat.id, update.effective_user.id, "result_back", "targets")
    flow.set_value(update.effective_chat.id, update.effective_user.id, "result_back_source", source_kind if source_kind in {"samples", "other"} else "other")
    sent = await _send_multi_result_photo_from_query(query=query, state=flow.get(update.effective_chat.id, update.effective_user.id) or state, result=result, lang=lang)
    if sent is None:
        return
    if getattr(sent, "message_id", None) is not None:
        flow.set_message_id(update.effective_chat.id, update.effective_user.id, int(sent.message_id))
        set_active_main_menu_message(context, update.effective_chat.id, update.effective_user.id, int(sent.message_id))
    flow.clear_pending(update.effective_chat.id, update.effective_user.id)
    _record_g25_usage(update, context, mode="multi", input_mode="saved", success=True, query=result.target_name)


async def _run_target_save_name_input(update: Update, context: ContextTypes.DEFAULT_TYPE, title: str) -> None:
    if update.message is None or update.effective_chat is None or update.effective_user is None:
        return
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    lang = get_user_language(context, user_id)
    flow = _flow_store(context)
    state = flow.get(chat_id, user_id)
    if not state:
        await update.message.reply_text(_vh_text(lang, "Сначала добавьте target в Vahaduo Lab."), do_quote=False)
        raise ApplicationHandlerStop
    try:
        target_line = str(state.get("target_line") or "").strip()
        target_path = Path(str(state.get("target_path") or ""))
        if not target_line and target_path.exists():
            target_line = target_path.read_text(encoding="utf-8").strip()
        if not target_line:
            raise ValueError(_vh_text(lang, "Target пустой или файл больше не найден."))
        saved = _my_data_store(context).save_coordinate(
            user_id,
            display_name=title,
            target_name=str(state.get("target_label") or title),
            coordinate_type="g25",
            g25_line=target_line,
            input_mode=str(state.get("target_input_mode") or "vahaduo"),
        )
    except ValueError as exc:
        await update.message.reply_text(_vh_error(lang, exc), do_quote=False)
        raise ApplicationHandlerStop
    state = _set_my_data_target_state(
        flow,
        chat_id,
        user_id,
        {
            "id": saved.asset_id,
            "title": saved.display_name,
            "target_name": saved.target_name,
            "g25_line": saved.g25_line,
            "target_input_mode": saved.input_mode,
        },
    )
    sent = await _reply_with_active_menu(
        update,
        context,
        vahaduo_ui._g25vahaduo_data_target_text(state, _vh_text(lang, "Target сохранен."), lang=lang),
        vahaduo_ui._build_g25vahaduo_data_target_keyboard(state, lang=lang),
        parse_mode="HTML",
    )
    if sent is not None:
        flow.set_message_id(chat_id, user_id, sent.message_id)
    raise ApplicationHandlerStop


async def _run_target_data_input(update: Update, context: ContextTypes.DEFAULT_TYPE, body: str = "") -> None:
    if update.message is None or update.effective_chat is None or update.effective_user is None:
        return
    service = _service(context)
    flow = _flow_store(context)
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    lang = get_user_language(context, user_id)
    document = update.message.document
    status_message = None
    try:
        if document is not None:
            status_message = await update.message.reply_text(_vh_text(lang, "Target получен, проверяю G25..."), do_quote=False)
            file_name = document.file_name or "target.txt"
            sample_name = _build_sample_name(update, Path(file_name).stem)
            temp_dir = service.create_run_dir("vahaduo_target_upload", sample_name)
            input_path = temp_dir / file_name
            telegram_file = await document.get_file()
            await telegram_file.download_to_drive(custom_path=str(input_path))
            coords_result = service.extract_coordinates_from_file(input_path, sample_name)
        else:
            sample_name = _build_sample_name(update, "target")
            coords_result = service.extract_coordinates_from_text(body, sample_name)
    except G25CommandError as exc:
        await update.message.reply_text(_vh_error(lang, exc), do_quote=False)
        raise ApplicationHandlerStop
    except Exception:
        logger.exception("Vahaduo target data input failed")
        await update.message.reply_text(_vh_text(lang, "Не удалось обработать target. Проверьте файл или G25-координаты и попробуйте еще раз."), do_quote=False)
        raise ApplicationHandlerStop
    saved = _my_data_store(context).save_coordinate(
        user_id,
        display_name=coords_result.target_name,
        target_name=coords_result.target_name,
        coordinate_type="g25",
        g25_line=coords_result.simulated_g25_line,
        input_mode=coords_result.input_mode,
    )
    state = _set_my_data_target_state(
        flow,
        chat_id,
        user_id,
        {
            "id": saved.asset_id,
            "title": saved.display_name,
            "target_name": saved.target_name,
            "g25_line": saved.g25_line,
            "target_input_mode": saved.input_mode,
        },
    )
    sent = await _reply_with_active_menu(
        update,
        context,
        vahaduo_ui._g25vahaduo_data_target_text(state, _vh_text(lang, "Target сохранен."), lang=lang),
        vahaduo_ui._build_g25vahaduo_data_target_keyboard(state, lang=lang),
        parse_mode="HTML",
    )
    if sent is not None:
        flow.set_message_id(chat_id, user_id, sent.message_id)
    if status_message is not None:
        await status_message.edit_text(_vh_text(lang, "Target сохранен."))
    raise ApplicationHandlerStop


async def _run_source_save_name_input(update: Update, context: ContextTypes.DEFAULT_TYPE, title: str) -> None:
    if update.message is None or update.effective_chat is None or update.effective_user is None:
        return
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    lang = get_user_language(context, user_id)
    flow = _flow_store(context)
    state = flow.get(chat_id, user_id)
    if not state:
        await update.message.reply_text(_vh_text(lang, "Сначала загрузите source в Vahaduo Lab."), do_quote=False)
        raise ApplicationHandlerStop
    try:
        saved = _saved_store(context).save_for_user(
            update,
            title=title,
            source_path=Path(str(state.get("source_path") or "")),
            source_count=int(state.get("source_count") or 0),
            source_label=str(state.get("source_label") or "source"),
            source_input_mode=str(state.get("source_input_mode") or ""),
            source_kind=str(state.get("mode") or "both"),
        )
    except ValueError as exc:
        await update.message.reply_text(_vh_error(lang, exc), do_quote=False)
        raise ApplicationHandlerStop
    state = flow.mark_source_saved(chat_id, user_id, int(saved["id"]), str(saved["title"]), Path(str(saved["source_path"])))
    if vahaduo_ui._is_vahaduo_data_only(state):
        state = flow.set_mode(chat_id, user_id, str(state.get("mode") or "distance"), awaiting="")
        text = vahaduo_ui._g25vahaduo_data_source_text(state, _vh_text(lang, "Набор сохранен."), lang=lang)
        markup = vahaduo_ui._build_g25vahaduo_data_source_keyboard(state, lang=lang)
    else:
        text = _vh_text(lang, "Набор сохранен.") + "\n\n" + vahaduo_ui._g25vahaduo_target_text(state, lang=lang)
        markup = vahaduo_ui._build_g25vahaduo_target_keyboard(state, lang=lang)
    sent = await _reply_with_active_menu(update, context, text, markup)
    if sent is not None:
        flow.set_message_id(chat_id, user_id, sent.message_id)
    raise ApplicationHandlerStop


async def _run_source_input(update: Update, context: ContextTypes.DEFAULT_TYPE, body: str = "") -> None:
    if update.message is None or update.effective_chat is None or update.effective_user is None:
        return
    service = _service(context)
    flow = _flow_store(context)
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    lang = get_user_language(context, user_id)
    document = update.message.document
    status_message = None
    try:
        if document is not None:
            status_message = await update.message.reply_text(_vh_text(lang, "Source получен, проверяю строки G25..."), do_quote=False)
            file_name = document.file_name or "source.txt"
            sample_name = _build_sample_name(update, Path(file_name).stem)
            temp_dir = service.create_run_dir("vahaduo_source_upload", sample_name)
            input_path = temp_dir / file_name
            telegram_file = await document.get_file()
            await telegram_file.download_to_drive(custom_path=str(input_path))
            source_info = service.prepare_vahaduo_source_from_file(input_path, sample_name)
        else:
            sample_name = _build_sample_name(update, "source")
            source_info = service.prepare_vahaduo_source_from_text(body, sample_name)
    except G25CommandError as exc:
        await update.message.reply_text(_vh_error(lang, exc), do_quote=False)
        raise ApplicationHandlerStop
    except Exception:
        logger.exception("Vahaduo source input failed")
        await update.message.reply_text(_vh_text(lang, "Не удалось обработать source. Проверьте формат строк G25 и попробуйте еще раз."), do_quote=False)
        raise ApplicationHandlerStop
    state = flow.set_source(
        chat_id,
        user_id,
        source_key=source_info.source_key,
        source_label=source_info.source_label,
        source_path=source_info.references_path,
        source_count=source_info.source_count,
        source_input_mode=source_info.input_mode,
        source_manifest_path=source_info.manifest_path,
    )
    source_input_mode = str(state.get("source_input_mode") or "")
    target_back = "vahaduo_source_file" if source_input_mode == "source-file" else ("vahaduo_source_text" if source_input_mode == "source-text" else "vahaduo_sources")
    state = flow.set_value(chat_id, user_id, "target_back", target_back)
    mode = str(state.get("mode") or "")
    data_only = vahaduo_ui._is_vahaduo_data_only(state)
    if mode in {"distance", "single", "multi"}:
        state = flow.set_mode(chat_id, user_id, mode, awaiting=("" if data_only else "target"))
    if data_only:
        saved = _saved_store(context).save_for_user(
            update,
            title=str(source_info.source_label or "source"),
            source_path=source_info.references_path,
            source_count=source_info.source_count,
            source_label=source_info.source_label,
            source_input_mode=source_info.input_mode,
            source_kind=mode if mode in {"distance", "single", "multi"} else "both",
        )
        state = flow.mark_source_saved(chat_id, user_id, int(saved["id"]), str(saved["title"]), Path(str(saved["source_path"])))
        state = flow.set_mode(chat_id, user_id, mode if mode in {"distance", "single", "multi"} else str(state.get("mode") or "distance"), awaiting="")
        text = vahaduo_ui._g25vahaduo_data_source_text(state, _vh_text(lang, "Набор сохранен."), lang=lang)
        markup = vahaduo_ui._build_g25vahaduo_data_source_keyboard(state, lang=lang)
    else:
        text = vahaduo_ui._g25vahaduo_target_text(state, lang=lang)
        markup = vahaduo_ui._build_g25vahaduo_target_keyboard(state, lang=lang)
    sent = await _reply_with_active_menu(update, context, text, markup)
    if sent is not None:
        flow.set_message_id(chat_id, user_id, sent.message_id)
    if status_message is not None:
        await status_message.edit_text(_vh_text(lang, "Source готов."))
    raise ApplicationHandlerStop


async def _run_target_input(update: Update, context: ContextTypes.DEFAULT_TYPE, body: str = "") -> None:
    if update.message is None or update.effective_chat is None or update.effective_user is None:
        return
    service = _service(context)
    flow = _flow_store(context)
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    lang = get_user_language(context, user_id)
    state = flow.get(chat_id, user_id)
    mode = str((state or {}).get("mode") or "")
    document = update.message.document
    try:
        if not state or mode not in {"distance", "single", "multi"}:
            raise G25CommandError(_vh_text(lang, "Сначала выберите режим и source."))
        source_key, source_label, source_path, manifest_path = _source_from_state(state)
        if document is not None:
            file_name = document.file_name or "target.txt"
            sample_name = _build_sample_name(update, Path(file_name).stem)
            temp_dir = service.create_run_dir(f"vahaduo_{mode}_input", sample_name)
            input_path = temp_dir / file_name
            telegram_file = await document.get_file()
            await telegram_file.download_to_drive(custom_path=str(input_path))
            if mode == "distance":
                result = service.run_vahaduo_distance_from_file(source_key, source_label, source_path, input_path, sample_name)
            elif mode == "multi":
                result = service.run_vahaduo_multi_from_file(source_key, source_label, source_path, input_path, sample_name, source_manifest_path=manifest_path)
            else:
                result = service.run_vahaduo_single_from_file(source_key, source_label, source_path, input_path, sample_name, source_manifest_path=manifest_path)
        else:
            sample_name = _build_sample_name(update)
            if mode == "distance":
                result = service.run_vahaduo_distance_from_text(source_key, source_label, source_path, body, sample_name)
            elif mode == "multi":
                result = service.run_vahaduo_multi_from_text(source_key, source_label, source_path, body, sample_name, source_manifest_path=manifest_path)
            else:
                result = service.run_vahaduo_single_from_text(source_key, source_label, source_path, body, sample_name, source_manifest_path=manifest_path)
    except G25CommandError as exc:
        _record_g25_usage(
            update,
            context,
            mode=mode,
            input_mode="g25-file" if document is not None else "g25-text",
            success=False,
            query=_build_sample_name(update),
        )
        await update.message.reply_text(_vh_error(lang, exc), do_quote=False)
        raise ApplicationHandlerStop
    except Exception:
        logger.exception("Vahaduo target run failed")
        _record_g25_usage(
            update,
            context,
            mode=mode,
            input_mode="g25-file" if document is not None else "g25-text",
            success=False,
            query=_build_sample_name(update),
        )
        await update.message.reply_text(_vh_text(lang, "Не удалось обработать target. Проверьте файл или G25-координаты и попробуйте еще раз."), do_quote=False)
        raise ApplicationHandlerStop
    if mode == "distance":
        flow.set_value(chat_id, user_id, "result_back", "target")
        sent = await _send_distance_result_photo_from_message(message=update.message, state=flow.get(chat_id, user_id) or state, result=result, lang=lang)
        if sent is None:
            raise ApplicationHandlerStop
        if getattr(sent, "message_id", None) is not None:
            flow.set_message_id(chat_id, user_id, int(sent.message_id))
            set_active_main_menu_message(context, chat_id, user_id, int(sent.message_id))
        flow.clear_pending(chat_id, user_id)
        _record_g25_usage(update, context, mode=mode, input_mode=getattr(result, "input_mode", "g25-text"), success=True, query=result.target_name)
        raise ApplicationHandlerStop
    if mode == "single":
        flow.set_value(chat_id, user_id, "result_back", "target")
        sent = await _send_single_result_photo_from_message(message=update.message, state=flow.get(chat_id, user_id) or state, result=result, lang=lang)
        if sent is None:
            raise ApplicationHandlerStop
        if getattr(sent, "message_id", None) is not None:
            flow.set_message_id(chat_id, user_id, int(sent.message_id))
            set_active_main_menu_message(context, chat_id, user_id, int(sent.message_id))
        flow.clear_pending(chat_id, user_id)
        _record_g25_usage(update, context, mode=mode, input_mode=getattr(result, "input_mode", "g25-text"), success=True, query=result.target_name)
        raise ApplicationHandlerStop
    flow.set_value(chat_id, user_id, "result_back", "target")
    sent = await _send_multi_result_photo_from_message(message=update.message, state=flow.get(chat_id, user_id) or state, result=result, lang=lang)
    if sent is None:
        raise ApplicationHandlerStop
    if getattr(sent, "message_id", None) is not None:
        flow.set_message_id(chat_id, user_id, int(sent.message_id))
        set_active_main_menu_message(context, chat_id, user_id, int(sent.message_id))
    flow.clear_pending(chat_id, user_id)
    _record_g25_usage(update, context, mode=mode, input_mode=getattr(result, "input_mode", "g25-text"), success=True, query=result.target_name)
    raise ApplicationHandlerStop


async def vahaduo_document_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.effective_chat is None or update.effective_user is None:
        return
    flow = _flow_store(context)
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    if flow.has_pending(chat_id, user_id, "source"):
        await _run_source_input(update, context)
    if flow.has_pending(chat_id, user_id, "target_data"):
        await _run_target_data_input(update, context)
    if flow.has_pending(chat_id, user_id, "target"):
        await _run_target_input(update, context)


async def vahaduo_text_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.effective_chat is None or update.effective_user is None:
        return
    body = (update.message.text or "").strip()
    if not body:
        return
    flow = _flow_store(context)
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    if flow.has_pending(chat_id, user_id, "target_save_name"):
        await _run_target_save_name_input(update, context, body)
    if flow.has_pending(chat_id, user_id, "save_name"):
        await _run_source_save_name_input(update, context, body)
    if flow.has_pending(chat_id, user_id, "source"):
        await _run_source_input(update, context, body=body)
    if flow.has_pending(chat_id, user_id, "target_data"):
        await _run_target_data_input(update, context, body=body)
    if flow.has_pending(chat_id, user_id, "target"):
        await _run_target_input(update, context, body=body)
