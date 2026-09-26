import { create } from 'zustand';
import type { Theme } from '@/types';

/**
 * Тема приложения.
 *
 * Состояние вынесено в общий стор, а не живёт внутри useTheme, потому что
 * тема — свойство всего документа, а не компонента. Пока она лежала в
 * useState хука, у каждого вызвавшего был свой экземпляр: экран, где хук не
 * вызывали, оставался без темы вовсе, а два вызова подряд спорили за один и
 * тот же атрибут data-theme.
 */

const STORAGE_KEY = 'theme';

/**
 * Тема, ВЫБРАННАЯ человеком вручную. null — выбора не было, и мы следуем
 * за оформлением Telegram.
 *
 * localStorage в приватном окне может бросить на чтении, поэтому обёрнуто.
 */
function storedTheme(): Theme | null {
    try {
        const value = localStorage.getItem(STORAGE_KEY);
        return value === 'light' || value === 'dark' ? value : null;
    } catch {
        return null;
    }
}

interface ThemeState {
    theme: Theme;
    /** Следуем ли за темой Telegram — до первого ручного выбора */
    followsTelegram: boolean;
    /** Ручной выбор: запоминается и отвязывает от Telegram */
    setTheme: (next: Theme) => void;
    /** Вернуться к оформлению Telegram — отменяет ручной выбор */
    followTelegram: (current?: Theme | null) => void;
    /** Тема пришла от Telegram. Ручной выбор она не перебивает. */
    adoptTelegram: (next: Theme) => void;
}

export const useThemeStore = create<ThemeState>((set) => ({
    theme: storedTheme() ?? 'light',
    followsTelegram: storedTheme() === null,

    setTheme: (next) => {
        try {
            localStorage.setItem(STORAGE_KEY, next);
        } catch {
            // Приватный режим: выбор не переживёт перезапуск
        }
        set({ theme: next, followsTelegram: false });
    },

    followTelegram: (current) => {
        try {
            localStorage.removeItem(STORAGE_KEY);
        } catch {
            // см. выше
        }
        set(current ? { followsTelegram: true, theme: current } : { followsTelegram: true });
    },

    adoptTelegram: (next) => set((state) => (
        state.followsTelegram && state.theme !== next ? { theme: next } : state
    )),
}));
