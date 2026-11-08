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
_CATEGORIES = {"Tech", "Gaming", "Music", "Education"}


def _normalize_category(value: object) -> object:
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    if not stripped:
        return None
    if stripped not in _CATEGORIES:
        raise ValueError("Category must be Tech, Gaming, Music, or Education")
    return stripped


def _normalize_tags(value: object) -> object:
    if value is None:
        return []
    if isinstance(value, str):
        value = [part.strip() for part in value.split(",")]
    if not isinstance(value, list):
        return value
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            return value
        tag = item.strip()
        if not tag:
            continue
        if len(tag) > 50:
            raise ValueError("Tag must be at most 50 characters")
        key = tag.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(tag)
    if len(cleaned) > 20:
        raise ValueError("At most 20 tags are allowed")
    return cleaned


Category = Annotated[str | None, BeforeValidator(_normalize_category)]
Tags = Annotated[list[str], BeforeValidator(_normalize_tags)]


class VideoCreate(BaseModel):
    """Metadata sent together with the uploaded video file."""

    model_config = ConfigDict(extra="forbid")

    title: Title
    description: Description = None
    is_private: bool = False
    category: Category = None
    tags: Tags = Field(default_factory=list)


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
