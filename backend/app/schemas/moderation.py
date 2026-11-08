import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

ReportStatus = Literal["pending", "resolved", "rejected"]


def _strip(value: object) -> object:
    if isinstance(value, str):
        return value.strip()
    return value


Reason = Annotated[str, BeforeValidator(_strip), Field(min_length=1, max_length=500)]


class ReportCreate(BaseModel):
    """Complaint text sent by a signed-in viewer."""

    model_config = ConfigDict(extra="forbid")

    reason: Reason


class ReportRead(BaseModel):
    """One complaint, plus the video ban note when staff has hidden it."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    video_id: uuid.UUID
    reporter_id: uuid.UUID
    reason: str
    status: ReportStatus
    created_at: datetime
    ban_reason: str | None = None


class VideoBanRequest(BaseModel):
    """Why a moderator or an admin is hiding a video."""

    model_config = ConfigDict(extra="forbid")

    reason: Reason


class WhitelistAddRequest(BaseModel):
    """User who should be allowed to watch a private video."""

    model_config = ConfigDict(extra="forbid")

    user_id: uuid.UUID


class AllowedUserRead(BaseModel):
    """A whitelist entry joined with the account it grants access to."""

    model_config = ConfigDict(from_attributes=True)

    user_id: uuid.UUID
    username: str
    email: str
