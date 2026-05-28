"""fix_penalty_ledger_unique_constraint_add_penalty_type

Revision ID: 11ac610c9655
Revises: ccbf2e1efafb
Create Date: 2026-05-28 16:54:43.633365

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '11ac610c9655'
down_revision: Union[str, Sequence[str], None] = 'ccbf2e1efafb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # The original constraint only covered (loan_id, schedule_id, accrual_date).
    # On DPD==60 the engine inserts two rows on the same date with different
    # penalty_type values ('penal_interest_dpd30' and 'legal_charge'), causing a
    # unique violation. Adding penalty_type to the constraint key fixes this.
    op.drop_constraint("idx_penalty_date", "penalty_ledger", type_="unique")
    op.create_unique_constraint(
        "idx_penalty_date",
        "penalty_ledger",
        ["loan_id", "schedule_id", "accrual_date", "penalty_type"],
    )


def downgrade() -> None:
    op.drop_constraint("idx_penalty_date", "penalty_ledger", type_="unique")
    op.create_unique_constraint(
        "idx_penalty_date",
        "penalty_ledger",
        ["loan_id", "schedule_id", "accrual_date"],
    )
