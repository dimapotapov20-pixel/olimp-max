# Olimp: MAX mini app, bot and PostgreSQL

## The principle

MAX mini apps are attached to a bot. For Olimp, the bot is the entry point and
notification channel; the mini app is the catalogue and planning interface.
They never copy data into each other. Both talk to one backend, whose source of
truth is PostgreSQL.

```text
                         public sources
                  РСОШ, organisers, university rules
                                   |
                                   v
                         parser + import worker
                                   |
                                   v
@olimp_bot  <---->  API / background worker  <---->  PostgreSQL
     ^                       ^                         |
     |                       |                         |
     +---- MAX messages -----+----- MAX initData -------+
                                     |
                               Olimp mini app
```

## User flow

1. The user opens `https://max.ru/<bot-name>?startapp=track_<opaque-id>` or
   presses the mini-app button in `@olimp_bot`.
2. MAX opens the HTTPS mini-app URL configured in that bot and exposes
   `window.WebApp.initData`.
3. The mini app sends that **raw** string in `X-MAX-Init-Data` to
   `POST /api/auth/max`. The backend validates its HMAC signature using the
   bot token, checks `auth_date`, then upserts `app_users.max_user_id`.
4. The mini app reads subjects, school/student profile, olympiad cards,
   university benefits and tracking status from the API. The API reads
   PostgreSQL.
5. A tap on “Отслеживать” writes `tracked_olympiads`; a scheduler creates
   `notification_jobs` from the registration and stage dates.
6. `backend/worker.py` sends due jobs with the MAX Bot API `POST /messages`.
   The bot can include a link that returns the user to a specific screen in the
   mini app.

`startapp` is only navigation context. It must be a short opaque identifier,
not a MAX user ID, access token or university choice that needs protection.

The university screen uses `GET /api/universities?q=<name-or-city>` for search
and `GET /api/universities/{code}/benefits` for the details. The latter returns
general policies separately from exact `benefits`; exact rules are filtered to
the verified, active rows only.

The mini-app catalogue itself is loaded from the read-only
`GET /api/university-locations` endpoint. It reads PostgreSQL directly and is
available before MAX authentication because it exposes only public university
and source metadata. `dist/data/universities.json` is no longer a frontend
source; it is the verified import snapshot consumed by the daily loader.

## What is authoritative

| Data | Owner | Why |
| --- | --- | --- |
| User subject selection and tracked olympiads | PostgreSQL | Available to the mini app and reminders in one place |
| Olympiad profiles, levels and dates | Parser imports + source documents | Every record carries a source and the import is auditable |
| University admission benefits | `benefit_rules` per programme and campaign | A general university page is not enough to infer an exact benefit |
| Bot token | Deployment secret only | It must never reach browser JavaScript or the database export |

## Local database bootstrap

PostgreSQL 15 or newer is required because the schema uses `UNIQUE NULLS NOT
DISTINCT` for programme-specific benefit rules. The included Compose setup
uses PostgreSQL 16 and applies `schema.sql` and `seed.sql` automatically on
the first launch of an empty database volume:

```bash
cp .env.example .env
docker compose up --build
```

The mini app and API are then available at `http://127.0.0.1:8000`; PostgreSQL
is exposed at `127.0.0.1:5432` for the local parser. In a second terminal,
after the containers become healthy:

```bash
python -m pip install -r requirements.txt
python parser/collect_olympiads.py
python parser/load_postgres.py
```

The `admission-crawler` container runs a full refresh once a day: it reloads
the verified location catalogue, then checks due university admission targets.
Its default pause is `CATALOG_REFRESH_SECONDS=86400`; each target also keeps
its own `poll_interval_hours` (24 hours by default). This prevents repeated
downloads while preserving a predictable daily schedule. It stores raw
snapshots in the `olimp-admission-snapshots` volume and writes only review
candidates to PostgreSQL. If a source is unavailable, the previous verified
catalogue and benefits stay published; the failure is logged and retried on
the next daily run.

For an existing database, apply `db/migrations/002_admission_rules_pipeline.sql`
once before deploying the version that reads verified benefit rules. The
initialisation files are intentionally not re-run against an existing Compose
volume.

Set `DATABASE_URL` and `MAX_BOT_TOKEN` from `.env.example` in your deployment
environment. Do not put a real bot token in `.env.example`, Git or frontend
files.

## Before connecting a live bot

- Create the bot and bind its mini-app URL in MAX. The mini app must be served
  through HTTPS, not `127.0.0.1`.
- Configure the same backend URL for the bot’s event delivery mechanism and
  save its token only in deployment secrets.
- Import a dated source document every time the catalogue changes; retain old
  campaigns rather than overwriting benefits.
- Add university adapters one by one. A rule should become visible as an exact
  match only after the programme, olympiad profile, diploma status, source URL
  and check date are stored in `benefit_rules`.
