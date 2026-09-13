import { useEffect, useRef } from 'react';
import { useAuthStore } from '../store/authStore';

// Use same env logic as frontend or default to /ws relative (proxied)
const WS_URL = import.meta.env.VITE_WS_URL || (window.location.protocol === 'https:' ? 'wss://' : 'ws://') + window.location.host + '/ws';

export const useWebSocket = (onMessage?: (data: any) => void) => {
    const ws = useRef<WebSocket | null>(null);

    const onMessageRef = useRef(onMessage);

    // Subscribe to access token changes
    const accessToken = useAuthStore((state) => state.accessToken);

    useEffect(() => {
        onMessageRef.current = onMessage;
    }, [onMessage]);

    useEffect(() => {
        // Connect
        const url = accessToken ? `${WS_URL}?token=${accessToken}` : WS_URL;

        ws.current = new WebSocket(url);

        ws.current.onopen = () => {
            console.log('WS Connected');
        };

        ws.current.onmessage = (event) => {
            try {
                const message = JSON.parse(event.data);

                // Pass to component-specific handler
                if (onMessageRef.current) {
                    onMessageRef.current(message);
                }
            } catch (e) {
                console.error('WS Parse Error', e);
            }
        };

        ws.current.onclose = () => {
            console.log('WS Disconnected');
            // Reconnect logic could go here
        };

        return () => {
            ws.current?.close();
        };
    }, [accessToken]); // Reconnect when token changes

    return ws.current;
};
