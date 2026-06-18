from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .yfull import YFullBranch, YFullChildBranch, YFullLookupResult


Color = tuple[int, int, int]
_WIDTH = 1280
_HEIGHT = 900
THEME_DARK = "dark"
THEME_LIGHT = "light"


@dataclass(frozen=True)
class BranchVisualTheme:
    background_top: Color
    background_bottom: Color
    panel: Color
    panel_soft: Color
    text: Color
    muted: Color
    faint: Color
    border: Color
    gold: Color
    cyan: Color
    green: Color
    pink: Color


_DARK = BranchVisualTheme(
    background_top=(8, 15, 25),
    background_bottom=(16, 24, 38),
    panel=(18, 28, 43),
    panel_soft=(25, 38, 56),
    text=(239, 244, 250),
    muted=(157, 171, 191),
    faint=(91, 108, 132),
    border=(48, 66, 91),
    gold=(244, 184, 78),
    cyan=(83, 200, 214),
    green=(103, 209, 158),
    pink=(224, 111, 150),
)

_LIGHT = BranchVisualTheme(
    background_top=(244, 247, 251),
    background_bottom=(229, 236, 244),
    panel=(255, 255, 255),
    panel_soft=(239, 244, 249),
    text=(25, 35, 49),
    muted=(84, 101, 124),
    faint=(132, 146, 165),
    border=(201, 211, 224),
    gold=(188, 124, 27),
    cyan=(25, 139, 157),
    green=(36, 151, 106),
    pink=(186, 68, 112),
)

_RU_GEOGRAPHY = {
    "Brazil": "Бразилия",
    "Georgia": "Грузия",
    "Lebanon": "Ливан",
    "Puerto Rico": "Пуэрто-Рико",
    "Russia": "Россия",
    "Saudi Arabia": "Саудовская Аравия",
    "Spain": "Испания",
    "Turkey": "Турция",
    "United States": "США",
}


def render_yfull_branch_png(
    output_path: Path,
    result: YFullLookupResult,
    *,
    lang: str = "ru",
    theme: str = THEME_DARK,
) -> Path:
    visual_theme = _LIGHT if str(theme).strip().lower() == THEME_LIGHT else _DARK
    image = Image.new("RGB", (_WIDTH, _HEIGHT), visual_theme.background_top)
    draw = ImageDraw.Draw(image, "RGBA")
    fonts = _fonts()
    _draw_background(draw, visual_theme)
    _draw_header(draw, fonts, visual_theme, result)
    _draw_lineage(draw, fonts, visual_theme, result.branch, lang)
    _draw_age_panel(draw, fonts, visual_theme, result.branch, lang)
    _draw_children_panel(draw, fonts, visual_theme, result.branch, lang)
    _draw_metrics_panel(draw, fonts, visual_theme, result.branch, lang)
    _draw_geography_panel(draw, fonts, visual_theme, result.branch, lang)
    _draw_footer(draw, fonts, visual_theme, result, lang)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, format="PNG", optimize=True)
    return output_path


def _draw_background(draw: ImageDraw.ImageDraw, theme: BranchVisualTheme) -> None:
    for y in range(_HEIGHT):
        ratio = y / max(1, _HEIGHT - 1)
        color = tuple(
            round(theme.background_top[index] * (1.0 - ratio) + theme.background_bottom[index] * ratio)
            for index in range(3)
        )
        draw.line((0, y, _WIDTH, y), fill=(*color, 255))
    draw.ellipse((930, -180, 1390, 280), fill=(*theme.cyan, 18))
    draw.ellipse((-170, 650, 300, 1120), fill=(*theme.gold, 14))
    for offset in range(0, 1280, 80):
        draw.line((offset, 0, offset - 320, 900), fill=(*theme.border, 18), width=1)


def _draw_header(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, ImageFont.ImageFont],
    theme: BranchVisualTheme,
    result: YFullLookupResult,
) -> None:
    branch = result.branch
    draw.text((42, 28), "YFULL YTREE", fill=(*theme.cyan, 255), font=fonts["label"])
    draw.text((42, 52), _ellipsize(draw, branch.name, fonts["title"], 750), fill=(*theme.text, 255), font=fonts["title"])
    snps = "  ·  ".join(branch.snps[:4]) or "terminal branch"
    draw.text((44, 98), _ellipsize(draw, snps, fonts["small"], 760), fill=(*theme.muted, 255), font=fonts["small"])

    version = f"v{branch.tree_version}" if branch.tree_version else "YTREE"
    _pill(draw, fonts, theme, (1000, 30), version, theme.cyan)
    cache_label = {"live": "LIVE", "cache": "CACHE", "stale": "STALE"}.get(result.cache_status, "YTREE")
    cache_color = theme.green if result.cache_status == "live" else theme.gold
    _pill(draw, fonts, theme, (1120, 30), cache_label, cache_color)
    if branch.release_date:
        release = _ellipsize(draw, branch.release_date, fonts["tiny"], 230)
        draw.text((1198 - draw.textlength(release, font=fonts["tiny"]), 92), release, fill=(*theme.muted, 255), font=fonts["tiny"])


def _draw_lineage(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, ImageFont.ImageFont],
    theme: BranchVisualTheme,
    branch: YFullBranch,
    lang: str,
) -> None:
    rect = (40, 132, 1240, 236)
    _panel(draw, theme, rect)
    draw.text((62, 151), _copy(lang, "Линия", "Lineage"), fill=(*theme.text, 255), font=fonts["section"])
    path = list(_compact_path(branch.path or (branch.name,)))
    if not path:
        return
    left = 220
    right = 1212
    center_y = 188
    step = 0 if len(path) == 1 else (right - left) / (len(path) - 1)
    if len(path) > 1:
        draw.line((left, center_y, right, center_y), fill=(*theme.border, 255), width=4)
    for index, item in enumerate(path):
        x = left + index * step
        current = index == len(path) - 1
        color = theme.gold if current else theme.cyan
        radius = 8 if current else 6
        draw.ellipse((x - radius, center_y - radius, x + radius, center_y + radius), fill=(*color, 255))
        label = _ellipsize(draw, item, fonts["tiny"], max(82, step - 12 if step else 180))
        label_width = draw.textlength(label, font=fonts["tiny"])
        label_color = theme.text if current else theme.muted
        draw.text((x - label_width / 2, center_y + 15), label, fill=(*label_color, 255), font=fonts["tiny"])


def _draw_age_panel(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, ImageFont.ImageFont],
    theme: BranchVisualTheme,
    branch: YFullBranch,
    lang: str,
) -> None:
    x, y, w, h = 40, 258, 760, 242
    _panel(draw, theme, (x, y, x + w, y + h))
    draw.text((x + 22, y + 18), _copy(lang, "Возраст ветви", "Branch age"), fill=(*theme.text, 255), font=fonts["section"])
    draw.text((x + 22, y + 49), _copy(lang, "лет до настоящего времени", "years before present"), fill=(*theme.muted, 255), font=fonts["tiny"])

    values = [value for value in (branch.formed_ybp, branch.tmrca_ybp) if value is not None]
    for interval in (branch.formed_ci_ybp, branch.tmrca_ci_ybp):
        if interval is not None:
            values.extend(interval)
    if not values:
        _empty(draw, fonts, theme, (x + 22, y + 100, w - 44, 80), _copy(lang, "Возраст не опубликован", "Age estimate unavailable"))
        return

    maximum = max(1000, int(max(values) * 1.12))
    line_left, line_right = x + 92, x + w - 40
    line_y = y + 132
    draw.line((line_left, line_y, line_right, line_y), fill=(*theme.border, 255), width=4)
    for index in range(5):
        age = round(maximum * index / 4)
        px = line_left + (line_right - line_left) * index / 4
        draw.line((px, line_y - 6, px, line_y + 7), fill=(*theme.faint, 255), width=2)
        label = _short_age(age)
        label_w = draw.textlength(label, font=fonts["tiny"])
        draw.text((px - label_w / 2, line_y + 15), label, fill=(*theme.muted, 255), font=fonts["tiny"])

    _age_marker(
        draw,
        fonts,
        theme,
        line=(line_left, line_right, line_y),
        maximum=maximum,
        value=branch.formed_ybp,
        interval=branch.formed_ci_ybp,
        label=_copy(lang, "Сформировалась", "Formed"),
        color=theme.gold,
        label_y=y + 76,
    )
    _age_marker(
        draw,
        fonts,
        theme,
        line=(line_left, line_right, line_y),
        maximum=maximum,
        value=branch.tmrca_ybp,
        interval=branch.tmrca_ci_ybp,
        label="TMRCA",
        color=theme.cyan,
        label_y=y + 181,
    )


def _age_marker(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, ImageFont.ImageFont],
    theme: BranchVisualTheme,
    *,
    line: tuple[int, int, int],
    maximum: int,
    value: int | None,
    interval: tuple[int, int] | None,
    label: str,
    color: Color,
    label_y: int,
) -> None:
    if value is None:
        return
    left, right, line_y = line
    if interval is not None:
        interval_left = left + (right - left) * interval[0] / maximum
        interval_right = left + (right - left) * interval[1] / maximum
        draw.rounded_rectangle((interval_left, line_y - 7, interval_right, line_y + 7), radius=7, fill=(*color, 75))
    position = left + (right - left) * value / maximum
    draw.line((position, line_y - 16, position, line_y + 16), fill=(*color, 255), width=4)
    draw.ellipse((position - 7, line_y - 7, position + 7, line_y + 7), fill=(*color, 255))
    value_text = f"{label}: {value:,}".replace(",", " ")
    draw.text((left, label_y), value_text, fill=(*color, 255), font=fonts["small"])


def _draw_children_panel(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, ImageFont.ImageFont],
    theme: BranchVisualTheme,
    branch: YFullBranch,
    lang: str,
) -> None:
    x, y, w, h = 40, 522, 760, 286
    _panel(draw, theme, (x, y, x + w, y + h))
    children = [item for item in branch.children if not item.name.endswith("*")]
    draw.text((x + 22, y + 18), _copy(lang, "Дочерние ветви", "Child branches"), fill=(*theme.text, 255), font=fonts["section"])
    draw.text((x + w - 56, y + 18), str(len(children)), fill=(*theme.gold, 255), font=fonts["section"])
    if not children:
        _empty(draw, fonts, theme, (x + 22, y + 82, w - 44, 130), _copy(lang, "Дочерние ветви не показаны", "No child branches shown"))
        return
    row_y = y + 62
    for index, child in enumerate(children[:6]):
        _child_row(draw, fonts, theme, (x + 20, row_y + index * 34, w - 40, 29), child)
    if len(children) > 6:
        draw.text((x + 24, y + h - 30), f"+{len(children) - 6}", fill=(*theme.muted, 255), font=fonts["tiny"])


def _child_row(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, ImageFont.ImageFont],
    theme: BranchVisualTheme,
    rect: tuple[int, int, int, int],
    child: YFullChildBranch,
) -> None:
    x, y, w, h = rect
    if y % 2:
        draw.rounded_rectangle((x, y, x + w, y + h), radius=7, fill=(*theme.panel_soft, 160))
    draw.ellipse((x + 4, y + 10, x + 12, y + 18), fill=(*theme.cyan, 255))
    draw.text((x + 24, y + 4), _ellipsize(draw, child.name, fonts["small"], 255), fill=(*theme.text, 255), font=fonts["small"])
    snps = ", ".join(child.snps[:2]) or "-"
    draw.text((x + 300, y + 6), _ellipsize(draw, snps, fonts["tiny"], 190), fill=(*theme.muted, 255), font=fonts["tiny"])
    age = f"{child.tmrca_ybp:,}".replace(",", " ") if child.tmrca_ybp is not None else "-"
    draw.text((x + 520, y + 6), age, fill=(*theme.gold, 255), font=fonts["tiny"])
    samples = str(child.public_sample_count)
    draw.text((x + w - 16 - draw.textlength(samples, font=fonts["tiny"]), y + 6), samples, fill=(*theme.green, 255), font=fonts["tiny"])


def _draw_metrics_panel(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, ImageFont.ImageFont],
    theme: BranchVisualTheme,
    branch: YFullBranch,
    lang: str,
) -> None:
    x, y, w, h = 824, 258, 416, 242
    _panel(draw, theme, (x, y, x + w, y + h))
    draw.text((x + 22, y + 18), _copy(lang, "Сводка", "Summary"), fill=(*theme.text, 255), font=fonts["section"])
    children = [item for item in branch.children if not item.name.endswith("*")]
    basal = sum(item.public_sample_count for item in branch.children if item.name.endswith("*"))
    metrics = (
        (_copy(lang, "Образцы", "Samples"), str(branch.public_sample_count), theme.green),
        (_copy(lang, "Ветви", "Children"), str(len(children)), theme.cyan),
        (_copy(lang, "Базальные", "Basal"), str(basal), theme.gold),
        ("SNP", str(len(branch.snps)), theme.pink),
    )
    card_w = 174
    for index, (label, value, color) in enumerate(metrics):
        cx = x + 22 + (index % 2) * (card_w + 18)
        cy = y + 62 + (index // 2) * 78
        _metric_card(draw, fonts, theme, (cx, cy, card_w, 64), label, value, color)


def _draw_geography_panel(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, ImageFont.ImageFont],
    theme: BranchVisualTheme,
    branch: YFullBranch,
    lang: str,
) -> None:
    x, y, w, h = 824, 522, 416, 286
    _panel(draw, theme, (x, y, x + w, y + h))
    draw.text((x + 22, y + 18), _copy(lang, "География", "Origins"), fill=(*theme.text, 255), font=fonts["section"])
    values = list(branch.geographies[:5])
    if not values:
        _empty(draw, fonts, theme, (x + 22, y + 82, w - 44, 130), _copy(lang, "География не опубликована", "Geography unavailable"))
        return
    maximum = max(1, max(item.count for item in values))
    row_y = y + 62
    for index, item in enumerate(values):
        yy = row_y + index * 39
        label = _RU_GEOGRAPHY.get(item.label, item.label) if lang != "en" else item.label
        draw.text((x + 24, yy), _ellipsize(draw, label, fonts["tiny"], 145), fill=(*theme.text, 255), font=fonts["tiny"])
        bar_x, bar_w = x + 178, 164
        draw.rounded_rectangle((bar_x, yy + 3, bar_x + bar_w, yy + 15), radius=6, fill=(*theme.panel_soft, 255))
        value_w = max(8, bar_w * item.count / maximum)
        draw.rounded_rectangle((bar_x, yy + 3, bar_x + value_w, yy + 15), radius=6, fill=(*theme.cyan, 220))
        value = str(item.count)
        draw.text((x + w - 24 - draw.textlength(value, font=fonts["tiny"]), yy), value, fill=(*theme.muted, 255), font=fonts["tiny"])


def _draw_footer(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, ImageFont.ImageFont],
    theme: BranchVisualTheme,
    result: YFullLookupResult,
    lang: str,
) -> None:
    y = 836
    draw.line((42, y, 1238, y), fill=(*theme.border, 180), width=1)
    left = _copy(lang, "Источник: публичный YFull YTree", "Source: public YFull YTree")
    draw.text((44, y + 19), left, fill=(*theme.muted, 255), font=fonts["tiny"])
    fetched = result.branch.fetched_at[:10] if result.branch.fetched_at else "-"
    right = f"{fetched}  ·  {result.cache_status.upper()}"
    draw.text((1236 - draw.textlength(right, font=fonts["tiny"]), y + 19), right, fill=(*theme.faint, 255), font=fonts["tiny"])
    note = _copy(lang, "Оценки возраста имеют статистическую неопределённость.", "Age estimates carry statistical uncertainty.")
    draw.text((44, y + 42), note, fill=(*theme.faint, 255), font=fonts["tiny"])


def _panel(draw: ImageDraw.ImageDraw, theme: BranchVisualTheme, rect: tuple[int, int, int, int]) -> None:
    x1, y1, x2, y2 = rect
    draw.rounded_rectangle((x1 + 4, y1 + 7, x2 + 4, y2 + 7), radius=18, fill=(0, 0, 0, 24))
    draw.rounded_rectangle(rect, radius=18, fill=(*theme.panel, 245), outline=(*theme.border, 210), width=1)


def _metric_card(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, ImageFont.ImageFont],
    theme: BranchVisualTheme,
    rect: tuple[int, int, int, int],
    label: str,
    value: str,
    color: Color,
) -> None:
    x, y, w, h = rect
    draw.rounded_rectangle((x, y, x + w, y + h), radius=12, fill=(*theme.panel_soft, 255))
    draw.rectangle((x, y + 10, x + 4, y + h - 10), fill=(*color, 255))
    draw.text((x + 16, y + 10), label.upper(), fill=(*theme.muted, 255), font=fonts["label"])
    draw.text((x + 16, y + 31), value, fill=(*color, 255), font=fonts["section"])


def _pill(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, ImageFont.ImageFont],
    theme: BranchVisualTheme,
    origin: tuple[int, int],
    text: str,
    color: Color,
) -> None:
    x, y = origin
    width = int(draw.textlength(text, font=fonts["label"])) + 24
    draw.rounded_rectangle((x, y, x + width, y + 30), radius=15, fill=(*theme.panel_soft, 255), outline=(*color, 150), width=1)
    draw.text((x + 12, y + 7), text, fill=(*color, 255), font=fonts["label"])


def _empty(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, ImageFont.ImageFont],
    theme: BranchVisualTheme,
    rect: tuple[int, int, int, int],
    text: str,
) -> None:
    x, y, w, h = rect
    text = _ellipsize(draw, text, fonts["small"], w - 20)
    text_w = draw.textlength(text, font=fonts["small"])
    draw.text((x + (w - text_w) / 2, y + h / 2 - 10), text, fill=(*theme.muted, 255), font=fonts["small"])


def _compact_path(path: tuple[str, ...]) -> tuple[str, ...]:
    if len(path) <= 6:
        return path
    return (path[0], "...", *path[-4:])


def _short_age(value: int) -> str:
    if value >= 1000:
        return f"{value / 1000:.1f}k"
    return str(value)


def _copy(lang: str, ru: str, en: str) -> str:
    return en if lang == "en" else ru


def _ellipsize(draw: ImageDraw.ImageDraw, text: object, font: ImageFont.ImageFont, max_width: float) -> str:
    value = str(text)
    if draw.textlength(value, font=font) <= max_width:
        return value
    suffix = "..."
    while value and draw.textlength(value + suffix, font=font) > max_width:
        value = value[:-1]
    return value + suffix if value else suffix


def _fonts() -> dict[str, ImageFont.ImageFont]:
    return {
        "title": _font(44, bold=True),
        "section": _font(20, bold=True),
        "label": _font(12, bold=True),
        "small": _font(16),
        "tiny": _font(13),
    }


def _font(size: int, *, bold: bool = False) -> ImageFont.ImageFont:
    candidates = (
        Path("C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf"),
        Path("C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    )
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default()
