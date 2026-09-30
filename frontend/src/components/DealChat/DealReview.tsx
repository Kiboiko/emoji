import React, { useState } from 'react';
import { Check, Star } from 'lucide-react';
import { reviewsApi } from '@/api/client';
import { useToastStore, errorText } from '@/store/toastStore';
import { useTelegram } from '@/hooks/useTelegram';
import type { Deal } from '@/types';

type T = (ru: string, en: string) => string;

/**
 * Отзыв о продавце по завершённой сделке — внизу её переписки.
 *
 * Здесь, а не в списке заказов: покупатель товара с рук думает о сделке, а не
 * о заказе, и оценивать продавца идёт туда, где с ним переписывался.
 * Бэкенд принимает отзыв только после завершения и только от покупателя.
 */
export const DealReview: React.FC<{
    deal: Deal;
    t: T;
    onDone: () => void;
}> = ({ deal, t, onDone }) => {
    const { haptic } = useTelegram();
    const showToast = useToastStore((s) => s.show);
    const [rating, setRating] = useState(0);
    const [text, setText] = useState('');
    const [busy, setBusy] = useState(false);

    if (deal.reviewed) {
        return (
            <div className="dchat-review-done">
                <Check size={16} />
                {t('Отзыв о продавце оставлен', 'Review left')}
            </div>
        );
    }

    const submit = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!rating || !text.trim() || !deal.product_id) return;
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
            onDone();
        } catch (err) {
            haptic.notification('error');
            showToast(errorText(err, t('Не удалось отправить отзыв', 'Failed to submit review')), 'error');
        } finally {
            setBusy(false);
        }
    };

    return (
        <form className="dchat-review" onSubmit={submit}>
            <span className="dchat-review-title">
                {t(`Оцените продавца «${deal.store?.name ?? ''}»`, `Rate “${deal.store?.name ?? 'the seller'}”`)}
            </span>
            <div className="dchat-stars">
                {[1, 2, 3, 4, 5].map((value) => (
                    <button
                        key={value}
                        type="button"
                        className={`dchat-star${value <= rating ? ' on' : ''}`}
                        onClick={() => setRating(value)}
                        aria-label={t(`${value} из 5`, `${value} of 5`)}
                    >
                        <Star size={26} fill="currentColor" />
                    </button>
                ))}
            </div>
            {rating > 0 && (
                <>
                    <textarea
                        className="dchat-review-text"
                        value={text}
                        onChange={(e) => setText(e.target.value)}
                        placeholder={t('Пара слов о сделке', 'A few words about the deal')}
                        maxLength={150}
                        rows={2}
                    />
                    <button type="submit" className="dchat-btn primary" disabled={busy || !text.trim()}>
                        {busy ? t('Отправляем…', 'Sending…') : t('Отправить отзыв', 'Submit review')}
                    </button>
                </>
            )}
        </form>
    );
};
