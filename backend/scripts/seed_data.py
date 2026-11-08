"""Idempotent demo fixture for manual checks of the YouTube clone.

Users are matched by email, videos and playlists by title, and the other
tables by their natural keys, so a second run does not insert duplicates.
The run restores demo metadata on those videos (description, category, tags,
views, duration, privacy, and a cleared ban) and puts the seeded complaint
back to ``pending``. Passwords of the demo emails are set to the values
printed at the end. Extra comments or reactions that were not part of this
fixture are left in place.

Accounts:

    admin@example.com       Admin123!       admin
    moderator@example.com   Moderator123!   moderator
    user1@example.com       User1123!       user
    user2@example.com       User2123!       user
    user3@example.com       User3123!       user

``user2`` is on the whitelist of the private video. ``user3`` filed the
pending complaint. ``user1``, ``user2``, and ``user3`` subscribe to each
other.

The stack must be running. From the repository root:

    docker compose exec backend python -m scripts.seed_data

Inside that container Postgres is ``db`` and MinIO is ``minio:9000``.
To run from a host checkout against the published ports:

    cd backend
    POSTGRES_HOST=localhost MINIO_ENDPOINT=localhost:9000 python -m scripts.seed_data

``assets/sample.mp4`` is a shared two-second 320x180 H.264/AAC test clip
(test pattern and a sine tone). Every seeded video points at that file.
Covers are PNGs painted in this module, one color per video, and uploaded
to the thumbnails bucket. Regenerate the clip with::

    docker run --rm -v "$PWD/backend/scripts/assets:/out" mwader/static-ffmpeg:7.1 \\
      -y -f lavfi -i testsrc=size=320x180:rate=15:duration=2 \\
      -f lavfi -i sine=frequency=440:duration=2 \\
      -c:v libx264 -pix_fmt yuv420p -profile:v baseline -level 3.0 \\
      -c:a aac -b:a 64k -shortest -movflags +faststart /out/sample.mp4
"""

from __future__ import annotations

import asyncio
import os
import struct
import sys
import zlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path

from minio.error import S3Error
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_engine, async_sessionmaker
from app.core.s3 import S3Storage, StorageError, get_s3_client
from app.core.security import hash_password, verify_password
from app.models import (
    Comment,
    Playlist,
    PlaylistVideo,
    Reaction,
    Subscription,
    User,
    UserRole,
    Video,
    VideoAllowedUser,
    VideoReport,
    WatchHistory,
)

SAMPLE_DURATION_SECONDS = 2
THUMBNAIL_WIDTH = 320
THUMBNAIL_HEIGHT = 180
_ASSETS = Path(__file__).resolve().parent / "assets"
_SAMPLE_MP4 = _ASSETS / "sample.mp4"
_MISSING_OBJECT = frozenset({"NoSuchKey", "NoSuchObject", "NotFound"})


class SeedError(Exception):
    """The fixture cannot be applied."""


@dataclass
class Counters:
    rows_created: int = 0
    rows_kept: int = 0
    objects_uploaded: int = 0
    objects_kept: int = 0

    def row(self, action: str, extra: int = 0) -> None:
        if action == "created":
            self.rows_created += 1
        else:
            self.rows_kept += 1
        self.rows_created += extra

    def obj(self, action: str) -> None:
        if action == "uploaded":
            self.objects_uploaded += 1
        else:
            self.objects_kept += 1


@dataclass(frozen=True)
class UserSpec:
    email: str
    username: str
    password: str
    role: UserRole


@dataclass(frozen=True)
class VideoSpec:
    slug: str
    title: str
    description: str
    category: str
    tags: tuple[str, ...]
    views_count: int
    is_private: bool
    owner_username: str
    color: tuple[int, int, int]
    days_ago: int


@dataclass(frozen=True)
class PlaylistSpec:
    owner_username: str
    title: str
    description: str
    is_private: bool
    video_slugs: tuple[str, ...]


@dataclass(frozen=True)
class ReportSpec:
    video_slug: str
    reporter_username: str
    reason: str


@dataclass(frozen=True)
class Ansi:
    reset: str
    bold: str
    cyan: str
    green: str
    yellow: str
    red: str
    dim: str


@dataclass
class AccountFact:
    role: str
    username: str
    email: str
    password: str


@dataclass
class VideoFact:
    title: str
    category: str
    views_count: int
    owner: str
    is_private: bool
    has_pending_report: bool


@dataclass
class PlaylistFact:
    title: str
    owner: str
    is_private: bool
    size: int


@dataclass
class ObjectFact:
    bucket: str
    key: str
    size: int


@dataclass
class Facts:
    problems: list[str]
    accounts: list[AccountFact]
    videos: list[VideoFact]
    playlists: list[PlaylistFact]
    objects: list[ObjectFact]
    totals: dict[str, int]
    likes: int
    dislikes: int


USERS: tuple[UserSpec, ...] = (
    UserSpec("admin@example.com", "admin", "Admin123!", UserRole.ADMIN),
    UserSpec("moderator@example.com", "moderator", "Moderator123!", UserRole.MODERATOR),
    UserSpec("user1@example.com", "user1", "User1123!", UserRole.USER),
    UserSpec("user2@example.com", "user2", "User2123!", UserRole.USER),
    UserSpec("user3@example.com", "user3", "User3123!", UserRole.USER),
)

VIDEOS: tuple[VideoSpec, ...] = (
    VideoSpec(
        slug="fastapi-clone",
        title="Building a FastAPI YouTube Clone",
        description=(
            "A walkthrough of a layered video service: upload to object storage, "
            "metadata in Postgres, and HTTP range reads for seeking."
        ),
        category="Tech",
        tags=("fastapi", "python", "backend"),
        views_count=15230,
        is_private=False,
        owner_username="user1",
        color=(32, 96, 186),
        days_ago=12,
    ),
    VideoSpec(
        slug="speedrun-echoes",
        title="Speedrun: Dungeon of Echoes",
        description="A single-segment run through Dungeon of Echoes, with the boss skip called out in the last third.",
        category="Gaming",
        tags=("speedrun", "indie", "gaming"),
        views_count=88412,
        is_private=False,
        owner_username="user2",
        color=(36, 140, 72),
        days_ago=9,
    ),
    VideoSpec(
        slug="lofi-session",
        title="Late Night Lo-fi Session",
        description="A short instrumental loop meant to sit under late-night work.",
        category="Music",
        tags=("lofi", "instrumental", "music"),
        views_count=42007,
        is_private=False,
        owner_username="user3",
        color=(126, 58, 168),
        days_ago=7,
    ),
    VideoSpec(
        slug="sql-indexes",
        title="SQL Indexes in 10 Minutes",
        description="When a btree index helps a Postgres filter, and when it does not.",
        category="Education",
        tags=("sql", "postgres", "indexes"),
        views_count=3105,
        is_private=False,
        owner_username="user1",
        color=(196, 112, 32),
        days_ago=4,
    ),
    VideoSpec(
        slug="release-notes-q4",
        title="Internal Release Notes: Q4",
        description="Q4 notes for the core team. Private: visible to the author and to user2.",
        category="Tech",
        tags=("release", "internal", "notes"),
        views_count=18,
        is_private=True,
        owner_username="user1",
        color=(24, 48, 96),
        days_ago=2,
    ),
    VideoSpec(
        slug="prototype-unbox",
        title="Unbox of the Prototype Console",
        description="A desk recording of a prototype console. The title oversells the clip, which is why it has an open complaint.",
        category="Gaming",
        tags=("unbox", "hardware", "gaming"),
        views_count=960,
        is_private=False,
        owner_username="user2",
        color=(176, 48, 48),
        days_ago=1,
    ),
)

# (subscriber username, channel username)
SUBSCRIPTIONS: tuple[tuple[str, str], ...] = (
    ("user1", "user2"),
    ("user1", "user3"),
    ("user2", "user1"),
    ("user2", "user3"),
    ("user3", "user1"),
    ("user3", "user2"),
)

# (video slug, username, is_like)
REACTIONS: tuple[tuple[str, str, bool], ...] = (
    ("fastapi-clone", "user2", True),
    ("fastapi-clone", "user3", True),
    ("fastapi-clone", "moderator", True),
    ("speedrun-echoes", "user1", True),
    ("speedrun-echoes", "user3", True),
    ("speedrun-echoes", "admin", True),
    ("lofi-session", "user1", True),
    ("lofi-session", "user2", False),
    ("sql-indexes", "user2", True),
    ("sql-indexes", "user3", False),
    ("sql-indexes", "admin", True),
    ("release-notes-q4", "user2", True),
    ("prototype-unbox", "user1", False),
    ("prototype-unbox", "user3", False),
    ("prototype-unbox", "moderator", False),
)

# (video slug, username, text, minutes_ago) — larger minutes_ago is older.
COMMENTS: tuple[tuple[str, str, str, int], ...] = (
    (
        "fastapi-clone",
        "user2",
        "Came here for the Range request part. Seeking in the player depends on it.",
        240,
    ),
    (
        "fastapi-clone",
        "user3",
        "Are the cover images stored in the same bucket as the video?",
        210,
    ),
    (
        "fastapi-clone",
        "user1",
        "No. Video bytes go to the videos bucket and covers go to thumbnails. Postgres stores only the keys.",
        180,
    ),
    (
        "fastapi-clone",
        "user2",
        "That matches the spec. Subscribed, the next part on private videos should be useful.",
        150,
    ),
    (
        "fastapi-clone",
        "moderator",
        "Checked the description and tags. Nothing to take down on this one.",
        40,
    ),
    (
        "prototype-unbox",
        "user3",
        "This looks like footage of a console that has not been announced. I filed a complaint.",
        90,
    ),
    (
        "prototype-unbox",
        "user1",
        "The title promises an unboxing, but the clip does not show the device.",
        70,
    ),
    (
        "prototype-unbox",
        "user2",
        "It is my own recording of a prototype on the desk. I will leave it up unless a moderator disagrees.",
        20,
    ),
    (
        "lofi-session",
        "user1",
        "Left this on while reading the migration notes.",
        300,
    ),
    (
        "lofi-session",
        "user2",
        "Quiet enough for a late session.",
        50,
    ),
    (
        "sql-indexes",
        "user3",
        "The bitmap index aside is the part I keep coming back to.",
        120,
    ),
    (
        "sql-indexes",
        "user2",
        "Clearer than the chapter in the Postgres docs.",
        100,
    ),
    (
        "speedrun-echoes",
        "user1",
        "The boss skip at the end is the whole run. Nice pacing.",
        160,
    ),
    (
        "speedrun-echoes",
        "user3",
        "Watched it twice. The timer in the corner is readable.",
        30,
    ),
)

# (username, video slug, progress_seconds, hours_ago)
HISTORY: tuple[tuple[str, str, int, int], ...] = (
    ("user1", "speedrun-echoes", 1, 5),
    ("user1", "lofi-session", 2, 4),
    ("user1", "prototype-unbox", 0, 3),
    ("user2", "fastapi-clone", 1, 8),
    ("user2", "sql-indexes", 2, 7),
    ("user2", "release-notes-q4", 1, 1),
    ("user3", "fastapi-clone", 2, 10),
    ("user3", "speedrun-echoes", 1, 9),
    ("user3", "sql-indexes", 1, 6),
    ("user3", "lofi-session", 0, 2),
)

# (video slug, username granted access)
ACCESS: tuple[tuple[str, str], ...] = (("release-notes-q4", "user2"),)

REPORT = ReportSpec(
    video_slug="prototype-unbox",
    reporter_username="user3",
    reason="Misleading title and footage that looks unlicensed.",
)

PLAYLISTS: tuple[PlaylistSpec, ...] = (
    PlaylistSpec(
        owner_username="user1",
        title="Weekend Tech Picks",
        description="Public picks: the FastAPI walkthrough and the SQL index lesson.",
        is_private=False,
        video_slugs=("fastapi-clone", "sql-indexes"),
    ),
    PlaylistSpec(
        owner_username="user2",
        title="Watch Later",
        description="Private queue, including the release notes shared with this account.",
        is_private=True,
        video_slugs=("release-notes-q4", "lofi-session", "speedrun-echoes"),
    ),
)


def _validate_specs() -> None:
    slugs = [video.slug for video in VIDEOS]
    titles = [video.title for video in VIDEOS]
    if len(slugs) != len(set(slugs)) or len(titles) != len(set(titles)):
        raise SeedError("Seed video slug or title is duplicated")
    if not 4 <= len(VIDEOS) <= 6:
        raise SeedError("Seed data must contain 4 to 6 videos")
    if {video.category for video in VIDEOS} != {"Tech", "Gaming", "Music", "Education"}:
        raise SeedError("Seed videos must cover Tech, Gaming, Music, and Education")

    emails = [user.email for user in USERS]
    usernames = [user.username for user in USERS]
    if len(emails) != len(set(emails)) or len(usernames) != len(set(usernames)):
        raise SeedError("Seed account email or username is duplicated")
    username_set = set(usernames)
    known = set(slugs)
    authors = [user.username for user in USERS if user.role == UserRole.USER]
    author_set = set(authors)

    private = [video for video in VIDEOS if video.is_private]
    if len(private) != 1:
        raise SeedError("Seed data must contain exactly one private video")
    if {slug for slug, _viewer in ACCESS} != {video.slug for video in private}:
        raise SeedError("Whitelist entries must cover the private video")
    for slug, viewer in ACCESS:
        if viewer not in username_set:
            raise SeedError(f"Whitelist viewer {viewer} is not a seed user")
        owner = next(video.owner_username for video in VIDEOS if video.slug == slug)
        if viewer == owner:
            raise SeedError("Whitelist viewer must be someone other than the author")

    if REPORT.video_slug not in known or REPORT.reporter_username not in username_set:
        raise SeedError("Seed report points at an unknown video or user")
    reported = next(video for video in VIDEOS if video.slug == REPORT.video_slug)
    if reported.is_private:
        raise SeedError("Pending complaint must target a public video")

    expected_subs = {(sub, channel) for sub in authors for channel in authors if sub != channel}
    if set(SUBSCRIPTIONS) != expected_subs:
        raise SeedError("user1, user2, and user3 must subscribe to each other")

    reaction_pairs = [(slug, username) for slug, username, _like in REACTIONS]
    if len(reaction_pairs) != len(set(reaction_pairs)):
        raise SeedError("A user is given two reactions on one video")
    flags = [is_like for _slug, _username, is_like in REACTIONS]
    if not any(flags) or all(flags):
        raise SeedError("Seed reactions need both likes and dislikes")
    for slug, username, _is_like in REACTIONS:
        if slug not in known or username not in username_set:
            raise SeedError("A reaction points at an unknown video or user")

    for slug, username, _text, _minutes in COMMENTS:
        if slug not in known or username not in username_set:
            raise SeedError("A comment points at an unknown video or user")

    watched_by = set()
    history_pairs = []
    for username, slug, progress, _hours in HISTORY:
        watched_by.add(username)
        history_pairs.append((username, slug))
        if username not in author_set:
            raise SeedError("Watch history must belong to a regular user")
        if slug not in known:
            raise SeedError("Watch history points at an unknown video")
        if not 0 <= progress <= SAMPLE_DURATION_SECONDS:
            raise SeedError("Watch progress is outside the sample duration")
    if watched_by != author_set:
        raise SeedError("Each regular user needs watch history")
    if len(history_pairs) != len(set(history_pairs)):
        raise SeedError("Watch history repeats a user and video")

    if {playlist.is_private for playlist in PLAYLISTS} != {True, False}:
        raise SeedError("Seed playlists need one public and one private list")
    if len({playlist.title for playlist in PLAYLISTS}) != len(PLAYLISTS):
        raise SeedError("Seed playlist titles are duplicated")
    private_slugs = {video.slug for video in private}
    for playlist in PLAYLISTS:
        if playlist.owner_username not in username_set:
            raise SeedError("A playlist points at an unknown owner")
        if not playlist.video_slugs or any(slug not in known for slug in playlist.video_slugs):
            raise SeedError(f"Playlist {playlist.title} has an unknown video")
        included = private_slugs.intersection(playlist.video_slugs)
        if playlist.is_private and not included:
            raise SeedError("Private playlist should include the private video")
        if not playlist.is_private and included:
            raise SeedError("Public playlist includes a private video")


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(tag + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)


def thumbnail_png(width: int, height: int, rgb: tuple[int, int, int]) -> bytes:
    """Build a solid RGB PNG with a lighter band so each cover is distinct."""
    if width < 1 or height < 1 or any(channel < 0 or channel > 255 for channel in rgb):
        raise SeedError("Thumbnail size or color is invalid")
    accent = tuple(min(255, channel + 90) for channel in rgb)
    body = b"\x00" + bytes(rgb) * width
    band = b"\x00" + bytes(accent) * width
    band_height = max(1, height // 5)
    raw = b"".join(band if y < band_height else body for y in range(height))
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", zlib.compress(raw, 9))
        + _png_chunk(b"IEND", b"")
    )


def load_sample_mp4() -> bytes:
    if not _SAMPLE_MP4.is_file():
        raise FileNotFoundError(
            f"Missing {_SAMPLE_MP4}. Add the two-second test clip before seeding."
        )
    data = _SAMPLE_MP4.read_bytes()
    if b"ftyp" not in data[:32]:
        raise ValueError(f"{_SAMPLE_MP4} is not an MP4 file")
    return data


def _role_name(role: UserRole | str) -> str:
    if isinstance(role, UserRole):
        return role.value
    return str(role)


def _object_key(slug: str, extension: str) -> str:
    return f"seed/{slug}.{extension}"


async def _ensure_object(
    storage: S3Storage,
    bucket: str,
    key: str,
    payload: bytes,
    content_type: str,
) -> str:
    def _stat():
        try:
            return storage.client.stat_object(bucket, key)
        except S3Error as exc:
            if exc.code in _MISSING_OBJECT:
                return None
            raise

    stat = await asyncio.to_thread(_stat)
    if stat is not None and stat.size:
        return "exists"
    await asyncio.to_thread(
        storage.put_object,
        bucket,
        key,
        BytesIO(payload),
        len(payload),
        content_type,
    )
    return "uploaded"


async def _ensure_user(session: AsyncSession, spec: UserSpec) -> tuple[User, str]:
    user = await session.scalar(select(User).where(User.email == spec.email))
    if user is None:
        taken = await session.scalar(select(User).where(User.username == spec.username))
        if taken is not None:
            raise SeedError(
                f"Username {spec.username} belongs to {taken.email}, not {spec.email}"
            )
        user = User(
            email=spec.email,
            username=spec.username,
            hashed_password=hash_password(spec.password),
            role=spec.role,
        )
        session.add(user)
        return user, "created"

    action = "exists"
    if user.username != spec.username:
        taken_id = await session.scalar(select(User.id).where(User.username == spec.username))
        if taken_id is not None and taken_id != user.id:
            raise SeedError(f"Cannot rename {spec.email} to {spec.username}: username is taken")
        user.username = spec.username
        action = "updated"
    if _role_name(user.role) != spec.role.value:
        user.role = spec.role
        action = "updated"
    if not verify_password(spec.password, user.hashed_password):
        user.hashed_password = hash_password(spec.password)
        action = "updated"
    return user, action


async def _ensure_video(
    session: AsyncSession,
    storage: S3Storage,
    spec: VideoSpec,
    owner: User,
    sample_mp4: bytes,
    now: datetime,
    counters: Counters,
) -> tuple[Video, str]:
    if owner.id is None:
        raise SeedError(f"User {owner.email} has no id")
    video = await session.scalar(select(Video).where(Video.title == spec.title))
    created = video is None
    if video is None:
        video = Video(
            title=spec.title,
            description=spec.description,
            s3_key=_object_key(spec.slug, "mp4"),
            preview_s3_key=_object_key(spec.slug, "png"),
            duration=SAMPLE_DURATION_SECONDS,
            views_count=spec.views_count,
            is_private=spec.is_private,
            is_banned=False,
            ban_reason=None,
            category=spec.category,
            tags=list(spec.tags),
            user_id=owner.id,
            created_at=now - timedelta(days=spec.days_ago),
        )
        session.add(video)
    else:
        video.description = spec.description
        video.duration = SAMPLE_DURATION_SECONDS
        video.views_count = spec.views_count
        video.is_private = spec.is_private
        video.is_banned = False
        video.ban_reason = None
        video.category = spec.category
        video.tags = list(spec.tags)
        video.user_id = owner.id
        if not video.preview_s3_key:
            video.preview_s3_key = _object_key(spec.slug, "png")

    counters.obj(
        await _ensure_object(storage, storage.video_bucket, video.s3_key, sample_mp4, "video/mp4")
    )
    if not video.preview_s3_key:
        raise SeedError(f"{spec.title} has no thumbnail key")
    counters.obj(
        await _ensure_object(
            storage,
            storage.thumbnail_bucket,
            video.preview_s3_key,
            thumbnail_png(THUMBNAIL_WIDTH, THUMBNAIL_HEIGHT, spec.color),
            "image/png",
        )
    )
    return video, "created" if created else "reused"


async def _ensure_subscription(session: AsyncSession, channel: User, subscriber: User) -> str:
    if channel.id is None or subscriber.id is None:
        raise SeedError("Subscription users have no id")
    if channel.id == subscriber.id:
        raise SeedError("A user cannot subscribe to themselves")
    existing = await session.scalar(
        select(Subscription).where(
            Subscription.channel_id == channel.id,
            Subscription.subscriber_id == subscriber.id,
        )
    )
    if existing is not None:
        return "exists"
    session.add(Subscription(channel_id=channel.id, subscriber_id=subscriber.id))
    return "created"


async def _ensure_reaction(session: AsyncSession, video: Video, user: User, is_like: bool) -> str:
    existing = await session.scalar(
        select(Reaction).where(Reaction.video_id == video.id, Reaction.user_id == user.id)
    )
    if existing is None:
        session.add(Reaction(video_id=video.id, user_id=user.id, is_like=is_like))
        return "created"
    existing.is_like = is_like
    return "exists"


async def _ensure_comment(
    session: AsyncSession,
    video: Video,
    author: User,
    text: str,
    created_at: datetime,
) -> str:
    existing = await session.scalar(
        select(Comment).where(
            Comment.video_id == video.id,
            Comment.user_id == author.id,
            Comment.text == text,
        )
    )
    if existing is None:
        session.add(
            Comment(
                video_id=video.id,
                user_id=author.id,
                text=text,
                created_at=created_at,
            )
        )
        return "created"
    existing.created_at = created_at
    return "exists"


async def _ensure_history(
    session: AsyncSession,
    video: Video,
    user: User,
    progress: int,
    watched_at: datetime,
) -> str:
    existing = await session.scalar(
        select(WatchHistory).where(
            WatchHistory.video_id == video.id,
            WatchHistory.user_id == user.id,
        )
    )
    if existing is None:
        session.add(
            WatchHistory(
                video_id=video.id,
                user_id=user.id,
                progress_seconds=progress,
                watched_at=watched_at,
            )
        )
        return "created"
    existing.progress_seconds = progress
    existing.watched_at = watched_at
    return "exists"


async def _ensure_access(session: AsyncSession, video: Video, user: User) -> str:
    existing = await session.scalar(
        select(VideoAllowedUser).where(
            VideoAllowedUser.video_id == video.id,
            VideoAllowedUser.user_id == user.id,
        )
    )
    if existing is not None:
        return "exists"
    session.add(VideoAllowedUser(video_id=video.id, user_id=user.id))
    return "created"


async def _ensure_report(session: AsyncSession, video: Video, reporter: User, reason: str) -> str:
    existing = await session.scalar(
        select(VideoReport).where(
            VideoReport.video_id == video.id,
            VideoReport.reporter_id == reporter.id,
            VideoReport.reason == reason,
        )
    )
    if existing is None:
        session.add(
            VideoReport(
                video_id=video.id,
                reporter_id=reporter.id,
                reason=reason,
                status="pending",
            )
        )
        return "created"
    existing.status = "pending"
    existing.resolved_by = None
    existing.resolved_at = None
    return "exists"


async def _ensure_playlist(
    session: AsyncSession,
    owner: User,
    spec: PlaylistSpec,
    videos: dict[str, Video],
) -> tuple[str, int]:
    playlist = await session.scalar(
        select(Playlist).where(Playlist.user_id == owner.id, Playlist.title == spec.title)
    )
    created = playlist is None
    if playlist is None:
        playlist = Playlist(
            title=spec.title,
            description=spec.description,
            is_private=spec.is_private,
            user_id=owner.id,
        )
        session.add(playlist)
        await session.flush()
    else:
        playlist.description = spec.description
        playlist.is_private = spec.is_private
        playlist.updated_at = datetime.now(timezone.utc)

    items = list(
        (
            await session.scalars(
                select(PlaylistVideo).where(PlaylistVideo.playlist_id == playlist.id)
            )
        ).all()
    )
    have = {item.video_id for item in items}
    position = max((item.position for item in items), default=-1)
    added = 0
    for slug in spec.video_slugs:
        video = videos[slug]
        if video.id in have:
            continue
        position += 1
        session.add(
            PlaylistVideo(playlist_id=playlist.id, video_id=video.id, position=position)
        )
        added += 1
    return ("created" if created else "reused"), added


def _require_user(users: dict[str, User], username: str) -> User:
    try:
        return users[username]
    except KeyError as exc:
        raise SeedError(f"Seed user {username} was not created") from exc


def _require_video(videos: dict[str, Video], slug: str) -> Video:
    try:
        return videos[slug]
    except KeyError as exc:
        raise SeedError(f"Seed video {slug} was not created") from exc


async def populate(
    session: AsyncSession,
    storage: S3Storage,
    sample_mp4: bytes,
) -> Counters:
    _validate_specs()
    counters = Counters()
    now = datetime.now(timezone.utc)
    users: dict[str, User] = {}
    for spec in USERS:
        user, action = await _ensure_user(session, spec)
        users[spec.username] = user
        counters.row(action)
    await session.flush()

    videos: dict[str, Video] = {}
    for spec in VIDEOS:
        video, action = await _ensure_video(
            session,
            storage,
            spec,
            _require_user(users, spec.owner_username),
            sample_mp4,
            now,
            counters,
        )
        videos[spec.slug] = video
        counters.row(action)
    await session.flush()

    for slug, username in ACCESS:
        action = await _ensure_access(
            session,
            _require_video(videos, slug),
            _require_user(users, username),
        )
        counters.row(action)

    report_action = await _ensure_report(
        session,
        _require_video(videos, REPORT.video_slug),
        _require_user(users, REPORT.reporter_username),
        REPORT.reason,
    )
    counters.row(report_action)

    for subscriber_name, channel_name in SUBSCRIPTIONS:
        action = await _ensure_subscription(
            session,
            _require_user(users, channel_name),
            _require_user(users, subscriber_name),
        )
        counters.row(action)

    for slug, username, is_like in REACTIONS:
        action = await _ensure_reaction(
            session,
            _require_video(videos, slug),
            _require_user(users, username),
            is_like,
        )
        counters.row(action)

    for slug, username, text, minutes_ago in COMMENTS:
        action = await _ensure_comment(
            session,
            _require_video(videos, slug),
            _require_user(users, username),
            text,
            now - timedelta(minutes=minutes_ago),
        )
        counters.row(action)

    for username, slug, progress, hours_ago in HISTORY:
        action = await _ensure_history(
            session,
            _require_video(videos, slug),
            _require_user(users, username),
            progress,
            now - timedelta(hours=hours_ago),
        )
        counters.row(action)

    for spec in PLAYLISTS:
        action, added = await _ensure_playlist(
            session,
            _require_user(users, spec.owner_username),
            spec,
            videos,
        )
        counters.row(action, extra=added)
    return counters


async def _count(session: AsyncSession, model: type) -> int:
    value = await session.scalar(select(func.count()).select_from(model))
    return int(value or 0)


async def _inspect(storage: S3Storage, bucket: str, key: str) -> tuple[int, str, bytes]:
    def _read() -> tuple[int, str, bytes]:
        stat = storage.client.stat_object(bucket, key)
        response = storage.client.get_object(bucket, key)
        try:
            head = response.read(32)
        finally:
            response.close()
            response.release_conn()
        return int(stat.size or 0), str(stat.content_type or ""), head

    return await asyncio.to_thread(_read)


def _content_type_matches(actual: str, expected: str) -> bool:
    return actual.split(";", 1)[0].strip().lower() == expected


async def verify(session: AsyncSession, storage: S3Storage) -> Facts:
    problems: list[str] = []
    totals = {
        "users": await _count(session, User),
        "videos": await _count(session, Video),
        "subscriptions": await _count(session, Subscription),
        "reactions": await _count(session, Reaction),
        "comments": await _count(session, Comment),
        "history": await _count(session, WatchHistory),
        "playlists": await _count(session, Playlist),
        "reports": await _count(session, VideoReport),
    }
    likes = int(
        await session.scalar(
            select(func.count()).select_from(Reaction).where(Reaction.is_like.is_(True))
        )
        or 0
    )
    dislikes = int(
        await session.scalar(
            select(func.count()).select_from(Reaction).where(Reaction.is_like.is_(False))
        )
        or 0
    )

    accounts: list[AccountFact] = []
    by_username: dict[str, User] = {}
    for spec in USERS:
        user = await session.scalar(select(User).where(User.email == spec.email))
        if user is None:
            problems.append(f"нет пользователя {spec.email}")
            continue
        by_username[spec.username] = user
        if user.username != spec.username:
            problems.append(f"{spec.email}: логин {user.username}, ожидался {spec.username}")
        if _role_name(user.role) != spec.role.value:
            problems.append(f"{spec.email}: роль {_role_name(user.role)}")
        if not verify_password(spec.password, user.hashed_password):
            problems.append(f"пароль {spec.email} не совпадает с демо-значением")
        accounts.append(
            AccountFact(spec.role.value, user.username, user.email, spec.password)
        )

    videos: list[VideoFact] = []
    by_slug: dict[str, Video] = {}
    objects: list[ObjectFact] = []
    for spec in VIDEOS:
        video = await session.scalar(select(Video).where(Video.title == spec.title))
        if video is None:
            problems.append(f"нет видео {spec.title}")
            continue
        by_slug[spec.slug] = video
        owner = by_username.get(spec.owner_username)
        if owner is None or video.user_id != owner.id:
            problems.append(f"{spec.title}: автор не {spec.owner_username}")
        if video.category != spec.category:
            problems.append(f"{spec.title}: категория {video.category}")
        if video.is_private != spec.is_private:
            problems.append(f"{spec.title}: is_private={video.is_private}")
        if video.views_count != spec.views_count:
            problems.append(f"{spec.title}: views_count={video.views_count}")
        if video.duration != SAMPLE_DURATION_SECONDS:
            problems.append(f"{spec.title}: duration={video.duration}")
        if video.is_banned:
            problems.append(f"{spec.title} осталось заблокированным")
        stored_tags = {tag.lower() for tag in (video.tags or [])}
        missing_tags = [tag for tag in spec.tags if tag.lower() not in stored_tags]
        if missing_tags:
            problems.append(f"{spec.title}: нет тегов {', '.join(missing_tags)}")
        videos.append(
            VideoFact(
                title=video.title,
                category=video.category or "",
                views_count=video.views_count,
                owner=spec.owner_username,
                is_private=video.is_private,
                has_pending_report=spec.slug == REPORT.video_slug,
            )
        )
        pairs = ((storage.video_bucket, video.s3_key, "video/mp4", b"ftyp"),)
        if video.preview_s3_key:
            pairs = (
                *pairs,
                (storage.thumbnail_bucket, video.preview_s3_key, "image/png", b"\x89PNG"),
            )
        else:
            problems.append(f"{spec.title}: нет ключа обложки")
        for bucket, key, content_type, marker in pairs:
            try:
                size, actual_type, head = await _inspect(storage, bucket, key)
            except S3Error as exc:
                problems.append(f"MinIO {bucket}/{key}: {exc.code}")
                continue
            objects.append(ObjectFact(bucket, key, size))
            if size <= 0:
                problems.append(f"MinIO {bucket}/{key} пустой")
            if not _content_type_matches(actual_type, content_type):
                problems.append(f"MinIO {bucket}/{key}: тип {actual_type or 'пустой'}")
            if marker not in head:
                problems.append(f"MinIO {bucket}/{key}: содержимое не {content_type}")

    for slug, username in ACCESS:
        video = by_slug.get(slug)
        user = by_username.get(username)
        if video is None or user is None:
            continue
        access = await session.scalar(
            select(VideoAllowedUser).where(
                VideoAllowedUser.video_id == video.id,
                VideoAllowedUser.user_id == user.id,
            )
        )
        if access is None:
            problems.append(f"нет доступа {username} к {slug}")

    reported = by_slug.get(REPORT.video_slug)
    reporter = by_username.get(REPORT.reporter_username)
    if reported is not None and reporter is not None:
        report = await session.scalar(
            select(VideoReport).where(
                VideoReport.video_id == reported.id,
                VideoReport.reporter_id == reporter.id,
                VideoReport.reason == REPORT.reason,
            )
        )
        if report is None:
            problems.append("нет демо-жалобы")
        elif report.status != "pending":
            problems.append(f"жалоба в статусе {report.status}, ожидался pending")

    for subscriber_name, channel_name in SUBSCRIPTIONS:
        subscriber = by_username.get(subscriber_name)
        channel = by_username.get(channel_name)
        if subscriber is None or channel is None:
            continue
        link = await session.scalar(
            select(Subscription).where(
                Subscription.subscriber_id == subscriber.id,
                Subscription.channel_id == channel.id,
            )
        )
        if link is None:
            problems.append(f"нет подписки {subscriber_name} -> {channel_name}")

    for slug, username, is_like in REACTIONS:
        video = by_slug.get(slug)
        user = by_username.get(username)
        if video is None or user is None:
            continue
        reaction = await session.scalar(
            select(Reaction).where(Reaction.video_id == video.id, Reaction.user_id == user.id)
        )
        if reaction is None:
            problems.append(f"нет реакции {username} на {slug}")
        elif reaction.is_like != is_like:
            problems.append(f"реакция {username} на {slug} не совпадает")

    for slug, username, text, _minutes in COMMENTS:
        video = by_slug.get(slug)
        user = by_username.get(username)
        if video is None or user is None:
            continue
        comment = await session.scalar(
            select(Comment.id).where(
                Comment.video_id == video.id,
                Comment.user_id == user.id,
                Comment.text == text,
            )
        )
        if comment is None:
            short = text if len(text) <= 42 else f"{text[:39]}..."
            problems.append(f"нет комментария {username} к {slug}: {short}")

    for username, slug, progress, _hours in HISTORY:
        video = by_slug.get(slug)
        user = by_username.get(username)
        if video is None or user is None:
            continue
        entry = await session.scalar(
            select(WatchHistory).where(
                WatchHistory.video_id == video.id,
                WatchHistory.user_id == user.id,
            )
        )
        if entry is None:
            problems.append(f"нет истории {username} / {slug}")
        elif entry.progress_seconds != progress:
            problems.append(f"прогресс {username} / {slug} = {entry.progress_seconds}")

    playlists: list[PlaylistFact] = []
    for spec in PLAYLISTS:
        owner = by_username.get(spec.owner_username)
        if owner is None:
            continue
        playlist = await session.scalar(
            select(Playlist).where(Playlist.user_id == owner.id, Playlist.title == spec.title)
        )
        if playlist is None:
            problems.append(f"нет плейлиста {spec.title}")
            continue
        if playlist.is_private != spec.is_private:
            problems.append(f"{spec.title}: is_private={playlist.is_private}")
        linked = set(
            (
                await session.scalars(
                    select(PlaylistVideo.video_id).where(PlaylistVideo.playlist_id == playlist.id)
                )
            ).all()
        )
        for slug in spec.video_slugs:
            video = by_slug.get(slug)
            if video is None or video.id not in linked:
                problems.append(f"плейлист {spec.title} не содержит {slug}")
        playlists.append(
            PlaylistFact(spec.title, spec.owner_username, playlist.is_private, len(linked))
        )

    if likes < 1 or dislikes < 1:
        problems.append("в базе нет и лайков, и дизлайков")

    return Facts(
        problems=problems,
        accounts=accounts,
        videos=videos,
        playlists=playlists,
        objects=objects,
        totals=totals,
        likes=likes,
        dislikes=dislikes,
    )


def _configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            continue


def _ansi() -> Ansi:
    if os.environ.get("NO_COLOR"):
        return Ansi("", "", "", "", "", "", "")
    return Ansi(
        reset="\033[0m",
        bold="\033[1m",
        cyan="\033[36m",
        green="\033[32m",
        yellow="\033[33m",
        red="\033[31m",
        dim="\033[2m",
    )


def _print_report(counters: Counters, facts: Facts) -> None:
    ansi = _ansi()
    rule = f"{ansi.cyan}{'=' * 72}{ansi.reset}"
    print(rule)
    print(f"{ansi.bold}{ansi.cyan}  Демо-данные YouTube clone{ansi.reset}")
    print(
        f"{ansi.dim}  Повторный запуск не создает дубликаты: пользователи по email,"
        f" видео и плейлисты по названию.{ansi.reset}"
    )
    print(
        f"{ansi.dim}  Пароли этих учеток приводятся к значениям ниже."
        f" Метаданные демо-видео и жалоба pending восстанавливаются.{ansi.reset}"
    )
    print(rule)
    print(f"{ansi.bold}  Учетные записи{ansi.reset}")
    print(f"  {'роль':<10} {'логин':<12} {'email':<26} пароль")
    for account in facts.accounts:
        print(
            f"  {ansi.cyan}{account.role:<10}{ansi.reset} "
            f"{account.username:<12} {account.email:<26} "
            f"{ansi.yellow}{account.password}{ansi.reset}"
        )
    print()
    print(f"{ansi.bold}  Видео{ansi.reset}")
    print(
        f"{ansi.dim}  Один общий MP4 на {SAMPLE_DURATION_SECONDS} с "
        f"(тестовая картинка). Обложки в бакете thumbnails разные.{ansi.reset}"
    )
    for video in facts.videos:
        flags = []
        if video.is_private:
            flags.append(f"{ansi.red}ПРИВАТНОЕ, доступ есть у user2{ansi.reset}")
        if video.has_pending_report:
            flags.append(f"{ansi.red}жалоба pending от user3{ansi.reset}")
        suffix = f"  {', '.join(flags)}" if flags else ""
        print(
            f"  [{video.category:<9}] {video.title} — {video.views_count} просмотров"
            f" — {video.owner}{suffix}"
        )
    print()
    print(f"{ansi.bold}  Плейлисты{ansi.reset}")
    for playlist in facts.playlists:
        privacy = "приватный" if playlist.is_private else "публичный"
        print(f"  {playlist.title} ({privacy}, {playlist.owner}) — {playlist.size} видео")
    print()
    print(f"{ansi.bold}  MinIO{ansi.reset}")
    for obj in facts.objects:
        print(f"  {obj.bucket}/{obj.key}  ({obj.size} bytes)")
    print()
    totals = facts.totals
    print(
        "  В базе: "
        f"пользователи {totals['users']}, видео {totals['videos']}, "
        f"подписки {totals['subscriptions']}, реакции {totals['reactions']} "
        f"(лайки {facts.likes}, дизлайки {facts.dislikes}), "
        f"комментарии {totals['comments']}, история {totals['history']}, "
        f"плейлисты {totals['playlists']}, жалобы {totals['reports']}"
    )
    print(
        "  Этот запуск: "
        f"строк создано {counters.rows_created}, уже было {counters.rows_kept}; "
        f"объектов загружено {counters.objects_uploaded}, "
        f"уже было {counters.objects_kept}"
    )
    print()
    print(f"{ansi.bold}  Куда смотреть{ansi.reset}")
    print("  POST /auth/login                         вход по email или логину")
    print("  GET  /videos                             публичный каталог (без приватного)")
    print("  GET  /videos/search?category=Tech        поиск по категории")
    print("  GET  /moderation/reports?status=pending  очередь, токен moderator или admin")
    print("  GET  /users/me/history                   история user1, user2 или user3")
    print("  GET  /feed/subscriptions                 лента подписок")
    print()
    print(f"{ansi.dim}  Повтор:{ansi.reset}")
    print("  docker compose exec backend python -m scripts.seed_data")
    print(rule)


async def _run() -> int:
    print(
        "Сидирую демо-данные (идемпотентно: email, название видео, естественные ключи)...",
        flush=True,
    )
    try:
        sample = load_sample_mp4()
    except (FileNotFoundError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 1

    storage = get_s3_client()
    try:
        await asyncio.to_thread(storage.ensure_buckets)
        async with async_sessionmaker() as session:
            counters = await populate(session, storage, sample)
            await session.commit()
        async with async_sessionmaker() as session:
            facts = await verify(session, storage)
    except SeedError as exc:
        print(exc, file=sys.stderr)
        return 1
    except IntegrityError as exc:
        print(f"База отклонила строку демо-данных: {exc.orig}", file=sys.stderr)
        return 1
    except OperationalError as exc:
        print(f"База недоступна. Запустите стек: docker compose up -d\n{exc}", file=sys.stderr)
        return 1
    except StorageError as exc:
        print(f"MinIO недоступен: {exc}", file=sys.stderr)
        return 1

    _print_report(counters, facts)
    if facts.problems:
        print("Проверка не пройдена:", file=sys.stderr)
        for problem in facts.problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    ansi = _ansi()
    print(f"{ansi.green}{ansi.bold}База и MinIO заполнены, проверка пройдена.{ansi.reset}")
    return 0


async def run() -> int:
    try:
        return await _run()
    finally:
        await async_engine.dispose()


def main() -> None:
    _configure_stdio()
    try:
        code = asyncio.run(run())
    except KeyboardInterrupt:
        print("\nОстановлено.", file=sys.stderr)
        code = 130
    raise SystemExit(code)


if __name__ == "__main__":
    main()
