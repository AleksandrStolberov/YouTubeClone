import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User, Video, VideoAllowedUser
from app.schemas.moderation import AllowedUserRead
from app.services.video import VideoNotFoundError


class AccessForbiddenError(Exception):
    """Raised when the caller does not own the video."""


class AccessNotFoundError(Exception):
    """Raised when the user is not on the video whitelist."""


class AccessAlreadyGrantedError(Exception):
    """Raised when the user is already allowed to watch the video."""


class UserNotFoundError(Exception):
    """Raised when the user id does not exist."""


def _allowed_user(user: User) -> AllowedUserRead:
    return AllowedUserRead(user_id=user.id, username=user.username, email=user.email)


async def _owned_video(
    session: AsyncSession,
    video_id: uuid.UUID,
    actor: User,
) -> Video:
    video = await session.get(Video, video_id)
    if video is None:
        raise VideoNotFoundError
    if video.user_id != actor.id:
        raise AccessForbiddenError
    return video


async def grant_access(
    session: AsyncSession,
    video_id: uuid.UUID,
    actor: User,
    user_id: uuid.UUID,
) -> AllowedUserRead:
    """Add a user to the private-video whitelist. Only the owner may do this."""
    video = await _owned_video(session, video_id, actor)
    user = await session.get(User, user_id)
    if user is None:
        raise UserNotFoundError

    session.add(VideoAllowedUser(video_id=video.id, user_id=user.id))
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        if getattr(exc.orig, "sqlstate", None) != "23505":
            raise
        raise AccessAlreadyGrantedError from exc
    return _allowed_user(user)


async def revoke_access(
    session: AsyncSession,
    video_id: uuid.UUID,
    actor: User,
    user_id: uuid.UUID,
) -> None:
    """Remove a user from the whitelist. Only the owner may do this."""
    video = await _owned_video(session, video_id, actor)
    entry = await session.scalar(
        select(VideoAllowedUser).where(
            VideoAllowedUser.video_id == video.id,
            VideoAllowedUser.user_id == user_id,
        )
    )
    if entry is None:
        raise AccessNotFoundError
    await session.delete(entry)
    await session.commit()


async def list_access(
    session: AsyncSession,
    video_id: uuid.UUID,
    actor: User,
) -> list[AllowedUserRead]:
    """Return whitelist accounts, ordered by username. Only the owner may list them."""
    video = await _owned_video(session, video_id, actor)
    rows = await session.scalars(
        select(User)
        .join(VideoAllowedUser, VideoAllowedUser.user_id == User.id)
        .where(VideoAllowedUser.video_id == video.id)
        .order_by(User.username.asc(), User.id.asc())
    )
    return [_allowed_user(user) for user in rows.all()]
