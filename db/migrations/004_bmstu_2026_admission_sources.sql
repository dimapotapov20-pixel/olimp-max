-- Replace the single «Шаг в будущее» landing page with the two official
-- Bauman 2026 admission attachments: BVI and 100-point equivalency.

UPDATE sources
SET name = 'МГТУ им. Н.Э. Баумана: особые права 2026',
    base_url = 'https://api.www.bmstu.ru/file/124777/download'
WHERE code = 'bmstu-admission';

UPDATE universities
SET official_url = 'https://bmstu.ru/documents'
WHERE code = 'bmstu';

UPDATE admission_campaigns campaign
SET rules_url = 'https://bmstu.ru/documents',
    rules_checked_at = now()
FROM universities university
WHERE university.id = campaign.university_id
  AND university.code = 'bmstu'
  AND campaign.campaign_year = 2026;

UPDATE admission_source_targets target
SET is_active = FALSE,
    updated_at = now()
FROM sources source, admission_campaigns campaign, universities university
WHERE source.code = 'bmstu-admission'
  AND campaign.university_id = university.id
  AND university.code = 'bmstu'
  AND campaign.campaign_year = 2026
  AND target.source_id = source.id
  AND target.admission_campaign_id = campaign.id
  AND target.url NOT IN (
    'https://api.www.bmstu.ru/file/124777/download',
    'https://api.www.bmstu.ru/file/122150/download'
  );

INSERT INTO admission_source_targets (
  admission_campaign_id, source_id, url, source_role, document_kind,
  adapter_code, adapter_config, next_check_at
)
SELECT campaign.id, source.id, seed.url, 'benefits_table', 'pdf',
       'requests-bs4-keyword-v1',
       '{"allow_hosts":["api.www.bmstu.ru","www.bmstu.ru","bmstu.ru"],"user_agent":"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"}'::jsonb,
       now()
FROM (
  VALUES
    ('https://api.www.bmstu.ru/file/124777/download'),
    ('https://api.www.bmstu.ru/file/122150/download')
) AS seed(url)
JOIN sources source ON source.code = 'bmstu-admission'
JOIN universities university ON university.code = 'bmstu'
JOIN admission_campaigns campaign
  ON campaign.university_id = university.id AND campaign.campaign_year = 2026
ON CONFLICT (admission_campaign_id, url) DO UPDATE SET
  source_id = EXCLUDED.source_id,
  source_role = EXCLUDED.source_role,
  document_kind = EXCLUDED.document_kind,
  adapter_code = EXCLUDED.adapter_code,
  adapter_config = EXCLUDED.adapter_config,
  is_active = TRUE,
  next_check_at = now(),
  updated_at = now();
