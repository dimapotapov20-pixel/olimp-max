-- Reference records for the Olimp MVP.
-- These are policy summaries, not a claim that every Olympiad is accepted by
-- every programme. Exact benefit_rules are imported only from programme-level
-- university documents and always keep their source URL and check date.

INSERT INTO sources (code, name, base_url, source_kind) VALUES
  ('rsosh', 'Российский совет олимпиад школьников', 'https://rsr-olymp.ru/', 'catalog'),
  ('ya-professional', 'Олимпиада «Я — профессионал»', 'https://yandex.ru/profi/', 'organizer'),
  ('hse-admission', 'НИУ ВШЭ: приложение РСОШ 2026', 'https://ba.hse.ru/mirror/pubs/share/1120646407', 'university_admissions'),
  ('mipt-admission', 'МФТИ: приём по олимпиадам', 'https://pk.mipt.ru/bachelor/2026_olympiads/', 'university_admissions'),
  ('mephi-admission', 'НИЯУ МИФИ: особые права олимпиадников', 'https://admission.mephi.ru/admission/baccalaureate-and-specialty/specials/winners', 'university_admissions'),
  ('msu-admission', 'МГУ: льготы РСОШ', 'https://cpk.msu.ru/files/2026/olymp_benefits.pdf', 'university_admissions'),
  ('bmstu-admission', 'МГТУ им. Н.Э. Баумана: особые права 2026', 'https://api.www.bmstu.ru/file/124777/download', 'university_admissions'),
  ('mai-admission', 'МАИ: поступление без вступительных испытаний 2026', 'https://priem.mai.ru/base/bvi/', 'university_admissions'),
  ('mirea-admission', 'РТУ МИРЭА: правила приёма 2026', 'https://stavropol.mirea.ru/wp-content/docs/sveden/document/Pravila-priyema-BSM-May-2026.pdf', 'university_admissions')
ON CONFLICT (code) DO UPDATE SET
  name = EXCLUDED.name,
  base_url = EXCLUDED.base_url,
  source_kind = EXCLUDED.source_kind,
  is_active = TRUE;

INSERT INTO subjects (code, name) VALUES
  ('english', 'Английский язык'),
  ('astronomy', 'Астрономия'),
  ('biology', 'Биология'),
  ('geography', 'География'),
  ('informatics', 'Информатика'),
  ('art', 'Искусство (МХК)'),
  ('spanish', 'Испанский язык'),
  ('history', 'История'),
  ('italian', 'Итальянский язык'),
  ('chinese', 'Китайский язык'),
  ('literature', 'Литература'),
  ('math', 'Математика'),
  ('german', 'Немецкий язык'),
  ('obzr', 'ОБЗР'),
  ('social-studies', 'Обществознание'),
  ('law', 'Право'),
  ('russian', 'Русский язык'),
  ('technology', 'Труд (технология)'),
  ('physics', 'Физика'),
  ('physical-education', 'Физическая культура'),
  ('french', 'Французский язык'),
  ('chemistry', 'Химия'),
  ('ecology', 'Экология'),
  ('economics', 'Экономика'),
  ('other', 'Разные предметы')
ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name;

INSERT INTO universities (code, name, city, official_url) VALUES
  ('hse', 'НИУ ВШЭ', 'Москва', 'https://ba.hse.ru/olimp'),
  ('mipt', 'МФТИ', 'Долгопрудный', 'https://pk.mipt.ru/bachelor/2026_olympiads/'),
  ('mephi', 'НИЯУ МИФИ', 'Москва', 'https://admission.mephi.ru/admission/baccalaureate-and-specialty/specials/winners'),
  ('msu', 'МГУ имени М. В. Ломоносова', 'Москва', 'https://cpk.msu.ru/files/2026/olymp_benefits.pdf'),
  ('bmstu', 'МГТУ им. Н. Э. Баумана', 'Москва', 'https://bmstu.ru/documents'),
  ('mai', 'МАИ', 'Москва', 'https://priem.mai.ru/base/bvi/'),
  ('mirea', 'РТУ МИРЭА', 'Москва', 'https://www.mirea.ru/')
ON CONFLICT (code) DO UPDATE SET
  name = EXCLUDED.name,
  city = EXCLUDED.city,
  official_url = EXCLUDED.official_url,
  is_active = TRUE;

INSERT INTO admission_campaigns (
  university_id, campaign_year, status, rules_url, rules_checked_at
)
SELECT id, 2026, 'published', official_url, TIMESTAMPTZ '2026-09-18T00:00:00Z'
FROM universities
WHERE code IN ('hse', 'mipt', 'mephi', 'msu', 'bmstu', 'mai', 'mirea')
ON CONFLICT (university_id, campaign_year) DO UPDATE SET
  status = EXCLUDED.status,
  rules_url = EXCLUDED.rules_url,
  rules_checked_at = EXCLUDED.rules_checked_at;

-- The generic Requests + BeautifulSoup crawler creates review candidates only. A reviewer
-- still maps them to programmes and publishes a verified benefit rule.
INSERT INTO admission_source_targets (
  admission_campaign_id, source_id, url, source_role, document_kind, adapter_code,
  adapter_config, next_check_at
)
SELECT campaign.id, source.id, seed.url, 'benefits_table', seed.document_kind, 'requests-bs4-keyword-v1',
       seed.adapter_config::jsonb, now()
FROM (
  VALUES
    ('hse', 'hse-admission', 'https://ba.hse.ru/mirror/pubs/share/1120646407', 'pdf', '{"allow_hosts":["ba.hse.ru","www.hse.ru"]}'),
    ('mipt', 'mipt-admission', 'https://pk.mipt.ru/bachelor/2026_olympiads/', 'html', '{"allow_hosts":["pk.mipt.ru"]}'),
    ('mephi', 'mephi-admission', 'https://admission.mephi.ru/admission/baccalaureate-and-specialty/specials/winners', 'html', '{"allow_hosts":["admission.mephi.ru"]}'),
    ('msu', 'msu-admission', 'https://cpk.msu.ru/files/2026/olymp_benefits.pdf', 'pdf', '{"allow_hosts":["cpk.msu.ru"]}'),
    ('bmstu', 'bmstu-admission', 'https://api.www.bmstu.ru/file/124777/download', 'pdf', '{"allow_hosts":["api.www.bmstu.ru","www.bmstu.ru","bmstu.ru"],"user_agent":"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"}'),
    ('bmstu', 'bmstu-admission', 'https://api.www.bmstu.ru/file/122150/download', 'pdf', '{"allow_hosts":["api.www.bmstu.ru","www.bmstu.ru","bmstu.ru"],"user_agent":"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"}'),
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

INSERT INTO admission_policies (
  admission_campaign_id, university_program_id, policy_kind,
  description, source_url, checked_at, is_verified
)
SELECT
  campaign.id,
  NULL,
  'general',
  CASE university.code
    WHEN 'hse' THEN 'Льгота для РСОШ зависит от образовательной программы и подтверждается профильным ЕГЭ или ВИ. Если особое право не используется, диплом может дать до 6 баллов как индивидуальное достижение.'
    WHEN 'mipt' THEN 'Условия БВИ и 100 баллов зависят от физтех-школы и конкурсной группы. Для РСОШ требуется подтверждение профильным ЕГЭ или ВИ не ниже 75 баллов.'
    WHEN 'mephi' THEN 'Победители и призёры олимпиад школьников могут получить БВИ или 100 баллов по соответствующему предмету. Для особых прав требуется не менее 75 баллов ЕГЭ или внутреннего испытания по профильному предмету.'
    WHEN 'msu' THEN 'МГУ публикует отдельный перечень соответствий олимпиад, профилей и направлений подготовки. Для использования особого права требуется сверить факультет и условия кампании 2026.'
    WHEN 'bmstu' THEN 'Бауманка публикует отдельные документы с соответствиями олимпиад для БВИ и для 100 баллов. Льгота зависит от профиля олимпиады и выбранного направления.'
    WHEN 'mai' THEN 'Победители и призёры РСОШ могут использовать БВИ при соответствии профиля выбранному направлению и подтверждении профильным ЕГЭ не ниже 75 баллов. Для заключительного этапа ВсОШ подтверждение ЕГЭ не требуется.'
  END,
  campaign.rules_url,
  TIMESTAMPTZ '2026-09-18T00:00:00Z',
  TRUE
FROM admission_campaigns campaign
JOIN universities university ON university.id = campaign.university_id
WHERE campaign.campaign_year = 2026
  AND university.code IN ('hse', 'mipt', 'mephi', 'msu', 'bmstu', 'mai')
ON CONFLICT (admission_campaign_id, university_program_id, policy_kind) DO UPDATE SET
  description = EXCLUDED.description,
  source_url = EXCLUDED.source_url,
  checked_at = EXCLUDED.checked_at,
  is_verified = EXCLUDED.is_verified;
