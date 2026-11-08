from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models import User
from app.schemas.feed import PaginatedFeedResponse
from app.services.history import list_subscription_feed

router = APIRouter(prefix="/feed", tags=["feed"])


@router.get("/subscriptions", response_model=PaginatedFeedResponse)
async def subscription_feed(
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PaginatedFeedResponse:
    """List published videos from channels the current user follows.

    Newest videos come first. Private and banned videos are left out.
    """
    return await list_subscription_feed(session, current_user, limit=limit, offset=offset)
