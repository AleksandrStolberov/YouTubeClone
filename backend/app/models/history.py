import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.video import Video


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class WatchHistory(Base):
    """One viewer's latest position in a video.

    The unique pair ``(user_id, video_id)`` keeps a single row per viewer and
    video, so a later view updates ``watched_at`` instead of inserting a copy.
    """

    __tablename__ = "watch_histories"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "video_id",
            name="uq_watch_histories_user_id_video_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    video_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("videos.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    watched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        server_default=func.now(),
    )
    progress_seconds: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )

    user: Mapped["User"] = relationship(back_populates="watch_history", lazy="raise")
    video: Mapped["Video"] = relationship(back_populates="watch_history", lazy="raise")
