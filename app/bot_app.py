"""Legacy standalone DNA Lab launcher.

Production KBDNA starts from bot.py. This module is kept only for isolated
DNA Lab development, so it has an explicit guard against accidental server use.
"""

from __future__ import annotations

import logging
import os
import re

from telegram.ext import ApplicationBuilder, CallbackQueryHandler, CommandHandler, MessageHandler, filters

from app.config import load_settings
from app.features.admixture.menu import ADMIXTURE_CALLBACK_PREFIX, admixture_callback_handler, register_admixture_services
from app.features.coordinate_space.menu import COORDINATE_SPACE_CALLBACK_PREFIX, coordinate_space_callback_handler
from app.features.haplogroups.menu import (
    HAPLOGROUPS_CALLBACK_PREFIX,
    haplogroups_callback_handler,
    haplogroups_document_input_handler,
    haplogroups_text_input_handler,
    register_haplogroup_services,
)
from app.features.help.menu import HELP_CALLBACK_PREFIX, help_callback_handler
from app.features.matching.menu import MATCHING_CALLBACK_PREFIX, matching_callback_handler, matching_text_input_handler, register_matching_services
from app.features.modeling.menu import MODELING_CALLBACK_PREFIX, modeling_callback_handler
from app.features.my_data.menu import (
    MY_DATA_CALLBACK_PREFIX,
    my_data_callback_handler,
    my_data_document_input_handler,
    my_data_text_input_handler,
    quick_g25_coordinates_reply_handler,
    register_my_data_services,
)
from app.features.reports.menu import REPORTS_CALLBACK_PREFIX, reports_callback_handler
from app.features.settings.menu import SETTINGS_CALLBACK_PREFIX, register_settings_services, settings_callback_handler
from app.features.traits.menu import TRAITS_CALLBACK_PREFIX, register_traits_services, traits_callback_handler
from app.features.vahaduo.menu import (
    VAHADUO_CALLBACK_PREFIX,
    register_vahaduo_services,
    vahaduo_callback_handler,
    vahaduo_document_input_handler,
    vahaduo_text_input_handler,
)
from app.main_menu import (
    MAIN_CALLBACK_PREFIX,
    G25_COORDINATES_REPLY_BUTTON_TEXT,
    admin_stats_reply_handler,
    main_menu_callback_handler,
    main_menu_command,
    main_menu_reply_handler,
    start_command,
)


ALLOW_LEGACY_STANDALONE_ENV = 'KBDNA_ALLOW_LEGACY_DNA_LAB_STANDALONE'


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        format='%(asctime)s %(levelname)s %(name)s: %(message)s',
        level=getattr(logging, level.upper(), logging.INFO),
    )


def build_application():
    settings = load_settings()
    _configure_logging(settings.log_level)

    application = ApplicationBuilder().token(settings.bot_token).build()
    register_settings_services(application, settings)
    register_my_data_services(application, settings)
    register_traits_services(application, settings)
    register_admixture_services(application, settings)
    register_matching_services(application, settings)
    register_haplogroup_services(application, settings)
    register_vahaduo_services(application, settings)

    application.add_handler(CommandHandler('start', start_command))
    application.add_handler(CommandHandler('menu', main_menu_command))
    application.add_handler(CommandHandler('stats', admin_stats_reply_handler))
    application.add_handler(MessageHandler(filters.Regex(f'^{re.escape(G25_COORDINATES_REPLY_BUTTON_TEXT)}$'), quick_g25_coordinates_reply_handler))
    application.add_handler(MessageHandler(filters.Regex(r'^(Menu)$'), main_menu_reply_handler))

    application.add_handler(CallbackQueryHandler(main_menu_callback_handler, pattern=fr'^{MAIN_CALLBACK_PREFIX}:'))
    application.add_handler(CallbackQueryHandler(coordinate_space_callback_handler, pattern=fr'^{COORDINATE_SPACE_CALLBACK_PREFIX}:'))
    application.add_handler(CallbackQueryHandler(admixture_callback_handler, pattern=fr'^{ADMIXTURE_CALLBACK_PREFIX}:'))
    application.add_handler(CallbackQueryHandler(modeling_callback_handler, pattern=fr'^{MODELING_CALLBACK_PREFIX}:'))
    application.add_handler(CallbackQueryHandler(matching_callback_handler, pattern=fr'^{MATCHING_CALLBACK_PREFIX}:'))
    application.add_handler(CallbackQueryHandler(traits_callback_handler, pattern=fr'^{TRAITS_CALLBACK_PREFIX}:'))
    application.add_handler(CallbackQueryHandler(haplogroups_callback_handler, pattern=fr'^{HAPLOGROUPS_CALLBACK_PREFIX}:'))
    application.add_handler(CallbackQueryHandler(my_data_callback_handler, pattern=fr'^{MY_DATA_CALLBACK_PREFIX}:'))
    application.add_handler(CallbackQueryHandler(reports_callback_handler, pattern=fr'^{REPORTS_CALLBACK_PREFIX}:'))
    application.add_handler(CallbackQueryHandler(settings_callback_handler, pattern=fr'^{SETTINGS_CALLBACK_PREFIX}:'))
    application.add_handler(CallbackQueryHandler(help_callback_handler, pattern=fr'^{HELP_CALLBACK_PREFIX}:'))
    application.add_handler(CallbackQueryHandler(vahaduo_callback_handler, pattern=fr'^{VAHADUO_CALLBACK_PREFIX}:'))

    application.add_handler(MessageHandler(filters.Document.ALL, my_data_document_input_handler), group=0)
    application.add_handler(MessageHandler(filters.Document.ALL, vahaduo_document_input_handler), group=1)
    application.add_handler(MessageHandler(filters.Document.ALL, haplogroups_document_input_handler), group=3)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, my_data_text_input_handler), group=0)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, vahaduo_text_input_handler), group=1)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, matching_text_input_handler), group=2)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, haplogroups_text_input_handler), group=3)

    return application


def main() -> None:
    if os.getenv(ALLOW_LEGACY_STANDALONE_ENV, '').strip() != '1':
        raise RuntimeError(
            'app.bot_app is a legacy standalone DNA Lab launcher. '
            'Run the merged KBDNA bot with `python bot.py`, or set '
            f'{ALLOW_LEGACY_STANDALONE_ENV}=1 only for isolated development.'
        )
    application = build_application()
    application.run_polling()
