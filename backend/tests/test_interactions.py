import asyncio
import uuid
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.api.v1.subscriptions import subscribe
from app.models import Reaction, User, UserRole
from app.schemas.interaction import VideoReactionsSummary
from app.services.interaction import (
    SelfSubscriptionError,
    resolve_reaction_toggle,
    set_video_reaction,
    toggle_subscription,
)


class FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.deleted: list[object] = []
        self.committed = False

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def delete(self, obj: object) -> None:
        self.deleted.append(obj)

    async def commit(self) -> None:
        self.committed = True


def _user() -> User:
    return User(
        id=uuid.uuid4(),
        email="alice@example.com",
        username="alice",
        hashed_password="hashed",
        role=UserRole.USER,
    )


@pytest.mark.parametrize(
    ("current", "requested", "action", "stored"),
    [
        (None, True, "create", True),
        (None, False, "create", False),
        (True, True, "delete", None),
        (False, False, "delete", None),
        (True, False, "update", False),
        (False, True, "update", True),
    ],
)
def test_resolve_reaction_toggle(
    current: bool | None,
    requested: bool,
    action: str,
    stored: bool | None,
) -> None:
    decision = resolve_reaction_toggle(current, requested)
    assert decision.action == action
    assert decision.is_like is stored


@pytest.mark.parametrize(
    ("current", "requested"),
    [
        (None, True),
        (None, False),
        (True, True),
        (False, False),
        (True, False),
        (False, True),
    ],
)
def test_set_video_reaction_applies_toggle(
    monkeypatch: pytest.MonkeyPatch,
    current: bool | None,
    requested: bool,
) -> None:
    decision = resolve_reaction_toggle(current, requested)
    video_id = uuid.uuid4()
    user = _user()
    existing = None
    if current is not None:
        existing = Reaction(video_id=video_id, user_id=user.id, is_like=current)

    async def fake_get_video(*_args: object, **_kwargs: object) -> None:
        return None

    async def fake_find(*_args: object, **_kwargs: object) -> Reaction | None:
        return existing

    async def fake_summary(*_args: object, **_kwargs: object) -> VideoReactionsSummary:
        return VideoReactionsSummary(
            likes_count=0,
            dislikes_count=0,
            user_reaction=decision.is_like,
        )

    monkeypatch.setattr("app.services.interaction.get_video", fake_get_video)
    monkeypatch.setattr("app.services.interaction._find_user_reaction", fake_find)
    monkeypatch.setattr("app.services.interaction.get_video_reactions", fake_summary)

    session = FakeSession()
    result = asyncio.run(set_video_reaction(session, video_id, user, requested))

    assert session.committed is True
    assert result.user_reaction is decision.is_like
    if decision.action == "create":
        assert len(session.added) == 1
        created = session.added[0]
        assert isinstance(created, Reaction)
        assert created.is_like is requested
        assert created.video_id == video_id
        assert created.user_id == user.id
        assert session.deleted == []
    elif decision.action == "delete":
        assert session.deleted == [existing]
        assert session.added == []
    else:
        assert existing is not None
        assert existing.is_like is requested
        assert session.added == []
        assert session.deleted == []


def test_toggle_subscription_rejects_self() -> None:
    user = _user()
    session = AsyncMock()

    with pytest.raises(SelfSubscriptionError):
        asyncio.run(toggle_subscription(session, user.id, user))

    session.get.assert_not_called()
    session.add.assert_not_called()
    session.commit.assert_not_called()


def test_subscribe_to_self_returns_400() -> None:
    user = _user()
    session = AsyncMock()

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(subscribe(user.id, session, user))

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Cannot subscribe to yourself"
    session.get.assert_not_called()
    session.add.assert_not_called()
