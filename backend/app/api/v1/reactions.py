import uuid
from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_optional_user, unauthorized
from app.core.database import get_db
from app.models import User
from app.schemas.interaction import ReactionCreate, VideoReactionsSummary
from app.services.interaction import get_video_reactions, set_video_reaction
from app.services.video import VideoForbiddenError, VideoNotFoundError

router = APIRouter(prefix="/videos", tags=["reactions"])


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


@router.post("/{video_id}/reaction", response_model=VideoReactionsSummary)
async def react_to_video(
    video_id: uuid.UUID,
    payload: ReactionCreate,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> VideoReactionsSummary:
    """Toggle a like or a dislike.

    A missing reaction is created. The same reaction sent again is removed.
    The opposite reaction replaces the current one.
    """
    try:
        return await set_video_reaction(session, video_id, current_user, payload.is_like)
    except (VideoNotFoundError, VideoForbiddenError) as exc:
        _raise_video_access(exc, current_user)


@router.get("/{video_id}/reactions", response_model=VideoReactionsSummary)
async def read_video_reactions(
    video_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
    viewer: Annotated[User | None, Depends(get_optional_user)],
) -> VideoReactionsSummary:
    """Return like and dislike counters and the caller's reaction when signed in."""
    try:
        return await get_video_reactions(session, video_id, viewer)
    except (VideoNotFoundError, VideoForbiddenError) as exc:
        _raise_video_access(exc, viewer)
