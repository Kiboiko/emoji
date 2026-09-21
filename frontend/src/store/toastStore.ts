import { create } from 'zustand';

/**
 * Короткие уведомления поверх интерфейса.
 *
 * До этого витрина молчала о любом исходе: ошибки уходили в console.error,
 * успешные действия не подтверждались ничем. Снаружи это выглядело как
 * «ничего не произошло» — например, корзина откатывала количество обратно
 * без единого слова о том, что товар продаётся штучно.
 *
 * Стор, а не React-контекст: zustand уже используется для корзины и
 * авторизации, и вызвать show() можно из любого места, включая catch-блок.
 */

export type ToastKind = 'info' | 'error' | 'success';

interface Toast {
    id: number;
    text: string;
    kind: ToastKind;
}

interface ToastState {
    toasts: Toast[];
    show: (text: string, kind?: ToastKind) => void;
    dismiss: (id: number) => void;
}

// Держим не больше трёх: экран телефона маленький, а очередь из десяти
// уведомлений перекрыла бы половину интерфейса.
const MAX_VISIBLE = 3;
const LIFETIME_MS = 3000;

let nextId = 1;

export const useToastStore = create<ToastState>((set, get) => ({
    toasts: [],

    show: (text, kind = 'info') => {
        const id = nextId++;
        set((state) => ({ toasts: [...state.toasts, { id, text, kind }].slice(-MAX_VISIBLE) }));
        setTimeout(() => get().dismiss(id), LIFETIME_MS);
    },

    dismiss: (id) => set((state) => ({ toasts: state.toasts.filter((t) => t.id !== id) })),
}));

/** Достаёт человеческий текст из ошибки axios. */
export function errorText(error: unknown, fallback: string): string {
    const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;

    if (typeof detail === 'string') return detail;

    // FastAPI отдаёт ошибки валидации массивом объектов — без разбора
    // пользователь увидел бы [object Object]
    if (Array.isArray(detail)) {
        const first = detail[0] as { msg?: string } | undefined;
        if (first?.msg) return first.msg;
    }

    return fallback;
}
