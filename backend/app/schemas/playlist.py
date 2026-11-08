import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from app.schemas.video import VideoRead


def _strip(value: object) -> object:
    if isinstance(value, str):
        return value.strip()
    return value


def _normalize_description(value: object) -> object:
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    if not stripped:
        return None
    if len(stripped) > 5000:
        raise ValueError("String should have at most 5000 characters")
    return stripped


PlaylistTitle = Annotated[str, BeforeValidator(_strip), Field(min_length=1, max_length=150)]
PlaylistDescription = Annotated[str | None, BeforeValidator(_normalize_description)]


class PlaylistCreate(BaseModel):
    """Payload for a new playlist. The author is taken from the access token."""

    model_config = ConfigDict(extra="forbid")

    title: PlaylistTitle
    description: PlaylistDescription = None
    is_private: bool = False


class PlaylistUpdate(BaseModel):
    """Partial playlist update. Fields left out stay unchanged."""

    model_config = ConfigDict(extra="forbid")

    title: PlaylistTitle | None = None
    description: PlaylistDescription = None
    is_private: bool | None = None


class PlaylistRead(BaseModel):
    """Playlist metadata without the video list."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    description: str | None
    is_private: bool
    user_id: uuid.UUID
    videos_count: int
    created_at: datetime


class PlaylistVideoRead(VideoRead):
    """Video metadata plus its order inside one playlist."""

    position: int


class PlaylistDetailRead(PlaylistRead):
    """Playlist with videos ordered by position, then by the time they were added."""

    videos: list[PlaylistVideoRead]
