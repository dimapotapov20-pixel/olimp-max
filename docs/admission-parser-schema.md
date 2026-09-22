# Схема правил поступления

Эта часть БД предназначена для данных о льготах олимпиад при поступлении. Она отделяет результат автоматического парсинга от информации, которую видят пользователи.

## Поток данных

1. `university_locations` хранит головные площадки, кампусы, филиалы и онлайн-площадки. У каждой свой статус проверки; льготы головного вуза не копируются в филиал.
2. `admission_source_targets` хранит официальный URL вуза или конкретной площадки, тип документа, адаптер парсинга и период проверки.
2. При обходе создаётся неизменяемый `source_documents`: дата скачивания, контрольная сумма и ключ исходного HTML, PDF или таблицы в объектном хранилище.
3. `admission_parse_runs` сохраняет версию парсера, результат запуска и диагностические данные.
4. Каждая извлечённая строка попадает в `admission_rule_candidates`. Там остаются исходный текст, координаты в документе, нормализованные предположения и уверенность матчинга.
5. Ревьюер фиксирует решение в `admission_rule_reviews`. При подтверждении появляется или обновляется `benefit_rules`.
6. `benefit_rule_observations` связывает опубликованное правило с очередной версией документа и позволяет заметить изменение или исчезновение льготы.

## Главное ограничение

В пользовательский каталог `v_benefit_catalog` попадают только активные правила со статусом `verified`. Черновики, неоднозначные совпадения и отклонённые кандидаты не могут оказаться в поиске мини-приложения.

## Статусы

| Сущность | Статусы |
| --- | --- |
| `admission_parse_runs` | `running`, `succeeded`, `failed` |
| `admission_rule_candidates.review_status` | `pending`, `approved`, `rejected`, `superseded` |
| `benefit_rules.verification_status` | `draft`, `needs_review`, `verified`, `rejected`, `superseded` |

`is_verified` сохранён ради совместимости со старым кодом и синхронизирован ограничением с `verification_status`: значение `true` возможно только для статуса `verified`.

## Применение

Для новой БД достаточно применить [schema.sql](../schema.sql). Для уже развёрнутой первой версии используется миграция [002_admission_rules_pipeline.sql](../migrations/002_admission_rules_pipeline.sql).

## Универсальный обходчик документов

[crawl_admission_rules.py](../parser/crawl_admission_rules.py) берёт активные
цели из `admission_source_targets` и работает одинаково с HTML, PDF и XLSX.
Он сохраняет исходный документ по SHA-256 и разбирает HTML через
[`requests` + BeautifulSoup](https://github.com/oxylabs/web-scraping-data-parsing-beautiful-soup).
Для PDF и XLSX используются `pdfplumber` и `openpyxl`. Затем он ищет в
таблицах и абзацах связки «олимпиада», «БВИ», «100 баллов», «ЕГЭ» и «75
баллов». Строки превращаются в кандидаты для ревью, вместе с позицией в
Markdown и исходным фрагментом.

```bash
python3 -m pip install -r requirements-crawler.txt
python3 parser/crawl_admission_rules.py --limit 10
python3 -m unittest parser/test_keyword_candidates.py
```

Обходчик сам запишет снимок, запуск и кандидатов в БД. Он намеренно не вставляет
строки напрямую в `benefit_rules`: сначала
необходимо сопоставить название конкурсной группы или программы с записью в
БД и подтвердить правило ревьюером.

## Связь с официальным Перечнем РСОШ

Сначала каталог загружается в БД, затем отдельный безопасный шаг сопоставляет
только однозначные упоминания названия олимпиады **и** её профиля из
одноимённых колонок одной строки таблицы. Совпадение только по предмету,
названию или тексту льготы никогда не связывается автоматически.

```bash
python3 parser/collect_olympiads.py
python3 parser/load_postgres.py
python3 parser/match_rsosh_candidates.py --campaign-year 2025
```

Неоднозначные и нераспознанные строки сохраняются в `admission_rule_candidates`
со статусом `ambiguous` или `unresolved` и требуют проверки человека.

## Площадки вузов

Перед обходом льгот нужно загрузить площадки из официальных каталогов:

```bash
python3 parser/load_university_locations.py
```

In Compose this step is automatic: the `admission-crawler` service runs the
location import and the admission-document crawler once a day. The interval is
`CATALOG_REFRESH_SECONDS=86400` by default; it may be lowered only for local
testing. A failed run never removes the last verified locations or published
benefits.

Витрина `dist/data/universities.json` содержит только подтверждённые адреса и
ссылки на источники. Статус `location_verified` означает только то, что
площадка существует; `rules_discovered` — найдены документы приёма;
`benefits_verified` — только этот статус разрешает показать пользователю
льготы по олимпиадам.

Для статического демо используется отдельный экспорт:

```bash
python3 parser/export_public_benefits.py --campaign-year 2026
```

Он создаёт `dist/data/benefit-rules.json` исключительно из строк
`benefit_rules` со статусом `verified`. В каждой строке обязательны код вуза,
код площадки, программа, олимпиада, профиль, уровень, статус диплома и ссылка
на источник. Благодаря коду площадки правило московской программы не попадёт
в карточку филиала. Кандидаты парсера, исходные фрагменты документов и данные
пользователей в этот файл не экспортируются.
