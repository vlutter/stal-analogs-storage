import logging
from logging.config import dictConfig
from pathlib import Path

from app.utils.settings import settings


def setup_logging() -> None:
    log_file = Path(settings.log_file)
    log_file.parent.mkdir(parents=True, exist_ok=True)

    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "default": {
                    "format": "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
                },
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "level": settings.log_level,
                    "formatter": "default",
                },
                "file": {
                    "class": "logging.handlers.RotatingFileHandler",
                    "level": settings.log_level,
                    "formatter": "default",
                    "filename": str(log_file),
                    "encoding": "utf-8",
                    "maxBytes": settings.log_max_bytes,
                    "backupCount": settings.log_backup_count,
                },
            },
            "root": {
                "level": settings.log_level,
                "handlers": ["console", "file"],
            },
        }
    )

    logging.getLogger(__name__).info(
        "Logging initialized, file=%s, max_bytes=%d, backups=%d",
        log_file,
        settings.log_max_bytes,
        settings.log_backup_count,
    )
