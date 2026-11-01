"""Add durable delivery feedback and shared recipient guard without altering old sends.

This migration is additive. Existing data is neither rewritten nor deleted.
A non-destructive rollback keeps historical feedback and exclusion rows in place.
"""
from alembic import op
import sqlalchemy as sa
from app.models import BusinessMailFeedback, BusinessRecipientGuard

revision = "0005_business_mail_history"
down_revision = "0004_owner_telegram_link"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    for model in (BusinessMailFeedback, BusinessRecipientGuard):
        model.__table__.create(bind=bind, checkfirst=True)


def downgrade():
    # CI must be able to run a complete empty-schema downgrade. Production
    # rollback is code-only: never discard real suppression or feedback rows.
    bind = op.get_bind()
    for model in (BusinessRecipientGuard, BusinessMailFeedback):
        table = model.__table__
        if sa.inspect(bind).has_table(table.name):
            count = bind.scalar(sa.select(sa.func.count()).select_from(table)) or 0
            if count:
                raise RuntimeError(
                    "Refuse destructive downgrade of persisted mail feedback or guards")
    # Children first so PostgreSQL foreign keys do not block parent migration.
    for model in (BusinessMailFeedback, BusinessRecipientGuard):
        model.__table__.drop(bind=bind, checkfirst=True)
