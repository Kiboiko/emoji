"""Обложка подписок: своя картинка у канала

Товар подписки брал картинку из аватара канала, а аватар подтягивается из
Telegram. У канала без фотографии его нет вовсе, и в каталоге такая подписка
стояла с серой заглушкой рядом с обычными товарами, у которых фото есть.

Отдельная колонка, а не запись в avatar_url: аватар перезаписывается при
каждой проверке прав бота, и загруженная вручную обложка терялась бы после
первой же проверки. Приоритет при показе — у обложки: её автор выбрал сам.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c2d3e4f5a6b7'
down_revision: Union[str, None] = 'b1c2d3e4f5a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('channels', sa.Column('cover_url', sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column('channels', 'cover_url')
