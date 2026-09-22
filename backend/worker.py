"""Deliver due Olimp reminders through the MAX bot API.

This process is intended to run every minute through a scheduler. A job is
marked sent only after MAX returns success, so a transient network failure can
be retried safely.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
import psycopg
from psycopg.rows import dict_row


API_URL = "https://platform-api2.max.ru/messages"


def send_reminders() -> int:
    database_url = os.environ["DATABASE_URL"]
    bot_token = os.environ["MAX_BOT_TOKEN"]
    sent = 0
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT job.id, user.max_user_id, olympiad.title, profile.profile_title,
                       job.notification_kind, job.payload
                FROM notification_jobs job
                JOIN tracked_olympiads tracked ON tracked.id = job.tracked_olympiad_id
                JOIN app_users user ON user.id = tracked.user_id
                JOIN olympiad_profiles profile ON profile.id = tracked.olympiad_profile_id
                JOIN olympiads olympiad ON olympiad.id = profile.olympiad_id
                WHERE job.sent_at IS NULL
                  AND job.scheduled_for <= now()
                  AND tracked.is_active
                ORDER BY job.scheduled_for
                FOR UPDATE SKIP LOCKED
                LIMIT 20
                """
            )
            jobs: list[dict[str, Any]] = cursor.fetchall()
            for job in jobs:
                text = f"Олимп: {job['title']} — {job['profile_title']}. Проверь срок и статус регистрации."
                response = httpx.post(
                    API_URL,
                    params={"user_id": job["max_user_id"]},
                    headers={"Authorization": bot_token},
                    json={"text": text, "notify": True},
                    timeout=15,
                )
                response.raise_for_status()
                cursor.execute("UPDATE notification_jobs SET sent_at = now() WHERE id = %s", (job["id"],))
                sent += 1
        connection.commit()
    return sent


if __name__ == "__main__":
    print(f"Sent {send_reminders()} reminder(s).")
