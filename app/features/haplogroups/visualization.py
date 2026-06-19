from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .yfull import YFullBranch, YFullChildBranch, YFullLookupResult


Color = tuple[int, int, int]
_WIDTH = 1280
_BASE_HEIGHT = 900
_BASE_CHILD_ROWS = 14
_CHILD_ROW_STEP = 29
_BASE_GEOGRAPHY_ROWS = 7
_GEOGRAPHY_ROW_STEP = 49
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
    image_height = _branch_visual_height(result.branch)
    extra_height = image_height - _BASE_HEIGHT
    image = Image.new("RGB", (_WIDTH, image_height), visual_theme.background_top)
    draw = ImageDraw.Draw(image, "RGBA")
    fonts = _fonts()
    _draw_background(draw, visual_theme, image_height)
    _draw_header(draw, fonts, visual_theme, result)
    _draw_age_panel(draw, fonts, visual_theme, result.branch, lang)
    _draw_children_panel(draw, fonts, visual_theme, result.branch, lang, extra_height=extra_height)
    _draw_metrics_panel(draw, fonts, visual_theme, result.branch, lang)
    _draw_geography_panel(draw, fonts, visual_theme, result.branch, lang, extra_height=extra_height)
    _draw_footer(draw, fonts, visual_theme, result, lang, extra_height=extra_height)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, format="PNG", optimize=True)
    return output_path


def _branch_visual_height(branch: YFullBranch) -> int:
    child_count = sum(1 for child in branch.children if not child.name.endswith("*"))
    child_extra = max(0, child_count - _BASE_CHILD_ROWS) * _CHILD_ROW_STEP
    geography_extra = max(0, len(branch.geographies) - _BASE_GEOGRAPHY_ROWS) * _GEOGRAPHY_ROW_STEP
    return _BASE_HEIGHT + max(child_extra, geography_extra)


def _draw_background(draw: ImageDraw.ImageDraw, theme: BranchVisualTheme, image_height: int) -> None:
    for y in range(image_height):
        ratio = y / max(1, image_height - 1)
        color = tuple(
            round(theme.background_top[index] * (1.0 - ratio) + theme.background_bottom[index] * ratio)
            for index in range(3)
        )
        draw.line((0, y, _WIDTH, y), fill=(*color, 255))
    draw.ellipse((930, -180, 1390, 280), fill=(*theme.cyan, 18))
    draw.ellipse((-170, image_height - 250, 300, image_height + 220), fill=(*theme.gold, 14))
    for offset in range(0, 1280, 80):
        draw.line((offset, 0, offset - 320, image_height), fill=(*theme.border, 18), width=1)


def _draw_header(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, ImageFont.ImageFont],
    theme: BranchVisualTheme,
    result: YFullLookupResult,
) -> None:
    branch = result.branch
    draw.text((42, 20), "YFULL YTREE", fill=(*theme.cyan, 255), font=fonts["label"])
    draw.text((42, 43), _ellipsize(draw, branch.name, fonts["title"], 750), fill=(*theme.text, 255), font=fonts["title"])
    snps = "  ·  ".join(branch.snps[:4])
    snp_line = f"SNP  {snps}" if snps else "terminal branch"
    draw.text((44, 100), _ellipsize(draw, snp_line, fonts["small"], 760), fill=(*theme.muted, 255), font=fonts["small"])

    version = f"v{branch.tree_version}" if branch.tree_version else "YTREE"
    _pill(draw, fonts, theme, (1000, 30), version, theme.cyan)
    cache_label = {"live": "LIVE", "cache": "CACHE", "stale": "STALE"}.get(result.cache_status, "YTREE")
    cache_color = theme.green if result.cache_status == "live" else theme.gold
    _pill(draw, fonts, theme, (1120, 30), cache_label, cache_color)
    if branch.release_date:
        release = _ellipsize(draw, branch.release_date, fonts["tiny"], 230)
        draw.text((1198 - draw.textlength(release, font=fonts["tiny"]), 92), release, fill=(*theme.muted, 255), font=fonts["tiny"])


def _draw_age_panel(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, ImageFont.ImageFont],
    theme: BranchVisualTheme,
    branch: YFullBranch,
    lang: str,
) -> None:
    rect = (40, 132, 1240, 214)
    _panel(draw, theme, rect)
    title = _copy(lang, "Возраст ветви", "Branch age")
    draw.text((62, 141), title, fill=(*theme.text, 255), font=fonts["section"])

    values = [value for value in (branch.formed_ybp, branch.tmrca_ybp) if value is not None]
    for interval in (branch.formed_ci_ybp, branch.tmrca_ci_ybp):
        if interval is not None:
            values.extend(interval)
    if not values:
        _empty(draw, fonts, theme, (220, 145, 998, 44), _copy(lang, "Возраст не опубликован", "Age estimate unavailable"))
        return

    maximum = max(1000, int(max(values) * 1.12))
    line_left, line_right = 220, 1210
    line_y = 191
    age_unit = _copy(lang, "лет назад", "years ago")
    age_unit_bbox = draw.textbbox((0, 0), age_unit, font=fonts["tiny"])
    age_unit_width = age_unit_bbox[2] - age_unit_bbox[0]
    age_unit_y = line_y - (age_unit_bbox[3] - age_unit_bbox[1]) / 2 - age_unit_bbox[1]
    draw.text((line_left - age_unit_width - 16, age_unit_y), age_unit, fill=(*theme.muted, 255), font=fonts["tiny"])
    draw.line((line_left, line_y, line_right, line_y), fill=(*theme.border, 255), width=4)
    marker_positions = [
        _age_timeline_x(line_left, line_right, value, maximum)
        for value in (branch.formed_ybp, branch.tmrca_ybp)
        if value is not None
    ]
    for index in range(5):
        age = round(maximum * (4 - index) / 4)
        px = line_left + (line_right - line_left) * index / 4
        draw.line((px, line_y - 6, px, line_y + 7), fill=(*theme.faint, 255), width=2)
        if index not in {0, 4} and any(abs(px - marker_position) < 72 for marker_position in marker_positions):
            continue
        label = _short_age(age)
        label_w = draw.textlength(label, font=fonts["tiny"])
        draw.text((px - label_w / 2, 147), label, fill=(*theme.muted, 255), font=fonts["tiny"])

    marker_labels = []
    for label, value, color in (
        (_copy(lang, "Сформировалась", "Formed"), branch.formed_ybp, theme.gold),
        ("TMRCA", branch.tmrca_ybp, theme.cyan),
    ):
        if value is None:
            continue
        text = f"{label}  {value:,}".replace(",", " ")
        position = _age_timeline_x(line_left, line_right, value, maximum)
        marker_labels.append((position, text, color, draw.textlength(text, font=fonts["tiny"])))

    label_origins: list[float] = []
    if len(marker_labels) == 2:
        ordered = sorted(marker_labels, key=lambda item: item[0])
        total_width = ordered[0][3] + 18 + ordered[1][3]
        group_center = (ordered[0][0] + ordered[1][0]) / 2
        group_left = min(max(line_left + 24, group_center - total_width / 2), line_right - 24 - total_width)
        origins_by_text = {
            ordered[0][1]: group_left,
            ordered[1][1]: group_left + ordered[0][3] + 18,
        }
        label_origins = [origins_by_text[item[1]] for item in marker_labels]
    else:
        label_origins = [
            min(max(line_left + 24, position - width / 2), line_right - 24 - width)
            for position, _, _, width in marker_labels
        ]
    for origin, (_, text, color, _) in zip(label_origins, marker_labels):
        draw.text((origin, 147), text, fill=(*color, 255), font=fonts["tiny"])

    _age_timeline_marker(
        draw,
        line=(line_left, line_right, line_y),
        maximum=maximum,
        value=branch.formed_ybp,
        interval=branch.formed_ci_ybp,
        color=theme.gold,
    )
    _age_timeline_marker(
        draw,
        line=(line_left, line_right, line_y),
        maximum=maximum,
        value=branch.tmrca_ybp,
        interval=branch.tmrca_ci_ybp,
        color=theme.cyan,
    )


def _age_timeline_marker(
    draw: ImageDraw.ImageDraw,
    *,
    line: tuple[int, int, int],
    maximum: int,
    value: int | None,
    interval: tuple[int, int] | None,
    color: Color,
) -> None:
    if value is None:
        return
    left, right, line_y = line
    if interval is not None:
        interval_left = _age_timeline_x(left, right, interval[1], maximum)
        interval_right = _age_timeline_x(left, right, interval[0], maximum)
        draw.rounded_rectangle((interval_left, line_y - 7, interval_right, line_y + 7), radius=7, fill=(*color, 75))
    position = _age_timeline_x(left, right, value, maximum)
    draw.line((position, line_y - 16, position, line_y + 16), fill=(*color, 255), width=4)
    draw.ellipse((position - 7, line_y - 7, position + 7, line_y + 7), fill=(*color, 255))


def _age_timeline_x(left: int, right: int, value: int, maximum: int) -> float:
    return right - (right - left) * value / maximum


def _draw_children_panel(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, ImageFont.ImageFont],
    theme: BranchVisualTheme,
    branch: YFullBranch,
    lang: str,
    *,
    extra_height: int,
) -> None:
    x, y, w, h = 40, 234, 760, 574 + extra_height
    _panel(draw, theme, (x, y, x + w, y + h))
    children = [item for item in branch.children if not item.name.endswith("*")]
    draw.text((x + 22, y + 18), _copy(lang, "Дерево ветви", "Branch tree"), fill=(*theme.text, 255), font=fonts["section"])

    trunk_x = x + 45
    path = tuple(_compact_path(branch.path or (branch.name,)))
    ancestors = path[:-1]
    ancestry_y = y + 68
    draw.ellipse((trunk_x - 5, ancestry_y - 5, trunk_x + 5, ancestry_y + 5), fill=(*theme.cyan, 255))
    ancestry_text = _copy(lang, "Предки", "Ancestors")
    if ancestors:
        ancestry_text += ": " + " › ".join(ancestors)
    draw.text(
        (x + 67, y + 59),
        _ellipsize(draw, ancestry_text, fonts["tiny"], w - 100),
        fill=(*theme.muted, 255),
        font=fonts["tiny"],
    )

    root_y = y + 108
    draw.line((trunk_x, ancestry_y + 5, trunk_x, root_y - 8), fill=(*theme.border, 255), width=3)
    draw.ellipse((trunk_x - 8, root_y - 8, trunk_x + 8, root_y + 8), fill=(*theme.gold, 255))
    root_label = _ellipsize(draw, branch.name, fonts["root"], 250)
    root_bbox = draw.textbbox((0, 0), root_label, font=fonts["root"])
    root_text_y = root_y - (root_bbox[3] - root_bbox[1]) / 2 - root_bbox[1]
    draw.text(
        (x + 67, root_text_y),
        root_label,
        fill=(*theme.text, 255),
        font=fonts["root"],
    )
    if not children:
        _empty(draw, fonts, theme, (x + 67, y + 140, w - 90, 150), _copy(lang, "Дочерние ветви не показаны", "No child branches shown"))
        return

    header_y = y + 122
    draw.text((x + 347, header_y), "SNP", fill=(*theme.faint, 255), font=fonts["label"])
    draw.text((x + 562, header_y), _copy(lang, "TMRCA, ЛЕТ", "TMRCA, YBP"), fill=(*theme.faint, 255), font=fonts["label"])
    samples_header = _copy(lang, "ОБРАЗЦЫ", "SAMPLES")
    draw.text(
        (x + w - 34 - draw.textlength(samples_header, font=fonts["label"]), header_y),
        samples_header,
        fill=(*theme.faint, 255),
        font=fonts["label"],
    )
    draw.line((x + 347, y + 142, x + w - 24, y + 142), fill=(*theme.border, 120), width=1)

    row_y = y + 158
    row_count = len(children)
    row_step = 42 if row_count <= 5 else 35 if row_count <= 8 else _CHILD_ROW_STEP
    last_center_y = row_y + (row_count - 1) * row_step
    draw.line((trunk_x, root_y + 8, trunk_x, last_center_y), fill=(*theme.border, 255), width=3)

    for index, child in enumerate(children):
        center_y = row_y + index * row_step
        _child_row(
            draw,
            fonts,
            theme,
            (x + 72, center_y - 13, w - 92, 27),
            child,
            trunk_x=trunk_x,
            center_y=center_y,
            striped=index % 2 == 1,
        )


def _child_row(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, ImageFont.ImageFont],
    theme: BranchVisualTheme,
    rect: tuple[int, int, int, int],
    child: YFullChildBranch,
    *,
    trunk_x: int,
    center_y: int,
    striped: bool,
) -> None:
    x, y, w, h = rect
    if striped:
        draw.rounded_rectangle((x, y, x + w, y + h), radius=7, fill=(*theme.panel_soft, 160))
    node_x = x + 8
    draw.line((trunk_x, center_y, node_x, center_y), fill=(*theme.border, 255), width=3)
    draw.ellipse((node_x - 5, center_y - 5, node_x + 5, center_y + 5), fill=(*theme.cyan, 255))
    draw.text((x + 24, y + 3), _ellipsize(draw, child.name, fonts["small"], 235), fill=(*theme.text, 255), font=fonts["small"])
    snps = ", ".join(child.snps[:2]) or "-"
    draw.text((x + 275, y + 5), _ellipsize(draw, snps, fonts["tiny"], 175), fill=(*theme.muted, 255), font=fonts["tiny"])
    age = f"{child.tmrca_ybp:,}".replace(",", " ") if child.tmrca_ybp is not None else "-"
    draw.text((x + 490, y + 5), age, fill=(*theme.gold, 255), font=fonts["tiny"])
    samples = str(child.public_sample_count)
    draw.text((x + w - 14 - draw.textlength(samples, font=fonts["tiny"]), y + 5), samples, fill=(*theme.green, 255), font=fonts["tiny"])


def _draw_metrics_panel(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, ImageFont.ImageFont],
    theme: BranchVisualTheme,
    branch: YFullBranch,
    lang: str,
) -> None:
    x, y, w, h = 824, 234, 416, 158
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
        cy = y + 50 + (index // 2) * 52
        _metric_card(draw, fonts, theme, (cx, cy, card_w, 44), label, value, color)


def _draw_geography_panel(
    draw: ImageDraw.ImageDraw,
    fonts: dict[str, ImageFont.ImageFont],
    theme: BranchVisualTheme,
    branch: YFullBranch,
    lang: str,
    *,
    extra_height: int,
) -> None:
    x, y, w, h = 824, 414, 416, 394 + extra_height
    _panel(draw, theme, (x, y, x + w, y + h))
    draw.text((x + 22, y + 18), _copy(lang, "География", "Origins"), fill=(*theme.text, 255), font=fonts["section"])
    values = list(branch.geographies)
    if not values:
        _empty(draw, fonts, theme, (x + 22, y + 82, w - 44, 130), _copy(lang, "География не опубликована", "Geography unavailable"))
        return
    maximum = max(1, max(item.count for item in values))
    row_y = y + 68
    for index, item in enumerate(values):
        yy = row_y + index * _GEOGRAPHY_ROW_STEP
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
    *,
    extra_height: int,
) -> None:
    y = 836 + extra_height
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
    draw.rectangle((x, y + 7, x + 4, y + h - 7), fill=(*color, 255))
    draw.text((x + 16, y + 5), label.upper(), fill=(*theme.muted, 255), font=fonts["label"])
    draw.text((x + 106, y + 11), value, fill=(*color, 255), font=fonts["small"])


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
        "root": _font(20, bold=True),
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
