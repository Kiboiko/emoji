import React, { useState, useEffect, useCallback } from 'react';
import axiosInstance from '../api/axios';
import { Loader2 } from 'lucide-react';

interface Order {
    id: string;
    user_id: string;
    user_telegram_id: number;
    user_name: string;
    total_usdt: number;
    total_ton: number | null;
    currency: string;
    status: string;
    created_at: string;
    paid_at: string | null;
    items: Array<{
        product_name: string;
        quantity: number;
        price_usdt: number;
    }>;
}

export const Orders: React.FC = () => {
    const [orders, setOrders] = useState<Order[]>([]);
    const [loading, setLoading] = useState(true);
    const [filter, setFilter] = useState<'all' | 'paid' | 'pending' | 'cancelled'>('paid');  // Default to paid

    const [currentPage, setCurrentPage] = useState(1);
    const ITEMS_PER_PAGE = 10;

    const fetchOrders = useCallback(async () => {
        try {
            setLoading(true);
            const response = await axiosInstance.get('/api/admin/orders', {
                params: { status: filter }
            });
            setOrders(response.data);
            setCurrentPage(1); // Reset to first page on new fetch
        } catch (error) {
            console.error('Failed to fetch orders:', error);
        } finally {
            setLoading(false);
        }
    }, [filter]);

    useEffect(() => {
        fetchOrders();
    }, [fetchOrders]);

    const getStatusColor = (status: string) => {
        switch (status.toLowerCase()) {
            case 'paid':
            case 'completed':
                return 'bg-green-500/10 text-green-400';
            case 'pending':
                return 'bg-yellow-500/10 text-yellow-400';
            case 'cancelled':
                return 'bg-red-500/10 text-red-400';
            default:
                return 'bg-gray-500/10 text-gray-400';
        }
    };

    // Pagination Logic
    const totalPages = Math.ceil(orders.length / ITEMS_PER_PAGE);
    const paginatedOrders = orders.slice(
        (currentPage - 1) * ITEMS_PER_PAGE,
        currentPage * ITEMS_PER_PAGE
    );

    if (loading) return (
        <div className="flex justify-center items-center h-64">
            <Loader2 className="animate-spin text-blue-500" size={48} />
        </div>
    );

    return (
        <div>
            {/* Header */}
            <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 mb-6">
                <h1 className="text-3xl font-bold">Заказы</h1>

                <div className="flex gap-4 border-b border-gray-800">
                    <button
                        onClick={() => setFilter('paid')}
                        className={`pb-3 px-2 text-sm font-medium transition-colors relative ${filter === 'paid'
                            ? 'text-green-400 border-b-2 border-green-500'
                            : 'text-gray-400 hover:text-white'
                            }`}
                    >
                        Оплаченные
                    </button>
                    <button
                        onClick={() => setFilter('pending')}
                        className={`pb-3 px-2 text-sm font-medium transition-colors relative ${filter === 'pending'
                            ? 'text-yellow-400 border-b-2 border-yellow-500'
                            : 'text-gray-400 hover:text-white'
                            }`}
                    >
                        Ожидание
                    </button>
                    <button
                        onClick={() => setFilter('cancelled')}
                        className={`pb-3 px-2 text-sm font-medium transition-colors relative ${filter === 'cancelled'
                            ? 'text-red-400 border-b-2 border-red-500'
                            : 'text-gray-400 hover:text-white'
                            }`}
                    >
                        Отмененные
                    </button>
                    <button
                        onClick={() => setFilter('all')}
                        className={`pb-3 px-2 text-sm font-medium transition-colors relative ${filter === 'all'
                            ? 'text-blue-400 border-b-2 border-blue-500'
                            : 'text-gray-400 hover:text-white'
                            }`}
                    >
                        Все
                    </button>
                </div>
            </div>

            {/* Table */}
            <div className="bg-gray-800 rounded-lg border border-gray-700 overflow-x-auto">
                <table className="w-full text-left min-w-[800px]">
                    <thead className="bg-gray-700/50 text-gray-400">
                        <tr>
                            <th className="p-4">ID</th>
                            <th className="p-4">Пользователь</th>
                            <th className="p-4">Товары</th>
                            <th className="p-4">Сумма</th>
                            <th className="p-4">Статус</th>
                            <th className="p-4">Дата</th>
                        </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-700">
                        {paginatedOrders.length === 0 ? (
                            <tr>
                                <td colSpan={6} className="p-8 text-center text-gray-500">
                                    Заказов нет
                                </td>
                            </tr>
                        ) : (
                            paginatedOrders.map((order) => (
                                <tr key={order.id} className="hover:bg-gray-700/50 transition-colors">
                                    <td className="p-4 text-sm font-mono text-gray-400">
                                        #{order.id.substring(0, 8)}...
                                    </td>
                                    <td className="p-4">
                                        <div className="font-medium text-white">{order.user_name}</div>
                                        <div className="text-xs text-gray-500">TG ID: {order.user_telegram_id}</div>
                                    </td>
                                    <td className="p-4">
                                        {order.items.map((item, idx) => (
                                            <div key={idx} className="text-sm text-gray-300">
                                                • {item.product_name} x{item.quantity}
                                            </div>
                                        ))}
                                    </td>
                                    <td className="p-4">
                                        <span className="text-green-400 font-medium">
                                            {order.currency === 'TON' && order.total_ton ? (
                                                `${order.total_ton} TON`
                                            ) : (
                                                `$${order.total_usdt}`
                                            )}
                                        </span>
                                    </td>
                                    <td className="p-4">
                                        <span className={`px-2 py-1 rounded text-xs ${getStatusColor(order.status)}`}>
                                            {order.status.toUpperCase()}
                                        </span>
                                    </td>
                                    <td className="p-4 text-sm text-gray-400">
                                        {new Date(order.created_at).toLocaleString('ru-RU')}
                                    </td>
                                </tr>
                            ))
                        )}
                    </tbody>
                </table>
            </div>

            {/* Pagination Controls */}
            {totalPages > 1 && (
                <div className="flex justify-center gap-2 mt-8">
                    <button
                        onClick={() => setCurrentPage(p => Math.max(1, p - 1))}
                        disabled={currentPage === 1}
                        className="px-4 py-2 bg-gray-800 text-white rounded-lg disabled:opacity-50 hover:bg-gray-700"
                    >
                        Назад
                    </button>
                    <span className="px-4 py-2 text-gray-400">
                        Страница {currentPage} из {totalPages}
                    </span>
                    <button
                        onClick={() => setCurrentPage(p => Math.min(totalPages, p + 1))}
                        disabled={currentPage === totalPages}
                        className="px-4 py-2 bg-gray-800 text-white rounded-lg disabled:opacity-50 hover:bg-gray-700"
                    >
                        Вперед
                    </button>
                </div>
            )}
        </div>
    );
};
