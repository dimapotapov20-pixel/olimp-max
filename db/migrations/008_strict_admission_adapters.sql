-- Strict admission adapters can publish only a fully linked programme-level
-- rule.  Keep the publication method visible: it distinguishes a row parsed
-- from a checked official table from a manually verified correction.

ALTER TABLE benefit_rules
  ADD COLUMN IF NOT EXISTS publication_method TEXT NOT NULL DEFAULT 'manual';

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'benefit_rules_publication_method_check'
  ) THEN
    ALTER TABLE benefit_rules
      ADD CONSTRAINT benefit_rules_publication_method_check
      CHECK (publication_method IN ('manual', 'strict_adapter'));
  END IF;
END $$;

ALTER TABLE admission_rule_candidates
  ADD COLUMN IF NOT EXISTS automatic_status TEXT NOT NULL DEFAULT 'not_applicable',
  ADD COLUMN IF NOT EXISTS automatic_note TEXT;

ALTER TABLE university_programs
  ADD COLUMN IF NOT EXISTS catalogue_status TEXT NOT NULL DEFAULT 'named_verified';

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'university_programs_catalogue_status_check'
  ) THEN
    ALTER TABLE university_programs
      ADD CONSTRAINT university_programs_catalogue_status_check
      CHECK (catalogue_status IN ('named_verified', 'code_only'));
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'admission_rule_candidates_automatic_status_check'
  ) THEN
    ALTER TABLE admission_rule_candidates
      ADD CONSTRAINT admission_rule_candidates_automatic_status_check
      CHECK (automatic_status IN ('not_applicable', 'pending_resolution', 'published', 'blocked'));
  END IF;
END $$;

-- The old physics-olympiad landing page is not the 2026 admission document.
-- Keep its prior snapshots, but do not treat it as an active benefits target.
UPDATE admission_source_targets target
SET is_active = FALSE,
    updated_at = now()
FROM sources source
WHERE target.source_id = source.id
  AND source.code = 'bmstu-admission'
  AND target.url NOT IN (
    'https://api.www.bmstu.ru/file/124777/download',
    'https://api.www.bmstu.ru/file/122150/download'
  );

-- Bind each official national/main-campus document to the campus it actually
-- describes. A head-office rule must never spill over to a branch.
UPDATE admission_source_targets target
SET university_location_id = location.id,
    adapter_code = CASE source.code
      WHEN 'hse-admission' THEN 'strict-hse-2026-v1'
      WHEN 'mipt-admission' THEN 'strict-mipt-2026-v1'
      WHEN 'mephi-admission' THEN 'strict-mephi-2026-v1'
      WHEN 'msu-admission' THEN 'strict-msu-2026-v1'
      WHEN 'bmstu-admission' THEN 'strict-bmstu-2026-v1'
      ELSE target.adapter_code
    END,
    adapter_config = target.adapter_config || jsonb_build_object(
      'strict_adapter', CASE source.code
        WHEN 'hse-admission' THEN 'strict-hse-2026-v1'
        WHEN 'mipt-admission' THEN 'strict-mipt-2026-v1'
        WHEN 'mephi-admission' THEN 'strict-mephi-2026-v1'
        WHEN 'msu-admission' THEN 'strict-msu-2026-v1'
        WHEN 'bmstu-admission' THEN 'strict-bmstu-2026-v1'
      END,
      'rsosh_catalogue_year', 2025
    ),
    next_check_at = now(),
    updated_at = now()
FROM sources source,
     admission_campaigns campaign,
     universities university,
     university_locations location
WHERE target.source_id = source.id
  AND campaign.id = target.admission_campaign_id
  AND university.id = campaign.university_id
  AND location.university_id = university.id
  AND location.code = CASE university.code
   WHEN 'hse' THEN 'hse-moscow'
   WHEN 'mipt' THEN 'mipt-dolgoprudny'
   WHEN 'mephi' THEN 'mephi-moscow'
   WHEN 'msu' THEN 'msu-moscow'
   WHEN 'bmstu' THEN 'bmstu-moscow'
 END
  AND campaign.campaign_year = 2026
  AND source.code IN ('hse-admission', 'mipt-admission', 'mephi-admission', 'msu-admission', 'bmstu-admission');
