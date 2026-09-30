import { useEffect, useRef } from 'react';
import { useAuthStore } from '../store/authStore';
import { realtime } from '../lib/realtime';

/**
 * Живые обновления с сервера.
 *
 * Соединение одно на всё приложение (lib/realtime): хук только подключает
 * его под текущим токеном и подписывает обработчик экрана.
 */
export const useWebSocket = (onMessage?: (data: any) => void) => {
    const accessToken = useAuthStore((state) => state.accessToken);
    const onMessageRef = useRef(onMessage);

    useEffect(() => {
        onMessageRef.current = onMessage;
    }, [onMessage]);

    useEffect(() => {
        realtime.connect(accessToken);
    }, [accessToken]);

    useEffect(() => realtime.subscribe((message) => onMessageRef.current?.(message)), []);
};
