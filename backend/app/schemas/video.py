import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field


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


Title = Annotated[str, BeforeValidator(_strip), Field(min_length=1, max_length=200)]
Description = Annotated[str | None, BeforeValidator(_normalize_description)]


class VideoCreate(BaseModel):
    """Metadata sent together with the uploaded video file."""

    model_config = ConfigDict(extra="forbid")

    title: Title
    description: Description = None
    is_private: bool = False


class VideoUpdate(BaseModel):
    """Partial metadata update. Fields left out stay unchanged."""

    model_config = ConfigDict(extra="forbid")

    title: Title | None = None
    description: Description = None
    is_private: bool | None = None


class VideoRead(BaseModel):
    """Video metadata stored in PostgreSQL. File bytes stay in MinIO."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    description: str | None
    s3_key: str
    preview_s3_key: str | None
    duration: int
    views_count: int
    is_private: bool
    is_banned: bool = False
    ban_reason: str | None = None
    category: str | None = None
    tags: list[str] = Field(default_factory=list)
    user_id: uuid.UUID
    created_at: datetime
