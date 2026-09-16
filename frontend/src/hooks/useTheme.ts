import { useEffect, useState } from 'react';
import { useTelegram } from './useTelegram';
import { applyTelegramTheme, clearTelegramTheme } from '@/lib/telegramTheme';
import type { Theme } from '@/types';

/**
 * Ключ хранит тему, ВЫБРАННУЮ пользователем вручную.
 *
 * Прежняя версия писала сюда тему на каждом рендере, в том числе значение по
 * умолчанию. Из-за этого ключ появлялся сразу после первого запуска, а проверка
 * «пользователь ничего не выбирал» больше никогда не срабатывала: тема Telegram
 * не подхватывалась вообще. Хуже того, useTelegram узнаёт colorScheme
 * асинхронно, поэтому в хранилище успевала попасть светлая тема — и человек с
 * тёмным Telegram всегда получал светлое приложение.
 */
const STORAGE_KEY = 'theme';

function storedTheme(): Theme | null {
    const value = localStorage.getItem(STORAGE_KEY);
    return value === 'light' || value === 'dark' ? value : null;
}

export const useTheme = () => {
    const { colorScheme, webApp } = useTelegram();
    const [theme, setThemeState] = useState<Theme>(() => storedTheme() ?? 'light');
    const [followsTelegram, setFollowsTelegram] = useState(() => storedTheme() === null);

    // Пока человек не выбрал тему сам, следуем за Telegram — в том числе когда
    // он переключает оформление мессенджера при открытом приложении
    useEffect(() => {
        if (followsTelegram && colorScheme) {
            setThemeState(colorScheme);
        }
    }, [colorScheme, followsTelegram]);

    useEffect(() => {
        document.documentElement.setAttribute('data-theme', theme);
    }, [theme]);

    // Цвета самого клиента Telegram. Применяются только пока тема не
    // переопределена вручную: иначе переключатель в приложении выглядел бы
    // сломанным — инлайновые переменные перебивают правила [data-theme].
    useEffect(() => {
        if (!webApp) return;

        if (!followsTelegram) {
            clearTelegramTheme();
            return;
        }

        applyTelegramTheme(webApp.themeParams);

        const onThemeChanged = () => {
            applyTelegramTheme(webApp.themeParams);
            if (webApp.colorScheme) setThemeState(webApp.colorScheme);
        };

        webApp.onEvent('themeChanged', onThemeChanged);
        return () => webApp.offEvent('themeChanged', onThemeChanged);
    }, [webApp, followsTelegram]);

    const setTheme = (next: Theme) => {
        setThemeState(next);
        setFollowsTelegram(false);
        localStorage.setItem(STORAGE_KEY, next);
    };

    const toggleTheme = () => setTheme(theme === 'light' ? 'dark' : 'light');

    /** Вернуться к оформлению Telegram — отменяет ручной выбор. */
    const followTelegram = () => {
        localStorage.removeItem(STORAGE_KEY);
        setFollowsTelegram(true);
        if (colorScheme) setThemeState(colorScheme);
    };

    return {
        theme,
        setTheme,
        toggleTheme,
        followTelegram,
        followsTelegram,
        isDark: theme === 'dark',
    };
};
