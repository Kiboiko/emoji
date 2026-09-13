import api from '../api/axios';

export interface Category {
    id: string;
    name_ru: string;
    name_en: string;
    sort_order: number;
    created_at: string;
}

export interface CategoryCreate {
    name_ru: string;
    name_en: string;
    sort_order: number;
}

export interface CategoryUpdate extends Partial<CategoryCreate> { }

export const categoriesApi = {
    getAll: async () => {
        return api.get<Category[]>('/api/categories/all');
    },

    create: async (data: CategoryCreate) => {
        return api.post<Category>('/api/categories', data);
    },

    update: async (id: string, data: CategoryUpdate) => {
        return api.put<Category>(`/api/categories/${id}`, data);
    },

    delete: async (id: string) => {
        return api.delete(`/api/categories/${id}`);
    }
}
