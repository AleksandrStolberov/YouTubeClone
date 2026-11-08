import asyncio
import uuid

from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.core.database import async_engine, async_sessionmaker
from app.core.security import create_access_token
from app.main import app
from app.models import User, UserRole, Video

_TRANSPORT = ASGITransport(app=app)


def _auth(user_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(str(user_id))}"}


def _user(prefix: str, *, role: UserRole = UserRole.USER) -> User:
    suffix = uuid.uuid4().hex[:10]
    return User(
        email=f"{prefix}-{suffix}@example.com",
        username=f"{prefix}{suffix}",
        hashed_password="hashed",
        role=role,
    )


def _video(owner: User, title: str, *, private: bool = False) -> Video:
    return Video(
        title=title,
        s3_key=f"{owner.id}/{uuid.uuid4()}.mp4",
        user_id=owner.id,
        is_private=private,
    )


async def _cleanup(user_ids: list[uuid.UUID]) -> None:
    try:
        if user_ids:
            async with async_sessionmaker() as session:
                await session.execute(delete(User).where(User.id.in_(user_ids)))
                await session.commit()
    finally:
        await async_engine.dispose()


def test_user_can_report_and_only_staff_can_list_reports() -> None:
    """A user files a complaint. A moderator can list it; a user cannot."""

    async def scenario() -> None:
        user_ids: list[uuid.UUID] = []
        try:
            async with async_sessionmaker() as session:
                author = _user("author")
                reporter = _user("reporter")
                moderator = _user("moderator", role=UserRole.MODERATOR)
                session.add_all([author, reporter, moderator])
                await session.flush()
                video = _video(author, f"Reported {uuid.uuid4().hex}")
                session.add(video)
                await session.commit()
                user_ids.extend([author.id, reporter.id, moderator.id])
                video_id = video.id

            reporter_headers = _auth(reporter.id)
            moderator_headers = _auth(moderator.id)
            async with AsyncClient(transport=_TRANSPORT, base_url="http://test") as client:
                created = await client.post(
                    f"/videos/{video_id}/report",
                    json={"reason": "  Misleading title  "},
                    headers=reporter_headers,
                )
                assert created.status_code == 201
                body = created.json()
                assert body["video_id"] == str(video_id)
                assert body["reporter_id"] == str(reporter.id)
                assert body["reason"] == "Misleading title"
                assert body["status"] == "pending"
                assert body["ban_reason"] is None

                forbidden = await client.get("/moderation/reports", headers=reporter_headers)
                assert forbidden.status_code == 403

                listed = await client.get(
                    "/moderation/reports",
                    headers=moderator_headers,
                    params={"status": "pending"},
                )
                assert listed.status_code == 200
                match = next(item for item in listed.json() if item["id"] == body["id"])
                assert match["reason"] == "Misleading title"
                assert match["status"] == "pending"

                rejected = await client.get(
                    "/moderation/reports",
                    headers=moderator_headers,
                    params={"status": "rejected"},
                )
                assert rejected.status_code == 200
                assert all(item["id"] != body["id"] for item in rejected.json())
        finally:
            await _cleanup(user_ids)

    asyncio.run(scenario())


def test_banned_video_is_hidden_from_public_surfaces() -> None:
    """A moderator ban removes the video from the catalog, search, feed, and playback."""

    async def scenario() -> None:
        user_ids: list[uuid.UUID] = []
        try:
            token = uuid.uuid4().hex
            async with async_sessionmaker() as session:
                author = _user("author")
                viewer = _user("viewer")
                moderator = _user("moderator", role=UserRole.MODERATOR)
                session.add_all([author, viewer, moderator])
                await session.flush()
                video = _video(author, f"Public clip {token}")
                session.add(video)
                await session.commit()
                user_ids.extend([author.id, viewer.id, moderator.id])
                video_id = video.id
                author_id = author.id

            viewer_headers = _auth(viewer.id)
            author_headers = _auth(author.id)
            moderator_headers = _auth(moderator.id)
            async with AsyncClient(transport=_TRANSPORT, base_url="http://test") as client:
                subscribed = await client.post(
                    f"/users/{author_id}/subscribe",
                    headers=viewer_headers,
                )
                assert subscribed.status_code == 200

                before_search = await client.get("/videos/search", params={"query": token})
                assert before_search.status_code == 200
                assert [item["id"] for item in before_search.json()["items"]] == [str(video_id)]

                before_list = await client.get("/videos", params={"limit": 50})
                assert any(item["id"] == str(video_id) for item in before_list.json())

                before_feed = await client.get("/feed/subscriptions", headers=viewer_headers)
                assert any(item["id"] == str(video_id) for item in before_feed.json()["items"])

                denied = await client.post(
                    f"/moderation/videos/{video_id}/ban",
                    json={"reason": "Hate speech"},
                    headers=viewer_headers,
                )
                assert denied.status_code == 403

                banned = await client.post(
                    f"/moderation/videos/{video_id}/ban",
                    json={"reason": "  Hate speech  "},
                    headers=moderator_headers,
                )
                assert banned.status_code == 200
                assert banned.json()["is_banned"] is True
                assert banned.json()["ban_reason"] == "Hate speech"

                hidden = await client.get(f"/videos/{video_id}", headers=viewer_headers)
                assert hidden.status_code == 404

                guest = await client.get(f"/videos/{video_id}")
                assert guest.status_code == 404

                author_view = await client.get(f"/videos/{video_id}", headers=author_headers)
                assert author_view.status_code == 200
                assert author_view.json()["ban_reason"] == "Hate speech"

                staff_view = await client.get(f"/videos/{video_id}", headers=moderator_headers)
                assert staff_view.status_code == 200

                after_search = await client.get("/videos/search", params={"query": token})
                assert after_search.json()["items"] == []
                assert after_search.json()["total"] == 0

                after_list = await client.get("/videos", params={"limit": 50})
                assert all(item["id"] != str(video_id) for item in after_list.json())

                after_feed = await client.get("/feed/subscriptions", headers=viewer_headers)
                assert all(item["id"] != str(video_id) for item in after_feed.json()["items"])

                restored = await client.post(
                    f"/moderation/videos/{video_id}/unban",
                    headers=moderator_headers,
                )
                assert restored.status_code == 200
                assert restored.json()["is_banned"] is False
                assert restored.json()["ban_reason"] is None

                visible = await client.get(f"/videos/{video_id}", headers=viewer_headers)
                assert visible.status_code == 200
        finally:
            await _cleanup(user_ids)

    asyncio.run(scenario())


def test_private_video_is_visible_only_after_whitelist_grant() -> None:
    """A stranger gets 403 until the owner adds them to the whitelist."""

    async def scenario() -> None:
        user_ids: list[uuid.UUID] = []
        try:
            async with async_sessionmaker() as session:
                owner = _user("owner")
                stranger = _user("stranger")
                session.add_all([owner, stranger])
                await session.flush()
                video = _video(owner, "Private clip", private=True)
                session.add(video)
                await session.commit()
                user_ids.extend([owner.id, stranger.id])
                video_id = video.id

            owner_headers = _auth(owner.id)
            stranger_headers = _auth(stranger.id)
            async with AsyncClient(transport=_TRANSPORT, base_url="http://test") as client:
                hidden = await client.get(f"/videos/{video_id}", headers=stranger_headers)
                assert hidden.status_code == 403

                refused = await client.post(
                    f"/videos/{video_id}/access",
                    json={"user_id": str(stranger.id)},
                    headers=stranger_headers,
                )
                assert refused.status_code == 403

                missing_user = await client.post(
                    f"/videos/{video_id}/access",
                    json={"user_id": str(uuid.uuid4())},
                    headers=owner_headers,
                )
                assert missing_user.status_code == 404

                granted = await client.post(
                    f"/videos/{video_id}/access",
                    json={"user_id": str(stranger.id)},
                    headers=owner_headers,
                )
                assert granted.status_code == 201
                assert granted.json()["user_id"] == str(stranger.id)
                assert granted.json()["username"] == stranger.username
                assert granted.json()["email"] == stranger.email

                duplicate = await client.post(
                    f"/videos/{video_id}/access",
                    json={"user_id": str(stranger.id)},
                    headers=owner_headers,
                )
                assert duplicate.status_code == 409

                allowed = await client.get(f"/videos/{video_id}/access", headers=owner_headers)
                assert allowed.status_code == 200
                assert [item["user_id"] for item in allowed.json()] == [str(stranger.id)]

                stranger_list = await client.get(
                    f"/videos/{video_id}/access",
                    headers=stranger_headers,
                )
                assert stranger_list.status_code == 403

                opened = await client.get(f"/videos/{video_id}", headers=stranger_headers)
                assert opened.status_code == 200
                assert opened.json()["id"] == str(video_id)
                assert opened.json()["is_private"] is True

                removed = await client.delete(
                    f"/videos/{video_id}/access/{stranger.id}",
                    headers=owner_headers,
                )
                assert removed.status_code == 204

                closed = await client.get(f"/videos/{video_id}", headers=stranger_headers)
                assert closed.status_code == 403
        finally:
            await _cleanup(user_ids)

    asyncio.run(scenario())
