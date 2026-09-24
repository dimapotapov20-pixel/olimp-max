#!/usr/bin/env python3
"""Strict, university-specific readers for official admission benefit tables.

The keyword crawler is useful for discovering documents, but it deliberately
does not publish anything.  This module is the narrower path used for a small
set of checked university formats.  It accepts a row only when the document
states all of the following in table cells: programme (or programme code),
olympiad, profile, diploma status and benefit.  The caller still resolves the
two foreign keys against PostgreSQL; a non-exact match is never published.

There is no fuzzy title matching here.  That is intentional: a changed table
layout should produce zero automatic rules and leave source data auditable,
not silently make a wrong admission promise.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Literal


BenefitKind = Literal["bvi", "hundred_points"]
DiplomaStatus = Literal["winner", "prize_winner"]


def compact(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\u00ad", "").replace("\xa0", " ")).strip()


def normalise(value: str) -> str:
    value = compact(value).casefold().replace("ё", "е")
    value = re.sub(r"[«»\"'`]+", "", value)
    return re.sub(r"\s+", " ", value).strip()


def table_cells(row: str) -> list[str]:
    return [compact(cell) for cell in row.strip().strip("|").split("|")]


def is_separator(row: str) -> bool:
    return bool(row.strip()) and all(
        re.fullmatch(r"\s*:?-{3,}:?\s*", cell or "---") is not None
        for cell in table_cells(row)
    )


def markdown_tables(markdown: str) -> Iterable[tuple[int, list[str], list[tuple[int, list[str]]]]]:
    """Yield a semantic header and its aligned rows from Markdown tables.

    PDF extraction sometimes prepends a title row above the real header.  The
    header is consequently selected by its known column vocabulary, rather
    than assumed to be the first row.
    """
    lines = markdown.splitlines()
    offset = 0
    while offset < len(lines):
        if not lines[offset].lstrip().startswith("|"):
            offset += 1
            continue
        start = offset
        while offset < len(lines) and lines[offset].lstrip().startswith("|"):
            offset += 1
        raw_rows = [(index + 1, table_cells(lines[index])) for index in range(start, offset)]
        non_separators = [(line, cells) for line, cells in raw_rows if not is_separator("|" + "|".join(cells) + "|")]
        if len(non_separators) < 2:
            continue
        scored = [
            (
                sum(
                    term in normalise(cell)
                    for cell in cells
                    for term in (
                        "олимпиад", "профиль", "программа", "направлен", "бви",
                        "100 бал", "льгот", "победител", "призер",
                    )
                ),
                index,
            )
            for index, (_, cells) in enumerate(non_separators)
        ]
        # `max((score, index))` would pick a later data row on a tie. The
        # first equally descriptive row is the actual table header.
        best_score = max(score for score, _ in scored)
        header_index = next(index for score, index in scored if score == best_score)
        header_line, headers = non_separators[header_index]
        data_rows = non_separators[header_index + 1 :]
        if data_rows:
            yield header_line, headers, data_rows


@dataclass(frozen=True)
class StrictAdapter:
    code: str
    programme_headers: tuple[str, ...]
    olympiad_headers: tuple[str, ...]
    profile_headers: tuple[str, ...]
    diploma_headers: tuple[str, ...] = ("диплом", "статус")
    generic_benefit_headers: tuple[str, ...] = ("льгота", "предоставляемая льгота", "особое право")
    subject_headers: tuple[str, ...] = ("общеобразовательный предмет", "предмет подтверждения")
    score_headers: tuple[str, ...] = ("егэ", "подтверждение")
    benefit_cells_are_programmes: bool = False
    default_diploma_statuses: tuple[DiplomaStatus, ...] = ()
    required_scope_terms: tuple[str, ...] = ()
    inherit_programme: bool = False
    inherit_olympiad: bool = False
    programme_group_in_first_cell: bool = False
    reader: str = "grid"


COMMON = dict(
    programme_headers=("наименование образовательной", "образовательной программ", "образовательная программа", "программ", "направлен", "специальност"),
    olympiad_headers=("полное наименование олимпиады", "наименование олимпиады", "название олимпиады", "олимпиада"),
    profile_headers=("профиль олимпиады", "профиль"),
)


# Each code is intentionally distinct even where the table vocabulary is
# shared. A source can be tightened independently after a university changes
# its site without loosening the others.
ADAPTERS: dict[str, StrictAdapter] = {
    "strict-hse-2026-v1": StrictAdapter(
        code="strict-hse-2026-v1",
        **COMMON,
        diploma_headers=("диплом", "статус", "кому предоставляется", "победителям либо"),
        generic_benefit_headers=("предоставляемая льгота", "льгот", "вид особого"),
        subject_headers=("предмет подтверждения", "один или несколько предметов", "предмет зачета 100"),
        score_headers=("количество баллов егэ", "количество баллов"),
        inherit_programme=True,
        inherit_olympiad=True,
        programme_group_in_first_cell=True,
    ),
    # MIPT grants BVI by a physical-school competition group, not an admission
    # programme. The reader validates that format but deliberately emits no
    # programme-level rule until an official group-to-programme source is
    # configured.
    "strict-mipt-2026-v2": StrictAdapter(
        code="strict-mipt-2026-v2", reader="mipt_competition_groups", **COMMON
    ),
    # MSU's PDF has a stable, programme-first table. It needs its own reader:
    # programme and olympiad cells may be inherited across continuation rows,
    # and a cell may enumerate several explicitly named RSOSh olympiads.
    "strict-msu-2026-v2": StrictAdapter(
        code="strict-msu-2026-v2", reader="msu_programme_table", **COMMON
    ),
    # Bauman publishes different official appendices for BVI and 100 points.
    # Keeping them separate avoids treating a subject/field scope as a named
    # educational programme.
    "strict-bmstu-bvi-2026-v1": StrictAdapter(
        code="strict-bmstu-bvi-2026-v1", reader="bmstu_bvi_appendix", **COMMON
    ),
    "strict-bmstu-100-2026-v1": StrictAdapter(
        code="strict-bmstu-100-2026-v1", reader="bmstu_hundred_appendix", **COMMON
    ),
    # The official МИФИ table uses programme codes in the BVI/100 columns and
    # explicitly covers both winners and prize winners in its scope heading.
    "strict-mephi-2026-v1": StrictAdapter(
        code="strict-mephi-2026-v1",
        **COMMON,
        benefit_cells_are_programmes=True,
        default_diploma_statuses=("winner", "prize_winner"),
        required_scope_terms=("победител", "призер"),
    ),
}


def supported_codes() -> tuple[str, ...]:
    return tuple(ADAPTERS)


def header_indexes(headers: list[str], aliases: tuple[str, ...]) -> list[int]:
    normalised = [normalise(header) for header in headers]
    return [
        index
        for index, header in enumerate(normalised)
        if any(alias in header for alias in aliases)
    ]


def cell_at(cells: list[str], index: int | None) -> str:
    return cells[index] if index is not None and index < len(cells) else ""


def explicit_statuses(value: str) -> tuple[DiplomaStatus, ...]:
    value = normalise(value)
    winner = "победител" in value
    prize_winner = "призер" in value
    if winner and prize_winner:
        return ("winner", "prize_winner")
    if winner:
        return ("winner",)
    if prize_winner:
        return ("prize_winner",)
    return ()


def subject_code(value: str) -> str | None:
    value = normalise(value)
    aliases = {
        "информатика": "informatics", "программирование": "informatics",
        "математика": "math", "физика": "physics", "химия": "chemistry",
        "биология": "biology", "астрономия": "astronomy", "экономика": "economics",
        "история": "history", "география": "geography", "обществознание": "social-studies",
        "право": "law", "литература": "literature", "русский язык": "russian",
        "английский язык": "english", "немецкий язык": "german",
        "французский язык": "french", "китайский язык": "chinese",
    }
    return aliases.get(value)


def confirmation_score(value: str) -> int | None:
    match = re.search(r"\b(\d{2,3})\b", normalise(value))
    if not match:
        return None
    score = int(match.group(1))
    return score if 0 <= score <= 100 else None


def programme_selectors(value: str) -> tuple[str, ...]:
    """Read explicit programme codes or one exact programme name.

    Phrases such as «все направления» are intentionally rejected: expanding
    such a phrase depends on a separate official programme catalogue and must
    never happen by accident in an admission parser.
    """
    value = compact(value)
    codes = tuple(dict.fromkeys(re.findall(r"(?<!\d)\d{2}\.\d{2}\.\d{2}(?!\d)", value)))
    if codes:
        return codes
    lowered = normalise(value)
    prohibited = ("все направлен", "все программ", "любое направлен", "см. ", "согласно")
    if not value or any(fragment in lowered for fragment in prohibited):
        return ()
    return (value,)


def benefit_from_cell(header: str, value: str, *, generic: bool = False) -> BenefitKind | None:
    header, value = normalise(header), normalise(value)
    if not value or value in {"-", "—", "нет", "не предоставляется"}:
        return None
    if "100 бал" in header or (generic and ("100 бал" in value or "максимальное количество баллов" in value)):
        return "hundred_points"
    if "бви" in header or "без вступительных" in header or (generic and ("бви" in value or "без вступительных" in value)):
        return "bvi"
    return None


@dataclass(frozen=True)
class StrictRule:
    programme_selector: str
    olympiad_title: str
    profile_title: str
    diploma_status: DiplomaStatus
    benefit_kind: BenefitKind
    confirmation_subject_code: str | None
    confirmation_min_score: int | None
    source_locator: str
    source_excerpt: str
    raw_payload: dict[str, object]


def first_header_index(headers: list[str], *fragments: str) -> int | None:
    """Return the first header containing every requested normalized fragment."""
    wanted = tuple(normalise(fragment) for fragment in fragments)
    return next(
        (index for index, header in enumerate(headers) if all(fragment in normalise(header) for fragment in wanted)),
        None,
    )


def provided(value: str) -> bool:
    """Bauman's appendices use this exact value for a granted benefit."""
    return normalise(value) == "предоставляется"


def split_msu_olympiads(value: str) -> tuple[str, ...]:
    """Split only an explicit MSU list of named olympiads.

    ``*`` means every olympiad of a listed level. It is intentionally not
    expanded: that would require joining an external catalogue and could
    silently broaden an admission right. Commas inside a name stay untouched;
    we split a comma only when the next fragment starts a new title.
    """
    value = compact(value)
    if not value or value == "*":
        return ()
    starts = (
        "всероссийская", "московская", "олимпиада", "санкт-петербургская",
        "турнир", "вузовско", "городская", "инженерная", "интернет-",
        "международная", "межрегиональная", "многопрофильная", "объединенная",
        "открытая", "общероссийская", "отраслевая", "плехановская", "пироговская",
        "телевизионная", "университетская", "всесибирская", "герценовская",
        "океан", "северо-восточная",
    )
    pattern = r"\s*(?:;|,\s+(?=(?:" + "|".join(starts) + r")\b))\s*"
    titles = tuple(compact(part) for part in re.split(pattern, value, flags=re.IGNORECASE) if compact(part))
    if not titles or any("олимпиад" not in normalise(title) and normalise(title) != "турнир городов" for title in titles):
        return ()
    return tuple(dict.fromkeys(titles))


def append_rule(
    output: list[StrictRule],
    seen: set[tuple[str, str, str, str, str]],
    *,
    programme_selector: str,
    olympiad_title: str,
    profile_title: str,
    diploma_status: DiplomaStatus,
    benefit_kind: BenefitKind,
    confirmation_subject_code: str | None,
    confirmation_min_score: int | None,
    source_locator: str,
    source_excerpt: str,
    raw_payload: dict[str, object],
) -> None:
    key = (programme_selector, olympiad_title, profile_title, diploma_status, benefit_kind)
    if key in seen:
        return
    seen.add(key)
    output.append(
        StrictRule(
            programme_selector=programme_selector,
            olympiad_title=olympiad_title,
            profile_title=profile_title,
            diploma_status=diploma_status,
            benefit_kind=benefit_kind,
            confirmation_subject_code=confirmation_subject_code,
            confirmation_min_score=confirmation_min_score,
            source_locator=source_locator,
            source_excerpt=source_excerpt,
            raw_payload=raw_payload,
        )
    )


def msu_rules(markdown: str) -> list[StrictRule]:
    """Read MSU's 2026 programme-first special-rights PDF.

    A row is emitted only for a named programme, a named profile, a concrete
    olympiad (not ``*``), stated diploma status and BVI/100-points benefit.
    """
    document = normalise(markdown)
    if not all(term in document for term in ("мгу", "особые права", "2026")):
        return []

    output: list[StrictRule] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    for header_line, headers, rows in markdown_tables(markdown):
        programme_index = first_header_index(headers, "направление подготовки")
        profile_index = first_header_index(headers, "профиль олимпиады")
        olympiad_index = first_header_index(headers, "перечень олимпиад")
        diploma_index = first_header_index(headers, "победитель", "призер")
        subject_index = first_header_index(headers, "общеобразовательный предмет", "егэ")
        benefit_index = first_header_index(headers, "льгота")
        if None in (programme_index, profile_index, olympiad_index, diploma_index, benefit_index):
            continue

        programme = profile = olympiads = subject = ""
        for line_number, cells in rows:
            programme_cell = cell_at(cells, programme_index)
            profile_cell = cell_at(cells, profile_index)
            olympiad_cell = cell_at(cells, olympiad_index)
            subject_cell = cell_at(cells, subject_index)
            if programme_cell:
                programme = programme_cell
            if profile_cell:
                profile = profile_cell
            if olympiad_cell:
                olympiads = olympiad_cell
            if subject_cell:
                subject = subject_cell
            statuses = explicit_statuses(cell_at(cells, diploma_index))
            benefit = benefit_from_cell(headers[benefit_index], cell_at(cells, benefit_index), generic=True)
            selectors = programme_selectors(programme)
            titles = split_msu_olympiads(olympiads)
            if not selectors or not profile or not statuses or benefit is None or not titles:
                continue
            excerpt = compact(" | ".join(cells))[:4_000]
            payload: dict[str, object] = {
                "kind": "msu_programme_table_row",
                "adapter": "strict-msu-2026-v2",
                "header_line": header_line,
                "headers": headers,
                "row": cells,
                "olympiad_titles": titles,
            }
            score = 75 if subject else None
            for selector in selectors:
                for title in titles:
                    for status in statuses:
                        append_rule(
                            output,
                            seen,
                            programme_selector=selector,
                            olympiad_title=title,
                            profile_title=profile,
                            diploma_status=status,
                            benefit_kind=benefit,
                            confirmation_subject_code=subject_code(subject),
                            confirmation_min_score=score,
                            source_locator=f"markdown:line:{line_number}",
                            source_excerpt=excerpt,
                            raw_payload=payload,
                        )
    return output


def bmstu_bvi_rules(markdown: str) -> list[StrictRule]:
    """Read Bauman appendix 5.1, whose explicit scope is direction codes."""
    document = normalise(markdown)
    if not all(term in document for term in ("приложение 5.1", "право поступления без вступительных")):
        return []

    output: list[StrictRule] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    directions: tuple[str, ...] = ()
    olympiad = ""
    for line_number, line in enumerate(markdown.splitlines(), start=1):
        if not line.lstrip().startswith("|") or is_separator(line):
            continue
        cells = table_cells(line)
        scope = " ".join(cells)
        if "для направлен" in normalise(scope):
            directions = tuple(dict.fromkeys(re.findall(r"(?<!\d)\d{2}\.\d{2}\.\d{2}(?!\d)", scope)))
            olympiad = ""
            continue
        if not directions or len(cells) < 8:
            continue
        if cells[1]:
            olympiad = cells[1]
        profile = cells[2]
        if not olympiad or not profile:
            continue
        statuses: list[DiplomaStatus] = []
        if provided(cells[6]):
            statuses.append("winner")
        if provided(cells[7]):
            statuses.append("prize_winner")
        if not statuses:
            continue
        excerpt = compact(" | ".join(cells))[:4_000]
        payload: dict[str, object] = {
            "kind": "bmstu_bvi_appendix_row",
            "adapter": "strict-bmstu-bvi-2026-v1",
            "direction_codes": directions,
            "row": cells,
        }
        for direction in directions:
            for status in statuses:
                append_rule(
                    output,
                    seen,
                    programme_selector=direction,
                    olympiad_title=olympiad,
                    profile_title=profile,
                    diploma_status=status,
                    benefit_kind="bvi",
                    confirmation_subject_code=subject_code(cells[5]),
                    confirmation_min_score=75,
                    source_locator=f"markdown:line:{line_number}",
                    source_excerpt=excerpt,
                    raw_payload=payload,
                )
    return output


def mipt_competition_group_rules(markdown: str) -> list[StrictRule]:
    """Fail closed until an official MIPT group-to-programme catalogue exists."""
    document = normalise(markdown)
    if "физтех-школ" not in document or "конкурсн" not in document:
        return []
    # MIPT's source names physical-school competition groups (ФРКТ, ФПМИ,
    # etc.) in BVI cells. They are not educational-programme identifiers, so
    # publishing them as programmes would make an unauditable claim.
    return []


def bmstu_hundred_rules(markdown: str) -> list[StrictRule]:
    """Fail closed for Bauman appendix 5.3's subject/field-only scope."""
    document = normalise(markdown)
    if not all(term in document for term in ("приложение 5.3", "100 баллов")):
        return []
    # The appendix identifies subject and higher-education field, but no exact
    # Bauman programme or standard direction code. Keep it out of automatic
    # publication until a first-party programme mapping is configured.
    return []


def _grid_rules(adapter_code: str, markdown: str) -> list[StrictRule]:
    """Parse complete, explicit rules for one configured official format."""
    adapter = ADAPTERS.get(adapter_code)
    if adapter is None:
        raise ValueError(f"Unsupported strict admission adapter: {adapter_code}")
    if adapter.default_diploma_statuses and not all(term in normalise(markdown) for term in adapter.required_scope_terms):
        return []
    output: list[StrictRule] = []
    seen: set[tuple[str, str, str, str, str]] = set()

    for header_line, headers, rows in markdown_tables(markdown):
        programme_indexes = header_indexes(headers, adapter.programme_headers)
        olympiad_indexes = header_indexes(headers, adapter.olympiad_headers)
        profile_indexes = header_indexes(headers, adapter.profile_headers)
        olympiad_indexes = [index for index in olympiad_indexes if index not in profile_indexes]
        diploma_indexes = header_indexes(headers, adapter.diploma_headers)
        subject_indexes = header_indexes(headers, adapter.subject_headers)
        score_indexes = header_indexes(headers, adapter.score_headers)
        generic_benefit_indexes = header_indexes(headers, adapter.generic_benefit_headers)
        named_benefit_indexes = [
            index
            for index, header in enumerate(headers)
            if benefit_from_cell(header, "да") is not None
        ]
        benefit_indexes = tuple(dict.fromkeys([*named_benefit_indexes, *generic_benefit_indexes]))

        # No named olympiad/profile column means a visual table must not be
        # treated as a benefit source, even if it contains familiar words.
        if not olympiad_indexes or not profile_indexes or not benefit_indexes:
            continue

        inherited_programme = ""
        inherited_olympiad = ""
        for line_number, cells in rows:
            programme_cell = cell_at(cells, programme_indexes[0]) if programme_indexes else ""
            if (
                not programme_cell
                and adapter.programme_group_in_first_cell
                and cells
                and len([cell for cell in cells if cell]) == 1
                and normalise(cells[0]).startswith(("направление", "программа"))
            ):
                # pdfplumber shifts a merged programme group one cell to the
                # left, while following rows stay aligned with the header.
                programme_cell = cells[0]
            if programme_cell:
                inherited_programme = programme_cell
            programme = programme_cell or (inherited_programme if adapter.inherit_programme else "")
            olympiad_cell = cell_at(cells, olympiad_indexes[0])
            if olympiad_cell:
                inherited_olympiad = olympiad_cell
            olympiad = olympiad_cell or (inherited_olympiad if adapter.inherit_olympiad else "")
            profile = cell_at(cells, profile_indexes[0])
            if (not programme and not adapter.benefit_cells_are_programmes) or not olympiad or not profile:
                continue
            statuses = tuple(
                status
                for index in diploma_indexes
                for status in explicit_statuses(cell_at(cells, index))
            )
            statuses = tuple(dict.fromkeys(statuses)) or adapter.default_diploma_statuses
            if not statuses:
                continue

            subject = next((subject_code(cell_at(cells, index)) for index in subject_indexes if subject_code(cell_at(cells, index))), None)
            score = next((confirmation_score(cell_at(cells, index)) for index in score_indexes if confirmation_score(cell_at(cells, index)) is not None), None)
            fixed_programmes = programme_selectors(programme)
            for benefit_index in benefit_indexes:
                header = headers[benefit_index]
                value = cell_at(cells, benefit_index)
                benefit = benefit_from_cell(header, value, generic=benefit_index in generic_benefit_indexes)
                if benefit is None:
                    continue
                selectors = programme_selectors(value) if adapter.benefit_cells_are_programmes else fixed_programmes
                if not selectors:
                    continue
                excerpt = compact(" | ".join(cells))[:4_000]
                payload: dict[str, object] = {
                    "kind": "strict_table_row",
                    "adapter": adapter.code,
                    "header_line": header_line,
                    "headers": headers,
                    "row": cells,
                    "benefit_column": header,
                }
                for selector in selectors:
                    for status in statuses:
                        key = (selector, olympiad, profile, status, benefit)
                        if key in seen:
                            continue
                        seen.add(key)
                        output.append(
                            StrictRule(
                                programme_selector=selector,
                                olympiad_title=olympiad,
                                profile_title=profile,
                                diploma_status=status,
                                benefit_kind=benefit,
                                confirmation_subject_code=subject,
                                confirmation_min_score=score,
                                source_locator=f"markdown:line:{line_number}",
                                source_excerpt=excerpt,
                                raw_payload=payload,
                            )
                        )
    return output


def strict_rules(adapter_code: str, markdown: str) -> list[StrictRule]:
    """Dispatch to the checked reader for a configured official format."""
    adapter = ADAPTERS.get(adapter_code)
    if adapter is None:
        raise ValueError(f"Unsupported strict admission adapter: {adapter_code}")
    readers = {
        "grid": _grid_rules,
        "mipt_competition_groups": lambda _code, text: mipt_competition_group_rules(text),
        "msu_programme_table": lambda _code, text: msu_rules(text),
        "bmstu_bvi_appendix": lambda _code, text: bmstu_bvi_rules(text),
        "bmstu_hundred_appendix": lambda _code, text: bmstu_hundred_rules(text),
    }
    try:
        return readers[adapter.reader](adapter_code, markdown)
    except KeyError as error:  # pragma: no cover - configuration guard
        raise ValueError(f"Unsupported strict reader: {adapter.reader}") from error
