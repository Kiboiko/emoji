import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { Trash2, Plus, Minus, ShoppingBag } from 'lucide-react';
import { cartApi } from '@/api/client';
import { useAuthStore } from '@/store/authStore';
import { useCartStore } from '@/store/cartStore';
import { errorText, useToastStore } from '@/store/toastStore';
import { useTelegram } from '@/hooks/useTelegram';
import './Cart.css';

export const Cart: React.FC = () => {
    const navigate = useNavigate();
    const { language } = useAuthStore();
    const { cart, setCart } = useCartStore();
    const showToast = useToastStore((s) => s.show);
    const { haptic } = useTelegram();
    const [isLoading, setIsLoading] = useState(true);

    useEffect(() => {
        loadCart();
    }, [language]);

    const loadCart = async () => {
        try {
            setIsLoading(true);
            const data = await cartApi.getCart(language);
            setCart(data);
        } catch (error) {
            console.error('Failed to load cart:', error);
        } finally {
            setIsLoading(false);
        }
    };

    const updateQuantity = async (itemId: string, newQuantity: number) => {
        if (newQuantity < 1) return;

        // Optimistic update - update UI immediately
        const oldCart = cart;
        if (!cart) return;

        const updatedItems = cart.items.map(item =>
            item.id === itemId ? { ...item, quantity: newQuantity, subtotal_usdt: item.price_usdt * newQuantity } : item
        );
        const newTotalUsdt = updatedItems.reduce((sum, item) => sum + item.subtotal_usdt, 0);

        setCart({
            ...cart,
            items: updatedItems,
            total_usdt: newTotalUsdt
        });

        try {
            haptic.selection();
            await cartApi.updateCartItem(itemId, newQuantity);
            // Silent reload to sync with backend (without showing loading)
            const data = await cartApi.getCart(language);
            setCart(data);
        } catch (error) {
            console.error('Failed to update quantity:', error);
            haptic.notification('error');
            // Откат без объяснения выглядит как глюк: число прыгает обратно, и
            // непонятно почему. Чаще всего это товар пользователя — он штучный,
            // и сервер отвечает «максимум 1».
            showToast(
                errorText(error, language === 'ru'
                    ? 'Не удалось изменить количество'
                    : 'Failed to update quantity'),
                'error',
            );
            // Revert on error (oldCart is guaranteed non-null because of check above)
            if (oldCart) setCart(oldCart);
        }
    };

    const removeItem = async (itemId: string) => {
        // Optimistic update - remove from UI immediately
        const oldCart = cart;
        if (!cart) return;

        const updatedItems = cart.items.filter(item => item.id !== itemId);
        const newTotalUsdt = updatedItems.reduce((sum, item) => sum + item.subtotal_usdt, 0);

        setCart({
            ...cart,
            items: updatedItems,
            total_usdt: newTotalUsdt
        });

        try {
            haptic.impact('medium');
            await cartApi.removeFromCart(itemId);
            // Silent reload to sync with backend
            const data = await cartApi.getCart(language);
            setCart(data);
            haptic.notification('success');
        } catch (error) {
            console.error('Failed to remove item:', error);
            haptic.notification('error');
            // Revert on error (oldCart is guaranteed non-null because of check above)
            if (oldCart) setCart(oldCart);
        }
    };

    const proceedToCheckout = () => {
        haptic.impact('light');
        navigate('/checkout');
    };

    if (isLoading) {
        return (
            <div className="cart-page">
                <div className="container">
                    <h1 className="cart-title">{language === 'ru' ? 'Корзина' : 'Cart'}</h1>
                    <div className="cart-skeleton shimmer" />
                </div>
            </div>
        );
    }

    if (!cart || cart.items.length === 0) {
        return (
            <div className="cart-page">
                <div className="container">
                    <div className="empty-cart">
                        <ShoppingBag size={44} className="empty-state-icon" />
                        <h2>{language === 'ru' ? 'Корзина пуста' : 'Cart is empty'}</h2>
                        <p>{language === 'ru' ? 'Добавьте товары из каталога' : 'Add products from catalog'}</p>
                        {/* Раньше пустая корзина была тупиком: сообщение без
                            единого способа что-то сделать */}
                        <button className="btn-gradient" onClick={() => navigate('/')}>
                            {language === 'ru' ? 'В каталог' : 'Browse catalog'}
                        </button>
                    </div>
                </div>
            </div>
        );
    }

    const itemCount = cart.items.reduce((sum, item) => sum + item.quantity, 0);

    return (
        <div className="cart-page">
            <div className="container">
                {/* Заголовок показывается везде. Раньше он был только для iOS и
                    Android, а место под него резервировалось всегда — на десктопе
                    страница начиналась с пустой полосы. */}
                <h1 className="cart-title">{language === 'ru' ? 'Корзина' : 'Cart'}</h1>

                <div className="cart-items">
                    <AnimatePresence>
                        {cart.items.map((item) => (
                            <motion.div
                                key={item.id}
                                className="cart-item"
                                initial={{ opacity: 0, x: -20 }}
                                animate={{ opacity: 1, x: 0 }}
                                exit={{ opacity: 0, x: 20 }}
                                layout
                            >
                                <img src={item.image_url} alt="" className="item-image" />

                                <h3 className="item-name">{item.name}</h3>

                                <button
                                    className="btn-remove"
                                    onClick={() => removeItem(item.id)}
                                    aria-label={language === 'ru'
                                        ? `Убрать «${item.name}» из корзины`
                                        : `Remove ${item.name} from cart`}
                                >
                                    <Trash2 size={17} />
                                </button>

                                <div className="item-price">
                                    <span className="item-total">${item.subtotal_usdt.toFixed(2)}</span>
                                    {/* Цена за штуку — только когда штук больше одной:
                                        иначе непонятно, откуда взялась сумма */}
                                    {item.quantity > 1 && (
                                        <span className="item-each">
                                            {item.quantity} &#215; ${item.price_usdt}
                                        </span>
                                    )}
                                </div>

                                <div className="quantity-control">
                                    <button
                                        onClick={() => updateQuantity(item.id, item.quantity - 1)}
                                        disabled={item.quantity === 1}
                                        aria-label={language === 'ru' ? 'Меньше' : 'Decrease'}
                                    >
                                        <Minus size={15} />
                                    </button>
                                    <span className="quantity-value">{item.quantity}</span>
                                    <button
                                        onClick={() => updateQuantity(item.id, item.quantity + 1)}
                                        aria-label={language === 'ru' ? 'Больше' : 'Increase'}
                                    >
                                        <Plus size={15} />
                                    </button>
                                </div>

                                {/* Ссылка, которую спросили при заказе услуги — третьим
                                    рядом во всю ширину, а не внутри колонки с названием */}
                                {item.user_data?.link && (
                                    <span className="item-link">{item.user_data.link}</span>
                                )}
                            </motion.div>
                        ))}
                    </AnimatePresence>
                </div>

                <div className="cart-summary">
                    <div className="summary-row">
                        <span>
                            {itemCount}{' '}
                            {language === 'ru' ? 'товаров' : 'items'}
                        </span>
                        <span>${cart.total_usdt.toFixed(2)}</span>
                    </div>

                    <div className="summary-divider" />

                    <div className="summary-row summary-total">
                        <span>{language === 'ru' ? 'Итого' : 'Total'}</span>
                        <span className="summary-amount">${cart.total_usdt.toFixed(2)}</span>
                    </div>

                    <button className="btn-checkout" onClick={proceedToCheckout}>
                        {language === 'ru' ? 'Оформить заказ' : 'Checkout'}
                    </button>
                </div>
            </div>

            <div className="bottom-nav-spacer" />
        </div>
    );
};
