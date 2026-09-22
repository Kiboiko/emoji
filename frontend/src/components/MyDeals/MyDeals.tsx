import React, { useEffect, useState } from 'react';
import { Handshake, Clock, MessageCircle, AlertTriangle, Check, Send, Star } from 'lucide-react';
import { p2pApi, reviewsApi } from '@/api/client';
import { useAuthStore } from '@/store/authStore';
import { useToastStore, errorText } from '@/store/toastStore';
import { useTelegram } from '@/hooks/useTelegram';
import type { Deal } from '@/types';
import './MyDeals.css';

const OPEN_STATUSES = ['paid_escrow', 'chat_opened', 'delivered_claimed', 'disputed'];

export const MyDeals: React.FC = () => {
    const { language } = useAuthStore();
    const { haptic } = useTelegram();
    const [deals, setDeals] = useState<Deal[]>([]);
    const [loading, setLoading] = useState(true);
    const [busy, setBusy] = useState<string | null>(null);

    const t = (ru: string, en: string) => (language === 'ru' ? ru : en);

    const load = () =>
        p2pApi.getMyDeals().then(setDeals).catch(() => setDeals([]));

    useEffect(() => {
        load().finally(() => setLoading(false));
    }, []);

    const act = async (deal: Deal, action: 'delivered' | 'confirm' | 'dispute' | 'activate') => {
        setBusy(deal.id);
        try {
            if (action === 'delivered') await p2pApi.markDelivered(deal.id);
            if (action === 'confirm') await p2pApi.confirmReceipt(deal.id);
            if (action === 'activate') await p2pApi.setActiveDeal(deal.id);
            if (action === 'dispute') {
                const reason = window.prompt(
                    t('Опишите проблему (минимум 10 символов)', 'Describe the problem (min 10 chars)'),
                );
                if (!reason || reason.trim().length < 10) return;
                await p2pApi.openDispute(deal.id, reason.trim());
            }
            haptic.notification('success');
            await load();
        } catch (e: any) {
            haptic.notification('error');
            const detail = e?.response?.data?.detail;
            window.alert(typeof detail === 'string' ? detail : t('Не удалось', 'Failed'));
        } finally {
            setBusy(null);
        }
    };

    if (loading || deals.length === 0) return null;

    const label: Record<string, string> = {
        paid_escrow: t('Оплачено', 'Paid'),
        chat_opened: t('Переписка', 'Chat open'),
        delivered_claimed: t('Отправлено', 'Shipped'),
        confirmed: t('Подтверждено', 'Confirmed'),
        released: t('Завершена', 'Completed'),
        disputed: t('Спор', 'Dispute'),
        refunded: t('Возврат', 'Refunded'),
        cancelled: t('Отменена', 'Cancelled'),
    };

    return (
        <div className="deals-section glass-card">
            <h2 className="deals-title">
                <Handshake size={18} />
                {t('Мои сделки', 'My Deals')}
            </h2>

            <div className="deals-list">
                {deals.map((deal) => {
                    const open = OPEN_STATUSES.includes(deal.status);
                    const isBuyer = deal.role === 'buyer';
                    const working = busy === deal.id;

                    return (
                        <div key={deal.id} className={`deal-item deal-${deal.status}`}>
                            <div className="deal-head">
                                <span className="deal-number">№{deal.number}</span>
                                <span className={`deal-badge badge-${deal.status}`}>
                                    {label[deal.status] ?? deal.status}
                                </span>
                            </div>

                            <div className="deal-product">{deal.product_name}</div>

                            <div className="deal-meta">
                                <span>{isBuyer ? t('Покупка', 'Buying') : t('Продажа', 'Selling')}</span>
                                <span className="deal-amount">
                                    {isBuyer ? deal.amount_ton : deal.seller_amount_ton} TON
                                </span>
                            </div>

                            {deal.status === 'delivered_claimed' && deal.confirm_deadline_at && (
                                <div className="deal-deadline">
                                    <Clock size={13} />
                                    {t('Подтвердить до ', 'Confirm before ')}
                                    {new Date(deal.confirm_deadline_at).toLocaleDateString(
                                        language === 'ru' ? 'ru-RU' : 'en-US',
                                    )}
                                </div>
                            )}

                            {deal.status === 'disputed' && (
                                <div className="deal-dispute">
                                    <AlertTriangle size={13} />
                                    {t('Спор на рассмотрении', 'Dispute under review')}
                                </div>
                            )}

                            {open && (
                                <div className="deal-actions">
                                    {/* Переписка идёт в боте: платформа передаёт сообщения
                                        между сторонами, контакты не раскрываются */}
                                    <button
                                        className="deal-btn deal-btn-ghost"
                                        disabled={working}
                                        onClick={() => act(deal, 'activate')}
                                    >
                                        <MessageCircle size={14} />
                                        {t('Писать в боте', 'Chat in bot')}
                                    </button>

                                    {!isBuyer && deal.status !== 'delivered_claimed' && (
                                        <button
                                            className="deal-btn"
                                            disabled={working}
                                            onClick={() => act(deal, 'delivered')}
                                        >
                                            <Send size={14} />
                                            {t('Я отправил', 'Shipped')}
                                        </button>
                                    )}

                                    {isBuyer && deal.status !== 'disputed' && (
                                        <button
                                            className="deal-btn"
                                            disabled={working}
                                            onClick={() => act(deal, 'confirm')}
                                        >
                                            <Check size={14} />
                                            {t('Получил', 'Received')}
                                        </button>
                                    )}

                                    {deal.status !== 'disputed' && (
                                        <button
                                            className="deal-btn deal-btn-danger"
                                            disabled={working}
                                            onClick={() => act(deal, 'dispute')}
                                        >
                                            <AlertTriangle size={14} />
                                            {t('Проблема', 'Problem')}
                                        </button>
                                    )}
                                </div>
                            )}

                            {/* Отзыв о продавце — здесь, а не в списке заказов.
                                Покупатель товара с рук думает о сделке, а не о
                                заказе, и искать оценку продавца идёт сюда. */}
                            {isBuyer && deal.status === 'released' && (
                                deal.reviewed ? (
                                    <div className="deal-reviewed">
                                        <Check size={13} />
                                        {t('Отзыв оставлен', 'Review left')}
                                    </div>
                                ) : (
                                    <DealReview
                                        deal={deal}
                                        language={language}
                                        onDone={load}
                                    />
                                )
                            )}

                            {isBuyer && open && (
                                <p className="deal-hint">
                                    {t(
                                        'Деньги удерживаются платформой до подтверждения получения.',
                                        'Funds are held by the platform until you confirm receipt.',
                                    )}
                                </p>
                            )}
                        </div>
                    );
                })}
            </div>
        </div>
    );
};

/**
 * Отзыв о продавце по завершённой сделке.
 *
 * Бэкенд принимает его только после статуса released и только от покупателя
 * — после возврата по спору оценивать нечего, сделка не состоялась.
 */
const DealReview: React.FC<{
    deal: Deal;
    language: string;
    onDone: () => Promise<unknown>;
}> = ({ deal, language, onDone }) => {
    const { haptic } = useTelegram();
    const showToast = useToastStore((s) => s.show);
    const [open, setOpen] = useState(false);
    const [rating, setRating] = useState(5);
    const [text, setText] = useState('');
    const [busy, setBusy] = useState(false);

    const t = (ru: string, en: string) => (language === 'ru' ? ru : en);

    const submit = async (e: React.FormEvent) => {
        e.preventDefault();
        setBusy(true);
        try {
            await reviewsApi.createReview({
                product_id: deal.product_id,
                order_id: deal.order_id,
                text: text.trim(),
                rating,
            });
            haptic.notification('success');
            showToast(t('Спасибо за отзыв', 'Thanks for the review'), 'success');
            await onDone();
        } catch (err) {
            haptic.notification('error');
            showToast(errorText(err, t('Не удалось отправить отзыв', 'Failed to submit review')), 'error');
        } finally {
            setBusy(false);
        }
    };

    if (!open) {
        return (
            <button className="deal-btn deal-btn-ghost" onClick={() => setOpen(true)}>
                <Star size={14} />
                {t('Оценить продавца', 'Rate the seller')}
            </button>
        );
    }

    return (
        <form className="deal-review" onSubmit={submit}>
            <div className="deal-stars">
                {[1, 2, 3, 4, 5].map((value) => (
                    <button
                        key={value}
                        type="button"
                        className={`deal-star ${value <= rating ? 'on' : ''}`}
                        onClick={() => setRating(value)}
                        aria-label={`${value}`}
                    >
                        <Star size={20} fill={value <= rating ? 'currentColor' : 'none'} />
                    </button>
                ))}
            </div>

            <textarea
                className="deal-review-text"
                value={text}
                onChange={(e) => setText(e.target.value)}
                placeholder={t('Как прошла сделка?', 'How did it go?')}
                maxLength={500}
                rows={2}
            />

            <div className="deal-review-actions">
                <button className="deal-btn" type="submit" disabled={busy}>
                    {busy ? t('Отправляем...', 'Sending...') : t('Отправить', 'Submit')}
                </button>
                <button
                    className="deal-btn deal-btn-ghost"
                    type="button"
                    onClick={() => setOpen(false)}
                >
                    {t('Отмена', 'Cancel')}
                </button>
            </div>
        </form>
    );
};
