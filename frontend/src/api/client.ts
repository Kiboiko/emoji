import axios from 'axios';
import { useAuthStore } from '@/store/authStore';
import type { AuthorChannel, ChannelStatus, ProfileSummary, Store, StoreCard } from '@/types';

const API_BASE_URL = import.meta.env.VITE_API_URL || '/api';

export const apiClient = axios.create({
    baseURL: API_BASE_URL,
    headers: {
        'Content-Type': 'application/json',
    },
});

// Request interceptor to add auth token
apiClient.interceptors.request.use(
    (config) => {
        const token = localStorage.getItem('access_token');
        if (token) {
            config.headers.Authorization = `Bearer ${token}`;
        }
        return config;
    },
    (error) => Promise.reject(error)
);

// Адреса самого входа. Их 401 означает «войти не вышло», а не «токен
// протух» — разница важная, см. ниже.
const LOGIN_PATHS = ['/auth/telegram', '/auth/dev'];

// Response interceptor for error handling
apiClient.interceptors.response.use(
    (response) => response,
    (error) => {
        const url: string = error.config?.url ?? '';
        const isLogin = LOGIN_PATHS.some((path) => url.includes(path));

        if (error.response?.status === 401 && !isLogin) {
            // Перезагрузку не дёргаем: фоновый запрос заблокированного
            // пользователя уходил бы в бесконечный цикл перезагрузок.
            //
            // Чистим И хранилище, И состояние. Раньше стирался только
            // localStorage, а в хранилище zustand токен оставался: приложение
            // считало себя авторизованным, а заголовок уже никуда не подставлялся.
            useAuthStore.getState().logout();
            localStorage.removeItem('user');
        }

        // А вот при провале самого входа токен НЕ трогаем. Приложение
        // перевходит при каждом открытии, и один неудачный вход уносил с собой
        // рабочий токен с прошлого раза — после чего ломалось всё сразу:
        // и корзина, и профиль.
        return Promise.reject(error);
    }
);

// Auth API
export const authApi = {
    authenticateTelegram: async (initData: string, referralCode?: string) => {
        const response = await apiClient.post('/auth/telegram', null, {
            headers: {
                'X-Telegram-Init-Data': initData,
            },
            params: referralCode ? { referral_code: referralCode } : {},
        });
        return response.data;
    },

    // Только для локальной разработки. На бэкенде роут существует лишь при
    // DEBUG=true, на проде запрос вернёт 404.
    authenticateDev: async () => {
        const response = await apiClient.post('/auth/dev');
        return response.data;
    },

    getCurrentUser: async () => {
        const response = await apiClient.get('/auth/me');
        return response.data;
    },
};

// Products API
export const productsApi = {
    getProducts: async (params?: {
        category_id?: string;
        search?: string;
        is_top?: boolean;
        lang?: string;
        skip?: number;
        limit?: number;
    }) => {
        const queryParams = { limit: 1000, ...params };
        const response = await apiClient.get('/products', { params: queryParams });
        return response.data;
    },

    getProduct: async (id: string, lang: string = 'ru') => {
        const response = await apiClient.get(`/products/${id}`, { params: { lang } });
        return response.data;
    },
};

// Categories API
export const categoriesApi = {
    getCategories: async (lang: string = 'ru') => {
        const response = await apiClient.get('/categories', {
            params: { lang },
        });
        return response.data;
    },
};

// Cart API
export const cartApi = {
    getCart: async (lang: string = 'ru') => {
        const response = await apiClient.get('/cart', {
            params: { lang },
        });
        return response.data;
    },

    addToCart: async (productId: string, quantity: number = 1, userData?: Record<string, any>) => {
        const response = await apiClient.post('/cart', {
            product_id: productId,
            quantity,
            user_data: userData,
        });
        return response.data;
    },

    updateCartItem: async (itemId: string, quantity: number) => {
        const response = await apiClient.put(`/cart/${itemId}`, { quantity });
        return response.data;
    },

    removeFromCart: async (itemId: string) => {
        const response = await apiClient.delete(`/cart/${itemId}`);
        return response.data;
    },

    clearCart: async () => {
        const response = await apiClient.delete('/cart');
        return response.data;
    },
};

// Orders API
export const ordersApi = {
    getOrders: async () => {
        const response = await apiClient.get('/orders');
        return response.data;
    },

    getOrder: async (id: string) => {
        const response = await apiClient.get(`/orders/${id}`);
        return response.data;
    },

    // accept_terms нужен, только если пользователь ещё не принимал текущую
    // редакцию условий: бэкенд ответит 409 с кодом terms_required
    createOrder: async (currency: 'USDT' | 'TON', acceptTerms = false) => {
        const response = await apiClient.post('/orders', {
            currency, accept_terms: acceptTerms,
        });
        return response.data;
    },

    cancelOrder: async (orderId: string) =>
        (await apiClient.post(`/orders/${orderId}/cancel`)).data,
};

// Payments API
export const paymentsApi = {
    // Путь совпадает с бэкендом: /api/payments/check/{id}.
    // Раньше фронт звал именно этот адрес, а роутер был смонтирован на
    // /api/webhook — опрос статуса всегда возвращал 404 и молча не работал.
    checkPaymentStatus: async (orderId: string) => {
        const response = await apiClient.get(`/payments/check/${orderId}`);
        return response.data;
    },

    getConfig: async () => {
        const response = await apiClient.get('/payments/config');
        return response.data;
    },

    // Перевыставить счёт: нужен, когда пользователь вернулся к неоплаченному
    // заказу или истёк зафиксированный курс
    initTonPayment: async (orderId: string) => {
        const response = await apiClient.post(`/payments/ton/init/${orderId}`);
        return response.data;
    },
};

// Reviews API
export const reviewsApi = {
    getReviews: async (productId?: string, skip: number = 0, limit: number = 20) => {
        const response = await apiClient.get('/reviews', {
            params: {
                ...(productId ? { product_id: productId } : {}),
                skip,
                limit
            },
        });
        return response.data;
    },

    createReview: async (data: {
        product_id: string;
        order_id: string;
        text: string;
        rating?: number;
    }) => {
        const response = await apiClient.post('/reviews', data);
        return response.data;
    },

};

// Users API
export const usersApi = {
    getReferralStats: async () => {
        const response = await apiClient.get('/users/referral-stats');
        return response.data;
    },

    // Счётчики разделов кабинета одним запросом: сами списки
    // живут на своих экранах и на главной не нужны
    getSummary: async (): Promise<ProfileSummary> =>
        (await apiClient.get('/users/me/summary')).data,
};

// Витрины магазинов. Площадка — такой же продавец, поэтому отдельного
// метода под неё нет: у неё такой же id, как у остальных.
export const storesApi = {
    // Магазины, у которых есть что купить: строка на главной
    getStores: async (): Promise<StoreCard[]> =>
        (await apiClient.get('/stores')).data,

    getSellerStore: async (id: string, lang = 'ru'): Promise<Store> =>
        (await apiClient.get(`/stores/seller/${id}`, { params: { lang } })).data,

    getChannelStore: async (id: string, lang = 'ru'): Promise<Store> =>
        (await apiClient.get(`/stores/channel/${id}`, { params: { lang } })).data,
};

// Terms API
export const termsApi = {
    get: async () => (await apiClient.get('/terms')).data,
    // Нужно ли показывать галочку: условия принимаются раз на версию,
    // а не перед каждой покупкой
    status: async () => (await apiClient.get('/terms/status')).data,
    accept: async (version: string) =>
        (await apiClient.post('/terms/accept', { version })).data,
};

// P2P API
export const p2pApi = {
    getSellerProfile: async () => (await apiClient.get('/p2p/seller/me')).data,

    registerSeller: async (data: {
        display_name: string; payout_wallet: string; accept_terms: boolean;
    }) => (await apiClient.post('/p2p/seller/register', data)).data,

    updateSeller: async (data: {
        display_name?: string; payout_wallet?: string; description?: string;
    }) => (await apiClient.patch('/p2p/seller/me', data)).data,

    // Логотип магазина. Content-Type снимаем явно — у инстанса он
    // application/json, и без этого multipart не собирается
    uploadSellerAvatar: async (file: File) => {
        const form = new FormData();
        form.append('image', file);
        return (await apiClient.post('/p2p/seller/me/avatar', form, {
            headers: { 'Content-Type': undefined },
        })).data;
    },

    getMyListings: async () => (await apiClient.get('/p2p/seller/listings')).data,

    updateListing: async (listingId: string, data: {
        name?: string; description?: string; price_usd?: string; category_id?: string;
    }) => (await apiClient.patch(`/p2p/seller/listings/${listingId}`, data)).data,

    deleteListing: async (listingId: string) =>
        (await apiClient.delete(`/p2p/seller/listings/${listingId}`)).data,

    deleteListingImage: async (listingId: string, imageId: string) =>
        (await apiClient.delete(`/p2p/seller/listings/${listingId}/images/${imageId}`)).data,

    withdrawListing: async (listingId: string) =>
        (await apiClient.post(`/p2p/seller/listings/${listingId}/withdraw`)).data,

    republishListing: async (listingId: string) =>
        (await apiClient.post(`/p2p/seller/listings/${listingId}/republish`)).data,

    createListing: async (data: {
        name: string; description: string; price_usd: string;
        category_id?: string; accept_terms: boolean;
    }) => (await apiClient.post('/p2p/seller/listings', data)).data,

    uploadListingImage: async (listingId: string, file: File) => {
        const form = new FormData();
        form.append('image', file);
        // Content-Type СНИМАЕМ явно. У инстанса он выставлен в application/json
        // (см. создание apiClient), и без этого JSON-заголовок уезжает вместе
        // с multipart-телом: браузер не добавляет boundary, FastAPI не может
        // разобрать тело и отвечает 422 «поле image отсутствует».
        // Загрузка фото из интерфейса не работала из-за этого вообще никогда.
        return (await apiClient.post(`/p2p/seller/listings/${listingId}/images`, form, {
            headers: { 'Content-Type': undefined },
        })).data;
    },

    submitListing: async (listingId: string) =>
        (await apiClient.post(`/p2p/seller/listings/${listingId}/submit`)).data,

    getMyDeals: async () => (await apiClient.get('/p2p/deals')).data,
    markDelivered: async (id: string) => (await apiClient.post(`/p2p/deals/${id}/delivered`)).data,
    confirmReceipt: async (id: string) => (await apiClient.post(`/p2p/deals/${id}/confirm`)).data,
    openDispute: async (id: string, reason: string) =>
        (await apiClient.post(`/p2p/deals/${id}/dispute`, { reason })).data,
    setActiveDeal: async (id: string) => (await apiClient.post(`/p2p/deals/${id}/activate`)).data,
    getMessages: async (id: string) => (await apiClient.get(`/p2p/deals/${id}/messages`)).data,
};

// Subscriptions API
export const subscriptionsApi = {
    // Каталог каналов с активными тарифами
    getChannels: async () => {
        const response = await apiClient.get('/subscriptions/channels');
        return response.data;
    },

    getMySubscriptions: async () => {
        const response = await apiClient.get('/subscriptions/my');
        return response.data;
    },

    // Ссылка одноразовая и живёт сутки — пользователь вполне может не успеть
    // перейти, поэтому её можно перевыпустить пока подписка активна
    reissueInvite: async (subscriptionId: string) => {
        const response = await apiClient.post(`/subscriptions/${subscriptionId}/invite`);
        return response.data;
    },

    // --- кабинет автора канала ---------------------------------------

    getMyChannels: async (): Promise<AuthorChannel[]> =>
        (await apiClient.get('/subscriptions/author/channels')).data,

    connectChannel: async (data: {
        chat_identifier: string;
        payout_wallet: string;
        description?: string;
        accept_terms: boolean;
    }): Promise<AuthorChannel> =>
        (await apiClient.post('/subscriptions/author/channels', data)).data,

    // Автор жмёт после того, как добавил бота администратором
    verifyChannel: async (channelId: string): Promise<{ bot_is_admin: boolean; error: string | null }> =>
        (await apiClient.post(`/subscriptions/author/channels/${channelId}/verify`)).data,

    createPlan: async (channelId: string, data: {
        title_ru: string;
        title_en: string;
        duration_days: number;
        price_usd: string;
    }) =>
        (await apiClient.post(`/subscriptions/author/channels/${channelId}/plans`, data)).data,

    submitChannel: async (channelId: string): Promise<{ status: ChannelStatus }> =>
        (await apiClient.post(`/subscriptions/author/channels/${channelId}/submit`)).data,

    updateChannel: async (channelId: string, data: {
        description?: string;
        payout_wallet?: string;
    }): Promise<AuthorChannel> =>
        (await apiClient.patch(`/subscriptions/author/channels/${channelId}`, data)).data,

    // Снять с продажи: купленные подписки продолжают действовать, новые
    // купить нельзя
    unpublishChannel: async (channelId: string): Promise<{ status: ChannelStatus }> =>
        (await apiClient.post(`/subscriptions/author/channels/${channelId}/unpublish`)).data,

    deleteChannel: async (channelId: string): Promise<{ deleted: boolean }> =>
        (await apiClient.delete(`/subscriptions/author/channels/${channelId}`)).data,

    updatePlan: async (channelId: string, planId: string, data: {
        title_ru?: string;
        title_en?: string;
        duration_days?: number;
        price_usd?: string;
        is_active?: boolean;
    }) =>
        (await apiClient.patch(
            `/subscriptions/author/channels/${channelId}/plans/${planId}`, data,
        )).data,

    deletePlan: async (channelId: string, planId: string): Promise<{ deleted: boolean }> =>
        (await apiClient.delete(
            `/subscriptions/author/channels/${channelId}/plans/${planId}`,
        )).data,
};

// Withdrawals API
export const withdrawalsApi = {
    // currency не указан — USD, как раньше: реферальный баланс
    requestWithdrawal: async (data: {
        amount: number | string; wallet: string; currency?: 'USD' | 'TON';
    }) => {
        const response = await apiClient.post('/withdrawals', data);
        return response.data;
    },

    // Доступно к выводу по валютам. Нужен автору канала: его заработок лежит
    // на том же счёте, но кабинет продавца показывает баланс только
    // зарегистрированным продавцам, а в профиле — реферальный баланс в USD.
    getBalances: async (): Promise<Record<string, {
        available: string; available_minor: number; hold_minor: number;
    }>> => (await apiClient.get('/withdrawals/balance')).data,

    getMyWithdrawals: async () => {
        const response = await apiClient.get('/withdrawals/my');
        return response.data;
    },

    // Admin methods
    getAllWithdrawals: async (params?: { status?: string; skip?: number; limit?: number }) => {
        const response = await apiClient.get('/withdrawals/admin/all', { params });
        return response.data;
    },

    updateWithdrawalStatus: async (id: string, status: 'pending' | 'completed') => {
        const response = await apiClient.patch(`/withdrawals/admin/${id}`, { status });
        return response.data;
    },
};
