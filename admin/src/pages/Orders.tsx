import React, { useCallback, useEffect, useState } from 'react';
import { Search, X, ExternalLink } from 'lucide-react';
import { ordersApi, type AdminOrder } from '../api/admin';
import { DataTable, type Column } from '../components/ui/DataTable';
import { Pagination } from '../components/ui/Pagination';
import { Badge, StatusBadge } from '../components/ui/Badge';
import { useToast, errorText } from '../components/ui/Toast';

const LIMIT = 25;

const STATUS_OPTIONS = [
    { value: 'all', label: 'Все' },
    { value: 'paid', label: 'Оплаченные' },
    { value: 'pending', label: 'Ожидают оплаты' },
    { value: 'completed', label: 'Завершённые' },
    { value: 'cancelled', label: 'Отменённые' },
];

export const Orders: React.FC = () => {
    const [rows, setRows] = useState<AdminOrder[]>([]);
    const [total, setTotal] = useState(0);
    const [skip, setSkip] = useState(0);
    const [status, setStatus] = useState('all');
    const [search, setSearch] = useState('');
    const [dateFrom, setDateFrom] = useState('');
    const [dateTo, setDateTo] = useState('');
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [cardId, setCardId] = useState<string | null>(null);

    const load = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const page = await ordersApi.list({
                status,
                search: search || undefined,
                date_from: dateFrom || undefined,
                // Конец дня, иначе фильтр «по сегодня» отсекает сегодняшние заказы
                date_to: dateTo ? `${dateTo}T23:59:59` : undefined,
                skip,
                limit: LIMIT,
            });
            setRows(page.items);
            setTotal(page.total);
        } catch (e) {
            setError(errorText(e, 'Не удалось загрузить заказы'));
        } finally {
            setLoading(false);
        }
    }, [status, search, dateFrom, dateTo, skip]);

    useEffect(() => {
        const timer = setTimeout(load, search ? 350 : 0);
        return () => clearTimeout(timer);
    }, [load, search]);

    const columns: Column<AdminOrder>[] = [
        {
            key: 'created_at',
            title: 'Дата',
            render: (o) => (
                <div className="whitespace-nowrap">
                    <div>{new Date(o.created_at).toLocaleDateString('ru-RU')}</div>
                    <div className="text-xs text-gray-500">
                        {new Date(o.created_at).toLocaleTimeString('ru-RU', {
                            hour: '2-digit', minute: '2-digit',
                        })}
                    </div>
                </div>
            ),
        },
        {
            key: 'user',
            title: 'Покупатель',
            render: (o) => (
                <div>
                    <div className="text-white">{o.user_name}</div>
                    <div className="text-xs text-gray-400">
                        {o.user_username ? `@${o.user_username}` : o.user_telegram_id}
                    </div>
                </div>
            ),
        },
        {
            key: 'items',
            title: 'Состав',
            render: (o) => (
                <div className="space-y-0.5 max-w-xs">
                    {o.items.slice(0, 3).map((item, index) => (
                        <div key={index} className="text-xs flex items-center gap-1.5">
                            <span className="truncate">{item.product_name}</span>
                            {item.quantity > 1 && <span className="text-gray-500">×{item.quantity}</span>}
                            {item.is_p2p && <Badge tone="info">P2P</Badge>}
                        </div>
                    ))}
                    {o.items.length > 3 && (
                        <div className="text-xs text-gray-500">…ещё {o.items.length - 3}</div>
                    )}
                </div>
            ),
        },
        {
            key: 'total',
            title: 'Сумма',
            render: (o) => (
                <div className="whitespace-nowrap">
                    <div className="text-white font-medium">${o.total_usdt.toFixed(2)}</div>
                    {o.total_ton && <div className="text-xs text-gray-500">{o.total_ton} TON</div>}
                </div>
            ),
        },
        {
            key: 'status',
            title: 'Статус',
            render: (o) => <StatusBadge status={o.status} />,
        },
        {
            key: 'actions',
            title: '',
            render: (o) => (
                <button
                    onClick={(e) => { e.stopPropagation(); setCardId(o.id); }}
                    className="p-2 rounded-lg bg-gray-700 hover:bg-gray-600 text-gray-300"
                >
                    <ExternalLink size={14} />
                </button>
            ),
            className: 'text-right',
        },
    ];

    return (
        <div className="p-4 md:p-8">
            <h1 className="text-2xl md:text-3xl font-bold text-white mb-6">Заказы</h1>

            <div className="flex flex-wrap gap-3 mb-4">
                <div className="relative flex-1 min-w-[200px]">
                    <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
                    <input
                        value={search}
                        onChange={(e) => { setSearch(e.target.value); setSkip(0); }}
                        placeholder="Покупатель"
                        className="w-full pl-9 pr-3 py-2 rounded-lg bg-gray-800 border border-gray-700 text-white text-sm placeholder-gray-500 focus:outline-none focus:border-blue-500"
                    />
                </div>

                <select
                    value={status}
                    onChange={(e) => { setStatus(e.target.value); setSkip(0); }}
                    className="px-3 py-2 rounded-lg bg-gray-800 border border-gray-700 text-white text-sm focus:outline-none focus:border-blue-500"
                >
                    {STATUS_OPTIONS.map((o) => (
                        <option key={o.value} value={o.value}>{o.label}</option>
                    ))}
                </select>

                <input
                    type="date"
                    value={dateFrom}
                    onChange={(e) => { setDateFrom(e.target.value); setSkip(0); }}
                    className="px-3 py-2 rounded-lg bg-gray-800 border border-gray-700 text-white text-sm focus:outline-none focus:border-blue-500"
                />
                <input
                    type="date"
                    value={dateTo}
                    onChange={(e) => { setDateTo(e.target.value); setSkip(0); }}
                    className="px-3 py-2 rounded-lg bg-gray-800 border border-gray-700 text-white text-sm focus:outline-none focus:border-blue-500"
                />
            </div>

            <DataTable
                columns={columns}
                rows={rows}
                rowKey={(o) => o.id}
                loading={loading}
                error={error}
                emptyText="Заказов не найдено"
            />

            <Pagination total={total} skip={skip} limit={LIMIT} onChange={setSkip} />

            {cardId && (
                <OrderCard
                    orderId={cardId}
                    onClose={() => setCardId(null)}
                    onChanged={load}
                />
            )}
        </div>
    );
};

/* ------------------------------------------------------------------ */

const OrderCard: React.FC<{
    orderId: string;
    onClose: () => void;
    onChanged: () => void;
}> = ({ orderId, onClose, onChanged }) => {
    const toast = useToast();
    const [data, setData] = useState<any>(null);
    const [error, setError] = useState<string | null>(null);
    const [busy, setBusy] = useState(false);

    const load = useCallback(() => {
        ordersApi.card(orderId).then(setData).catch((e) => setError(errorText(e)));
    }, [orderId]);

    useEffect(load, [load]);

    const cancel = async () => {
        if (!window.confirm('Отменить заказ?')) return;
        setBusy(true);
        try {
            await ordersApi.setStatus(orderId, 'cancelled', 'отменён администратором');
            toast.success('Заказ отменён');
            load();
            onChanged();
        } catch (e) {
            toast.fromError(e);
        } finally {
            setBusy(false);
        }
    };

    return (
        <div className="fixed inset-0 bg-black/60 z-50 flex items-start justify-center overflow-y-auto p-4">
            <div className="bg-gray-800 rounded-xl border border-gray-700 w-full max-w-2xl my-8">
                <div className="flex items-center justify-between p-5 border-b border-gray-700">
                    <h2 className="text-lg font-semibold text-white">Заказ</h2>
                    <button onClick={onClose} className="text-gray-400 hover:text-white">
                        <X size={20} />
                    </button>
                </div>

                <div className="p-5 space-y-5">
                    {error && <div className="text-red-400 text-sm">{error}</div>}

                    {data && (
                        <>
                            <div className="flex items-center gap-3 flex-wrap">
                                <StatusBadge status={data.status} />
                                <span className="text-white text-lg font-semibold">
                                    ${data.total_usdt.toFixed(2)}
                                </span>
                                <span className="text-gray-400 text-sm">
                                    {new Date(data.created_at).toLocaleString('ru-RU')}
                                </span>
                            </div>

                            {data.user && (
                                <Block title="Покупатель">
                                    <Row label="Имя" value={data.user.first_name} />
                                    <Row
                                        label="Telegram"
                                        value={data.user.username ? `@${data.user.username}` : data.user.telegram_id}
                                    />
                                </Block>
                            )}

                            <Block title="Состав">
                                {data.items.map((item: any) => (
                                    <div key={item.id} className="flex items-start justify-between gap-3 text-sm py-1">
                                        <div className="flex-1">
                                            <div className="text-gray-200">
                                                {item.product_name}
                                                {item.quantity > 1 && ` ×${item.quantity}`}
                                            </div>
                                            {item.is_p2p && <Badge tone="info">товар пользователя</Badge>}
                                            {Object.keys(item.user_data).length > 0 && (
                                                <pre className="text-xs text-gray-500 mt-1 whitespace-pre-wrap">
                                                    {JSON.stringify(item.user_data, null, 2)}
                                                </pre>
                                            )}
                                        </div>
                                        <span className="text-gray-300">${item.price_usdt.toFixed(2)}</span>
                                    </div>
                                ))}
                            </Block>

                            {data.payment && (
                                <Block title="Платёж">
                                    <Row label="Статус" value={<StatusBadge status={data.payment.status} />} />
                                    <Row label="Комментарий" value={data.payment.comment} mono />
                                    <Row
                                        label="Ожидалось"
                                        value={`${(Number(data.payment.amount_nano) / 1e9).toFixed(9)} TON`}
                                    />
                                    <Row
                                        label="Получено"
                                        value={`${(Number(data.payment.received_nano) / 1e9).toFixed(9)} TON`}
                                    />
                                    {data.payment.tx_hash && (
                                        <Row label="Транзакция" value={data.payment.tx_hash} mono />
                                    )}
                                </Block>
                            )}

                            {data.deals.length > 0 && (
                                <Block title="Сделки">
                                    {data.deals.map((d: any) => (
                                        <div key={d.id} className="flex items-center gap-3 text-sm py-1">
                                            <span className="text-gray-300">№{d.number} {d.product_name}</span>
                                            <StatusBadge status={d.status} />
                                        </div>
                                    ))}
                                </Block>
                            )}

                            {data.status !== 'cancelled' && data.status !== 'completed' && (
                                <button
                                    onClick={cancel}
                                    disabled={busy}
                                    className="px-4 py-2 rounded-lg bg-red-600/20 text-red-400 hover:bg-red-600/30 text-sm disabled:opacity-50"
                                >
                                    Отменить заказ
                                </button>
                            )}
                        </>
                    )}
                </div>
            </div>
        </div>
    );
};

const Block: React.FC<{ title: string; children: React.ReactNode }> = ({ title, children }) => (
    <div>
        <h3 className="text-sm font-semibold text-gray-400 mb-2">{title}</h3>
        <div className="bg-gray-900/50 rounded-lg p-3">{children}</div>
    </div>
);

const Row: React.FC<{ label: string; value: React.ReactNode; mono?: boolean }> = ({
    label, value, mono,
}) => (
    <div className="flex items-start justify-between gap-4 text-sm py-0.5">
        <span className="text-gray-500">{label}</span>
        <span className={`text-gray-200 text-right break-all ${mono ? 'font-mono text-xs' : ''}`}>
            {value}
        </span>
    </div>
);
