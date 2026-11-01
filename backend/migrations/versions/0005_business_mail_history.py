"""Add durable delivery feedback and shared recipient guard without altering old sends.

This migration is additive. Existing data is neither rewritten nor deleted.
A non-destructive rollback keeps historical feedback and exclusion rows in place.
"""
from alembic import op
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
    # Preserve mail history, delivery evidence and global blocks.
    # Old code ignores these additive tables; never erase historic facts.
    pass
