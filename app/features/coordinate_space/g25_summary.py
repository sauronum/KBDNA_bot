from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from g25_core import g25_engine


MODERN_G25_AVERAGES_PATH = Path(__file__).resolve().parent / "data" / "Global25_PCA_modern_pop_averages_scaled.txt"


GLOBAL_REGION_LABELS: dict[str, tuple[str, ...]] = {
    "Europe": (
        "Austrian",
        "BelgianA",
        "Czech",
        "Danish",
        "Dutch",
        "English",
        "French_Paris",
        "German",
        "Irish",
        "Italian_Northeast",
        "Norwegian",
        "Polish",
        "Romanian",
        "Scottish",
        "Spanish_Castilla_Y_Leon",
        "Swedish",
        "Belarusian",
        "Ukrainian_Lviv",
        "Russian_Belgorod",
        "Russian_Smolensk",
    ),
    "Caucasus": (
        "Abazin",
        "Abkhasian",
        "Adygei",
        "Circassian",
        "Cherkes",
        "Avar",
        "Balkar",
        "Chechen",
        "Ingushian",
        "Kabardin",
        "Karachay",
        "Kumyk",
        "Lezgin",
        "North_Ossetian",
        "Ossetian",
        "Armenian_Ararat",
        "Armenian_Syunik",
        "Georgian_Kart",
        "Georgian_Kakh",
        "Georgian_Svaneti",
    ),
    "Middle East": (
        "Alawite",
        "BedouinA",
        "BedouinB",
        "Druze",
        "Jordanian",
        "Lebanese_Christian",
        "Lebanese_Druze",
        "Lebanese_Maronite_Christian_Zgharta",
        "Lebanese_Muslim",
        "Palestinian",
        "Palestinian_Beit_Sahour",
        "Samaritan",
        "Syrian",
        "Syrian_Aleppo",
        "Syrian_Hama",
        "Syrian_Homs",
        "Iraqi_Arab_Central",
        "Iraqi_Arab_West",
    ),
    "Central Asia": (
        "Uzbek",
        "Turkmen",
        "Turkmen_Uzbekistan",
        "Turkmen_Iran",
        "Kirghiz_Tajikistan_Pamir",
        "Tajik_Afghanistan",
        "Tajik_Tajikistan_Ayni",
        "Tajik_Tajikistan_Hisor",
        "Tajik_Tajikistan_Kulob",
        "Tajik_Yaghnobi",
        "Pamiri_Badakhshan",
        "Pamiri_Rushan",
        "Pamiri_Shugnan",
        "Pamiri_Wakhi",
        "Pashtun_Afghanistan",
    ),
    "South Asia": (
        "Arain",
        "Awan",
        "Gujarati",
        "Punjabi_Hindu_India",
        "Punjabi_Lahore",
        "Bengali_Bangladesh",
        "Bengali_India",
        "Sinhala",
        "Telugu",
        "Brahmin_Tamil_Nadu",
        "Nepali_Indo-Aryan_A",
        "Balochi_Pakistan",
        "Pashtun_Pakistan",
    ),
    "East Asia": (
        "Han_Henan",
        "Han_Shandong",
        "Han_Sichuan",
        "Japanese",
        "Korean",
        "Mongol",
        "Daur",
        "Hezhen",
        "Yi",
        "Naxi",
    ),
    "Africa": (
        "Algerian",
        "Berber_Algeria",
        "Moroccan",
        "Tunisian",
        "Libyan",
        "EgyptianA",
        "Egyptian_Copt",
        "Bantu_Kenya",
        "Bantu_S.E.",
        "Baka",
        "Bakola",
        "Bedzan",
    ),
    "Americas": (
        "Amerindian_North",
        "Aymara",
        "Quechua",
        "Pima",
        "Karitiana",
        "Surui",
        "Mixtec",
        "Mayan",
    ),
    "Oceania": (
        "Australian",
        "Papuan",
        "Papuan_Highland_A",
        "Papuan_Highland_B",
        "Maori",
    ),
}


@dataclass(frozen=True)
class G25PopulationDistance:
    name: str
    distance: float


@dataclass(frozen=True)
class G25CoordinateSummary:
    region: str
    top_modern: tuple[G25PopulationDistance, ...]
    first_distance: float | None
    first_second_gap: float | None


@lru_cache(maxsize=1)
def load_modern_population_averages(
    path: Path = MODERN_G25_AVERAGES_PATH,
) -> tuple[g25_engine.G25Entry, ...]:
    if not path.exists():
        raise FileNotFoundError(f"Missing modern G25 refs file: {path}")
    return tuple(g25_engine.load_g25_entries(path))


@lru_cache(maxsize=1)
def load_modern_population_map(path: Path = MODERN_G25_AVERAGES_PATH) -> dict[str, tuple[float, ...]]:
    return {entry.name: entry.coords for entry in load_modern_population_averages(path)}


def build_centroid(
    populations: dict[str, tuple[float, ...]],
    *,
    region_name: str,
    labels: tuple[str, ...],
) -> tuple[float, ...]:
    missing = [label for label in labels if label not in populations]
    if missing:
        raise ValueError(f"Region {region_name} is missing modern labels: {', '.join(missing)}")

    dims = len(next(iter(populations.values())))
    return tuple(sum(populations[label][index] for label in labels) / len(labels) for index in range(dims))


@lru_cache(maxsize=1)
def global_region_profiles(path: Path = MODERN_G25_AVERAGES_PATH) -> dict[str, tuple[float, ...]]:
    populations = load_modern_population_map(path)
    return {
        region_name: build_centroid(populations, region_name=region_name, labels=labels)
        for region_name, labels in GLOBAL_REGION_LABELS.items()
    }


def classify_global_region(g25_line: str) -> str:
    target = g25_engine.parse_g25_line(g25_line)
    profiles = global_region_profiles()
    return min(profiles, key=lambda region_name: g25_engine.euclidean_distance(target.coords, profiles[region_name]))


def summarize_g25_coordinate(g25_line: str, *, top: int = 3) -> G25CoordinateSummary:
    target = g25_engine.parse_g25_line(g25_line)
    nearest = g25_engine.nearest_entries(target, load_modern_population_averages(), top=max(2, top))
    top_modern = tuple(
        G25PopulationDistance(name=entry.name, distance=distance)
        for distance, entry in nearest[:top]
    )
    first_distance = top_modern[0].distance if top_modern else None
    first_second_gap = (nearest[1][0] - nearest[0][0]) if len(nearest) > 1 else None
    return G25CoordinateSummary(
        region=classify_global_region(g25_line),
        top_modern=top_modern,
        first_distance=first_distance,
        first_second_gap=first_second_gap,
    )
