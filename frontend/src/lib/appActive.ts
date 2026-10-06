/**
 * Смотрит ли человек на приложение прямо сейчас.
 *
 * Одного document.visibilityState мало: Telegram умеет сворачивать мини-апп
 * в полоску внизу чата, и страница при этом остаётся «видимой». Чат сделки
 * считал себя открытым, отмечал входящие прочитанными — и бот молчал, хотя
 * человек давно переписывался с кем-то другим. Свёрнутость Telegram сообщает
 * сам: isActive и события activated/deactivated (Bot API 8.0). На старых
 * клиентах их нет — там решает только видимость страницы.
 */

type Listener = (active: boolean) => void;

const listeners = new Set<Listener>();

// Своё значение по событиям, а не чтение isActive: не на всех версиях
// клиента свойство успевает обновиться к моменту, когда приходит событие
let telegramActive = (window as any).Telegram?.WebApp?.isActive !== false;
let last: boolean | null = null;

export function isAppActive(): boolean {
    return document.visibilityState === 'visible' && telegramActive;
}

function notify() {
    const active = isAppActive();
    if (active === last) return;
    last = active;
    listeners.forEach((fn) => fn(active));
}

let started = false;

function start() {
    if (started) return;
    started = true;
    last = isAppActive();
    document.addEventListener('visibilitychange', notify);
    const app = (window as any).Telegram?.WebApp;
    app?.onEvent?.('activated', () => {
        telegramActive = true;
        notify();
    });
    app?.onEvent?.('deactivated', () => {
        telegramActive = false;
        notify();
    });
}

export function onAppActiveChange(fn: Listener): () => void {
    start();
    listeners.add(fn);
    return () => {
        listeners.delete(fn);
    };
}
