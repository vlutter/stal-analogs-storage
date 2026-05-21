import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse

from app.api import agent, mappings, search
from app.deps.auth import verify_api_token
from app.repositories.sheets_repository import SheetsRepositoryError
from app.utils.logging import setup_logging
from app.utils.settings import settings

setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not settings.api_token:
        raise RuntimeError("API_TOKEN is not configured. Set it in .env before starting the server.")
    yield


app = FastAPI(
    title=settings.app_title,
    version=settings.app_version,
    description="API для хранения и поиска соответствий артикулов STAL",
    debug=settings.debug,
    lifespan=lifespan,
)

app.include_router(mappings.router, dependencies=[Depends(verify_api_token)])
app.include_router(search.router, dependencies=[Depends(verify_api_token)])
app.include_router(agent.router, dependencies=[Depends(verify_api_token)])


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
