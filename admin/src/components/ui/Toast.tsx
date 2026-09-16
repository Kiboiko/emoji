import React, { createContext, useCallback, useContext, useState } from 'react';
import { CheckCircle2, AlertCircle, X } from 'lucide-react';

type ToastKind = 'success' | 'error';

interface Toast {
    id: number;
    kind: ToastKind;
    text: string;
}

interface ToastApi {
    success: (text: string) => void;
    error: (text: string) => void;
    /** Достаёт человекочитаемое сообщение из ошибки axios */
    fromError: (e: unknown, fallback?: string) => void;
}

const ToastContext = createContext<ToastApi | null>(null);

export const useToast = (): ToastApi => {
    const api = useContext(ToastContext);
    if (!api) throw new Error('useToast использован вне ToastProvider');
    return api;
};

/**
 * Достаёт текст ошибки из ответа бэкенда.
 *
 * detail бывает строкой, объектом (машиночитаемые ошибки вроде terms_required)
 * и массивом (ошибки валидации FastAPI). Без разбора всех трёх на экран
 * попадает «[object Object]».
 */
export function errorText(e: any, fallback = 'Не удалось выполнить'): string {
    const detail = e?.response?.data?.detail;
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail)) return detail[0]?.msg ?? fallback;
    if (detail?.message) return detail.message;
    return e?.message ?? fallback;
}

export const ToastProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
    const [toasts, setToasts] = useState<Toast[]>([]);

    const push = useCallback((kind: ToastKind, text: string) => {
        const id = Date.now() + Math.random();
        setToasts((current) => [...current, { id, kind, text }]);
        setTimeout(() => {
            setToasts((current) => current.filter((t) => t.id !== id));
        }, 5000);
    }, []);

    const api: ToastApi = {
        success: useCallback((text: string) => push('success', text), [push]),
        error: useCallback((text: string) => push('error', text), [push]),
        fromError: useCallback(
            (e: unknown, fallback?: string) => push('error', errorText(e, fallback)),
            [push],
        ),
    };

    return (
        <ToastContext.Provider value={api}>
            {children}
            <div className="fixed bottom-6 right-6 z-[100] flex flex-col gap-2 max-w-sm">
                {toasts.map((toast) => (
                    <div
                        key={toast.id}
                        className={`flex items-start gap-3 px-4 py-3 rounded-lg shadow-lg border text-sm ${
                            toast.kind === 'success'
                                ? 'bg-green-900/90 border-green-700 text-green-100'
                                : 'bg-red-900/90 border-red-700 text-red-100'
                        }`}
                    >
                        {toast.kind === 'success'
                            ? <CheckCircle2 size={18} className="shrink-0 mt-0.5" />
                            : <AlertCircle size={18} className="shrink-0 mt-0.5" />}
                        <span className="flex-1 break-words">{toast.text}</span>
                        <button
                            onClick={() => setToasts((c) => c.filter((t) => t.id !== toast.id))}
                            className="shrink-0 opacity-60 hover:opacity-100"
                        >
                            <X size={15} />
                        </button>
                    </div>
                ))}
            </div>
        </ToastContext.Provider>
    );
};
