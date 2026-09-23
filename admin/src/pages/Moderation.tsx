import React, { useCallback, useEffect, useState } from 'react';
import {
    Check, X, Loader2, Image as ImageIcon, BadgeCheck, Ban, Undo2,
} from 'lucide-react';
import { p2pApi } from '../api/admin';
import { DataTable, type Column } from '../components/ui/DataTable';
import { Pagination } from '../components/ui/Pagination';
import { StatusBadge } from '../components/ui/Badge';
import { useToast, errorText } from '../components/ui/Toast';

const LIMIT = 20;

const STATUSES = [
    { value: 'pending', label: 'На модерации' },
    { value: 'approved', label: 'Одобренные' },
    { value: 'rejected', label: 'Отклонённые' },
    { value: 'withdrawn', label: 'Снятые' },
    { value: 'draft', label: 'Черновики' },
];

/**
 * Модерация товаров и продавцы.
 *
 * Ручки по продавцам (список, блокировка, ограничение) существовали на
 * бэкенде, но вызвать их из админки было неоткуда — страницы просто не
 * было. Галочка проверенного продавца без неё тоже не ставилась бы.
 */
export const Moderation: React.FC = () => {
    const [tab, setTab] = useState<'listings' | 'sellers'>('listings');

    return (
        <div className="p-4 md:p-8">
            <h1 className="text-2xl md:text-3xl font-bold text-white mb-6">Модерация</h1>

            <div className="flex gap-2 mb-5">
                <button
                    onClick={() => setTab('listings')}
                    className={`px-4 py-2 rounded-lg text-sm ${
                        tab === 'listings' ? 'bg-blue-600 text-white' : 'bg-gray-800 text-gray-400 hover:bg-gray-700'
                    }`}
                >
                    Товары
                </button>
                <button
                    onClick={() => setTab('sellers')}
                    className={`px-4 py-2 rounded-lg text-sm ${
                        tab === 'sellers' ? 'bg-blue-600 text-white' : 'bg-gray-800 text-gray-400 hover:bg-gray-700'
                    }`}
                >
                    Продавцы
                </button>
            </div>

            {tab === 'listings' ? <ListingsTab /> : <SellersTab />}
        </div>
    );
};

/* ------------------------------------------------------------------ */

const ListingsTab: React.FC = () => {
    const toast = useToast();
    const [rows, setRows] = useState<any[]>([]);
    const [total, setTotal] = useState(0);
    const [skip, setSkip] = useState(0);
    const [status, setStatus] = useState('pending');
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [busy, setBusy] = useState<string | null>(null);

    const load = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const page = await p2pApi.listings({ status, skip, limit: LIMIT });
            setRows(page.items ?? []);
            setTotal(page.total ?? 0);
        } catch (e) {
            setError(errorText(e, 'Не удалось загрузить заявки'));
        } finally {
            setLoading(false);
        }
    }, [status, skip]);

    useEffect(() => { load(); }, [load]);

    const decide = async (listing: any, approve: boolean) => {
        let comment: string | undefined;
        if (!approve) {
            // Причина обязательна: отказ без объяснения продавец не может
            // исправить, а счётчик отказов подряд ведёт к ограничению
            const input = window.prompt('Причина отказа (будет отправлена продавцу):');
            if (!input || !input.trim()) return;
            comment = input.trim();
        }

        setBusy(listing.id);
        try {
            const result = await p2pApi.moderate(listing.id, approve, comment);
            if (result.seller_restricted) {
                toast.error('Отклонено. Продавец ограничен за серию отказов подряд.');
            } else {
                toast.success(approve ? 'Товар опубликован' : 'Заявка отклонена');
            }
            await load();
        } catch (e) {
            toast.fromError(e);
        } finally {
            setBusy(null);
        }
    };

    return (
        <div>
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

            {loading && <Loader2 size={22} className="animate-spin text-gray-400" />}
            {error && <div className="text-red-400 text-sm">{error}</div>}
            {!loading && !error && rows.length === 0 && (
                <div className="text-gray-500 py-12 text-center">Заявок нет</div>
            )}

            <div className="space-y-4">
                {rows.map((listing) => (
                    <div key={listing.id} className="bg-gray-800 rounded-xl border border-gray-700 p-5">
                        <div className="flex items-start justify-between gap-4 mb-3 flex-wrap">
                            <div>
                                <h3 className="text-white font-semibold">{listing.name}</h3>
                                <div className="text-sm text-gray-400 mt-0.5">
                                    ${listing.price_usd} · {listing.seller?.display_name ?? 'продавец'}
                                    {listing.seller?.username && ` (@${listing.seller.username})`}
                                </div>
                            </div>
                            <StatusBadge status={listing.status} />
                        </div>

                        <p className="text-sm text-gray-300 whitespace-pre-wrap mb-3">
                            {listing.description}
                        </p>

                        {listing.images?.length > 0 ? (
                            <div className="flex gap-2 flex-wrap mb-4">
                                {listing.images.map((url: string) => (
                                    <a key={url} href={url} target="_blank" rel="noreferrer">
                                        <img
                                            src={url}
                                            alt=""
                                            className="w-24 h-24 object-cover rounded-lg border border-gray-700"
                                        />
                                    </a>
                                ))}
                            </div>
                        ) : (
                            <div className="flex items-center gap-2 text-gray-500 text-sm mb-4">
                                <ImageIcon size={15} /> без фото
                            </div>
                        )}

                        {listing.moderation_comment && (
                            <div className="text-sm text-amber-400 mb-3">
                                Комментарий: {listing.moderation_comment}
                            </div>
                        )}

                        {listing.status === 'pending' && (
                            <div className="flex gap-2">
                                <button
                                    onClick={() => decide(listing, true)}
                                    disabled={busy === listing.id}
                                    className="flex items-center gap-2 px-4 py-2 rounded-lg bg-green-600 text-white text-sm hover:bg-green-500 disabled:opacity-50"
                                >
                                    <Check size={15} /> Одобрить
                                </button>
                                <button
                                    onClick={() => decide(listing, false)}
                                    disabled={busy === listing.id}
                                    className="flex items-center gap-2 px-4 py-2 rounded-lg bg-red-600/20 text-red-400 text-sm hover:bg-red-600/30 disabled:opacity-50"
                                >
                                    <X size={15} /> Отклонить
                                </button>
                            </div>
                        )}
                    </div>
                ))}
            </div>

            <Pagination total={total} skip={skip} limit={LIMIT} onChange={setSkip} />
        </div>
    );
};


/* ------------------------------------------------------------------ */
/* Продавцы                                                          */
/* ------------------------------------------------------------------ */

const SELLER_STATUSES = [
    { value: '', label: 'Все' },
    { value: 'active', label: 'Активные' },
    { value: 'restricted', label: 'Ограниченные' },
    { value: 'banned', label: 'Заблокированные' },
];

const SellersTab: React.FC = () => {
    const toast = useToast();
    const [rows, setRows] = useState<any[]>([]);
    const [total, setTotal] = useState(0);
    const [skip, setSkip] = useState(0);
    const [status, setStatus] = useState('');
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [busy, setBusy] = useState<string | null>(null);

    const load = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const page = await p2pApi.sellers({
                status: status || undefined, skip, limit: LIMIT,
            });
            setRows(page.items ?? []);
            setTotal(page.total ?? 0);
        } catch (e) {
            setError(errorText(e, 'Не удалось загрузить продавцов'));
        } finally {
            setLoading(false);
        }
    }, [status, skip]);

    useEffect(() => { load(); }, [load]);

    const run = async (seller: any, fn: () => Promise<unknown>, done: string) => {
        setBusy(seller.id);
        try {
            await fn();
            toast.success(done);
            await load();
        } catch (e) {
            toast.fromError(e);
        } finally {
            setBusy(null);
        }
    };

    // Галочка и статус — разные решения: «не заблокирован» не значит
    // «площадка за него ручается»
    const toggleVerified = (seller: any) => run(
        seller,
        () => p2pApi.setSellerVerified(seller.id, !seller.is_verified),
        seller.is_verified ? 'Галочка снята' : 'Продавец отмечен как проверенный',
    );

    const ban = (seller: any) => {
        const reason = window.prompt('Причина блокировки:');
        if (!reason?.trim()) return;
        return run(
            seller,
            () => p2pApi.setSellerStatus(seller.id, 'banned', reason.trim()),
            'Продавец заблокирован, его товары сняты с витрины',
        );
    };

    const unblock = (seller: any) => run(
        seller,
        () => p2pApi.setSellerStatus(seller.id, 'active'),
        'Ограничения сняты',
    );

    const columns: Column<any>[] = [
        {
            key: 'name',
            title: 'Продавец',
            render: (s) => (
                <div>
                    <div className="text-white font-medium flex items-center gap-2">
                        {s.display_name}
                        {s.is_verified && (
                            <BadgeCheck size={14} className="text-violet-400" aria-label="Проверенный продавец" />
                        )}
                    </div>
                    <div className="text-xs text-gray-500">
                        {s.username ? `@${s.username}` : s.telegram_id ?? '—'}
                    </div>
                </div>
            ),
        },
        {
            key: 'rating',
            title: 'Рейтинг / сделки',
            render: (s) => (
                <span className="text-sm">
                    {s.rating ?? '—'}
                    {s.rating_count ? ` (${s.rating_count})` : ''} / {s.deals_completed}
                </span>
            ),
        },
        {
            key: 'status',
            title: 'Статус',
            render: (s) => (
                <div>
                    <StatusBadge status={s.status} />
                    {s.restricted_until && (
                        <div className="text-xs text-yellow-500 mt-1">
                            до {new Date(s.restricted_until).toLocaleDateString('ru')}
                        </div>
                    )}
                    {s.restriction_reason && (
                        <div className="text-xs text-gray-500 mt-1 max-w-[200px]">
                            {s.restriction_reason}
                        </div>
                    )}
                </div>
            ),
        },
        {
            key: 'actions',
            title: '',
            render: (s) => (
                <div className="flex gap-2 justify-end">
                    <button
                        onClick={() => toggleVerified(s)}
                        disabled={busy === s.id}
                        className={`p-2 rounded-lg disabled:opacity-50 ${
                            s.is_verified
                                ? 'bg-violet-600/20 text-violet-300 hover:bg-violet-600/30'
                                : 'bg-gray-800 text-gray-400 hover:bg-gray-700'
                        }`}
                        title={s.is_verified ? 'Снять галочку' : 'Отметить проверенным'}
                    >
                        <BadgeCheck size={16} />
                    </button>

                    {s.status === 'active' ? (
                        <button
                            onClick={() => ban(s)}
                            disabled={busy === s.id}
                            className="p-2 rounded-lg bg-red-600/20 text-red-400 hover:bg-red-600/30 disabled:opacity-50"
                            title="Заблокировать"
                        >
                            <Ban size={16} />
                        </button>
                    ) : (
                        <button
                            onClick={() => unblock(s)}
                            disabled={busy === s.id}
                            className="p-2 rounded-lg bg-gray-800 text-gray-300 hover:bg-gray-700 disabled:opacity-50"
                            title="Снять ограничения"
                        >
                            <Undo2 size={16} />
                        </button>
                    )}
                </div>
            ),
        },
    ];

    return (
        <div>
            <div className="flex gap-2 mb-5 flex-wrap">
                {SELLER_STATUSES.map((item) => (
                    <button
                        key={item.value}
                        onClick={() => { setStatus(item.value); setSkip(0); }}
                        className={`px-3 py-1.5 rounded-lg text-sm transition-colors ${
                            status === item.value
                                ? 'bg-blue-600 text-white'
                                : 'bg-gray-800 text-gray-400 hover:bg-gray-700'
                        }`}
                    >
                        {item.label}
                    </button>
                ))}
            </div>

            {error && <div className="text-red-400 text-sm mb-4">{error}</div>}

            <DataTable columns={columns} rows={rows} rowKey={(s) => s.id} loading={loading} />
            <Pagination total={total} skip={skip} limit={LIMIT} onChange={setSkip} />
        </div>
    );
};
