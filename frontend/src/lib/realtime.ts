/**
 * Одно WebSocket-соединение на всё приложение.
 *
 * Раньше каждый экран, которому нужны живые обновления, открывал своё
 * соединение: каталог, карточка товара и корень приложения держали три сокета
 * одновременно. И ни один не переподключался: телефон ушёл в фон, сеть
 * мигнула — обновления переставали приходить до перезапуска приложения. Для
 * каталога это терпимо, для чата сделки — нет: сообщения просто не доходили бы.
 *
 * Здесь соединение одно, подписчиков сколько угодно, а обрыв лечится
 * переподключением с нарастающей паузой. После переподключения подписчики
 * узнают об этом и дочитывают пропущенное запросом — сервер события, ушедшие
 * в оборванный сокет, не повторяет.
 */

import { isAppActive, onAppActiveChange } from './appActive';

type Listener = (message: any) => void;

const WS_URL = import.meta.env.VITE_WS_URL
    || (window.location.protocol === 'https:' ? 'wss://' : 'ws://') + window.location.host + '/ws';

const MAX_DELAY = 30_000;

let socket: WebSocket | null = null;
let token: string | null = null;
let attempts = 0;
let retryTimer: ReturnType<typeof setTimeout> | null = null;

const listeners = new Set<Listener>();
const reconnectListeners = new Set<() => void>();

function open() {
    if (retryTimer) {
        clearTimeout(retryTimer);
        retryTimer = null;
    }
    if (!token) return;

    const ws = new WebSocket(`${WS_URL}?token=${encodeURIComponent(token)}`);
    socket = ws;

    ws.onopen = () => {
        const recovered = attempts > 0;
        attempts = 0;
        // Сервер по умолчанию считает новое соединение «в сети» — а оно
        // могло подняться и в свёрнутом приложении
        sendPresence(isAppActive());
        if (recovered) reconnectListeners.forEach((fn) => fn());
    };

    ws.onmessage = (event) => {
        let data: any;
        try {
            data = JSON.parse(event.data);
        } catch {
            return;
        }
        listeners.forEach((fn) => {
            try {
                fn(data);
            } catch (e) {
                console.error('WS listener failed', e);
            }
        });
    };

    ws.onclose = () => {
        // Сокет заменили новым — этот закрылся штатно, переподключать нечего
        if (socket !== ws) return;
        socket = null;
        scheduleRetry();
    };
}

function scheduleRetry() {
    if (!token || retryTimer) return;
    const delay = Math.min(MAX_DELAY, 1000 * 2 ** attempts);
    attempts += 1;
    retryTimer = setTimeout(open, delay);
}

function sendPresence(active: boolean) {
    if (socket?.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ type: 'presence', active }));
    }
}

onAppActiveChange((active) => {
    // Собеседник в чате сделки видит «в сети» или «был(а) в сети»
    sendPresence(active);
    // Вернулись в приложение — переподключаемся сразу, не дожидаясь паузы:
    // в фоне телефон рвёт соединения, а ждать до полуминуты незачем
    if (!active || !token) return;
    if (!socket || socket.readyState === WebSocket.CLOSED) {
        attempts = Math.max(attempts, 1);
        open();
    }
});

export const realtime = {
    /** Подключиться с токеном пользователя. Повторный вызов с тем же токеном ничего не делает */
    connect(nextToken: string | null) {
        if (nextToken === token && socket) return;
        token = nextToken;
        const previous = socket;
        socket = null;
        previous?.close();
        attempts = 0;
        if (token) open();
    },

    subscribe(fn: Listener): () => void {
        listeners.add(fn);
        return () => {
            listeners.delete(fn);
        };
    },

    /** Соединение восстановилось после обрыва — пора дочитать пропущенное */
    onReconnect(fn: () => void): () => void {
        reconnectListeners.add(fn);
        return () => {
            reconnectListeners.delete(fn);
        };
    },

    send(payload: object) {
        if (socket?.readyState === WebSocket.OPEN) {
            socket.send(JSON.stringify(payload));
        }
    },
};
