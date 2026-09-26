import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
    Users, ShoppingCart, DollarSign, Package,
    ShieldAlert, Handshake, Wallet, Radio, Zap, ArrowRight,
} from 'lucide-react';
import { statsApi } from '../api/admin';
import { BarChart, type ChartPoint } from '../components/ui/BarChart';

type Period = 'all' | '30d' | '7d' | '24h';

const PERIODS: { value: Period; label: string }[] = [
    { value: 'all', label: 'Всё время' },
    { value: '30d', label: '30 дней' },
    { value: '7d', label: '7 дней' },
    { value: '24h', label: '24 часа' },
];

/**
 * Что требует вмешательства администратора.
 *
 * За каждой цифрой стоит человек, который чего-то ждёт: продавец — решения по
 * заявке, стороны спора — разбора, пользователь — вывода денег. Поэтому блок
 * стоит выше сводки и ведёт прямо в нужный раздел.
 */
const ATTENTION = [
    { key: 'listings_pending', label: 'Заявки на модерации', icon: ShieldAlert, to: '/moderation' },
    { key: 'disputes_open', label: 'Открытые споры', icon: Handshake, to: '/deals' },
    { key: 'withdrawals_pending', label: 'Заявки на вывод', icon: Wallet, to: '/withdrawals' },
    { key: 'channels_pending', label: 'Каналы на модерации', icon: Radio, to: '/subscriptions' },
    { key: 'service_orders_pending', label: 'Услуги в обработке', icon: Zap, to: '/processing' },
];

export const Dashboard: React.FC = () => {
    const [stats, setStats] = useState<any>(null);
    const [attention, setAttention] = useState<Record<string, number>>({});
    const [series, setSeries] = useState<ChartPoint[]>([]);
    const [top, setTop] = useState<any[]>([]);
    const [conversion, setConversion] = useState<any>(null);
    const [loading, setLoading] = useState(true);
    const [period, setPeriod] = useState<Period>('all');
    const [chartDays, setChartDays] = useState(30);

    useEffect(() => {
        statsApi.summary(period).then(setStats).catch(() => setStats(null)).finally(
            () => setLoading(false),
        );
    }, [period]);

    useEffect(() => {
        statsApi.attention().then(setAttention).catch(() => setAttention({}));
    }, []);

    useEffect(() => {
        statsApi.timeseries(chartDays)
            .then((d) => setSeries(d.series.map((p: any) => ({
                label: p.date,
                value: p.revenue_usdt,
                secondary: p.orders,
            }))))
            .catch(() => setSeries([]));

        statsApi.topProducts(chartDays).then((d) => setTop(d.items)).catch(() => setTop([]));
        statsApi.conversion(chartDays).then(setConversion).catch(() => setConversion(null));
    }, [chartDays]);

    const cards = [
        { label: 'Пользователи', value: stats?.total_users ?? 0, icon: Users },
        { label: 'Заказы', value: stats?.total_orders ?? 0, icon: ShoppingCart },
        {
            label: 'Выручка',
            value: `$${Number(stats?.total_revenue_usdt ?? 0).toFixed(2)}`,
            icon: DollarSign,
        },
        { label: 'Товары', value: stats?.total_products ?? 0, icon: Package },
    ];

    const pending = ATTENTION.filter((a) => (attention[a.key] ?? 0) > 0);

    return (
        <div>
            <div className="flex flex-col md:flex-row md:items-center justify-between mb-6 gap-4">
                <h1 className="text-2xl md:text-3xl font-bold text-white">Дашборд</h1>

                <div className="flex bg-gray-800 p-1 rounded-lg border border-gray-700">
                    {PERIODS.map((p) => (
                        <button
                            key={p.value}
                            onClick={() => setPeriod(p.value)}
                            className={`px-3 py-1.5 text-sm font-medium rounded-md transition-all ${
                                period === p.value
                                    ? 'bg-blue-600 text-white'
                                    : 'text-gray-400 hover:text-white hover:bg-gray-700'
                            }`}
                        >
                            {p.label}
                        </button>
                    ))}
                </div>
            </div>

            {pending.length > 0 && (
                <div className="mb-6">
                    <h2 className="text-sm font-semibold text-gray-400 mb-3">Требует действия</h2>
                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                        {pending.map((item) => (
                            <Link
                                key={item.key}
                                to={item.to}
                                className="flex items-center gap-3 bg-amber-500/10 border border-amber-500/30 rounded-xl px-4 py-3 hover:bg-amber-500/15 transition-colors group"
                            >
                                <item.icon size={20} className="text-amber-400 shrink-0" />
                                <div className="flex-1 min-w-0">
                                    <div className="text-white font-semibold">
                                        {attention[item.key]}
                                    </div>
                                    <div className="text-xs text-amber-200/70 truncate">
                                        {item.label}
                                    </div>
                                </div>
                                <ArrowRight
                                    size={16}
                                    className="text-amber-400/50 group-hover:text-amber-400 shrink-0"
                                />
                            </Link>
                        ))}
                    </div>
                </div>
            )}

            {loading ? (
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
                    {[1, 2, 3, 4].map((i) => (
                        <div key={i} className="h-28 bg-gray-800 rounded-xl animate-pulse" />
                    ))}
                </div>
            ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
                    {cards.map((card) => (
                        <div
                            key={card.label}
                            className="bg-gray-800 rounded-xl p-5 border border-gray-700"
                        >
                            <card.icon className="w-5 h-5 text-gray-400 mb-3" />
                            <h3 className="text-gray-400 text-sm">{card.label}</h3>
                            <p className="text-2xl font-bold text-white mt-1">{card.value}</p>
                        </div>
                    ))}
                </div>
            )}

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mt-6">
                <div className="lg:col-span-2 bg-gray-800 rounded-xl p-5 border border-gray-700">
                    <div className="flex items-center justify-between mb-5 gap-3 flex-wrap">
                        <h2 className="text-white font-semibold">Выручка по дням</h2>
                        <div className="flex gap-1">
                            {[7, 30, 90].map((d) => (
                                <button
                                    key={d}
                                    onClick={() => setChartDays(d)}
                                    className={`px-2.5 py-1 text-xs rounded-md ${
                                        chartDays === d
                                            ? 'bg-blue-600 text-white'
                                            : 'bg-gray-900 text-gray-400 hover:text-white'
                                    }`}
                                >
                                    {d}д
                                </button>
                            ))}
                        </div>
                    </div>

                    <BarChart
                        points={series}
                        formatValue={(v) => `$${v.toFixed(2)}`}
                        formatSecondary={(v) => `${v} заказ(ов)`}
                    />
                </div>

                <div className="bg-gray-800 rounded-xl p-5 border border-gray-700">
                    <h2 className="text-white font-semibold mb-4">Конверсия</h2>

                    {conversion ? (
                        <>
                            <div className="text-3xl font-bold text-white">
                                {conversion.conversion_percent}%
                            </div>
                            <p className="text-xs text-gray-500 mt-1 mb-4">
                                {conversion.paid} из {conversion.total} заказов дошли до оплаты
                                за {chartDays} дн.
                            </p>

                            <div className="space-y-1.5">
                                {Object.entries(conversion.by_status).map(([status, count]) => (
                                    <div key={status} className="flex justify-between text-sm">
                                        <span className="text-gray-400">{status}</span>
                                        <span className="text-gray-200">{count as number}</span>
                                    </div>
                                ))}
                            </div>
                        </>
                    ) : (
                        <div className="text-gray-500 text-sm">Нет данных</div>
                    )}
                </div>
            </div>

            <div className="bg-gray-800 rounded-xl p-5 border border-gray-700 mt-4">
                <h2 className="text-white font-semibold mb-4">
                    Топ товаров за {chartDays} дн.
                </h2>

                {top.length === 0 ? (
                    <div className="text-gray-500 text-sm">Продаж пока нет</div>
                ) : (
                    <div className="space-y-2">
                        {top.map((item, index) => (
                            <div
                                key={index}
                                className="flex items-center gap-3 text-sm py-1.5 border-b border-gray-700/50 last:border-0"
                            >
                                <span className="text-gray-600 w-5 shrink-0">{index + 1}</span>
                                <span className="flex-1 text-gray-200 truncate">{item.name}</span>
                                <span className="text-gray-500 shrink-0">{item.sold} шт.</span>
                                <span className="text-white font-medium w-20 text-right shrink-0">
                                    ${item.revenue_usdt.toFixed(2)}
                                </span>
                            </div>
                        ))}
                    </div>
                )}
            </div>
        </div>
    );
};
