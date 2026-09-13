import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import { ArrowLeft } from 'lucide-react';
import { ordersApi, paymentsApi } from '@/api/client';
import { useCartStore } from '@/store/cartStore';
import { useAuthStore } from '@/store/authStore';
import { useTelegram } from '@/hooks/useTelegram';
import './Checkout.css';

export const Checkout: React.FC = () => {
    const navigate = useNavigate();
    const { language } = useAuthStore();
    const { cart } = useCartStore();
    const { haptic } = useTelegram();

    const [selectedCurrency, setSelectedCurrency] = useState<'USDT' | 'TON'>('USDT');
    const [isProcessing, setIsProcessing] = useState(false);

    const handleCheckout = async () => {
        try {
            setIsProcessing(true);
            haptic.impact('medium');

            const response = await ordersApi.createOrder(selectedCurrency);
            const orderId = response.order_id;

            // Open payment URL using Telegram WebApp API
            const payUrl = response.pay_url || response.mini_app_url;
            if (payUrl) {
                // Check if it's a telegram link (direct or via t.me)
                if (payUrl.includes('t.me/') || payUrl.includes('tg://')) {
                    // @ts-ignore
                    window.Telegram?.WebApp?.openTelegramLink(payUrl);
                } else {
                    // @ts-ignore
                    window.Telegram?.WebApp?.openLink(payUrl);
                }
            }

            // Poll for payment status
            const maxAttempts = 60; // Poll for 5 minutes (60 * 5 seconds)
            let attempts = 0;
            const pollInterval = setInterval(async () => {
                try {
                    attempts++;
                    const status = await paymentsApi.checkPaymentStatus(orderId);

                    if (status.paid) {
                        clearInterval(pollInterval);

                        // Clear cart manually since webhook might not have cleared it yet
                        const { clearCart } = useCartStore.getState();
                        await clearCart();

                        haptic.notification('success');
                        navigate('/profile'); // Navigate to profile to show completed order
                    } else if (attempts >= maxAttempts) {
                        clearInterval(pollInterval);
                        // Timeout - navigate to profile anyway, webhook might complete later
                        navigate('/profile');
                    }
                } catch (error) {
                    console.error('Payment status check failed:', error);
                    if (attempts >= maxAttempts) {
                        clearInterval(pollInterval);
                        navigate('/profile');
                    }
                }
            }, 5000); // Check every 5 seconds

        } catch (error) {
            console.error('Checkout failed:', error);
            haptic.notification('error');
            alert(language === 'ru' ? 'Ошибка при создании заказа' : 'Failed to create order');
        } finally {
            setIsProcessing(false);
        }
    };

    if (!cart || cart.items.length === 0) {
        navigate('/cart');
        return null;
    }

    return (
        <div className="checkout-page">
            <div className="container">
                <button className="btn-back" onClick={() => navigate('/cart')}>
                    <ArrowLeft size={20} />
                    <span>{language === 'ru' ? 'Назад' : 'Back'}</span>
                </button>

                <h1>{language === 'ru' ? 'Оформление заказа' : 'Checkout'}</h1>

                {/* Order Summary */}
                <div className="order-summary glass-card">
                    <h2>{language === 'ru' ? 'Ваш заказ' : 'Your Order'}</h2>

                    <div className="summary-items">
                        {cart.items.map((item) => (
                            <div key={item.id} className="summary-item">
                                <img src={item.image_url} alt={item.name} />
                                <div className="item-details">
                                    <p className="item-name">{item.name}</p>
                                    <p className="item-quantity">x{item.quantity}</p>
                                </div>
                                <p className="item-price">${item.subtotal_usdt.toFixed(2)}</p>
                            </div>
                        ))}
                    </div>

                    <div className="divider" />

                    <div className="summary-row">
                        <span>{language === 'ru' ? 'Всего товаров' : 'Total Items'}</span>
                        <span>{cart.items.reduce((sum, item) => sum + item.quantity, 0)}</span>
                    </div>
                </div>

                {/* Payment Method */}
                <div className="payment-section glass-card">
                    <h2>{language === 'ru' ? 'Выберите валюту' : 'Select Currency'}</h2>

                    <div className="currency-options">
                        <motion.button
                            className={`currency-option ${selectedCurrency === 'USDT' ? 'active' : ''}`}
                            onClick={() => {
                                setSelectedCurrency('USDT');
                                haptic.selection();
                            }}
                            whileTap={{ scale: 0.98 }}
                        >
                            <div className="currency-info">
                                <p className="currency-name">USDT</p>
                            </div>
                            {selectedCurrency === 'USDT' && (
                                <div className="check-mark">✓</div>
                            )}
                        </motion.button>

                        <motion.button
                            className={`currency-option ${selectedCurrency === 'TON' ? 'active' : ''}`}
                            onClick={() => {
                                setSelectedCurrency('TON');
                                haptic.selection();
                            }}
                            whileTap={{ scale: 0.98 }}
                        >
                            <div className="currency-info">
                                <p className="currency-name">TON</p>
                            </div>
                            {selectedCurrency === 'TON' && (
                                <div className="check-mark">✓</div>
                            )}
                        </motion.button>
                    </div>

                </div>

                {/* Total */}
                <div className="total-section glass-card">
                    <div className="total-row">
                        <span>{language === 'ru' ? 'Итого к оплате' : 'Total to Pay'}</span>
                        <span className="total-amount text-gradient">
                            ${cart.total_usdt.toFixed(2)}
                        </span>
                    </div>

                    <motion.button
                        className="btn-gradient btn-pay"
                        onClick={handleCheckout}
                        disabled={isProcessing}
                        whileTap={{ scale: 0.98 }}
                    >
                        {isProcessing
                            ? (language === 'ru' ? 'Обработка...' : 'Processing...')
                            : (language === 'ru' ? 'Оплатить' : 'Pay Now')
                        }
                    </motion.button>
                </div>
            </div>

            <div style={{ height: '80px' }} />
        </div>
    );
};
