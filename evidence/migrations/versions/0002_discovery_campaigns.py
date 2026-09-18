"""discovery campaigns table (mission §7/§18/§84).

Revision ID: 0002_discovery_campaigns
Revises: 0001_factory_baseline
Create Date: 2026-09-06
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0002_discovery_campaigns"
down_revision = "0001_factory_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Migration 0001 creates the full DECLARED schema (which already
    # includes this table); for databases migrated before the
    # declaration existed, create it here.  Idempotent either way.
    if op.get_bind().dialect.has_table(op.get_bind(),
                                      "discovery_campaigns"):
        return
    op.create_table(
        "discovery_campaigns",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("campaign_id", sa.String(length=64), nullable=False,
                  unique=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("parent_campaign_id", sa.String(length=64),
                  nullable=True),
        sa.Column("stage", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("budget", sa.JSON(), nullable=True),
        sa.Column("progress", sa.JSON(), nullable=True),
        sa.Column("manifest", sa.JSON(), nullable=True),
        sa.Column("manifest_hash", sa.String(length=64), nullable=False,
                  server_default=""),
        sa.Column("policy_hash", sa.String(length=64), nullable=False,
                  server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("dataset_hash", sa.String(length=128), nullable=False,
                  server_default=""),
    )
    # §84: a campaign may reference the campaign that spawned it, but
    # progress/migration NEVER reuses another campaign's evidence; the
    # parent link is informational only (no FK on purpose — campaigns
    # can outlive their parents).
    op.create_index("ix_campaign_status", "discovery_campaigns",
                    ["status"])


def downgrade() -> None:
    bind = op.get_bind()
    if not bind.dialect.has_table(bind, "discovery_campaigns"):
        return
    indexes = {ix["name"] for ix in sa.inspect(bind).get_indexes(
        "discovery_campaigns")}
    if "ix_campaign_status" in indexes:
        op.drop_index("ix_campaign_status",
                      table_name="discovery_campaigns")
    op.drop_table("discovery_campaigns")
