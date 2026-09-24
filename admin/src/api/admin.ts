/**
 * Клиент админского API.
 *
 * Отдельный файл от axios.ts: там перехватчики и обновление токена, здесь
 * только эндпоинты. Старый объект adminApi в axios.ts оставлен — на него
 * опираются страницы товаров, отзывов и выводов.
 */
import api from './axios';

export interface Page<T> {
    total: number;
    skip: number;
    limit: number;
    items: T[];
}

export interface AdminUser {
    id: string;
    telegram_id: number;
    username: string | null;
    first_name: string;
    is_admin: boolean;
    is_blocked: boolean;
    referral_code: string;
    referral_earnings: number;
    orders_count: number;
    orders_total_usdt: number;
    referrals_count: number;
    created_at: string;
}

export interface AdminOrder {
    id: string;
    user_id: string;
    user_telegram_id: number | null;
    user_name: string;
    user_username: string | null;
    total_usdt: number;
    total_ton: number | null;
    currency: string;
    status: string;
    created_at: string;
    paid_at: string | null;
    items: Array<{
        product_name: string;
        quantity: number;
        price_usdt: number;
        is_p2p: boolean;
        type: string | null;
    }>;
}

export interface SettingDef {
    key: string;
    type: 'int' | 'bool' | 'str' | 'list';
    default: unknown;
    description: string;
    min: number | null;
    max: number | null;
    value: unknown;
}

export const usersApi = {
    list: (params: {
        search?: string; blocked?: boolean; sort?: string; order?: string;
        skip?: number; limit?: number;
    }) => api.get<Page<AdminUser>>('/api/admin/users', { params }).then((r) => r.data),

    card: (id: string) => api.get<any>(`/api/admin/users/${id}`).then((r) => r.data),

    block: (id: string, blocked: boolean, reason?: string) =>
        api.post(`/api/admin/users/${id}/block`, { blocked, reason }).then((r) => r.data),
};

export const ordersApi = {
    list: (params: {
        status?: string; search?: string; date_from?: string; date_to?: string;
        skip?: number; limit?: number;
    }) => api.get<Page<AdminOrder>>('/api/admin/orders', { params }).then((r) => r.data),

    card: (id: string) => api.get<any>(`/api/admin/orders/${id}`).then((r) => r.data),

    setStatus: (id: string, status: string, reason?: string) =>
        api.post(`/api/admin/orders/${id}/status`, { status, reason }).then((r) => r.data),
};

export const statsApi = {
    summary: (period: string) =>
        api.get<any>('/api/admin/stats', { params: { period } }).then((r) => r.data),
    attention: () => api.get<any>('/api/admin/stats/attention').then((r) => r.data),
    timeseries: (days: number) =>
        api.get<any>('/api/admin/stats/timeseries', { params: { days } }).then((r) => r.data),
    topProducts: (days: number) =>
        api.get<any>('/api/admin/stats/top-products', { params: { days } }).then((r) => r.data),
    conversion: (days: number) =>
        api.get<any>('/api/admin/stats/conversion', { params: { days } }).then((r) => r.data),
};

export const settingsApi = {
    list: () => api.get<SettingDef[]>('/api/admin/settings').then((r) => r.data),
    update: (key: string, value: unknown) =>
        api.put(`/api/admin/settings/${key}`, { value }).then((r) => r.data),
};

export const p2pApi = {
    listings: (params: { status?: string; skip?: number; limit?: number }) =>
        api.get<any>('/api/admin/p2p/listings', { params }).then((r) => r.data),
    moderate: (id: string, approve: boolean, comment?: string) =>
        api.post(`/api/admin/p2p/listings/${id}/moderate`, { approve, comment }).then((r) => r.data),

    sellers: (params: { status?: string; skip?: number; limit?: number }) =>
        api.get<any>('/api/admin/p2p/sellers', { params }).then((r) => r.data),
    setSellerStatus: (id: string, status: string, reason?: string, restrict_days?: number) =>
        api.post(`/api/admin/p2p/sellers/${id}/status`, { status, reason, restrict_days })
            .then((r) => r.data),
    // Галочка проверенного продавца — решение отдельное от статуса:
    // «не заблокирован» и «площадка за него ручается» это разные вещи
    setSellerVerified: (id: string, verified: boolean) =>
        api.post(`/api/admin/p2p/sellers/${id}/verify`, { verified }).then((r) => r.data),

    // Магазин самой площадки: такой же продавец, но заполняет его
    // администратор, а не владелец
    platformStore: () =>
        api.get<any>('/api/admin/p2p/platform-store').then((r) => r.data),
    updatePlatformStore: (data: { display_name?: string; description?: string }) =>
        api.patch('/api/admin/p2p/platform-store', data).then((r) => r.data),
    uploadPlatformStoreAvatar: (file: File) => {
        const form = new FormData();
        form.append('image', file);
        return api.post('/api/admin/p2p/platform-store/avatar', form).then((r) => r.data);
    },

    deals: (params: { status?: string; skip?: number; limit?: number }) =>
        api.get<any>('/api/admin/p2p/deals', { params }).then((r) => r.data),
    dealMessages: (id: string) =>
        api.get<any>(`/api/admin/p2p/deals/${id}/messages`).then((r) => r.data),
    resolveDispute: (id: string, release: boolean, comment?: string) =>
        api.post(`/api/admin/p2p/deals/${id}/resolve`, { release, comment }).then((r) => r.data),
};

export const referralsApi = {
    list: (params: {
        level?: number; source?: string; referrer_id?: string; search?: string;
        date_from?: string; date_to?: string; skip?: number; limit?: number;
    }) => api.get<any>('/api/admin/referrals', { params }).then((r) => r.data),
    top: (params: { limit?: number; date_from?: string; date_to?: string }) =>
        api.get<any>('/api/admin/referrals/top', { params }).then((r) => r.data),
};

export const subscriptionsApi = {
    channels: (params: { status?: string; skip?: number; limit?: number }) =>
        api.get<any>('/api/admin/subscriptions/channels', { params }).then((r) => r.data),
    moderateChannel: (id: string, approve: boolean, comment?: string) =>
        api.post(`/api/admin/subscriptions/channels/${id}/moderate`, { approve, comment })
            .then((r) => r.data),
    suspendChannel: (id: string, reason?: string) =>
        api.post(`/api/admin/subscriptions/channels/${id}/suspend`, { reason }).then((r) => r.data),
    setChannelVerified: (id: string, verified: boolean) =>
        api.post(`/api/admin/subscriptions/channels/${id}/verify`, { verified }).then((r) => r.data),

    list: (params: { status?: string; skip?: number; limit?: number }) =>
        api.get<any>('/api/admin/subscriptions', { params }).then((r) => r.data),
    revoke: (id: string, reason?: string) =>
        api.post(`/api/admin/subscriptions/${id}/revoke`, { reason }).then((r) => r.data),
    reissueInvite: (id: string) =>
        api.post(`/api/admin/subscriptions/${id}/reissue-invite`).then((r) => r.data),
};

export const financeApi = {
    accounts: (params: { currency?: string; owner_type?: string }) =>
        api.get<any>('/api/admin/finance/accounts', { params }).then((r) => r.data),
    ledger: (params: {
        account_id?: string; ref_type?: string; entry_type?: string;
        skip?: number; limit?: number;
    }) => api.get<any>('/api/admin/finance/ledger', { params }).then((r) => r.data),
    reconcile: () => api.post('/api/admin/finance/reconcile').then((r) => r.data),
    scanUnmatched: () => api.post('/api/admin/finance/ton/scan-unmatched').then((r) => r.data),
};
