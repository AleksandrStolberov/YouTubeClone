import asyncio
import uuid
from datetime import datetime, timedelta, timezone

from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.core.database import async_engine, async_sessionmaker
from app.main import app
from app.models import Reaction, User, UserRole, Video

_TRANSPORT = ASGITransport(app=app)


def _user(prefix: str) -> User:
    suffix = uuid.uuid4().hex[:10]
    return User(
        email=f"{prefix}-{suffix}@example.com",
        username=f"{prefix}{suffix}",
        hashed_password="hashed",
        role=UserRole.USER,
    )


def _video(
    owner: User,
    title: str,
    *,
    description: str | None = None,
    private: bool = False,
    views: int = 0,
    category: str | None = None,
    tags: list[str] | None = None,
    created_at: datetime | None = None,
) -> Video:
    video = Video(
        title=title,
        description=description,
        s3_key=f"{owner.id}/{uuid.uuid4()}.mp4",
        user_id=owner.id,
        is_private=private,
        views_count=views,
        category=category,
        tags=list(tags or []),
    )
    if created_at is not None:
        video.created_at = created_at
    return video


async def _cleanup(user_ids: list[uuid.UUID]) -> None:
    try:
        if user_ids:
            async with async_sessionmaker() as session:
                await session.execute(delete(User).where(User.id.in_(user_ids)))
                await session.commit()
    finally:
        await async_engine.dispose()


def test_search_matches_title_and_description_substring() -> None:
    """A case-insensitive substring matches the title or the description."""

    async def scenario() -> None:
        user_ids: list[uuid.UUID] = []
        try:
            token = uuid.uuid4().hex[:12]
            async with async_sessionmaker() as session:
                author = _user("author")
                session.add(author)
                await session.flush()
                by_title = _video(author, f"Lesson {token.upper()} basics")
                by_description = _video(
                    author,
                    "Studio notes",
                    description=f"The chapter mentions {token.upper()} once.",
                )
                unrelated = _video(author, "Cooking pasta", description="No shared words here")
                session.add_all([by_title, by_description, unrelated])
                await session.commit()
                user_ids.append(author.id)
                title_id, description_id = by_title.id, by_description.id
                unrelated_id = unrelated.id

            async with AsyncClient(transport=_TRANSPORT, base_url="http://test") as client:
                found = await client.get("/videos/search", params={"query": token.lower()})
                assert found.status_code == 200
                body = found.json()
                ids = {item["id"] for item in body["items"]}
                assert body["total"] == 2
                assert ids == {str(title_id), str(description_id)}
                assert str(unrelated_id) not in ids
                assert body["limit"] == 20
                assert body["offset"] == 0

                rejected = await client.get("/videos/search", params={"sort_by": "title"})
                assert rejected.status_code == 422
        finally:
            await _cleanup(user_ids)

    asyncio.run(scenario())


def test_search_hides_private_videos() -> None:
    """Private videos stay out of search even when the text matches."""

    async def scenario() -> None:
        user_ids: list[uuid.UUID] = []
        try:
            token = uuid.uuid4().hex[:12]
            async with async_sessionmaker() as session:
                author = _user("author")
                session.add(author)
                await session.flush()
                public = _video(author, f"Visible {token}")
                private = _video(author, f"Hidden {token}", private=True)
                session.add_all([public, private])
                await session.commit()
                user_ids.append(author.id)
                public_id = public.id

            async with AsyncClient(transport=_TRANSPORT, base_url="http://test") as client:
                found = await client.get("/videos/search", params={"query": token})
                assert found.status_code == 200
                body = found.json()
                assert body["total"] == 1
                assert len(body["items"]) == 1
                assert body["items"][0]["id"] == str(public_id)
                assert body["items"][0]["is_private"] is False
        finally:
            await _cleanup(user_ids)

    asyncio.run(scenario())


def test_search_filters_by_category_and_sorts_by_views() -> None:
    """Category keeps one group, and view count decides the page order."""

    async def scenario() -> None:
        user_ids: list[uuid.UUID] = []
        try:
            category = f"music{uuid.uuid4().hex[:8]}"
            async with async_sessionmaker() as session:
                author = _user("author")
                session.add(author)
                await session.flush()
                quiet = _video(author, "Quiet concert", views=3, category=category)
                popular = _video(author, "Popular concert", views=30, category=category.upper())
                other = _video(author, "Match highlights", views=1000, category="sports")
                session.add_all([quiet, popular, other])
                await session.commit()
                user_ids.append(author.id)
                quiet_id, popular_id, other_id = quiet.id, popular.id, other.id

            async with AsyncClient(transport=_TRANSPORT, base_url="http://test") as client:
                found = await client.get(
                    "/videos/search",
                    params={
                        "category": category,
                        "sort_by": "views",
                        "order": "desc",
                        "limit": 1,
                        "offset": 0,
                    },
                )
                assert found.status_code == 200
                body = found.json()
                assert body["total"] == 2
                assert body["limit"] == 1
                assert [item["id"] for item in body["items"]] == [str(popular_id)]
                assert str(other_id) not in {item["id"] for item in body["items"]}

                rest = await client.get(
                    "/videos/search",
                    params={
                        "category": category,
                        "sort_by": "views",
                        "order": "desc",
                        "limit": 1,
                        "offset": 1,
                    },
                )
                assert rest.status_code == 200
                assert [item["id"] for item in rest.json()["items"]] == [str(quiet_id)]

                ascending = await client.get(
                    "/videos/search",
                    params={"category": category, "sort_by": "views", "order": "asc"},
                )
                assert [item["id"] for item in ascending.json()["items"]] == [
                    str(quiet_id),
                    str(popular_id),
                ]
        finally:
            await _cleanup(user_ids)

    asyncio.run(scenario())


def test_search_sorts_by_likes_and_filters_upload_date() -> None:
    """Likes outrank dislikes, and the upload-date window drops older videos."""

    async def scenario() -> None:
        user_ids: list[uuid.UUID] = []
        try:
            token = uuid.uuid4().hex[:12]
            now = datetime.now(timezone.utc)
            async with async_sessionmaker() as session:
                author = _user("author")
                fan_one = _user("fanone")
                fan_two = _user("fantwo")
                session.add_all([author, fan_one, fan_two])
                await session.flush()
                liked = _video(author, f"Liked {token}", created_at=now)
                mixed = _video(author, f"Mixed {token}", created_at=now)
                old = _video(
                    author,
                    f"Archive {token}",
                    created_at=now - timedelta(days=40),
                )
                session.add_all([liked, mixed, old])
                await session.flush()
                session.add_all(
                    [
                        Reaction(video_id=liked.id, user_id=fan_one.id, is_like=True),
                        Reaction(video_id=liked.id, user_id=fan_two.id, is_like=True),
                        Reaction(video_id=mixed.id, user_id=fan_one.id, is_like=True),
                        Reaction(video_id=mixed.id, user_id=fan_two.id, is_like=False),
                    ]
                )
                await session.commit()
                user_ids.extend([author.id, fan_one.id, fan_two.id])
                liked_id, mixed_id, old_id = liked.id, mixed.id, old.id

            async with AsyncClient(transport=_TRANSPORT, base_url="http://test") as client:
                by_likes = await client.get(
                    "/videos/search",
                    params={"query": token, "sort_by": "likes", "order": "desc"},
                )
                assert by_likes.status_code == 200
                assert [item["id"] for item in by_likes.json()["items"]] == [
                    str(liked_id),
                    str(mixed_id),
                    str(old_id),
                ]

                by_rating = await client.get(
                    "/videos/search",
                    params={"query": token, "sort_by": "rating", "order": "asc"},
                )
                assert [item["id"] for item in by_rating.json()["items"]] == [
                    str(old_id),
                    str(mixed_id),
                    str(liked_id),
                ]

                this_month = await client.get(
                    "/videos/search",
                    params={"query": token, "upload_date": "this_month", "sort_by": "date"},
                )
                assert this_month.status_code == 200
                month_ids = {item["id"] for item in this_month.json()["items"]}
                assert month_ids == {str(liked_id), str(mixed_id)}
                assert this_month.json()["total"] == 2
        finally:
            await _cleanup(user_ids)

    asyncio.run(scenario())


def test_search_filters_by_tag_and_lists_trending_tags() -> None:
    """A tag filter is case-insensitive, and trending tags ignore private videos."""

    async def scenario() -> None:
        user_ids: list[uuid.UUID] = []
        try:
            shared = f"shared{uuid.uuid4().hex[:8]}"
            only_public = f"public{uuid.uuid4().hex[:8]}"
            only_private = f"secret{uuid.uuid4().hex[:8]}"
            async with async_sessionmaker() as session:
                author = _user("author")
                session.add(author)
                await session.flush()
                first = _video(author, "First", tags=[shared, only_public])
                second = _video(author, "Second", tags=[shared.upper()])
                other = _video(author, "Other", tags=["solo"])
                private = _video(
                    author,
                    "Private",
                    private=True,
                    tags=[shared, only_private],
                )
                session.add_all([first, second, other, private])
                await session.commit()
                user_ids.append(author.id)
                first_id, second_id = first.id, second.id

            async with AsyncClient(transport=_TRANSPORT, base_url="http://test") as client:
                found = await client.get("/videos/search", params={"tag": shared.upper()})
                assert found.status_code == 200
                body = found.json()
                assert body["total"] == 2
                assert {item["id"] for item in body["items"]} == {str(first_id), str(second_id)}

                trending = await client.get("/videos/tags/trending", params={"limit": 50})
                assert trending.status_code == 200
                counts = {item["tag"]: item["count"] for item in trending.json()}
                assert counts[shared] == 1
                assert counts[shared.upper()] == 1
                assert counts[only_public] == 1
                assert only_private not in counts
        finally:
            await _cleanup(user_ids)

    asyncio.run(scenario())
