#!/usr/bin/env python3
"""Collect public, official olympiad catalogues for the Olimp mini app.

The collector intentionally names its coverage in the output instead of
claiming to know every competition in Russia: it imports the full approved
RСОШ school list and every current direction from the official
«Я — профессионал» catalogue. New sources are added as separate adapters so
their status, URL and record count remain auditable.
"""

from __future__ import annotations

import html
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "dist" / "data" / "olympiads.json"
USER_AGENT = "OlimpScout-MVP/0.1 (+educational-demo; public-catalog-reader)"


def get_html(url: str) -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "ru,en;q=0.8"})
    with urlopen(request, timeout=20) as response:  # nosec B310 — URLs are fixed below
        return response.read().decode("utf-8", errors="replace")


def text(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


VSOSH_SUBJECTS = (
    "Английский язык", "Астрономия", "Биология", "География", "Информатика",
    "Искусство (МХК)", "Испанский язык", "История", "Итальянский язык",
    "Китайский язык", "Литература", "Математика", "Немецкий язык", "ОБЗР",
    "Обществознание", "Право", "Русский язык", "Труд (технология)", "Физика",
    "Физическая культура", "Французский язык", "Химия", "Экология", "Экономика",
)


def subject_tags(value: str) -> list[str]:
    """Map a source profile to one or more base subjects of ВсОШ."""
    value = value.lower()
    tags: list[str] = []
    rules = (
        ("иностранн", ("Английский язык", "Немецкий язык", "Французский язык", "Испанский язык", "Итальянский язык", "Китайский язык")),
        ("информат", ("Информатика",)), ("программир", ("Информатика",)),
        ("робототех", ("Информатика",)), ("кибербезопас", ("Информатика",)),
        ("искусственн", ("Информатика",)), ("математ", ("Математика",)),
        ("физик", ("Физика",)), ("хими", ("Химия",)), ("биолог", ("Биология",)),
        ("астроном", ("Астрономия",)), ("географ", ("География",)),
        ("геолог", ("География",)), ("эколог", ("Экология",)),
        ("эконом", ("Экономика",)), ("истори", ("История",)), ("прав", ("Право",)),
        ("обществ", ("Обществознание",)), ("финансов", ("Обществознание",)),
        ("английск", ("Английский язык",)), ("немецк", ("Немецкий язык",)),
        ("француз", ("Французский язык",)), ("испанск", ("Испанский язык",)),
        ("итальян", ("Итальянский язык",)), ("китайск", ("Китайский язык",)),
        ("русск", ("Русский язык",)), ("родн", ("Русский язык",)),
        ("лингв", ("Русский язык",)), ("филолог", ("Русский язык",)),
        ("литератур", ("Литература",)),
        ("мировая художественная", ("Искусство (МХК)",)),
        ("искусство", ("Искусство (МХК)",)), ("рисунок", ("Искусство (МХК)",)),
        ("живоп", ("Искусство (МХК)",)), ("скульптур", ("Искусство (МХК)",)),
        ("архитектур", ("Искусство (МХК)",)), ("дизайн", ("Искусство (МХК)",)),
        ("обж", ("ОБЗР",)), ("основы безопасности", ("ОБЗР",)),
        ("технолог", ("Труд (технология)",)), ("труд", ("Труд (технология)",)),
        ("физическ", ("Физическая культура",)),
    )
    for keyword, subjects in rules:
        if keyword in value:
            tags.extend(subjects)
    return list(dict.fromkeys(tags)) or ["Разные предметы"]


def primary_subject(value: str) -> str:
    return subject_tags(value)[0]


def parse_rsosh(markup: str) -> list[dict]:
    """Read the approved RСОШ list with profile, subject and level fields."""
    table = re.search(r'<table class="mainTableInfo">(?P<body>.*?)</table>', markup, re.IGNORECASE | re.DOTALL)
    if not table:
        raise ValueError("РСОШ table was not found")

    seen: set[tuple[str, str]] = set()
    items: list[dict] = []
    previous_title = ""
    previous_number = ""
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", table.group("body"), re.IGNORECASE | re.DOTALL):
        cells = [text(cell) for cell in re.findall(r"<td[^>]*>(.*?)</td>", row, re.IGNORECASE | re.DOTALL)]
        if len(cells) >= 5 and cells[0].isdigit():
            number, title, profile, subjects, level = cells[:5]
            previous_number = number
            previous_title = title
        elif previous_title and previous_number and len(cells) >= 3:
            # The official table uses rowspan for an olympiad number and its
            # title. Following rows contain only profile, subject and level.
            number = previous_number
            title = previous_title
            profile, subjects, level = cells[:3]
        else:
            continue
        key = (title.lower(), profile.lower())
        if not title or key in seen:
            continue
        seen.add(key)
        level_match = re.search(r"[123]", level)
        level_number = level_match.group(0) if level_match else "—"
        tags = subject_tags(f"{profile} {subjects}")
        items.append({
            "id": f"rsosh-{number}-{len(items) + 1}",
            "title": title,
            "audience": "school",
            "subject": tags[0],
            "subjects": tags,
            "subject_detail": subjects,
            "profile": profile,
            "level": level_number,
            "level_label": f"РСОШ · уровень {level_number}",
            "deadline": None,
            "deadline_label": "Срок уточняется у организатора",
            "source": "РСОШ · Перечень 2025/26",
            "source_url": "https://rsr-olymp.ru/",
            "kind": "Олимпиада из Перечня РСОШ",
        })
    return items


def parse_student_portal(markup: str) -> list[dict]:
    """Read every published direction from «Я — профессионал».

    Each direction gets its own card and link to the official direction page.
    The page is server-rendered, but classes are hashed, so the parser matches
    their stable prefixes rather than a particular build hash.
    """
    item_pattern = re.compile(
        r'<a\s+class="DirectionsSpoilerItem_item[^\"]*"\s+href="(?P<url>[^"]+)">'
        r'\s*<span\s+class="DirectionsSpoilerItem_title[^\"]*">(?P<title>.*?)</span>'
        r'\s*<span\s+class="DirectionsSpoilerItem_place[^\"]*">(?P<organizer>.*?)</span>',
        re.IGNORECASE | re.DOTALL,
    )
    season_match = re.search(r"Направления\s+(20\d{2})\s*[—–-]\s*(20\d{2})", text(markup))
    season = f"{season_match.group(1)}/{season_match.group(2)}" if season_match else "текущий сезон"
    seen: set[str] = set()
    items: list[dict] = []
    for match in item_pattern.finditer(markup):
        direction = text(match.group("title"))
        organizer = text(match.group("organizer"))
        if not direction or direction.casefold() in seen:
            continue
        seen.add(direction.casefold())
        source_url = html.unescape(match.group("url"))
        if source_url.startswith("/"):
            source_url = f"https://yandex.ru{source_url}"
        tags = subject_tags(direction)
        items.append({
            "id": f"ya-professional-{len(items) + 1}",
            "title": f"Я — профессионал · {direction}",
            "audience": "student",
            "subject": tags[0],
            "subjects": tags,
            "subject_detail": direction,
            "profile": direction,
            "organizer": organizer,
            "deadline": None,
            "deadline_label": "Сроки — на официальной странице направления",
            "source": f"Я — профессионал · направления {season}",
            "source_url": source_url,
            "kind": "Всероссийская олимпиада студентов",
        })
    if not items:
        raise ValueError("Я — профессионал: directions were not found")
    return items


def main() -> int:
    adapters = (
        ("rsosh_2025_26", "https://rsr-olymp.ru/", parse_rsosh),
        ("ya_professional_directions", "https://yandex.ru/profi/courses", parse_student_portal),
    )
    records: list[dict] = []
    sources: list[dict] = []
    for adapter_id, url, parser in adapters:
        try:
            parsed = parser(get_html(url))
            records.extend(parsed)
            sources.append({"id": adapter_id, "url": url, "status": "ok", "records": len(parsed)})
        except (URLError, TimeoutError, ValueError) as error:
            sources.append({"id": adapter_id, "url": url, "status": "error", "message": str(error), "records": 0})

    # One olympiad can have several distinct profiles, so the profile is part of the key.
    unique: dict[tuple[str, str, str], dict] = {}
    for record in records:
        unique[(record["title"].lower(), record["audience"], record.get("profile", "").lower())] = record

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "coverage": {
            "school": "Полный утверждённый Перечень РСОШ на 2025/26 учебный год: олимпиады и профили.",
            "student": "Все опубликованные направления олимпиады «Я — профессионал» на текущей официальной странице направлений.",
            "note": "Региональные, корпоративные и вузовские олимпиады добавляются отдельными адаптерами после выбора официального источника.",
        },
        "records": list(unique.values()),
        "sources": sources,
    }
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Collected {len(payload['records'])} records from {sum(item['status'] == 'ok' for item in sources)} sources")
    return 0


if __name__ == "__main__":
    sys.exit(main())
