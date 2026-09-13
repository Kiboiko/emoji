import { useEffect, useRef } from 'react';

// Use same env logic as frontend or default to /ws relative (proxied)
const WS_URL = import.meta.env.VITE_WS_URL || (window.location.protocol === 'https:' ? 'wss://' : 'ws://') + window.location.host + '/ws';

export const useWebSocket = (onMessage?: (data: any) => void, token?: string | null) => {
    const ws = useRef<WebSocket | null>(null);

    const onMessageRef = useRef(onMessage);

    useEffect(() => {
        onMessageRef.current = onMessage;
    }, [onMessage]);

    useEffect(() => {
        if (!token) return; // Don't connect without token

        // Connect
        const url = `${WS_URL}?token=${token}`;
        ws.current = new WebSocket(url);

        ws.current.onopen = () => {
            console.log('Admin WS Connected');
        };

        ws.current.onmessage = (event) => {
            try {
                const message = JSON.parse(event.data);
                if (onMessageRef.current) {
                    onMessageRef.current(message);
                }
            } catch (e) {
                console.error('WS Parse Error', e);
            }
        };

        ws.current.onclose = () => {
            console.log('Admin WS Disconnected');
            // Reconnect logic could go here
        };

        return () => {
            ws.current?.close();
        };
    }, [token]); // Reconnect when token changes

    return;
};
