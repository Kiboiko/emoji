import { useEffect } from 'react';
import { useTelegram } from './useTelegram';
import { applyTelegramTheme, clearTelegramTheme } from '@/lib/telegramTheme';
import { useThemeStore } from '@/store/themeStore';

/**
 * Применяет тему к документу и отдаёт управление ею.
 *
 * Хук обязан быть смонтирован всегда — его вызывает App. Раньше он висел на
 * шапке каталога, а после её переработки остался только в настройках
 * профиля: на всех остальных экранах тему не применял никто. Пока человек
 * ходил по приложению внутри роутера, атрибут data-theme, выставленный при
 * заходе в профиль, сохранялся, — но любая полная перезагрузка страницы
 * (например, по обычной ссылке <a href>) открывала приложение светлым.
 *
 * Состояние лежит в общем сторе, поэтому второй вызов из настроек профиля
 * не заводит свою копию темы, а работает с той же.
 */
export const useTheme = () => {
    const { colorScheme, webApp } = useTelegram();
    const theme = useThemeStore((s) => s.theme);
    const followsTelegram = useThemeStore((s) => s.followsTelegram);
    const setTheme = useThemeStore((s) => s.setTheme);
    const adoptTelegram = useThemeStore((s) => s.adoptTelegram);
    const followTelegramRaw = useThemeStore((s) => s.followTelegram);

    // Пока человек не выбрал тему сам, следуем за Telegram — в том числе
    // когда он переключает оформление мессенджера при открытом приложении
    useEffect(() => {
        if (followsTelegram && colorScheme) adoptTelegram(colorScheme);
    }, [colorScheme, followsTelegram, adoptTelegram]);

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
            if (webApp.colorScheme) adoptTelegram(webApp.colorScheme);
        };

        webApp.onEvent('themeChanged', onThemeChanged);
        return () => webApp.offEvent('themeChanged', onThemeChanged);
    }, [webApp, followsTelegram, adoptTelegram]);

    /** Вернуться к оформлению Telegram — отменяет ручной выбор. */
    const followTelegram = () => followTelegramRaw(colorScheme ?? null);

    return {
        theme,
        setTheme,
        followTelegram,
        followsTelegram,
        isDark: theme === 'dark',
    };
};
