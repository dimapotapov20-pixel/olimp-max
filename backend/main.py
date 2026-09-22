"""One backend for the MAX bot and the Olimp mini app.

Run behind HTTPS in production. The mini app, database and bot API should use
the same deployment, so tracking state is never copied between systems.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import psycopg
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from psycopg.rows import dict_row

from backend.max_auth import MaxInitDataError, MaxUser, verify_init_data


ROOT = Path(__file__).resolve().parents[1]
DATABASE_URL = os.environ.get("DATABASE_URL", "")
BOT_TOKEN = os.environ.get("MAX_BOT_TOKEN", "")

app = FastAPI(title="Olimp MAX backend")


def database():
    if not DATABASE_URL:
        raise HTTPException(status_code=503, detail="Database is not configured")
    connection = psycopg.connect(DATABASE_URL, row_factory=dict_row)
    try:
        yield connection
    finally:
        connection.close()


def current_user(
    init_data: str = Header(alias="X-MAX-Init-Data"),
    connection: psycopg.Connection = Depends(database),
) -> dict:
    if not BOT_TOKEN:
        raise HTTPException(status_code=503, detail="MAX bot is not configured")
    try:
        max_user = verify_init_data(init_data, BOT_TOKEN)
    except MaxInitDataError as error:
        raise HTTPException(status_code=401, detail="Invalid MAX launch data") from error
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO app_users (max_user_id, audience)
            VALUES (%s, 'school')
            ON CONFLICT (max_user_id) DO UPDATE SET updated_at = now()
            RETURNING id, max_user_id, audience, grade_or_course, region
            """,
            (max_user.user_id,),
        )
        user = cursor.fetchone()
    connection.commit()
    return user


@app.get("/api/health")
def health(connection: psycopg.Connection = Depends(database)) -> dict:
    """A deployment check that never exposes configuration or user data."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1 AS ok")
        cursor.fetchone()
    return {"status": "ok", "database": "connected"}


class UserSetup(BaseModel):
    audience: Literal["school", "student"]
    grade_or_course: str | None = Field(default=None, max_length=40)
    subject_codes: list[str] = Field(default_factory=list, max_length=12)


class TrackRequest(BaseModel):
    olympiad_profile_id: int
    is_active: bool = True


@app.get("/api/university-locations")
def search_university_locations(
    q: str = "",
    region: str | None = None,
    location_type: Literal["main", "campus", "branch", "online"] | None = None,
    campaign_year: int = 2026,
    connection: psycopg.Connection = Depends(database),
) -> dict:
    """Return the public catalogue of locations from PostgreSQL.

    This read-only endpoint contains no user data, so the mini app can draw the
    catalogue before a MAX session is established. Personal endpoints remain
    authenticated through the signed MAX launch data.
    """
    query = " ".join(q.split())
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
              university.code AS university_code,
              university.name AS university_name,
              location.code AS location_code,
              location.name AS location_name,
              location.location_type,
              location.city,
              location.region,
              location.country,
              location.official_url,
              location.directory_url,
              location.admission_status,
              location.location_checked_at,
              location.admission_checked_at,
              campaign.rules_url AS campaign_rules_url,
              policy.description AS verified_policy_description,
              policy.source_url AS verified_policy_source_url,
              count(rule.id) FILTER (
                WHERE rule.is_active
                  AND rule.verification_status = 'verified'
              ) AS verified_benefits_count
            FROM university_locations location
            JOIN universities university ON university.id = location.university_id
            LEFT JOIN admission_campaigns campaign
              ON campaign.university_id = university.id
             AND campaign.campaign_year = %s
            LEFT JOIN LATERAL (
              SELECT admission_policy.description, admission_policy.source_url
              FROM admission_policies admission_policy
              WHERE admission_policy.admission_campaign_id = campaign.id
                AND admission_policy.university_program_id IS NULL
                AND admission_policy.is_verified
              ORDER BY admission_policy.policy_kind = 'general' DESC,
                       admission_policy.checked_at DESC
              LIMIT 1
            ) policy ON TRUE
            LEFT JOIN university_programs program
              ON program.university_location_id = location.id AND program.is_active
            LEFT JOIN benefit_rules rule
              ON rule.university_program_id = program.id
             AND rule.admission_campaign_id = campaign.id
            WHERE location.is_active
              AND university.is_active
              AND (%s = '' OR concat_ws(' ', university.name, location.name, location.city, location.region, location.country) ILIKE '%%' || %s || '%%')
              AND (%s::text IS NULL OR location.region = %s::text)
              AND (%s::text IS NULL OR location.location_type = %s::text)
            GROUP BY university.id, location.id, campaign.id, policy.description, policy.source_url
            ORDER BY university.name, location.location_type = 'main' DESC, location.name
            LIMIT 200
            """,
            (campaign_year, query, query, region, region, location_type, location_type),
        )
        locations = cursor.fetchall()
    return {"items": locations}


@app.post("/api/auth/max")
def authenticate_in_max(user: dict = Depends(current_user)) -> dict:
    """Creates/updates the local user only after the MAX signature is checked."""
    return {"user": user}


@app.put("/api/me/setup")
def update_setup(
    payload: UserSetup,
    user: dict = Depends(current_user),
    connection: psycopg.Connection = Depends(database),
) -> dict:
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE app_users SET audience = %s, grade_or_course = %s, updated_at = now() WHERE id = %s",
            (payload.audience, payload.grade_or_course, user["id"]),
        )
        cursor.execute("DELETE FROM user_subjects WHERE user_id = %s", (user["id"],))
        cursor.execute(
            """
            INSERT INTO user_subjects (user_id, subject_id)
            SELECT %s, id FROM subjects WHERE code = ANY(%s)
            ON CONFLICT DO NOTHING
            """,
            (user["id"], payload.subject_codes),
        )
    connection.commit()
    return {"ok": True}


@app.get("/api/discovery")
def discover(
    campaign_year: int = 2025,
    audience: Literal["school", "student"] = "school",
    subject: list[str] | None = None,
    user: dict = Depends(current_user),
    connection: psycopg.Connection = Depends(database),
) -> dict:
    subject_codes = subject or []
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT profile.id, olympiad.title, olympiad.kind, profile.profile_title,
                   profile.level, profile.source_url,
                   array_agg(DISTINCT subjects.code) AS subject_codes,
                   array_agg(DISTINCT subjects.name) AS subject_names,
                   EXISTS (
                     SELECT 1 FROM tracked_olympiads tracked
                     WHERE tracked.user_id = %s
                       AND tracked.olympiad_profile_id = profile.id
                       AND tracked.is_active
                   ) AS is_tracked
            FROM olympiad_profiles profile
            JOIN olympiads olympiad ON olympiad.id = profile.olympiad_id
            LEFT JOIN olympiad_profile_subjects relation ON relation.olympiad_profile_id = profile.id
            LEFT JOIN subjects ON subjects.id = relation.subject_id
            WHERE profile.campaign_year = %s
              AND profile.approval_status = 'approved'
              AND profile.is_active
              AND olympiad.audience = %s
              AND (
                cardinality(%s::text[]) = 0 OR EXISTS (
                  SELECT 1
                  FROM olympiad_profile_subjects wanted_relation
                  JOIN subjects wanted_subject ON wanted_subject.id = wanted_relation.subject_id
                  WHERE wanted_relation.olympiad_profile_id = profile.id
                    AND wanted_subject.code = ANY(%s)
                )
              )
            GROUP BY profile.id, olympiad.id
            ORDER BY profile.level NULLS LAST, olympiad.title
            """,
            (user["id"], campaign_year, audience, subject_codes, subject_codes),
        )
        rows = cursor.fetchall()
    return {"items": rows}


@app.post("/api/me/tracked")
def set_tracking(
    payload: TrackRequest,
    user: dict = Depends(current_user),
    connection: psycopg.Connection = Depends(database),
) -> dict:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO tracked_olympiads (user_id, olympiad_profile_id, is_active)
            VALUES (%s, %s, %s)
            ON CONFLICT (user_id, olympiad_profile_id)
            DO UPDATE SET is_active = EXCLUDED.is_active
            RETURNING id, is_active
            """,
            (user["id"], payload.olympiad_profile_id, payload.is_active),
        )
        tracked = cursor.fetchone()
    connection.commit()
    return {"tracked": tracked}


@app.get("/api/universities/{university_code}/benefits")
def university_benefits(
    university_code: str,
    campaign_year: int = 2026,
    user: dict = Depends(current_user),
    connection: psycopg.Connection = Depends(database),
) -> dict:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT university.name AS university_name, campaign.rules_url,
                   policy.policy_kind, policy.description, policy.is_verified,
                   policy.checked_at
            FROM admission_campaigns campaign
            JOIN universities university ON university.id = campaign.university_id
            JOIN admission_policies policy ON policy.admission_campaign_id = campaign.id
            WHERE university.code = %s AND campaign.campaign_year = %s
            ORDER BY policy.university_program_id NULLS FIRST, policy.policy_kind
            """,
            (university_code, campaign_year),
        )
        policies = cursor.fetchall()
        cursor.execute(
            """
            SELECT
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
              rule.checked_at
            FROM benefit_rules rule
            JOIN admission_campaigns campaign ON campaign.id = rule.admission_campaign_id
            JOIN universities university ON university.id = campaign.university_id
            LEFT JOIN university_programs program ON program.id = rule.university_program_id
            LEFT JOIN university_locations location ON location.id = program.university_location_id
            JOIN olympiad_profiles profile ON profile.id = rule.olympiad_profile_id
            JOIN olympiads olympiad ON olympiad.id = profile.olympiad_id
            LEFT JOIN subjects confirmation ON confirmation.id = rule.confirmation_subject_id
            WHERE university.code = %s
              AND campaign.campaign_year = %s
              AND rule.is_active
              AND rule.verification_status = 'verified'
            ORDER BY program.name NULLS FIRST, olympiad.title, profile.profile_title, rule.diploma_status
            """,
            (university_code, campaign_year),
        )
        benefits = cursor.fetchall()
    return {"policies": policies, "benefits": benefits}


@app.get("/api/universities")
def search_universities(
    q: str = "",
    campaign_year: int = 2026,
    user: dict = Depends(current_user),
    connection: psycopg.Connection = Depends(database),
) -> dict:
    """Find universities with rules for the selected admission campaign."""
    query = " ".join(q.split())
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
              university.code,
              university.name,
              university.city,
              university.official_url,
              campaign.rules_url,
              campaign.rules_checked_at,
              count(rule.id) FILTER (
                WHERE rule.is_active AND rule.verification_status = 'verified'
              ) AS verified_benefits_count
            FROM admission_campaigns campaign
            JOIN universities university ON university.id = campaign.university_id
            LEFT JOIN benefit_rules rule ON rule.admission_campaign_id = campaign.id
            WHERE campaign.campaign_year = %s
              AND university.is_active
              AND (
                %s = ''
                OR university.name ILIKE '%%' || %s || '%%'
                OR COALESCE(university.city, '') ILIKE '%%' || %s || '%%'
              )
            GROUP BY campaign.id, university.id
            ORDER BY verified_benefits_count DESC, university.name
            LIMIT 50
            """,
            (campaign_year, query, query, query),
        )
        universities = cursor.fetchall()
    return {"items": universities}


app.mount("/", StaticFiles(directory=ROOT / "dist", html=True), name="miniapp")
