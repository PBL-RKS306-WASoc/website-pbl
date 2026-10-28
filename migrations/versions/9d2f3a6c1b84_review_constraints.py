"""Add review rating and uniqueness constraints.

Revision ID: 9d2f3a6c1b84
Revises: 350a4ee6369f
Create Date: 2026-10-28
"""

from alembic import op

revision = "9d2f3a6c1b84"
down_revision = "350a4ee6369f"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("reviews") as batch_op:
        batch_op.create_check_constraint(
            "ck_reviews_rating_range", "rating >= 1 AND rating <= 5"
        )
        batch_op.create_unique_constraint(
            "uq_reviews_product_user", ["product_id", "user_id"]
        )


def downgrade():
    with op.batch_alter_table("reviews") as batch_op:
        batch_op.drop_constraint("uq_reviews_product_user", type_="unique")
        batch_op.drop_constraint("ck_reviews_rating_range", type_="check")
