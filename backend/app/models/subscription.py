import uuid
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.user import User


class Subscription(Base):
    __tablename__ = "subscriptions"
    __table_args__ = (
        UniqueConstraint(
            "channel_id",
            "subscriber_id",
            name="uq_subscriptions_channel_id_subscriber_id",
        ),
        CheckConstraint(
            "channel_id <> subscriber_id",
            name="subscriber_is_not_channel",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    channel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    subscriber_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    channel: Mapped["User"] = relationship(
        back_populates="channel_subscriptions",
        foreign_keys=[channel_id],
        lazy="raise",
    )
    subscriber: Mapped["User"] = relationship(
        back_populates="subscriber_subscriptions",
        foreign_keys=[subscriber_id],
        lazy="raise",
    )
