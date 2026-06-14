from __future__ import annotations

from functools import lru_cache
import logging
import math
import os
import tempfile
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from g25_core import g25_engine
from g25_core.render_fit_png import _draw_text, _put_rect, _write_png

from app.i18n import get_user_language, t
from app.features.coordinate_space import g25_summary as coordinate_g25_summary
from app.features.coordinate_space.reports import CoordinateSpaceReportStore
try:
    from app.features.coordinate_space.visualization import render_coordinate_space_png
except ModuleNotFoundError as exc:
    if exc.name not in {'PIL', 'numpy'}:
        raise
    render_coordinate_space_png = None
from app.features.my_data.storage import CoordinateAsset, MyDataStore, SampleAsset
from app.main_menu import ensure_active_main_menu


logger = logging.getLogger(__name__)

COORDINATE_SPACE_CALLBACK_PREFIX = 'coordinate_space'
_COORDINATE_SPACE_SAMPLE_PICKER_LIMIT = 30


def _copy(lang: str, ru: str, en: str) -> str:
    return en if lang == 'en' else ru


def _back_label(lang: str) -> str:
    return _copy(lang, '⬅️ Назад', t('nav.back', lang))


def _cancel_label(lang: str) -> str:
    return t('nav.cancel', lang)


def _back_cancel_row(back_callback: str, *, lang: str = 'ru') -> list[InlineKeyboardButton]:
    return [
        InlineKeyboardButton(_back_label(lang), callback_data=back_callback),
        InlineKeyboardButton(_cancel_label(lang), callback_data=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:cancel'),
    ]


def _save_report_label(lang: str = 'ru') -> str:
    return _copy(lang, '💾 Сохранить отчёт', '💾 Save report')


def _change_g25_label(lang: str = 'ru') -> str:
    return _copy(lang, '🔁 Выбрать другой G25', '🔁 Choose another G25')


_VISIBLE_SPACE_TITLES: dict[str, str] = {
    'Global': '🌍 Global',
    'West Eurasia': '🧭 West Eurasia',
    'Europe': '🇪🇺 Europe',
    'Caucasus / Steppe': '⛰ Caucasus / Steppe',
    'South Asia': '🌿 South Asia',
    'East Eurasia': '🌏 East Eurasia',
    'North Caucasus': '🏔 North Caucasus',
    'South Caucasus': '🏔 South Caucasus',
    'Steppe fringe': '🐎 Steppe fringe',
    'Caucasus': '⛰ Caucasus',
    'Steppe': '🐎 Steppe',
    'Anatolia': '🌄 Anatolia',
    'Levant': '🌊 Levant',
    'Mesopotamia / Iran': '🏺 Mesopotamia / Iran',
    'East Europe': '🇪🇺 East Europe',
    'North Europe': '🌲 North Europe',
    'South Europe': '☀️ South Europe',
    'Balkans': '⛰ Balkans',
    'Baltic': '🌊 Baltic',
    'Northwest South Asia': '🌿 Northwest South Asia',
    'Gangetic / North India': '🏞 Gangetic / North India',
    'West India': '🌅 West India',
    'South India': '🌴 South India',
    'East India / Bengal': '🌾 East India / Bengal',
    'Northeast Asia': '🌏 Northeast Asia',
    'North China': '🏯 North China',
    'South China': '🌾 South China',
    'Siberia / Inner Asia': '❄️ Siberia / Inner Asia',
}


def _visible_space_title(title: object) -> str:
    cleaned = str(title or '').strip()
    if not cleaned:
        return '🧭 Coordinates'
    if cleaned[:1] and not cleaned[:1].isascii():
        return cleaned
    return _VISIBLE_SPACE_TITLES.get(cleaned, cleaned)


def _caption_space_title(title: object, mode: str) -> str:
    visible = _visible_space_title(title)
    if visible == str(title or '').strip() and mode == 'population':
        return f'⛰ {visible}'
    if visible == str(title or '').strip() and mode != 'population':
        return f'🧭 {visible}'
    return visible


def _whole_region_label(lang: str = 'ru') -> str:
    return _copy(lang, '🧭 Весь регион', '🧭 Whole region')


def _all_populations_label(lang: str = 'ru') -> str:
    return _copy(lang, '👥 Все популяции', '👥 All populations')


def _samples_source_label(lang: str) -> str:
    return '🧬 Samples'


def _other_g25_source_label(lang: str) -> str:
    return _copy(lang, '📍 G25-профили', '📍 G25 profiles')


def _target_source_label(source: str | None, lang: str) -> str:
    if source == 'samples':
        return _samples_source_label(lang)
    if source == 'other':
        return _other_g25_source_label(lang)
    return _copy(lang, 'G25-координаты', 'G25 coordinates')


def _target_source_for_sample_id(sample_id: str) -> str:
    value = str(sample_id or '')
    if value.startswith((_G25_LIBRARY_SAMPLE_PREFIX, _G25_LIBRARY_LEGACY_SAMPLE_PREFIX)):
        return 'other'
    return 'samples'


def _target_list_back_callback(sample_root: str, sample_id: str, *, source: str | None = None) -> str:
    target_source = source if source in {'samples', 'other'} else _target_source_for_sample_id(sample_id)
    return f'{COORDINATE_SPACE_CALLBACK_PREFIX}:picksrc:{sample_root}:{target_source}'

_ROOT_PLACEHOLDER_TITLES: dict[str, str] = {
    'project_into_space': 'Project into space',
    'compare_in_current_space': 'Compare in current space',
    'viewer_3d': '3D viewer',
    'saved_sessions': 'Сохранённые сессии',
}

_READY_MADE_SPACE_TITLES: dict[str, str] = {
    'ready_made_europe': 'Europe',
    'ready_made_caucasus_steppe': 'Caucasus / Steppe',
    'ready_made_south_asia': 'South Asia',
    'ready_made_east_eurasia': 'East Eurasia',
}

_MODERN_G25_AVERAGES_PATH = Path(__file__).resolve().parent / 'data' / 'Global25_PCA_modern_pop_averages_scaled.txt'


def _ordered_unique_labels(*groups: tuple[str, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for group in groups:
        for label in group:
            if label in seen:
                continue
            seen.add(label)
            ordered.append(label)
    return tuple(ordered)


def _build_grouped_population_layout(
    groups: tuple[tuple[tuple[str, ...], tuple[int, int], int], ...],
    *,
    x_spacing: int = 38,
    y_spacing: int = 30,
) -> dict[str, tuple[int, int]]:
    layout: dict[str, tuple[int, int]] = {}
    for labels, (center_x, center_y), columns in groups:
        rows = max(1, math.ceil(len(labels) / columns))
        start_x = center_x - ((columns - 1) * x_spacing) // 2
        start_y = center_y - ((rows - 1) * y_spacing) // 2
        for index, label in enumerate(labels):
            if label in layout:
                continue
            layout[label] = (
                start_x + (index % columns) * x_spacing,
                start_y + (index // columns) * y_spacing,
            )
    return layout

_GLOBAL_REGION_LABELS: dict[str, tuple[str, ...]] = {
    'Europe': (
        'Austrian',
        'BelgianA',
        'Czech',
        'Danish',
        'Dutch',
        'English',
        'French_Paris',
        'German',
        'Irish',
        'Italian_Northeast',
        'Norwegian',
        'Polish',
        'Romanian',
        'Scottish',
        'Spanish_Castilla_Y_Leon',
        'Swedish',
        'Belarusian',
        'Ukrainian_Lviv',
        'Russian_Belgorod',
        'Russian_Smolensk',
    ),
    'Caucasus': (
        'Abazin',
        'Abkhasian',
        'Adygei',
        'Circassian',
        'Cherkes',
        'Avar',
        'Balkar',
        'Chechen',
        'Ingushian',
        'Kabardin',
        'Karachay',
        'Kumyk',
        'Lezgin',
        'North_Ossetian',
        'Ossetian',
        'Armenian_Ararat',
        'Armenian_Syunik',
        'Georgian_Kart',
        'Georgian_Kakh',
        'Georgian_Svaneti',
    ),
    'Middle East': (
        'Alawite',
        'BedouinA',
        'BedouinB',
        'Druze',
        'Jordanian',
        'Lebanese_Christian',
        'Lebanese_Druze',
        'Lebanese_Maronite_Christian_Zgharta',
        'Lebanese_Muslim',
        'Palestinian',
        'Palestinian_Beit_Sahour',
        'Samaritan',
        'Syrian',
        'Syrian_Aleppo',
        'Syrian_Hama',
        'Syrian_Homs',
        'Iraqi_Arab_Central',
        'Iraqi_Arab_West',
    ),
    'Central Asia': (
        'Uzbek',
        'Turkmen',
        'Turkmen_Uzbekistan',
        'Turkmen_Iran',
        'Kirghiz_Tajikistan_Pamir',
        'Tajik_Afghanistan',
        'Tajik_Tajikistan_Ayni',
        'Tajik_Tajikistan_Hisor',
        'Tajik_Tajikistan_Kulob',
        'Tajik_Yaghnobi',
        'Pamiri_Badakhshan',
        'Pamiri_Rushan',
        'Pamiri_Shugnan',
        'Pamiri_Wakhi',
        'Pashtun_Afghanistan',
    ),
    'South Asia': (
        'Arain',
        'Awan',
        'Gujarati',
        'Punjabi_Hindu_India',
        'Punjabi_Lahore',
        'Bengali_Bangladesh',
        'Bengali_India',
        'Sinhala',
        'Telugu',
        'Brahmin_Tamil_Nadu',
        'Nepali_Indo-Aryan_A',
        'Balochi_Pakistan',
        'Pashtun_Pakistan',
    ),
    'East Asia': (
        'Han_Henan',
        'Han_Shandong',
        'Han_Sichuan',
        'Japanese',
        'Korean',
        'Mongol',
        'Daur',
        'Hezhen',
        'Yi',
        'Naxi',
    ),
    'Africa': (
        'Algerian',
        'Berber_Algeria',
        'Moroccan',
        'Tunisian',
        'Libyan',
        'EgyptianA',
        'Egyptian_Copt',
        'Bantu_Kenya',
        'Bantu_S.E.',
        'Baka',
        'Bakola',
        'Bedzan',
    ),
    'Americas': (
        'Amerindian_North',
        'Aymara',
        'Quechua',
        'Pima',
        'Karitiana',
        'Surui',
        'Mixtec',
        'Mayan',
    ),
    'Oceania': (
        'Australian',
        'Papuan',
        'Papuan_Highland_A',
        'Papuan_Highland_B',
        'Maori',
    ),
}

_GLOBAL_REGION_LAYOUT: dict[str, tuple[int, int]] = {
    'Europe': (330, 110),
    'Caucasus': (465, 112),
    'Middle East': (500, 198),
    'Central Asia': (470, 275),
    'South Asia': (590, 320),
    'East Asia': (710, 245),
    'Africa': (355, 230),
    'Americas': (105, 170),
    'Oceania': (725, 385),
}

_GLOBAL_SAMPLE_OFFSETS: dict[str, tuple[int, int]] = {
    'Europe': (24, -26),
    'Caucasus': (24, -22),
    'Middle East': (26, -20),
    'Central Asia': (24, -24),
    'South Asia': (22, -24),
    'East Asia': (26, -18),
    'Africa': (24, -24),
    'Americas': (24, -24),
    'Oceania': (-24, -24),
}

_GLOBAL_LABEL_OFFSETS: dict[str, tuple[int, int]] = {
    'Europe': (-28, -32),
    'Caucasus': (-38, -32),
    'Middle East': (-52, 18),
    'Central Asia': (-52, 18),
    'South Asia': (-44, 18),
    'East Asia': (-34, 18),
    'Africa': (-26, 18),
    'Americas': (-44, 18),
    'Oceania': (-32, 18),
}

_WEST_EURASIA_REGION_LABELS: dict[str, tuple[str, ...]] = {
    'Europe': (
        'Austrian',
        'BelgianA',
        'Czech',
        'Danish',
        'Dutch',
        'English',
        'French_Paris',
        'German',
        'Irish',
        'Italian_Northeast',
        'Norwegian',
        'Polish',
        'Romanian',
        'Scottish',
        'Spanish_Castilla_Y_Leon',
        'Swedish',
        'Hungarian',
        'Croatian',
        'Russian_Belgorod',
        'Russian_Smolensk',
    ),
    'Caucasus': (
        'Abazin',
        'Abkhasian',
        'Adygei',
        'Circassian',
        'Cherkes',
        'Avar',
        'Balkar',
        'Chechen',
        'Ingushian',
        'Kabardin',
        'Karachay',
        'Kumyk',
        'Lezgin',
        'North_Ossetian',
        'Ossetian',
        'Armenian_Ararat',
        'Armenian_Artsakh',
        'Armenian_Syunik',
        'Georgian_Kart',
        'Georgian_Svaneti',
        'Georgian_Kakh',
    ),
    # No exact "Anatolia" label exists in the file, so this centroid uses modern
    # Central/West Anatolian populations that are explicitly present in the dataset.
    'Anatolia': (
        'Turkish_Antalya',
        'Turkish_Aydin',
        'Turkish_Balikesir',
        'Turkish_Denizli',
        'Turkish_Kayseri',
        'Turkish_Konya',
        'Turkish_Nevsehir',
        'Turkish_Sivas',
        'Greek_Central_Anatolia',
        'Alevi_Dersim',
    ),
    'Levant': (
        'Alawite',
        'Druze',
        'Jordanian',
        'Lebanese_Christian',
        'Lebanese_Druze',
        'Lebanese_Maronite_Christian_Zgharta',
        'Lebanese_Muslim',
        'Lebanese_Orthodox_Christian_Koura',
        'Palestinian',
        'Palestinian_Beit_Sahour',
        'Samaritan',
        'Syrian',
        'Syrian_Aleppo',
        'Syrian_Hama',
        'Syrian_Homs',
    ),
    # No exact "Mesopotamia" label exists in the file, so this centroid uses
    # modern Assyrian and Iraqi core populations from Upper and Lower Mesopotamia.
    'Mesopotamia': (
        'Assyrian',
        'Assyrian_Mardin',
        'Assyrian_o',
        'Iraqi_Arab_Central',
        'Iraqi_Arab_South',
        'Iraqi_Arab_West',
        'Kurd_Iraq',
        'Kurd_Syria',
    ),
    'Iran': (
        'Iranian_Central',
        'Iranian_Cosmopolitan_Tehran',
        'Iranian_Lor_Bakhtiari',
        'Iranian_Lor_Khorramabad',
        'Iranian_Mazandarani',
        'Iranian_Persian_Fars',
        'Iranian_Persian_Khorasan',
        'Iranian_Persian_Shiraz',
        'Iranian_Persian_Yazd',
        'Iranian_Qashqai',
        'Iranian_Zoroastrian',
        'Kurd_Sorani_Iran_Mukriyan',
    ),
    # No exact "Steppe" label exists in the file, so this centroid uses modern
    # steppe-facing populations present in the dataset.
    'Steppe': (
        'Nogai',
        'Nogai_Dobruja',
        'Tatar_Crimean_steppe',
        'Tatar_Kazan',
        'Tatar_Mishar',
        'Bashkir',
        'Chuvash',
        'Cossack_Kuban',
        'Russian_Belgorod',
        'Russian_Voronez',
    ),
    'North Africa': (
        'Algerian',
        'Berber_Algeria',
        'Moroccan',
        'Moroccan_North',
        'Tunisian',
        'Tunisian_Berber_Matmata',
        'Libyan',
        'EgyptianA',
        'Egyptian_Copt',
    ),
}

_WEST_EURASIA_REGION_LAYOUT: dict[str, tuple[int, int]] = {
    'Europe': (245, 120),
    'Caucasus': (470, 125),
    'Anatolia': (360, 230),
    'Levant': (345, 312),
    'Mesopotamia': (455, 280),
    'Iran': (610, 255),
    'Steppe': (420, 72),
    'North Africa': (170, 335),
}

_WEST_EURASIA_SAMPLE_OFFSETS: dict[str, tuple[int, int]] = {
    'Europe': (26, -20),
    'Caucasus': (24, -20),
    'Anatolia': (24, -22),
    'Levant': (24, -18),
    'Mesopotamia': (24, -20),
    'Iran': (24, -22),
    'Steppe': (24, -18),
    'North Africa': (26, -20),
}

_WEST_EURASIA_LABEL_OFFSETS: dict[str, tuple[int, int]] = {
    'Europe': (-20, -34),
    'Caucasus': (-40, -34),
    'Anatolia': (-34, 18),
    'Levant': (-22, 18),
    'Mesopotamia': (-54, 18),
    'Iran': (-10, 18),
    'Steppe': (-22, -34),
    'North Africa': (-54, 18),
}

_EUROPE_REGION_LABELS: dict[str, tuple[str, ...]] = {
    'Atlantic': ('English', 'Irish', 'Scottish', 'French_Brittany', 'French_Nord', 'Dutch', 'BelgianA'),
    'Iberia': ('Portuguese', 'Spanish_Galicia', 'Spanish_Castilla_Y_Leon', 'Spanish_Andalucia', 'Basque_Spanish'),
    'Central Europe': ('German', 'Austrian', 'Swiss_German', 'Czech', 'Hungarian'),
    'North Europe': ('Danish', 'Norwegian', 'Swedish', 'Finnish_Southwest', 'Finnish_Central'),
    'East Europe': ('Belarusian', 'Ukrainian_Lviv', 'Ukrainian_Dnipro', 'Russian_Belgorod', 'Russian_Smolensk', 'Polish'),
    'Balkans': ('Albanian', 'Serbian', 'Croatian', 'Bosnian', 'Romanian', 'Greek_Macedonia'),
    'Mediterranean': ('Italian_Northeast', 'Italian_Tuscany', 'Italian_Calabria', 'Sardinian', 'Greek_Crete'),
}

_EUROPE_REGION_LAYOUT: dict[str, tuple[int, int]] = {
    'Atlantic': (180, 118),
    'Iberia': (180, 302),
    'Central Europe': (390, 168),
    'North Europe': (390, 76),
    'East Europe': (610, 160),
    'Balkans': (560, 290),
    'Mediterranean': (350, 334),
}

_EUROPE_LABEL_OFFSETS: dict[str, tuple[int, int]] = {
    'Atlantic': (-38, -32),
    'Iberia': (-26, 18),
    'Central Europe': (-66, -32),
    'North Europe': (-52, -32),
    'East Europe': (-46, -32),
    'Balkans': (-34, 18),
    'Mediterranean': (-72, 18),
}

_CAUCASUS_STEPPE_REGION_LABELS: dict[str, tuple[str, ...]] = {
    'NW Caucasus': ('Abazin', 'Abkhasian', 'Adygei', 'Circassian', 'Cherkes', 'Kabardin', 'Karachay', 'Balkar'),
    'NE Caucasus': ('Avar', 'Chechen', 'Ingushian', 'Kumyk', 'Lezgin'),
    'South Caucasus': ('Armenian_Ararat', 'Armenian_Artsakh', 'Armenian_Syunik', 'Georgian_Kart', 'Georgian_Kakh', 'Georgian_Svaneti'),
    'Anatolia': ('Turkish_Antalya', 'Turkish_Aydin', 'Turkish_Balikesir', 'Turkish_Denizli', 'Turkish_Konya', 'Greek_Central_Anatolia', 'Alevi_Dersim'),
    'Pontic Steppe': ('Nogai', 'Cossack_Kuban', 'Russian_Voronez', 'Tatar_Crimean_steppe'),
    'Volga-Ural': ('Tatar_Kazan', 'Tatar_Mishar', 'Bashkir', 'Chuvash'),
}

_CAUCASUS_STEPPE_REGION_LAYOUT: dict[str, tuple[int, int]] = {
    'NW Caucasus': (224, 186),
    'NE Caucasus': (378, 146),
    'South Caucasus': (354, 254),
    'Anatolia': (256, 322),
    'Pontic Steppe': (570, 164),
    'Volga-Ural': (690, 122),
}

_CAUCASUS_STEPPE_LABEL_OFFSETS: dict[str, tuple[int, int]] = {
    'NW Caucasus': (-58, -32),
    'NE Caucasus': (-58, -32),
    'South Caucasus': (-68, 18),
    'Anatolia': (-34, 18),
    'Pontic Steppe': (-58, -32),
    'Volga-Ural': (-46, -32),
}

_SOUTH_ASIA_REGION_LABELS: dict[str, tuple[str, ...]] = {
    'Northwest': (
        'Arain',
        'Awan',
        'Punjabi_Hindu_India',
        'Punjabi_Lahore',
        'Punjabi_Christian_India',
        'Punjabi_Muslim_India',
        'Punjabi_Sikh_India',
        'Brahmin_Punjab',
        'Rajput_Punjab',
        'Pashtun_Pakistan',
        'Balochi_Pakistan',
        'Burusho',
        'Kalash',
    ),
    'Gangetic': ('Brahmin_Uttar_Pradesh_Awadh', 'Brahmin_Uttar_Pradesh_Braj', 'Brahmin_Uttar_Pradesh_East', 'Brahmin_Rajasthan'),
    'West India': (
        'Gujarati',
        'Gujarati_Bharuch_Muslim',
        'Brahmin_Gujarat',
        'Brahmin_Gujarat_Nagar',
        'Brahmin_Gujarat_Audichya',
        'Brahmin_Gujarat_o',
        'Brahmin_Chitpavan',
        'Sonar_Marathi',
        'Rajput_Rajasthan',
    ),
    'East India': ('Bengali_Bangladesh', 'Bengali_Bangladesh_Sylhet', 'Bengali_India', 'Brahmin_West_Bengal'),
    'South India': (
        'Telugu',
        'Yadav_Telugu',
        'Reddy',
        'Pillai_Tamil',
        'Tamil_Sri_Lanka',
        'Sinhala',
        'Vellalar',
        'Poduval_Kerala_North',
        'Vishwakarma_Kerala',
    ),
    'Himalayan': ('Nepali_Indo-Aryan_A', 'Nepali_Indo-Aryan_B', 'Nepali_Sherpa_Rolwaling', 'Nepali_Tamang_Simigaon', 'Tamang', 'Sherpa', 'Balti'),
}

_SOUTH_ASIA_REGION_LAYOUT: dict[str, tuple[int, int]] = {
    'Northwest': (184, 152),
    'Gangetic': (388, 184),
    'West India': (236, 286),
    'East India': (606, 194),
    'South India': (394, 340),
    'Himalayan': (308, 92),
}

_SOUTH_ASIA_LABEL_OFFSETS: dict[str, tuple[int, int]] = {
    'Northwest': (-42, -32),
    'Gangetic': (-38, 18),
    'West India': (-46, 18),
    'East India': (-42, 18),
    'South India': (-50, 18),
    'Himalayan': (-50, -32),
}

# West Eurasia detail acts as a bridge layer and keeps all centroids strictly
# modern-only, without trying to force samples into narrower 2D visual anchors.
_WEST_EURASIA_EUROPE_DETAIL_REGION_LABELS: dict[str, tuple[str, ...]] = {
    'North Europe': ('Danish', 'Norwegian', 'Swedish', 'Finnish_Southwest', 'Finnish_Central'),
    'East Europe': ('Belarusian', 'Ukrainian_Lviv', 'Ukrainian_Dnipro', 'Russian_Belgorod', 'Russian_Smolensk', 'Polish'),
    'South Europe': ('Italian_Northeast', 'Italian_Tuscany', 'Italian_Calabria', 'Sardinian', 'Greek_Crete'),
    'Balkans': ('Albanian', 'Serbian', 'Croatian', 'Bosnian', 'Romanian', 'Greek_Macedonia'),
    'Baltic': ('Estonian', 'Latvian', 'Lithuanian_PA', 'Lithuanian_VA', 'Lithuanian_RA'),
}

_WEST_EURASIA_EUROPE_DETAIL_LAYOUT: dict[str, tuple[int, int]] = {
    'North Europe': (250, 104),
    'East Europe': (528, 170),
    'South Europe': (314, 318),
    'Balkans': (544, 286),
    'Baltic': (406, 118),
}

_WEST_EURASIA_EUROPE_DETAIL_LABEL_OFFSETS: dict[str, tuple[int, int]] = {
    'North Europe': (-84, -32),
    'East Europe': (-70, -32),
    'South Europe': (-84, 18),
    'Balkans': (-58, 18),
    'Baltic': (-42, -32),
}

_WEST_EURASIA_EUROPE_POPULATION_LABELS: tuple[str, ...] = (
    'Danish',
    'Norwegian',
    'Swedish',
    'Finnish_Southwest',
    'Finnish_Central',
    'Belarusian',
    'Ukrainian_Lviv',
    'Ukrainian_Dnipro',
    'Russian_Belgorod',
    'Russian_Smolensk',
    'Polish',
    'Italian_Northeast',
    'Italian_Tuscany',
    'Italian_Calabria',
    'Sardinian',
    'Greek_Crete',
    'Albanian',
    'Serbian',
    'Croatian',
    'Bosnian',
    'Romanian',
    'Greek_Macedonia',
    'Estonian',
    'Latvian',
    'Lithuanian_PA',
    'Lithuanian_VA',
    'Lithuanian_RA',
)

_WEST_EURASIA_EUROPE_POPULATION_LAYOUT: dict[str, tuple[int, int]] = {
    'Danish': (190, 88),
    'Norwegian': (154, 122),
    'Swedish': (236, 130),
    'Finnish_Southwest': (318, 74),
    'Finnish_Central': (362, 122),
    'Belarusian': (446, 176),
    'Ukrainian_Lviv': (430, 248),
    'Ukrainian_Dnipro': (516, 220),
    'Russian_Belgorod': (594, 186),
    'Russian_Smolensk': (530, 132),
    'Polish': (384, 190),
    'Italian_Northeast': (292, 286),
    'Italian_Tuscany': (236, 332),
    'Italian_Calabria': (358, 366),
    'Sardinian': (160, 374),
    'Greek_Crete': (446, 382),
    'Albanian': (504, 300),
    'Serbian': (560, 264),
    'Croatian': (514, 230),
    'Bosnian': (468, 262),
    'Romanian': (602, 250),
    'Greek_Macedonia': (618, 318),
    'Estonian': (436, 86),
    'Latvian': (486, 104),
    'Lithuanian_PA': (550, 98),
    'Lithuanian_VA': (600, 122),
    'Lithuanian_RA': (650, 148),
}

_WEST_EURASIA_CAUCASUS_DETAIL_REGION_LABELS: dict[str, tuple[str, ...]] = {
    'North Caucasus': ('Abazin', 'Adygei', 'Circassian', 'Cherkes', 'Kabardin', 'Balkar', 'Karachay', 'North_Ossetian', 'Ossetian', 'Ingushian', 'Avar', 'Chechen', 'Lezgin'),
    'South Caucasus': ('Armenian_Ararat', 'Armenian_Artsakh', 'Armenian_Syunik', 'Georgian_Kart', 'Georgian_Kakh', 'Georgian_Svaneti', 'Azerbaijani_Republic_Gabala'),
    'Steppe-adjacent Caucasus': ('Kumyk', 'Nogai', 'Nogai_Dobruja', 'Cossack_Kuban', 'Azerbaijani_Dagestan'),
}

_WEST_EURASIA_CAUCASUS_DETAIL_LAYOUT: dict[str, tuple[int, int]] = {
    'North Caucasus': (228, 162),
    'South Caucasus': (434, 246),
    'Steppe-adjacent Caucasus': (622, 172),
}

_WEST_EURASIA_CAUCASUS_DETAIL_LABEL_OFFSETS: dict[str, tuple[int, int]] = {
    'North Caucasus': (-92, -32),
    'South Caucasus': (-96, 18),
    'Steppe-adjacent Caucasus': (-164, -32),
}

_WEST_EURASIA_CAUCASUS_POPULATION_LABELS: tuple[str, ...] = (
    'Abazin',
    'Abkhasian',
    'Adygei',
    'Circassian',
    'Cherkes',
    'Kabardin',
    'Balkar',
    'Karachay',
    'North_Ossetian',
    'Ossetian',
    'Ingushian',
    'Avar',
    'Chechen',
    'Lezgin',
    'Kumyk',
    'Nogai',
    'Nogai_Dobruja',
    'Cossack_Kuban',
    'Armenian_Ararat',
    'Armenian_Artsakh',
    'Armenian_Syunik',
    'Georgian_Kart',
    'Georgian_Kakh',
    'Georgian_Svaneti',
    'Azerbaijani_Dagestan',
    'Azerbaijani_Republic_Gabala',
)

_WEST_EURASIA_CAUCASUS_POPULATION_LAYOUT: dict[str, tuple[int, int]] = {
    'Abazin': (128, 128),
    'Abkhasian': (152, 176),
    'Adygei': (198, 132),
    'Circassian': (238, 174),
    'Cherkes': (280, 146),
    'Kabardin': (332, 164),
    'Balkar': (364, 204),
    'Karachay': (312, 244),
    'North_Ossetian': (430, 176),
    'Ossetian': (470, 216),
    'Ingushian': (508, 160),
    'Avar': (576, 132),
    'Chechen': (626, 174),
    'Lezgin': (690, 212),
    'Kumyk': (550, 272),
    'Nogai': (628, 294),
    'Nogai_Dobruja': (706, 326),
    'Cossack_Kuban': (510, 320),
    'Armenian_Ararat': (334, 300),
    'Armenian_Artsakh': (410, 262),
    'Armenian_Syunik': (474, 336),
    'Georgian_Kart': (280, 238),
    'Georgian_Kakh': (516, 220),
    'Georgian_Svaneti': (226, 214),
    'Azerbaijani_Dagestan': (642, 236),
    'Azerbaijani_Republic_Gabala': (590, 210),
}

# No exact modern west/central/east Anatolia cluster labels exist, so these
# groups use the closest present-day regional analogs available in the file.
_WEST_EURASIA_ANATOLIA_DETAIL_REGION_LABELS: dict[str, tuple[str, ...]] = {
    'West Anatolia': ('Turkish_Aydin', 'Turkish_Balikesir', 'Turkish_Canakkale_Europe', 'Turkish_Antalya', 'Greek_Izmir'),
    'Central Anatolia': ('Turkish_Konya', 'Greek_Central_Anatolia', 'Turkish_Nevsehir', 'Turkish_Kayseri', 'Turkish_Sivas'),
    'East Anatolia': ('Turkish_Erzurum', 'Armenian_Erzurum', 'Armenian_Gesaria', 'Alevi_Dersim', 'Armenian_Hemsheni', 'Turkish_Trabzon'),
}

_WEST_EURASIA_ANATOLIA_DETAIL_LAYOUT: dict[str, tuple[int, int]] = {
    'West Anatolia': (218, 262),
    'Central Anatolia': (440, 214),
    'East Anatolia': (646, 160),
}

_WEST_EURASIA_ANATOLIA_DETAIL_LABEL_OFFSETS: dict[str, tuple[int, int]] = {
    'West Anatolia': (-94, 18),
    'Central Anatolia': (-106, -32),
    'East Anatolia': (-86, -32),
}

_WEST_EURASIA_ANATOLIA_POPULATION_LABELS: tuple[str, ...] = (
    'Turkish_Aydin',
    'Turkish_Balikesir',
    'Turkish_Canakkale_Europe',
    'Turkish_Antalya',
    'Greek_Izmir',
    'Turkish_Konya',
    'Greek_Central_Anatolia',
    'Turkish_Nevsehir',
    'Turkish_Kayseri',
    'Turkish_Sivas',
    'Turkish_Erzurum',
    'Armenian_Erzurum',
    'Armenian_Gesaria',
    'Alevi_Dersim',
    'Armenian_Hemsheni',
    'Turkish_Trabzon',
    'Turkish_Giresun',
)

_WEST_EURASIA_ANATOLIA_POPULATION_LAYOUT: dict[str, tuple[int, int]] = {
    'Turkish_Aydin': (146, 282),
    'Turkish_Balikesir': (140, 222),
    'Turkish_Canakkale_Europe': (92, 184),
    'Turkish_Antalya': (208, 336),
    'Greek_Izmir': (210, 228),
    'Turkish_Konya': (350, 264),
    'Greek_Central_Anatolia': (404, 214),
    'Turkish_Nevsehir': (458, 244),
    'Turkish_Kayseri': (510, 206),
    'Turkish_Sivas': (564, 170),
    'Turkish_Erzurum': (670, 166),
    'Armenian_Erzurum': (712, 220),
    'Armenian_Gesaria': (590, 236),
    'Alevi_Dersim': (608, 286),
    'Armenian_Hemsheni': (768, 136),
    'Turkish_Trabzon': (744, 84),
    'Turkish_Giresun': (674, 92),
}

_WEST_EURASIA_LEVANT_DETAIL_REGION_LABELS: dict[str, tuple[str, ...]] = {
    'North Levant': ('Lebanese_Christian', 'Lebanese_Orthodox_Christian_Koura', 'Alawite', 'Syrian_Aleppo', 'Syrian_Hama', 'Syrian_Homs'),
    'South Levant': ('Palestinian', 'Palestinian_Beit_Sahour', 'Jordanian', 'Samaritan', 'Druze'),
    'Levantine mixed': ('Lebanese_Druze', 'Lebanese_Muslim', 'Lebanese_Sunni_Muslim_Beirut', 'Lebanese_Shia_Muslim_Beirut', 'Syrian', 'Syrian_Jew'),
}

_WEST_EURASIA_LEVANT_DETAIL_LAYOUT: dict[str, tuple[int, int]] = {
    'North Levant': (344, 144),
    'South Levant': (292, 312),
    'Levantine mixed': (526, 232),
}

_WEST_EURASIA_LEVANT_DETAIL_LABEL_OFFSETS: dict[str, tuple[int, int]] = {
    'North Levant': (-94, -32),
    'South Levant': (-94, 18),
    'Levantine mixed': (-116, 18),
}

_WEST_EURASIA_LEVANT_POPULATION_LABELS: tuple[str, ...] = (
    'Lebanese_Christian',
    'Lebanese_Orthodox_Christian_Koura',
    'Alawite',
    'Syrian_Aleppo',
    'Syrian_Hama',
    'Syrian_Homs',
    'Palestinian',
    'Palestinian_Beit_Sahour',
    'Jordanian',
    'Samaritan',
    'Druze',
    'Lebanese_Druze',
    'Lebanese_Muslim',
    'Lebanese_Sunni_Muslim_Beirut',
    'Lebanese_Shia_Muslim_Beirut',
    'Syrian',
    'Syrian_Jew',
)

_WEST_EURASIA_LEVANT_POPULATION_LAYOUT: dict[str, tuple[int, int]] = {
    'Lebanese_Christian': (286, 126),
    'Lebanese_Orthodox_Christian_Koura': (242, 170),
    'Alawite': (392, 92),
    'Syrian_Aleppo': (458, 126),
    'Syrian_Hama': (436, 182),
    'Syrian_Homs': (392, 224),
    'Palestinian': (226, 326),
    'Palestinian_Beit_Sahour': (284, 352),
    'Jordanian': (360, 336),
    'Samaritan': (174, 276),
    'Druze': (348, 256),
    'Lebanese_Druze': (518, 192),
    'Lebanese_Muslim': (574, 228),
    'Lebanese_Sunni_Muslim_Beirut': (522, 278),
    'Lebanese_Shia_Muslim_Beirut': (606, 300),
    'Syrian': (646, 202),
    'Syrian_Jew': (716, 244),
}

# Mesopotamia / Iran is intentionally broad and modern-only, using stable
# present-day cores rather than ancient proxies.
_WEST_EURASIA_MESO_IRAN_DETAIL_REGION_LABELS: dict[str, tuple[str, ...]] = {
    'Mesopotamia': ('Iraqi_Arab_Central', 'Iraqi_Arab_West', 'Iraqi_Arab_South', 'Assyrian', 'Assyrian_Mardin'),
    'Iran plateau': ('Iranian_Central', 'Iranian_Persian_Fars', 'Iranian_Persian_Shiraz', 'Iranian_Persian_Yazd', 'Iranian_Mazandarani', 'Iranian_Lor_Bakhtiari'),
    'Iran-Mesopotamia mixed': ('Iranian_Arab_Khuzestan', 'Kurd_Sorani_Iran_Mukriyan', 'Talysh_Azerbaijan', 'Azerbaijani_Iran_Ardabil', 'Azerbaijani_Iran_EastAz', 'Azerbaijani_Iran_WestAz_Maku', 'Iraqi_Jew'),
}

_WEST_EURASIA_MESO_IRAN_DETAIL_LAYOUT: dict[str, tuple[int, int]] = {
    'Mesopotamia': (280, 250),
    'Iran plateau': (560, 184),
    'Iran-Mesopotamia mixed': (472, 322),
}

_WEST_EURASIA_MESO_IRAN_DETAIL_LABEL_OFFSETS: dict[str, tuple[int, int]] = {
    'Mesopotamia': (-78, 18),
    'Iran plateau': (-90, -32),
    'Iran-Mesopotamia mixed': (-150, 18),
}

_WEST_EURASIA_MESO_IRAN_POPULATION_LABELS: tuple[str, ...] = (
    'Iraqi_Arab_Central',
    'Iraqi_Arab_West',
    'Iraqi_Arab_South',
    'Assyrian',
    'Assyrian_Mardin',
    'Iranian_Central',
    'Iranian_Persian_Fars',
    'Iranian_Persian_Shiraz',
    'Iranian_Persian_Yazd',
    'Iranian_Mazandarani',
    'Iranian_Lor_Bakhtiari',
    'Iranian_Arab_Khuzestan',
    'Kurd_Sorani_Iran_Mukriyan',
    'Talysh_Azerbaijan',
    'Azerbaijani_Iran_Ardabil',
    'Azerbaijani_Iran_EastAz',
    'Azerbaijani_Iran_WestAz_Maku',
    'Iraqi_Jew',
)

_WEST_EURASIA_MESO_IRAN_POPULATION_LAYOUT: dict[str, tuple[int, int]] = {
    'Iraqi_Arab_Central': (198, 258),
    'Iraqi_Arab_West': (152, 218),
    'Iraqi_Arab_South': (248, 324),
    'Assyrian': (312, 208),
    'Assyrian_Mardin': (368, 166),
    'Iranian_Central': (540, 180),
    'Iranian_Persian_Fars': (558, 284),
    'Iranian_Persian_Shiraz': (612, 326),
    'Iranian_Persian_Yazd': (652, 216),
    'Iranian_Mazandarani': (636, 116),
    'Iranian_Lor_Bakhtiari': (484, 240),
    'Iranian_Arab_Khuzestan': (434, 330),
    'Kurd_Sorani_Iran_Mukriyan': (476, 120),
    'Talysh_Azerbaijan': (704, 148),
    'Azerbaijani_Iran_Ardabil': (738, 198),
    'Azerbaijani_Iran_EastAz': (796, 244),
    'Azerbaijani_Iran_WestAz_Maku': (778, 94),
    'Iraqi_Jew': (340, 308),
}

_WEST_EURASIA_STEPPE_DETAIL_REGION_LABELS: dict[str, tuple[str, ...]] = {
    'West Steppe': ('Ukrainian_Dnipro', 'Russian_Belgorod', 'Russian_Kursk', 'Russian_Orel', 'Cossack_Ukrainian'),
    'Pontic-Caspian': ('Russian_Voronez', 'Cossack_Kuban', 'Tatar_Crimean_steppe', 'Nogai', 'Nogai_Dobruja'),
    'East Steppe fringe': ('Tatar_Kazan', 'Tatar_Mishar', 'Bashkir', 'Chuvash', 'Kalmyk', 'Kazakh'),
}

_WEST_EURASIA_STEPPE_DETAIL_LAYOUT: dict[str, tuple[int, int]] = {
    'West Steppe': (230, 202),
    'Pontic-Caspian': (452, 164),
    'East Steppe fringe': (676, 144),
}

_WEST_EURASIA_STEPPE_DETAIL_LABEL_OFFSETS: dict[str, tuple[int, int]] = {
    'West Steppe': (-82, 18),
    'Pontic-Caspian': (-112, -32),
    'East Steppe fringe': (-124, -32),
}

_WEST_EURASIA_STEPPE_POPULATION_LABELS: tuple[str, ...] = (
    'Ukrainian_Dnipro',
    'Russian_Belgorod',
    'Russian_Kursk',
    'Russian_Orel',
    'Cossack_Ukrainian',
    'Russian_Voronez',
    'Cossack_Kuban',
    'Tatar_Crimean_steppe',
    'Nogai',
    'Nogai_Dobruja',
    'Tatar_Kazan',
    'Tatar_Mishar',
    'Bashkir',
    'Chuvash',
    'Kalmyk',
    'Kazakh',
)

_WEST_EURASIA_STEPPE_POPULATION_LAYOUT: dict[str, tuple[int, int]] = {
    'Ukrainian_Dnipro': (166, 230),
    'Russian_Belgorod': (228, 180),
    'Russian_Kursk': (286, 166),
    'Russian_Orel': (322, 210),
    'Cossack_Ukrainian': (248, 292),
    'Russian_Voronez': (398, 154),
    'Cossack_Kuban': (450, 262),
    'Tatar_Crimean_steppe': (388, 248),
    'Nogai': (542, 206),
    'Nogai_Dobruja': (598, 270),
    'Tatar_Kazan': (704, 156),
    'Tatar_Mishar': (662, 214),
    'Bashkir': (776, 130),
    'Chuvash': (610, 120),
    'Kalmyk': (744, 274),
    'Kazakh': (822, 214),
}

# South Asia detail intentionally uses modern-only regional panels rather than
# sharper ethnolinguistic labels, because that branch is more calibration-sensitive.
_NORTHWEST_SOUTH_ASIA_DETAIL_REGION_LABELS: dict[str, tuple[str, ...]] = {
    'Punjab / Pakistan': (
        'Arain',
        'Awan',
        'Punjabi_Hindu_India',
        'Punjabi_Lahore',
        'Punjabi_Christian_India',
        'Punjabi_Muslim_India',
        'Punjabi_Sikh_India',
        'Brahmin_Punjab',
        'Rajput_Punjab',
    ),
    'Afghan fringe': (
        'Pashtun_Afghanistan',
        'Pashtun_Afghanistan_North',
        'Pashtun_Afghanistan_Northeast',
        'Pashtun_Afghanistan_Paktia',
        'Pashtun_Northeast_Afghanistan',
        'Pashtun_Pakistan',
        'Pashtun_Pakistan_Bettani',
        'Pashtun_Pakistan_Khattak_Nowshera',
        'Pashtun_Tarkalani',
        'Pashtun_Uthmankhel',
        'Pashtun_Yusufzai',
        'Burusho',
        'Kalash',
        'Balti',
    ),
    'Northwest mixed': (
        'Balochi_Pakistan',
        'Balochi_Iran',
        'Sindhi',
        'Sindhi_o',
        'Balti_o',
    ),
}

_NORTHWEST_SOUTH_ASIA_DETAIL_LAYOUT: dict[str, tuple[int, int]] = {
    'Punjab / Pakistan': (208, 198),
    'Afghan fringe': (414, 124),
    'Northwest mixed': (318, 310),
}

_NORTHWEST_SOUTH_ASIA_DETAIL_LABEL_OFFSETS: dict[str, tuple[int, int]] = {
    'Punjab / Pakistan': (-100, 18),
    'Afghan fringe': (-88, -32),
    'Northwest mixed': (-92, 18),
}

_NORTHWEST_SOUTH_ASIA_POPULATION_LABELS: tuple[str, ...] = (
    'Arain',
    'Awan',
    'Punjabi_Hindu_India',
    'Punjabi_Lahore',
    'Punjabi_Christian_India',
    'Punjabi_Muslim_India',
    'Punjabi_Sikh_India',
    'Brahmin_Punjab',
    'Rajput_Punjab',
    'Pashtun_Afghanistan',
    'Pashtun_Afghanistan_North',
    'Pashtun_Afghanistan_Northeast',
    'Pashtun_Afghanistan_Paktia',
    'Pashtun_Northeast_Afghanistan',
    'Pashtun_Pakistan',
    'Pashtun_Pakistan_Bettani',
    'Pashtun_Pakistan_Khattak_Nowshera',
    'Pashtun_Tarkalani',
    'Pashtun_Uthmankhel',
    'Pashtun_Yusufzai',
    'Burusho',
    'Kalash',
    'Balti',
    'Balochi_Pakistan',
    'Balochi_Iran',
    'Sindhi',
    'Sindhi_o',
    'Balti_o',
)

_NORTHWEST_SOUTH_ASIA_POPULATION_LAYOUT: dict[str, tuple[int, int]] = {
    'Arain': (190, 180),
    'Awan': (236, 214),
    'Punjabi_Hindu_India': (278, 184),
    'Punjabi_Lahore': (214, 150),
    'Punjabi_Christian_India': (302, 222),
    'Punjabi_Muslim_India': (262, 264),
    'Punjabi_Sikh_India': (336, 188),
    'Brahmin_Punjab': (346, 132),
    'Rajput_Punjab': (386, 170),
    'Pashtun_Afghanistan': (418, 108),
    'Pashtun_Afghanistan_North': (362, 70),
    'Pashtun_Afghanistan_Northeast': (472, 78),
    'Pashtun_Afghanistan_Paktia': (438, 152),
    'Pashtun_Northeast_Afghanistan': (524, 104),
    'Pashtun_Pakistan': (474, 196),
    'Pashtun_Pakistan_Bettani': (414, 220),
    'Pashtun_Pakistan_Khattak_Nowshera': (360, 234),
    'Pashtun_Tarkalani': (546, 162),
    'Pashtun_Uthmankhel': (518, 226),
    'Pashtun_Yusufzai': (584, 196),
    'Burusho': (628, 124),
    'Kalash': (608, 84),
    'Balti': (694, 136),
    'Balochi_Pakistan': (244, 330),
    'Balochi_Iran': (188, 366),
    'Sindhi': (334, 338),
    'Sindhi_o': (402, 356),
    'Balti_o': (758, 166),
}

# North India is kept regionally broad and modern-only to avoid overly narrow labels.
_GANGETIC_NORTH_INDIA_DETAIL_REGION_LABELS: dict[str, tuple[str, ...]] = {
    'Gangetic core': (
        'Brahmin_Uttar_Pradesh_Awadh',
        'Brahmin_Uttar_Pradesh_Braj',
        'Brahmin_Uttar_Pradesh_East',
    ),
    'Upper North India': (
        'Nepali_Indo-Aryan_A',
        'Nepali_Indo-Aryan_B',
        'Nepali_Indo-Aryan_C',
        'Nepali_Indo-Aryan_D',
    ),
    'North-central mixed': (
        'Kshatriya_Uttar_Pradesh_East',
        'Brahmin_Rajasthan',
        'Pathan_Bhopal',
        'Nepali_Indo-Aryan_o1',
        'Nepali_Indo-Aryan_o2',
    ),
}

_GANGETIC_NORTH_INDIA_DETAIL_LAYOUT: dict[str, tuple[int, int]] = {
    'Gangetic core': (270, 206),
    'Upper North India': (456, 118),
    'North-central mixed': (510, 278),
}

_GANGETIC_NORTH_INDIA_DETAIL_LABEL_OFFSETS: dict[str, tuple[int, int]] = {
    'Gangetic core': (-82, 18),
    'Upper North India': (-92, -32),
    'North-central mixed': (-120, 18),
}

_GANGETIC_NORTH_INDIA_POPULATION_LABELS: tuple[str, ...] = (
    'Brahmin_Uttar_Pradesh_Awadh',
    'Brahmin_Uttar_Pradesh_Braj',
    'Brahmin_Uttar_Pradesh_East',
    'Kshatriya_Uttar_Pradesh_East',
    'Brahmin_Rajasthan',
    'Pathan_Bhopal',
    'Nepali_Indo-Aryan_A',
    'Nepali_Indo-Aryan_B',
    'Nepali_Indo-Aryan_C',
    'Nepali_Indo-Aryan_D',
    'Nepali_Indo-Aryan_o1',
    'Nepali_Indo-Aryan_o2',
)

_GANGETIC_NORTH_INDIA_POPULATION_LAYOUT: dict[str, tuple[int, int]] = {
    'Brahmin_Uttar_Pradesh_Awadh': (200, 238),
    'Brahmin_Uttar_Pradesh_Braj': (252, 190),
    'Brahmin_Uttar_Pradesh_East': (308, 248),
    'Kshatriya_Uttar_Pradesh_East': (374, 288),
    'Brahmin_Rajasthan': (410, 226),
    'Pathan_Bhopal': (470, 330),
    'Nepali_Indo-Aryan_A': (416, 102),
    'Nepali_Indo-Aryan_B': (468, 138),
    'Nepali_Indo-Aryan_C': (530, 108),
    'Nepali_Indo-Aryan_D': (578, 146),
    'Nepali_Indo-Aryan_o1': (612, 190),
    'Nepali_Indo-Aryan_o2': (658, 236),
}

_WEST_INDIA_DETAIL_REGION_LABELS: dict[str, tuple[str, ...]] = {
    'Gujarati / West coastal': (
        'Gujarati',
        'Gujarati_Bharuch_Muslim',
        'Brahmin_Gujarat',
        'Brahmin_Gujarat_Nagar',
        'Brahmin_Gujarat_Audichya',
        'Brahmin_Gujarat_Bardai',
    ),
    'Rajasthan / West inland': (
        'Rajput_Rajasthan',
        'Brahmin_Rajasthan',
    ),
    'West mixed': (
        'Brahmin_Gujarat_o',
        'Brahmin_Chitpavan',
        'Sonar_Marathi',
        'Maratha',
    ),
}

_WEST_INDIA_DETAIL_LAYOUT: dict[str, tuple[int, int]] = {
    'Gujarati / West coastal': (210, 186),
    'Rajasthan / West inland': (420, 146),
    'West mixed': (462, 302),
}

_WEST_INDIA_DETAIL_LABEL_OFFSETS: dict[str, tuple[int, int]] = {
    'Gujarati / West coastal': (-126, 18),
    'Rajasthan / West inland': (-124, -32),
    'West mixed': (-70, 18),
}

_WEST_INDIA_POPULATION_LABELS: tuple[str, ...] = (
    'Gujarati',
    'Gujarati_Bharuch_Muslim',
    'Brahmin_Gujarat',
    'Brahmin_Gujarat_Nagar',
    'Brahmin_Gujarat_Audichya',
    'Brahmin_Gujarat_Bardai',
    'Brahmin_Gujarat_o',
    'Rajput_Rajasthan',
    'Brahmin_Rajasthan',
    'Brahmin_Chitpavan',
    'Sonar_Marathi',
    'Maratha',
)

_WEST_INDIA_POPULATION_LAYOUT: dict[str, tuple[int, int]] = {
    'Gujarati': (156, 208),
    'Gujarati_Bharuch_Muslim': (204, 262),
    'Brahmin_Gujarat': (224, 166),
    'Brahmin_Gujarat_Nagar': (284, 190),
    'Brahmin_Gujarat_Audichya': (252, 132),
    'Brahmin_Gujarat_Bardai': (316, 228),
    'Brahmin_Gujarat_o': (332, 278),
    'Rajput_Rajasthan': (430, 150),
    'Brahmin_Rajasthan': (486, 120),
    'Brahmin_Chitpavan': (430, 316),
    'Sonar_Marathi': (500, 356),
    'Maratha': (566, 316),
}

_SOUTH_INDIA_DETAIL_REGION_LABELS: dict[str, tuple[str, ...]] = {
    'South Dravidian': (
        'Pillai_Tamil',
        'Tamil_Sri_Lanka',
        'Vellalar',
    ),
    'Deccan / South-central': (
        'Telugu',
        'Yadav_Telugu',
        'Reddy',
    ),
    'Southern mixed': (
        'Nair',
        'Poduval_Kerala_North',
        'Vishwakarma_Kerala',
        'Brahmin_Tamil_Nadu',
        'Brahmin_Tamil_Nadu_Iyer',
        'Brahmin_Tamil_Nadu_Iyengar',
        'Sinhala',
    ),
}

_SOUTH_INDIA_DETAIL_LAYOUT: dict[str, tuple[int, int]] = {
    'South Dravidian': (470, 306),
    'Deccan / South-central': (316, 198),
    'Southern mixed': (238, 326),
}

_SOUTH_INDIA_DETAIL_LABEL_OFFSETS: dict[str, tuple[int, int]] = {
    'South Dravidian': (-96, 18),
    'Deccan / South-central': (-126, -32),
    'Southern mixed': (-100, 18),
}

_SOUTH_INDIA_POPULATION_LABELS: tuple[str, ...] = (
    'Telugu',
    'Yadav_Telugu',
    'Reddy',
    'Pillai_Tamil',
    'Tamil_Sri_Lanka',
    'Vellalar',
    'Nair',
    'Poduval_Kerala_North',
    'Vishwakarma_Kerala',
    'Brahmin_Tamil_Nadu',
    'Brahmin_Tamil_Nadu_Iyer',
    'Brahmin_Tamil_Nadu_Iyengar',
    'Sinhala',
)

_SOUTH_INDIA_POPULATION_LAYOUT: dict[str, tuple[int, int]] = {
    'Telugu': (262, 164),
    'Yadav_Telugu': (338, 206),
    'Reddy': (386, 156),
    'Pillai_Tamil': (468, 292),
    'Tamil_Sri_Lanka': (560, 350),
    'Vellalar': (414, 348),
    'Nair': (170, 322),
    'Poduval_Kerala_North': (124, 276),
    'Vishwakarma_Kerala': (210, 372),
    'Brahmin_Tamil_Nadu': (280, 286),
    'Brahmin_Tamil_Nadu_Iyer': (324, 336),
    'Brahmin_Tamil_Nadu_Iyengar': (352, 270),
    'Sinhala': (634, 320),
}

# East India / Bengal absorbs the eastern Indo-Aryan and tribal-fringe modern
# labels that are available in the dataset; this avoids forcing a synthetic 2D fix.
_EAST_INDIA_BENGAL_DETAIL_REGION_LABELS: dict[str, tuple[str, ...]] = {
    'Bengal': (
        'Bengali_Bangladesh',
        'Bengali_Bangladesh_Sylhet',
        'Bengali_Bangladesh_SouthEast',
        'Bengali_India',
    ),
    'East Indo-Gangetic': (
        'Brahmin_West_Bengal',
        'Nepali_Indo-Aryan_A',
        'Nepali_Indo-Aryan_B',
        'Nepali_Indo-Aryan_C',
        'Nepali_Indo-Aryan_D',
    ),
    'East mixed / tribal fringe': (
        'Santhal',
        'Ho',
        'Tripuri',
        'Nepali_Indo-Aryan_o1',
        'Nepali_Indo-Aryan_o2',
    ),
}

_EAST_INDIA_BENGAL_DETAIL_LAYOUT: dict[str, tuple[int, int]] = {
    'Bengal': (542, 202),
    'East Indo-Gangetic': (360, 138),
    'East mixed / tribal fringe': (316, 312),
}

_EAST_INDIA_BENGAL_DETAIL_LABEL_OFFSETS: dict[str, tuple[int, int]] = {
    'Bengal': (-44, 18),
    'East Indo-Gangetic': (-132, -32),
    'East mixed / tribal fringe': (-160, 18),
}

_EAST_INDIA_BENGAL_POPULATION_LABELS: tuple[str, ...] = (
    'Bengali_Bangladesh',
    'Bengali_Bangladesh_Sylhet',
    'Bengali_Bangladesh_SouthEast',
    'Bengali_India',
    'Brahmin_West_Bengal',
    'Nepali_Indo-Aryan_A',
    'Nepali_Indo-Aryan_B',
    'Nepali_Indo-Aryan_C',
    'Nepali_Indo-Aryan_D',
    'Nepali_Indo-Aryan_o1',
    'Nepali_Indo-Aryan_o2',
    'Santhal',
    'Ho',
    'Tripuri',
)

_EAST_INDIA_BENGAL_POPULATION_LAYOUT: dict[str, tuple[int, int]] = {
    'Bengali_Bangladesh': (548, 236),
    'Bengali_Bangladesh_Sylhet': (616, 168),
    'Bengali_Bangladesh_SouthEast': (634, 274),
    'Bengali_India': (466, 220),
    'Brahmin_West_Bengal': (416, 168),
    'Nepali_Indo-Aryan_A': (282, 118),
    'Nepali_Indo-Aryan_B': (334, 86),
    'Nepali_Indo-Aryan_C': (384, 108),
    'Nepali_Indo-Aryan_D': (436, 134),
    'Nepali_Indo-Aryan_o1': (360, 204),
    'Nepali_Indo-Aryan_o2': (306, 246),
    'Santhal': (226, 334),
    'Ho': (292, 374),
    'Tripuri': (714, 200),
}

_EAST_EURASIA_REGION_LABELS: dict[str, tuple[str, ...]] = {
    'Siberia': ('Yakut_Sakha', 'Evenk', 'Evenk_o'),
    'Mongolia': ('Mongol', 'Mongolian', 'Mongol_Inner_Mongolia', 'Daur'),
    'North China': ('Han_Henan', 'Han_Shandong', 'Han_Shanxi', 'Han_Jiangsu', 'Han_Hubei'),
    'South China': ('Han_Fujian', 'Han_Guangdong', 'Han_Guizhou', 'Han_Zhejiang', 'Naxi', 'Yi', 'Bai'),
    'Korea-Japan': ('Korean', 'Korean_Antu', 'Japanese'),
    'Tibetan Plateau': ('Tibetan_Lhasa', 'Tibetan_Shigatse', 'Tibetan_Gannan', 'Tibetan_Chamdo', 'Tibetan_Yunnan'),
    'SE Asia': ('Thai', 'Cambodian', 'Malay', 'Indonesian_Java', 'Indonesian_Bali', 'Atayal', 'Ami'),
}

_EAST_EURASIA_REGION_LAYOUT: dict[str, tuple[int, int]] = {
    'Siberia': (218, 88),
    'Mongolia': (352, 150),
    'North China': (522, 182),
    'South China': (558, 286),
    'Korea-Japan': (712, 176),
    'Tibetan Plateau': (356, 286),
    'SE Asia': (666, 360),
}

_EAST_EURASIA_LABEL_OFFSETS: dict[str, tuple[int, int]] = {
    'Siberia': (-28, -32),
    'Mongolia': (-34, -32),
    'North China': (-54, -32),
    'South China': (-54, 18),
    'Korea-Japan': (-58, 18),
    'Tibetan Plateau': (-74, 18),
    'SE Asia': (-38, 18),
}

# East Eurasia detail uses modern-only labels from the Global25 modern averages file.
_NORTHEAST_ASIA_DETAIL_REGION_LABELS: dict[str, tuple[str, ...]] = {
    'Japanese / Korean': ('Japanese', 'Korean', 'Korean_Antu'),
    # No exact "Amur / Tungusic" cluster exists in the source file, so this
    # centroid uses present-day Amur and Tungusic-adjacent labels available there.
    'Amur / Tungusic': ('Hezhen', 'Oroqen', 'Ulchi', 'Nanai', 'Evenk', 'Manchu_Liaoning'),
    # No exact "Far Northeast / Arctic edge" label exists, so this centroid
    # uses modern far northeast and Arctic-edge analogs from the dataset.
    'Far Northeast / Arctic edge': ('Nivkh', 'Yakut_Sakha', 'Dolgan', 'Chukchi', 'Koryak', 'Nganasan'),
}

_NORTHEAST_ASIA_DETAIL_LAYOUT: dict[str, tuple[int, int]] = {
    'Japanese / Korean': (214, 244),
    'Amur / Tungusic': (462, 176),
    'Far Northeast / Arctic edge': (664, 108),
}

_NORTHEAST_ASIA_DETAIL_LABEL_OFFSETS: dict[str, tuple[int, int]] = {
    'Japanese / Korean': (-106, 18),
    'Amur / Tungusic': (-92, -32),
    'Far Northeast / Arctic edge': (-180, -32),
}

_NORTHEAST_ASIA_POPULATION_LABELS: tuple[str, ...] = (
    'Japanese',
    'Korean',
    'Korean_Antu',
    'Hezhen',
    'Oroqen',
    'Ulchi',
    'Nanai',
    'Evenk',
    'Manchu_Liaoning',
    'Daur',
    'Nivkh',
    'Yakut_Sakha',
    'Dolgan',
    'Chukchi',
    'Koryak',
    'Nganasan',
)

_NORTHEAST_ASIA_POPULATION_LAYOUT: dict[str, tuple[int, int]] = {
    'Japanese': (178, 286),
    'Korean': (250, 236),
    'Korean_Antu': (292, 198),
    'Hezhen': (468, 182),
    'Oroqen': (508, 142),
    'Ulchi': (574, 174),
    'Nanai': (526, 220),
    'Evenk': (448, 114),
    'Manchu_Liaoning': (382, 226),
    'Daur': (386, 152),
    'Nivkh': (662, 174),
    'Yakut_Sakha': (602, 98),
    'Dolgan': (522, 72),
    'Chukchi': (742, 88),
    'Koryak': (778, 146),
    'Nganasan': (414, 72),
}

# No exact modern "Yellow River core / North China mixed / Northwest China edge"
# ontology exists in the file, so these centroids use the nearest present-day
# northern China and northwest-edge analogs explicitly available there.
_NORTH_CHINA_DETAIL_REGION_LABELS: dict[str, tuple[str, ...]] = {
    'Yellow River core': ('Han_Henan', 'Han_Shandong', 'Han_Shanxi'),
    'North China mixed': ('Han_Hubei', 'Han_Jiangsu', 'Han_Shanghai', 'Manchu_Liaoning', 'Manchu_Jinzhou', 'Xibo'),
    'Northwest China edge': ('Mongol_Inner_Mongolia', 'Mongol_IMAR', 'Tu', 'Tibetan_Gangcha', 'Tibetan_Xunhua', 'Uygur'),
}

_NORTH_CHINA_DETAIL_LAYOUT: dict[str, tuple[int, int]] = {
    'Yellow River core': (264, 214),
    'North China mixed': (468, 194),
    'Northwest China edge': (642, 138),
}

_NORTH_CHINA_DETAIL_LABEL_OFFSETS: dict[str, tuple[int, int]] = {
    'Yellow River core': (-102, 18),
    'North China mixed': (-100, -32),
    'Northwest China edge': (-126, -32),
}

_NORTH_CHINA_POPULATION_LABELS: tuple[str, ...] = (
    'Han_Henan',
    'Han_Shandong',
    'Han_Shanxi',
    'Han_Hubei',
    'Han_Jiangsu',
    'Han_Shanghai',
    'Manchu_Liaoning',
    'Manchu_Jinzhou',
    'Xibo',
    'Mongol_Inner_Mongolia',
    'Mongol_IMAR',
    'Tu',
    'Tibetan_Gangcha',
    'Tibetan_Xunhua',
    'Uygur',
)

_NORTH_CHINA_POPULATION_LAYOUT: dict[str, tuple[int, int]] = {
    'Han_Henan': (212, 234),
    'Han_Shandong': (292, 194),
    'Han_Shanxi': (186, 176),
    'Han_Hubei': (274, 284),
    'Han_Jiangsu': (368, 236),
    'Han_Shanghai': (424, 254),
    'Manchu_Liaoning': (452, 154),
    'Manchu_Jinzhou': (504, 182),
    'Xibo': (590, 186),
    'Mongol_Inner_Mongolia': (530, 108),
    'Mongol_IMAR': (610, 92),
    'Tu': (494, 276),
    'Tibetan_Gangcha': (420, 334),
    'Tibetan_Xunhua': (468, 306),
    'Uygur': (660, 238),
}

# "Southeast coastal" has no exact mainland-only label set in the file, so this
# centroid uses present-day southeast coastal and island-edge modern analogs.
_SOUTH_CHINA_DETAIL_REGION_LABELS: dict[str, tuple[str, ...]] = {
    'South China Han': ('Han_Fujian', 'Han_Guangdong', 'Han_Zhejiang'),
    'Southeast coastal': ('Atayal', 'Ami', 'Dai', 'Thai'),
    'Southwest / inland South China': ('Han_Guizhou', 'Han_Sichuan', 'Han_Chongqing', 'Naxi', 'Yi', 'Bai', 'Miao', 'Tujia'),
}

_SOUTH_CHINA_DETAIL_LAYOUT: dict[str, tuple[int, int]] = {
    'South China Han': (522, 176),
    'Southeast coastal': (666, 272),
    'Southwest / inland South China': (312, 298),
}

_SOUTH_CHINA_DETAIL_LABEL_OFFSETS: dict[str, tuple[int, int]] = {
    'South China Han': (-84, -32),
    'Southeast coastal': (-96, 18),
    'Southwest / inland South China': (-200, 18),
}

_SOUTH_CHINA_POPULATION_LABELS: tuple[str, ...] = (
    'Han_Fujian',
    'Han_Guangdong',
    'Han_Zhejiang',
    'Atayal',
    'Ami',
    'Dai',
    'Thai',
    'Han_Guizhou',
    'Han_Sichuan',
    'Han_Chongqing',
    'Naxi',
    'Yi',
    'Bai',
    'Miao',
    'Tujia',
    'Miao_Leishan',
    'Miao_Songtao',
)

_SOUTH_CHINA_POPULATION_LAYOUT: dict[str, tuple[int, int]] = {
    'Han_Fujian': (540, 178),
    'Han_Guangdong': (506, 234),
    'Han_Zhejiang': (582, 136),
    'Atayal': (746, 242),
    'Ami': (776, 292),
    'Dai': (604, 320),
    'Thai': (676, 352),
    'Han_Guizhou': (346, 270),
    'Han_Sichuan': (248, 236),
    'Han_Chongqing': (280, 196),
    'Naxi': (186, 304),
    'Yi': (238, 334),
    'Bai': (148, 272),
    'Miao': (416, 320),
    'Tujia': (362, 214),
    'Miao_Leishan': (456, 360),
    'Miao_Songtao': (400, 258),
}

# No exact modern "South Siberia / Central Inner Asia / Northeast Siberia"
# cluster labels exist in the file, so these centroids use the nearest
# present-day Siberian and Inner Asian analogs explicitly present there.
_SIBERIA_INNER_ASIA_DETAIL_REGION_LABELS: dict[str, tuple[str, ...]] = {
    'South Siberia': ('Altaian', 'Altaian_Kizhi', 'Khakass', 'Khakass_Kachins', 'Buryat', 'Tuvinian'),
    'Central Inner Asia': ('Mongolian', 'Mongol_Xinjiang', 'Kazakh', 'Kazakh_China', 'Kazakh_Xinjiang', 'Kirghiz', 'Kirghiz_China', 'Uygur'),
    'Northeast Siberia': ('Yakut_Sakha', 'Even', 'Evenk', 'Dolgan', 'Nganasan', 'Chukchi', 'Koryak'),
}

_SIBERIA_INNER_ASIA_DETAIL_LAYOUT: dict[str, tuple[int, int]] = {
    'South Siberia': (252, 168),
    'Central Inner Asia': (470, 242),
    'Northeast Siberia': (662, 118),
}

_SIBERIA_INNER_ASIA_DETAIL_LABEL_OFFSETS: dict[str, tuple[int, int]] = {
    'South Siberia': (-78, -32),
    'Central Inner Asia': (-112, 18),
    'Northeast Siberia': (-130, -32),
}

_SIBERIA_INNER_ASIA_POPULATION_LABELS: tuple[str, ...] = (
    'Altaian',
    'Altaian_Kizhi',
    'Khakass',
    'Khakass_Kachins',
    'Buryat',
    'Mongolian',
    'Tuvinian',
    'Mongol_Xinjiang',
    'Kazakh',
    'Kazakh_China',
    'Kazakh_Xinjiang',
    'Kirghiz',
    'Kirghiz_China',
    'Uygur',
    'Yakut_Sakha',
    'Even',
    'Evenk',
    'Dolgan',
    'Nganasan',
    'Chukchi',
    'Koryak',
)

_SIBERIA_INNER_ASIA_POPULATION_LAYOUT: dict[str, tuple[int, int]] = {
    'Altaian': (154, 172),
    'Altaian_Kizhi': (208, 210),
    'Khakass': (250, 138),
    'Khakass_Kachins': (294, 178),
    'Buryat': (326, 104),
    'Mongolian': (426, 174),
    'Tuvinian': (350, 244),
    'Mongol_Xinjiang': (458, 288),
    'Kazakh': (510, 250),
    'Kazakh_China': (566, 286),
    'Kazakh_Xinjiang': (604, 244),
    'Kirghiz': (480, 328),
    'Kirghiz_China': (544, 352),
    'Uygur': (654, 328),
    'Yakut_Sakha': (614, 112),
    'Even': (692, 144),
    'Evenk': (524, 128),
    'Dolgan': (486, 72),
    'Nganasan': (406, 70),
    'Chukchi': (772, 94),
    'Koryak': (798, 164),
}

# No exact "Central North Caucasus" label exists in the file, so this centroid
# uses modern central North Caucasus populations explicitly present in the dataset.
_NORTH_CAUCASUS_DETAIL_REGION_LABELS: dict[str, tuple[str, ...]] = {
    'NW Caucasus': ('Abazin', 'Abkhasian', 'Adygei', 'Circassian', 'Cherkes'),
    'Central North Caucasus': ('Kabardin', 'Balkar', 'Karachay', 'North_Ossetian', 'Ossetian', 'Ingushian'),
    'NE Caucasus': ('Avar', 'Chechen', 'Lezgin'),
    # No exact "Steppe-adjacent North Caucasus" label exists in the file, so
    # this centroid uses modern steppe-facing North Caucasus analogs from the dataset.
    'Steppe-adjacent North Caucasus': ('Kumyk', 'Nogai', 'Nogai_Dobruja', 'Cossack_Kuban'),
}

_NORTH_CAUCASUS_DETAIL_LAYOUT: dict[str, tuple[int, int]] = {
    'NW Caucasus': (210, 166),
    'Central North Caucasus': (398, 176),
    'NE Caucasus': (596, 154),
    'Steppe-adjacent North Caucasus': (500, 286),
}

_NORTH_CAUCASUS_DETAIL_LABEL_OFFSETS: dict[str, tuple[int, int]] = {
    'NW Caucasus': (-56, -32),
    'Central North Caucasus': (-124, 18),
    'NE Caucasus': (-56, -32),
    'Steppe-adjacent North Caucasus': (-146, 18),
}

_NORTH_CAUCASUS_POPULATION_LABELS: tuple[str, ...] = (
    'Abazin',
    'Abkhasian',
    'Adygei',
    'Circassian',
    'Cherkes',
    'Kabardin',
    'Balkar',
    'Karachay',
    'North_Ossetian',
    'Ossetian',
    'Ingushian',
    'Avar',
    'Chechen',
    'Lezgin',
    'Kumyk',
    'Nogai',
    'Nogai_Dobruja',
    'Cossack_Kuban',
)

_NORTH_CAUCASUS_POPULATION_LAYOUT: dict[str, tuple[int, int]] = {
    'Abazin': (158, 132),
    'Abkhasian': (194, 172),
    'Adygei': (232, 138),
    'Circassian': (266, 180),
    'Cherkes': (304, 148),
    'Kabardin': (356, 166),
    'Balkar': (396, 204),
    'Karachay': (342, 244),
    'North_Ossetian': (450, 180),
    'Ossetian': (488, 220),
    'Ingushian': (522, 160),
    'Avar': (600, 132),
    'Chechen': (652, 170),
    'Lezgin': (704, 212),
    'Kumyk': (562, 282),
    'Nogai': (626, 306),
    'Nogai_Dobruja': (692, 330),
    'Cossack_Kuban': (500, 318),
}

# No exact "West/Central/East South Caucasus" labels exist in the file, so these
# centroids use modern Georgia/Armenia/Azerbaijan labels explicitly present in the dataset.
_SOUTH_CAUCASUS_DETAIL_REGION_LABELS: dict[str, tuple[str, ...]] = {
    'West South Caucasus': (
        'Georgian_Ajar',
        'Georgian_Guria',
        'Georgian_Imer',
        'Georgian_Lechkhumi',
        'Georgian_Megr',
        'Georgian_Ratcha',
        'Georgian_Svaneti',
        'Georgian_West',
    ),
    'Central South Caucasus': (
        'Armenian_Ararat',
        'Armenian_Artsakh',
        'Armenian_Parspatunik',
        'Georgian_Javakheti',
        'Georgian_Kart',
        'Georgian_Meskheti',
        'Georgian_Samtckhe',
    ),
    # No exact "East South Caucasus" centroid exists in the source file, so this
    # branch uses modern east Georgian, Azerbaijani, and Syunik-facing analogs.
    'East South Caucasus': (
        'Armenian_Syunik',
        'Azerbaijani_Dagestan',
        'Azerbaijani_Republic_Agjabedi',
        'Azerbaijani_Republic_Gabala',
        'Azerbaijani_Republic_Shaki',
        'Georgian_Kakh',
        'Georgian_Khevs',
        'Georgian_NorthEast',
        'Georgian_Tush',
    ),
}

_SOUTH_CAUCASUS_DETAIL_LAYOUT: dict[str, tuple[int, int]] = {
    'West South Caucasus': (222, 192),
    'Central South Caucasus': (420, 244),
    'East South Caucasus': (616, 186),
}

_SOUTH_CAUCASUS_DETAIL_LABEL_OFFSETS: dict[str, tuple[int, int]] = {
    'West South Caucasus': (-120, -32),
    'Central South Caucasus': (-142, 18),
    'East South Caucasus': (-122, -32),
}

_SOUTH_CAUCASUS_POPULATION_LABELS: tuple[str, ...] = _ordered_unique_labels(*_SOUTH_CAUCASUS_DETAIL_REGION_LABELS.values())

_SOUTH_CAUCASUS_POPULATION_LAYOUT: dict[str, tuple[int, int]] = {
    'Georgian_Ajar': (142, 192),
    'Georgian_Guria': (170, 150),
    'Georgian_Imer': (222, 178),
    'Georgian_Lechkhumi': (242, 126),
    'Georgian_Megr': (112, 142),
    'Georgian_Ratcha': (286, 148),
    'Georgian_Svaneti': (210, 96),
    'Georgian_West': (164, 232),
    'Armenian_Ararat': (384, 254),
    'Armenian_Artsakh': (454, 196),
    'Armenian_Parspatunik': (418, 318),
    'Georgian_Javakheti': (294, 254),
    'Georgian_Kart': (344, 194),
    'Georgian_Meskheti': (284, 304),
    'Georgian_Samtckhe': (324, 346),
    'Armenian_Syunik': (548, 312),
    'Azerbaijani_Dagestan': (694, 132),
    'Azerbaijani_Republic_Agjabedi': (666, 276),
    'Azerbaijani_Republic_Gabala': (620, 208),
    'Azerbaijani_Republic_Shaki': (606, 170),
    'Georgian_Kakh': (520, 140),
    'Georgian_Khevs': (452, 112),
    'Georgian_NorthEast': (562, 104),
    'Georgian_Tush': (528, 84),
}

# No exact modern "North/Central/South Steppe fringe" ontology exists in the
# file, so these centroids use present-day steppe-facing Volga-Ural, Pontic,
# and south fringe analogs explicitly available in the dataset.
_STEPPE_FRINGE_DETAIL_REGION_LABELS: dict[str, tuple[str, ...]] = {
    'North Steppe fringe': (
        'Bashkir',
        'Chuvash',
        'Tatar_Kazan',
        'Tatar_Mishar',
    ),
    'Central Steppe fringe': (
        'Nogai',
        'Nogai_Dobruja',
        'Tatar_Crimean_steppe',
        'Cossack_Kuban',
        'Cossack_Ukrainian',
        'Russian_Voronez',
    ),
    'South Steppe fringe': (
        'Kumyk',
        'Kalmyk',
        'Karachay',
        'Balkar',
    ),
}

_STEPPE_FRINGE_DETAIL_LAYOUT: dict[str, tuple[int, int]] = {
    'North Steppe fringe': (260, 124),
    'Central Steppe fringe': (462, 220),
    'South Steppe fringe': (632, 292),
}

_STEPPE_FRINGE_DETAIL_LABEL_OFFSETS: dict[str, tuple[int, int]] = {
    'North Steppe fringe': (-104, -32),
    'Central Steppe fringe': (-112, 18),
    'South Steppe fringe': (-104, 18),
}

_STEPPE_FRINGE_POPULATION_LABELS: tuple[str, ...] = _ordered_unique_labels(*_STEPPE_FRINGE_DETAIL_REGION_LABELS.values())

_STEPPE_FRINGE_POPULATION_LAYOUT: dict[str, tuple[int, int]] = {
    'Bashkir': (192, 106),
    'Chuvash': (236, 156),
    'Tatar_Kazan': (304, 114),
    'Tatar_Mishar': (332, 174),
    'Nogai': (448, 206),
    'Nogai_Dobruja': (542, 262),
    'Tatar_Crimean_steppe': (412, 286),
    'Cossack_Kuban': (494, 318),
    'Cossack_Ukrainian': (360, 216),
    'Russian_Voronez': (378, 146),
    'Kumyk': (642, 224),
    'Kalmyk': (714, 182),
    'Karachay': (560, 312),
    'Balkar': (598, 346),
}

_CAUCASUS_STEPPE_ALL_POPULATION_LABELS: tuple[str, ...] = _ordered_unique_labels(*_CAUCASUS_STEPPE_REGION_LABELS.values())

_CAUCASUS_STEPPE_ALL_POPULATION_LAYOUT: dict[str, tuple[int, int]] = {
    'Abazin': (142, 126),
    'Abkhasian': (114, 188),
    'Adygei': (188, 132),
    'Circassian': (232, 182),
    'Cherkes': (274, 148),
    'Kabardin': (316, 182),
    'Karachay': (282, 236),
    'Balkar': (340, 226),
    'Avar': (432, 120),
    'Chechen': (476, 164),
    'Ingushian': (432, 200),
    'Kumyk': (490, 248),
    'Lezgin': (548, 208),
    'Armenian_Ararat': (318, 276),
    'Armenian_Artsakh': (386, 238),
    'Armenian_Syunik': (444, 314),
    'Georgian_Kart': (262, 222),
    'Georgian_Kakh': (498, 178),
    'Georgian_Svaneti': (194, 236),
    'Turkish_Antalya': (162, 362),
    'Turkish_Aydin': (118, 328),
    'Turkish_Balikesir': (102, 286),
    'Turkish_Denizli': (148, 304),
    'Turkish_Konya': (218, 326),
    'Greek_Central_Anatolia': (254, 368),
    'Alevi_Dersim': (308, 330),
    'Nogai': (630, 204),
    'Cossack_Kuban': (574, 258),
    'Russian_Voronez': (590, 126),
    'Tatar_Crimean_steppe': (526, 182),
    'Tatar_Kazan': (700, 106),
    'Tatar_Mishar': (756, 138),
    'Bashkir': (752, 84),
    'Chuvash': (654, 82),
}

_NORTH_EUROPE_DETAIL_REGION_LABELS: dict[str, tuple[str, ...]] = {
    'Scandinavia': (
        'Danish',
        'Norwegian',
        'Swedish',
    ),
    'Finland': (
        'Finnish_Southwest',
        'Finnish_Central',
        'Finnish_East',
        'Finnish_Southeast',
    ),
    'North Sea fringe': (
        'English',
        'Scottish',
        'Irish',
        'Dutch',
        'BelgianA',
        'German',
        'French_Nord',
    ),
}

_NORTH_EUROPE_DETAIL_LAYOUT: dict[str, tuple[int, int]] = {
    'Scandinavia': (238, 116),
    'Finland': (454, 118),
    'North Sea fringe': (248, 270),
}

_NORTH_EUROPE_DETAIL_LABEL_OFFSETS: dict[str, tuple[int, int]] = {
    'Scandinavia': (-74, -32),
    'Finland': (-38, -32),
    'North Sea fringe': (-100, 18),
}

_NORTH_EUROPE_POPULATION_LABELS: tuple[str, ...] = _ordered_unique_labels(*_NORTH_EUROPE_DETAIL_REGION_LABELS.values())

_NORTH_EUROPE_POPULATION_LAYOUT: dict[str, tuple[int, int]] = {
    'Danish': (212, 128),
    'Norwegian': (170, 98),
    'Swedish': (264, 102),
    'Finnish_Southwest': (406, 94),
    'Finnish_Central': (454, 130),
    'Finnish_East': (506, 102),
    'Finnish_Southeast': (458, 176),
    'English': (224, 262),
    'Scottish': (160, 220),
    'Irish': (116, 252),
    'Dutch': (306, 246),
    'BelgianA': (300, 294),
    'German': (390, 250),
    'French_Nord': (242, 338),
}

_SOUTH_EUROPE_DETAIL_REGION_LABELS: dict[str, tuple[str, ...]] = {
    'Italy': (
        'Italian_Northeast',
        'Italian_Tuscany',
        'Italian_Lazio',
        'Italian_Calabria',
    ),
    'Aegean': (
        'Greek_Macedonia',
        'Greek_Thessaly',
        'Greek_Peloponnese',
        'Greek_Crete',
    ),
    'Western Mediterranean': (
        'Sardinian',
        'Spanish_Castilla_Y_Leon',
        'Portuguese',
        'French_Provence',
        'French_Corsica',
    ),
}

_SOUTH_EUROPE_DETAIL_LAYOUT: dict[str, tuple[int, int]] = {
    'Italy': (262, 244),
    'Aegean': (554, 244),
    'Western Mediterranean': (134, 252),
}

_SOUTH_EUROPE_DETAIL_LABEL_OFFSETS: dict[str, tuple[int, int]] = {
    'Italy': (-22, -32),
    'Aegean': (-28, -32),
    'Western Mediterranean': (-174, 18),
}

_SOUTH_EUROPE_POPULATION_LABELS: tuple[str, ...] = _ordered_unique_labels(*_SOUTH_EUROPE_DETAIL_REGION_LABELS.values())

_SOUTH_EUROPE_POPULATION_LAYOUT: dict[str, tuple[int, int]] = {
    'Italian_Northeast': (274, 176),
    'Italian_Tuscany': (212, 236),
    'Italian_Lazio': (246, 284),
    'Italian_Calabria': (338, 356),
    'Greek_Macedonia': (486, 186),
    'Greek_Thessaly': (550, 228),
    'Greek_Peloponnese': (592, 300),
    'Greek_Crete': (630, 388),
    'Sardinian': (136, 348),
    'Spanish_Castilla_Y_Leon': (92, 214),
    'Portuguese': (54, 248),
    'French_Provence': (148, 176),
    'French_Corsica': (188, 314),
}

_BALKANS_DETAIL_REGION_LABELS: dict[str, tuple[str, ...]] = {
    'West Balkans': (
        'Croatian',
        'Bosnian',
        'Montenegrin',
        'Slovenian',
    ),
    'Central Balkans': (
        'Serbian',
        'Romanian',
        'Macedonian',
    ),
    'Southeast Balkans': (
        'Albanian',
        'Bulgarian',
        'Greek_Macedonia',
        'Greek_Thessaly',
    ),
}

_BALKANS_DETAIL_LAYOUT: dict[str, tuple[int, int]] = {
    'West Balkans': (228, 206),
    'Central Balkans': (392, 220),
    'Southeast Balkans': (456, 326),
}

_BALKANS_DETAIL_LABEL_OFFSETS: dict[str, tuple[int, int]] = {
    'West Balkans': (-84, -32),
    'Central Balkans': (-98, 18),
    'Southeast Balkans': (-126, 18),
}

_BALKANS_POPULATION_LABELS: tuple[str, ...] = _ordered_unique_labels(*_BALKANS_DETAIL_REGION_LABELS.values())

_BALKANS_POPULATION_LAYOUT: dict[str, tuple[int, int]] = {
    'Slovenian': (166, 122),
    'Croatian': (214, 176),
    'Bosnian': (246, 216),
    'Montenegrin': (254, 286),
    'Serbian': (344, 232),
    'Romanian': (460, 176),
    'Macedonian': (398, 312),
    'Albanian': (336, 356),
    'Bulgarian': (516, 278),
    'Greek_Macedonia': (456, 356),
    'Greek_Thessaly': (526, 356),
}

_BALTIC_DETAIL_REGION_LABELS: dict[str, tuple[str, ...]] = {
    'Estonia': (
        'Estonian',
    ),
    'Latvia': (
        'Latvian',
    ),
    'Lithuania': (
        'Lithuanian_PA',
        'Lithuanian_PZ',
        'Lithuanian_VA',
        'Lithuanian_SZ',
        'Lithuanian_VZ',
        'Lithuanian_RA',
    ),
}

_BALTIC_DETAIL_LAYOUT: dict[str, tuple[int, int]] = {
    'Estonia': (284, 108),
    'Latvia': (350, 170),
    'Lithuania': (454, 254),
}

_BALTIC_DETAIL_LABEL_OFFSETS: dict[str, tuple[int, int]] = {
    'Estonia': (-36, -32),
    'Latvia': (-28, 18),
    'Lithuania': (-54, 18),
}

_BALTIC_POPULATION_LABELS: tuple[str, ...] = _ordered_unique_labels(*_BALTIC_DETAIL_REGION_LABELS.values())

_BALTIC_POPULATION_LAYOUT: dict[str, tuple[int, int]] = {
    'Estonian': (282, 98),
    'Latvian': (338, 166),
    'Lithuanian_PA': (382, 210),
    'Lithuanian_PZ': (432, 204),
    'Lithuanian_VA': (470, 244),
    'Lithuanian_SZ': (410, 286),
    'Lithuanian_VZ': (470, 316),
    'Lithuanian_RA': (540, 272),
}

_EAST_EUROPE_DETAIL_REGION_LABELS: dict[str, tuple[str, ...]] = {
    # Northeast Europe uses modern Finnic/North Russian labels that are present in the dataset.
    'Northeast Europe': (
        'Estonian',
        'Finnish_Central',
        'Finnish_East',
        'Finnish_Southeast',
        'Russian_Krasnoborsky',
        'Russian_Leshukonsky',
        'Russian_Pinega',
        'Russian_Pinezhsky',
    ),
    'East Slavic': (
        'Belarusian',
        'Ukrainian_Chernihiv',
        'Ukrainian_Sumy',
        'Ukrainian_Zhytomyr',
        'Ukrainian_Rivne',
        'Russian_Smolensk',
        'Russian_Kaluga',
        'Russian_Tver',
        'Russian_Yaroslavl',
        'Russian_Ryazan',
    ),
    # Volga-Ural fringe uses modern Uralic/Turkic-adjacent labels available in the file.
    'Volga-Ural fringe': (
        'Mordovian',
        'Mari',
        'Udmurt',
        'Chuvash',
        'Tatar_Kazan',
        'Tatar_Mishar',
        'Bashkir',
    ),
    # Steppe-adjacent East Europe uses modern south/east Slavic and steppe-facing labels from the dataset.
    'Steppe-adjacent East Europe': (
        'Ukrainian_Dnipro',
        'Russian_Belgorod',
        'Russian_Kursk',
        'Russian_Orel',
        'Russian_Voronez',
        'Cossack_Ukrainian',
        'Cossack_Kuban',
        'Tatar_Crimean_steppe',
        'Nogai',
    ),
}

_EAST_EUROPE_DETAIL_LAYOUT: dict[str, tuple[int, int]] = {
    'Northeast Europe': (260, 132),
    'East Slavic': (386, 238),
    'Volga-Ural fringe': (620, 154),
    'Steppe-adjacent East Europe': (568, 316),
}

_EAST_EUROPE_DETAIL_LABEL_OFFSETS: dict[str, tuple[int, int]] = {
    'Northeast Europe': (-76, -32),
    'East Slavic': (-44, 18),
    'Volga-Ural fringe': (-78, -32),
    'Steppe-adjacent East Europe': (-142, 18),
}

_EAST_EUROPE_POPULATION_LABELS: tuple[str, ...] = _ordered_unique_labels(*_EAST_EUROPE_DETAIL_REGION_LABELS.values())

_EAST_EUROPE_POPULATION_LAYOUT: dict[str, tuple[int, int]] = {
    'Estonian': (180, 106),
    'Finnish_Central': (252, 88),
    'Finnish_East': (308, 104),
    'Finnish_Southeast': (276, 150),
    'Russian_Krasnoborsky': (396, 70),
    'Russian_Leshukonsky': (456, 78),
    'Russian_Pinega': (470, 120),
    'Russian_Pinezhsky': (524, 100),
    'Belarusian': (180, 204),
    'Ukrainian_Chernihiv': (218, 242),
    'Ukrainian_Sumy': (286, 246),
    'Ukrainian_Zhytomyr': (134, 258),
    'Ukrainian_Rivne': (102, 220),
    'Russian_Smolensk': (260, 186),
    'Russian_Kaluga': (328, 198),
    'Russian_Tver': (328, 152),
    'Russian_Yaroslavl': (414, 172),
    'Russian_Ryazan': (420, 222),
    'Mordovian': (512, 212),
    'Mari': (604, 164),
    'Udmurt': (688, 146),
    'Chuvash': (572, 228),
    'Tatar_Kazan': (648, 204),
    'Tatar_Mishar': (554, 170),
    'Bashkir': (748, 128),
    'Ukrainian_Dnipro': (250, 326),
    'Russian_Belgorod': (338, 290),
    'Russian_Kursk': (392, 260),
    'Russian_Orel': (366, 226),
    'Russian_Voronez': (454, 286),
    'Cossack_Ukrainian': (176, 314),
    'Cossack_Kuban': (426, 354),
    'Tatar_Crimean_steppe': (318, 374),
    'Nogai': (548, 372),
}

_EUROPE_ALL_POPULATION_GROUP_LABELS: dict[str, tuple[str, ...]] = {
    'East Europe': _EAST_EUROPE_POPULATION_LABELS,
    'North Europe': _NORTH_EUROPE_POPULATION_LABELS,
    'South Europe': _SOUTH_EUROPE_POPULATION_LABELS,
    'Balkans': _BALKANS_POPULATION_LABELS,
    'Baltic': _BALTIC_POPULATION_LABELS,
}

_EUROPE_ALL_POPULATION_LABELS: tuple[str, ...] = _ordered_unique_labels(*_EUROPE_ALL_POPULATION_GROUP_LABELS.values())

_EUROPE_ALL_POPULATION_LAYOUT: dict[str, tuple[int, int]] = _build_grouped_population_layout(
    (
        (_NORTH_EUROPE_POPULATION_LABELS, (250, 112), 4),
        (_EAST_EUROPE_POPULATION_LABELS, (612, 206), 6),
        (_SOUTH_EUROPE_POPULATION_LABELS, (212, 334), 4),
        (_BALKANS_POPULATION_LABELS, (504, 330), 4),
        (_BALTIC_POPULATION_LABELS, (520, 94), 3),
    )
)

_WEST_EURASIA_ALL_POPULATION_GROUP_LABELS: dict[str, tuple[str, ...]] = {
    'Europe': _WEST_EURASIA_EUROPE_POPULATION_LABELS,
    'Caucasus': _WEST_EURASIA_CAUCASUS_POPULATION_LABELS,
    'Anatolia': _WEST_EURASIA_ANATOLIA_POPULATION_LABELS,
    'Levant': _WEST_EURASIA_LEVANT_POPULATION_LABELS,
    'Mesopotamia / Iran': _WEST_EURASIA_MESO_IRAN_POPULATION_LABELS,
    'Steppe': _WEST_EURASIA_STEPPE_POPULATION_LABELS,
}

_WEST_EURASIA_ALL_POPULATION_LABELS: tuple[str, ...] = _ordered_unique_labels(*_WEST_EURASIA_ALL_POPULATION_GROUP_LABELS.values())

_WEST_EURASIA_ALL_POPULATION_LAYOUT: dict[str, tuple[int, int]] = _build_grouped_population_layout(
    (
        (_WEST_EURASIA_STEPPE_POPULATION_LABELS, (654, 96), 4),
        (_WEST_EURASIA_EUROPE_POPULATION_LABELS, (182, 130), 5),
        (_WEST_EURASIA_CAUCASUS_POPULATION_LABELS, (450, 138), 6),
        (_WEST_EURASIA_ANATOLIA_POPULATION_LABELS, (230, 304), 5),
        (_WEST_EURASIA_LEVANT_POPULATION_LABELS, (452, 334), 5),
        (_WEST_EURASIA_MESO_IRAN_POPULATION_LABELS, (678, 286), 5),
    )
)

_SOUTH_ASIA_ALL_POPULATION_GROUP_LABELS: dict[str, tuple[str, ...]] = {
    'Northwest South Asia': _NORTHWEST_SOUTH_ASIA_POPULATION_LABELS,
    'Gangetic / North India': _GANGETIC_NORTH_INDIA_POPULATION_LABELS,
    'West India': _WEST_INDIA_POPULATION_LABELS,
    'South India': _SOUTH_INDIA_POPULATION_LABELS,
    'East India / Bengal': _EAST_INDIA_BENGAL_POPULATION_LABELS,
}

_SOUTH_ASIA_ALL_POPULATION_LABELS: tuple[str, ...] = _ordered_unique_labels(*_SOUTH_ASIA_ALL_POPULATION_GROUP_LABELS.values())

_SOUTH_ASIA_ALL_POPULATION_LAYOUT: dict[str, tuple[int, int]] = _build_grouped_population_layout(
    (
        (_NORTHWEST_SOUTH_ASIA_POPULATION_LABELS, (186, 160), 5),
        (_GANGETIC_NORTH_INDIA_POPULATION_LABELS, (404, 170), 4),
        (_WEST_INDIA_POPULATION_LABELS, (180, 310), 4),
        (_SOUTH_INDIA_POPULATION_LABELS, (398, 338), 4),
        (_EAST_INDIA_BENGAL_POPULATION_LABELS, (646, 200), 4),
    )
)

_EAST_EURASIA_ALL_POPULATION_GROUP_LABELS: dict[str, tuple[str, ...]] = {
    'Northeast Asia': _NORTHEAST_ASIA_POPULATION_LABELS,
    'North China': _NORTH_CHINA_POPULATION_LABELS,
    'South China': _SOUTH_CHINA_POPULATION_LABELS,
    'Siberia / Inner Asia': _SIBERIA_INNER_ASIA_POPULATION_LABELS,
}

_EAST_EURASIA_ALL_POPULATION_LABELS: tuple[str, ...] = _ordered_unique_labels(*_EAST_EURASIA_ALL_POPULATION_GROUP_LABELS.values())

_EAST_EURASIA_ALL_POPULATION_LAYOUT: dict[str, tuple[int, int]] = _build_grouped_population_layout(
    (
        (_SIBERIA_INNER_ASIA_POPULATION_LABELS, (250, 156), 5),
        (_NORTH_CHINA_POPULATION_LABELS, (486, 186), 4),
        (_NORTHEAST_ASIA_POPULATION_LABELS, (682, 154), 4),
        (_SOUTH_CHINA_POPULATION_LABELS, (532, 330), 5),
    )
)

_REGIONAL_READY_MADE_SPACES: dict[str, dict[str, object]] = {
    'ready_made_europe': {
        'code': 'eu',
        'title': 'Europe',
        'region_labels': _EUROPE_REGION_LABELS,
        'layout': _EUROPE_REGION_LAYOUT,
        'label_offsets': _EUROPE_LABEL_OFFSETS,
        'bounds': (106, 68, 698, 370),
        'frame': (44, 42, 806, 380),
        'boxes': (
            (92, 92, 180, 268, (231, 236, 242)),
            (294, 78, 172, 132, (238, 233, 224)),
            (304, 210, 204, 154, (232, 226, 211)),
            (508, 102, 194, 176, (229, 223, 210)),
            (506, 278, 146, 82, (225, 234, 227)),
        ),
    },
    'ready_made_caucasus_steppe': {
        'code': 'cs',
        'title': 'Caucasus / Steppe',
        'region_labels': _CAUCASUS_STEPPE_REGION_LABELS,
        'layout': _CAUCASUS_STEPPE_REGION_LAYOUT,
        'label_offsets': _CAUCASUS_STEPPE_LABEL_OFFSETS,
        'bounds': (112, 76, 760, 348),
        'frame': (44, 42, 806, 380),
        'boxes': (
            (92, 122, 230, 188, (231, 236, 242)),
            (280, 120, 220, 170, (238, 233, 224)),
            (210, 282, 168, 76, (232, 226, 211)),
            (500, 82, 282, 132, (229, 223, 210)),
            (522, 214, 198, 92, (225, 234, 227)),
        ),
    },
    'ready_made_south_asia': {
        'code': 'sa',
        'title': 'South Asia',
        'region_labels': _SOUTH_ASIA_REGION_LABELS,
        'layout': _SOUTH_ASIA_REGION_LAYOUT,
        'label_offsets': _SOUTH_ASIA_LABEL_OFFSETS,
        'bounds': (112, 72, 700, 366),
        'frame': (44, 42, 806, 380),
        'boxes': (
            (120, 112, 204, 158, (231, 236, 242)),
            (332, 74, 162, 118, (238, 233, 224)),
            (312, 186, 354, 160, (232, 226, 211)),
            (182, 260, 168, 98, (229, 223, 210)),
            (614, 154, 118, 88, (225, 234, 227)),
        ),
    },
    'ready_made_east_eurasia': {
        'code': 'ee',
        'title': 'East Eurasia',
        'region_labels': _EAST_EURASIA_REGION_LABELS,
        'layout': _EAST_EURASIA_REGION_LAYOUT,
        'label_offsets': _EAST_EURASIA_LABEL_OFFSETS,
        'bounds': (126, 68, 760, 382),
        'frame': (44, 42, 806, 380),
        'boxes': (
            (120, 72, 210, 104, (231, 236, 242)),
            (314, 110, 146, 126, (238, 233, 224)),
            (460, 118, 194, 122, (232, 226, 211)),
            (450, 242, 212, 118, (229, 223, 210)),
            (286, 236, 132, 96, (225, 234, 227)),
            (678, 136, 110, 82, (231, 236, 242)),
        ),
    },
}

_DETAIL_CONFIGURED_SPACES: dict[str, dict[str, object]] = {
    'west_eurasia_europe_detail': {
        'code': 'weed',
        'title': 'Europe',
        'region_labels': _WEST_EURASIA_EUROPE_DETAIL_REGION_LABELS,
        'layout': _WEST_EURASIA_EUROPE_DETAIL_LAYOUT,
        'label_offsets': _WEST_EURASIA_EUROPE_DETAIL_LABEL_OFFSETS,
        'bounds': (108, 72, 724, 396),
        'frame': (44, 42, 806, 380),
        'boxes': (
            (116, 62, 304, 136, (0, 0, 0)),
            (374, 108, 328, 152, (0, 0, 0)),
            (174, 252, 244, 158, (0, 0, 0)),
            (432, 232, 264, 146, (0, 0, 0)),
        ),
    },
    'west_eurasia_caucasus_detail': {
        'code': 'wecd',
        'title': 'Caucasus',
        'region_labels': _WEST_EURASIA_CAUCASUS_DETAIL_REGION_LABELS,
        'layout': _WEST_EURASIA_CAUCASUS_DETAIL_LAYOUT,
        'label_offsets': _WEST_EURASIA_CAUCASUS_DETAIL_LABEL_OFFSETS,
        'bounds': (110, 102, 762, 368),
        'frame': (44, 42, 806, 380),
        'boxes': (
            (96, 104, 254, 164, (0, 0, 0)),
            (260, 188, 272, 174, (0, 0, 0)),
            (520, 112, 252, 148, (0, 0, 0)),
        ),
    },
    'west_eurasia_anatolia_detail': {
        'code': 'wead',
        'title': 'Anatolia',
        'region_labels': _WEST_EURASIA_ANATOLIA_DETAIL_REGION_LABELS,
        'layout': _WEST_EURASIA_ANATOLIA_DETAIL_LAYOUT,
        'label_offsets': _WEST_EURASIA_ANATOLIA_DETAIL_LABEL_OFFSETS,
        'bounds': (92, 78, 816, 386),
        'frame': (44, 42, 806, 380),
        'boxes': (
            (80, 166, 260, 212, (0, 0, 0)),
            (314, 126, 320, 184, (0, 0, 0)),
            (596, 74, 220, 248, (0, 0, 0)),
        ),
    },
    'west_eurasia_levant_detail': {
        'code': 'weld',
        'title': 'Levant',
        'region_labels': _WEST_EURASIA_LEVANT_DETAIL_REGION_LABELS,
        'layout': _WEST_EURASIA_LEVANT_DETAIL_LAYOUT,
        'label_offsets': _WEST_EURASIA_LEVANT_DETAIL_LABEL_OFFSETS,
        'bounds': (116, 70, 760, 394),
        'frame': (44, 42, 806, 380),
        'boxes': (
            (192, 84, 314, 176, (0, 0, 0)),
            (120, 238, 336, 168, (0, 0, 0)),
            (472, 148, 286, 214, (0, 0, 0)),
        ),
    },
    'west_eurasia_mesopotamia_iran_detail': {
        'code': 'wemid',
        'title': 'Mesopotamia / Iran',
        'region_labels': _WEST_EURASIA_MESO_IRAN_DETAIL_REGION_LABELS,
        'layout': _WEST_EURASIA_MESO_IRAN_DETAIL_LAYOUT,
        'label_offsets': _WEST_EURASIA_MESO_IRAN_DETAIL_LABEL_OFFSETS,
        'bounds': (116, 70, 826, 392),
        'frame': (44, 42, 806, 380),
        'boxes': (
            (114, 150, 270, 220, (0, 0, 0)),
            (450, 82, 298, 214, (0, 0, 0)),
            (356, 274, 350, 146, (0, 0, 0)),
        ),
    },
    'west_eurasia_steppe_detail': {
        'code': 'wesd',
        'title': 'Steppe',
        'region_labels': _WEST_EURASIA_STEPPE_DETAIL_REGION_LABELS,
        'layout': _WEST_EURASIA_STEPPE_DETAIL_LAYOUT,
        'label_offsets': _WEST_EURASIA_STEPPE_DETAIL_LABEL_OFFSETS,
        'bounds': (110, 98, 836, 344),
        'frame': (44, 42, 806, 380),
        'boxes': (
            (120, 144, 248, 196, (0, 0, 0)),
            (356, 96, 274, 212, (0, 0, 0)),
            (598, 84, 244, 230, (0, 0, 0)),
        ),
    },
    'northwest_south_asia_detail': {
        'code': 'nwsad',
        'title': 'Northwest South Asia',
        'region_labels': _NORTHWEST_SOUTH_ASIA_DETAIL_REGION_LABELS,
        'layout': _NORTHWEST_SOUTH_ASIA_DETAIL_LAYOUT,
        'label_offsets': _NORTHWEST_SOUTH_ASIA_DETAIL_LABEL_OFFSETS,
        'bounds': (110, 72, 784, 388),
        'frame': (44, 42, 806, 380),
        'boxes': (
            (116, 116, 306, 184, (0, 0, 0)),
            (334, 54, 324, 226, (0, 0, 0)),
            (128, 286, 350, 118, (0, 0, 0)),
        ),
    },
    'gangetic_north_india_detail': {
        'code': 'gnid',
        'title': 'Gangetic / North India',
        'region_labels': _GANGETIC_NORTH_INDIA_DETAIL_REGION_LABELS,
        'layout': _GANGETIC_NORTH_INDIA_DETAIL_LAYOUT,
        'label_offsets': _GANGETIC_NORTH_INDIA_DETAIL_LABEL_OFFSETS,
        'bounds': (122, 72, 742, 352),
        'frame': (44, 42, 806, 380),
        'boxes': (
            (134, 140, 250, 172, (0, 0, 0)),
            (374, 62, 278, 134, (0, 0, 0)),
            (374, 214, 324, 158, (0, 0, 0)),
        ),
    },
    'west_india_detail': {
        'code': 'wid',
        'title': 'West India',
        'region_labels': _WEST_INDIA_DETAIL_REGION_LABELS,
        'layout': _WEST_INDIA_DETAIL_LAYOUT,
        'label_offsets': _WEST_INDIA_DETAIL_LABEL_OFFSETS,
        'bounds': (104, 90, 690, 366),
        'frame': (44, 42, 806, 380),
        'boxes': (
            (100, 112, 254, 214, (0, 0, 0)),
            (352, 74, 210, 162, (0, 0, 0)),
            (334, 232, 306, 162, (0, 0, 0)),
        ),
    },
    'south_india_detail': {
        'code': 'sid',
        'title': 'South India',
        'region_labels': _SOUTH_INDIA_DETAIL_REGION_LABELS,
        'layout': _SOUTH_INDIA_DETAIL_LAYOUT,
        'label_offsets': _SOUTH_INDIA_DETAIL_LABEL_OFFSETS,
        'bounds': (102, 104, 706, 388),
        'frame': (44, 42, 806, 380),
        'boxes': (
            (182, 112, 276, 134, (0, 0, 0)),
            (126, 248, 244, 170, (0, 0, 0)),
            (354, 228, 350, 186, (0, 0, 0)),
        ),
    },
    'east_india_bengal_detail': {
        'code': 'eibd',
        'title': 'East India / Bengal',
        'region_labels': _EAST_INDIA_BENGAL_DETAIL_REGION_LABELS,
        'layout': _EAST_INDIA_BENGAL_DETAIL_LAYOUT,
        'label_offsets': _EAST_INDIA_BENGAL_DETAIL_LABEL_OFFSETS,
        'bounds': (124, 72, 764, 392),
        'frame': (44, 42, 806, 380),
        'boxes': (
            (430, 120, 260, 182, (0, 0, 0)),
            (218, 56, 296, 178, (0, 0, 0)),
            (158, 246, 248, 170, (0, 0, 0)),
        ),
    },
    'northeast_asia_detail': {
        'code': 'nead',
        'title': 'Northeast Asia',
        'region_labels': _NORTHEAST_ASIA_DETAIL_REGION_LABELS,
        'layout': _NORTHEAST_ASIA_DETAIL_LAYOUT,
        'label_offsets': _NORTHEAST_ASIA_DETAIL_LABEL_OFFSETS,
        'bounds': (118, 88, 756, 336),
        'frame': (44, 42, 806, 380),
        'boxes': (
            (96, 178, 220, 150, (0, 0, 0)),
            (344, 112, 256, 168, (0, 0, 0)),
            (574, 64, 232, 148, (0, 0, 0)),
        ),
    },
    'north_china_detail': {
        'code': 'nchd',
        'title': 'North China',
        'region_labels': _NORTH_CHINA_DETAIL_REGION_LABELS,
        'layout': _NORTH_CHINA_DETAIL_LAYOUT,
        'label_offsets': _NORTH_CHINA_DETAIL_LABEL_OFFSETS,
        'bounds': (118, 88, 760, 354),
        'frame': (44, 42, 806, 380),
        'boxes': (
            (110, 144, 226, 180, (0, 0, 0)),
            (342, 126, 232, 188, (0, 0, 0)),
            (566, 76, 206, 214, (0, 0, 0)),
        ),
    },
    'south_china_detail': {
        'code': 'schd',
        'title': 'South China',
        'region_labels': _SOUTH_CHINA_DETAIL_REGION_LABELS,
        'layout': _SOUTH_CHINA_DETAIL_LAYOUT,
        'label_offsets': _SOUTH_CHINA_DETAIL_LABEL_OFFSETS,
        'bounds': (104, 104, 790, 372),
        'frame': (44, 42, 806, 380),
        'boxes': (
            (456, 92, 194, 180, (0, 0, 0)),
            (606, 196, 198, 164, (0, 0, 0)),
            (114, 172, 376, 212, (0, 0, 0)),
        ),
    },
    'siberia_inner_asia_detail': {
        'code': 'siad',
        'title': 'Siberia / Inner Asia',
        'region_labels': _SIBERIA_INNER_ASIA_DETAIL_REGION_LABELS,
        'layout': _SIBERIA_INNER_ASIA_DETAIL_LAYOUT,
        'label_offsets': _SIBERIA_INNER_ASIA_DETAIL_LABEL_OFFSETS,
        'bounds': (114, 74, 796, 364),
        'frame': (44, 42, 806, 380),
        'boxes': (
            (96, 102, 252, 188, (0, 0, 0)),
            (328, 168, 316, 206, (0, 0, 0)),
            (596, 54, 220, 178, (0, 0, 0)),
        ),
    },
    'north_caucasus_detail': {
        'code': 'ncd',
        'title': 'North Caucasus',
        'region_labels': _NORTH_CAUCASUS_DETAIL_REGION_LABELS,
        'layout': _NORTH_CAUCASUS_DETAIL_LAYOUT,
        'label_offsets': _NORTH_CAUCASUS_DETAIL_LABEL_OFFSETS,
        'bounds': (120, 92, 744, 320),
        'frame': (44, 42, 806, 380),
        'boxes': (
            (96, 106, 214, 136, (0, 0, 0)),
            (304, 118, 202, 128, (0, 0, 0)),
            (496, 104, 212, 124, (0, 0, 0)),
            (410, 244, 234, 74, (0, 0, 0)),
        ),
    },
    'south_caucasus_detail': {
        'code': 'scd',
        'title': 'South Caucasus',
        'region_labels': _SOUTH_CAUCASUS_DETAIL_REGION_LABELS,
        'layout': _SOUTH_CAUCASUS_DETAIL_LAYOUT,
        'label_offsets': _SOUTH_CAUCASUS_DETAIL_LABEL_OFFSETS,
        'bounds': (116, 92, 742, 336),
        'frame': (44, 42, 806, 380),
        'boxes': (
            (94, 116, 238, 170, (0, 0, 0)),
            (276, 180, 256, 168, (0, 0, 0)),
            (528, 104, 214, 226, (0, 0, 0)),
        ),
    },
    'steppe_fringe_detail': {
        'code': 'sfd',
        'title': 'Steppe fringe',
        'region_labels': _STEPPE_FRINGE_DETAIL_REGION_LABELS,
        'layout': _STEPPE_FRINGE_DETAIL_LAYOUT,
        'label_offsets': _STEPPE_FRINGE_DETAIL_LABEL_OFFSETS,
        'bounds': (120, 90, 744, 346),
        'frame': (44, 42, 806, 380),
        'boxes': (
            (116, 84, 258, 128, (0, 0, 0)),
            (322, 146, 274, 156, (0, 0, 0)),
            (546, 236, 220, 126, (0, 0, 0)),
        ),
    },
    'north_europe_detail': {
        'code': 'ned',
        'title': 'North Europe',
        'region_labels': _NORTH_EUROPE_DETAIL_REGION_LABELS,
        'layout': _NORTH_EUROPE_DETAIL_LAYOUT,
        'label_offsets': _NORTH_EUROPE_DETAIL_LABEL_OFFSETS,
        'bounds': (96, 74, 560, 360),
        'frame': (44, 42, 806, 380),
        'boxes': (
            (94, 70, 238, 112, (0, 0, 0)),
            (364, 62, 194, 146, (0, 0, 0)),
            (94, 188, 346, 174, (0, 0, 0)),
        ),
    },
    'south_europe_detail': {
        'code': 'sed',
        'title': 'South Europe',
        'region_labels': _SOUTH_EUROPE_DETAIL_REGION_LABELS,
        'layout': _SOUTH_EUROPE_DETAIL_LAYOUT,
        'label_offsets': _SOUTH_EUROPE_DETAIL_LABEL_OFFSETS,
        'bounds': (50, 146, 676, 396),
        'frame': (44, 42, 806, 380),
        'boxes': (
            (44, 156, 186, 242, (0, 0, 0)),
            (194, 148, 208, 248, (0, 0, 0)),
            (426, 156, 244, 244, (0, 0, 0)),
        ),
    },
    'balkans_detail': {
        'code': 'bkd',
        'title': 'Balkans',
        'region_labels': _BALKANS_DETAIL_REGION_LABELS,
        'layout': _BALKANS_DETAIL_LAYOUT,
        'label_offsets': _BALKANS_DETAIL_LABEL_OFFSETS,
        'bounds': (120, 94, 582, 382),
        'frame': (44, 42, 806, 380),
        'boxes': (
            (118, 96, 190, 248, (0, 0, 0)),
            (302, 122, 198, 182, (0, 0, 0)),
            (278, 274, 306, 120, (0, 0, 0)),
        ),
    },
    'baltic_detail': {
        'code': 'bld',
        'title': 'Baltic',
        'region_labels': _BALTIC_DETAIL_REGION_LABELS,
        'layout': _BALTIC_DETAIL_LAYOUT,
        'label_offsets': _BALTIC_DETAIL_LABEL_OFFSETS,
        'bounds': (228, 72, 566, 332),
        'frame': (44, 42, 806, 380),
        'boxes': (
            (236, 82, 124, 84, (0, 0, 0)),
            (292, 146, 136, 96, (0, 0, 0)),
            (350, 186, 216, 158, (0, 0, 0)),
        ),
    },
    'east_europe_detail': {
        'code': 'eed',
        'title': 'East Europe',
        'region_labels': _EAST_EUROPE_DETAIL_REGION_LABELS,
        'layout': _EAST_EUROPE_DETAIL_LAYOUT,
        'label_offsets': _EAST_EUROPE_DETAIL_LABEL_OFFSETS,
        'bounds': (128, 92, 736, 344),
        'frame': (44, 42, 806, 380),
        'boxes': (
            (128, 88, 256, 132, (0, 0, 0)),
            (256, 214, 248, 126, (0, 0, 0)),
            (498, 92, 250, 132, (0, 0, 0)),
            (454, 282, 300, 80, (0, 0, 0)),
        ),
    },
}

_ALL_CONFIGURED_SPACES: dict[str, dict[str, object]] = {
    **_REGIONAL_READY_MADE_SPACES,
    **_DETAIL_CONFIGURED_SPACES,
}

_REGIONAL_SAMPLE_ROOT_ACTIONS = {
    f"{config['code']}_sample": action
    for action, config in _REGIONAL_READY_MADE_SPACES.items()
}

_REGIONAL_SAVE_ROOT_ACTIONS = {
    f"{config['code']}_save": action
    for action, config in _REGIONAL_READY_MADE_SPACES.items()
}

_DETAIL_SAMPLE_ROOT_ACTIONS = {
    'weed_sample': 'west_eurasia_europe_detail',
    'wecd_sample': 'west_eurasia_caucasus_detail',
    'wead_sample': 'west_eurasia_anatolia_detail',
    'weld_sample': 'west_eurasia_levant_detail',
    'wemid_sample': 'west_eurasia_mesopotamia_iran_detail',
    'wesd_sample': 'west_eurasia_steppe_detail',
    'nwsad_sample': 'northwest_south_asia_detail',
    'gnid_sample': 'gangetic_north_india_detail',
    'wid_sample': 'west_india_detail',
    'sid_sample': 'south_india_detail',
    'eibd_sample': 'east_india_bengal_detail',
    'nead_sample': 'northeast_asia_detail',
    'nchd_sample': 'north_china_detail',
    'schd_sample': 'south_china_detail',
    'siad_sample': 'siberia_inner_asia_detail',
    'ncd_sample': 'north_caucasus_detail',
    'scd_sample': 'south_caucasus_detail',
    'sfd_sample': 'steppe_fringe_detail',
    'ned_sample': 'north_europe_detail',
    'sed_sample': 'south_europe_detail',
    'bkd_sample': 'balkans_detail',
    'bld_sample': 'baltic_detail',
    'eed_sample': 'east_europe_detail',
}

_DETAIL_SAVE_ROOT_ACTIONS = {
    'weed_save': 'west_eurasia_europe_detail',
    'wecd_save': 'west_eurasia_caucasus_detail',
    'wead_save': 'west_eurasia_anatolia_detail',
    'weld_save': 'west_eurasia_levant_detail',
    'wemid_save': 'west_eurasia_mesopotamia_iran_detail',
    'wesd_save': 'west_eurasia_steppe_detail',
    'nwsad_save': 'northwest_south_asia_detail',
    'gnid_save': 'gangetic_north_india_detail',
    'wid_save': 'west_india_detail',
    'sid_save': 'south_india_detail',
    'eibd_save': 'east_india_bengal_detail',
    'nead_save': 'northeast_asia_detail',
    'nchd_save': 'north_china_detail',
    'schd_save': 'south_china_detail',
    'siad_save': 'siberia_inner_asia_detail',
    'ncd_save': 'north_caucasus_detail',
    'scd_save': 'south_caucasus_detail',
    'sfd_save': 'steppe_fringe_detail',
    'ned_save': 'north_europe_detail',
    'sed_save': 'south_europe_detail',
    'bkd_save': 'balkans_detail',
    'bld_save': 'baltic_detail',
    'eed_save': 'east_europe_detail',
}

_DETAIL_POPULATION_SAVE_ROOT_ACTIONS = {
    f'{save_root}p': detail_action
    for save_root, detail_action in _DETAIL_SAVE_ROOT_ACTIONS.items()
}

_READY_MADE_ALL_POPULATION_FLOWS: dict[str, dict[str, str]] = {
    'ready_made_west_eurasia_all_populations': {
        'title': 'West Eurasia',
        'mode_action': 'west_eurasia_all_populations_mode',
        'sample_root': 'weallp_sample',
        'change_action': 'west_eurasia_all_populations_change',
        'back_callback': f'{COORDINATE_SPACE_CALLBACK_PREFIX}:west_eurasia_detail_menu',
        'save_root': 'weallp_save',
    },
    'ready_made_europe_all_populations': {
        'title': 'Europe',
        'mode_action': 'europe_all_populations_mode',
        'sample_root': 'euallp_sample',
        'change_action': 'europe_all_populations_change',
        'back_callback': f'{COORDINATE_SPACE_CALLBACK_PREFIX}:europe_detail_menu',
        'save_root': 'euallp_save',
    },
    'ready_made_south_asia_all_populations': {
        'title': 'South Asia',
        'mode_action': 'south_asia_all_populations_mode',
        'sample_root': 'saallp_sample',
        'change_action': 'south_asia_all_populations_change',
        'back_callback': f'{COORDINATE_SPACE_CALLBACK_PREFIX}:south_asia_detail_menu',
        'save_root': 'saallp_save',
    },
    'ready_made_east_eurasia_all_populations': {
        'title': 'East Eurasia',
        'mode_action': 'east_eurasia_all_populations_mode',
        'sample_root': 'eeallp_sample',
        'change_action': 'east_eurasia_all_populations_change',
        'back_callback': f'{COORDINATE_SPACE_CALLBACK_PREFIX}:east_eurasia_detail_menu',
        'save_root': 'eeallp_save',
    },
}

_READY_MADE_ALL_POPULATION_MODE_ACTIONS = {
    config['mode_action']: view_action
    for view_action, config in _READY_MADE_ALL_POPULATION_FLOWS.items()
}

_READY_MADE_ALL_POPULATION_SAMPLE_ROOT_ACTIONS = {
    config['sample_root']: view_action
    for view_action, config in _READY_MADE_ALL_POPULATION_FLOWS.items()
}

_READY_MADE_ALL_POPULATION_CHANGE_ACTIONS = {
    config['change_action']: view_action
    for view_action, config in _READY_MADE_ALL_POPULATION_FLOWS.items()
}

_EUROPE_DETAIL_BRANCH_CONFIGS: dict[str, dict[str, str]] = {
    'east_europe_detail': {
        'title': 'East Europe',
        'sample_root': 'eed_sample',
        'population_sample_root': 'eedp_sample',
        'population_callback': 'eep',
        'region_mode_action': 'east_europe_region_mode',
        'population_mode_action': 'east_europe_population_mode',
        'change_action': 'east_europe_detail_change',
        'population_change_action': 'east_europe_population_change',
        'save_root': 'eed_save',
    },
    'north_europe_detail': {
        'title': 'North Europe',
        'sample_root': 'ned_sample',
        'population_sample_root': 'nedp_sample',
        'population_callback': 'neup',
        'region_mode_action': 'north_europe_region_mode',
        'population_mode_action': 'north_europe_population_mode',
        'change_action': 'north_europe_detail_change',
        'population_change_action': 'north_europe_population_change',
        'save_root': 'ned_save',
    },
    'south_europe_detail': {
        'title': 'South Europe',
        'sample_root': 'sed_sample',
        'population_sample_root': 'sedp_sample',
        'population_callback': 'seup',
        'region_mode_action': 'south_europe_region_mode',
        'population_mode_action': 'south_europe_population_mode',
        'change_action': 'south_europe_detail_change',
        'population_change_action': 'south_europe_population_change',
        'save_root': 'sed_save',
    },
    'balkans_detail': {
        'title': 'Balkans',
        'sample_root': 'bkd_sample',
        'population_sample_root': 'bkdp_sample',
        'population_callback': 'bkp',
        'region_mode_action': 'balkans_region_mode',
        'population_mode_action': 'balkans_population_mode',
        'change_action': 'balkans_detail_change',
        'population_change_action': 'balkans_population_change',
        'save_root': 'bkd_save',
    },
    'baltic_detail': {
        'title': 'Baltic',
        'sample_root': 'bld_sample',
        'population_sample_root': 'bldp_sample',
        'population_callback': 'blp',
        'region_mode_action': 'baltic_region_mode',
        'population_mode_action': 'baltic_population_mode',
        'change_action': 'baltic_detail_change',
        'population_change_action': 'baltic_population_change',
        'save_root': 'bld_save',
    },
}

_CAUCASUS_DETAIL_BRANCH_CONFIGS: dict[str, dict[str, str]] = {
    'north_caucasus_detail': {
        'title': 'North Caucasus',
        'sample_root': 'ncd_sample',
        'population_sample_root': 'ncdp_sample',
        'population_callback': 'ncp',
        'region_mode_action': 'north_caucasus_region_mode',
        'population_mode_action': 'north_caucasus_population_mode',
        'change_action': 'north_caucasus_detail_change',
        'population_change_action': 'north_caucasus_population_change',
        'save_root': 'ncd_save',
    },
    'south_caucasus_detail': {
        'title': 'South Caucasus',
        'sample_root': 'scd_sample',
        'population_sample_root': 'scdp_sample',
        'population_callback': 'scp',
        'region_mode_action': 'south_caucasus_region_mode',
        'population_mode_action': 'south_caucasus_population_mode',
        'change_action': 'south_caucasus_detail_change',
        'population_change_action': 'south_caucasus_population_change',
        'save_root': 'scd_save',
    },
    'steppe_fringe_detail': {
        'title': 'Steppe fringe',
        'sample_root': 'sfd_sample',
        'population_sample_root': 'sfdp_sample',
        'population_callback': 'sfp',
        'region_mode_action': 'steppe_fringe_region_mode',
        'population_mode_action': 'steppe_fringe_population_mode',
        'change_action': 'steppe_fringe_detail_change',
        'population_change_action': 'steppe_fringe_population_change',
        'save_root': 'sfd_save',
    },
}

_EAST_EURASIA_DETAIL_BRANCH_CONFIGS: dict[str, dict[str, str]] = {
    'northeast_asia_detail': {
        'title': 'Northeast Asia',
        'sample_root': 'nead_sample',
        'population_sample_root': 'neadp_sample',
        'population_callback': 'neap',
        'region_mode_action': 'northeast_asia_region_mode',
        'population_mode_action': 'northeast_asia_population_mode',
        'change_action': 'northeast_asia_detail_change',
        'population_change_action': 'northeast_asia_population_change',
        'save_root': 'nead_save',
    },
    'north_china_detail': {
        'title': 'North China',
        'sample_root': 'nchd_sample',
        'population_sample_root': 'nchdp_sample',
        'population_callback': 'ncpop',
        'region_mode_action': 'north_china_region_mode',
        'population_mode_action': 'north_china_population_mode',
        'change_action': 'north_china_detail_change',
        'population_change_action': 'north_china_population_change',
        'save_root': 'nchd_save',
    },
    'south_china_detail': {
        'title': 'South China',
        'sample_root': 'schd_sample',
        'population_sample_root': 'schdp_sample',
        'population_callback': 'schp',
        'region_mode_action': 'south_china_region_mode',
        'population_mode_action': 'south_china_population_mode',
        'change_action': 'south_china_detail_change',
        'population_change_action': 'south_china_population_change',
        'save_root': 'schd_save',
    },
    'siberia_inner_asia_detail': {
        'title': 'Siberia / Inner Asia',
        'sample_root': 'siad_sample',
        'population_sample_root': 'siadp_sample',
        'population_callback': 'siap',
        'region_mode_action': 'siberia_inner_asia_region_mode',
        'population_mode_action': 'siberia_inner_asia_population_mode',
        'change_action': 'siberia_inner_asia_detail_change',
        'population_change_action': 'siberia_inner_asia_population_change',
        'save_root': 'siad_save',
    },
}

_SOUTH_ASIA_DETAIL_BRANCH_CONFIGS: dict[str, dict[str, str]] = {
    'northwest_south_asia_detail': {
        'title': 'Northwest South Asia',
        'sample_root': 'nwsad_sample',
        'population_sample_root': 'nwsadp_sample',
        'population_callback': 'nwsap',
        'region_mode_action': 'northwest_south_asia_region_mode',
        'population_mode_action': 'northwest_south_asia_population_mode',
        'change_action': 'northwest_south_asia_detail_change',
        'population_change_action': 'northwest_south_asia_population_change',
        'save_root': 'nwsad_save',
    },
    'gangetic_north_india_detail': {
        'title': 'Gangetic / North India',
        'sample_root': 'gnid_sample',
        'population_sample_root': 'gnidp_sample',
        'population_callback': 'gnip',
        'region_mode_action': 'gangetic_north_india_region_mode',
        'population_mode_action': 'gangetic_north_india_population_mode',
        'change_action': 'gangetic_north_india_detail_change',
        'population_change_action': 'gangetic_north_india_population_change',
        'save_root': 'gnid_save',
    },
    'west_india_detail': {
        'title': 'West India',
        'sample_root': 'wid_sample',
        'population_sample_root': 'widp_sample',
        'population_callback': 'wip',
        'region_mode_action': 'west_india_region_mode',
        'population_mode_action': 'west_india_population_mode',
        'change_action': 'west_india_detail_change',
        'population_change_action': 'west_india_population_change',
        'save_root': 'wid_save',
    },
    'south_india_detail': {
        'title': 'South India',
        'sample_root': 'sid_sample',
        'population_sample_root': 'sidp_sample',
        'population_callback': 'sip',
        'region_mode_action': 'south_india_region_mode',
        'population_mode_action': 'south_india_population_mode',
        'change_action': 'south_india_detail_change',
        'population_change_action': 'south_india_population_change',
        'save_root': 'sid_save',
    },
    'east_india_bengal_detail': {
        'title': 'East India / Bengal',
        'sample_root': 'eibd_sample',
        'population_sample_root': 'eibdp_sample',
        'population_callback': 'eibp',
        'region_mode_action': 'east_india_bengal_region_mode',
        'population_mode_action': 'east_india_bengal_population_mode',
        'change_action': 'east_india_bengal_detail_change',
        'population_change_action': 'east_india_bengal_population_change',
        'save_root': 'eibd_save',
    },
}

_WEST_EURASIA_DETAIL_BRANCH_CONFIGS: dict[str, dict[str, str]] = {
    'west_eurasia_europe_detail': {
        'title': 'Europe',
        'sample_root': 'weed_sample',
        'population_sample_root': 'weedp_sample',
        'population_callback': 'weep',
        'region_mode_action': 'west_eurasia_europe_region_mode',
        'population_mode_action': 'west_eurasia_europe_population_mode',
        'change_action': 'west_eurasia_europe_detail_change',
        'population_change_action': 'west_eurasia_europe_population_change',
        'save_root': 'weed_save',
    },
    'west_eurasia_caucasus_detail': {
        'title': 'Caucasus',
        'sample_root': 'wecd_sample',
        'population_sample_root': 'wecdp_sample',
        'population_callback': 'wecp',
        'region_mode_action': 'west_eurasia_caucasus_region_mode',
        'population_mode_action': 'west_eurasia_caucasus_population_mode',
        'change_action': 'west_eurasia_caucasus_detail_change',
        'population_change_action': 'west_eurasia_caucasus_population_change',
        'save_root': 'wecd_save',
    },
    'west_eurasia_anatolia_detail': {
        'title': 'Anatolia',
        'sample_root': 'wead_sample',
        'population_sample_root': 'weadp_sample',
        'population_callback': 'weap',
        'region_mode_action': 'west_eurasia_anatolia_region_mode',
        'population_mode_action': 'west_eurasia_anatolia_population_mode',
        'change_action': 'west_eurasia_anatolia_detail_change',
        'population_change_action': 'west_eurasia_anatolia_population_change',
        'save_root': 'wead_save',
    },
    'west_eurasia_levant_detail': {
        'title': 'Levant',
        'sample_root': 'weld_sample',
        'population_sample_root': 'weldp_sample',
        'population_callback': 'welp',
        'region_mode_action': 'west_eurasia_levant_region_mode',
        'population_mode_action': 'west_eurasia_levant_population_mode',
        'change_action': 'west_eurasia_levant_detail_change',
        'population_change_action': 'west_eurasia_levant_population_change',
        'save_root': 'weld_save',
    },
    'west_eurasia_mesopotamia_iran_detail': {
        'title': 'Mesopotamia / Iran',
        'sample_root': 'wemid_sample',
        'population_sample_root': 'wemidp_sample',
        'population_callback': 'wemip',
        'region_mode_action': 'west_eurasia_mesopotamia_iran_region_mode',
        'population_mode_action': 'west_eurasia_mesopotamia_iran_population_mode',
        'change_action': 'west_eurasia_mesopotamia_iran_detail_change',
        'population_change_action': 'west_eurasia_mesopotamia_iran_population_change',
        'save_root': 'wemid_save',
    },
    'west_eurasia_steppe_detail': {
        'title': 'Steppe',
        'sample_root': 'wesd_sample',
        'population_sample_root': 'wesdp_sample',
        'population_callback': 'wesp',
        'region_mode_action': 'west_eurasia_steppe_region_mode',
        'population_mode_action': 'west_eurasia_steppe_population_mode',
        'change_action': 'west_eurasia_steppe_detail_change',
        'population_change_action': 'west_eurasia_steppe_population_change',
        'save_root': 'wesd_save',
    },
}

_POPULATION_VIEW_CONFIGS: dict[str, dict[str, object]] = {
    'ready_made_caucasus_steppe_all_populations': {
        'title': 'Caucasus / Steppe',
        'population_labels': _CAUCASUS_STEPPE_ALL_POPULATION_LABELS,
        'layout': _CAUCASUS_STEPPE_ALL_POPULATION_LAYOUT,
        'bounds': (92, 80, 774, 390),
        'frame': (44, 42, 806, 380),
        'boxes': (
            (82, 98, 260, 178, (0, 0, 0)),
            (334, 92, 248, 182, (0, 0, 0)),
            (212, 254, 258, 138, (0, 0, 0)),
            (492, 84, 292, 130, (0, 0, 0)),
            (530, 214, 236, 126, (0, 0, 0)),
        ),
        'back_callback': f'{COORDINATE_SPACE_CALLBACK_PREFIX}:caucasus_detail_menu',
        'change_action': 'caucasus_steppe_population_change',
        'save_root': 'csallp_save',
    },
    'ready_made_west_eurasia_all_populations': {
        'title': 'West Eurasia',
        'population_labels': _WEST_EURASIA_ALL_POPULATION_LABELS,
        'layout': _WEST_EURASIA_ALL_POPULATION_LAYOUT,
        'render_scale': 6,
        'label_scale': 2,
        'legend_scale': 2,
        'marker_scale': 1,
        'sample_marker_scale': 2,
        'frame_thickness': 2,
        'bounds': (86, 64, 844, 398),
        'frame': (44, 42, 806, 380),
        'boxes': (
            (74, 70, 244, 176, (0, 0, 0)),
            (346, 74, 244, 178, (0, 0, 0)),
            (596, 58, 230, 126, (0, 0, 0)),
            (82, 250, 248, 172, (0, 0, 0)),
            (336, 264, 252, 152, (0, 0, 0)),
            (600, 198, 222, 200, (0, 0, 0)),
        ),
        'back_callback': f'{COORDINATE_SPACE_CALLBACK_PREFIX}:west_eurasia_detail_menu',
        'change_action': 'west_eurasia_all_populations_change',
        'save_root': 'weallp_save',
    },
    'ready_made_europe_all_populations': {
        'title': 'Europe',
        'population_labels': _EUROPE_ALL_POPULATION_LABELS,
        'layout': _EUROPE_ALL_POPULATION_LAYOUT,
        'render_scale': 6,
        'label_scale': 2,
        'legend_scale': 2,
        'marker_scale': 1,
        'sample_marker_scale': 2,
        'frame_thickness': 2,
        'bounds': (96, 62, 802, 396),
        'frame': (44, 42, 806, 380),
        'boxes': (
            (110, 64, 208, 118, (0, 0, 0)),
            (442, 58, 170, 112, (0, 0, 0)),
            (438, 146, 324, 232, (0, 0, 0)),
            (84, 238, 230, 182, (0, 0, 0)),
            (356, 260, 248, 154, (0, 0, 0)),
        ),
        'back_callback': f'{COORDINATE_SPACE_CALLBACK_PREFIX}:europe_detail_menu',
        'change_action': 'europe_all_populations_change',
        'save_root': 'euallp_save',
    },
    'ready_made_south_asia_all_populations': {
        'title': 'South Asia',
        'population_labels': _SOUTH_ASIA_ALL_POPULATION_LABELS,
        'layout': _SOUTH_ASIA_ALL_POPULATION_LAYOUT,
        'render_scale': 6,
        'label_scale': 2,
        'legend_scale': 2,
        'marker_scale': 1,
        'sample_marker_scale': 2,
        'frame_thickness': 2,
        'bounds': (96, 64, 814, 398),
        'frame': (44, 42, 806, 380),
        'boxes': (
            (74, 72, 244, 178, (0, 0, 0)),
            (330, 82, 202, 146, (0, 0, 0)),
            (82, 250, 208, 174, (0, 0, 0)),
            (296, 248, 254, 172, (0, 0, 0)),
            (560, 96, 254, 208, (0, 0, 0)),
        ),
        'back_callback': f'{COORDINATE_SPACE_CALLBACK_PREFIX}:south_asia_detail_menu',
        'change_action': 'south_asia_all_populations_change',
        'save_root': 'saallp_save',
    },
    'ready_made_east_eurasia_all_populations': {
        'title': 'East Eurasia',
        'population_labels': _EAST_EURASIA_ALL_POPULATION_LABELS,
        'layout': _EAST_EURASIA_ALL_POPULATION_LAYOUT,
        'render_scale': 6,
        'label_scale': 2,
        'legend_scale': 2,
        'marker_scale': 1,
        'sample_marker_scale': 2,
        'frame_thickness': 2,
        'bounds': (92, 60, 838, 398),
        'frame': (44, 42, 806, 380),
        'boxes': (
            (88, 72, 250, 202, (0, 0, 0)),
            (332, 96, 234, 176, (0, 0, 0)),
            (568, 68, 246, 186, (0, 0, 0)),
            (360, 262, 308, 160, (0, 0, 0)),
        ),
        'back_callback': f'{COORDINATE_SPACE_CALLBACK_PREFIX}:east_eurasia_detail_menu',
        'change_action': 'east_eurasia_all_populations_change',
        'save_root': 'eeallp_save',
    },
    'east_europe_detail': {
        'title': 'East Europe',
        'population_labels': _EAST_EUROPE_POPULATION_LABELS,
        'layout': _EAST_EUROPE_POPULATION_LAYOUT,
        'bounds': (100, 64, 780, 390),
        'frame': (44, 42, 806, 380),
        'boxes': (
            (116, 74, 444, 114, (0, 0, 0)),
            (92, 184, 374, 118, (0, 0, 0)),
            (488, 118, 290, 158, (0, 0, 0)),
            (132, 292, 472, 108, (0, 0, 0)),
        ),
        'back_callback': f'{COORDINATE_SPACE_CALLBACK_PREFIX}:east_europe_detail',
        'change_action': 'east_europe_population_change',
        'save_root': 'eed_save',
    },
    'north_europe_detail': {
        'title': 'North Europe',
        'population_labels': _NORTH_EUROPE_POPULATION_LABELS,
        'layout': _NORTH_EUROPE_POPULATION_LAYOUT,
        'bounds': (96, 74, 560, 360),
        'frame': (44, 42, 806, 380),
        'boxes': (
            (94, 70, 238, 112, (0, 0, 0)),
            (364, 62, 194, 146, (0, 0, 0)),
            (94, 188, 346, 174, (0, 0, 0)),
        ),
        'back_callback': f'{COORDINATE_SPACE_CALLBACK_PREFIX}:europe_detail_menu',
        'change_action': 'north_europe_population_change',
        'save_root': 'ned_save',
    },
    'south_europe_detail': {
        'title': 'South Europe',
        'population_labels': _SOUTH_EUROPE_POPULATION_LABELS,
        'layout': _SOUTH_EUROPE_POPULATION_LAYOUT,
        'bounds': (50, 146, 676, 396),
        'frame': (44, 42, 806, 380),
        'boxes': (
            (44, 156, 186, 242, (0, 0, 0)),
            (194, 148, 208, 248, (0, 0, 0)),
            (426, 156, 244, 244, (0, 0, 0)),
        ),
        'back_callback': f'{COORDINATE_SPACE_CALLBACK_PREFIX}:europe_detail_menu',
        'change_action': 'south_europe_population_change',
        'save_root': 'sed_save',
    },
    'balkans_detail': {
        'title': 'Balkans',
        'population_labels': _BALKANS_POPULATION_LABELS,
        'layout': _BALKANS_POPULATION_LAYOUT,
        'bounds': (120, 94, 582, 382),
        'frame': (44, 42, 806, 380),
        'boxes': (
            (118, 96, 190, 248, (0, 0, 0)),
            (302, 122, 198, 182, (0, 0, 0)),
            (278, 274, 306, 120, (0, 0, 0)),
        ),
        'back_callback': f'{COORDINATE_SPACE_CALLBACK_PREFIX}:europe_detail_menu',
        'change_action': 'balkans_population_change',
        'save_root': 'bkd_save',
    },
    'baltic_detail': {
        'title': 'Baltic',
        'population_labels': _BALTIC_POPULATION_LABELS,
        'layout': _BALTIC_POPULATION_LAYOUT,
        'bounds': (228, 72, 566, 332),
        'frame': (44, 42, 806, 380),
        'boxes': (
            (236, 82, 124, 84, (0, 0, 0)),
            (292, 146, 136, 96, (0, 0, 0)),
            (350, 186, 216, 158, (0, 0, 0)),
        ),
        'back_callback': f'{COORDINATE_SPACE_CALLBACK_PREFIX}:europe_detail_menu',
        'change_action': 'baltic_population_change',
        'save_root': 'bld_save',
    },
    'west_eurasia_europe_detail': {
        'title': 'Europe',
        'population_labels': _WEST_EURASIA_EUROPE_POPULATION_LABELS,
        'layout': _WEST_EURASIA_EUROPE_POPULATION_LAYOUT,
        'bounds': (110, 70, 740, 394),
        'frame': (44, 42, 806, 380),
        'boxes': (
            (106, 58, 300, 166, (0, 0, 0)),
            (362, 90, 360, 174, (0, 0, 0)),
            (132, 246, 284, 172, (0, 0, 0)),
            (430, 220, 294, 198, (0, 0, 0)),
        ),
        'back_callback': f'{COORDINATE_SPACE_CALLBACK_PREFIX}:west_eurasia_detail_menu',
        'change_action': 'west_eurasia_europe_population_change',
        'save_root': 'weed_save',
    },
    'west_eurasia_caucasus_detail': {
        'title': 'Caucasus',
        'population_labels': _WEST_EURASIA_CAUCASUS_POPULATION_LABELS,
        'layout': _WEST_EURASIA_CAUCASUS_POPULATION_LAYOUT,
        'bounds': (112, 100, 786, 372),
        'frame': (44, 42, 806, 380),
        'boxes': (
            (94, 100, 266, 166, (0, 0, 0)),
            (246, 182, 292, 182, (0, 0, 0)),
            (518, 110, 272, 234, (0, 0, 0)),
        ),
        'back_callback': f'{COORDINATE_SPACE_CALLBACK_PREFIX}:west_eurasia_detail_menu',
        'change_action': 'west_eurasia_caucasus_population_change',
        'save_root': 'wecd_save',
    },
    'west_eurasia_anatolia_detail': {
        'title': 'Anatolia',
        'population_labels': _WEST_EURASIA_ANATOLIA_POPULATION_LABELS,
        'layout': _WEST_EURASIA_ANATOLIA_POPULATION_LAYOUT,
        'bounds': (86, 76, 840, 392),
        'frame': (44, 42, 806, 380),
        'boxes': (
            (74, 164, 274, 218, (0, 0, 0)),
            (314, 118, 338, 206, (0, 0, 0)),
            (594, 64, 246, 278, (0, 0, 0)),
        ),
        'back_callback': f'{COORDINATE_SPACE_CALLBACK_PREFIX}:west_eurasia_detail_menu',
        'change_action': 'west_eurasia_anatolia_population_change',
        'save_root': 'wead_save',
    },
    'west_eurasia_levant_detail': {
        'title': 'Levant',
        'population_labels': _WEST_EURASIA_LEVANT_POPULATION_LABELS,
        'layout': _WEST_EURASIA_LEVANT_POPULATION_LAYOUT,
        'bounds': (110, 74, 760, 404),
        'frame': (44, 42, 806, 380),
        'boxes': (
            (180, 80, 332, 194, (0, 0, 0)),
            (114, 240, 356, 176, (0, 0, 0)),
            (478, 140, 292, 230, (0, 0, 0)),
        ),
        'back_callback': f'{COORDINATE_SPACE_CALLBACK_PREFIX}:west_eurasia_detail_menu',
        'change_action': 'west_eurasia_levant_population_change',
        'save_root': 'weld_save',
    },
    'west_eurasia_mesopotamia_iran_detail': {
        'title': 'Mesopotamia / Iran',
        'population_labels': _WEST_EURASIA_MESO_IRAN_POPULATION_LABELS,
        'layout': _WEST_EURASIA_MESO_IRAN_POPULATION_LAYOUT,
        'bounds': (114, 70, 832, 404),
        'frame': (44, 42, 806, 380),
        'boxes': (
            (112, 138, 284, 236, (0, 0, 0)),
            (440, 76, 324, 214, (0, 0, 0)),
            (342, 266, 370, 164, (0, 0, 0)),
        ),
        'back_callback': f'{COORDINATE_SPACE_CALLBACK_PREFIX}:west_eurasia_detail_menu',
        'change_action': 'west_eurasia_mesopotamia_iran_population_change',
        'save_root': 'wemid_save',
    },
    'west_eurasia_steppe_detail': {
        'title': 'Steppe',
        'population_labels': _WEST_EURASIA_STEPPE_POPULATION_LABELS,
        'layout': _WEST_EURASIA_STEPPE_POPULATION_LAYOUT,
        'bounds': (116, 94, 846, 356),
        'frame': (44, 42, 806, 380),
        'boxes': (
            (116, 138, 260, 206, (0, 0, 0)),
            (352, 94, 292, 226, (0, 0, 0)),
            (596, 80, 262, 250, (0, 0, 0)),
        ),
        'back_callback': f'{COORDINATE_SPACE_CALLBACK_PREFIX}:west_eurasia_detail_menu',
        'change_action': 'west_eurasia_steppe_population_change',
        'save_root': 'wesd_save',
    },
    'northwest_south_asia_detail': {
        'title': 'Northwest South Asia',
        'population_labels': _NORTHWEST_SOUTH_ASIA_POPULATION_LABELS,
        'layout': _NORTHWEST_SOUTH_ASIA_POPULATION_LAYOUT,
        'bounds': (102, 58, 790, 394),
        'frame': (44, 42, 806, 380),
        'boxes': (
            (108, 110, 312, 190, (0, 0, 0)),
            (330, 52, 360, 220, (0, 0, 0)),
            (130, 286, 322, 130, (0, 0, 0)),
            (678, 78, 126, 144, (0, 0, 0)),
        ),
        'back_callback': f'{COORDINATE_SPACE_CALLBACK_PREFIX}:south_asia_detail_menu',
        'change_action': 'northwest_south_asia_population_change',
        'save_root': 'nwsad_save',
    },
    'gangetic_north_india_detail': {
        'title': 'Gangetic / North India',
        'population_labels': _GANGETIC_NORTH_INDIA_POPULATION_LABELS,
        'layout': _GANGETIC_NORTH_INDIA_POPULATION_LAYOUT,
        'bounds': (120, 66, 720, 368),
        'frame': (44, 42, 806, 380),
        'boxes': (
            (138, 148, 254, 178, (0, 0, 0)),
            (392, 58, 250, 148, (0, 0, 0)),
            (350, 212, 346, 164, (0, 0, 0)),
        ),
        'back_callback': f'{COORDINATE_SPACE_CALLBACK_PREFIX}:south_asia_detail_menu',
        'change_action': 'gangetic_north_india_population_change',
        'save_root': 'gnid_save',
    },
    'west_india_detail': {
        'title': 'West India',
        'population_labels': _WEST_INDIA_POPULATION_LABELS,
        'layout': _WEST_INDIA_POPULATION_LAYOUT,
        'bounds': (110, 100, 676, 380),
        'frame': (44, 42, 806, 380),
        'boxes': (
            (94, 102, 260, 234, (0, 0, 0)),
            (368, 76, 228, 176, (0, 0, 0)),
            (352, 254, 286, 148, (0, 0, 0)),
        ),
        'back_callback': f'{COORDINATE_SPACE_CALLBACK_PREFIX}:south_asia_detail_menu',
        'change_action': 'west_india_population_change',
        'save_root': 'wid_save',
    },
    'south_india_detail': {
        'title': 'South India',
        'population_labels': _SOUTH_INDIA_POPULATION_LABELS,
        'layout': _SOUTH_INDIA_POPULATION_LAYOUT,
        'bounds': (96, 108, 710, 392),
        'frame': (44, 42, 806, 380),
        'boxes': (
            (184, 112, 282, 130, (0, 0, 0)),
            (108, 240, 276, 178, (0, 0, 0)),
            (356, 228, 362, 186, (0, 0, 0)),
        ),
        'back_callback': f'{COORDINATE_SPACE_CALLBACK_PREFIX}:south_asia_detail_menu',
        'change_action': 'south_india_population_change',
        'save_root': 'sid_save',
    },
    'east_india_bengal_detail': {
        'title': 'East India / Bengal',
        'population_labels': _EAST_INDIA_BENGAL_POPULATION_LABELS,
        'layout': _EAST_INDIA_BENGAL_POPULATION_LAYOUT,
        'bounds': (122, 70, 782, 396),
        'frame': (44, 42, 806, 380),
        'boxes': (
            (426, 116, 280, 190, (0, 0, 0)),
            (210, 52, 314, 184, (0, 0, 0)),
            (150, 236, 274, 182, (0, 0, 0)),
            (680, 146, 112, 112, (0, 0, 0)),
        ),
        'back_callback': f'{COORDINATE_SPACE_CALLBACK_PREFIX}:south_asia_detail_menu',
        'change_action': 'east_india_bengal_population_change',
        'save_root': 'eibd_save',
    },
    'north_caucasus_detail': {
        'title': 'North Caucasus',
        'population_labels': _NORTH_CAUCASUS_POPULATION_LABELS,
        'layout': _NORTH_CAUCASUS_POPULATION_LAYOUT,
        'bounds': (116, 92, 752, 344),
        'frame': (44, 42, 806, 380),
        'boxes': (
            (88, 88, 248, 178, (0, 0, 0)),
            (320, 104, 236, 178, (0, 0, 0)),
            (548, 88, 214, 178, (0, 0, 0)),
            (456, 268, 294, 94, (0, 0, 0)),
        ),
        'back_callback': f'{COORDINATE_SPACE_CALLBACK_PREFIX}:north_caucasus_detail',
        'change_action': 'north_caucasus_population_change',
        'save_root': 'ncd_save',
    },
    'northeast_asia_detail': {
        'title': 'Northeast Asia',
        'population_labels': _NORTHEAST_ASIA_POPULATION_LABELS,
        'layout': _NORTHEAST_ASIA_POPULATION_LAYOUT,
        'bounds': (100, 62, 816, 336),
        'frame': (44, 42, 806, 380),
        'boxes': (
            (120, 176, 214, 156, (0, 0, 0)),
            (336, 96, 282, 172, (0, 0, 0)),
            (594, 54, 236, 188, (0, 0, 0)),
        ),
        'back_callback': f'{COORDINATE_SPACE_CALLBACK_PREFIX}:east_eurasia_detail_menu',
        'change_action': 'northeast_asia_population_change',
        'save_root': 'nead_save',
    },
    'north_china_detail': {
        'title': 'North China',
        'population_labels': _NORTH_CHINA_POPULATION_LABELS,
        'layout': _NORTH_CHINA_POPULATION_LAYOUT,
        'bounds': (116, 86, 730, 368),
        'frame': (44, 42, 806, 380),
        'boxes': (
            (110, 142, 240, 176, (0, 0, 0)),
            (340, 126, 236, 206, (0, 0, 0)),
            (558, 72, 224, 292, (0, 0, 0)),
        ),
        'back_callback': f'{COORDINATE_SPACE_CALLBACK_PREFIX}:east_eurasia_detail_menu',
        'change_action': 'north_china_population_change',
        'save_root': 'nchd_save',
    },
    'south_china_detail': {
        'title': 'South China',
        'population_labels': _SOUTH_CHINA_POPULATION_LABELS,
        'layout': _SOUTH_CHINA_POPULATION_LAYOUT,
        'bounds': (116, 120, 802, 390),
        'frame': (44, 42, 806, 380),
        'boxes': (
            (452, 88, 206, 184, (0, 0, 0)),
            (612, 180, 204, 210, (0, 0, 0)),
            (108, 164, 384, 226, (0, 0, 0)),
        ),
        'back_callback': f'{COORDINATE_SPACE_CALLBACK_PREFIX}:east_eurasia_detail_menu',
        'change_action': 'south_china_population_change',
        'save_root': 'schd_save',
    },
    'siberia_inner_asia_detail': {
        'title': 'Siberia / Inner Asia',
        'population_labels': _SIBERIA_INNER_ASIA_POPULATION_LABELS,
        'layout': _SIBERIA_INNER_ASIA_POPULATION_LAYOUT,
        'bounds': (102, 68, 822, 370),
        'frame': (44, 42, 806, 380),
        'boxes': (
            (94, 96, 256, 210, (0, 0, 0)),
            (318, 156, 360, 236, (0, 0, 0)),
            (590, 52, 232, 194, (0, 0, 0)),
        ),
        'back_callback': f'{COORDINATE_SPACE_CALLBACK_PREFIX}:east_eurasia_detail_menu',
        'change_action': 'siberia_inner_asia_population_change',
        'save_root': 'siad_save',
    },
    'south_caucasus_detail': {
        'title': 'South Caucasus',
        'population_labels': _SOUTH_CAUCASUS_POPULATION_LABELS,
        'layout': _SOUTH_CAUCASUS_POPULATION_LAYOUT,
        'bounds': (92, 78, 764, 392),
        'frame': (44, 42, 806, 380),
        'boxes': (
            (84, 74, 254, 210, (0, 0, 0)),
            (252, 148, 320, 242, (0, 0, 0)),
            (560, 72, 224, 264, (0, 0, 0)),
        ),
        'back_callback': f'{COORDINATE_SPACE_CALLBACK_PREFIX}:south_caucasus_detail',
        'change_action': 'south_caucasus_population_change',
        'save_root': 'scd_save',
    },
    'steppe_fringe_detail': {
        'title': 'Steppe fringe',
        'population_labels': _STEPPE_FRINGE_POPULATION_LABELS,
        'layout': _STEPPE_FRINGE_POPULATION_LAYOUT,
        'bounds': (104, 86, 774, 366),
        'frame': (44, 42, 806, 380),
        'boxes': (
            (106, 82, 264, 136, (0, 0, 0)),
            (324, 116, 270, 226, (0, 0, 0)),
            (580, 118, 198, 256, (0, 0, 0)),
        ),
        'back_callback': f'{COORDINATE_SPACE_CALLBACK_PREFIX}:steppe_fringe_detail',
        'change_action': 'steppe_fringe_population_change',
        'save_root': 'sfd_save',
    },
}


_POPULATION_VIEW_GROUP_LABELS: dict[str, dict[str, tuple[str, ...]]] = {
    'ready_made_caucasus_steppe_all_populations': _CAUCASUS_STEPPE_REGION_LABELS,
    'ready_made_west_eurasia_all_populations': _WEST_EURASIA_ALL_POPULATION_GROUP_LABELS,
    'ready_made_europe_all_populations': _EUROPE_ALL_POPULATION_GROUP_LABELS,
    'ready_made_south_asia_all_populations': _SOUTH_ASIA_ALL_POPULATION_GROUP_LABELS,
    'ready_made_east_eurasia_all_populations': _EAST_EURASIA_ALL_POPULATION_GROUP_LABELS,
    'east_europe_detail': _EAST_EUROPE_DETAIL_REGION_LABELS,
    'north_europe_detail': _NORTH_EUROPE_DETAIL_REGION_LABELS,
    'south_europe_detail': _SOUTH_EUROPE_DETAIL_REGION_LABELS,
    'balkans_detail': _BALKANS_DETAIL_REGION_LABELS,
    'baltic_detail': _BALTIC_DETAIL_REGION_LABELS,
    'west_eurasia_europe_detail': _WEST_EURASIA_EUROPE_DETAIL_REGION_LABELS,
    'west_eurasia_caucasus_detail': _WEST_EURASIA_CAUCASUS_DETAIL_REGION_LABELS,
    'west_eurasia_anatolia_detail': _WEST_EURASIA_ANATOLIA_DETAIL_REGION_LABELS,
    'west_eurasia_levant_detail': _WEST_EURASIA_LEVANT_DETAIL_REGION_LABELS,
    'west_eurasia_mesopotamia_iran_detail': _WEST_EURASIA_MESO_IRAN_DETAIL_REGION_LABELS,
    'west_eurasia_steppe_detail': _WEST_EURASIA_STEPPE_DETAIL_REGION_LABELS,
    'northwest_south_asia_detail': _NORTHWEST_SOUTH_ASIA_DETAIL_REGION_LABELS,
    'gangetic_north_india_detail': _GANGETIC_NORTH_INDIA_DETAIL_REGION_LABELS,
    'west_india_detail': _WEST_INDIA_DETAIL_REGION_LABELS,
    'south_india_detail': _SOUTH_INDIA_DETAIL_REGION_LABELS,
    'east_india_bengal_detail': _EAST_INDIA_BENGAL_DETAIL_REGION_LABELS,
    'north_caucasus_detail': _NORTH_CAUCASUS_DETAIL_REGION_LABELS,
    'south_caucasus_detail': _SOUTH_CAUCASUS_DETAIL_REGION_LABELS,
    'steppe_fringe_detail': _STEPPE_FRINGE_DETAIL_REGION_LABELS,
    'northeast_asia_detail': _NORTHEAST_ASIA_DETAIL_REGION_LABELS,
    'north_china_detail': _NORTH_CHINA_DETAIL_REGION_LABELS,
    'south_china_detail': _SOUTH_CHINA_DETAIL_REGION_LABELS,
    'siberia_inner_asia_detail': _SIBERIA_INNER_ASIA_DETAIL_REGION_LABELS,
}


def _population_view_group_map(view_action: str) -> dict[str, str]:
    groups = _POPULATION_VIEW_GROUP_LABELS.get(view_action, {})
    mapped: dict[str, str] = {}
    for group_name, labels in groups.items():
        for label in labels:
            mapped.setdefault(label, group_name)
    return mapped


def _my_data_store(context: ContextTypes.DEFAULT_TYPE) -> MyDataStore:
    return context.application.bot_data['my_data_store']


def _coordinate_space_report_store(context: ContextTypes.DEFAULT_TYPE) -> CoordinateSpaceReportStore:
    store = context.application.bot_data.get('coordinate_space_report_store')
    if isinstance(store, CoordinateSpaceReportStore):
        return store
    store = CoordinateSpaceReportStore(_my_data_store(context).root_dir.parent / 'coordinate_space' / 'reports')
    context.application.bot_data['coordinate_space_report_store'] = store
    return store


def _set_active_menu_message(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int, message_id: int) -> None:
    store = context.application.bot_data.get('main_menu_store')
    if store is not None and hasattr(store, 'set'):
        store.set(chat_id, user_id, message_id)


def _is_photo_message(message) -> bool:
    return bool(getattr(message, 'photo', None))


async def _show_menu_from_photo_message(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    chat_id: int,
    user_id: int,
    text: str,
    reply_markup,
) -> None:
    sent = await message.reply_text(text, reply_markup=reply_markup, parse_mode="HTML", do_quote=False)
    _set_active_menu_message(context, chat_id, user_id, sent.message_id)
    try:
        await message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass


def coordinate_space_text(*, lang: str = 'ru') -> str:
    return "\n".join([
        "🧭 Coordinates",
        "",
        _copy(
            lang,
            'Готовые региональные пространства\nдля сравнения G25-профилей.',
            'Ready-made regional spaces\nfor comparing G25 profiles.',
        ),
    ])


def ready_made_spaces_text(*, lang: str = 'ru') -> str:
    return coordinate_space_text(lang=lang)


def _mode_screen_text(title: str, *, lang: str = 'ru') -> str:
    return f"{_visible_space_title(title)}\n\n{_copy(lang, 'Выберите режим', 'Choose a mode')}"


def caucasus_detail_text(*, lang: str = 'ru') -> str:
    return _mode_screen_text('Caucasus / Steppe', lang=lang)


def caucasus_branch_mode_text(title: str, *, lang: str = 'ru') -> str:
    return _mode_screen_text(title, lang=lang)


def east_eurasia_detail_text(*, lang: str = 'ru') -> str:
    return _mode_screen_text('East Eurasia', lang=lang)


def south_asia_detail_text(*, lang: str = 'ru') -> str:
    return _mode_screen_text('South Asia', lang=lang)


def west_eurasia_detail_text(*, lang: str = 'ru') -> str:
    return _mode_screen_text('West Eurasia', lang=lang)


def europe_detail_text(*, lang: str = 'ru') -> str:
    return _mode_screen_text('Europe', lang=lang)


def coordinate_space_stub_text(title: str, *, lang: str = 'ru') -> str:
    return f"{_visible_space_title(title)}\n\n{_copy(lang, 'Раздел в разработке.', 'This section is in development.')}"


def global_sample_picker_text(
    items: list[tuple[SampleAsset, CoordinateAsset]],
    *,
    source: str | None = None,
    lang: str = 'ru',
) -> str:
    return _coordinate_space_target_picker_text('Global', items, source=source, lang=lang)


def west_eurasia_sample_picker_text(
    items: list[tuple[SampleAsset, CoordinateAsset]],
    *,
    source: str | None = None,
    lang: str = 'ru',
) -> str:
    return _coordinate_space_target_picker_text('West Eurasia', items, source=source, lang=lang)


def global_result_text(sample: SampleAsset, *, region_name: str) -> str:
    return (
        f'Sample: {sample.display_name}\n'
        f'Closest region: {region_name}'
    )


def west_eurasia_result_text(sample: SampleAsset, *, region_name: str) -> str:
    return (
        f'Sample: {sample.display_name}\n'
        f'Closest region: {region_name}'
    )


def configured_space_sample_picker_text(
    title: str,
    items: list[tuple[SampleAsset, CoordinateAsset]],
    *,
    source: str | None = None,
    lang: str = 'ru',
) -> str:
    return _coordinate_space_target_picker_text(title, items, source=source, lang=lang)


def configured_space_result_text(sample: SampleAsset, *, region_name: str) -> str:
    return (
        f'Sample: {sample.display_name}\n'
        f'Closest region: {region_name}'
    )


def caucasus_steppe_all_populations_result_text(
    sample: SampleAsset,
    *,
    top_populations: tuple[str, ...],
) -> str:
    lines = [f'Sample: {sample.display_name}']
    if top_populations:
        lines.append(f'Top populations: {", ".join(top_populations)}')
    return '\n'.join(lines)


def ready_made_all_populations_result_text(
    sample: SampleAsset,
    *,
    top_populations: tuple[str, ...],
) -> str:
    lines = [f'Sample: {sample.display_name}']
    if top_populations:
        lines.append(f'Top populations: {", ".join(top_populations)}')
    return '\n'.join(lines)


def caucasus_detail_result_text(
    sample: SampleAsset,
    *,
    region_name: str,
    top_populations: tuple[str, ...],
) -> str:
    return (
        f'Sample: {sample.display_name}\n'
        f'Closest cluster: {region_name}\n'
        f'Top populations: {", ".join(top_populations)}'
    )


def north_caucasus_detail_result_text(
    sample: SampleAsset,
    *,
    region_name: str,
    top_populations: tuple[str, ...],
) -> str:
    return caucasus_detail_result_text(sample, region_name=region_name, top_populations=top_populations)


def build_coordinate_space_keyboard(*, lang: str = 'ru') -> InlineKeyboardMarkup:
    return build_ready_made_spaces_keyboard(lang=lang)


def build_ready_made_spaces_keyboard(*, lang: str = 'ru') -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton('🌍 Global', callback_data=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:ready_made_global')],
            [InlineKeyboardButton('🧭 West Eurasia', callback_data=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:ready_made_west_eurasia')],
            [InlineKeyboardButton('🇪🇺 Europe', callback_data=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:ready_made_europe')],
            [InlineKeyboardButton('⛰ Caucasus / Steppe', callback_data=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:ready_made_caucasus_steppe')],
            [InlineKeyboardButton('🌿 South Asia', callback_data=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:ready_made_south_asia')],
            [InlineKeyboardButton('🌏 East Eurasia', callback_data=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:ready_made_east_eurasia')],
            _back_cancel_row('main:root', lang=lang),
        ]
    )


def build_coordinate_space_stub_keyboard(*, back_callback: str, lang: str = 'ru') -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [_back_cancel_row(back_callback, lang=lang)]
    )


def build_north_caucasus_detail_sample_picker_keyboard(
    items: list[tuple[SampleAsset, CoordinateAsset]],
    *,
    mode: str = 'clusters',
    source: str | None = None,
) -> InlineKeyboardMarkup:
    return build_caucasus_detail_sample_picker_keyboard('north_caucasus_detail', items, mode=mode, source=source)


def build_caucasus_detail_sample_picker_keyboard(
    detail_action: str,
    items: list[tuple[SampleAsset, CoordinateAsset]],
    *,
    mode: str = 'clusters',
    lang: str = 'ru',
    source: str | None = None,
) -> InlineKeyboardMarkup:
    branch = _CAUCASUS_DETAIL_BRANCH_CONFIGS[detail_action]
    root_action = branch['population_sample_root'] if mode == 'populations' else branch['sample_root']
    return _build_coordinate_space_target_picker_keyboard(root_action, items, source=source, lang=lang)


def build_caucasus_steppe_population_sample_picker_keyboard(
    items: list[tuple[SampleAsset, CoordinateAsset]],
    *,
    source: str | None = None,
    lang: str = 'ru',
) -> InlineKeyboardMarkup:
    return _build_coordinate_space_target_picker_keyboard('csp_sample', items, source=source, lang=lang)


def build_caucasus_detail_keyboard(*, lang: str = 'ru') -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(_whole_region_label(lang), callback_data=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:caucasus_steppe_region_mode')],
            [InlineKeyboardButton(_all_populations_label(lang), callback_data=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:caucasus_steppe_population_mode')],
            [InlineKeyboardButton(_visible_space_title('North Caucasus'), callback_data=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:north_caucasus_detail')],
            [InlineKeyboardButton(_visible_space_title('South Caucasus'), callback_data=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:south_caucasus_detail')],
            [InlineKeyboardButton(_visible_space_title('Steppe fringe'), callback_data=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:steppe_fringe_detail')],
            [
                InlineKeyboardButton(_back_label(lang), callback_data=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:ready_made_spaces'),
                InlineKeyboardButton(_cancel_label(lang), callback_data=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:cancel'),
            ],
        ]
    )


def build_caucasus_branch_mode_keyboard(detail_action: str, *, lang: str = 'ru') -> InlineKeyboardMarkup:
    branch = _CAUCASUS_DETAIL_BRANCH_CONFIGS[detail_action]
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(_copy(lang, 'По региону', 'By region'), callback_data=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:{branch["region_mode_action"]}')],
            [InlineKeyboardButton(_copy(lang, 'По популяциям', 'By populations'), callback_data=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:{branch["population_mode_action"]}')],
            [
                InlineKeyboardButton(_back_label(lang), callback_data=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:caucasus_detail_menu'),
                InlineKeyboardButton(_cancel_label(lang), callback_data=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:cancel'),
            ],
        ]
    )


def build_north_caucasus_detail_result_keyboard(sample_id: str, *, mode: str = 'clusters') -> InlineKeyboardMarkup:
    return build_caucasus_detail_result_keyboard('north_caucasus_detail', sample_id, mode=mode)


def build_caucasus_detail_result_keyboard(
    detail_action: str,
    sample_id: str,
    *,
    mode: str = 'clusters',
    source: str | None = None,
) -> InlineKeyboardMarkup:
    branch = _CAUCASUS_DETAIL_BRANCH_CONFIGS[detail_action]
    sample_root = branch['population_sample_root'] if mode == 'populations' else branch['sample_root']
    back_callback = _target_list_back_callback(sample_root, sample_id, source=source)
    save_root = f'{branch["save_root"]}p' if mode == 'populations' else branch['save_root']
    if mode == 'populations':
        return InlineKeyboardMarkup(
            [
                [InlineKeyboardButton(_save_report_label(), callback_data=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:{save_root}:{sample_id}')],
                [InlineKeyboardButton(_change_g25_label(), callback_data=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:{branch["population_change_action"]}')],
                _back_cancel_row(back_callback),
            ]
        )
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(_save_report_label(), callback_data=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:{save_root}:{sample_id}')],
            [InlineKeyboardButton(_change_g25_label(), callback_data=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:{branch["change_action"]}')],
            _back_cancel_row(back_callback),
        ]
    )


def build_caucasus_steppe_all_populations_result_keyboard(sample_id: str, *, source: str | None = None) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(_save_report_label(), callback_data=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:csallp_save:{sample_id}')],
            [InlineKeyboardButton(_change_g25_label(), callback_data=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:caucasus_steppe_population_change')],
            _back_cancel_row(_target_list_back_callback('csp_sample', sample_id, source=source)),
        ]
    )


def _pick_sample_g25_coordinate(store: MyDataStore, user_id: int, sample_id: str) -> CoordinateAsset | None:
    coordinates = [
        item
        for item in store.list_sample_coordinates(user_id, sample_id)
        if item.coordinate_type.strip().lower() == 'g25'
    ]
    if not coordinates:
        return None
    return max(coordinates, key=lambda item: (item.created_at, item.asset_id))


_G25_LIBRARY_SAMPLE_PREFIX = 'g:'
_G25_LIBRARY_LEGACY_SAMPLE_PREFIX = 'g25lib:'


def _g25_library_sample_id(coordinate_id: str) -> str:
    return f'{_G25_LIBRARY_SAMPLE_PREFIX}{coordinate_id}'


def _sample_from_g25_library_coordinate(coordinate: CoordinateAsset) -> SampleAsset:
    return SampleAsset(
        asset_id=_g25_library_sample_id(coordinate.asset_id),
        display_name=coordinate.display_name,
        raw_file_id='',
        coordinate_ids=[coordinate.asset_id],
        created_at=coordinate.created_at,
    )


def _resolve_space_target(store: MyDataStore, user_id: int, sample_id: str) -> tuple[SampleAsset | None, CoordinateAsset | None]:
    if sample_id.startswith(_G25_LIBRARY_SAMPLE_PREFIX):
        coordinate_id = sample_id[len(_G25_LIBRARY_SAMPLE_PREFIX):]
        coordinate = store.get_coordinate(user_id, coordinate_id)
        if coordinate is None or coordinate.coordinate_type.strip().lower() != 'g25' or not coordinate.g25_line.strip():
            return None, None
        return _sample_from_g25_library_coordinate(coordinate), coordinate
    if sample_id.startswith(_G25_LIBRARY_LEGACY_SAMPLE_PREFIX):
        coordinate_id = sample_id[len(_G25_LIBRARY_LEGACY_SAMPLE_PREFIX):]
        coordinate = store.get_coordinate(user_id, coordinate_id)
        if coordinate is None or coordinate.coordinate_type.strip().lower() != 'g25' or not coordinate.g25_line.strip():
            return None, None
        return _sample_from_g25_library_coordinate(coordinate), coordinate

    sample = store.get_sample(user_id, sample_id)
    coordinate = _pick_sample_g25_coordinate(store, user_id, sample_id)
    return sample, coordinate


def _sort_ready_target_items(items: list[tuple[SampleAsset, CoordinateAsset]]) -> list[tuple[SampleAsset, CoordinateAsset]]:
    def sort_key(item: tuple[SampleAsset, CoordinateAsset]) -> tuple[str, str]:
        sample, coordinate = item
        return coordinate.created_at or sample.created_at, sample.asset_id

    return sorted(items, key=sort_key, reverse=True)


def _attached_g25_coordinate_ids(store: MyDataStore, user_id: int) -> set[str]:
    attached: set[str] = set()
    for sample in store.list_samples(user_id):
        attached.update(str(value) for value in sample.coordinate_ids if str(value))
    return attached


def _list_sample_ready_samples(store: MyDataStore, user_id: int) -> list[tuple[SampleAsset, CoordinateAsset]]:
    sample_items: list[tuple[SampleAsset, CoordinateAsset]] = []
    for sample in store.list_samples(user_id):
        coordinate = _pick_sample_g25_coordinate(store, user_id, sample.asset_id)
        if coordinate is not None:
            sample_items.append((sample, coordinate))
    return _sort_ready_target_items(sample_items)


def _list_g25_library_ready_samples(store: MyDataStore, user_id: int) -> list[tuple[SampleAsset, CoordinateAsset]]:
    library_items: list[tuple[SampleAsset, CoordinateAsset]] = []
    attached_coordinate_ids = _attached_g25_coordinate_ids(store, user_id)
    for coordinate in store.list_coordinates(user_id):
        if coordinate.coordinate_type.strip().lower() != 'g25' or not coordinate.g25_line.strip():
            continue
        if coordinate.asset_id in attached_coordinate_ids:
            continue
        library_items.append((_sample_from_g25_library_coordinate(coordinate), coordinate))
    return _sort_ready_target_items(library_items)


def _list_ready_samples_for_source(
    store: MyDataStore,
    user_id: int,
    source: str | None,
) -> list[tuple[SampleAsset, CoordinateAsset]]:
    if source == 'samples':
        return _list_sample_ready_samples(store, user_id)
    if source == 'other':
        return _list_g25_library_ready_samples(store, user_id)
    return _list_global_ready_samples(store, user_id)


def _list_global_ready_samples(store: MyDataStore, user_id: int) -> list[tuple[SampleAsset, CoordinateAsset]]:
    return _list_g25_library_ready_samples(store, user_id) + _list_sample_ready_samples(store, user_id)


def _coordinate_space_picker_spec(sample_root: str) -> dict[str, str] | None:
    if sample_root == 'global_sample':
        return {
            'title': 'Global',
            'back_callback': f'{COORDINATE_SPACE_CALLBACK_PREFIX}:ready_made_global',
        }
    if sample_root == 'we_sample':
        return {
            'title': 'West Eurasia',
            'back_callback': f'{COORDINATE_SPACE_CALLBACK_PREFIX}:ready_made_west_eurasia',
        }
    if sample_root == 'csp_sample':
        return {
            'title': 'Caucasus / Steppe',
            'back_callback': f'{COORDINATE_SPACE_CALLBACK_PREFIX}:caucasus_detail_menu',
        }

    regional_action = _REGIONAL_SAMPLE_ROOT_ACTIONS.get(sample_root)
    if regional_action is not None:
        return {
            'title': str(_REGIONAL_READY_MADE_SPACES[regional_action]['title']),
            'back_callback': f'{COORDINATE_SPACE_CALLBACK_PREFIX}:{regional_action}',
        }

    all_population_action = _READY_MADE_ALL_POPULATION_SAMPLE_ROOT_ACTIONS.get(sample_root)
    if all_population_action is not None:
        flow = _READY_MADE_ALL_POPULATION_FLOWS[all_population_action]
        return {
            'title': flow['title'],
            'back_callback': flow['back_callback'],
        }

    for detail_action, branch in {
        **_EUROPE_DETAIL_BRANCH_CONFIGS,
        **_WEST_EURASIA_DETAIL_BRANCH_CONFIGS,
        **_CAUCASUS_DETAIL_BRANCH_CONFIGS,
        **_SOUTH_ASIA_DETAIL_BRANCH_CONFIGS,
        **_EAST_EURASIA_DETAIL_BRANCH_CONFIGS,
    }.items():
        if sample_root in {branch['sample_root'], branch['population_sample_root']}:
            return {
                'title': branch['title'],
                'back_callback': f'{COORDINATE_SPACE_CALLBACK_PREFIX}:{detail_action}',
            }
    return None


def _coordinate_space_target_picker_text(
    title: str,
    items: list[tuple[SampleAsset, CoordinateAsset]],
    *,
    source: str | None = None,
    lang: str = 'ru',
) -> str:
    visible_title = _visible_space_title(title)
    if source is None:
        lines = [
            visible_title,
            '',
            _copy(lang, 'Выберите источник G25-профиля.', 'Choose a G25 profile source.'),
        ]
        if not items:
            lines.extend([
                '',
                _copy(lang, 'Пока нет G25-профилей. Сохраните их в My DNA или получите из raw через My DNA -> Добавить данные.', 'There are no G25 profiles yet. Save them in My DNA or extract them from raw through My DNA -> Add data.'),
            ])
        return '\n'.join(lines)

    lines = [
        visible_title,
        '',
        _target_source_label(source, lang),
        '',
    ]
    if items:
        lines.append(_copy(lang, 'Выберите G25-профиль.', 'Choose a G25 profile.'))
    elif source == 'samples':
        lines.append(_copy(lang, 'Нет samples с G25-координатами.', 'There are no samples with G25 coordinates.'))
    else:
        lines.append(_copy(lang, 'Нет отдельных записей в «G25-профили».', 'There are no standalone records in G25 profiles.'))
    return '\n'.join(lines)


def _coordinate_space_target_picker_text_for_root(
    sample_root: str,
    items: list[tuple[SampleAsset, CoordinateAsset]],
    *,
    source: str | None = None,
    lang: str = 'ru',
) -> str:
    spec = _coordinate_space_picker_spec(sample_root)
    title = spec['title'] if spec is not None else 'Coordinates'
    return _coordinate_space_target_picker_text(title, items, source=source, lang=lang)


def _build_coordinate_space_target_picker_keyboard(
    sample_root: str,
    items: list[tuple[SampleAsset, CoordinateAsset]],
    *,
    source: str | None = None,
    lang: str = 'ru',
) -> InlineKeyboardMarkup:
    spec = _coordinate_space_picker_spec(sample_root) or {
        'back_callback': f'{COORDINATE_SPACE_CALLBACK_PREFIX}:ready_made_spaces',
    }
    if source is None:
        return InlineKeyboardMarkup(
            [
                [InlineKeyboardButton(_samples_source_label(lang), callback_data=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:picksrc:{sample_root}:samples')],
                [InlineKeyboardButton(_other_g25_source_label(lang), callback_data=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:picksrc:{sample_root}:other')],
                [
                    InlineKeyboardButton(_back_label(lang), callback_data=spec['back_callback']),
                    InlineKeyboardButton(_cancel_label(lang), callback_data=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:cancel'),
                ],
            ]
        )

    rows: list[list[InlineKeyboardButton]] = []
    for index, (sample, _) in enumerate(items[:_COORDINATE_SPACE_SAMPLE_PICKER_LIMIT], start=1):
        rows.append(
            [InlineKeyboardButton(f'{index}. {sample.display_name}', callback_data=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:{sample_root}:{sample.asset_id}')]
        )
    rows.append(
        [
            InlineKeyboardButton(_back_label(lang), callback_data=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:picksrc:{sample_root}'),
            InlineKeyboardButton(_cancel_label(lang), callback_data=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:cancel'),
        ]
    )
    return InlineKeyboardMarkup(rows)


def _ready_made_all_population_save_actions() -> dict[str, str]:
    return {
        str(config['save_root']): view_action
        for view_action, config in _POPULATION_VIEW_CONFIGS.items()
        if view_action.startswith('ready_made_')
    }


def _rank_ready_made_all_population_view(view_action: str, g25_line: str) -> tuple[str, ...]:
    rankers = {
        'ready_made_west_eurasia_all_populations': _rank_west_eurasia_all_populations,
        'ready_made_europe_all_populations': _rank_europe_all_populations,
        'ready_made_south_asia_all_populations': _rank_south_asia_all_populations,
        'ready_made_east_eurasia_all_populations': _rank_east_eurasia_all_populations,
        'ready_made_caucasus_steppe_all_populations': _rank_caucasus_steppe_all_populations,
    }
    return rankers[view_action](g25_line)


def _detail_region_and_populations(detail_action: str, g25_line: str) -> tuple[str, tuple[str, ...]]:
    if detail_action == 'north_caucasus_detail':
        return _classify_north_caucasus_region(g25_line), _rank_north_caucasus_populations(g25_line)
    if detail_action == 'south_caucasus_detail':
        return _classify_south_caucasus_region(g25_line), _rank_south_caucasus_populations(g25_line)
    if detail_action == 'steppe_fringe_detail':
        return _classify_steppe_fringe_region(g25_line), _rank_steppe_fringe_populations(g25_line)

    if detail_action in _EUROPE_DETAIL_BRANCH_CONFIGS:
        rankers = {
            'east_europe_detail': _rank_east_europe_populations,
            'north_europe_detail': _rank_north_europe_populations,
            'south_europe_detail': _rank_south_europe_populations,
            'balkans_detail': _rank_balkans_populations,
            'baltic_detail': _rank_baltic_populations,
        }
        return _classify_configured_space_region(detail_action, g25_line), rankers[detail_action](g25_line)

    if detail_action in _WEST_EURASIA_DETAIL_BRANCH_CONFIGS:
        classifiers = {
            'west_eurasia_europe_detail': _classify_west_eurasia_europe_region,
            'west_eurasia_caucasus_detail': _classify_west_eurasia_caucasus_region,
            'west_eurasia_anatolia_detail': _classify_west_eurasia_anatolia_region,
            'west_eurasia_levant_detail': _classify_west_eurasia_levant_region,
            'west_eurasia_mesopotamia_iran_detail': _classify_west_eurasia_mesopotamia_iran_region,
            'west_eurasia_steppe_detail': _classify_west_eurasia_steppe_region,
        }
        rankers = {
            'west_eurasia_europe_detail': _rank_west_eurasia_europe_populations,
            'west_eurasia_caucasus_detail': _rank_west_eurasia_caucasus_populations,
            'west_eurasia_anatolia_detail': _rank_west_eurasia_anatolia_populations,
            'west_eurasia_levant_detail': _rank_west_eurasia_levant_populations,
            'west_eurasia_mesopotamia_iran_detail': _rank_west_eurasia_mesopotamia_iran_populations,
            'west_eurasia_steppe_detail': _rank_west_eurasia_steppe_populations,
        }
        return classifiers[detail_action](g25_line), rankers[detail_action](g25_line)

    if detail_action in _EAST_EURASIA_DETAIL_BRANCH_CONFIGS:
        classifiers = {
            'northeast_asia_detail': _classify_northeast_asia_region,
            'north_china_detail': _classify_north_china_region,
            'south_china_detail': _classify_south_china_region,
            'siberia_inner_asia_detail': _classify_siberia_inner_asia_region,
        }
        rankers = {
            'northeast_asia_detail': _rank_northeast_asia_populations,
            'north_china_detail': _rank_north_china_populations,
            'south_china_detail': _rank_south_china_populations,
            'siberia_inner_asia_detail': _rank_siberia_inner_asia_populations,
        }
        return classifiers[detail_action](g25_line), rankers[detail_action](g25_line)

    classifiers = {
        'northwest_south_asia_detail': _classify_northwest_south_asia_region,
        'gangetic_north_india_detail': _classify_gangetic_north_india_region,
        'west_india_detail': _classify_west_india_region,
        'south_india_detail': _classify_south_india_region,
        'east_india_bengal_detail': _classify_east_india_bengal_region,
    }
    rankers = {
        'northwest_south_asia_detail': _rank_northwest_south_asia_populations,
        'gangetic_north_india_detail': _rank_gangetic_north_india_populations,
        'west_india_detail': _rank_west_india_populations,
        'south_india_detail': _rank_south_india_populations,
        'east_india_bengal_detail': _rank_east_india_bengal_populations,
    }
    return classifiers[detail_action](g25_line), rankers[detail_action](g25_line)


def _coordinate_space_report_caption(
    sample: SampleAsset,
    g25_line: str,
    *,
    title: str,
    mode: str,
    preset_id: str,
) -> str:
    caption_mode = 'population' if mode in {'all_populations', 'populations'} else 'region'
    group_map = None
    label_formatter = None
    if caption_mode == 'population':
        profiles = _population_view_profiles()[preset_id]
        group_map = _population_view_group_map(preset_id)
        label_formatter = _population_label_text
    elif preset_id == 'global':
        profiles = _ready_made_g25_profiles()['global']
    elif preset_id == 'ready_made_west_eurasia':
        profiles = _ready_made_g25_profiles()['west_eurasia']
    else:
        profiles = _ready_made_g25_profiles()[preset_id]
    return _coordinate_space_photo_caption(
        sample,
        g25_line,
        profiles,
        space_title=title,
        mode=caption_mode,
        group_map=group_map,
        label_formatter=label_formatter,
    )


def _render_coordinate_space_report_image(
    output_path: Path,
    *,
    preset_id: str,
    mode: str,
    g25_line: str,
    summary_lines: list[str],
) -> None:
    render_summary = tuple(summary_lines)
    if preset_id == 'global':
        _render_global_visualization(
            output_path,
            sample_point=_project_global_sample_position(g25_line),
            g25_line=g25_line,
            summary_lines=render_summary,
        )
        return
    if preset_id == 'ready_made_west_eurasia':
        _render_west_eurasia_visualization(
            output_path,
            sample_point=_project_west_eurasia_sample_position(g25_line),
            g25_line=g25_line,
            summary_lines=render_summary,
        )
        return
    if mode in {'all_populations', 'populations'}:
        _render_population_view_visualization(
            preset_id,
            output_path,
            sample_point=_project_population_view_position(preset_id, g25_line),
            g25_line=g25_line,
            summary_lines=render_summary,
        )
        return
    _render_configured_space_visualization(
        output_path,
        space_action=preset_id,
        sample_point=_project_configured_space_position(preset_id, g25_line),
        g25_line=g25_line,
        summary_lines=render_summary,
    )


def _create_coordinate_space_report_image(
    *,
    preset_id: str,
    mode: str,
    g25_line: str,
    summary_lines: list[str],
) -> Path | None:
    image_path = _create_global_visualization_path()
    try:
        _render_coordinate_space_report_image(
            image_path,
            preset_id=preset_id,
            mode=mode,
            g25_line=g25_line,
            summary_lines=summary_lines,
        )
        return image_path
    except Exception:
        logger.exception("Could not render Coordinate Space report PNG artifact")
        try:
            image_path.unlink()
        except FileNotFoundError:
            pass
        return None


def _save_coordinate_space_result(
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    sample_id: str,
    *,
    title: str,
    mode: str,
    preset_id: str,
    summary_lines: list[str],
    top_populations: tuple[str, ...] = (),
    config_snapshot: dict[str, object] | None = None,
) -> bool:
    sample, coordinate = _resolve_space_target(_my_data_store(context), user_id, sample_id)
    if sample is None or coordinate is None:
        return False
    image_path = _create_coordinate_space_report_image(
        preset_id=preset_id,
        mode=mode,
        g25_line=coordinate.g25_line,
        summary_lines=summary_lines,
    )
    caption = _coordinate_space_report_caption(
        sample,
        coordinate.g25_line,
        title=title,
        mode=mode,
        preset_id=preset_id,
    )
    try:
        _coordinate_space_report_store(context).save_result(
            user_id,
            sample_id=sample.asset_id,
            coordinate_id=coordinate.asset_id,
            title=title,
            mode=mode,
            coordinate_system='G25',
            session_id='ready_made',
            preset_id=preset_id,
            summary_lines=summary_lines,
            top_populations=list(top_populations),
            config_snapshot=config_snapshot or {},
            image_source_path=image_path,
            caption=caption,
        )
    finally:
        if image_path is not None:
            try:
                image_path.unlink()
            except FileNotFoundError:
                pass
    return True


async def _handle_coordinate_space_save(
    query,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    root_action: str,
    sample_id: str,
    *,
    lang: str = 'ru',
) -> bool:
    sample, coordinate = _resolve_space_target(_my_data_store(context), user_id, sample_id)
    if sample is None or coordinate is None:
        await query.answer(_copy(lang, 'Target больше не найден.', 'Target is no longer available.'), show_alert=True)
        return True

    title = ''
    mode = ''
    preset_id = ''
    summary_lines: list[str] = []
    top_populations: tuple[str, ...] = ()
    config_snapshot: dict[str, object] = {}

    if root_action == 'global_save':
        title = 'Global'
        mode = 'region'
        preset_id = 'global'
        summary_lines = global_result_text(sample, region_name=_classify_global_region(coordinate.g25_line)).splitlines()
    elif root_action == 'west_eurasia_save':
        title = 'West Eurasia'
        mode = 'region'
        preset_id = 'ready_made_west_eurasia'
        summary_lines = west_eurasia_result_text(sample, region_name=_classify_west_eurasia_region(coordinate.g25_line)).splitlines()
    elif root_action in _REGIONAL_SAVE_ROOT_ACTIONS:
        preset_id = _REGIONAL_SAVE_ROOT_ACTIONS[root_action]
        title = str(_REGIONAL_READY_MADE_SPACES[preset_id]['title'])
        mode = 'region'
        region_name = _classify_configured_space_region(preset_id, coordinate.g25_line)
        summary_lines = configured_space_result_text(sample, region_name=region_name).splitlines()
        config_snapshot = {'space_action': preset_id}
    elif root_action in _ready_made_all_population_save_actions():
        preset_id = _ready_made_all_population_save_actions()[root_action]
        title = str(_POPULATION_VIEW_CONFIGS[preset_id]['title'])
        mode = 'all_populations'
        top_populations = _rank_ready_made_all_population_view(preset_id, coordinate.g25_line)
        summary_lines = ready_made_all_populations_result_text(sample, top_populations=top_populations).splitlines()
        config_snapshot = {'view_action': preset_id}
    elif root_action in _DETAIL_SAVE_ROOT_ACTIONS or root_action in _DETAIL_POPULATION_SAVE_ROOT_ACTIONS:
        is_population_mode = root_action in _DETAIL_POPULATION_SAVE_ROOT_ACTIONS
        preset_id = (
            _DETAIL_POPULATION_SAVE_ROOT_ACTIONS[root_action]
            if is_population_mode
            else _DETAIL_SAVE_ROOT_ACTIONS[root_action]
        )
        title = str(_DETAIL_CONFIGURED_SPACES[preset_id]['title'])
        mode = 'populations' if is_population_mode else 'region'
        region_name, top_populations = _detail_region_and_populations(preset_id, coordinate.g25_line)
        summary_lines = caucasus_detail_result_text(sample, region_name=region_name, top_populations=top_populations).splitlines()
        config_snapshot = {'detail_action': preset_id}
    else:
        return False

    saved = _save_coordinate_space_result(
        context,
        user_id,
        sample.asset_id,
        title=title,
        mode=mode,
        preset_id=preset_id,
        summary_lines=summary_lines,
        top_populations=top_populations,
        config_snapshot=config_snapshot,
    )
    if not saved:
        await query.answer(_copy(lang, 'Не удалось сохранить report.', 'Could not save the report.'), show_alert=True)
        return True
    await query.answer(_copy(lang, '✅ Отчёт сохранён в My DNA.', '✅ Report saved to My DNA.'), show_alert=True)
    return True


@lru_cache(maxsize=1)
def _load_modern_population_averages() -> dict[str, tuple[float, ...]]:
    return coordinate_g25_summary.load_modern_population_map()


def _build_centroid(
    populations: dict[str, tuple[float, ...]],
    *,
    region_name: str,
    labels: tuple[str, ...],
) -> tuple[float, ...]:
    return coordinate_g25_summary.build_centroid(populations, region_name=region_name, labels=labels)


@lru_cache(maxsize=1)
def _north_caucasus_population_profiles() -> dict[str, tuple[float, ...]]:
    return _population_view_profiles()['north_caucasus_detail']


@lru_cache(maxsize=1)
def _population_view_profiles() -> dict[str, dict[str, tuple[float, ...]]]:
    populations = _load_modern_population_averages()
    return {
        view_action: {
            label: populations[label]
            for label in config['population_labels']
            if label in populations
        }
        for view_action, config in _POPULATION_VIEW_CONFIGS.items()
    }


def _rank_north_caucasus_populations(g25_line: str, *, limit: int = 3) -> tuple[str, ...]:
    return _rank_population_view_labels('north_caucasus_detail', g25_line, limit=limit)


def _rank_south_caucasus_populations(g25_line: str, *, limit: int = 3) -> tuple[str, ...]:
    return _rank_population_view_labels('south_caucasus_detail', g25_line, limit=limit)


def _rank_steppe_fringe_populations(g25_line: str, *, limit: int = 3) -> tuple[str, ...]:
    return _rank_population_view_labels('steppe_fringe_detail', g25_line, limit=limit)


def _rank_caucasus_steppe_all_populations(g25_line: str, *, limit: int = 3) -> tuple[str, ...]:
    return _rank_population_view_labels('ready_made_caucasus_steppe_all_populations', g25_line, limit=limit)


def _rank_west_eurasia_all_populations(g25_line: str, *, limit: int = 3) -> tuple[str, ...]:
    return _rank_population_view_labels('ready_made_west_eurasia_all_populations', g25_line, limit=limit)


def _rank_europe_all_populations(g25_line: str, *, limit: int = 3) -> tuple[str, ...]:
    return _rank_population_view_labels('ready_made_europe_all_populations', g25_line, limit=limit)


def _rank_south_asia_all_populations(g25_line: str, *, limit: int = 3) -> tuple[str, ...]:
    return _rank_population_view_labels('ready_made_south_asia_all_populations', g25_line, limit=limit)


def _rank_east_eurasia_all_populations(g25_line: str, *, limit: int = 3) -> tuple[str, ...]:
    return _rank_population_view_labels('ready_made_east_eurasia_all_populations', g25_line, limit=limit)


def _rank_northeast_asia_populations(g25_line: str, *, limit: int = 3) -> tuple[str, ...]:
    return _rank_population_view_labels('northeast_asia_detail', g25_line, limit=limit)


def _rank_north_china_populations(g25_line: str, *, limit: int = 3) -> tuple[str, ...]:
    return _rank_population_view_labels('north_china_detail', g25_line, limit=limit)


def _rank_south_china_populations(g25_line: str, *, limit: int = 3) -> tuple[str, ...]:
    return _rank_population_view_labels('south_china_detail', g25_line, limit=limit)


def _rank_siberia_inner_asia_populations(g25_line: str, *, limit: int = 3) -> tuple[str, ...]:
    return _rank_population_view_labels('siberia_inner_asia_detail', g25_line, limit=limit)


def _rank_northwest_south_asia_populations(g25_line: str, *, limit: int = 3) -> tuple[str, ...]:
    return _rank_population_view_labels('northwest_south_asia_detail', g25_line, limit=limit)


def _rank_gangetic_north_india_populations(g25_line: str, *, limit: int = 3) -> tuple[str, ...]:
    return _rank_population_view_labels('gangetic_north_india_detail', g25_line, limit=limit)


def _rank_west_india_populations(g25_line: str, *, limit: int = 3) -> tuple[str, ...]:
    return _rank_population_view_labels('west_india_detail', g25_line, limit=limit)


def _rank_south_india_populations(g25_line: str, *, limit: int = 3) -> tuple[str, ...]:
    return _rank_population_view_labels('south_india_detail', g25_line, limit=limit)


def _rank_east_india_bengal_populations(g25_line: str, *, limit: int = 3) -> tuple[str, ...]:
    return _rank_population_view_labels('east_india_bengal_detail', g25_line, limit=limit)


def _rank_east_europe_populations(g25_line: str, *, limit: int = 3) -> tuple[str, ...]:
    return _rank_population_view_labels('east_europe_detail', g25_line, limit=limit)


def _rank_north_europe_populations(g25_line: str, *, limit: int = 3) -> tuple[str, ...]:
    return _rank_population_view_labels('north_europe_detail', g25_line, limit=limit)


def _rank_south_europe_populations(g25_line: str, *, limit: int = 3) -> tuple[str, ...]:
    return _rank_population_view_labels('south_europe_detail', g25_line, limit=limit)


def _rank_balkans_populations(g25_line: str, *, limit: int = 3) -> tuple[str, ...]:
    return _rank_population_view_labels('balkans_detail', g25_line, limit=limit)


def _rank_baltic_populations(g25_line: str, *, limit: int = 3) -> tuple[str, ...]:
    return _rank_population_view_labels('baltic_detail', g25_line, limit=limit)


def _rank_west_eurasia_europe_populations(g25_line: str, *, limit: int = 3) -> tuple[str, ...]:
    return _rank_population_view_labels('west_eurasia_europe_detail', g25_line, limit=limit)


def _rank_west_eurasia_caucasus_populations(g25_line: str, *, limit: int = 3) -> tuple[str, ...]:
    return _rank_population_view_labels('west_eurasia_caucasus_detail', g25_line, limit=limit)


def _rank_west_eurasia_anatolia_populations(g25_line: str, *, limit: int = 3) -> tuple[str, ...]:
    return _rank_population_view_labels('west_eurasia_anatolia_detail', g25_line, limit=limit)


def _rank_west_eurasia_levant_populations(g25_line: str, *, limit: int = 3) -> tuple[str, ...]:
    return _rank_population_view_labels('west_eurasia_levant_detail', g25_line, limit=limit)


def _rank_west_eurasia_mesopotamia_iran_populations(g25_line: str, *, limit: int = 3) -> tuple[str, ...]:
    return _rank_population_view_labels('west_eurasia_mesopotamia_iran_detail', g25_line, limit=limit)


def _rank_west_eurasia_steppe_populations(g25_line: str, *, limit: int = 3) -> tuple[str, ...]:
    return _rank_population_view_labels('west_eurasia_steppe_detail', g25_line, limit=limit)


def _rank_population_view_labels(view_action: str, g25_line: str, *, limit: int = 3) -> tuple[str, ...]:
    entry = g25_engine.parse_g25_line(g25_line)
    profiles = _population_view_profiles()[view_action]
    return tuple(
        sorted(
            profiles,
            key=lambda label: math.dist(entry.coords, profiles[label]),
        )[:limit]
    )


def _rank_profile_distances(
    g25_line: str,
    profiles: dict[str, tuple[float, ...]],
    *,
    limit: int = 5,
) -> tuple[tuple[str, float], ...]:
    entry = g25_engine.parse_g25_line(g25_line)
    return tuple(
        sorted(
            ((label, math.dist(entry.coords, coords)) for label, coords in profiles.items()),
            key=lambda item: item[1],
        )[:limit]
    )


def _caption_label(value: str, *, max_length: int = 56) -> str:
    cleaned = ' '.join(str(value).replace('\n', ' ').split())
    if len(cleaned) <= max_length:
        return cleaned
    return cleaned[:max_length - 3].rstrip() + '...'


def _coordinate_space_photo_caption(
    sample: SampleAsset,
    g25_line: str,
    profiles: dict[str, tuple[float, ...]],
    *,
    space_title: str = 'Coordinates',
    mode: str = 'region',
    group_map: dict[str, str] | None = None,
    label_formatter=None,
) -> str:
    formatter = label_formatter or (lambda label: label)
    ranked = _rank_profile_distances(g25_line, profiles, limit=5)
    lines = [
        _caption_space_title(space_title, mode),
        '',
        f'G25-профиль: {_caption_label(sample.display_name)}',
    ]
    if not ranked:
        return '\n'.join(lines)

    closest_label, closest_distance = ranked[0]
    closest_text = _caption_label(formatter(closest_label), max_length=42)
    if mode == 'population':
        lines.append(f'Ближайшая популяция: {closest_text}')
        region_label = (group_map or {}).get(closest_label, '')
        if region_label:
            lines.append(f'Регион: {_caption_label(region_label, max_length=42)}')
    else:
        lines.append(f'Ближайшая зона: {closest_text}')
    lines.append(f'Дистанция: {closest_distance:.5f}')
    if len(ranked) > 1:
        lines.append(f'Отрыв от #2: {ranked[1][1] - closest_distance:.5f}')
    return '\n'.join(lines)


def _ready_made_g25_profiles() -> dict[str, dict[str, tuple[float, ...]]]:
    populations = _load_modern_population_averages()
    profiles = {
        'global': {
            region_name: _build_centroid(populations, region_name=region_name, labels=labels)
            for region_name, labels in _GLOBAL_REGION_LABELS.items()
        },
        'west_eurasia': {
            region_name: _build_centroid(populations, region_name=region_name, labels=labels)
            for region_name, labels in _WEST_EURASIA_REGION_LABELS.items()
        },
    }
    for space_action, config in _ALL_CONFIGURED_SPACES.items():
        profiles[space_action] = {
            region_name: _build_centroid(populations, region_name=region_name, labels=labels)
            for region_name, labels in config['region_labels'].items()
        }
    return profiles


def _classify_region_by_full_g25(g25_line: str, region_profiles: dict[str, tuple[float, ...]]) -> str:
    entry = g25_engine.parse_g25_line(g25_line)
    return min(
        region_profiles,
        key=lambda region_name: math.dist(entry.coords, region_profiles[region_name]),
    )


def _project_sample_to_layout(
    g25_line: str,
    *,
    region_profiles: dict[str, tuple[float, ...]],
    region_layout: dict[str, tuple[int, int]],
    bounds: tuple[int, int, int, int],
    top_regions: int = 4,
) -> tuple[int, int]:
    entry = g25_engine.parse_g25_line(g25_line)
    ranked_regions = sorted(
        region_profiles,
        key=lambda region_name: math.dist(entry.coords, region_profiles[region_name]),
    )[:top_regions]

    weighted_points: list[tuple[float, int, int]] = []
    for region_name in ranked_regions:
        distance = math.dist(entry.coords, region_profiles[region_name])
        weight = 1.0 / ((distance + 1e-6) ** 2)
        x, y = region_layout[region_name]
        weighted_points.append((weight, x, y))

    total_weight = sum(weight for weight, _, _ in weighted_points)
    x = sum(weight * point_x for weight, point_x, _ in weighted_points) / total_weight
    y = sum(weight * point_y for weight, _, point_y in weighted_points) / total_weight

    min_x, min_y, max_x, max_y = bounds
    clamped_x = max(min_x, min(max_x, round(x)))
    clamped_y = max(min_y, min(max_y, round(y)))
    return clamped_x, clamped_y


def _classify_global_region(g25_line: str) -> str:
    return coordinate_g25_summary.classify_global_region(g25_line)


def _classify_west_eurasia_region(g25_line: str) -> str:
    return _classify_region_by_full_g25(g25_line, _ready_made_g25_profiles()['west_eurasia'])


def _project_global_sample_position(g25_line: str) -> tuple[int, int]:
    return _project_sample_to_layout(
        g25_line,
        region_profiles=_ready_made_g25_profiles()['global'],
        region_layout=_GLOBAL_REGION_LAYOUT,
        bounds=(88, 78, 760, 392),
    )


def _project_west_eurasia_sample_position(g25_line: str) -> tuple[int, int]:
    return _project_sample_to_layout(
        g25_line,
        region_profiles=_ready_made_g25_profiles()['west_eurasia'],
        region_layout=_WEST_EURASIA_REGION_LAYOUT,
        bounds=(110, 72, 748, 350),
    )


def _classify_configured_space_region(space_action: str, g25_line: str) -> str:
    return _classify_region_by_full_g25(g25_line, _ready_made_g25_profiles()[space_action])


def _classify_north_caucasus_region(g25_line: str) -> str:
    return _classify_configured_space_region('north_caucasus_detail', g25_line)


def _classify_south_caucasus_region(g25_line: str) -> str:
    return _classify_configured_space_region('south_caucasus_detail', g25_line)


def _classify_steppe_fringe_region(g25_line: str) -> str:
    return _classify_configured_space_region('steppe_fringe_detail', g25_line)


def _classify_northeast_asia_region(g25_line: str) -> str:
    return _classify_configured_space_region('northeast_asia_detail', g25_line)


def _classify_north_china_region(g25_line: str) -> str:
    return _classify_configured_space_region('north_china_detail', g25_line)


def _classify_south_china_region(g25_line: str) -> str:
    return _classify_configured_space_region('south_china_detail', g25_line)


def _classify_siberia_inner_asia_region(g25_line: str) -> str:
    return _classify_configured_space_region('siberia_inner_asia_detail', g25_line)


def _classify_northwest_south_asia_region(g25_line: str) -> str:
    return _classify_configured_space_region('northwest_south_asia_detail', g25_line)


def _classify_gangetic_north_india_region(g25_line: str) -> str:
    return _classify_configured_space_region('gangetic_north_india_detail', g25_line)


def _classify_west_india_region(g25_line: str) -> str:
    return _classify_configured_space_region('west_india_detail', g25_line)


def _classify_south_india_region(g25_line: str) -> str:
    return _classify_configured_space_region('south_india_detail', g25_line)


def _classify_east_india_bengal_region(g25_line: str) -> str:
    return _classify_configured_space_region('east_india_bengal_detail', g25_line)


def _classify_north_europe_region(g25_line: str) -> str:
    return _classify_configured_space_region('north_europe_detail', g25_line)


def _classify_south_europe_region(g25_line: str) -> str:
    return _classify_configured_space_region('south_europe_detail', g25_line)


def _classify_balkans_region(g25_line: str) -> str:
    return _classify_configured_space_region('balkans_detail', g25_line)


def _classify_baltic_region(g25_line: str) -> str:
    return _classify_configured_space_region('baltic_detail', g25_line)


def _classify_west_eurasia_europe_region(g25_line: str) -> str:
    return _classify_configured_space_region('west_eurasia_europe_detail', g25_line)


def _classify_west_eurasia_caucasus_region(g25_line: str) -> str:
    return _classify_configured_space_region('west_eurasia_caucasus_detail', g25_line)


def _classify_west_eurasia_anatolia_region(g25_line: str) -> str:
    return _classify_configured_space_region('west_eurasia_anatolia_detail', g25_line)


def _classify_west_eurasia_levant_region(g25_line: str) -> str:
    return _classify_configured_space_region('west_eurasia_levant_detail', g25_line)


def _classify_west_eurasia_mesopotamia_iran_region(g25_line: str) -> str:
    return _classify_configured_space_region('west_eurasia_mesopotamia_iran_detail', g25_line)


def _classify_west_eurasia_steppe_region(g25_line: str) -> str:
    return _classify_configured_space_region('west_eurasia_steppe_detail', g25_line)


def _project_configured_space_position(space_action: str, g25_line: str) -> tuple[int, int]:
    config = _ALL_CONFIGURED_SPACES[space_action]
    return _project_sample_to_layout(
        g25_line,
        region_profiles=_ready_made_g25_profiles()[space_action],
        region_layout=config['layout'],
        bounds=config['bounds'],
    )


def _project_north_caucasus_population_position(g25_line: str) -> tuple[int, int]:
    return _project_population_view_position('north_caucasus_detail', g25_line)


def _project_population_view_position(view_action: str, g25_line: str) -> tuple[int, int]:
    config = _POPULATION_VIEW_CONFIGS[view_action]
    return _project_sample_to_layout(
        g25_line,
        region_profiles=_population_view_profiles()[view_action],
        region_layout=config['layout'],
        bounds=config['bounds'],
        top_regions=5,
    )


def _draw_frame(
    buffer: bytearray,
    width: int,
    height: int,
    x: int,
    y: int,
    frame_w: int,
    frame_h: int,
    color: tuple[int, int, int],
    *,
    thickness: int = 2,
) -> None:
    _put_rect(buffer, width, height, x, y, frame_w, thickness, color)
    _put_rect(buffer, width, height, x, y + frame_h - thickness, frame_w, thickness, color)
    _put_rect(buffer, width, height, x, y, thickness, frame_h, color)
    _put_rect(buffer, width, height, x + frame_w - thickness, y, thickness, frame_h, color)


_READY_MADE_DARK_BACKGROUND = (27, 31, 39)
_READY_MADE_DARK_FRAME = (126, 138, 156)
_READY_MADE_DARK_LABEL = (240, 244, 250)
_READY_MADE_DARK_LABEL_MUTED = (197, 206, 218)
_READY_MADE_DARK_LABEL_SOFT = (174, 186, 201)
_READY_MADE_DARK_LEGEND = (206, 216, 228)
_READY_MADE_DARK_REGION_OUTER = (132, 164, 201)
_READY_MADE_DARK_REGION_INNER = (232, 239, 248)
_READY_MADE_DARK_TOP_OUTER = (151, 214, 255)
_READY_MADE_DARK_TOP_INNER = (242, 248, 255)
_READY_MADE_DARK_TOP_LINE = (96, 145, 191)
_READY_MADE_DARK_SAMPLE_OUTER = (255, 179, 108)
_READY_MADE_DARK_SAMPLE_GLOW = (120, 86, 48)
_READY_MADE_DARK_SAMPLE_INNER = (61, 69, 82)
_READY_MADE_DARK_SAMPLE_HIGHLIGHT = (255, 223, 186)
_READY_MADE_DARK_SUMMARY_LINE = (83, 94, 109)
_READY_MADE_DARK_BOX_COLORS = (
    (47, 58, 74),
    (56, 50, 69),
    (68, 58, 50),
    (46, 58, 64),
    (62, 50, 69),
    (43, 64, 68),
)


def _theme_boxes(
    boxes: tuple[tuple[int, int, int, int, tuple[int, int, int]], ...],
) -> tuple[tuple[int, int, int, int, tuple[int, int, int]], ...]:
    themed_boxes: list[tuple[int, int, int, int, tuple[int, int, int]]] = []
    for index, (x, y, box_w, box_h, _) in enumerate(boxes):
        themed_boxes.append((x, y, box_w, box_h, _READY_MADE_DARK_BOX_COLORS[index % len(_READY_MADE_DARK_BOX_COLORS)]))
    return tuple(themed_boxes)


def _draw_pixel_line(
    buffer: bytearray,
    width: int,
    height: int,
    *,
    start: tuple[int, int],
    end: tuple[int, int],
    color: tuple[int, int, int],
    thickness: int = 1,
) -> None:
    x0, y0 = start
    x1, y1 = end
    dx = abs(x1 - x0)
    sx = 1 if x0 < x1 else -1
    dy = -abs(y1 - y0)
    sy = 1 if y0 < y1 else -1
    error = dx + dy
    while True:
        _put_rect(
            buffer,
            width,
            height,
            x0 - thickness // 2,
            y0 - thickness // 2,
            max(1, thickness),
            max(1, thickness),
            color,
        )
        if x0 == x1 and y0 == y1:
            break
        twice_error = 2 * error
        if twice_error >= dy:
            error += dy
            x0 += sx
        if twice_error <= dx:
            error += dx
            y0 += sy


def _transform_plot_point(
    point: tuple[int, int],
    *,
    x_scale: float = 1.0,
    y_scale: float = 1.0,
    x_shift: int = 0,
    y_shift: int = 0,
    origin: tuple[int, int] = (450, 225),
) -> tuple[int, int]:
    x, y = point
    origin_x, origin_y = origin
    return (
        int(round(origin_x + (x - origin_x) * x_scale + x_shift)),
        int(round(origin_y + (y - origin_y) * y_scale + y_shift)),
    )


def _transform_plot_rect(
    rect: tuple[int, int, int, int],
    *,
    x_scale: float = 1.0,
    y_scale: float = 1.0,
    x_shift: int = 0,
    y_shift: int = 0,
    origin: tuple[int, int] = (450, 225),
) -> tuple[int, int, int, int]:
    x, y, rect_w, rect_h = rect
    top_left = _transform_plot_point((x, y), x_scale=x_scale, y_scale=y_scale, x_shift=x_shift, y_shift=y_shift, origin=origin)
    return (
        top_left[0],
        top_left[1],
        int(round(rect_w * x_scale)),
        int(round(rect_h * y_scale)),
    )


_CYRILLIC_TO_ASCII_PLOT = {
    'А': 'A', 'Б': 'B', 'В': 'V', 'Г': 'G', 'Д': 'D', 'Е': 'E', 'Ё': 'E', 'Ж': 'ZH',
    'З': 'Z', 'И': 'I', 'Й': 'I', 'К': 'K', 'Л': 'L', 'М': 'M', 'Н': 'N', 'О': 'O',
    'П': 'P', 'Р': 'R', 'С': 'S', 'Т': 'T', 'У': 'U', 'Ф': 'F', 'Х': 'KH', 'Ц': 'TS',
    'Ч': 'CH', 'Ш': 'SH', 'Щ': 'SCH', 'Ъ': '', 'Ы': 'Y', 'Ь': '', 'Э': 'E', 'Ю': 'YU',
    'Я': 'YA',
}


def _ascii_plot_text(text: str) -> str:
    converted_parts: list[str] = []
    for char in text:
        if 'A' <= char <= 'Z' or '0' <= char <= '9' or char in {' ', '.', ':', '-', '/'}:
            converted_parts.append(char)
            continue
        converted = _CYRILLIC_TO_ASCII_PLOT.get(char.upper())
        if converted is not None:
            converted_parts.append(converted)
    return ''.join(converted_parts).strip()


def _draw_global_region_marker(
    buffer: bytearray,
    width: int,
    height: int,
    *,
    x: int,
    y: int,
    scale: int = 1,
) -> None:
    _put_rect(buffer, width, height, x - 5 * scale, y - 5 * scale, 10 * scale, 10 * scale, _READY_MADE_DARK_REGION_OUTER)
    _put_rect(buffer, width, height, x - 2 * scale, y - 2 * scale, 4 * scale, 4 * scale, _READY_MADE_DARK_REGION_INNER)


def _draw_top_population_marker(
    buffer: bytearray,
    width: int,
    height: int,
    *,
    x: int,
    y: int,
    scale: int = 1,
) -> None:
    _put_rect(buffer, width, height, x - 7 * scale, y - 7 * scale, 14 * scale, 14 * scale, _READY_MADE_DARK_TOP_OUTER)
    _put_rect(buffer, width, height, x - 4 * scale, y - 4 * scale, 8 * scale, 8 * scale, _READY_MADE_DARK_SAMPLE_INNER)
    _put_rect(buffer, width, height, x - 2 * scale, y - 2 * scale, 4 * scale, 4 * scale, _READY_MADE_DARK_TOP_INNER)


def _draw_global_sample_marker(
    buffer: bytearray,
    width: int,
    height: int,
    *,
    x: int,
    y: int,
    scale: int = 1,
) -> None:
    _put_rect(buffer, width, height, x - 9 * scale, y - 9 * scale, 18 * scale, 18 * scale, _READY_MADE_DARK_SAMPLE_GLOW)
    _put_rect(buffer, width, height, x - 7 * scale, y - 7 * scale, 14 * scale, 14 * scale, _READY_MADE_DARK_SAMPLE_OUTER)
    _put_rect(buffer, width, height, x - 4 * scale, y - 4 * scale, 8 * scale, 8 * scale, _READY_MADE_DARK_SAMPLE_INNER)
    _put_rect(buffer, width, height, x - 2 * scale, y - 2 * scale, 4 * scale, 4 * scale, _READY_MADE_DARK_SAMPLE_HIGHLIGHT)
    _put_rect(buffer, width, height, x - 1 * scale, y - 1 * scale, 2 * scale, 2 * scale, _READY_MADE_DARK_SAMPLE_OUTER)


def _summary_key_value(summary_line: str) -> tuple[str, str]:
    if ':' not in summary_line:
        return (summary_line.strip(), '')
    key, value = summary_line.split(':', 1)
    return (key.strip(), value.strip())


def _summary_top_population_values(summary_lines: tuple[str, ...]) -> tuple[str, ...]:
    for summary_line in summary_lines:
        key, value = _summary_key_value(summary_line)
        if key.lower() == 'top populations' and value:
            return tuple(part.strip() for part in value.split(',') if part.strip())
    return ()


def _summary_sample_value(summary_lines: tuple[str, ...]) -> str:
    for summary_line in summary_lines:
        key, value = _summary_key_value(summary_line)
        if key.lower() == 'sample' and value:
            return value.strip()
    return ''


def _draw_summary_block(
    buffer: bytearray,
    width: int,
    height: int,
    *,
    summary_lines: tuple[str, ...],
    primary_label: str = 'POPULATION',
    plot_bottom: int | None = None,
    ui_scale: int = 1,
) -> None:
    if not summary_lines:
        return

    def _text_width(text: str, scale: int) -> int:
        return len(text) * 6 * scale

    top_population_values = _summary_top_population_values(summary_lines)
    sample_value = _summary_sample_value(summary_lines)
    visible_lines = tuple(
        line for line in summary_lines
        if _summary_key_value(line)[0].lower() not in {'sample'}
    )
    if not visible_lines:
        return
    panel_x = 20 * ui_scale
    panel_w = width - panel_x * 2
    line_gap = 14 * ui_scale
    legend_scale = max(1, ui_scale)
    text_scale = legend_scale
    legend_gap = 16 * ui_scale if sample_value else 0
    panel_h = max(38 * ui_scale, legend_gap + len(visible_lines) * line_gap + 8 * ui_scale)
    if plot_bottom is None:
        panel_y = height - panel_h - 10 * ui_scale
    else:
        panel_y = plot_bottom + 4 * ui_scale
    _put_rect(buffer, width, height, panel_x, panel_y, panel_w, max(1, ui_scale), _READY_MADE_DARK_SUMMARY_LINE)
    text_x = panel_x + 16 * ui_scale
    text_y = panel_y + 10 * ui_scale
    if sample_value:
        legend_y = text_y
        _draw_text(buffer, width, height, text_x, legend_y, primary_label, _READY_MADE_DARK_LEGEND, scale=legend_scale)
        primary_marker_x = text_x + _text_width(primary_label, legend_scale) + 12 * ui_scale
        _draw_global_region_marker(
            buffer,
            width,
            height,
            x=primary_marker_x,
            y=legend_y + 4 * legend_scale,
            scale=max(1, ui_scale),
        )
        sample_label_x = primary_marker_x + 20 * ui_scale
        _draw_text(buffer, width, height, sample_label_x, legend_y, 'SAMPLE', _READY_MADE_DARK_LEGEND, scale=legend_scale)
        sample_marker_x = sample_label_x + _text_width('SAMPLE', legend_scale) + 14 * ui_scale
        _draw_global_sample_marker(
            buffer,
            width,
            height,
            x=sample_marker_x,
            y=legend_y + 4 * legend_scale,
            scale=max(1, ui_scale),
        )
        target_label = f'TARGET {_ascii_plot_text(sample_value.strip().upper())}'.strip()
        if len(target_label) > 28:
            target_label = target_label[:28]
        target_x = sample_marker_x + 30 * ui_scale
        _draw_text(
            buffer,
            width,
            height,
            target_x,
            legend_y,
            target_label,
            _READY_MADE_DARK_LABEL_MUTED,
            scale=legend_scale,
        )
        text_y += legend_gap
    current_row = 0
    for line in visible_lines:
        key, value = _summary_key_value(line)
        upper_key = f'{key.upper()}:'
        row_y = text_y + current_row * line_gap
        key_color = _READY_MADE_DARK_LABEL if key.lower() in {'closest cluster', 'closest region', 'closest population', 'top populations'} else _READY_MADE_DARK_LEGEND
        value_color = _READY_MADE_DARK_LABEL if key.lower() in {'closest cluster', 'closest region', 'closest population', 'top populations'} else _READY_MADE_DARK_LABEL_MUTED
        _draw_text(buffer, width, height, text_x, row_y, upper_key, key_color, scale=text_scale)
        key_width = _text_width(upper_key, text_scale)
        if key.lower() == 'top populations':
            inline_value = ' '.join(
                f'{index} {_population_label_text(top_population).upper()}'
                for index, top_population in enumerate(top_population_values, start=1)
            )
            _draw_text(
                buffer,
                width,
                height,
                text_x + key_width + 8 * ui_scale,
                row_y,
                inline_value,
                value_color,
                scale=text_scale,
            )
        else:
            _draw_text(
                buffer,
                width,
                height,
                text_x + key_width + 8 * ui_scale,
                row_y,
                value.upper(),
                value_color,
                scale=text_scale,
            )
        current_row += 1


def _create_global_visualization_path() -> Path:
    fd, raw_path = tempfile.mkstemp(prefix='global_space_', suffix='.png')
    os.close(fd)
    return Path(raw_path)


def _render_global_visualization(
    output_path: Path,
    *,
    sample_point: tuple[int, int],
    summary_lines: tuple[str, ...] = (),
) -> None:
    width = 900
    height = 490 if summary_lines else 500
    plot_x_scale = 1.05 if summary_lines else 1.0
    plot_y_scale = 1.08 if summary_lines else 1.0
    plot_x_shift = -6 if summary_lines else 0
    plot_y_shift = -10 if summary_lines else 0
    background = _READY_MADE_DARK_BACKGROUND
    buffer = bytearray(bytes(background) * width * height)

    for x, y, box_w, box_h, color in _theme_boxes((
        (36, 52, 220, 220, (0, 0, 0)),
        (270, 70, 500, 300, (0, 0, 0)),
        (300, 255, 120, 110, (0, 0, 0)),
        (680, 345, 120, 70, (0, 0, 0)),
    )):
        tx, ty, tw, th = _transform_plot_rect(
            (x, y, box_w, box_h),
            x_scale=plot_x_scale,
            y_scale=plot_y_scale,
            x_shift=plot_x_shift,
            y_shift=plot_y_shift,
        )
        _put_rect(buffer, width, height, tx, ty, tw, th, color)
    frame_rect = _transform_plot_rect(
        (28, 28, 844, 404),
        x_scale=plot_x_scale,
        y_scale=plot_y_scale,
        x_shift=plot_x_shift,
        y_shift=plot_y_shift,
    )
    _draw_frame(buffer, width, height, *frame_rect, _READY_MADE_DARK_FRAME)

    if not summary_lines:
        _draw_text(buffer, width, height, 42, 442, 'REGION', _READY_MADE_DARK_LEGEND, scale=2)
        _draw_global_region_marker(buffer, width, height, x=160, y=450)
        _draw_text(buffer, width, height, 230, 442, 'SAMPLE', _READY_MADE_DARK_LEGEND, scale=2)
        _draw_global_sample_marker(buffer, width, height, x=336, y=450)

    for region_name, (x, y) in _GLOBAL_REGION_LAYOUT.items():
        label_dx, label_dy = _GLOBAL_LABEL_OFFSETS[region_name]
        tx, ty = _transform_plot_point(
            (x, y),
            x_scale=plot_x_scale,
            y_scale=plot_y_scale,
            x_shift=plot_x_shift,
            y_shift=plot_y_shift,
        )
        _draw_global_region_marker(buffer, width, height, x=tx, y=ty)
        _draw_text(
            buffer,
            width,
            height,
            int(round(tx + label_dx * plot_x_scale)),
            int(round(ty + label_dy * plot_y_scale)),
            region_name,
            _READY_MADE_DARK_LABEL,
            scale=2,
        )

    sample_draw_point = _transform_plot_point(
        sample_point,
        x_scale=plot_x_scale,
        y_scale=plot_y_scale,
        x_shift=plot_x_shift,
        y_shift=plot_y_shift,
    )
    _draw_global_sample_marker(
        buffer,
        width,
        height,
        x=sample_draw_point[0],
        y=sample_draw_point[1],
    )

    _draw_summary_block(
        buffer,
        width,
        height,
        summary_lines=summary_lines,
        primary_label='REGION',
        plot_bottom=28 + 404,
        ui_scale=1,
    )
    _write_png(output_path, width, height, buffer)


def _render_west_eurasia_visualization(
    output_path: Path,
    *,
    sample_point: tuple[int, int],
    summary_lines: tuple[str, ...] = (),
) -> None:
    width = 900
    height = 490 if summary_lines else 500
    plot_x_scale = 1.05 if summary_lines else 1.0
    plot_y_scale = 1.08 if summary_lines else 1.0
    plot_x_shift = -6 if summary_lines else 0
    plot_y_shift = -10 if summary_lines else 0
    background = _READY_MADE_DARK_BACKGROUND
    buffer = bytearray(bytes(background) * width * height)

    for x, y, box_w, box_h, color in _theme_boxes((
        (74, 76, 690, 290, (0, 0, 0)),
        (118, 108, 220, 188, (0, 0, 0)),
        (286, 210, 138, 98, (0, 0, 0)),
        (388, 198, 142, 112, (0, 0, 0)),
        (520, 192, 170, 134, (0, 0, 0)),
        (112, 322, 146, 66, (0, 0, 0)),
    )):
        tx, ty, tw, th = _transform_plot_rect(
            (x, y, box_w, box_h),
            x_scale=plot_x_scale,
            y_scale=plot_y_scale,
            x_shift=plot_x_shift,
            y_shift=plot_y_shift,
        )
        _put_rect(buffer, width, height, tx, ty, tw, th, color)
    frame_rect = _transform_plot_rect(
        (44, 42, 806, 380),
        x_scale=plot_x_scale,
        y_scale=plot_y_scale,
        x_shift=plot_x_shift,
        y_shift=plot_y_shift,
    )
    _draw_frame(buffer, width, height, *frame_rect, _READY_MADE_DARK_FRAME)

    if not summary_lines:
        _draw_text(buffer, width, height, 58, 442, 'REGION', _READY_MADE_DARK_LEGEND, scale=2)
        _draw_global_region_marker(buffer, width, height, x=160, y=450)
        _draw_text(buffer, width, height, 230, 442, 'SAMPLE', _READY_MADE_DARK_LEGEND, scale=2)
        _draw_global_sample_marker(buffer, width, height, x=336, y=450)

    for region_name, (x, y) in _WEST_EURASIA_REGION_LAYOUT.items():
        label_dx, label_dy = _WEST_EURASIA_LABEL_OFFSETS[region_name]
        tx, ty = _transform_plot_point(
            (x, y),
            x_scale=plot_x_scale,
            y_scale=plot_y_scale,
            x_shift=plot_x_shift,
            y_shift=plot_y_shift,
        )
        _draw_global_region_marker(buffer, width, height, x=tx, y=ty)
        _draw_text(
            buffer,
            width,
            height,
            int(round(tx + label_dx * plot_x_scale)),
            int(round(ty + label_dy * plot_y_scale)),
            region_name,
            _READY_MADE_DARK_LABEL,
            scale=2,
        )

    sample_draw_point = _transform_plot_point(
        sample_point,
        x_scale=plot_x_scale,
        y_scale=plot_y_scale,
        x_shift=plot_x_shift,
        y_shift=plot_y_shift,
    )
    _draw_global_sample_marker(
        buffer,
        width,
        height,
        x=sample_draw_point[0],
        y=sample_draw_point[1],
    )

    _draw_summary_block(
        buffer,
        width,
        height,
        summary_lines=summary_lines,
        primary_label='REGION',
        plot_bottom=42 + 380,
        ui_scale=1,
    )
    _write_png(output_path, width, height, buffer)


def _render_configured_space_visualization(
    output_path: Path,
    *,
    space_action: str,
    sample_point: tuple[int, int],
    summary_lines: tuple[str, ...] = (),
) -> None:
    config = _ALL_CONFIGURED_SPACES[space_action]
    width = 900
    height = 490 if summary_lines else 500
    plot_x_scale = 1.05 if summary_lines else 1.0
    plot_y_scale = 1.08 if summary_lines else 1.0
    plot_x_shift = -6 if summary_lines else 0
    plot_y_shift = -10 if summary_lines else 0
    background = _READY_MADE_DARK_BACKGROUND
    buffer = bytearray(bytes(background) * width * height)

    for x, y, box_w, box_h, color in _theme_boxes(config['boxes']):
        tx, ty, tw, th = _transform_plot_rect(
            (x, y, box_w, box_h),
            x_scale=plot_x_scale,
            y_scale=plot_y_scale,
            x_shift=plot_x_shift,
            y_shift=plot_y_shift,
        )
        _put_rect(buffer, width, height, tx, ty, tw, th, color)

    frame_x, frame_y, frame_w, frame_h = config['frame']
    frame_x, frame_y, frame_w, frame_h = _transform_plot_rect(
        (frame_x, frame_y, frame_w, frame_h),
        x_scale=plot_x_scale,
        y_scale=plot_y_scale,
        x_shift=plot_x_shift,
        y_shift=plot_y_shift,
    )
    _draw_frame(
        buffer,
        width,
        height,
        frame_x,
        frame_y,
        frame_w,
        frame_h,
        _READY_MADE_DARK_FRAME,
        thickness=2,
    )

    if not summary_lines:
        _draw_text(buffer, width, height, 58, 442, 'REGION', _READY_MADE_DARK_LEGEND, scale=2)
        _draw_global_region_marker(buffer, width, height, x=160, y=450)
        _draw_text(buffer, width, height, 230, 442, 'SAMPLE', _READY_MADE_DARK_LEGEND, scale=2)
        _draw_global_sample_marker(buffer, width, height, x=336, y=450)

    for region_name, (x, y) in config['layout'].items():
        label_dx, label_dy = config['label_offsets'][region_name]
        tx, ty = _transform_plot_point(
            (x, y),
            x_scale=plot_x_scale,
            y_scale=plot_y_scale,
            x_shift=plot_x_shift,
            y_shift=plot_y_shift,
        )
        _draw_global_region_marker(buffer, width, height, x=tx, y=ty)
        _draw_text(
            buffer,
            width,
            height,
            int(round(tx + label_dx * plot_x_scale)),
            int(round(ty + label_dy * plot_y_scale)),
            region_name,
            _READY_MADE_DARK_LABEL,
            scale=2,
        )

    sample_draw_point = _transform_plot_point(
        sample_point,
        x_scale=plot_x_scale,
        y_scale=plot_y_scale,
        x_shift=plot_x_shift,
        y_shift=plot_y_shift,
    )
    _draw_global_sample_marker(
        buffer,
        width,
        height,
        x=sample_draw_point[0],
        y=sample_draw_point[1],
    )

    _draw_summary_block(
        buffer,
        width,
        height,
        summary_lines=summary_lines,
        primary_label='REGION',
        plot_bottom=frame_y + frame_h,
        ui_scale=1,
    )
    _write_png(output_path, width, height, buffer)


_POPULATION_LABEL_PREFIX_ABBREVIATIONS: dict[str, str] = {
    'Turkish': 'Tr.',
    'Georgian': 'Geo.',
    'Armenian': 'Arm.',
    'Azerbaijani': 'Azer.',
    'Iranian': 'Iran.',
    'Lebanese': 'Leb.',
    'Syrian': 'Syr.',
    'Russian': 'Rus.',
    'Ukrainian': 'Ukr.',
    'Finnish': 'Fin.',
    'Lithuanian': 'Lith.',
    'Greek': 'Gr.',
    'Italian': 'It.',
    'Punjabi': 'Punj.',
    'Pashtun': 'Pash.',
    'Brahmin': 'Brah.',
    'Bengali': 'Beng.',
    'Gujarati': 'Guj.',
    'Kshatriya': 'Kshat.',
}


_POPULATION_LABEL_TOKEN_ABBREVIATIONS: dict[str, str] = {
    'Republic': 'Rep.',
    'Orthodox': 'Orth.',
    'Christian': 'Chr.',
    'Muslim': 'Mus.',
    'Afghanistan': 'Afg.',
    'Pakistan': 'Pak.',
    'Bangladesh': 'Bang.',
    'Northeast': 'NE',
    'NorthEast': 'NE',
    'Northwest': 'NW',
    'SouthEast': 'SE',
    'Southeast': 'SE',
    'Southwest': 'SW',
    'Central': 'Ctr.',
    'Inner': 'Inn.',
}


_POPULATION_LABEL_EXACT_OVERRIDES: dict[str, str] = {
    'Lebanese_Orthodox_Christian_Koura': 'Leb. Orth. Chr. Koura',
    'Lebanese_Sunni_Muslim_Beirut': 'Leb. Sunni Mus. Beirut',
    'Lebanese_Shia_Muslim_Beirut': 'Leb. Shia Mus. Beirut',
    'Pashtun_Pakistan_Khattak_Nowshera': 'Pash. Pak. Khattak Nowshera',
    'Pashtun_Afghanistan_Northeast': 'Pash. Afg. NE',
    'Pashtun_Northeast_Afghanistan': 'Pash. NE Afg.',
    'Pashtun_Afghanistan_North': 'Pash. Afg. North',
    'Pashtun_Afghanistan_Paktia': 'Pash. Afg. Paktia',
    'Azerbaijani_Republic_Agjabedi': 'Azer. Rep. Agjabedi',
    'Azerbaijani_Republic_Gabala': 'Azer. Rep. Gabala',
    'Azerbaijani_Republic_Shaki': 'Azer. Rep. Shaki',
    'Azerbaijani_Iran_WestAz_Maku': 'Azer. Iran W. Az. Maku',
    'Azerbaijani_Iran_EastAz': 'Azer. Iran E. Az.',
    'Kshatriya_Uttar_Pradesh_East': 'Kshat. UP East',
    'Brahmin_Uttar_Pradesh_Awadh': 'Brah. UP Awadh',
    'Brahmin_Uttar_Pradesh_Braj': 'Brah. UP Braj',
    'Brahmin_Uttar_Pradesh_East': 'Brah. UP East',
    'Brahmin_Tamil_Nadu_Iyengar': 'Brah. TN Iyengar',
    'Brahmin_Tamil_Nadu_Iyer': 'Brah. TN Iyer',
    'Bengali_Bangladesh_SouthEast': 'Beng. Bang. SE',
    'Bengali_Bangladesh_Sylhet': 'Beng. Bang. Sylhet',
    'Punjabi_Christian_India': 'Punj. Chr. India',
    'Palestinian_Beit_Sahour': 'Pal. Beit Sahour',
    'Greek_Central_Anatolia': 'Gr. Ctr. Anatolia',
    'Spanish_Castilla_Y_Leon': 'Spanish Castilla y Leon',
}


def _population_label_text(label: str) -> str:
    exact = _POPULATION_LABEL_EXACT_OVERRIDES.get(label)
    if exact is not None:
        return exact
    parts = label.split('_')
    if len(parts) > 1 and parts[0] in _POPULATION_LABEL_PREFIX_ABBREVIATIONS:
        parts = [_POPULATION_LABEL_PREFIX_ABBREVIATIONS[parts[0]], *parts[1:]]
    parts = [_POPULATION_LABEL_TOKEN_ABBREVIATIONS.get(part, part) for part in parts]
    return ' '.join(parts)


def _scale_population_view_point(point: tuple[int, int], *, scale: int) -> tuple[int, int]:
    return (point[0] * scale, point[1] * scale)


def _scale_population_view_rect(rect: tuple[int, int, int, int], *, scale: int) -> tuple[int, int, int, int]:
    x, y, rect_w, rect_h = rect
    return (x * scale, y * scale, rect_w * scale, rect_h * scale)


def _render_north_caucasus_population_visualization(output_path: Path, *, sample_point: tuple[int, int]) -> None:
    _render_population_view_visualization('north_caucasus_detail', output_path, sample_point=sample_point)


def _render_population_view_visualization(
    view_action: str,
    output_path: Path,
    *,
    sample_point: tuple[int, int],
    summary_lines: tuple[str, ...] = (),
) -> None:
    config = _POPULATION_VIEW_CONFIGS[view_action]
    render_scale = int(config.get('render_scale', 1))
    label_scale = int(config.get('label_scale', render_scale))
    effective_label_scale = label_scale
    legend_scale = int(config.get('legend_scale', 2 * render_scale))
    marker_scale = int(config.get('marker_scale', render_scale))
    sample_marker_scale = int(config.get('sample_marker_scale', marker_scale))
    frame_thickness = int(config.get('frame_thickness', render_scale))
    width = 900 * render_scale
    summary_ui_scale = 1 if render_scale == 1 else 2
    height = (490 * render_scale) if summary_lines else (500 * render_scale)
    plot_x_scale = 1.05 if summary_lines else 1.0
    plot_y_scale = 1.08 if summary_lines else 1.0
    plot_x_shift = -6 if summary_lines else 0
    plot_y_shift = -10 if summary_lines else 0
    background = _READY_MADE_DARK_BACKGROUND
    buffer = bytearray(bytes(background) * width * height)

    for x, y, box_w, box_h, color in _theme_boxes(config['boxes']):
        tx, ty, tw, th = _transform_plot_rect(
            (x, y, box_w, box_h),
            x_scale=plot_x_scale,
            y_scale=plot_y_scale,
            x_shift=plot_x_shift,
            y_shift=plot_y_shift,
        )
        _put_rect(
            buffer,
            width,
            height,
            tx * render_scale,
            ty * render_scale,
            tw * render_scale,
            th * render_scale,
            color,
        )

    frame_x, frame_y, frame_w, frame_h = _transform_plot_rect(
        config['frame'],
        x_scale=plot_x_scale,
        y_scale=plot_y_scale,
        x_shift=plot_x_shift,
        y_shift=plot_y_shift,
    )
    frame_x, frame_y, frame_w, frame_h = _scale_population_view_rect((frame_x, frame_y, frame_w, frame_h), scale=render_scale)
    _draw_frame(
        buffer,
        width,
        height,
        frame_x,
        frame_y,
        frame_w,
        frame_h,
        _READY_MADE_DARK_FRAME,
        thickness=frame_thickness,
    )

    if not summary_lines:
        _draw_text(buffer, width, height, 58 * render_scale, 442 * render_scale, 'POPULATION', _READY_MADE_DARK_LEGEND, scale=legend_scale)
        _draw_global_region_marker(
            buffer,
            width,
            height,
            x=218 * render_scale,
            y=450 * render_scale,
            scale=marker_scale,
        )
        _draw_text(buffer, width, height, 304 * render_scale, 442 * render_scale, 'SAMPLE', _READY_MADE_DARK_LEGEND, scale=legend_scale)
        _draw_global_sample_marker(
            buffer,
            width,
            height,
            x=410 * render_scale,
            y=450 * render_scale,
            scale=sample_marker_scale,
        )

    top_population_labels = set(_summary_top_population_values(summary_lines))
    transformed_sample_point = _transform_plot_point(
        sample_point,
        x_scale=plot_x_scale,
        y_scale=plot_y_scale,
        x_shift=plot_x_shift,
        y_shift=plot_y_shift,
    )
    scaled_sample_point = _scale_population_view_point(transformed_sample_point, scale=render_scale)
    highlighted_points: list[tuple[str, tuple[int, int]]] = []

    for label, (x, y) in config['layout'].items():
        if label not in _population_view_profiles()[view_action]:
            continue
        transformed_point = _transform_plot_point(
            (x, y),
            x_scale=plot_x_scale,
            y_scale=plot_y_scale,
            x_shift=plot_x_shift,
            y_shift=plot_y_shift,
        )
        scaled_x, scaled_y = _scale_population_view_point(transformed_point, scale=render_scale)
        if label in top_population_labels:
            highlighted_points.append((label, (scaled_x, scaled_y)))
            continue
        _draw_global_region_marker(buffer, width, height, x=scaled_x, y=scaled_y, scale=marker_scale)
        _draw_text(
            buffer,
            width,
            height,
            scaled_x + 10 * marker_scale,
            scaled_y - 5 * marker_scale,
            _population_label_text(label),
            _READY_MADE_DARK_LABEL_SOFT,
            scale=effective_label_scale,
        )

    for _, point in highlighted_points:
        _draw_pixel_line(
            buffer,
            width,
            height,
            start=scaled_sample_point,
            end=point,
            color=_READY_MADE_DARK_TOP_LINE,
            thickness=1,
        )

    for label, (scaled_x, scaled_y) in highlighted_points:
        _draw_top_population_marker(
            buffer,
            width,
            height,
            x=scaled_x,
            y=scaled_y,
            scale=max(1, marker_scale),
        )
        _draw_text(
            buffer,
            width,
            height,
            scaled_x + 12 * max(1, marker_scale),
            scaled_y - 6 * max(1, marker_scale),
            _population_label_text(label),
            _READY_MADE_DARK_LABEL,
            scale=effective_label_scale,
        )

    _draw_global_sample_marker(
        buffer,
        width,
        height,
        x=scaled_sample_point[0],
        y=scaled_sample_point[1],
        scale=sample_marker_scale,
    )

    _draw_summary_block(
        buffer,
        width,
        height,
        summary_lines=summary_lines,
        primary_label='POPULATION',
        plot_bottom=frame_y + frame_h,
        ui_scale=summary_ui_scale,
    )
    _write_png(output_path, width, height, buffer)


_legacy_render_global_visualization = _render_global_visualization
_legacy_render_west_eurasia_visualization = _render_west_eurasia_visualization
_legacy_render_configured_space_visualization = _render_configured_space_visualization
_legacy_render_population_view_visualization = _render_population_view_visualization


def _render_global_visualization(
    output_path: Path,
    *,
    sample_point: tuple[int, int] | None = None,
    g25_line: str | None = None,
    summary_lines: tuple[str, ...] = (),
) -> None:
    if g25_line is None:
        _legacy_render_global_visualization(output_path, sample_point=sample_point or (450, 225), summary_lines=summary_lines)
        return
    if render_coordinate_space_png is None:
        raise RuntimeError('Coordinate Space visualization renderer is unavailable. Install Pillow and numpy.')

    profiles = _ready_made_g25_profiles()['global']
    render_coordinate_space_png(
        output_path,
        title='Global',
        g25_line=g25_line,
        reference_profiles=profiles,
        group_map={label: label for label in profiles},
        mode_label='Region',
        summary_lines=summary_lines,
    )


def _render_west_eurasia_visualization(
    output_path: Path,
    *,
    sample_point: tuple[int, int] | None = None,
    g25_line: str | None = None,
    summary_lines: tuple[str, ...] = (),
) -> None:
    if g25_line is None:
        _legacy_render_west_eurasia_visualization(output_path, sample_point=sample_point or (450, 225), summary_lines=summary_lines)
        return
    if render_coordinate_space_png is None:
        raise RuntimeError('Coordinate Space visualization renderer is unavailable. Install Pillow and numpy.')

    profiles = _ready_made_g25_profiles()['west_eurasia']
    render_coordinate_space_png(
        output_path,
        title='West Eurasia',
        g25_line=g25_line,
        reference_profiles=profiles,
        group_map={label: label for label in profiles},
        mode_label='Region',
        summary_lines=summary_lines,
    )


def _render_configured_space_visualization(
    output_path: Path,
    *,
    space_action: str,
    sample_point: tuple[int, int] | None = None,
    g25_line: str | None = None,
    summary_lines: tuple[str, ...] = (),
) -> None:
    if g25_line is None:
        _legacy_render_configured_space_visualization(
            output_path,
            space_action=space_action,
            sample_point=sample_point or (450, 225),
            summary_lines=summary_lines,
        )
        return
    if render_coordinate_space_png is None:
        raise RuntimeError('Coordinate Space visualization renderer is unavailable. Install Pillow and numpy.')

    config = _ALL_CONFIGURED_SPACES[space_action]
    profiles = _ready_made_g25_profiles()[space_action]
    render_coordinate_space_png(
        output_path,
        title=str(config['title']),
        g25_line=g25_line,
        reference_profiles=profiles,
        group_map={label: label for label in profiles},
        mode_label='Region',
        summary_lines=summary_lines,
    )


def _render_population_view_visualization(
    view_action: str,
    output_path: Path,
    *,
    sample_point: tuple[int, int] | None = None,
    g25_line: str | None = None,
    summary_lines: tuple[str, ...] = (),
) -> None:
    if g25_line is None:
        _legacy_render_population_view_visualization(
            view_action,
            output_path,
            sample_point=sample_point or (450, 225),
            summary_lines=summary_lines,
        )
        return
    if render_coordinate_space_png is None:
        raise RuntimeError('Coordinate Space visualization renderer is unavailable. Install Pillow and numpy.')

    config = _POPULATION_VIEW_CONFIGS[view_action]
    render_coordinate_space_png(
        output_path,
        title=str(config['title']),
        g25_line=g25_line,
        reference_profiles=_population_view_profiles()[view_action],
        group_map=_population_view_group_map(view_action),
        label_formatter=_population_label_text,
        mode_label='Population',
        summary_lines=summary_lines,
    )


async def show_coordinate_space_menu(message, *, edit_existing: bool = False, lang: str = 'ru') -> None:
    text = ready_made_spaces_text(lang=lang)
    markup = build_ready_made_spaces_keyboard(lang=lang)
    if edit_existing:
        await message.edit_text(text, reply_markup=markup, parse_mode="HTML")
    else:
        await message.reply_text(text, reply_markup=markup, parse_mode="HTML", do_quote=False)


async def show_ready_made_spaces_menu(message, *, edit_existing: bool = False, lang: str = 'ru') -> None:
    text = ready_made_spaces_text(lang=lang)
    markup = build_ready_made_spaces_keyboard(lang=lang)
    if edit_existing:
        await message.edit_text(text, reply_markup=markup, parse_mode="HTML")
    else:
        await message.reply_text(text, reply_markup=markup, parse_mode="HTML", do_quote=False)


async def show_coordinate_space_stub(
    message,
    *,
    title: str,
    back_callback: str,
    edit_existing: bool = False,
    lang: str = 'ru',
) -> None:
    text = coordinate_space_stub_text(title, lang=lang)
    markup = build_coordinate_space_stub_keyboard(back_callback=back_callback, lang=lang)
    if edit_existing:
        await message.edit_text(text, reply_markup=markup)
    else:
        await message.reply_text(text, reply_markup=markup, do_quote=False)


async def show_global_sample_picker(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    source: str | None = None,
    edit_existing: bool = False,
    lang: str = 'ru',
) -> None:
    items = _list_ready_samples_for_source(_my_data_store(context), user_id, source)
    text = global_sample_picker_text(items, source=source, lang=lang)
    markup = build_global_sample_picker_keyboard(items, source=source, lang=lang)
    if edit_existing:
        await message.edit_text(text, reply_markup=markup, parse_mode="HTML")
    else:
        await message.reply_text(text, reply_markup=markup, parse_mode="HTML", do_quote=False)


async def show_west_eurasia_sample_picker(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    source: str | None = None,
    edit_existing: bool = False,
    lang: str = 'ru',
) -> None:
    items = _list_ready_samples_for_source(_my_data_store(context), user_id, source)
    text = west_eurasia_sample_picker_text(items, source=source, lang=lang)
    markup = build_west_eurasia_sample_picker_keyboard(items, source=source, lang=lang)
    if edit_existing:
        await message.edit_text(text, reply_markup=markup, parse_mode="HTML")
    else:
        await message.reply_text(text, reply_markup=markup, parse_mode="HTML", do_quote=False)


async def show_configured_space_sample_picker(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    space_action: str,
    source: str | None = None,
    edit_existing: bool = False,
    lang: str = 'ru',
) -> None:
    items = _list_ready_samples_for_source(_my_data_store(context), user_id, source)
    title = _ALL_CONFIGURED_SPACES[space_action]['title']
    text = configured_space_sample_picker_text(title, items, source=source, lang=lang)
    markup = build_configured_space_sample_picker_keyboard(space_action, items, source=source, lang=lang)
    if edit_existing:
        await message.edit_text(text, reply_markup=markup, parse_mode="HTML")
    else:
        await message.reply_text(text, reply_markup=markup, parse_mode="HTML", do_quote=False)


async def show_caucasus_detail_sample_picker(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    detail_action: str,
    mode: str = 'clusters',
    source: str | None = None,
    edit_existing: bool = False,
    lang: str = 'ru',
) -> None:
    items = _list_ready_samples_for_source(_my_data_store(context), user_id, source)
    text = configured_space_sample_picker_text(_CAUCASUS_DETAIL_BRANCH_CONFIGS[detail_action]['title'], items, source=source, lang=lang)
    markup = build_caucasus_detail_sample_picker_keyboard(detail_action, items, mode=mode, source=source, lang=lang)
    if edit_existing:
        await message.edit_text(text, reply_markup=markup)
    else:
        await message.reply_text(text, reply_markup=markup, do_quote=False)


async def show_caucasus_steppe_population_sample_picker(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    source: str | None = None,
    edit_existing: bool = False,
    lang: str = 'ru',
) -> None:
    items = _list_ready_samples_for_source(_my_data_store(context), user_id, source)
    text = configured_space_sample_picker_text('Caucasus / Steppe', items, source=source, lang=lang)
    markup = build_caucasus_steppe_population_sample_picker_keyboard(items, source=source, lang=lang)
    if edit_existing:
        await message.edit_text(text, reply_markup=markup)
    else:
        await message.reply_text(text, reply_markup=markup, do_quote=False)


async def show_europe_detail_sample_picker(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    detail_action: str,
    mode: str = 'clusters',
    source: str | None = None,
    edit_existing: bool = False,
    lang: str = 'ru',
) -> None:
    items = _list_ready_samples_for_source(_my_data_store(context), user_id, source)
    text = configured_space_sample_picker_text(_EUROPE_DETAIL_BRANCH_CONFIGS[detail_action]['title'], items, source=source, lang=lang)
    markup = build_europe_detail_sample_picker_keyboard(detail_action, items, mode=mode, source=source, lang=lang)
    if edit_existing:
        await message.edit_text(text, reply_markup=markup)
    else:
        await message.reply_text(text, reply_markup=markup, do_quote=False)


async def show_west_eurasia_detail_sample_picker(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    detail_action: str,
    mode: str = 'clusters',
    source: str | None = None,
    edit_existing: bool = False,
    lang: str = 'ru',
) -> None:
    items = _list_ready_samples_for_source(_my_data_store(context), user_id, source)
    text = configured_space_sample_picker_text(_WEST_EURASIA_DETAIL_BRANCH_CONFIGS[detail_action]['title'], items, source=source, lang=lang)
    markup = build_west_eurasia_detail_sample_picker_keyboard(detail_action, items, mode=mode, source=source, lang=lang)
    if edit_existing:
        await message.edit_text(text, reply_markup=markup)
    else:
        await message.reply_text(text, reply_markup=markup, do_quote=False)


async def show_east_eurasia_detail_sample_picker(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    detail_action: str,
    mode: str = 'clusters',
    source: str | None = None,
    edit_existing: bool = False,
    lang: str = 'ru',
) -> None:
    items = _list_ready_samples_for_source(_my_data_store(context), user_id, source)
    text = configured_space_sample_picker_text(_EAST_EURASIA_DETAIL_BRANCH_CONFIGS[detail_action]['title'], items, source=source, lang=lang)
    markup = build_east_eurasia_detail_sample_picker_keyboard(detail_action, items, mode=mode, source=source, lang=lang)
    if edit_existing:
        await message.edit_text(text, reply_markup=markup)
    else:
        await message.reply_text(text, reply_markup=markup, do_quote=False)


async def show_south_asia_detail_sample_picker(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    detail_action: str,
    mode: str = 'clusters',
    source: str | None = None,
    edit_existing: bool = False,
    lang: str = 'ru',
) -> None:
    items = _list_ready_samples_for_source(_my_data_store(context), user_id, source)
    text = configured_space_sample_picker_text(_SOUTH_ASIA_DETAIL_BRANCH_CONFIGS[detail_action]['title'], items, source=source, lang=lang)
    markup = build_south_asia_detail_sample_picker_keyboard(detail_action, items, mode=mode, source=source, lang=lang)
    if edit_existing:
        await message.edit_text(text, reply_markup=markup)
    else:
        await message.reply_text(text, reply_markup=markup, do_quote=False)


async def show_ready_made_all_populations_sample_picker(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    *,
    view_action: str,
    source: str | None = None,
    edit_existing: bool = False,
    lang: str = 'ru',
) -> None:
    items = _list_ready_samples_for_source(_my_data_store(context), user_id, source)
    text = configured_space_sample_picker_text(_READY_MADE_ALL_POPULATION_FLOWS[view_action]['title'], items, source=source, lang=lang)
    markup = build_ready_made_all_populations_sample_picker_keyboard(view_action, items, source=source, lang=lang)
    if edit_existing:
        await message.edit_text(text, reply_markup=markup)
    else:
        await message.reply_text(text, reply_markup=markup, do_quote=False)


async def show_global_result(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_id: int,
    sample_id: str,
    *,
    edit_existing: bool = False,
) -> None:
    store = _my_data_store(context)
    sample, coordinate = _resolve_space_target(store, user_id, sample_id)
    if sample is None or coordinate is None:
        await show_global_sample_picker(message, context, user_id, edit_existing=edit_existing)
        return

    region_name = _classify_global_region(coordinate.g25_line)
    sample_point = _project_global_sample_position(coordinate.g25_line)
    caption = global_result_text(sample, region_name=region_name)
    photo_caption = _coordinate_space_photo_caption(
        sample,
        coordinate.g25_line,
        _ready_made_g25_profiles()['global'],
        space_title='Global',
    )
    markup = build_global_result_keyboard(sample.asset_id)
    image_path = _create_global_visualization_path()
    try:
        _render_global_visualization(
            image_path,
            sample_point=sample_point,
            g25_line=coordinate.g25_line,
            summary_lines=tuple(caption.splitlines()),
        )
        with image_path.open('rb') as handle:
            sent = await message.reply_photo(photo=handle, caption=photo_caption, reply_markup=markup, do_quote=False)
        _set_active_menu_message(context, chat_id, user_id, sent.message_id)
        try:
            await message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
    except Exception:
        if edit_existing:
            await message.edit_text(caption, reply_markup=markup)
        else:
            await message.reply_text(caption, reply_markup=markup, do_quote=False)
    finally:
        try:
            image_path.unlink()
        except FileNotFoundError:
            pass


async def show_ready_made_all_populations_result(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_id: int,
    sample_id: str,
    *,
    view_action: str,
    edit_existing: bool = False,
) -> None:
    store = _my_data_store(context)
    sample, coordinate = _resolve_space_target(store, user_id, sample_id)
    if sample is None or coordinate is None:
        await show_ready_made_all_populations_sample_picker(
            message,
            context,
            user_id,
            view_action=view_action,
            edit_existing=edit_existing,
        )
        return

    rankers = {
        'ready_made_west_eurasia_all_populations': _rank_west_eurasia_all_populations,
        'ready_made_europe_all_populations': _rank_europe_all_populations,
        'ready_made_south_asia_all_populations': _rank_south_asia_all_populations,
        'ready_made_east_eurasia_all_populations': _rank_east_eurasia_all_populations,
        'ready_made_caucasus_steppe_all_populations': _rank_caucasus_steppe_all_populations,
    }
    top_populations = rankers[view_action](coordinate.g25_line)
    caption = ready_made_all_populations_result_text(sample, top_populations=top_populations)
    photo_caption = _coordinate_space_photo_caption(
        sample,
        coordinate.g25_line,
        _population_view_profiles()[view_action],
        space_title=str(_POPULATION_VIEW_CONFIGS[view_action]['title']),
        mode='population',
        group_map=_population_view_group_map(view_action),
        label_formatter=_population_label_text,
    )
    markup = build_ready_made_all_populations_result_keyboard(view_action, sample.asset_id)
    image_path = _create_global_visualization_path()
    try:
        sample_point = _project_population_view_position(view_action, coordinate.g25_line)
        _render_population_view_visualization(
            view_action,
            image_path,
            sample_point=sample_point,
            g25_line=coordinate.g25_line,
            summary_lines=tuple(caption.splitlines()),
        )
        with image_path.open('rb') as handle:
            sent = await message.reply_photo(photo=handle, caption=photo_caption, reply_markup=markup, do_quote=False)
        _set_active_menu_message(context, chat_id, user_id, sent.message_id)
        try:
            await message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
    except Exception:
        if edit_existing:
            await message.edit_text(caption, reply_markup=markup)
        else:
            await message.reply_text(caption, reply_markup=markup, do_quote=False)
    finally:
        try:
            image_path.unlink()
        except FileNotFoundError:
            pass


async def show_north_caucasus_detail_result(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_id: int,
    sample_id: str,
    *,
    mode: str = 'clusters',
    edit_existing: bool = False,
) -> None:
    await show_caucasus_detail_branch_result(
        message,
        context,
        chat_id,
        user_id,
        sample_id,
        detail_action='north_caucasus_detail',
        mode=mode,
        edit_existing=edit_existing,
    )


async def show_south_caucasus_detail_result(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_id: int,
    sample_id: str,
    *,
    mode: str = 'clusters',
    edit_existing: bool = False,
) -> None:
    await show_caucasus_detail_branch_result(
        message,
        context,
        chat_id,
        user_id,
        sample_id,
        detail_action='south_caucasus_detail',
        mode=mode,
        edit_existing=edit_existing,
    )


async def show_steppe_fringe_detail_result(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_id: int,
    sample_id: str,
    *,
    mode: str = 'clusters',
    edit_existing: bool = False,
) -> None:
    await show_caucasus_detail_branch_result(
        message,
        context,
        chat_id,
        user_id,
        sample_id,
        detail_action='steppe_fringe_detail',
        mode=mode,
        edit_existing=edit_existing,
    )


async def show_caucasus_detail_branch_result(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_id: int,
    sample_id: str,
    *,
    detail_action: str,
    mode: str = 'clusters',
    edit_existing: bool = False,
) -> None:
    store = _my_data_store(context)
    sample, coordinate = _resolve_space_target(store, user_id, sample_id)
    if sample is None or coordinate is None:
        await show_caucasus_detail_sample_picker(
            message,
            context,
            user_id,
            detail_action=detail_action,
            mode=mode,
            edit_existing=edit_existing,
        )
        return

    if detail_action == 'north_caucasus_detail':
        region_name = _classify_north_caucasus_region(coordinate.g25_line)
        top_populations = _rank_north_caucasus_populations(coordinate.g25_line)
    elif detail_action == 'south_caucasus_detail':
        region_name = _classify_south_caucasus_region(coordinate.g25_line)
        top_populations = _rank_south_caucasus_populations(coordinate.g25_line)
    else:
        region_name = _classify_steppe_fringe_region(coordinate.g25_line)
        top_populations = _rank_steppe_fringe_populations(coordinate.g25_line)
    caption = caucasus_detail_result_text(
        sample,
        region_name=region_name,
        top_populations=top_populations,
    )
    photo_caption = _coordinate_space_photo_caption(
        sample,
        coordinate.g25_line,
        _population_view_profiles()[detail_action] if mode == 'populations' else _ready_made_g25_profiles()[detail_action],
        space_title=str(_DETAIL_CONFIGURED_SPACES[detail_action]['title']),
        mode='population' if mode == 'populations' else 'region',
        group_map=_population_view_group_map(detail_action) if mode == 'populations' else None,
        label_formatter=_population_label_text if mode == 'populations' else None,
    )
    markup = build_caucasus_detail_result_keyboard(detail_action, sample.asset_id, mode=mode)
    image_path = _create_global_visualization_path()
    try:
        if mode == 'populations':
            sample_point = _project_population_view_position(detail_action, coordinate.g25_line)
            _render_population_view_visualization(
                detail_action,
                image_path,
                sample_point=sample_point,
                g25_line=coordinate.g25_line,
                summary_lines=tuple(caption.splitlines()),
            )
        else:
            sample_point = _project_configured_space_position(detail_action, coordinate.g25_line)
            _render_configured_space_visualization(
                image_path,
                space_action=detail_action,
                sample_point=sample_point,
                g25_line=coordinate.g25_line,
                summary_lines=tuple(caption.splitlines()),
            )
        with image_path.open('rb') as handle:
            sent = await message.reply_photo(photo=handle, caption=photo_caption, reply_markup=markup, do_quote=False)
        _set_active_menu_message(context, chat_id, user_id, sent.message_id)
        try:
            await message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
    except Exception:
        if edit_existing:
            await message.edit_text(caption, reply_markup=markup)
        else:
            await message.reply_text(caption, reply_markup=markup, do_quote=False)
    finally:
        try:
            image_path.unlink()
        except FileNotFoundError:
            pass


async def show_caucasus_steppe_all_populations_result(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_id: int,
    sample_id: str,
    *,
    edit_existing: bool = False,
) -> None:
    store = _my_data_store(context)
    sample, coordinate = _resolve_space_target(store, user_id, sample_id)
    if sample is None or coordinate is None:
        await show_caucasus_steppe_population_sample_picker(message, context, user_id, edit_existing=edit_existing)
        return

    top_populations = _rank_caucasus_steppe_all_populations(coordinate.g25_line)
    caption = caucasus_steppe_all_populations_result_text(sample, top_populations=top_populations)
    photo_caption = _coordinate_space_photo_caption(
        sample,
        coordinate.g25_line,
        _population_view_profiles()['ready_made_caucasus_steppe_all_populations'],
        space_title='Caucasus / Steppe',
        mode='population',
        group_map=_population_view_group_map('ready_made_caucasus_steppe_all_populations'),
        label_formatter=_population_label_text,
    )
    markup = build_caucasus_steppe_all_populations_result_keyboard(sample.asset_id)
    image_path = _create_global_visualization_path()
    try:
        sample_point = _project_population_view_position('ready_made_caucasus_steppe_all_populations', coordinate.g25_line)
        _render_population_view_visualization(
            'ready_made_caucasus_steppe_all_populations',
            image_path,
            sample_point=sample_point,
            g25_line=coordinate.g25_line,
            summary_lines=tuple(caption.splitlines()),
        )
        with image_path.open('rb') as handle:
            sent = await message.reply_photo(photo=handle, caption=photo_caption, reply_markup=markup, do_quote=False)
        _set_active_menu_message(context, chat_id, user_id, sent.message_id)
        try:
            await message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
    except Exception:
        if edit_existing:
            await message.edit_text(caption, reply_markup=markup)
        else:
            await message.reply_text(caption, reply_markup=markup, do_quote=False)
    finally:
        try:
            image_path.unlink()
        except FileNotFoundError:
            pass


async def show_west_eurasia_europe_detail_result(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_id: int,
    sample_id: str,
    *,
    mode: str = 'clusters',
    edit_existing: bool = False,
) -> None:
    await show_west_eurasia_detail_branch_result(
        message,
        context,
        chat_id,
        user_id,
        sample_id,
        detail_action='west_eurasia_europe_detail',
        mode=mode,
        edit_existing=edit_existing,
    )


async def show_west_eurasia_caucasus_detail_result(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_id: int,
    sample_id: str,
    *,
    mode: str = 'clusters',
    edit_existing: bool = False,
) -> None:
    await show_west_eurasia_detail_branch_result(
        message,
        context,
        chat_id,
        user_id,
        sample_id,
        detail_action='west_eurasia_caucasus_detail',
        mode=mode,
        edit_existing=edit_existing,
    )


async def show_west_eurasia_anatolia_detail_result(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_id: int,
    sample_id: str,
    *,
    mode: str = 'clusters',
    edit_existing: bool = False,
) -> None:
    await show_west_eurasia_detail_branch_result(
        message,
        context,
        chat_id,
        user_id,
        sample_id,
        detail_action='west_eurasia_anatolia_detail',
        mode=mode,
        edit_existing=edit_existing,
    )


async def show_west_eurasia_levant_detail_result(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_id: int,
    sample_id: str,
    *,
    mode: str = 'clusters',
    edit_existing: bool = False,
) -> None:
    await show_west_eurasia_detail_branch_result(
        message,
        context,
        chat_id,
        user_id,
        sample_id,
        detail_action='west_eurasia_levant_detail',
        mode=mode,
        edit_existing=edit_existing,
    )


async def show_west_eurasia_mesopotamia_iran_detail_result(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_id: int,
    sample_id: str,
    *,
    mode: str = 'clusters',
    edit_existing: bool = False,
) -> None:
    await show_west_eurasia_detail_branch_result(
        message,
        context,
        chat_id,
        user_id,
        sample_id,
        detail_action='west_eurasia_mesopotamia_iran_detail',
        mode=mode,
        edit_existing=edit_existing,
    )


async def show_west_eurasia_steppe_detail_result(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_id: int,
    sample_id: str,
    *,
    mode: str = 'clusters',
    edit_existing: bool = False,
) -> None:
    await show_west_eurasia_detail_branch_result(
        message,
        context,
        chat_id,
        user_id,
        sample_id,
        detail_action='west_eurasia_steppe_detail',
        mode=mode,
        edit_existing=edit_existing,
    )


async def show_northeast_asia_detail_result(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_id: int,
    sample_id: str,
    *,
    mode: str = 'clusters',
    edit_existing: bool = False,
) -> None:
    await show_east_eurasia_detail_branch_result(
        message,
        context,
        chat_id,
        user_id,
        sample_id,
        detail_action='northeast_asia_detail',
        mode=mode,
        edit_existing=edit_existing,
    )


async def show_north_china_detail_result(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_id: int,
    sample_id: str,
    *,
    mode: str = 'clusters',
    edit_existing: bool = False,
) -> None:
    await show_east_eurasia_detail_branch_result(
        message,
        context,
        chat_id,
        user_id,
        sample_id,
        detail_action='north_china_detail',
        mode=mode,
        edit_existing=edit_existing,
    )


async def show_south_china_detail_result(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_id: int,
    sample_id: str,
    *,
    mode: str = 'clusters',
    edit_existing: bool = False,
) -> None:
    await show_east_eurasia_detail_branch_result(
        message,
        context,
        chat_id,
        user_id,
        sample_id,
        detail_action='south_china_detail',
        mode=mode,
        edit_existing=edit_existing,
    )


async def show_siberia_inner_asia_detail_result(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_id: int,
    sample_id: str,
    *,
    mode: str = 'clusters',
    edit_existing: bool = False,
) -> None:
    await show_east_eurasia_detail_branch_result(
        message,
        context,
        chat_id,
        user_id,
        sample_id,
        detail_action='siberia_inner_asia_detail',
        mode=mode,
        edit_existing=edit_existing,
    )


async def show_northwest_south_asia_detail_result(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_id: int,
    sample_id: str,
    *,
    mode: str = 'clusters',
    edit_existing: bool = False,
) -> None:
    await show_south_asia_detail_branch_result(
        message,
        context,
        chat_id,
        user_id,
        sample_id,
        detail_action='northwest_south_asia_detail',
        mode=mode,
        edit_existing=edit_existing,
    )


async def show_gangetic_north_india_detail_result(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_id: int,
    sample_id: str,
    *,
    mode: str = 'clusters',
    edit_existing: bool = False,
) -> None:
    await show_south_asia_detail_branch_result(
        message,
        context,
        chat_id,
        user_id,
        sample_id,
        detail_action='gangetic_north_india_detail',
        mode=mode,
        edit_existing=edit_existing,
    )


async def show_west_india_detail_result(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_id: int,
    sample_id: str,
    *,
    mode: str = 'clusters',
    edit_existing: bool = False,
) -> None:
    await show_south_asia_detail_branch_result(
        message,
        context,
        chat_id,
        user_id,
        sample_id,
        detail_action='west_india_detail',
        mode=mode,
        edit_existing=edit_existing,
    )


async def show_south_india_detail_result(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_id: int,
    sample_id: str,
    *,
    mode: str = 'clusters',
    edit_existing: bool = False,
) -> None:
    await show_south_asia_detail_branch_result(
        message,
        context,
        chat_id,
        user_id,
        sample_id,
        detail_action='south_india_detail',
        mode=mode,
        edit_existing=edit_existing,
    )


async def show_east_india_bengal_detail_result(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_id: int,
    sample_id: str,
    *,
    mode: str = 'clusters',
    edit_existing: bool = False,
) -> None:
    await show_south_asia_detail_branch_result(
        message,
        context,
        chat_id,
        user_id,
        sample_id,
        detail_action='east_india_bengal_detail',
        mode=mode,
        edit_existing=edit_existing,
    )


async def show_west_eurasia_result(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_id: int,
    sample_id: str,
    *,
    edit_existing: bool = False,
) -> None:
    store = _my_data_store(context)
    sample, coordinate = _resolve_space_target(store, user_id, sample_id)
    if sample is None or coordinate is None:
        await show_west_eurasia_sample_picker(message, context, user_id, edit_existing=edit_existing)
        return

    region_name = _classify_west_eurasia_region(coordinate.g25_line)
    sample_point = _project_west_eurasia_sample_position(coordinate.g25_line)
    caption = west_eurasia_result_text(sample, region_name=region_name)
    photo_caption = _coordinate_space_photo_caption(
        sample,
        coordinate.g25_line,
        _ready_made_g25_profiles()['west_eurasia'],
        space_title='West Eurasia',
    )
    markup = build_west_eurasia_result_keyboard(sample.asset_id)
    image_path = _create_global_visualization_path()
    try:
        _render_west_eurasia_visualization(
            image_path,
            sample_point=sample_point,
            g25_line=coordinate.g25_line,
            summary_lines=tuple(caption.splitlines()),
        )
        with image_path.open('rb') as handle:
            sent = await message.reply_photo(photo=handle, caption=photo_caption, reply_markup=markup, do_quote=False)
        _set_active_menu_message(context, chat_id, user_id, sent.message_id)
        try:
            await message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
    except Exception:
        if edit_existing:
            await message.edit_text(caption, reply_markup=markup)
        else:
            await message.reply_text(caption, reply_markup=markup, do_quote=False)
    finally:
        try:
            image_path.unlink()
        except FileNotFoundError:
            pass


def global_menu_text() -> str:
    return _mode_screen_text('Global')


def build_global_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(_whole_region_label(), callback_data=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:global_region_mode')],
            _back_cancel_row(f'{COORDINATE_SPACE_CALLBACK_PREFIX}:ready_made_spaces'),
        ]
    )


def build_global_sample_picker_keyboard(
    items: list[tuple[SampleAsset, CoordinateAsset]],
    *,
    source: str | None = None,
    lang: str = 'ru',
) -> InlineKeyboardMarkup:
    return _build_coordinate_space_target_picker_keyboard('global_sample', items, source=source, lang=lang)


def build_west_eurasia_sample_picker_keyboard(
    items: list[tuple[SampleAsset, CoordinateAsset]],
    *,
    source: str | None = None,
    lang: str = 'ru',
) -> InlineKeyboardMarkup:
    return _build_coordinate_space_target_picker_keyboard('we_sample', items, source=source, lang=lang)


def build_global_result_keyboard(sample_id: str, *, source: str | None = None) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(_save_report_label(), callback_data=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:global_save:{sample_id}')],
            [InlineKeyboardButton(_change_g25_label(), callback_data=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:ready_made_global_change')],
            _back_cancel_row(_target_list_back_callback('global_sample', sample_id, source=source)),
        ]
    )


def build_west_eurasia_result_keyboard(sample_id: str, *, source: str | None = None) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(_save_report_label(), callback_data=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:west_eurasia_save:{sample_id}')],
            [InlineKeyboardButton(_change_g25_label(), callback_data=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:ready_made_west_eurasia_change')],
            _back_cancel_row(_target_list_back_callback('we_sample', sample_id, source=source)),
        ]
    )


def build_ready_made_all_populations_sample_picker_keyboard(
    view_action: str,
    items: list[tuple[SampleAsset, CoordinateAsset]],
    *,
    source: str | None = None,
    lang: str = 'ru',
) -> InlineKeyboardMarkup:
    flow = _READY_MADE_ALL_POPULATION_FLOWS[view_action]
    return _build_coordinate_space_target_picker_keyboard(flow['sample_root'], items, source=source, lang=lang)


def build_ready_made_all_populations_result_keyboard(
    view_action: str,
    sample_id: str,
    *,
    source: str | None = None,
) -> InlineKeyboardMarkup:
    config = _POPULATION_VIEW_CONFIGS[view_action]
    flow = _READY_MADE_ALL_POPULATION_FLOWS[view_action]
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(_save_report_label(), callback_data=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:{config["save_root"]}:{sample_id}')],
            [InlineKeyboardButton(_change_g25_label(), callback_data=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:{config["change_action"]}')],
            _back_cancel_row(_target_list_back_callback(flow['sample_root'], sample_id, source=source)),
        ]
    )


def build_configured_space_sample_picker_keyboard(
    space_action: str,
    items: list[tuple[SampleAsset, CoordinateAsset]],
    *,
    source: str | None = None,
    lang: str = 'ru',
) -> InlineKeyboardMarkup:
    config = _ALL_CONFIGURED_SPACES[space_action]
    space_code = config['code']
    return _build_coordinate_space_target_picker_keyboard(f'{space_code}_sample', items, source=source, lang=lang)


def build_configured_space_result_keyboard(
    space_action: str,
    sample_id: str,
    *,
    source: str | None = None,
) -> InlineKeyboardMarkup:
    config = _ALL_CONFIGURED_SPACES[space_action]
    space_code = config['code']
    sample_root = f'{space_code}_sample'
    broad_result_back = {
        'ready_made_europe': f'{COORDINATE_SPACE_CALLBACK_PREFIX}:ready_made_spaces',
        'ready_made_caucasus_steppe': f'{COORDINATE_SPACE_CALLBACK_PREFIX}:ready_made_spaces',
        'ready_made_south_asia': f'{COORDINATE_SPACE_CALLBACK_PREFIX}:ready_made_spaces',
        'ready_made_east_eurasia': f'{COORDINATE_SPACE_CALLBACK_PREFIX}:ready_made_spaces',
    }
    if space_action in broad_result_back:
        return InlineKeyboardMarkup(
            [
                [InlineKeyboardButton(_save_report_label(), callback_data=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:{space_code}_save:{sample_id}')],
                [InlineKeyboardButton(_change_g25_label(), callback_data=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:{space_action}_change')],
                _back_cancel_row(_target_list_back_callback(sample_root, sample_id, source=source)),
            ]
        )
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(_save_report_label(), callback_data=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:{space_code}_save:{sample_id}')],
            [InlineKeyboardButton(_change_g25_label(), callback_data=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:{space_action}_change')],
            _back_cancel_row(_target_list_back_callback(sample_root, sample_id, source=source)),
        ]
    )


def build_region_branch_mode_keyboard(
    branch_configs: dict[str, dict[str, str]],
    detail_action: str,
    *,
    back_callback: str,
) -> InlineKeyboardMarkup:
    branch = branch_configs[detail_action]
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(_whole_region_label(), callback_data=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:{branch["region_mode_action"]}')],
            [InlineKeyboardButton(_all_populations_label(), callback_data=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:{branch["population_mode_action"]}')],
            _back_cancel_row(back_callback),
        ]
    )


def build_west_eurasia_branch_mode_keyboard(detail_action: str) -> InlineKeyboardMarkup:
    return build_region_branch_mode_keyboard(
        _WEST_EURASIA_DETAIL_BRANCH_CONFIGS,
        detail_action,
        back_callback=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:west_eurasia_detail_menu',
    )


def build_east_eurasia_branch_mode_keyboard(detail_action: str) -> InlineKeyboardMarkup:
    return build_region_branch_mode_keyboard(
        _EAST_EURASIA_DETAIL_BRANCH_CONFIGS,
        detail_action,
        back_callback=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:east_eurasia_detail_menu',
    )


def build_south_asia_branch_mode_keyboard(detail_action: str) -> InlineKeyboardMarkup:
    return build_region_branch_mode_keyboard(
        _SOUTH_ASIA_DETAIL_BRANCH_CONFIGS,
        detail_action,
        back_callback=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:south_asia_detail_menu',
    )


def build_europe_branch_mode_keyboard(detail_action: str) -> InlineKeyboardMarkup:
    return build_region_branch_mode_keyboard(
        _EUROPE_DETAIL_BRANCH_CONFIGS,
        detail_action,
        back_callback=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:europe_detail_menu',
    )


def build_west_eurasia_detail_keyboard(*, lang: str = 'ru') -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(_whole_region_label(lang), callback_data=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:west_eurasia_region_mode')],
            [InlineKeyboardButton(_all_populations_label(lang), callback_data=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:west_eurasia_all_populations_mode')],
            [InlineKeyboardButton(_visible_space_title('Europe'), callback_data=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:west_eurasia_europe_detail')],
            [InlineKeyboardButton(_visible_space_title('Caucasus'), callback_data=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:west_eurasia_caucasus_detail')],
            [InlineKeyboardButton(_visible_space_title('Anatolia'), callback_data=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:west_eurasia_anatolia_detail')],
            [InlineKeyboardButton(_visible_space_title('Levant'), callback_data=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:west_eurasia_levant_detail')],
            [InlineKeyboardButton(_visible_space_title('Mesopotamia / Iran'), callback_data=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:west_eurasia_mesopotamia_iran_detail')],
            [InlineKeyboardButton(_visible_space_title('Steppe'), callback_data=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:west_eurasia_steppe_detail')],
            [
                InlineKeyboardButton(_back_label(lang), callback_data=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:ready_made_spaces'),
                InlineKeyboardButton(_cancel_label(lang), callback_data=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:cancel'),
            ],
        ]
    )


def build_east_eurasia_detail_keyboard(*, lang: str = 'ru') -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(_whole_region_label(lang), callback_data=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:east_eurasia_region_mode')],
            [InlineKeyboardButton(_all_populations_label(lang), callback_data=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:east_eurasia_all_populations_mode')],
            [InlineKeyboardButton(_visible_space_title('Northeast Asia'), callback_data=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:northeast_asia_detail')],
            [InlineKeyboardButton(_visible_space_title('North China'), callback_data=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:north_china_detail')],
            [InlineKeyboardButton(_visible_space_title('South China'), callback_data=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:south_china_detail')],
            [InlineKeyboardButton(_visible_space_title('Siberia / Inner Asia'), callback_data=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:siberia_inner_asia_detail')],
            [
                InlineKeyboardButton(_back_label(lang), callback_data=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:ready_made_spaces'),
                InlineKeyboardButton(_cancel_label(lang), callback_data=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:cancel'),
            ],
        ]
    )


def build_south_asia_detail_keyboard(*, lang: str = 'ru') -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(_whole_region_label(lang), callback_data=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:south_asia_region_mode')],
            [InlineKeyboardButton(_all_populations_label(lang), callback_data=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:south_asia_all_populations_mode')],
            [InlineKeyboardButton(_visible_space_title('Northwest South Asia'), callback_data=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:northwest_south_asia_detail')],
            [InlineKeyboardButton(_visible_space_title('Gangetic / North India'), callback_data=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:gangetic_north_india_detail')],
            [InlineKeyboardButton(_visible_space_title('West India'), callback_data=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:west_india_detail')],
            [InlineKeyboardButton(_visible_space_title('South India'), callback_data=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:south_india_detail')],
            [InlineKeyboardButton(_visible_space_title('East India / Bengal'), callback_data=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:east_india_bengal_detail')],
            [
                InlineKeyboardButton(_back_label(lang), callback_data=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:ready_made_spaces'),
                InlineKeyboardButton(_cancel_label(lang), callback_data=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:cancel'),
            ],
        ]
    )


def build_europe_detail_keyboard(*, lang: str = 'ru') -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(_whole_region_label(lang), callback_data=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:europe_region_mode')],
            [InlineKeyboardButton(_all_populations_label(lang), callback_data=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:europe_all_populations_mode')],
            [InlineKeyboardButton(_visible_space_title('East Europe'), callback_data=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:east_europe_detail')],
            [InlineKeyboardButton(_visible_space_title('North Europe'), callback_data=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:north_europe_detail')],
            [InlineKeyboardButton(_visible_space_title('South Europe'), callback_data=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:south_europe_detail')],
            [InlineKeyboardButton(_visible_space_title('Balkans'), callback_data=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:balkans_detail')],
            [InlineKeyboardButton(_visible_space_title('Baltic'), callback_data=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:baltic_detail')],
            [
                InlineKeyboardButton(_back_label(lang), callback_data=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:ready_made_spaces'),
                InlineKeyboardButton(_cancel_label(lang), callback_data=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:cancel'),
            ],
        ]
    )


def build_europe_detail_sample_picker_keyboard(
    detail_action: str,
    items: list[tuple[SampleAsset, CoordinateAsset]],
    *,
    mode: str = 'clusters',
    source: str | None = None,
    lang: str = 'ru',
) -> InlineKeyboardMarkup:
    branch = _EUROPE_DETAIL_BRANCH_CONFIGS[detail_action]
    root_action = branch['population_sample_root'] if mode == 'populations' else branch['sample_root']
    return _build_coordinate_space_target_picker_keyboard(root_action, items, source=source, lang=lang)


def build_east_eurasia_detail_sample_picker_keyboard(
    detail_action: str,
    items: list[tuple[SampleAsset, CoordinateAsset]],
    *,
    mode: str = 'clusters',
    source: str | None = None,
    lang: str = 'ru',
) -> InlineKeyboardMarkup:
    branch = _EAST_EURASIA_DETAIL_BRANCH_CONFIGS[detail_action]
    root_action = branch['population_sample_root'] if mode == 'populations' else branch['sample_root']
    return _build_coordinate_space_target_picker_keyboard(root_action, items, source=source, lang=lang)


def build_west_eurasia_detail_sample_picker_keyboard(
    detail_action: str,
    items: list[tuple[SampleAsset, CoordinateAsset]],
    *,
    mode: str = 'clusters',
    source: str | None = None,
    lang: str = 'ru',
) -> InlineKeyboardMarkup:
    branch = _WEST_EURASIA_DETAIL_BRANCH_CONFIGS[detail_action]
    root_action = branch['population_sample_root'] if mode == 'populations' else branch['sample_root']
    return _build_coordinate_space_target_picker_keyboard(root_action, items, source=source, lang=lang)


def build_south_asia_detail_sample_picker_keyboard(
    detail_action: str,
    items: list[tuple[SampleAsset, CoordinateAsset]],
    *,
    mode: str = 'clusters',
    source: str | None = None,
    lang: str = 'ru',
) -> InlineKeyboardMarkup:
    branch = _SOUTH_ASIA_DETAIL_BRANCH_CONFIGS[detail_action]
    root_action = branch['population_sample_root'] if mode == 'populations' else branch['sample_root']
    return _build_coordinate_space_target_picker_keyboard(root_action, items, source=source, lang=lang)


def build_europe_detail_result_keyboard(
    detail_action: str,
    sample_id: str,
    *,
    mode: str = 'clusters',
    source: str | None = None,
) -> InlineKeyboardMarkup:
    branch = _EUROPE_DETAIL_BRANCH_CONFIGS[detail_action]
    save_root = f'{branch["save_root"]}p' if mode == 'populations' else branch['save_root']
    sample_root = branch['population_sample_root'] if mode == 'populations' else branch['sample_root']
    back_callback = _target_list_back_callback(sample_root, sample_id, source=source)
    change_action = branch['population_change_action'] if mode == 'populations' else branch['change_action']
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(_save_report_label(), callback_data=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:{save_root}:{sample_id}')],
            [InlineKeyboardButton(_change_g25_label(), callback_data=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:{change_action}')],
            _back_cancel_row(back_callback),
        ]
    )


def build_east_europe_detail_result_keyboard(sample_id: str) -> InlineKeyboardMarkup:
    return build_europe_detail_result_keyboard('east_europe_detail', sample_id)


def build_west_eurasia_detail_result_keyboard(
    detail_action: str,
    sample_id: str,
    *,
    mode: str = 'clusters',
    source: str | None = None,
) -> InlineKeyboardMarkup:
    branch = _WEST_EURASIA_DETAIL_BRANCH_CONFIGS[detail_action]
    save_root = f'{branch["save_root"]}p' if mode == 'populations' else branch['save_root']
    sample_root = branch['population_sample_root'] if mode == 'populations' else branch['sample_root']
    back_callback = _target_list_back_callback(sample_root, sample_id, source=source)
    change_action = branch['population_change_action'] if mode == 'populations' else branch['change_action']
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(_save_report_label(), callback_data=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:{save_root}:{sample_id}')],
            [InlineKeyboardButton(_change_g25_label(), callback_data=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:{change_action}')],
            _back_cancel_row(back_callback),
        ]
    )


def build_east_eurasia_detail_result_keyboard(
    detail_action: str,
    sample_id: str,
    *,
    mode: str = 'clusters',
    source: str | None = None,
) -> InlineKeyboardMarkup:
    branch = _EAST_EURASIA_DETAIL_BRANCH_CONFIGS[detail_action]
    save_root = f'{branch["save_root"]}p' if mode == 'populations' else branch['save_root']
    sample_root = branch['population_sample_root'] if mode == 'populations' else branch['sample_root']
    back_callback = _target_list_back_callback(sample_root, sample_id, source=source)
    change_action = branch['population_change_action'] if mode == 'populations' else branch['change_action']
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(_save_report_label(), callback_data=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:{save_root}:{sample_id}')],
            [InlineKeyboardButton(_change_g25_label(), callback_data=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:{change_action}')],
            _back_cancel_row(back_callback),
        ]
    )


def build_south_asia_detail_result_keyboard(
    detail_action: str,
    sample_id: str,
    *,
    mode: str = 'clusters',
    source: str | None = None,
) -> InlineKeyboardMarkup:
    branch = _SOUTH_ASIA_DETAIL_BRANCH_CONFIGS[detail_action]
    save_root = f'{branch["save_root"]}p' if mode == 'populations' else branch['save_root']
    sample_root = branch['population_sample_root'] if mode == 'populations' else branch['sample_root']
    back_callback = _target_list_back_callback(sample_root, sample_id, source=source)
    change_action = branch['population_change_action'] if mode == 'populations' else branch['change_action']
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(_save_report_label(), callback_data=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:{save_root}:{sample_id}')],
            [InlineKeyboardButton(_change_g25_label(), callback_data=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:{change_action}')],
            _back_cancel_row(back_callback),
        ]
    )


async def show_global_menu(message, *, edit_existing: bool = False) -> None:
    text = global_menu_text()
    markup = build_global_menu_keyboard()
    if edit_existing:
        await message.edit_text(text, reply_markup=markup)
    else:
        await message.reply_text(text, reply_markup=markup, do_quote=False)


async def show_west_eurasia_detail_menu(message, *, edit_existing: bool = False, lang: str = 'ru') -> None:
    text = west_eurasia_detail_text(lang=lang)
    markup = build_west_eurasia_detail_keyboard(lang=lang)
    if edit_existing:
        await message.edit_text(text, reply_markup=markup, parse_mode='HTML')
    else:
        await message.reply_text(text, reply_markup=markup, parse_mode='HTML', do_quote=False)


async def show_europe_detail_menu(message, *, edit_existing: bool = False, lang: str = 'ru') -> None:
    text = europe_detail_text(lang=lang)
    markup = build_europe_detail_keyboard(lang=lang)
    if edit_existing:
        await message.edit_text(text, reply_markup=markup, parse_mode='HTML')
    else:
        await message.reply_text(text, reply_markup=markup, parse_mode='HTML', do_quote=False)


async def show_caucasus_detail_menu(message, *, edit_existing: bool = False, lang: str = 'ru') -> None:
    text = caucasus_detail_text(lang=lang)
    markup = build_caucasus_detail_keyboard(lang=lang)
    if edit_existing:
        await message.edit_text(text, reply_markup=markup, parse_mode='HTML')
    else:
        await message.reply_text(text, reply_markup=markup, parse_mode='HTML', do_quote=False)


async def show_south_asia_detail_menu(message, *, edit_existing: bool = False, lang: str = 'ru') -> None:
    text = south_asia_detail_text(lang=lang)
    markup = build_south_asia_detail_keyboard(lang=lang)
    if edit_existing:
        await message.edit_text(text, reply_markup=markup, parse_mode='HTML')
    else:
        await message.reply_text(text, reply_markup=markup, parse_mode='HTML', do_quote=False)


async def show_east_eurasia_detail_menu(message, *, edit_existing: bool = False, lang: str = 'ru') -> None:
    text = east_eurasia_detail_text(lang=lang)
    markup = build_east_eurasia_detail_keyboard(lang=lang)
    if edit_existing:
        await message.edit_text(text, reply_markup=markup, parse_mode='HTML')
    else:
        await message.reply_text(text, reply_markup=markup, parse_mode='HTML', do_quote=False)


async def show_west_eurasia_branch_menu(message, *, detail_action: str, edit_existing: bool = False) -> None:
    text = caucasus_branch_mode_text(_WEST_EURASIA_DETAIL_BRANCH_CONFIGS[detail_action]['title'])
    markup = build_west_eurasia_branch_mode_keyboard(detail_action)
    if edit_existing:
        await message.edit_text(text, reply_markup=markup)
    else:
        await message.reply_text(text, reply_markup=markup, do_quote=False)


async def show_east_eurasia_branch_menu(message, *, detail_action: str, edit_existing: bool = False) -> None:
    text = caucasus_branch_mode_text(_EAST_EURASIA_DETAIL_BRANCH_CONFIGS[detail_action]['title'])
    markup = build_east_eurasia_branch_mode_keyboard(detail_action)
    if edit_existing:
        await message.edit_text(text, reply_markup=markup)
    else:
        await message.reply_text(text, reply_markup=markup, do_quote=False)


async def show_south_asia_branch_menu(message, *, detail_action: str, edit_existing: bool = False) -> None:
    text = caucasus_branch_mode_text(_SOUTH_ASIA_DETAIL_BRANCH_CONFIGS[detail_action]['title'])
    markup = build_south_asia_branch_mode_keyboard(detail_action)
    if edit_existing:
        await message.edit_text(text, reply_markup=markup)
    else:
        await message.reply_text(text, reply_markup=markup, do_quote=False)


async def show_caucasus_branch_menu(message, *, detail_action: str, edit_existing: bool = False, lang: str = 'ru') -> None:
    text = caucasus_branch_mode_text(_CAUCASUS_DETAIL_BRANCH_CONFIGS[detail_action]['title'], lang=lang)
    markup = build_caucasus_branch_mode_keyboard(detail_action, lang=lang)
    if edit_existing:
        await message.edit_text(text, reply_markup=markup, parse_mode='HTML')
    else:
        await message.reply_text(text, reply_markup=markup, parse_mode='HTML', do_quote=False)


async def show_europe_branch_menu(message, *, detail_action: str, edit_existing: bool = False) -> None:
    text = caucasus_branch_mode_text(_EUROPE_DETAIL_BRANCH_CONFIGS[detail_action]['title'])
    markup = build_europe_branch_mode_keyboard(detail_action)
    if edit_existing:
        await message.edit_text(text, reply_markup=markup)
    else:
        await message.reply_text(text, reply_markup=markup, do_quote=False)


async def show_configured_space_result(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_id: int,
    sample_id: str,
    *,
    space_action: str,
    edit_existing: bool = False,
) -> None:
    store = _my_data_store(context)
    sample, coordinate = _resolve_space_target(store, user_id, sample_id)
    if sample is None or coordinate is None:
        await show_configured_space_sample_picker(
            message,
            context,
            user_id,
            space_action=space_action,
            edit_existing=edit_existing,
        )
        return

    region_name = _classify_configured_space_region(space_action, coordinate.g25_line)
    sample_point = _project_configured_space_position(space_action, coordinate.g25_line)
    caption = configured_space_result_text(sample, region_name=region_name)
    photo_caption = _coordinate_space_photo_caption(
        sample,
        coordinate.g25_line,
        _ready_made_g25_profiles()[space_action],
        space_title=str(_ALL_CONFIGURED_SPACES[space_action]['title']),
    )
    markup = build_configured_space_result_keyboard(space_action, sample.asset_id)
    image_path = _create_global_visualization_path()
    try:
        _render_configured_space_visualization(
            image_path,
            space_action=space_action,
            sample_point=sample_point,
            g25_line=coordinate.g25_line,
            summary_lines=tuple(caption.splitlines()),
        )
        with image_path.open('rb') as handle:
            sent = await message.reply_photo(photo=handle, caption=photo_caption, reply_markup=markup, do_quote=False)
        _set_active_menu_message(context, chat_id, user_id, sent.message_id)
        try:
            await message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
    except Exception:
        if edit_existing:
            await message.edit_text(caption, reply_markup=markup)
        else:
            await message.reply_text(caption, reply_markup=markup, do_quote=False)
    finally:
        try:
            image_path.unlink()
        except FileNotFoundError:
            pass


async def show_east_europe_detail_result(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_id: int,
    sample_id: str,
    *,
    mode: str = 'clusters',
    edit_existing: bool = False,
) -> None:
    await show_europe_detail_branch_result(
        message,
        context,
        chat_id,
        user_id,
        sample_id,
        detail_action='east_europe_detail',
        mode=mode,
        edit_existing=edit_existing,
    )


async def show_europe_detail_branch_result(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_id: int,
    sample_id: str,
    *,
    detail_action: str,
    mode: str = 'clusters',
    edit_existing: bool = False,
) -> None:
    store = _my_data_store(context)
    sample, coordinate = _resolve_space_target(store, user_id, sample_id)
    if sample is None or coordinate is None:
        await show_europe_detail_sample_picker(
            message,
            context,
            user_id,
            detail_action=detail_action,
            mode=mode,
            edit_existing=edit_existing,
        )
        return

    region_name = _classify_configured_space_region(detail_action, coordinate.g25_line)
    top_populations = _rank_east_europe_populations(coordinate.g25_line) if detail_action == 'east_europe_detail' else (
        _rank_north_europe_populations(coordinate.g25_line) if detail_action == 'north_europe_detail' else (
            _rank_south_europe_populations(coordinate.g25_line) if detail_action == 'south_europe_detail' else (
                _rank_balkans_populations(coordinate.g25_line) if detail_action == 'balkans_detail' else _rank_baltic_populations(coordinate.g25_line)
            )
        )
    )
    caption = caucasus_detail_result_text(sample, region_name=region_name, top_populations=top_populations)
    photo_caption = _coordinate_space_photo_caption(
        sample,
        coordinate.g25_line,
        _population_view_profiles()[detail_action] if mode == 'populations' else _ready_made_g25_profiles()[detail_action],
        space_title=str(_DETAIL_CONFIGURED_SPACES[detail_action]['title']),
        mode='population' if mode == 'populations' else 'region',
        group_map=_population_view_group_map(detail_action) if mode == 'populations' else None,
        label_formatter=_population_label_text if mode == 'populations' else None,
    )
    markup = build_europe_detail_result_keyboard(detail_action, sample.asset_id, mode=mode)
    image_path = _create_global_visualization_path()
    try:
        if mode == 'populations':
            sample_point = _project_population_view_position(detail_action, coordinate.g25_line)
            _render_population_view_visualization(
                detail_action,
                image_path,
                sample_point=sample_point,
                g25_line=coordinate.g25_line,
                summary_lines=tuple(caption.splitlines()),
            )
        else:
            sample_point = _project_configured_space_position(detail_action, coordinate.g25_line)
            _render_configured_space_visualization(
                image_path,
                space_action=detail_action,
                sample_point=sample_point,
                g25_line=coordinate.g25_line,
                summary_lines=tuple(caption.splitlines()),
            )
        with image_path.open('rb') as handle:
            sent = await message.reply_photo(photo=handle, caption=photo_caption, reply_markup=markup, do_quote=False)
        _set_active_menu_message(context, chat_id, user_id, sent.message_id)
        try:
            await message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
    except Exception:
        if edit_existing:
            await message.edit_text(caption, reply_markup=markup)
        else:
            await message.reply_text(caption, reply_markup=markup, do_quote=False)
    finally:
        try:
            image_path.unlink()
        except FileNotFoundError:
            pass


async def show_west_eurasia_detail_branch_result(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_id: int,
    sample_id: str,
    *,
    detail_action: str,
    mode: str = 'clusters',
    edit_existing: bool = False,
) -> None:
    store = _my_data_store(context)
    sample, coordinate = _resolve_space_target(store, user_id, sample_id)
    if sample is None or coordinate is None:
        await show_west_eurasia_detail_sample_picker(
            message,
            context,
            user_id,
            detail_action=detail_action,
            mode=mode,
            edit_existing=edit_existing,
        )
        return

    if detail_action == 'west_eurasia_europe_detail':
        region_name = _classify_west_eurasia_europe_region(coordinate.g25_line)
        top_populations = _rank_west_eurasia_europe_populations(coordinate.g25_line)
    elif detail_action == 'west_eurasia_caucasus_detail':
        region_name = _classify_west_eurasia_caucasus_region(coordinate.g25_line)
        top_populations = _rank_west_eurasia_caucasus_populations(coordinate.g25_line)
    elif detail_action == 'west_eurasia_anatolia_detail':
        region_name = _classify_west_eurasia_anatolia_region(coordinate.g25_line)
        top_populations = _rank_west_eurasia_anatolia_populations(coordinate.g25_line)
    elif detail_action == 'west_eurasia_levant_detail':
        region_name = _classify_west_eurasia_levant_region(coordinate.g25_line)
        top_populations = _rank_west_eurasia_levant_populations(coordinate.g25_line)
    elif detail_action == 'west_eurasia_mesopotamia_iran_detail':
        region_name = _classify_west_eurasia_mesopotamia_iran_region(coordinate.g25_line)
        top_populations = _rank_west_eurasia_mesopotamia_iran_populations(coordinate.g25_line)
    else:
        region_name = _classify_west_eurasia_steppe_region(coordinate.g25_line)
        top_populations = _rank_west_eurasia_steppe_populations(coordinate.g25_line)
    caption = caucasus_detail_result_text(sample, region_name=region_name, top_populations=top_populations)
    photo_caption = _coordinate_space_photo_caption(
        sample,
        coordinate.g25_line,
        _population_view_profiles()[detail_action] if mode == 'populations' else _ready_made_g25_profiles()[detail_action],
        space_title=str(_DETAIL_CONFIGURED_SPACES[detail_action]['title']),
        mode='population' if mode == 'populations' else 'region',
        group_map=_population_view_group_map(detail_action) if mode == 'populations' else None,
        label_formatter=_population_label_text if mode == 'populations' else None,
    )
    markup = build_west_eurasia_detail_result_keyboard(detail_action, sample.asset_id, mode=mode)
    image_path = _create_global_visualization_path()
    try:
        if mode == 'populations':
            sample_point = _project_population_view_position(detail_action, coordinate.g25_line)
            _render_population_view_visualization(
                detail_action,
                image_path,
                sample_point=sample_point,
                g25_line=coordinate.g25_line,
                summary_lines=tuple(caption.splitlines()),
            )
        else:
            sample_point = _project_configured_space_position(detail_action, coordinate.g25_line)
            _render_configured_space_visualization(
                image_path,
                space_action=detail_action,
                sample_point=sample_point,
                g25_line=coordinate.g25_line,
                summary_lines=tuple(caption.splitlines()),
            )
        with image_path.open('rb') as handle:
            sent = await message.reply_photo(photo=handle, caption=photo_caption, reply_markup=markup, do_quote=False)
        _set_active_menu_message(context, chat_id, user_id, sent.message_id)
        try:
            await message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
    except Exception:
        if edit_existing:
            await message.edit_text(caption, reply_markup=markup)
        else:
            await message.reply_text(caption, reply_markup=markup, do_quote=False)
    finally:
        try:
            image_path.unlink()
        except FileNotFoundError:
            pass


async def show_east_eurasia_detail_branch_result(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_id: int,
    sample_id: str,
    *,
    detail_action: str,
    mode: str = 'clusters',
    edit_existing: bool = False,
) -> None:
    store = _my_data_store(context)
    sample, coordinate = _resolve_space_target(store, user_id, sample_id)
    if sample is None or coordinate is None:
        await show_east_eurasia_detail_sample_picker(
            message,
            context,
            user_id,
            detail_action=detail_action,
            mode=mode,
            edit_existing=edit_existing,
        )
        return

    if detail_action == 'northeast_asia_detail':
        region_name = _classify_northeast_asia_region(coordinate.g25_line)
        top_populations = _rank_northeast_asia_populations(coordinate.g25_line)
    elif detail_action == 'north_china_detail':
        region_name = _classify_north_china_region(coordinate.g25_line)
        top_populations = _rank_north_china_populations(coordinate.g25_line)
    elif detail_action == 'south_china_detail':
        region_name = _classify_south_china_region(coordinate.g25_line)
        top_populations = _rank_south_china_populations(coordinate.g25_line)
    else:
        region_name = _classify_siberia_inner_asia_region(coordinate.g25_line)
        top_populations = _rank_siberia_inner_asia_populations(coordinate.g25_line)
    caption = caucasus_detail_result_text(sample, region_name=region_name, top_populations=top_populations)
    photo_caption = _coordinate_space_photo_caption(
        sample,
        coordinate.g25_line,
        _population_view_profiles()[detail_action] if mode == 'populations' else _ready_made_g25_profiles()[detail_action],
        space_title=str(_DETAIL_CONFIGURED_SPACES[detail_action]['title']),
        mode='population' if mode == 'populations' else 'region',
        group_map=_population_view_group_map(detail_action) if mode == 'populations' else None,
        label_formatter=_population_label_text if mode == 'populations' else None,
    )
    markup = build_east_eurasia_detail_result_keyboard(detail_action, sample.asset_id, mode=mode)
    image_path = _create_global_visualization_path()
    try:
        if mode == 'populations':
            sample_point = _project_population_view_position(detail_action, coordinate.g25_line)
            _render_population_view_visualization(
                detail_action,
                image_path,
                sample_point=sample_point,
                g25_line=coordinate.g25_line,
                summary_lines=tuple(caption.splitlines()),
            )
        else:
            sample_point = _project_configured_space_position(detail_action, coordinate.g25_line)
            _render_configured_space_visualization(
                image_path,
                space_action=detail_action,
                sample_point=sample_point,
                g25_line=coordinate.g25_line,
                summary_lines=tuple(caption.splitlines()),
            )
        with image_path.open('rb') as handle:
            sent = await message.reply_photo(photo=handle, caption=photo_caption, reply_markup=markup, do_quote=False)
        _set_active_menu_message(context, chat_id, user_id, sent.message_id)
        try:
            await message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
    except Exception:
        if edit_existing:
            await message.edit_text(caption, reply_markup=markup)
        else:
            await message.reply_text(caption, reply_markup=markup, do_quote=False)
    finally:
        try:
            image_path.unlink()
        except FileNotFoundError:
            pass


async def show_south_asia_detail_branch_result(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_id: int,
    sample_id: str,
    *,
    detail_action: str,
    mode: str = 'clusters',
    edit_existing: bool = False,
) -> None:
    store = _my_data_store(context)
    sample, coordinate = _resolve_space_target(store, user_id, sample_id)
    if sample is None or coordinate is None:
        await show_south_asia_detail_sample_picker(
            message,
            context,
            user_id,
            detail_action=detail_action,
            mode=mode,
            edit_existing=edit_existing,
        )
        return

    if detail_action == 'northwest_south_asia_detail':
        region_name = _classify_northwest_south_asia_region(coordinate.g25_line)
        top_populations = _rank_northwest_south_asia_populations(coordinate.g25_line)
    elif detail_action == 'gangetic_north_india_detail':
        region_name = _classify_gangetic_north_india_region(coordinate.g25_line)
        top_populations = _rank_gangetic_north_india_populations(coordinate.g25_line)
    elif detail_action == 'west_india_detail':
        region_name = _classify_west_india_region(coordinate.g25_line)
        top_populations = _rank_west_india_populations(coordinate.g25_line)
    elif detail_action == 'south_india_detail':
        region_name = _classify_south_india_region(coordinate.g25_line)
        top_populations = _rank_south_india_populations(coordinate.g25_line)
    else:
        region_name = _classify_east_india_bengal_region(coordinate.g25_line)
        top_populations = _rank_east_india_bengal_populations(coordinate.g25_line)
    caption = caucasus_detail_result_text(sample, region_name=region_name, top_populations=top_populations)
    photo_caption = _coordinate_space_photo_caption(
        sample,
        coordinate.g25_line,
        _population_view_profiles()[detail_action] if mode == 'populations' else _ready_made_g25_profiles()[detail_action],
        space_title=str(_DETAIL_CONFIGURED_SPACES[detail_action]['title']),
        mode='population' if mode == 'populations' else 'region',
        group_map=_population_view_group_map(detail_action) if mode == 'populations' else None,
        label_formatter=_population_label_text if mode == 'populations' else None,
    )
    markup = build_south_asia_detail_result_keyboard(detail_action, sample.asset_id, mode=mode)
    image_path = _create_global_visualization_path()
    try:
        if mode == 'populations':
            sample_point = _project_population_view_position(detail_action, coordinate.g25_line)
            _render_population_view_visualization(
                detail_action,
                image_path,
                sample_point=sample_point,
                g25_line=coordinate.g25_line,
                summary_lines=tuple(caption.splitlines()),
            )
        else:
            sample_point = _project_configured_space_position(detail_action, coordinate.g25_line)
            _render_configured_space_visualization(
                image_path,
                space_action=detail_action,
                sample_point=sample_point,
                g25_line=coordinate.g25_line,
                summary_lines=tuple(caption.splitlines()),
            )
        with image_path.open('rb') as handle:
            sent = await message.reply_photo(photo=handle, caption=photo_caption, reply_markup=markup, do_quote=False)
        _set_active_menu_message(context, chat_id, user_id, sent.message_id)
        try:
            await message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
    except Exception:
        if edit_existing:
            await message.edit_text(caption, reply_markup=markup)
        else:
            await message.reply_text(caption, reply_markup=markup, do_quote=False)
    finally:
        try:
            image_path.unlink()
        except FileNotFoundError:
            pass


async def coordinate_space_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None or query.message is None:
        return
    if not query.data.startswith(f'{COORDINATE_SPACE_CALLBACK_PREFIX}:'):
        return

    if not await ensure_active_main_menu(update, context):
        return

    user_id = int(update.effective_user.id) if update.effective_user is not None else None
    lang = get_user_language(context, user_id)
    action = query.data.split(':', 1)[1]
    root_action, _, payload = action.partition(':')

    if action == 'cancel':
        await query.answer()
        if _is_photo_message(query.message):
            try:
                await query.edit_message_caption(caption=_copy(lang, 'Раздел Coordinate spaces закрыт.', 'Coordinate spaces closed.'), reply_markup=None)
            except Exception:
                await query.edit_message_reply_markup(reply_markup=None)
            return
        await query.edit_message_text(_copy(lang, 'Раздел Coordinate spaces закрыт.', 'Coordinate spaces closed.'))
        return

    if action == 'root':
        await query.answer()
        if _is_photo_message(query.message):
            if update.effective_chat is None or update.effective_user is None:
                return
            await _show_menu_from_photo_message(
                query.message,
                context,
                chat_id=update.effective_chat.id,
                user_id=update.effective_user.id,
                text=ready_made_spaces_text(lang=lang),
                reply_markup=build_ready_made_spaces_keyboard(lang=lang),
            )
            return
        await show_coordinate_space_menu(query.message, edit_existing=True, lang=lang)
        return

    if action == 'ready_made_spaces':
        await query.answer()
        if _is_photo_message(query.message):
            if update.effective_chat is None or update.effective_user is None:
                return
            await _show_menu_from_photo_message(
                query.message,
                context,
                chat_id=update.effective_chat.id,
                user_id=update.effective_user.id,
                text=ready_made_spaces_text(lang=lang),
                reply_markup=build_ready_made_spaces_keyboard(lang=lang),
            )
            return
        await show_ready_made_spaces_menu(query.message, edit_existing=True, lang=lang)
        return

    if root_action == 'picksrc':
        if update.effective_user is None:
            return
        sample_root, _, source = payload.partition(':')
        source = source or None
        if not sample_root or _coordinate_space_picker_spec(sample_root) is None:
            await query.answer(_copy(lang, 'Список устарел. Откройте Coordinates заново.', 'The list is stale. Open Coordinates again.'), show_alert=True)
            return
        if source not in {None, 'samples', 'other'}:
            await query.answer(_copy(lang, 'Неизвестный источник target.', 'Unknown target source.'), show_alert=True)
            return

        await query.answer()
        items = _list_ready_samples_for_source(_my_data_store(context), update.effective_user.id, source)
        text = _coordinate_space_target_picker_text_for_root(sample_root, items, source=source, lang=lang)
        markup = _build_coordinate_space_target_picker_keyboard(sample_root, items, source=source, lang=lang)
        if _is_photo_message(query.message):
            if update.effective_chat is None:
                return
            await _show_menu_from_photo_message(
                query.message,
                context,
                chat_id=update.effective_chat.id,
                user_id=update.effective_user.id,
                text=text,
                reply_markup=markup,
            )
            return
        await query.message.edit_text(text, reply_markup=markup, parse_mode="HTML")
        if update.effective_chat is not None:
            _set_active_menu_message(context, update.effective_chat.id, update.effective_user.id, query.message.message_id)
        return

    if action == 'caucasus_detail_menu':
        await query.answer()
        if _is_photo_message(query.message):
            if update.effective_chat is None or update.effective_user is None:
                return
            await _show_menu_from_photo_message(
                query.message,
                context,
                chat_id=update.effective_chat.id,
                user_id=update.effective_user.id,
                text=caucasus_detail_text(lang=lang),
                reply_markup=build_caucasus_detail_keyboard(lang=lang),
            )
            return
        await show_caucasus_detail_menu(query.message, edit_existing=True, lang=lang)
        return

    if action == 'west_eurasia_detail_menu':
        await query.answer()
        if _is_photo_message(query.message):
            if update.effective_chat is None or update.effective_user is None:
                return
            await _show_menu_from_photo_message(
                query.message,
                context,
                chat_id=update.effective_chat.id,
                user_id=update.effective_user.id,
                text=west_eurasia_detail_text(lang=lang),
                reply_markup=build_west_eurasia_detail_keyboard(lang=lang),
            )
            return
        await show_west_eurasia_detail_menu(query.message, edit_existing=True, lang=lang)
        return

    if action == 'europe_detail_menu':
        await query.answer()
        if _is_photo_message(query.message):
            if update.effective_chat is None or update.effective_user is None:
                return
            await _show_menu_from_photo_message(
                query.message,
                context,
                chat_id=update.effective_chat.id,
                user_id=update.effective_user.id,
                text=europe_detail_text(lang=lang),
                reply_markup=build_europe_detail_keyboard(lang=lang),
            )
            return
        await show_europe_detail_menu(query.message, edit_existing=True, lang=lang)
        return

    if action == 'east_eurasia_detail_menu':
        await query.answer()
        if _is_photo_message(query.message):
            if update.effective_chat is None or update.effective_user is None:
                return
            await _show_menu_from_photo_message(
                query.message,
                context,
                chat_id=update.effective_chat.id,
                user_id=update.effective_user.id,
                text=east_eurasia_detail_text(lang=lang),
                reply_markup=build_east_eurasia_detail_keyboard(lang=lang),
            )
            return
        await show_east_eurasia_detail_menu(query.message, edit_existing=True, lang=lang)
        return

    if action == 'south_asia_detail_menu':
        await query.answer()
        if _is_photo_message(query.message):
            if update.effective_chat is None or update.effective_user is None:
                return
            await _show_menu_from_photo_message(
                query.message,
                context,
                chat_id=update.effective_chat.id,
                user_id=update.effective_user.id,
                text=south_asia_detail_text(lang=lang),
                reply_markup=build_south_asia_detail_keyboard(lang=lang),
            )
            return
        await show_south_asia_detail_menu(query.message, edit_existing=True, lang=lang)
        return

    if action == 'ready_made_caucasus_steppe':
        await query.answer()
        if _is_photo_message(query.message):
            if update.effective_chat is None or update.effective_user is None:
                return
            await _show_menu_from_photo_message(
                query.message,
                context,
                chat_id=update.effective_chat.id,
                user_id=update.effective_user.id,
                text=caucasus_detail_text(lang=lang),
                reply_markup=build_caucasus_detail_keyboard(lang=lang),
            )
            return
        await show_caucasus_detail_menu(query.message, edit_existing=True, lang=lang)
        return

    if action == 'east_europe_detail':
        await query.answer()
        if _is_photo_message(query.message):
            if update.effective_chat is None or update.effective_user is None:
                return
            await _show_menu_from_photo_message(
                query.message,
                context,
                chat_id=update.effective_chat.id,
                user_id=update.effective_user.id,
                text=caucasus_branch_mode_text(_EUROPE_DETAIL_BRANCH_CONFIGS['east_europe_detail']['title']),
                reply_markup=build_europe_branch_mode_keyboard('east_europe_detail'),
            )
            return
        await show_europe_branch_menu(query.message, detail_action='east_europe_detail', edit_existing=True)
        return

    if action == 'east_europe_detail_change':
        await query.answer()
        if update.effective_user is None:
            return
        items = _list_global_ready_samples(_my_data_store(context), update.effective_user.id)
        if _is_photo_message(query.message):
            if update.effective_chat is None:
                return
            await _show_menu_from_photo_message(
                query.message,
                context,
                chat_id=update.effective_chat.id,
                user_id=update.effective_user.id,
                text=configured_space_sample_picker_text('East Europe', items),
                reply_markup=build_europe_detail_sample_picker_keyboard('east_europe_detail', items),
            )
            return
        await show_europe_detail_sample_picker(
            query.message,
            context,
            update.effective_user.id,
            detail_action='east_europe_detail',
            edit_existing=True,
        )
        return

    if action == 'caucasus_steppe_result':
        await query.answer()
        if _is_photo_message(query.message):
            if update.effective_chat is None or update.effective_user is None:
                return
            await _show_menu_from_photo_message(
                query.message,
                context,
                chat_id=update.effective_chat.id,
                user_id=update.effective_user.id,
                text=caucasus_detail_text(),
                reply_markup=build_caucasus_detail_keyboard(),
            )
            return
        await show_caucasus_detail_menu(query.message, edit_existing=True)
        return

    if action == 'west_eurasia_north_africa_detail':
        await query.answer()
        if _is_photo_message(query.message):
            if update.effective_chat is None or update.effective_user is None:
                return
            await _show_menu_from_photo_message(
                query.message,
                context,
                chat_id=update.effective_chat.id,
                user_id=update.effective_user.id,
                text=coordinate_space_stub_text('North Africa'),
                reply_markup=build_coordinate_space_stub_keyboard(back_callback=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:west_eurasia_detail_menu'),
            )
            return
        await show_coordinate_space_stub(
            query.message,
            title='North Africa',
            back_callback=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:west_eurasia_detail_menu',
            edit_existing=True,
        )
        return

    if action == 'caucasus_steppe_region_mode':
        await query.answer()
        if update.effective_user is None:
            return
        if _is_photo_message(query.message):
            if update.effective_chat is None:
                return
            items = _list_global_ready_samples(_my_data_store(context), update.effective_user.id)
            await _show_menu_from_photo_message(
                query.message,
                context,
                chat_id=update.effective_chat.id,
                user_id=update.effective_user.id,
                text=configured_space_sample_picker_text('Caucasus / Steppe', items),
                reply_markup=build_configured_space_sample_picker_keyboard('ready_made_caucasus_steppe', items),
            )
            return
        await show_configured_space_sample_picker(
            query.message,
            context,
            update.effective_user.id,
            space_action='ready_made_caucasus_steppe',
            edit_existing=True,
        )
        return

    if action == 'caucasus_steppe_population_mode':
        await query.answer()
        if update.effective_user is None:
            return
        if _is_photo_message(query.message):
            if update.effective_chat is None:
                return
            items = _list_global_ready_samples(_my_data_store(context), update.effective_user.id)
            await _show_menu_from_photo_message(
                query.message,
                context,
                chat_id=update.effective_chat.id,
                user_id=update.effective_user.id,
                text=configured_space_sample_picker_text('Caucasus / Steppe', items),
                reply_markup=build_caucasus_steppe_population_sample_picker_keyboard(items),
            )
            return
        await show_caucasus_steppe_population_sample_picker(query.message, context, update.effective_user.id, edit_existing=True)
        return

    if action in _WEST_EURASIA_DETAIL_BRANCH_CONFIGS:
        await query.answer()
        detail_action = action
        if _is_photo_message(query.message):
            if update.effective_chat is None or update.effective_user is None:
                return
            await _show_menu_from_photo_message(
                query.message,
                context,
                chat_id=update.effective_chat.id,
                user_id=update.effective_user.id,
                text=caucasus_branch_mode_text(_WEST_EURASIA_DETAIL_BRANCH_CONFIGS[detail_action]['title']),
                reply_markup=build_west_eurasia_branch_mode_keyboard(detail_action),
            )
            return
        await show_west_eurasia_branch_menu(query.message, detail_action=detail_action, edit_existing=True)
        return

    if action in {branch['region_mode_action'] for branch in _WEST_EURASIA_DETAIL_BRANCH_CONFIGS.values()}:
        await query.answer()
        if update.effective_user is None:
            return
        detail_action = next(
            key for key, branch in _WEST_EURASIA_DETAIL_BRANCH_CONFIGS.items()
            if branch['region_mode_action'] == action
        )
        detail_title = _WEST_EURASIA_DETAIL_BRANCH_CONFIGS[detail_action]['title']
        if _is_photo_message(query.message):
            if update.effective_chat is None:
                return
            items = _list_global_ready_samples(_my_data_store(context), update.effective_user.id)
            await _show_menu_from_photo_message(
                query.message,
                context,
                chat_id=update.effective_chat.id,
                user_id=update.effective_user.id,
                text=configured_space_sample_picker_text(detail_title, items),
                reply_markup=build_west_eurasia_detail_sample_picker_keyboard(detail_action, items),
            )
            return
        await show_west_eurasia_detail_sample_picker(
            query.message,
            context,
            update.effective_user.id,
            detail_action=detail_action,
            edit_existing=True,
        )
        return

    if action in {branch['population_mode_action'] for branch in _WEST_EURASIA_DETAIL_BRANCH_CONFIGS.values()}:
        await query.answer()
        if update.effective_user is None:
            return
        detail_action = next(
            key for key, branch in _WEST_EURASIA_DETAIL_BRANCH_CONFIGS.items()
            if branch['population_mode_action'] == action
        )
        detail_title = _WEST_EURASIA_DETAIL_BRANCH_CONFIGS[detail_action]['title']
        items = _list_global_ready_samples(_my_data_store(context), update.effective_user.id)
        if _is_photo_message(query.message):
            if update.effective_chat is None:
                return
            await _show_menu_from_photo_message(
                query.message,
                context,
                chat_id=update.effective_chat.id,
                user_id=update.effective_user.id,
                text=configured_space_sample_picker_text(detail_title, items),
                reply_markup=build_west_eurasia_detail_sample_picker_keyboard(detail_action, items, mode='populations'),
            )
            return
        if update.effective_chat is None:
            return
        await query.message.edit_text(
            configured_space_sample_picker_text(detail_title, items),
            reply_markup=build_west_eurasia_detail_sample_picker_keyboard(detail_action, items, mode='populations'),
        )
        _set_active_menu_message(context, update.effective_chat.id, update.effective_user.id, query.message.message_id)
        return

    if action in {branch['change_action'] for branch in _WEST_EURASIA_DETAIL_BRANCH_CONFIGS.values()}:
        await query.answer()
        if update.effective_user is None:
            return
        detail_action = next(
            key for key, branch in _WEST_EURASIA_DETAIL_BRANCH_CONFIGS.items()
            if branch['change_action'] == action
        )
        detail_title = _WEST_EURASIA_DETAIL_BRANCH_CONFIGS[detail_action]['title']
        if _is_photo_message(query.message):
            if update.effective_chat is None:
                return
            items = _list_global_ready_samples(_my_data_store(context), update.effective_user.id)
            await _show_menu_from_photo_message(
                query.message,
                context,
                chat_id=update.effective_chat.id,
                user_id=update.effective_user.id,
                text=configured_space_sample_picker_text(detail_title, items),
                reply_markup=build_west_eurasia_detail_sample_picker_keyboard(detail_action, items),
            )
            return
        await show_west_eurasia_detail_sample_picker(
            query.message,
            context,
            update.effective_user.id,
            detail_action=detail_action,
            edit_existing=True,
        )
        return

    if action in {branch['population_change_action'] for branch in _WEST_EURASIA_DETAIL_BRANCH_CONFIGS.values()}:
        await query.answer()
        if update.effective_user is None:
            return
        detail_action = next(
            key for key, branch in _WEST_EURASIA_DETAIL_BRANCH_CONFIGS.items()
            if branch['population_change_action'] == action
        )
        detail_title = _WEST_EURASIA_DETAIL_BRANCH_CONFIGS[detail_action]['title']
        items = _list_global_ready_samples(_my_data_store(context), update.effective_user.id)
        if _is_photo_message(query.message):
            if update.effective_chat is None:
                return
            await _show_menu_from_photo_message(
                query.message,
                context,
                chat_id=update.effective_chat.id,
                user_id=update.effective_user.id,
                text=configured_space_sample_picker_text(detail_title, items),
                reply_markup=build_west_eurasia_detail_sample_picker_keyboard(detail_action, items, mode='populations'),
            )
            return
        if update.effective_chat is None:
            return
        await query.message.edit_text(
            configured_space_sample_picker_text(detail_title, items),
            reply_markup=build_west_eurasia_detail_sample_picker_keyboard(detail_action, items, mode='populations'),
        )
        _set_active_menu_message(context, update.effective_chat.id, update.effective_user.id, query.message.message_id)
        return

    if action in _EUROPE_DETAIL_BRANCH_CONFIGS:
        await query.answer()
        detail_action = action
        if _is_photo_message(query.message):
            if update.effective_chat is None or update.effective_user is None:
                return
            await _show_menu_from_photo_message(
                query.message,
                context,
                chat_id=update.effective_chat.id,
                user_id=update.effective_user.id,
                text=caucasus_branch_mode_text(_EUROPE_DETAIL_BRANCH_CONFIGS[detail_action]['title']),
                reply_markup=build_europe_branch_mode_keyboard(detail_action),
            )
            return
        await show_europe_branch_menu(query.message, detail_action=detail_action, edit_existing=True)
        return

    if action in {branch['region_mode_action'] for branch in _EUROPE_DETAIL_BRANCH_CONFIGS.values()}:
        await query.answer()
        if update.effective_user is None:
            return
        detail_action = next(
            key for key, branch in _EUROPE_DETAIL_BRANCH_CONFIGS.items()
            if branch['region_mode_action'] == action
        )
        detail_title = _EUROPE_DETAIL_BRANCH_CONFIGS[detail_action]['title']
        if _is_photo_message(query.message):
            if update.effective_chat is None:
                return
            items = _list_global_ready_samples(_my_data_store(context), update.effective_user.id)
            await _show_menu_from_photo_message(
                query.message,
                context,
                chat_id=update.effective_chat.id,
                user_id=update.effective_user.id,
                text=configured_space_sample_picker_text(detail_title, items),
                reply_markup=build_europe_detail_sample_picker_keyboard(detail_action, items),
            )
            return
        await show_europe_detail_sample_picker(
            query.message,
            context,
            update.effective_user.id,
            detail_action=detail_action,
            edit_existing=True,
        )
        return

    if action in {branch['population_mode_action'] for branch in _EUROPE_DETAIL_BRANCH_CONFIGS.values()}:
        await query.answer()
        if update.effective_user is None:
            return
        detail_action = next(
            key for key, branch in _EUROPE_DETAIL_BRANCH_CONFIGS.items()
            if branch['population_mode_action'] == action
        )
        detail_title = _EUROPE_DETAIL_BRANCH_CONFIGS[detail_action]['title']
        items = _list_global_ready_samples(_my_data_store(context), update.effective_user.id)
        if _is_photo_message(query.message):
            if update.effective_chat is None:
                return
            await _show_menu_from_photo_message(
                query.message,
                context,
                chat_id=update.effective_chat.id,
                user_id=update.effective_user.id,
                text=configured_space_sample_picker_text(detail_title, items),
                reply_markup=build_europe_detail_sample_picker_keyboard(detail_action, items, mode='populations'),
            )
            return
        if update.effective_chat is None:
            return
        await query.message.edit_text(
            configured_space_sample_picker_text(detail_title, items),
            reply_markup=build_europe_detail_sample_picker_keyboard(detail_action, items, mode='populations'),
        )
        _set_active_menu_message(context, update.effective_chat.id, update.effective_user.id, query.message.message_id)
        return

    if action in {branch['change_action'] for branch in _EUROPE_DETAIL_BRANCH_CONFIGS.values()}:
        await query.answer()
        if update.effective_user is None:
            return
        detail_action = next(
            key for key, branch in _EUROPE_DETAIL_BRANCH_CONFIGS.items()
            if branch['change_action'] == action
        )
        detail_title = _EUROPE_DETAIL_BRANCH_CONFIGS[detail_action]['title']
        if _is_photo_message(query.message):
            if update.effective_chat is None:
                return
            items = _list_global_ready_samples(_my_data_store(context), update.effective_user.id)
            await _show_menu_from_photo_message(
                query.message,
                context,
                chat_id=update.effective_chat.id,
                user_id=update.effective_user.id,
                text=configured_space_sample_picker_text(detail_title, items),
                reply_markup=build_europe_detail_sample_picker_keyboard(detail_action, items),
            )
            return
        await show_europe_detail_sample_picker(
            query.message,
            context,
            update.effective_user.id,
            detail_action=detail_action,
            edit_existing=True,
        )
        return

    if action in {branch['population_change_action'] for branch in _EUROPE_DETAIL_BRANCH_CONFIGS.values()}:
        await query.answer()
        if update.effective_user is None:
            return
        detail_action = next(
            key for key, branch in _EUROPE_DETAIL_BRANCH_CONFIGS.items()
            if branch['population_change_action'] == action
        )
        detail_title = _EUROPE_DETAIL_BRANCH_CONFIGS[detail_action]['title']
        items = _list_global_ready_samples(_my_data_store(context), update.effective_user.id)
        if _is_photo_message(query.message):
            if update.effective_chat is None:
                return
            await _show_menu_from_photo_message(
                query.message,
                context,
                chat_id=update.effective_chat.id,
                user_id=update.effective_user.id,
                text=configured_space_sample_picker_text(detail_title, items),
                reply_markup=build_europe_detail_sample_picker_keyboard(detail_action, items, mode='populations'),
            )
            return
        if update.effective_chat is None:
            return
        await query.message.edit_text(
            configured_space_sample_picker_text(detail_title, items),
            reply_markup=build_europe_detail_sample_picker_keyboard(detail_action, items, mode='populations'),
        )
        _set_active_menu_message(context, update.effective_chat.id, update.effective_user.id, query.message.message_id)
        return

    if action in _CAUCASUS_DETAIL_BRANCH_CONFIGS:
        await query.answer()
        detail_action = action
        if _is_photo_message(query.message):
            if update.effective_chat is None or update.effective_user is None:
                return
            await _show_menu_from_photo_message(
                query.message,
                context,
                chat_id=update.effective_chat.id,
                user_id=update.effective_user.id,
                text=caucasus_branch_mode_text(_CAUCASUS_DETAIL_BRANCH_CONFIGS[detail_action]['title']),
                reply_markup=build_caucasus_branch_mode_keyboard(detail_action),
            )
            return
        await show_caucasus_branch_menu(query.message, detail_action=detail_action, edit_existing=True)
        return

    if action in {branch['region_mode_action'] for branch in _CAUCASUS_DETAIL_BRANCH_CONFIGS.values()}:
        await query.answer()
        if update.effective_user is None:
            return
        detail_action = next(
            key for key, branch in _CAUCASUS_DETAIL_BRANCH_CONFIGS.items()
            if branch['region_mode_action'] == action
        )
        detail_title = _CAUCASUS_DETAIL_BRANCH_CONFIGS[detail_action]['title']
        if _is_photo_message(query.message):
            if update.effective_chat is None:
                return
            items = _list_global_ready_samples(_my_data_store(context), update.effective_user.id)
            await _show_menu_from_photo_message(
                query.message,
                context,
                chat_id=update.effective_chat.id,
                user_id=update.effective_user.id,
                text=configured_space_sample_picker_text(detail_title, items),
                reply_markup=build_caucasus_detail_sample_picker_keyboard(detail_action, items),
            )
            return
        await show_caucasus_detail_sample_picker(
            query.message,
            context,
            update.effective_user.id,
            detail_action=detail_action,
            edit_existing=True,
        )
        return

    if action in {branch['population_mode_action'] for branch in _CAUCASUS_DETAIL_BRANCH_CONFIGS.values()}:
        await query.answer()
        if update.effective_user is None:
            return
        detail_action = next(
            key for key, branch in _CAUCASUS_DETAIL_BRANCH_CONFIGS.items()
            if branch['population_mode_action'] == action
        )
        detail_title = _CAUCASUS_DETAIL_BRANCH_CONFIGS[detail_action]['title']
        items = _list_global_ready_samples(_my_data_store(context), update.effective_user.id)
        if _is_photo_message(query.message):
            if update.effective_chat is None:
                return
            await _show_menu_from_photo_message(
                query.message,
                context,
                chat_id=update.effective_chat.id,
                user_id=update.effective_user.id,
                text=configured_space_sample_picker_text(detail_title, items),
                reply_markup=build_caucasus_detail_sample_picker_keyboard(detail_action, items, mode='populations'),
            )
            return
        if update.effective_chat is None:
            return
        await query.message.edit_text(
            configured_space_sample_picker_text(detail_title, items),
            reply_markup=build_caucasus_detail_sample_picker_keyboard(detail_action, items, mode='populations'),
        )
        _set_active_menu_message(context, update.effective_chat.id, update.effective_user.id, query.message.message_id)
        return

    if action in {branch['change_action'] for branch in _CAUCASUS_DETAIL_BRANCH_CONFIGS.values()}:
        await query.answer()
        if update.effective_user is None:
            return
        detail_action = next(
            key for key, branch in _CAUCASUS_DETAIL_BRANCH_CONFIGS.items()
            if branch['change_action'] == action
        )
        detail_title = _CAUCASUS_DETAIL_BRANCH_CONFIGS[detail_action]['title']
        if _is_photo_message(query.message):
            if update.effective_chat is None:
                return
            items = _list_global_ready_samples(_my_data_store(context), update.effective_user.id)
            await _show_menu_from_photo_message(
                query.message,
                context,
                chat_id=update.effective_chat.id,
                user_id=update.effective_user.id,
                text=configured_space_sample_picker_text(detail_title, items),
                reply_markup=build_caucasus_detail_sample_picker_keyboard(detail_action, items),
            )
            return
        await show_caucasus_detail_sample_picker(
            query.message,
            context,
            update.effective_user.id,
            detail_action=detail_action,
            edit_existing=True,
        )
        return

    if action in {branch['population_change_action'] for branch in _CAUCASUS_DETAIL_BRANCH_CONFIGS.values()}:
        await query.answer()
        if update.effective_user is None:
            return
        detail_action = next(
            key for key, branch in _CAUCASUS_DETAIL_BRANCH_CONFIGS.items()
            if branch['population_change_action'] == action
        )
        detail_title = _CAUCASUS_DETAIL_BRANCH_CONFIGS[detail_action]['title']
        items = _list_global_ready_samples(_my_data_store(context), update.effective_user.id)
        if _is_photo_message(query.message):
            if update.effective_chat is None:
                return
            await _show_menu_from_photo_message(
                query.message,
                context,
                chat_id=update.effective_chat.id,
                user_id=update.effective_user.id,
                text=configured_space_sample_picker_text(detail_title, items),
                reply_markup=build_caucasus_detail_sample_picker_keyboard(detail_action, items, mode='populations'),
            )
            return
        if update.effective_chat is None:
            return
        await query.message.edit_text(
            configured_space_sample_picker_text(detail_title, items),
            reply_markup=build_caucasus_detail_sample_picker_keyboard(detail_action, items, mode='populations'),
        )
        _set_active_menu_message(context, update.effective_chat.id, update.effective_user.id, query.message.message_id)
        return

    if action == 'caucasus_steppe_population_change':
        await query.answer()
        if update.effective_user is None:
            return
        if _is_photo_message(query.message):
            if update.effective_chat is None:
                return
            items = _list_global_ready_samples(_my_data_store(context), update.effective_user.id)
            await _show_menu_from_photo_message(
                query.message,
                context,
                chat_id=update.effective_chat.id,
                user_id=update.effective_user.id,
                text=configured_space_sample_picker_text('Caucasus / Steppe', items),
                reply_markup=build_caucasus_steppe_population_sample_picker_keyboard(items),
            )
            return
        await show_caucasus_steppe_population_sample_picker(query.message, context, update.effective_user.id, edit_existing=True)
        return

    if action in _EAST_EURASIA_DETAIL_BRANCH_CONFIGS:
        await query.answer()
        detail_action = action
        if _is_photo_message(query.message):
            if update.effective_chat is None or update.effective_user is None:
                return
            await _show_menu_from_photo_message(
                query.message,
                context,
                chat_id=update.effective_chat.id,
                user_id=update.effective_user.id,
                text=caucasus_branch_mode_text(_EAST_EURASIA_DETAIL_BRANCH_CONFIGS[detail_action]['title']),
                reply_markup=build_east_eurasia_branch_mode_keyboard(detail_action),
            )
            return
        await show_east_eurasia_branch_menu(query.message, detail_action=detail_action, edit_existing=True)
        return

    if action in {branch['region_mode_action'] for branch in _EAST_EURASIA_DETAIL_BRANCH_CONFIGS.values()}:
        await query.answer()
        if update.effective_user is None:
            return
        detail_action = next(
            key for key, branch in _EAST_EURASIA_DETAIL_BRANCH_CONFIGS.items()
            if branch['region_mode_action'] == action
        )
        detail_title = _EAST_EURASIA_DETAIL_BRANCH_CONFIGS[detail_action]['title']
        if _is_photo_message(query.message):
            if update.effective_chat is None:
                return
            items = _list_global_ready_samples(_my_data_store(context), update.effective_user.id)
            await _show_menu_from_photo_message(
                query.message,
                context,
                chat_id=update.effective_chat.id,
                user_id=update.effective_user.id,
                text=configured_space_sample_picker_text(detail_title, items),
                reply_markup=build_east_eurasia_detail_sample_picker_keyboard(detail_action, items),
            )
            return
        await show_east_eurasia_detail_sample_picker(
            query.message,
            context,
            update.effective_user.id,
            detail_action=detail_action,
            edit_existing=True,
        )
        return

    if action in {branch['population_mode_action'] for branch in _EAST_EURASIA_DETAIL_BRANCH_CONFIGS.values()}:
        await query.answer()
        if update.effective_user is None:
            return
        detail_action = next(
            key for key, branch in _EAST_EURASIA_DETAIL_BRANCH_CONFIGS.items()
            if branch['population_mode_action'] == action
        )
        detail_title = _EAST_EURASIA_DETAIL_BRANCH_CONFIGS[detail_action]['title']
        items = _list_global_ready_samples(_my_data_store(context), update.effective_user.id)
        if _is_photo_message(query.message):
            if update.effective_chat is None:
                return
            await _show_menu_from_photo_message(
                query.message,
                context,
                chat_id=update.effective_chat.id,
                user_id=update.effective_user.id,
                text=configured_space_sample_picker_text(detail_title, items),
                reply_markup=build_east_eurasia_detail_sample_picker_keyboard(detail_action, items, mode='populations'),
            )
            return
        if update.effective_chat is None:
            return
        await query.message.edit_text(
            configured_space_sample_picker_text(detail_title, items),
            reply_markup=build_east_eurasia_detail_sample_picker_keyboard(detail_action, items, mode='populations'),
        )
        _set_active_menu_message(context, update.effective_chat.id, update.effective_user.id, query.message.message_id)
        return

    if action in {branch['change_action'] for branch in _EAST_EURASIA_DETAIL_BRANCH_CONFIGS.values()}:
        await query.answer()
        if update.effective_user is None:
            return
        detail_action = next(
            key for key, branch in _EAST_EURASIA_DETAIL_BRANCH_CONFIGS.items()
            if branch['change_action'] == action
        )
        detail_title = _EAST_EURASIA_DETAIL_BRANCH_CONFIGS[detail_action]['title']
        if _is_photo_message(query.message):
            if update.effective_chat is None:
                return
            items = _list_global_ready_samples(_my_data_store(context), update.effective_user.id)
            await _show_menu_from_photo_message(
                query.message,
                context,
                chat_id=update.effective_chat.id,
                user_id=update.effective_user.id,
                text=configured_space_sample_picker_text(detail_title, items),
                reply_markup=build_east_eurasia_detail_sample_picker_keyboard(detail_action, items),
            )
            return
        await show_east_eurasia_detail_sample_picker(
            query.message,
            context,
            update.effective_user.id,
            detail_action=detail_action,
            edit_existing=True,
        )
        return

    if action in {branch['population_change_action'] for branch in _EAST_EURASIA_DETAIL_BRANCH_CONFIGS.values()}:
        await query.answer()
        if update.effective_user is None:
            return
        detail_action = next(
            key for key, branch in _EAST_EURASIA_DETAIL_BRANCH_CONFIGS.items()
            if branch['population_change_action'] == action
        )
        detail_title = _EAST_EURASIA_DETAIL_BRANCH_CONFIGS[detail_action]['title']
        items = _list_global_ready_samples(_my_data_store(context), update.effective_user.id)
        if _is_photo_message(query.message):
            if update.effective_chat is None:
                return
            await _show_menu_from_photo_message(
                query.message,
                context,
                chat_id=update.effective_chat.id,
                user_id=update.effective_user.id,
                text=configured_space_sample_picker_text(detail_title, items),
                reply_markup=build_east_eurasia_detail_sample_picker_keyboard(detail_action, items, mode='populations'),
            )
            return
        if update.effective_chat is None:
            return
        await query.message.edit_text(
            configured_space_sample_picker_text(detail_title, items),
            reply_markup=build_east_eurasia_detail_sample_picker_keyboard(detail_action, items, mode='populations'),
        )
        _set_active_menu_message(context, update.effective_chat.id, update.effective_user.id, query.message.message_id)
        return

    if action in _SOUTH_ASIA_DETAIL_BRANCH_CONFIGS:
        await query.answer()
        detail_action = action
        if _is_photo_message(query.message):
            if update.effective_chat is None or update.effective_user is None:
                return
            await _show_menu_from_photo_message(
                query.message,
                context,
                chat_id=update.effective_chat.id,
                user_id=update.effective_user.id,
                text=caucasus_branch_mode_text(_SOUTH_ASIA_DETAIL_BRANCH_CONFIGS[detail_action]['title']),
                reply_markup=build_south_asia_branch_mode_keyboard(detail_action),
            )
            return
        await show_south_asia_branch_menu(query.message, detail_action=detail_action, edit_existing=True)
        return

    if action in {branch['region_mode_action'] for branch in _SOUTH_ASIA_DETAIL_BRANCH_CONFIGS.values()}:
        await query.answer()
        if update.effective_user is None:
            return
        detail_action = next(
            key for key, branch in _SOUTH_ASIA_DETAIL_BRANCH_CONFIGS.items()
            if branch['region_mode_action'] == action
        )
        detail_title = _SOUTH_ASIA_DETAIL_BRANCH_CONFIGS[detail_action]['title']
        if _is_photo_message(query.message):
            if update.effective_chat is None:
                return
            items = _list_global_ready_samples(_my_data_store(context), update.effective_user.id)
            await _show_menu_from_photo_message(
                query.message,
                context,
                chat_id=update.effective_chat.id,
                user_id=update.effective_user.id,
                text=configured_space_sample_picker_text(detail_title, items),
                reply_markup=build_south_asia_detail_sample_picker_keyboard(detail_action, items),
            )
            return
        await show_south_asia_detail_sample_picker(
            query.message,
            context,
            update.effective_user.id,
            detail_action=detail_action,
            edit_existing=True,
        )
        return

    if action in {branch['population_mode_action'] for branch in _SOUTH_ASIA_DETAIL_BRANCH_CONFIGS.values()}:
        await query.answer()
        if update.effective_user is None:
            return
        detail_action = next(
            key for key, branch in _SOUTH_ASIA_DETAIL_BRANCH_CONFIGS.items()
            if branch['population_mode_action'] == action
        )
        detail_title = _SOUTH_ASIA_DETAIL_BRANCH_CONFIGS[detail_action]['title']
        items = _list_global_ready_samples(_my_data_store(context), update.effective_user.id)
        if _is_photo_message(query.message):
            if update.effective_chat is None:
                return
            await _show_menu_from_photo_message(
                query.message,
                context,
                chat_id=update.effective_chat.id,
                user_id=update.effective_user.id,
                text=configured_space_sample_picker_text(detail_title, items),
                reply_markup=build_south_asia_detail_sample_picker_keyboard(detail_action, items, mode='populations'),
            )
            return
        if update.effective_chat is None:
            return
        await query.message.edit_text(
            configured_space_sample_picker_text(detail_title, items),
            reply_markup=build_south_asia_detail_sample_picker_keyboard(detail_action, items, mode='populations'),
        )
        _set_active_menu_message(context, update.effective_chat.id, update.effective_user.id, query.message.message_id)
        return

    if action in {branch['change_action'] for branch in _SOUTH_ASIA_DETAIL_BRANCH_CONFIGS.values()}:
        await query.answer()
        if update.effective_user is None:
            return
        detail_action = next(
            key for key, branch in _SOUTH_ASIA_DETAIL_BRANCH_CONFIGS.items()
            if branch['change_action'] == action
        )
        detail_title = _SOUTH_ASIA_DETAIL_BRANCH_CONFIGS[detail_action]['title']
        if _is_photo_message(query.message):
            if update.effective_chat is None:
                return
            items = _list_global_ready_samples(_my_data_store(context), update.effective_user.id)
            await _show_menu_from_photo_message(
                query.message,
                context,
                chat_id=update.effective_chat.id,
                user_id=update.effective_user.id,
                text=configured_space_sample_picker_text(detail_title, items),
                reply_markup=build_south_asia_detail_sample_picker_keyboard(detail_action, items),
            )
            return
        await show_south_asia_detail_sample_picker(
            query.message,
            context,
            update.effective_user.id,
            detail_action=detail_action,
            edit_existing=True,
        )
        return

    if action in {branch['population_change_action'] for branch in _SOUTH_ASIA_DETAIL_BRANCH_CONFIGS.values()}:
        await query.answer()
        if update.effective_user is None:
            return
        detail_action = next(
            key for key, branch in _SOUTH_ASIA_DETAIL_BRANCH_CONFIGS.items()
            if branch['population_change_action'] == action
        )
        detail_title = _SOUTH_ASIA_DETAIL_BRANCH_CONFIGS[detail_action]['title']
        items = _list_global_ready_samples(_my_data_store(context), update.effective_user.id)
        if _is_photo_message(query.message):
            if update.effective_chat is None:
                return
            await _show_menu_from_photo_message(
                query.message,
                context,
                chat_id=update.effective_chat.id,
                user_id=update.effective_user.id,
                text=configured_space_sample_picker_text(detail_title, items),
                reply_markup=build_south_asia_detail_sample_picker_keyboard(detail_action, items, mode='populations'),
            )
            return
        if update.effective_chat is None:
            return
        await query.message.edit_text(
            configured_space_sample_picker_text(detail_title, items),
            reply_markup=build_south_asia_detail_sample_picker_keyboard(detail_action, items, mode='populations'),
        )
        _set_active_menu_message(context, update.effective_chat.id, update.effective_user.id, query.message.message_id)
        return

    if action == 'ready_made_global':
        await query.answer()
        if _is_photo_message(query.message):
            if update.effective_chat is None or update.effective_user is None:
                return
            await _show_menu_from_photo_message(
                query.message,
                context,
                chat_id=update.effective_chat.id,
                user_id=update.effective_user.id,
                text=global_menu_text(),
                reply_markup=build_global_menu_keyboard(),
            )
            return
        await show_global_menu(query.message, edit_existing=True)
        return

    if action == 'ready_made_global_change':
        await query.answer()
        if update.effective_user is None:
            return
        if _is_photo_message(query.message):
            if update.effective_chat is None:
                return
            items = _list_global_ready_samples(_my_data_store(context), update.effective_user.id)
            await _show_menu_from_photo_message(
                query.message,
                context,
                chat_id=update.effective_chat.id,
                user_id=update.effective_user.id,
                text=global_sample_picker_text(items),
                reply_markup=build_global_sample_picker_keyboard(items),
            )
            return
        await show_global_sample_picker(query.message, context, update.effective_user.id, edit_existing=True)
        return

    if action == 'ready_made_west_eurasia':
        await query.answer()
        if _is_photo_message(query.message):
            if update.effective_chat is None or update.effective_user is None:
                return
            await _show_menu_from_photo_message(
                query.message,
                context,
                chat_id=update.effective_chat.id,
                user_id=update.effective_user.id,
                text=west_eurasia_detail_text(),
                reply_markup=build_west_eurasia_detail_keyboard(lang=lang),
            )
            return
        await show_west_eurasia_detail_menu(query.message, edit_existing=True)
        return

    if action == 'ready_made_west_eurasia_change':
        await query.answer()
        if update.effective_user is None:
            return
        if _is_photo_message(query.message):
            if update.effective_chat is None:
                return
            items = _list_global_ready_samples(_my_data_store(context), update.effective_user.id)
            await _show_menu_from_photo_message(
                query.message,
                context,
                chat_id=update.effective_chat.id,
                user_id=update.effective_user.id,
                text=west_eurasia_sample_picker_text(items),
                reply_markup=build_west_eurasia_sample_picker_keyboard(items),
            )
            return
        await show_west_eurasia_sample_picker(query.message, context, update.effective_user.id, edit_existing=True)
        return

    if action == 'ready_made_europe':
        await query.answer()
        if _is_photo_message(query.message):
            if update.effective_chat is None or update.effective_user is None:
                return
            await _show_menu_from_photo_message(
                query.message,
                context,
                chat_id=update.effective_chat.id,
                user_id=update.effective_user.id,
                text=europe_detail_text(),
                reply_markup=build_europe_detail_keyboard(lang=lang),
            )
            return
        await show_europe_detail_menu(query.message, edit_existing=True)
        return

    if action == 'ready_made_south_asia':
        await query.answer()
        if _is_photo_message(query.message):
            if update.effective_chat is None or update.effective_user is None:
                return
            await _show_menu_from_photo_message(
                query.message,
                context,
                chat_id=update.effective_chat.id,
                user_id=update.effective_user.id,
                text=south_asia_detail_text(),
                reply_markup=build_south_asia_detail_keyboard(lang=lang),
            )
            return
        await show_south_asia_detail_menu(query.message, edit_existing=True)
        return

    if action == 'ready_made_east_eurasia':
        await query.answer()
        if _is_photo_message(query.message):
            if update.effective_chat is None or update.effective_user is None:
                return
            await _show_menu_from_photo_message(
                query.message,
                context,
                chat_id=update.effective_chat.id,
                user_id=update.effective_user.id,
                text=east_eurasia_detail_text(),
                reply_markup=build_east_eurasia_detail_keyboard(lang=lang),
            )
            return
        await show_east_eurasia_detail_menu(query.message, edit_existing=True)
        return

    if action == 'global_region_mode':
        await query.answer()
        if update.effective_user is None:
            return
        if _is_photo_message(query.message):
            if update.effective_chat is None:
                return
            items = _list_global_ready_samples(_my_data_store(context), update.effective_user.id)
            await _show_menu_from_photo_message(
                query.message,
                context,
                chat_id=update.effective_chat.id,
                user_id=update.effective_user.id,
                text=global_sample_picker_text(items),
                reply_markup=build_global_sample_picker_keyboard(items),
            )
            return
        await show_global_sample_picker(query.message, context, update.effective_user.id, edit_existing=True)
        return

    if action == 'west_eurasia_region_mode':
        await query.answer()
        if update.effective_user is None:
            return
        if _is_photo_message(query.message):
            if update.effective_chat is None:
                return
            items = _list_global_ready_samples(_my_data_store(context), update.effective_user.id)
            await _show_menu_from_photo_message(
                query.message,
                context,
                chat_id=update.effective_chat.id,
                user_id=update.effective_user.id,
                text=west_eurasia_sample_picker_text(items),
                reply_markup=build_west_eurasia_sample_picker_keyboard(items),
            )
            return
        await show_west_eurasia_sample_picker(query.message, context, update.effective_user.id, edit_existing=True)
        return

    if action == 'europe_region_mode':
        await query.answer()
        if update.effective_user is None:
            return
        if _is_photo_message(query.message):
            if update.effective_chat is None:
                return
            items = _list_global_ready_samples(_my_data_store(context), update.effective_user.id)
            await _show_menu_from_photo_message(
                query.message,
                context,
                chat_id=update.effective_chat.id,
                user_id=update.effective_user.id,
                text=configured_space_sample_picker_text('Europe', items),
                reply_markup=build_configured_space_sample_picker_keyboard('ready_made_europe', items),
            )
            return
        await show_configured_space_sample_picker(
            query.message,
            context,
            update.effective_user.id,
            space_action='ready_made_europe',
            edit_existing=True,
        )
        return

    if action == 'south_asia_region_mode':
        await query.answer()
        if update.effective_user is None:
            return
        if _is_photo_message(query.message):
            if update.effective_chat is None:
                return
            items = _list_global_ready_samples(_my_data_store(context), update.effective_user.id)
            await _show_menu_from_photo_message(
                query.message,
                context,
                chat_id=update.effective_chat.id,
                user_id=update.effective_user.id,
                text=configured_space_sample_picker_text('South Asia', items),
                reply_markup=build_configured_space_sample_picker_keyboard('ready_made_south_asia', items),
            )
            return
        await show_configured_space_sample_picker(
            query.message,
            context,
            update.effective_user.id,
            space_action='ready_made_south_asia',
            edit_existing=True,
        )
        return

    if action == 'east_eurasia_region_mode':
        await query.answer()
        if update.effective_user is None:
            return
        if _is_photo_message(query.message):
            if update.effective_chat is None:
                return
            items = _list_global_ready_samples(_my_data_store(context), update.effective_user.id)
            await _show_menu_from_photo_message(
                query.message,
                context,
                chat_id=update.effective_chat.id,
                user_id=update.effective_user.id,
                text=configured_space_sample_picker_text('East Eurasia', items),
                reply_markup=build_configured_space_sample_picker_keyboard('ready_made_east_eurasia', items),
            )
            return
        await show_configured_space_sample_picker(
            query.message,
            context,
            update.effective_user.id,
            space_action='ready_made_east_eurasia',
            edit_existing=True,
        )
        return

    all_population_view_action = _READY_MADE_ALL_POPULATION_MODE_ACTIONS.get(action)
    if all_population_view_action is not None:
        await query.answer()
        if update.effective_user is None:
            return
        if _is_photo_message(query.message):
            if update.effective_chat is None:
                return
            items = _list_global_ready_samples(_my_data_store(context), update.effective_user.id)
            await _show_menu_from_photo_message(
                query.message,
                context,
                chat_id=update.effective_chat.id,
                user_id=update.effective_user.id,
                text=configured_space_sample_picker_text(_READY_MADE_ALL_POPULATION_FLOWS[all_population_view_action]['title'], items),
                reply_markup=build_ready_made_all_populations_sample_picker_keyboard(all_population_view_action, items),
            )
            return
        await show_ready_made_all_populations_sample_picker(
            query.message,
            context,
            update.effective_user.id,
            view_action=all_population_view_action,
            edit_existing=True,
        )
        return

    all_population_change_view_action = _READY_MADE_ALL_POPULATION_CHANGE_ACTIONS.get(action)
    if all_population_change_view_action is not None:
        await query.answer()
        if update.effective_user is None:
            return
        if _is_photo_message(query.message):
            if update.effective_chat is None:
                return
            items = _list_global_ready_samples(_my_data_store(context), update.effective_user.id)
            await _show_menu_from_photo_message(
                query.message,
                context,
                chat_id=update.effective_chat.id,
                user_id=update.effective_user.id,
                text=configured_space_sample_picker_text(_READY_MADE_ALL_POPULATION_FLOWS[all_population_change_view_action]['title'], items),
                reply_markup=build_ready_made_all_populations_sample_picker_keyboard(all_population_change_view_action, items),
            )
            return
        await show_ready_made_all_populations_sample_picker(
            query.message,
            context,
            update.effective_user.id,
            view_action=all_population_change_view_action,
            edit_existing=True,
        )
        return

    configured_space = _REGIONAL_READY_MADE_SPACES.get(action)
    if configured_space is not None:
        await query.answer()
        if update.effective_user is None:
            return
        if _is_photo_message(query.message):
            if update.effective_chat is None:
                return
            items = _list_global_ready_samples(_my_data_store(context), update.effective_user.id)
            await _show_menu_from_photo_message(
                query.message,
                context,
                chat_id=update.effective_chat.id,
                user_id=update.effective_user.id,
                text=configured_space_sample_picker_text(configured_space['title'], items),
                reply_markup=build_configured_space_sample_picker_keyboard(action, items),
            )
            return
        await show_configured_space_sample_picker(
            query.message,
            context,
            update.effective_user.id,
            space_action=action,
            edit_existing=True,
        )
        return

    if action.endswith('_change') and action[:-7] in _REGIONAL_READY_MADE_SPACES:
        await query.answer()
        if update.effective_user is None:
            return
        space_action = action[:-7]
        if _is_photo_message(query.message):
            if update.effective_chat is None:
                return
            items = _list_global_ready_samples(_my_data_store(context), update.effective_user.id)
            await _show_menu_from_photo_message(
                query.message,
                context,
                chat_id=update.effective_chat.id,
                user_id=update.effective_user.id,
                text=configured_space_sample_picker_text(_REGIONAL_READY_MADE_SPACES[space_action]['title'], items),
                reply_markup=build_configured_space_sample_picker_keyboard(space_action, items),
            )
            return
        await show_configured_space_sample_picker(
            query.message,
            context,
            update.effective_user.id,
            space_action=space_action,
            edit_existing=True,
        )
        return

    if root_action == 'global_sample':
        await query.answer()
        if update.effective_user is None or update.effective_chat is None or not payload:
            return
        await show_global_result(
            query.message,
            context,
            update.effective_chat.id,
            update.effective_user.id,
            payload,
            edit_existing=True,
        )
        return

    if root_action == 'we_sample':
        await query.answer()
        if update.effective_user is None or update.effective_chat is None or not payload:
            return
        await show_west_eurasia_result(
            query.message,
            context,
            update.effective_chat.id,
            update.effective_user.id,
            payload,
            edit_existing=True,
        )
        return

    ready_made_all_population_view_action = _READY_MADE_ALL_POPULATION_SAMPLE_ROOT_ACTIONS.get(root_action)
    if ready_made_all_population_view_action is not None:
        await query.answer()
        if update.effective_user is None or update.effective_chat is None or not payload:
            return
        await show_ready_made_all_populations_result(
            query.message,
            context,
            update.effective_chat.id,
            update.effective_user.id,
            payload,
            view_action=ready_made_all_population_view_action,
            edit_existing=True,
        )
        return

    configured_sample_space = _REGIONAL_SAMPLE_ROOT_ACTIONS.get(root_action)
    if configured_sample_space is not None:
        await query.answer()
        if update.effective_user is None or update.effective_chat is None or not payload:
            return
        await show_configured_space_result(
            query.message,
            context,
            update.effective_chat.id,
            update.effective_user.id,
            payload,
            space_action=configured_sample_space,
            edit_existing=True,
        )
        return

    detail_sample_space = _DETAIL_SAMPLE_ROOT_ACTIONS.get(root_action)
    if detail_sample_space is not None:
        await query.answer()
        if update.effective_user is None or update.effective_chat is None or not payload:
            return
        if detail_sample_space == 'east_europe_detail':
            await show_east_europe_detail_result(
                query.message,
                context,
                update.effective_chat.id,
                update.effective_user.id,
                payload,
                edit_existing=True,
            )
            return
        if detail_sample_space in _EUROPE_DETAIL_BRANCH_CONFIGS:
            await show_europe_detail_branch_result(
                query.message,
                context,
                update.effective_chat.id,
                update.effective_user.id,
                payload,
                detail_action=detail_sample_space,
                edit_existing=True,
            )
            return
        if detail_sample_space in _SOUTH_ASIA_DETAIL_BRANCH_CONFIGS:
            await show_south_asia_detail_branch_result(
                query.message,
                context,
                update.effective_chat.id,
                update.effective_user.id,
                payload,
                detail_action=detail_sample_space,
                edit_existing=True,
            )
            return
        if detail_sample_space in _WEST_EURASIA_DETAIL_BRANCH_CONFIGS:
            await show_west_eurasia_detail_branch_result(
                query.message,
                context,
                update.effective_chat.id,
                update.effective_user.id,
                payload,
                detail_action=detail_sample_space,
                edit_existing=True,
            )
            return
        if detail_sample_space in _EAST_EURASIA_DETAIL_BRANCH_CONFIGS:
            await show_east_eurasia_detail_branch_result(
                query.message,
                context,
                update.effective_chat.id,
                update.effective_user.id,
                payload,
                detail_action=detail_sample_space,
                edit_existing=True,
            )
            return
        await show_caucasus_detail_branch_result(
            query.message,
            context,
            update.effective_chat.id,
            update.effective_user.id,
            payload,
            detail_action=detail_sample_space,
            edit_existing=True,
        )
        return

    if root_action == 'csp':
        await query.answer()
        if update.effective_user is None:
            return
        if _is_photo_message(query.message):
            if update.effective_chat is None:
                return
            items = _list_global_ready_samples(_my_data_store(context), update.effective_user.id)
            await _show_menu_from_photo_message(
                query.message,
                context,
                chat_id=update.effective_chat.id,
                user_id=update.effective_user.id,
                text=configured_space_sample_picker_text('Caucasus / Steppe', items),
                reply_markup=build_caucasus_steppe_population_sample_picker_keyboard(items),
            )
            return
        await show_caucasus_steppe_population_sample_picker(
            query.message,
            context,
            update.effective_user.id,
            edit_existing=True,
        )
        return

    if root_action == 'csp_sample':
        await query.answer()
        if update.effective_user is None or update.effective_chat is None or not payload:
            return
        await show_caucasus_steppe_all_populations_result(
            query.message,
            context,
            update.effective_chat.id,
            update.effective_user.id,
            payload,
            edit_existing=True,
        )
        return

    if root_action in {branch['population_sample_root'] for branch in _EUROPE_DETAIL_BRANCH_CONFIGS.values()}:
        await query.answer()
        if update.effective_user is None or update.effective_chat is None or not payload:
            return
        detail_action = next(
            key for key, branch in _EUROPE_DETAIL_BRANCH_CONFIGS.items()
            if branch['population_sample_root'] == root_action
        )
        await show_europe_detail_branch_result(
            query.message,
            context,
            update.effective_chat.id,
            update.effective_user.id,
            payload,
            detail_action=detail_action,
            mode='populations',
            edit_existing=True,
        )
        return

    if root_action in {branch['population_sample_root'] for branch in _WEST_EURASIA_DETAIL_BRANCH_CONFIGS.values()}:
        await query.answer()
        if update.effective_user is None or update.effective_chat is None or not payload:
            return
        detail_action = next(
            key for key, branch in _WEST_EURASIA_DETAIL_BRANCH_CONFIGS.items()
            if branch['population_sample_root'] == root_action
        )
        await show_west_eurasia_detail_branch_result(
            query.message,
            context,
            update.effective_chat.id,
            update.effective_user.id,
            payload,
            detail_action=detail_action,
            mode='populations',
            edit_existing=True,
        )
        return

    if root_action in {branch['population_sample_root'] for branch in _SOUTH_ASIA_DETAIL_BRANCH_CONFIGS.values()}:
        await query.answer()
        if update.effective_user is None or update.effective_chat is None or not payload:
            return
        detail_action = next(
            key for key, branch in _SOUTH_ASIA_DETAIL_BRANCH_CONFIGS.items()
            if branch['population_sample_root'] == root_action
        )
        await show_south_asia_detail_branch_result(
            query.message,
            context,
            update.effective_chat.id,
            update.effective_user.id,
            payload,
            detail_action=detail_action,
            mode='populations',
            edit_existing=True,
        )
        return

    if root_action in {branch['population_sample_root'] for branch in _EAST_EURASIA_DETAIL_BRANCH_CONFIGS.values()}:
        await query.answer()
        if update.effective_user is None or update.effective_chat is None or not payload:
            return
        detail_action = next(
            key for key, branch in _EAST_EURASIA_DETAIL_BRANCH_CONFIGS.items()
            if branch['population_sample_root'] == root_action
        )
        await show_east_eurasia_detail_branch_result(
            query.message,
            context,
            update.effective_chat.id,
            update.effective_user.id,
            payload,
            detail_action=detail_action,
            mode='populations',
            edit_existing=True,
        )
        return

    if root_action in {branch['population_sample_root'] for branch in _CAUCASUS_DETAIL_BRANCH_CONFIGS.values()}:
        await query.answer()
        if update.effective_user is None or update.effective_chat is None or not payload:
            return
        detail_action = next(
            key for key, branch in _CAUCASUS_DETAIL_BRANCH_CONFIGS.items()
            if branch['population_sample_root'] == root_action
        )
        await show_caucasus_detail_branch_result(
            query.message,
            context,
            update.effective_chat.id,
            update.effective_user.id,
            payload,
            detail_action=detail_action,
            mode='populations',
            edit_existing=True,
        )
        return

    if root_action in {branch['population_callback'] for branch in _EUROPE_DETAIL_BRANCH_CONFIGS.values()}:
        await query.answer()
        if update.effective_user is None:
            return
        detail_action = next(
            key for key, branch in _EUROPE_DETAIL_BRANCH_CONFIGS.items()
            if branch['population_callback'] == root_action
        )
        if _is_photo_message(query.message):
            if update.effective_chat is None:
                return
            await _show_menu_from_photo_message(
                query.message,
                context,
                chat_id=update.effective_chat.id,
                user_id=update.effective_user.id,
                text=caucasus_branch_mode_text(_EUROPE_DETAIL_BRANCH_CONFIGS[detail_action]['title']),
                reply_markup=build_europe_branch_mode_keyboard(detail_action),
            )
            return
        await show_europe_branch_menu(query.message, detail_action=detail_action, edit_existing=True)
        return

    if root_action in {branch['population_callback'] for branch in _WEST_EURASIA_DETAIL_BRANCH_CONFIGS.values()}:
        await query.answer()
        if update.effective_user is None:
            return
        detail_action = next(
            key for key, branch in _WEST_EURASIA_DETAIL_BRANCH_CONFIGS.items()
            if branch['population_callback'] == root_action
        )
        if _is_photo_message(query.message):
            if update.effective_chat is None:
                return
            await _show_menu_from_photo_message(
                query.message,
                context,
                chat_id=update.effective_chat.id,
                user_id=update.effective_user.id,
                text=caucasus_branch_mode_text(_WEST_EURASIA_DETAIL_BRANCH_CONFIGS[detail_action]['title']),
                reply_markup=build_west_eurasia_branch_mode_keyboard(detail_action),
            )
            return
        await show_west_eurasia_branch_menu(query.message, detail_action=detail_action, edit_existing=True)
        return

    if root_action in {branch['population_callback'] for branch in _SOUTH_ASIA_DETAIL_BRANCH_CONFIGS.values()}:
        await query.answer()
        if update.effective_user is None:
            return
        detail_action = next(
            key for key, branch in _SOUTH_ASIA_DETAIL_BRANCH_CONFIGS.items()
            if branch['population_callback'] == root_action
        )
        if _is_photo_message(query.message):
            if update.effective_chat is None:
                return
            await _show_menu_from_photo_message(
                query.message,
                context,
                chat_id=update.effective_chat.id,
                user_id=update.effective_user.id,
                text=caucasus_branch_mode_text(_SOUTH_ASIA_DETAIL_BRANCH_CONFIGS[detail_action]['title']),
                reply_markup=build_south_asia_branch_mode_keyboard(detail_action),
            )
            return
        await show_south_asia_branch_menu(query.message, detail_action=detail_action, edit_existing=True)
        return

    if root_action in {branch['population_callback'] for branch in _EAST_EURASIA_DETAIL_BRANCH_CONFIGS.values()}:
        await query.answer()
        if update.effective_user is None:
            return
        detail_action = next(
            key for key, branch in _EAST_EURASIA_DETAIL_BRANCH_CONFIGS.items()
            if branch['population_callback'] == root_action
        )
        if _is_photo_message(query.message):
            if update.effective_chat is None:
                return
            await _show_menu_from_photo_message(
                query.message,
                context,
                chat_id=update.effective_chat.id,
                user_id=update.effective_user.id,
                text=caucasus_branch_mode_text(_EAST_EURASIA_DETAIL_BRANCH_CONFIGS[detail_action]['title']),
                reply_markup=build_east_eurasia_branch_mode_keyboard(detail_action),
            )
            return
        await show_east_eurasia_branch_menu(query.message, detail_action=detail_action, edit_existing=True)
        return

    if root_action in {branch['population_callback'] for branch in _CAUCASUS_DETAIL_BRANCH_CONFIGS.values()}:
        await query.answer()
        if update.effective_user is None:
            return
        detail_action = next(
            key for key, branch in _CAUCASUS_DETAIL_BRANCH_CONFIGS.items()
            if branch['population_callback'] == root_action
        )
        if _is_photo_message(query.message):
            if update.effective_chat is None:
                return
            await _show_menu_from_photo_message(
                query.message,
                context,
                chat_id=update.effective_chat.id,
                user_id=update.effective_user.id,
                text=caucasus_branch_mode_text(_CAUCASUS_DETAIL_BRANCH_CONFIGS[detail_action]['title']),
                reply_markup=build_caucasus_branch_mode_keyboard(detail_action),
            )
            return
        await show_caucasus_branch_menu(query.message, detail_action=detail_action, edit_existing=True)
        return

    if payload and await _handle_coordinate_space_save(
        query,
        context,
        update.effective_user.id if update.effective_user is not None else 0,
        root_action,
        payload,
        lang=lang,
    ):
        return

    title = _ROOT_PLACEHOLDER_TITLES.get(action)
    if title is not None:
        await query.answer()
        await show_coordinate_space_stub(
            query.message,
            title=title,
            back_callback=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:root',
            edit_existing=True,
        )
        return

    ready_made_title = _READY_MADE_SPACE_TITLES.get(action)
    if ready_made_title is not None:
        await query.answer()
        await show_coordinate_space_stub(
            query.message,
            title=ready_made_title,
            back_callback=f'{COORDINATE_SPACE_CALLBACK_PREFIX}:ready_made_spaces',
            edit_existing=True,
        )
        return

    await query.answer()

