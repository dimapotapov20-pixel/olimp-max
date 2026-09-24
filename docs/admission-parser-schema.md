# Схема правил поступления

Эта часть БД предназначена для данных о льготах олимпиад при поступлении. Она отделяет результат автоматического парсинга от информации, которую видят пользователи.

## Поток данных

1. `university_locations` хранит головные площадки, кампусы, филиалы и онлайн-площадки. У каждой свой статус проверки; льготы головного вуза не копируются в филиал.
2. `admission_source_targets` хранит официальный URL вуза или конкретной площадки, тип документа, адаптер парсинга и период проверки.
2. При обходе создаётся неизменяемый `source_documents`: дата скачивания, контрольная сумма и ключ исходного HTML, PDF или таблицы в объектном хранилище.
3. `admission_parse_runs` сохраняет версию парсера, результат запуска и диагностические данные.
4. Каждая извлечённая строка попадает в `admission_rule_candidates`. Там остаются исходный текст, координаты в документе, нормализованные предположения и уверенность матчинга.
5. Обычный кандидат проверяет ревьюер. Для пяти строгих адаптеров действует второй путь: строка публикуется сама, только если точно разрешились программа конкретной площадки и профиль РСОШ.
6. `benefit_rule_observations` связывает опубликованное правило с очередной версией документа и позволяет заметить изменение или исчезновение льготы.

## Главное ограничение

В пользовательский каталог `v_benefit_catalog` попадают только активные правила со статусом `verified`. Черновики, неоднозначные совпадения и отклонённые кандидаты не могут оказаться в поиске мини-приложения.

## Статусы

| Сущность | Статусы |
| --- | --- |
| `admission_parse_runs` | `running`, `succeeded`, `failed` |
| `admission_rule_candidates.review_status` | `pending`, `approved`, `rejected`, `superseded` |
| `benefit_rules.verification_status` | `draft`, `needs_review`, `verified`, `rejected`, `superseded` |
| `admission_rule_candidates.automatic_status` | `not_applicable`, `pending_resolution`, `published`, `blocked` |

`is_verified` сохранён ради совместимости со старым кодом и синхронизирован ограничением с `verification_status`: значение `true` возможно только для статуса `verified`.

## Применение

Для новой БД достаточно применить [schema.sql](../db/schema.sql). Для уже развёрнутой первой версии применяются миграции [002_admission_rules_pipeline.sql](../db/migrations/002_admission_rules_pipeline.sql) и [008_strict_admission_adapters.sql](../db/migrations/008_strict_admission_adapters.sql).

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

Обходчик сам запишет снимок, запуск и кандидатов в БД. Для обычных источников
он намеренно не вставляет строки напрямую в `benefit_rules`: сначала нужно
сопоставить программу с записью в БД и подтвердить правило. Это сохраняет
безопасность для страниц со свободным текстом.

## Пять строгих адаптеров без ручного подтверждения

Для ВШЭ, МФТИ, МИФИ, МГУ и МГТУ им. Баумана после загрузки площадок запускается
`configure_strict_admission_targets.py`. Он привязывает только главный кампус
каждого вуза к его официальному документу и никогда не переносит правило на
филиал. Затем `strict_admission_adapters.py` принимает лишь строку таблицы, в
которой явно названы программа (или её код), олимпиада, профиль, статус диплома
и вид льготы. МИФИ дополнительно поддерживает свой официальный формат, где
коды программ находятся прямо в колонках «Поступление БВИ» и «100 баллов».

`publish_strict_admission_rules.py` автоматически публикует такую строку,
только если код/название программы однозначно совпали с
`university_programs` **той же площадки**, а пара «олимпиада + профиль» — с
утверждённой записью РСОШ. Иначе кандидат остаётся в БД с
`automatic_status = blocked` и причиной: например,
`programme_not_exactly_mapped_for_location` или `rsosh_title_without_profile`.
Он не появится у пользователя. Автоматическая строка получает
`publication_method = strict_adapter`; вручную исправленная строка имеет
приоритет и не перезаписывается адаптером.

Если документ указывает только официальный код направления (например,
`38.03.01`), система создаёт прозрачную запись `Направление 38.03.01` со
статусом каталога `code_only`, а не выдумывает название программы. При
появлении официального каталога с несколькими программами на один код такая
строка больше не расширяется автоматически.

Для кампании поступления 2026 адаптеры проверяют утверждённый перечень РСОШ
2025/26 (`rsosh_catalogue_year = 2025`), а не подменяют его несуществующим
списком 2026/27.

```bash
python3 parser/load_university_locations.py
python3 parser/configure_strict_admission_targets.py
python3 parser/crawl_admission_rules.py --force --limit 100
python3 parser/publish_strict_admission_rules.py --limit 500
python3 -m unittest parser/test_strict_admission_adapters.py parser/test_strict_admission_publisher.py
```

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
location import, strict target binding, admission-document crawler and strict
publisher once a day. The interval is
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
