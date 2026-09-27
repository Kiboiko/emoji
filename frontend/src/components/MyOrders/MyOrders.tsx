import React, { useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Clock, ChevronDown, ChevronUp, Star, Check } from 'lucide-react';
import { ordersApi } from '@/api/client';
import { useAuthStore } from '@/store/authStore';
import { useTelegram } from '@/hooks/useTelegram';
import type { Order } from '@/types';
import './MyOrders.css';

const ReviewForm: React.FC<{
    orderId: string;
    productId: string;
    productName: string;
    language: string;
    onSuccess: () => void;
}> = ({ orderId, productId, productName, language, onSuccess }) => {
    const [isVisible, setIsVisible] = useState(false);
    const [rating, setRating] = useState(5);
    const [text, setText] = useState('');
    const [isSubmitting, setIsSubmitting] = useState(false);
    const { haptic } = useTelegram();

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        if (text.length > 150) return;

        setIsSubmitting(true);
        try {
            // Simple sanitization: remove HTML-like tags
            const sanitizedText = text.replace(/<[^>]*>?/gm, '');

            const reviewsApi = (await import('@/api/client')).reviewsApi;
            await reviewsApi.createReview({
                order_id: orderId,
                product_id: productId,
                rating,
                text: sanitizedText
            });

            haptic.notification('success');
            onSuccess();
        } catch (error: any) {
            console.error('Failed to submit review:', error);
            if (error.response?.status === 400 && error.response?.data?.detail?.includes('already exists')) {
                onSuccess(); // Consider it done if already reviewed
            } else {
                haptic.notification('error');
                alert(language === 'ru' ? 'Ошибка при отправке отзыва' : 'Failed to submit review');
            }
        } finally {
            setIsSubmitting(false);
        }
    };

    if (!isVisible) {
        return (
            <button
                onClick={() => {
                    setIsVisible(true);
                    haptic.impact('light');
                }}
                className="btn-show-review"
            >
                {language === 'ru' ? 'Оставить отзыв' : 'Leave a review'}
            </button>
        );
    }

    return (
        <AnimatePresence>
            <motion.div
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: 'auto', opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
                className="overflow-hidden"
            >
                <form onSubmit={handleSubmit} className="review-form">
                    <h4>
                        {language === 'ru' ? `Оставить отзыв о ${productName}` : `Leave a review for ${productName}`}
                    </h4>

                    <div className="review-stars">
                        {[1, 2, 3, 4, 5].map((star) => (
                            <button
                                key={star}
                                type="button"
                                onClick={() => setRating(star)}
                                className={`star-btn ${rating >= star ? 'active' : 'inactive'}`}
                            >
                                <Star size={24} fill={rating >= star ? 'currentColor' : 'none'} />
                            </button>
                        ))}
                    </div>

                    <div className="review-text-container">
                        <textarea
                            value={text}
                            onChange={(e) => setText(e.target.value.slice(0, 150))}
                            placeholder={language === 'ru' ? 'Поделитесь впечатлениями (макс. 150 символов)' : 'Share your thoughts (max 150 chars)'}
                            className="review-textarea"
                            required
                        />
                        <span className={`char-count ${text.length >= 140 ? 'warning' : ''}`}>
                            {text.length}/150
                        </span>
                    </div>

                    <button
                        type="submit"
                        disabled={isSubmitting || !text.trim()}
                        className="btn-submit-review"
                    >
                        {isSubmitting ? (language === 'ru' ? 'Отправка...' : 'Submitting...') : (language === 'ru' ? 'Отправить отзыв' : 'Submit Review')}
                    </button>
                </form>
            </motion.div>
        </AnimatePresence>
    );
};


/**
 * Описание купленного товара, свёрнутое до трёх строк.

 * Целиком его в списке заказов держать нельзя: у товара с описанием на
 * полэкрана заказ перестал бы помещаться, а рядом ещё форма отзыва.
 */
const OrderDescription: React.FC<{ text: string; language: string }> = ({ text, language }) => {
    const [isExpanded, setIsExpanded] = useState(false);
    const isLong = text.length > 140;

    return (
        <div className={`order-item-desc ${isExpanded ? 'is-open' : ''}`}>
            <p>{text}</p>
            {isLong && (
                <button type="button" onClick={() => setIsExpanded(!isExpanded)}>
                    {isExpanded
                        ? (language === 'ru' ? 'Свернуть' : 'Show less')
                        : (language === 'ru' ? 'Показать полностью' : 'Show more')}
                </button>
            )}
        </div>
    );
};


/**
 * Мои заказы.
 *
 * Жили внутри Profile вместе со всем остальным и были самым длинным его
 * куском. Заказы — самостоятельный раздел, и на своём экране им хватает
 * места и на позиции, и на формы отзывов.
 */
export const MyOrders: React.FC = () => {
    const { language } = useAuthStore();
    const [orders, setOrders] = useState<Order[]>([]);
    const [visibleOrdersCount, setVisibleOrdersCount] = useState(5);
    const [reviewedItems, setReviewedItems] = useState<Set<string>>(new Set());

    useEffect(() => {
        ordersApi.getOrders()
            .then(setOrders)
            .catch((error) => console.error('Failed to load orders:', error));
    }, []);

    return (
                <div className="orders-section glass-card">
                    <h2>{language === 'ru' ? 'Мои заказы' : 'My Orders'}</h2>

                    {!orders || orders.length === 0 ? (
                        <p className="empty-message">
                            {language === 'ru' ? 'У вас пока нет заказов' : 'You have no orders yet'}
                        </p>
                    ) : (
                        <>
                            <div className="orders-list">
                                {orders.slice(0, visibleOrdersCount).map((order) => (
                                    <motion.div
                                        key={order.id}
                                        initial={{ opacity: 0, y: 10 }}
                                        animate={{ opacity: 1, y: 0 }}
                                        className="order-card"
                                    >
                                        <div className="order-header">
                                            <div className="order-date">
                                                <Clock size={14} />
                                                {new Date(order.created_at).toLocaleDateString()}
                                            </div>
                                            <div className={`order-status status-${order.status}`}>
                                                {order.status}
                                            </div>
                                        </div>

                                        <div className="order-total">
                                            ${Number(order.total_usdt).toFixed(2)}
                                        </div>

                                        <div className="order-items">
                                            {order.items?.map((item) => {
                                                const itemKey = `${order.id}-${item.product_id}`;
                                                const snapshot = item.product_snapshot;
                                                const pName = language === 'ru' ? snapshot?.name_ru : snapshot?.name_en;
                                                const pDesc = language === 'ru'
                                                    ? snapshot?.description_ru
                                                    : snapshot?.description_en;

                                                // Снимок сделан в момент покупки: продавец мог потом
                                                // сменить фотографии или вовсе снять товар с продажи,
                                                // а покупатель должен видеть то, за что заплатил.
                                                const shots = snapshot?.images?.length
                                                    ? snapshot.images
                                                    : (snapshot?.image_url ? [snapshot.image_url] : []);

                                                const isReviewed = item.is_reviewed || reviewedItems.has(itemKey);

                                                return (
                                                    <div key={item.id} className="order-item">
                                                        <div className="order-item-name">
                                                            {pName}
                                                            {item.quantity > 1 && (
                                                                <span className="order-item-count">
                                                                    × {item.quantity}
                                                                </span>
                                                            )}
                                                        </div>

                                                        {/* Фотографии и описание. Раньше в заказе стояло
                                                            одно название строкой — вспомнить по нему,
                                                            что именно купили, было нечем. */}
                                                        {shots.length > 0 && (
                                                            <div className="order-item-shots">
                                                                {shots.map((url, index) => (
                                                                    <img
                                                                        key={`${url}-${index}`}
                                                                        src={url}
                                                                        alt=""
                                                                        loading="lazy"
                                                                    />
                                                                ))}
                                                            </div>
                                                        )}

                                                        {pDesc && (
                                                            <OrderDescription text={pDesc} language={language} />
                                                        )}

                                                        {/* Review Section - Only for COMPLETED orders */}
                                                        {order.status === 'completed' && (
                                                            isReviewed ? (
                                                                <div className="review-badge">
                                                                    <Check size={12} />
                                                                    {language === 'ru' ? 'Отзыв оставлен' : 'Review left'}
                                                                </div>
                                                            ) : (
                                                                <ReviewForm
                                                                    orderId={order.id}
                                                                    productId={item.product_id}
                                                                    productName={pName || 'Product'}
                                                                    language={language}
                                                                    onSuccess={() => setReviewedItems(prev => new Set(prev).add(itemKey))}
                                                                />
                                                            )
                                                        )}
                                                    </div>
                                                );
                                            })}
                                        </div>
                                    </motion.div>
                                ))}
                            </div>

                            {orders.length > 5 && (
                                <button
                                    className="btn-show-more"
                                    onClick={() => {
                                        if (visibleOrdersCount >= orders.length) {
                                            setVisibleOrdersCount(5);
                                            // Optional: Scroll back to orders title
                                            document.querySelector('.orders-section')?.scrollIntoView({ behavior: 'smooth' });
                                        } else {
                                            setVisibleOrdersCount(prev => prev + 5);
                                        }
                                    }}
                                >
                                    {visibleOrdersCount >= orders.length ? (
                                        <>
                                            {language === 'ru' ? 'Скрыть заказы' : 'Hide Orders'}
                                            <ChevronUp size={16} />
                                        </>
                                    ) : (
                                        <>
                                            {language === 'ru' ? 'Показать еще' : 'Show More'}
                                            <ChevronDown size={16} />
                                        </>
                                    )}
                                </button>
                            )}
                        </>
                    )}
                </div>
    );
};
