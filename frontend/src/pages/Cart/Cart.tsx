import React, { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Trash2, Plus, Minus, ShoppingBag } from 'lucide-react';
import { useAuthStore } from '@/store/authStore';
import { useCartStore } from '@/store/cartStore';
import { useToastStore } from '@/store/toastStore';
import { useTelegram } from '@/hooks/useTelegram';
import { thumb } from '@/lib/image';
import './Cart.css';

export const Cart: React.FC = () => {
    const navigate = useNavigate();
    const language = useAuthStore(state => state.language);
    const { cart, isLoading, isSaving, fetchCart, updateQuantity: saveQuantity, removeItem: deleteItem } = useCartStore();
    const showToast = useToastStore((s) => s.show);
    const { haptic } = useTelegram();
    useEffect(() => { void fetchCart(); }, [language, fetchCart]);

    const updateQuantity = (itemId: string, delta: number) => {
        const item = useCartStore.getState().cart?.items.find(item => item.id === itemId);
        if (!item) return;
        const quantity = item.quantity + delta;
        if (quantity < 1) return;
        if (item.max_quantity != null && quantity > item.max_quantity) {
            showToast(language === 'ru' ? `Максимум ${item.max_quantity} шт.` : `Maximum ${item.max_quantity}`, 'error');
            return;
        }
        haptic.selection();
        saveQuantity(itemId, quantity);
    };

    const removeItem = (itemId: string) => {
        haptic.impact('medium');
        deleteItem(itemId);
    };

    const proceedToCheckout = () => {
        haptic.impact('light');
        navigate('/checkout');
    };

    if (isLoading && !cart) {
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
                    {cart.items.map((item) => (
                        <div
                            key={item.id}
                            className="cart-item"
                        >
                            <img src={thumb(item.image_url, 'cart')} alt="" className="item-image" loading="lazy" decoding="async" />

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
                                {/* Потолок называем только когда в него упёрлись:
                                    иначе погасший «плюс» ничего не объясняет */}
                                {item.max_quantity != null
                                    && item.quantity >= item.max_quantity && (
                                    <span className="item-limit">
                                        {language === 'ru'
                                            ? `макс. ${item.max_quantity}`
                                            : `max ${item.max_quantity}`}
                                    </span>
                                )}
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
                                    onClick={() => updateQuantity(item.id, -1)}
                                    disabled={item.quantity === 1}
                                    aria-label={language === 'ru' ? 'Меньше' : 'Decrease'}
                                >
                                    <Minus size={15} />
                                </button>
                                <span className="quantity-value">{item.quantity}</span>
                                <button
                                    onClick={() => updateQuantity(item.id, 1)}
                                    disabled={item.max_quantity != null
                                        && item.quantity >= item.max_quantity}
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
                        </div>
                    ))}

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

                    <button className="btn-checkout" disabled={isSaving} onClick={proceedToCheckout}>
                        {isSaving ? (language === 'ru' ? 'Сохраняем…' : 'Saving…') : (language === 'ru' ? 'Оформить заказ' : 'Checkout')}
                    </button>
                </div>
            </div>

            <div className="bottom-nav-spacer" />
        </div>
    );
};
