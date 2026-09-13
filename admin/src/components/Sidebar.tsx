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
    MessageSquare
} from 'lucide-react';

interface SidebarProps {
    isOpen?: boolean;
    onClose?: () => void;
}

export const Sidebar: React.FC<SidebarProps> = ({ isOpen = true, onClose }) => {
    const { logout } = useAuth();
    const navigate = useNavigate();

    const handleLogout = async () => {
        await logout();
        navigate('/login');
    };

    const navItems = [
        { path: '/', icon: LayoutDashboard, label: 'Дашборд' },
        { path: '/processing', icon: Zap, label: 'Обработка' },
        { path: '/products', icon: Package, label: 'Товары' },
        { path: '/categories', icon: ListTree, label: 'Категории' },
        { path: '/orders', icon: ShoppingCart, label: 'Заказы' },
        { path: '/users', icon: Users, label: 'Пользователи' },
        { path: '/reviews', icon: MessageSquare, label: 'Отзывы' },
        { path: '/withdrawals', icon: Wallet, label: 'Выводы' },
    ];

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
                <div className="p-6 flex justify-between items-center">
                    {/* Removed "Admin Panel" text as requested */}
                    <div className="w-8"></div> {/* Spacer for alignment if needed, or remove */}

                    {/* Close button for mobile */}
                    <button
                        onClick={onClose}
                        className="md:hidden text-gray-400 hover:text-white"
                    >
                        <X size={24} />
                    </button>
                </div>

                <nav className="flex-1 px-4 space-y-2 mt-4">
                    {navItems.map((item) => (
                        <NavLink
                            key={item.path}
                            to={item.path}
                            onClick={() => onClose && onClose()} // Close on click for mobile
                            className={({ isActive }) =>
                                `flex items-center gap-3 px-4 py-3 rounded-lg transition-colors ${isActive
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
