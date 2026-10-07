import React, { useCallback, useEffect, useState } from 'react';
import { useLocation, useNavigate, useParams } from 'react-router-dom';
import { ArrowLeft, Copy, Package } from 'lucide-react';
import { ordersApi } from '@/api/client';
import { useAuthStore } from '@/store/authStore';
import { useToastStore, errorText } from '@/store/toastStore';
import { useTelegram } from '@/hooks/useTelegram';
import type { Order, OrderDelivery } from '@/types';
import { ReviewBox } from '@/components/DealChat/DealReview';
import { fmtDate } from '@/components/DealChat/dealFormat';
import './DealPage.css';

/**
 * Покупка у самой площадки: ключ, инструкция или услуга.
 *
 * Раньше купленное приходило только файлом в Telegram, а в приложении о нём
 * не было ни слова — потерял сообщение, и ключа больше нигде нет. Теперь
 * оно здесь, навсегда. Продавца и переписки у таких покупок нет — поэтому
 * и чата на этой странице нет.
 */
export const OrderPage: React.FC = () => {
    const { orderId = '', itemId = '' } = useParams();
    const navigate = useNavigate();
    const location = useLocation();
    const { language, accessToken } = useAuthStore();
    const { haptic } = useTelegram();
    const showToast = useToastStore((s) => s.show);
    const t = useCallback((ru: string, en: string) => (language === 'ru' ? ru : en), [language]);

    const [order, setOrder] = useState<Order | null>(null);
    const [delivery, setDelivery] = useState<OrderDelivery | null>(null);
    const [failed, setFailed] = useState<string | null>(null);

    const load = useCallback(async () => {
        try {
            const [loaded, goods] = await Promise.all([
                ordersApi.getOrder(orderId),
                ordersApi.getDelivery(orderId, itemId),
            ]);
            setOrder(loaded);
            setDelivery(goods);
            setFailed(null);
        } catch (e) {
            setFailed(errorText(e, t('Не удалось загрузить покупку', 'Failed to load the purchase')));
        }
    }, [orderId, itemId, t]);

    useEffect(() => {
        if (accessToken) load();
    }, [accessToken, load]);

    const goBack = () => (location.key !== 'default' ? navigate(-1) : navigate('/my/deals'));

    const copy = async (value: string) => {
        try {
            await navigator.clipboard.writeText(value);
        } catch {
            // В WebView Telegram clipboard бывает недоступен — запасной путь
            const area = document.createElement('textarea');
            area.value = value;
            area.style.position = 'fixed';
            area.style.opacity = '0';
            document.body.appendChild(area);
            area.select();
            document.execCommand('copy');
            area.remove();
        }
        haptic.notification('success');
        showToast(t('Скопировано', 'Copied'), 'success');
    };

    const item = order?.items.find((i) => i.id === itemId);

    if (failed || (order && !item)) {
        return (
            <div className="dpage">
                <div className="container dpage-body">
                    <button className="btn-back" onClick={goBack}>
                        <ArrowLeft size={20} />
                        <span>{t('Мои сделки', 'My deals')}</span>
                    </button>
                    <p className="dpage-muted">{failed ?? t('Покупка не найдена', 'Purchase not found')}</p>
                </div>
            </div>
        );
    }

    if (!order || !item) {
        return (
            <div className="dpage">
                <div className="container dpage-body">
                    <div className="skeleton dpage-skeleton-line" />
                    <div className="skeleton dpage-skeleton-photo" />
                </div>
            </div>
        );
    }

    const snapshot = item.product_snapshot;
    const name = (language === 'en' ? snapshot.name_en : snapshot.name_ru) || snapshot.name_ru;
    const description = (language === 'en' ? snapshot.description_en : snapshot.description_ru) || snapshot.description_ru;
    const image = snapshot.images?.[0] ?? snapshot.image_url ?? null;
    const service = snapshot.type === 'service';
    const inWork = service && order.status !== 'completed';
    const total = Number(item.price_usdt) * item.quantity;

    return (
        <div className="dpage">
            <div className="container dpage-body">
                <div className="dpage-top">
                    <button className="btn-back" onClick={goBack}>
                        <ArrowLeft size={20} />
                        <span>{t('Мои сделки', 'My deals')}</span>
                    </button>
                    <span className="dpage-number">
                        {t(`Заказ от ${fmtDate(order.paid_at ?? order.created_at, language)}`,
                           `Order of ${fmtDate(order.paid_at ?? order.created_at, language)}`)}
                    </span>
                </div>

                <div className="dpage-product">
                    <span className="dpage-product-thumb">
                        {image ? <img src={image} alt="" /> : <Package size={28} />}
                    </span>
                    <div className="dpage-title">
                        <div className="dpage-chips">
                            <span className={`dchat-chip ${inWork ? 'open' : 'done'}`}>
                                {inWork ? t('В работе', 'In progress') : service ? t('Выполнено', 'Done') : t('Выдано', 'Delivered')}
                            </span>
                        </div>
                        <h1>{name}</h1>
                        <div className="dpage-price">
                            ${total.toFixed(2).replace(/\.00$/, '')}
                            {item.quantity > 1 && <span> · {item.quantity} {t('шт.', 'pcs')}</span>}
                        </div>
                    </div>
                </div>

                {delivery && (delivery.keys.length > 0 || delivery.instruction) && (
                    <section className="dpage-goods">
                        <h2>{t('Ваш товар', 'Your item')}</h2>
                        {delivery.keys.map((key, index) => (
                            <div key={`${key}-${index}`} className="dpage-key">
                                <code>{key}</code>
                                <button
                                    type="button"
                                    className="dpage-copy"
                                    onClick={() => copy(key)}
                                    aria-label={t('Скопировать', 'Copy')}
                                >
                                    <Copy size={20} />
                                </button>
                            </div>
                        ))}
                        {delivery.instruction && (
                            <div className="dpage-key">
                                <div className="dpage-instruction">{delivery.instruction}</div>
                            </div>
                        )}
                        {delivery.instruction && (
                            <button type="button" className="dchat-btn ghost" onClick={() => copy(delivery.instruction!)}>
                                <Copy size={16} />
                                {t('Скопировать текст', 'Copy text')}
                            </button>
                        )}
                        <span className="dpage-goods-note">
                            {t('Купленное остаётся здесь навсегда.', 'Your purchase stays here for good.')}
                        </span>
                    </section>
                )}

                {service && (
                    <section className="dpage-goods">
                        <h2>{t('Услуга', 'Service')}</h2>
                        <p className="dpage-muted" style={{ margin: 0 }}>
                            {inWork
                                ? t('Заказ передан в работу — администратор выполнит его и пришлёт сообщение.',
                                    'The order is being processed — an administrator will complete it and message you.')
                                : t('Услуга выполнена.', 'The service has been completed.')}
                        </p>
                        {delivery?.link && <code className="dpage-instruction">{delivery.link}</code>}
                    </section>
                )}

                {description && (
                    <section className="dpage-section">
                        <h2>{t('Описание', 'Description')}</h2>
                        <p>{description}</p>
                    </section>
                )}

                {order.status === 'completed' && (
                    <ReviewBox
                        orderId={order.id}
                        productId={item.product_id}
                        title={t('Оцените покупку', 'Rate the purchase')}
                        reviewed={item.is_reviewed}
                        doneText={t('Отзыв оставлен', 'Review left')}
                        t={t}
                        onDone={load}
                    />
                )}
            </div>
        </div>
    );
};
