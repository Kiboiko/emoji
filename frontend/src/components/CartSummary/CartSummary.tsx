import React from 'react';
import { useNavigate } from 'react-router-dom';
import { useCartStore } from '@/store/cartStore';
import { useAuthStore } from '@/store/authStore';
import './CartSummary.css';

export const CartSummary: React.FC = () => {
    const navigate = useNavigate();
    const { language } = useAuthStore();

    // Subscribe effectively to changes
    const { itemCount, totalUSDT } = useCartStore((state) => {
        const items = state.cart?.items || [];
        return {
            itemCount: items.reduce((sum, item) => sum + item.quantity, 0),
            totalUSDT: state.cart?.total_usdt || 0
        };
    });

    if (itemCount === 0) return null;

    return (
        <div className="cart-summary-widget">
            <div className="summary-row">
                <span>{language === 'ru' ? 'Товары' : 'Items'}</span>
                <span>{itemCount}</span>
            </div>

            <div className="divider divider-tight" />

            <div className="summary-total">
                <span className="total-label">{language === 'ru' ? 'Итого' : 'Total'}</span>
                <span className="total-value">${totalUSDT.toFixed(2)}</span>
            </div>

            <button
                className="checkout-btn"
                onClick={() => navigate('/checkout')}
            >
                {language === 'ru' ? 'Оформить заказ' : 'Checkout'}
            </button>
        </div>
    );
};
