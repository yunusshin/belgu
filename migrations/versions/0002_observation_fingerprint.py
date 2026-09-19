"""Preserve distinct observation occurrences.

Revision ID: 0002_observation_fingerprint
Revises: 0001_initial
Create Date: 2026-09-08
"""

import sqlalchemy as sa
from alembic import op

from belgu.persistence.models import observation_fingerprint

revision = "0002_observation_fingerprint"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {item["name"] for item in sa.inspect(bind).get_columns("observations")}
    if "fingerprint" in columns:
        return

    op.add_column("observations", sa.Column("fingerprint", sa.String(length=64), nullable=True))
    observations = sa.table(
        "observations",
        sa.column("id", sa.String),
        sa.column("provider", sa.String),
        sa.column("source_ref", sa.Text),
        sa.column("subject_id", sa.String),
        sa.column("kind", sa.String),
        sa.column("observed_at", sa.DateTime(timezone=True)),
        sa.column("retrieved_at", sa.DateTime(timezone=True)),
        sa.column("payload", sa.JSON),
        sa.column("fingerprint", sa.String),
    )
    rows = bind.execute(sa.select(
        observations.c.id,
        observations.c.provider,
        observations.c.source_ref,
        observations.c.subject_id,
        observations.c.kind,
        observations.c.observed_at,
        observations.c.retrieved_at,
        observations.c.payload,
    )).mappings()
    for row in rows:
        fingerprint = observation_fingerprint(
            row["provider"], row["source_ref"], row["subject_id"], row["kind"],
            row["observed_at"], row["retrieved_at"], row["payload"],
        )
        bind.execute(sa.update(observations).where(observations.c.id == row["id"]).values(fingerprint=fingerprint))

    with op.batch_alter_table("observations", recreate="always") as batch:
        batch.drop_constraint("uq_observation_identity", type_="unique")
        batch.alter_column("fingerprint", existing_type=sa.String(length=64), nullable=False)
        batch.create_unique_constraint("uq_observation_fingerprint", ["investigation_id", "fingerprint"])


def downgrade() -> None:
    raise RuntimeError("observation fingerprint migration cannot be downgraded without losing distinct evidence")
