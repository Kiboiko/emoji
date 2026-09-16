import React, { useCallback, useEffect, useState } from 'react';
import { Scale, RefreshCw, Search, CheckCircle2, AlertTriangle, Loader2 } from 'lucide-react';
import { financeApi } from '../api/admin';
import { DataTable, type Column } from '../components/ui/DataTable';
import { Pagination } from '../components/ui/Pagination';
import { Badge } from '../components/ui/Badge';
import { useToast, errorText } from '../components/ui/Toast';

const LIMIT = 50;

const OWNER_LABEL: Record<string, string> = {
    external: 'Внешний мир',
    platform: 'Платформа',
    user: 'Пользователь',
};

export const Finance: React.FC = () => {
    const [tab, setTab] = useState<'accounts' | 'ledger'>('accounts');
    const [accountId, setAccountId] = useState<string | null>(null);

    return (
        <div className="p-4 md:p-8">
            <h1 className="text-2xl md:text-3xl font-bold text-white mb-6">Финансы</h1>

            <div className="flex gap-2 mb-5">
                <button
                    onClick={() => { setTab('accounts'); setAccountId(null); }}
                    className={`px-4 py-2 rounded-lg text-sm ${
                        tab === 'accounts' ? 'bg-blue-600 text-white' : 'bg-gray-800 text-gray-400 hover:bg-gray-700'
                    }`}
                >
                    Счета
                </button>
                <button
                    onClick={() => setTab('ledger')}
                    className={`px-4 py-2 rounded-lg text-sm ${
                        tab === 'ledger' ? 'bg-blue-600 text-white' : 'bg-gray-800 text-gray-400 hover:bg-gray-700'
                    }`}
                >
                    Журнал операций
                </button>
            </div>

            {tab === 'accounts'
                ? <AccountsTab onOpenLedger={(id) => { setAccountId(id); setTab('ledger'); }} />
                : <LedgerTab accountId={accountId} onClearFilter={() => setAccountId(null)} />}
        </div>
    );
};

/* ------------------------------------------------------------------ */

const AccountsTab: React.FC<{ onOpenLedger: (id: string) => void }> = ({ onOpenLedger }) => {
    const toast = useToast();
    const [rows, setRows] = useState<any[]>([]);
    const [total, setTotal] = useState(0);
    const [skip, setSkip] = useState(0);
    const [currency, setCurrency] = useState('');
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [checking, setChecking] = useState(false);
    const [reconcile, setReconcile] = useState<any>(null);

    const load = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const page = await financeApi.accounts({
                currency: currency || undefined, skip, limit: LIMIT,
            } as any);
            setRows(page.items ?? []);
            setTotal(page.total ?? 0);
        } catch (e) {
            setError(errorText(e, 'Не удалось загрузить счета'));
        } finally {
            setLoading(false);
        }
    }, [currency, skip]);

    useEffect(() => { load(); }, [load]);

    const runReconcile = async () => {
        setChecking(true);
        try {
            const result = await financeApi.reconcile();
            setReconcile(result);
            if (result.ok) {
                toast.success('Сверка сошлась: журнал и балансы совпадают');
            } else {
                toast.error('Расхождение между журналом и балансами');
            }
        } catch (e) {
            toast.fromError(e);
        } finally {
            setChecking(false);
        }
    };

    const scan = async () => {
        setChecking(true);
        try {
            const result = await financeApi.scanUnmatched();
            toast.success(
                result.matched
                    ? `Найдено и зачтено платежей: ${result.matched}`
                    : 'Незачтённых платежей не найдено',
            );
            await load();
        } catch (e) {
            toast.fromError(e);
        } finally {
            setChecking(false);
        }
    };

    const columns: Column<any>[] = [
        {
            key: 'owner',
            title: 'Владелец',
            render: (a) => (
                <div>
                    <Badge tone={a.owner_type === 'platform' ? 'info' : 'neutral'}>
                        {OWNER_LABEL[a.owner_type] ?? a.owner_type}
                    </Badge>
                    {a.owner_username && (
                        <div className="text-xs text-gray-400 mt-1">@{a.owner_username}</div>
                    )}
                    {!a.owner_username && a.owner_telegram_id && (
                        <div className="text-xs text-gray-500 mt-1 font-mono">{a.owner_telegram_id}</div>
                    )}
                </div>
            ),
        },
        { key: 'currency', title: 'Валюта' },
        {
            key: 'balance',
            title: 'Баланс',
            render: (a) => <span className="text-white font-medium">{a.balance}</span>,
        },
        {
            key: 'hold',
            title: 'Заморожено',
            render: (a) => (
                Number(a.hold) ? <span className="text-amber-400">{a.hold}</span> : '—'
            ),
        },
        {
            key: 'available',
            title: 'Доступно',
            render: (a) => a.available,
        },
        {
            key: 'actions',
            title: '',
            render: (a) => (
                <button
                    onClick={(e) => { e.stopPropagation(); onOpenLedger(a.id); }}
                    className="p-2 rounded-lg bg-gray-700 hover:bg-gray-600 text-gray-300"
                    title="Операции по счёту"
                >
                    <Search size={14} />
                </button>
            ),
            className: 'text-right',
        },
    ];

    return (
        <>
            <div className="flex flex-wrap gap-3 mb-4 items-center">
                <select
                    value={currency}
                    onChange={(e) => { setCurrency(e.target.value); setSkip(0); }}
                    className="px-3 py-2 rounded-lg bg-gray-800 border border-gray-700 text-white text-sm"
                >
                    <option value="">Все валюты</option>
                    <option value="TON">TON</option>
                    <option value="USD">USD</option>
                </select>

                <button
                    onClick={runReconcile}
                    disabled={checking}
                    className="flex items-center gap-2 px-4 py-2 rounded-lg bg-gray-800 border border-gray-700 text-gray-200 text-sm hover:bg-gray-700 disabled:opacity-50"
                >
                    {checking ? <Loader2 size={15} className="animate-spin" /> : <Scale size={15} />}
                    Сверить балансы
                </button>

                <button
                    onClick={scan}
                    disabled={checking}
                    className="flex items-center gap-2 px-4 py-2 rounded-lg bg-gray-800 border border-gray-700 text-gray-200 text-sm hover:bg-gray-700 disabled:opacity-50"
                    title="Искать оплаты, пришедшие после истечения счёта"
                >
                    <RefreshCw size={15} />
                    Найти незачтённые платежи
                </button>
            </div>

            {reconcile && (
                <div className={`mb-4 rounded-xl border p-4 text-sm ${
                    reconcile.ok
                        ? 'bg-green-500/10 border-green-500/30 text-green-300'
                        : 'bg-red-500/10 border-red-500/30 text-red-300'
                }`}>
                    <div className="flex items-center gap-2 font-medium mb-1">
                        {reconcile.ok ? <CheckCircle2 size={16} /> : <AlertTriangle size={16} />}
                        {reconcile.ok
                            ? 'Журнал и балансы сходятся'
                            : 'Балансы разошлись с журналом'}
                    </div>
                    <pre className="text-xs opacity-80 whitespace-pre-wrap">
                        {JSON.stringify(reconcile, null, 2)}
                    </pre>
                </div>
            )}

            <DataTable
                columns={columns}
                rows={rows}
                rowKey={(a) => a.id}
                loading={loading}
                error={error}
                emptyText="Счетов нет"
            />
            <Pagination total={total} skip={skip} limit={LIMIT} onChange={setSkip} />
        </>
    );
};

/* ------------------------------------------------------------------ */

const LedgerTab: React.FC<{
    accountId: string | null;
    onClearFilter: () => void;
}> = ({ accountId, onClearFilter }) => {
    const [rows, setRows] = useState<any[]>([]);
    const [total, setTotal] = useState(0);
    const [skip, setSkip] = useState(0);
    const [entryType, setEntryType] = useState('');
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    const load = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const page = await financeApi.ledger({
                account_id: accountId || undefined,
                entry_type: entryType || undefined,
                skip,
                limit: LIMIT,
            });
            setRows(page.items ?? []);
            setTotal(page.total ?? 0);
        } catch (e) {
            setError(errorText(e, 'Не удалось загрузить журнал'));
        } finally {
            setLoading(false);
        }
    }, [accountId, entryType, skip]);

    useEffect(() => { load(); }, [load]);

    const columns: Column<any>[] = [
        {
            key: 'created_at',
            title: 'Время',
            render: (e) => (
                <span className="whitespace-nowrap text-xs">
                    {new Date(e.created_at).toLocaleString('ru-RU')}
                </span>
            ),
        },
        { key: 'entry_type', title: 'Тип', render: (e) => <Badge>{e.entry_type}</Badge> },
        {
            key: 'amount',
            title: 'Сумма',
            render: (e) => (
                <span className={`font-medium whitespace-nowrap ${
                    e.amount_minor < 0 ? 'text-red-400' : 'text-green-400'
                }`}>
                    {e.amount_minor > 0 ? '+' : ''}{e.amount} {e.currency}
                </span>
            ),
        },
        {
            key: 'hold',
            title: 'Заморозка',
            render: (e) => (
                e.hold_delta_minor
                    ? <span className="text-amber-400 text-xs">{e.hold_delta_minor > 0 ? '+' : ''}{e.hold_delta_minor}</span>
                    : '—'
            ),
        },
        { key: 'ref_type', title: 'Основание', render: (e) => <span className="text-xs">{e.ref_type}</span> },
        {
            key: 'comment',
            title: 'Комментарий',
            render: (e) => <span className="text-xs text-gray-400">{e.comment ?? '—'}</span>,
        },
    ];

    const ENTRY_TYPES = [
        '', 'payment_in', 'referral_accrual', 'escrow_hold', 'escrow_release',
        'seller_accrual', 'commission', 'payout', 'manual_adjust',
    ];

    return (
        <>
            <div className="flex flex-wrap gap-3 mb-4 items-center">
                <select
                    value={entryType}
                    onChange={(e) => { setEntryType(e.target.value); setSkip(0); }}
                    className="px-3 py-2 rounded-lg bg-gray-800 border border-gray-700 text-white text-sm"
                >
                    {ENTRY_TYPES.map((t) => (
                        <option key={t} value={t}>{t || 'Все типы'}</option>
                    ))}
                </select>

                {accountId && (
                    <button
                        onClick={onClearFilter}
                        className="px-3 py-2 rounded-lg bg-blue-600/20 text-blue-300 text-sm hover:bg-blue-600/30"
                    >
                        Фильтр по счёту — снять
                    </button>
                )}
            </div>

            <DataTable
                columns={columns}
                rows={rows}
                rowKey={(e) => e.id}
                loading={loading}
                error={error}
                emptyText="Операций нет"
            />
            <Pagination total={total} skip={skip} limit={LIMIT} onChange={setSkip} />
        </>
    );
};
