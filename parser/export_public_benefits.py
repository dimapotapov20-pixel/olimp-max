#!/usr/bin/env python3
"""Export only reviewed programme-level admission benefits for static demo hosting.

The API reads the same rows from PostgreSQL at runtime.  This exporter is for
the static MAX/Vercel demo: it creates a small public snapshot after review,
never exposing parser candidates, source excerpts, or user data.
"""

from __future__ import annotations

import argparse
import json
import os
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
DEFAULT_OUTPUT = ROOT / "dist" / "data" / "benefit-rules.json"
REQUIRED_FIELDS = {
    "university_code",
    "university_location_code",
    "programme_name",
    "olympiad_title",
    "profile_title",
    "olympiad_level",
    "diploma_status",
    "benefit_kind",
    "source_url",
    "checked_at",
}
VALID_DIPLOMAS = {"winner", "prize_winner", "finalist"}
VALID_BENEFITS = {"bvi", "hundred_points", "individual_points"}


def validate_public_rule(rule: dict[str, Any]) -> None:
    missing = sorted(field for field in REQUIRED_FIELDS if not str(rule.get(field, "")).strip())
    if missing:
        raise ValueError("Public benefit rule is missing: " + ", ".join(missing))
    if rule["diploma_status"] not in VALID_DIPLOMAS:
        raise ValueError(f"Unsupported diploma status: {rule['diploma_status']}")
    if rule["benefit_kind"] not in VALID_BENEFITS:
        raise ValueError(f"Unsupported benefit kind: {rule['benefit_kind']}")
    if int(rule["olympiad_level"]) not in {1, 2, 3}:
        raise ValueError("Olympiad level must be 1, 2 or 3")
    points = rule.get("point_value")
    if rule["benefit_kind"] == "individual_points":
        if not isinstance(points, int) or not 1 <= points <= 10:
            raise ValueError("Individual achievement points must be an integer from 1 to 10")
    elif points is not None:
        raise ValueError("Only individual achievement rules may include point_value")


def build_payload(rows: list[dict[str, Any]], campaign_year: int, generated_at: str) -> dict[str, Any]:
    """Validate, normalize ordering and remove fields that are not public."""
    rules: list[dict[str, Any]] = []
    public_fields = (
        "university_code",
        "university_location_code",
        "programme_name",
        "olympiad_title",
        "profile_title",
        "olympiad_level",
        "diploma_status",
        "benefit_kind",
        "point_value",
        "confirmation_subject_name",
        "confirmation_min_score",
        "source_url",
        "source_locator",
        "checked_at",
    )
    for row in rows:
        rule = {field: row.get(field) for field in public_fields}
        validate_public_rule(rule)
        rules.append(rule)
    rules.sort(
        key=lambda rule: (
            rule["university_code"],
            rule["university_location_code"],
            rule["programme_name"],
            rule["olympiad_title"],
            rule["profile_title"],
            rule["diploma_status"],
            rule["benefit_kind"],
        )
    )
    return {
        "campaign": campaign_year,
        "updated_at": generated_at,
        "scope_note": (
            "Публичный снимок содержит только проверенные построчные правила, "
            "привязанные к конкретной площадке и программе."
        ),
        "rules": rules,
    }


def fetch_verified_rows(connection: "psycopg.Connection", campaign_year: int) -> list[dict[str, Any]]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
              university.code AS university_code,
              location.code AS university_location_code,
              program.name AS programme_name,
              olympiad.title AS olympiad_title,
              profile.profile_title,
              profile.level AS olympiad_level,
              rule.diploma_status,
              rule.benefit_kind,
              rule.point_value,
              confirmation.name AS confirmation_subject_name,
              rule.confirmation_min_score,
              rule.source_url,
              rule.source_locator,
              to_char(rule.checked_at AT TIME ZONE 'UTC', 'YYYY-MM-DD') AS checked_at
            FROM benefit_rules rule
            JOIN admission_campaigns campaign ON campaign.id = rule.admission_campaign_id
            JOIN universities university ON university.id = campaign.university_id
            JOIN university_programs program ON program.id = rule.university_program_id
            JOIN university_locations location ON location.id = program.university_location_id
            JOIN olympiad_profiles profile ON profile.id = rule.olympiad_profile_id
            JOIN olympiads olympiad ON olympiad.id = profile.olympiad_id
            LEFT JOIN subjects confirmation ON confirmation.id = rule.confirmation_subject_id
            WHERE campaign.campaign_year = %s
              AND rule.is_active
              AND rule.verification_status = 'verified'
              AND location.is_active
              AND location.admission_status = 'benefits_verified'
            ORDER BY university.code, location.code, program.name, olympiad.title,
                     profile.profile_title, rule.diploma_status, rule.benefit_kind
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
    parser = argparse.ArgumentParser(description="Export reviewed Olimp admission benefits for static hosting")
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
        rows = fetch_verified_rows(connection, args.campaign_year)
    payload = build_payload(rows, args.campaign_year, datetime.now(UTC).date().isoformat())
    write_payload(payload, args.output)
    print(f"Exported {len(rows)} reviewed benefit rule(s) to {args.output}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
