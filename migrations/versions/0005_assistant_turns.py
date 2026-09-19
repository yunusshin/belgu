"""Retain grounded assistant turns and their source snapshots."""
from alembic import op
from belgu.persistence.models import AssistantTurn

revision = '0005_assistant_turns'
down_revision = '0004_workbench'
branch_labels = None
depends_on = None


def upgrade():
    AssistantTurn.__table__.create(op.get_bind(), checkfirst=True)


def downgrade():
    AssistantTurn.__table__.drop(op.get_bind(), checkfirst=True)
