-- Olimp / PostgreSQL 15+
-- The database keeps data by admission campaign. Do not overwrite a prior year:
-- admission benefits depend on the university, programme, diploma status and year.

CREATE TABLE sources (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  base_url TEXT NOT NULL,
  source_kind TEXT NOT NULL CHECK (source_kind IN ('catalog', 'organizer', 'university_admissions')),
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE source_documents (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  source_id BIGINT NOT NULL REFERENCES sources(id),
  url TEXT NOT NULL,
  fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  content_sha256 CHAR(64),
  -- Raw HTML/PDF/XLSX lives in object storage. A parser must use this immutable
  -- copy, never re-fetch a changed page while a review is in progress.
  storage_key TEXT,
  content_type TEXT,
  content_size_bytes BIGINT CHECK (content_size_bytes >= 0),
  http_etag TEXT,
  source_last_modified_at TIMESTAMPTZ,
  title TEXT,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  UNIQUE (source_id, url, fetched_at)
);

CREATE TABLE import_runs (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  source_document_id BIGINT REFERENCES source_documents(id),
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at TIMESTAMPTZ,
  status TEXT NOT NULL CHECK (status IN ('running', 'succeeded', 'failed')),
  records_seen INTEGER NOT NULL DEFAULT 0 CHECK (records_seen >= 0),
  records_changed INTEGER NOT NULL DEFAULT 0 CHECK (records_changed >= 0),
  error_message TEXT
);

CREATE TABLE subjects (
  id SMALLINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL UNIQUE
);

CREATE TABLE olympiads (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  external_key TEXT NOT NULL UNIQUE,
  title TEXT NOT NULL,
  audience TEXT NOT NULL CHECK (audience IN ('school', 'student')),
  kind TEXT NOT NULL,
  organizer_name TEXT,
  official_url TEXT,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE olympiad_profiles (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  olympiad_id BIGINT NOT NULL REFERENCES olympiads(id) ON DELETE CASCADE,
  source_id BIGINT NOT NULL REFERENCES sources(id),
  import_run_id BIGINT REFERENCES import_runs(id),
  campaign_year SMALLINT NOT NULL CHECK (campaign_year BETWEEN 2020 AND 2100),
  profile_title TEXT NOT NULL,
  level SMALLINT CHECK (level BETWEEN 1 AND 3),
  approval_status TEXT NOT NULL CHECK (approval_status IN ('approved', 'draft', 'archived')),
  source_url TEXT NOT NULL,
  registration_opens_at TIMESTAMPTZ,
  registration_closes_at TIMESTAMPTZ,
  last_checked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  UNIQUE (olympiad_id, campaign_year, profile_title)
);

CREATE TABLE olympiad_profile_subjects (
  olympiad_profile_id BIGINT NOT NULL REFERENCES olympiad_profiles(id) ON DELETE CASCADE,
  subject_id SMALLINT NOT NULL REFERENCES subjects(id),
  PRIMARY KEY (olympiad_profile_id, subject_id)
);

CREATE TABLE olympiad_stages (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  olympiad_profile_id BIGINT NOT NULL REFERENCES olympiad_profiles(id) ON DELETE CASCADE,
  stage_kind TEXT NOT NULL CHECK (stage_kind IN ('registration', 'qualifying', 'final', 'results')),
  starts_at TIMESTAMPTZ,
  ends_at TIMESTAMPTZ,
  source_url TEXT NOT NULL,
  checked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (olympiad_profile_id, stage_kind)
);

CREATE TABLE universities (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL UNIQUE,
  city TEXT,
  official_url TEXT,
  is_active BOOLEAN NOT NULL DEFAULT TRUE
);

-- A university can have a head office, campuses, legal branches and an online
-- presence. A location gets its own admission status because rules from the
-- head office must never be silently copied to a branch.
CREATE TABLE university_locations (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  university_id BIGINT NOT NULL REFERENCES universities(id) ON DELETE CASCADE,
  code TEXT NOT NULL,
  name TEXT NOT NULL,
  location_type TEXT NOT NULL CHECK (location_type IN ('main', 'campus', 'branch', 'online')),
  city TEXT,
  region TEXT,
  country TEXT NOT NULL DEFAULT 'Россия',
  official_url TEXT NOT NULL,
  directory_url TEXT NOT NULL,
  location_checked_at TIMESTAMPTZ NOT NULL,
  admission_status TEXT NOT NULL DEFAULT 'candidate'
    CHECK (admission_status IN ('candidate', 'location_verified', 'rules_discovered', 'benefits_verified', 'archived')),
  admission_rules_url TEXT,
  admission_checked_at TIMESTAMPTZ,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  UNIQUE (university_id, code)
);

CREATE TABLE admission_campaigns (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  university_id BIGINT NOT NULL REFERENCES universities(id) ON DELETE CASCADE,
  campaign_year SMALLINT NOT NULL CHECK (campaign_year BETWEEN 2020 AND 2100),
  status TEXT NOT NULL CHECK (status IN ('draft', 'published', 'archived')),
  rules_url TEXT NOT NULL,
  rules_checked_at TIMESTAMPTZ NOT NULL,
  UNIQUE (university_id, campaign_year)
);

-- Official educational-programme catalogues are polled independently from
-- admission-benefit appendices.  A catalogue target is scoped to exactly one
-- campus or branch, so a programme found for a head office can never leak
-- into a branch just because both belong to the same university.
CREATE TABLE university_catalogue_targets (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  university_location_id BIGINT NOT NULL REFERENCES university_locations(id) ON DELETE CASCADE,
  source_id BIGINT NOT NULL REFERENCES sources(id),
  url TEXT NOT NULL,
  document_kind TEXT NOT NULL CHECK (document_kind IN ('html', 'pdf', 'xlsx', 'other')),
  adapter_code TEXT NOT NULL,
  adapter_config JSONB NOT NULL DEFAULT '{}'::jsonb,
  poll_interval_hours SMALLINT NOT NULL DEFAULT 24 CHECK (poll_interval_hours BETWEEN 1 AND 720),
  next_check_at TIMESTAMPTZ,
  last_checked_at TIMESTAMPTZ,
  last_successful_document_id BIGINT REFERENCES source_documents(id),
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (university_location_id, url)
);

-- Catalogue parses are kept separately from benefit parses: a catalogue can
-- update a programme name without creating or changing an admission benefit.
CREATE TABLE university_catalogue_parse_runs (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  university_catalogue_target_id BIGINT NOT NULL REFERENCES university_catalogue_targets(id) ON DELETE CASCADE,
  source_document_id BIGINT NOT NULL REFERENCES source_documents(id),
  adapter_code TEXT NOT NULL,
  adapter_version TEXT NOT NULL,
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at TIMESTAMPTZ,
  status TEXT NOT NULL CHECK (status IN ('running', 'succeeded', 'failed')),
  records_seen INTEGER NOT NULL DEFAULT 0 CHECK (records_seen >= 0),
  programmes_upserted INTEGER NOT NULL DEFAULT 0 CHECK (programmes_upserted >= 0),
  error_message TEXT,
  UNIQUE (university_catalogue_target_id, source_document_id, adapter_version)
);

-- A configured official page or document to check for one admission campaign.
-- Different universities publish rules in different places, so the adapter is
-- deliberately selected per target rather than inferred from arbitrary URLs.
CREATE TABLE admission_source_targets (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  admission_campaign_id BIGINT NOT NULL REFERENCES admission_campaigns(id) ON DELETE CASCADE,
  university_location_id BIGINT REFERENCES university_locations(id) ON DELETE SET NULL,
  source_id BIGINT NOT NULL REFERENCES sources(id),
  url TEXT NOT NULL,
  source_role TEXT NOT NULL CHECK (source_role IN ('campaign_rules', 'programme_rules', 'benefits_table')),
  document_kind TEXT NOT NULL CHECK (document_kind IN ('html', 'pdf', 'xlsx', 'other')),
  adapter_code TEXT NOT NULL,
  adapter_config JSONB NOT NULL DEFAULT '{}'::jsonb,
  poll_interval_hours SMALLINT NOT NULL DEFAULT 24 CHECK (poll_interval_hours BETWEEN 1 AND 720),
  next_check_at TIMESTAMPTZ,
  last_checked_at TIMESTAMPTZ,
  last_successful_document_id BIGINT REFERENCES source_documents(id),
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (admission_campaign_id, url)
);

-- The discovery worker periodically walks a small, allow-listed portion of
-- each university's official admissions site. It can attach a newly found
-- source to the generic candidate parser, but it cannot publish a benefit.
CREATE TABLE official_source_discovery_targets (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  admission_campaign_id BIGINT NOT NULL REFERENCES admission_campaigns(id) ON DELETE CASCADE,
  university_location_id BIGINT REFERENCES university_locations(id) ON DELETE SET NULL,
  source_id BIGINT NOT NULL REFERENCES sources(id),
  seed_url TEXT NOT NULL,
  adapter_config JSONB NOT NULL DEFAULT '{}'::jsonb,
  poll_interval_hours SMALLINT NOT NULL DEFAULT 24 CHECK (poll_interval_hours BETWEEN 1 AND 720),
  next_check_at TIMESTAMPTZ,
  last_checked_at TIMESTAMPTZ,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (admission_campaign_id, seed_url)
);

CREATE TABLE official_source_discovery_runs (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  official_source_discovery_target_id BIGINT NOT NULL REFERENCES official_source_discovery_targets(id) ON DELETE CASCADE,
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at TIMESTAMPTZ,
  status TEXT NOT NULL CHECK (status IN ('running', 'succeeded', 'failed')),
  pages_seen INTEGER NOT NULL DEFAULT 0 CHECK (pages_seen >= 0),
  candidates_found INTEGER NOT NULL DEFAULT 0 CHECK (candidates_found >= 0),
  targets_attached INTEGER NOT NULL DEFAULT 0 CHECK (targets_attached >= 0),
  error_message TEXT
);

CREATE TABLE official_source_discovery_candidates (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  official_source_discovery_run_id BIGINT NOT NULL REFERENCES official_source_discovery_runs(id) ON DELETE CASCADE,
  url TEXT NOT NULL,
  document_kind TEXT NOT NULL CHECK (document_kind IN ('html', 'pdf', 'xlsx', 'other')),
  title TEXT,
  source_excerpt TEXT,
  score SMALLINT NOT NULL CHECK (score BETWEEN 0 AND 100),
  signals JSONB NOT NULL DEFAULT '{}'::jsonb,
  status TEXT NOT NULL DEFAULT 'discovered'
    CHECK (status IN ('discovered', 'attached', 'already_tracked', 'ignored')),
  admission_source_target_id BIGINT REFERENCES admission_source_targets(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (official_source_discovery_run_id, url)
);

CREATE INDEX official_source_discovery_targets_due_idx
  ON official_source_discovery_targets (next_check_at)
  WHERE is_active;

CREATE INDEX official_source_discovery_candidates_run_idx
  ON official_source_discovery_candidates (official_source_discovery_run_id, score DESC);

-- One parser attempt against an immutable source document.
CREATE TABLE admission_parse_runs (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  admission_source_target_id BIGINT NOT NULL REFERENCES admission_source_targets(id) ON DELETE CASCADE,
  source_document_id BIGINT NOT NULL REFERENCES source_documents(id),
  adapter_code TEXT NOT NULL,
  adapter_version TEXT NOT NULL,
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at TIMESTAMPTZ,
  status TEXT NOT NULL CHECK (status IN ('running', 'succeeded', 'failed')),
  records_seen INTEGER NOT NULL DEFAULT 0 CHECK (records_seen >= 0),
  candidates_created INTEGER NOT NULL DEFAULT 0 CHECK (candidates_created >= 0),
  error_message TEXT,
  UNIQUE (admission_source_target_id, source_document_id, adapter_version)
);

CREATE TABLE university_programs (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  university_id BIGINT NOT NULL REFERENCES universities(id) ON DELETE CASCADE,
  university_location_id BIGINT REFERENCES university_locations(id) ON DELETE CASCADE,
  external_code TEXT,
  name TEXT NOT NULL,
  catalogue_status TEXT NOT NULL DEFAULT 'named_verified'
    CHECK (catalogue_status IN ('named_verified', 'code_only')),
  degree_level TEXT NOT NULL DEFAULT 'bachelor' CHECK (degree_level IN ('bachelor', 'specialist')),
  catalogue_source_target_id BIGINT REFERENCES university_catalogue_targets(id) ON DELETE SET NULL,
  catalogue_parse_run_id BIGINT REFERENCES university_catalogue_parse_runs(id) ON DELETE SET NULL,
  catalogue_source_url TEXT,
  catalogue_checked_at TIMESTAMPTZ,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  UNIQUE NULLS NOT DISTINCT (university_id, university_location_id, external_code, name)
);

CREATE TABLE admission_policies (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  admission_campaign_id BIGINT NOT NULL REFERENCES admission_campaigns(id) ON DELETE CASCADE,
  university_program_id BIGINT REFERENCES university_programs(id) ON DELETE CASCADE,
  policy_kind TEXT NOT NULL CHECK (policy_kind IN ('general', 'bvi', 'hundred_points', 'individual_achievement')),
  description TEXT NOT NULL,
  source_url TEXT NOT NULL,
  checked_at TIMESTAMPTZ NOT NULL,
  is_verified BOOLEAN NOT NULL DEFAULT FALSE,
  UNIQUE NULLS NOT DISTINCT (admission_campaign_id, university_program_id, policy_kind)
);

-- The row users actually need: a particular diploma for a particular programme
-- in a specific admission campaign.
CREATE TABLE benefit_rules (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  admission_campaign_id BIGINT NOT NULL REFERENCES admission_campaigns(id) ON DELETE CASCADE,
  university_program_id BIGINT REFERENCES university_programs(id) ON DELETE CASCADE,
  olympiad_profile_id BIGINT NOT NULL REFERENCES olympiad_profiles(id) ON DELETE CASCADE,
  diploma_status TEXT NOT NULL CHECK (diploma_status IN ('winner', 'prize_winner', 'finalist')),
  benefit_kind TEXT NOT NULL CHECK (benefit_kind IN ('bvi', 'hundred_points', 'individual_points')),
  point_value SMALLINT CHECK (point_value BETWEEN 1 AND 10),
  confirmation_subject_id SMALLINT REFERENCES subjects(id),
  confirmation_min_score SMALLINT CHECK (confirmation_min_score BETWEEN 0 AND 100),
  source_url TEXT NOT NULL,
  source_document_id BIGINT REFERENCES source_documents(id),
  admission_parse_run_id BIGINT REFERENCES admission_parse_runs(id),
  source_locator TEXT,
  source_excerpt TEXT,
  checked_at TIMESTAMPTZ NOT NULL,
  is_verified BOOLEAN NOT NULL DEFAULT FALSE,
  verification_status TEXT NOT NULL DEFAULT 'draft' CHECK (verification_status IN ('draft', 'needs_review', 'verified', 'rejected', 'superseded')),
  publication_method TEXT NOT NULL DEFAULT 'manual'
    CHECK (publication_method IN ('manual', 'strict_adapter')),
  verified_at TIMESTAMPTZ,
  verified_by TEXT,
  last_seen_at TIMESTAMPTZ,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  notes TEXT,
  CHECK (
    (benefit_kind = 'individual_points' AND point_value IS NOT NULL)
    OR (benefit_kind <> 'individual_points' AND point_value IS NULL)
  ),
  CHECK (is_verified = (verification_status = 'verified')),
  UNIQUE NULLS NOT DISTINCT (
    admission_campaign_id, university_program_id, olympiad_profile_id,
    diploma_status, benefit_kind
  )
);

-- A parser result is not a published benefit rule. It keeps the raw wording,
-- source position and inferred links until a reviewer resolves ambiguity.
CREATE TABLE admission_rule_candidates (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  admission_parse_run_id BIGINT NOT NULL REFERENCES admission_parse_runs(id) ON DELETE CASCADE,
  source_document_id BIGINT NOT NULL REFERENCES source_documents(id),
  admission_campaign_id BIGINT NOT NULL REFERENCES admission_campaigns(id) ON DELETE CASCADE,
  university_program_id BIGINT REFERENCES university_programs(id) ON DELETE SET NULL,
  olympiad_profile_id BIGINT REFERENCES olympiad_profiles(id) ON DELETE SET NULL,
  candidate_key TEXT NOT NULL,
  source_locator TEXT NOT NULL,
  source_excerpt TEXT NOT NULL,
  raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  raw_programme_name TEXT,
  raw_olympiad_name TEXT,
  raw_profile_name TEXT,
  raw_rule_text TEXT NOT NULL,
  suggested_olympiad_level SMALLINT CHECK (suggested_olympiad_level BETWEEN 1 AND 3),
  suggested_diploma_status TEXT CHECK (suggested_diploma_status IN ('winner', 'prize_winner', 'finalist')),
  suggested_benefit_kind TEXT CHECK (suggested_benefit_kind IN ('bvi', 'hundred_points', 'individual_points')),
  suggested_point_value SMALLINT CHECK (suggested_point_value BETWEEN 1 AND 10),
  suggested_confirmation_subject_id SMALLINT REFERENCES subjects(id),
  suggested_confirmation_min_score SMALLINT CHECK (suggested_confirmation_min_score BETWEEN 0 AND 100),
  match_status TEXT NOT NULL DEFAULT 'unresolved' CHECK (match_status IN ('unresolved', 'resolved', 'ambiguous')),
  review_status TEXT NOT NULL DEFAULT 'pending' CHECK (review_status IN ('pending', 'approved', 'rejected', 'superseded')),
  automatic_status TEXT NOT NULL DEFAULT 'not_applicable'
    CHECK (automatic_status IN ('not_applicable', 'pending_resolution', 'published', 'blocked')),
  automatic_note TEXT,
  confidence SMALLINT CHECK (confidence BETWEEN 0 AND 100),
  published_benefit_rule_id BIGINT REFERENCES benefit_rules(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  reviewed_at TIMESTAMPTZ,
  UNIQUE (admission_parse_run_id, candidate_key)
);

CREATE TABLE admission_rule_reviews (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  admission_rule_candidate_id BIGINT NOT NULL REFERENCES admission_rule_candidates(id) ON DELETE CASCADE,
  action TEXT NOT NULL CHECK (action IN ('approved', 'corrected', 'rejected', 'superseded')),
  reviewer_id TEXT NOT NULL,
  notes TEXT,
  resolved_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Keeps a trace of what the parser observed in every subsequent official
-- document, including a rule disappearing from a new version of the rules.
CREATE TABLE benefit_rule_observations (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  benefit_rule_id BIGINT NOT NULL REFERENCES benefit_rules(id) ON DELETE CASCADE,
  source_document_id BIGINT NOT NULL REFERENCES source_documents(id),
  admission_parse_run_id BIGINT REFERENCES admission_parse_runs(id),
  admission_rule_candidate_id BIGINT REFERENCES admission_rule_candidates(id) ON DELETE SET NULL,
  observed_status TEXT NOT NULL CHECK (observed_status IN ('present', 'changed', 'missing')),
  source_locator TEXT,
  source_excerpt TEXT,
  observed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (benefit_rule_id, source_document_id)
);

-- MAX identity is stored as an opaque external identifier, without profile data
-- the application does not need.
CREATE TABLE app_users (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  max_user_id TEXT NOT NULL UNIQUE,
  audience TEXT NOT NULL CHECK (audience IN ('school', 'student')),
  grade_or_course TEXT,
  default_diploma_year SMALLINT CHECK (default_diploma_year BETWEEN 2020 AND 2100),
  region TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE user_subjects (
  user_id BIGINT NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
  subject_id SMALLINT NOT NULL REFERENCES subjects(id),
  PRIMARY KEY (user_id, subject_id)
);

CREATE TABLE tracked_olympiads (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id BIGINT NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
  olympiad_profile_id BIGINT NOT NULL REFERENCES olympiad_profiles(id) ON DELETE CASCADE,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  diploma_year SMALLINT CHECK (diploma_year BETWEEN 2020 AND 2100),
  added_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_notified_at TIMESTAMPTZ,
  UNIQUE (user_id, olympiad_profile_id)
);

CREATE TABLE notification_jobs (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  tracked_olympiad_id BIGINT NOT NULL REFERENCES tracked_olympiads(id) ON DELETE CASCADE,
  notification_kind TEXT NOT NULL CHECK (notification_kind IN ('registration_open', 'deadline_7d', 'deadline_3d', 'deadline_1d', 'stage_start')),
  scheduled_for TIMESTAMPTZ NOT NULL,
  sent_at TIMESTAMPTZ,
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  UNIQUE (tracked_olympiad_id, notification_kind, scheduled_for)
);

CREATE INDEX olympiad_profiles_discovery_idx
  ON olympiad_profiles (campaign_year, approval_status, level, is_active);
CREATE INDEX source_documents_content_sha_idx
  ON source_documents (content_sha256) WHERE content_sha256 IS NOT NULL;
CREATE INDEX olympiad_profile_subjects_subject_idx
  ON olympiad_profile_subjects (subject_id, olympiad_profile_id);
CREATE INDEX benefit_rules_lookup_idx
  ON benefit_rules (admission_campaign_id, university_program_id, olympiad_profile_id, verification_status, is_active);
CREATE INDEX admission_source_targets_due_idx
  ON admission_source_targets (next_check_at) WHERE is_active;
CREATE INDEX admission_parse_runs_target_idx
  ON admission_parse_runs (admission_source_target_id, started_at DESC);
CREATE INDEX admission_rule_candidates_review_idx
  ON admission_rule_candidates (review_status, admission_campaign_id, created_at) WHERE review_status = 'pending';
CREATE INDEX benefit_rule_observations_rule_idx
  ON benefit_rule_observations (benefit_rule_id, observed_at DESC);
CREATE INDEX tracked_olympiads_user_idx
  ON tracked_olympiads (user_id, is_active);
CREATE INDEX notification_jobs_due_idx
  ON notification_jobs (scheduled_for) WHERE sent_at IS NULL;

CREATE VIEW v_benefit_catalog AS
SELECT
  campaign.campaign_year,
  university.name AS university_name,
  program.name AS program_name,
  olympiad.title AS olympiad_title,
  profile.profile_title,
  profile.level,
  subject.name AS subject_name,
  rule.diploma_status,
  rule.benefit_kind,
  rule.point_value,
  confirmation.name AS confirmation_subject_name,
  rule.confirmation_min_score,
  rule.is_verified,
  rule.verification_status,
  rule.source_url,
  rule.source_locator,
  rule.checked_at
FROM benefit_rules rule
JOIN admission_campaigns campaign ON campaign.id = rule.admission_campaign_id
JOIN universities university ON university.id = campaign.university_id
LEFT JOIN university_programs program ON program.id = rule.university_program_id
JOIN olympiad_profiles profile ON profile.id = rule.olympiad_profile_id
JOIN olympiads olympiad ON olympiad.id = profile.olympiad_id
LEFT JOIN olympiad_profile_subjects profile_subject ON profile_subject.olympiad_profile_id = profile.id
LEFT JOIN subjects subject ON subject.id = profile_subject.subject_id
LEFT JOIN subjects confirmation ON confirmation.id = rule.confirmation_subject_id
WHERE rule.is_active
  AND rule.verification_status = 'verified';
