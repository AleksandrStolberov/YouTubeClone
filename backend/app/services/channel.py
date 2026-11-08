import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Subscription, User, Video
from app.schemas.channel import ChannelProfileRead
from app.services.video import public_video_filters


class ChannelNotFoundError(Exception):
    """Raised when the channel user id does not exist."""


async def get_channel_profile(
    session: AsyncSession,
    user_id: uuid.UUID,
) -> ChannelProfileRead:
    """Return public channel counters.

    Views are summed for public videos that are not banned. The video total
    includes private uploads, because it is the size of the author's catalog.
    """
    user = await session.get(User, user_id)
    if user is None:
        raise ChannelNotFoundError

    subscribers_count = (
        select(func.count())
        .select_from(Subscription)
        .where(Subscription.channel_id == user_id)
        .scalar_subquery()
    )
    total_views = (
        select(func.coalesce(func.sum(Video.views_count), 0))
        .where(Video.user_id == user_id, *public_video_filters())
        .scalar_subquery()
    )
    videos_count = (
        select(func.count())
        .select_from(Video)
        .where(Video.user_id == user_id)
        .scalar_subquery()
    )
    row = (await session.execute(select(subscribers_count, total_views, videos_count))).one()
    subscribers, views, videos = row
    return ChannelProfileRead(
        user_id=user.id,
        username=user.username,
        created_at=user.created_at,
        subscribers_count=int(subscribers or 0),
        total_views=int(views or 0),
        videos_count=int(videos or 0),
    )
