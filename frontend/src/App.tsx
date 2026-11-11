import { Rankings, Giveaways } from "./pages/Growth/Growth";
import { StartLinkGate } from './components/StartLinkGate/StartLinkGate';
import { StartupScreen, StartupRouteReady } from './components/StartupScreen/StartupScreen';
import { markStartup, finishStartupData, failStartup } from './store/startupStore';
import { SalesFeed } from './pages/SalesFeed/SalesFeed';
import { SubscriptionEditor } from './pages/SubscriptionEditor/SubscriptionEditor';
import { InquiryChat } from './pages/InquiryChat/InquiryChat';
import { startInquiries, useInquiryStore } from './store/inquiryStore';
import React, { useEffect } from 'react';
import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom';
import { AnimatePresence, motion } from 'framer-motion';
import { useTelegram } from './hooks/useTelegram';
import { useTheme } from './hooks/useTheme';
import { useWebSocket } from './hooks/useWebSocket';
import { useAuthStore } from './store/authStore';
import { useCartStore } from './store/cartStore';
import { useToastStore } from './store/toastStore';
import { startDeals } from './store/dealsStore';
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
import { DealChat } from './pages/DealChat/DealChat';
import {
    ChatsPage, MyListingsPage, MyChannelsPage, MyDealsPage, MySubscriptionsPage,
} from './pages/Cabinet/CabinetRoutes';
import { DealPage } from './pages/DealPage/DealPage';
import { OrderPage } from './pages/DealPage/OrderPage';
import { ListingEditor } from './pages/ListingEditor/ListingEditor';

// Dev-вход без Telegram. Включается только на локальной сборке
// (VITE_DEV_AUTH=true) и дополнительно требует DEBUG=true на бэкенде.
const DEV_AUTH_ENABLED = import.meta.env.VITE_DEV_AUTH === 'true';

// «Мои заказы» влились в «Мои сделки»: там и покупки у площадки, и сделки
// с продавцами. Старые ссылки и закладки ведут туда же.
const Orders = () => <Navigate to="/my/deals" replace />;

export const App: React.FC = () => {
    const { initData, startParam, isReady } = useTelegram();
    // Тема применяется здесь, на корне: это свойство документа, а не
    // отдельного экрана. Раньше хук висел на шапке каталога, после её
    // переработки остался только в настройках профиля — и приложение
    // открывалось светлым везде, куда заходили в обход профиля.
    useTheme();
    const { setUser, setAccessToken, isAuthenticated, accessToken } = useAuthStore();
    const [isAuthenticating, setIsAuthenticating] = React.useState(true);

    // Initialize WebSocket
    useWebSocket();

    // Непрочитанное по сделкам нужно с первого экрана: значок на «Профиле»
    // в нижнем меню, а не только внутри списка сделок
    useEffect(() => {
        if (accessToken) startDeals();
    }, [accessToken]);
    useEffect(() => {
        if (!accessToken) { useInquiryStore.setState({ rows: [] }); return; }
        return startInquiries();
    }, [accessToken]);

    useEffect(() => {
        // Кабинет не должен запрашивать профиль старым токеном, пока SDK
        // готовит initData и идёт новый вход. Иначе 401 выглядит как отсутствие
        // магазина, а запоздавший ответ может сбросить уже новую сессию.
        if (!isReady) return;
        markStartup('telegram');
        if (!isAuthenticated) {
            setIsAuthenticating(true);
            authenticate();
        } else {
            markStartup('auth');
            // Already authenticated (restored from storage), load data
            useCartStore.getState().fetchCart();
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
                // Только safeAreaInset — реальный отступ устройства (жест-бар
                // Android, полоса Home на iPhone). contentSafeAreaInset — про
                // элементы интерфейса самого Telegram (шапку с «Закрыть» и
                // «⋮» сверху), а не про системные кнопки; на части версий
                // клиента снизу это давало на глаз лишний, вложенный запас, и
                // Math.max выбирал именно его вместо реального отступа.
                let bottom = tg.safeAreaInset?.bottom ?? 0;

                // Трёхкнопочная панель Android в полноэкранном режиме
                // спрятана: она выезжает поверх приложения только по свайпу
                // от края и через пару секунд уходит сама. Telegram при этом
                // всё равно сообщает её полную высоту (~48px), и резерв под
                // невидимую панель оставлял под меню пустую полосу.
                // Жестовая полоска тоньше (16–24px) и видна всегда — под неё
                // место оставляем. Порог между ними с запасом в обе стороны.
                if (tg.platform === 'android' && bottom > 32) {
                    bottom = 0;
                }

                const root = document.documentElement;

                // Сверху — строка состояния (safeAreaInset) плюс плавающие
                // кнопки Telegram «Закрыть» и «⌄ ⋮» (contentSafeAreaInset).
                //
                // Раньше точную сумму брал только чат сделки, а остальные
                // экраны — оценку из index.css: 48px плюс системный отступ.
                // На iPhone системный отступ в WebView равен нулю, хотя окно
                // начинается под самой чёлкой, и оценке не хватало целой
                // строки состояния: заголовок, поиск и стрелка «Назад»
                // уходили под кнопки Telegram, и нажать «Назад» было нельзя.
                // Теперь сумма от Telegram заменяет оценку везде; оценка
                // остаётся только на клиентах, которые отступов не сообщают.
                const top = (tg.safeAreaInset?.top ?? 0) + (tg.contentSafeAreaInset?.top ?? 0);
                if (top > 0) {
                    root.style.setProperty('--tg-content-top', `${top}px`);
                    // body уже сдвинут на env(safe-area-inset-top) — эту часть
                    // не считаем второй раз
                    const bodyTop = parseFloat(getComputedStyle(document.body).paddingTop) || 0;
                    root.style.setProperty('--tg-chrome-top', `${Math.max(0, top - bodyTop)}px`);
                } else {
                    root.style.removeProperty('--tg-content-top');
                    root.style.removeProperty('--tg-chrome-top');
                }

                if (bottom > 0) {
                    root.style.setProperty('--safe-area-bottom', `${bottom}px`);
                } else {
                    // Ноль не записываем, а снимаем своё значение: тогда
                    // решает env(safe-area-inset-bottom), который верен там,
                    // где браузер знает отступ сам. И заодно не остаётся
                    // устаревшее число от прошлого события — при повороте
                    // экрана отступ меняется.
                    root.style.removeProperty('--safe-area-bottom');
                }
            };
            applySafeArea();
            if (typeof tg.onEvent === 'function') {
                tg.onEvent('safeAreaChanged', applySafeArea);
                tg.onEvent('contentSafeAreaChanged', applySafeArea);
                tg.onEvent('viewportChanged', applySafeArea);
                tg.onEvent('fullscreenChanged', applySafeArea);
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
                    markStartup('auth');
                    useCartStore.getState().fetchCart();
                    setIsAuthenticating(false);
                    return;
                }

                console.warn('No Telegram initData available');
                markStartup('auth');
                finishStartupData();
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
            markStartup('auth');

            // Sync cart with server immediately
            useCartStore.getState().fetchCart();

        } catch (error: any) {
            console.warn('Telegram sign-in failed', { status: error?.response?.status, code: error?.code });
            // Раньше неудачный вход молчал: приложение открывалось «гостем», а
            // человек видел невнятные ошибки в разных местах (например, при
            // регистрации магазина) и не понимал, что дело во входе.
            const ru = useAuthStore.getState().language === 'ru';
            const status = error?.response?.status;
            const detail = error?.response?.data?.detail;
            const text = status === 403 && typeof detail === 'string'
                ? detail
                : !error?.response
                    ? (ru ? 'Нет связи с сервером. Откройте приложение заново.'
                        : 'No connection. Reopen the app.')
                    : (ru ? 'Не удалось войти через Telegram. Откройте приложение заново.'
                        : 'Sign-in failed. Reopen the app.');
            useToastStore.getState().show(text, 'error');
            failStartup(text, () => { setIsAuthenticating(true); void authenticate(); });
        } finally {
            setIsAuthenticating(false);
        }
    };

    if (!isAuthenticating && !initData && !DEV_AUTH_ENABLED) {
        // Цвета брались жёстко белым по тёмному: в тёмной теме этот экран
        // вспыхивал белым прямоугольником поверх тёмного Telegram
        return (
            <><StartupScreen /><div className="boot-screen boot-screen-message">
                <div className="boot-title">Откройте через Telegram</div>
                <div className="boot-text">
                    Это приложение работает только внутри Telegram.
                    Откройте бота и нажмите кнопку запуска.
                </div>
            </div></>
        );
    }

    return (
        <><StartupScreen />{!isAuthenticating && <BrowserRouter>
            <div className="app relative">
                <StartLinkGate startParam={startParam}>
                    <StartupRouteReady />
                    <AppContent />
                    <NavigationWrapper />
                </StartLinkGate>
                <ToastHost />
            </div>
        </BrowserRouter>}</>
    );
};

const AppContent: React.FC = () => {
    const location = useLocation();

    // Ключ экрана. Карточка товара открывается поверх каталога, поэтому
    // у «/» и «/product/:id» он общий: раньше смена адреса пересоздавала
    // каталог под карточкой — он заново грузился, показывал заглушки и
    // мигал и при открытии товара, и при возврате
    const screenKey = location.pathname.startsWith('/product/') ? '/'
        : location.pathname.startsWith('/chats/seller/') ? '/chats/seller'
        : location.pathname;

    return (
        <>
            <Routes location={location} key={screenKey}>
                <Route path="/rankings" element={<PageTransition><Rankings /></PageTransition>} />
                <Route path="/giveaways" element={<PageTransition><Giveaways /></PageTransition>} />
                <Route path="/giveaways/:id" element={<PageTransition><Giveaways /></PageTransition>} />
                <Route path="/sales" element={<PageTransition><SalesFeed /></PageTransition>} />
                <Route path="/my/channels/new" element={<PageTransition><SubscriptionEditor /></PageTransition>} />
                <Route path="/my/channels/:channelId" element={<PageTransition><SubscriptionEditor /></PageTransition>} />
                <Route path="/chats/seller/:id" element={<PageTransition><InquiryChat /></PageTransition>} />
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
                {/* Вкладка «Чаты» нижнего меню — переписки по сделкам */}
                <Route path="/chats" element={
                    <PageTransition>
                        <ChatsPage />
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
                <Route path="/my/orders" element={<Orders />} />
                {/* Новое объявление и правка существующего — отдельным экраном */}
                <Route path="/my/listings/:listingId" element={
                    <PageTransition>
                        <ListingEditor />
                    </PageTransition>
                } />
                {/* Страница сделки и покупки у площадки — из «Мои сделки» */}
                <Route path="/my/deal/:dealId" element={
                    <PageTransition>
                        <DealPage />
                    </PageTransition>
                } />
                <Route path="/my/purchase/:orderId/:itemId" element={
                    <PageTransition>
                        <OrderPage />
                    </PageTransition>
                } />
                <Route path="/my/deals" element={
                    <PageTransition>
                        <MyDealsPage />
                    </PageTransition>
                } />
                {/* Переписка по сделке — во весь экран, без нижнего меню.
                    Сюда же ведёт кнопка «Открыть чат» из уведомления бота */}
                <Route path="/my/deals/:dealId" element={
                    <PageTransition>
                        <DealChat />
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
        </>
    );
};

/**
 * Обёртка экрана.
 *
 * Здесь была анимация смены экранов: старый экран 0,2 с гас, и только
 * потом 0,2 с проявлялся новый (AnimatePresence mode="wait"). На каждое
 * нажатие в нижнем меню — почти полсекунды пустоты и двойное мерцание, а
 * на длинных экранах слой с анимацией ещё и не дорисовывался. Вкладки в
 * приложениях переключаются мгновенно — так теперь и здесь.
 */
const PageTransition: React.FC<{ children: React.ReactNode }> = ({ children }) => (
    <div className="page-transition">{children}</div>
);

const HomeWithProductOverlay: React.FC = () => {
    const location = useLocation();
    const isProductPage = location.pathname.startsWith('/product/');
    const [hasCatalog, setHasCatalog] = React.useState(!isProductPage);
    useEffect(() => {
        if (!isProductPage) setHasCatalog(true);
    }, [isProductPage]);

    return (
        <>
            {(!isProductPage || hasCatalog) && <Home />}
            <AnimatePresence>
                {isProductPage && (
                    <motion.div
                        key="product-details-overlay"
                        initial={hasCatalog ? { x: '100%' } : false}
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
    // В чате сделки снизу поле ввода, на странице сделки и в правке
    // объявления — своя панель действий: меню там только мешало бы
    const ownBottomBar = ['/my/deals/', '/my/deal/', '/my/listings/', '/chats/seller/']
        .some((prefix) => location.pathname.startsWith(prefix));

    if (isProductPage || ownBottomBar) return null;

    return <BottomNav />;
};
