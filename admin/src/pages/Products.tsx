import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { productsApi } from '../services/products';
import { categoriesApi } from '../services/categories';
import type { Product } from '../services/products';
import type { Category } from '../services/categories';
import { DataTable, type Column } from '../components/ui/DataTable';
import {
    Plus,
    Pencil,
    Trash2,
    X,
    Loader2,
    Search,
    Upload,
    FileText,
    Flame
} from 'lucide-react';

const SortIcon = ({ column, sortBy, sortOrder }: { column: string, sortBy: string, sortOrder: string }) => {
    if (sortBy !== column) return <div className="w-4" />;
    return <span className="ml-1 text-blue-400 font-bold">{sortOrder === 'asc' ? '↑' : '↓'}</span>;
};

export const Products: React.FC = () => {
    const queryClient = useQueryClient();
    const [page, setPage] = useState(1);
    const [search, setSearch] = useState('');
    const [debouncedSearch, setDebouncedSearch] = useState('');
    const [isModalOpen, setIsModalOpen] = useState(false);
    const [editingProduct, setEditingProduct] = useState<Product | null>(null);

    const [sortBy, setSortBy] = useState('created_at');
    const [sortOrder, setSortOrder] = useState('desc');

    // Filter debouncing
    React.useEffect(() => {
        const timer = setTimeout(() => setDebouncedSearch(search), 500);
        return () => clearTimeout(timer);
    }, [search]);

    // Data fetching
    const { data: productsData, isLoading } = useQuery({
        queryKey: ['products', page, debouncedSearch, sortBy, sortOrder],
        queryFn: () => productsApi.getAll(page, 20, debouncedSearch, sortBy, sortOrder).then(r => r.data)
    });

    const { data: categories } = useQuery({
        queryKey: ['categories'],
        queryFn: () => categoriesApi.getAll().then(r => r.data)
    });

    // Form State
    const [formData, setFormData] = useState({
        name_ru: '',
        name_en: '',
        description_ru: '',
        description_en: '',
        price_usdt: '',
        category_id: '',
        type: 'digital' as 'digital' | 'service' | 'instruction',
        is_top: false,
        min_quantity: '1',
        image: null as File | null,
        digital_file: null as File | null,
        instruction_text: ''
    });

    const resetForm = () => {
        setFormData({
            name_ru: '',
            name_en: '',
            description_ru: '',
            description_en: '',
            price_usdt: '',
            category_id: categories && categories.length > 0 ? categories[0].id : '',
            type: 'digital',
            is_top: false,
            min_quantity: '1',
            image: null,
            digital_file: null,
            instruction_text: ''
        });
    };

    const handleCreateOpen = () => {
        setEditingProduct(null);
        resetForm();
        setIsModalOpen(true);
    };

    const handleEditOpen = (product: Product) => {
        setEditingProduct(product);
        setFormData({
            name_ru: product.name_ru,
            name_en: product.name_en,
            description_ru: product.description_ru,
            description_en: product.description_en,
            price_usdt: String(product.price_usdt),
            category_id: product.category_id,
            type: product.type,
            is_top: product.is_top,
            min_quantity: String(product.min_quantity),
            image: null,
            digital_file: null,
            instruction_text: product.content_data?.instruction || ''
        });
        setIsModalOpen(true);
    };

    const createMutation = useMutation({
        mutationFn: (data: FormData) => productsApi.create(data),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['products'] });
            setIsModalOpen(false);
        }
    });

    const updateMutation = useMutation({
        mutationFn: ({ id, data }: { id: string; data: FormData }) => productsApi.update(id, data),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['products'] });
            setIsModalOpen(false);
        }
    });

    const deleteMutation = useMutation({
        mutationFn: (id: string) => productsApi.delete(id),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['products'] });
        }
    });

    const handleSubmit = (e: React.FormEvent) => {
        e.preventDefault();
        const data = new FormData();
        data.append('name_ru', formData.name_ru);
        data.append('name_en', formData.name_en);
        data.append('description_ru', formData.description_ru);
        data.append('description_en', formData.description_en);
        data.append('price_usdt', formData.price_usdt);
        data.append('category_id', formData.category_id);
        data.append('type', formData.type);
        data.append('is_top', String(formData.is_top));
        data.append('min_quantity', formData.min_quantity);

        if (formData.image) {
            data.append('image', formData.image);
        }
        if (formData.digital_file) {
            data.append('digital_file', formData.digital_file);
        }
        if (formData.type === 'instruction' && formData.instruction_text) {
            data.append('instruction_text', formData.instruction_text);
        }

        if (editingProduct) {
            updateMutation.mutate({ id: editingProduct.id, data });
        } else {
            createMutation.mutate(data);
        }
    };

    const handleSort = (column: string) => {
        if (sortBy === column) {
            setSortOrder(sortOrder === 'asc' ? 'desc' : 'asc');
        } else {
            setSortBy(column);
            setSortOrder('desc');
        }
    };

    const totalPages = productsData?.pages || 1;
    /** Колонки, по которым можно сортировать. Список общий для шапки
        таблицы и для выбора на телефоне, где шапки нет. */
    const SORTABLE = [
        { key: 'name', label: 'Название' },
        { key: 'price', label: 'Цена' },
        { key: 'category', label: 'Категория' },
        { key: 'type', label: 'Тип' },
        { key: 'stock', label: 'Остаток' },
        { key: 'is_top', label: 'TOP' },
        { key: 'created_at', label: 'Дате добавления' },
    ];

    const sortable = (key: string, title: string, className?: string): Column<Product> => ({
        key,
        title,
        className,
        onHeaderClick: () => handleSort(key),
        header: (
            <div className={`flex items-center ${className?.includes('center') ? 'justify-center' : ''}`}>
                {title} <SortIcon column={key} sortBy={sortBy} sortOrder={sortOrder} />
            </div>
        ),
    });

    if (isLoading) return (
        <div className="flex justify-center items-center h-64">
            <Loader2 className="animate-spin text-blue-500" size={48} />
        </div>
    );

    const columns: Column<Product>[] = [
        {
            key: 'image',
            title: 'Фото',
            hideOnMobile: true,
            render: (product) => (
                <div className="w-12 h-12 rounded-lg overflow-hidden bg-gray-900">
                    <img
                        src={product.image_url}
                        alt={product.name_ru}
                        className="w-full h-full object-cover"
                    />
                </div>
            ),
        },
        {
            ...sortable('name', 'Название'),
            // На телефоне это заголовок карточки: картинка идёт рядом с ним,
            // отдельной строкой «Фото: [квадрат]» она выглядела бы нелепо
            wide: true,
            render: (product) => (
                <div className="flex items-center gap-3">
                    <div className="md:hidden w-12 h-12 shrink-0 rounded-lg overflow-hidden bg-gray-900">
                        <img
                            src={product.image_url}
                            alt=""
                            className="w-full h-full object-cover"
                        />
                    </div>
                    <div className="min-w-0">
                        <div className="font-medium text-white break-words">{product.name_ru}</div>
                        <div className="text-xs text-gray-500 break-words">{product.name_en}</div>
                    </div>
                </div>
            ),
        },
        {
            ...sortable('price', 'Цена'),
            render: (product) => (
                <span className="text-green-400 font-medium">${product.price_usdt}</span>
            ),
        },
        {
            ...sortable('category', 'Категория'),
            render: (product) => {
                const category = categories?.find((c) => c.id === product.category_id);
                return <span className="text-gray-300">{category ? category.name_ru : '-'}</span>;
            },
        },
        {
            ...sortable('type', 'Тип'),
            render: (product) => (
                <span className={`text-xs px-2 py-1 rounded ${product.type === 'service'
                    ? 'bg-purple-500/10 text-purple-400'
                    : 'bg-blue-500/10 text-blue-400'}`}>
                    {product.type === 'service'
                        ? 'Услуга'
                        : product.type === 'instruction' ? 'Инструкция' : 'Цифровой'}
                </span>
            ),
        },
        {
            ...sortable('stock', 'Остаток'),
            render: (product) => (
                <span className="text-gray-300">
                    {product.type === 'digital' ? product.stock : '\u221e'}
                </span>
            ),
        },
        {
            ...sortable('is_top', 'TOP', 'text-center'),
            render: (product) => (product.is_top
                ? <Flame size={20} className="text-orange-600 md:mx-auto" />
                : <span className="text-gray-600">—</span>),
        },
        {
            key: 'actions',
            title: 'Действия',
            className: 'text-right',
            wide: true,
            render: (product) => (
                <div className="flex gap-2 md:justify-end">
                    <button
                        onClick={() => handleEditOpen(product)}
                        className="p-2 hover:bg-gray-700 text-gray-400 hover:text-white rounded-lg transition-colors"
                        aria-label="Править"
                    >
                        <Pencil size={18} />
                    </button>
                    <button
                        onClick={() => {
                            if (window.confirm('Удалить товар?')) {
                                deleteMutation.mutate(product.id);
                            }
                        }}
                        className="p-2 hover:bg-gray-700 text-gray-400 hover:text-white rounded-lg transition-colors"
                        aria-label="Удалить"
                    >
                        <Trash2 size={18} />
                    </button>
                </div>
            ),
        },
    ];

    return (
        <div>
            {/* Header */}
            <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 mb-6">
                <h1 className="text-2xl md:text-3xl font-bold">Товары</h1>

                <div className="flex gap-4 w-full md:w-auto">
                    <div className="relative flex-1 md:w-64">
                        <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" size={18} />
                        <input
                            type="text"
                            placeholder="Поиск..."
                            value={search}
                            onChange={(e) => setSearch(e.target.value)}
                            className="w-full bg-gray-800 border border-gray-700 rounded-lg pl-10 pr-4 py-2 focus:ring-2 focus:ring-blue-500 outline-none"
                        />
                    </div>
                    <button
                        onClick={handleCreateOpen}
                        className="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-lg flex items-center gap-2 whitespace-nowrap"
                    >
                        <Plus size={20} />
                        Добавить
                    </button>
                </div>
            </div>

            {/* Сортировка на телефоне: шапки таблицы там нет, а без неё
                порядок товаров изменить было бы нечем */}
            <div className="md:hidden flex items-center gap-2 mb-3">
                <label htmlFor="sort" className="text-sm text-gray-400 shrink-0">Сортировка</label>
                <select
                    id="sort"
                    value={sortBy}
                    onChange={(e) => handleSort(e.target.value)}
                    className="flex-1 min-w-0 bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-blue-500"
                >
                    {SORTABLE.map((item) => (
                        <option key={item.key} value={item.key}>{item.label}</option>
                    ))}
                </select>
                <button
                    onClick={() => handleSort(sortBy)}
                    className="shrink-0 px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm"
                    aria-label="Обратный порядок"
                >
                    {sortOrder === 'asc' ? '\u2191' : '\u2193'}
                </button>
            </div>

            <DataTable<Product>
                columns={columns}
                rows={productsData?.items ?? []}
                rowKey={(product) => product.id}
                emptyText="Нет товаров"
            />

            {/* Pagination */}
            {totalPages > 1 && (
                <div className="flex justify-center gap-2 mt-6">
                    <button
                        onClick={() => setPage(p => Math.max(1, p - 1))}
                        disabled={page === 1}
                        className="px-4 py-2 bg-gray-800 rounded-lg disabled:opacity-50 hover:bg-gray-700"
                    >
                        Назад
                    </button>
                    <span className="flex items-center text-gray-400">
                        Страница {page} из {totalPages}
                    </span>
                    <button
                        onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                        disabled={page === totalPages}
                        className="px-4 py-2 bg-gray-800 rounded-lg disabled:opacity-50 hover:bg-gray-700"
                    >
                        Вперед
                    </button>
                </div>
            )}

            {/* Create/Edit Modal */}
            {isModalOpen && (
                <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-0 md:p-4">
                    <div className="bg-gray-800 w-full h-full md:h-auto md:max-h-[90vh] md:max-w-2xl md:rounded-xl flex flex-col relative">
                        {/* Modal Header */}
                        <div className="flex justify-between items-center p-4 md:p-6 border-b border-gray-700 sticky top-0 bg-gray-800 z-10 md:rounded-t-xl">
                            <h2 className="text-xl font-bold">
                                {editingProduct ? 'Редактировать товар' : 'Новый товар'}
                            </h2>
                            <button
                                onClick={() => setIsModalOpen(false)}
                                className="text-gray-400 hover:text-white p-2"
                            >
                                <X size={24} />
                            </button>
                        </div>

                        {/* Modal Body (Scrollable) */}
                        <div className="flex-1 overflow-y-auto p-4 md:p-6 custom-scrollbar">
                            <form id="product-form" onSubmit={handleSubmit} className="space-y-6 pb-20 md:pb-0">
                                {/* Images and Basic Info Logic */}
                                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                                    <div className="order-first md:order-0">
                                        <label className="block text-sm font-medium text-gray-400 mb-2">Изображение</label>
                                        <div className="border-2 border-dashed border-gray-600 rounded-lg p-8 text-center hover:border-blue-500 transition-colors relative bg-gray-900/50">
                                            <input
                                                type="file"
                                                accept="image/*"
                                                onChange={(e) => setFormData({ ...formData, image: e.target.files?.[0] || null })}
                                                className="absolute inset-0 opacity-0 cursor-pointer w-full h-full"
                                            />
                                            <Upload className="mx-auto text-gray-500 mb-2" size={32} />
                                            <div className="text-sm text-gray-400 font-medium">
                                                {formData.image ? (
                                                    <span className="text-green-400">{formData.image.name}</span>
                                                ) : (
                                                    'Нажмите для загрузки'
                                                )}
                                            </div>
                                        </div>
                                        {editingProduct && !formData.image && (
                                            <p className="text-xs text-gray-500 mt-2 text-center">Текущее изображение сохранено</p>
                                        )}
                                    </div>

                                    <div className="space-y-4">
                                        <div>
                                            <label className="block text-sm font-medium text-gray-400 mb-1">Категория</label>
                                            <select
                                                className="w-full bg-gray-900 border border-gray-700 rounded-lg px-4 py-3 focus:ring-2 focus:ring-blue-500 outline-none"
                                                value={formData.category_id}
                                                onChange={(e) => setFormData({ ...formData, category_id: e.target.value })}
                                                required
                                            >
                                                <option value="" disabled>Выберите категорию</option>
                                                {categories?.map((c: Category) => (
                                                    <option key={c.id} value={c.id}>{c.name_ru}</option>
                                                ))}
                                            </select>
                                        </div>

                                        <div>
                                            <label className="block text-sm font-medium text-gray-400 mb-1">Тип товара</label>
                                            <select
                                                className="w-full bg-gray-900 border border-gray-700 rounded-lg px-4 py-3 focus:ring-2 focus:ring-blue-500 outline-none"
                                                value={formData.type}
                                                onChange={(e) => setFormData({ ...formData, type: e.target.value as 'digital' | 'service' | 'instruction' })}
                                            >
                                                <option value="digital">Цифровой (Файл/Текст)</option>
                                                <option value="instruction">Инструкция (Текст)</option>
                                                <option value="service">Услуга</option>
                                            </select>
                                        </div>

                                        <div className="flex items-center justify-between bg-gray-900 border border-gray-700 rounded-lg p-3">
                                            <div className="flex items-center gap-2">
                                                <Flame size={18} className="text-orange-500" />
                                                <label htmlFor="is_top" className="text-sm font-medium text-gray-300 cursor-pointer select-none">
                                                    ТОП товар
                                                </label>
                                            </div>
                                            <label className="relative inline-flex items-center cursor-pointer">
                                                <input
                                                    type="checkbox"
                                                    id="is_top"
                                                    checked={formData.is_top}
                                                    onChange={(e) => setFormData({ ...formData, is_top: e.target.checked })}
                                                    className="sr-only peer"
                                                />
                                                <div className="w-11 h-6 bg-gray-700 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-600"></div>
                                            </label>
                                        </div>
                                    </div>
                                </div>

                                {/* Translations */}
                                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                                    <div className="space-y-4">
                                        <h3 className="text-xs font-bold text-gray-500 uppercase tracking-wider">Русский язык</h3>
                                        <input
                                            type="text"
                                            placeholder="Название"
                                            value={formData.name_ru}
                                            onChange={(e) => setFormData({ ...formData, name_ru: e.target.value })}
                                            className="w-full bg-gray-900 border border-gray-700 rounded-lg px-4 py-3 focus:ring-2 focus:ring-blue-500 outline-none placeholder-gray-600"
                                            required
                                        />
                                        <textarea
                                            placeholder="Описание"
                                            value={formData.description_ru}
                                            onChange={(e) => setFormData({ ...formData, description_ru: e.target.value })}
                                            className="w-full bg-gray-900 border border-gray-700 rounded-lg px-4 py-3 focus:ring-2 focus:ring-blue-500 outline-none h-24 placeholder-gray-600 resize-none leading-relaxed"
                                            required
                                        />
                                    </div>
                                    <div className="space-y-4">
                                        <h3 className="text-xs font-bold text-gray-500 uppercase tracking-wider">English</h3>
                                        <input
                                            type="text"
                                            placeholder="Name"
                                            value={formData.name_en}
                                            onChange={(e) => setFormData({ ...formData, name_en: e.target.value })}
                                            className="w-full bg-gray-900 border border-gray-700 rounded-lg px-4 py-3 focus:ring-2 focus:ring-blue-500 outline-none placeholder-gray-600"
                                            required
                                        />
                                        <textarea
                                            placeholder="Description"
                                            value={formData.description_en}
                                            onChange={(e) => setFormData({ ...formData, description_en: e.target.value })}
                                            className="w-full bg-gray-900 border border-gray-700 rounded-lg px-4 py-3 focus:ring-2 focus:ring-blue-500 outline-none h-24 placeholder-gray-600 resize-none leading-relaxed"
                                            required
                                        />
                                    </div>
                                </div>

                                {/* Pricing and Details */}
                                <div className="grid grid-cols-2 gap-4">
                                    <div>
                                        <label className="block text-sm font-medium text-gray-400 mb-1">Цена (USDT)</label>
                                        <input
                                            type="number"
                                            step="0.01"
                                            value={formData.price_usdt}
                                            onChange={(e) => setFormData({ ...formData, price_usdt: e.target.value })}
                                            className="w-full bg-gray-900 border border-gray-700 rounded-lg px-4 py-3 focus:ring-2 focus:ring-blue-500 outline-none text-white font-bold"
                                            required
                                        />
                                    </div>
                                    <div>
                                        <label className="block text-sm font-medium text-gray-400 mb-1">Мин. кол-во</label>
                                        <input
                                            type="number"
                                            value={formData.min_quantity}
                                            onChange={(e) => setFormData({ ...formData, min_quantity: e.target.value })}
                                            className="w-full bg-gray-900 border border-gray-700 rounded-lg px-4 py-3 focus:ring-2 focus:ring-blue-500 outline-none text-white"
                                            required
                                        />
                                    </div>
                                </div>

                                {/* Digital Content Upload */}
                                {formData.type === 'digital' && (
                                    <div className="bg-gray-900/50 p-4 rounded-lg border border-gray-700">
                                        <label className="block text-sm font-medium text-gray-300 mb-2 flex items-center gap-2">
                                            <FileText size={16} />
                                            Загрузить базу товаров (txt)
                                        </label>
                                        <p className="text-xs text-gray-500 mb-3">
                                            Файл с ключами/аккаунтами (по 1 строке).
                                        </p>
                                        <input
                                            type="file"
                                            accept=".txt"
                                            onChange={(e) => setFormData({ ...formData, digital_file: e.target.files?.[0] || null })}
                                            className="w-full text-sm text-gray-400 file:mr-4 file:py-2 file:px-4 file:rounded-lg file:border-0 file:text-sm file:font-semibold file:bg-blue-600 file:text-white hover:file:bg-blue-700 cursor-pointer"
                                        />
                                    </div>
                                )}

                                {/* Instruction Text Input */}
                                {formData.type === 'instruction' && (
                                    <div>
                                        <label className="block text-sm font-medium text-gray-400 mb-2">Текст инструкции</label>
                                        <textarea
                                            placeholder="Введите текст инструкции, который получит покупатель после оплаты..."
                                            value={formData.instruction_text}
                                            onChange={(e) => setFormData({ ...formData, instruction_text: e.target.value })}
                                            className="w-full bg-gray-900 border border-gray-700 rounded-lg px-4 py-3 focus:ring-2 focus:ring-blue-500 outline-none h-48 placeholder-gray-600 resize-none leading-relaxed font-mono text-sm"
                                            required={formData.type === 'instruction'}
                                        />
                                        <p className="text-xs text-gray-500 mt-2">
                                            Этот текст будет показан покупателю в деталях заказа.
                                        </p>
                                    </div>
                                )}
                            </form>
                        </div>

                        {/* Modal Footer (Sticky on Mobile) */}
                        <div className="p-4 md:p-6 border-t border-gray-700 bg-gray-800 md:rounded-b-xl sticky bottom-0 z-10 w-full mb-0 safe-area-bottom">
                            <button
                                type="submit"
                                form="product-form"
                                disabled={createMutation.isPending || updateMutation.isPending}
                                className="w-full bg-blue-600 hover:bg-blue-700 text-white font-bold py-3.5 rounded-xl transition-colors flex justify-center items-center gap-2 shadow-lg active:scale-[0.98]"
                            >
                                {(createMutation.isPending || updateMutation.isPending) && (
                                    <Loader2 size={20} className="animate-spin" />
                                )}
                                {editingProduct ? 'Сохранить изменения' : 'Создать товар'}
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
};
