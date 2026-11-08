import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, String, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.access import VideoAllowedUser
    from app.models.comment import Comment
    from app.models.history import WatchHistory
    from app.models.playlist import Playlist
    from app.models.reaction import Reaction
    from app.models.report import VideoReport
    from app.models.subscription import Subscription
    from app.models.video import Video


class UserRole(str, enum.Enum):
    USER = "user"
    MODERATOR = "moderator"
    ADMIN = "admin"


USER_ROLE = Enum(
    UserRole,
    name="user_role",
    native_enum=True,
    values_callable=lambda roles: [role.value for role in roles],
    validate_strings=True,
)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    role: Mapped[UserRole] = mapped_column(
        USER_ROLE,
        nullable=False,
        default=UserRole.USER,
        server_default=text("'user'"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    def __repr__(self) -> str:
        return (
            f"User(id={self.id!r}, email={self.email!r}, "
            f"username={self.username!r}, role={self.role!r})"
        )

    videos: Mapped[list["Video"]] = relationship(
        back_populates="owner",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="raise",
    )
    comments: Mapped[list["Comment"]] = relationship(
        back_populates="author",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="raise",
    )
    reactions: Mapped[list["Reaction"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="raise",
    )
    video_accesses: Mapped[list["VideoAllowedUser"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="raise",
    )
    filed_reports: Mapped[list["VideoReport"]] = relationship(
        back_populates="reporter",
        foreign_keys="VideoReport.reporter_id",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="raise",
    )
    resolved_reports: Mapped[list["VideoReport"]] = relationship(
        back_populates="resolver",
        foreign_keys="VideoReport.resolved_by",
        passive_deletes=True,
        lazy="raise",
    )
    channel_subscriptions: Mapped[list["Subscription"]] = relationship(
        back_populates="channel",
        foreign_keys="Subscription.channel_id",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="raise",
    )
    subscriber_subscriptions: Mapped[list["Subscription"]] = relationship(
        back_populates="subscriber",
        foreign_keys="Subscription.subscriber_id",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="raise",
    )
    watch_history: Mapped[list["WatchHistory"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="raise",
    )
    playlists: Mapped[list["Playlist"]] = relationship(
        back_populates="author",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="raise",
    )
