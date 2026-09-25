import React, { useCallback, useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { ArrowLeft, BadgeCheck, Link2, Store as StoreIcon, Users } from 'lucide-react';
import { cartApi, storesApi } from '@/api/client';
import { useAuthStore } from '@/store/authStore';
import { useCartStore } from '@/store/cartStore';
import { useToastStore, errorText } from '@/store/toastStore';
import { useTelegram } from '@/hooks/useTelegram';
import { ProductCard } from '@/components/ProductCard/ProductCard';
import { Stars } from '@/components/Stars/Stars';
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
    const { setCart } = useCartStore();
    const { haptic } = useTelegram();
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

    const addToCart = async (product: StoreData['products'][number]) => {
        // Услуге нужна ссылка на аккаунт или пост, а её спрашивают на
        // странице товара — как и в каталоге
        if (product.type === 'service') {
            haptic.impact('light');
            navigate(`/product/${product.id}`);
            return;
        }

        try {
            haptic.impact('light');
            await cartApi.addToCart(product.id, product.min_quantity || 1);
            setCart(await cartApi.getCart(language));
            haptic.notification('success');
        } catch (e) {
            haptic.notification('error');
            showToast(errorText(e, t('Не удалось добавить в корзину', 'Failed to add to cart')), 'error');
        }
    };

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
                                    <Stars value={store.rating} size={13} />
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
                        {/* Тот же компонент, что и в каталоге. Своя вёрстка
                            здесь уже однажды разошлась с каталожной: там появились
                            оценка и кнопка покупки, а тут осталась старая. */}
                        {store.products.map((product) => (
                            <ProductCard
                                key={product.id}
                                product={product}
                                onClick={() => navigate(`/product/${product.id}`)}
                                onAddToCart={() => addToCart(product)}
                            />
                        ))}
                    </div>
                )}
            </div>

            <div className="store-bottom-spacer" />
        </div>
    );
};
