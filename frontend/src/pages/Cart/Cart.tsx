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
                    <h1>{language === 'ru' ? 'Корзина' : 'Cart'}</h1>
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

    return (
        <div className="cart-page">
            <div className="container">
                <div className="page-title-mobile">
                    <h1>{language === 'ru' ? 'Корзина' : 'Cart'}</h1>
                </div>

                <div className="cart-items">
                    <AnimatePresence>
                        {cart.items.map((item) => (
                            <motion.div
                                key={item.id}
                                className="cart-item glass-card"
                                initial={{ opacity: 0, x: -20 }}
                                animate={{ opacity: 1, x: 0 }}
                                exit={{ opacity: 0, x: 20 }}
                                layout
                            >
                                <img src={item.image_url} alt={item.name} className="item-image" />

                                <div className="item-info">
                                    <h3>{item.name}</h3>
                                    {item.user_data?.link && (
                                        <div className="item-link-wrapper">
                                            <span className="item-link-chip">
                                                {item.user_data.link}
                                            </span>
                                        </div>
                                    )}
                                </div>

                                <div className="item-controls">
                                    <div className="quantity-control">
                                        <button
                                            onClick={() => updateQuantity(item.id, item.quantity - 1)}
                                            disabled={item.quantity === 1}
                                        >
                                            <Minus size={16} />
                                        </button>
                                        <span>{item.quantity}</span>
                                        <button onClick={() => updateQuantity(item.id, item.quantity + 1)}>
                                            <Plus size={16} />
                                        </button>
                                    </div>
                                </div>



                                <p className="item-price">${item.price_usdt}</p>

                                <button
                                    className="btn-remove"
                                    onClick={() => removeItem(item.id)}
                                >
                                    <Trash2 size={18} />
                                </button>
                            </motion.div>
                        ))}
                    </AnimatePresence>
                </div>

                <div className="cart-summary glass-card">
                    <div className="summary-row total">
                        <span>{language === 'ru' ? 'Итого' : 'Total'}</span>
                        <span className="text-gradient">${cart.total_usdt.toFixed(2)}</span>
                    </div>

                    <button className="btn-gradient btn-checkout" onClick={proceedToCheckout}>
                        {language === 'ru' ? 'Оформить заказ' : 'Checkout'}
                    </button>
                </div>
            </div>

            <div className="bottom-nav-spacer" />
        </div>
    );
};
