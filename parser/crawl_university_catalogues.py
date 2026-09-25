#!/usr/bin/env python3
"""Refresh official programme catalogues into PostgreSQL.

This worker is intentionally separate from ``crawl_admission_rules.py``:

``catalogue -> named programme at one campus``
``admission appendix -> exact benefit for a programme/direction``

Keeping those paths apart means a newly discovered programme cannot acquire a
benefit automatically, and an admission PDF cannot invent a human-readable
programme name.  Both parsers keep an immutable source-document snapshot and
their own auditable run row.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from dataclasses import dataclass
from pathlib import Path
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
    from parser.crawl_admission_rules import (
        ROOT,
        SNAPSHOT_DIR,
        document_to_markdown,
        fetch,
        guess_suffix,
        parsed_http_date,
        requests,
    )
    from parser.university_catalogue_adapters import CatalogueProgramme, catalogue_programmes, supported_codes
except ModuleNotFoundError:  # Allows `python parser/crawl_university_catalogues.py`.
    from crawl_admission_rules import (  # type: ignore
        ROOT,
        SNAPSHOT_DIR,
        document_to_markdown,
        fetch,
        guess_suffix,
        parsed_http_date,
        requests,
    )
    from university_catalogue_adapters import CatalogueProgramme, catalogue_programmes, supported_codes


ADAPTER_VERSION = "2026.2"


@dataclass(frozen=True)
class CatalogueTarget:
    id: int
    source_id: int
    university_id: int
    university_location_id: int
    location_code: str
    adapter_code: str
    url: str
    source_base_url: str
    adapter_config: dict[str, Any]


def adapter_version(target: CatalogueTarget) -> str:
    return f"{target.adapter_code}:{ADAPTER_VERSION}"


def due_targets(
    connection: "psycopg.Connection", limit: int, *, force: bool, excluded_ids: tuple[int, ...]
) -> list[CatalogueTarget]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT target.id, target.source_id, location.university_id,
                   target.university_location_id, location.code AS location_code,
                   target.adapter_code, target.url, source.base_url AS source_base_url,
                   target.adapter_config
            FROM university_catalogue_targets target
            JOIN university_locations location ON location.id = target.university_location_id
            JOIN sources source ON source.id = target.source_id
            WHERE target.is_active
              AND location.is_active
              AND target.adapter_code = ANY(%s)
              AND (%s OR target.next_check_at IS NULL OR target.next_check_at <= now())
              AND NOT target.id = ANY(%s)
              AND NOT EXISTS (
                SELECT 1
                FROM university_catalogue_parse_runs running
                WHERE running.university_catalogue_target_id = target.id
                  AND running.status = 'running'
                  AND running.started_at > now() - interval '1 hour'
              )
            ORDER BY target.next_check_at NULLS FIRST, target.id
            LIMIT %s
            FOR UPDATE OF target SKIP LOCKED
            """,
            (list(supported_codes()), force, list(excluded_ids), limit),
        )
        return [CatalogueTarget(**row) for row in cursor.fetchall()]


def defer_target(connection: "psycopg.Connection", target_id: int) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE university_catalogue_targets
            SET last_checked_at = now(),
                next_check_at = now() + make_interval(hours => poll_interval_hours),
                updated_at = now()
            WHERE id = %s
            """,
            (target_id,),
        )
    connection.commit()


def create_document_and_run(
    connection: "psycopg.Connection",
    target: CatalogueTarget,
    *,
    final_url: str,
    body: bytes,
    content_type: str,
    etag: str | None,
    last_modified: str | None,
    storage_key: str,
) -> tuple[int, int] | None:
    """Create an immutable source document and retryable parse run.

    An unchanged document is not reparsed at the same adapter version; only
    its next polling time is advanced.  A parser-version bump creates a new
    run against the same snapshot, which makes an adapter change auditable.
    """
    digest = hashlib.sha256(body).hexdigest()
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT document.id,
                   EXISTS (
                     SELECT 1 FROM university_catalogue_parse_runs run
                     WHERE run.university_catalogue_target_id = %s
                       AND run.source_document_id = document.id
                       AND run.adapter_version = %s
                       AND run.status = 'succeeded'
                   ) AS parsed
            FROM source_documents document
            WHERE document.source_id = %s AND document.content_sha256 = %s
            ORDER BY document.fetched_at DESC
            LIMIT 1
            """,
            (target.id, adapter_version(target), target.source_id, digest),
        )
        prior = cursor.fetchone()
        if prior and prior["parsed"]:
            cursor.execute(
                """
                UPDATE university_catalogue_targets
                SET last_checked_at = now(), last_successful_document_id = %s,
                    next_check_at = now() + make_interval(hours => poll_interval_hours),
                    updated_at = now()
                WHERE id = %s
                """,
                (prior["id"], target.id),
            )
            connection.commit()
            return None
        if prior:
            document_id = prior["id"]
            cursor.execute(
                """
                SELECT id
                FROM university_catalogue_parse_runs
                WHERE university_catalogue_target_id = %s
                  AND source_document_id = %s
                  AND adapter_version = %s
                LIMIT 1
                """,
                (target.id, document_id, adapter_version(target)),
            )
            existing = cursor.fetchone()
            if existing:
                run_id = existing["id"]
                cursor.execute(
                    """
                    UPDATE university_catalogue_parse_runs
                    SET status = 'running', started_at = now(), finished_at = NULL,
                        records_seen = 0, programmes_upserted = 0, error_message = NULL
                    WHERE id = %s
                    """,
                    (run_id,),
                )
            else:
                run_id = None
        else:
            cursor.execute(
                """
                INSERT INTO source_documents (
                  source_id, url, content_sha256, storage_key, content_type, content_size_bytes,
                  http_etag, source_last_modified_at, title, metadata
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    target.source_id,
                    final_url,
                    digest,
                    storage_key,
                    content_type,
                    len(body),
                    etag,
                    parsed_http_date(last_modified),
                    f"University catalogue: {target.location_code}",
                    Jsonb({"crawler": target.adapter_code, "crawler_version": adapter_version(target)}),
                ),
            )
            document_id = cursor.fetchone()["id"]
            run_id = None
        if run_id is None:
            cursor.execute(
                """
                INSERT INTO university_catalogue_parse_runs (
                  university_catalogue_target_id, source_document_id, adapter_code, adapter_version, status
                ) VALUES (%s, %s, %s, %s, 'running')
                RETURNING id
                """,
                (target.id, document_id, target.adapter_code, adapter_version(target)),
            )
            run_id = cursor.fetchone()["id"]
    connection.commit()
    return document_id, run_id


def upsert_programmes(
    connection: "psycopg.Connection",
    target: CatalogueTarget,
    document_id: int,
    run_id: int,
    programmes: list[CatalogueProgramme],
    source_url: str,
) -> int:
    """Persist names seen in one official location catalogue.

    Existing code-only rows from benefit documents stay intact.  A direction
    can have multiple marketed programmes, and choosing one of them would be
    an unsafe automatic rewrite of a verified benefit relationship.
    """
    count = 0
    with connection.cursor() as cursor:
        for programme in programmes:
            cursor.execute(
                """
                INSERT INTO university_programs (
                  university_id, university_location_id, external_code, name,
                  catalogue_status, degree_level, catalogue_source_target_id,
                  catalogue_parse_run_id, catalogue_source_url, catalogue_checked_at,
                  is_active
                ) VALUES (%s, %s, %s, %s, 'named_verified', %s, %s, %s, %s, now(), TRUE)
                ON CONFLICT (university_id, university_location_id, external_code, name)
                DO UPDATE SET
                  catalogue_status = 'named_verified',
                  degree_level = EXCLUDED.degree_level,
                  catalogue_source_target_id = EXCLUDED.catalogue_source_target_id,
                  catalogue_parse_run_id = EXCLUDED.catalogue_parse_run_id,
                  catalogue_source_url = EXCLUDED.catalogue_source_url,
                  catalogue_checked_at = EXCLUDED.catalogue_checked_at,
                  is_active = TRUE
                """,
                (
                    target.university_id,
                    target.university_location_id,
                    programme.external_code,
                    programme.name,
                    programme.degree_level,
                    target.id,
                    run_id,
                    source_url,
                ),
            )
            count += cursor.rowcount
        cursor.execute(
            """
            UPDATE university_catalogue_parse_runs
            SET status = 'succeeded', records_seen = %s, programmes_upserted = %s, finished_at = now()
            WHERE id = %s
            """,
            (len(programmes), count, run_id),
        )
        cursor.execute(
            """
            UPDATE university_catalogue_targets
            SET last_checked_at = now(), last_successful_document_id = %s,
                next_check_at = now() + make_interval(hours => poll_interval_hours),
                updated_at = now()
            WHERE id = %s
            """,
            (document_id, target.id),
        )
    connection.commit()
    return count


def fail_run(connection: "psycopg.Connection", target: CatalogueTarget, run_id: int, message: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE university_catalogue_parse_runs
            SET status = 'failed', error_message = %s, finished_at = now()
            WHERE id = %s
            """,
            (message[:4_000], run_id),
        )
    connection.commit()
    defer_target(connection, target.id)


def crawl_target(connection: "psycopg.Connection", target: CatalogueTarget) -> tuple[str, int]:
    body, final_url, content_type, etag, last_modified = fetch(target)
    suffix = guess_suffix(content_type, final_url)
    if suffix == ".bin":
        raise ValueError(f"Unsupported source content type: {content_type}")
    digest = hashlib.sha256(body).hexdigest()
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    snapshot = SNAPSHOT_DIR / f"catalogue-{digest}{suffix}"
    if not snapshot.exists():
        snapshot.write_bytes(body)
    created = create_document_and_run(
        connection,
        target,
        final_url=final_url,
        body=body,
        content_type=content_type,
        etag=etag,
        last_modified=last_modified,
        storage_key=str(snapshot.relative_to(ROOT)),
    )
    if created is None:
        return "unchanged", 0
    document_id, run_id = created
    try:
        markdown = document_to_markdown(snapshot)
        programmes = catalogue_programmes(target.adapter_code, markdown)
        if not programmes:
            # A source layout change must not silently clear a programme
            # directory.  Retain the old verified snapshot and retry later.
            raise ValueError("Adapter found no explicit programme rows")
        return "succeeded", upsert_programmes(
            connection, target, document_id, run_id, programmes, final_url
        )
    except Exception as error:
        fail_run(connection, target, run_id, str(error))
        raise


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=30, help="maximum due catalogue targets to crawl")
    parser.add_argument("--force", action="store_true", help="ignore poll time for active targets")
    return parser.parse_args()


def main() -> int:
    args = arguments()
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("DATABASE_URL is required", file=sys.stderr)
        return 2
    if psycopg is None or requests is None:
        print("Install dependencies first: python3 -m pip install -r requirements-crawler.txt", file=sys.stderr)
        return 2
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        errors = processed = 0
        excluded: set[int] = set()
        while processed < args.limit:
            targets = due_targets(connection, 1, force=args.force, excluded_ids=tuple(excluded) if args.force else ())
            if not targets:
                if processed == 0:
                    print("No due official university catalogue sources.")
                break
            target = targets[0]
            excluded.add(target.id)
            processed += 1
            try:
                status, count = crawl_target(connection, target)
                print(f"catalogue target {target.id} ({target.location_code}): {status}; {count} programme rows")
            except (requests.RequestException, OSError, RuntimeError, ValueError) as error:
                errors += 1
                defer_target(connection, target.id)
                print(f"catalogue target {target.id}: failed — {error}", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
