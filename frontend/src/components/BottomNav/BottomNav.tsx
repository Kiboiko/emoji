import React from 'react';
import { NavLink } from 'react-router-dom';
import { Home, ShoppingCart, User } from 'lucide-react';
import { useCartStore } from '@/store/cartStore';
import { useAuthStore } from '@/store/authStore';
import { useDealsStore, selectUnreadTotal } from '@/store/dealsStore';
import './BottomNav.css';

export const BottomNav: React.FC = () => {
    // For digital products: sum quantity (Netflix x2 = 2)
    // For service products: count cards (YouTube 1000 subscribers = 1 card)
    const itemCount = useCartStore((state) => {
        if (!state.cart?.items) return 0;
        return state.cart.items.reduce((count, item) => {
            if (item.type === 'service') {
                return count + 1; // Service: count as 1 item regardless of quantity
            } else {
                return count + item.quantity; // Digital: sum quantity
            }
        }, 0);
    });
    const { language } = useAuthStore();
    // Непрочитанное в переписке по сделкам: сама переписка — в профиле
    const unreadDeals = useDealsStore(selectUnreadTotal);

    const navItems = [
        {
            to: '/',
            icon: Home,
            label: language === 'ru' ? 'Главная' : 'Home',
        },
        {
            to: '/cart',
            icon: ShoppingCart,
            label: language === 'ru' ? 'Корзина' : 'Cart',
            badge: itemCount,
        },
        {
            to: '/profile',
            icon: User,
            label: language === 'ru' ? 'Профиль' : 'Profile',
            badge: unreadDeals,
        },
    ];

    return (
        <nav className="bottom-nav">
            {navItems.map((item) => (
                <NavLink
                    key={item.to}
                    to={item.to}
                    className={({ isActive }) =>
                        `nav-item ${isActive ? 'nav-item-active' : ''}`
                    }
                >
                    <div className="nav-icon">
                        <item.icon size={22} />
                        {item.badge !== undefined && item.badge > 0 && (
                            <span className="nav-badge">{item.badge}</span>
                        )}
                    </div>
                    <span className="nav-label">{item.label}</span>
                </NavLink>
            ))}
        </nav>
    );
};
