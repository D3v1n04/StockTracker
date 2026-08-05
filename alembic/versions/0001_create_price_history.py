"""Create the price history table.

Revision ID: 0001
Revises:
Create Date: 2026-08-05

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "price_history" in inspector.get_table_names():
        column_names = [
            column["name"]
            for column in inspector.get_columns("price_history")
        ]
        primary_key = set(
            inspector.get_pk_constraint("price_history")["constrained_columns"]
        )
        expected_columns = [
            "Symbol",
            "Date",
            "Open",
            "High",
            "Low",
            "Close",
            "Volume",
        ]

        if column_names != expected_columns or primary_key != {"Symbol", "Date"}:
            raise RuntimeError(
                "Existing price_history schema does not match StockTracker"
            )
        return

    op.create_table(
        "price_history",
        sa.Column("Symbol", sa.String(), nullable=False),
        sa.Column("Date", sa.String(), nullable=False),
        sa.Column("Open", sa.Float(), nullable=True),
        sa.Column("High", sa.Float(), nullable=True),
        sa.Column("Low", sa.Float(), nullable=True),
        sa.Column("Close", sa.Float(), nullable=True),
        sa.Column("Volume", sa.BigInteger(), nullable=True),
        sa.PrimaryKeyConstraint("Symbol", "Date"),
    )


def downgrade() -> None:
    op.drop_table("price_history")
