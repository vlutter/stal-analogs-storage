# Деплой на Ubuntu 24.04 через Docker и GitHub Actions

Схема деплоя:

1. GitHub Actions собирает Docker image.
2. Image публикуется в GitHub Container Registry: `ghcr.io/<owner>/<repo>`.
3. Workflow подключается к серверу по SSH.
4. На сервере запускается `docker compose pull && docker compose up -d`.

Секреты приложения (`API_TOKEN`, `OPENAI_API_KEY`, Google credentials, доступы к MinIO) хранятся только на сервере в `.env`.

Помимо самого API, docker-compose поднимает сервис `minio` (S3-совместимое хранилище для файлов, которые пользователь прикрепляет к агенту) и держит SQLite-БД сессий агента на отдельном томе.

## 1. Подготовить сервер

Подключитесь к Ubuntu 24.04:

```bash
ssh root@YOUR_SERVER_IP
```

Обновите систему и поставьте Docker:

```bash
apt update && apt upgrade -y
apt install -y ca-certificates curl gnupg ufw
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu noble stable" > /etc/apt/sources.list.d/docker.list
apt update
apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker
```

Создайте пользователя для деплоя:

```bash
adduser deploy
usermod -aG docker deploy
mkdir -p /home/deploy/.ssh
nano /home/deploy/.ssh/authorized_keys
chown -R deploy:deploy /home/deploy/.ssh
chmod 700 /home/deploy/.ssh
chmod 600 /home/deploy/.ssh/authorized_keys
```

В `authorized_keys` вставьте публичный SSH-ключ, приватную часть которого добавите в GitHub Secret `SSH_KEY`.

## 2. Создать директорию приложения

```bash
su - deploy
mkdir -p /home/deploy/stal-analogs-storage
cd /home/deploy/stal-analogs-storage
```

Создайте `.env`:

```bash
nano .env
```

Минимальный пример:

```env
APP_TITLE=STAL Analogs Storage
APP_VERSION=0.1.0
DEBUG=false
APP_HOST=127.0.0.1
APP_PORT=8000

API_TOKEN=replace-with-long-random-secret

GOOGLE_SHEETS_SPREADSHEET_ID=your-spreadsheet-id
GOOGLE_SHEETS_CREDENTIALS_JSON={"type":"service_account","project_id":"..."}
GOOGLE_SHEETS_SHEET_NAME=Лист1

OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o
LOG_LEVEL=INFO

# Сессии агента (контекст диалога)
SESSIONS_DB_PATH=/app/data/sessions.db
AGENT_HISTORY_LIMIT=10
AGENT_SESSION_TTL_MINUTES=30

# S3-совместимое хранилище (MinIO в docker-compose)
S3_ENDPOINT_URL=http://minio:9000
S3_ACCESS_KEY=replace-with-strong-access-key
S3_SECRET_KEY=replace-with-strong-secret-key
S3_BUCKET=agent-files
S3_REGION=us-east-1
S3_USE_SSL=false

# Логин/пароль для MinIO (должны совпадать с S3_ACCESS_KEY/S3_SECRET_KEY)
MINIO_ROOT_USER=replace-with-strong-access-key
MINIO_ROOT_PASSWORD=replace-with-strong-secret-key

# Публикация MinIO (по умолчанию только на 127.0.0.1)
MINIO_HOST=127.0.0.1
MINIO_PORT=9000
MINIO_CONSOLE_PORT=9001
```

Для Docker удобнее использовать `GOOGLE_SHEETS_CREDENTIALS_JSON`, а не файл `credentials.json`. JSON должен быть в одну строку. На локальной машине его можно получить так:

```bash
python -c "import json; print(json.dumps(json.load(open('credentials.json', encoding='utf-8')), separators=(',', ':')))"
```

Важно про MinIO и S3:

- `S3_ACCESS_KEY` / `S3_SECRET_KEY` должны совпадать с `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD` — это один и тот же пользователь, под которым API ходит в бакет.
- Бакет с именем `S3_BUCKET` создаётся автоматически при старте API (`ensure_bucket` в `lifespan`). Если MinIO недоступен, API не стартует.
- Файлы пользователя и БД сессий лежат на именованных томах `minio_data` и `app_data` — они переживают `docker compose down` (но не `down -v`).

## 3. Настроить GitHub Secrets

В репозитории откройте `Settings -> Secrets and variables -> Actions -> New repository secret` и добавьте:

```text
SSH_HOST=YOUR_SERVER_IP
SSH_USER=deploy
SSH_KEY=<private ssh key>
SSH_PORT=22
DEPLOY_PATH=/home/deploy/stal-analogs-storage
```

Секреты приложения в GitHub добавлять не нужно: они лежат на сервере в `.env`.

## 4. Запустить первый деплой

Смержите изменения в `main` или `master`, либо запустите workflow вручную:

```text
GitHub -> Actions -> CI/CD -> Run workflow
```

После успешного workflow проверьте сервер:

```bash
cd /home/deploy/stal-analogs-storage
docker compose ps
docker compose logs -f api
docker compose logs -f minio
curl http://127.0.0.1:8000/health
```

Ожидаемый ответ:

```json
{ "status": "ok", "version": "0.1.0" }
```

Проверьте, что MinIO здоров и бакет создан:

```bash
docker compose exec minio mc alias set local http://127.0.0.1:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD"
docker compose exec minio mc ls local
```

Веб-консоль MinIO доступна на `http://127.0.0.1:9001` (логин/пароль из `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD`). Если хотите достучаться до неё с локальной машины через SSH-туннель:

```bash
ssh -L 9001:127.0.0.1:9001 deploy@YOUR_SERVER_IP
```

## 5. Подключить другой контейнер на этом же сервере

`docker-compose.yml` создаёт сеть `stal-analogs-storage`. Другие compose-проекты (например, Telegram-бот) могут подключиться к ней без `host.docker.internal` и без `APP_HOST=0.0.0.0`.

В `docker-compose.yml` бота:

```yaml
services:
  bot:
    # ...
    networks:
      - stal-analogs-storage

networks:
  stal-analogs-storage:
    external: true
```

URL API для бота:

```text
http://stal-analogs-storage-api:8000/agent/command
```

Проверка с сервера после `docker compose up -d` в обоих проектах:

```bash
docker network inspect stal-analogs-storage --format '{{range .Containers}}{{.Name}} {{end}}'
# в контейнере бота:
docker compose exec bot curl -s http://stal-analogs-storage-api:8000/health
```

`APP_HOST=127.0.0.1` при этом можно оставить: порт на хосте нужен только для `curl`/nginx, а бот ходит напрямую в контейнер по внутренней сети Docker.

## 6. Опубликовать наружу

Рекомендуемый вариант - nginx или другой reverse proxy на сервере, а контейнер оставить на `127.0.0.1:8000`.

Пример nginx:

```nginx
server {
    listen 80;
    server_name example.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Если хотите открыть FastAPI напрямую без nginx, в `.env` поменяйте:

```env
APP_HOST=0.0.0.0
APP_PORT=8000
```

И откройте порт:

```bash
ufw allow OpenSSH
ufw allow 8000/tcp
ufw enable
```

Если хотите открыть MinIO наружу (например, для прямого аплоада из других сервисов), либо публикуйте через nginx с TLS на отдельном поддомене, либо в `.env` поменяйте `MINIO_HOST=0.0.0.0` и откройте порты `9000/9001` в фаерволе. Делайте это только с надёжными `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD`.

## Полезные команды

```bash
docker compose ps
docker compose logs -f api
docker compose logs -f minio
docker compose restart api
docker compose pull && docker compose up -d
docker image prune -f
```

Бэкап важных данных:

```bash
# SQLite с сессиями и историей
docker run --rm -v stal-analogs-storage_app_data:/data -v "$PWD":/backup alpine \
    tar czf /backup/sessions-$(date +%F).tgz -C /data .

# Файлы агента из MinIO
docker run --rm -v stal-analogs-storage_minio_data:/data -v "$PWD":/backup alpine \
    tar czf /backup/minio-$(date +%F).tgz -C /data .
```

Если нужно полностью очистить контекст сессий и загруженные файлы, остановите стек и удалите тома:

```bash
docker compose down
docker volume rm stal-analogs-storage_app_data stal-analogs-storage_minio_data
docker compose up -d
```
