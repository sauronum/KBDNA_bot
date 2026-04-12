import argparse
import json
from pathlib import Path
from typing import Iterable, List, Tuple


GROUP_RENDER_ORDER = [
    "Maikop",
    "KuraAraxes",
    "Steppe",
    "Yamnaya",
    "Anatolia_BA",
    "Baltic_BA",
    "Afanasievo",
    "Khovsgol",
    "AngaraRiver_BA",
    "Ulaanzukh",
    "YellowRiver",
    "BMAK",
    "Maikop_Cluster",
    "Yamnaya_Cluster",
    "Steppe_Sintashta_Cluster",
    "Anatolia_BA_Cluster",
    "KuraAraxes_Cluster",
    "Baltic_BA_Cluster",
    "Ulaanzukh_Cluster",
    "Khovsgol_Cluster",
    "YellowRiver_Cluster",
    "BMAK_Cluster",
    "Ulaanzuukh_culture_BA",
    "Khovsgol_BA",
    "Yellow_River_LN",
    "BMAC_or_Oxus_Civilization",
    "Helmandculture",
    "Steppe_MLBA",
    "RUS_Angara_River_BA",
]

GROUP_DISPLAY_ALIASES = {
    "YR": "Yellow River",
    "YellowRiver": "Yellow River",
    "Anatolia_BA": "Anatolia BA",
    "Baltic_BA": "Baltic BA",
    "AngaraRiver_BA": "Angara River BA",
    "Steppe_Sintashta_Cluster": "Steppe Sintashta",
    "Anatolia_BA_Cluster": "Anatolia BA",
    "Baltic_BA_Cluster": "Baltic BA",
    "YellowRiver_Cluster": "Yellow River",
    "YR_Cluster": "Yellow River",
    "Ulaanzuukh_culture_BA": "Ulaanzuukh culture BA",
    "Khovsgol_BA": "Khovsgol BA",
    "Yellow_River_LN": "Yellow River LN",
    "BMAC_or_Oxus_Civilization": "BMAC or Oxus Civilization",
    "Helmandculture": "Helmandculture",
    "Steppe_MLBA": "Steppe MLBA",
    "RUS_Angara_River_BA": "RUS Angara River BA",
}

VISUAL_GROUP_EXCLUSIONS = {
    "BMAK",
    "BMAK_Cluster",
}


def display_name(raw_name: str) -> str:
    if raw_name in GROUP_DISPLAY_ALIASES:
        return GROUP_DISPLAY_ALIASES[raw_name]
    if raw_name.endswith("_Cluster"):
        raw_name = raw_name[: -len("_Cluster")]
    return raw_name.replace("_", " ")


def group_sort_key(raw_name: str) -> Tuple[int, str]:
    if raw_name in GROUP_RENDER_ORDER:
        return (GROUP_RENDER_ORDER.index(raw_name), raw_name)
    return (len(GROUP_RENDER_ORDER), display_name(raw_name))


def load_groups(json_path: Path, zero_threshold: float) -> Tuple[str, float, int, List[Tuple[str, float]]]:
    data = json.loads(json_path.read_text(encoding="utf-8-sig"))
    groups = [
        (name, float(value))
        for name, value in data["groups"].items()
        if name not in VISUAL_GROUP_EXCLUSIONS and float(value) > zero_threshold
    ]
    groups.sort(key=lambda item: group_sort_key(item[0]))
    if not groups:
        raise ValueError(f"{json_path}: no non-zero groups to render.")
    return data["target"], float(data["distance"]), int(data["sources"]), groups


def render_svg(
    target: str,
    distance: float,
    sources: int,
    groups: Iterable[Tuple[str, float]],
    output_path: Path,
) -> None:
    group_list = list(groups)
    left = 16
    top = 18
    pct_x = left
    label_x = 82
    row_gap = 28
    bar_h = 12
    start_y = 70
    bar_w = 700

    label_texts = [display_name(name) for name, _ in group_list]
    max_label_chars = max(len(text) for text in label_texts)
    label_area_w = max(170, min(320, int(max_label_chars * 8.2)))
    bar_x = label_x + label_area_w + 18
    width = bar_x + bar_w + 24
    height = start_y + (row_gap * len(group_list)) + 16

    bg = "#4e4e4e"
    fg = "#ffffff"
    small = "#e8e8e8"
    bar_color = "#ff8a1f"
    bar_bg = "#6a6a6a"

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        f'<rect width="100%" height="100%" fill="{bg}"/>',
        (
            f'<text x="{left}" y="{top}" fill="{fg}" font-family="Segoe UI, Arial, sans-serif" '
            f'font-size="18">Target: {target}</text>'
        ),
        (
            f'<text x="{left}" y="{top + 22}" fill="{small}" font-family="Segoe UI, Arial, sans-serif" '
            f'font-size="16">Distance: {distance:.6f} | Sources: {sources}</text>'
        ),
    ]

    for index, (raw_name, value) in enumerate(group_list):
        name = display_name(raw_name)
        y = start_y + (index * row_gap)
        pct = value * 100.0
        fill_w = bar_w * value
        lines.append(
            f'<text x="{pct_x}" y="{y + 10}" fill="{fg}" font-family="Segoe UI, Arial, sans-serif" '
            f'font-size="16">{pct:.1f}</text>'
        )
        lines.append(
            f'<text x="{label_x}" y="{y + 10}" fill="{fg}" font-family="Segoe UI, Arial, sans-serif" '
            f'font-size="16">{name}</text>'
        )
        lines.append(
            f'<rect x="{bar_x}" y="{y}" width="{bar_w}" height="{bar_h}" fill="{bar_bg}" rx="2"/>'
        )
        lines.append(
            f'<rect x="{bar_x}" y="{y}" width="{fill_w:.2f}" height="{bar_h}" fill="{bar_color}" rx="2"/>'
        )

    lines.append("</svg>")
    output_path.write_text("\n".join(lines), encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render a fit JSON file into a compact SVG card.")
    parser.add_argument("input", help="Path to fit JSON.")
    parser.add_argument("output", help="Path to SVG output.")
    parser.add_argument(
        "--zero-threshold",
        type=float,
        default=1e-12,
        help="Skip groups with values at or below this threshold.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    target, distance, sources, groups = load_groups(Path(args.input), args.zero_threshold)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    render_svg(target, distance, sources, groups, output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
