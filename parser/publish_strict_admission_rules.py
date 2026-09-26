#!/usr/bin/env python3
"""Automatically publish complete rows emitted by strict admission adapters.

This is deliberately separate from discovery.  A rule reaches ``benefit_rules``
only after this program resolves, in one transaction, both exact foreign keys:

``official table row -> programme of this campus -> RСОШ profile``.

If a programme code is absent from the local programme catalogue, or an
olympiad/profile does not resolve exactly, the candidate is retained with a
machine-readable reason.  No fallback to another programme, university or
branch is permitted.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from typing import Any

try:
    import psycopg
    from psycopg.rows import dict_row
    from psycopg.types.json import Jsonb
except ImportError:  # pragma: no cover - environment dependent
    psycopg = None
    dict_row = None
    Jsonb = None

try:
    from parser.match_rsosh_candidates import RsoshProfile, match_candidate_text, normalise, read_catalogue
    from parser.strict_admission_adapters import supported_codes
except ModuleNotFoundError:  # Allows `python parser/publish_strict_admission_rules.py`.
    from match_rsosh_candidates import RsoshProfile, match_candidate_text, normalise, read_catalogue
    from strict_admission_adapters import supported_codes


@dataclass(frozen=True)
class Programme:
    id: int
    external_code: str | None
    name: str
    catalogue_status: str = "named_verified"


def programme_match(selector: str, programmes: list[Programme]) -> Programme | None:
    """Resolve one programme only; duplicates stay unresolved.

    A catalogue can name several educational programmes inside the same
    direction.  An admission appendix that names only that direction must
    resolve to the separate ``code_only`` scope, not arbitrarily to one of
    the catalogue labels.
    """
    expected = normalise(selector)
    selector_code = direction_code(selector)
    if selector_code:
        code_scopes = [
            programme
            for programme in programmes
            if programme.external_code == selector_code and programme.catalogue_status == "code_only"
        ]
        if len(code_scopes) == 1:
            return code_scopes[0]
        if len(code_scopes) > 1:
            return None
    matches = [
        programme
        for programme in programmes
        if normalise(programme.name) == expected
        or (programme.external_code is not None and normalise(programme.external_code) == expected)
    ]
    return matches[0] if len(matches) == 1 else None


def complete(candidate: dict[str, Any]) -> str | None:
    """Return an explainable block reason, or ``None`` for a complete record."""
    adapter_code = candidate.get("adapter_code")
    payload = candidate.get("raw_payload") or {}
    automatic_table = isinstance(payload, dict) and payload.get("kind") == "automatic_explicit_table_row"
    if adapter_code and adapter_code not in supported_codes() and not automatic_table:
        return "generic_source_without_explicit_table_proof"
    if candidate.get("confidence") != 100:
        return "strict_confidence_required"
    if not candidate.get("university_location_id"):
        return "missing_location_scope"
    if not all(candidate.get(key) for key in ("raw_programme_name", "raw_olympiad_name", "raw_profile_name")):
        return "missing_explicit_identity"
    if candidate.get("suggested_diploma_status") not in {"winner", "prize_winner"}:
        return "missing_explicit_diploma_status"
    if candidate.get("suggested_benefit_kind") not in {"bvi", "hundred_points"}:
        return "missing_explicit_benefit_kind"
    return None


def programmes_for_location(connection: "psycopg.Connection", location_id: int) -> list[Programme]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT id, external_code, name
                   , catalogue_status
            FROM university_programs
            WHERE university_location_id = %s AND is_active
            """,
            (location_id,),
        )
        return [Programme(**row) for row in cursor.fetchall()]


def direction_code(value: str) -> str | None:
    """A code is an official scope even when a source omits a prose name."""
    value = value.strip()
    return value if re.fullmatch(r"\d{2}\.\d{2}\.\d{2}", value) else None


def degree_level_for_direction(code: str) -> str:
    """The middle classifier block ``05`` denotes a specialist programme."""
    return "specialist" if code.split(".")[1] == "05" else "bachelor"


def official_named_scope(candidate: dict[str, Any]) -> str | None:
    """Accept a programme name only from an adapter with programme-first rows.

    MSU's official table explicitly labels the first column as a programme or
    specialty. Other sources can use prose such as a competition group,
    faculty, or a collection of fields; those must not become user-visible
    programmes merely because they happen to be in the same PDF.
    """
    if candidate.get("adapter_code") != "strict-msu-2026-v2":
        return None
    payload = candidate.get("raw_payload") or {}
    if payload.get("kind") != "msu_programme_table_row":
        return None
    value = str(candidate.get("raw_programme_name") or "").strip()
    blocked_fragments = ("все направлен", "группа программ", "конкурсн", "факультет")
    if not value or direction_code(value) or any(part in normalise(value) for part in blocked_fragments):
        return None
    return value


def create_code_scope(
    connection: "psycopg.Connection", candidate: dict[str, Any], programmes: list[Programme]
) -> Programme | None:
    """Create a transparent code-only scope when the official table names it.

    This is not a guessed programme title.  It deliberately displays as
    «Направление 38.03.01» until an official programme catalogue supplies a
    verified human-readable name.  If the database already has one or more
    named entries for that code, the source is too coarse to choose between
    them and no automatic record is created.
    """
    code = direction_code(candidate["raw_programme_name"])
    if code is None or any(
        programme.external_code == code and programme.catalogue_status == "code_only"
        for programme in programmes
    ):
        return None
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT university_id
            FROM admission_campaigns
            WHERE id = %s
            """,
            (candidate["campaign_id"],),
        )
        campaign = cursor.fetchone()
        if campaign is None:
            return None
        label = f"Направление {code}"
        cursor.execute(
            """
            INSERT INTO university_programs (
              university_id, university_location_id, external_code, name, catalogue_status, degree_level
            ) VALUES (%s, %s, %s, %s, 'code_only', %s)
            ON CONFLICT (university_id, university_location_id, external_code, name)
            DO UPDATE SET is_active = TRUE, degree_level = EXCLUDED.degree_level
            RETURNING id, external_code, name, catalogue_status
            """,
            (campaign["university_id"], candidate["university_location_id"], code, label, degree_level_for_direction(code)),
        )
        return Programme(**cursor.fetchone())


def create_named_scope(
    connection: "psycopg.Connection", candidate: dict[str, Any], programmes: list[Programme]
) -> Programme | None:
    """Persist an exact programme label that appears in MSU's official table."""
    name = official_named_scope(candidate)
    if name is None or any(normalise(programme.name) == normalise(name) for programme in programmes):
        return None
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT university_id
            FROM admission_campaigns
            WHERE id = %s
            """,
            (candidate["campaign_id"],),
        )
        campaign = cursor.fetchone()
        if campaign is None:
            return None
        cursor.execute(
            """
            INSERT INTO university_programs (
              university_id, university_location_id, external_code, name, catalogue_status
            ) VALUES (%s, %s, NULL, %s, 'named_verified')
            ON CONFLICT (university_id, university_location_id, external_code, name)
            DO UPDATE SET is_active = TRUE, catalogue_status = 'named_verified'
            RETURNING id, external_code, name, catalogue_status
            """,
            (campaign["university_id"], candidate["university_location_id"], name),
        )
        return Programme(**cursor.fetchone())


def subject_id(connection: "psycopg.Connection", code: str | None) -> int | None:
    if not code:
        return None
    with connection.cursor() as cursor:
        cursor.execute("SELECT id FROM subjects WHERE code = %s", (code,))
        row = cursor.fetchone()
        return row["id"] if row else None


def block(connection: "psycopg.Connection", candidate_id: int, reason: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE admission_rule_candidates
            SET automatic_status = 'blocked', automatic_note = %s
            WHERE id = %s AND review_status = 'pending'
            """,
            (reason, candidate_id),
        )


def publish(
    connection: "psycopg.Connection",
    candidate: dict[str, Any],
    programme: Programme,
    profile: RsoshProfile,
) -> int:
    """Publish one resolved rule and return its canonical benefit-rule id."""
    confirmation_id = subject_id(connection, candidate.get("confirmation_subject_code"))
    raw_payload = candidate.get("raw_payload") or {}
    prefix = "automatic-table" if raw_payload.get("kind") == "automatic_explicit_table_row" else "strict-adapter"
    actor = f"{prefix}:{candidate['adapter_code']}"
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO benefit_rules (
              admission_campaign_id, university_program_id, olympiad_profile_id,
              diploma_status, benefit_kind, point_value,
              confirmation_subject_id, confirmation_min_score,
              source_url, source_document_id, admission_parse_run_id,
              source_locator, source_excerpt, checked_at,
              is_verified, verification_status, verified_at, verified_by,
              last_seen_at, is_active, publication_method
            ) VALUES (
              %s, %s, %s, %s, %s, NULL, %s, %s,
              %s, %s, %s, %s, %s, now(),
              TRUE, 'verified', now(), %s, now(), TRUE, 'strict_adapter'
            )
            ON CONFLICT (admission_campaign_id, university_program_id, olympiad_profile_id, diploma_status, benefit_kind)
            DO UPDATE SET
              confirmation_subject_id = EXCLUDED.confirmation_subject_id,
              confirmation_min_score = EXCLUDED.confirmation_min_score,
              source_url = EXCLUDED.source_url,
              source_document_id = EXCLUDED.source_document_id,
              admission_parse_run_id = EXCLUDED.admission_parse_run_id,
              source_locator = EXCLUDED.source_locator,
              source_excerpt = EXCLUDED.source_excerpt,
              checked_at = now(),
              verified_at = now(),
              verified_by = EXCLUDED.verified_by,
              last_seen_at = now(),
              is_active = TRUE
            WHERE benefit_rules.publication_method = 'strict_adapter'
            RETURNING id
            """,
            (
                candidate["campaign_id"], programme.id, profile.id,
                candidate["suggested_diploma_status"], candidate["suggested_benefit_kind"],
                confirmation_id, candidate["suggested_confirmation_min_score"],
                candidate["source_url"], candidate["source_document_id"], candidate["parse_run_id"],
                candidate["source_locator"], candidate["source_excerpt"], actor,
            ),
        )
        row = cursor.fetchone()
        if row:
            benefit_rule_id = row["id"]
        else:
            # A manually maintained row always wins over automatic updates.
            cursor.execute(
                """
                SELECT id
                FROM benefit_rules
                WHERE admission_campaign_id = %s
                  AND university_program_id = %s
                  AND olympiad_profile_id = %s
                  AND diploma_status = %s
                  AND benefit_kind = %s
                """,
                (
                    candidate["campaign_id"], programme.id, profile.id,
                    candidate["suggested_diploma_status"], candidate["suggested_benefit_kind"],
                ),
            )
            benefit_rule_id = cursor.fetchone()["id"]
        cursor.execute(
            """
            UPDATE admission_rule_candidates
            SET university_program_id = %s, olympiad_profile_id = %s,
                match_status = 'resolved', review_status = 'approved', reviewed_at = now(),
                published_benefit_rule_id = %s,
                automatic_status = 'published', automatic_note = 'exact_programme_and_rsosh_profile'
            WHERE id = %s AND review_status = 'pending'
            """,
            (programme.id, profile.id, benefit_rule_id, candidate["id"]),
        )
        cursor.execute(
            """
            INSERT INTO admission_rule_reviews (
              admission_rule_candidate_id, action, reviewer_id, notes, resolved_payload
            ) VALUES (%s, 'approved', %s, %s, %s)
            """,
            (
                candidate["id"], actor, "Automatically published after exact programme and РСОШ profile resolution.",
                Jsonb({"programme_id": programme.id, "olympiad_profile_id": profile.id, "method": "strict_adapter"}),
            ),
        )
        cursor.execute(
            """
            INSERT INTO benefit_rule_observations (
              benefit_rule_id, source_document_id, admission_parse_run_id,
              admission_rule_candidate_id, observed_status, source_locator, source_excerpt
            ) VALUES (%s, %s, %s, %s, 'present', %s, %s)
            ON CONFLICT (benefit_rule_id, source_document_id) DO UPDATE SET
              admission_parse_run_id = EXCLUDED.admission_parse_run_id,
              admission_rule_candidate_id = EXCLUDED.admission_rule_candidate_id,
              observed_status = 'present', source_locator = EXCLUDED.source_locator,
              source_excerpt = EXCLUDED.source_excerpt, observed_at = now()
            """,
            (
                benefit_rule_id, candidate["source_document_id"], candidate["parse_run_id"], candidate["id"],
                candidate["source_locator"], candidate["source_excerpt"],
            ),
        )
    return benefit_rule_id


def candidates(connection: "psycopg.Connection", limit: int) -> list[dict[str, Any]]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT candidate.id, candidate.admission_campaign_id AS campaign_id,
                   candidate.source_document_id, candidate.raw_programme_name,
                   candidate.raw_olympiad_name, candidate.raw_profile_name,
                   candidate.suggested_diploma_status, candidate.suggested_benefit_kind,
                   confirmation.code AS confirmation_subject_code,
                   candidate.suggested_confirmation_min_score, candidate.suggested_olympiad_level,
                   candidate.confidence,
                   candidate.source_locator, candidate.source_excerpt, candidate.raw_payload,
                   parse_run.id AS parse_run_id, parse_run.adapter_code,
                   target.university_location_id, document.url AS source_url,
                   COALESCE((target.adapter_config ->> 'rsosh_catalogue_year')::smallint,
                            campaign.campaign_year - 1) AS rsosh_catalogue_year
            FROM admission_rule_candidates candidate
            JOIN admission_parse_runs parse_run ON parse_run.id = candidate.admission_parse_run_id
            JOIN admission_source_targets target ON target.id = parse_run.admission_source_target_id
            JOIN admission_campaigns campaign ON campaign.id = candidate.admission_campaign_id
            JOIN source_documents document ON document.id = candidate.source_document_id
            LEFT JOIN subjects confirmation ON confirmation.id = candidate.suggested_confirmation_subject_id
            WHERE candidate.review_status = 'pending'
              AND candidate.automatic_status IN ('pending_resolution', 'blocked')
              AND (
                parse_run.adapter_code = ANY(%s)
                -- Generic extraction can join the automatic path only when
                -- the crawler proved that each identity field came from its
                -- own explicit table cell. Its confidence is set to 100 only
                -- for that narrow representation.
                OR candidate.confidence = 100
              )
            -- New exact rows must not be starved by an older exception queue.
            ORDER BY CASE candidate.automatic_status WHEN 'pending_resolution' THEN 0 ELSE 1 END,
                     candidate.created_at, candidate.id
            LIMIT %s
            FOR UPDATE OF candidate SKIP LOCKED
            """,
            (list(supported_codes()), limit),
        )
        return list(cursor.fetchall())


def run(connection: "psycopg.Connection", limit: int) -> tuple[int, int]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE university_programs
            SET degree_level = CASE
              WHEN split_part(external_code, '.', 2) = '05' THEN 'specialist'
              ELSE 'bachelor'
            END
            WHERE catalogue_status = 'code_only'
              AND external_code ~ '^\\d{2}\\.\\d{2}\\.\\d{2}$'
            """
        )
    published = blocked = 0
    profiles_by_year: dict[int, list[RsoshProfile]] = {}
    programmes_by_location: dict[int, list[Programme]] = {}
    for candidate in candidates(connection, limit):
        reason = complete(candidate)
        if reason:
            block(connection, candidate["id"], reason)
            blocked += 1
            continue
        location_id = candidate["university_location_id"]
        if location_id not in programmes_by_location:
            programmes_by_location[location_id] = programmes_for_location(connection, location_id)
        programmes = programmes_by_location[location_id]
        programme = programme_match(candidate["raw_programme_name"], programmes)
        if programme is None:
            created_scope = create_code_scope(connection, candidate, programmes)
            if created_scope is None:
                created_scope = create_named_scope(connection, candidate, programmes)
            if created_scope is not None:
                programmes.append(created_scope)
                programme = created_scope
        if programme is None:
            block(connection, candidate["id"], "programme_not_exactly_mapped_for_location")
            blocked += 1
            continue
        rsosh_year = candidate["rsosh_catalogue_year"]
        if rsosh_year not in profiles_by_year:
            profiles_by_year[rsosh_year] = read_catalogue(connection, rsosh_year)
        profiles = profiles_by_year[rsosh_year]
        match = match_candidate_text(f"{candidate['raw_olympiad_name']} | {candidate['raw_profile_name']}", profiles)
        if match.status != "resolved" or match.profile is None:
            block(connection, candidate["id"], f"rsosh_{match.reason}")
            blocked += 1
            continue
        if (
            candidate.get("suggested_olympiad_level") is not None
            and match.profile.level != candidate["suggested_olympiad_level"]
        ):
            block(connection, candidate["id"], "rsosh_level_mismatch")
            blocked += 1
            continue
        publish(connection, candidate, programme, match.profile)
        published += 1
    connection.commit()
    return published, blocked


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=500, help="maximum strict candidates to resolve")
    return parser.parse_args()


def main() -> int:
    args = arguments()
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("DATABASE_URL is required", file=sys.stderr)
        return 2
    if psycopg is None:
        print("Install dependencies first: python3 -m pip install -r requirements-crawler.txt", file=sys.stderr)
        return 2
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        published, blocked = run(connection, args.limit)
    print(f"Strict admission publisher: {published} published, {blocked} blocked for exact data.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
