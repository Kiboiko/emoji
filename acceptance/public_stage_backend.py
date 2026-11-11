"""Real-Telegram stage launcher. Synthetic fixture recipients are captured only.

Never installed in a production image. The public stage has its own database,
token and testnet configuration. Real Telegram users/channels use real API calls.
"""
import os
import sys

assert '@gram-stage-db:5432/stage' in os.environ.get('DATABASE_URL', '')
assert os.environ.get('VITE_BOT_USERNAME') == 'Funshop_bot'
assert os.environ.get('TON_NETWORK') == 'testnet'
assert os.environ.get('DEBUG') == 'false'
sys.path.insert(0, '/app')

import httpx
import main
import uvicorn

original_send = httpx.AsyncClient.send


async def send(client, request, **kwargs):
    if request.url.host == 'api.telegram.org':
        import json
        try:
            body = json.loads(request.content or b'{}')
        except (ValueError, httpx.RequestNotRead):
            body = dict(request.url.params)
        try:
            synthetic = 8_800_000_000 <= int(body.get('chat_id', 0)) < 8_800_000_100
        except (TypeError, ValueError):
            synthetic = False
        if synthetic:
            return httpx.Response(200, request=request, json={
                'ok': True, 'result': {'message_id': 1, 'date': 1,
                    'chat': {'id': body['chat_id'], 'type': 'private'}},
            })
    return await original_send(client, request, **kwargs)


httpx.AsyncClient.send = send
uvicorn.run(main.app, host='0.0.0.0', port=8000, log_level='info')
