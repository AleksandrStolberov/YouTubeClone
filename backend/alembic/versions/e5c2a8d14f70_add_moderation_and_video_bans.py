"""add moderation and video bans

Revision ID: e5c2a8d14f70
Revises: d8a1c4e62b30
Create Date: 2026-11-08 19:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e5c2a8d14f70"
down_revision: Union[str, None] = "d8a1c4e62b30"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "videos",
        sa.Column(
            "is_banned",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.add_column("videos", sa.Column("ban_reason", sa.String(length=500), nullable=True))
    op.create_index(op.f("ix_videos_is_banned"), "videos", ["is_banned"], unique=False)
    op.create_table(
        "video_reports",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("video_id", sa.UUID(), nullable=False),
        sa.Column("reporter_id", sa.UUID(), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("resolved_by", sa.UUID(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'resolved', 'rejected')",
            name=op.f("ck_video_reports_status_allowed"),
        ),
        sa.ForeignKeyConstraint(
            ["reporter_id"],
            ["users.id"],
            name=op.f("fk_video_reports_reporter_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["resolved_by"],
            ["users.id"],
            name=op.f("fk_video_reports_resolved_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["video_id"],
            ["videos.id"],
            name=op.f("fk_video_reports_video_id_videos"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_video_reports")),
    )
    op.create_index(op.f("ix_video_reports_reporter_id"), "video_reports", ["reporter_id"], unique=False)
    op.create_index(op.f("ix_video_reports_status"), "video_reports", ["status"], unique=False)
    op.create_index(op.f("ix_video_reports_video_id"), "video_reports", ["video_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_video_reports_video_id"), table_name="video_reports")
    op.drop_index(op.f("ix_video_reports_status"), table_name="video_reports")
    op.drop_index(op.f("ix_video_reports_reporter_id"), table_name="video_reports")
    op.drop_table("video_reports")
    op.drop_index(op.f("ix_videos_is_banned"), table_name="videos")
    op.drop_column("videos", "ban_reason")
    op.drop_column("videos", "is_banned")
