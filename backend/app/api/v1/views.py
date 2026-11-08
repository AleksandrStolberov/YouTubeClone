import uuid
from typing import Annotated, NoReturn

from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_optional_user, unauthorized
from app.core.database import get_db
from app.models import User, Video
from app.schemas.history import ViewRecordRequest
from app.schemas.video import VideoRead
from app.services.history import record_view
from app.services.video import VideoForbiddenError, VideoNotFoundError

router = APIRouter(prefix="/videos", tags=["views"])


def _raise_video_access(exc: Exception, viewer: User | None) -> NoReturn:
    if isinstance(exc, VideoNotFoundError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found") from exc
    if isinstance(exc, VideoForbiddenError):
        if viewer is None:
            raise unauthorized() from exc
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions",
        ) from exc
    raise exc


@router.post("/{video_id}/view", response_model=VideoRead)
async def record_video_view(
    video_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
    viewer: Annotated[User | None, Depends(get_optional_user)],
    payload: Annotated[ViewRecordRequest | None, Body()] = None,
) -> Video:
    """Count a view.

    Guests only increment ``views_count``. A signed-in user also creates or
    updates their watch-history row for this video.
    """
    progress = None if payload is None else payload.progress_seconds
    try:
        return await record_view(session, video_id, viewer, progress)
    except (VideoNotFoundError, VideoForbiddenError) as exc:
        _raise_video_access(exc, viewer)
