"""add video category and tags

Revision ID: c3e8b1a94f06
Revises: b7d3e1a84c02
Create Date: 2026-11-08 17:50:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "c3e8b1a94f06"
down_revision: Union[str, None] = "b7d3e1a84c02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("videos", sa.Column("category", sa.String(length=50), nullable=True))
    op.add_column(
        "videos",
        sa.Column(
            "tags",
            postgresql.ARRAY(sa.String(length=50)),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
    )
    op.create_index(op.f("ix_videos_category"), "videos", ["category"], unique=False)
    op.create_index(
        "ix_videos_tags",
        "videos",
        ["tags"],
        unique=False,
        postgresql_using="gin",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_videos_tags", table_name="videos")
    op.drop_index(op.f("ix_videos_category"), table_name="videos")
    op.drop_column("videos", "tags")
    op.drop_column("videos", "category")
