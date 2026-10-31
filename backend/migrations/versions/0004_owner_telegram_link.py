"""Introduce owner-bound two-phase Telegram linking without confirming old codes."""
from alembic import op
import sqlalchemy as sa

revision = "0004_owner_telegram_link"
down_revision = "0003_telegram_receipts"
branch_labels = None
depends_on = None


def upgrade():
    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("telegram_link_codes")}
    if "initiated_by_user_id" not in columns:
        op.add_column("telegram_link_codes", sa.Column("initiated_by_user_id", sa.String(36), nullable=True))
    if "pending_chat_id" not in columns:
        op.add_column("telegram_link_codes", sa.Column("pending_chat_id", sa.String(255), nullable=True))
    if "pending_telegram_user_id" not in columns:
        op.add_column("telegram_link_codes", sa.Column("pending_telegram_user_id", sa.String(255), nullable=True))
    if "confirmed_at" not in columns:
        op.add_column("telegram_link_codes", sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True))
    inspector = sa.inspect(op.get_bind())
    indexes = {i["name"] for i in inspector.get_indexes("telegram_link_codes")}
    if "ix_telegram_link_codes_initiated_by_user_id" not in indexes:
        op.create_index("ix_telegram_link_codes_initiated_by_user_id", "telegram_link_codes",
                        ["initiated_by_user_id"])
    foreign_keys = inspector.get_foreign_keys("telegram_link_codes")
    if not any(key.get("constrained_columns") == ["initiated_by_user_id"] and
               key.get("referred_table") == "users" for key in foreign_keys):
        op.create_foreign_key("fk_telegram_link_codes_initiated_by_user_id", "telegram_link_codes",
                              "users", ["initiated_by_user_id"], ["id"])


def downgrade():
    # Only new owner-bound link metadata; existing CRM, channels and mail claims untouched.
    op.drop_constraint("fk_telegram_link_codes_initiated_by_user_id", "telegram_link_codes", type_="foreignkey")
    op.drop_index("ix_telegram_link_codes_initiated_by_user_id", table_name="telegram_link_codes")
    for col in ("confirmed_at", "pending_telegram_user_id", "pending_chat_id", "initiated_by_user_id"):
        op.drop_column("telegram_link_codes", col)
