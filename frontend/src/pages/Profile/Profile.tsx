import React, { useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
    Copy, Clock, Download, X, Wallet, Store, Radio, Package, Handshake, Ticket,
} from 'lucide-react';
import { usersApi } from '@/api/client';
import { useAuthStore } from '@/store/authStore';
import { useToastStore } from '@/store/toastStore';
import { useTelegram } from '@/hooks/useTelegram';
import { PaymentWallet } from '@/components/PaymentWallet/PaymentWallet';
import { CabinetNav, type CabinetLink } from '@/components/CabinetNav/CabinetNav';
import { AppSettings } from '@/components/AppSettings/AppSettings';
import type { ReferralStats, ProfileSummary } from '@/types';
import './Profile.css';

export const Profile: React.FC = () => {
    const { user, language } = useAuthStore();
    const showToast = useToastStore((s) => s.show);
    const { haptic } = useTelegram();
    const [stats, setStats] = useState<ReferralStats | null>(null);
    const [summary, setSummary] = useState<ProfileSummary | null>(null);
    // Ошибка отдельным флагом: без него пустой stats означал и «ещё
    // грузится», и «не загрузилось» — и скелетон крутился вечно
    const [statsFailed, setStatsFailed] = useState(false);
    const [isModalOpen, setIsModalOpen] = useState(false);
    const [walletAddress, setWalletAddress] = useState('');
    const [withdrawAmount, setWithdrawAmount] = useState<string>('');
    const [isSubmitting, setIsSubmitting] = useState(false);

    useEffect(() => {
        loadStats();
    }, []);

    const loadStats = async () => {
        setStatsFailed(false);
        try {
            // Сами списки здесь больше не нужны — только числа рядом
            // со строками разделов
            const [statsData, summaryData] = await Promise.all([
                usersApi.getReferralStats(),
                usersApi.getSummary(),
            ]);
            setStats(statsData);
            setSummary(summaryData);
        } catch (error) {
            console.error('Failed to load data:', error);
            setStatsFailed(true);
        }
    };

    const copyReferralLink = async () => {
        const botUsername = import.meta.env.VITE_BOT_USERNAME || 'your_bot';
        const link = `https://t.me/${botUsername}?start=ref_${user?.referral_code}`;

        // navigator.clipboard есть не везде: внутри Telegram WebView он может
        // отсутствовать или отклонить вызов. Промис раньше не ожидался, поэтому
        // отказ уходил в никуда — ссылка молча не копировалась.
        try {
            if (navigator.clipboard?.writeText) {
                await navigator.clipboard.writeText(link);
            } else {
                const field = document.createElement('textarea');
                field.value = link;
                field.setAttribute('readonly', '');
                field.style.position = 'fixed';
                field.style.opacity = '0';
                document.body.appendChild(field);
                field.select();
                document.execCommand('copy');
                document.body.removeChild(field);
            }
            haptic.notification('success');
            showToast(language === 'ru' ? 'Ссылка скопирована' : 'Link copied', 'success');
        } catch {
            haptic.notification('error');
            showToast(
                language === 'ru' ? 'Не удалось скопировать ссылку' : 'Failed to copy link',
                'error',
            );
        }
    };

    const openWithdrawModal = () => {
        setIsModalOpen(true);
        haptic.impact('light');
    };

    const closeWithdrawModal = () => {
        setIsModalOpen(false);
        setWalletAddress('');
        setWithdrawAmount('');
    };

    const handleWithdraw = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!stats) return;

        const amount = parseFloat(withdrawAmount);

        // Validation: Must be > 0 and <= balance
        if (isNaN(amount) || amount <= 0) {
            haptic.notification('error');
            alert(language === 'ru' ? 'Сумма должна быть больше 0' : 'Amount must be greater than 0');
            return;
        }

        if (amount > stats.total_earnings) {
            haptic.notification('error');
            alert(language === 'ru' ? 'Недостаточно средств на балансе' : 'Insufficient balance');
            return;
        }

        setIsSubmitting(true);
        haptic.impact('heavy');

        try {
            if (!walletAddress.trim()) {
                alert(language === 'ru' ? 'Введите адрес кошелька' : 'Enter wallet address');
                return;
            }

            const withdrawalsApi = (await import('@/api/client')).withdrawalsApi;
            await withdrawalsApi.requestWithdrawal({
                amount: amount,
                wallet: walletAddress
            });

            haptic.notification('success');

            // Show toast
            const toast = document.createElement('div');
            toast.className = 'toast success';
            toast.textContent = language === 'ru' ? 'Заявка на вывод отправлена!' : 'Withdrawal request sent!';
            document.body.appendChild(toast);
            setTimeout(() => toast.remove(), 3000);

            closeWithdrawModal();
            loadStats(); // Refresh stats to reflect deducted balance
        } catch (error: any) {
            console.error('Withdrawal failed:', error);
            haptic.notification('error');

            let errorMessage = language === 'ru' ? 'Ошибка при отправке заявки' : 'Failed to send request';

            if (error.response?.data?.detail) {
                const detail = error.response.data.detail;
                if (Array.isArray(detail) && detail.length > 0) {
                    // Handle FastAPI 422 errors
                    errorMessage = detail[0].msg || JSON.stringify(detail);
                } else if (typeof detail === 'string') {
                    errorMessage = detail;
                } else {
                    errorMessage = JSON.stringify(detail);
                }
            }

            alert(errorMessage);
        } finally {
            setIsSubmitting(false);
        }
    };

    const t = (ru: string, en: string) => (language === 'ru' ? ru : en);

    // Строка магазина есть всегда, даже у не-продавца: иначе завести
    // магазин неоткуда — регистрация живёт внутри того же экрана
    const cabinetLinks: CabinetLink[] = [
        {
            to: '/my/listings',
            icon: <Store size={18} />,
            label: t('Мой магазин', 'My store'),
            hint: summary?.is_seller
                ? t('Товары и заявки на размещение', 'Products and listings')
                : t('Начать продавать', 'Start selling'),
            count: summary?.is_seller ? summary.listings : null,
        },
        {
            to: '/my/channels',
            icon: <Radio size={18} />,
            label: t('Мои каналы', 'My channels'),
            hint: t('Продажа подписок', 'Selling subscriptions'),
            count: summary?.channels ?? null,
        },
        {
            to: '/my/orders',
            icon: <Package size={18} />,
            label: t('Мои заказы', 'My orders'),
            count: summary?.orders ?? null,
        },
        {
            to: '/my/deals',
            icon: <Handshake size={18} />,
            label: t('Мои сделки', 'My deals'),
            hint: t('Покупки и продажи через эскроу', 'Escrow purchases and sales'),
            count: summary?.deals ?? null,
        },
        {
            to: '/my/subscriptions',
            icon: <Ticket size={18} />,
            label: t('Мои подписки', 'My subscriptions'),
            count: summary?.subscriptions ?? null,
        },
    ];

    return (
        <div className="profile-page">
            <div className="container">
                <div className="profile-title-mobile">
                    <h1>{language === 'ru' ? 'Профиль' : 'Profile'}</h1>
                </div>

                {/* Баланс реферальной программы */}
                <section className="refwallet-card glass-card">
                    <div className="refwallet-head">
                        <span className="refwallet-label">
                            <span className="refwallet-dot" aria-hidden="true" />
                            {language === 'ru' ? 'Доступно к выводу' : 'Available to withdraw'}
                        </span>
                        {stats !== null && stats.total_earnings > 0 && (
                            <span className="refwallet-pill">
                                {language === 'ru' ? 'готово' : 'ready'}
                            </span>
                        )}
                    </div>

                    {/* Пока статистика не пришла, показывать $0.00 нельзя:
                        человек с балансом видит ноль и решает, что деньги
                        пропали. Скелетон честнее — «ещё не знаем». */}
                    {statsFailed ? (
                        <div className="refwallet-failed">
                            <span>
                                {language === 'ru'
                                    ? 'Не удалось загрузить баланс'
                                    : 'Could not load the balance'}
                            </span>
                            <button className="refwallet-retry" onClick={loadStats}>
                                {language === 'ru' ? 'Повторить' : 'Retry'}
                            </button>
                        </div>
                    ) : stats === null ? (
                        <div className="skeleton refwallet-skeleton" />
                    ) : (
                        <div className="refwallet-amount">
                            {stats.total_earnings.toFixed(2)}
                            <span className="refwallet-currency">$</span>
                        </div>
                    )}

                    {/* Второй уровень включается настройкой и чаще выключен —
                        показываем строку, только когда по нему что-то есть */}
                    {!!stats?.level2_earnings && (
                        <div className="refwallet-note">
                            {language === 'ru'
                                ? 'из них со второго уровня'
                                : 'of which from level 2'}: ${stats.level2_earnings.toFixed(2)}
                        </div>
                    )}

                    <button
                        className="refwallet-cta"
                        onClick={openWithdrawModal}
                        disabled={stats === null || stats.total_earnings <= 0}
                    >
                        <Download size={18} />
                        {language === 'ru' ? 'Вывести средства' : 'Withdraw funds'}
                    </button>
                </section>

                {/* Показываем только то, что действительно считается на сервере:
                    выдумывать «прирост за неделю» без таких данных нельзя. */}
                <div className="stat-row">
                    <div className="stat-tile">
                        <span className="stat-label">{language === 'ru' ? 'Рефералов' : 'Referrals'}</span>
                        <span className="stat-value">{stats?.referral_count ?? '—'}</span>
                    </div>
                    <div className="stat-tile">
                        <span className="stat-label">{language === 'ru' ? 'Ставка' : 'Rate'}</span>
                        <span className="stat-value accent">
                            {stats ? `${stats.referral_percent ?? 0}%` : '—'}
                        </span>
                    </div>
                    <div className="stat-tile">
                        <span className="stat-label">{language === 'ru' ? 'Покупок' : 'Purchases'}</span>
                        <span className="stat-value">{stats?.paid_orders_count ?? '—'}</span>
                    </div>
                </div>

                <section className="reflink glass-card">
                    <div className="reflink-head">
                        <span className="reflink-title">
                            {language === 'ru' ? 'Моя реферальная ссылка' : 'My referral link'}
                        </span>
                        <span className="reflink-hint">
                            {language === 'ru' ? 'копируйте и делитесь' : 'copy and share'}
                        </span>
                    </div>
                    <div className="reflink-row">
                        <span className="reflink-text">
                            <span className="reflink-prefix">
                                t.me/{import.meta.env.VITE_BOT_USERNAME || 'your_bot'}?start=ref_
                            </span>
                            <span className="reflink-code">
                                {user?.referral_code || user?.telegram_id}
                            </span>
                        </span>
                        <button className="reflink-copy" onClick={copyReferralLink}>
                            <Copy size={14} />
                            {language === 'ru' ? 'Копировать' : 'Copy'}
                        </button>
                    </div>
                </section>

                {/* Кошелёк, которым платят. Стоит до разделов:
                    это условие покупки, а не один из них. */}
                <PaymentWallet />

                {/* Разделы уехали на отдельные экраны: в одном свитке при
                    десятке товаров и подписок всё превращалось в мелкую кашу. */}
                <CabinetNav links={cabinetLinks} />

                {/* Язык и оформление. Были кнопками в шапке каталога, где
                    висели на каждом экране ради настройки, которую меняют
                    один раз. */}
                <AppSettings />
            </div>

            <div className="bottom-nav-spacer" />

            {/* Withdraw Modal */}
            <AnimatePresence>
                {isModalOpen && (
                    <div className="modal-overlay" onClick={closeWithdrawModal}>
                        <motion.div
                            className="withdraw-modal"
                            initial={{ scale: 0.9, opacity: 0 }}
                            animate={{ scale: 1, opacity: 1 }}
                            exit={{ scale: 0.9, opacity: 0 }}
                            onClick={(e) => e.stopPropagation()}
                        >
                            <div className="modal-header">
                                <h3>{language === 'ru' ? 'Вывод средств' : 'Withdraw Funds'}</h3>
                                <button className="btn-close" onClick={closeWithdrawModal}>
                                    <X size={20} />
                                </button>
                            </div>

                            <form onSubmit={handleWithdraw} className="withdraw-form">
                                <div className="form-group">
                                    <label>
                                        <Wallet size={16} />
                                        {language === 'ru' ? 'Кошелек (TRC20)' : 'Wallet Address (TRC20)'}
                                    </label>
                                    <input
                                        type="text"
                                        value={walletAddress}
                                        onChange={(e) => setWalletAddress(e.target.value)}
                                        placeholder="T..."
                                        className="withdraw-input"
                                        required
                                    />
                                </div>

                                <div className="form-group">
                                    <label>
                                        <Clock size={16} />
                                        {language === 'ru' ? 'Сумма вывода' : 'Withdraw Amount'}
                                    </label>
                                    <div className="withdraw-amount-container">
                                        <input
                                            type="number"
                                            value={withdrawAmount}
                                            onChange={(e) => setWithdrawAmount(e.target.value)}
                                            placeholder="0.00"
                                            className="withdraw-input"
                                            step="0.01"
                                            required
                                        />
                                        <span className="withdraw-currency">USDT</span>
                                    </div>
                                    <div className="available-balance-hint">
                                        {language === 'ru' ? 'Доступно:' : 'Available:'}
                                        <span>${(stats?.total_earnings || 0).toFixed(2)}</span>
                                    </div>
                                </div>

                                <button
                                    type="submit"
                                    className="btn-submit-withdraw"
                                    disabled={isSubmitting}
                                >
                                    {isSubmitting ? (
                                        <div className="loader-small"></div>
                                    ) : (
                                        language === 'ru' ? 'Вывод' : 'Withdraw'
                                    )}
                                </button>
                            </form>
                        </motion.div>
                    </div>
                )}
            </AnimatePresence>
        </div>
    );
};
