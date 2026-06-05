from __future__ import annotations

import html
import tempfile
from math import ceil
from pathlib import Path
from uuid import uuid4

from telegram import InlineKeyboardButton, Update
from telegram.ext import Application, ContextTypes

from g25_core.command_service import G25CommandError, G25CommandService

from app.features.my_data.storage import CoordinateAsset, MyDataStore, SampleAsset
from app.i18n import get_user_language, t
from app.main_menu import ensure_active_main_menu, set_active_main_menu_message

from .domain import build_k36_profile, compare_admixture_payloads, profile_to_payload, run_raw_admixture_model
from .model_catalog import RawAdmixtureModel, RawAdmixtureProject, get_raw_admixture_model, list_raw_admixture_models
from .model_catalog import get_raw_admixture_project, list_raw_admixture_projects
from .oracle import available_oracle_models, load_oracle_references, oracle_reference_dir, similar_populations, three_way_oracle_mixes, two_way_oracle_mixes
from .storage import AdmixtureReportStore
from .ui import (
    admixture_root_text,
    build_markup,
    compare_profiles_text,
    compare_project_models_text,
    compare_report_button_label,
    compare_report_picker_text,
    compare_result_text,
    compare_visual_caption,
    error_text,
    extracting_k36_text,
    k36_sample_picker_text,
    k36_coordinate_picker_text,
    oracle_project_models_text,
    oracle_projects_text,
    oracle_mix_project_models_text,
    oracle_mix_projects_text,
    oracle_mix_mode_text,
    oracle_mix_report_picker_text,
    oracle_mix_report_button_label,
    oracle_mix_result_text,
    oracle_mix_visual_caption,
    oracle_report_picker_text,
    oracle_result_text,
    oracle_visual_caption,
    placeholder_feature_text,
    profile_preview_text,
    profile_visual_caption,
    raw_calculators_text,
    raw_model_detail_text,
    raw_model_sample_picker_text,
    raw_project_models_text,
    report_button_label,
    report_detail_text,
    report_detail_visual_caption,
    report_saved_text,
    saved_report_visual_caption,
    running_k36_text,
    sample_admixture_reports_text,
    similar_report_button_label,
)
from .visualization import (
    render_compare_png,
    render_oracle_mix_png,
    render_oracle_png,
    render_profile_png,
)


ADMIXTURE_CALLBACK_PREFIX = "admixture"
_PAGE_SIZE = 8


def _copy(lang: str, ru: str, en: str) -> str:
    return en if lang == "en" else ru


def _next_label(lang: str) -> str:
    return _copy(lang, "Показать ещё", "Show more")


class AdmixtureFlowStore:
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


def register_admixture_services(application: Application, settings) -> None:
    application.bot_data["admixture_report_store"] = AdmixtureReportStore(settings.root_dir / "storage" / "admixture")
    application.bot_data["admixture_flow_store"] = AdmixtureFlowStore()
    application.bot_data["admixture_data_dir"] = settings.root_dir / "g25_core" / "vendor" / "admix" / "data"
    application.bot_data["admixture_oracle_reference_dir"] = oracle_reference_dir(settings.root_dir)
    if "pca_service" not in application.bot_data:
        application.bot_data["pca_service"] = G25CommandService(settings.root_dir / "g25_core")


def _my_data_store(context: ContextTypes.DEFAULT_TYPE) -> MyDataStore:
    return context.application.bot_data["my_data_store"]


def _report_store(context: ContextTypes.DEFAULT_TYPE) -> AdmixtureReportStore:
    store = context.application.bot_data.get("admixture_report_store")
    if isinstance(store, AdmixtureReportStore):
        return store
    store = AdmixtureReportStore(context.application.bot_data["my_data_store"].root_dir.parent / "admixture")
    context.application.bot_data["admixture_report_store"] = store
    return store


def _g25_service(context: ContextTypes.DEFAULT_TYPE) -> G25CommandService:
    return context.application.bot_data["pca_service"]


def _flow_store(context: ContextTypes.DEFAULT_TYPE) -> AdmixtureFlowStore:
    store = context.application.bot_data.get("admixture_flow_store")
    if isinstance(store, AdmixtureFlowStore):
        return store
    store = AdmixtureFlowStore()
    context.application.bot_data["admixture_flow_store"] = store
    return store


def _admixture_data_dir(context: ContextTypes.DEFAULT_TYPE) -> Path:
    value = context.application.bot_data.get("admixture_data_dir")
    if isinstance(value, Path):
        return value
    return Path(__file__).resolve().parents[3] / "g25_core" / "vendor" / "admix" / "data"


def _oracle_reference_dir(context: ContextTypes.DEFAULT_TYPE) -> Path:
    value = context.application.bot_data.get("admixture_oracle_reference_dir")
    if isinstance(value, Path):
        return value
    return Path(__file__).resolve().parents[3] / "g25_core" / "vendor" / "admix" / "oracle_references"


def _raw_models(context: ContextTypes.DEFAULT_TYPE) -> list[RawAdmixtureModel]:
    return list_raw_admixture_models(_admixture_data_dir(context))


def _raw_projects(context: ContextTypes.DEFAULT_TYPE):
    return list_raw_admixture_projects(_admixture_data_dir(context))


def _compare_model_counts(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> dict[str, int]:
    counts: dict[str, int] = {}
    for report in _report_store(context).list_all_reports(user_id):
        counts[report.model] = counts.get(report.model, 0) + 1
    return counts


def _project_compare_model_counts(project: RawAdmixtureProject, counts: dict[str, int]) -> list[tuple[str, int]]:
    return [(model.name, counts[model.name]) for model in project.models if counts.get(model.name, 0) >= 2]


def _model_project_code(context: ContextTypes.DEFAULT_TYPE, model_name: str) -> str | None:
    for project in _raw_projects(context):
        if any(model.name == model_name for model in project.models):
            return project.code
    return None


def _oracle_model_counts(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> dict[str, int]:
    available = available_oracle_models(_oracle_reference_dir(context))
    counts: dict[str, int] = {model: 0 for model in available}
    for report in _report_store(context).list_all_reports(user_id):
        if report.model in available:
            counts[report.model] = counts.get(report.model, 0) + 1
    return counts


def _project_oracle_model_counts(project: RawAdmixtureProject, counts: dict[str, int]) -> list[tuple[str, int]]:
    available = set(counts)
    return [(model.name, counts.get(model.name, 0)) for model in project.models if model.name in available]


def _oracle_mix_mode_label(mode: str) -> str:
    return "3-way" if mode == "3" else "2-way"


def _paginate(items: list[object], page: int) -> tuple[list[object], int, int]:
    total_pages = max(1, ceil(len(items) / _PAGE_SIZE)) if items else 1
    normalized_page = max(0, min(page, total_pages - 1))
    start = normalized_page * _PAGE_SIZE
    return items[start:start + _PAGE_SIZE], normalized_page, total_pages


def _k36_coordinates(context: ContextTypes.DEFAULT_TYPE, user_id: int, sample: SampleAsset) -> list[CoordinateAsset]:
    return [
        item
        for item in _my_data_store(context).list_sample_coordinates(user_id, sample.asset_id)
        if item.coordinate_type.strip().lower() == "k36"
    ]


def _sample_admixture_reports_for_origin(
    reports,
    *,
    origin: str,
):
    if origin == "my_data":
        return list(reports)
    return [report for report in reports if report.model == "K36"]


def _raw_model_coordinate_id(raw_file_id: str, model_name: str) -> str:
    return f"raw:{raw_file_id}:{model_name}"


def _raw_model_button_label(model: RawAdmixtureModel) -> str:
    return model.name if model.installed else f"{model.name} (not installed)"


def _report_button_text(report) -> str:
    return f"{report.sample_name}: {report_button_label(report)}"


def _create_visualization_path() -> Path:
    return Path(tempfile.gettempdir()) / f"dna_admixture_{uuid4().hex}.png"


def _is_photo_message(message) -> bool:
    return bool(getattr(message, "photo", None))


def _message_chat_id(message) -> int | None:
    chat_id = getattr(message, "chat_id", None)
    if chat_id is not None:
        return int(chat_id)
    chat = getattr(message, "chat", None)
    if chat is not None and getattr(chat, "id", None) is not None:
        return int(chat.id)
    return None


async def _clear_old_visual_markup(message) -> None:
    try:
        await message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass


async def _delete_old_status_message(message) -> None:
    if _is_photo_message(message):
        await _clear_old_visual_markup(message)
        return
    try:
        await message.delete()
    except Exception:
        pass


async def _show_status_message(message, text_value: str):
    if _is_photo_message(message):
        status_message = await message.reply_text(text_value, parse_mode="HTML", do_quote=False)
        await _clear_old_visual_markup(message)
        return status_message
    await message.edit_text(text_value, parse_mode="HTML")
    return message


async def _send_visual_or_fallback(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    image_path: Path,
    caption: str,
    fallback_text: str,
    reply_markup,
    edit_existing: bool = False,
) -> None:
    try:
        with image_path.open("rb") as handle:
            sent = await message.reply_photo(
                photo=handle,
                caption=caption,
                reply_markup=reply_markup,
                parse_mode="HTML",
                do_quote=False,
            )
        chat_id = _message_chat_id(sent)
        if chat_id is not None:
            set_active_main_menu_message(context, chat_id, user_id, sent.message_id)
        await _delete_old_status_message(message)
    except Exception:
        if edit_existing and not _is_photo_message(message):
            await message.edit_text(fallback_text, reply_markup=reply_markup, parse_mode="HTML")
        else:
            sent = await message.reply_text(fallback_text, reply_markup=reply_markup, parse_mode="HTML", do_quote=False)
            chat_id = _message_chat_id(sent)
            if chat_id is not None:
                set_active_main_menu_message(context, chat_id, user_id, sent.message_id)
            await _clear_old_visual_markup(message)
    finally:
        try:
            image_path.unlink()
        except FileNotFoundError:
            pass


async def _show_or_edit(
    message,
    text_value: str,
    reply_markup,
    *,
    edit_existing: bool = False,
    context: ContextTypes.DEFAULT_TYPE | None = None,
    user_id: int | None = None,
) -> None:
    if edit_existing:
        if _is_photo_message(message):
            sent = await message.reply_text(text_value, reply_markup=reply_markup, parse_mode="HTML", do_quote=False)
            chat_id = _message_chat_id(sent)
            if context is not None and user_id is not None and chat_id is not None:
                set_active_main_menu_message(context, chat_id, user_id, sent.message_id)
            await _clear_old_visual_markup(message)
            return
        await message.edit_text(text_value, reply_markup=reply_markup, parse_mode="HTML")
    else:
        sent = await message.reply_text(text_value, reply_markup=reply_markup, parse_mode="HTML", do_quote=False)
        chat_id = _message_chat_id(sent)
        if context is not None and user_id is not None and chat_id is not None:
            set_active_main_menu_message(context, chat_id, user_id, sent.message_id)


async def _show_profile_visual(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    sample_name: str,
    coordinate_name: str,
    payload: dict[str, object],
    caption: str,
    fallback_text: str,
    reply_markup,
    status_label: str = "PROFILE",
    edit_existing: bool = True,
) -> None:
    image_path = _create_visualization_path()
    try:
        render_profile_png(
            image_path,
            sample_name=sample_name,
            coordinate_name=coordinate_name,
            payload=payload,
            status_label=status_label,
        )
    except Exception:
        try:
            image_path.unlink()
        except FileNotFoundError:
            pass
        if edit_existing and not _is_photo_message(message):
            await message.edit_text(fallback_text, reply_markup=reply_markup, parse_mode="HTML")
        else:
            await _show_or_edit(
                message,
                fallback_text,
                reply_markup,
                edit_existing=edit_existing,
                context=context,
                user_id=user_id,
            )
        return
    await _send_visual_or_fallback(
        message,
        context,
        user_id,
        image_path=image_path,
        caption=caption,
        fallback_text=fallback_text,
        reply_markup=reply_markup,
        edit_existing=edit_existing,
    )


async def show_admixture_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    lang: str | None = None,
    edit_existing: bool = False,
) -> None:
    lang = lang or get_user_language(context, user_id)
    rows = [
        [InlineKeyboardButton("🧮 Raw calculators", callback_data=f"{ADMIXTURE_CALLBACK_PREFIX}:cal")],
        [InlineKeyboardButton("⚖️ Compare profiles", callback_data=f"{ADMIXTURE_CALLBACK_PREFIX}:cmp")],
        [InlineKeyboardButton("🧭 Similar populations", callback_data=f"{ADMIXTURE_CALLBACK_PREFIX}:op")],
        [InlineKeyboardButton("🧬 Oracle mix", callback_data=f"{ADMIXTURE_CALLBACK_PREFIX}:omix")],
        [InlineKeyboardButton("🎨 Chromosome painting", callback_data=f"{ADMIXTURE_CALLBACK_PREFIX}:paint")],
    ]
    markup = build_markup(rows, "main:root", lang=lang)
    await _show_or_edit(message, admixture_root_text(lang), markup, edit_existing=edit_existing, context=context, user_id=user_id)


async def show_raw_calculators_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    lang: str = "ru",
    edit_existing: bool = False,
    user_id: int | None = None,
) -> None:
    projects = _raw_projects(context)
    rows = []
    for project in projects:
        installed_count = sum(1 for model in project.models if model.installed)
        label = f"{project.title} ({installed_count}/{len(project.models)})"
        rows.append([InlineKeyboardButton(label, callback_data=f"{ADMIXTURE_CALLBACK_PREFIX}:grp:{project.code}")])
    markup = build_markup(rows, f"{ADMIXTURE_CALLBACK_PREFIX}:r", lang=lang)
    await _show_or_edit(message, raw_calculators_text(projects, lang), markup, edit_existing=edit_existing, context=context, user_id=user_id)


async def show_placeholder_feature_menu(
    message,
    title: str,
    description: str,
    *,
    context: ContextTypes.DEFAULT_TYPE | None = None,
    user_id: int | None = None,
    lang: str = "ru",
    edit_existing: bool = False,
) -> None:
    await _show_or_edit(
        message,
        placeholder_feature_text(title, description, lang),
        build_markup([], f"{ADMIXTURE_CALLBACK_PREFIX}:r", lang=lang),
        edit_existing=edit_existing,
        context=context,
        user_id=user_id,
    )


async def show_raw_project_models_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    project_code: str,
    *,
    lang: str = "ru",
    edit_existing: bool = False,
    user_id: int | None = None,
) -> None:
    project = get_raw_admixture_project(_admixture_data_dir(context), project_code)
    if project is None:
        await _show_or_edit(
            message,
            error_text("Raw calculators", _copy(lang, "Проект не найден.", "Project not found.")),
            build_markup([], f"{ADMIXTURE_CALLBACK_PREFIX}:cal", lang=lang),
            edit_existing=edit_existing,
            context=context,
            user_id=user_id,
        )
        return
    rows = []
    for model in project.models:
        if model.name == "K36" and model.installed:
            callback = f"{ADMIXTURE_CALLBACK_PREFIX}:k36"
        elif model.installed:
            callback = f"{ADMIXTURE_CALLBACK_PREFIX}:ms:{model.name}:0"
        else:
            callback = f"{ADMIXTURE_CALLBACK_PREFIX}:mdl:{model.name}"
        label = _raw_model_button_label(model)
        rows.append([InlineKeyboardButton(label, callback_data=callback)])
    markup = build_markup(rows, f"{ADMIXTURE_CALLBACK_PREFIX}:cal", lang=lang)
    await _show_or_edit(message, raw_project_models_text(project, lang), markup, edit_existing=edit_existing, context=context, user_id=user_id)


async def show_raw_model_detail_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    model_name: str,
    *,
    lang: str = "ru",
    edit_existing: bool = False,
    user_id: int | None = None,
) -> None:
    model = get_raw_admixture_model(_admixture_data_dir(context), model_name)
    if model is None:
        await _show_or_edit(
            message,
            error_text("Raw calculators", _copy(lang, "Модель не найдена.", "Model not found.")),
            build_markup([], f"{ADMIXTURE_CALLBACK_PREFIX}:cal", lang=lang),
            edit_existing=edit_existing,
            context=context,
            user_id=user_id,
        )
        return
    rows = []
    if model.name == "K36" and model.installed:
        rows.append([InlineKeyboardButton(_copy(lang, "Открыть K36", "Open K36"), callback_data=f"{ADMIXTURE_CALLBACK_PREFIX}:k36")])
    elif model.installed:
        rows.append([InlineKeyboardButton(_copy(lang, "Выбрать sample", "Choose sample"), callback_data=f"{ADMIXTURE_CALLBACK_PREFIX}:ms:{model.name}:0")])
    markup = build_markup(rows, f"{ADMIXTURE_CALLBACK_PREFIX}:cal", lang=lang)
    await _show_or_edit(message, raw_model_detail_text(model, lang), markup, edit_existing=edit_existing, context=context, user_id=user_id)


async def show_raw_model_sample_picker_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    model_name: str,
    *,
    page: int = 0,
    lang: str = "ru",
    edit_existing: bool = False,
) -> None:
    model = get_raw_admixture_model(_admixture_data_dir(context), model_name)
    if model is None or not model.installed:
        await show_raw_model_detail_menu(message, context, model_name, lang=lang, edit_existing=edit_existing)
        return
    samples = _my_data_store(context).list_samples(user_id)
    page_samples, current_page, total_pages = _paginate(samples, page)
    rows: list[list[InlineKeyboardButton]] = []
    for sample in page_samples:
        rows.append([InlineKeyboardButton(sample.display_name, callback_data=f"{ADMIXTURE_CALLBACK_PREFIX}:mr:{model.name}:{sample.asset_id}")])
    pager = []
    if current_page > 0:
        pager.append(InlineKeyboardButton(t("nav.back", lang), callback_data=f"{ADMIXTURE_CALLBACK_PREFIX}:ms:{model.name}:{current_page - 1}"))
    if current_page + 1 < total_pages:
        pager.append(InlineKeyboardButton(_next_label(lang), callback_data=f"{ADMIXTURE_CALLBACK_PREFIX}:ms:{model.name}:{current_page + 1}"))
    if pager:
        rows.append(pager)
    if not samples:
        rows.append([InlineKeyboardButton(_copy(lang, "Открыть My DNA", "Open My DNA"), callback_data="mydna:root")])
    text = raw_model_sample_picker_text(model.name, samples, lang)
    markup = build_markup(rows, f"{ADMIXTURE_CALLBACK_PREFIX}:cal", lang=lang)
    await _show_or_edit(message, text, markup, edit_existing=edit_existing, context=context, user_id=user_id)


async def show_compare_profiles_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    lang: str = "ru",
    edit_existing: bool = False,
) -> None:
    counts = _compare_model_counts(context, user_id)
    projects = _raw_projects(context)
    project_counts = [
        (project, len(_project_compare_model_counts(project, counts)))
        for project in projects
    ]
    comparable_project_counts = [(project, count) for project, count in project_counts if count > 0]
    rows = [
        [InlineKeyboardButton(f"{project.title} ({count})", callback_data=f"{ADMIXTURE_CALLBACK_PREFIX}:cgrp:{project.code}")]
        for project, count in comparable_project_counts
    ]
    markup = build_markup(rows, f"{ADMIXTURE_CALLBACK_PREFIX}:r", lang=lang)
    await _show_or_edit(message, compare_profiles_text([(project.code, count) for project, count in comparable_project_counts], lang), markup, edit_existing=edit_existing, context=context, user_id=user_id)


async def show_compare_project_models_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    project_code: str,
    *,
    lang: str = "ru",
    edit_existing: bool = False,
) -> None:
    project = get_raw_admixture_project(_admixture_data_dir(context), project_code)
    if project is None:
        await show_compare_profiles_menu(message, context, user_id, lang=lang, edit_existing=edit_existing)
        return
    model_counts = _project_compare_model_counts(project, _compare_model_counts(context, user_id))
    rows = [
        [InlineKeyboardButton(f"{model} ({count})", callback_data=f"{ADMIXTURE_CALLBACK_PREFIX}:cm:{model}")]
        for model, count in model_counts
    ]
    markup = build_markup(rows, f"{ADMIXTURE_CALLBACK_PREFIX}:cmp", lang=lang)
    await _show_or_edit(message, compare_project_models_text(project, model_counts, lang), markup, edit_existing=edit_existing, context=context, user_id=user_id)


async def show_compare_report_picker_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    model: str,
    *,
    side: str,
    left_report_id: str | None = None,
    lang: str = "ru",
    edit_existing: bool = False,
) -> None:
    reports = [report for report in _report_store(context).list_all_reports(user_id) if report.model == model]
    if side == "right" and left_report_id:
        reports = [report for report in reports if report.report_id != left_report_id]
    token = None
    if side == "right" and left_report_id:
        token = _flow_store(context).create(
            user_id=user_id,
            payload={"mode": "compare_left", "model": model, "left_report_id": left_report_id},
        )
    rows: list[list[InlineKeyboardButton]] = []
    for report in reports[:20]:
        if side == "left":
            callback = f"{ADMIXTURE_CALLBACK_PREFIX}:cl:{model}:{report.report_id}"
        else:
            callback = f"{ADMIXTURE_CALLBACK_PREFIX}:cr:{token}:{report.report_id}"
        rows.append([InlineKeyboardButton(compare_report_button_label(report), callback_data=callback)])
    project_code = _model_project_code(context, model)
    model_back_callback = (
        f"{ADMIXTURE_CALLBACK_PREFIX}:cgrp:{project_code}"
        if project_code is not None
        else f"{ADMIXTURE_CALLBACK_PREFIX}:cmp"
    )
    back_callback = model_back_callback if side == "left" else f"{ADMIXTURE_CALLBACK_PREFIX}:cm:{model}"
    markup = build_markup(rows, back_callback, lang=lang)
    first_record = _report_store(context).find_report(user_id, left_report_id) if side == "right" and left_report_id else None
    first_report = first_record.summary if first_record is not None else None
    await _show_or_edit(message, compare_report_picker_text(model, reports, side=side, first_report=first_report, lang=lang), markup, edit_existing=edit_existing, context=context, user_id=user_id)


async def show_compare_result_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    left_report_id: str,
    right_report_id: str,
    *,
    lang: str = "ru",
    edit_existing: bool = False,
) -> None:
    left = _report_store(context).find_report(user_id, left_report_id)
    right = _report_store(context).find_report(user_id, right_report_id)
    if left is None or right is None:
        await _show_or_edit(
            message,
            error_text("Compare profiles", _copy(lang, "Один из reports не найден.", "One of the reports was not found.")),
            build_markup([], f"{ADMIXTURE_CALLBACK_PREFIX}:cmp", lang=lang),
            edit_existing=edit_existing,
            context=context,
            user_id=user_id,
        )
        return
    if left.summary.model != right.summary.model:
        await _show_or_edit(
            message,
            error_text("Compare profiles", _copy(lang, "Для сравнения нужны reports одной модели.", "Comparison requires reports from the same model.")),
            build_markup([], f"{ADMIXTURE_CALLBACK_PREFIX}:cmp", lang=lang),
            edit_existing=edit_existing,
            context=context,
            user_id=user_id,
        )
        return
    comparison = compare_admixture_payloads(left.product_payload, right.product_payload)
    markup = build_markup([], f"{ADMIXTURE_CALLBACK_PREFIX}:cm:{left.summary.model}", lang=lang)
    image_path = _create_visualization_path()
    fallback_text = compare_result_text(left, right, comparison)
    try:
        render_compare_png(
            image_path,
            left_name=left.summary.sample_name,
            right_name=right.summary.sample_name,
            comparison=comparison,
        )
    except Exception:
        try:
            image_path.unlink()
        except FileNotFoundError:
            pass
        await _show_or_edit(message, fallback_text, markup, edit_existing=edit_existing, context=context, user_id=user_id)
        return
    await _send_visual_or_fallback(
        message,
        context,
        user_id,
        image_path=image_path,
        caption=compare_visual_caption(left, right, comparison),
        fallback_text=fallback_text,
        reply_markup=markup,
        edit_existing=edit_existing,
    )


async def show_oracle_projects_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    lang: str = "ru",
    edit_existing: bool = False,
) -> None:
    counts = _oracle_model_counts(context, user_id)
    project_counts = [
        (project, len(_project_oracle_model_counts(project, counts)))
        for project in _raw_projects(context)
    ]
    visible = [(project, count) for project, count in project_counts if count > 0]
    rows = [
        [InlineKeyboardButton(f"{project.title} ({count})", callback_data=f"{ADMIXTURE_CALLBACK_PREFIX}:opg:{project.code}")]
        for project, count in visible
    ]
    markup = build_markup(rows, f"{ADMIXTURE_CALLBACK_PREFIX}:r", lang=lang)
    await _show_or_edit(message, oracle_projects_text([(project.code, count) for project, count in visible], lang), markup, edit_existing=edit_existing, context=context, user_id=user_id)


async def show_oracle_project_models_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    project_code: str,
    *,
    lang: str = "ru",
    edit_existing: bool = False,
) -> None:
    project = get_raw_admixture_project(_admixture_data_dir(context), project_code)
    if project is None:
        await show_oracle_projects_menu(message, context, user_id, lang=lang, edit_existing=edit_existing)
        return
    model_counts = _project_oracle_model_counts(project, _oracle_model_counts(context, user_id))
    rows = [
        [InlineKeyboardButton(f"{model} ({count})", callback_data=f"{ADMIXTURE_CALLBACK_PREFIX}:om:{model}")]
        for model, count in model_counts
    ]
    markup = build_markup(rows, f"{ADMIXTURE_CALLBACK_PREFIX}:op", lang=lang)
    await _show_or_edit(message, oracle_project_models_text(project, model_counts, lang), markup, edit_existing=edit_existing, context=context, user_id=user_id)


async def show_oracle_report_picker_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    model: str,
    *,
    lang: str = "ru",
    edit_existing: bool = False,
) -> None:
    reference_set = load_oracle_references(_oracle_reference_dir(context), model)
    if reference_set is None:
        await _show_or_edit(
            message,
            error_text("Similar populations", _copy(lang, "Reference table для этой модели не найдена.", "Reference table for this model was not found.")),
            build_markup([], f"{ADMIXTURE_CALLBACK_PREFIX}:op", lang=lang),
            edit_existing=edit_existing,
            context=context,
            user_id=user_id,
        )
        return
    reports = [report for report in _report_store(context).list_all_reports(user_id) if report.model == model]
    rows = [
        [InlineKeyboardButton(similar_report_button_label(report), callback_data=f"{ADMIXTURE_CALLBACK_PREFIX}:or:{report.report_id}")]
        for report in reports[:20]
    ]
    project_code = _model_project_code(context, model)
    back_callback = f"{ADMIXTURE_CALLBACK_PREFIX}:opg:{project_code}" if project_code is not None else f"{ADMIXTURE_CALLBACK_PREFIX}:op"
    markup = build_markup(rows, back_callback, lang=lang)
    await _show_or_edit(message, oracle_report_picker_text(model, reports, len(reference_set.populations), lang), markup, edit_existing=edit_existing, context=context, user_id=user_id)


async def show_oracle_result_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    report_id: str,
    *,
    lang: str = "ru",
    edit_existing: bool = False,
) -> None:
    record = _report_store(context).find_report(user_id, report_id)
    if record is None:
        await _show_or_edit(
            message,
            error_text("Similar populations", _copy(lang, "Сохраненный report не найден.", "Saved report not found.")),
            build_markup([], f"{ADMIXTURE_CALLBACK_PREFIX}:op", lang=lang),
            edit_existing=edit_existing,
            context=context,
            user_id=user_id,
        )
        return
    reference_set = load_oracle_references(_oracle_reference_dir(context), record.summary.model)
    if reference_set is None:
        await _show_or_edit(
            message,
            error_text("Similar populations", _copy(lang, "Reference table для этой модели не найдена.", "Reference table for this model was not found.")),
            build_markup([], f"{ADMIXTURE_CALLBACK_PREFIX}:op", lang=lang),
            edit_existing=edit_existing,
            context=context,
            user_id=user_id,
        )
        return
    matches = similar_populations(record.product_payload, reference_set)
    markup = build_markup([], f"{ADMIXTURE_CALLBACK_PREFIX}:om:{record.summary.model}", lang=lang)
    image_path = _create_visualization_path()
    fallback_text = oracle_result_text(record, reference_set, matches)
    try:
        render_oracle_png(
            image_path,
            sample_name=record.summary.sample_name,
            model=record.summary.model,
            reference_set=reference_set,
            matches=matches,
        )
    except Exception:
        try:
            image_path.unlink()
        except FileNotFoundError:
            pass
        await _show_or_edit(message, fallback_text, markup, edit_existing=edit_existing, context=context, user_id=user_id)
        return
    await _send_visual_or_fallback(
        message,
        context,
        user_id,
        image_path=image_path,
        caption=oracle_visual_caption(record, matches),
        fallback_text=fallback_text,
        reply_markup=markup,
        edit_existing=edit_existing,
    )


async def show_oracle_mix_projects_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    lang: str = "ru",
    edit_existing: bool = False,
) -> None:
    counts = _oracle_model_counts(context, user_id)
    project_counts = [
        (project, len(_project_oracle_model_counts(project, counts)))
        for project in _raw_projects(context)
    ]
    visible = [(project, count) for project, count in project_counts if count > 0]
    rows = [
        [InlineKeyboardButton(f"{project.title} ({count})", callback_data=f"{ADMIXTURE_CALLBACK_PREFIX}:omg:{project.code}")]
        for project, count in visible
    ]
    markup = build_markup(rows, f"{ADMIXTURE_CALLBACK_PREFIX}:r", lang=lang)
    await _show_or_edit(message, oracle_mix_projects_text([(project.code, count) for project, count in visible], lang), markup, edit_existing=edit_existing, context=context, user_id=user_id)


async def show_oracle_mix_project_models_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    project_code: str,
    *,
    lang: str = "ru",
    edit_existing: bool = False,
) -> None:
    project = get_raw_admixture_project(_admixture_data_dir(context), project_code)
    if project is None:
        await show_oracle_mix_projects_menu(message, context, user_id, lang=lang, edit_existing=edit_existing)
        return
    model_counts = _project_oracle_model_counts(project, _oracle_model_counts(context, user_id))
    rows = [
        [InlineKeyboardButton(f"{model} ({count})", callback_data=f"{ADMIXTURE_CALLBACK_PREFIX}:omd:{model}")]
        for model, count in model_counts
    ]
    markup = build_markup(rows, f"{ADMIXTURE_CALLBACK_PREFIX}:omix", lang=lang)
    await _show_or_edit(message, oracle_mix_project_models_text(project, model_counts, lang), markup, edit_existing=edit_existing, context=context, user_id=user_id)


async def show_oracle_mix_mode_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    model: str,
    *,
    lang: str = "ru",
    edit_existing: bool = False,
) -> None:
    reference_set = load_oracle_references(_oracle_reference_dir(context), model)
    if reference_set is None:
        await _show_or_edit(
            message,
            error_text("Oracle mix", _copy(lang, "Reference table для этой модели не найдена.", "Reference table for this model was not found.")),
            build_markup([], f"{ADMIXTURE_CALLBACK_PREFIX}:omix", lang=lang),
            edit_existing=edit_existing,
            context=context,
            user_id=user_id,
        )
        return
    reports = [report for report in _report_store(context).list_all_reports(user_id) if report.model == model]
    rows = [
        [InlineKeyboardButton("2-way mix", callback_data=f"{ADMIXTURE_CALLBACK_PREFIX}:omm:2:{model}")],
        [InlineKeyboardButton("3-way mix", callback_data=f"{ADMIXTURE_CALLBACK_PREFIX}:omm:3:{model}")],
    ] if reports else []
    project_code = _model_project_code(context, model)
    back_callback = f"{ADMIXTURE_CALLBACK_PREFIX}:omg:{project_code}" if project_code is not None else f"{ADMIXTURE_CALLBACK_PREFIX}:omix"
    markup = build_markup(rows, back_callback, lang=lang)
    await _show_or_edit(message, oracle_mix_mode_text(model, len(reference_set.populations), len(reports), lang), markup, edit_existing=edit_existing, context=context, user_id=user_id)


async def show_oracle_mix_report_picker_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    model: str,
    mode: str,
    *,
    lang: str = "ru",
    edit_existing: bool = False,
) -> None:
    reference_set = load_oracle_references(_oracle_reference_dir(context), model)
    if reference_set is None:
        await _show_or_edit(
            message,
            error_text("Oracle mix", _copy(lang, "Reference table для этой модели не найдена.", "Reference table for this model was not found.")),
            build_markup([], f"{ADMIXTURE_CALLBACK_PREFIX}:omix", lang=lang),
            edit_existing=edit_existing,
            context=context,
            user_id=user_id,
        )
        return
    reports = [report for report in _report_store(context).list_all_reports(user_id) if report.model == model]
    rows = [
        [InlineKeyboardButton(oracle_mix_report_button_label(report), callback_data=f"{ADMIXTURE_CALLBACK_PREFIX}:omr:{mode}:{report.report_id}")]
        for report in reports[:20]
    ]
    markup = build_markup(rows, f"{ADMIXTURE_CALLBACK_PREFIX}:omd:{model}", lang=lang)
    await _show_or_edit(message, oracle_mix_report_picker_text(model, _oracle_mix_mode_label(mode), reports, len(reference_set.populations), lang), markup, edit_existing=edit_existing, context=context, user_id=user_id)


async def show_oracle_mix_result_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    mode: str,
    report_id: str,
    *,
    lang: str = "ru",
    edit_existing: bool = False,
) -> None:
    record = _report_store(context).find_report(user_id, report_id)
    if record is None:
        await _show_or_edit(
            message,
            error_text("Oracle mix", _copy(lang, "Сохраненный report не найден.", "Saved report not found.")),
            build_markup([], f"{ADMIXTURE_CALLBACK_PREFIX}:omix", lang=lang),
            edit_existing=edit_existing,
            context=context,
            user_id=user_id,
        )
        return
    reference_set = load_oracle_references(_oracle_reference_dir(context), record.summary.model)
    if reference_set is None:
        await _show_or_edit(
            message,
            error_text("Oracle mix", _copy(lang, "Reference table для этой модели не найдена.", "Reference table for this model was not found.")),
            build_markup([], f"{ADMIXTURE_CALLBACK_PREFIX}:omix", lang=lang),
            edit_existing=edit_existing,
            context=context,
            user_id=user_id,
        )
        return
    clean_mode = "3" if mode == "3" else "2"
    single_matches = similar_populations(record.product_payload, reference_set, top=30)
    matches = (
        three_way_oracle_mixes(record.product_payload, reference_set, candidate_limit=18)
        if clean_mode == "3"
        else two_way_oracle_mixes(record.product_payload, reference_set, candidate_limit=30)
    )
    mode_label = _oracle_mix_mode_label(clean_mode)
    markup = build_markup([], f"{ADMIXTURE_CALLBACK_PREFIX}:omm:{clean_mode}:{record.summary.model}", lang=lang)
    fallback_text = oracle_mix_result_text(record, reference_set, mode_label, single_matches, matches)
    image_path = _create_visualization_path()
    try:
        render_oracle_mix_png(
            image_path,
            sample_name=record.summary.sample_name,
            model=record.summary.model,
            mode_label=mode_label,
            reference_set=reference_set,
            single_matches=single_matches,
            mix_matches=matches,
        )
    except Exception:
        try:
            image_path.unlink()
        except FileNotFoundError:
            pass
        await _show_or_edit(message, fallback_text, markup, edit_existing=edit_existing, context=context, user_id=user_id)
        return
    await _send_visual_or_fallback(
        message,
        context,
        user_id,
        image_path=image_path,
        caption=oracle_mix_visual_caption(record, mode_label, matches),
        fallback_text=fallback_text,
        reply_markup=markup,
        edit_existing=edit_existing,
    )


async def show_k36_sample_picker_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    page: int = 0,
    lang: str = "ru",
    edit_existing: bool = False,
) -> None:
    samples = _my_data_store(context).list_samples(user_id)
    page_samples, current_page, total_pages = _paginate(samples, page)
    rows: list[list[InlineKeyboardButton]] = []
    for sample in page_samples:
        rows.append([InlineKeyboardButton(sample.display_name, callback_data=f"{ADMIXTURE_CALLBACK_PREFIX}:s:{sample.asset_id}")])
    pager = []
    if current_page > 0:
        pager.append(InlineKeyboardButton(t("nav.back", lang), callback_data=f"{ADMIXTURE_CALLBACK_PREFIX}:p:{current_page - 1}"))
    if current_page + 1 < total_pages:
        pager.append(InlineKeyboardButton(_next_label(lang), callback_data=f"{ADMIXTURE_CALLBACK_PREFIX}:p:{current_page + 1}"))
    if pager:
        rows.append(pager)
    if not samples:
        rows.append([InlineKeyboardButton(_copy(lang, "Открыть My DNA", "Open My DNA"), callback_data="mydna:root")])
    markup = build_markup(rows, f"{ADMIXTURE_CALLBACK_PREFIX}:cal", lang=lang)
    await _show_or_edit(message, k36_sample_picker_text(samples, lang), markup, edit_existing=edit_existing, context=context, user_id=user_id)


async def show_sample_admixture_reports_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    sample_id: str,
    *,
    origin: str = "admixture",
    lang: str = "ru",
    edit_existing: bool = False,
) -> None:
    is_my_data_origin = origin == "my_data"
    sample = _my_data_store(context).get_sample(user_id, sample_id)
    if sample is None:
        markup = build_markup([], "mydna:root" if is_my_data_origin else f"{ADMIXTURE_CALLBACK_PREFIX}:r", lang=lang)
        await _show_or_edit(
            message,
            error_text("K36 profile", _copy(lang, "Сохраненный sample не найден.", "Saved sample not found.")),
            markup,
            edit_existing=edit_existing,
            context=context,
            user_id=user_id,
        )
        return

    all_reports = _report_store(context).list_reports(user_id, sample.asset_id)
    reports = _sample_admixture_reports_for_origin(all_reports, origin=origin)
    k36_items = _k36_coordinates(context, user_id, sample)
    if not is_my_data_origin and len(reports) == 1:
        await show_admixture_report_detail_menu(
            message,
            context,
            user_id,
            reports[0].report_id,
            back_callback=f"{ADMIXTURE_CALLBACK_PREFIX}:k36",
            lang=lang,
            edit_existing=edit_existing,
        )
        return
    rows: list[list[InlineKeyboardButton]] = []
    report_action = "mo" if is_my_data_origin else "o"
    for report in reports[:10]:
        rows.append([InlineKeyboardButton(report_button_label(report), callback_data=f"{ADMIXTURE_CALLBACK_PREFIX}:{report_action}:{report.report_id}")])
    if not reports and not is_my_data_origin:
        if len(k36_items) == 1:
            rows.append([InlineKeyboardButton(_copy(lang, "Открыть K36 profile", "Open K36 profile"), callback_data=f"{ADMIXTURE_CALLBACK_PREFIX}:k:{k36_items[0].asset_id}")])
        elif len(k36_items) > 1:
            rows.append([InlineKeyboardButton(_copy(lang, "Выбрать K36 coordinates", "Choose K36 coordinates"), callback_data=f"{ADMIXTURE_CALLBACK_PREFIX}:c:{sample.asset_id}")])
        else:
            rows.append([InlineKeyboardButton(_copy(lang, "Извлечь K36 из raw", "Extract K36 from raw"), callback_data=f"{ADMIXTURE_CALLBACK_PREFIX}:x:{sample.asset_id}")])
    back_callback = f"my_data:sample_reports:{sample.asset_id}" if is_my_data_origin else f"{ADMIXTURE_CALLBACK_PREFIX}:k36"
    markup = build_markup(rows, back_callback, lang=lang)
    await _show_or_edit(
        message,
        sample_admixture_reports_text(sample, reports, k36_items, lang),
        markup,
        edit_existing=edit_existing,
        context=context,
        user_id=user_id,
    )


async def show_k36_coordinate_picker_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    sample_id: str,
    *,
    lang: str = "ru",
    edit_existing: bool = False,
) -> None:
    sample = _my_data_store(context).get_sample(user_id, sample_id)
    if sample is None:
        await show_admixture_menu(message, context, user_id, lang=lang, edit_existing=edit_existing)
        return
    coordinates = _k36_coordinates(context, user_id, sample)
    rows = [
        [InlineKeyboardButton(item.display_name, callback_data=f"{ADMIXTURE_CALLBACK_PREFIX}:k:{item.asset_id}")]
        for item in coordinates[:10]
    ]
    markup = build_markup(rows, f"{ADMIXTURE_CALLBACK_PREFIX}:s:{sample.asset_id}", lang=lang)
    await _show_or_edit(message, k36_coordinate_picker_text(sample, coordinates, lang), markup, edit_existing=edit_existing, context=context, user_id=user_id)


async def show_admixture_report_detail_menu(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    report_id: str,
    *,
    back_callback: str | None = None,
    lang: str = "ru",
    edit_existing: bool = False,
) -> None:
    record = _report_store(context).find_report(user_id, report_id)
    resolved_back_callback = back_callback or f"{ADMIXTURE_CALLBACK_PREFIX}:r"
    if record is None:
        await _show_or_edit(
            message,
            error_text("Admixture report", _copy(lang, "Сохраненный отчет не найден.", "Saved report not found.")),
            build_markup([], resolved_back_callback, lang=lang),
            edit_existing=edit_existing,
            context=context,
            user_id=user_id,
        )
        return
    rows: list[list[InlineKeyboardButton]] = []
    markup = build_markup(rows, back_callback or f"{ADMIXTURE_CALLBACK_PREFIX}:s:{record.summary.sample_id}", lang=lang)
    await _show_profile_visual(
        message,
        context,
        user_id,
        sample_name=record.summary.sample_name,
        coordinate_name=record.summary.coordinate_name,
        payload=record.product_payload,
        caption=report_detail_visual_caption(record, lang),
        fallback_text=report_detail_text(record, lang),
        reply_markup=markup,
        status_label="SAVED",
        edit_existing=edit_existing,
    )


async def _run_k36_profile(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    sample_id: str,
    coordinate_id: str,
    lang: str = "ru",
) -> None:
    sample = _my_data_store(context).get_sample(user_id, sample_id)
    coordinate = _my_data_store(context).get_coordinate(user_id, coordinate_id)
    if sample is None or coordinate is None:
        await _show_or_edit(
            message,
            error_text("K36 profile", _copy(lang, "Sample или координаты не найдены.", "Sample or coordinates not found.")),
            build_markup([], f"{ADMIXTURE_CALLBACK_PREFIX}:r", lang=lang),
            edit_existing=True,
            context=context,
            user_id=user_id,
        )
        return
    if coordinate.coordinate_type.strip().lower() != "k36":
        await _show_or_edit(
            message,
            error_text("K36 profile", _copy(lang, "Для этого отчета нужны K36-координаты.", "This report needs K36 coordinates.")),
            build_markup([], f"{ADMIXTURE_CALLBACK_PREFIX}:s:{sample.asset_id}", lang=lang),
            edit_existing=True,
            context=context,
            user_id=user_id,
        )
        return

    message = await _show_status_message(message, running_k36_text(sample, lang))
    try:
        profile = build_k36_profile(coordinate.g25_line, sample_name=sample.display_name)
    except ValueError as exc:
        await _show_or_edit(
            message,
            error_text("K36 profile", _copy(lang, "Не удалось разобрать K36-координаты.", "Could not parse K36 coordinates."), details=str(exc)),
            build_markup([], f"{ADMIXTURE_CALLBACK_PREFIX}:s:{sample.asset_id}", lang=lang),
            edit_existing=True,
            context=context,
            user_id=user_id,
        )
        return

    payload = profile_to_payload(profile)
    rows = [
        [InlineKeyboardButton(_copy(lang, "💾 Сохранить отчёт", "💾 Save report"), callback_data=f"{ADMIXTURE_CALLBACK_PREFIX}:save:{coordinate.asset_id}")],
        [InlineKeyboardButton(_copy(lang, "🔁 Запустить заново", "🔁 Run again"), callback_data=f"{ADMIXTURE_CALLBACK_PREFIX}:k:{coordinate.asset_id}")],
    ]
    markup = build_markup(rows, f"{ADMIXTURE_CALLBACK_PREFIX}:s:{sample.asset_id}", lang=lang)
    await _show_profile_visual(
        message,
        context,
        user_id,
        sample_name=sample.display_name,
        coordinate_name=coordinate.display_name,
        payload=payload,
        caption=profile_visual_caption(sample, payload, lang),
        fallback_text=profile_preview_text(sample, coordinate, payload, lang),
        reply_markup=markup,
        status_label="PREVIEW",
        edit_existing=True,
    )


async def _save_k36_profile(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    coordinate_id: str,
    lang: str = "ru",
) -> None:
    coordinate = _my_data_store(context).get_coordinate(user_id, coordinate_id)
    sample = _my_data_store(context).find_sample_by_coordinate(user_id, coordinate_id)
    if sample is None or coordinate is None:
        await _show_or_edit(
            message,
            error_text("K36 profile", _copy(lang, "Sample или координаты не найдены.", "Sample or coordinates not found.")),
            build_markup([], f"{ADMIXTURE_CALLBACK_PREFIX}:r", lang=lang),
            edit_existing=True,
            context=context,
            user_id=user_id,
        )
        return
    if coordinate.coordinate_type.strip().lower() != "k36":
        await _show_or_edit(
            message,
            error_text("K36 profile", _copy(lang, "Для этого отчета нужны K36-координаты.", "This report needs K36 coordinates.")),
            build_markup([], f"{ADMIXTURE_CALLBACK_PREFIX}:s:{sample.asset_id}", lang=lang),
            edit_existing=True,
            context=context,
            user_id=user_id,
        )
        return
    try:
        profile = build_k36_profile(coordinate.g25_line, sample_name=sample.display_name)
    except ValueError as exc:
        await _show_or_edit(
            message,
            error_text("K36 profile", _copy(lang, "Не удалось разобрать K36-координаты.", "Could not parse K36 coordinates."), details=str(exc)),
            build_markup([], f"{ADMIXTURE_CALLBACK_PREFIX}:s:{sample.asset_id}", lang=lang),
            edit_existing=True,
            context=context,
            user_id=user_id,
        )
        return

    payload = profile_to_payload(profile)
    saved = _report_store(context).save_report(
        user_id,
        sample_id=sample.asset_id,
        sample_name=sample.display_name,
        coordinate_id=coordinate.asset_id,
        coordinate_name=coordinate.display_name,
        technical_payload={
            "coordinate_id": coordinate.asset_id,
            "coordinate_type": coordinate.coordinate_type,
            "input_mode": coordinate.input_mode,
            "canonical_line": coordinate.g25_line,
        },
        product_payload=payload,
    )
    rows = [
        [InlineKeyboardButton(_copy(lang, "Открыть отчёт", "Open report"), callback_data=f"{ADMIXTURE_CALLBACK_PREFIX}:o:{saved.summary.report_id}")],
        [InlineKeyboardButton(_copy(lang, "🧬 Admixture profiles", "🧬 Admixture profiles"), callback_data=f"{ADMIXTURE_CALLBACK_PREFIX}:s:{sample.asset_id}")],
    ]
    markup = build_markup(rows, f"{ADMIXTURE_CALLBACK_PREFIX}:s:{sample.asset_id}", lang=lang)
    await _show_profile_visual(
        message,
        context,
        user_id,
        sample_name=saved.summary.sample_name,
        coordinate_name=saved.summary.coordinate_name,
        payload=saved.product_payload,
        caption=saved_report_visual_caption(saved, lang),
        fallback_text=report_saved_text(saved, lang),
        reply_markup=markup,
        status_label="SAVED",
        edit_existing=True,
    )


async def _run_raw_model_profile(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    model_name: str,
    sample_id: str,
    lang: str = "ru",
) -> None:
    sample = _my_data_store(context).get_sample(user_id, sample_id)
    model = get_raw_admixture_model(_admixture_data_dir(context), model_name)
    if sample is None or model is None or not model.installed:
        await _show_or_edit(
            message,
            error_text("Raw calculator", _copy(lang, "Sample или модель не найдены.", "Sample or model not found.")),
            build_markup([], f"{ADMIXTURE_CALLBACK_PREFIX}:cal", lang=lang),
            edit_existing=True,
            context=context,
            user_id=user_id,
        )
        return
    raw_file = _my_data_store(context).get_sample_raw_file(user_id, sample.asset_id)
    if raw_file is None:
        await _show_or_edit(
            message,
            error_text(model.name, _copy(lang, "У sample не найден исходный raw-файл.", "This sample has no source raw file.")),
            build_markup([], f"{ADMIXTURE_CALLBACK_PREFIX}:ms:{model.name}:0", lang=lang),
            edit_existing=True,
            context=context,
            user_id=user_id,
        )
        return
    raw_path = _my_data_store(context).resolve_raw_file_path(raw_file)
    if not raw_path.exists():
        await _show_or_edit(
            message,
            error_text(model.name, _copy(lang, "Исходный raw-файл отсутствует на диске.", "Source raw file is missing on disk.")),
            build_markup([], f"{ADMIXTURE_CALLBACK_PREFIX}:ms:{model.name}:0", lang=lang),
            edit_existing=True,
            context=context,
            user_id=user_id,
        )
        return

    existing = _report_store(context).find_report_for_coordinate(
        user_id,
        sample.asset_id,
        _raw_model_coordinate_id(raw_file.asset_id, model.name),
        model.name,
    )
    if existing is not None:
        await show_admixture_report_detail_menu(
            message,
            context,
            user_id,
            existing.summary.report_id,
            back_callback=f"{ADMIXTURE_CALLBACK_PREFIX}:ms:{model.name}:0",
            lang=lang,
            edit_existing=True,
        )
        return

    message = await _show_status_message(
        message,
        f"<b>🧮 {html.escape(model.name)} profile</b>\n\nSample: <b>{html.escape(sample.display_name)}</b>\n{_copy(lang, 'Строю профиль...', 'Building profile...')}",
    )
    try:
        payload = run_raw_admixture_model(
            raw_path,
            model=model.name,
            sample_name=sample.display_name,
            run_dir=_g25_service(context).create_run_dir(f"admix_{model.name}", sample.display_name),
        )
    except Exception as exc:
        await _show_or_edit(
            message,
            error_text(model.name, _copy(lang, "Не удалось выполнить raw calculator.", "Could not run raw calculator."), details=str(exc)),
            build_markup([], f"{ADMIXTURE_CALLBACK_PREFIX}:ms:{model.name}:0", lang=lang),
            edit_existing=True,
            context=context,
            user_id=user_id,
        )
        return

    token = _flow_store(context).create(
        user_id=user_id,
        payload={
            "mode": "raw_model_preview",
            "model": model.name,
            "sample_id": sample.asset_id,
            "raw_file_id": raw_file.asset_id,
            "payload": payload,
        },
    )
    coordinate_preview = CoordinateAsset(
        asset_id=token,
        display_name=raw_file.display_name,
        target_name=sample.display_name,
        coordinate_type="raw",
        g25_line="",
        input_mode=str(payload.get("vendor") or "raw"),
        created_at="",
    )
    rows = [
        [InlineKeyboardButton(_copy(lang, "💾 Сохранить отчёт", "💾 Save report"), callback_data=f"{ADMIXTURE_CALLBACK_PREFIX}:savem:{token}")],
        [InlineKeyboardButton(_copy(lang, "🔁 Запустить заново", "🔁 Run again"), callback_data=f"{ADMIXTURE_CALLBACK_PREFIX}:mr:{model.name}:{sample.asset_id}")],
    ]
    markup = build_markup(rows, f"{ADMIXTURE_CALLBACK_PREFIX}:ms:{model.name}:0", lang=lang)
    await _show_profile_visual(
        message,
        context,
        user_id,
        sample_name=sample.display_name,
        coordinate_name=coordinate_preview.display_name,
        payload=payload,
        caption=profile_visual_caption(sample, payload, lang),
        fallback_text=profile_preview_text(sample, coordinate_preview, payload, lang),
        reply_markup=markup,
        status_label="PREVIEW",
        edit_existing=True,
    )


async def _save_raw_model_profile(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    token: str,
    lang: str = "ru",
) -> None:
    draft = _flow_store(context).get(token, user_id)
    if draft is None:
        await _show_or_edit(
            message,
            error_text("Raw calculator", _copy(lang, "Черновик расчета не найден. Запустите preview заново.", "Calculation draft not found. Run the preview again.")),
            build_markup([], f"{ADMIXTURE_CALLBACK_PREFIX}:cal", lang=lang),
            edit_existing=True,
            context=context,
            user_id=user_id,
        )
        return
    sample_id = str(draft.get("sample_id") or "")
    raw_file_id = str(draft.get("raw_file_id") or "")
    payload = dict(draft.get("payload") or {})
    model_name = str(draft.get("model") or payload.get("model") or "Admixture")
    sample = _my_data_store(context).get_sample(user_id, sample_id)
    raw_file = _my_data_store(context).get_raw_file(user_id, raw_file_id)
    if sample is None or raw_file is None:
        await _show_or_edit(
            message,
            error_text(model_name, _copy(lang, "Sample или raw-файл не найден.", "Sample or raw file not found.")),
            build_markup([], f"{ADMIXTURE_CALLBACK_PREFIX}:cal", lang=lang),
            edit_existing=True,
            context=context,
            user_id=user_id,
        )
        return
    saved = _report_store(context).save_report(
        user_id,
        sample_id=sample.asset_id,
        sample_name=sample.display_name,
        coordinate_id=_raw_model_coordinate_id(raw_file.asset_id, model_name),
        coordinate_name=raw_file.display_name,
        technical_payload={
            "raw_file_id": raw_file.asset_id,
            "model": model_name,
            "vendor": payload.get("vendor"),
            "output_path": payload.get("output_path"),
        },
        product_payload=payload,
    )
    rows = [
        [InlineKeyboardButton(_copy(lang, "Открыть отчёт", "Open report"), callback_data=f"{ADMIXTURE_CALLBACK_PREFIX}:o:{saved.summary.report_id}")],
        [InlineKeyboardButton("🧮 Raw calculators", callback_data=f"{ADMIXTURE_CALLBACK_PREFIX}:cal")],
    ]
    markup = build_markup(rows, f"{ADMIXTURE_CALLBACK_PREFIX}:ms:{model_name}:0", lang=lang)
    await _show_profile_visual(
        message,
        context,
        user_id,
        sample_name=saved.summary.sample_name,
        coordinate_name=saved.summary.coordinate_name,
        payload=saved.product_payload,
        caption=saved_report_visual_caption(saved, lang),
        fallback_text=report_saved_text(saved, lang),
        reply_markup=markup,
        status_label="SAVED",
        edit_existing=True,
    )


async def _extract_k36_and_run(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    sample_id: str,
    lang: str = "ru",
) -> None:
    sample = _my_data_store(context).get_sample(user_id, sample_id)
    if sample is None:
        await show_admixture_menu(message, context, user_id, lang=lang, edit_existing=True)
        return
    raw_file = _my_data_store(context).get_sample_raw_file(user_id, sample.asset_id)
    if raw_file is None:
        await _show_or_edit(
            message,
            error_text("K36 extraction", _copy(lang, "У sample не найден исходный raw-файл.", "This sample has no source raw file.")),
            build_markup([], f"{ADMIXTURE_CALLBACK_PREFIX}:s:{sample.asset_id}", lang=lang),
            edit_existing=True,
            context=context,
            user_id=user_id,
        )
        return
    raw_path = _my_data_store(context).resolve_raw_file_path(raw_file)
    if not raw_path.exists():
        await _show_or_edit(
            message,
            error_text("K36 extraction", _copy(lang, "Исходный raw-файл отсутствует на диске.", "Source raw file is missing on disk.")),
            build_markup([], f"{ADMIXTURE_CALLBACK_PREFIX}:s:{sample.asset_id}", lang=lang),
            edit_existing=True,
            context=context,
            user_id=user_id,
        )
        return

    message = await _show_status_message(message, extracting_k36_text(sample, lang))
    try:
        result = _g25_service(context).extract_coordinates_from_file(Path(raw_path), sample.display_name, "k36")
    except G25CommandError as exc:
        await _show_or_edit(
            message,
            error_text("K36 extraction", _copy(lang, "Не удалось извлечь K36 из raw.", "Could not extract K36 from raw."), details=str(exc)),
            build_markup([], f"{ADMIXTURE_CALLBACK_PREFIX}:s:{sample.asset_id}", lang=lang),
            edit_existing=True,
            context=context,
            user_id=user_id,
        )
        return

    try:
        profile = build_k36_profile(result.simulated_g25_line, sample_name=sample.display_name)
    except ValueError as exc:
        await _show_or_edit(
            message,
            error_text("K36 profile", _copy(lang, "Не удалось разобрать K36-координаты.", "Could not parse K36 coordinates."), details=str(exc)),
            build_markup([], f"{ADMIXTURE_CALLBACK_PREFIX}:s:{sample.asset_id}", lang=lang),
            edit_existing=True,
            context=context,
            user_id=user_id,
        )
        return

    token = _flow_store(context).create(
        user_id=user_id,
        payload={
            "sample_id": sample.asset_id,
            "target_name": result.target_name,
            "coordinate_line": result.simulated_g25_line,
            "input_mode": result.input_mode,
        },
    )
    coordinate_preview = CoordinateAsset(
        asset_id=token,
        display_name=f"{sample.display_name} K36",
        target_name=result.target_name,
        coordinate_type="k36",
        g25_line=result.simulated_g25_line,
        input_mode=result.input_mode,
        created_at="",
    )
    payload = profile_to_payload(profile)
    rows = [
        [InlineKeyboardButton(_copy(lang, "💾 Сохранить отчёт", "💾 Save report"), callback_data=f"{ADMIXTURE_CALLBACK_PREFIX}:svx:{token}")],
        [InlineKeyboardButton(_copy(lang, "Извлечь заново", "Extract again"), callback_data=f"{ADMIXTURE_CALLBACK_PREFIX}:x:{sample.asset_id}")],
    ]
    markup = build_markup(rows, f"{ADMIXTURE_CALLBACK_PREFIX}:s:{sample.asset_id}", lang=lang)
    await _show_profile_visual(
        message,
        context,
        user_id,
        sample_name=sample.display_name,
        coordinate_name=coordinate_preview.display_name,
        payload=payload,
        caption=profile_visual_caption(sample, payload, lang),
        fallback_text=profile_preview_text(sample, coordinate_preview, payload, lang),
        reply_markup=markup,
        status_label="PREVIEW",
        edit_existing=True,
    )


async def _save_extracted_k36_profile(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    token: str,
    lang: str = "ru",
) -> None:
    payload = _flow_store(context).get(token, user_id)
    if payload is None:
        await _show_or_edit(
            message,
            error_text("K36 profile", _copy(lang, "Черновик расчета не найден. Запустите extraction заново.", "Calculation draft not found. Run extraction again.")),
            build_markup([], f"{ADMIXTURE_CALLBACK_PREFIX}:r", lang=lang),
            edit_existing=True,
            context=context,
            user_id=user_id,
        )
        return
    sample_id = str(payload.get("sample_id") or "")
    sample = _my_data_store(context).get_sample(user_id, sample_id)
    if sample is None:
        await _show_or_edit(
            message,
            error_text("K36 profile", _copy(lang, "Сохраненный sample не найден.", "Saved sample not found.")),
            build_markup([], f"{ADMIXTURE_CALLBACK_PREFIX}:r", lang=lang),
            edit_existing=True,
            context=context,
            user_id=user_id,
        )
        return
    coordinate_line = str(payload.get("coordinate_line") or "")
    target_name = str(payload.get("target_name") or sample.display_name)
    input_mode = str(payload.get("input_mode") or "raw-file-k36")
    coordinate = _my_data_store(context).save_coordinate(
        user_id,
        display_name=f"{sample.display_name} K36",
        target_name=target_name,
        coordinate_type="k36",
        g25_line=coordinate_line,
        input_mode=input_mode,
    )
    _my_data_store(context).attach_coordinate_to_sample(user_id, sample.asset_id, coordinate.asset_id)
    await _save_k36_profile(message, context, user_id, coordinate_id=coordinate.asset_id, lang=lang)


async def admixture_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None or query.message is None:
        return
    if not query.data.startswith(f"{ADMIXTURE_CALLBACK_PREFIX}:"):
        return
    if not await ensure_active_main_menu(update, context):
        return
    if update.effective_user is None:
        return

    await query.answer()
    parts = query.data.split(":")
    action = parts[1] if len(parts) > 1 else ""
    user_id = update.effective_user.id
    lang = get_user_language(context, user_id)

    if action in {"root", "r"}:
        await show_admixture_menu(query.message, context, user_id, lang=lang, edit_existing=True)
        return
    if action == "cal":
        await show_raw_calculators_menu(query.message, context, lang=lang, edit_existing=True, user_id=user_id)
        return
    if action == "grp":
        await show_raw_project_models_menu(
            query.message,
            context,
            parts[2] if len(parts) > 2 else "",
            lang=lang,
            edit_existing=True,
            user_id=user_id,
        )
        return
    if action == "mdl":
        await show_raw_model_detail_menu(
            query.message,
            context,
            parts[2] if len(parts) > 2 else "",
            lang=lang,
            edit_existing=True,
            user_id=user_id,
        )
        return
    if action == "ms":
        await show_raw_model_sample_picker_menu(
            query.message,
            context,
            user_id,
            parts[2] if len(parts) > 2 else "",
            page=int(parts[3] if len(parts) > 3 else 0),
            lang=lang,
            edit_existing=True,
        )
        return
    if action == "mr":
        await _run_raw_model_profile(
            query.message,
            context,
            user_id,
            model_name=parts[2] if len(parts) > 2 else "",
            sample_id=parts[3] if len(parts) > 3 else "",
            lang=lang,
        )
        return
    if action == "cmp":
        await show_compare_profiles_menu(query.message, context, user_id, lang=lang, edit_existing=True)
        return
    if action == "cgrp":
        await show_compare_project_models_menu(
            query.message,
            context,
            user_id,
            parts[2] if len(parts) > 2 else "",
            lang=lang,
            edit_existing=True,
        )
        return
    if action == "cm":
        await show_compare_report_picker_menu(
            query.message,
            context,
            user_id,
            parts[2] if len(parts) > 2 else "",
            side="left",
            lang=lang,
            edit_existing=True,
        )
        return
    if action == "cl":
        await show_compare_report_picker_menu(
            query.message,
            context,
            user_id,
            parts[2] if len(parts) > 2 else "",
            side="right",
            left_report_id=parts[3] if len(parts) > 3 else "",
            lang=lang,
            edit_existing=True,
        )
        return
    if action == "cr":
        flow = _flow_store(context).get(parts[2] if len(parts) > 2 else "", user_id)
        if flow is None:
            await show_compare_profiles_menu(query.message, context, user_id, lang=lang, edit_existing=True)
            return
        await show_compare_result_menu(
            query.message,
            context,
            user_id,
            str(flow.get("left_report_id") or ""),
            parts[3] if len(parts) > 3 else "",
            lang=lang,
            edit_existing=True,
        )
        return
    if action == "op":
        await show_oracle_projects_menu(query.message, context, user_id, lang=lang, edit_existing=True)
        return
    if action == "omix":
        await show_oracle_mix_projects_menu(query.message, context, user_id, lang=lang, edit_existing=True)
        return
    if action == "omg":
        await show_oracle_mix_project_models_menu(
            query.message,
            context,
            user_id,
            parts[2] if len(parts) > 2 else "",
            lang=lang,
            edit_existing=True,
        )
        return
    if action == "omd":
        await show_oracle_mix_mode_menu(
            query.message,
            context,
            user_id,
            parts[2] if len(parts) > 2 else "",
            lang=lang,
            edit_existing=True,
        )
        return
    if action == "omm":
        await show_oracle_mix_report_picker_menu(
            query.message,
            context,
            user_id,
            parts[3] if len(parts) > 3 else "",
            parts[2] if len(parts) > 2 else "2",
            lang=lang,
            edit_existing=True,
        )
        return
    if action == "omr":
        await show_oracle_mix_result_menu(
            query.message,
            context,
            user_id,
            parts[2] if len(parts) > 2 else "2",
            parts[3] if len(parts) > 3 else "",
            lang=lang,
            edit_existing=True,
        )
        return
    if action == "paint":
        await show_placeholder_feature_menu(
            query.message,
            "🎨 Chromosome painting",
            _copy(
                lang,
                "Разметка участков хромосом по admixture-компонентам.",
                "Chromosome segment painting by admixture components.",
            ),
            context=context,
            user_id=user_id,
            lang=lang,
            edit_existing=True,
        )
        return
    if action == "opg":
        await show_oracle_project_models_menu(
            query.message,
            context,
            user_id,
            parts[2] if len(parts) > 2 else "",
            lang=lang,
            edit_existing=True,
        )
        return
    if action == "om":
        await show_oracle_report_picker_menu(
            query.message,
            context,
            user_id,
            parts[2] if len(parts) > 2 else "",
            lang=lang,
            edit_existing=True,
        )
        return
    if action == "or":
        await show_oracle_result_menu(
            query.message,
            context,
            user_id,
            parts[2] if len(parts) > 2 else "",
            lang=lang,
            edit_existing=True,
        )
        return
    if action == "k36":
        await show_k36_sample_picker_menu(query.message, context, user_id, lang=lang, edit_existing=True)
        return
    if action == "p":
        await show_k36_sample_picker_menu(query.message, context, user_id, page=int(parts[2] if len(parts) > 2 else 0), lang=lang, edit_existing=True)
        return
    if action == "s":
        await show_sample_admixture_reports_menu(query.message, context, user_id, parts[2] if len(parts) > 2 else "", lang=lang, edit_existing=True)
        return
    if action == "c":
        await show_k36_coordinate_picker_menu(query.message, context, user_id, parts[2] if len(parts) > 2 else "", lang=lang, edit_existing=True)
        return
    if action == "run":
        await _run_k36_profile(
            query.message,
            context,
            user_id,
            sample_id=parts[2] if len(parts) > 2 else "",
            coordinate_id=parts[3] if len(parts) > 3 else "",
            lang=lang,
        )
        return
    if action == "k":
        coordinate_id = parts[2] if len(parts) > 2 else ""
        sample = _my_data_store(context).find_sample_by_coordinate(user_id, coordinate_id)
        if sample is None:
            await _show_or_edit(
                query.message,
                error_text("K36 profile", _copy(lang, "Не удалось найти sample для этих координат.", "Could not find the sample for these coordinates.")),
                build_markup([], f"{ADMIXTURE_CALLBACK_PREFIX}:r", lang=lang),
                edit_existing=True,
                context=context,
                user_id=user_id,
            )
            return
        await _run_k36_profile(
            query.message,
            context,
            user_id,
            sample_id=sample.asset_id,
            coordinate_id=coordinate_id,
            lang=lang,
        )
        return
    if action == "save":
        await _save_k36_profile(
            query.message,
            context,
            user_id,
            coordinate_id=parts[2] if len(parts) > 2 else "",
            lang=lang,
        )
        return
    if action == "savem":
        await _save_raw_model_profile(
            query.message,
            context,
            user_id,
            token=parts[2] if len(parts) > 2 else "",
            lang=lang,
        )
        return
    if action == "svx":
        await _save_extracted_k36_profile(
            query.message,
            context,
            user_id,
            token=parts[2] if len(parts) > 2 else "",
            lang=lang,
        )
        return
    if action == "x":
        await _extract_k36_and_run(query.message, context, user_id, sample_id=parts[2] if len(parts) > 2 else "", lang=lang)
        return
    if action == "o":
        await show_admixture_report_detail_menu(query.message, context, user_id, parts[2] if len(parts) > 2 else "", lang=lang, edit_existing=True)
        return
    if action == "mo":
        report = _report_store(context).find_report(user_id, parts[2] if len(parts) > 2 else "")
        back_callback = (
            f"my_data:sample_admixture:{report.summary.sample_id}"
            if report is not None
            else "mydna:root"
        )
        await show_admixture_report_detail_menu(
            query.message,
            context,
            user_id,
            parts[2] if len(parts) > 2 else "",
            back_callback=back_callback,
            lang=lang,
            edit_existing=True,
        )
        return
