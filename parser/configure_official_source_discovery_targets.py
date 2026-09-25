#!/usr/bin/env python3
"""Configure bounded official-site discovery for admission documents.

Each row supplies a human-checked starting point and an allow-list of the
university's own hosts.  Discovery can add a *generic* candidate-parser target
when a highly relevant new document appears; exact benefit publication still
requires a strict campus-level adapter.
"""

from __future__ import annotations

import os
import sys

try:
    import psycopg
    from psycopg.types.json import Jsonb
except ImportError:  # pragma: no cover - environment dependent
    psycopg = None
    Jsonb = None


# source code, university, exact campus, starting page, approved official hosts
TARGETS = (
    ("hse-admission", "hse", "hse-moscow", "https://ba.hse.ru/", ["ba.hse.ru", "www.hse.ru"]),
    ("mipt-admission", "mipt", "mipt-dolgoprudny", "https://pk.mipt.ru/bachelor/", ["pk.mipt.ru"]),
    ("mephi-admission", "mephi", "mephi-moscow", "https://admission.mephi.ru/admission/baccalaureate-and-specialty/", ["admission.mephi.ru"]),
    ("msu-admission", "msu", "msu-moscow", "https://cpk.msu.ru/", ["cpk.msu.ru"]),
    ("bmstu-admission", "bmstu", "bmstu-moscow", "https://bmstu.ru/documents", ["bmstu.ru", "www.bmstu.ru", "api.www.bmstu.ru"]),
    ("mai-admission", "mai", "mai-moscow", "https://priem.mai.ru/base/", ["priem.mai.ru"]),
    ("mirea-admission", "mirea", "mirea-stavropol", "https://stavropol.mirea.ru/", ["stavropol.mirea.ru", "mirea.ru", "www.mirea.ru"]),
)


def configure(connection: "psycopg.Connection") -> int:
    configured = 0
    with connection.cursor() as cursor:
        for source_code, university_code, location_code, seed_url, allow_hosts in TARGETS:
            cursor.execute(
                """
                INSERT INTO official_source_discovery_targets (
                  admission_campaign_id, university_location_id, source_id, seed_url,
                  adapter_config, next_check_at, is_active
                )
                SELECT campaign.id, location.id, source.id, %s, %s, now(), TRUE
                FROM universities university
                JOIN admission_campaigns campaign
                  ON campaign.university_id = university.id AND campaign.campaign_year = 2026
                JOIN university_locations location
                  ON location.university_id = university.id
                JOIN sources source ON source.code = %s
                WHERE university.code = %s AND location.code = %s
                ON CONFLICT (admission_campaign_id, seed_url) DO UPDATE SET
                  university_location_id = EXCLUDED.university_location_id,
                  source_id = EXCLUDED.source_id,
                  adapter_config = EXCLUDED.adapter_config,
                  next_check_at = now(),
                  is_active = TRUE,
                  updated_at = now()
                """,
                (
                    seed_url,
                    Jsonb(
                        {
                            "allow_hosts": allow_hosts,
                            "max_pages": 24,
                            "max_depth": 2,
                            "minimum_score": 38,
                            "max_attachments": 8,
                        }
                    ),
                    source_code,
                    university_code,
                    location_code,
                ),
            )
            configured += cursor.rowcount
    return configured


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
    print(f"Configured {count} official-source discovery target(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
