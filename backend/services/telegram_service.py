import httpx
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
    
    async def send_message(self, chat_id: Union[int, str], text: str, parse_mode: str = "HTML") -> dict:
        """Send message to user"""
        print(f"[TELEGRAM] Sending message to {chat_id}...")
        async with httpx.AsyncClient() as client:
            try:
                payload = {
                    "chat_id": chat_id,
                    "text": text
                }
                if parse_mode:
                    payload["parse_mode"] = parse_mode
                    
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
