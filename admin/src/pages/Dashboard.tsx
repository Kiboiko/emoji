import React, { useEffect, useState } from 'react';
import api from '../api/axios';
import {
    Users,
    ShoppingCart,
    DollarSign,
    Package
} from 'lucide-react';

interface Stats {
    total_users: number;
    total_orders: number;
    total_revenue_usdt: number;
    total_products: number;
}

type Period = 'all' | '30d' | '7d' | '24h';

export const Dashboard: React.FC = () => {
    const [stats, setStats] = useState<Stats | null>(null);
    const [loading, setLoading] = useState(true);
    const [period, setPeriod] = useState<Period>('all');

    useEffect(() => {
        const fetchStats = async () => {
            try {
                setLoading(true);
                const { data } = await api.get('/api/admin/stats', {
                    params: { period }
                });
                setStats(data);
            } catch (error) {
                console.error("Failed to fetch stats", error);
            } finally {
                setLoading(false);
            }
        };

        fetchStats();
    }, [period]);

    const statCards = [
        {
            label: 'Пользователи',
            value: stats?.total_users ?? 0,
            icon: Users
        },
        {
            label: 'Заказы',
            value: stats?.total_orders ?? 0,
            icon: ShoppingCart
        },
        {
            label: 'Выручка',
            value: `$${stats?.total_revenue_usdt ?? 0}`,
            icon: DollarSign
        },
        {
            label: 'Товары',
            value: stats?.total_products ?? 0,
            icon: Package
        },
    ];

    const periods: { value: Period; label: string }[] = [
        { value: 'all', label: 'Все время' },
        { value: '30d', label: '30 дней' },
        { value: '7d', label: '7 дней' },
        { value: '24h', label: '24 часа' },
    ];

    return (
        <div>
            <div className="flex flex-col md:flex-row md:items-center justify-between mb-8 gap-4">
                <h1 className="text-3xl font-bold">Дашборд</h1>

                <div className="flex bg-gray-800 p-1 rounded-lg border border-gray-700">
                    {periods.map((p) => (
                        <button
                            key={p.value}
                            onClick={() => setPeriod(p.value)}
                            className={`px-4 py-2 text-sm font-medium rounded-md transition-all ${period === p.value
                                ? 'bg-blue-600 text-white shadow-lg'
                                : 'text-gray-400 hover:text-white hover:bg-gray-700'
                                }`}
                        >
                            {p.label}
                        </button>
                    ))}
                </div>
            </div>

            {loading ? (
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
                    {[1, 2, 3, 4].map(i => (
                        <div key={i} className="h-32 bg-gray-800 rounded-xl animate-pulse"></div>
                    ))}
                </div>
            ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
                    {statCards.map((card, index) => (
                        <div key={index} className="bg-gray-800 rounded-xl p-6 border border-gray-700 hover:border-gray-600 transition-colors">
                            <div className="flex items-center justify-between mb-4">
                                <card.icon className="w-6 h-6 text-gray-400" />
                                {period !== 'all' && (index === 1 || index === 2) && (
                                    <span className="text-xs text-gray-500 bg-gray-900 px-2 py-1 rounded">
                                        {periods.find(p => p.value === period)?.label}
                                    </span>
                                )}
                            </div>
                            <h3 className="text-gray-400 text-sm font-medium">{card.label}</h3>
                            <p className="text-2xl font-bold text-white mt-1">{card.value}</p>
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
};
