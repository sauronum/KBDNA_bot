from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from g25_core.vendor.admix import admix_models


@dataclass(frozen=True)
class RawAdmixtureModel:
    name: str
    population_count: int
    allele_file: str
    frequency_file: str
    installed: bool


@dataclass(frozen=True)
class RawAdmixtureProject:
    code: str
    title: str
    models: tuple[RawAdmixtureModel, ...]


RAW_ADMIXTURE_PROJECTS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "mdlp",
        "MDLP Project",
        ("MDLPK27",),
    ),
    (
        "eurogenes",
        "Eurogenes",
        ("K13", "K36", "EUtest13", "Jtest14"),
    ),
    (
        "dodecad",
        "Dodecad",
        ("K7b", "K12b", "globe13", "globe10", "world9", "Eurasia7", "Africa9", "weac2"),
    ),
    (
        "harappa",
        "HarappaWorld",
        ("HarappaWorld",),
    ),
    (
        "ethihelix",
        "Ethihelix",
        ("E11",),
    ),
    (
        "puntdnal",
        "puntDNAL",
        ("puntDNAL", "AncientNearEast13", "K7AMI", "K8AMI"),
    ),
    (
        "gedrosia",
        "GedrosiaDNA",
        ("TurkicK11", "KurdishK10", "K47", "K7M1", "K13M2", "K14M1", "K18M4", "K25R1", "MichalK25"),
    ),
)


def list_raw_admixture_models(data_dir: Path) -> list[RawAdmixtureModel]:
    models: list[RawAdmixtureModel] = []
    for model_name in admix_models.models():
        allele_file = admix_models.snp_file_name(model_name)
        frequency_file = admix_models.frequency_file_name(model_name)
        models.append(
            RawAdmixtureModel(
                name=model_name,
                population_count=admix_models.n_populations(model_name),
                allele_file=allele_file,
                frequency_file=frequency_file,
                installed=(data_dir / allele_file).exists() and (data_dir / frequency_file).exists(),
            )
        )
    return models


def list_raw_admixture_projects(data_dir: Path) -> list[RawAdmixtureProject]:
    models_by_name = {model.name: model for model in list_raw_admixture_models(data_dir)}
    projects: list[RawAdmixtureProject] = []
    assigned: set[str] = set()
    for code, title, model_names in RAW_ADMIXTURE_PROJECTS:
        project_models = tuple(models_by_name[name] for name in model_names if name in models_by_name)
        assigned.update(model.name for model in project_models)
        projects.append(RawAdmixtureProject(code=code, title=title, models=project_models))

    unassigned = tuple(model for model in models_by_name.values() if model.name not in assigned)
    if unassigned:
        projects.append(RawAdmixtureProject(code="other", title="Other", models=unassigned))
    return projects


def get_raw_admixture_project(data_dir: Path, code: str) -> RawAdmixtureProject | None:
    clean_code = code.strip().lower()
    for project in list_raw_admixture_projects(data_dir):
        if project.code == clean_code:
            return project
    return None


def get_raw_admixture_model(data_dir: Path, model_name: str) -> RawAdmixtureModel | None:
    clean_name = model_name.strip()
    for model in list_raw_admixture_models(data_dir):
        if model.name == clean_name:
            return model
    return None
