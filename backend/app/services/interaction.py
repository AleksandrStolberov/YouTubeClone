import uuid
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Comment, Reaction, Subscription, User, UserRole
from app.schemas.interaction import (
    CommentCreate,
    CommentRead,
    SubscribersCount,
    SubscriptionStatus,
    VideoReactionsSummary,
)
from app.services.video import get_video

ReactionAction = Literal["create", "delete", "update"]
_STAFF_ROLES = {UserRole.MODERATOR.value, UserRole.ADMIN.value}


class SelfSubscriptionError(Exception):
    """Raised when a user tries to subscribe to their own channel."""


class ChannelNotFoundError(Exception):
    """Raised when the channel user id does not exist."""


class CommentNotFoundError(Exception):
    """Raised when the comment id does not exist."""


class CommentForbiddenError(Exception):
    """Raised when the caller cannot delete the comment."""


@dataclass(frozen=True)
class ReactionToggle:
    """What to do with the viewer's current like or dislike."""

    action: ReactionAction
    is_like: bool | None


def resolve_reaction_toggle(current: bool | None, requested: bool) -> ReactionToggle:
    """Choose create, delete, or update for one user's reaction on a video.

    ``current`` is ``None`` when the user has no reaction yet, ``True`` for a
    like, and ``False`` for a dislike. The same value sent again removes the
    reaction. The opposite value replaces it.
    """
    if current is None:
        return ReactionToggle("create", requested)
    if current is requested:
        return ReactionToggle("delete", None)
    return ReactionToggle("update", requested)


async def set_video_reaction(
    session: AsyncSession,
    video_id: uuid.UUID,
    user: User,
    is_like: bool,
) -> VideoReactionsSummary:
    """Apply the like/dislike toggle and return the updated counters."""
    await get_video(session, video_id, user)
    existing = await _find_user_reaction(session, video_id, user.id)
    decision = resolve_reaction_toggle(
        None if existing is None else existing.is_like,
        is_like,
    )

    if decision.action == "create":
        session.add(Reaction(video_id=video_id, user_id=user.id, is_like=is_like))
    elif existing is None:
        raise RuntimeError("Reaction toggle expected an existing row")
    elif decision.action == "delete":
        await session.delete(existing)
    else:
        existing.is_like = is_like

    await session.commit()
    return await get_video_reactions(session, video_id, user)


async def get_video_reactions(
    session: AsyncSession,
    video_id: uuid.UUID,
    viewer: User | None,
) -> VideoReactionsSummary:
    """Return like and dislike totals and the viewer's reaction, if any."""
    await get_video(session, video_id, viewer)
    counts = await session.execute(
        select(
            func.count().filter(Reaction.is_like.is_(True)),
            func.count().filter(Reaction.is_like.is_(False)),
        ).where(Reaction.video_id == video_id)
    )
    likes_count, dislikes_count = counts.one()
    user_reaction: bool | None = None
    if viewer is not None:
        existing = await _find_user_reaction(session, video_id, viewer.id)
        if existing is not None:
            user_reaction = existing.is_like
    return VideoReactionsSummary(
        likes_count=int(likes_count or 0),
        dislikes_count=int(dislikes_count or 0),
        user_reaction=user_reaction,
    )


async def add_comment(
    session: AsyncSession,
    video_id: uuid.UUID,
    author: User,
    data: CommentCreate,
) -> CommentRead:
    """Store a comment for a video the author is allowed to view."""
    await get_video(session, video_id, author)
    comment = Comment(video_id=video_id, user_id=author.id, text=data.text)
    session.add(comment)
    await session.commit()
    await session.refresh(comment)
    return _comment_read(comment, author.username)


async def list_comments(
    session: AsyncSession,
    video_id: uuid.UUID,
    viewer: User | None,
    *,
    limit: int,
    offset: int,
) -> list[CommentRead]:
    """Return comments newest first."""
    await get_video(session, video_id, viewer)
    stmt = (
        select(Comment, User.username)
        .join(User, User.id == Comment.user_id)
        .where(Comment.video_id == video_id)
        .order_by(Comment.created_at.desc(), Comment.id.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = await session.execute(stmt)
    return [_comment_read(comment, username) for comment, username in rows.all()]


async def remove_comment(
    session: AsyncSession,
    comment_id: uuid.UUID,
    actor: User,
) -> None:
    """Delete a comment when the actor is the author, a moderator, or an admin."""
    comment = await session.get(Comment, comment_id)
    if comment is None:
        raise CommentNotFoundError
    if comment.user_id != actor.id and not _is_staff(actor):
        raise CommentForbiddenError
    await session.delete(comment)
    await session.commit()


async def toggle_subscription(
    session: AsyncSession,
    channel_id: uuid.UUID,
    subscriber: User,
) -> SubscriptionStatus:
    """Subscribe when missing, unsubscribe when the row already exists."""
    if channel_id == subscriber.id:
        raise SelfSubscriptionError
    channel = await session.get(User, channel_id)
    if channel is None:
        raise ChannelNotFoundError

    result = await session.execute(
        select(Subscription).where(
            Subscription.channel_id == channel_id,
            Subscription.subscriber_id == subscriber.id,
        )
    )
    existing = result.scalar_one_or_none()
    if existing is None:
        session.add(Subscription(channel_id=channel_id, subscriber_id=subscriber.id))
        is_subscribed = True
    else:
        await session.delete(existing)
        is_subscribed = False
    await session.commit()

    count = await _count_subscribers(session, channel_id)
    return SubscriptionStatus(
        channel_id=channel_id,
        is_subscribed=is_subscribed,
        subscribers_count=count,
    )


async def get_subscribers_count(
    session: AsyncSession,
    channel_id: uuid.UUID,
) -> SubscribersCount:
    """Return how many users are subscribed to the channel."""
    channel = await session.get(User, channel_id)
    if channel is None:
        raise ChannelNotFoundError
    return SubscribersCount(subscribers_count=await _count_subscribers(session, channel_id))


def _comment_read(comment: Comment, username: str) -> CommentRead:
    return CommentRead(
        id=comment.id,
        video_id=comment.video_id,
        user_id=comment.user_id,
        author_username=username,
        text=comment.text,
        created_at=comment.created_at,
    )


def _is_staff(user: User) -> bool:
    role = user.role
    name = role.value if isinstance(role, UserRole) else str(role)
    return name in _STAFF_ROLES


async def _find_user_reaction(
    session: AsyncSession,
    video_id: uuid.UUID,
    user_id: uuid.UUID,
) -> Reaction | None:
    result = await session.execute(
        select(Reaction).where(
            Reaction.video_id == video_id,
            Reaction.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def _count_subscribers(session: AsyncSession, channel_id: uuid.UUID) -> int:
    result = await session.scalar(
        select(func.count())
        .select_from(Subscription)
        .where(Subscription.channel_id == channel_id)
    )
    return int(result or 0)
