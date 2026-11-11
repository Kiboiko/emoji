import os
import unittest
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

os.environ["TELEGRAM_BOT_TOKEN"] = "111111111:TEST_ONLY_TOKEN_WITHOUT_EXTERNAL_CALLS"
spec = importlib.util.spec_from_file_location("market_bot", Path(__file__).parents[1] / "bot.py")
market = importlib.util.module_from_spec(spec)
spec.loader.exec_module(market)


def message():
    return SimpleNamespace(from_user=SimpleNamespace(id=123, full_name="Test", username="test"),
        answer=AsyncMock(), chat=SimpleNamespace(type="private"), model_dump=Mock(return_value={"text":"hello"}))


class Handlers(unittest.IsolatedAsyncioTestCase):
    async def test_start_carries_product_parameter(self):
        msg=message()
        with patch.object(market,"WEBAPP_URL","https://stage.example/?lang=ru"):
            await market.command_start_handler(msg,SimpleNamespace(args="product_123"))
        button=msg.answer.call_args.kwargs["reply_markup"].inline_keyboard[0][0]
        self.assertEqual(button.web_app.url,"https://stage.example/?lang=ru&startapp=product_123")

    async def test_start_without_https_omits_button(self):
        for url in ["", "http://localhost:8080"]:
            msg=message()
            with patch.object(market,"WEBAPP_URL",url):await market.command_start_handler(msg,SimpleNamespace(args=None))
            self.assertNotIn("reply_markup",msg.answer.call_args.kwargs)

    async def test_malformed_deal_callbacks_do_not_call_backend(self):
        with patch.object(market,"call_backend",new_callable=AsyncMock) as backend:
            for data in [None,"deal:","deal:confirm:abc","deal:confirm:-1","deal:unknown:1"]:
                callback=SimpleNamespace(data=data,answer=AsyncMock())
                await market.on_deal_action(callback)
                callback.answer.assert_awaited_once_with("Некорректная кнопка")
            backend.assert_not_awaited()

    async def test_deal_action_forwards_authenticated_sender(self):
        callback=SimpleNamespace(data="deal:confirm:12",from_user=SimpleNamespace(id=123),answer=AsyncMock())
        with patch.object(market,"call_backend",new_callable=AsyncMock,return_value={"reply":"OK"}) as backend:
            await market.on_deal_action(callback)
            backend.assert_awaited_once_with("deal-action",{"telegram_user_id":123,"deal_number":12,"action":"confirm"})
        callback.answer.assert_awaited_once_with("OK",show_alert=True)

    async def test_malformed_moderation_callbacks_do_not_call_backend(self):
        with patch.object(market,"call_backend",new_callable=AsyncMock) as backend:
            for data in [None,"mod:","mod:approve:bad","mod:other:11111111-1111-4111-8111-111111111111"]:
                callback=SimpleNamespace(data=data,answer=AsyncMock())
                await market.on_moderation_action(callback)
                callback.answer.assert_awaited_once_with("Некорректная кнопка")
            backend.assert_not_awaited()

    async def test_relay_unavailable_and_group_ignored(self):
        msg=message()
        with patch.object(market,"call_backend",new_callable=AsyncMock,return_value=None) as backend:
            await market.on_relay_message(msg)
            self.assertEqual(backend.call_args.args[1]["telegram_user_id"],123)
            msg.answer.assert_awaited_once()
            msg.chat.type="group";backend.reset_mock()
            await market.on_relay_message(msg);backend.assert_not_awaited()

    async def test_polling_requests_membership_updates(self):
        with patch.object(market.bot,"delete_webhook",new_callable=AsyncMock), patch.object(market.dp,"start_polling",new_callable=AsyncMock) as polling:
            await market.main()
            self.assertIn("chat_member",polling.call_args.kwargs["allowed_updates"])
            self.assertIn("my_chat_member",polling.call_args.kwargs["allowed_updates"])

    async def test_no_internal_secret_no_request(self):
        with patch.object(market,"INTERNAL_TOKEN",""):
            self.assertIsNone(await market.call_backend("relay",{}))


if __name__=="__main__":unittest.main()
