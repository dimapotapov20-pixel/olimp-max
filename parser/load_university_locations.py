#!/usr/bin/env python3
"""Load official university locations into PostgreSQL.

The public snapshot is intentionally flat for the mini app, but every row is
stored under its parent university in PostgreSQL.  A location is not an
admission benefit: ``location_verified`` only means that its official catalogue
entry was checked.  Benefit data remains hidden until a location has
``benefits_verified`` status and programme-level rules are reviewed.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

try:
    import psycopg
except ImportError:  # pragma: no cover - environment dependent
    psycopg = None


ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "dist" / "data" / "universities.json"
LOCATION_TYPES = {"main", "campus", "branch", "online"}
ADMISSION_STATUSES = {
    "candidate",
    "location_verified",
    "rules_discovered",
    "benefits_verified",
    "archived",
}


def validate(records: list[dict[str, object]]) -> None:
    seen: set[tuple[str, str]] = set()
    required = {
        "id",
        "university_code",
        "name",
        "campus_name",
        "campus_type",
        "official_url",
        "location_source_url",
        "admission_status",
    }
    for record in records:
        missing = sorted(key for key in required if not str(record.get(key, "")).strip())
        if missing:
            raise ValueError(f"Location {record.get('id', '<unknown>')} is missing: {', '.join(missing)}")
        location_type = str(record["campus_type"])
        status = str(record["admission_status"])
        if location_type not in LOCATION_TYPES:
            raise ValueError(f"Unsupported location type: {location_type}")
        if status not in ADMISSION_STATUSES:
            raise ValueError(f"Unsupported admission status: {status}")
        key = (str(record["university_code"]), str(record["id"]))
        if key in seen:
            raise ValueError(f"Duplicate location key: {key}")
        seen.add(key)


def load_locations(conn: "psycopg.Connection", records: list[dict[str, object]]) -> int:
    with conn.cursor() as cursor:
        cursor.execute("SELECT id, code FROM universities")
        university_ids = {code: university_id for university_id, code in cursor.fetchall()}
        missing = sorted({str(record["university_code"]) for record in records} - set(university_ids))
        if missing:
            raise ValueError("Seed parent universities first: " + ", ".join(missing))

        for record in records:
            university_id = university_ids[str(record["university_code"])]
            cursor.execute(
                """
                INSERT INTO university_locations (
                  university_id, code, name, location_type, city, region, country,
                  official_url, directory_url, location_checked_at, admission_status,
                  admission_rules_url, admission_checked_at, is_active
                ) VALUES (
                  %(university_id)s, %(code)s, %(name)s, %(location_type)s,
                  %(city)s, %(region)s, %(country)s, %(official_url)s,
                  %(directory_url)s, %(checked_at)s, %(admission_status)s,
                  %(admission_rules_url)s, %(admission_checked_at)s, TRUE
                )
                ON CONFLICT (university_id, code) DO UPDATE SET
                  name = EXCLUDED.name,
                  location_type = EXCLUDED.location_type,
                  city = EXCLUDED.city,
                  region = EXCLUDED.region,
                  country = EXCLUDED.country,
                  official_url = EXCLUDED.official_url,
                  directory_url = EXCLUDED.directory_url,
                  location_checked_at = EXCLUDED.location_checked_at,
                  admission_status = EXCLUDED.admission_status,
                  admission_rules_url = EXCLUDED.admission_rules_url,
                  admission_checked_at = EXCLUDED.admission_checked_at,
                  is_active = TRUE
                """,
                {
                    "university_id": university_id,
                    "code": str(record["id"]),
                    "name": str(record["campus_name"]),
                    "location_type": str(record["campus_type"]),
                    "city": record.get("city"),
                    "region": record.get("region"),
                    "country": record.get("country") or "Россия",
                    "official_url": str(record["official_url"]),
                    "directory_url": str(record["location_source_url"]),
                    "checked_at": datetime.now(UTC),
                    "admission_status": str(record["admission_status"]),
                    "admission_rules_url": record.get("official_url")
                    if record.get("admission_status") in {"rules_discovered", "benefits_verified"}
                    else None,
                    "admission_checked_at": datetime.now(UTC)
                    if record.get("admission_status") in {"rules_discovered", "benefits_verified"}
                    else None,
                },
            )
    return len(records)


def main() -> int:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("DATABASE_URL is required", file=sys.stderr)
        return 2
    if psycopg is None:
        print("Install dependencies first: python -m pip install -r requirements.txt", file=sys.stderr)
        return 2
    payload = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    records = payload.get("universities", [])
    if not isinstance(records, list):
        raise ValueError("universities.json must contain a universities list")
    validate(records)
    with psycopg.connect(database_url) as connection:
        count = load_locations(connection, records)
        connection.commit()
    print(f"Loaded {count} official university locations into PostgreSQL.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
