import React, { useCallback, useEffect, useState } from 'react';
import { Trophy, Search } from 'lucide-react';
import { referralsApi } from '../api/admin';
import { DataTable, type Column } from '../components/ui/DataTable';
import { Pagination } from '../components/ui/Pagination';
import { Badge } from '../components/ui/Badge';
import { errorText } from '../components/ui/Toast';

const LIMIT = 50;

const SOURCE_LABEL: Record<string, string> = {
    product: 'товар',
    subscription: 'подписка',
    p2p: 'товар пользователя',
};

export const Referrals: React.FC = () => {
    const [tab, setTab] = useState<'history' | 'top'>('history');

    return (
        <div>
            <h1 className="text-2xl md:text-3xl font-bold text-white mb-6">Рефералы</h1>

            <div className="flex gap-2 mb-5">
                <button
                    onClick={() => setTab('history')}
                    className={`px-4 py-2 rounded-lg text-sm ${
                        tab === 'history' ? 'bg-blue-600 text-white' : 'bg-gray-800 text-gray-400 hover:bg-gray-700'
                    }`}
                >
                    История начислений
                </button>
                <button
                    onClick={() => setTab('top')}
                    className={`px-4 py-2 rounded-lg text-sm ${
                        tab === 'top' ? 'bg-blue-600 text-white' : 'bg-gray-800 text-gray-400 hover:bg-gray-700'
                    }`}
                >
                    Топ рефереров
                </button>
            </div>

            {tab === 'history' ? <HistoryTab /> : <TopTab />}
        </div>
    );
};

const HistoryTab: React.FC = () => {
    const [rows, setRows] = useState<any[]>([]);
    const [total, setTotal] = useState(0);
    const [skip, setSkip] = useState(0);
    const [level, setLevel] = useState('');
    const [source, setSource] = useState('');
    const [search, setSearch] = useState('');
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    const load = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const page = await referralsApi.list({
                level: level ? Number(level) : undefined,
                source: source || undefined,
                search: search || undefined,
                skip,
                limit: LIMIT,
            });
            setRows(page.items ?? []);
            setTotal(page.total ?? 0);
        } catch (e) {
            setError(errorText(e, 'Не удалось загрузить историю'));
        } finally {
            setLoading(false);
        }
    }, [level, source, search, skip]);

    useEffect(() => {
        const timer = setTimeout(load, search ? 350 : 0);
        return () => clearTimeout(timer);
    }, [load, search]);

    const columns: Column<any>[] = [
        {
            key: 'created_at',
            title: 'Время',
            render: (r) => (
                <span className="whitespace-nowrap text-xs">
                    {new Date(r.created_at).toLocaleString('ru-RU')}
                </span>
            ),
        },
        {
            key: 'referrer',
            title: 'Получил',
            render: (r) => (
                <span className="text-sm">
                    {r.referrer.username ? `@${r.referrer.username}` : r.referrer.telegram_id ?? '—'}
                </span>
            ),
        },
        {
            key: 'referral',
            title: 'С покупки',
            render: (r) => (
                <span className="text-sm text-gray-400">
                    {r.referral.username ? `@${r.referral.username}` : r.referral.telegram_id ?? '—'}
                </span>
            ),
        },
        {
            key: 'level',
            title: 'Уровень',
            render: (r) => (
                <Badge tone={r.level === 2 ? 'warning' : 'info'}>{r.level}</Badge>
            ),
        },
        {
            key: 'percent',
            title: 'Процент',
            render: (r) => (
                // NULL у начислений до этапа 6: процент тогда задавался в .env
                // и восстановить его нечем
                r.percent_bp_applied != null
                    ? `${(r.percent_bp_applied / 100).toFixed(2).replace(/\.?0+$/, '')}%`
                    : <span className="text-gray-600" title="Начислено до появления настройки">—</span>
            ),
        },
        {
            key: 'source',
            title: 'Источник',
            render: (r) => (
                r.source
                    ? <span className="text-xs">{SOURCE_LABEL[r.source] ?? r.source}</span>
                    : <span className="text-gray-600">—</span>
            ),
        },
        {
            key: 'amount',
            title: 'Сумма',
            render: (r) => (
                <span className="text-green-400 font-medium whitespace-nowrap">
                    ${r.amount}
                </span>
            ),
        },
    ];

    return (
        <>
            <div className="flex flex-wrap gap-3 mb-4">
                <div className="relative flex-1 min-w-[200px]">
                    <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
                    <input
                        value={search}
                        onChange={(e) => { setSearch(e.target.value); setSkip(0); }}
                        placeholder="Реферер"
                        className="w-full pl-9 pr-3 py-2 rounded-lg bg-gray-800 border border-gray-700 text-white text-sm placeholder-gray-500 focus:outline-none focus:border-blue-500"
                    />
                </div>

                <select
                    value={level}
                    onChange={(e) => { setLevel(e.target.value); setSkip(0); }}
                    className="px-3 py-2 rounded-lg bg-gray-800 border border-gray-700 text-white text-sm"
                >
                    <option value="">Все уровни</option>
                    <option value="1">Уровень 1</option>
                    <option value="2">Уровень 2</option>
                </select>

                <select
                    value={source}
                    onChange={(e) => { setSource(e.target.value); setSkip(0); }}
                    className="px-3 py-2 rounded-lg bg-gray-800 border border-gray-700 text-white text-sm"
                >
                    <option value="">Все источники</option>
                    <option value="product">Товары</option>
                    <option value="subscription">Подписки</option>
                    <option value="p2p">Товары пользователей</option>
                </select>
            </div>

            <DataTable
                columns={columns}
                rows={rows}
                rowKey={(r) => r.id}
                loading={loading}
                error={error}
                emptyText="Начислений нет"
            />
            <Pagination total={total} skip={skip} limit={LIMIT} onChange={setSkip} />
        </>
    );
};

const TopTab: React.FC = () => {
    const [rows, setRows] = useState<any[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        referralsApi.top({ limit: 50 })
            .then((d) => setRows(d.items ?? []))
            .catch((e) => setError(errorText(e)))
            .finally(() => setLoading(false));
    }, []);

    const columns: Column<any>[] = [
        {
            key: 'rank',
            title: '#',
            render: (r) => {
                const index = rows.indexOf(r);
                return (
                    <span className={index < 3 ? 'text-amber-400' : 'text-gray-600'}>
                        {index < 3 ? <Trophy size={14} /> : index + 1}
                    </span>
                );
            },
        },
        {
            key: 'user',
            title: 'Реферер',
            render: (r) => (
                <span className="text-white">
                    {r.username ? `@${r.username}` : r.telegram_id ?? '—'}
                </span>
            ),
        },
        { key: 'invited', title: 'Приглашено' },
        { key: 'accruals', title: 'Начислений' },
        {
            key: 'earned',
            title: 'Заработано',
            render: (r) => <span className="text-green-400 font-medium">${r.earned}</span>,
        },
    ];

    return (
        <DataTable
            columns={columns}
            rows={rows}
            rowKey={(r) => r.user_id}
            loading={loading}
            error={error}
            emptyText="Пока никто ничего не заработал"
        />
    );
};
