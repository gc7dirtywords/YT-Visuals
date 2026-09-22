"""Track explicit producer SFX skips for beat resolution.

Revision ID: 0016_beat_sfx_skip
Revises: 0015_story_narration_audio
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0016_beat_sfx_skip"
down_revision = "0015_story_narration_audio"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("producer_beats", sa.Column("sfx_skipped_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("producer_beats", "sfx_skipped_at")
