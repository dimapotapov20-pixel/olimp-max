-- Bind each non-uniform official format to its own checked parser.  The two
-- Bauman appendices describe different benefits and must never share one
-- adapter code.

UPDATE admission_source_targets target
SET adapter_code = CASE
      WHEN source.code = 'mipt-admission' THEN 'strict-mipt-2026-v2'
      WHEN source.code = 'msu-admission' THEN 'strict-msu-2026-v2'
      WHEN source.code = 'bmstu-admission'
           AND target.url = 'https://api.www.bmstu.ru/file/124777/download'
        THEN 'strict-bmstu-bvi-2026-v1'
      WHEN source.code = 'bmstu-admission'
           AND target.url = 'https://api.www.bmstu.ru/file/122150/download'
        THEN 'strict-bmstu-100-2026-v1'
      ELSE target.adapter_code
    END,
    adapter_config = target.adapter_config || jsonb_build_object(
      'strict_adapter', CASE
        WHEN source.code = 'mipt-admission' THEN 'strict-mipt-2026-v2'
        WHEN source.code = 'msu-admission' THEN 'strict-msu-2026-v2'
        WHEN source.code = 'bmstu-admission'
             AND target.url = 'https://api.www.bmstu.ru/file/124777/download'
          THEN 'strict-bmstu-bvi-2026-v1'
        WHEN source.code = 'bmstu-admission'
             AND target.url = 'https://api.www.bmstu.ru/file/122150/download'
          THEN 'strict-bmstu-100-2026-v1'
        ELSE target.adapter_code
      END,
      'rsosh_catalogue_year', 2025
    ),
    next_check_at = now(),
    updated_at = now()
FROM sources source
WHERE target.source_id = source.id
  AND source.code IN ('mipt-admission', 'msu-admission', 'bmstu-admission');
