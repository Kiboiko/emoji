import React, { useState } from 'react';
import { Outlet, Navigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { useWebSocket } from '../hooks/useWebSocket';
import { useQueryClient } from '@tanstack/react-query';
import { Sidebar } from '../components/Sidebar';
import { Menu } from 'lucide-react';

export const AdminLayout: React.FC = () => {
    const { user, isLoading, accessToken } = useAuth();
    const [sidebarOpen, setSidebarOpen] = useState(false);
    const queryClient = useQueryClient();

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
                {/* Mobile Header */}
                <header className="md:hidden bg-gray-800 border-b border-gray-700 p-4 flex items-center">
                    <button
                        onClick={() => setSidebarOpen(true)}
                        className="text-gray-400 hover:text-white"
                    >
                        <Menu size={24} />
                    </button>

                </header>

                <main className="flex-1 p-4 md:p-8 overflow-y-auto max-h-screen">
                    <Outlet />
                </main>
            </div>
        </div>
    );
};
