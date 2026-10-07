"""Выплаты через TonConnect из админки

Раньше админ переводил деньги из своего кошелька вручную, копируя адрес и
сумму, а потом отмечал заявку выполненной. Теперь он нажимает «Выплатить»,
подтверждает перевод в кошельке площадки, и заявка закрывается сама, когда
перевод появится в блокчейне. Для этого у заявки:

  * payout_comment — уникальный комментарий перевода, по нему он находится;
  * sent_at — когда админ подписал перевод (статус SENDING);
  * tx_hash — найденная транзакция;
  * reject_reason — заявку теперь можно отклонить, деньги вернутся на баланс.

Статусы хранятся строкой (native_enum=False, без CHECK), поэтому новые
SENDING и REJECTED схемы не требуют.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, None] = 'e0f1a2b3c4d5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('withdrawals', sa.Column('payout_comment', sa.String(length=64), nullable=True))
    op.add_column('withdrawals', sa.Column('sent_at', sa.DateTime(), nullable=True))
    op.add_column('withdrawals', sa.Column('tx_hash', sa.String(length=100), nullable=True))
    op.add_column('withdrawals', sa.Column('reject_reason', sa.String(length=500), nullable=True))
    op.create_index(
        'ix_withdrawals_payout_comment', 'withdrawals', ['payout_comment'], unique=True,
    )


def downgrade() -> None:
    op.drop_index('ix_withdrawals_payout_comment', table_name='withdrawals')
    op.drop_column('withdrawals', 'reject_reason')
    op.drop_column('withdrawals', 'tx_hash')
    op.drop_column('withdrawals', 'sent_at')
    op.drop_column('withdrawals', 'payout_comment')
