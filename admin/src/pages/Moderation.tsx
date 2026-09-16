import React, { useCallback, useEffect, useState } from 'react';
import { Check, X, Loader2, Image as ImageIcon } from 'lucide-react';
import { p2pApi } from '../api/admin';
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

export const Moderation: React.FC = () => {
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
        <div className="p-4 md:p-8">
            <h1 className="text-2xl md:text-3xl font-bold text-white mb-6">Модерация товаров</h1>

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
