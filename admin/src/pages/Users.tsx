import React, { useCallback, useEffect, useState } from 'react';
import { Search, Ban, ShieldCheck, X, ExternalLink } from 'lucide-react';
import { usersApi, type AdminUser } from '../api/admin';
import { DataTable, type Column } from '../components/ui/DataTable';
import { Pagination } from '../components/ui/Pagination';
import { Badge, StatusBadge } from '../components/ui/Badge';
import { useToast, errorText } from '../components/ui/Toast';

const LIMIT = 25;

export const Users: React.FC = () => {
    const toast = useToast();
    const [rows, setRows] = useState<AdminUser[]>([]);
    const [total, setTotal] = useState(0);
    const [skip, setSkip] = useState(0);
    const [search, setSearch] = useState('');
    const [blockedOnly, setBlockedOnly] = useState<boolean | undefined>(undefined);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [cardId, setCardId] = useState<string | null>(null);

    const load = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const page = await usersApi.list({
                search: search || undefined,
                blocked: blockedOnly,
                skip,
                limit: LIMIT,
            });
            setRows(page.items);
            setTotal(page.total);
        } catch (e) {
            setError(errorText(e, 'Не удалось загрузить пользователей'));
        } finally {
            setLoading(false);
        }
    }, [search, blockedOnly, skip]);

    // Поиск с задержкой: запрос на каждую букву заваливает бэкенд
    useEffect(() => {
        const timer = setTimeout(load, search ? 350 : 0);
        return () => clearTimeout(timer);
    }, [load, search]);

    const toggleBlock = async (user: AdminUser) => {
        const blocking = !user.is_blocked;
        if (blocking && !window.confirm(
            `Заблокировать ${user.first_name}? Он потеряет доступ к приложению полностью.`
        )) return;

        try {
            const result = await usersApi.block(user.id, blocking);
            if (blocking && result.open_deals > 0) {
                toast.error(
                    `Заблокирован, но у него ${result.open_deals} открытых сделок — ` +
                    `закрыть их сам он больше не сможет`
                );
            } else {
                toast.success(blocking ? 'Пользователь заблокирован' : 'Блокировка снята');
            }
            await load();
        } catch (e) {
            toast.fromError(e);
        }
    };

    const columns: Column<AdminUser>[] = [
        {
            key: 'telegram_id',
            title: 'Telegram ID',
            render: (u) => <span className="font-mono text-xs">{u.telegram_id}</span>,
        },
        {
            key: 'name',
            title: 'Пользователь',
            render: (u) => (
                <div>
                    <div className="text-white font-medium flex items-center gap-2">
                        {u.first_name}
                        {u.is_admin && <Badge tone="info">админ</Badge>}
                        {u.is_blocked && <StatusBadge status="banned" />}
                    </div>
                    {u.username && <div className="text-xs text-gray-400">@{u.username}</div>}
                </div>
            ),
        },
        {
            key: 'orders',
            title: 'Заказы',
            render: (u) => (
                <div>
                    <div>{u.orders_count}</div>
                    <div className="text-xs text-gray-400">${u.orders_total_usdt.toFixed(2)}</div>
                </div>
            ),
        },
        {
            key: 'referrals',
            title: 'Рефералы',
            render: (u) => (
                <div>
                    <div>{u.referrals_count}</div>
                    <div className="text-xs text-gray-400">${(u.referral_earnings ?? 0).toFixed(2)}</div>
                </div>
            ),
        },
        {
            key: 'created_at',
            title: 'Регистрация',
            render: (u) => new Date(u.created_at).toLocaleDateString('ru-RU'),
        },
        {
            key: 'actions',
            title: '',
            render: (u) => (
                <div className="flex items-center gap-2 justify-end">
                    <button
                        onClick={(e) => { e.stopPropagation(); setCardId(u.id); }}
                        className="p-2 rounded-lg bg-gray-700 hover:bg-gray-600 text-gray-300"
                        title="Карточка"
                    >
                        <ExternalLink size={14} />
                    </button>
                    {!u.is_admin && (
                        <button
                            onClick={(e) => { e.stopPropagation(); toggleBlock(u); }}
                            className={`p-2 rounded-lg ${
                                u.is_blocked
                                    ? 'bg-green-600/20 text-green-400 hover:bg-green-600/30'
                                    : 'bg-red-600/20 text-red-400 hover:bg-red-600/30'
                            }`}
                            title={u.is_blocked ? 'Разблокировать' : 'Заблокировать'}
                        >
                            {u.is_blocked ? <ShieldCheck size={14} /> : <Ban size={14} />}
                        </button>
                    )}
                </div>
            ),
            className: 'text-right',
        },
    ];

    return (
        <div>
            <h1 className="text-2xl md:text-3xl font-bold text-white mb-6">Пользователи</h1>

            <div className="flex flex-wrap gap-3 mb-4">
                <div className="relative flex-1 min-w-[220px]">
                    <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
                    <input
                        value={search}
                        onChange={(e) => { setSearch(e.target.value); setSkip(0); }}
                        placeholder="Имя, username или Telegram ID"
                        className="w-full pl-9 pr-3 py-2 rounded-lg bg-gray-800 border border-gray-700 text-white text-sm placeholder-gray-500 focus:outline-none focus:border-blue-500"
                    />
                </div>

                <select
                    value={blockedOnly === undefined ? 'all' : blockedOnly ? 'blocked' : 'active'}
                    onChange={(e) => {
                        const v = e.target.value;
                        setBlockedOnly(v === 'all' ? undefined : v === 'blocked');
                        setSkip(0);
                    }}
                    className="px-3 py-2 rounded-lg bg-gray-800 border border-gray-700 text-white text-sm focus:outline-none focus:border-blue-500"
                >
                    <option value="all">Все</option>
                    <option value="active">Активные</option>
                    <option value="blocked">Заблокированные</option>
                </select>
            </div>

            <DataTable
                columns={columns}
                rows={rows}
                rowKey={(u) => u.id}
                loading={loading}
                error={error}
                emptyText="Никого не нашлось"
            />

            <Pagination total={total} skip={skip} limit={LIMIT} onChange={setSkip} />

            {cardId && <UserCard userId={cardId} onClose={() => setCardId(null)} />}
        </div>
    );
};

/* ------------------------------------------------------------------ */
/* Карточка                                                            */
/* ------------------------------------------------------------------ */

const UserCard: React.FC<{ userId: string; onClose: () => void }> = ({ userId, onClose }) => {
    const [data, setData] = useState<any>(null);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        usersApi.card(userId).then(setData).catch((e) => setError(errorText(e)));
    }, [userId]);

    return (
        <div className="fixed inset-0 bg-black/60 z-50 flex items-start justify-center overflow-y-auto p-4">
            <div className="bg-gray-800 rounded-xl border border-gray-700 w-full max-w-3xl my-8">
                <div className="flex items-center justify-between p-5 border-b border-gray-700 sticky top-0 bg-gray-800 rounded-t-xl">
                    <h2 className="text-lg font-semibold text-white">
                        {data ? `${data.first_name}${data.username ? ` (@${data.username})` : ''}` : 'Загрузка...'}
                    </h2>
                    <button onClick={onClose} className="text-gray-400 hover:text-white">
                        <X size={20} />
                    </button>
                </div>

                <div className="p-5 space-y-5">
                    {error && <div className="text-red-400 text-sm">{error}</div>}

                    {data && (
                        <>
                            <Section title="Профиль">
                                <Field label="Telegram ID" value={data.telegram_id} mono />
                                <Field label="Реф. код" value={data.referral_code} mono />
                                <Field label="Начислено рефералов" value={`$${data.referral_accrued_total}`} />
                                <Field
                                    label="Регистрация"
                                    value={new Date(data.created_at).toLocaleString('ru-RU')}
                                />
                                {data.referrer && (
                                    <Field
                                        label="Пригласил"
                                        value={data.referrer.username ? `@${data.referrer.username}` : data.referrer.telegram_id}
                                    />
                                )}
                            </Section>

                            {data.seller && (
                                <Section title="Продавец">
                                    <Field label="Имя" value={data.seller.display_name} />
                                    <Field label="Статус" value={<StatusBadge status={data.seller.status} />} />
                                    <Field label="Сделок" value={data.seller.deals_completed} />
                                    <Field label="Кошелёк" value={data.seller.payout_wallet} mono />
                                </Section>
                            )}

                            {data.accounts.length > 0 && (
                                <Section title="Счета">
                                    {data.accounts.map((a: any) => (
                                        <Field
                                            key={a.currency}
                                            label={a.currency}
                                            value={`${a.balance}${Number(a.hold) ? ` (заморожено ${a.hold})` : ''}`}
                                        />
                                    ))}
                                </Section>
                            )}

                            <ListSection
                                title={`Заказы (${data.orders.length})`}
                                rows={data.orders}
                                render={(o: any) => (
                                    <>
                                        <span className="text-gray-300">${o.total_usdt.toFixed(2)}</span>
                                        <StatusBadge status={o.status} />
                                        <span className="text-gray-500 text-xs">
                                            {new Date(o.created_at).toLocaleDateString('ru-RU')}
                                        </span>
                                    </>
                                )}
                            />

                            <ListSection
                                title={`Сделки (${data.deals.length})`}
                                rows={data.deals}
                                render={(d: any) => (
                                    <>
                                        <span className="text-gray-300">№{d.number} {d.product_name}</span>
                                        <Badge tone="neutral">{d.role === 'buyer' ? 'покупка' : 'продажа'}</Badge>
                                        <StatusBadge status={d.status} />
                                    </>
                                )}
                            />

                            <ListSection
                                title={`Рефералы (${data.referrals.length})`}
                                rows={data.referrals}
                                render={(r: any) => (
                                    <>
                                        <span className="text-gray-300">
                                            {r.username ? `@${r.username}` : r.telegram_id}
                                        </span>
                                        <span className="text-gray-500 text-xs">
                                            {new Date(r.created_at).toLocaleDateString('ru-RU')}
                                        </span>
                                    </>
                                )}
                            />

                            <ListSection
                                title={`Выводы (${data.withdrawals.length})`}
                                rows={data.withdrawals}
                                render={(w: any) => (
                                    <>
                                        <span className="text-gray-300">${w.amount.toFixed(2)}</span>
                                        <StatusBadge status={w.status} />
                                    </>
                                )}
                            />
                        </>
                    )}
                </div>
            </div>
        </div>
    );
};

const Section: React.FC<{ title: string; children: React.ReactNode }> = ({ title, children }) => (
    <div>
        <h3 className="text-sm font-semibold text-gray-400 mb-2">{title}</h3>
        <div className="bg-gray-900/50 rounded-lg p-3 space-y-1.5">{children}</div>
    </div>
);

const Field: React.FC<{ label: string; value: React.ReactNode; mono?: boolean }> = ({
    label, value, mono,
}) => (
    <div className="flex items-start justify-between gap-4 text-sm">
        <span className="text-gray-500">{label}</span>
        <span className={`text-gray-200 text-right break-all ${mono ? 'font-mono text-xs' : ''}`}>
            {value}
        </span>
    </div>
);

const ListSection: React.FC<{
    title: string;
    rows: any[];
    render: (row: any) => React.ReactNode;
}> = ({ title, rows, render }) => {
    if (rows.length === 0) return null;
    return (
        <Section title={title}>
            {rows.slice(0, 20).map((row) => (
                <div key={row.id} className="flex items-center gap-3 flex-wrap text-sm py-1">
                    {render(row)}
                </div>
            ))}
            {rows.length > 20 && (
                <div className="text-xs text-gray-500 pt-1">…и ещё {rows.length - 20}</div>
            )}
        </Section>
    );
};
