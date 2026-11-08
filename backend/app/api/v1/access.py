import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models import User
from app.schemas.moderation import AllowedUserRead, WhitelistAddRequest
from app.services.access import (
    AccessAlreadyGrantedError,
    AccessForbiddenError,
    AccessNotFoundError,
    UserNotFoundError,
    grant_access,
    list_access,
    revoke_access,
)
from app.services.video import VideoNotFoundError

router = APIRouter(tags=["access"])


@router.post(
    "/videos/{video_id}/access",
    response_model=AllowedUserRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_video_access(
    video_id: uuid.UUID,
    payload: WhitelistAddRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> AllowedUserRead:
    """Grant a user access to a private video. Only the video owner may do this."""
    try:
        return await grant_access(session, video_id, current_user, payload.user_id)
    except VideoNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found") from exc
    except UserNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found") from exc
    except AccessForbiddenError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions",
        ) from exc
    except AccessAlreadyGrantedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User already has access",
        ) from exc


@router.delete("/videos/{video_id}/access/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_video_access(
    video_id: uuid.UUID,
    user_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> None:
    """Remove a user from a private video whitelist. Only the owner may do this."""
    try:
        await revoke_access(session, video_id, current_user, user_id)
    except VideoNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found") from exc
    except AccessNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Access entry not found") from exc
    except AccessForbiddenError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions",
        ) from exc


@router.get("/videos/{video_id}/access", response_model=list[AllowedUserRead])
async def read_video_access(
    video_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> list[AllowedUserRead]:
    """List users allowed to watch a private video. Only the owner may do this."""
    try:
        return await list_access(session, video_id, current_user)
    except VideoNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found") from exc
    except AccessForbiddenError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions",
        ) from exc
