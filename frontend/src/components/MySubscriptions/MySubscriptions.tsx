import React, { useEffect, useState } from 'react';
import { Lock, ExternalLink, RefreshCw, Clock } from 'lucide-react';
import { subscriptionsApi } from '@/api/client';
import { useAuthStore } from '@/store/authStore';
import { useTelegram } from '@/hooks/useTelegram';
import type { MySubscription } from '@/types';
import './MySubscriptions.css';

export const MySubscriptions: React.FC = () => {
    const { language } = useAuthStore();
    const { haptic } = useTelegram();
    const [items, setItems] = useState<MySubscription[]>([]);
    const [loading, setLoading] = useState(true);
    const [reissuing, setReissuing] = useState<string | null>(null);

    const t = (ru: string, en: string) => (language === 'ru' ? ru : en);

    useEffect(() => {
        subscriptionsApi
            .getMySubscriptions()
            .then(setItems)
            .catch(() => setItems([]))
            .finally(() => setLoading(false));
    }, []);

    const openLink = (link: string) => {
        haptic.impact('light');
        // Ссылка на закрытый канал — это t.me, открывать надо внутри Telegram
        (window as any).Telegram?.WebApp?.openTelegramLink?.(link);
    };

    const handleReissue = async (subscription: MySubscription) => {
        setReissuing(subscription.id);
        try {
            const { invite_link } = await subscriptionsApi.reissueInvite(subscription.id);
            setItems((prev) =>
                prev.map((s) =>
                    s.id === subscription.id ? { ...s, invite_link } : s,
                ),
            );
            openLink(invite_link);
        } catch {
            haptic.notification('error');
        } finally {
            setReissuing(null);
        }
    };

    // Блок не занимает место, пока подписок нет
    if (loading || items.length === 0) return null;

    return (
        <div className="subscriptions-section glass-card">
            <h2 className="subscriptions-title">
                <Lock size={18} />
                {t('Мои подписки', 'My Subscriptions')}
            </h2>

            <div className="subscriptions-list">
                {items.map((s) => {
                    const isActive = s.status === 'active';
                    return (
                        <div key={s.id} className={`subscription-item status-${s.status}`}>
                            <div className="subscription-head">
                                <span className="subscription-channel">
                                    {language === 'en' ? s.channel_title_en ?? s.channel_title : s.channel_title}
                                </span>
                                <span className={`subscription-badge badge-${s.status}`}>
                                    {s.status === 'active' && t('Активна', 'Active')}
                                    {s.status === 'expired' && t('Истекла', 'Expired')}
                                    {s.status === 'revoked' && t('Отозвана', 'Revoked')}
                                    {s.status === 'pending' && t('Ожидает', 'Pending')}
                                </span>
                            </div>

                            {s.plan_title && (
                                <div className="subscription-plan">
                                    {language === 'en' ? s.plan_title_en ?? s.plan_title : s.plan_title}
                                </div>
                            )}

                            {isActive && s.expires_at && (
                                <div className="subscription-expiry">
                                    <Clock size={14} />
                                    {t('Действует до ', 'Valid until ')}
                                    {new Date(s.expires_at).toLocaleDateString(
                                        language === 'ru' ? 'ru-RU' : 'en-US',
                                    )}
                                    {s.days_left !== null && (
                                        <span className="days-left">
                                            {' '}
                                            ({s.days_left} {t('дн.', 'days')})
                                        </span>
                                    )}
                                </div>
                            )}

                            {isActive && !s.joined && (
                                <div className="subscription-actions">
                                    {s.invite_link ? (
                                        <button
                                            className="subscription-btn"
                                            onClick={() => openLink(s.invite_link!)}
                                        >
                                            <ExternalLink size={14} />
                                            {t('Войти в канал', 'Open channel')}
                                        </button>
                                    ) : (
                                        <button
                                            className="subscription-btn"
                                            disabled={reissuing === s.id}
                                            onClick={() => handleReissue(s)}
                                        >
                                            <RefreshCw size={14} />
                                            {reissuing === s.id
                                                ? t('Получаем...', 'Requesting...')
                                                : t('Получить ссылку', 'Get link')}
                                        </button>
                                    )}
                                </div>
                            )}

                            {isActive && s.joined && (
                                <div className="subscription-joined">
                                    {t('Вы в канале', 'You are in the channel')}
                                </div>
                            )}
                        </div>
                    );
                })}
            </div>
        </div>
    );
};
