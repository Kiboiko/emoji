import React, { useEffect, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { TonConnectButton, useTonAddress } from '@tonconnect/ui-react';
import { CheckCircle2, Clock, Download, Info, Wallet, X, XCircle } from 'lucide-react';
import { withdrawalsApi } from '@/api/client';
import { useAuthStore } from '@/store/authStore';
import { useToastStore, errorText } from '@/store/toastStore';
import { useTelegram } from '@/hooks/useTelegram';
import { ton } from '@/components/DealChat/dealFormat';
import type { MyWithdrawal } from '@/types';

/**
 * Баланс и вывод.
 *
 * Баланс один, в TON: заработок с продаж и подписок, возвраты по сделкам и
 * реферальные. Раньше их было два с половиной — реферальный в долларах здесь
 * с выводом на USDT TRC20, заработок продавца в TON в кабинете магазина, у
 * автора канала свой, — а покупатель, которому вернули деньги по спору, свой
 * баланс не видел вовсе.
 *
 * Вывод — на кошелёк, подключённый через TonConnect: тот же, которым человек
 * платит. Адрес не вводится руками, поэтому и ошибиться в нём нельзя.
 * Комиссию сети платит площадка.
 */
export const BalanceCard: React.FC = () => {
    const { language } = useAuthStore();
    const showToast = useToastStore((s) => s.show);
    const { haptic } = useTelegram();
    const address = useTonAddress();
    const t = (ru: string, en: string) => (language === 'ru' ? ru : en);

    const [available, setAvailable] = useState<string | null>(null);
    const [holdNano, setHoldNano] = useState(0);
    const [minimum, setMinimum] = useState('1');
    const [failed, setFailed] = useState(false);
    const [history, setHistory] = useState<MyWithdrawal[]>([]);
    const [open, setOpen] = useState(false);
    const [amount, setAmount] = useState('');
    const [sending, setSending] = useState(false);
    const [infoOpen, setInfoOpen] = useState(false);

    const load = async () => {
        setFailed(false);
        try {
            const [balances, mine] = await Promise.all([
                withdrawalsApi.getBalances(),
                withdrawalsApi.getMyWithdrawals(),
            ]);
            setAvailable(balances.TON?.available ?? '0');
            setHoldNano(balances.TON?.hold_minor ?? 0);
            setMinimum(balances.TON?.min_withdrawal ?? '1');
            setHistory(mine.filter((w) => w.currency === 'TON').slice(0, 5));
        } catch {
            setFailed(true);
        }
    };

    useEffect(() => { load(); }, []);

    const total = Number(available ?? 0);
    const enough = total >= Number(minimum);

    const openSheet = () => {
        haptic.impact('light');
        setAmount(available ?? '');
        setOpen(true);
    };

    const submit = async (e: React.FormEvent) => {
        e.preventDefault();
        const value = Number(amount);
        if (!(value > 0) || value > total) {
            showToast(t('Столько на балансе нет', 'Not enough balance'), 'error');
            return;
        }
        if (value < Number(minimum)) {
            showToast(t(`Минимальная сумма вывода — ${minimum} TON`, `Minimum withdrawal is ${minimum} TON`), 'error');
            return;
        }
        if (!address) return;

        setSending(true);
        try {
            await withdrawalsApi.requestWithdrawal({ amount: amount.trim(), wallet: address, currency: 'TON' });
            haptic.notification('success');
            showToast(t('Заявка на вывод отправлена', 'Withdrawal requested'), 'success');
            setOpen(false);
            load();
        } catch (err) {
            haptic.notification('error');
            showToast(errorText(err, t('Не удалось отправить заявку', 'Failed to request withdrawal')), 'error');
        } finally {
            setSending(false);
        }
    };

    const status = (w: MyWithdrawal) => {
        if (w.status === 'completed') {
            return <span className="balance-status done"><CheckCircle2 size={13} />{t('Выплачено', 'Paid')}</span>;
        }
        if (w.status === 'rejected') {
            return <span className="balance-status rejected"><XCircle size={13} />{t('Отклонено', 'Declined')}</span>;
        }
        return <span className="balance-status"><Clock size={13} />{t('В обработке', 'Processing')}</span>;
    };

    return (
        <section className="refwallet-card glass-card">
            <div className="refwallet-head">
                <span className="refwallet-label">
                    <span className="refwallet-dot" aria-hidden="true" />
                    {t('Баланс', 'Balance')}
                    {/* Пояснение спрятано за «i»: в карточке оно занимало две
                        строки, а нужно один раз — понять, что сюда попадает */}
                    <button
                        type="button"
                        className="balance-info-btn"
                        onClick={() => setInfoOpen(!infoOpen)}
                        aria-expanded={infoOpen}
                        aria-label={t('Что входит в баланс', 'What the balance includes')}
                    >
                        <Info size={16} />
                    </button>
                </span>
            </div>

            {infoOpen && (
                <div className="balance-info">
                    {t(
                        'Продажи, подписки, возвраты и реферальные — всё здесь. Выводится на кошелёк, подключённый в профиле.',
                        'Sales, subscriptions, refunds and referral rewards — all in one place. Withdrawn to the wallet connected in your profile.',
                    )}
                </div>
            )}

            {failed ? (
                <div className="refwallet-failed">
                    <span>{t('Не удалось загрузить баланс', 'Could not load the balance')}</span>
                    <button className="refwallet-retry" onClick={load}>{t('Повторить', 'Retry')}</button>
                </div>
            ) : available === null ? (
                <div className="skeleton refwallet-skeleton" />
            ) : (
                <div className="refwallet-amount balance-amount">
                    <span className="balance-ton-mark" aria-hidden="true">
                        <svg width="22" height="22" viewBox="0 0 56 56" fill="currentColor">
                            <path d="M37.58 15.4H18.42c-3.52 0-5.75 3.8-3.98 6.87l11.82 20.49c.77 1.34 2.7 1.34 3.47 0l11.83-20.49c1.76-3.06-.47-6.87-3.98-6.87zM26.25 36.62l-2.57-4.98-6.21-11.1c-.41-.71.1-1.62.95-1.62h7.82v17.7zm12.28-16.09l-6.2 11.1-2.58 4.98V18.91h7.83c.85 0 1.36.91.95 1.62z" />
                        </svg>
                    </span>
                    {ton(available)}
                    <span className="refwallet-currency">TON</span>
                </div>
            )}

            {holdNano > 0 && (
                <div className="refwallet-note">
                    {t(
                        `${ton(String(holdNano / 1e9))} TON выводится`,
                        `${ton(String(holdNano / 1e9))} TON being withdrawn`,
                    )}
                </div>
            )}

            <button className="refwallet-cta" onClick={openSheet} disabled={!enough}>
                <Download size={18} />
                {t('Вывести', 'Withdraw')}
            </button>
            <div className="refwallet-note balance-min">
                {t(`Минимальная сумма — ${minimum} TON`, `Minimum — ${minimum} TON`)}
            </div>

            {history.length > 0 && (
                <ul className="balance-history">
                    {history.map((w) => (
                        <li key={w.id}>
                            <span className="balance-history-main">
                                <span className="balance-history-amount">{ton(String(w.amount))} TON</span>
                                <span className="balance-history-date">
                                    {new Date(w.created_at).toLocaleDateString(language === 'ru' ? 'ru-RU' : 'en-US', {
                                        day: 'numeric', month: 'short',
                                    })}
                                </span>
                            </span>
                            {status(w)}
                            {w.status === 'rejected' && w.reject_reason && (
                                <span className="balance-history-reason">{w.reject_reason}</span>
                            )}
                        </li>
                    ))}
                </ul>
            )}

            <AnimatePresence>
                {open && (
                    <div className="modal-overlay" onClick={() => setOpen(false)}>
                        <motion.div
                            className="withdraw-modal"
                            initial={{ scale: 0.9, opacity: 0 }}
                            animate={{ scale: 1, opacity: 1 }}
                            exit={{ scale: 0.9, opacity: 0 }}
                            onClick={(e) => e.stopPropagation()}
                        >
                            <div className="modal-header">
                                <h3>{t('Вывод средств', 'Withdraw')}</h3>
                                <button className="btn-close" onClick={() => setOpen(false)}>
                                    <X size={20} />
                                </button>
                            </div>

                            <form onSubmit={submit} className="withdraw-form">
                                <div className="form-group">
                                    <label>{t('Сумма', 'Amount')}</label>
                                    <div className="withdraw-amount-container">
                                        <input
                                            type="text"
                                            inputMode="decimal"
                                            value={amount}
                                            onChange={(e) => setAmount(e.target.value.replace(',', '.'))}
                                            className="withdraw-input"
                                            required
                                        />
                                        <span className="withdraw-currency">TON</span>
                                    </div>
                                    <div className="available-balance-hint">
                                        {t('Доступно:', 'Available:')}
                                        <span>{ton(available ?? '0')} TON</span>
                                    </div>
                                </div>

                                {/* Куда придут деньги — подключённый кошелёк. Без
                                    него вывести некуда: адрес руками не вводится */}
                                <div className="form-group">
                                    <label><Wallet size={16} />{t('На кошелёк', 'To wallet')}</label>
                                    {address ? (
                                        <code className="balance-address">{address}</code>
                                    ) : (
                                        <div className="balance-connect">
                                            <span>
                                                {t(
                                                    'Подключите кошелёк — на него придут деньги.',
                                                    'Connect a wallet — the money will be sent there.',
                                                )}
                                            </span>
                                            <TonConnectButton />
                                        </div>
                                    )}
                                </div>

                                <p className="balance-terms">
                                    {t(
                                        `Комиссию сети платит площадка: придёт ровно указанная сумма. Выплату проводит администратор, минимум — ${minimum} TON.`,
                                        `The marketplace pays the network fee: you receive exactly this amount. Payouts are processed by an administrator, minimum ${minimum} TON.`,
                                    )}
                                </p>

                                <button type="submit" className="btn-submit-withdraw" disabled={sending || !address}>
                                    {sending ? <div className="loader-small" /> : t('Вывести', 'Withdraw')}
                                </button>
                            </form>
                        </motion.div>
                    </div>
                )}
            </AnimatePresence>
        </section>
    );
};
