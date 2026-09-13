import { useEffect, useState } from 'react';

interface TelegramWebApp {
    initData: string;
    version: string;
    initDataUnsafe: {
        user?: {
            id: number;
            first_name: string;
            last_name?: string;
            username?: string;
            language_code?: string;
        };
        start_param?: string;
    };
    colorScheme: 'light' | 'dark';
    themeParams: {
        bg_color?: string;
        text_color?: string;
        hint_color?: string;
        link_color?: string;
        button_color?: string;
        button_text_color?: string;
    };
    isExpanded: boolean;
    viewportHeight: number;
    viewportStableHeight: number;
    MainButton: {
        text: string;
        color: string;
        textColor: string;
        isVisible: boolean;
        isActive: boolean;
        isProgressVisible: boolean;
        setText: (text: string) => void;
        onClick: (callback: () => void) => void;
        offClick: (callback: () => void) => void;
        show: () => void;
        hide: () => void;
        enable: () => void;
        disable: () => void;
        showProgress: (leaveActive?: boolean) => void;
        hideProgress: () => void;
    };
    BackButton: {
        isVisible: boolean;
        onClick: (callback: () => void) => void;
        offClick: (callback: () => void) => void;
        show: () => void;
        hide: () => void;
    };
    HapticFeedback: {
        impactOccurred: (style: 'light' | 'medium' | 'heavy' | 'rigid' | 'soft') => void;
        notificationOccurred: (type: 'error' | 'success' | 'warning') => void;
        selectionChanged: () => void;
    };
    ready: () => void;
    expand: () => void;
    close: () => void;
    onEvent: (eventType: string, callback: () => void) => void;
    offEvent: (eventType: string, callback: () => void) => void;
}

declare global {
    interface Window {
        Telegram?: {
            WebApp: TelegramWebApp;
        };
    }
}

// Mock WebApp for browser development
const mockWebApp: TelegramWebApp = {
    initData: '',
    version: '7.0',
    initDataUnsafe: {},
    colorScheme: 'light',
    themeParams: {},
    isExpanded: true,
    viewportHeight: 800,
    viewportStableHeight: 800,
    MainButton: {
        text: '',
        color: '',
        textColor: '',
        isVisible: false,
        isActive: false,
        isProgressVisible: false,
        setText: () => { },
        onClick: () => { },
        offClick: () => { },
        show: () => { },
        hide: () => { },
        enable: () => { },
        disable: () => { },
        showProgress: () => { },
        hideProgress: () => { },
    },
    BackButton: {
        isVisible: false,
        onClick: () => { },
        offClick: () => { },
        show: () => { },
        hide: () => { },
    },
    HapticFeedback: {
        impactOccurred: (style) => console.log(`[Mock] Haptic impact: ${style}`),
        notificationOccurred: (type) => console.log(`[Mock] Haptic notification: ${type}`),
        selectionChanged: () => console.log('[Mock] Haptic selection'),
    },
    ready: () => { },
    expand: () => { },
    close: () => { },
    onEvent: () => { },
    offEvent: () => { },
};

// Try to extract tgWebAppData from URL hash (Telegram Web passes data this way)
function getInitDataFromHash(): string {
    try {
        const hash = window.location.hash.slice(1);
        const params = new URLSearchParams(hash);
        return params.get('tgWebAppData') || '';
    } catch {
        return '';
    }
}

export const useTelegram = () => {
    const [webApp, setWebApp] = useState<TelegramWebApp | null>(null);
    const [user, setUser] = useState<TelegramWebApp['initDataUnsafe']['user'] | null>(null);
    const [startParam, setStartParam] = useState<string | null>(null);
    const [isReady, setIsReady] = useState(false);

    useEffect(() => {
        const initTelegram = (attempt = 0) => {
            const tg = window.Telegram?.WebApp;

            if (tg) {
                tg.ready();
                tg.expand();

                // If SDK exists but initData is empty, retry a few times
                // (Telegram Web may populate it asynchronously)
                if (!tg.initData && attempt < 10) {
                    console.log(`[Telegram] initData empty, retry ${attempt + 1}/10`);
                    setTimeout(() => initTelegram(attempt + 1), 100);
                    return;
                }

                // Fallback: try to get initData from URL hash
                if (!tg.initData) {
                    const hashData = getInitDataFromHash();
                    if (hashData) {
                        console.log('[Telegram] Got initData from URL hash');
                        (tg as any).initData = hashData;
                    }
                }

                setWebApp(tg);
                setUser(tg.initDataUnsafe.user || null);

                // Try to get start_param from initDataUnsafe first
                let param: string | null = tg.initDataUnsafe.start_param || null;

                // If not available, try to extract from URL query string
                if (!param) {
                    const urlParams = new URLSearchParams(window.location.search);
                    param = urlParams.get('startapp') || urlParams.get('start_param');
                }

                console.log('[Frontend] Extracted start_param:', param);
                console.log('[Frontend] initData length:', tg.initData?.length || 0);
                setStartParam(param);
                setIsReady(true);
            } else {
                // Use mock in browser
                setWebApp(mockWebApp);
                console.log('Telegram WebApp not found, using mock');
                setIsReady(true);
            }
        };

        initTelegram();
    }, []);

    const showMainButton = (text: string, onClick: () => void) => {
        if (webApp) {
            webApp.MainButton.setText(text);
            webApp.MainButton.onClick(onClick);
            webApp.MainButton.show();
        }
    };

    const hideMainButton = () => {
        if (webApp) {
            webApp.MainButton.hide();
        }
    };

    const showBackButton = (onClick: () => void) => {
        if (webApp) {
            webApp.BackButton.onClick(onClick);
            webApp.BackButton.show();
        }
    };

    const hideBackButton = () => {
        if (webApp) {
            webApp.BackButton.hide();
        }
    };

    const haptic = {
        impact: (style: 'light' | 'medium' | 'heavy' = 'medium') => {
            // HapticFeedback available since version 6.1
            if (webApp && webApp.version && parseFloat(webApp.version) >= 6.1) {
                try {
                    webApp.HapticFeedback.impactOccurred(style);
                } catch (e) { /* ignore */ }
            }
        },
        notification: (type: 'error' | 'success' | 'warning') => {
            if (webApp && webApp.version && parseFloat(webApp.version) >= 6.1) {
                try {
                    webApp.HapticFeedback.notificationOccurred(type);
                } catch (e) { /* ignore */ }
            }
        },
        selection: () => {
            if (webApp && webApp.version && parseFloat(webApp.version) >= 6.1) {
                try {
                    webApp.HapticFeedback.selectionChanged();
                } catch (e) { /* ignore */ }
            }
        }
    };

    const close = () => {
        webApp?.close();
    };

    return {
        webApp,
        user,
        startParam,
        colorScheme: webApp?.colorScheme || 'light',
        initData: webApp?.initData || '',
        showMainButton,
        hideMainButton,
        showBackButton,
        hideBackButton,
        haptic,
        close,
        isReady
    };
};
