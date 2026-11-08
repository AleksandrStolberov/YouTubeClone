import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.channel import ChannelProfileRead
from app.services.channel import ChannelNotFoundError, get_channel_profile

router = APIRouter(prefix="/channels", tags=["channels"])


@router.get("/{user_id}", response_model=ChannelProfileRead)
async def read_channel(
    user_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ChannelProfileRead:
    """Return public channel statistics.

    The response includes the subscriber total, the summed views of every
    public video, and the number of videos on the channel.
    """
    try:
        return await get_channel_profile(session, user_id)
    except ChannelNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found") from exc
