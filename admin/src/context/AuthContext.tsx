import React, { createContext, useContext, useEffect, useState } from 'react';
import api, { setOnSessionLost, setOnTokenRefreshed } from '../api/axios';

export type Role = 'admin' | 'moderator';

interface User {
    id: string;
    username: string;
    is_admin: boolean;
    role: Role;
}

interface AuthContextType {
    user: User | null;
    /** Роль нужна меню и охране маршрутов; настоящие права проверяет бэкенд */
    role: Role | null;
    accessToken: string | null;
    isLoading: boolean;
    login: (token: string) => void;
    logout: () => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
    const [user, setUser] = useState<User | null>(null);
    const [accessToken, setAccessToken] = useState<string | null>(null);
    const [isLoading, setIsLoading] = useState(true);

    const updateToken = (token: string) => {
        setAccessToken(token);
        api.defaults.headers.common['Authorization'] = `Bearer ${token}`;
        try {
            const payload = JSON.parse(atob(token.split('.')[1]));
            // Токены, выданные до появления ролей, роли не несут — это админы
            const role: Role = payload.role === 'moderator' ? 'moderator' : 'admin';
            setUser({
                id: payload.user_id,
                username: payload.sub,
                is_admin: Boolean(payload.is_admin),
                role,
            });
        } catch (e) {
            console.error("Failed to decode token", e);
        }
    };

    const login = (token: string) => {
        updateToken(token);
    };

    const logout = async () => {
        try {
            await api.post('/api/admin/auth/logout');
        } catch (e) {
            console.error("Logout failed", e);
        }
        setAccessToken(null);
        setUser(null);
        delete api.defaults.headers.common['Authorization'];
    };

    useEffect(() => {
        // Setup axios callback
        setOnTokenRefreshed((token) => {
            updateToken(token);
        });
        setOnSessionLost(() => {
            setAccessToken(null);
            setUser(null);
            delete api.defaults.headers.common['Authorization'];
        });

        // Try to refresh token on mount to check if we are logged in
        const checkAuth = async () => {
            try {
                const { data } = await api.post('/api/admin/auth/refresh');
                updateToken(data.access_token);
            } catch (e) {
                // Not logged in
            } finally {
                setIsLoading(false);
            }
        };

        checkAuth();
    }, []);

    return (
        <AuthContext.Provider value={{ user, role: user?.role ?? null, accessToken, isLoading, login, logout }}>
            {children}
        </AuthContext.Provider>
    );
};

export const useAuth = () => {
    const context = useContext(AuthContext);
    if (!context) {
        throw new Error('useAuth must be used within an AuthProvider');
    }
    return context;
};
