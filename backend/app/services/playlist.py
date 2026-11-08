import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Playlist, PlaylistVideo, User, UserRole, Video
from app.schemas.playlist import (
    PlaylistCreate,
    PlaylistDetailRead,
    PlaylistRead,
    PlaylistUpdate,
    PlaylistVideoRead,
)
from app.schemas.video import VideoRead
from app.services.video import get_video, visible_video_ids


class PlaylistNotFoundError(Exception):
    """Raised when the playlist id does not exist."""


class PlaylistForbiddenError(Exception):
    """Raised when the caller cannot view or change the playlist."""


class UserNotFoundError(Exception):
    """Raised when a playlist list is requested for a missing user."""


class PlaylistVideoExistsError(Exception):
    """Raised when the video is already stored in the playlist."""


class PlaylistVideoMissingError(Exception):
    """Raised when the video is not a member of the playlist."""


async def create_playlist(
    session: AsyncSession,
    owner: User,
    data: PlaylistCreate,
) -> PlaylistRead:
    """Store a playlist owned by the signed-in user."""
    playlist = Playlist(
        title=data.title,
        description=data.description,
        is_private=data.is_private,
        user_id=owner.id,
    )
    session.add(playlist)
    await session.commit()
    await session.refresh(playlist)
    return _playlist_read(playlist, 0)


async def get_playlist_detail(
    session: AsyncSession,
    playlist_id: uuid.UUID,
    viewer: User | None,
) -> PlaylistDetailRead:
    """Return a playlist and the videos this viewer is allowed to see.

    A private playlist is visible only to its author. Private videos and
    banned videos inside a playlist stay hidden from viewers who cannot open
    those videos. ``videos_count`` is the number of membership rows, before
    that filter.
    """
    playlist = await _get_playlist(session, playlist_id)
    _ensure_can_view(playlist, viewer)
    pairs = await _load_items(session, playlist.id)
    visible = await visible_video_ids(session, [video for _, video in pairs], viewer)
    videos = [
        _video_item(video, link.position)
        for link, video in pairs
        if video.id in visible
    ]
    return PlaylistDetailRead(
        id=playlist.id,
        title=playlist.title,
        description=playlist.description,
        is_private=playlist.is_private,
        user_id=playlist.user_id,
        videos_count=len(pairs),
        created_at=playlist.created_at,
        videos=videos,
    )


async def update_playlist(
    session: AsyncSession,
    playlist_id: uuid.UUID,
    actor: User,
    data: PlaylistUpdate,
) -> PlaylistRead:
    """Change title, description, or privacy. Only the author may edit."""
    playlist = await _get_playlist(session, playlist_id)
    _ensure_owner(playlist, actor)
    changes = data.model_dump(exclude_unset=True)
    changed = False
    if "title" in changes and changes["title"] is not None and changes["title"] != playlist.title:
        playlist.title = changes["title"]
        changed = True
    if "description" in changes and changes["description"] != playlist.description:
        playlist.description = changes["description"]
        changed = True
    if (
        "is_private" in changes
        and changes["is_private"] is not None
        and changes["is_private"] != playlist.is_private
    ):
        playlist.is_private = changes["is_private"]
        changed = True
    if changed:
        playlist.updated_at = datetime.now(timezone.utc)
        await session.commit()
        await session.refresh(playlist)
    total = await _videos_count(session, playlist.id)
    return _playlist_read(playlist, total)


async def delete_playlist(
    session: AsyncSession,
    playlist_id: uuid.UUID,
    actor: User,
) -> None:
    """Delete a playlist. Allowed for the author and for an admin."""
    playlist = await _get_playlist(session, playlist_id)
    if playlist.user_id != actor.id and not _is_admin(actor):
        raise PlaylistForbiddenError
    await session.delete(playlist)
    await session.commit()


async def add_video_to_playlist(
    session: AsyncSession,
    playlist_id: uuid.UUID,
    video_id: uuid.UUID,
    actor: User,
) -> PlaylistDetailRead:
    """Append a video the author can view. Position is the next free index."""
    playlist = await _get_playlist(session, playlist_id, lock=True)
    _ensure_owner(playlist, actor)
    await get_video(session, video_id, actor)
    existing = await session.scalar(
        select(PlaylistVideo.id).where(
            PlaylistVideo.playlist_id == playlist.id,
            PlaylistVideo.video_id == video_id,
        )
    )
    if existing is not None:
        raise PlaylistVideoExistsError

    current = await session.scalar(
        select(func.max(PlaylistVideo.position)).where(PlaylistVideo.playlist_id == playlist.id)
    )
    position = 0 if current is None else int(current) + 1
    session.add(
        PlaylistVideo(
            playlist_id=playlist.id,
            video_id=video_id,
            position=position,
        )
    )
    playlist.updated_at = datetime.now(timezone.utc)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        if _is_unique_violation(exc):
            raise PlaylistVideoExistsError from exc
        raise
    return await get_playlist_detail(session, playlist.id, actor)


async def remove_video_from_playlist(
    session: AsyncSession,
    playlist_id: uuid.UUID,
    video_id: uuid.UUID,
    actor: User,
) -> None:
    """Drop a video and pack the remaining positions back to 0..n-1."""
    playlist = await _get_playlist(session, playlist_id, lock=True)
    _ensure_owner(playlist, actor)
    link = await session.scalar(
        select(PlaylistVideo).where(
            PlaylistVideo.playlist_id == playlist.id,
            PlaylistVideo.video_id == video_id,
        )
    )
    if link is None:
        raise PlaylistVideoMissingError
    await session.delete(link)
    remaining = (
        await session.scalars(
            select(PlaylistVideo)
            .where(PlaylistVideo.playlist_id == playlist.id)
            .order_by(PlaylistVideo.position.asc(), PlaylistVideo.added_at.asc())
        )
    ).all()
    for index, row in enumerate(remaining):
        row.position = index
    playlist.updated_at = datetime.now(timezone.utc)
    await session.commit()


async def list_user_playlists(
    session: AsyncSession,
    user_id: uuid.UUID,
    viewer: User | None,
) -> list[PlaylistRead]:
    """List a user's playlists. Someone else's private playlists are omitted."""
    owner = await session.get(User, user_id)
    if owner is None:
        raise UserNotFoundError

    counts = (
        select(
            PlaylistVideo.playlist_id,
            func.count().label("videos_count"),
        )
        .group_by(PlaylistVideo.playlist_id)
        .subquery()
    )
    stmt = (
        select(Playlist, func.coalesce(counts.c.videos_count, 0))
        .outerjoin(counts, counts.c.playlist_id == Playlist.id)
        .where(Playlist.user_id == user_id)
        .order_by(Playlist.created_at.desc(), Playlist.id.desc())
    )
    if viewer is None or viewer.id != user_id:
        stmt = stmt.where(Playlist.is_private.is_(False))
    rows = await session.execute(stmt)
    return [_playlist_read(playlist, int(total or 0)) for playlist, total in rows.all()]


async def _get_playlist(
    session: AsyncSession,
    playlist_id: uuid.UUID,
    *,
    lock: bool = False,
) -> Playlist:
    if lock:
        playlist = await session.get(Playlist, playlist_id, with_for_update=True)
    else:
        playlist = await session.get(Playlist, playlist_id)
    if playlist is None:
        raise PlaylistNotFoundError
    return playlist


async def _load_items(
    session: AsyncSession,
    playlist_id: uuid.UUID,
) -> list[tuple[PlaylistVideo, Video]]:
    rows = await session.execute(
        select(PlaylistVideo, Video)
        .join(Video, Video.id == PlaylistVideo.video_id)
        .where(PlaylistVideo.playlist_id == playlist_id)
        .order_by(
            PlaylistVideo.position.asc(),
            PlaylistVideo.added_at.asc(),
            PlaylistVideo.id.asc(),
        )
    )
    return list(rows.all())


async def _videos_count(session: AsyncSession, playlist_id: uuid.UUID) -> int:
    total = await session.scalar(
        select(func.count())
        .select_from(PlaylistVideo)
        .where(PlaylistVideo.playlist_id == playlist_id)
    )
    return int(total or 0)


def _ensure_can_view(playlist: Playlist, viewer: User | None) -> None:
    if playlist.is_private and (viewer is None or viewer.id != playlist.user_id):
        raise PlaylistForbiddenError


def _ensure_owner(playlist: Playlist, actor: User) -> None:
    if playlist.user_id != actor.id:
        raise PlaylistForbiddenError


def _is_admin(user: User) -> bool:
    return _role_name(user) == UserRole.ADMIN.value


def _role_name(user: User) -> str:
    role = user.role
    return role.value if isinstance(role, UserRole) else str(role)


def _playlist_read(playlist: Playlist, videos_count: int) -> PlaylistRead:
    return PlaylistRead(
        id=playlist.id,
        title=playlist.title,
        description=playlist.description,
        is_private=playlist.is_private,
        user_id=playlist.user_id,
        videos_count=videos_count,
        created_at=playlist.created_at,
    )


def _video_item(video: Video, position: int) -> PlaylistVideoRead:
    payload = VideoRead.model_validate(video).model_dump()
    payload["position"] = position
    return PlaylistVideoRead.model_validate(payload)


def _is_unique_violation(exc: IntegrityError) -> bool:
    return getattr(exc.orig, "sqlstate", None) == "23505"
