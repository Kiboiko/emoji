import axios from 'axios';

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

// Response interceptor for error handling
apiClient.interceptors.response.use(
    (response) => response,
    (error) => {
        if (error.response?.status === 401) {
            // Clear token but DO NOT force reload/redirect
            // Background requests (e.g. cart update during ban) should fail silently or show UI error
            localStorage.removeItem('access_token');
            localStorage.removeItem('user');
            // window.location.href = '/'; // DISABLED: Causes infinite reload loops during ban
        }
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

    createOrder: async (currency: 'USDT' | 'TON') => {
        const response = await apiClient.post('/orders', { currency });
        return response.data;
    },
};

// Payments API
export const paymentsApi = {
    checkPaymentStatus: async (orderId: string) => {
        const response = await apiClient.get(`/payments/check/${orderId}`);
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
};

// Withdrawals API
export const withdrawalsApi = {
    requestWithdrawal: async (data: { amount: number; wallet: string }) => {
        const response = await apiClient.post('/withdrawals', data);
        return response.data;
    },

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
