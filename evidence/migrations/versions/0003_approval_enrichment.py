"""approval record enrichment: evidence_hash + policy_version
(convergence §32/§71).

Revision ID: 0003_approval_enrichment
Revises: 0002_discovery_campaigns
Create Date: 2026-09-06
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0003_approval_enrichment"
down_revision = "0002_discovery_campaigns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns(
        "promotion_decisions")}
    if "evidence_hash" not in cols:
        op.add_column("promotion_decisions",
                      sa.Column("evidence_hash", sa.String(length=64),
                                nullable=False, server_default=""))
    if "policy_version" not in cols:
        op.add_column("promotion_decisions",
                      sa.Column("policy_version", sa.String(length=64),
                                nullable=False, server_default=""))


def downgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns(
        "promotion_decisions")}
    if "policy_version" in cols:
        op.drop_column("promotion_decisions", "policy_version")
    if "evidence_hash" in cols:
        op.drop_column("promotion_decisions", "evidence_hash")
