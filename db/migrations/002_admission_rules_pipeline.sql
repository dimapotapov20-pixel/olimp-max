-- Admission-rules parser pipeline.
-- Apply after the original Olimp schema, before application code starts
-- reading the extended v_benefit_catalog view.

ALTER TABLE source_documents
  ADD COLUMN IF NOT EXISTS storage_key TEXT,
  ADD COLUMN IF NOT EXISTS content_type TEXT,
  ADD COLUMN IF NOT EXISTS content_size_bytes BIGINT CHECK (content_size_bytes >= 0),
  ADD COLUMN IF NOT EXISTS http_etag TEXT,
  ADD COLUMN IF NOT EXISTS source_last_modified_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS admission_source_targets (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  admission_campaign_id BIGINT NOT NULL REFERENCES admission_campaigns(id) ON DELETE CASCADE,
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

CREATE TABLE IF NOT EXISTS admission_parse_runs (
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

ALTER TABLE benefit_rules
  ADD COLUMN IF NOT EXISTS source_document_id BIGINT REFERENCES source_documents(id),
  ADD COLUMN IF NOT EXISTS source_locator TEXT,
  ADD COLUMN IF NOT EXISTS source_excerpt TEXT,
  ADD COLUMN IF NOT EXISTS verification_status TEXT,
  ADD COLUMN IF NOT EXISTS verified_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS verified_by TEXT,
  ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE;

ALTER TABLE benefit_rules
  ADD COLUMN IF NOT EXISTS admission_parse_run_id BIGINT REFERENCES admission_parse_runs(id);

UPDATE benefit_rules
SET verification_status = CASE WHEN is_verified THEN 'verified' ELSE 'draft' END
WHERE verification_status IS NULL;

UPDATE benefit_rules
SET last_seen_at = checked_at
WHERE last_seen_at IS NULL;

ALTER TABLE benefit_rules
  ALTER COLUMN verification_status SET DEFAULT 'draft',
  ALTER COLUMN verification_status SET NOT NULL;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'benefit_rules_verification_status_check'
  ) THEN
    ALTER TABLE benefit_rules
      ADD CONSTRAINT benefit_rules_verification_status_check
      CHECK (verification_status IN ('draft', 'needs_review', 'verified', 'rejected', 'superseded'));
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'benefit_rules_verification_sync_check'
  ) THEN
    ALTER TABLE benefit_rules
      ADD CONSTRAINT benefit_rules_verification_sync_check
      CHECK (is_verified = (verification_status = 'verified'));
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS admission_rule_candidates (
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
  suggested_diploma_status TEXT CHECK (suggested_diploma_status IN ('winner', 'prize_winner', 'finalist')),
  suggested_benefit_kind TEXT CHECK (suggested_benefit_kind IN ('bvi', 'hundred_points', 'individual_points')),
  suggested_point_value SMALLINT CHECK (suggested_point_value BETWEEN 1 AND 10),
  suggested_confirmation_subject_id SMALLINT REFERENCES subjects(id),
  suggested_confirmation_min_score SMALLINT CHECK (suggested_confirmation_min_score BETWEEN 0 AND 100),
  match_status TEXT NOT NULL DEFAULT 'unresolved' CHECK (match_status IN ('unresolved', 'resolved', 'ambiguous')),
  review_status TEXT NOT NULL DEFAULT 'pending' CHECK (review_status IN ('pending', 'approved', 'rejected', 'superseded')),
  confidence SMALLINT CHECK (confidence BETWEEN 0 AND 100),
  published_benefit_rule_id BIGINT REFERENCES benefit_rules(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  reviewed_at TIMESTAMPTZ,
  UNIQUE (admission_parse_run_id, candidate_key)
);

ALTER TABLE admission_rule_candidates
  ADD COLUMN IF NOT EXISTS suggested_olympiad_level SMALLINT
    CHECK (suggested_olympiad_level BETWEEN 1 AND 3);

CREATE TABLE IF NOT EXISTS admission_rule_reviews (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  admission_rule_candidate_id BIGINT NOT NULL REFERENCES admission_rule_candidates(id) ON DELETE CASCADE,
  action TEXT NOT NULL CHECK (action IN ('approved', 'corrected', 'rejected', 'superseded')),
  reviewer_id TEXT NOT NULL,
  notes TEXT,
  resolved_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS benefit_rule_observations (
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

CREATE INDEX IF NOT EXISTS admission_source_targets_due_idx
  ON admission_source_targets (next_check_at) WHERE is_active;
CREATE INDEX IF NOT EXISTS source_documents_content_sha_idx
  ON source_documents (content_sha256) WHERE content_sha256 IS NOT NULL;
CREATE INDEX IF NOT EXISTS admission_parse_runs_target_idx
  ON admission_parse_runs (admission_source_target_id, started_at DESC);
CREATE INDEX IF NOT EXISTS benefit_rules_lookup_idx
  ON benefit_rules (admission_campaign_id, university_program_id, olympiad_profile_id, verification_status, is_active);
CREATE INDEX IF NOT EXISTS admission_rule_candidates_review_idx
  ON admission_rule_candidates (review_status, admission_campaign_id, created_at) WHERE review_status = 'pending';
CREATE INDEX IF NOT EXISTS benefit_rule_observations_rule_idx
  ON benefit_rule_observations (benefit_rule_id, observed_at DESC);

-- The previous view has a smaller column set; drop it so the new provenance
-- columns can be added without PostgreSQL's CREATE OR REPLACE restrictions.
DROP VIEW IF EXISTS v_benefit_catalog;

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
