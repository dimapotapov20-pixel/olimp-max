#!/usr/bin/env python3
"""Export the verified university-location programme catalogue for the mini app.

The static MAX/Vercel build cannot query PostgreSQL directly.  This exporter
keeps the same relationship as the database: a programme is displayed only
under its explicit university location.  A code from an admission appendix is
kept as ``code_only`` until a first-party programme catalogue confirms its
marketing name.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:  # pragma: no cover - environment dependent
    psycopg = None
    dict_row = None


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "dist" / "data" / "university-programs.json"
PROGRAMME_STATUSES = {"named_verified", "code_only"}
DEGREE_LEVELS = {"bachelor", "specialist"}
DIRECTION_CODE = re.compile(r"^\d{2}\.\d{2}\.\d{2}$")


def validate_public_programme(programme: dict[str, Any]) -> None:
    required = {"university_code", "university_location_code", "programme_name", "catalogue_status", "degree_level", "source_url", "checked_at"}
    missing = sorted(field for field in required if not str(programme.get(field, "")).strip())
    if missing:
        raise ValueError("Public programme is missing: " + ", ".join(missing))
    if programme["catalogue_status"] not in PROGRAMME_STATUSES:
        raise ValueError(f"Unsupported programme catalogue status: {programme['catalogue_status']}")
    if programme["degree_level"] not in DEGREE_LEVELS:
        raise ValueError(f"Unsupported degree level: {programme['degree_level']}")
    external_code = programme.get("external_code")
    if programme["catalogue_status"] == "code_only" and not DIRECTION_CODE.fullmatch(str(external_code or "")):
        raise ValueError("Code-only programme must have a full direction code")


def build_payload(rows: list[dict[str, Any]], campaign_year: int, generated_at: str) -> dict[str, Any]:
    programmes: list[dict[str, Any]] = []
    public_fields = (
        "university_code",
        "university_location_code",
        "external_code",
        "programme_name",
        "catalogue_status",
        "degree_level",
        "verified_benefits_count",
        "source_url",
        "checked_at",
    )
    for row in rows:
        programme = {field: row.get(field) for field in public_fields}
        validate_public_programme(programme)
        programme["verified_benefits_count"] = int(programme.get("verified_benefits_count") or 0)
        programmes.append(programme)
    programmes.sort(
        key=lambda programme: (
            programme["university_code"],
            programme["university_location_code"],
            programme.get("external_code") or "",
            programme["programme_name"],
        )
    )
    return {
        "campaign": campaign_year,
        "updated_at": generated_at,
        "scope_note": (
            "Каждая запись привязана к конкретной площадке. Кодовое направление "
            "не считается названной образовательной программой, пока это не "
            "подтверждено официальным каталогом вуза."
        ),
        "programmes": programmes,
    }


def fetch_programmes(connection: "psycopg.Connection", campaign_year: int) -> list[dict[str, Any]]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
              university.code AS university_code,
              location.code AS university_location_code,
              program.external_code,
              program.name AS programme_name,
              program.catalogue_status,
              program.degree_level,
              count(rule.id) FILTER (
                WHERE rule.is_active AND rule.verification_status = 'verified'
              ) AS verified_benefits_count,
              COALESCE(
                min(rule.source_url) FILTER (
                  WHERE rule.is_active AND rule.verification_status = 'verified'
                ),
                location.admission_rules_url,
                location.official_url
              ) AS source_url,
              to_char(
                COALESCE(
                  max(rule.checked_at) FILTER (
                    WHERE rule.is_active AND rule.verification_status = 'verified'
                  ),
                  location.admission_checked_at,
                  location.location_checked_at
                ) AT TIME ZONE 'UTC',
                'YYYY-MM-DD'
              ) AS checked_at
            FROM university_programs program
            JOIN universities university ON university.id = program.university_id
            JOIN university_locations location ON location.id = program.university_location_id
            LEFT JOIN admission_campaigns campaign
              ON campaign.university_id = university.id
             AND campaign.campaign_year = %s
            LEFT JOIN benefit_rules rule
              ON rule.university_program_id = program.id
             AND rule.admission_campaign_id = campaign.id
            WHERE program.is_active
              AND location.is_active
              AND university.is_active
            GROUP BY university.code, location.code, program.id, location.id
            ORDER BY university.code, location.code, program.external_code, program.name
            """,
            (campaign_year,),
        )
        return list(cursor.fetchall())


def write_payload(payload: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output)


def main() -> int:
    parser = argparse.ArgumentParser(description="Export university programmes for static MAX hosting")
    parser.add_argument("--campaign-year", type=int, default=2026)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("DATABASE_URL is required", file=sys.stderr)
        return 2
    if psycopg is None:
        print("Install dependencies first: python -m pip install -r requirements.txt", file=sys.stderr)
        return 2
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        rows = fetch_programmes(connection, args.campaign_year)
    payload = build_payload(rows, args.campaign_year, datetime.now(UTC).date().isoformat())
    write_payload(payload, args.output)
    print(f"Exported {len(rows)} university programme(s) to {args.output}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
