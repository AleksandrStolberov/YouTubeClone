"""create watch history

Revision ID: b7d3e1a84c02
Revises: 2e70a054b67b
Create Date: 2026-11-08 17:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7d3e1a84c02'
down_revision: Union[str, None] = '2e70a054b67b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'watch_histories',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('video_id', sa.UUID(), nullable=False),
        sa.Column('watched_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('progress_seconds', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_watch_histories_user_id_users'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['video_id'], ['videos.id'], name=op.f('fk_watch_histories_video_id_videos'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_watch_histories')),
        sa.UniqueConstraint('user_id', 'video_id', name='uq_watch_histories_user_id_video_id'),
    )
    op.create_index(op.f('ix_watch_histories_video_id'), 'watch_histories', ['video_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_watch_histories_video_id'), table_name='watch_histories')
    op.drop_table('watch_histories')
