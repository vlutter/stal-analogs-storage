# Деплой на Ubuntu 24.04 через Docker и GitHub Actions

Схема деплоя:

1. GitHub Actions собирает Docker image.
2. Image публикуется в GitHub Container Registry: `ghcr.io/<owner>/<repo>`.
3. Workflow подключается к серверу по SSH.
4. На сервере запускается `docker compose pull && docker compose up -d`.

Секреты приложения (`API_TOKEN`, `OPENAI_API_KEY`, Google credentials) хранятся только на сервере в `.env`.

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
```

Для Docker удобнее использовать `GOOGLE_SHEETS_CREDENTIALS_JSON`, а не файл `credentials.json`. JSON должен быть в одну строку. На локальной машине его можно получить так:

```bash
python -c "import json; print(json.dumps(json.load(open('credentials.json', encoding='utf-8')), separators=(',', ':')))"
```

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
curl http://127.0.0.1:8000/health
```

Ожидаемый ответ:

```json
{"status":"ok","version":"0.1.0"}
```

## 5. Опубликовать наружу

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

## Полезные команды

```bash
docker compose ps
docker compose logs -f api
docker compose restart api
docker compose pull && docker compose up -d
docker image prune -f
```
