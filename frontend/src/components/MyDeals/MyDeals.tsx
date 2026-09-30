import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Package } from 'lucide-react';
import { useAuthStore } from '@/store/authStore';
import { useDealsStore } from '@/store/dealsStore';
import { errorText } from '@/store/toastStore';
import type { Deal } from '@/types';
import {
    author, listTime, statusLabel, statusTone,
} from '@/components/DealChat/dealFormat';
import './MyDeals.css';

/**
 * Список сделок — как список чатов в мессенджере.
 *
 * У каждой сделки своя переписка, и свежая наверху. Раньше здесь были
 * карточки с кнопкой «Писать в боте»: переписка шла через бота, и при двух
 * открытых сделках он переспрашивал, кому адресовано сообщение.
 */
export const MyDeals: React.FC = () => {
    const navigate = useNavigate();
    const { language, accessToken } = useAuthStore();
    const deals = useDealsStore((s) => s.deals);
    const unread = useDealsStore((s) => s.unread);
    const typing = useDealsStore((s) => s.typing);
    const [error, setError] = useState<string | null>(null);

    const t = (ru: string, en: string) => (language === 'ru' ? ru : en);

    // По токену, а не один раз: экран может открыться раньше, чем закончился
    // вход, — тогда запрос без токена получил бы 401 и список так и не появился
    useEffect(() => {
        if (!accessToken) return;
        useDealsStore.getState().loadDeals()
            .then(() => setError(null))
            .catch((e) => setError(errorText(e, t('Не удалось загрузить сделки', 'Failed to load deals'))));
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [accessToken]);

    if (error && !deals) return <p className="mydeals-empty">{error}</p>;
    if (!deals) {
        return (
            <div className="mydeals">
                {[0, 1, 2].map((i) => <div key={i} className="mydeals-row skeleton mydeals-skeleton" />)}
            </div>
        );
    }
    if (deals.length === 0) {
        return (
            <p className="mydeals-empty">
                {t(
                    'Сделок пока нет. Здесь появятся покупки и продажи товаров с рук — у каждой своя переписка.',
                    'No deals yet. Purchases and sales between users appear here, each with its own chat.',
                )}
            </p>
        );
    }

    const preview = (deal: Deal) => {
        if ((typing[deal.id] ?? 0) > Date.now()) {
            return <span className="mydeals-last typing">{t('печатает…', 'typing…')}</span>;
        }
        const last = deal.last_message;
        if (!last) return <span className="mydeals-last">{t('Переписки ещё нет', 'No messages yet')}</span>;
        const text = last.photo && !last.text ? t('Фото', 'Photo') : (last.text ?? '').replace(/`/g, '');
        return (
            <span className="mydeals-last">
                {last.from !== 'system' && (
                    <span className="mydeals-who">{author(deal, last.from, t)}: </span>
                )}
                {text}
            </span>
        );
    };

    return (
        <div className="mydeals">
            {deals.map((deal) => {
                const count = unread[deal.id] ?? 0;
                const when = deal.last_message?.created_at ?? deal.last_activity_at;
                return (
                    <button
                        key={deal.id}
                        type="button"
                        className="mydeals-row"
                        onClick={() => navigate(`/my/deals/${deal.id}`)}
                    >
                        <span className="mydeals-thumb">
                            {deal.product_image
                                ? <img src={deal.product_image} alt="" />
                                : <Package size={22} />}
                        </span>

                        <span className="mydeals-main">
                            <span className="mydeals-name">{deal.product_name}</span>
                            {preview(deal)}
                            <span className="mydeals-foot">
                                <span className={`dchat-chip ${statusTone(deal.status)}`}>
                                    {statusLabel(deal.status, t)}
                                </span>
                                <span className="mydeals-num">
                                    №{deal.number}
                                    {deal.role === 'buyer' && deal.store ? ` · ${deal.store.name}` : ''}
                                    {deal.role === 'seller' ? ` · ${t('продажа', 'sale')}` : ''}
                                </span>
                            </span>
                        </span>

                        <span className="mydeals-side">
                            <span className="mydeals-time">{listTime(when, language, t)}</span>
                            {count > 0 && <span className="mydeals-count">{count}</span>}
                        </span>
                    </button>
                );
            })}
        </div>
    );
};
