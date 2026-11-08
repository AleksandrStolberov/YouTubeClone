import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.comment import Comment
    from app.models.history import WatchHistory
    from app.models.reaction import Reaction
    from app.models.user import User
    from app.models.video_access import VideoAccess


class Video(Base):
    __tablename__ = "videos"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    s3_key: Mapped[str] = mapped_column(String(1024), unique=True, nullable=False)
    preview_s3_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    duration: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    views_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    is_private: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    owner: Mapped["User"] = relationship(back_populates="videos", lazy="raise")
    comments: Mapped[list["Comment"]] = relationship(
        back_populates="video",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="raise",
    )
    reactions: Mapped[list["Reaction"]] = relationship(
        back_populates="video",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="raise",
    )
    access_entries: Mapped[list["VideoAccess"]] = relationship(
        back_populates="video",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="raise",
    )
    watch_history: Mapped[list["WatchHistory"]] = relationship(
        back_populates="video",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="raise",
    )
