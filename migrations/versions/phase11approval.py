
"""Add recruiter approval fields.

Revision ID: phase11approval
Revises: 65796178f34f
"""

from alembic import op
import sqlalchemy as sa

revision = "phase11approval"
down_revision = "65796178f34f"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "users",
        sa.Column(
            "approval_status",
            sa.String(length=20),
            nullable=False,
            server_default="approved",
        ),
    )

    op.add_column(
        "users",
        sa.Column(
            "approved_at",
            sa.DateTime(),
            nullable=True,
        ),
    )


def downgrade():
    op.drop_column("users", "approved_at")
    op.drop_column("users", "approval_status")
