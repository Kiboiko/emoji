import React, { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import { ArrowLeft, Wallet, Loader2, AlertCircle } from 'lucide-react';
import { TonConnectButton, useTonWallet } from '@tonconnect/ui-react';
import { useCartStore } from '@/store/cartStore';
import { useAuthStore } from '@/store/authStore';
import { useTelegram } from '@/hooks/useTelegram';
import { useTonPayment } from '@/hooks/useTonPayment';
import './Checkout.css';

export const Checkout: React.FC = () => {
    const navigate = useNavigate();
    const { language } = useAuthStore();
    const { cart } = useCartStore();
    const { haptic } = useTelegram();
    const wallet = useTonWallet();
    const { pay, phase, error, request, stopPolling } = useTonPayment();

    const t = (ru: string, en: string) => (language === 'ru' ? ru : en);

    // Опрос статуса продолжался бы и после ухода со страницы
    useEffect(() => stopPolling, [stopPolling]);

    useEffect(() => {
        if (!cart || cart.items.length === 0) {
            if (phase === 'idle') navigate('/cart');
        }
    }, [cart, phase, navigate]);

    const busy = phase === 'creating' || phase === 'awaiting_sign' || phase === 'confirming';

    const handlePay = async () => {
        haptic.impact('medium');
        await pay('TON', async () => {
            await useCartStore.getState().clearCart();
            haptic.notification('success');
            navigate('/profile');
        });
    };

    if (!cart || cart.items.length === 0) return null;

    const statusText: Record<string, string> = {
        creating: t('Готовим счёт...', 'Preparing invoice...'),
        awaiting_sign: t('Подтвердите в кошельке', 'Confirm in your wallet'),
        confirming: t('Ждём подтверждения сети...', 'Waiting for network confirmation...'),
    };

    return (
        <div className="checkout-page">
            <div className="container">
                <button className="btn-back" onClick={() => navigate('/cart')} disabled={busy}>
                    <ArrowLeft size={20} />
                    <span>{t('Назад', 'Back')}</span>
                </button>

                <h1>{t('Оформление заказа', 'Checkout')}</h1>

                <div className="order-summary glass-card">
                    <h2>{t('Ваш заказ', 'Your Order')}</h2>
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
                        <span>{t('Всего товаров', 'Total Items')}</span>
                        <span>{cart.items.reduce((sum, i) => sum + i.quantity, 0)}</span>
                    </div>
                </div>

                <div className="payment-section glass-card">
                    <h2>{t('Оплата', 'Payment')}</h2>

                    <div className="wallet-row">
                        <div className="wallet-label">
                            <Wallet size={18} />
                            <span>
                                {wallet
                                    ? t('Кошелёк подключён', 'Wallet connected')
                                    : t('Подключите кошелёк TON', 'Connect your TON wallet')}
                            </span>
                        </div>
                        <TonConnectButton />
                    </div>

                    {request && (
                        <div className="rate-note">
                            {t('Курс зафиксирован: ', 'Rate locked: ')}
                            1 TON = ${request.rate_usd_per_ton}
                        </div>
                    )}
                </div>

                <div className="total-section glass-card">
                    <div className="total-row">
                        <span>{t('Итого к оплате', 'Total to Pay')}</span>
                        <span className="total-amount text-gradient">
                            ${cart.total_usdt.toFixed(2)}
                        </span>
                    </div>

                    {request && (
                        <div className="total-row total-row-secondary">
                            <span>{t('В TON', 'In TON')}</span>
                            <span>{Number(request.amount_ton).toFixed(4)} TON</span>
                        </div>
                    )}

                    {error && (
                        <div className="payment-error">
                            <AlertCircle size={16} />
                            <span>{error}</span>
                        </div>
                    )}

                    <motion.button
                        className="btn-gradient btn-pay"
                        onClick={handlePay}
                        disabled={busy || !wallet}
                        whileTap={{ scale: 0.98 }}
                    >
                        {busy ? (
                            <span className="btn-busy">
                                <Loader2 size={18} className="spin" />
                                {statusText[phase]}
                            </span>
                        ) : !wallet ? (
                            t('Сначала подключите кошелёк', 'Connect wallet first')
                        ) : (
                            t('Оплатить', 'Pay Now')
                        )}
                    </motion.button>

                    {phase === 'confirming' && (
                        <p className="confirm-hint">
                            {t(
                                'Не закрывайте страницу. Подтверждение обычно занимает несколько секунд.',
                                'Keep this page open. Confirmation usually takes a few seconds.',
                            )}
                        </p>
                    )}
                </div>
            </div>

            <div className="checkout-bottom-spacer" />
        </div>
    );
};
