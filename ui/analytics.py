from __future__ import annotations

import html

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


MTDNA_HAPLOGROUP_DESCRIPTIONS: dict[str, str] = {
    "A": "Восточноевразийская материнская линия из макроветви N. Часто встречается в Северной и Восточной Азии, Сибири и у части коренных народов Америки.",
    "B": "Восточно- и юго-восточноазиатская линия из макроветви R. Ее ветви встречаются в Центральной Азии, Сибири, Восточной Азии, Океании и у части коренных народов Америки.",
    "C": "Северо- и восточноевразийская линия из макроветви M. Особенно характерна для Сибири, Центральной и Восточной Азии, а также для древних и современных популяций Америки.",
    "D": "Крупная восточноевразийская линия из макроветви M. Распространена в Восточной Азии, Сибири, Центральной Азии и у коренных народов Америки.",
    "E": "Линия юго-восточноазиатского происхождения из макроветви M. Чаще связана с островной Юго-Восточной Азией и австронезийскими миграциями.",
    "F": "Восточно- и юго-восточноазиатская линия из макроветви R9. Встречается от Китая и Индокитая до Центральной Азии и островной Юго-Восточной Азии.",
    "G": "Северо-восточноазиатская линия из макроветви M. Ее ветви часто встречаются в Сибири, на Дальнем Востоке, в Монголии, Центральной Азии и у тюрко-монгольских групп.",
    "H": "Крупнейшая западноевразийская линия, дочерняя ветвь HV. Особенно часта в Европе, на Кавказе и Ближнем Востоке; включает множество локальных ветвей H1, H2, H5, H13, H28 и др.",
    "HV": "Западноевразийская родительская линия для H и V. Встречается в Европе, на Кавказе, Ближнем Востоке и в Передней Азии; отдельные HV-ветви полезно смотреть отдельно от H/V.",
    "I": "Западноевразийская линия из ветви N1. Обычно встречается с невысокой частотой в Европе, на Кавказе, Ближнем Востоке и в степных/североевразийских выборках.",
    "J": "Западноевразийская линия из комплекса JT. Ее ветви J1 и J2 часто встречаются в Европе, на Кавказе, Ближнем Востоке и в Средиземноморье.",
    "K": "Западноевразийская ветвь внутри U8. Распространена в Европе, на Кавказе и Ближнем Востоке; часто дробится на K1 и K2 с множеством молодых подветвей.",
    "L": "Африканские базальные линии mtDNA. Если L встречается в таблице, обычно требует отдельной проверки конкретного субклада и контекста записи.",
    "M": "Одна из двух главных неафриканских макроветвей mtDNA наряду с N. Ее дочерние линии особенно разнообразны в Южной, Восточной и Центральной Азии.",
    "N": "Одна из двух главных неафриканских макроветвей mtDNA. От нее происходят многие западно- и восточноевразийские линии, включая R, X, A и I.",
    "R": "Крупная макроветвь внутри N. От нее происходят западноевразийские H, J, T, U, K, HV, V и восточноевразийские B/F/R9-подветви.",
    "R0": "Западноевразийская ветвь внутри R, родительская для HV. Встречается в Европе, Передней Азии, Аравии и на Кавказе.",
    "T": "Западноевразийская линия из комплекса JT. Ветви T1 и T2 распространены в Европе, на Кавказе, Ближнем Востоке и в древних степных выборках.",
    "U": "Древняя и очень разветвленная западноевразийская линия. Включает U1, U2, U3, U4, U5, U7, U8/K и встречается от Европы и Кавказа до Центральной и Южной Азии.",
    "V": "Западноевразийская линия, близкая к HV0. Обычно встречается в Европе, на Кавказе и в западноевразийских выборках с умеренной или низкой частотой.",
    "W": "Западноевразийская линия из N2. Встречается в Европе, на Кавказе, в Передней и Центральной Азии; отдельные ветви заметны в степных и кавказских контекстах.",
    "X": "Редкая линия из макроветви N. Ветвь X2 характерна для западноевразийских, кавказских и ближневосточных контекстов; другие ветви имеют более широкую евразийскую историю.",
    "Y": "Северо-восточноазиатская линия из N9. Чаще встречается у народов Дальнего Востока, Сибири и северо-восточной Азии.",
    "Z": "Северо- и восточноевразийская линия из M8. Встречается в Сибири, Северо-Восточной Азии, у финно-угорских и тюрко-монгольских групп с низкой частотой.",
}
MTDNA_SUBCLADE_DESCRIPTIONS: dict[str, str] = {
    "B4B1A3A": "Ветвь B4b1a3a относится к восточноевразийской линии B4b. В MTree/литературе она связана с Центральной и Восточной Азией, включая тюрко-монгольские и сибирские контексты.",
    "C4A1A": "C4a1a относится к северо-восточноевразийской линии C4a. Ветви C4 часто встречаются в Сибири, Центральной Азии и древних степных выборках; знак '-' в таблице лучше воспринимать как техническую пометку.",
    "D4G2C": "D4g2c — подветвь восточноевразийской линии D4. Такие ветви характерны для северо-восточной Азии, Сибири и центральноазиатских материнских линий.",
    "D4J5C1": "D4j5c1 — редкая подветвь D4j. По общему положению в дереве относится к восточноевразийскому пласту D4, связанному с Сибирью, Восточной и Центральной Азией.",
    "G2A1A": "G2a1a относится к северо-восточноазиатской линии G2a. Встречается в сибирских, дальневосточных и центральноазиатских контекстах.",
    "G2A5B1": "G2a5b1 — подветвь G2a, северо-восточноевразийской линии из макроветви M. Для навигатора это маркер восточно-сибирского/центральноазиатского пласта.",
    "H101A4": "H101a4 — редкая подветвь западноевразийской H. Такие глубокие H-ветви обычно требуют привязки к конкретным совпадениям и дереву YFull/MTree.",
    "H123A": "H123a — редкая ветвь H. Относится к западноевразийскому пласту H, но точная интерпретация зависит от полного митогенома и соседних образцов.",
    "H133A": "H133a — редкая подветвь H. Ее лучше трактовать как узкую западноевразийскую линию внутри большого разнообразия H.",
    "H1E8A": "H1e8a — ветвь внутри H1, одной из крупных европейско-западноевразийских линий H. Полезна для сравнения с H1-ветвями Европы, Кавказа и Передней Азии.",
    "H2A1C2": "H2a1c2 — подветвь H2a. H2 широко представлена в западноевразийских и древних евразийских выборках, включая Европу, Кавказ и степные контексты.",
    "H3H2": "H3h2 — ветвь H3. H3 часто связывают с западноевропейским и средиземноморским разнообразием, но отдельные подветви встречаются шире.",
    "H5AC": "H5ac — подветвь H5. H5 распространена в Европе, на Кавказе и в Передней Азии и часто заметна в древних западноевразийских выборках.",
    "H5B12": "H5b12 — ветвь H5b. Это западноевразийская линия внутри H5, для которой важны ближайшие полногеномные совпадения.",
    "H28D": "H28d — подветвь H28. H28 встречается в западноевразийском пространстве; конкретная ветвь может быть локальной и лучше читается по YFull/MTree.",
    "H79B": "H79b — редкая ветвь H. В навигаторе ее стоит понимать как узкий западноевразийский субклад с ограниченным числом опубликованных совпадений.",
    "HV12A2A": "HV12a2a — подветвь HV12 внутри родительской линии HV. Это западноевразийский пласт до разделения на привычные H/V-ветви.",
    "HV1A1A": "HV1a1a — подветвь HV1. Встречается в западноевразийских, кавказских и ближневосточных контекстах и может быть информативнее общей метки HV.",
    "I1A1A8": "I1a1a8 — подветвь I1a. Линия I редкая, но устойчивая в западноевразийских, североевропейских, кавказских и ближневосточных выборках.",
    "I6A1": "I6a1 — подветвь I6. Это редкая западноевразийская линия, для которой особенно важны ближайшие полногеномные совпадения.",
    "J1D3A1": "J1d3a1 — подветвь J1. Ветви J1 распространены в Европе, на Кавказе, Ближнем Востоке и в Средиземноморье.",
    "J2B1L": "J2b1l — подветвь J2b. J2b относится к западноевразийскому комплексу JT и встречается в Европе, на Кавказе и в Передней Азии.",
    "K1A3C": "K1a3c — подветвь K1a. K1a широко представлена в западноевразийских выборках; конкретные молодые ветви могут иметь локальные кавказские, европейские или ближневосточные связи.",
    "K1A4I": "K1a4i — подветвь K1a4. Это западноевразийская линия внутри K1, обычно требующая сравнения по полным митогеномам.",
    "K1B1C": "K1b1c — подветвь K1b. Линия K1b встречается в западноевразийских популяциях, включая Европу, Кавказ и Переднюю Азию.",
    "M1A1B1B": "M1a1b1b — подветвь M1a. M1 — западноевразийско-североафриканская ветвь макролинии M, часто обсуждаемая отдельно от восточноазиатских M-ветвей.",
    "N1B1A5": "N1b1a5 — подветвь N1b. N1b встречается на Ближнем Востоке, Кавказе, в Европе и древних западноевразийских выборках.",
    "R1A1C": "R1a1c — подветвь mtDNA R1a, не путать с Y-ДНК R1a. Это материнская линия внутри макроветви R, встречающаяся в западно- и южноевразийских контекстах.",
    "R1A2": "R1a2 — подветвь mtDNA R1a. Для интерпретации важны именно mtDNA-совпадения, так как название совпадает с известной Y-ДНК ветвью только формально.",
    "R1A3": "R1a3 — подветвь mtDNA R1a внутри макроветви R. Встречается сравнительно редко и лучше уточняется по MTree/YFull.",
    "T1A1AM": "T1a1am — молодая подветвь T1a1a. T1 часто встречается в западноевразийских, кавказских, ближневосточных и степных контекстах.",
    "T1B3B": "T1b3b — подветвь T1b. T1b относится к западноевразийской линии T1 и может встречаться в Европе, на Кавказе и в Передней Азии.",
    "T2B": "T2b — крупная ветвь T2. Широко известна в Европе и западноевразийских выборках, с множеством дочерних линий.",
    "T2D2A": "T2d2a — подветвь T2d. T2d встречается в западноевразийских и переднеазиатских контекстах, обычно с невысокой частотой.",
    "T2G1A2": "T2g1a2 — подветвь T2g. T2g представлена в Европе, на Кавказе и в Передней Азии; конкретные ветви часто локальны.",
    "T2L2": "T2l2 — подветвь T2l. Относится к западноевразийскому комплексу T2 и требует уточнения по ближайшим полным митогеномам.",
    "U1A1A12A": "U1a1a12a — подветвь U1a. U1 часто встречается в Кавказско-Переднеазиатском, ближневосточном и южно-центральноазиатском контекстах.",
    "U1A1A3A": "U1a1a3a — подветвь U1a. Ветви U1a хорошо подходят для сравнения кавказских, переднеазиатских и степных материнских линий.",
    "U1B2D": "U1b2d — ветвь U1b2. По MTree она имеет заметные совпадения в кавказском, турецком, армянском, казахстанском и северокавказском контекстах.",
    "U2D2A": "U2d2a — подветвь U2d. U2d встречается в Кавказско-Переднеазиатском и южно-центральноазиатском пространстве и в древних евразийских выборках.",
    "U2E1H1A5": "U2e1h1a5 — подветвь U2e1. U2e часто заметна в Европе, степных и североевразийских древних выборках; молодые ветви уточняются по полным митогеномам.",
    "U2E1J": "U2e1j — подветвь U2e1. Это западно- и североевразийская линия, интересная для сравнения со степными и европейскими выборками.",
    "U2E2A1": "U2e2a1 — подветвь U2e2. Относится к западноевразийскому пласту U2e, часто встречающемуся в древних европейских и степных контекстах.",
    "U3A3B": "U3a3b — подветвь U3a. U3 характерна для Кавказа, Передней Азии, Ближнего Востока и Европы; отдельные ветви могут быть локальными.",
    "U3B2H": "U3b2h — подветвь U3b2. Это западноевразийская линия, особенно интересная для Кавказа, Передней Азии и соседних регионов.",
    "U3B3C1": "U3b3c1 — подветвь U3b3. U3b часто встречается в кавказско-переднеазиатском и европейском пространстве; эта ветвь может быть локально информативной.",
    "U4A9A": "U4a9a — подветвь U4a. U4 — древняя северо- и восточноевропейская/степная линия, встречающаяся также на Кавказе и в Сибири.",
    "U5A1B1U": "U5a1b1u — подветвь U5a1b. U5 — одна из древнейших европейских линий; U5a хорошо представлена в древних североевразийских и европейских выборках.",
    "U5A1F1A2": "U5a1f1a2 — подветвь U5a1f. Относится к древнему европейско-североевразийскому пласту U5a, где важны ближайшие полные совпадения.",
    "U7": "U7 — западно- и южноазиатская линия внутри U. Часто встречается в Иране, Южной Азии, на Кавказе и в Передней Азии; '-' в таблице выглядит как техническая пометка.",
    "V2K": "V2k — подветвь V2. V2 относится к западноевразийской линии V и встречается в Европе, на Кавказе и соседних регионах.",
    "W6": "W6 — ветвь W. W6 встречается в западноевразийских, кавказских, переднеазиатских и центральноазиатских контекстах.",
    "X2D1B": "X2d1b — подветвь X2d. X2 — редкая западноевразийская линия; X2d полезна для сравнения кавказских, ближневосточных и европейских совпадений.",
    "X2E2A2": "X2e2a2 — подветвь X2e. X2e встречается в западноевразийском пространстве, обычно редко, и лучше читается по полным митогеномам.",
    "X2F2": "X2f2 — подветвь X2f. Относится к редкому западноевразийскому пласту X2 и требует проверки ближайших совпадений в MTree/YFull.",
}


def mtdna_haplogroup_description(group: str) -> str:
    return MTDNA_HAPLOGROUP_DESCRIPTIONS.get(group.upper().strip(), "")


def mtdna_subclade_description(subclade: str) -> str:
    normalized = "".join(char for char in str(subclade or "").upper() if char.isalnum())
    if normalized in MTDNA_SUBCLADE_DESCRIPTIONS:
        return MTDNA_SUBCLADE_DESCRIPTIONS[normalized]
    for key in sorted(MTDNA_SUBCLADE_DESCRIPTIONS, key=len, reverse=True):
        if normalized.startswith(key):
            return MTDNA_SUBCLADE_DESCRIPTIONS[key]
    return ""


def build_haplo_group_mode_keyboard(haplo_prefix: str, selected_mode: str | None = None) -> InlineKeyboardMarkup:
    labels = {
        "families": "📊 По родам",
        "tests": "📊 По тестам",
    }
    rows = []
    row = []
    for mode in ("families", "tests"):
        if selected_mode and mode == selected_mode:
            continue
        row.append(InlineKeyboardButton(labels[mode], callback_data=f"{haplo_prefix}:{mode}"))
    if row:
        rows.append(row)
    rows.append([
        InlineKeyboardButton("⬅️ Y-ДНК", callback_data=f"{haplo_prefix}:ydna"),
        InlineKeyboardButton("Отмена", callback_data=f"{haplo_prefix}:cancel"),
    ])
    return InlineKeyboardMarkup(rows)


def build_haplo_navigator_names_keyboard(haplo_prefix: str, group_index: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("Назад", callback_data=f"{haplo_prefix}:navg:{group_index}"),
        InlineKeyboardButton("Отмена", callback_data=f"{haplo_prefix}:cancel"),
    ]])


def build_haplo_subclade_mode_keyboard(haplo_prefix: str, group_index: int, selected_mode: str | None = None) -> InlineKeyboardMarkup:
    labels = {
        "families": "📊 По родам",
        "tests": "📊 По тестам",
    }
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for mode, prefix in (("families", "subf"), ("tests", "subt")):
        if selected_mode and mode == selected_mode:
            continue
        row.append(InlineKeyboardButton(labels[mode], callback_data=f"{haplo_prefix}:{prefix}:{group_index}"))
    if row:
        rows.append(row)
    rows.append([
        InlineKeyboardButton("⬅️ Субклады", callback_data=f"{haplo_prefix}:subclades"),
        InlineKeyboardButton("Отмена", callback_data=f"{haplo_prefix}:cancel"),
    ])
    return InlineKeyboardMarkup(rows)


def build_haplo_root_keyboard(haplo_prefix: str, menu_prefix: str, *, include_back: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("🧬 Y-ДНК", callback_data=f"{haplo_prefix}:ydna")],
        [InlineKeyboardButton("🧬 mtDNA", callback_data=f"{haplo_prefix}:mtdna")],
    ]
    footer_row: list[InlineKeyboardButton] = []
    if include_back:
        footer_row.append(InlineKeyboardButton("Назад", callback_data=f"{menu_prefix}:root"))
    footer_row.append(InlineKeyboardButton("Отмена", callback_data=f"{haplo_prefix}:cancel"))
    rows.append(footer_row)
    return InlineKeyboardMarkup(rows)


def build_stats_view_keyboard(haplo_prefix: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("Назад", callback_data=f"{haplo_prefix}:statsroot"),
        InlineKeyboardButton("Отмена", callback_data=f"{haplo_prefix}:cancel"),
    ]])


def untested_surname_count(group: dict[str, object]) -> int:
    return len(group.get("names") or []) + len(group.get("confirm_names") or [])


def build_untested_surname_groups_keyboard(haplo_prefix: str, groups: list[dict[str, object]]) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                f"{group['label']} · {untested_surname_count(group)}",
                callback_data=f"{haplo_prefix}:untested:{index}",
            )
        ]
        for index, group in enumerate(groups)
    ]
    rows.append([
        InlineKeyboardButton("Назад", callback_data=f"{haplo_prefix}:ydna"),
        InlineKeyboardButton("Отмена", callback_data=f"{haplo_prefix}:cancel"),
    ])
    return InlineKeyboardMarkup(rows)


def build_untested_surname_view_keyboard(haplo_prefix: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("Назад", callback_data=f"{haplo_prefix}:untested"),
        InlineKeyboardButton("Отмена", callback_data=f"{haplo_prefix}:cancel"),
    ]])


def format_untested_surname_group(group: dict[str, object]) -> str:
    names = [str(name) for name in (group.get("names") or [])]
    confirm_names = [str(name) for name in (group.get("confirm_names") or [])]
    lines = [
        "<b>Y-ДНК · Непротестированные роды</b>",
        "",
        f"<b>{html.escape(str(group.get('label') or ''))}</b>",
    ]
    subtitle = str(group.get("subtitle") or "")
    if subtitle:
        lines.append(html.escape(subtitle))
    lines.extend(["", f"Всего: {untested_surname_count(group)}"])
    if names:
        lines.extend(["", html.escape(", ".join(names))])
    if confirm_names:
        lines.extend([
            "",
            "<b>Требуют подтверждения:</b>",
            html.escape(", ".join(confirm_names)),
        ])
    return "\n".join(lines)


def build_haplo_mode_keyboard(haplo_prefix: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Гаплогруппы по родам", callback_data=f"{haplo_prefix}:families")],
        [InlineKeyboardButton("📊 Гаплогруппы по тестам", callback_data=f"{haplo_prefix}:tests")],
        [InlineKeyboardButton("🧬 Субклады", callback_data=f"{haplo_prefix}:subclades")],
        [InlineKeyboardButton("🧭 Навигатор", callback_data=f"{haplo_prefix}:navigator")],
        [InlineKeyboardButton("🧮 STR-маркеры", callback_data=f"{haplo_prefix}:ystr")],
        [InlineKeyboardButton("📌 Непротестированные", callback_data=f"{haplo_prefix}:untested")],
        [
            InlineKeyboardButton("⬅️ Назад", callback_data=f"{haplo_prefix}:root"),
            InlineKeyboardButton("Отмена", callback_data=f"{haplo_prefix}:cancel"),
        ],
    ])


def build_ydna_diagram_keyboard(haplo_prefix: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Гаплогруппы по родам", callback_data=f"{haplo_prefix}:families")],
        [InlineKeyboardButton("📊 Гаплогруппы по тестам", callback_data=f"{haplo_prefix}:tests")],
        [InlineKeyboardButton("🧬 Субклады", callback_data=f"{haplo_prefix}:subclades")],
        [
            InlineKeyboardButton("⬅️ Y-ДНК", callback_data=f"{haplo_prefix}:ydna"),
            InlineKeyboardButton("Отмена", callback_data=f"{haplo_prefix}:cancel"),
        ],
    ])


def build_mtdna_root_keyboard(haplo_prefix: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Гаплогруппы", callback_data=f"{haplo_prefix}:mtdna_groups")],
        [InlineKeyboardButton("📊 Субклады", callback_data=f"{haplo_prefix}:mtdna_subclades")],
        [InlineKeyboardButton("🧭 Навигатор", callback_data=f"{haplo_prefix}:mtdna_navigator")],
        [
            InlineKeyboardButton("⬅️ Назад", callback_data=f"{haplo_prefix}:root"),
            InlineKeyboardButton("Отмена", callback_data=f"{haplo_prefix}:cancel"),
        ],
    ])


def build_mtdna_mode_keyboard(haplo_prefix: str, selected_kind: str | None = None) -> InlineKeyboardMarkup:
    labels = {
        "groups": "📊 Гаплогруппы",
        "subclades": "📊 Субклады",
    }
    rows: list[list[InlineKeyboardButton]] = []
    for kind, label in labels.items():
        if selected_kind and kind == selected_kind:
            continue
        rows.append([InlineKeyboardButton(label, callback_data=f"{haplo_prefix}:mtdna_{kind}")])
    rows.append([
        InlineKeyboardButton("⬅️ mtDNA", callback_data=f"{haplo_prefix}:mtdna"),
        InlineKeyboardButton("Отмена", callback_data=f"{haplo_prefix}:cancel"),
    ])
    return InlineKeyboardMarkup(rows)


def build_mtdna_navigator_groups_keyboard(haplo_prefix: str, groups: list[dict[str, object]]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for index, item in enumerate(groups):
        row.append(InlineKeyboardButton(f"{item['label']} · {item['count']}", callback_data=f"{haplo_prefix}:mtnavg:{index}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([
        InlineKeyboardButton("Назад", callback_data=f"{haplo_prefix}:mtdna"),
        InlineKeyboardButton("Отмена", callback_data=f"{haplo_prefix}:cancel"),
    ])
    return InlineKeyboardMarkup(rows)


def build_mtdna_navigator_subclades_keyboard(haplo_prefix: str, subclades: list[dict[str, object]]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for index, item in enumerate(subclades):
        row.append(InlineKeyboardButton(f"{item['label']} · {item['count']}", callback_data=f"{haplo_prefix}:mtnavs:{index}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([
        InlineKeyboardButton("Назад", callback_data=f"{haplo_prefix}:mtdna_navigator"),
        InlineKeyboardButton("Отмена", callback_data=f"{haplo_prefix}:cancel"),
    ])
    return InlineKeyboardMarkup(rows)


def build_mtdna_navigator_entries_keyboard(haplo_prefix: str, group_index: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("Назад", callback_data=f"{haplo_prefix}:mtnavg:{group_index}"),
        InlineKeyboardButton("Отмена", callback_data=f"{haplo_prefix}:cancel"),
    ]])


def build_haplo_subclade_groups_keyboard(haplo_prefix: str, groups: list[str]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for index, group in enumerate(groups):
        row.append(InlineKeyboardButton(group, callback_data=f"{haplo_prefix}:subg:{index}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([
        InlineKeyboardButton("⬅️ Y-ДНК", callback_data=f"{haplo_prefix}:ydna"),
        InlineKeyboardButton("Отмена", callback_data=f"{haplo_prefix}:cancel"),
    ])
    return InlineKeyboardMarkup(rows)


def build_haplo_navigator_groups_keyboard(haplo_prefix: str, groups: list[dict[str, object]]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for index, item in enumerate(groups):
        row.append(InlineKeyboardButton(f"{item['label']} · {item['count']}", callback_data=f"{haplo_prefix}:navg:{index}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([
        InlineKeyboardButton("Назад", callback_data=f"{haplo_prefix}:ydna"),
        InlineKeyboardButton("Отмена", callback_data=f"{haplo_prefix}:cancel"),
    ])
    return InlineKeyboardMarkup(rows)


def build_haplo_navigator_subclades_keyboard(haplo_prefix: str, subclades: list[dict[str, object]]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(f"{item['label']} · {item['count']}", callback_data=f"{haplo_prefix}:navs:{index}")]
        for index, item in enumerate(subclades)
    ]
    rows.append([
        InlineKeyboardButton("Назад", callback_data=f"{haplo_prefix}:navigator"),
        InlineKeyboardButton("Отмена", callback_data=f"{haplo_prefix}:cancel"),
    ])
    return InlineKeyboardMarkup(rows)


def format_subclade_surnames_text(group: str, subclade: str, names: list[str]) -> str:
    header = f"<b>{html.escape(group)} -> {html.escape(subclade)}</b>"
    if not names:
        return f"{header}\n\nФамилии пока не найдены."

    visible = names[:80]
    lines = [f"{index}. {html.escape(name)}" for index, name in enumerate(visible, start=1)]
    if len(names) > len(visible):
        lines.append(f"... и еще {len(names) - len(visible)}")
    return f"{header}\n\n" + "\n".join(lines)


def format_mtdna_entries_text(group: str, subclade: str, entries: list[dict[str, object]]) -> str:
    description = mtdna_subclade_description(subclade) or mtdna_haplogroup_description(group)
    header = f"<b>МтДНК: {html.escape(group)} -> {html.escape(subclade)}</b>"
    blocks = [header]
    if description:
        blocks.append(html.escape(description))
    if not entries:
        blocks.append("Записи пока не найдены.")
        return "\n\n".join(blocks)

    named_entries = [
        entry
        for entry in entries
        if " ".join(str(entry.get("name") or "").split())
    ]
    unnamed_entries = [
        entry
        for entry in entries
        if not " ".join(str(entry.get("name") or "").split())
    ]
    unnamed_with_links = [
        entry
        for entry in unnamed_entries
        if entry.get("links")
    ]
    unnamed_without_links_count = len(unnamed_entries) - len(unnamed_with_links)
    visible = (named_entries + unnamed_with_links)[:80]
    seen_link_urls: set[str] = set()
    rendered_links: list[str] = []
    for entry in entries:
        for link in entry.get("links") or []:
            if not isinstance(link, dict):
                continue
            url = str(link.get("url") or "")
            if not url or url in seen_link_urls:
                continue
            seen_link_urls.add(url)
            label = str(link.get("label") or "Ссылка")
            rendered_links.append(f'<a href="{html.escape(url, quote=True)}">{html.escape(label)}</a>')

    lines: list[str] = []
    for index, entry in enumerate(visible, start=1):
        name = " ".join(str(entry.get("name") or "").split()) or "образец"
        lines.append(f"{index}. {html.escape(name)}")
    hidden_named_or_linked = len(named_entries) + len(unnamed_with_links) - len(visible)
    if hidden_named_or_linked > 0:
        lines.append(f"... и еще {hidden_named_or_linked}")
    if unnamed_without_links_count > 0:
        suffix = "образец без подписи" if unnamed_without_links_count == 1 else "образцов без подписи"
        lines.append(f"Еще {unnamed_without_links_count} {suffix} в таблице.")
    blocks.append("\n".join(lines))
    if rendered_links:
        blocks.append("Ссылки: " + " · ".join(rendered_links[:6]))
    return "\n\n".join(blocks)
