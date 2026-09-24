import React, { useCallback, useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { motion } from 'framer-motion';
import { ArrowLeft, BadgeCheck, Link2, Star, Store as StoreIcon, Users } from 'lucide-react';
import { storesApi } from '@/api/client';
import { useAuthStore } from '@/store/authStore';
import { useToastStore, errorText } from '@/store/toastStore';
import type { Store as StoreData } from '@/types';
import './Store.css';

/**
 * Витрина магазина.
 *
 * Один экран на три вида продавца: пользователя, канал и саму площадку.
 * Площадка — такой же магазин, как остальные, поэтому отдельного вида под
 * неё нет: у неё такая же строка в seller_profiles и такой же адрес.
 */
export const Store: React.FC = () => {
    const { kind, id } = useParams<{ kind: string; id: string }>();
    const navigate = useNavigate();
    const { language } = useAuthStore();
    const showToast = useToastStore((s) => s.show);

    const [store, setStore] = useState<StoreData | null>(null);
    const [failed, setFailed] = useState(false);

    const t = (ru: string, en: string) => (language === 'ru' ? ru : en);

    const load = useCallback(async () => {
        if (!id) return;
        try {
            const data = kind === 'channel'
                ? await storesApi.getChannelStore(id, language)
                : await storesApi.getSellerStore(id, language);
            setStore(data);
        } catch (e) {
            setFailed(true);
            showToast(errorText(e, t('Магазин не найден', 'Store not found')), 'error');
        }
    }, [id, kind, language, showToast]);

    useEffect(() => { load(); }, [load]);

    if (failed) {
        return (
            <div className="store-page">
                <div className="container">
                    <button className="btn-back" onClick={() => navigate(-1)}>
                        <ArrowLeft size={20} />
                        <span>{t('Назад', 'Back')}</span>
                    </button>
                    <p className="store-empty">
                        {t('Магазин не найден или снят с публикации.',
                           'This store was not found or is no longer published.')}
                    </p>
                </div>
            </div>
        );
    }

    if (!store) {
        return (
            <div className="store-page">
                <div className="container">
                    <div className="skeleton store-head-skeleton" />
                    <div className="store-grid">
                        {Array.from({ length: 4 }).map((_, i) => (
                            <div key={i} className="skeleton store-card-skeleton" />
                        ))}
                    </div>
                </div>
            </div>
        );
    }

    const initial = store.name.trim().charAt(0).toUpperCase();

    return (
        <div className="store-page">
            <div className="container">
                <button className="btn-back" onClick={() => navigate(-1)}>
                    <ArrowLeft size={20} />
                    <span>{t('Назад', 'Back')}</span>
                </button>

                <section className="store-head glass-card">
                    <div className="store-avatar">
                        {store.avatar_url
                            ? <img src={store.avatar_url} alt="" />
                            : <span aria-hidden="true">{initial || <StoreIcon size={24} />}</span>}
                    </div>

                    <div className="store-ident">
                        <h1 className="store-name">
                            {store.name}
                            {store.is_verified && (
                                <BadgeCheck
                                    className="store-verified"
                                    size={18}
                                    aria-label={t('Проверенный продавец', 'Verified seller')}
                                />
                            )}
                        </h1>

                        {/* Показываем только то, что действительно посчитано.
                            У канала рейтинга нет — отзывы собираются по
                            сделкам, а подписка идёт не через сделку. */}
                        <div className="store-stats">
                            {store.rating != null && (
                                <span className="store-stat">
                                    <Star size={13} fill="currentColor" />
                                    {store.rating}
                                    <span className="store-stat-dim">({store.rating_count})</span>
                                </span>
                            )}
                            {store.deals_completed > 0 && (
                                <span className="store-stat">
                                    {store.deals_completed} {t('сделок', 'deals')}
                                </span>
                            )}
                            {store.subscribers != null && store.subscribers > 0 && (
                                <span className="store-stat">
                                    <Users size={13} />
                                    {store.subscribers}
                                </span>
                            )}
                            {store.link && (
                                <a
                                    className="store-stat store-link"
                                    href={`https://t.me/${store.link}`}
                                    target="_blank"
                                    rel="noreferrer"
                                >
                                    <Link2 size={13} />
                                    @{store.link}
                                </a>
                            )}
                        </div>
                    </div>
                </section>

                {store.description && (
                    <p className="store-description">{store.description}</p>
                )}

                <h2 className="store-section-title">
                    {t('Товары', 'Products')}
                    <span className="store-count">{store.products.length}</span>
                </h2>

                {store.products.length === 0 ? (
                    <p className="store-empty">
                        {t('В этом магазине пока ничего не продаётся.',
                           'Nothing is on sale in this store yet.')}
                    </p>
                ) : (
                    <div className="store-grid">
                        {store.products.map((product) => (
                            <motion.button
                                key={product.id}
                                className="store-card glass-card"
                                onClick={() => navigate(`/product/${product.id}`)}
                                whileTap={{ scale: 0.98 }}
                            >
                                <div className="store-card-image">
                                    <img src={product.image_url} alt={product.name} loading="lazy" />
                                </div>
                                <div className="store-card-body">
                                    <span className="store-card-name">{product.name}</span>
                                    <span className="store-card-price">${product.price_usdt}</span>
                                </div>
                            </motion.button>
                        ))}
                    </div>
                )}
            </div>

            <div className="store-bottom-spacer" />
        </div>
    );
};
