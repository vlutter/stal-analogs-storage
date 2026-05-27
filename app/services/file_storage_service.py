"""S3-compatible file storage (MinIO) for agent attached files."""

from __future__ import annotations

import logging
import mimetypes
from uuid import uuid4

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from app.utils.settings import settings

logger = logging.getLogger(__name__)


class FileStorageError(RuntimeError):
    """Raised when an S3/MinIO operation cannot be completed."""


class FileStorageService:
    def __init__(
        self,
        endpoint_url: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
        bucket: str | None = None,
        region: str | None = None,
        use_ssl: bool | None = None,
    ) -> None:
        self._endpoint_url = endpoint_url or settings.s3_endpoint_url
        self._access_key = access_key or settings.s3_access_key
        self._secret_key = secret_key or settings.s3_secret_key
        self._bucket = bucket or settings.s3_bucket
        self._region = region or settings.s3_region
        self._use_ssl = settings.s3_use_ssl if use_ssl is None else use_ssl

        if not self._endpoint_url or not self._access_key or not self._secret_key:
            raise FileStorageError(
                "S3 storage is not configured. Set S3_ENDPOINT_URL, S3_ACCESS_KEY, S3_SECRET_KEY."
            )

        self._client = boto3.client(
            "s3",
            endpoint_url=self._endpoint_url,
            aws_access_key_id=self._access_key,
            aws_secret_access_key=self._secret_key,
            region_name=self._region,
            use_ssl=self._use_ssl,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

    @property
    def bucket(self) -> str:
        return self._bucket

    def ensure_bucket(self) -> None:
        """Create the bucket if it does not exist."""
        try:
            self._client.head_bucket(Bucket=self._bucket)
            logger.info("S3 bucket '%s' already exists", self._bucket)
            return
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code", "")
            if error_code not in {"404", "NoSuchBucket", "NotFound"}:
                logger.exception("Failed to check S3 bucket '%s'", self._bucket)
                raise FileStorageError(f"Cannot access S3 bucket '{self._bucket}'") from exc

        try:
            self._client.create_bucket(Bucket=self._bucket)
            logger.info("Created S3 bucket '%s'", self._bucket)
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code", "")
            if error_code in {"BucketAlreadyOwnedByYou", "BucketAlreadyExists"}:
                logger.info("S3 bucket '%s' already exists (race)", self._bucket)
                return
            logger.exception("Failed to create S3 bucket '%s'", self._bucket)
            raise FileStorageError(f"Cannot create S3 bucket '{self._bucket}'") from exc

    def upload(
        self,
        filename: str,
        file_bytes: bytes,
        content_type: str | None = None,
    ) -> tuple[str, str]:
        """Upload bytes to S3 under a unique key. Returns (s3_key, content_type)."""
        key = f"{uuid4().hex}/{filename}"
        ctype = content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"
        try:
            self._client.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=file_bytes,
                ContentType=ctype,
            )
        except ClientError as exc:
            logger.exception("Failed to upload '%s' to S3 (key=%s)", filename, key)
            raise FileStorageError(f"Cannot upload file '{filename}' to S3") from exc
        logger.info("Uploaded '%s' to S3 as key=%s (%d bytes)", filename, key, len(file_bytes))
        return key, ctype

    def download(self, s3_key: str) -> bytes:
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=s3_key)
            return response["Body"].read()
        except ClientError as exc:
            logger.exception("Failed to download key=%s from S3", s3_key)
            raise FileStorageError(f"Cannot download file '{s3_key}' from S3") from exc
