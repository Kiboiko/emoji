import React, { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { ChevronRight, Package } from 'lucide-react';
import { ordersApi } from '@/api/client';
import { useAuthStore } from '@/store/authStore';
import { useDealsStore } from '@/store/dealsStore';
import { errorText } from '@/store/toastStore';
import { formatTon } from '@/lib/ton';
import { fmtDate, isFinished, statusLabel, statusTone } from '@/components/DealChat/dealFormat';
import type { Deal, Order } from '@/types';
import './Purchases.css';

type T = (ru: string, en: string) => string;
type Tab = 'all' | 'buy' | 'sell';
type Group = 'action' | 'active' | 'done';

interface Row {
    key: string;
    to: string;
    image: string | null;
    name: string;
    side: 'buy' | 'sell';
    who: string;
    chip: { label: string; tone: string };
    hint: { text: string; warn?: boolean } | null;
    date: string;
    amount: string;
    struck?: boolean;
    group: Group;
}

function dealRow(deal: Deal, language: string, t: T): Row {
    const buyer = deal.role === 'buyer';
    const finished = isFinished(deal);
    const deadline = deal.confirm_deadline_at ? fmtDate(deal.confirm_deadline_at, language) : null;

    // Ждут вас — сделки, где следующий шаг за этим человеком. Остальное
    // незакрытое — «в процессе»: ждём другую сторону или модератора
    let group: Group = finished ? 'done' : 'active';
    let hint: Row['hint'] = null;
    if (!finished) {
        if (deal.status === 'disputed') {
            hint = { text: t('Спор — разбирает модератор', 'Dispute — a moderator is on it') };
        } else if (buyer && deal.status === 'delivered_claimed') {
            group = 'action';
            hint = {
                text: deadline ? t(`Подтвердите до ${deadline}`, `Confirm by ${deadline}`) : t('Подтвердите получение', 'Confirm receipt'),
                warn: true,
            };
        } else if (!buyer && deal.status !== 'delivered_claimed') {
            group = 'action';
            hint = { text: t('Отправьте товар', 'Send the item'), warn: true };
        } else if (buyer) {
            hint = { text: t('Ждём отправку', 'Waiting for shipment') };
        } else {
            hint = { text: t('Ждём подтверждения', 'Waiting for confirmation') };
        }
    }

    const amount = buyer ? deal.amount_ton : deal.seller_amount_ton;
    return {
        key: `deal-${deal.id}`,
        to: `/my/deal/${deal.id}`,
        image: deal.product_image,
        name: (language === 'en' && deal.details?.name_en) || deal.product_name,
        side: buyer ? 'buy' : 'sell',
        who: buyer
            ? t(`Покупка · ${deal.store?.name ?? 'продавец'}`, `Purchase · ${deal.store?.name ?? 'seller'}`)
            : t(`Продажа · №${deal.number}`, `Sale · #${deal.number}`),
        chip: { label: statusLabel(deal.status, t), tone: statusTone(deal.status) },
        hint,
        date: deal.last_activity_at || deal.created_at,
        amount: `${formatTon(amount)} TON`,
        struck: deal.status === 'refunded' || deal.status === 'cancelled',
        group,
    };
}

function orderRows(orders: Order[], language: string, t: T): Row[] {
    const rows: Row[] = [];
    for (const order of orders) {
        for (const item of order.items ?? []) {
            const snapshot = item.product_snapshot ?? ({} as Order['items'][number]['product_snapshot']);
            // Товар продавца идёт сделкой, подписка — в «Моих подписках»
            if (snapshot.is_p2p || snapshot.type === 'subscription') continue;

            const service = snapshot.type === 'service';
            const inWork = service && order.status !== 'completed';
            const total = Number(item.price_usdt) * item.quantity;
            rows.push({
                key: `order-${order.id}-${item.id}`,
                to: `/my/purchase/${order.id}/${item.id}`,
                image: snapshot.images?.[0] ?? snapshot.image_url ?? null,
                name: (language === 'en' ? snapshot.name_en : snapshot.name_ru) || snapshot.name_ru,
                side: 'buy',
                who: t('Покупка · Магазин площадки', 'Purchase · Marketplace store'),
                chip: inWork
                    ? { label: t('В работе', 'In progress'), tone: 'open' }
                    : { label: service ? t('Выполнено', 'Done') : t('Выдано', 'Delivered'), tone: 'done' },
                hint: null,
                date: order.paid_at ?? order.created_at,
                amount: `$${total.toFixed(2).replace(/\.00$/, '')}`,
                group: inWork ? 'active' : 'done',
            });
        }
    }
    return rows;
}

/**
 * Мои сделки: все покупки и продажи одним списком.
 *
 * Раньше покупки у самой площадки жили в «Моих заказах», а сделки с
 * продавцами — здесь, и человек искал купленное в двух местах. Теперь всё
 * тут, сверху — то, что ждёт его действия. Переписка — во вкладке «Чаты»;
 * строка ведёт на страницу товара, а оттуда — в чат.
 */
export const Purchases: React.FC = () => {
    const { language, accessToken } = useAuthStore();
    const deals = useDealsStore((s) => s.deals);
    const [orders, setOrders] = useState<Order[] | null>(null);
    const [tab, setTab] = useState<Tab>('all');
    const [error, setError] = useState<string | null>(null);

    const t: T = (ru, en) => (language === 'ru' ? ru : en);

    useEffect(() => {
        if (!accessToken) return;
        useDealsStore.getState().loadDeals().catch((e) => setError(errorText(e, t('Не удалось загрузить сделки', 'Failed to load deals'))));
        ordersApi.getOrders().then(setOrders).catch(() => setOrders([]));
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [accessToken]);

    const rows = useMemo(() => {
        if (!deals || !orders) return null;
        const all = [
            ...deals.map((d) => dealRow(d, language, t)),
            ...orderRows(orders, language, t),
        ];
        return all
            .filter((r) => tab === 'all' || (tab === 'buy' ? r.side === 'buy' : r.side === 'sell'))
            .sort((a, b) => b.date.localeCompare(a.date));
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [deals, orders, tab, language]);

    if (error && !deals) return <p className="purchases-empty">{error}</p>;

    const groups: { id: Group; title: string }[] = [
        { id: 'action', title: t('Ждут вас', 'Waiting for you') },
        { id: 'active', title: t('В процессе', 'In progress') },
        { id: 'done', title: t('Завершённые', 'Completed') },
    ];

    return (
        <div className="purchases">
            <div className="purchases-tabs" role="tablist">
                {([
                    ['all', t('Все', 'All')],
                    ['buy', t('Покупки', 'Purchases')],
                    ['sell', t('Продажи', 'Sales')],
                ] as [Tab, string][]).map(([id, label]) => (
                    <button
                        key={id}
                        type="button"
                        role="tab"
                        aria-selected={tab === id}
                        className={tab === id ? 'is-active' : ''}
                        onClick={() => setTab(id)}
                    >
                        {label}
                    </button>
                ))}
            </div>

            {rows === null ? (
                <div className="purchases-list">
                    {[0, 1, 2].map((i) => <div key={i} className="purchases-row skeleton purchases-skeleton" />)}
                </div>
            ) : rows.length === 0 ? (
                <p className="purchases-empty">
                    {tab === 'sell'
                        ? t('Продаж пока нет.', 'No sales yet.')
                        : t('Покупок пока нет. Здесь появится всё, что вы купите или продадите.', 'Nothing here yet. Everything you buy or sell appears here.')}
                </p>
            ) : (
                groups.map((group) => {
                    const items = rows.filter((r) => r.group === group.id);
                    if (!items.length) return null;
                    return (
                        <section key={group.id} className="purchases-group">
                            <h2 className="purchases-group-title">
                                {group.title}
                                {group.id === 'action' && ` · ${items.length}`}
                            </h2>
                            <div className="purchases-list">
                                {items.map((row) => (
                                    <Link
                                        key={row.key}
                                        to={row.to}
                                        className={`purchases-row${row.group === 'action' ? ' needs-you' : ''}`}
                                    >
                                        <span className="purchases-thumb">
                                            {row.image ? <img src={row.image} alt="" loading="lazy" /> : <Package size={22} />}
                                        </span>
                                        <span className="purchases-main">
                                            <span className="purchases-name">{row.name}</span>
                                            <span className="purchases-who">{row.who}</span>
                                            <span className="purchases-foot">
                                                <span className={`dchat-chip ${row.chip.tone}`}>{row.chip.label}</span>
                                                <span className={`purchases-hint${row.hint?.warn ? ' warn' : ''}`}>
                                                    {row.hint?.text ?? fmtDate(row.date, language)}
                                                </span>
                                            </span>
                                        </span>
                                        <span className="purchases-side">
                                            <span className={`purchases-amount${row.struck ? ' struck' : ''}`}>{row.amount}</span>
                                            <ChevronRight size={18} />
                                        </span>
                                    </Link>
                                ))}
                            </div>
                        </section>
                    );
                })
            )}
        </div>
    );
};
