-- Add MAI and RTU MIREA to the 2026 admissions pipeline.  The crawler creates
-- review candidates only: no benefit is displayed for MIREA until a reviewer
-- verifies programme-level rules.

INSERT INTO sources (code, name, base_url, source_kind) VALUES
  ('mai-admission', 'МАИ: поступление без вступительных испытаний 2026', 'https://priem.mai.ru/base/bvi/', 'university_admissions'),
  ('mirea-admission', 'РТУ МИРЭА: правила приёма 2026', 'https://stavropol.mirea.ru/wp-content/docs/sveden/document/Pravila-priyema-BSM-May-2026.pdf', 'university_admissions')
ON CONFLICT (code) DO UPDATE SET
  name = EXCLUDED.name,
  base_url = EXCLUDED.base_url,
  source_kind = EXCLUDED.source_kind,
  is_active = TRUE;

INSERT INTO universities (code, name, city, official_url) VALUES
  ('mai', 'МАИ', 'Москва', 'https://priem.mai.ru/base/bvi/'),
  ('mirea', 'РТУ МИРЭА', 'Москва', 'https://www.mirea.ru/')
ON CONFLICT (code) DO UPDATE SET
  name = EXCLUDED.name,
  city = EXCLUDED.city,
  official_url = EXCLUDED.official_url,
  is_active = TRUE;

INSERT INTO admission_campaigns (university_id, campaign_year, status, rules_url, rules_checked_at)
SELECT university.id, 2026, 'published', seed.rules_url, now()
FROM (
  VALUES
    ('mai', 'https://priem.mai.ru/base/bvi/'),
    ('mirea', 'https://stavropol.mirea.ru/wp-content/docs/sveden/document/Pravila-priyema-BSM-May-2026.pdf')
) AS seed(university_code, rules_url)
JOIN universities university ON university.code = seed.university_code
ON CONFLICT (university_id, campaign_year) DO UPDATE SET
  status = EXCLUDED.status,
  rules_url = EXCLUDED.rules_url,
  rules_checked_at = EXCLUDED.rules_checked_at;

INSERT INTO admission_source_targets (
  admission_campaign_id, source_id, url, source_role, document_kind,
  adapter_code, adapter_config, next_check_at
)
SELECT campaign.id, source.id, seed.url, 'benefits_table', seed.document_kind,
       'requests-bs4-keyword-v1', seed.adapter_config::jsonb, now()
FROM (
  VALUES
    ('mai', 'mai-admission', 'https://priem.mai.ru/base/bvi/', 'html', '{"allow_hosts":["priem.mai.ru"]}'),
    ('mirea', 'mirea-admission', 'https://stavropol.mirea.ru/wp-content/docs/sveden/document/Pravila-priyema-BSM-May-2026.pdf', 'pdf', '{"allow_hosts":["stavropol.mirea.ru"]}')
) AS seed(university_code, source_code, url, document_kind, adapter_config)
JOIN universities university ON university.code = seed.university_code
JOIN admission_campaigns campaign ON campaign.university_id = university.id AND campaign.campaign_year = 2026
JOIN sources source ON source.code = seed.source_code
ON CONFLICT (admission_campaign_id, url) DO UPDATE SET
  source_id = EXCLUDED.source_id,
  source_role = EXCLUDED.source_role,
  document_kind = EXCLUDED.document_kind,
  adapter_code = EXCLUDED.adapter_code,
  adapter_config = EXCLUDED.adapter_config,
  is_active = TRUE,
  next_check_at = now(),
  updated_at = now();
