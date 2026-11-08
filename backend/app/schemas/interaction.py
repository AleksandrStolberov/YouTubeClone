import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field


def _strip(value: object) -> object:
    if isinstance(value, str):
        return value.strip()
    return value


CommentText = Annotated[str, BeforeValidator(_strip), Field(min_length=1, max_length=1000)]


class CommentCreate(BaseModel):
    """Text of a new comment. Blank input is rejected after trimming."""

    model_config = ConfigDict(extra="forbid")

    text: CommentText


class CommentRead(BaseModel):
    """Comment stored for a video, with the author's username."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    video_id: uuid.UUID
    user_id: uuid.UUID
    author_username: str
    text: str
    created_at: datetime


class ReactionCreate(BaseModel):
    """Like when true, dislike when false."""

    model_config = ConfigDict(extra="forbid")

    is_like: bool


class VideoReactionsSummary(BaseModel):
    """Like and dislike totals, plus the viewer's own reaction when signed in."""

    likes_count: int
    dislikes_count: int
    user_reaction: bool | None = None


class SubscriptionStatus(BaseModel):
    """Result of a subscribe or unsubscribe toggle."""

    channel_id: uuid.UUID
    is_subscribed: bool
    subscribers_count: int


class SubscribersCount(BaseModel):
    """How many users follow a channel."""

    subscribers_count: int
