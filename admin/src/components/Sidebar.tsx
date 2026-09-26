import React from 'react';
import { NavLink, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import {
    LayoutDashboard,
    Package,
    ListTree,
    ShoppingCart,
    Users,
    LogOut,
    X,
    Zap,
    Wallet,
    MessageSquare,
    ShieldCheck,
    Handshake,
    Radio,
    Scale,
    Share2,
    Settings as SettingsIcon
} from 'lucide-react';

interface SidebarProps {
    isOpen?: boolean;
    onClose?: () => void;
}

/**
 * Разделы админки. Вынесены из компонента: шапка на телефоне показывает по
 * этому же списку, в каком разделе человек находится, — иначе список
 * пришлось бы держать в двух местах.
 */
export const NAV_ITEMS = [
    { path: '/', icon: LayoutDashboard, label: 'Дашборд' },
    { path: '/processing', icon: Zap, label: 'Обработка' },
    { path: '/products', icon: Package, label: 'Товары' },
    { path: '/categories', icon: ListTree, label: 'Категории' },
    { path: '/orders', icon: ShoppingCart, label: 'Заказы' },
    { path: '/users', icon: Users, label: 'Пользователи' },
    { path: '/moderation', icon: ShieldCheck, label: 'Модерация' },
    { path: '/deals', icon: Handshake, label: 'Сделки' },
    { path: '/subscriptions', icon: Radio, label: 'Каналы' },
    { path: '/referrals', icon: Share2, label: 'Рефералы' },
    { path: '/finance', icon: Scale, label: 'Финансы' },
    { path: '/reviews', icon: MessageSquare, label: 'Отзывы' },
    { path: '/withdrawals', icon: Wallet, label: 'Выводы' },
    { path: '/settings', icon: SettingsIcon, label: 'Настройки' },
];

export const Sidebar: React.FC<SidebarProps> = ({ isOpen = true, onClose }) => {
    const { logout } = useAuth();
    const navigate = useNavigate();

    const handleLogout = async () => {
        await logout();
        navigate('/login');
    };

    const navItems = NAV_ITEMS;

    return (
        <>
            {/* Overlay for mobile */}
            {isOpen && (
                <div
                    className="fixed inset-0 bg-black/50 z-40 md:hidden"
                    onClick={onClose}
                />
            )}

            <aside className={`
                fixed inset-y-0 left-0 z-50 w-64 bg-gray-800 border-r border-gray-700 
                transform transition-transform duration-200 ease-in-out
                md:relative md:translate-x-0 flex flex-col
                ${isOpen ? 'translate-x-0' : '-translate-x-full'}
            `}>
                <div className="px-6 py-4 flex justify-between items-center">
                    <span className="font-semibold text-white">Админка</span>

                    <button
                        onClick={onClose}
                        className="md:hidden text-gray-400 hover:text-white"
                        aria-label="Закрыть меню"
                    >
                        <X size={24} />
                    </button>
                </div>

                {/* Разделов четырнадцать: на невысоком экране они не помещались
                    целиком, а список не прокручивался — «Настройки» были
                    недоступны вовсе */}
                <nav className="flex-1 overflow-y-auto px-4 space-y-1 pb-4">
                    {navItems.map((item) => (
                        <NavLink
                            key={item.path}
                            to={item.path}
                            onClick={() => onClose && onClose()} // Close on click for mobile
                            className={({ isActive }) =>
                                `flex items-center gap-3 px-4 py-2.5 rounded-lg transition-colors ${isActive
                                    ? 'bg-blue-600/10 text-blue-500'
                                    : 'text-gray-400 hover:bg-gray-700 hover:text-white'
                                }`
                            }
                        >
                            <item.icon size={20} />
                            <span className="font-medium">{item.label}</span>
                        </NavLink>
                    ))}
                </nav>

                <div className="p-4 border-t border-gray-700">
                    <button
                        onClick={handleLogout}
                        className="flex items-center gap-3 px-4 py-3 w-full text-red-500 hover:bg-red-500/10 rounded-lg transition-colors"
                    >
                        <LogOut size={20} />
                        <span className="font-medium">Выйти</span>
                    </button>
                </div>
            </aside>
        </>
    );
};
