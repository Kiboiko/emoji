import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { categoriesApi } from '../services/categories';
import type { Category, CategoryCreate, CategoryUpdate } from '../services/categories';
import {
    Plus,
    Pencil,
    Trash2,
    X,
    Loader2
} from 'lucide-react';

export const Categories: React.FC = () => {
    const queryClient = useQueryClient();
    const [isModalOpen, setIsModalOpen] = useState(false);
    const [editingCategory, setEditingCategory] = useState<Category | null>(null);

    // Form inputs
    const [nameRu, setNameRu] = useState('');
    const [nameEn, setNameEn] = useState('');
    const [sortOrder, setSortOrder] = useState<number>(0);

    const { data: categories, isLoading } = useQuery({
        queryKey: ['categories'],
        queryFn: async () => {
            const res = await categoriesApi.getAll();
            return res.data;
        }
    });

    const createMutation = useMutation({
        mutationFn: (newCat: CategoryCreate) => categoriesApi.create(newCat),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['categories'] });
            closeModal();
        }
    });

    const updateMutation = useMutation({
        mutationFn: ({ id, data }: { id: string; data: CategoryUpdate }) => categoriesApi.update(id, data),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['categories'] });
            closeModal();
        }
    });

    const deleteMutation = useMutation({
        mutationFn: (id: string) => categoriesApi.delete(id),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['categories'] });
        }
    });

    const openCreateModal = () => {
        setEditingCategory(null);
        setNameRu('');
        setNameEn('');
        setSortOrder(0);
        setIsModalOpen(true);
    };

    const openEditModal = (category: Category) => {
        setEditingCategory(category);
        setNameRu(category.name_ru);
        setNameEn(category.name_en);
        setSortOrder(category.sort_order);
        setIsModalOpen(true);
    };

    const closeModal = () => {
        setIsModalOpen(false);
        setEditingCategory(null);
    };

    const handleSubmit = (e: React.FormEvent) => {
        e.preventDefault();
        const data = {
            name_ru: nameRu,
            name_en: nameEn,
            sort_order: sortOrder
        };

        if (editingCategory) {
            updateMutation.mutate({ id: editingCategory.id, data });
        } else {
            createMutation.mutate(data);
        }
    };

    const handleDelete = (id: string) => {
        if (window.confirm('Вы уверены, что хотите удалить эту категорию?')) {
            deleteMutation.mutate(id);
        }
    };

    if (isLoading) return <div>Загрузка...</div>;

    return (
        <div>
            <div className="flex justify-between items-center mb-6">
                <h1 className="text-3xl font-bold">Категории</h1>
                <button
                    onClick={openCreateModal}
                    className="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-lg flex items-center gap-2"
                >
                    <Plus size={20} />
                    Добавить
                </button>
            </div>

            <div className="bg-gray-800 rounded-lg border border-gray-700 overflow-x-auto">
                <table className="w-full text-left min-w-[600px]">
                    <thead className="bg-gray-700/50 text-gray-400">
                        <tr>
                            <th className="p-4">Название (RU)</th>
                            <th className="p-4">Название (EN)</th>
                            <th className="p-4 text-center">Сорт.</th>
                            <th className="p-4 text-right">Действия</th>
                        </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-700">
                        {categories?.length === 0 && (
                            <tr>
                                <td colSpan={4} className="p-8 text-center text-gray-500">
                                    Нет категорий
                                </td>
                            </tr>
                        )}
                        {categories?.map((category) => (
                            <tr key={category.id} className="hover:bg-gray-700/50 transition-colors">
                                <td className="p-4 font-medium">{category.name_ru}</td>
                                <td className="p-4 text-gray-400">{category.name_en}</td>
                                <td className="p-4 text-center">
                                    <span className="bg-gray-700 px-2 py-1 rounded text-sm">
                                        {category.sort_order}
                                    </span>
                                </td>
                                <td className="p-4 flex justify-end gap-2">
                                    <button
                                        onClick={() => openEditModal(category)}
                                        className="p-2 hover:bg-gray-700 text-gray-400 hover:text-white rounded-lg transition-colors"
                                    >
                                        <Pencil size={18} />
                                    </button>
                                    <button
                                        onClick={() => handleDelete(category.id)}
                                        className="p-2 hover:bg-gray-700 text-gray-400 hover:text-white rounded-lg transition-colors"
                                    >
                                        <Trash2 size={18} />
                                    </button>
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>

            {/* Modal */}
            {isModalOpen && (
                <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 px-4">
                    <div className="bg-gray-800 rounded-xl max-w-md w-full p-6 relative">
                        <button
                            onClick={closeModal}
                            className="absolute top-4 right-4 text-gray-400 hover:text-white"
                        >
                            <X size={24} />
                        </button>

                        <h2 className="text-xl font-bold mb-6">
                            {editingCategory ? 'Редактировать категорию' : 'Новая категория'}
                        </h2>

                        <form onSubmit={handleSubmit} className="space-y-4">
                            <div>
                                <label className="block text-sm font-medium text-gray-400 mb-1">
                                    Название (RU)
                                </label>
                                <input
                                    type="text"
                                    required
                                    value={nameRu}
                                    onChange={(e) => setNameRu(e.target.value)}
                                    className="w-full bg-gray-900 border border-gray-700 rounded-lg px-4 py-2 focus:ring-2 focus:ring-blue-500 outline-none"
                                />
                            </div>

                            <div>
                                <label className="block text-sm font-medium text-gray-400 mb-1">
                                    Название (EN)
                                </label>
                                <input
                                    type="text"
                                    required
                                    value={nameEn}
                                    onChange={(e) => setNameEn(e.target.value)}
                                    className="w-full bg-gray-900 border border-gray-700 rounded-lg px-4 py-2 focus:ring-2 focus:ring-blue-500 outline-none"
                                />
                            </div>

                            <div>
                                <label className="block text-sm font-medium text-gray-400 mb-1">
                                    Сортировка (чем больше, тем выше)
                                </label>
                                <input
                                    type="number"
                                    required
                                    value={sortOrder}
                                    onChange={(e) => setSortOrder(Number(e.target.value))}
                                    className="w-full bg-gray-900 border border-gray-700 rounded-lg px-4 py-2 focus:ring-2 focus:ring-blue-500 outline-none"
                                />
                            </div>

                            <button
                                type="submit"
                                disabled={createMutation.isPending || updateMutation.isPending}
                                className="w-full bg-blue-600 hover:bg-blue-700 text-white font-medium py-2 rounded-lg transition-colors flex justify-center items-center gap-2"
                            >
                                {(createMutation.isPending || updateMutation.isPending) && (
                                    <Loader2 size={18} className="animate-spin" />
                                )}
                                {editingCategory ? 'Сохранить' : 'Создать'}
                            </button>
                        </form>
                    </div>
                </div>
            )}
        </div>
    );
};
