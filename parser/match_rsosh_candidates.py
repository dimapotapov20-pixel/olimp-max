#!/usr/bin/env python3
"""Safely link admission-rule candidates to the official RСОШ catalogue.

This is intentionally a *matcher*, not an auto-publisher.  It writes an
``olympiad_profile_id`` only when a candidate text identifies exactly one
approved RСОШ olympiad profile for the requested academic year.  Candidates
with no clear title/profile remain ``unresolved``; candidates with several
possible profiles become ``ambiguous``.  Neither result reaches users.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from typing import Literal

try:
    import psycopg
    from psycopg.rows import dict_row
    from psycopg.types.json import Jsonb
except ImportError:  # pragma: no cover - reported by main
    psycopg = None
    dict_row = None
    Jsonb = None


MatchStatus = Literal["resolved", "ambiguous", "unresolved"]


@dataclass(frozen=True)
class RsoshProfile:
    id: int
    olympiad_title: str
    profile_title: str
    level: int | None


@dataclass(frozen=True)
class CatalogueMatch:
    status: MatchStatus
    profile: RsoshProfile | None
    confidence: int | None
    reason: str
    alternatives: tuple[int, ...] = ()


def normalise(value: str) -> str:
    """Compare Russian titles independent of quotes, dashes and whitespace."""
    value = value.casefold().replace("ё", "е")
    value = re.sub(r"[^a-zа-я0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def title_aliases(title: str) -> tuple[str, ...]:
    """Return full and safe shortened forms of an official olympiad title."""
    full = normalise(title)
    aliases = {full}
    prefixes = (
        "всероссийская олимпиада школьников ",
        "межрегиональная олимпиада школьников ",
        "международная олимпиада школьников ",
        "олимпиада школьников ",
        "всероссийская олимпиада ",
        "межрегиональная олимпиада ",
        "олимпиада ",
    )
    for prefix in prefixes:
        if full.startswith(prefix):
            short = full.removeprefix(prefix).strip()
            # One generic word is never sufficient evidence of an identity.
            if len(short) >= 8 and " " in short:
                aliases.add(short)
    return tuple(sorted(aliases, key=len, reverse=True))


GENERIC_TITLE_WORDS = frozenset(
    {
        "всероссийская",
        "всероссийский",
        "межрегиональная",
        "международная",
        "открытая",
        "олимпиада",
        "школьников",
        "школьник",
        "конкурс",
        "по",
        "для",
        "имени",
    }
)


def title_is_specific(alias: str) -> bool:
    """Reject a title made solely of generic competition words.

    It prevents an official entry such as «Открытая олимпиада школьников»
    from matching the different «Всесибирская открытая олимпиада школьников».
    """
    distinctive = [word for word in alias.split() if word not in GENERIC_TITLE_WORDS]
    return sum(len(word) for word in distinctive) >= 8


def title_is_present(text: str, profile: RsoshProfile) -> bool:
    padded = f" {text} "
    return any(
        title_is_specific(alias) and f" {alias} " in padded
        for alias in title_aliases(profile.olympiad_title)
    )


def profile_is_present(text: str, profile: RsoshProfile) -> bool:
    profile_name = normalise(profile.profile_title)
    # Short profile names such as "ИИ" are too broad for automatic linking.
    return len(profile_name) >= 5 and profile_name in text


def table_cells(row: str) -> list[str]:
    """Read a Markdown table row without treating the whole row as evidence."""
    return [cell.strip() for cell in row.strip().strip("|").split("|")]


def candidate_identity_text(candidate: dict) -> str | None:
    """Return precisely the olympiad and profile cells from one parsed row.

    A benefit column frequently mentions several school subjects. Matching
    against the full row can therefore attach the mathematics profile to a
    physics row. Only an explicit table schema is reliable enough for the
    automatic link; paragraph candidates stay in the review queue.
    """
    payload = candidate.get("raw_payload")
    if not isinstance(payload, dict):
        return None
    identity = payload.get("identity")
    if isinstance(identity, dict):
        olympiad = identity.get("olympiad_title")
        profile = identity.get("profile_title")
        if isinstance(olympiad, str) and isinstance(profile, str) and olympiad and profile:
            return f"{olympiad} | {profile}"
    if payload.get("kind") != "table_row":
        return None
    headers = payload.get("headers")
    row = payload.get("row")
    if not isinstance(headers, list) or not isinstance(row, str):
        return None
    header_line = next((item for item in headers if isinstance(item, str) and "|" in item), None)
    if header_line is None:
        return None
    header_cells = [normalise(cell) for cell in table_cells(header_line)]
    row_cells = table_cells(row)
    olympiad_index = next(
        (
            index
            for index, cell in enumerate(header_cells)
            if cell in {"олимпиада", "наименование олимпиады", "название олимпиады"}
            or "наименование олимпиады" in cell
            or "название олимпиады" in cell
        ),
        None,
    )
    profile_index = next(
        (index for index, cell in enumerate(header_cells) if "профиль олимпиады" in cell),
        None,
    )
    if olympiad_index is None or profile_index is None:
        return None
    # HTML tables with colspan/rowspan often produce extra empty benefit cells
    # after the identity columns. The first columns still form an aligned
    # record, so only require that they are present; never shift values.
    if len(row_cells) <= max(olympiad_index, profile_index):
        return None
    olympiad, profile = row_cells[olympiad_index], row_cells[profile_index]
    if not olympiad or not profile:
        return None
    return f"{olympiad} | {profile}"


def match_candidate_text(text: str, profiles: list[RsoshProfile]) -> CatalogueMatch:
    """Resolve only exact title + profile evidence from the official catalogue."""
    document_text = normalise(text)
    title_hits = [profile for profile in profiles if title_is_present(document_text, profile)]
    if not title_hits:
        return CatalogueMatch("unresolved", None, None, "no_rsosh_title")

    profile_hits = [profile for profile in title_hits if profile_is_present(document_text, profile)]
    if len(profile_hits) == 1:
        return CatalogueMatch("resolved", profile_hits[0], 100, "title_and_profile")
    if len(profile_hits) > 1:
        return CatalogueMatch(
            "ambiguous", None, None, "multiple_profiles_in_candidate", tuple(profile.id for profile in profile_hits)
        )

    # Admission pages are not a copy of the РСОШ catalogue: a university can
    # list another profile under an olympiad name that happens to have one
    # row in our current source snapshot.  A title alone never identifies a
    # benefit rule reliably enough to write a foreign key.
    unique_profiles = {profile.id: profile for profile in title_hits}
    if len(unique_profiles) == 1:
        return CatalogueMatch("unresolved", None, None, "title_without_profile")
    return CatalogueMatch(
        "ambiguous", None, None, "title_has_multiple_profiles", tuple(unique_profiles)
    )


def read_catalogue(connection: "psycopg.Connection", campaign_year: int) -> list[RsoshProfile]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT profile.id, olympiad.title AS olympiad_title, profile.profile_title, profile.level
            FROM olympiad_profiles profile
            JOIN olympiads olympiad ON olympiad.id = profile.olympiad_id
            JOIN sources source ON source.id = profile.source_id
            WHERE source.code = 'rsosh'
              AND profile.campaign_year = %s
              AND profile.approval_status = 'approved'
              AND profile.is_active
              AND olympiad.is_active
            ORDER BY olympiad.title, profile.profile_title
            """,
            (campaign_year,),
        )
        return [RsoshProfile(**row) for row in cursor.fetchall()]


def pending_candidates(connection: "psycopg.Connection", limit: int) -> list[dict]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT id, raw_rule_text, raw_payload, confidence
            FROM admission_rule_candidates
            WHERE review_status = 'pending'
              AND match_status = 'unresolved'
            ORDER BY id
            LIMIT %s
            """,
            (limit,),
        )
        return cursor.fetchall()


def persist_match(connection: "psycopg.Connection", candidate: dict, match: CatalogueMatch) -> None:
    payload = {
        "rsosh_match": {
            "status": match.status,
            "reason": match.reason,
            "profile_id": match.profile.id if match.profile else None,
            "alternatives": list(match.alternatives),
        }
    }
    confidence = max(candidate.get("confidence") or 0, match.confidence or 0) or None
    with connection.cursor() as cursor:
        if match.status == "resolved" and match.profile:
            cursor.execute(
                """
                UPDATE admission_rule_candidates
                SET olympiad_profile_id = %s,
                    suggested_olympiad_level = %s,
                    match_status = 'resolved', confidence = %s,
                    raw_payload = raw_payload || %s
                WHERE id = %s
                """,
                (match.profile.id, match.profile.level, confidence, Jsonb(payload), candidate["id"]),
            )
        elif match.status == "ambiguous":
            cursor.execute(
                """
                UPDATE admission_rule_candidates
                SET match_status = 'ambiguous', raw_payload = raw_payload || %s
                WHERE id = %s
                """,
                (Jsonb(payload), candidate["id"]),
            )


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-year", type=int, default=2025, help="academic year of the RСОШ list")
    parser.add_argument("--limit", type=int, default=10_000, help="maximum pending candidates to inspect")
    parser.add_argument("--dry-run", action="store_true", help="print counts without writing candidate matches")
    parser.add_argument(
        "--show-samples",
        type=int,
        default=0,
        help="print up to N resolved/ambiguous samples for manual audit",
    )
    return parser.parse_args()


def main() -> int:
    args = arguments()
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("DATABASE_URL is required", file=sys.stderr)
        return 2
    if psycopg is None:
        print("Install dependencies first: python3 -m pip install -r requirements.txt", file=sys.stderr)
        return 2
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        profiles = read_catalogue(connection, args.campaign_year)
        if not profiles:
            print(f"No approved RСОШ profiles for {args.campaign_year}. Run parser/load_postgres.py first.", file=sys.stderr)
            return 2
        counts = {"resolved": 0, "ambiguous": 0, "unresolved": 0}
        samples: list[tuple[dict, CatalogueMatch]] = []
        for candidate in pending_candidates(connection, args.limit):
            identity = candidate_identity_text(candidate)
            match = (
                match_candidate_text(identity, profiles)
                if identity
                else CatalogueMatch("unresolved", None, None, "no_structured_identity")
            )
            counts[match.status] += 1
            if match.status != "unresolved" and len(samples) < args.show_samples:
                samples.append((candidate, match))
            if not args.dry_run and match.status != "unresolved":
                persist_match(connection, candidate, match)
        if not args.dry_run:
            connection.commit()
    prefix = "Would match" if args.dry_run else "Matched"
    print(f"{prefix}: {counts['resolved']} resolved, {counts['ambiguous']} ambiguous, {counts['unresolved']} unresolved.")
    for candidate, match in samples:
        excerpt = " ".join((candidate_identity_text(candidate) or candidate["raw_rule_text"]).split())[:180]
        target = (
            f"{match.profile.olympiad_title} / {match.profile.profile_title}"
            if match.profile
            else f"alternatives: {', '.join(map(str, match.alternatives))}"
        )
        print(f"  #{candidate['id']} [{match.reason}] → {target}\n    {excerpt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
