import React from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { Home, MessageCircle, ShoppingCart, User } from 'lucide-react';
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
    // Непрочитанное в переписке по сделкам — на вкладке «Чаты». Раньше
    // значок висел на «Профиле»: переписка была спрятана внутри него
    const unreadDeals = useDealsStore(selectUnreadTotal);
    const navigate = useNavigate();
    const { pathname } = useLocation();

    // Как считал NavLink: раздел активен на своём адресе и на вложенных.
    // Главная — только на самой себе, иначе она горела бы на всех экранах
    const isActive = (to: string) => pathname === to || (to !== '/' && pathname.startsWith(`${to}/`));

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
            to: '/chats',
            icon: MessageCircle,
            label: language === 'ru' ? 'Чаты' : 'Chats',
            badge: unreadDeals,
        },
        {
            to: '/profile',
            icon: User,
            label: language === 'ru' ? 'Профиль' : 'Profile',
        },
    ];

    return (
        // Кнопки, а не ссылки. У ссылки есть адрес, и при долгом нажатии
        // телефон показывал меню с этим адресом («открыть», «копировать
        // ссылку») — в приложении это выглядит как сломанная вёрстка.
        // У кнопки адреса нет, и показывать нечего.
        <nav className="bottom-nav" onContextMenu={(e) => e.preventDefault()}>
            {navItems.map((item) => {
                const active = isActive(item.to);
                return (
                    <button
                        key={item.to}
                        type="button"
                        className={`nav-item ${active ? 'nav-item-active' : ''}`}
                        aria-current={active ? 'page' : undefined}
                        // Повторное нажатие на открытый раздел не плодит
                        // записи в истории — так же вела себя ссылка
                        onClick={() => navigate(item.to, { replace: active })}
                    >
                        <div className="nav-icon">
                            <item.icon size={22} />
                            {item.badge !== undefined && item.badge > 0 && (
                                <span className="nav-badge">{item.badge > 99 ? '99+' : item.badge}</span>
                            )}
                        </div>
                        <span className="nav-label">{item.label}</span>
                    </button>
                );
            })}
        </nav>
    );
};
