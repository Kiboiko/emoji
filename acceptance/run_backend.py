"""
Бэкенд приёмочного стенда: тот же код, что на сервере, но Telegram не уходит
наружу — отправки пишутся в файл, чтобы проверить, что именно и кому ушло бы.

Подменяется только транспорт (telegram_service.send_message). Всё, что решает,
отправлять ли сообщение и с каким текстом, — боевой код.
"""
import json
import os
import sys

import uvicorn

sys.path.insert(0, "/app")
import main  # noqa: E402
from services.telegram_service import telegram_service  # noqa: E402

OUTBOX = os.environ.get("OUTBOX", "/outbox/telegram.jsonl")

# Opt-in only in the isolated stage, including new getChatMember/sendPhoto
# and TON calls. The application has no route or production flag for this.
if os.environ.get("CAPTURE_EXTERNAL_API") == "1":
    from captured_transport import install
    install(OUTBOX, os.environ.get("MOCK_CONTROLS", "/outbox/mock-controls.json"))


async def capture(chat_id, text, parse_mode="HTML", reply_markup=None):
    with open(OUTBOX, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(
            {"chat_id": str(chat_id), "text": text, "reply_markup": reply_markup},
            ensure_ascii=False,
        ) + "\n")
    return {"ok": True}


telegram_service.send_message = capture
uvicorn.run(main.app, host="0.0.0.0", port=8000, log_level="info")
