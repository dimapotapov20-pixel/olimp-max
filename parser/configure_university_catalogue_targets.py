#!/usr/bin/env python3
"""Bind checked official programme catalogues to campus-specific adapters.

The mapping is intentionally data, not URL guessing.  Each target names both
the university and the exact location it describes.  For example, the public
Bauman source below is the Kaluga branch catalogue, so it is *not* attached to
Bauman's Moscow campus.
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


SOURCES = (
    ("hse-programmes", "НИУ ВШЭ: каталог программ", "https://ba.hse.ru/"),
    ("mipt-programmes", "МФТИ: программы и места", "https://pk.mipt.ru/"),
    ("mephi-programmes", "НИЯУ МИФИ: образовательные программы", "https://admission.mephi.ru/"),
    ("msu-programmes", "МГУ: направления подготовки", "https://cpk.msu.ru/"),
    ("bmstu-programmes", "МГТУ им. Н. Э. Баумана: программы филиала", "https://kf.bmstu.ru/"),
    ("mai-programmes", "МАИ: программы базового высшего образования", "https://priem.mai.ru/"),
    ("mirea-programmes", "РТУ МИРЭА: каталог филиала", "https://stavropol.mirea.ru/"),
)


# (source, university, location, URL, document type, adapter, approved hosts)
TARGETS = (
    (
        "hse-programmes", "hse", "hse-moscow", "https://ba.hse.ru/kolmest", "html",
        "catalogue-hse-2026-v1", ["ba.hse.ru", "www.hse.ru"],
    ),
    (
        "mipt-programmes", "mipt", "mipt-dolgoprudny", "https://pk.mipt.ru/bachelor/2026_places/", "html",
        "catalogue-mipt-2026-v1", ["pk.mipt.ru"],
    ),
    (
        "mephi-programmes", "mephi", "mephi-moscow", "https://admission.mephi.ru/admission/baccalaureate-and-specialty/education/programs", "html",
        "catalogue-mephi-2026-v1", ["admission.mephi.ru"],
    ),
    (
        "msu-programmes", "msu", "msu-moscow", "https://cpk.msu.ru/files/2026/kcp_bak.pdf", "pdf",
        "catalogue-msu-2026-v1", ["cpk.msu.ru"],
    ),
    (
        "bmstu-programmes", "bmstu", "bmstu-kaluga", "https://kf.bmstu.ru/bakalavriat-i-specialitet/kontrolnye-cifry-priyoma", "html",
        "catalogue-bmstu-2026-v1", ["kf.bmstu.ru", "bmstu.ru", "www.bmstu.ru"],
    ),
    (
        "mai-programmes", "mai", "mai-moscow", "https://priem.mai.ru/base/programs/", "html",
        "catalogue-mai-2026-v1", ["priem.mai.ru"],
    ),
    (
        "mirea-programmes", "mirea", "mirea-stavropol", "https://stavropol.mirea.ru/sveden/education", "html",
        "catalogue-mirea-2026-v1", ["stavropol.mirea.ru", "mirea.ru", "www.mirea.ru"],
    ),
)


def configure(connection: "psycopg.Connection") -> int:
    with connection.cursor() as cursor:
        for code, name, base_url in SOURCES:
            cursor.execute(
                """
                INSERT INTO sources (code, name, base_url, source_kind)
                VALUES (%s, %s, %s, 'catalog')
                ON CONFLICT (code) DO UPDATE SET
                  name = EXCLUDED.name, base_url = EXCLUDED.base_url,
                  source_kind = EXCLUDED.source_kind, is_active = TRUE
                """,
                (code, name, base_url),
            )
        configured = 0
        for source_code, university_code, location_code, url, document_kind, adapter_code, allowed_hosts in TARGETS:
            cursor.execute(
                """
                INSERT INTO university_catalogue_targets (
                  university_location_id, source_id, url, document_kind, adapter_code,
                  adapter_config, next_check_at, is_active
                )
                SELECT location.id, source.id, %s, %s, %s, %s, now(), TRUE
                FROM universities university
                JOIN university_locations location ON location.university_id = university.id
                JOIN sources source ON source.code = %s
                WHERE university.code = %s AND location.code = %s
                ON CONFLICT (university_location_id, url) DO UPDATE SET
                  source_id = EXCLUDED.source_id,
                  document_kind = EXCLUDED.document_kind,
                  adapter_code = EXCLUDED.adapter_code,
                  adapter_config = EXCLUDED.adapter_config,
                  next_check_at = now(),
                  is_active = TRUE,
                  updated_at = now()
                """,
                (
                    url,
                    document_kind,
                    adapter_code,
                    Jsonb({"allow_hosts": allowed_hosts}),
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
    print(f"Configured {count} official university catalogue target(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
