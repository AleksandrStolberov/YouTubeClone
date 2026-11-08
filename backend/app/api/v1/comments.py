import uuid
from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_optional_user, unauthorized
from app.core.database import get_db
from app.models import User
from app.schemas.interaction import CommentCreate, CommentRead
from app.services.interaction import (
    CommentForbiddenError,
    CommentNotFoundError,
    add_comment,
    list_comments,
    remove_comment,
)
from app.services.video import VideoForbiddenError, VideoNotFoundError

router = APIRouter(tags=["comments"])


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


@router.post(
    "/videos/{video_id}/comments",
    response_model=CommentRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_comment(
    video_id: uuid.UUID,
    payload: CommentCreate,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> CommentRead:
    """Add a comment. Only an authenticated user can post."""
    try:
        return await add_comment(session, video_id, current_user, payload)
    except (VideoNotFoundError, VideoForbiddenError) as exc:
        _raise_video_access(exc, current_user)


@router.get("/videos/{video_id}/comments", response_model=list[CommentRead])
async def read_comments(
    video_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
    viewer: Annotated[User | None, Depends(get_optional_user)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[CommentRead]:
    """List comments for a video, newest first."""
    try:
        return await list_comments(session, video_id, viewer, limit=limit, offset=offset)
    except (VideoNotFoundError, VideoForbiddenError) as exc:
        _raise_video_access(exc, viewer)


@router.delete("/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_comment(
    comment_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> None:
    """Delete a comment. Allowed for the author, a moderator, or an admin."""
    try:
        await remove_comment(session, comment_id, current_user)
    except CommentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comment not found") from exc
    except CommentForbiddenError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions",
        ) from exc
