import httpx
import time
from typing import List, Union
from config import settings

class TelegramService:
    """Service for Telegram Bot operations"""
    
    def __init__(self):
        self.bot_token = settings.TELEGRAM_BOT_TOKEN
        self.api_url = f"https://api.telegram.org/bot{self.bot_token}"
        # Parse comma-separated list of channel IDs/usernames
        print(f"[TELEGRAM] Raw ADMIN_CHAT_ID from settings: '{settings.ADMIN_CHAT_ID}'")
        self.channel_ids = [c.strip() for c in settings.REVIEWS_CHANNEL_ID.split(",") if c.strip()]
        # Support multiple admin chats too
        self.admin_chat_ids = [c.strip() for c in settings.ADMIN_CHAT_ID.split(",") if c.strip()]
        print(f"[TELEGRAM] Initialized. Admin chat IDs to notify: {self.admin_chat_ids}")
    
    async def send_message(
        self,
        chat_id: Union[int, str],
        text: str,
        parse_mode: str = "HTML",
        reply_markup: dict | None = None,
    ) -> dict:
        """
        Send message to user.

        reply_markup передаётся готовым словарём Telegram API: на бэкенде нет
        aiogram, а собирать клавиатуру из трёх ключей ради типизации отдельной
        зависимости не стоит.
        """
        print(f"[TELEGRAM] Sending message to {chat_id}...")
        async with httpx.AsyncClient() as client:
            try:
                payload = {
                    "chat_id": chat_id,
                    "text": text
                }
                if parse_mode:
                    payload["parse_mode"] = parse_mode
                if reply_markup:
                    payload["reply_markup"] = reply_markup

                response = await client.post(
                    f"{self.api_url}/sendMessage",
                    json=payload
                )
                print(f"[TELEGRAM] Response from {chat_id}: {response.status_code}")
                response.raise_for_status()
                return response.json()
            except Exception as e:
                print(f"[TELEGRAM] ERROR sending to {chat_id}: {e}")
                if hasattr(e, 'response'):
                    print(f"[TELEGRAM] Error details: {e.response.text}")
                raise e
    
    async def send_purchase_data(
        self,
        telegram_id: int,
        product_name: str,
        product_type: str = "service",
        quantity: int = 1,
        content_data: dict = None,
        digital_items: list = None
    ) -> None:
        """Send purchased product data to user"""
        
        if product_type == "digital":
            # Send digital items as text file
            if digital_items:
                message = f"Спасибо за покупку!\n{product_name}\nКоличество: {quantity}"
                
                # Create file content
                file_content = "\n".join(digital_items)
                
                # Send document
                async with httpx.AsyncClient() as client:
                    files = {
                        'document': (f'{product_name}.txt', file_content.encode('utf-8'), 'text/plain')
                    }
                    data = {
                        'chat_id': telegram_id,
                        'caption': message
                    }
                    response = await client.post(
                        f"{self.api_url}/sendDocument",
                        files=files,
                        data=data
                    )
                    response.raise_for_status()
                    
        elif product_type == "instruction":
            # Send instruction as text file
            instruction_text = content_data.get("instruction", "") if content_data else ""
            if instruction_text:
                message = f"Спасибо за покупку!\n{product_name}"
                
                # Send document
                async with httpx.AsyncClient() as client:
                    files = {
                        'document': (f'{product_name}.txt', instruction_text.encode('utf-8'), 'text/plain')
                    }
                    data = {
                        'chat_id': telegram_id,
                        'caption': message
                    }
                    response = await client.post(
                        f"{self.api_url}/sendDocument",
                        files=files,
                        data=data
                    )
                    response.raise_for_status()
        else:
            # Service type - detailed notification after payment
            message = (
                f"<b>Спасибо за заказ!</b>\n\n"
                f"<b>Услуга:</b> {product_name}\n"
                f"<b>Количество:</b> {quantity}\n\n"
                f"Взяли в работу, ожидайте!"
            )
            await self.send_message(telegram_id, message)
    
    async def publish_review_to_channel(
        self,
        product_name: str,
        price_usdt: float,
        review_text: str,
        rating: int = None,
        product_id: str = None,
        username: str = None,
        quantity: int = None
    ) -> int:
        """
        Publish review to Telegram channel
        Returns message_id
        """
        message = f"⭐️ <b>Отзыв о товаре</b>\n\n"
        if username:
            message += f"<b>Покупатель:</b> {username}\n"
        message += f"<b>Товар:</b> {product_name}\n"
        message += f"<b>Цена:</b> ${price_usdt:.2f} USDT\n"
        if quantity:
            message += f"<b>Количество:</b> {quantity}\n"
        message += "\n"

        if rating:
            stars = "⭐️" * rating
            message += f"<b>Оценка:</b> {stars} ({rating}/5)\n\n"

        message += f"<b>Отзыв:</b>\n{review_text}\n\n"
        
        last_message_id = 0
        async with httpx.AsyncClient() as client:
            for channel in self.channel_ids:
                try:
                    response = await client.post(
                        f"{self.api_url}/sendMessage",
                        json={
                            "chat_id": channel,
                            "text": message,
                            "parse_mode": "HTML"
                        }
                    )
                    response.raise_for_status()
                    result = response.json()
                    last_message_id = result["result"]["message_id"]
                except Exception as e:
                    print(f"[TELEGRAM] Failed to post review to {channel}: {e}")
            
            return last_message_id


    async def send_service_completion_notification(
        self,
        chat_id: int,
        order_id: str,
        product_name: str,
        user_link: str,
        quantity: int
    ) -> None:
        """Send service completion notification"""
        message = (
            f"✅ <b>Ваш заказ #{str(order_id)[:8]}</b>\n"
            f"По товару - {product_name}\n"
            f"Ваша ссылка - {user_link}\n"
            f"Количество - {quantity}\n\n"
            f"<b>Выполнено.</b>\n"
            f"Спасибо за заказ"
        )
        
        await self.send_message(chat_id, message)

    async def send_out_of_stock_notification(self, product_name: str) -> None:
        """Send notification when stock reaches 0"""
        print(f"[TELEGRAM] DEBUG: send_out_of_stock_notification for '{product_name}'")
        if not self.admin_chat_ids:
            print("[TELEGRAM] WARNING: No admin chat IDs configured for out-of-stock notification!")
            return
        message = (
            f"Нет в наличии\n"
            f"Товар - {product_name}\n"
            f"Закончился сток, пополните"
        )
        print(f"[TELEGRAM] Sending stock alert to {len(self.admin_chat_ids)} admins")
        for chat_id in self.admin_chat_ids:
            try:
                await self.send_message(chat_id, message, parse_mode=None)
            except Exception as e:
                print(f"[TELEGRAM] FAILED out-of-stock to {chat_id}: {e}")

    async def send_new_service_order_notification(
        self, 
        product_name: str, 
        user_link: str, 
        quantity: int
    ) -> None:
        """Send notification for new service order"""
        if not self.admin_chat_ids:
            return
        message = (
            f"Новый заказ Услуги\n"
            f"Товар - {product_name}\n"
            f"Ссылка - {user_link}\n"
            f"Количество - {quantity}\n\n"
            f"Обработайте в админке"
        )
        for chat_id in self.admin_chat_ids:
            try:
                await self.send_message(chat_id, message, parse_mode=None)
            except Exception as e:
                print(f"[TELEGRAM] Failed to send service order notification to {chat_id}: {e}")

    async def send_withdrawal_request_notification(
        self,
        user_identifier: str,
        wallet: str,
        amount: float,
        balance_after: float
    ) -> None:
        """Send notification for new withdrawal request"""
        if not self.admin_chat_ids:
            return
        message = (
            f"Заявка на вывод!\n"
            f"Юзер - {user_identifier}\n"
            f"Адрес вывода - {wallet}\n"
            f"Сумма вывода - ${amount:.2f}\n"
            f"Остаток реф.баланса - ${balance_after:.2f}\n\n"
            f"Выполните вывод в админке"
        )
        for chat_id in self.admin_chat_ids:
            try:
                await self.send_message(chat_id, message, parse_mode=None)
            except Exception as e:
                print(f"[TELEGRAM] Failed to send withdrawal notification to {chat_id}: {e}")


# Global instance
telegram_service = TelegramService()


# ===========================================================================
# Управление доступом в закрытые каналы (подписки)
#
# Важное ограничение Bot API, определяющее всю схему: бот НЕ МОЖЕТ добавить
# пользователя в чат по user_id. Метода addChatMember в Bot API не существует
# (он есть только в клиентском MTProto). Единственный способ выдать доступ —
# создать персональную одноразовую инвайт-ссылку, по которой человек войдёт
# сам.
# ===========================================================================

class TelegramApiError(Exception):
    """Ошибка Bot API с сохранённым описанием — его пишем в журнал доступа."""

    def __init__(self, method: str, description: str, error_code: int | None = None):
        self.method = method
        self.description = description
        self.error_code = error_code
        super().__init__(f"{method}: {description}")


async def _call(method: str, payload: dict) -> dict:
    """Вызов Bot API с разбором telegram-ответа."""
    url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/{method}"
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(url, json=payload)

    try:
        data = response.json()
    except ValueError:
        raise TelegramApiError(method, f"не-JSON ответ, HTTP {response.status_code}")

    if not data.get("ok"):
        raise TelegramApiError(
            method,
            data.get("description", "unknown error"),
            data.get("error_code"),
        )
    return data["result"]


class ChannelAccessService:
    """Операции с закрытыми каналами авторов."""

    REQUIRED_RIGHTS = ("can_invite_users", "can_restrict_members")

    async def get_chat(self, chat_id: int | str) -> dict:
        return await _call("getChat", {"chat_id": chat_id})

    async def check_bot_is_admin(self, chat_id: int | str) -> tuple[bool, str | None]:
        """
        Проверяет, что бот — администратор канала с нужными правами.

        Без can_invite_users бот не сможет выдать доступ, без
        can_restrict_members — отозвать его по истечении подписки. Поэтому
        канал без обоих прав публиковать нельзя: подписки на нём будут
        продаваться, а работать не будут.
        """
        try:
            me = await _call("getMe", {})
            member = await _call(
                "getChatMember", {"chat_id": chat_id, "user_id": me["id"]}
            )
        except TelegramApiError as e:
            return False, e.description

        if member.get("status") != "administrator":
            return False, f"бот не администратор канала (статус: {member.get('status')})"

        missing = [r for r in self.REQUIRED_RIGHTS if not member.get(r)]
        if missing:
            return False, f"боту не хватает прав: {', '.join(missing)}"

        return True, None

    async def create_invite_link(
        self, chat_id: int | str, *, expire_seconds: int = 86400, name: str | None = None
    ) -> dict:
        """
        Персональная одноразовая ссылка-приглашение.

        member_limit=1 — ссылка сгорает после первого входа, чтобы её нельзя
        было передать другому. member_limit и creates_join_request
        взаимоисключающие, поэтому заявки на вступление здесь не используем.
        """
        payload = {
            "chat_id": chat_id,
            "member_limit": 1,
            "expire_date": int(time.time()) + expire_seconds,
        }
        if name:
            payload["name"] = name[:32]  # Telegram ограничивает длину имени
        return await _call("createChatInviteLink", payload)

    async def revoke_invite_link(self, chat_id: int | str, invite_link: str) -> None:
        await _call("revokeChatInviteLink", {"chat_id": chat_id, "invite_link": invite_link})

    async def ensure_not_banned(self, chat_id: int | str, user_id: int) -> bool:
        """
        Снимает бан с пользователя, если он забанен.

        Обязательный шаг перед выдачей доступа. В Telegram «удалить участника
        из канала» через интерфейс — это БАН, а не просто исключение:
        пользователь остаётся в чёрном списке. Забаненный не может войти ни по
        какой инвайт-ссылке, Telegram показывает ему «срок действия ссылки
        истёк» — и выглядит это как поломка оплаты, хотя ссылка живая.

        Такое случается, когда владелец канала убирал человека вручную, а тот
        потом купил подписку.

        only_if_banned=True не трогает тех, кто не забанен.
        Возвращает True, если бан пришлось снимать.
        """
        try:
            member = await _call("getChatMember", {"chat_id": chat_id, "user_id": user_id})
        except TelegramApiError:
            return False

        if member.get("status") != "kicked":
            return False

        await _call(
            "unbanChatMember",
            {"chat_id": chat_id, "user_id": user_id, "only_if_banned": True},
        )
        return True

    async def kick_member(self, chat_id: int | str, user_id: int) -> None:
        """
        Удаляет пользователя из канала.

        Два вызова подряд не избыточны: banChatMember оставляет человека в
        вечном бане, и он не сможет купить подписку повторно.
        unbanChatMember с only_if_banned снимает бан, не трогая тех, кто
        забанен администрацией за нарушения.
        """
        await _call("banChatMember", {"chat_id": chat_id, "user_id": user_id})
        await _call(
            "unbanChatMember",
            {"chat_id": chat_id, "user_id": user_id, "only_if_banned": True},
        )


channel_access = ChannelAccessService()
