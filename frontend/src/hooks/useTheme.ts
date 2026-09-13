import { useEffect, useState } from 'react';
import { useTelegram } from './useTelegram';
import type { Theme } from '@/types';

export const useTheme = () => {
    const { colorScheme } = useTelegram();
    const [theme, setTheme] = useState<Theme>(() => {
        const stored = localStorage.getItem('theme') as Theme;
        return stored || colorScheme || 'light';
    });

    useEffect(() => {
        // Sync with Telegram theme on mount
        if (colorScheme && !localStorage.getItem('theme')) {
            setTheme(colorScheme);
        }
    }, [colorScheme]);

    useEffect(() => {
        // Apply theme to document
        document.documentElement.setAttribute('data-theme', theme);
        localStorage.setItem('theme', theme);
    }, [theme]);

    const toggleTheme = () => {
        setTheme(prev => prev === 'light' ? 'dark' : 'light');
    };

    return {
        theme,
        setTheme,
        toggleTheme,
        isDark: theme === 'dark'
    };
};
