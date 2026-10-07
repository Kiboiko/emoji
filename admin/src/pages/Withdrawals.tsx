import React, { useState, useEffect, useCallback } from 'react';
import { CHAIN, TonConnectButton, useTonConnectUI, useTonWallet } from '@tonconnect/ui-react';
import { Address, beginCell } from '@ton/core';
import { adminApi, type PayoutSummary } from '../api/axios';
import { DataTable, type Column } from '../components/ui/DataTable';
import { useToast } from '../components/ui/Toast';
import {
    AlertTriangle,
    CheckCircle,
    ChevronLeft,
    ChevronRight,
    Clock,
    Copy,
    Loader2,
    Send,
    XCircle,
} from 'lucide-react';

interface Withdrawal {
    id: string;
    user_id: string;
    user_first_name: string;
    user_telegram_id: number;
    amount: number;
    /** TON — общий баланс; USD — старые реферальные заявки на USDT */
    currency?: string;
    wallet: string;
    /** sending — перевод подписан в кошельке, ждём его в блокчейне */
    status: 'pending' | 'sending' | 'completed' | 'rejected';
    created_at: string;
    completed_at?: string;
    sent_at?: string | null;
    reject_reason?: string | null;
}

type Tab = 'pending' | 'completed' | 'rejected';

const tonText = (nano: string | null | undefined) => {
    if (nano === null || nano === undefined) return '—';
    const value = Number(nano) / 1e9;
    return `${value.toLocaleString('ru-RU', { maximumFractionDigits: 4 })} TON`;
};

/** Ячейка с текстовым комментарием — так его видит получатель в кошельке */
const commentPayload = (comment: string) =>
    beginCell().storeUint(0, 32).storeStringTail(comment).endCell().toBoc().toString('base64');

const sameAddress = (a: string, b: string) => {
    try {
        return Address.parse(a).equals(Address.parse(b));
    } catch {
        return false;
    }
};

/**
 * Выводы.
 *
 * Выплату подписывает админ в кошельке площадки: «Выплатить» → кошелёк через
 * TonConnect показывает готовый перевод (адрес, сумма, комментарий) →
 * подтверждение. Приватного ключа на сервере нет, поэтому без этого
 * подтверждения деньги не уйдут, даже если войти в админку чужими руками.
 * Сервер находит перевод в блокчейне по комментарию и закрывает заявку сам.
 * Комиссию сети платит площадка: человек получает ровно сумму заявки.
 */
export const Withdrawals: React.FC = () => {
    const toast = useToast();
    const [tonConnectUI] = useTonConnectUI();
    const wallet = useTonWallet();

    const [withdrawals, setWithdrawals] = useState<Withdrawal[]>([]);
    const [loading, setLoading] = useState(true);
    const [filter, setFilter] = useState<Tab>('pending');
    const [page, setPage] = useState(0);
    const [total, setTotal] = useState(0);
    const [summary, setSummary] = useState<PayoutSummary | null>(null);
    const [busyId, setBusyId] = useState<string | null>(null);
    const limit = 10;

    const loadWithdrawals = useCallback(async () => {
        setLoading(true);
        try {
            const { data } = await adminApi.getWithdrawals({
                status: filter,
                skip: page * limit,
                limit
            });
            setWithdrawals(data.items);
            setTotal(data.total);
        } catch (error) {
            toast.fromError(error);
        } finally {
            setLoading(false);
        }
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [filter, page]);

    const loadSummary = useCallback(async () => {
        try {
            setSummary((await adminApi.getPayoutSummary()).data);
        } catch {
            setSummary(null);
        }
    }, []);

    useEffect(() => { loadWithdrawals(); }, [loadWithdrawals]);
    useEffect(() => { loadSummary(); }, [loadSummary]);

    // Пока есть отправленные, но не подтверждённые сетью — перечитываем:
    // сервер закрывает их сам, как только перевод появится в блокчейне
    const waiting = withdrawals.some((w) => w.status === 'sending');
    useEffect(() => {
        if (!waiting) return;
        const timer = setInterval(() => { loadWithdrawals(); loadSummary(); }, 15_000);
        return () => clearInterval(timer);
    }, [waiting, loadWithdrawals, loadSummary]);

    const reload = () => { loadWithdrawals(); loadSummary(); };

    const expectedChain = summary?.network === 'mainnet' ? CHAIN.MAINNET : CHAIN.TESTNET;
    const wrongNetwork = Boolean(wallet && summary && wallet.account.chain !== expectedChain);
    const notPlatformWallet = Boolean(
        wallet && summary?.platform_address && !sameAddress(wallet.account.address, summary.platform_address),
    );

    const pay = async (w: Withdrawal) => {
        if (!wallet) {
            toast.error('Сначала подключите кошелёк площадки — кнопка над списком');
            return;
        }
        setBusyId(w.id);
        try {
            const { data } = await adminApi.preparePayout(w.id);
            await tonConnectUI.sendTransaction({
                validUntil: data.valid_until,
                network: data.network === 'mainnet' ? CHAIN.MAINNET : CHAIN.TESTNET,
                messages: [{
                    address: data.address,
                    amount: data.amount_nano,
                    payload: commentPayload(data.comment),
                }],
            });
            await adminApi.payoutSent(w.id);
            toast.success('Перевод отправлен. Заявка закроется, когда он появится в сети');
            reload();
        } catch (error: any) {
            // Отказ в кошельке — не ошибка: заявка остаётся в ожидании
            const message = String(error?.message ?? '');
            if (/reject|declin|cancel|not sent/i.test(message)) {
                toast.error('Перевод не подтверждён в кошельке — заявка по-прежнему ждёт');
            } else {
                toast.fromError(error);
            }
        } finally {
            setBusyId(null);
        }
    };

    const markPaid = async (w: Withdrawal) => {
        const amount = `${w.amount} ${w.currency === 'USD' ? 'USDT' : 'TON'}`;
        const ok = window.confirm(
            w.status === 'sending'
                ? `Перевод ${amount} точно дошёл?\n\nЗаявка закроется, человеку придёт сообщение. Отменить нельзя.`
                : `Вы уже перевели ${amount} на кошелёк получателя вручную?\n\n` +
                  'Нажатие спишет сумму со счёта и отправит человеку уведомление. Отменить нельзя.'
        );
        if (!ok) return;
        setBusyId(w.id);
        try {
            await adminApi.updateWithdrawalStatus(w.id, 'completed');
            toast.success('Заявка закрыта');
            reload();
        } catch (error) {
            toast.fromError(error);
        } finally {
            setBusyId(null);
        }
    };

    const notArrived = async (w: Withdrawal) => {
        const ok = window.confirm(
            'Перевод не прошёл?\n\nПроверьте историю кошелька площадки: если перевод всё-таки ' +
            'ушёл, повторная выплата отправит деньги второй раз. Заявка вернётся в ожидание; ' +
            'если перевод дойдёт позже, она закроется сама.'
        );
        if (!ok) return;
        setBusyId(w.id);
        try {
            await adminApi.updateWithdrawalStatus(w.id, 'pending');
            reload();
        } catch (error) {
            toast.fromError(error);
        } finally {
            setBusyId(null);
        }
    };

    const reject = async (w: Withdrawal) => {
        const reason = window.prompt('Причина отказа — её увидит человек. Деньги вернутся ему на баланс.');
        if (!reason || reason.trim().length < 3) return;
        setBusyId(w.id);
        try {
            await adminApi.rejectWithdrawal(w.id, reason.trim());
            toast.success('Заявка отклонена, деньги вернулись на баланс');
            reload();
        } catch (error) {
            toast.fromError(error);
        } finally {
            setBusyId(null);
        }
    };

    const totalPages = Math.ceil(total / limit);

    const money = (w: Withdrawal) => (w.currency === 'TON'
        // У TON девять знаков — округление до двух показало бы 0.00 вместо
        // реальной суммы
        ? `${w.amount.toFixed(9).replace(/0+$/, '').replace(/\.$/, '')} TON`
        : `$${w.amount.toFixed(2)}`);

    const actions = (w: Withdrawal) => {
        const busy = busyId === w.id;
        if (w.status === 'completed') {
            return (
                <div className="text-gray-500 flex items-center gap-2 md:justify-end">
                    <CheckCircle size={16} />
                    {w.completed_at && new Date(w.completed_at).toLocaleDateString('ru-RU')}
                </div>
            );
        }
        if (w.status === 'rejected') {
            return (
                <div className="text-red-400 text-sm md:text-right">
                    <div className="flex items-center gap-2 md:justify-end"><XCircle size={16} />Отклонена</div>
                    {w.reject_reason && <div className="text-gray-500 text-xs mt-1">{w.reject_reason}</div>}
                </div>
            );
        }
        if (w.status === 'sending') {
            return (
                <div className="flex flex-col gap-2 md:items-end">
                    <span className="inline-flex items-center gap-2 text-amber-400 text-sm">
                        <Loader2 size={14} className="animate-spin" />
                        Отправлено, ждём сеть
                    </span>
                    <div className="flex gap-2">
                        <button
                            onClick={() => markPaid(w)}
                            disabled={busy}
                            className="px-3 py-1.5 rounded-lg bg-gray-700 hover:bg-gray-600 text-white text-xs"
                        >
                            Дошло
                        </button>
                        <button
                            onClick={() => notArrived(w)}
                            disabled={busy}
                            className="px-3 py-1.5 rounded-lg bg-gray-700 hover:bg-gray-600 text-gray-300 text-xs"
                        >
                            Не прошёл
                        </button>
                    </div>
                </div>
            );
        }
        const isTon = (w.currency || 'USD') === 'TON';
        return (
            <div className="flex flex-col gap-2 md:items-end">
                {isTon && (
                    <button
                        onClick={() => pay(w)}
                        disabled={busy || !wallet || wrongNetwork}
                        title={!wallet ? 'Подключите кошелёк площадки' : undefined}
                        className="bg-green-600 hover:bg-green-700 disabled:opacity-40 text-white px-4 py-2 rounded-lg text-sm font-medium flex items-center justify-center gap-2 transition-colors w-full md:w-auto whitespace-nowrap"
                    >
                        {busy ? <Loader2 size={16} className="animate-spin" /> : <Send size={16} />}
                        Выплатить
                    </button>
                )}
                <div className="flex gap-2 w-full md:w-auto">
                    {/* Ручная отметка — для выплат мимо TonConnect и для
                        старых заявок в USDT */}
                    <button
                        onClick={() => markPaid(w)}
                        disabled={busy}
                        className={`flex-1 px-3 py-1.5 rounded-lg text-xs whitespace-nowrap ${isTon
                            ? 'bg-gray-700 hover:bg-gray-600 text-gray-300'
                            : 'bg-green-600 hover:bg-green-700 text-white'}`}
                    >
                        Выплачено вручную
                    </button>
                    <button
                        onClick={() => reject(w)}
                        disabled={busy}
                        className="flex-1 px-3 py-1.5 rounded-lg bg-gray-700 hover:bg-red-900/60 text-red-300 text-xs"
                    >
                        Отклонить
                    </button>
                </div>
            </div>
        );
    };

    const columns: Column<Withdrawal>[] = [
        {
            key: 'user',
            title: 'Пользователь',
            // На телефоне это заголовок карточки, подпись ему не нужна
            wide: true,
            render: (w) => (
                <div className="flex flex-col">
                    <span className="text-white font-medium">{w.user_first_name}</span>
                    <span className="text-xs text-gray-400">ID: {w.user_telegram_id}</span>
                </div>
            ),
        },
        {
            key: 'amount',
            title: 'Сумма',
            render: (w) => <span className="text-green-400 font-bold">{money(w)}</span>,
        },
        {
            key: 'wallet',
            title: 'Кошелёк',
            render: (w) => (
                <div className="flex items-center gap-2 justify-end md:justify-start">
                    {/* На телефоне адрес переносится целиком: обрезанный
                        кошелёк бесполезен, по нему нельзя свериться */}
                    <code className="bg-gray-900 border border-gray-700 px-2 py-1 rounded text-blue-400 text-xs break-all md:break-normal md:truncate md:max-w-[200px]">
                        {w.wallet}
                    </code>
                    <button
                        onClick={() => navigator.clipboard.writeText(w.wallet)}
                        className="shrink-0 text-gray-500 hover:text-white"
                        title="Копировать"
                    >
                        <Copy size={14} />
                    </button>
                </div>
            ),
        },
        {
            key: 'created_at',
            title: 'Дата',
            render: (w) => (
                <span className="inline-flex items-center gap-2 text-gray-400 text-sm">
                    <Clock size={14} className="shrink-0" />
                    {new Date(w.created_at).toLocaleString('ru-RU')}
                </span>
            ),
        },
        {
            key: 'action',
            title: 'Действие',
            className: 'text-right',
            wide: true,
            render: actions,
        },
    ];

    const tab = (value: Tab, label: string, color: string) => (
        <button
            onClick={() => { setFilter(value); setPage(0); }}
            className={`pb-3 px-2 text-sm font-medium transition-colors relative ${filter === value
                ? `${color} border-b-2 border-current`
                : 'text-gray-400 hover:text-white'
                }`}
        >
            {label}
        </button>
    );

    return (
        <div>
            <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 mb-6">
                <h1 className="text-2xl md:text-3xl font-bold text-white">Заявки на вывод</h1>

                <div className="flex gap-4 border-b border-gray-800">
                    {tab('pending', 'Новые', 'text-blue-400')}
                    {tab('completed', 'Выполнено', 'text-green-400')}
                    {tab('rejected', 'Отклонено', 'text-red-400')}
                </div>
            </div>

            {/* Кошелёк площадки и чьи на нём деньги */}
            <div className="bg-gray-800 rounded-xl border border-gray-700 p-5 mb-6">
                <div className="flex flex-col md:flex-row md:items-start md:justify-between gap-4">
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-4 flex-1">
                        <div>
                            <div className="text-xs text-gray-400 mb-1">На кошельке площадки</div>
                            <div className="text-white font-semibold">
                                {summary ? (summary.wallet_nano === null ? 'нет связи с сетью' : tonText(summary.wallet_nano)) : '…'}
                            </div>
                        </div>
                        <div>
                            <div className="text-xs text-gray-400 mb-1">Деньги пользователей</div>
                            <div className="text-white font-semibold">{tonText(summary?.users_nano)}</div>
                            {summary && Number(summary.withdrawals_nano) > 0 && (
                                <div className="text-xs text-gray-500">из них в заявках: {tonText(summary.withdrawals_nano)}</div>
                            )}
                        </div>
                        <div>
                            <div className="text-xs text-gray-400 mb-1">Заморожено в сделках</div>
                            <div className="text-white font-semibold">{tonText(summary?.escrow_nano)}</div>
                        </div>
                        <div>
                            <div className="text-xs text-gray-400 mb-1">Можно забрать себе</div>
                            <div className={`font-semibold ${summary?.free_nano && Number(summary.free_nano) < 0 ? 'text-red-400' : 'text-green-400'}`}>
                                {tonText(summary?.free_nano)}
                            </div>
                        </div>
                    </div>
                    <div className="shrink-0">
                        <TonConnectButton />
                    </div>
                </div>

                <p className="text-xs text-gray-500 mt-4">
                    «Можно забрать» — остаток кошелька после денег пользователей и сделок.
                    Комиссии сети за выплаты и реферальные в нём уже учтены.
                    {summary && summary.network !== 'mainnet' && ' Сейчас площадка работает в тестовой сети.'}
                </p>

                {wrongNetwork && (
                    <div className="mt-3 flex items-center gap-2 text-amber-400 text-sm">
                        <AlertTriangle size={16} />
                        Кошелёк подключён к другой сети, площадка работает в {summary?.network}. Переключите сеть в кошельке.
                    </div>
                )}
                {notPlatformWallet && !wrongNetwork && (
                    <div className="mt-3 flex items-center gap-2 text-amber-400 text-sm">
                        <AlertTriangle size={16} />
                        Подключён не кошелёк площадки. Выплатить можно, но деньги уйдут с этого кошелька.
                    </div>
                )}
            </div>

            <DataTable<Withdrawal>
                columns={columns}
                rows={withdrawals}
                rowKey={(w) => w.id}
                loading={loading}
                emptyText="Нет заявок"
            />

            {/* Pagination */}
            {totalPages > 1 && (
                <div className="flex justify-center items-center gap-4 mt-8">
                    <button
                        onClick={() => setPage(prev => Math.max(0, prev - 1))}
                        disabled={page === 0 || loading}
                        className="p-2 rounded-lg bg-gray-800 border border-gray-700 text-gray-400 hover:bg-gray-700 hover:text-white disabled:opacity-50 disabled:hover:bg-gray-800 transition-colors"
                    >
                        <ChevronLeft size={20} />
                    </button>

                    <span className="text-gray-400 font-medium whitespace-nowrap">
                        Страница <span className="text-white">{page + 1}</span> из <span className="text-white">{totalPages}</span>
                    </span>

                    <button
                        onClick={() => setPage(prev => Math.min(totalPages - 1, prev + 1))}
                        disabled={page === totalPages - 1 || loading}
                        className="p-2 rounded-lg bg-gray-800 border border-gray-700 text-gray-400 hover:bg-gray-700 hover:text-white disabled:opacity-50 disabled:hover:bg-gray-800 transition-colors"
                    >
                        <ChevronRight size={20} />
                    </button>
                </div>
            )}
        </div>
    );
};
