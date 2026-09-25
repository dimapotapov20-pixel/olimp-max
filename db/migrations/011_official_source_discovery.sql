-- An official site can move a rules appendix, rename a section, or replace an
-- HTML page with a PDF. Discovery is deliberately separate from parsing:
-- it finds candidate official documents but never publishes a benefit.

CREATE TABLE IF NOT EXISTS official_source_discovery_targets (
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

CREATE TABLE IF NOT EXISTS official_source_discovery_runs (
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

CREATE TABLE IF NOT EXISTS official_source_discovery_candidates (
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

CREATE INDEX IF NOT EXISTS official_source_discovery_targets_due_idx
  ON official_source_discovery_targets (next_check_at)
  WHERE is_active;

CREATE INDEX IF NOT EXISTS official_source_discovery_candidates_run_idx
  ON official_source_discovery_candidates (official_source_discovery_run_id, score DESC);
