import asyncio
import logging
import re
import uuid
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import BinaryIO

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.s3 import S3Storage, StorageError
from app.models import User, UserRole, Video, VideoAllowedUser
from app.schemas.video import VideoCreate

logger = logging.getLogger(__name__)

MAX_VIDEO_BYTES = 2 * 1024 * 1024 * 1024
MAX_THUMBNAIL_BYTES = 8 * 1024 * 1024

_VIDEO_TYPES = {
    "video/mp4": ".mp4",
    "video/webm": ".webm",
}
_VIDEO_EXTENSIONS = {extension: content_type for content_type, extension in _VIDEO_TYPES.items()}

_THUMBNAIL_TYPES = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/pjpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}
_THUMBNAIL_EXTENSIONS = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}
_STAFF_ROLES = {UserRole.MODERATOR.value, UserRole.ADMIN.value}
_BYTE_RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")


def public_video_filters():
    """Clauses for videos shown on public surfaces.

    Private videos and videos hidden by moderation stay out of feeds,
    search, and catalog lists.
    """
    return (Video.is_private.is_(False), Video.is_banned.is_(False))


class VideoNotFoundError(Exception):
    """Raised when the video id does not exist."""


class VideoForbiddenError(Exception):
    """Raised when the caller cannot view or delete the video."""


class ByteRangeError(Exception):
    """Raised when a Range header cannot be satisfied."""

    def __init__(self, size: int) -> None:
        self.size = size
        super().__init__("Invalid byte range")


class VideoValidationError(Exception):
    """Raised when the uploaded file or its metadata is rejected."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        self.status_code = status_code
        super().__init__(message)


@dataclass(frozen=True)
class IncomingFile:
    stream: BinaryIO
    size: int
    filename: str | None
    content_type: str | None


def resolve_video_type(filename: str | None, content_type: str | None) -> tuple[str, str]:
    """Return the stored content type and extension for an mp4 or webm file."""
    return _resolve_media(
        filename,
        content_type,
        types=_VIDEO_TYPES,
        extensions=_VIDEO_EXTENSIONS,
        message="Only mp4 and webm video files are allowed",
    )


def resolve_thumbnail_type(filename: str | None, content_type: str | None) -> tuple[str, str]:
    """Return the stored content type and extension for a cover image."""
    return _resolve_media(
        filename,
        content_type,
        types=_THUMBNAIL_TYPES,
        extensions=_THUMBNAIL_EXTENSIONS,
        message="Only jpeg, png, and webp images are allowed for the cover",
    )


async def create_video(
    session: AsyncSession,
    storage: S3Storage,
    author: User,
    data: VideoCreate,
    video_file: IncomingFile,
    thumbnail_file: IncomingFile | None = None,
) -> Video:
    content_type, extension = resolve_video_type(video_file.filename, video_file.content_type)
    _ensure_size(video_file.size, MAX_VIDEO_BYTES, "Video file")
    thumb_type: str | None = None
    thumb_ext: str | None = None
    if thumbnail_file is not None:
        thumb_type, thumb_ext = resolve_thumbnail_type(
            thumbnail_file.filename,
            thumbnail_file.content_type,
        )
        _ensure_size(thumbnail_file.size, MAX_THUMBNAIL_BYTES, "Cover image")

    video_id = uuid.uuid4()
    video_key = f"{author.id}/{video_id}{extension}"
    preview_key: str | None = None
    stored: list[tuple[str, str]] = []

    try:
        await asyncio.to_thread(
            storage.put_object,
            storage.video_bucket,
            video_key,
            video_file.stream,
            video_file.size,
            content_type,
        )
        stored.append((storage.video_bucket, video_key))

        if thumbnail_file is not None and thumb_type is not None and thumb_ext is not None:
            preview_key = f"{author.id}/{video_id}{thumb_ext}"
            await asyncio.to_thread(
                storage.put_object,
                storage.thumbnail_bucket,
                preview_key,
                thumbnail_file.stream,
                thumbnail_file.size,
                thumb_type,
            )
            stored.append((storage.thumbnail_bucket, preview_key))

        video = Video(
            id=video_id,
            title=data.title,
            description=data.description,
            s3_key=video_key,
            preview_s3_key=preview_key,
            is_private=data.is_private,
            category=data.category,
            tags=list(data.tags),
            user_id=author.id,
        )
        session.add(video)
        await session.commit()
    except Exception:
        await session.rollback()
        await _delete_stored(storage, stored)
        raise

    await session.refresh(video)
    return video


async def list_channel_videos(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    limit: int,
    offset: int,
) -> list[Video]:
    """List one author's public videos that are not banned, newest first."""
    stmt = (
        select(Video)
        .where(Video.user_id == user_id, *public_video_filters())
        .order_by(Video.created_at.desc(), Video.id.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def list_public_videos(
    session: AsyncSession,
    *,
    limit: int,
    offset: int,
) -> list[Video]:
    """List videos that are public and not banned, newest first."""
    stmt = (
        select(Video)
        .where(*public_video_filters())
        .order_by(Video.created_at.desc(), Video.id.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


@dataclass(frozen=True)
class StoredObject:
    data: bytes
    media_type: str


def parse_byte_range(header: str | None, size: int) -> tuple[int, int]:
    """Return an inclusive byte range. A missing header selects the whole object."""
    if size <= 0:
        return 0, -1
    if header is None or not header.strip():
        return 0, size - 1
    match = _BYTE_RANGE.match(header.strip())
    if match is None:
        raise ByteRangeError(size)
    start_text, end_text = match.group(1), match.group(2)
    if start_text == "" and end_text == "":
        raise ByteRangeError(size)
    if start_text == "":
        suffix = int(end_text)
        if suffix <= 0:
            raise ByteRangeError(size)
        start = max(size - suffix, 0)
        end = size - 1
    else:
        start = int(start_text)
        end = size - 1 if end_text == "" else int(end_text)
    if start < 0 or start >= size or end < start:
        raise ByteRangeError(size)
    return start, min(end, size - 1)


@dataclass(frozen=True)
class VideoFile:
    bucket: str
    key: str
    size: int
    media_type: str


async def describe_video_file(
    session: AsyncSession,
    storage: S3Storage,
    video_id: uuid.UUID,
    viewer: User | None,
) -> VideoFile:
    """Return the stored video object when the viewer may open it."""
    video = await get_video(session, video_id, viewer)
    size, media_type = await asyncio.to_thread(
        storage.stat_object,
        storage.video_bucket,
        video.s3_key,
    )
    return VideoFile(
        bucket=storage.video_bucket,
        key=video.s3_key,
        size=size,
        media_type=media_type,
    )


async def load_thumbnail(
    session: AsyncSession,
    storage: S3Storage,
    video_id: uuid.UUID,
    viewer: User | None,
) -> StoredObject:
    """Read a cover image the viewer is allowed to see."""
    video = await get_video(session, video_id, viewer)
    if not video.preview_s3_key:
        raise VideoNotFoundError
    data, media_type = await asyncio.to_thread(
        storage.read_object,
        storage.thumbnail_bucket,
        video.preview_s3_key,
    )
    return StoredObject(data=data, media_type=media_type)


async def get_video(
    session: AsyncSession,
    video_id: uuid.UUID,
    viewer: User | None,
) -> Video:
    """Return a video the viewer is allowed to open.

    A missing video, and a banned video for anyone except the author and
    staff, raise ``VideoNotFoundError``. A private video the viewer cannot
    open raises ``VideoForbiddenError``.
    """
    video = await session.get(Video, video_id)
    if video is None or (video.is_banned and not _bypasses_ban(viewer, video)):
        raise VideoNotFoundError
    if not await _can_view(session, video, viewer):
        raise VideoForbiddenError
    return video


async def delete_video(
    session: AsyncSession,
    storage: S3Storage,
    video_id: uuid.UUID,
    actor: User,
) -> None:
    video = await session.get(Video, video_id)
    if video is None:
        raise VideoNotFoundError
    if not _can_manage(actor, video):
        raise VideoForbiddenError

    await asyncio.to_thread(storage.delete_object, storage.video_bucket, video.s3_key)
    if video.preview_s3_key:
        await asyncio.to_thread(
            storage.delete_object,
            storage.thumbnail_bucket,
            video.preview_s3_key,
        )
    await session.delete(video)
    await session.commit()


def _resolve_media(
    filename: str | None,
    content_type: str | None,
    *,
    types: dict[str, str],
    extensions: dict[str, str],
    message: str,
) -> tuple[str, str]:
    extension = _extension(filename)
    media_type = (content_type or "").split(";", 1)[0].strip().lower()
    generic = media_type in {"", "application/octet-stream"}

    if media_type in types:
        expected = types[media_type]
        if extension and _canonical(extension, extensions) != _canonical(expected, extensions):
            raise VideoValidationError(message, status_code=415)
        return extensions.get(expected, media_type), expected

    if generic and extension in extensions:
        return extensions[extension], _canonical(extension, extensions)

    raise VideoValidationError(message, status_code=415)


def _extension(filename: str | None) -> str:
    name = (filename or "").replace("\\", "/").split("/")[-1]
    return PurePosixPath(name).suffix.lower()


def _canonical(extension: str, extensions: dict[str, str]) -> str:
    """Map aliases such as ``.jpeg`` to the extension stored in the object key."""
    if extension == ".jpeg" and ".jpg" in extensions:
        return ".jpg"
    if extension == ".jpg" and extension not in extensions and ".jpeg" in extensions:
        return ".jpeg"
    return extension


def _ensure_size(size: int, limit: int, label: str) -> None:
    if size <= 0:
        raise VideoValidationError(f"{label} is empty")
    if size > limit:
        raise VideoValidationError(f"{label} is too large", status_code=413)


def _role_name(user: User) -> str:
    role = user.role
    return role.value if isinstance(role, UserRole) else str(role)


def _can_manage(user: User, video: Video) -> bool:
    return user.id == video.user_id or _role_name(user) in _STAFF_ROLES


def _bypasses_ban(viewer: User | None, video: Video) -> bool:
    """Author, moderators, and admins can still open a banned video."""
    return viewer is not None and _can_manage(viewer, video)


async def visible_video_ids(
    session: AsyncSession,
    videos: list[Video],
    viewer: User | None,
) -> set[uuid.UUID]:
    """Return ids of videos this viewer is allowed to see.

    Banned videos stay visible to the author and to moderators or admins.
    Private videos stay visible to the author, staff, and the whitelist.
    """
    allowed: set[uuid.UUID] = set()
    hidden: list[uuid.UUID] = []
    for video in videos:
        if video.is_banned and not _bypasses_ban(viewer, video):
            continue
        if not video.is_private:
            allowed.add(video.id)
            continue
        if viewer is not None and _can_manage(viewer, video):
            allowed.add(video.id)
            continue
        if viewer is not None:
            hidden.append(video.id)
    if viewer is None or not hidden:
        return allowed
    granted = await session.scalars(
        select(VideoAllowedUser.video_id).where(
            VideoAllowedUser.user_id == viewer.id,
            VideoAllowedUser.video_id.in_(hidden),
        )
    )
    allowed.update(granted.all())
    return allowed


async def _can_view(session: AsyncSession, video: Video, viewer: User | None) -> bool:
    if not video.is_private:
        return True
    if viewer is None:
        return False
    if _can_manage(viewer, video):
        return True
    result = await session.execute(
        select(VideoAllowedUser.id).where(
            VideoAllowedUser.video_id == video.id,
            VideoAllowedUser.user_id == viewer.id,
        )
    )
    return result.scalar_one_or_none() is not None


async def _delete_stored(storage: S3Storage, stored: list[tuple[str, str]]) -> None:
    for bucket, key in reversed(stored):
        try:
            await asyncio.to_thread(storage.delete_object, bucket, key)
        except StorageError:
            logger.exception("Failed to roll back object %s/%s", bucket, key)
