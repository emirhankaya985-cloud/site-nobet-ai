"""Persist per-delivery Telegram API message receipts without exposing credentials."""
from alembic import op
import sqlalchemy as sa

revision = '0003_telegram_receipts'
down_revision = '0002_business'
branch_labels = None
depends_on = None


def upgrade():
    # The baseline migration creates latest metadata on a fresh database.
    columns = {c['name'] for c in sa.inspect(op.get_bind()).get_columns('notification_deliveries')}
    if 'telegram_receipt_ids' not in columns:
        op.add_column('notification_deliveries', sa.Column('telegram_receipt_ids', sa.Text(), nullable=True))


def downgrade():
    columns = {c['name'] for c in sa.inspect(op.get_bind()).get_columns('notification_deliveries')}
    if 'telegram_receipt_ids' in columns:
        op.drop_column('notification_deliveries', 'telegram_receipt_ids')
