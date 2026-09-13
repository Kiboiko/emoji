import React, { useEffect, useState } from 'react';
import api from '../api/axios';
// import { Layout } from 'lucide-react'; // Placeholder icon if needed, or import User icon

interface User {
    id: string;
    telegram_id: number;
    username: string | null;
    first_name: string;
    is_admin: boolean;
    referral_code: string;
    referral_earnings: number;
    created_at: string;
}

export const Users: React.FC = () => {
    const [users, setUsers] = useState<User[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');

    const fetchUsers = async () => {
        try {
            setLoading(true);
            // Calling the endpoint we confirmed exists in backend/routes/users.py
            // Endpoint prefix: /api/users, path: /admin/all -> /api/users/admin/all
            const { data } = await api.get('/api/users/admin/all');
            setUsers(data);
        } catch (err: any) {
            console.error(err);
            setError('Failed to fetch users');
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchUsers();
    }, []);

    if (loading) return <div className="p-8 text-white">Loading...</div>;
    if (error) return <div className="p-8 text-red-500">{error}</div>;

    return (
        <div className="p-8">
            <h1 className="text-3xl font-bold text-white mb-8">Пользователи</h1>

            <div className="bg-gray-800 rounded-xl overflow-hidden shadow-lg border border-gray-700">
                <div className="overflow-x-auto">
                    <table className="w-full text-left">
                        <thead className="bg-gray-700/50">
                            <tr>
                                <th className="px-6 py-4 text-gray-400 font-medium">Telegram ID</th>
                                <th className="px-6 py-4 text-gray-400 font-medium">Имя / Username</th>
                                <th className="px-6 py-4 text-gray-400 font-medium">Регистрация</th>
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-gray-700">
                            {users.map((user) => (
                                <tr key={user.id} className="hover:bg-gray-700/30 transition-colors">
                                    <td className="px-6 py-4 text-white font-mono text-sm">{user.telegram_id}</td>
                                    <td className="px-6 py-4">
                                        <div className="text-white font-medium">{user.first_name}</div>
                                        {user.username && <div className="text-sm text-gray-400">@{user.username}</div>}
                                    </td>
                                    <td className="px-6 py-4 text-gray-300">
                                        {new Date(user.created_at).toLocaleDateString('ru-RU')}
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    );
};
