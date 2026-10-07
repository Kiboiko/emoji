import React, { useEffect, useState } from 'react';
import { Copy, Store, Radio, Handshake, Ticket } from 'lucide-react';
import { usersApi } from '@/api/client';
import { useAuthStore } from '@/store/authStore';
import { useToastStore } from '@/store/toastStore';
import { useTelegram } from '@/hooks/useTelegram';
import { PaymentWallet } from '@/components/PaymentWallet/PaymentWallet';
import { CabinetNav, type CabinetLink } from '@/components/CabinetNav/CabinetNav';
import { AppSettings } from '@/components/AppSettings/AppSettings';
import { ton } from '@/components/DealChat/dealFormat';
import { withGram } from '@/components/Gram/Gram';
import type { ReferralStats, ProfileSummary } from '@/types';
import { BalanceCard } from './BalanceCard';
import './Profile.css';

export const Profile: React.FC = () => {
    const { user, language } = useAuthStore();
    const showToast = useToastStore((s) => s.show);
    const { haptic } = useTelegram();
    const [stats, setStats] = useState<ReferralStats | null>(null);
    const [summary, setSummary] = useState<ProfileSummary | null>(null);

    useEffect(() => {
        // Сами списки здесь не нужны — только числа рядом со строками
        // разделов и статистика рефералов. Баланс грузит своя карточка
        Promise.all([usersApi.getReferralStats(), usersApi.getSummary()])
            .then(([statsData, summaryData]) => {
                setStats(statsData);
                setSummary(summaryData);
            })
            .catch((error) => console.error('Failed to load data:', error));
    }, []);

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
            // «Мои заказы» влились сюда: покупки у площадки и сделки с
            // продавцами — одним списком. Непрочитанное — на вкладке «Чаты»
            to: '/my/deals',
            icon: <Handshake size={18} />,
            label: t('Мои сделки', 'My deals'),
            hint: t('Покупки и продажи', 'Purchases and sales'),
            count: summary?.deals ?? null,
        },
        {
            to: '/my/subscriptions',
            icon: <Ticket size={18} />,
            label: t('Мои подписки', 'My subscriptions'),
            count: summary?.subscriptions ?? null,
        },
    ];

    const earned = stats ? ton(stats.earned_ton ?? '0') : null;

    return (
        <div className="profile-page">
            <div className="container">
                <div className="profile-title-mobile">
                    <h1>{t('Профиль', 'Profile')}</h1>
                </div>

                {/* Один баланс в TON на всё: продажи, подписки, возвраты,
                    реферальные — и вывод на кошелёк из TonConnect */}
                <BalanceCard />

                {/* Показываем только то, что действительно считается на сервере:
                    выдумывать «прирост за неделю» без таких данных нельзя. */}
                <div className="stat-row">
                    <div className="stat-tile">
                        <span className="stat-label">{t('Рефералов', 'Referrals')}</span>
                        <span className="stat-value">{stats?.referral_count ?? '—'}</span>
                    </div>
                    <div className="stat-tile">
                        <span className="stat-label">{t('Ставка', 'Rate')}</span>
                        <span className="stat-value accent">
                            {stats ? `${stats.referral_percent ?? 0}%` : '—'}
                        </span>
                    </div>
                    <div className="stat-tile">
                        <span className="stat-label">{t('Покупок', 'Purchases')}</span>
                        <span className="stat-value">{stats?.paid_orders_count ?? '—'}</span>
                    </div>
                </div>

                <section className="reflink glass-card">
                    <div className="reflink-head">
                        <span className="reflink-title">
                            {t('Моя реферальная ссылка', 'My referral link')}
                        </span>
                        <span className="reflink-hint">
                            {/* Заработанное на рефералах лежит на общем балансе
                                выше; здесь — сколько всего принесла ссылка */}
                            {earned && earned !== '0'
                                ? withGram(t(`заработано ${earned} Gram`, `earned ${earned} Gram`))
                                : t('копируйте и делитесь', 'copy and share')}
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
                            {t('Копировать', 'Copy')}
                        </button>
                    </div>
                </section>

                {/* Кошелёк, которым платят и на который выводят. Стоит до
                    разделов: это условие покупки, а не один из них. */}
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
        </div>
    );
};
