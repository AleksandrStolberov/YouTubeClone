import logging
from datetime import timedelta
from typing import BinaryIO

from minio import Minio
from minio.error import MinioException, S3Error
from urllib3.exceptions import HTTPError

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

_ALREADY_EXISTS = frozenset({"BucketAlreadyOwnedByYou", "BucketAlreadyExists"})


class StorageError(Exception):
    """Raised when MinIO cannot complete a request."""


def normalize_minio_endpoint(endpoint: str) -> tuple[str, bool | None]:
    """Return ``host:port`` and a secure flag when the value includes a scheme.

    The Docker network address is ``minio:9000`` with no scheme. A scheme, if
    present, decides TLS and is stripped because the MinIO SDK rejects URLs.
    """
    raw = endpoint.strip()
    if not raw:
        raise ValueError("MinIO endpoint is empty")

    secure: bool | None = None
    lowered = raw.lower()
    if lowered.startswith("https://"):
        secure = True
        raw = raw[len("https://") :]
    elif lowered.startswith("http://"):
        secure = False
        raw = raw[len("http://") :]

    raw = raw.rstrip("/")
    if "/" in raw:
        raise ValueError("MinIO endpoint must be host:port without a path")
    return raw, secure


class S3Storage:
    """Thin MinIO wrapper used by the video service."""

    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        secure: bool,
        video_bucket: str,
        thumbnail_bucket: str,
    ) -> None:
        host, secure_override = normalize_minio_endpoint(endpoint)
        self.client = Minio(
            host,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure if secure_override is None else secure_override,
        )
        self.video_bucket = video_bucket
        self.thumbnail_bucket = thumbnail_bucket

    @classmethod
    def from_settings(cls, settings: Settings) -> "S3Storage":
        return cls(
            endpoint=settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_secure,
            video_bucket=settings.minio_bucket,
            thumbnail_bucket=settings.minio_thumbnails_bucket,
        )

    def ensure_buckets(self) -> None:
        """Create the video and thumbnail buckets when they are missing."""
        for bucket in (self.video_bucket, self.thumbnail_bucket):
            self._ensure_bucket(bucket)

    def put_object(
        self,
        bucket: str,
        key: str,
        data: BinaryIO,
        length: int,
        content_type: str,
    ) -> str:
        self._run(
            self.client.put_object,
            bucket,
            key,
            data,
            length,
            content_type=content_type,
        )
        return key

    def presigned_url(
        self,
        bucket: str,
        key: str,
        expires: timedelta = timedelta(hours=1),
    ) -> str:
        url = self._run(
            self.client.presigned_get_object,
            bucket,
            key,
            expires=expires,
        )
        return str(url)

    def delete_object(self, bucket: str, key: str) -> None:
        self._run(self.client.remove_object, bucket, key)

    def _ensure_bucket(self, bucket: str) -> None:
        if self._run(self.client.bucket_exists, bucket):
            return
        try:
            self.client.make_bucket(bucket)
        except S3Error as exc:
            if exc.code in _ALREADY_EXISTS:
                return
            logger.exception("Failed to create bucket %s", bucket)
            raise StorageError("Object storage request failed") from exc
        except (MinioException, HTTPError, OSError, TimeoutError) as exc:
            logger.exception("Failed to create bucket %s", bucket)
            raise StorageError("Object storage request failed") from exc

    def _run(self, func, *args, **kwargs):
        try:
            return func(*args, **kwargs)
        except (MinioException, HTTPError, OSError, TimeoutError) as exc:
            logger.exception("MinIO request failed")
            raise StorageError("Object storage request failed") from exc


_storage: S3Storage | None = None


def get_s3_client() -> S3Storage:
    global _storage
    if _storage is None:
        _storage = S3Storage.from_settings(get_settings())
    return _storage
