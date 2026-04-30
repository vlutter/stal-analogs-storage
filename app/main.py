import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api import agent, mappings, search
from app.repositories.sheets_repository import SheetsRepositoryError
from app.utils.logging import setup_logging
from app.utils.settings import settings

setup_logging()
logger = logging.getLogger(__name__)


app = FastAPI(
    title=settings.app_title,
    version=settings.app_version,
    description="API для хранения и поиска соответствий артикулов STAL",
    debug=settings.debug,
)

app.include_router(mappings.router)
app.include_router(search.router)
app.include_router(agent.router)


@app.exception_handler(SheetsRepositoryError)
async def sheets_repository_error_handler(request: Request, exc: SheetsRepositoryError):
    logger.warning("Google Sheets operation failed for %s %s: %s", request.method, request.url.path, exc)
    return JSONResponse(
        status_code=503,
        content={"detail": "Google Sheets is temporarily unavailable. Please retry the request."},
    )


@app.get("/health", tags=["System"])
async def healthcheck():
    return {"status": "ok", "version": settings.app_version}
