# Руководство пользователя API

**stal-analogs-storage** — HTTP API для хранения соответствий `STAL-артикул → аналоги` в Google Sheets. Сервис предоставляет CRUD, поиск, извлечение артикулов из файлов через OpenAI и агент для команд на естественном языке.

---

## Обзор

```text
Клиент (бот, скрипт, интеграция)
        │
        │  HTTP + Bearer token
        ▼
stal-analogs-storage (FastAPI)
        │
        ├── Google Sheets API  →  база соответствий
        └── OpenAI API         →  извлечение из файлов, agent-команды
```

**База данных (Google Sheets):**


| Колонка         | Содержимое                                             |
| --------------- | ------------------------------------------------------ |
| **A**           | STAL-артикул (формат `ST` + цифры, например `ST20868`) |
| **B–Z**         | Аналоги                                                |
| *(notes ячеек)* | Источник файла, время обновления                       |


**Swagger UI:** `http://<host>:8000/docs`  
**Healthcheck:** `GET /health` (без авторизации)

---

## Аутентификация

Все эндпоинты, кроме `/health`, требуют заголовок:

```http
Authorization: Bearer <API_TOKEN>
```

Токен задаётся в переменных окружения backend и в `.env` бота (`API_TOKEN`).

---

## Справочник эндпоинтов

### Системные


| Метод | Путь      | Описание                 |
| ----- | --------- | ------------------------ |
| `GET` | `/health` | Проверка доступности API |


### Маппинги (CRUD)


| Метод    | Путь                        | Описание                        |
| -------- | --------------------------- | ------------------------------- |
| `POST`   | `/mappings`                 | Создать связку STAL → аналоги   |
| `GET`    | `/mappings`                 | Все связки                      |
| `GET`    | `/mappings/{stal_code}`     | Одна связка по STAL-коду        |
| `PATCH`  | `/mappings/{stal_code}`     | Обновить аналоги                |
| `DELETE` | `/mappings/{stal_code}`     | Удалить всю связку              |
| `POST`   | `/mappings/bulk-upsert`     | Массовое создание/обновление    |
| `POST`   | `/mappings/deep-extraction` | Preview глубокого сопоставления |


### Поиск


| Метод | Путь              | Параметры | Описание                             |
| ----- | ----------------- | --------- | ------------------------------------ |
| `GET` | `/search`         | `article` | STAL по аналогу (или по самому STAL) |
| `GET` | `/search/by-stal` | `article` | Все аналоги по STAL-коду             |


### Агент и файлы


| Метод  | Путь                         | Описание                           |
| ------ | ---------------------------- | ---------------------------------- |
| `POST` | `/agent/ingest-file`         | Извлечь связки из файла (preview)  |
| `POST` | `/agent/deep-extraction`     | Глубокий поиск по файлу (preview)  |
| `POST` | `/agent/refine-ingest-items` | Правка preview перед сохранением   |
| `POST` | `/agent/command`             | Свободная команда (как в Telegram) |
| `POST` | `/agent/session/reset`       | Сброс сессии пользователя          |


---

## Работа с маппингами

### Создать связку

`POST /mappings`

```json
{
  "stal_code": "ST20868",
  "aliases": ["P551039", "P550690"],
  "source_filename": "manual-entry"
}
```

- **201** — создано.
- **409** — запись с таким STAL уже существует.

### Обновить аналоги

`PATCH /mappings/{stal_code}`

```json
{
  "aliases": ["P551039", "NEW001"],
  "append": true,
  "source_filename": "update.csv"
}
```


| `append`               | Поведение                                |
| ---------------------- | ---------------------------------------- |
| `false` (по умолчанию) | Полная замена списка аналогов            |
| `true`                 | Добавление к существующим без дубликатов |


### Массовое сохранение

`POST /mappings/bulk-upsert`

```json
{
  "source_filename": "price_list.xlsx",
  "items": [
    {
      "stal_code": "ST20868",
      "aliases": ["P551039", "P550690"],
      "alias_parent_codes": {}
    }
  ]
}
```

- Если STAL нет — создаётся новая строка.
- Если STAL есть — новые аналоги **добавляются** к существующим (старые не удаляются).
- Поле `alias_parent_codes` — связи из глубокого поиска: `{"аналог": "родительский_артикул_из_файла"}`.

Ответ:

```json
{
  "created": 5,
  "updated": 12,
  "total": 17
}
```

### Удалить связку

`DELETE /mappings/{stal_code}` → удаляет строку целиком со всеми аналогами.

---

## Поиск

### STAL по аналогу

`GET /search?article=P551039`

```json
{
  "found": true,
  "query": "P551039",
  "stal_code": "ST20868",
  "matched_alias": "P551039"
}
```

### Аналоги по STAL

`GET /search/by-stal?article=ST20868`

```json
{
  "found": true,
  "stal_code": "ST20868",
  "aliases": ["P551039", "P550690"]
}
```

---

## Извлечение артикулов из файлов

Главный сценарий API — загрузить прайс или таблицу и получить структурированные связки `STAL → аналоги` без ручного ввода.

### Поддерживаемые форматы

`xlsx`, `xls`, `csv`, `pdf`, `png`, `jpg`, `jpeg`, `webp`


| Тип                              | Обработка                                                          |
| -------------------------------- | ------------------------------------------------------------------ |
| Табличные (`xlsx`, `xls`, `csv`) | Парсер преобразует строки в текст, затем OpenAI извлекает артикулы |
| PDF и изображения                | Файл отправляется в OpenAI для распознавания таблиц                |


Лимит: до **5000 строк на лист** при подготовке текста для AI.

### Два режима

#### Обычное извлечение — `POST /agent/ingest-file`

Ищет в файле группы артикулов одного товара. В каждой группе определяется STAL (`ST` + цифры), остальные коды — аналоги. Строки без STAL пропускаются.

**Не сохраняет в Google Sheets** — только preview в поле `llm_items`.

#### Глубокий поиск — `POST /agent/deep-extraction`

1. OpenAI извлекает **наборы артикулов** из файла (строка = один товар, STAL не обязателен).
2. Backend сравнивает каждый код с уже сохранёнными STAL и аналогами в Google Sheets.
3. При совпадении весь набор предлагается к добавлению к найденному STAL.

**Не сохраняет** — возвращает структуру `BulkUpsertRequest` для последующего `bulk-upsert`.

### Типовой pipeline: ingest → refine → save

```text
POST /agent/ingest-file          →  preview (llm_items)
        │
        ├── POST /agent/refine-ingest-items  →  обновлённый preview (опционально)
        │
        └── POST /mappings/bulk-upsert       →  запись в Google Sheets
```

### Шаг 1: загрузить файл

`POST /agent/ingest-file` — `multipart/form-data`, поле `file`.

```bash
curl -X POST "http://127.0.0.1:8000/agent/ingest-file" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -F "file=@price_list.xlsx"
```

Ответ при успехе:

```json
{
  "filename": "price_list.xlsx",
  "items_extracted": 42,
  "items_saved": 0,
  "status": "preview_ready",
  "llm_items": [
    {
      "stal_code": "ST20868",
      "aliases": ["P551039", "P550690"],
      "source_fragment": "Row 15: ST20868 | P551039 | P550690"
    }
  ]
}
```

Статус `no_mappings_found` — в файле не найдено подходящих таблиц с артикулами.

### Шаг 2: скорректировать preview (опционально)

`POST /agent/refine-ingest-items` — JSON:

```json
{
  "filename": "price_list.xlsx",
  "items": [
    {
      "stal_code": "ST20868",
      "aliases": ["P551039", "P550690"],
      "source_fragment": "Row 15: ST20868 | P551039 | P550690"
    }
  ],
  "correction": "Убери строки без STAL-кода и дубликаты аналогов"
}
```

Поле `correction` — инструкция на естественном языке: что изменить в preview.

### Шаг 3: сохранить

`POST /mappings/bulk-upsert` с массивом `items` из preview.

### Глубокий поиск через API

`POST /agent/deep-extraction` — `multipart/form-data`, поле `file`.

```bash
curl -X POST "http://127.0.0.1:8000/agent/deep-extraction" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -F "file=@supplier_without_stal.csv"
```

Ответ — `BulkUpsertRequest`:

```json
{
  "source_filename": "supplier_without_stal.csv",
  "items": [
    {
      "stal_code": "ST20868",
      "aliases": ["NEW001", "NEW002"],
      "alias_parent_codes": {
        "NEW001": "P551039"
      }
    }
  ]
}
```

Для сохранения передайте этот объект в `POST /mappings/bulk-upsert`.

Альтернатива: если наборы артикулов уже известны, вызовите `POST /mappings/deep-extraction` напрямую:

```json
{
  "externalCodeSets": [
    ["P551039", "NEW001", "NEW002"],
    ["AT112393", "X999"]
  ]
}
```

---

## Инструкции по извлечению данных

Эндпоинты `/agent/ingest-file` и `/agent/deep-extraction` **не принимают** поле `instructions` напрямую. Инструкции по колонкам, листам и структуре файла передаются через `**POST /agent/command`** — агент извлекает их из текста `message` и передаёт в OpenAI.

**Что можно указать в `message`:**

- колонка/столбец для STAL-артикула;
- колонки для аналогов;
- имя листа Excel;
- пропуск шапки, игнорируемые колонки;
- правила группировки кодов в строке.

**Пример:**

```bash
curl -X POST "http://127.0.0.1:8000/agent/command" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -F "user_id=123456789" \
  -F "message=Извлеки артикулы. STAL в колонке A, аналоги в B и C. Лист Прайс." \
  -F "file=@supplier.csv"
```

Для программного pipeline без агента инструкции пока не поддерживаются на `/agent/ingest-file` — используйте `/agent/command` или подготовьте файл с понятной структурой.

---

## Agent command — свободные команды

`POST /agent/command` — `multipart/form-data`:


| Поле      | Обязательно | Описание                                                           |
| --------- | ----------- | ------------------------------------------------------------------ |
| `user_id` | да          | ID пользователя для сессии и контекста (в боте — Telegram user_id) |
| `message` | нет         | Текст команды на русском или английском                            |
| `file`    | нет         | Вложение для извлечения или глубокого поиска                       |


Агент выбирает инструмент и выполняет действие. Примеры `message`:

```
Добавь аналог P551039 к ST20868
Найди ST11013
Извлеки артикулы из файла. STAL — колонка A, аналоги — C и D
Сделай глубокий поиск по файлу
применить
отменить
Убери дубликаты из предпросмотра
```

Ответ:

```json
{
  "message": "Файл обработан: извлечено 42, ожидает подтверждения.",
  "tool_name": "ingest_file",
  "tool_arguments": {
    "instructions": "STAL в колонке A, аналоги в B и C"
  },
  "result": {
    "filename": "price_list.xlsx",
    "items_extracted": 42,
    "status": "preview_ready",
    "llm_items": [...]
  }
}
```

### Сессии

- Контекст привязан к `user_id`.
- TTL сессии: **30 минут** без активности (настраивается `AGENT_SESSION_TTL_MINUTES`).
- История: последние **10** сообщений (`AGENT_HISTORY_LIMIT`).
- Активный preview сохраняется в сессии до `apply` / `cancel` или сброса.

`POST /agent/session/reset` — форма с полем `user_id`:

```bash
curl -X POST "http://127.0.0.1:8000/agent/session/reset" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -F "user_id=123456789"
```

### Инструменты агента


| Инструмент              | Когда вызывается                   |
| ----------------------- | ---------------------------------- |
| `add_aliases`           | Добавить аналоги к STAL            |
| `set_aliases`           | Заменить весь список аналогов      |
| `remove_aliases`        | Удалить конкретные аналоги         |
| `delete_mapping`        | Удалить всю связку                 |
| `search_article`        | STAL по аналогу                    |
| `search_by_stal`        | Аналоги по STAL                    |
| `get_mapping`           | Показать сохранённую связку        |
| `bulk_upsert`           | Массовое обновление из текста      |
| `ingest_file`           | Извлечение из прикреплённого файла |
| `deep_extraction_file`  | Глубокий поиск по файлу            |
| `refine_ingest_items`   | Правка активного preview           |
| `apply_ingest_preview`  | Сохранить preview в Google Sheets  |
| `cancel_ingest_preview` | Отменить preview                   |


---

## Коды ответов и ошибки


| Код     | Типичная причина                                           |
| ------- | ---------------------------------------------------------- |
| **400** | Неподдерживаемый формат файла, пустой файл, пустой `items` |
| **401** | Неверный или отсутствующий Bearer token                    |
| **404** | STAL-артикул не найден                                     |
| **409** | Попытка создать уже существующую связку                    |
| **500** | Ошибка Google Sheets, OpenAI или внутренняя ошибка         |


Тело ошибки FastAPI:

```json
{
  "detail": "Unsupported file type '.doc'. Allowed: .csv, .jpeg, ..."
}
```

---

## Частые вопросы

**Чем отличается `/agent/ingest-file` от `/agent/deep-extraction`?**  
`ingest-file` ищет прямые пары STAL → аналоги в файле. `deep-extraction` ищет косвенные связи через уже сохранённую базу.

**Сохраняет ли `/agent/ingest-file` данные автоматически?**  
Нет. Только preview. Сохранение — через `/mappings/bulk-upsert` или `apply_ingest_preview` в `/agent/command`.

**Как передать инструкции по колонкам при прямом вызове ingest?**  
Используйте `/agent/command` с текстом инструкций в `message`.

**Нормализация артикулов**  
Перед сравнением и записью артикулы нормализуются (регистр, пробелы и т.п.).

---

## Краткая шпаргалка

```text
Один STAL вручную       →  POST /mappings
Поиск                     →  GET /search или GET /search/by-stal
Файл → preview            →  POST /agent/ingest-file
Файл → глубокий preview   →  POST /agent/deep-extraction
Правка preview            →  POST /agent/refine-ingest-items
Сохранить preview         →  POST /mappings/bulk-upsert
Как в Telegram            →  POST /agent/command
Сброс сессии              →  POST /agent/session/reset
```

