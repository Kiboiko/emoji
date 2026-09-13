import api from '../api/axios';

export interface Product {
    id: string;
    name_ru: string;
    name_en: string;
    description_ru: string;
    description_en: string;
    price_usdt: number;
    price_ton?: number;
    image_url: string;
    category_id: string;
    is_top: boolean;
    sort_order: number;
    stock: number;
    type: 'digital' | 'service' | 'instruction';
    min_quantity: number;
    max_quantity?: number;
    content_data?: {
        instruction?: string;
        [key: string]: unknown;
    };
    created_at: string;
}

export interface ProductsResponse {
    items: Product[];
    total: number;
    page: number;
    pages: number;
}

export const productsApi = {
    getAll: async (page = 1, limit = 20, search = '', sortBy = 'created_at', sortOrder = 'desc') => {
        return api.get<ProductsResponse>('/api/products/admin', {
            params: {
                page,
                limit,
                search,
                sort_by: sortBy,
                sort_order: sortOrder
            }
        });
    },

    create: async (data: FormData) => {
        return api.post<Product>('/api/products', data, {
            headers: { 'Content-Type': 'multipart/form-data' }
        });
    },

    update: async (id: string, data: FormData) => {
        return api.put<Product>(`/api/products/${id}`, data, {
            headers: { 'Content-Type': 'multipart/form-data' }
        });
    },

    delete: async (id: string) => {
        return api.delete(`/api/products/${id}`);
    }
}
