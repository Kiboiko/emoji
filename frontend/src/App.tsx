import React, { useEffect } from 'react';
import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom';
import { AnimatePresence, motion } from 'framer-motion';
import { useTelegram } from './hooks/useTelegram';
import { useWebSocket } from './hooks/useWebSocket';
import { useAuthStore } from './store/authStore';
import { useCartStore } from './store/cartStore';
import { authApi } from './api/client';
import { BottomNav } from './components/BottomNav/BottomNav';
import { Home } from './pages/Home/Home';
import { Cart } from './pages/Cart/Cart';
import { Checkout } from './pages/Checkout/Checkout';
import { ProductDetails } from './pages/ProductDetails/ProductDetails';
import { Profile } from './pages/Profile/Profile';

// Dev-вход без Telegram. Включается только на локальной сборке
// (VITE_DEV_AUTH=true) и дополнительно требует DEBUG=true на бэкенде.
const DEV_AUTH_ENABLED = import.meta.env.VITE_DEV_AUTH === 'true';

// Placeholder components for other pages
// История заказов живёт в профиле, а отдельная страница так и осталась
// заглушкой «Coming Soon». Редирект вместо неё: по ссылке из старой переписки
// или закладки человек попадает туда, где заказы действительно есть.
const Orders = () => <Navigate to="/profile" replace />;

export const App: React.FC = () => {
    const { initData, startParam, isReady } = useTelegram();
    const { setUser, setAccessToken, isAuthenticated } = useAuthStore();
    const [isAuthenticating, setIsAuthenticating] = React.useState(true);

    // Initialize WebSocket
    useWebSocket();

    useEffect(() => {
        if (isReady && !isAuthenticated) {
            authenticate();
        } else if (isReady && isAuthenticated) {
            // Already authenticated (restored from storage), load data
            useCartStore.getState().fetchCart();
            setIsAuthenticating(false);
        } else {
            setIsAuthenticating(false);
        }
    }, [isReady]);


    // Initialize Telegram WebApp - ALWAYS fullscreen on mobile
    useEffect(() => {
        const tg = (window as any).Telegram?.WebApp;
        if (tg) {
            console.log('[Telegram] Version:', tg.version, 'Platform:', tg.platform);

            // Set platform attribute for CSS
            document.documentElement.setAttribute('data-platform', tg.platform || 'unknown');

            // Always expand to use full available height
            tg.expand();

            // Force fullscreen ONLY on mobile platforms (iOS/Android)
            // This works regardless of BotFather fullscreen setting
            const isMobile = tg.platform === 'ios' || tg.platform === 'android';

            if (isMobile && typeof tg.requestFullscreen === 'function') {
                console.log('[Telegram] Requesting fullscreen for mobile platform');
                try {
                    tg.requestFullscreen();
                } catch (e) {
                    console.error('[Telegram] Fullscreen request failed:', e);
                }
            } else if (isMobile) {
                console.warn('[Telegram] requestFullscreen() not available (SDK version too old?)');
            } else {
                console.log('[Telegram] Desktop platform detected, skipping fullscreen');
            }

            // Set theme colors
            if (tg.setHeaderColor) tg.setHeaderColor('bg_color');
            if (tg.setBackgroundColor) tg.setBackgroundColor('bg_color');
        }
    }, []);



    const authenticate = async () => {
        try {
            if (!initData) {
                // Локальная разработка: без Telegram initData витрину иначе
                // вообще не открыть в браузере. Закрыто ДВУМЯ независимыми
                // флагами — VITE_DEV_AUTH на сборке фронта и DEBUG на бэкенде
                // (при DEBUG=false эндпоинта /api/auth/dev не существует).
                // В production не включается ни один из них.
                if (DEV_AUTH_ENABLED) {
                    console.warn('[DEV] initData нет — вход через /api/auth/dev');
                    const response = await authApi.authenticateDev();
                    setAccessToken(response.access_token);
                    setUser(response.user);
                    useCartStore.getState().fetchCart();
                    setIsAuthenticating(false);
                    return;
                }

                console.warn('No Telegram initData available');
                setIsAuthenticating(false);
                return;
            }

            // Extract referral code from start param
            const referralCode = startParam?.startsWith('ref_')
                ? startParam.replace('ref_', '')
                : undefined;

            const response = await authApi.authenticateTelegram(initData, referralCode);

            setAccessToken(response.access_token);
            setUser(response.user);

            // Sync cart with server immediately
            useCartStore.getState().fetchCart();

        } catch (error: any) {
            console.error('Authentication failed:', error);
        } finally {
            setIsAuthenticating(false);
        }
    };

    if (isAuthenticating) {
        return (
            <div style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                minHeight: '100vh',
                background: 'var(--tg-theme-bg-color, #fff)'
            }}>
                <div className="shimmer" style={{
                    width: '200px',
                    height: '200px',
                    borderRadius: '20px',
                }} />
            </div>
        );
    }

    if (!initData && !DEV_AUTH_ENABLED) {
        return (
            <div style={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                height: '100vh',
                backgroundColor: '#ffffff',
                color: '#1a1a1a',
                padding: '20px',
                textAlign: 'center'
            }}>
                <div style={{ fontSize: '20px', fontWeight: 'bold', marginBottom: '8px' }}>
                    Откройте через Telegram
                </div>
                <div style={{ fontSize: '14px', color: '#6c757d', maxWidth: '300px' }}>
                    Это приложение работает только внутри Telegram. Откройте бота и нажмите кнопку запуска.
                </div>
            </div>
        );
    }

    return (
        <BrowserRouter>
            <div className="app relative">
                <AppContent />
                <NavigationWrapper />
            </div>
        </BrowserRouter>
    );
};

const AppContent: React.FC = () => {
    const location = useLocation();

    return (
        <AnimatePresence mode="wait">
            <Routes location={location} key={location.pathname}>
                <Route path="/" element={
                    <PageTransition>
                        <HomeWithProductOverlay />
                    </PageTransition>
                } />
                <Route path="/product/:id" element={
                    <PageTransition>
                        <HomeWithProductOverlay />
                    </PageTransition>
                } />
                <Route path="/cart" element={
                    <PageTransition>
                        <Cart />
                    </PageTransition>
                } />
                <Route path="/checkout" element={
                    <PageTransition>
                        <Checkout />
                    </PageTransition>
                } />
                <Route path="/orders" element={
                    <PageTransition>
                        <Orders />
                    </PageTransition>
                } />
                <Route path="/profile" element={
                    <PageTransition>
                        <Profile />
                    </PageTransition>
                } />
                <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
        </AnimatePresence>
    );
};

const PageTransition: React.FC<{ children: React.ReactNode }> = ({ children }) => (
    <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: -10 }}
        transition={{ duration: 0.2, ease: "easeOut" }}
        style={{ width: '100%', height: '100%' }}
    >
        {children}
    </motion.div>
);

const HomeWithProductOverlay: React.FC = () => {
    const location = useLocation();
    const isProductPage = location.pathname.startsWith('/product/');

    return (
        <>
            <Home />
            <AnimatePresence>
                {isProductPage && (
                    <motion.div
                        key="product-details-overlay"
                        initial={{ x: '100%' }}
                        animate={{ x: 0 }}
                        exit={{ x: '100%' }}
                        transition={{ type: 'spring', damping: 25, stiffness: 200 }}
                        style={{
                            position: 'fixed',
                            top: 0,
                            left: 0,
                            right: 0,
                            bottom: 0,
                            zIndex: 1100,
                            background: 'var(--bg-primary)'
                        }}
                    >
                        <ProductDetails />
                    </motion.div>
                )}
            </AnimatePresence>
        </>
    );
};

const NavigationWrapper: React.FC = () => {
    const location = useLocation();
    const isProductPage = location.pathname.startsWith('/product/');

    if (isProductPage) return null;

    return <BottomNav />;
};
