import React, { useState, useEffect } from 'react';
import { adminApi } from '../api/axios';
import { DataTable, type Column } from '../components/ui/DataTable';
import {
    Clock,
    CheckCircle,
    ChevronLeft,
    ChevronRight,
    ExternalLink
} from 'lucide-react';

interface Withdrawal {
    id: string;
    user_id: string;
    user_first_name: string;
    user_telegram_id: number;
    amount: number;
    /** USD — реферальный баланс, TON — заработок продавца */
    currency?: string;
    wallet: string;
    status: 'pending' | 'completed';
    created_at: string;
    completed_at?: string;
}

export const Withdrawals: React.FC = () => {
    const [withdrawals, setWithdrawals] = useState<Withdrawal[]>([]);
    const [loading, setLoading] = useState(true);
    const [filter, setFilter] = useState<'pending' | 'completed'>('pending');
    const [page, setPage] = useState(0);
    const [total, setTotal] = useState(0);
    const limit = 10;

    const loadWithdrawals = React.useCallback(async () => {
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
            console.error('Failed to load withdrawals:', error);
        } finally {
            setLoading(false);
        }
    }, [filter, page]);

    useEffect(() => {
        loadWithdrawals();
    }, [loadWithdrawals]);

    const handleComplete = async (id: string, amount: number, currency: string) => {
        // Нажатие списывает деньги со счёта и уведомляет человека. Отменить
        // нельзя, поэтому спрашиваем не «пометить?», а проверяем порядок:
        // сначала перевод со своего кошелька, потом отметка здесь.
        const ok = window.confirm(
            `Вы уже перевели ${amount} ${currency} на кошелёк получателя?\n\n` +
            'Нажатие спишет сумму со счёта и отправит человеку уведомление. ' +
            'Отменить это действие нельзя.'
        );
        if (!ok) return;

        try {
            await adminApi.updateWithdrawalStatus(id, 'completed');
            loadWithdrawals();
        } catch (error) {
            console.error('Failed to update status:', error);
            alert('Ошибка при обновлении статуса');
        }
    };

    const totalPages = Math.ceil(total / limit);

    const money = (w: Withdrawal) => (w.currency === 'TON'
        // У TON девять знаков — округление до двух показало бы 0.00 вместо
        // реальной суммы
        ? `${w.amount.toFixed(9).replace(/0+$/, '').replace(/\.$/, '')} TON`
        : `$${w.amount.toFixed(2)}`);

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
                        <ExternalLink size={14} />
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
            render: (w) => (w.status === 'pending' ? (
                /* Подпись в повелительном наклонении: «Выполнено» в колонке
                   «Действие» читается как статус, и админ решает, что
                   выплата уже проведена. */
                <button
                    onClick={() => handleComplete(w.id, w.amount, w.currency || 'USD')}
                    className="bg-green-600 hover:bg-green-700 text-white px-4 py-2 rounded-lg text-sm font-medium flex items-center justify-center gap-2 transition-colors w-full md:w-auto md:ml-auto whitespace-nowrap"
                >
                    <CheckCircle size={16} />
                    Отметить выплаченным
                </button>
            ) : (
                <div className="text-gray-500 flex items-center gap-2 md:justify-end">
                    <CheckCircle size={16} />
                    {new Date(w.completed_at!).toLocaleDateString('ru-RU')}
                </div>
            )),
        },
    ];

    return (
        <div>
            <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 mb-6">
                {/* Раздел давно не только про реферальный баланс: сюда же
                    приходят выводы заработка продавцов и авторов каналов в TON */}
                <h1 className="text-2xl md:text-3xl font-bold text-white">
                    Заявки на вывод
                </h1>

                <div className="flex gap-4 border-b border-gray-800">
                    <button
                        onClick={() => { setFilter('pending'); setPage(0); }}
                        className={`pb-3 px-2 text-sm font-medium transition-colors relative ${filter === 'pending'
                            ? 'text-blue-400 border-b-2 border-blue-500'
                            : 'text-gray-400 hover:text-white'
                            }`}
                    >
                        Новые
                    </button>
                    <button
                        onClick={() => { setFilter('completed'); setPage(0); }}
                        className={`pb-3 px-2 text-sm font-medium transition-colors relative ${filter === 'completed'
                            ? 'text-green-400 border-b-2 border-green-500'
                            : 'text-gray-400 hover:text-white'
                            }`}
                    >
                        Выполнено
                    </button>
                </div>
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
