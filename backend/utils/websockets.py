from fastapi import WebSocket


class ConnectionManager:
    def __init__(self):
        # Map user_id to list of active websockets
        self.active_connections: dict[str, list[WebSocket]] = {}
        # Сокеты свёрнутых приложений. Соединение у свёрнутого мини-аппа
        # живёт, но человек на экран не смотрит — «в сети» он не считается
        self.inactive: set[WebSocket] = set()

    async def connect(self, websocket: WebSocket, user_id: str):
        await websocket.accept()
        if user_id not in self.active_connections:
            self.active_connections[user_id] = []
        self.active_connections[user_id].append(websocket)

    def disconnect(self, websocket: WebSocket, user_id: str):
        self.inactive.discard(websocket)
        if user_id in self.active_connections:
            if websocket in self.active_connections[user_id]:
                self.active_connections[user_id].remove(websocket)
            if not self.active_connections[user_id]:
                del self.active_connections[user_id]

    def set_active(self, websocket: WebSocket, active: bool):
        if active:
            self.inactive.discard(websocket)
        else:
            self.inactive.add(websocket)

    def is_online(self, user_id: str) -> bool:
        """Приложение открыто и на экране хотя бы на одном устройстве."""
        return any(ws not in self.inactive for ws in self.active_connections.get(user_id, ()))

    async def send_personal_message(self, message: dict, user_id: str):
        if user_id in self.active_connections:
            for connection in self.active_connections[user_id]:
                try:
                    await connection.send_json(message)
                except Exception:
                    pass

    async def broadcast(self, message: dict):
        for user_id, connections in self.active_connections.items():
            for connection in connections:
                try:
                    await connection.send_json(message)
                except Exception:
                    pass

manager = ConnectionManager()
