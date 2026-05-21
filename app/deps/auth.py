import logging
from secrets import compare_digest
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.utils.settings import settings

logger = logging.getLogger(__name__)

bearer_scheme = HTTPBearer(auto_error=False, scheme_name="Bearer")


async def verify_api_token(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> None:
    """Проверяет заголовок Authorization: Bearer <token>."""
    if credentials is None:
        logger.warning("API request rejected: missing Authorization header")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing API token",
        )

    expected = settings.api_token
    provided = credentials.credentials

    if not expected or not compare_digest(provided, expected):
        logger.warning("API request rejected: invalid Bearer token")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing API token",
        )
