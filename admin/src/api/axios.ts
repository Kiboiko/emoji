import axios from 'axios';

// Create axios instance
const api = axios.create({
    baseURL: '/', // Changed from '/api' to avoid double prefix if calls include /api
    withCredentials: true, // Important for cookies
});

let isRefreshing = false;
let failedQueue: any[] = [];

const processQueue = (error: any, token: string | null = null) => {
    failedQueue.forEach(prom => {
        if (error) {
            prom.reject(error);
        } else {
            prom.resolve(token);
        }
    });

    failedQueue = [];
};

// Callback to update token in React state
let onTokenRefreshed: ((token: string) => void) | null = null;

export const setOnTokenRefreshed = (callback: (token: string) => void) => {
    onTokenRefreshed = callback;
};

// Add a request interceptor to add token
api.interceptors.request.use(
    (config) => {
        // We assume token is set in headers.common by AuthContext or we can store it in a variable here
        // But headers.common is easier if AuthContext updates it.
        return config;
    },
    (error) => {
        return Promise.reject(error);
    }
);

api.interceptors.response.use(
    (response) => response,
    async (error) => {
        const originalRequest = error.config;

        // Prevent infinite loop: if the error comes from the refresh endpoint itself, don't try to refresh again
        if (error.response?.status === 401 && !originalRequest._retry && !originalRequest.url?.includes('/refresh')) {
            if (isRefreshing) {
                return new Promise(function (resolve, reject) {
                    failedQueue.push({ resolve, reject });
                }).then(token => {
                    originalRequest.headers['Authorization'] = 'Bearer ' + token;
                    return api(originalRequest);
                }).catch(err => {
                    return Promise.reject(err);
                });
            }

            originalRequest._retry = true;
            isRefreshing = true;

            try {
                const { data } = await api.post('/api/admin/auth/refresh');
                const newToken = data.access_token;

                // Update defaults
                api.defaults.headers.common['Authorization'] = 'Bearer ' + newToken;
                originalRequest.headers['Authorization'] = 'Bearer ' + newToken;

                // Notify Context
                if (onTokenRefreshed) {
                    onTokenRefreshed(newToken);
                }

                processQueue(null, newToken);
                return api(originalRequest);
            } catch (refreshError) {
                processQueue(refreshError, null);
                return Promise.reject(refreshError);
            } finally {
                isRefreshing = false;
            }
        }

        return Promise.reject(error);
    }
);

// API Wrapper
export const adminApi = {
    // Orders
    getOrders: (status?: string) => api.get<any[]>('/api/admin/orders', { params: { status } }),
    getServiceOrders: (status: 'paid' | 'completed' = 'paid') => api.get<any[]>('/api/admin/orders/processing', { params: { status } }),
    completeServiceOrder: (id: string) => api.post(`/api/admin/orders/${id}/complete`),

    // Users
    // Add other endpoints as needed

    // Reviews
    getReviews: () => api.get<any[]>('/api/reviews/admin/all'),
    deleteReview: (id: string) => api.delete(`/api/reviews/${id}`),
    createFakeReview: (data: {
        product_id: string;
        fake_username: string;
        text: string;
        rating?: number | null;
        fake_quantity?: number | null;
    }) => api.post('/api/reviews/admin/fake', data),

    // Products (for selectors)
    getProductsList: () => api.get<any>('/api/products/admin', { params: { page: 1, limit: 200 } }),

    // Withdrawals
    getWithdrawals: (params: { status?: string, skip?: number, limit?: number }) => api.get<any>('/api/withdrawals/admin/all', { params }),
    updateWithdrawalStatus: (id: string, status: string) => api.patch(`/api/withdrawals/admin/${id}`, { status }),
    // Чьи деньги на кошельке площадки и сколько из них можно забрать себе
    getPayoutSummary: () => api.get<PayoutSummary>('/api/withdrawals/admin/summary'),
    // Перевод для подписи в кошельке площадки через TonConnect
    preparePayout: (id: string) => api.post<PreparedPayout>(`/api/withdrawals/admin/${id}/payout`),
    // Кошелёк подписал и отправил — сервер ждёт перевод в блокчейне
    payoutSent: (id: string) => api.post(`/api/withdrawals/admin/${id}/sent`),
    rejectWithdrawal: (id: string, reason: string) =>
        api.post(`/api/withdrawals/admin/${id}/reject`, { reason }),
};

export interface PayoutSummary {
    /** null — индексер не ответил, баланс кошелька неизвестен */
    wallet_nano: string | null;
    users_nano: string;
    withdrawals_nano: string;
    escrow_nano: string;
    owed_nano: string;
    free_nano: string | null;
    platform_address: string | null;
    network: string;
}

export interface PreparedPayout {
    address: string;
    amount_nano: string;
    comment: string;
    valid_until: number;
    network: string;
    platform_address: string | null;
}

export default api;
