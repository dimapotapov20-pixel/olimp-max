-- The MAI BVI page is an official, reviewed campaign-level source.  Store its
-- wording in PostgreSQL so the mini app never needs a JSON summary for it.

INSERT INTO admission_policies (
  admission_campaign_id, university_program_id, policy_kind,
  description, source_url, checked_at, is_verified
)
SELECT
  campaign.id,
  NULL,
  'general',
  'Победители и призёры РСОШ могут использовать БВИ при соответствии профиля выбранному направлению и подтверждении профильным ЕГЭ не ниже 75 баллов. Для заключительного этапа ВсОШ подтверждение ЕГЭ не требуется.',
  'https://priem.mai.ru/base/bvi/',
  now(),
  TRUE
FROM admission_campaigns campaign
JOIN universities university ON university.id = campaign.university_id
WHERE university.code = 'mai'
  AND campaign.campaign_year = 2026
ON CONFLICT (admission_campaign_id, university_program_id, policy_kind) DO UPDATE SET
  description = EXCLUDED.description,
  source_url = EXCLUDED.source_url,
  checked_at = EXCLUDED.checked_at,
  is_verified = EXCLUDED.is_verified;
