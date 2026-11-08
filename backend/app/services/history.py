import uuid

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Subscription, User, Video, WatchHistory
from app.schemas.feed import PaginatedFeedResponse
from app.schemas.history import PaginatedHistoryResponse, WatchHistoryItemRead
from app.schemas.video import VideoRead
from app.services.video import get_video, public_video_filters


class HistoryNotFoundError(Exception):
    """Raised when this user has no watch-history row for the video."""


def _progress(progress_seconds: int | None) -> int:
    return 0 if progress_seconds is None else progress_seconds


async def record_view(
    session: AsyncSession,
    video_id: uuid.UUID,
    viewer: User | None,
    progress_seconds: int | None = 0,
) -> Video:
    """Increment the view counter and, for a signed-in viewer, upsert history.

    Guests only move ``views_count``. A signed-in viewer also gets one history
    row per video: a later view refreshes ``watched_at`` and the position.
    """
    video = await get_video(session, video_id, viewer)
    progress = _progress(progress_seconds)
    await session.execute(
        update(Video)
        .where(Video.id == video.id)
        .values(views_count=Video.views_count + 1)
        .execution_options(synchronize_session="fetch")
    )
    if viewer is not None:
        await session.execute(
            pg_insert(WatchHistory)
            .values(
                id=uuid.uuid4(),
                user_id=viewer.id,
                video_id=video.id,
                watched_at=func.now(),
                progress_seconds=progress,
            )
            .on_conflict_do_update(
                index_elements=[WatchHistory.user_id, WatchHistory.video_id],
                set_={
                    "watched_at": func.now(),
                    "progress_seconds": progress,
                },
            )
        )
    await session.commit()
    await session.refresh(video)
    return video


async def list_subscription_feed(
    session: AsyncSession,
    user: User,
    *,
    limit: int,
    offset: int,
) -> PaginatedFeedResponse:
    """Return published videos from channels the user is subscribed to.

    Published means public and not banned. Newest videos come first.
    """
    filters = (
        Subscription.subscriber_id == user.id,
        *public_video_filters(),
    )
    matched = (
        select(Video)
        .join(Subscription, Subscription.channel_id == Video.user_id)
        .where(*filters)
    )
    total = await session.scalar(select(func.count()).select_from(matched.subquery()))
    rows = await session.scalars(
        matched.order_by(Video.created_at.desc(), Video.id.desc()).limit(limit).offset(offset)
    )
    return PaginatedFeedResponse(
        items=[VideoRead.model_validate(video) for video in rows.all()],
        total=int(total or 0),
        limit=limit,
        offset=offset,
    )


async def list_watch_history(
    session: AsyncSession,
    user: User,
    *,
    limit: int,
    offset: int,
) -> PaginatedHistoryResponse:
    """Return the user's watch history, most recently watched first."""
    filters = (WatchHistory.user_id == user.id,)
    total = await session.scalar(
        select(func.count()).select_from(WatchHistory).where(*filters)
    )
    rows = await session.scalars(
        select(WatchHistory)
        .where(*filters)
        .options(selectinload(WatchHistory.video))
        .order_by(WatchHistory.watched_at.desc(), WatchHistory.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return PaginatedHistoryResponse(
        items=[
            WatchHistoryItemRead(
                video=VideoRead.model_validate(entry.video),
                watched_at=entry.watched_at,
                progress_seconds=entry.progress_seconds,
            )
            for entry in rows.all()
        ],
        total=int(total or 0),
        limit=limit,
        offset=offset,
    )


async def remove_watch_history_item(
    session: AsyncSession,
    user: User,
    video_id: uuid.UUID,
) -> None:
    """Delete one video from the user's watch history."""
    entry = await session.scalar(
        select(WatchHistory).where(
            WatchHistory.user_id == user.id,
            WatchHistory.video_id == video_id,
        )
    )
    if entry is None:
        raise HistoryNotFoundError
    await session.delete(entry)
    await session.commit()


async def clear_watch_history(session: AsyncSession, user: User) -> None:
    """Delete every watch-history row that belongs to the user."""
    await session.execute(delete(WatchHistory).where(WatchHistory.user_id == user.id))
    await session.commit()
