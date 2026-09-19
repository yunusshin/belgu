"""Index evidence joins by investigation and subject.

Revision ID: 0003_observation_subject_index
Revises: 0002_observation_fingerprint
Create Date: 2026-09-08
"""

import sqlalchemy as sa
from alembic import op

revision = "0003_observation_subject_index"
down_revision = "0002_observation_fingerprint"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    indexes = {item["name"] for item in sa.inspect(bind).get_indexes("observations")}
    if "ix_observation_inv_subject" not in indexes:
        op.create_index("ix_observation_inv_subject", "observations", ["investigation_id", "subject_id"])


def downgrade() -> None:
    bind = op.get_bind()
    indexes = {item["name"] for item in sa.inspect(bind).get_indexes("observations")}
    if "ix_observation_inv_subject" in indexes:
        op.drop_index("ix_observation_inv_subject", table_name="observations")
