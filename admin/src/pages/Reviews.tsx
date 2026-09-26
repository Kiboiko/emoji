import React, { useState, useEffect, useCallback } from 'react';
import { adminApi } from '../api/axios';
import { Loader2, Trash2, Plus, X, Star } from 'lucide-react';
import { DataTable, type Column } from '../components/ui/DataTable';

interface ReviewUser {
    first_name: string;
}

interface ReviewProduct {
    name_ru: string;
}

interface Review {
    id: string;
    user_id: string | null;
    user: ReviewUser | null;
    product_id: string;
    product: ReviewProduct | null;
    order_id: string | null;
    text: string;
    rating: number | null;
    is_hidden: boolean;
    is_fake: boolean;
    fake_username: string | null;
    fake_quantity: number | null;
    created_at: string;
}

interface ProductOption {
    id: string;
    name_ru: string;
    price_usdt: number;
}

export const Reviews: React.FC = () => {
    const [reviews, setReviews] = useState<Review[]>([]);
    const [loading, setLoading] = useState(true);
    const [deletingId, setDeletingId] = useState<string | null>(null);

    const [currentPage, setCurrentPage] = useState(1);
    const ITEMS_PER_PAGE = 10;

    // Modal state
    const [showModal, setShowModal] = useState(false);
    const [products, setProducts] = useState<ProductOption[]>([]);
    const [productsLoading, setProductsLoading] = useState(false);
    const [submitting, setSubmitting] = useState(false);

    // Form state
    const [fakeUsername, setFakeUsername] = useState('');
    const [reviewText, setReviewText] = useState('');
    const [selectedProductId, setSelectedProductId] = useState('');
    const [fakeQuantity, setFakeQuantity] = useState<number | ''>('');
    const [selectedRating, setSelectedRating] = useState<number>(0);
    const [hoverRating, setHoverRating] = useState<number>(0);

    const fetchReviews = useCallback(async () => {
        try {
            setLoading(true);
            const response = await adminApi.getReviews();
            setReviews(response.data);
            setCurrentPage(1);
        } catch (error) {
            console.error('Failed to fetch reviews:', error);
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        fetchReviews();
    }, [fetchReviews]);

    const fetchProducts = async () => {
        try {
            setProductsLoading(true);
            const response = await adminApi.getProductsList();
            const items = response.data.items || response.data || [];
            setProducts(items.map((p: any) => ({
                id: p.id,
                name_ru: p.name_ru,
                price_usdt: p.price_usdt,
            })));
        } catch (error) {
            console.error('Failed to fetch products:', error);
        } finally {
            setProductsLoading(false);
        }
    };

    const openModal = () => {
        setFakeUsername('');
        setReviewText('');
        setSelectedProductId('');
        setFakeQuantity('');
        setSelectedRating(0);
        setHoverRating(0);
        setShowModal(true);
        fetchProducts();
    };

    const closeModal = () => {
        setShowModal(false);
    };

    const handleSubmitFakeReview = async (e: React.FormEvent) => {
        e.preventDefault();

        if (!selectedProductId || !fakeUsername.trim() || !reviewText.trim()) {
            alert('Заполните все обязательные поля');
            return;
        }

        try {
            setSubmitting(true);
            await adminApi.createFakeReview({
                product_id: selectedProductId,
                fake_username: fakeUsername.trim(),
                text: reviewText.trim(),
                rating: selectedRating > 0 ? selectedRating : null,
                fake_quantity: fakeQuantity ? Number(fakeQuantity) : null,
            });
            closeModal();
            fetchReviews();
        } catch (error: any) {
            console.error('Failed to create fake review:', error);
            alert(error.response?.data?.detail || 'Ошибка при создании отзыва');
        } finally {
            setSubmitting(false);
        }
    };

    const handleDelete = async (id: string) => {
        if (!confirm('Удалить отзыв?')) return;

        try {
            setDeletingId(id);
            await adminApi.deleteReview(id);
            setReviews(prev => prev.filter(r => r.id !== id));
        } catch (error) {
            console.error('Failed to delete review:', error);
            alert('Ошибка при удалении отзыва');
        } finally {
            setDeletingId(null);
        }
    };

    const renderStars = (rating: number | null) => {
        if (rating === null) return <span className="text-gray-500">-</span>;
        return (
            <span className="text-yellow-400">
                {'★'.repeat(rating)}{'☆'.repeat(5 - rating)}
            </span>
        );
    };

    const getDisplayName = (review: Review) => {
        if (review.is_fake && review.fake_username) {
            return review.fake_username;
        }
        return review.user?.first_name || 'Unknown';
    };

    // Pagination
    const totalPages = Math.ceil(reviews.length / ITEMS_PER_PAGE);
    const paginatedReviews = reviews.slice(
        (currentPage - 1) * ITEMS_PER_PAGE,
        currentPage * ITEMS_PER_PAGE
    );

    if (loading) return (
        <div className="flex justify-center items-center h-64">
            <Loader2 className="animate-spin text-blue-500" size={48} />
        </div>
    );

    const columns: Column<Review>[] = [
        {
            key: 'user',
            title: 'Пользователь',
            // Заголовок карточки на телефоне — подпись ему не нужна
            wide: true,
            render: (review) => (
                <div>
                    <span className="font-medium text-white">{getDisplayName(review)}</span>
                    {review.is_fake && (
                        <span className="text-xs text-purple-400 ml-2">фейк</span>
                    )}
                    {review.is_hidden && (
                        <span className="text-xs text-yellow-400 ml-1">скрыт</span>
                    )}
                </div>
            ),
        },
        {
            key: 'product',
            title: 'Товар',
            render: (review) => (
                <span className="text-sm text-gray-300">{review.product?.name_ru || '—'}</span>
            ),
        },
        {
            key: 'text',
            title: 'Текст',
            wide: true,
            render: (review) => (
                /* На телефоне текст показываем целиком: отзыв в одну
                   обрезанную строку не даёт понять, за что его удалять */
                <div className="text-sm text-gray-300 md:max-w-xs md:truncate" title={review.text}>
                    {review.text}
                </div>
            ),
        },
        {
            key: 'rating',
            title: 'Рейтинг',
            render: (review) => <span className="text-sm">{renderStars(review.rating)}</span>,
        },
        {
            key: 'created_at',
            title: 'Дата',
            render: (review) => (
                <span className="text-sm text-gray-400 whitespace-nowrap">
                    {new Date(review.created_at).toLocaleString('ru-RU')}
                </span>
            ),
        },
        {
            key: 'actions',
            title: 'Действия',
            className: 'text-right',
            wide: true,
            render: (review) => (
                <div className="flex md:justify-end">
                    <button
                        onClick={() => handleDelete(review.id)}
                        disabled={deletingId === review.id}
                        className="p-2 text-red-400 hover:bg-red-500/10 rounded-lg transition-colors disabled:opacity-50"
                        title="Удалить отзыв"
                        aria-label="Удалить отзыв"
                    >
                        {deletingId === review.id ? (
                            <Loader2 className="animate-spin" size={18} />
                        ) : (
                            <Trash2 size={18} />
                        )}
                    </button>
                </div>
            ),
        },
    ];

    return (
        <div>
            <div className="flex flex-wrap justify-between items-center gap-3 mb-6">
                <h1 className="text-2xl md:text-3xl font-bold">Отзывы</h1>
                <div className="flex items-center gap-3 flex-wrap">
                    <span className="text-gray-400 text-sm">Всего: {reviews.length}</span>
                    <button
                        onClick={openModal}
                        className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg transition-colors"
                    >
                        <Plus size={18} />
                        Создать отзыв
                    </button>
                </div>
            </div>

            <DataTable<Review>
                columns={columns}
                rows={paginatedReviews}
                rowKey={(review) => review.id}
                emptyText="Отзывов нет"
            />

            {totalPages > 1 && (
                <div className="flex justify-center gap-2 mt-8">
                    <button
                        onClick={() => setCurrentPage(p => Math.max(1, p - 1))}
                        disabled={currentPage === 1}
                        className="px-4 py-2 bg-gray-800 text-white rounded-lg disabled:opacity-50 hover:bg-gray-700"
                    >
                        Назад
                    </button>
                    <span className="px-4 py-2 text-gray-400">
                        Страница {currentPage} из {totalPages}
                    </span>
                    <button
                        onClick={() => setCurrentPage(p => Math.min(totalPages, p + 1))}
                        disabled={currentPage === totalPages}
                        className="px-4 py-2 bg-gray-800 text-white rounded-lg disabled:opacity-50 hover:bg-gray-700"
                    >
                        Вперед
                    </button>
                </div>
            )}

            {/* Create Fake Review Modal */}
            {showModal && (
                <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
                    <div className="bg-gray-800 rounded-xl border border-gray-700 w-full max-w-lg max-h-[90vh] overflow-y-auto">
                        <div className="flex items-center justify-between p-6 border-b border-gray-700">
                            <h2 className="text-xl font-bold text-white">Создать отзыв</h2>
                            <button
                                onClick={closeModal}
                                className="p-1 text-gray-400 hover:text-white transition-colors"
                            >
                                <X size={20} />
                            </button>
                        </div>

                        <form onSubmit={handleSubmitFakeReview} className="p-6 space-y-5">
                            {/* Product selector */}
                            <div>
                                <label className="block text-sm font-medium text-gray-300 mb-2">
                                    Товар <span className="text-red-400">*</span>
                                </label>
                                {productsLoading ? (
                                    <div className="flex items-center gap-2 text-gray-400 text-sm">
                                        <Loader2 className="animate-spin" size={16} />
                                        Загрузка товаров...
                                    </div>
                                ) : (
                                    <select
                                        value={selectedProductId}
                                        onChange={(e) => setSelectedProductId(e.target.value)}
                                        className="w-full bg-gray-700 border border-gray-600 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:border-blue-500"
                                        required
                                    >
                                        <option value="">Выберите товар</option>
                                        {products.map((p) => (
                                            <option key={p.id} value={p.id}>
                                                {p.name_ru} (${p.price_usdt})
                                            </option>
                                        ))}
                                    </select>
                                )}
                            </div>

                            {/* Fake username */}
                            <div>
                                <label className="block text-sm font-medium text-gray-300 mb-2">
                                    Имя покупателя <span className="text-red-400">*</span>
                                </label>
                                <input
                                    type="text"
                                    value={fakeUsername}
                                    onChange={(e) => setFakeUsername(e.target.value)}
                                    placeholder="Введите имя"
                                    maxLength={100}
                                    className="w-full bg-gray-700 border border-gray-600 rounded-lg px-4 py-2.5 text-white placeholder-gray-500 focus:outline-none focus:border-blue-500"
                                    required
                                />
                            </div>

                            {/* Review text */}
                            <div>
                                <label className="block text-sm font-medium text-gray-300 mb-2">
                                    Текст отзыва <span className="text-red-400">*</span>
                                </label>
                                <textarea
                                    value={reviewText}
                                    onChange={(e) => setReviewText(e.target.value)}
                                    placeholder="Введите текст отзыва"
                                    maxLength={500}
                                    rows={4}
                                    className="w-full bg-gray-700 border border-gray-600 rounded-lg px-4 py-2.5 text-white placeholder-gray-500 focus:outline-none focus:border-blue-500 resize-none"
                                    required
                                />
                                <div className="text-xs text-gray-500 mt-1 text-right">
                                    {reviewText.length}/500
                                </div>
                            </div>

                            {/* Quantity */}
                            <div>
                                <label className="block text-sm font-medium text-gray-300 mb-2">
                                    Количество купленного
                                </label>
                                <input
                                    type="number"
                                    value={fakeQuantity}
                                    onChange={(e) => setFakeQuantity(e.target.value ? Number(e.target.value) : '')}
                                    placeholder="Необязательно"
                                    min={1}
                                    className="w-full bg-gray-700 border border-gray-600 rounded-lg px-4 py-2.5 text-white placeholder-gray-500 focus:outline-none focus:border-blue-500"
                                />
                            </div>

                            {/* Rating */}
                            <div>
                                <label className="block text-sm font-medium text-gray-300 mb-2">
                                    Оценка
                                </label>
                                <div className="flex items-center gap-1">
                                    {[1, 2, 3, 4, 5].map((star) => (
                                        <button
                                            key={star}
                                            type="button"
                                            onClick={() => setSelectedRating(selectedRating === star ? 0 : star)}
                                            onMouseEnter={() => setHoverRating(star)}
                                            onMouseLeave={() => setHoverRating(0)}
                                            className="p-0.5 transition-colors"
                                        >
                                            <Star
                                                size={28}
                                                className={
                                                    (hoverRating || selectedRating) >= star
                                                        ? 'text-yellow-400 fill-yellow-400'
                                                        : 'text-gray-600'
                                                }
                                            />
                                        </button>
                                    ))}
                                    {selectedRating > 0 && (
                                        <span className="text-sm text-gray-400 ml-2">{selectedRating}/5</span>
                                    )}
                                </div>
                            </div>

                            {/* Submit */}
                            <div className="flex justify-end gap-3 pt-2">
                                <button
                                    type="button"
                                    onClick={closeModal}
                                    className="px-4 py-2.5 bg-gray-700 hover:bg-gray-600 text-gray-300 rounded-lg transition-colors"
                                >
                                    Отмена
                                </button>
                                <button
                                    type="submit"
                                    disabled={submitting}
                                    className="flex items-center gap-2 px-6 py-2.5 bg-blue-600 hover:bg-blue-700 text-white rounded-lg transition-colors disabled:opacity-50"
                                >
                                    {submitting && <Loader2 className="animate-spin" size={16} />}
                                    Создать
                                </button>
                            </div>
                        </form>
                    </div>
                </div>
            )}
        </div>
    );
};
