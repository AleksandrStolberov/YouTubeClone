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


def _video(
    owner: User,
    title: str,
    *,
    private: bool = False,
    views_count: int = 0,
) -> Video:
    return Video(
        title=title,
        s3_key=f"{owner.id}/{uuid.uuid4()}.mp4",
        user_id=owner.id,
        is_private=private,
        views_count=views_count,
    )


async def _cleanup(user_ids: list[uuid.UUID]) -> None:
    try:
        if user_ids:
            async with async_sessionmaker() as session:
                await session.execute(delete(User).where(User.id.in_(user_ids)))
                await session.commit()
    finally:
        await async_engine.dispose()


def test_create_playlist_and_manage_videos() -> None:
    """An author creates a playlist, appends videos in order, and removes one."""

    async def scenario() -> None:
        user_ids: list[uuid.UUID] = []
        try:
            async with async_sessionmaker() as session:
                owner = _user("owner")
                stranger = _user("stranger")
                session.add_all([owner, stranger])
                await session.flush()
                first = _video(owner, "First")
                second = _video(owner, "Second")
                hidden = _video(stranger, "Hidden", private=True)
                session.add_all([first, second, hidden])
                await session.commit()
                user_ids.extend([owner.id, stranger.id])
                owner_id, stranger_id = owner.id, stranger.id
                first_id, second_id, hidden_id = first.id, second.id, hidden.id

            headers = _auth(owner_id)
            stranger_headers = _auth(stranger_id)
            async with AsyncClient(transport=_TRANSPORT, base_url="http://test") as client:
                anonymous = await client.post("/playlists", json={"title": "Nope"})
                assert anonymous.status_code == 401

                blank = await client.post("/playlists", json={"title": " "}, headers=headers)
                assert blank.status_code == 422
                too_long = await client.post(
                    "/playlists",
                    json={"title": "x" * 151},
                    headers=headers,
                )
                assert too_long.status_code == 422

                created = await client.post(
                    "/playlists",
                    json={"title": "Road trips", "description": "Summer", "is_private": False},
                    headers=headers,
                )
                assert created.status_code == 201
                created_body = created.json()
                playlist_id = created_body["id"]
                assert created_body["title"] == "Road trips"
                assert created_body["description"] == "Summer"
                assert created_body["is_private"] is False
                assert created_body["user_id"] == str(owner_id)
                assert created_body["videos_count"] == 0
                assert created_body["created_at"]

                missing = await client.get(f"/playlists/{uuid.uuid4()}")
                assert missing.status_code == 404

                first_add = await client.post(
                    f"/playlists/{playlist_id}/videos/{first_id}",
                    headers=headers,
                )
                assert first_add.status_code == 201
                first_body = first_add.json()
                assert first_body["videos_count"] == 1
                assert first_body["videos"][0]["id"] == str(first_id)
                assert first_body["videos"][0]["title"] == "First"
                assert first_body["videos"][0]["position"] == 0

                second_add = await client.post(
                    f"/playlists/{playlist_id}/videos/{second_id}",
                    headers=headers,
                )
                assert second_add.status_code == 201
                second_body = second_add.json()
                assert [item["id"] for item in second_body["videos"]] == [
                    str(first_id),
                    str(second_id),
                ]
                assert [item["position"] for item in second_body["videos"]] == [0, 1]

                duplicate = await client.post(
                    f"/playlists/{playlist_id}/videos/{first_id}",
                    headers=headers,
                )
                assert duplicate.status_code == 409

                forbidden_video = await client.post(
                    f"/playlists/{playlist_id}/videos/{hidden_id}",
                    headers=headers,
                )
                assert forbidden_video.status_code == 403
                unknown_video = await client.post(
                    f"/playlists/{playlist_id}/videos/{uuid.uuid4()}",
                    headers=headers,
                )
                assert unknown_video.status_code == 404

                listed = await client.get(f"/users/{owner_id}/playlists", headers=headers)
                assert listed.status_code == 200
                assert listed.json()[0]["id"] == playlist_id
                assert listed.json()[0]["videos_count"] == 2

                public_view = await client.get(f"/playlists/{playlist_id}")
                assert public_view.status_code == 200
                assert public_view.json()["videos_count"] == 2

                renamed = await client.put(
                    f"/playlists/{playlist_id}",
                    json={"title": "Updated trips"},
                    headers=headers,
                )
                assert renamed.status_code == 200
                assert renamed.json()["title"] == "Updated trips"
                assert renamed.json()["description"] == "Summer"
                assert renamed.json()["videos_count"] == 2

                cleared = await client.put(
                    f"/playlists/{playlist_id}",
                    json={"description": None},
                    headers=headers,
                )
                assert cleared.status_code == 200
                assert cleared.json()["description"] is None

                stranger_remove = await client.delete(
                    f"/playlists/{playlist_id}/videos/{second_id}",
                    headers=stranger_headers,
                )
                assert stranger_remove.status_code == 403

                removed = await client.delete(
                    f"/playlists/{playlist_id}/videos/{first_id}",
                    headers=headers,
                )
                assert removed.status_code == 204
                after_remove = await client.get(f"/playlists/{playlist_id}", headers=headers)
                assert after_remove.status_code == 200
                after_body = after_remove.json()
                assert after_body["videos_count"] == 1
                assert after_body["videos"][0]["id"] == str(second_id)
                assert after_body["videos"][0]["position"] == 0

                missing_link = await client.delete(
                    f"/playlists/{playlist_id}/videos/{first_id}",
                    headers=headers,
                )
                assert missing_link.status_code == 404

                deleted = await client.delete(f"/playlists/{playlist_id}", headers=headers)
                assert deleted.status_code == 204
                gone = await client.get(f"/playlists/{playlist_id}", headers=headers)
                assert gone.status_code == 404
        finally:
            await _cleanup(user_ids)

    asyncio.run(scenario())


def test_private_playlist_is_hidden_from_other_users() -> None:
    """A stranger cannot open or list someone else's private playlist."""

    async def scenario() -> None:
        user_ids: list[uuid.UUID] = []
        try:
            async with async_sessionmaker() as session:
                owner = _user("owner")
                stranger = _user("stranger")
                admin = _user("admin", role=UserRole.ADMIN)
                session.add_all([owner, stranger, admin])
                await session.commit()
                user_ids.extend([owner.id, stranger.id, admin.id])
                owner_id, stranger_id, admin_id = owner.id, stranger.id, admin.id

            owner_headers = _auth(owner_id)
            stranger_headers = _auth(stranger_id)
            admin_headers = _auth(admin_id)
            async with AsyncClient(transport=_TRANSPORT, base_url="http://test") as client:
                public = await client.post(
                    "/playlists",
                    json={"title": "Open", "is_private": False},
                    headers=owner_headers,
                )
                private = await client.post(
                    "/playlists",
                    json={"title": "Secret", "is_private": True},
                    headers=owner_headers,
                )
                assert public.status_code == 201
                assert private.status_code == 201
                public_id = public.json()["id"]
                private_id = private.json()["id"]

                hidden = await client.get(
                    f"/playlists/{private_id}",
                    headers=stranger_headers,
                )
                assert hidden.status_code == 403

                anonymous = await client.get(f"/playlists/{private_id}")
                assert anonymous.status_code == 401

                visible = await client.get(f"/playlists/{public_id}")
                assert visible.status_code == 200
                assert visible.json()["title"] == "Open"

                owner_view = await client.get(
                    f"/playlists/{private_id}",
                    headers=owner_headers,
                )
                assert owner_view.status_code == 200
                assert owner_view.json()["is_private"] is True

                stranger_list = await client.get(
                    f"/users/{owner_id}/playlists",
                    headers=stranger_headers,
                )
                assert stranger_list.status_code == 200
                stranger_ids = {item["id"] for item in stranger_list.json()}
                assert stranger_ids == {public_id}

                anonymous_list = await client.get(f"/users/{owner_id}/playlists")
                assert anonymous_list.status_code == 200
                assert {item["id"] for item in anonymous_list.json()} == {public_id}

                owner_list = await client.get(
                    f"/users/{owner_id}/playlists",
                    headers=owner_headers,
                )
                assert owner_list.status_code == 200
                assert {item["id"] for item in owner_list.json()} == {public_id, private_id}

                stranger_edit = await client.put(
                    f"/playlists/{private_id}",
                    json={"title": "Hijacked"},
                    headers=stranger_headers,
                )
                assert stranger_edit.status_code == 403
                stranger_delete = await client.delete(
                    f"/playlists/{private_id}",
                    headers=stranger_headers,
                )
                assert stranger_delete.status_code == 403

                missing_user = await client.get(f"/users/{uuid.uuid4()}/playlists")
                assert missing_user.status_code == 404

                removed = await client.delete(
                    f"/playlists/{private_id}",
                    headers=admin_headers,
                )
                assert removed.status_code == 204
                gone = await client.get(f"/playlists/{private_id}", headers=owner_headers)
                assert gone.status_code == 404
        finally:
            await _cleanup(user_ids)

    asyncio.run(scenario())


def test_channel_profile_aggregates_subscribers_and_public_views() -> None:
    """Subscriber rows and public view counters are summed for the channel."""

    async def scenario() -> None:
        user_ids: list[uuid.UUID] = []
        try:
            async with async_sessionmaker() as session:
                author = _user("author")
                fan_a = _user("fana")
                fan_b = _user("fanb")
                session.add_all([author, fan_a, fan_b])
                await session.flush()
                first = _video(author, "Public one", views_count=10)
                second = _video(author, "Public two", views_count=15)
                draft = _video(author, "Draft", private=True, views_count=100)
                session.add_all([first, second, draft])
                await session.commit()
                user_ids.extend([author.id, fan_a.id, fan_b.id])
                author_id, fan_a_id, fan_b_id = author.id, fan_a.id, fan_b.id
                author_name = author.username

            async with AsyncClient(transport=_TRANSPORT, base_url="http://test") as client:
                missing = await client.get(f"/channels/{uuid.uuid4()}")
                assert missing.status_code == 404

                first_sub = await client.post(
                    f"/users/{author_id}/subscribe",
                    headers=_auth(fan_a_id),
                )
                second_sub = await client.post(
                    f"/users/{author_id}/subscribe",
                    headers=_auth(fan_b_id),
                )
                assert first_sub.status_code == 200
                assert second_sub.status_code == 200
                assert first_sub.json()["is_subscribed"] is True
                assert second_sub.json()["subscribers_count"] == 2

                profile = await client.get(f"/channels/{author_id}")
                assert profile.status_code == 200
                body = profile.json()
                assert body["user_id"] == str(author_id)
                assert body["username"] == author_name
                assert body["created_at"]
                assert body["subscribers_count"] == 2
                assert body["total_views"] == 25
                assert body["videos_count"] == 3

                subscribers = await client.get(f"/users/{author_id}/subscribers/count")
                assert subscribers.status_code == 200
                assert subscribers.json()["subscribers_count"] == body["subscribers_count"]

                empty = await client.get(f"/channels/{fan_a_id}")
                assert empty.status_code == 200
                empty_body = empty.json()
                assert empty_body["subscribers_count"] == 0
                assert empty_body["total_views"] == 0
                assert empty_body["videos_count"] == 0
        finally:
            await _cleanup(user_ids)

    asyncio.run(scenario())
