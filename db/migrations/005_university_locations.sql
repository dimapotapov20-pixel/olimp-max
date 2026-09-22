-- Add a real location layer to the admissions catalogue. Existing campaigns
-- remain university-wide; new sources and programmes can be tied to a campus
-- or branch as their official documents are discovered.

CREATE TABLE IF NOT EXISTS university_locations (
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

ALTER TABLE university_programs
  ADD COLUMN IF NOT EXISTS university_location_id BIGINT REFERENCES university_locations(id) ON DELETE CASCADE;

ALTER TABLE university_programs
  DROP CONSTRAINT IF EXISTS university_programs_university_id_external_code_name_key;

CREATE UNIQUE INDEX IF NOT EXISTS university_programs_location_identity_idx
  ON university_programs (university_id, university_location_id, external_code, name) NULLS NOT DISTINCT;

ALTER TABLE admission_source_targets
  ADD COLUMN IF NOT EXISTS university_location_id BIGINT REFERENCES university_locations(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS university_locations_lookup_idx
  ON university_locations (university_id, location_type, region, is_active);
