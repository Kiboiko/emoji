import React, { useEffect } from 'react';
import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom';
import { AnimatePresence, motion } from 'framer-motion';
import { useTelegram } from './hooks/useTelegram';
import { useTheme } from './hooks/useTheme';
import { useWebSocket } from './hooks/useWebSocket';
import { useAuthStore } from './store/authStore';
import { useCartStore } from './store/cartStore';
import { authApi } from './api/client';
import { BottomNav } from './components/BottomNav/BottomNav';
import { ToastHost } from './components/Toast/Toast';
import { Home } from './pages/Home/Home';
import { Cart } from './pages/Cart/Cart';
import { Checkout } from './pages/Checkout/Checkout';
import { ProductDetails } from './pages/ProductDetails/ProductDetails';
import { Profile } from './pages/Profile/Profile';
import { Store } from './pages/Store/Store';
import { TermsPage } from './pages/Terms/TermsPage';
import {
    MyListingsPage, MyChannelsPage, MyOrdersPage, MyDealsPage, MySubscriptionsPage,
} from './pages/Cabinet/CabinetRoutes';

// Dev-вход без Telegram. Включается только на локальной сборке
// (VITE_DEV_AUTH=true) и дополнительно требует DEBUG=true на бэкенде.
const DEV_AUTH_ENABLED = import.meta.env.VITE_DEV_AUTH === 'true';

// Отдельной страницы заказов не было — только заглушка «Coming Soon».
// Редирект вместо неё: по ссылке из старой переписки или закладки человек
// попадает туда, где заказы действительно есть.
const Orders = () => <Navigate to="/my/orders" replace />;

export const App: React.FC = () => {
    const { initData, startParam, isReady } = useTelegram();
    // Тема применяется здесь, на корне: это свойство документа, а не
    // отдельного экрана. Раньше хук висел на шапке каталога, после её
    // переработки остался только в настройках профиля — и приложение
    // открывалось светлым везде, куда заходили в обход профиля.
    useTheme();
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

            // Вертикальный свайп по странице Telegram принимает за попытку
            // утянуть окно Mini App вниз, и вместе с прокруткой уезжала вся
            // страница. Метод появился в Bot API 7.7 — на клиентах постарше
            // его просто нет, поэтому проверяем.
            if (typeof tg.disableVerticalSwipes === 'function') {
                tg.disableVerticalSwipes();
            } else {
                // До Bot API 7.7 официального способа нет. Убираем прокрутку
                // у самого документа и переносим её внутрь #root: жест тогда
                // не доходит до Telegram и окно не едет.
                document.documentElement.classList.add('tg-inner-scroll');
            }

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

            // Полноэкранный режим кладёт страницу под системные кнопки
            // Android и под «шторку» iPhone, а env(safe-area-inset-bottom) в
            // этом WebView равен нулю — нижнее меню оказывалось прямо под
            // кнопками системы, и подписи читались сквозь них.
            //
            // Настоящие отступы Telegram сообщает сам, начиная с Bot API 8.0.
            // Переопределяем ими --safe-area-bottom: его уже используют и
            // меню, и панель покупки, и запас в конце списков.
            const applySafeArea = () => {
                const bottom = Math.max(
                    tg.safeAreaInset?.bottom ?? 0,
                    tg.contentSafeAreaInset?.bottom ?? 0,
                );
                if (bottom > 0) {
                    document.documentElement.style.setProperty(
                        '--safe-area-bottom', `${bottom}px`,
                    );
                }
            };
            applySafeArea();
            if (typeof tg.onEvent === 'function') {
                tg.onEvent('safeAreaChanged', applySafeArea);
                tg.onEvent('contentSafeAreaChanged', applySafeArea);
                tg.onEvent('viewportChanged', applySafeArea);
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
            <div className="boot-screen">
                <div className="skeleton boot-placeholder" />
            </div>
        );
    }

    if (!initData && !DEV_AUTH_ENABLED) {
        // Цвета брались жёстко белым по тёмному: в тёмной теме этот экран
        // вспыхивал белым прямоугольником поверх тёмного Telegram
        return (
            <div className="boot-screen boot-screen-message">
                <div className="boot-title">Откройте через Telegram</div>
                <div className="boot-text">
                    Это приложение работает только внутри Telegram.
                    Откройте бота и нажмите кнопку запуска.
                </div>
            </div>
        );
    }

    return (
        <BrowserRouter>
            <div className="app relative">
                <AppContent />
                <NavigationWrapper />
                <ToastHost />
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

                {/* Витрина магазина. kind в адресе, а не два разных маршрута:
                    страница одна, разница только в источнике данных */}
                <Route path="/store/:kind/:id" element={
                    <PageTransition>
                        <Store />
                    </PageTransition>
                } />

                {/* Разделы кабинета на своих экранах: в одном свитке при
                    десятке товаров и подписок всё превращалось в мелкую кашу */}
                <Route path="/my/listings" element={
                    <PageTransition>
                        <MyListingsPage />
                    </PageTransition>
                } />
                <Route path="/my/channels" element={
                    <PageTransition>
                        <MyChannelsPage />
                    </PageTransition>
                } />
                <Route path="/my/orders" element={
                    <PageTransition>
                        <MyOrdersPage />
                    </PageTransition>
                } />
                <Route path="/my/deals" element={
                    <PageTransition>
                        <MyDealsPage />
                    </PageTransition>
                } />
                <Route path="/my/subscriptions" element={
                    <PageTransition>
                        <MySubscriptionsPage />
                    </PageTransition>
                } />

                {/* Условия площадки отдельным экраном: документ на
                    несколько страниц не помещался в раскрывающийся блок
                    внутри формы оформления заказа */}
                <Route path="/terms" element={
                    <PageTransition>
                        <TermsPage />
                    </PageTransition>
                } />

                <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
        </AnimatePresence>
    );
};

/**
 * Появление экрана.
 *
 * После анимации inline-стили снимаются, и это не украшательство. Элемент с
 * трансформом живёт в собственном слое композитора, а слой выше предела
 * текстуры (у большинства Android это 4096px) растрируется не целиком:
 * на длинных экранах — в списке объявлений, в заказах — часть карточек
 * занимала своё место, но оставалась незакрашенной. Пустой прямоугольник
 * вместо товара, и при прокрутке пустым оказывался уже другой.
 *
 * Снятый трансформ возвращает страницу в общий слой страницы, который
 * рисуется кусками по мере прокрутки и в предел не упирается.
 */
const PageTransition: React.FC<{ children: React.ReactNode }> = ({ children }) => {
    const ref = React.useRef<HTMLDivElement>(null);

    return (
        <motion.div
            ref={ref}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
            transition={{ duration: 0.2, ease: "easeOut" }}
            className="page-transition"
            onAnimationComplete={() => {
                const el = ref.current;
                if (!el) return;
                // Пустая строка убирает свойство целиком, а не ставит
                // «none»: none тоже создаёт слой на части движков
                el.style.transform = '';
                el.style.willChange = '';
                el.style.opacity = '';
            }}
        >
            {children}
        </motion.div>
    );
};

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
                        className="product-overlay"
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
