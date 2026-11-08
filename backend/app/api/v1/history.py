import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models import User
from app.schemas.history import PaginatedHistoryResponse
from app.services.history import (
    HistoryNotFoundError,
    clear_watch_history,
    list_watch_history,
    remove_watch_history_item,
)

router = APIRouter(prefix="/users/me/history", tags=["history"])


@router.get("", response_model=PaginatedHistoryResponse)
async def read_watch_history(
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PaginatedHistoryResponse:
    """List videos the current user has watched, most recent first."""
    return await list_watch_history(session, current_user, limit=limit, offset=offset)


@router.delete("/{video_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_watch_history_item(
    video_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> None:
    """Remove one video from the current user's watch history."""
    try:
        await remove_watch_history_item(session, current_user, video_id)
    except HistoryNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Watch history entry not found",
        ) from exc


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def delete_watch_history(
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> None:
    """Remove every video from the current user's watch history."""
    await clear_watch_history(session, current_user)
