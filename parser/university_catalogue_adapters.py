#!/usr/bin/env python3
"""Strict readers for official university programme catalogues.

Admission appendices and programme catalogues solve different problems.  The
former says which direction receives a benefit; the latter supplies a human
readable title and proves that it belongs to one particular campus.  This
module deliberately keeps both parser families separate.

Every university has a named adapter even when its current page happens to be
a normal HTML table.  It means a markup change at one university can be fixed
without broadening parsing rules for the others.  An adapter returns only
records explicitly present in its supplied official document; it never falls
back to a parent university or fills a branch from another campus.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Iterable


CODE = re.compile(r"(?<!\d)(\d{2}\.\d{2}\.\d{2})(?!\d)")
MAX_PROGRAMME_NAME = 240


def compact(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\u00ad", "").replace("\xa0", " ")).strip()


def normalise(value: str) -> str:
    return compact(value).casefold().replace("ё", "е")


def degree_level(code: str | None, context: str) -> str:
    if code and code.split(".")[1] == "05":
        return "specialist"
    return "specialist" if "специалитет" in normalise(context) else "bachelor"


def is_admission_direction_code(code: str | None) -> bool:
    """Accept only bachelor/specialist direction codes for this catalogue.

    Pages under ``/sveden/education`` can also list short courses whose local
    identifiers look like ``00.00.12``.  They are not admission directions
    and must never appear as programmes in the school-olympiad flow.
    """
    if not code or not CODE.fullmatch(code):
        return False
    first, level, last = (int(part) for part in code.split("."))
    return 1 <= first <= 99 and level in {3, 5} and 1 <= last <= 99


def valid_name(value: str) -> bool:
    value = compact(value)
    lowered = normalise(value)
    blocked = (
        "итого", "всего", "количество мест", "контрольные цифры",
        "направления подготовки и", "образовательные программы",
        "бюджетных мест", "платных мест", "вступительные испытания",
    )
    return (
        3 <= len(value) <= MAX_PROGRAMME_NAME
        and any(letter.isalpha() for letter in value)
        and not any(fragment in lowered for fragment in blocked)
    )


def strip_code(value: str) -> tuple[str | None, str]:
    value = compact(value)
    match = CODE.search(value)
    if not match:
        return None, value
    code = match.group(1)
    before = compact(value[:match.start()]).strip(" —–-:;,")
    after = compact(value[match.end():]).strip(" —–-:;,")
    # Catalogue rows often start with a faculty, a serial number or a group;
    # when the official direction code has a following title, that suffix is
    # the programme/direction name.  If the code is terminal, retain the
    # human-readable text before it instead.
    return code, after or before


@dataclass(frozen=True)
class CatalogueProgramme:
    external_code: str | None
    name: str
    degree_level: str
    source_locator: str
    source_excerpt: str


def deduplicate(programmes: Iterable[CatalogueProgramme]) -> list[CatalogueProgramme]:
    output: list[CatalogueProgramme] = []
    seen: set[tuple[str | None, str]] = set()
    for programme in programmes:
        key = (programme.external_code, normalise(programme.name))
        if key in seen:
            continue
        seen.add(key)
        output.append(programme)
    return output


def table_cells(row: str) -> list[str]:
    return [compact(cell) for cell in row.strip().strip("|").split("|")]


def is_separator(row: str) -> bool:
    return bool(row.strip()) and all(
        re.fullmatch(r"\s*:?-{3,}:?\s*", cell or "---") is not None
        for cell in table_cells(row)
    )


def markdown_tables(markdown: str) -> Iterable[tuple[int, list[str], list[tuple[int, list[str]]]]]:
    """Yield only tables with a semantic programme-related header."""
    lines = markdown.splitlines()
    offset = 0
    while offset < len(lines):
        if not lines[offset].lstrip().startswith("|"):
            offset += 1
            continue
        start = offset
        while offset < len(lines) and lines[offset].lstrip().startswith("|"):
            offset += 1
        rows = [(line + 1, table_cells(lines[line])) for line in range(start, offset)]
        non_separators = [(line, cells) for line, cells in rows if not is_separator("|" + "|".join(cells) + "|")]
        if len(non_separators) < 2:
            continue
        vocabulary = ("код", "наименован", "направлен", "специальност", "образовательн", "программ")
        scores = [
            (sum(term in normalise(cell) for cell in cells for term in vocabulary), index)
            for index, (_, cells) in enumerate(non_separators)
        ]
        best_score = max(score for score, _ in scores)
        if best_score < 2:
            continue
        header_index = next(index for score, index in scores if score == best_score)
        line, headers = non_separators[header_index]
        data = non_separators[header_index + 1 :]
        if data:
            yield line, headers, data


def header_index(headers: list[str], aliases: tuple[str, ...]) -> int | None:
    # Alias order is semantic priority: МИФИ, for example, publishes both a
    # direction title and a narrower educational-programme title in one row.
    # The latter must win even though the direction column occurs first.
    normalised_headers = [normalise(header) for header in headers]
    for alias in aliases:
        index = next((index for index, header in enumerate(normalised_headers) if alias in header), None)
        if index is not None:
            return index
    return None


def cell(cells: list[str], index: int | None) -> str:
    return cells[index] if index is not None and index < len(cells) else ""


def table_programmes(
    markdown: str,
    *,
    name_headers: tuple[str, ...],
    require_code: bool,
) -> list[CatalogueProgramme]:
    """Read labelled official table columns without relying on their order."""
    output: list[CatalogueProgramme] = []
    for header_line, headers, rows in markdown_tables(markdown):
        code_index = header_index(headers, ("код",))
        name_index = header_index(headers, name_headers)
        if name_index is None:
            continue
        for line, cells in rows:
            title_cell = cell(cells, name_index)
            code, title = strip_code(cell(cells, code_index)) if code_index is not None else (None, "")
            embedded_code, embedded_title = strip_code(title_cell)
            code = code or embedded_code
            title = title or embedded_title or title_cell
            title = compact(title)
            if code is not None and not is_admission_direction_code(code):
                continue
            if require_code and code is None:
                continue
            if not valid_name(title):
                continue
            excerpt = " | ".join(cells)
            output.append(
                CatalogueProgramme(
                    external_code=code,
                    name=title,
                    degree_level=degree_level(code, " ".join([*headers, *cells])),
                    source_locator=f"markdown:table:{header_line}:row:{line}",
                    source_excerpt=excerpt[:4_000],
                )
            )
    return deduplicate(output)


def code_line_programmes(markdown: str) -> list[CatalogueProgramme]:
    """Read programme headings followed by a full education-direction code.

    MAI's public page is card-like rather than a single table; other sites may
    turn a PDF row into a plain line during extraction.  The nearest heading is
    used only when the code line itself has no title.
    """
    output: list[CatalogueProgramme] = []
    previous_heading = ""
    for line_number, raw_line in enumerate(markdown.splitlines(), start=1):
        # Table rows are handled by ``table_programmes``.  Treating them as
        # free text would accidentally append neighboring count columns to a
        # programme title.
        if raw_line.lstrip().startswith("|"):
            continue
        line = compact(raw_line.lstrip("# "))
        if not line:
            continue
        if raw_line.lstrip().startswith("#") and valid_name(line):
            previous_heading = line
            continue
        code, title = strip_code(line)
        if code is None:
            continue
        if not is_admission_direction_code(code):
            continue
        title = title or previous_heading
        if not valid_name(title):
            continue
        output.append(
            CatalogueProgramme(
                external_code=code,
                name=title,
                degree_level=degree_level(code, line + " " + previous_heading),
                source_locator=f"markdown:line:{line_number}",
                source_excerpt=line[:4_000],
            )
        )
    return deduplicate(output)


def programme_card_headings(markdown: str) -> list[CatalogueProgramme]:
    """Read a card catalogue where each third-level heading is a programme.

    MAI renders the programme cards client-side, so its static HTML does not
    contain the direction code.  It *does* contain the official card headings;
    those are useful catalogue names but intentionally keep ``external_code``
    null rather than guessing one from another document.
    """
    output: list[CatalogueProgramme] = []
    in_programme_section = False
    for line_number, raw_line in enumerate(markdown.splitlines(), start=1):
        stripped = raw_line.lstrip()
        if not stripped.startswith("#"):
            continue
        hashes, _, title = stripped.partition(" ")
        level = len(hashes)
        title = compact(title)
        if level <= 2:
            in_programme_section = "программ" in normalise(title)
            continue
        if level != 3 or not in_programme_section or not valid_name(title):
            continue
        output.append(
            CatalogueProgramme(
                external_code=None,
                name=title,
                degree_level="bachelor",
                source_locator=f"markdown:heading:{line_number}",
                source_excerpt=title,
            )
        )
    return deduplicate(output)


def source_is(markdown: str, *markers: str) -> bool:
    document = normalise(markdown)
    return all(normalise(marker) in document for marker in markers)


def hse_catalogue(markdown: str) -> list[CatalogueProgramme]:
    if not source_is(markdown, "вшэ"):
        return []
    # HSE's public catalogue can list a programme title without a direction
    # code. That is still a verified programme name, so its code stays null.
    return deduplicate(
        [
            *table_programmes(
                markdown,
                name_headers=("образовательн", "направлен", "специальност"),
                require_code=False,
            ),
            *code_line_programmes(markdown),
        ]
    )


def mipt_catalogue(markdown: str) -> list[CatalogueProgramme]:
    # The page is served by an approved MIPT target, but its extracted body
    # does not always repeat the acronym "МФТИ".  Its table has a special
    # shape: a code-only direction summary precedes rows for Физтех-школы.
    output: list[CatalogueProgramme] = []
    for header_line, headers, rows in markdown_tables(markdown):
        programme_index = header_index(headers, ("образовательные программы", "образовательн"))
        if programme_index is None:
            continue
        current_code: str | None = None
        for line, cells in rows:
            first = cell(cells, 0)
            row_code = CODE.search(" ".join(cells))
            if row_code and is_admission_direction_code(row_code.group(1)) and CODE.fullmatch(first.split(" ", 1)[0] if first else ""):
                current_code = row_code.group(1)
                continue
            # Rows listing target employers have no Физтех-школа in the first
            # cell.  They are not programmes and therefore cannot inherit the
            # preceding direction code.
            unit_like = bool(first) and first.upper() == first and any(char.isalpha() for char in first)
            title = cell(cells, programme_index)
            if not current_code or not unit_like or not valid_name(title):
                continue
            output.append(
                CatalogueProgramme(
                    external_code=current_code,
                    name=title,
                    degree_level=degree_level(current_code, " ".join(cells)),
                    source_locator=f"markdown:table:{header_line}:row:{line}",
                    source_excerpt=" | ".join(cells)[:4_000],
                )
            )
    return deduplicate(output)


def mephi_catalogue(markdown: str) -> list[CatalogueProgramme]:
    if not source_is(markdown, "мифи"):
        return []
    # The admission catalogue contains both a direction and a separate
    # educational-programme column.  The latter is selected when present.
    programmes = table_programmes(
        markdown,
        name_headers=("образовательная программа", "наименование направления", "направления", "специальност"),
        require_code=True,
    )
    return deduplicate([*programmes, *code_line_programmes(markdown)])


def msu_catalogue(markdown: str) -> list[CatalogueProgramme]:
    if not source_is(markdown, "мгу"):
        return []
    return deduplicate(
        [
            *table_programmes(
                markdown,
                name_headers=("образовательная программа", "направление", "специальност"),
                require_code=True,
            ),
            *code_line_programmes(markdown),
        ]
    )


def bmstu_catalogue(markdown: str) -> list[CatalogueProgramme]:
    if not source_is(markdown, "баумана"):
        return []
    return deduplicate(
        [
            *table_programmes(
                markdown,
                name_headers=("код, наименован", "наименован", "направлен", "специальност"),
                require_code=True,
            ),
            *code_line_programmes(markdown),
        ]
    )


def mai_catalogue(markdown: str) -> list[CatalogueProgramme]:
    if not source_is(markdown, "маи"):
        return []
    return deduplicate(
        [
            *programme_card_headings(markdown),
            *code_line_programmes(markdown),
            *table_programmes(
                markdown,
                name_headers=("наименован", "направлен", "специальност", "образовательн"),
                require_code=True,
            ),
        ]
    )


def mirea_catalogue(markdown: str) -> list[CatalogueProgramme]:
    if not source_is(markdown, "мирэа"):
        return []
    return deduplicate(
        [
            *table_programmes(
                markdown,
                name_headers=("наименован", "направлен", "специальност", "образовательн"),
                require_code=True,
            ),
            *code_line_programmes(markdown),
        ]
    )


CatalogueAdapter = Callable[[str], list[CatalogueProgramme]]

CATALOGUE_ADAPTERS: dict[str, CatalogueAdapter] = {
    "catalogue-hse-2026-v1": hse_catalogue,
    "catalogue-mipt-2026-v1": mipt_catalogue,
    "catalogue-mephi-2026-v1": mephi_catalogue,
    "catalogue-msu-2026-v1": msu_catalogue,
    "catalogue-bmstu-2026-v1": bmstu_catalogue,
    "catalogue-mai-2026-v1": mai_catalogue,
    "catalogue-mirea-2026-v1": mirea_catalogue,
}


def supported_codes() -> tuple[str, ...]:
    return tuple(CATALOGUE_ADAPTERS)


def catalogue_programmes(adapter_code: str, markdown: str) -> list[CatalogueProgramme]:
    adapter = CATALOGUE_ADAPTERS.get(adapter_code)
    if adapter is None:
        raise ValueError(f"Unsupported university catalogue adapter: {adapter_code}")
    return adapter(markdown)
