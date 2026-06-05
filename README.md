# STAL Analogs Storage

HTTP API для хранения и поиска соответствий **STAL-артикул → аналоги**. Данные хранятся в Google Sheets; извлечение из файлов и команды на естественном языке выполняются через OpenAI.

Предназначен для интеграции с Telegram-ботом и другими внутренними клиентами.

## Возможности

- **CRUD маппингов** — создание, чтение, обновление и удаление связок STAL → аналоги
- **Поиск** — STAL по аналогу и список аналогов по STAL-коду
- **Импорт из файлов** — извлечение связок из CSV, Excel, изображений (preview без автосохранения)
- **Глубокое сопоставление** — поиск косвенных связей через уже сохранённую базу
- **Агент** — свободные команды на естественном языке (как в Telegram), сессии с контекстом диалога
- **Файловое хранилище** — S3-совместимое (MinIO) для вложений агента

## Архитектура

```text
Клиент (бот, скрипт, интеграция)
        │
        │  HTTP + Bearer token
        ▼
stal-analogs-storage (FastAPI)
        │
        ├── Google Sheets API  →  база соответствий
        ├── OpenAI API         →  извлечение из файлов, agent-команды
        ├── SQLite             →  сессии агента (контекст диалога)
        └── MinIO (S3)         →  файлы, прикреплённые к агенту
```

**Swagger UI:** `http://<host>:8000/docs`  
**Healthcheck:** `GET /health` (без авторизации)

## Быстрый старт

### Требования

- Python 3.12+
- Google Service Account с доступом к таблице
- Ключ OpenAI API
- Для агента с файлами — S3-совместимое хранилище (MinIO поднимается через docker-compose)

### Локальная разработка

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux/macOS

pip install -r requirements.txt
cp .env.example .env            # заполните переменные
```

Положите `credentials.json` в корень проекта или задайте `GOOGLE_SHEETS_CREDENTIALS_JSON` в `.env`.

Для локальной работы агента с файлами поднимите MinIO:

```bash
docker compose up -d minio
```

В `.env` для локального запуска API укажите:

```env
S3_ENDPOINT_URL=http://127.0.0.1:9000
```

Запуск API:

```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Проверка:

```bash
curl http://127.0.0.1:8000/health
```

### Docker Compose (полный стек)

```bash
cp .env.example .env            # заполните переменные
docker compose up -d --build
```

Поднимаются два сервиса:

| Сервис | Контейнер | Назначение |
| ------ | --------- | ---------- |
| `api` | `stal-analogs-storage-api` | FastAPI на порту `APP_PORT` (по умолчанию 8000) |
| `minio` | `stal-analogs-storage-minio` | S3-хранилище файлов агента |

Сеть `stal-analogs-storage` доступна другим compose-проектам на том же сервере (например, Telegram-бот подключается к `http://stal-analogs-storage-api:8000`).

## Аутентификация

Все эндпоинты, кроме `/health`, требуют заголовок:

```http
Authorization: Bearer <API_TOKEN>
```

## Эндпоинты (кратко)

| Группа | Пути | Описание |
| ------ | ---- | -------- |
| System | `GET /health` | Проверка доступности |
| Mappings | `/mappings`, `/mappings/{stal_code}`, `/mappings/bulk-upsert`, `/mappings/deep-extraction` | CRUD и массовые операции |
| Search | `GET /search`, `GET /search/by-stal` | Поиск по аналогу и по STAL |
| Agent | `/agent/ingest-file`, `/agent/deep-extraction`, `/agent/refine-ingest-items`, `/agent/command`, `/agent/session/reset` | Файлы, preview, NL-команды, сессии |

Подробные примеры запросов, коды ответов и FAQ — в [GUIDE.md](GUIDE.md).

## Переменные окружения

Скопируйте [.env.example](.env.example) в `.env`. Основные группы:

| Группа | Переменные | Назначение |
| ------ | ---------- | ---------- |
| Приложение | `APP_HOST`, `APP_PORT`, `API_TOKEN`, `DEBUG` | Сеть и авторизация |
| Google Sheets | `GOOGLE_SHEETS_SPREADSHEET_ID`, `GOOGLE_SHEETS_CREDENTIALS_JSON`, `GOOGLE_SHEETS_SHEET_NAME` | Хранилище маппингов |
| OpenAI | `OPENAI_API_KEY`, `OPENAI_MODEL` | Извлечение и агент |
| Сессии | `SESSIONS_DB_PATH`, `AGENT_HISTORY_LIMIT`, `AGENT_SESSION_TTL_MINUTES` | Контекст диалога агента |
| S3 / MinIO | `S3_ENDPOINT_URL`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_BUCKET`, `MINIO_ROOT_USER`, `MINIO_ROOT_PASSWORD` | Файлы агента |

`S3_ACCESS_KEY` / `S3_SECRET_KEY` должны совпадать с `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD`. Бакет создаётся автоматически при старте API.

## Структура проекта

```text
app/
├── api/            # FastAPI-роутеры (mappings, search, agent)
├── deps/           # Зависимости (аутентификация)
├── parsers/        # Парсеры файлов (Excel и др.)
├── repositories/   # Google Sheets, SQLite-сессии
├── schemas/        # Pydantic-модели запросов/ответов
├── services/       # Бизнес-логика (маппинги, поиск, агент, S3)
└── utils/          # Настройки, логирование, нормализация
```

## Деплой

Продакшен-деплой на Ubuntu через Docker и GitHub Actions (GHCR) описан в [DEPLOY.md](DEPLOY.md).

## Документация

| Файл | Содержание |
| ---- | ---------- |
| [GUIDE.md](GUIDE.md) | Справочник API, примеры curl, агент, коды ошибок |
| [DEPLOY.md](DEPLOY.md) | Сервер, GitHub Actions, nginx, интеграция с ботом |
| `/docs` | Интерактивная OpenAPI-документация (Swagger UI) |
