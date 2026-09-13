import React, { useState, useEffect } from 'react';
import { adminApi } from '../api/axios';
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

    const handleComplete = async (id: string) => {
        if (!window.confirm('Пометить как выполненное?')) return;

        try {
            await adminApi.updateWithdrawalStatus(id, 'completed');
            loadWithdrawals();
        } catch (error) {
            console.error('Failed to update status:', error);
            alert('Ошибка при обновлении статуса');
        }
    };

    const totalPages = Math.ceil(total / limit);

    return (
        <div className="p-6">
            <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 mb-6">
                <h1 className="text-3xl font-bold text-white">
                    Выводы реф. баланса
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

            <div className="bg-gray-800 rounded-xl border border-gray-700 overflow-hidden">
                <table className="w-full text-left border-collapse">
                    <thead>
                        <tr className="bg-gray-700/50 text-gray-400 text-sm uppercase">
                            <th className="px-6 py-4 font-semibold">Пользователь</th>
                            <th className="px-6 py-4 font-semibold">Сумма</th>
                            <th className="px-6 py-4 font-semibold">Кошелек</th>
                            <th className="px-6 py-4 font-semibold">Дата</th>
                            <th className="px-6 py-4 font-semibold">Действие</th>
                        </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-700">
                        {loading ? (
                            <tr>
                                <td colSpan={5} className="px-6 py-12 text-center text-gray-500">
                                    Загрузка...
                                </td>
                            </tr>
                        ) : withdrawals.length === 0 ? (
                            <tr>
                                <td colSpan={5} className="px-6 py-12 text-center text-gray-500">
                                    Нет заявок
                                </td>
                            </tr>
                        ) : (
                            withdrawals.map((w) => (
                                <tr key={w.id} className="hover:bg-gray-750 transition-colors">
                                    <td className="px-6 py-4">
                                        <div className="flex flex-col">
                                            <span className="text-white font-medium">{w.user_first_name}</span>
                                            <span className="text-xs text-gray-400">ID: {w.user_telegram_id}</span>
                                        </div>
                                    </td>
                                    <td className="px-6 py-4">
                                        <span className="text-green-400 font-bold">${w.amount.toFixed(2)}</span>
                                    </td>
                                    <td className="px-6 py-4">
                                        <div className="flex items-center gap-2 group">
                                            <code className="bg-gray-900 border border-gray-700 px-2 py-1 rounded text-blue-400 text-xs truncate max-w-[200px]">
                                                {w.wallet}
                                            </code>
                                            <button
                                                onClick={() => navigator.clipboard.writeText(w.wallet)}
                                                className="text-gray-500 hover:text-white opacity-0 group-hover:opacity-100 transition-opacity"
                                                title="Копировать"
                                            >
                                                <ExternalLink size={14} />
                                            </button>
                                        </div>
                                    </td>
                                    <td className="px-6 py-4 text-gray-400 text-sm">
                                        <div className="flex items-center gap-2">
                                            <Clock size={14} />
                                            {new Date(w.created_at).toLocaleString('ru-RU')}
                                        </div>
                                    </td>
                                    <td className="px-6 py-4 text-right">
                                        {w.status === 'pending' ? (
                                            <button
                                                onClick={() => handleComplete(w.id)}
                                                className="bg-green-600 hover:bg-green-700 text-white px-4 py-2 rounded-lg text-sm font-medium flex items-center gap-2 transition-colors ml-auto"
                                            >
                                                <CheckCircle size={16} />
                                                Выполнено
                                            </button>
                                        ) : (
                                            <div className="text-gray-500 flex items-center gap-2 justify-end">
                                                <CheckCircle size={16} />
                                                {new Date(w.completed_at!).toLocaleDateString('ru-RU')}
                                            </div>
                                        )}
                                    </td>
                                </tr>
                            ))
                        )}
                    </tbody>
                </table>
            </div>

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
