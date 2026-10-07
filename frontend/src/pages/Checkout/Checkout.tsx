import React, { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import { ArrowLeft, Wallet, Loader2, AlertCircle, Check, ChevronRight } from 'lucide-react';
import { useTonAddress, useTonWallet } from '@tonconnect/ui-react';
import { useCartStore } from '@/store/cartStore';
import { useAuthStore } from '@/store/authStore';
import { useToastStore } from '@/store/toastStore';
import { useTelegram } from '@/hooks/useTelegram';
import { useTonPayment } from '@/hooks/useTonPayment';
import { formatTon } from '@/lib/ton';
import { GramIcon } from '@/components/Gram/Gram';
import { TermsGate } from '@/components/TermsGate/TermsGate';
import './Checkout.css';

/** Адрес в 48 символов не читается и ломает узкие экраны */
function shortAddress(address: string): string {
    if (address.length <= 16) return address;
    return `${address.slice(0, 6)}…${address.slice(-6)}`;
}

export const Checkout: React.FC = () => {
    const navigate = useNavigate();
    const { language } = useAuthStore();
    const { cart } = useCartStore();
    const { haptic } = useTelegram();
    const wallet = useTonWallet();
    // Человекочитаемый вид UQ…, а не сырой 0:abc… из wallet.account
    const friendlyAddress = useTonAddress();
    const { pay, cancel, reopenWallet, phase, error, request, orderId, stopPolling } = useTonPayment();
    const [termsAccepted, setTermsAccepted] = React.useState(false);
    const [cancelling, setCancelling] = React.useState(false);
    const showToast = useToastStore((s) => s.show);

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
        await pay('TON', termsAccepted, async () => {
            await useCartStore.getState().clearCart();
            haptic.notification('success');
            navigate('/profile');
        });
    };

    const handleCancel = async () => {
        setCancelling(true);
        haptic.impact('light');
        const ok = await cancel();
        setCancelling(false);

        if (ok) {
            showToast(
                t('Заказ отменён, товар снова в продаже', 'Order cancelled, item is back on sale'),
                'success',
            );
            navigate('/cart');
        } else {
            haptic.notification('error');
        }
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

                    {/* Кошелёк подключается в профиле, а не здесь: перед самой
                        оплатой это ещё один шаг с уходом в другое приложение.
                        Здесь только состояние и дорога туда, если кошелька нет. */}
                    {wallet ? (
                        <div className="wallet-row wallet-row--ok">
                            <div className="wallet-label">
                                <Check size={18} />
                                <span>{t('Кошелёк подключён', 'Wallet connected')}</span>
                            </div>
                            <span className="wallet-address">
                                {shortAddress(friendlyAddress)}
                            </span>
                        </div>
                    ) : (
                        <button
                            className="wallet-row wallet-row--empty"
                            onClick={() => navigate('/profile#wallet')}
                        >
                            <div className="wallet-label">
                                <Wallet size={18} />
                                <span>
                                    {t(
                                        'Кошелёк не подключён — подключить в профиле',
                                        'No wallet connected — connect it in your profile',
                                    )}
                                </span>
                            </div>
                            <ChevronRight size={18} />
                        </button>
                    )}

                    <TermsGate onChange={setTermsAccepted} />

                    {request && (
                        <div className="rate-note">
                            {t('Курс зафиксирован: ', 'Rate locked: ')}
                            1 <GramIcon title="TON" /> = ${request.rate_usd_per_ton}
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
                            <span>{t('К оплате кошельком', 'Wallet payment')}</span>
                            <span>{formatTon(request.amount_ton)} <GramIcon title="TON" /></span>
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
                        disabled={busy || !wallet || !termsAccepted}
                        whileTap={{ scale: 0.98 }}
                    >
                        {busy ? (
                            <span className="btn-busy">
                                <Loader2 size={18} className="spin" />
                                {statusText[phase]}
                            </span>
                        ) : !wallet ? (
                            t('Сначала подключите кошелёк в профиле', 'Connect a wallet in your profile first')
                        ) : !termsAccepted ? (
                            t('Примите условия площадки', 'Accept the terms first')
                        ) : (
                            t('Оплатить', 'Pay Now')
                        )}
                    </motion.button>

                    {/* Кошелёк Telegram иногда открывается не до конца —
                        открываем его снова на тот же запрос, без второго заказа */}
                    {phase === 'awaiting_sign' && (
                        <button className="btn-reopen-wallet" onClick={reopenWallet}>
                            {t(
                                'Кошелёк не открылся или открылся не до конца? Открыть снова',
                                'Wallet did not open properly? Open it again',
                            )}
                        </button>
                    )}

                    {phase === 'confirming' && (
                        <p className="confirm-hint">
                            {t(
                                'Не закрывайте страницу. Подтверждение обычно занимает несколько секунд.',
                                'Keep this page open. Confirmation usually takes a few seconds.',
                            )}
                        </p>
                    )}

                    {/* Заказ создан в момент нажатия «Оплатить» и держит товар в
                        резерве. Если оплата не прошла, без этой кнопки вещь
                        пропадает с витрины до прогона планировщика. */}
                    {orderId && phase !== 'paid' && (
                        <button
                            className="btn-cancel-order"
                            onClick={handleCancel}
                            disabled={cancelling || phase === 'confirming'}
                        >
                            {cancelling
                                ? t('Отменяем...', 'Cancelling...')
                                : t('Отменить заказ', 'Cancel order')}
                        </button>
                    )}

                    {orderId && phase === 'confirming' && (
                        <p className="confirm-hint">
                            {t(
                                'Пока идёт проверка платежа, отменить нельзя.',
                                'Cannot cancel while the payment is being verified.',
                            )}
                        </p>
                    )}
                </div>
            </div>

            <div className="checkout-bottom-spacer" />
        </div>
    );
};
