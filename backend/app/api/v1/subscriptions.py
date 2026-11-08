import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_optional_user
from app.core.database import get_db
from app.models import User
from app.schemas.interaction import SubscribersCount, SubscriptionStatus
from app.services.interaction import (
    ChannelNotFoundError,
    SelfSubscriptionError,
    get_subscribers_count,
    subscription_state,
    toggle_subscription,
)

router = APIRouter(prefix="/users", tags=["subscriptions"])


@router.get("/{user_id}/subscription", response_model=SubscriptionStatus)
async def read_subscription(
    user_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
    viewer: Annotated[User | None, Depends(get_optional_user)],
) -> SubscriptionStatus:
    """Return the caller's subscription flag and the channel's subscriber total."""
    try:
        return await subscription_state(session, user_id, viewer)
    except ChannelNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found") from exc


@router.post("/{user_id}/subscribe", response_model=SubscriptionStatus)
async def subscribe(
    user_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> SubscriptionStatus:
    """Subscribe to a channel, or unsubscribe when the subscription already exists.

    A user cannot subscribe to their own channel.
    """
    try:
        return await toggle_subscription(session, user_id, current_user)
    except SelfSubscriptionError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot subscribe to yourself",
        ) from exc
    except ChannelNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found") from exc


@router.get("/{user_id}/subscribers/count", response_model=SubscribersCount)
async def subscribers_count(
    user_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> SubscribersCount:
    """Return how many users are subscribed to this channel."""
    try:
        return await get_subscribers_count(session, user_id)
    except ChannelNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found") from exc
