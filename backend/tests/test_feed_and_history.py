import asyncio
import uuid
from datetime import datetime, timedelta, timezone

from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select

from app.core.database import async_engine, async_sessionmaker
from app.core.security import create_access_token
from app.main import app
from app.models import User, UserRole, Video, WatchHistory

_TRANSPORT = ASGITransport(app=app)


def _auth(user_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(str(user_id))}"}


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
    private: bool = False,
    created_at: datetime | None = None,
) -> Video:
    video = Video(
        title=title,
        s3_key=f"{owner.id}/{uuid.uuid4()}.mp4",
        user_id=owner.id,
        is_private=private,
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


async def _history_count(video_id: uuid.UUID) -> int:
    async with async_sessionmaker() as session:
        total = await session.scalar(
            select(func.count())
            .select_from(WatchHistory)
            .where(WatchHistory.video_id == video_id)
        )
    return int(total or 0)


def test_view_increments_for_guest_and_user() -> None:
    """A guest only bumps the counter. A user also upserts one history row."""

    async def scenario() -> None:
        user_ids: list[uuid.UUID] = []
        try:
            async with async_sessionmaker() as session:
                author = _user("author")
                viewer = _user("viewer")
                session.add_all([author, viewer])
                await session.flush()
                video = _video(author, "Public clip")
                session.add(video)
                await session.commit()
                user_ids.extend([author.id, viewer.id])
                video_id = video.id

            async with AsyncClient(transport=_TRANSPORT, base_url="http://test") as client:
                missing = await client.post(f"/videos/{uuid.uuid4()}/view")
                assert missing.status_code == 404

                guest = await client.post(f"/videos/{video_id}/view")
                assert guest.status_code == 200
                assert guest.json()["views_count"] == 1
                assert await _history_count(video_id) == 0

                first = await client.post(
                    f"/videos/{video_id}/view",
                    json={"progress_seconds": 12},
                    headers=_auth(viewer.id),
                )
                assert first.status_code == 200
                assert first.json()["views_count"] == 2

                second = await client.post(
                    f"/videos/{video_id}/view",
                    json={"progress_seconds": 40},
                    headers=_auth(viewer.id),
                )
                assert second.status_code == 200
                assert second.json()["views_count"] == 3

                history = await client.get("/users/me/history", headers=_auth(viewer.id))
                assert history.status_code == 200
                body = history.json()
                assert body["total"] == 1
                assert len(body["items"]) == 1
                assert body["items"][0]["video"]["id"] == str(video_id)
                assert body["items"][0]["progress_seconds"] == 40
                assert await _history_count(video_id) == 1
        finally:
            await _cleanup(user_ids)

    asyncio.run(scenario())


def test_subscription_feed_includes_only_subscribed_authors() -> None:
    """The feed lists public videos of followed channels, newest first."""

    async def scenario() -> None:
        user_ids: list[uuid.UUID] = []
        try:
            now = datetime.now(timezone.utc)
            async with async_sessionmaker() as session:
                viewer = _user("viewer")
                author = _user("author")
                outsider = _user("outsider")
                session.add_all([viewer, author, outsider])
                await session.flush()
                older = _video(author, "Older public", created_at=now - timedelta(hours=2))
                newer = _video(author, "Newer public", created_at=now - timedelta(minutes=5))
                private = _video(author, "Private draft", private=True, created_at=now)
                other = _video(outsider, "Someone else", created_at=now)
                session.add_all([older, newer, private, other])
                await session.commit()
                user_ids.extend([viewer.id, author.id, outsider.id])
                viewer_id, author_id = viewer.id, author.id
                newer_id, older_id = newer.id, older.id
                private_id, other_id = private.id, other.id

            headers = _auth(viewer_id)
            async with AsyncClient(transport=_TRANSPORT, base_url="http://test") as client:
                anonymous = await client.get("/feed/subscriptions")
                assert anonymous.status_code == 401

                subscribed = await client.post(f"/users/{author_id}/subscribe", headers=headers)
                assert subscribed.status_code == 200
                assert subscribed.json()["is_subscribed"] is True

                feed = await client.get("/feed/subscriptions", headers=headers)
                assert feed.status_code == 200
                body = feed.json()
                ids = [item["id"] for item in body["items"]]
                assert body["total"] == 2
                assert ids == [str(newer_id), str(older_id)]
                assert str(private_id) not in ids
                assert str(other_id) not in ids
                assert all(item["is_private"] is False for item in body["items"])
        finally:
            await _cleanup(user_ids)

    asyncio.run(scenario())


def test_watch_history_records_and_clears() -> None:
    """Views land in history, one row can be removed, and clear drops the rest."""

    async def scenario() -> None:
        user_ids: list[uuid.UUID] = []
        try:
            async with async_sessionmaker() as session:
                author = _user("author")
                viewer = _user("viewer")
                session.add_all([author, viewer])
                await session.flush()
                first_video = _video(author, "First")
                second_video = _video(author, "Second")
                session.add_all([first_video, second_video])
                await session.commit()
                user_ids.extend([author.id, viewer.id])
                viewer_id = viewer.id
                first_id, second_id = first_video.id, second_video.id

            headers = _auth(viewer_id)
            async with AsyncClient(transport=_TRANSPORT, base_url="http://test") as client:
                anonymous = await client.get("/users/me/history")
                assert anonymous.status_code == 401

                first_view = await client.post(
                    f"/videos/{first_id}/view",
                    json={"progress_seconds": 10},
                    headers=headers,
                )
                second_view = await client.post(
                    f"/videos/{second_id}/view",
                    json={"progress_seconds": 20},
                    headers=headers,
                )
                assert first_view.status_code == 200
                assert second_view.status_code == 200

                listed = await client.get("/users/me/history", headers=headers)
                assert listed.status_code == 200
                body = listed.json()
                assert body["total"] == 2
                assert [item["video"]["id"] for item in body["items"]] == [
                    str(second_id),
                    str(first_id),
                ]

                removed = await client.delete(f"/users/me/history/{second_id}", headers=headers)
                assert removed.status_code == 204
                after_delete = await client.get("/users/me/history", headers=headers)
                assert after_delete.json()["total"] == 1
                assert after_delete.json()["items"][0]["video"]["id"] == str(first_id)

                missing = await client.delete(f"/users/me/history/{second_id}", headers=headers)
                assert missing.status_code == 404

                cleared = await client.delete("/users/me/history", headers=headers)
                assert cleared.status_code == 204
                empty = await client.get("/users/me/history", headers=headers)
                assert empty.status_code == 200
                assert empty.json()["total"] == 0
                assert empty.json()["items"] == []
        finally:
            await _cleanup(user_ids)

    asyncio.run(scenario())
