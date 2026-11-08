from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.search import PaginatedSearchResult, TrendingTag, VideoSearchParams
from app.services.search import list_trending_tags, search_public_videos

router = APIRouter(prefix="/videos", tags=["search"])


@router.get("/search", response_model=PaginatedSearchResult)
async def search_videos(
    session: Annotated[AsyncSession, Depends(get_db)],
    params: Annotated[VideoSearchParams, Query()],
) -> PaginatedSearchResult:
    """Search public videos by title and description.

    Results can be narrowed by category, tag, and upload date, then sorted by
    publication date, view count, or likes. Private videos are never returned.
    """
    return await search_public_videos(session, params)


@router.get("/tags/trending", response_model=list[TrendingTag])
async def trending_tags(
    session: Annotated[AsyncSession, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> list[TrendingTag]:
    """List tags that appear most often on public videos."""
    return await list_trending_tags(session, limit=limit)
