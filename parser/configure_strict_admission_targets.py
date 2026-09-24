#!/usr/bin/env python3
"""Bind known 2026 official sources to their strict campus-level adapters.

It runs after the location importer.  Keeping the binding in code as well as
in migration 008 makes a newly initialised PostgreSQL volume behave exactly
like an upgraded one.  The mapping intentionally contains only a university's
main location; a branch needs its own official benefits document before it can
receive an adapter.
"""

from __future__ import annotations

import os
import sys

try:
    import psycopg
except ImportError:  # pragma: no cover - environment dependent
    psycopg = None


TARGETS = (
    ("hse-admission", "hse", "hse-moscow", "strict-hse-2026-v1"),
    ("mipt-admission", "mipt", "mipt-dolgoprudny", "strict-mipt-2026-v1"),
    ("mephi-admission", "mephi", "mephi-moscow", "strict-mephi-2026-v1"),
    ("msu-admission", "msu", "msu-moscow", "strict-msu-2026-v1"),
    ("bmstu-admission", "bmstu", "bmstu-moscow", "strict-bmstu-2026-v1"),
)


def configure(connection: "psycopg.Connection") -> int:
    updated = 0
    with connection.cursor() as cursor:
        for source_code, university_code, location_code, adapter_code in TARGETS:
            cursor.execute(
                """
                UPDATE admission_source_targets target
                SET university_location_id = location.id,
                    adapter_code = %s,
                    adapter_config = target.adapter_config || jsonb_build_object(
                      'strict_adapter', %s::text,
                      'rsosh_catalogue_year', 2025
                    ),
                    next_check_at = now(),
                    updated_at = now()
                FROM sources source,
                     admission_campaigns campaign,
                     universities university,
                     university_locations location
                WHERE target.source_id = source.id
                  AND campaign.id = target.admission_campaign_id
                  AND university.id = campaign.university_id
                  AND location.university_id = university.id
                  AND source.code = %s
                  AND university.code = %s
                  AND location.code = %s
                  AND campaign.campaign_year = 2026
                """,
                (adapter_code, adapter_code, source_code, university_code, location_code),
            )
            updated += cursor.rowcount
        cursor.execute(
            """
            UPDATE admission_source_targets target
            SET is_active = FALSE, updated_at = now()
            FROM sources source
            WHERE target.source_id = source.id
              AND source.code = 'bmstu-admission'
              AND target.url NOT IN (
                'https://api.www.bmstu.ru/file/124777/download',
                'https://api.www.bmstu.ru/file/122150/download'
              )
            """
        )
    return updated


def main() -> int:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("DATABASE_URL is required", file=sys.stderr)
        return 2
    if psycopg is None:
        print("Install dependencies first: python -m pip install -r requirements.txt", file=sys.stderr)
        return 2
    with psycopg.connect(database_url) as connection:
        count = configure(connection)
        connection.commit()
    print(f"Configured {count} strict admission source targets.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
