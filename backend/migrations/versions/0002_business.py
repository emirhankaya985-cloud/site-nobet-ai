"""Shared CRM and review draft storage, safe on existing and fresh installs."""
from alembic import op
from app.models import BusinessLead, ReviewDraft, MailClaim, BusinessBatch
revision = '0002_business'
down_revision = '0001_initial'
branch_labels = None
depends_on = None


def upgrade():
    for model in (BusinessLead, ReviewDraft, MailClaim, BusinessBatch):
        model.__table__.create(bind=op.get_bind(), checkfirst=True)


def downgrade():
    for model in (BusinessBatch, MailClaim, ReviewDraft, BusinessLead):
        model.__table__.drop(bind=op.get_bind(), checkfirst=True)
