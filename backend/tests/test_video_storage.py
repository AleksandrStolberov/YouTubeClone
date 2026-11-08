from datetime import timedelta
from io import BytesIO

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.s3 import S3Storage, normalize_minio_endpoint
from app.schemas.video import VideoCreate, VideoUpdate
from app.services.video import (
    VideoValidationError,
    resolve_thumbnail_type,
    resolve_video_type,
)


def test_normalize_docker_endpoint_without_scheme() -> None:
    host, secure = normalize_minio_endpoint("minio:9000")
    assert host == "minio:9000"
    assert secure is None


def test_normalize_strips_scheme_and_trailing_slash() -> None:
    assert normalize_minio_endpoint("http://minio:9000/") == ("minio:9000", False)
    assert normalize_minio_endpoint("https://minio:9000") == ("minio:9000", True)


def test_normalize_rejects_path() -> None:
    with pytest.raises(ValueError):
        normalize_minio_endpoint("http://minio:9000/videos")


def test_storage_uses_docker_host_and_secure_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class FakeMinio:
        def __init__(self, endpoint: str, *, access_key: str, secret_key: str, secure: bool) -> None:
            captured["endpoint"] = endpoint
            captured["access_key"] = access_key
            captured["secret_key"] = secret_key
            captured["secure"] = secure

    monkeypatch.setattr("app.core.s3.Minio", FakeMinio)
    settings = Settings(
        _env_file=None,
        minio_endpoint="minio:9000",
        minio_access_key="minioadmin",
        minio_secret_key="minioadmin",
        minio_secure=False,
        minio_bucket="videos",
        minio_thumbnails_bucket="thumbnails",
    )
    storage = S3Storage.from_settings(settings)
    assert captured == {
        "endpoint": "minio:9000",
        "access_key": "minioadmin",
        "secret_key": "minioadmin",
        "secure": False,
    }
    assert storage.video_bucket == "videos"
    assert storage.thumbnail_bucket == "thumbnails"


def test_scheme_overrides_secure_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class FakeMinio:
        def __init__(self, endpoint: str, *, access_key: str, secret_key: str, secure: bool) -> None:
            captured["endpoint"] = endpoint
            captured["secure"] = secure

    monkeypatch.setattr("app.core.s3.Minio", FakeMinio)
    S3Storage(
        endpoint="http://minio:9000",
        access_key="key",
        secret_key="secret",
        secure=True,
        video_bucket="videos",
        thumbnail_bucket="thumbnails",
    )
    assert captured["endpoint"] == "minio:9000"
    assert captured["secure"] is False


def test_ensure_buckets_creates_only_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    created: list[str] = []

    class FakeMinio:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def bucket_exists(self, bucket: str) -> bool:
            return bucket == "videos"

        def make_bucket(self, bucket: str) -> None:
            created.append(bucket)

    monkeypatch.setattr("app.core.s3.Minio", FakeMinio)
    storage = S3Storage(
        endpoint="minio:9000",
        access_key="key",
        secret_key="secret",
        secure=False,
        video_bucket="videos",
        thumbnail_bucket="thumbnails",
    )
    storage.ensure_buckets()
    assert created == ["thumbnails"]


def test_put_presign_and_delete(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, tuple, dict]] = []

    class FakeMinio:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def put_object(self, *args, **kwargs):
            calls.append(("put", args, kwargs))

        def presigned_get_object(self, *args, **kwargs) -> str:
            calls.append(("presign", args, kwargs))
            return "http://minio:9000/videos/a.mp4?X-Amz-Signature=test"

        def remove_object(self, *args, **kwargs) -> None:
            calls.append(("delete", args, kwargs))

    monkeypatch.setattr("app.core.s3.Minio", FakeMinio)
    storage = S3Storage(
        endpoint="minio:9000",
        access_key="key",
        secret_key="secret",
        secure=False,
        video_bucket="videos",
        thumbnail_bucket="thumbnails",
    )
    payload = BytesIO(b"video")
    assert storage.put_object("videos", "a.mp4", payload, 5, "video/mp4") == "a.mp4"
    expires = timedelta(minutes=15)
    url = storage.presigned_url("videos", "a.mp4", expires=expires)
    storage.delete_object("thumbnails", "a.jpg")

    assert url.startswith("http://minio:9000/")
    assert calls[0][0] == "put"
    assert calls[0][1][:4] == ("videos", "a.mp4", payload, 5)
    assert calls[0][2] == {"content_type": "video/mp4"}
    assert calls[1][2]["expires"] == expires
    assert calls[2][1] == ("thumbnails", "a.jpg")


@pytest.mark.parametrize(
    ("filename", "content_type", "expected"),
    [
        ("clip.mp4", "video/mp4", ("video/mp4", ".mp4")),
        ("clip.webm", "video/webm", ("video/webm", ".webm")),
        ("CLIP.MP4", "application/octet-stream", ("video/mp4", ".mp4")),
        ("clip.webm", None, ("video/webm", ".webm")),
    ],
)
def test_resolve_video_type(filename: str, content_type: str | None, expected: tuple[str, str]) -> None:
    assert resolve_video_type(filename, content_type) == expected


@pytest.mark.parametrize(
    ("filename", "content_type"),
    [
        ("clip.avi", "video/avi"),
        ("clip.mkv", "video/mp4"),
        ("clip.txt", "text/plain"),
        ("clip", "application/octet-stream"),
    ],
)
def test_resolve_video_type_rejects_other_formats(filename: str, content_type: str) -> None:
    with pytest.raises(VideoValidationError) as exc_info:
        resolve_video_type(filename, content_type)
    assert exc_info.value.status_code == 415


def test_resolve_thumbnail_accepts_jpeg_alias() -> None:
    assert resolve_thumbnail_type("cover.jpeg", "image/jpeg") == ("image/jpeg", ".jpg")
    assert resolve_thumbnail_type("cover.png", None) == ("image/png", ".png")


def test_video_create_strips_title_and_blank_description() -> None:
    data = VideoCreate(title="  Demo  ", description="  ", is_private=True)
    assert data.title == "Demo"
    assert data.description is None
    assert data.is_private is True


def test_video_create_rejects_empty_title() -> None:
    with pytest.raises(ValidationError):
        VideoCreate(title="   ", description=None)


def test_video_update_allows_partial_payload() -> None:
    data = VideoUpdate(is_private=False)
    assert data.model_dump(exclude_unset=True) == {"is_private": False}
