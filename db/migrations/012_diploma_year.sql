-- The calendar year shown on the diploma is separate from the admission
-- campaign. For example, a 2022 diploma reaches its final general eligibility
-- year in the 2026 campaign (four years following the olympiad's year).
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'app_users'
      AND column_name = 'default_diploma_academic_year'
  ) AND NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'app_users'
      AND column_name = 'default_diploma_year'
  ) THEN
    ALTER TABLE app_users RENAME COLUMN default_diploma_academic_year TO default_diploma_year;
  ELSIF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'app_users'
      AND column_name = 'default_diploma_year'
  ) THEN
    ALTER TABLE app_users ADD COLUMN default_diploma_year SMALLINT
      CHECK (default_diploma_year BETWEEN 2020 AND 2100);
  END IF;

  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'tracked_olympiads'
      AND column_name = 'diploma_academic_year'
  ) AND NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'tracked_olympiads'
      AND column_name = 'diploma_year'
  ) THEN
    ALTER TABLE tracked_olympiads RENAME COLUMN diploma_academic_year TO diploma_year;
  ELSIF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'tracked_olympiads'
      AND column_name = 'diploma_year'
  ) THEN
    ALTER TABLE tracked_olympiads ADD COLUMN diploma_year SMALLINT
      CHECK (diploma_year BETWEEN 2020 AND 2100);
  END IF;
END $$;
