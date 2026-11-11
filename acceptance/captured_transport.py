"""Stage-only HTTP transport. Never imported by the application itself."""
import json
from pathlib import Path
import httpx


def install(outbox, controls):
    original = httpx.AsyncClient.send
    serial = 1000

    async def send(client, request, **kwargs):
        nonlocal serial
        try:
            config = json.loads(Path(controls).read_text(encoding="utf-8"))
        except FileNotFoundError:
            config = {}
        host = request.url.host
        if config.get("nft_preview") and host == "t.me" and request.url.path.startswith("/nft/"):
            return httpx.Response(200, request=request, text='<meta property="og:title" content="Plush Pepe #7776"><meta property="og:image" content="https://nft.fragment.com/perf-preview.jpg">')
        if config.get("nft_preview") and str(request.url) == "https://nft.fragment.com/perf-preview.jpg":
            return httpx.Response(200, request=request, content=Path('/outbox/nft-preview.jpg').read_bytes())
        if host == "api.telegram.org":
            method = request.url.path.rsplit("/", 1)[-1]
            try:
                body = json.loads(request.content or b"{}")
            except (ValueError, httpx.RequestNotRead):
                body = dict(request.url.params)
            serial += 1
            record = {"method": method, "chat_id": str(body.get("chat_id", "")),
                "text": body.get("text", body.get("caption", "")), "message_id": serial}
            with open(outbox, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            error = config.get("send_errors", {}).get(method)
            if error:
                if error == "timeout":
                    raise httpx.ReadTimeout("Stage simulated timeout", request=request)
                return httpx.Response(200, request=request, json={"ok": False,
                    "error_code": error["code"], "description": "Stage simulated rejection",
                    "parameters": {"retry_after": error.get("retry_after", 1)}})
            if method == "getMe":
                result = {"id": 111111111, "is_bot": True, "first_name": "Acceptance", "username": "acc_bot"}
            elif method == "getChat":
                result = {"id": body.get("chat_id"), "type": "channel", "title": "Acceptance chat"}
            elif method == "getChatMember":
                if str(body.get("user_id")) == "111111111":
                    result = {"status": "member"} if config.get("deny_bot_admin") else {"status": "administrator", "can_post_messages": True}
                else:
                    value = config.get("memberships", {}).get(f"{body.get('chat_id')}:{body.get('user_id')}", "member")
                    result = value if isinstance(value, dict) else {"status": value}
            else:
                result = {"message_id": serial, "date": 1, "chat": {"id": body.get("chat_id", 1), "type": "private"}}
            return httpx.Response(200, request=request, json={"ok": True, "result": result})
        if host == "api.coingecko.com":
            return httpx.Response(200, request=request, json={"the-open-network": {"usd": 2.5}})
        if host in ("toncenter.com", "testnet.toncenter.com"):
            return httpx.Response(200, request=request, json={"ok": True, "result": config.get("transactions", [])})
        if host in ("localhost", "127.0.0.1", "backend", "gram-verify-nginx"):
            return await original(client, request, **kwargs)
        raise RuntimeError("External HTTP is disabled on acceptance stage")

    httpx.AsyncClient.send = send
