-- Keep official programme catalogues separate from admission-benefit sources.
-- A programme is only attached to the campus/branch whose catalogue target
-- emitted it; this is the guardrail against copying a head-campus catalogue
-- to a branch.

CREATE TABLE IF NOT EXISTS university_catalogue_targets (
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

CREATE TABLE IF NOT EXISTS university_catalogue_parse_runs (
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

ALTER TABLE university_programs
  ADD COLUMN IF NOT EXISTS catalogue_source_target_id BIGINT REFERENCES university_catalogue_targets(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS catalogue_parse_run_id BIGINT REFERENCES university_catalogue_parse_runs(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS catalogue_source_url TEXT,
  ADD COLUMN IF NOT EXISTS catalogue_checked_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS university_catalogue_targets_due_idx
  ON university_catalogue_targets (next_check_at, is_active);

CREATE INDEX IF NOT EXISTS university_programs_catalogue_location_idx
  ON university_programs (university_location_id, catalogue_status, is_active);
