import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.video import VideoRead


class ViewRecordRequest(BaseModel):
    """Playback position sent with a view. Omitted progress is stored as zero."""

    model_config = ConfigDict(extra="forbid")

    progress_seconds: int | None = Field(default=0, ge=0)


class WatchHistoryItemRead(BaseModel):
    """A video the current user has watched, with the latest position."""

    model_config = ConfigDict(from_attributes=True)

    video: VideoRead
    watched_at: datetime
    progress_seconds: int


class PaginatedHistoryResponse(BaseModel):
    """One page of the current user's watch history, newest view first."""

    items: list[WatchHistoryItemRead]
    total: int
    limit: int
    offset: int
