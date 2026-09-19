"""Add collection run identity and durable local watches without changing evidence."""
from alembic import op
from belgu.persistence.models import CollectionRun, Watch, WatchAlert

revision = '0004_workbench'
down_revision = '0003_observation_subject_index'
branch_labels = None
depends_on = None


def upgrade():
    for table in (CollectionRun.__table__, Watch.__table__, WatchAlert.__table__):
        table.create(op.get_bind(), checkfirst=True)


def downgrade():
    for table in (WatchAlert.__table__, Watch.__table__, CollectionRun.__table__):
        table.drop(op.get_bind(), checkfirst=True)
