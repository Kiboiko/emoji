import React, { useState, useEffect } from 'react';
import {
    Clock,
    CheckCircle,
    ExternalLink,
    User,
    Copy,
    AlertCircle,
    Loader2
} from 'lucide-react';
import { adminApi } from '../api/axios';

// Types derived from API response
interface ServiceItem {
    id: string;
    product_name: string;
    quantity: number;
    user_data: {
        link: string;
        [key: string]: any;
    };
    price_usdt: number;
}

interface ServiceOrder {
    id: string;
    user_id: string;
    user_telegram_id: number;
    user_username: string | null;
    user_first_name: string | null;
    total_usdt: number;
    status: string;
    created_at: string;
    items: ServiceItem[];
}

const ProcessingPage: React.FC = () => {
    const [activeTab, setActiveTab] = useState<'new' | 'completed'>('new');
    const [orders, setOrders] = useState<ServiceOrder[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [completingId, setCompletingId] = useState<string | null>(null);

    const [currentPage, setCurrentPage] = useState(1);
    const ITEMS_PER_PAGE = 10;

    useEffect(() => {
        loadOrders();
        setCurrentPage(1); // Reset page on tab change
    }, [activeTab]);

    const loadOrders = async () => {
        try {
            setLoading(true);
            const response = await adminApi.getServiceOrders(activeTab === 'new' ? 'paid' : 'completed');
            setOrders(response.data);
            setError(null);
        } catch (err) {
            console.error('Failed to load orders:', err);
            setError('Не удалось загрузить заказы');
        } finally {
            setLoading(false);
        }
    };

    const handleComplete = async (orderId: string) => {
        if (!confirm('Вы уверены, что хотите отметить услугу как выполненную? Пользователь получит уведомление.')) return;

        try {
            setCompletingId(orderId);
            await adminApi.completeServiceOrder(orderId);
            // Refresh list
            loadOrders();
        } catch (err) {
            console.error('Failed to complete order:', err);
            alert('Не удалось завершить заказ');
        } finally {
            setCompletingId(null);
        }
    };

    const copyToClipboard = (text: string) => {
        navigator.clipboard.writeText(text);
        // Could show toast here
    };

    const formatDate = (dateString: string) => {
        return new Date(dateString).toLocaleString('ru-RU', {
            day: '2-digit',
            month: '2-digit',
            year: 'numeric',
            hour: '2-digit',
            minute: '2-digit'
        });
    };

    // Pagination Logic
    const totalPages = Math.ceil(orders.length / ITEMS_PER_PAGE);
    const paginatedOrders = orders.slice(
        (currentPage - 1) * ITEMS_PER_PAGE,
        currentPage * ITEMS_PER_PAGE
    );

    return (
        <div className="p-6 max-w-7xl mx-auto">
            <div className="flex items-center justify-between mb-8">
                <div>
                    <h1 className="text-2xl font-bold text-white mb-2">Обработка услуг</h1>
                    <p className="text-gray-400">Управление заказами на буст и услуги</p>
                </div>
                <button
                    onClick={loadOrders}
                    className="p-2 hover:bg-gray-800 rounded-lg transition-colors text-gray-400 hover:text-white"
                    title="Обновить"
                >
                    <Clock size={20} />
                </button>
            </div>

            {/* Tabs */}
            <div className="flex gap-4 mb-8 border-b border-gray-800">
                <button
                    onClick={() => setActiveTab('new')}
                    className={`pb-4 px-2 text-sm font-medium transition-colors relative ${activeTab === 'new'
                        ? 'text-purple-400 border-b-2 border-purple-500'
                        : 'text-gray-400 hover:text-white'
                        }`}
                >
                    Новые
                </button>
                <button
                    onClick={() => setActiveTab('completed')}
                    className={`pb-4 px-2 text-sm font-medium transition-colors relative ${activeTab === 'completed'
                        ? 'text-green-400 border-b-2 border-green-500'
                        : 'text-gray-400 hover:text-white'
                        }`}
                >
                    Выполненные
                </button>
            </div>

            {/* Content */}
            {loading ? (
                <div className="flex justify-center items-center h-64">
                    <Loader2 className="animate-spin text-purple-500" size={32} />
                </div>
            ) : error ? (
                <div className="bg-red-500/10 border border-red-500/20 rounded-xl p-4 text-red-400 flex items-center gap-3">
                    <AlertCircle size={20} />
                    {error}
                </div>
            ) : orders.length === 0 ? (
                <div className="text-center py-20 text-gray-500">
                    Заказов не найдено
                </div>
            ) : (
                <>
                    <div className="grid gap-4">
                        {paginatedOrders.map((order) => (
                            <div
                                key={order.id}
                                className="bg-gray-900 border border-gray-800 rounded-xl p-6"
                            >
                                <div className="flex flex-col lg:flex-row gap-6 justify-between">
                                    {/* Order Info */}
                                    <div className="flex-shrink-0 min-w-[200px]">
                                        <div className="flex items-center gap-2 text-gray-400 text-sm mb-2">
                                            <span>#{order.id.slice(0, 8)}</span>
                                            <span>•</span>
                                            <span>{formatDate(order.created_at)}</span>
                                        </div>
                                        <div className="flex items-center gap-2 mb-2">
                                            <User size={16} className="text-gray-400" />
                                            <span className="text-white font-medium">
                                                {order.user_first_name || 'Неизвестно'}
                                            </span>
                                            {order.user_username && (
                                                <span className="text-gray-500 text-sm">@{order.user_username}</span>
                                            )}
                                        </div>
                                        <div className="text-lg font-bold text-white">
                                            ${order.total_usdt.toFixed(2)}
                                        </div>
                                    </div>

                                    {/* Service Items */}
                                    <div className="flex-grow space-y-4">
                                        {order.items.map((item) => (
                                            <div key={item.id} className="bg-gray-800/50 rounded-lg p-4 border border-gray-800">
                                                <div className="font-medium text-white mb-2">{item.product_name}</div>
                                                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                                    <div className="space-y-1">
                                                        <div className="text-xs text-gray-500 uppercase tracking-wider">Ссылка</div>
                                                        <div className="flex items-center gap-2 group">
                                                            <div className="bg-gray-900 px-3 py-1.5 rounded text-sm text-blue-400 font-mono truncate max-w-[250px]">
                                                                {item.user_data?.link || 'Нет ссылки'}
                                                            </div>
                                                            {item.user_data?.link && (
                                                                <>
                                                                    <button
                                                                        onClick={() => copyToClipboard(item.user_data.link)}
                                                                        className="p-1.5 hover:bg-gray-700 rounded text-gray-400 hover:text-white transition-colors"
                                                                        title="Копировать"
                                                                    >
                                                                        <Copy size={14} />
                                                                    </button>
                                                                    <a
                                                                        href={item.user_data.link}
                                                                        target="_blank"
                                                                        rel="noopener noreferrer"
                                                                        className="p-1.5 hover:bg-gray-700 rounded text-gray-400 hover:text-white transition-colors"
                                                                        title="Открыть"
                                                                    >
                                                                        <ExternalLink size={14} />
                                                                    </a>
                                                                </>
                                                            )}
                                                        </div>
                                                    </div>
                                                    <div className="space-y-1">
                                                        <div className="text-xs text-gray-500 uppercase tracking-wider">Количество</div>
                                                        <div className="text-white font-mono text-lg font-bold">
                                                            {item.quantity.toLocaleString()}
                                                        </div>
                                                    </div>
                                                </div>
                                            </div>
                                        ))}
                                    </div>

                                    {/* Actions */}
                                    {activeTab === 'new' && (
                                        <div className="flex items-center">
                                            <button
                                                onClick={() => handleComplete(order.id)}
                                                disabled={completingId === order.id}
                                                className="w-full lg:w-auto px-6 py-3 bg-purple-600 hover:bg-purple-500 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-xl font-medium transition-all shadow-lg shadow-purple-900/20 hover:shadow-purple-900/40 flex items-center justify-center gap-2"
                                            >
                                                {completingId === order.id ? (
                                                    <Loader2 className="animate-spin" size={20} />
                                                ) : (
                                                    <CheckCircle size={20} />
                                                )}
                                                Выполнить
                                            </button>
                                        </div>
                                    )}
                                </div>
                            </div>
                        ))}
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
                </>
            )}
        </div>
    );
};
export default ProcessingPage;
