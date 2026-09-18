"""factory baseline: strategies, versions, sources, claims, runs,
metrics, artifacts, lifecycle events, promotion decisions, shadow/live
observations, alerts (mission §18).

Revision ID: 0001_factory_baseline
Revises:
Create Date: 2026-09-06
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0001_factory_baseline"
down_revision = None
branch_labels = None
depends_on = None


def _tables():
    from mql5bot.factory.models import Base
    return list(reversed(Base.metadata.sorted_tables))


def upgrade() -> None:
    # The baseline creates the full declared schema; table creation is
    # ordered by metadata dependencies.
    from mql5bot.factory.models import Base
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    from mql5bot.factory.models import Base
    Base.metadata.drop_all(bind=op.get_bind())
