#!/usr/bin/env python3
"""Load the public olympiad snapshot into the Olimp PostgreSQL catalogue.

Run collect_olympiads.py first. This loader preserves historical admission
campaigns and treats every source record as an auditable profile, not merely a
card in the interface.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

try:
    import psycopg
except ImportError:  # pragma: no cover - handled in main for a useful CLI error
    psycopg = None


ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "dist" / "data" / "olympiads.json"

SUBJECT_CODES = {
    "Английский язык": "english",
    "Астрономия": "astronomy",
    "Биология": "biology",
    "География": "geography",
    "Информатика": "informatics",
    "Искусство (МХК)": "art",
    "Испанский язык": "spanish",
    "История": "history",
    "Итальянский язык": "italian",
    "Китайский язык": "chinese",
    "Литература": "literature",
    "Математика": "math",
    "Немецкий язык": "german",
    "ОБЗР": "obzr",
    "Обществознание": "social-studies",
    "Право": "law",
    "Русский язык": "russian",
    "Труд (технология)": "technology",
    "Физика": "physics",
    "Физическая культура": "physical-education",
    "Французский язык": "french",
    "Химия": "chemistry",
    "Экономика": "economics",
    "Экология": "ecology",
    "Разные предметы": "other",
}


def stable_key(audience: str, title: str) -> str:
    normalized = " ".join(title.casefold().split())
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:20]
    return f"{audience}:{digest}"


def source_code(record: dict[str, object]) -> str:
    return "rsosh" if str(record.get("source", "")).startswith("РСОШ") else "ya-professional"


def campaign_year_for_record(record: dict[str, object]) -> int:
    """Keep catalogues from different academic years separate in PostgreSQL."""
    match = re.search(r"(20\d{2})\s*/\s*20\d{2}", str(record.get("source", "")))
    return int(match.group(1)) if match else 2025


def chunks(values: Iterable[dict[str, object]], size: int = 100) -> Iterable[list[dict[str, object]]]:
    batch: list[dict[str, object]] = []
    for value in values:
        batch.append(value)
        if len(batch) == size:
            yield batch
            batch = []
    if batch:
        yield batch


def load_records(conn: "psycopg.Connection", records: list[dict[str, object]]) -> int:
    """Upsert records and their subject relation; returns changed profile count."""
    changed = 0
    with conn.cursor() as cur:
        cur.execute("SELECT id, code FROM sources")
        sources = {code: source_id for source_id, code in cur.fetchall()}
        cur.execute("SELECT id, code FROM subjects")
        subjects = {code: subject_id for subject_id, code in cur.fetchall()}

        for batch in chunks(records):
            for record in batch:
                audience = str(record["audience"])
                title = str(record["title"])
                source = source_code(record)
                profile_title = str(record.get("profile") or "Общий зачёт")
                subject_codes = {
                    SUBJECT_CODES.get(str(subject), "other")
                    for subject in record.get("subjects", [record.get("subject")])
                }
                level_value = str(record.get("level") or "")
                level = int(level_value) if level_value in {"1", "2", "3"} else None
                status = "approved" if source == "rsosh" else "approved"
                campaign_year = campaign_year_for_record(record)

                cur.execute(
                    """
                    INSERT INTO olympiads (external_key, title, audience, kind, official_url)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (external_key) DO UPDATE SET
                      title = EXCLUDED.title,
                      audience = EXCLUDED.audience,
                      kind = EXCLUDED.kind,
                      official_url = EXCLUDED.official_url,
                      updated_at = now(),
                      is_active = TRUE
                    RETURNING id
                    """,
                    (stable_key(audience, title), title, audience, str(record["kind"]), str(record["source_url"])),
                )
                olympiad_id = cur.fetchone()[0]
                cur.execute(
                    """
                    INSERT INTO olympiad_profiles (
                      olympiad_id, source_id, campaign_year, profile_title, level,
                      approval_status, source_url, last_checked_at, is_active
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, TRUE)
                    ON CONFLICT (olympiad_id, campaign_year, profile_title) DO UPDATE SET
                      source_id = EXCLUDED.source_id,
                      level = EXCLUDED.level,
                      approval_status = EXCLUDED.approval_status,
                      source_url = EXCLUDED.source_url,
                      last_checked_at = EXCLUDED.last_checked_at,
                      is_active = TRUE
                    RETURNING id
                    """,
                    (
                        olympiad_id,
                        sources[source],
                        campaign_year,
                        profile_title,
                        level,
                        status,
                        str(record["source_url"]),
                        datetime.now(UTC),
                    ),
                )
                profile_id = cur.fetchone()[0]
                cur.execute("DELETE FROM olympiad_profile_subjects WHERE olympiad_profile_id = %s", (profile_id,))
                cur.executemany(
                    """
                    INSERT INTO olympiad_profile_subjects (olympiad_profile_id, subject_id)
                    VALUES (%s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    [(profile_id, subjects[subject_code]) for subject_code in subject_codes],
                )
                changed += 1
    return changed


def main() -> int:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("DATABASE_URL is required, for example postgresql://olimp:olimp@localhost:5432/olimp", file=sys.stderr)
        return 2
    if psycopg is None:
        print("Install dependencies first: python -m pip install -r requirements.txt", file=sys.stderr)
        return 2
    if not SNAPSHOT.exists():
        print(f"Snapshot not found: {SNAPSHOT}. Run parser/collect_olympiads.py first.", file=sys.stderr)
        return 2

    payload = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    records = list(payload.get("records", []))
    with psycopg.connect(database_url) as conn:
        changed = load_records(conn, records)
        conn.commit()
    print(f"Loaded {changed} olympiad profiles into PostgreSQL.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
