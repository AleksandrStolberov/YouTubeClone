from datetime import datetime, timedelta, timezone

from sqlalchemy import asc, desc, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Reaction, Video
from app.schemas.search import PaginatedSearchResult, TrendingTag, VideoSearchParams
from app.schemas.video import VideoRead


def _like_pattern(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _likes_count():
    """Number of likes on the correlated video. Dislikes are ignored."""
    return (
        select(func.count(Reaction.id))
        .where(Reaction.video_id == Video.id, Reaction.is_like.is_(True))
        .scalar_subquery()
    )


def _uploaded_since(upload_date: str | None, now: datetime) -> datetime | None:
    if upload_date is None or upload_date == "all":
        return None
    if upload_date == "today":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    if upload_date == "this_week":
        start = now - timedelta(days=now.weekday())
        return start.replace(hour=0, minute=0, second=0, microsecond=0)
    if upload_date == "this_month":
        return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if upload_date == "this_year":
        return now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    return None


def _filters(params: VideoSearchParams, now: datetime) -> list:
    filters: list = [Video.is_private.is_(False)]
    if params.query:
        pattern = _like_pattern(params.query)
        filters.append(
            Video.title.ilike(pattern, escape="\\")
            | Video.description.ilike(pattern, escape="\\")
        )
    if params.category:
        filters.append(func.lower(Video.category) == params.category.lower())
    if params.tag:
        search_tag = func.unnest(Video.tags).column_valued("search_tag")
        filters.append(
            select(search_tag).where(func.lower(search_tag) == params.tag.lower()).exists()
        )
    uploaded_since = _uploaded_since(params.upload_date, now)
    if uploaded_since is not None:
        filters.append(Video.created_at >= uploaded_since)
    return filters


def _order_by(params: VideoSearchParams) -> tuple:
    direction = asc if params.order == "asc" else desc
    if params.sort_by == "views":
        primary = Video.views_count
    elif params.sort_by in {"rating", "likes"}:
        primary = _likes_count()
    else:
        primary = Video.created_at
    return (direction(primary), direction(Video.id))


async def search_public_videos(
    session: AsyncSession,
    params: VideoSearchParams,
) -> PaginatedSearchResult:
    """Search public videos by title and description, then filter and sort.

    Private videos are excluded. Text search is a case-insensitive substring
    match. A tag matches when any element of ``tags`` equals it, ignoring case.
    """
    filters = _filters(params, datetime.now(timezone.utc))
    total = await session.scalar(select(func.count()).select_from(Video).where(*filters))
    rows = await session.scalars(
        select(Video)
        .where(*filters)
        .order_by(*_order_by(params))
        .limit(params.limit)
        .offset(params.offset)
    )
    return PaginatedSearchResult(
        items=[VideoRead.model_validate(video) for video in rows.all()],
        total=int(total or 0),
        limit=params.limit,
        offset=params.offset,
    )


async def list_trending_tags(session: AsyncSession, *, limit: int) -> list[TrendingTag]:
    """Return tags used by public videos, most common first.

    A tag's count is the number of public videos that include it. Tags that
    appear only on private videos are left out.
    """
    rows = await session.execute(
        text(
            """
            SELECT tag, COUNT(DISTINCT videos.id) AS video_count
            FROM videos
            CROSS JOIN LATERAL unnest(videos.tags) AS tag
            WHERE videos.is_private IS FALSE
              AND tag <> ''
            GROUP BY tag
            ORDER BY video_count DESC, tag ASC
            LIMIT :limit
            """
        ),
        {"limit": limit},
    )
    return [
        TrendingTag(tag=tag, count=int(video_count))
        for tag, video_count in rows.all()
    ]
