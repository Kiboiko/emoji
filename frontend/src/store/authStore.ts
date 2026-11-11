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

export const useAuthStore = create<AuthStore>()((set) => ({
    user: null,
    accessToken: localStorage.getItem('access_token'),
    language: 'ru',

    // Язык, выбранный раньше, приходит вместе с пользователем: без этого
    // приложение при каждом запуске открывалось по-русски
    setUser: (user) => set((state) => ({
        user, isAuthenticated: !!state.accessToken && !!user,
        ...(user?.app_language ? { language: user.app_language } : {}),
    })),

    setAccessToken: (token) => {
        set((state) => ({ accessToken: token, isAuthenticated: !!token && !!state.user }));
        if (token) {
            localStorage.setItem('access_token', token);
        } else {
            localStorage.removeItem('access_token');
        }
    },

    setLanguage: (lang) => set({ language: lang }),

    logout: () => {
        set({ user: null, accessToken: null, isAuthenticated: false });
        localStorage.removeItem('access_token');
    },

    isAuthenticated: false,
}));
