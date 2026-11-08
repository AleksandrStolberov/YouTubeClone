"""create playlists

Revision ID: d8a1c4e62b30
Revises: c3e8b1a94f06
Create Date: 2026-11-08 18:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d8a1c4e62b30"
down_revision: Union[str, None] = "c3e8b1a94f06"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "playlists",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("title", sa.String(length=150), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "is_private",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_playlists_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_playlists")),
    )
    op.create_index(op.f("ix_playlists_user_id"), "playlists", ["user_id"], unique=False)
    op.create_table(
        "playlist_videos",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("playlist_id", sa.UUID(), nullable=False),
        sa.Column("video_id", sa.UUID(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column(
            "added_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("position >= 0", name=op.f("ck_playlist_videos_position_non_negative")),
        sa.ForeignKeyConstraint(
            ["playlist_id"],
            ["playlists.id"],
            name=op.f("fk_playlist_videos_playlist_id_playlists"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["video_id"],
            ["videos.id"],
            name=op.f("fk_playlist_videos_video_id_videos"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_playlist_videos")),
        sa.UniqueConstraint(
            "playlist_id",
            "video_id",
            name="uq_playlist_videos_playlist_id_video_id",
        ),
    )
    op.create_index(
        op.f("ix_playlist_videos_video_id"),
        "playlist_videos",
        ["video_id"],
        unique=False,
    )
    op.create_index(
        "ix_playlist_videos_playlist_id_position",
        "playlist_videos",
        ["playlist_id", "position"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_playlist_videos_playlist_id_position", table_name="playlist_videos")
    op.drop_index(op.f("ix_playlist_videos_video_id"), table_name="playlist_videos")
    op.drop_table("playlist_videos")
    op.drop_index(op.f("ix_playlists_user_id"), table_name="playlists")
    op.drop_table("playlists")
