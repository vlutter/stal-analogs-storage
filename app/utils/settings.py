from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_title: str = "STAL Analogs Storage"
    app_version: str = "0.1.0"
    debug: bool = False
    api_token: str = ""

    google_sheets_spreadsheet_id: str = ""
    google_sheets_credentials_file: str = "credentials.json"
    google_sheets_credentials_json: str = ""
    google_sheets_sheet_name: str = "Лист1"

    openai_api_key: str = ""
    openai_model: str = "gpt-4o"
    log_level: str = "INFO"
    log_file: str = "logs/app.log"
    log_max_bytes: int = 5 * 1024 * 1024
    log_backup_count: int = 5

    sessions_db_path: str = "data/sessions.db"
    agent_history_limit: int = 10
    agent_session_ttl_minutes: int = 30

    s3_endpoint_url: str = ""
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_bucket: str = "agent-files"
    s3_region: str = "us-east-1"
    s3_use_ssl: bool = False

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
