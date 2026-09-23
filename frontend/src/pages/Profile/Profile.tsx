import React, { useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Copy, Clock, Download, X, Wallet, ChevronDown, ChevronUp, Star, Check } from 'lucide-react';
import { usersApi, ordersApi } from '@/api/client';
import { useAuthStore } from '@/store/authStore';
import { useToastStore } from '@/store/toastStore';
import { useTelegram } from '@/hooks/useTelegram';
import { MySubscriptions } from '@/components/MySubscriptions/MySubscriptions';
import { MyDeals } from '@/components/MyDeals/MyDeals';
import { SellerCabinet } from '@/components/SellerCabinet/SellerCabinet';
import { ChannelCabinet } from '@/components/ChannelCabinet/ChannelCabinet';
import type { ReferralStats, Order } from '@/types';
import './Profile.css';

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

export const Profile: React.FC = () => {
    const { user, language } = useAuthStore();
    const showToast = useToastStore((s) => s.show);
    const { haptic } = useTelegram();
    const [stats, setStats] = useState<ReferralStats | null>(null);
    const [orders, setOrders] = useState<Order[]>([]);
    const [visibleOrdersCount, setVisibleOrdersCount] = useState(5);
    const [isModalOpen, setIsModalOpen] = useState(false);
    const [walletAddress, setWalletAddress] = useState('');
    const [withdrawAmount, setWithdrawAmount] = useState<string>('');
    const [isSubmitting, setIsSubmitting] = useState(false);
    const [reviewedItems, setReviewedItems] = useState<Set<string>>(new Set());

    useEffect(() => {
        loadStats();
    }, []);

    const loadStats = async () => {
        try {
            const [statsData, ordersData] = await Promise.all([
                usersApi.getReferralStats(),
                ordersApi.getOrders(),
            ]);
            setStats(statsData);
            setOrders(ordersData);
        } catch (error) {
            console.error('Failed to load data:', error);
        }
    };

    const copyReferralLink = async () => {
        const botUsername = import.meta.env.VITE_BOT_USERNAME || 'your_bot';
        const link = `https://t.me/${botUsername}?start=ref_${user?.referral_code}`;

        // navigator.clipboard есть не везде: внутри Telegram WebView он может
        // отсутствовать или отклонить вызов. Промис раньше не ожидался, поэтому
        // отказ уходил в никуда — ссылка молча не копировалась.
        try {
            if (navigator.clipboard?.writeText) {
                await navigator.clipboard.writeText(link);
            } else {
                const field = document.createElement('textarea');
                field.value = link;
                field.setAttribute('readonly', '');
                field.style.position = 'fixed';
                field.style.opacity = '0';
                document.body.appendChild(field);
                field.select();
                document.execCommand('copy');
                document.body.removeChild(field);
            }
            haptic.notification('success');
            showToast(language === 'ru' ? 'Ссылка скопирована' : 'Link copied', 'success');
        } catch {
            haptic.notification('error');
            showToast(
                language === 'ru' ? 'Не удалось скопировать ссылку' : 'Failed to copy link',
                'error',
            );
        }
    };

    const openWithdrawModal = () => {
        setIsModalOpen(true);
        haptic.impact('light');
    };

    const closeWithdrawModal = () => {
        setIsModalOpen(false);
        setWalletAddress('');
        setWithdrawAmount('');
    };

    const handleWithdraw = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!stats) return;

        const amount = parseFloat(withdrawAmount);

        // Validation: Must be > 0 and <= balance
        if (isNaN(amount) || amount <= 0) {
            haptic.notification('error');
            alert(language === 'ru' ? 'Сумма должна быть больше 0' : 'Amount must be greater than 0');
            return;
        }

        if (amount > stats.total_earnings) {
            haptic.notification('error');
            alert(language === 'ru' ? 'Недостаточно средств на балансе' : 'Insufficient balance');
            return;
        }

        setIsSubmitting(true);
        haptic.impact('heavy');

        try {
            if (!walletAddress.trim()) {
                alert(language === 'ru' ? 'Введите адрес кошелька' : 'Enter wallet address');
                return;
            }

            const withdrawalsApi = (await import('@/api/client')).withdrawalsApi;
            await withdrawalsApi.requestWithdrawal({
                amount: amount,
                wallet: walletAddress
            });

            haptic.notification('success');

            // Show toast
            const toast = document.createElement('div');
            toast.className = 'toast success';
            toast.textContent = language === 'ru' ? 'Заявка на вывод отправлена!' : 'Withdrawal request sent!';
            document.body.appendChild(toast);
            setTimeout(() => toast.remove(), 3000);

            closeWithdrawModal();
            loadStats(); // Refresh stats to reflect deducted balance
        } catch (error: any) {
            console.error('Withdrawal failed:', error);
            haptic.notification('error');

            let errorMessage = language === 'ru' ? 'Ошибка при отправке заявки' : 'Failed to send request';

            if (error.response?.data?.detail) {
                const detail = error.response.data.detail;
                if (Array.isArray(detail) && detail.length > 0) {
                    // Handle FastAPI 422 errors
                    errorMessage = detail[0].msg || JSON.stringify(detail);
                } else if (typeof detail === 'string') {
                    errorMessage = detail;
                } else {
                    errorMessage = JSON.stringify(detail);
                }
            }

            alert(errorMessage);
        } finally {
            setIsSubmitting(false);
        }
    };

    return (
        <div className="profile-page">
            <div className="container">
                <div className="profile-title-mobile">
                    <h1>{language === 'ru' ? 'Профиль' : 'Profile'}</h1>
                </div>

                {/* Баланс реферальной программы */}
                <section className="refwallet-card">
                    <div className="refwallet-head">
                        <span className="refwallet-label">
                            <span className="refwallet-dot" aria-hidden="true" />
                            {language === 'ru' ? 'Доступно к выводу' : 'Available to withdraw'}
                        </span>
                        {stats !== null && stats.total_earnings > 0 && (
                            <span className="refwallet-pill">
                                {language === 'ru' ? 'готово' : 'ready'}
                            </span>
                        )}
                    </div>

                    {/* Пока статистика не пришла, показывать $0.00 нельзя:
                        человек с балансом видит ноль и решает, что деньги
                        пропали. Скелетон честнее — «ещё не знаем». */}
                    {stats === null ? (
                        <div className="skeleton refwallet-skeleton" />
                    ) : (
                        <div className="refwallet-amount">
                            {stats.total_earnings.toFixed(2)}
                            <span className="refwallet-currency">$</span>
                        </div>
                    )}

                    {/* Второй уровень включается настройкой и чаще выключен —
                        показываем строку, только когда по нему что-то есть */}
                    {!!stats?.level2_earnings && (
                        <div className="refwallet-note">
                            {language === 'ru'
                                ? 'из них со второго уровня'
                                : 'of which from level 2'}: ${stats.level2_earnings.toFixed(2)}
                        </div>
                    )}

                    <button
                        className="refwallet-cta"
                        onClick={openWithdrawModal}
                        disabled={stats === null || stats.total_earnings <= 0}
                    >
                        <Download size={18} />
                        {language === 'ru' ? 'Вывести средства' : 'Withdraw funds'}
                    </button>
                </section>

                {/* Показываем только то, что действительно считается на сервере:
                    выдумывать «прирост за неделю» без таких данных нельзя. */}
                <div className="stat-row">
                    <div className="stat-tile">
                        <span className="stat-label">{language === 'ru' ? 'Рефералов' : 'Referrals'}</span>
                        <span className="stat-value">{stats?.referral_count ?? '—'}</span>
                    </div>
                    <div className="stat-tile">
                        <span className="stat-label">{language === 'ru' ? 'Ставка' : 'Rate'}</span>
                        <span className="stat-value accent">
                            {stats ? `${stats.referral_percent ?? 0}%` : '—'}
                        </span>
                    </div>
                    <div className="stat-tile">
                        <span className="stat-label">{language === 'ru' ? 'Покупок' : 'Purchases'}</span>
                        <span className="stat-value">{stats?.paid_orders_count ?? '—'}</span>
                    </div>
                </div>

                <section className="reflink">
                    <div className="reflink-head">
                        <span className="reflink-title">
                            {language === 'ru' ? 'Моя реферальная ссылка' : 'My referral link'}
                        </span>
                        <span className="reflink-hint">
                            {language === 'ru' ? 'копируйте и делитесь' : 'copy and share'}
                        </span>
                    </div>
                    <div className="reflink-row">
                        <span className="reflink-text">
                            <span className="reflink-prefix">
                                t.me/{import.meta.env.VITE_BOT_USERNAME || 'your_bot'}?start=ref_
                            </span>
                            <span className="reflink-code">
                                {user?.referral_code || user?.telegram_id}
                            </span>
                        </span>
                        <button className="reflink-copy" onClick={copyReferralLink}>
                            <Copy size={14} />
                            {language === 'ru' ? 'Копировать' : 'Copy'}
                        </button>
                    </div>
                </section>

                {/* Orders Section */}
                <MyDeals />

                <SellerCabinet />

                {/* Рядом с кабинетом продавца: оба — «что я продаю на площадке» */}
                <ChannelCabinet />

                <MySubscriptions />

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
                                                const pName = language === 'ru' ? item.product_snapshot?.name_ru : item.product_snapshot?.name_en;

                                                const isReviewed = item.is_reviewed || reviewedItems.has(itemKey);

                                                return (
                                                    <div key={item.id} className="flex flex-col gap-1 mb-4 last:mb-0">
                                                        <div className="order-item-name">
                                                            • {pName}
                                                            {item.quantity > 1 && ` x${item.quantity}`}
                                                        </div>

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
            </div>

            <div className="bottom-nav-spacer" />

            {/* Withdraw Modal */}
            <AnimatePresence>
                {isModalOpen && (
                    <div className="modal-overlay" onClick={closeWithdrawModal}>
                        <motion.div
                            className="withdraw-modal"
                            initial={{ scale: 0.9, opacity: 0 }}
                            animate={{ scale: 1, opacity: 1 }}
                            exit={{ scale: 0.9, opacity: 0 }}
                            onClick={(e) => e.stopPropagation()}
                        >
                            <div className="modal-header">
                                <h3>{language === 'ru' ? 'Вывод средств' : 'Withdraw Funds'}</h3>
                                <button className="btn-close" onClick={closeWithdrawModal}>
                                    <X size={20} />
                                </button>
                            </div>

                            <form onSubmit={handleWithdraw} className="withdraw-form">
                                <div className="form-group">
                                    <label>
                                        <Wallet size={16} />
                                        {language === 'ru' ? 'Кошелек (TRC20)' : 'Wallet Address (TRC20)'}
                                    </label>
                                    <input
                                        type="text"
                                        value={walletAddress}
                                        onChange={(e) => setWalletAddress(e.target.value)}
                                        placeholder="T..."
                                        className="withdraw-input"
                                        required
                                    />
                                </div>

                                <div className="form-group">
                                    <label>
                                        <Clock size={16} />
                                        {language === 'ru' ? 'Сумма вывода' : 'Withdraw Amount'}
                                    </label>
                                    <div className="withdraw-amount-container">
                                        <input
                                            type="number"
                                            value={withdrawAmount}
                                            onChange={(e) => setWithdrawAmount(e.target.value)}
                                            placeholder="0.00"
                                            className="withdraw-input"
                                            step="0.01"
                                            required
                                        />
                                        <span className="withdraw-currency">USDT</span>
                                    </div>
                                    <div className="available-balance-hint">
                                        {language === 'ru' ? 'Доступно:' : 'Available:'}
                                        <span>${(stats?.total_earnings || 0).toFixed(2)}</span>
                                    </div>
                                </div>

                                <button
                                    type="submit"
                                    className="btn-submit-withdraw"
                                    disabled={isSubmitting}
                                >
                                    {isSubmitting ? (
                                        <div className="loader-small"></div>
                                    ) : (
                                        language === 'ru' ? 'Вывод' : 'Withdraw'
                                    )}
                                </button>
                            </form>
                        </motion.div>
                    </div>
                )}
            </AnimatePresence>
        </div>
    );
};
