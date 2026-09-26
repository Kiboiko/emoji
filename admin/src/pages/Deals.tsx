import React, { useCallback, useEffect, useState } from 'react';
import { MessageSquare, X, Loader2, AlertTriangle } from 'lucide-react';
import { p2pApi } from '../api/admin';
import { DataTable, type Column } from '../components/ui/DataTable';
import { Pagination } from '../components/ui/Pagination';
import { StatusBadge } from '../components/ui/Badge';
import { useToast, errorText } from '../components/ui/Toast';

const LIMIT = 25;

const STATUSES = [
    { value: '', label: 'Все' },
    { value: 'disputed', label: 'Споры' },
    { value: 'paid_escrow', label: 'В эскроу' },
    { value: 'chat_opened', label: 'Переписка' },
    { value: 'delivered_claimed', label: 'Отправлено' },
    { value: 'released', label: 'Выплачено' },
    { value: 'refunded', label: 'Возвраты' },
];

export const Deals: React.FC = () => {
    const [rows, setRows] = useState<any[]>([]);
    const [total, setTotal] = useState(0);
    const [skip, setSkip] = useState(0);
    const [status, setStatus] = useState('disputed');
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [openId, setOpenId] = useState<string | null>(null);

    const load = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const page = await p2pApi.deals({
                status: status || undefined, skip, limit: LIMIT,
            });
            setRows(page.items ?? []);
            setTotal(page.total ?? 0);
        } catch (e) {
            setError(errorText(e, 'Не удалось загрузить сделки'));
        } finally {
            setLoading(false);
        }
    }, [status, skip]);

    useEffect(() => { load(); }, [load]);

    const columns: Column<any>[] = [
        { key: 'number', title: '№', render: (d) => <span className="font-mono">{d.number}</span> },
        { key: 'product_name', title: 'Товар' },
        {
            key: 'parties',
            title: 'Стороны',
            render: (d) => (
                <div className="text-xs">
                    <div>покупатель: {d.buyer ?? '—'}</div>
                    <div className="text-gray-400">продавец: {d.seller ?? '—'}</div>
                </div>
            ),
        },
        {
            key: 'amount',
            title: 'Сумма',
            render: (d) => (
                <div className="whitespace-nowrap">
                    <div>{d.amount_ton} TON</div>
                    <div className="text-xs text-gray-500">комиссия {d.commission_ton}</div>
                </div>
            ),
        },
        { key: 'status', title: 'Статус', render: (d) => <StatusBadge status={d.status} /> },
        {
            key: 'created_at',
            title: 'Создана',
            render: (d) => new Date(d.created_at).toLocaleDateString('ru-RU'),
        },
        {
            key: 'actions',
            title: '',
            render: (d) => (
                <button
                    onClick={(e) => { e.stopPropagation(); setOpenId(d.id); }}
                    className="p-2 rounded-lg bg-gray-700 hover:bg-gray-600 text-gray-300"
                    title="Переписка и разбор"
                >
                    <MessageSquare size={14} />
                </button>
            ),
            className: 'text-right',
        },
    ];

    return (
        <div>
            <h1 className="text-2xl md:text-3xl font-bold text-white mb-6">Сделки</h1>

            <div className="flex gap-2 mb-5 flex-wrap">
                {STATUSES.map((s) => (
                    <button
                        key={s.value}
                        onClick={() => { setStatus(s.value); setSkip(0); }}
                        className={`px-3 py-1.5 rounded-lg text-sm transition-colors ${
                            status === s.value
                                ? 'bg-blue-600 text-white'
                                : 'bg-gray-800 text-gray-400 hover:bg-gray-700'
                        }`}
                    >
                        {s.label}
                    </button>
                ))}
            </div>

            <DataTable
                columns={columns}
                rows={rows}
                rowKey={(d) => d.id}
                loading={loading}
                error={error}
                emptyText="Сделок нет"
            />

            <Pagination total={total} skip={skip} limit={LIMIT} onChange={setSkip} />

            {openId && (
                <DealDrawer
                    dealId={openId}
                    onClose={() => setOpenId(null)}
                    onResolved={load}
                />
            )}
        </div>
    );
};

/* ------------------------------------------------------------------ */

const DealDrawer: React.FC<{
    dealId: string;
    onClose: () => void;
    onResolved: () => void;
}> = ({ dealId, onClose, onResolved }) => {
    const toast = useToast();
    const [data, setData] = useState<any>(null);
    const [error, setError] = useState<string | null>(null);
    const [busy, setBusy] = useState(false);

    const load = useCallback(() => {
        p2pApi.dealMessages(dealId).then(setData).catch((e) => setError(errorText(e)));
    }, [dealId]);

    useEffect(load, [load]);

    const resolve = async (release: boolean) => {
        const who = release ? 'продавцу' : 'покупателю';
        if (!window.confirm(`Отдать деньги ${who}? Действие необратимо.`)) return;

        const comment = window.prompt('Комментарий к решению (увидят обе стороны):') ?? undefined;

        setBusy(true);
        try {
            await p2pApi.resolveDispute(dealId, release, comment);
            toast.success(`Спор закрыт: деньги ${who}`);
            load();
            onResolved();
        } catch (e) {
            toast.fromError(e);
        } finally {
            setBusy(false);
        }
    };

    const deal = data?.deal;

    return (
        <div className="fixed inset-0 bg-black/60 z-50 flex items-start justify-center overflow-y-auto p-4">
            <div className="bg-gray-800 rounded-xl border border-gray-700 w-full max-w-2xl my-8">
                <div className="flex items-center justify-between p-5 border-b border-gray-700">
                    <h2 className="text-lg font-semibold text-white">
                        {deal ? `Сделка №${deal.number} — ${deal.product_name}` : 'Загрузка...'}
                    </h2>
                    <button onClick={onClose} className="text-gray-400 hover:text-white">
                        <X size={20} />
                    </button>
                </div>

                <div className="p-5">
                    {error && <div className="text-red-400 text-sm">{error}</div>}
                    {!data && !error && <Loader2 size={20} className="animate-spin text-gray-400" />}

                    {data && (
                        <>
                            <div className="mb-4">
                                <StatusBadge status={deal.status} />
                            </div>

                            <div className="space-y-2 max-h-[45vh] overflow-y-auto mb-5">
                                {data.messages.length === 0 && (
                                    <div className="text-gray-500 text-sm py-6 text-center">
                                        Переписки пока нет
                                    </div>
                                )}

                                {data.messages.map((m: any, index: number) => (
                                    <div
                                        key={index}
                                        className={`rounded-lg p-3 text-sm ${
                                            m.direction === 'system'
                                                ? 'bg-gray-900/70 text-gray-400 text-center'
                                                : m.direction === 'buyer_to_seller'
                                                    ? 'bg-blue-900/30 text-blue-100 mr-8'
                                                    : 'bg-green-900/30 text-green-100 ml-8'
                                        }`}
                                    >
                                        {m.direction !== 'system' && (
                                            <div className="text-xs opacity-60 mb-1">
                                                {m.direction === 'buyer_to_seller' ? 'покупатель' : 'продавец'}
                                                {' · '}
                                                {new Date(m.created_at).toLocaleString('ru-RU')}
                                            </div>
                                        )}
                                        {m.text && <div className="whitespace-pre-wrap break-words">{m.text}</div>}
                                        {m.media_type && (
                                            <div className="text-xs opacity-70 mt-1">
                                                вложение: {m.media_type}
                                                {m.media_file_id && (
                                                    <span className="font-mono ml-1 break-all">
                                                        {m.media_file_id}
                                                    </span>
                                                )}
                                            </div>
                                        )}
                                        {m.delivery_error && (
                                            <div className="text-xs text-red-400 mt-1 flex items-center gap-1">
                                                <AlertTriangle size={12} /> не доставлено: {m.delivery_error}
                                            </div>
                                        )}
                                    </div>
                                ))}
                            </div>

                            {deal.status === 'disputed' && (
                                <div className="border-t border-gray-700 pt-4">
                                    <p className="text-sm text-gray-400 mb-3">
                                        Деньги удерживаются платформой. Решение необратимо.
                                    </p>
                                    <div className="flex gap-2 flex-wrap">
                                        <button
                                            onClick={() => resolve(true)}
                                            disabled={busy}
                                            className="px-4 py-2 rounded-lg bg-green-600 text-white text-sm hover:bg-green-500 disabled:opacity-50"
                                        >
                                            Деньги продавцу
                                        </button>
                                        <button
                                            onClick={() => resolve(false)}
                                            disabled={busy}
                                            className="px-4 py-2 rounded-lg bg-amber-600 text-white text-sm hover:bg-amber-500 disabled:opacity-50"
                                        >
                                            Вернуть покупателю
                                        </button>
                                    </div>
                                </div>
                            )}
                        </>
                    )}
                </div>
            </div>
        </div>
    );
};
