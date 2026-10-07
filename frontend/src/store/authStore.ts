import { create } from 'zustand';
import type { User, Language } from '@/types';

interface AuthStore {
    user: User | null;
    accessToken: string | null;
    language: Language;
    setUser: (user: User | null) => void;
    setAccessToken: (token: string | null) => void;
    setLanguage: (lang: Language) => void;
    logout: () => void;
    isAuthenticated: boolean;
}

export const useAuthStore = create<AuthStore>()((set, get) => ({
    user: null,
    accessToken: localStorage.getItem('access_token'),
    language: 'ru',

    // Язык, выбранный раньше, приходит вместе с пользователем: без этого
    // приложение при каждом запуске открывалось по-русски
    setUser: (user) => set(user?.app_language
        ? { user, language: user.app_language }
        : { user }),

    setAccessToken: (token) => {
        set({ accessToken: token });
        if (token) {
            localStorage.setItem('access_token', token);
        } else {
            localStorage.removeItem('access_token');
        }
    },

    setLanguage: (lang) => set({ language: lang }),

    logout: () => {
        set({ user: null, accessToken: null });
        localStorage.removeItem('access_token');
    },

    get isAuthenticated() {
        return !!get().accessToken && !!get().user;
    },
}));
