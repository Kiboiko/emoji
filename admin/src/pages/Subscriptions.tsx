import React, { useCallback, useEffect, useState } from 'react';
import { Check, X, Ban, RefreshCw, AlertTriangle, Link2, BadgeCheck } from 'lucide-react';
import { subscriptionsApi } from '../api/admin';
import { DataTable, type Column } from '../components/ui/DataTable';
import { Pagination } from '../components/ui/Pagination';
import { Badge, StatusBadge } from '../components/ui/Badge';
import { useToast, errorText } from '../components/ui/Toast';

const LIMIT = 25;

const CHANNEL_STATUSES = [
    { value: 'pending', label: 'На модерации' },
    { value: 'active', label: 'Активные' },
    { value: 'suspended', label: 'Снятые' },
    { value: 'rejected', label: 'Отклонённые' },
    { value: '', label: 'Все' },
];

const SUB_STATUSES = [
    { value: 'active', label: 'Активные' },
    { value: 'pending', label: 'Ожидают' },
    { value: 'expired', label: 'Истёкшие' },
    { value: 'revoked', label: 'Отозванные' },
    { value: '', label: 'Все' },
];

export const Subscriptions: React.FC = () => {
    const [tab, setTab] = useState<'channels' | 'subs'>('channels');

    return (
        <div>
            <h1 className="text-2xl md:text-3xl font-bold text-white mb-6">Каналы и подписки</h1>

            <div className="flex gap-2 mb-5">
                <button
                    onClick={() => setTab('channels')}
                    className={`px-4 py-2 rounded-lg text-sm ${
                        tab === 'channels' ? 'bg-blue-600 text-white' : 'bg-gray-800 text-gray-400 hover:bg-gray-700'
                    }`}
                >
                    Каналы
                </button>
                <button
                    onClick={() => setTab('subs')}
                    className={`px-4 py-2 rounded-lg text-sm ${
                        tab === 'subs' ? 'bg-blue-600 text-white' : 'bg-gray-800 text-gray-400 hover:bg-gray-700'
                    }`}
                >
                    Подписки
                </button>
            </div>

            {tab === 'channels' ? <ChannelsTab /> : <SubsTab />}
        </div>
    );
};

/* ------------------------------------------------------------------ */

const ChannelsTab: React.FC = () => {
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
            const page = await subscriptionsApi.channels({
                status: status || undefined, skip, limit: LIMIT,
            });
            setRows(page.items ?? []);
            setTotal(page.total ?? 0);
        } catch (e) {
            setError(errorText(e, 'Не удалось загрузить каналы'));
        } finally {
            setLoading(false);
        }
    }, [status, skip]);

    useEffect(() => { load(); }, [load]);

    const moderate = async (channel: any, approve: boolean) => {
        let comment: string | undefined;
        if (!approve) {
            const input = window.prompt('Причина отказа (отправится владельцу):');
            if (!input?.trim()) return;
            comment = input.trim();
        } else if (!channel.bot_is_admin && !window.confirm(
            'Бот не подтверждён как администратор канала. Без прав он не сможет ' +
            'выдавать приглашения и удалять по окончании подписки. Всё равно одобрить?'
        )) {
            return;
        }

        setBusy(channel.id);
        try {
            await subscriptionsApi.moderateChannel(channel.id, approve, comment);
            toast.success(approve ? 'Канал опубликован' : 'Канал отклонён');
            await load();
        } catch (e) {
            toast.fromError(e);
        } finally {
            setBusy(null);
        }
    };

    // Галочка не связана с модерацией: одобрение значит «подписки можно
    // продавать», галочка — «площадка подтвердила, кто за каналом стоит»
    const toggleVerified = async (channel: any) => {
        setBusy(channel.id);
        try {
            await subscriptionsApi.setChannelVerified(channel.id, !channel.is_verified);
            toast.success(channel.is_verified ? 'Галочка снята' : 'Автор отмечен как проверенный');
            await load();
        } catch (e) {
            toast.fromError(e);
        } finally {
            setBusy(null);
        }
    };

    const suspend = async (channel: any) => {
        const reason = window.prompt('Причина снятия канала:');
        if (!reason?.trim()) return;

        setBusy(channel.id);
        try {
            await subscriptionsApi.suspendChannel(channel.id, reason.trim());
            toast.success('Канал снят с публикации');
            await load();
        } catch (e) {
            toast.fromError(e);
        } finally {
            setBusy(null);
        }
    };

    const columns: Column<any>[] = [
        {
            key: 'title',
            title: 'Канал',
            render: (c) => (
                <div>
                    <div className="text-white font-medium flex items-center gap-2">
                        {c.title}
                        {c.is_verified && (
                            <BadgeCheck size={14} className="text-violet-400" aria-label="Проверенный автор" />
                        )}
                        {c.username && (
                            <a
                                href={`https://t.me/${c.username}`}
                                target="_blank"
                                rel="noreferrer"
                                onClick={(e) => e.stopPropagation()}
                                className="text-blue-400 hover:text-blue-300"
                            >
                                <Link2 size={13} />
                            </a>
                        )}
                    </div>
                    <div className="text-xs text-gray-500 font-mono">{c.telegram_chat_id}</div>
                </div>
            ),
        },
        {
            key: 'owner',
            title: 'Владелец',
            render: (c) => (
                <span className="text-sm">
                    {c.owner_username ? `@${c.owner_username}` : c.owner_telegram_id ?? '—'}
                </span>
            ),
        },
        {
            key: 'bot',
            title: 'Бот',
            render: (c) => (
                c.bot_is_admin
                    ? <Badge tone="success">админ</Badge>
                    : (
                        <div>
                            <Badge tone="danger">нет прав</Badge>
                            {c.bot_check_error && (
                                <div className="text-xs text-red-400 mt-1 max-w-[180px]">
                                    {c.bot_check_error}
                                </div>
                            )}
                        </div>
                    )
            ),
        },
        {
            key: 'stats',
            title: 'Тарифы / подписчики',
            render: (c) => (
                <span className="text-sm">{c.plans_count} / {c.active_subscribers}</span>
            ),
        },
        { key: 'status', title: 'Статус', render: (c) => <StatusBadge status={c.status} /> },
        {
            key: 'actions',
            title: '',
            render: (c) => (
                <div className="flex gap-2 justify-end">
                    <button
                        onClick={() => toggleVerified(c)}
                        disabled={busy === c.id}
                        className={`p-2 rounded-lg disabled:opacity-50 ${
                            c.is_verified
                                ? 'bg-violet-600/20 text-violet-300 hover:bg-violet-600/30'
                                : 'bg-gray-800 text-gray-400 hover:bg-gray-700'
                        }`}
                        title={c.is_verified ? 'Снять галочку' : 'Отметить проверенным'}
                    >
                        <BadgeCheck size={16} />
                    </button>

                    {c.status === 'pending' && (
                        <>
                            <button
                                onClick={() => moderate(c, true)}
                                disabled={busy === c.id}
                                className="p-2 rounded-lg bg-green-600/20 text-green-400 hover:bg-green-600/30 disabled:opacity-50"
                                title="Одобрить"
                            >
                                <Check size={14} />
                            </button>
                            <button
                                onClick={() => moderate(c, false)}
                                disabled={busy === c.id}
                                className="p-2 rounded-lg bg-red-600/20 text-red-400 hover:bg-red-600/30 disabled:opacity-50"
                                title="Отклонить"
                            >
                                <X size={14} />
                            </button>
                        </>
                    )}
                    {c.status === 'active' && (
                        <button
                            onClick={() => suspend(c)}
                            disabled={busy === c.id}
                            className="p-2 rounded-lg bg-amber-600/20 text-amber-400 hover:bg-amber-600/30 disabled:opacity-50"
                            title="Снять с публикации"
                        >
                            <Ban size={14} />
                        </button>
                    )}
                </div>
            ),
            className: 'text-right',
        },
    ];

    return (
        <>
            <div className="flex gap-2 mb-4 flex-wrap">
                {CHANNEL_STATUSES.map((s) => (
                    <button
                        key={s.value}
                        onClick={() => { setStatus(s.value); setSkip(0); }}
                        className={`px-3 py-1.5 rounded-lg text-sm ${
                            status === s.value
                                ? 'bg-gray-700 text-white'
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
                rowKey={(c) => c.id}
                loading={loading}
                error={error}
                emptyText="Каналов нет"
            />
            <Pagination total={total} skip={skip} limit={LIMIT} onChange={setSkip} />
        </>
    );
};

/* ------------------------------------------------------------------ */

const SubsTab: React.FC = () => {
    const toast = useToast();
    const [rows, setRows] = useState<any[]>([]);
    const [total, setTotal] = useState(0);
    const [skip, setSkip] = useState(0);
    const [status, setStatus] = useState('active');
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [busy, setBusy] = useState<string | null>(null);

    const load = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const page = await subscriptionsApi.list({
                status: status || undefined, skip, limit: LIMIT,
            });
            setRows(page.items ?? []);
            setTotal(page.total ?? 0);
        } catch (e) {
            setError(errorText(e, 'Не удалось загрузить подписки'));
        } finally {
            setLoading(false);
        }
    }, [status, skip]);

    useEffect(() => { load(); }, [load]);

    const revoke = async (sub: any) => {
        const reason = window.prompt('Причина отзыва (подписчик будет удалён из канала):');
        if (!reason?.trim()) return;

        setBusy(sub.id);
        try {
            await subscriptionsApi.revoke(sub.id, reason.trim());
            toast.success('Подписка отозвана');
            await load();
        } catch (e) {
            toast.fromError(e);
        } finally {
            setBusy(null);
        }
    };

    const reissue = async (sub: any) => {
        setBusy(sub.id);
        try {
            const result = await subscriptionsApi.reissueInvite(sub.id);
            toast.success(result.invite_link
                ? 'Ссылка перевыпущена и отправлена подписчику'
                : 'Ссылка перевыпущена');
            await load();
        } catch (e) {
            toast.fromError(e);
        } finally {
            setBusy(null);
        }
    };

    const columns: Column<any>[] = [
        {
            key: 'user',
            title: 'Подписчик',
            render: (s) => (
                <span className="text-sm">
                    {s.user_username ? `@${s.user_username}` : s.user_telegram_id ?? '—'}
                </span>
            ),
        },
        { key: 'channel_title', title: 'Канал' },
        { key: 'plan_title', title: 'Тариф' },
        {
            key: 'expires_at',
            title: 'Действует до',
            render: (s) => {
                if (!s.expires_at) return '—';
                // Остаток считаем здесь: бэкенд отдаёт только дату окончания,
                // а администратору важнее «сколько осталось», чем само число
                const left = Math.ceil(
                    (new Date(s.expires_at).getTime() - Date.now()) / 86_400_000,
                );
                return (
                    <div className="whitespace-nowrap">
                        <div>{new Date(s.expires_at).toLocaleDateString('ru-RU')}</div>
                        <div className={`text-xs ${left <= 3 ? 'text-amber-400' : 'text-gray-500'}`}>
                            {left > 0 ? `${left} дн.` : 'истекла'}
                        </div>
                    </div>
                );
            },
        },
        {
            key: 'joined',
            title: 'В канале',
            render: (s) => (
                s.joined
                    ? <Badge tone="success">да</Badge>
                    : (
                        <span className="flex items-center gap-1 text-amber-400 text-xs">
                            <AlertTriangle size={12} /> не вошёл
                        </span>
                    )
            ),
        },
        { key: 'status', title: 'Статус', render: (s) => <StatusBadge status={s.status} /> },
        {
            key: 'actions',
            title: '',
            render: (s) => (
                <div className="flex gap-2 justify-end">
                    {s.status === 'active' && (
                        <>
                            <button
                                onClick={() => reissue(s)}
                                disabled={busy === s.id}
                                className="p-2 rounded-lg bg-gray-700 hover:bg-gray-600 text-gray-300 disabled:opacity-50"
                                title="Перевыпустить приглашение"
                            >
                                <RefreshCw size={14} />
                            </button>
                            <button
                                onClick={() => revoke(s)}
                                disabled={busy === s.id}
                                className="p-2 rounded-lg bg-red-600/20 text-red-400 hover:bg-red-600/30 disabled:opacity-50"
                                title="Отозвать"
                            >
                                <Ban size={14} />
                            </button>
                        </>
                    )}
                </div>
            ),
            className: 'text-right',
        },
    ];

    return (
        <>
            <div className="flex gap-2 mb-4 flex-wrap">
                {SUB_STATUSES.map((s) => (
                    <button
                        key={s.value}
                        onClick={() => { setStatus(s.value); setSkip(0); }}
                        className={`px-3 py-1.5 rounded-lg text-sm ${
                            status === s.value
                                ? 'bg-gray-700 text-white'
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
                rowKey={(s) => s.id}
                loading={loading}
                error={error}
                emptyText="Подписок нет"
            />
            <Pagination total={total} skip={skip} limit={LIMIT} onChange={setSkip} />
        </>
    );
};
