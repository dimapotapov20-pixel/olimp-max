-- Replace the informational HSE olympiad page with the official 2026
-- programme-level РСОШ attachment. The old page is retained in source
-- documents and its candidates stay auditable but become superseded by the
-- crawler's new run.

UPDATE sources
SET name = 'НИУ ВШЭ: приложение РСОШ 2026',
    base_url = 'https://ba.hse.ru/mirror/pubs/share/1120646407'
WHERE code = 'hse-admission';

UPDATE admission_campaigns campaign
SET rules_url = 'https://ba.hse.ru/mirror/pubs/share/1120646407',
    rules_checked_at = now()
FROM universities university
WHERE university.id = campaign.university_id
  AND university.code = 'hse'
  AND campaign.campaign_year = 2026;

UPDATE admission_source_targets target
SET url = 'https://ba.hse.ru/mirror/pubs/share/1120646407',
    document_kind = 'pdf',
    adapter_config = '{"allow_hosts":["ba.hse.ru","www.hse.ru"]}'::jsonb,
    next_check_at = now(),
    updated_at = now()
FROM sources source, admission_campaigns campaign, universities university
WHERE source.code = 'hse-admission'
  AND campaign.university_id = university.id
  AND university.code = 'hse'
  AND campaign.campaign_year = 2026
  AND target.source_id = source.id
  AND target.admission_campaign_id = campaign.id;
