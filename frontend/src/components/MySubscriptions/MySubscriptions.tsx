import React, { useCallback, useEffect, useState } from 'react';
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
    const [failed, setFailed] = useState(false);
    const [reissuing, setReissuing] = useState<string | null>(null);

    const t = (ru: string, en: string) => (language === 'ru' ? ru : en);

    const load = useCallback(async () => {
        setLoading(true);
        setFailed(false);
        try {
            setItems(await subscriptionsApi.getMySubscriptions());
        } catch {
            setFailed(true);
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        void load();
    }, [load]);

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

    if (loading) return <p role="status">{t('Загружаем подписки…', 'Loading subscriptions…')}</p>;

    if (failed) return (
        <div className="subscriptions-section glass-card" role="alert">
            <p>{t('Не удалось загрузить подписки. Проверьте соединение и повторите попытку.', 'Could not load subscriptions. Check your connection and try again.')}</p>
            <button className="subscription-btn" type="button" onClick={() => void load()}>
                <RefreshCw size={14} />{t('Повторить', 'Retry')}
            </button>
        </div>
    );

    if (items.length === 0) return (
        <p className="subscriptions-section glass-card">
            {t('У вас пока нет подписок. После покупки доступа в канал они появятся здесь.', 'You have no subscriptions yet. They will appear here after you purchase access to a channel.')}
        </p>
    );

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
