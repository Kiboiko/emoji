import React, { useState } from 'react';
import { Outlet, Navigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { useWebSocket } from '../hooks/useWebSocket';
import { useQueryClient } from '@tanstack/react-query';
import { Sidebar } from '../components/Sidebar';
import { NAV_ITEMS } from '../components/Sidebar';
import { useLocation } from 'react-router-dom';
import { Menu } from 'lucide-react';

export const AdminLayout: React.FC = () => {
    const { user, isLoading, accessToken } = useAuth();
    const [sidebarOpen, setSidebarOpen] = useState(false);
    const queryClient = useQueryClient();
    const location = useLocation();

    // Название раздела рядом с гамбургером. Одна кнопка без подписи не
    // говорит, где ты находишься, а боковое меню на телефоне закрыто.
    const section = NAV_ITEMS.find((item) => (item.path === '/'
        ? location.pathname === '/'
        : location.pathname.startsWith(item.path)));

    useWebSocket((message: any) => {
        if (['category_created', 'category_updated', 'category_deleted'].includes(message.type)) {
            queryClient.invalidateQueries({ queryKey: ['categories'] });
        }
        if (['product_created', 'product_updated', 'product_deleted'].includes(message.type)) {
            queryClient.invalidateQueries({ queryKey: ['products'] });
        }
    }, accessToken);

    if (isLoading) {
        return <div className="min-h-screen bg-gray-900 flex items-center justify-center text-white">Loading...</div>;
    }

    if (!user) {
        return <Navigate to="/login" replace />;
    }

    return (
        <div className="min-h-screen bg-gray-900 flex text-white">
            <Sidebar
                isOpen={sidebarOpen}
                onClose={() => setSidebarOpen(false)}
            />

            <div className="flex-1 flex flex-col min-w-0">
                {/* Шапка на телефоне. Липкая: разделы длинные, и без этого
                    за меню приходилось пролистывать список обратно вверх. */}
                <header className="md:hidden sticky top-0 z-30 bg-gray-800 border-b border-gray-700 px-4 py-3 flex items-center gap-3">
                    <button
                        onClick={() => setSidebarOpen(true)}
                        className="text-gray-400 hover:text-white -ml-1 p-1"
                        aria-label="Открыть меню"
                    >
                        <Menu size={24} />
                    </button>
                    <span className="font-semibold truncate">
                        {section?.label ?? 'Админка'}
                    </span>
                </header>

                <main className="flex-1 p-4 md:p-8 min-w-0">
                    <Outlet />
                </main>
            </div>
        </div>
    );
};
