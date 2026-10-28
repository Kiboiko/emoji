from fastapi import Depends

from models.user import User
from utils.auth import require_admin


async def get_current_admin_user(user: User = Depends(require_admin)) -> User:
    """
    Администратор для разделов «Статистика», «Пользователи» и «Заказы».

    Здесь была своя проверка токена, которая смотрела только на is_admin: ни
    версия токена, ни блокировка не сверялись. Поэтому после смены пароля или
    «Выйти везде» старый админский токен продолжал открывать эти разделы
    (включая блокировку пользователей и смену статуса заказов) до конца срока
    жизни. Теперь проверка общая со всей админкой — utils.auth.require_admin.
    """
    return user
