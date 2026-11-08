import asyncio
import os
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import Response
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_optional_user, unauthorized
from app.core.database import get_db
from app.core.s3 import S3Storage, StorageError, get_s3_client
from app.models import User, Video
from app.schemas.video import VideoCreate, VideoRead
from app.services.video import (
    ByteRangeError,
    IncomingFile,
    VideoForbiddenError,
    VideoNotFoundError,
    VideoValidationError,
    create_video,
    delete_video,
    describe_video_file,
    get_video,
    list_public_videos,
    load_thumbnail,
    parse_byte_range,
)

router = APIRouter(prefix="/videos", tags=["videos"])


def _parse_video_form(
    title: str,
    description: str | None,
    is_private: bool,
    category: str | None,
    tags: str | None,
) -> VideoCreate:
    try:
        return VideoCreate(
            title=title,
            description=description,
            is_private=is_private,
            category=category,
            tags=tags or [],
        )
    except ValidationError as exc:
        raise RequestValidationError(exc.errors()) from exc


def _incoming_file(upload: UploadFile) -> IncomingFile:
    stream = upload.file
    stream.seek(0, os.SEEK_END)
    size = stream.tell()
    stream.seek(0)
    content_type = upload.content_type
    if content_type:
        content_type = content_type.split(";", 1)[0].strip().lower() or None
    return IncomingFile(
        stream=stream,
        size=size,
        filename=upload.filename,
        content_type=content_type,
    )


def _thumbnail_provided(upload: UploadFile | None) -> bool:
    if upload is None:
        return False
    if (upload.filename or "").strip():
        return True
    return bool(upload.size)


@router.post("/upload", response_model=VideoRead, status_code=status.HTTP_201_CREATED)
async def upload_video(
    video: Annotated[UploadFile, File(description="Video file (mp4 or webm)")],
    title: Annotated[str, Form()],
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    storage: Annotated[S3Storage, Depends(get_s3_client)],
    description: Annotated[str | None, Form()] = None,
    is_private: Annotated[bool, Form()] = False,
    category: Annotated[str | None, Form()] = None,
    tags: Annotated[str | None, Form()] = None,
    thumbnail: Annotated[
        UploadFile | None,
        File(description="Optional cover image (jpeg, png, or webp)"),
    ] = None,
) -> Video:
    """Store a video in MinIO and its metadata in PostgreSQL."""
    payload = _parse_video_form(title, description, is_private, category, tags)
    cover = _incoming_file(thumbnail) if _thumbnail_provided(thumbnail) else None
    try:
        return await create_video(
            session,
            storage,
            current_user,
            payload,
            _incoming_file(video),
            cover,
        )
    except VideoValidationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except StorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Object storage is unavailable",
        ) from exc


@router.get("", response_model=list[VideoRead])
async def list_videos(
    session: Annotated[AsyncSession, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[Video]:
    """List public videos that are not banned, newest first."""
    return await list_public_videos(session, limit=limit, offset=offset)


@router.get("/{video_id}/thumbnail")
async def read_video_thumbnail(
    video_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
    storage: Annotated[S3Storage, Depends(get_s3_client)],
    viewer: Annotated[User | None, Depends(get_optional_user)],
) -> Response:
    """Stream the cover image stored in the thumbnails bucket."""
    try:
        cover = await load_thumbnail(session, storage, video_id, viewer)
    except VideoNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found") from exc
    except VideoForbiddenError as exc:
        if viewer is None:
            raise unauthorized() from exc
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions",
        ) from exc
    except StorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Object storage is unavailable",
        ) from exc
    return Response(
        content=cover.data,
        media_type=cover.media_type,
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.get("/{video_id}/stream")
async def stream_video(
    video_id: uuid.UUID,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
    storage: Annotated[S3Storage, Depends(get_s3_client)],
    viewer: Annotated[User | None, Depends(get_optional_user)],
) -> Response:
    """Stream the video file, honoring a single HTTP Range request."""
    try:
        stored = await describe_video_file(session, storage, video_id, viewer)
    except VideoNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found") from exc
    except VideoForbiddenError as exc:
        if viewer is None:
            raise unauthorized() from exc
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions",
        ) from exc
    except StorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Object storage is unavailable",
        ) from exc

    try:
        start, end = parse_byte_range(request.headers.get("range"), stored.size)
    except ByteRangeError as exc:
        return Response(
            status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE,
            headers={
                "Accept-Ranges": "bytes",
                "Content-Range": f"bytes */{exc.size}",
            },
        )

    headers = {"Accept-Ranges": "bytes", "Content-Length": "0"}
    if end < start:
        return Response(status_code=status.HTTP_200_OK, media_type=stored.media_type, headers=headers)

    try:
        payload = await asyncio.to_thread(
            storage.read_object_range,
            stored.bucket,
            stored.key,
            start,
            end - start + 1,
        )
    except StorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Object storage is unavailable",
        ) from exc

    headers["Content-Length"] = str(len(payload))
    status_code = status.HTTP_200_OK
    if request.headers.get("range"):
        status_code = status.HTTP_206_PARTIAL_CONTENT
        headers["Content-Range"] = f"bytes {start}-{start + len(payload) - 1}/{stored.size}"
    return Response(content=payload, status_code=status_code, media_type=stored.media_type, headers=headers)


@router.get("/{video_id}", response_model=VideoRead)
async def read_video(
    video_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
    viewer: Annotated[User | None, Depends(get_optional_user)],
) -> Video:
    """Return metadata for one video.

    Public videos are visible without a token. Private videos are visible to
    the author, a moderator, an admin, or a user on the whitelist. Banned
    videos are hidden from everyone except the author and staff.
    """
    try:
        return await get_video(session, video_id, viewer)
    except VideoNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found") from exc
    except VideoForbiddenError as exc:
        if viewer is None:
            raise unauthorized() from exc
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions",
        ) from exc


@router.delete("/{video_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_video(
    video_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    storage: Annotated[S3Storage, Depends(get_s3_client)],
) -> None:
    """Delete the MinIO objects and the database row.

    Allowed for the author and for users with the moderator or admin role.
    """
    try:
        await delete_video(session, storage, video_id, current_user)
    except VideoNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found") from exc
    except VideoForbiddenError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions",
        ) from exc
    except StorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Object storage is unavailable",
        ) from exc
