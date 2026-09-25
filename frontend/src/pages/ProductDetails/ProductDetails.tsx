import React, { useEffect, useState, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { ArrowLeft, ShoppingCart, Plus, Minus } from 'lucide-react';
import { productsApi, cartApi, reviewsApi } from '@/api/client';
import { useAuthStore } from '@/store/authStore';
import { useCartStore } from '@/store/cartStore';
import { useTelegram } from '@/hooks/useTelegram';
import { useWebSocket } from '@/hooks/useWebSocket';
import type { Product, Review } from '@/types';
import { StoreLine } from '@/components/StoreLine/StoreLine';
import { Stars } from '@/components/Stars/Stars';
import { useToastStore, errorText } from '@/store/toastStore';
import './ProductDetails.css';

export const ProductDetails: React.FC = () => {
    const { id } = useParams<{ id: string }>();
    const navigate = useNavigate();
    const { language } = useAuthStore();
    const { setCart } = useCartStore();
    const { haptic } = useTelegram();
    const showToast = useToastStore((state) => state.show);

    const [product, setProduct] = useState<Product | null>(null);
    const [isLoading, setIsLoading] = useState(true);
    const [reviews, setReviews] = useState<Review[]>([]);
    const [isReviewsExpanded, setIsReviewsExpanded] = useState(false);
    const [isLoadingReviews, setIsLoadingReviews] = useState(false);
    const [hasMoreReviews, setHasMoreReviews] = useState(true);
    const [reviewsSkip, setReviewsSkip] = useState(0);
    const reviewsLimit = 5;

    const reviewsRef = useRef<HTMLDivElement>(null);
    const [serviceInput, setServiceInput] = useState('');
    const [inputError, setInputError] = useState(false);
    const [quantity, setQuantity] = useState(1);

    useWebSocket((message) => {
        if (!id) return;

        if (message.type === 'product_updated' && message.data.id === id) {
            setProduct(message.data);
        } else if (message.type === 'product_deleted' && message.data.id === id) {
            setProduct(null);
        }
    });

    useEffect(() => {
        if (product) {
            const min = product.min_quantity || 1;
            setQuantity(prev => Math.max(prev, min));
        }
    }, [product]);

    useEffect(() => {
        if (id) {
            loadProduct(id);
            fetchInitialReviews(id);
        }
    }, [id]);

    const loadProduct = async (productId: string) => {
        try {
            setIsLoading(true);
            const data = await productsApi.getProduct(productId, language);
            setProduct(data);
        } catch (error) {
            console.error('Failed to load product:', error);
        } finally {
            setIsLoading(false);
        }
    };

    const fetchInitialReviews = async (productId: string) => {
        try {
            setIsLoadingReviews(true);
            const data = await reviewsApi.getReviews(productId, 0, 10);

            if (data && data.length > 0) {
                setReviews(data);
                setReviewsSkip(data.length);
                setHasMoreReviews(data.length >= 10);
            } else {
                setReviews([]);
                setHasMoreReviews(false);
            }
        } catch (error) {
            console.error('Failed to load reviews:', error);
            setReviews([]);
            setHasMoreReviews(false);
        } finally {
            setIsLoadingReviews(false);
        }
    };

    const fetchMoreReviews = async () => {
        if (!id || isLoadingReviews || !hasMoreReviews) return;

        try {
            setIsLoadingReviews(true);
            const data = await reviewsApi.getReviews(id, reviewsSkip, reviewsLimit);
            setReviews(prev => [...prev, ...data]);
            setReviewsSkip(prev => prev + data.length);
            setHasMoreReviews(data.length >= reviewsLimit);
        } catch (error) {
            console.error('Failed to fetch more reviews:', error);
        } finally {
            setIsLoadingReviews(false);
        }
    };

    const handleScroll = (e: React.UIEvent<HTMLDivElement>) => {
        if (!isReviewsExpanded) return;

        const target = e.currentTarget;
        const reachedBottom = target.scrollHeight - target.scrollTop <= target.clientHeight + 100;

        if (reachedBottom && hasMoreReviews && !isLoadingReviews) {
            fetchMoreReviews();
        }
    };

    const toggleReviews = () => {
        const nextState = !isReviewsExpanded;
        setIsReviewsExpanded(nextState);
        haptic.impact('light');

        if (nextState) {
            // Wait a bit more for the expansion animation to start
            setTimeout(() => {
                reviewsRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
            }, 150);
        } else {
            // Smooth scroll back up when hiding
            reviewsRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
    };

    const handleBadgeClick = () => {
        haptic.impact('light');
        // Always scroll to reviews on badge click, but don't expand
        reviewsRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    };

    const handleAddToCart = async () => {
        if (!product) return;

        // Validation for service type products
        if (product.type === 'service') {
            if (!serviceInput.trim()) {
                setInputError(true);
                haptic.notification('error');
                const inputElement = document.getElementById('service-input');
                inputElement?.scrollIntoView({ behavior: 'smooth', block: 'center' });
                inputElement?.focus();
                return;
            }
        }

        // Validate Quantity Locally
        const min = product.min_quantity || 1;
        const max = product.max_quantity || 999999;

        let finalQuantity = quantity;
        if (finalQuantity < min) finalQuantity = min;
        if (finalQuantity > max) finalQuantity = max;

        console.log(`Adding to cart: ${product.name} (ID: ${product.id}), Quantity: ${finalQuantity}, Min: ${min}, Max: ${max}`);

        try {
            haptic.impact('light');
            const userData = product.type === 'service' ? { link: serviceInput } : undefined;

            await cartApi.addToCart(product.id, finalQuantity, userData);

            const cart = await cartApi.getCart(language);
            setCart(cart);
            haptic.notification('success');
            navigate('/cart');
        } catch (error) {
            // Был window.alert с техническим текстом вроде «Error: Not
            // authenticated»: системное окно поверх Mini App выглядит
            // чужеродно и ничего человеку не объясняет. В каталоге это уже
            // исправлено, здесь окно оставалось.
            console.error('Failed to add to cart:', error);
            haptic.notification('error');
            showToast(errorText(error, language === 'ru'
                ? 'Не удалось добавить в корзину'
                : 'Failed to add to cart'), 'error');
        }
    };

    const handleQuantityChange = (delta: number) => {
        if (!product) return;
        const newQuantity = quantity + delta;
        const min = product.min_quantity || 1;
        const max = product.max_quantity || 999999;

        if (newQuantity >= min && newQuantity <= max) {
            setQuantity(newQuantity);
            haptic.impact('light');
        }
    };

    if (isLoading) {
        return (
            <div className="product-details-page">
                <div className="skeleton details-skeleton-image" />
                <div className="container details-skeleton-body">
                    <div className="skeleton details-skeleton-title" />
                    <div className="skeleton details-skeleton-price" />
                    <div className="skeleton details-skeleton-text" />
                    <div className="skeleton details-skeleton-button" />
                </div>
            </div>
        );
    }

    if (!product) {
        return (
            <div className="product-details-page">
                <div className="container">
                    <p>{language === 'ru' ? 'Товар не найден' : 'Product not found'}</p>
                    <button className="btn-back" onClick={() => navigate(-1)}>
                        {language === 'ru' ? 'Вернуться назад' : 'Go back'}
                    </button>
                </div>
            </div>
        );
    }

    // Оценку считает сервер по всем отзывам сразу. Раньше она усреднялась
    // по загруженной первой странице: у товара с сорока отзывами на экране
    // стояло среднее первых пяти, и оно менялось по мере пролистывания.
    const rating = product.rating ?? null;
    const reviewsCount = product.reviews_count ?? 0;

    const reviewWord = (n: number) => {
        if (language !== 'ru') return n === 1 ? 'review' : 'reviews';
        const tail = n % 10;
        const hundred = n % 100;
        if (tail === 1 && hundred !== 11) return 'отзыв';
        if (tail >= 2 && tail <= 4 && (hundred < 12 || hundred > 14)) return 'отзыва';
        return 'отзывов';
    };

    // Столько же, сколько уйдёт в корзину: handleAddToCart зажимает
    // количество теми же границами
    const chargedQuantity = Math.min(
        Math.max(quantity, product.min_quantity || 1),
        product.max_quantity || 999999,
    );
    const total = (product.price_usdt * chargedQuantity).toFixed(2);

    return (
        <motion.div
            className="product-details-page"
            onScroll={handleScroll}
        >
            <button className="back-button" onClick={() => navigate(-1)}>
                <ArrowLeft size={24} />
            </button>

            <motion.div
                className="product-hero"
                initial={{ y: -20, opacity: 0 }}
                animate={{ y: 0, opacity: 1 }}
                transition={{ delay: 0.1, duration: 0.4 }}
            >
                <img src={product.image_url} alt={product.name} />
                {/* Плашка на картинке — как на карточке в каталоге. Раньше
                    это был градиентный кружок с огоньком и без подписи: что
                    он означает, понять было неоткуда. */}
                {product.is_top && <span className="product-tag-hero">Хит</span>}
                <div className="hero-gradient" />
            </motion.div>

            <motion.div
                className="container product-content"
                initial={{ y: 20, opacity: 0 }}
                animate={{ y: 0, opacity: 1 }}
                transition={{ delay: 0.2, duration: 0.4 }}
            >
                <div className="product-header">
                    <h1>{product.name}</h1>

                    {/* Чей это товар и переход в его магазин.
                        Именно здесь, а не в сетке каталога: там магазин
                        перетягивал внимание с самого товара. */}
                    <StoreLine product={product} />

                    {product.is_active === false && (
                        <div className="product-unavailable">
                            {language === 'ru'
                                ? 'Товар снят с продажи'
                                : 'This item is no longer for sale'}
                        </div>
                    )}

                    {/* Цена и оценка одной строкой. Раньше цена стояла
                        отдельным блоком, а внизу её же показывала панель
                        покупки — один и тот же доллар встречался трижды. */}
                    <div className="product-facts">
                        <span className="price-large">${product.price_usdt}</span>

                        {rating != null && (
                            <button
                                type="button"
                                className="rating-link"
                                onClick={handleBadgeClick}
                            >
                                <Stars value={rating} size={14} />
                                <span className="rating-value">{rating}</span>
                                <span className="rating-count">
                                    {reviewsCount} {reviewWord(reviewsCount)}
                                </span>
                            </button>
                        )}
                    </div>
                </div>

                <div className="product-description-block">
                    <h3>{language === 'ru' ? 'Описание' : 'Description'}</h3>
                    <DescriptionText text={product.description} language={language} />
                </div>

                {product.type === 'service' && (
                    <div className="service-details-block">
                        <div className="service-input-block">
                            <label className="service-label">
                                {language === 'ru' ? 'Ссылка на аккаунт/пост' : 'Link to account/post'}
                                <span className="required">*</span>
                            </label>
                            <input
                                id="service-input"
                                type="text"
                                className={`service-input ${inputError ? 'error' : ''}`}
                                placeholder={language === 'ru' ? 'https://...' : 'https://...'}
                                value={serviceInput}
                                onChange={(e) => {
                                    setServiceInput(e.target.value);
                                    setInputError(false);
                                }}
                            />
                            {inputError && (
                                <p className="error-message">
                                    {language === 'ru' ? 'Это поле обязательно' : 'This field is required'}
                                </p>
                            )}
                        </div>

                        <div className="quantity-selector">
                            <span className="quantity-label">
                                {language === 'ru' ? 'Количество' : 'Quantity'}
                                {product.min_quantity && ` (min: ${product.min_quantity})`}
                            </span>
                            <div className="quantity-controls">
                                <button
                                    className="btn-quantity"
                                    onClick={() => handleQuantityChange(-1)}
                                    disabled={quantity <= (product.min_quantity || 1)}
                                >
                                    <Minus size={20} />
                                </button>
                                <span className="quantity-value">{quantity}</span>
                                <button
                                    className="btn-quantity"
                                    onClick={() => handleQuantityChange(1)}
                                    disabled={!!product.max_quantity && quantity >= product.max_quantity}
                                >
                                    <Plus size={20} />
                                </button>
                            </div>
                        </div>
                    </div>
                )}

                <div className="product-reviews-block" ref={reviewsRef}>
                    <div className="reviews-header">
                        <h3>{language === 'ru' ? 'Отзывы' : 'Reviews'}</h3>
                        {!isReviewsExpanded && reviews.length > 2 && (
                            <button className="btn-text" onClick={toggleReviews}>
                                {language === 'ru' ? 'Показать все' : 'Show all'}
                            </button>
                        )}
                    </div>

                    <div className="reviews-list">
                        {/* Static: First 2 reviews are always rendered simply to avoid jumping */}
                        {reviews.slice(0, 2).map((review) => (
                            <div key={review.id} className="review-card glass-card">
                                <div className="review-header">
                                    <div className="review-user">
                                        <div className="user-avatar-small">
                                            {(review.fake_username || review.user?.first_name || 'U').charAt(0).toUpperCase()}
                                        </div>
                                        <span className="user-name">{review.fake_username || review.user?.first_name || 'User'}</span>
                                    </div>
                                    <Stars value={review.rating || 0} size={12} />
                                </div>
                                <p className="review-text">{review.text}</p>
                                <span className="review-date">
                                    {new Date(review.created_at).toLocaleDateString()}
                                </span>
                            </div>
                        ))}

                        {/* Dynamic: Additional reviews with smooth fade + glide */}
                        <AnimatePresence initial={false}>
                            {isReviewsExpanded && reviews.slice(2).map((review, index) => (
                                <motion.div
                                    key={review.id}
                                    className="review-card glass-card review-item"
                                    initial={{ opacity: 0, y: -10 }}
                                    animate={{
                                        opacity: 1,
                                        y: 0,
                                        transition: {
                                            duration: 0.4,
                                            ease: "easeOut",
                                            delay: index * 0.05
                                        }
                                    }}
                                    exit={{
                                        opacity: 0,
                                        transition: { duration: 0.2 }
                                    }}
                                >
                                    <div className="review-header">
                                        <div className="review-user">
                                            <div className="user-avatar-small">
                                                {(review.fake_username || review.user?.first_name || 'U').charAt(0).toUpperCase()}
                                            </div>
                                            <span className="user-name">{review.fake_username || review.user?.first_name || 'User'}</span>
                                        </div>
                                        <Stars value={review.rating || 0} size={12} />
                                    </div>
                                    <p className="review-text">{review.text}</p>
                                    <span className="review-date">
                                        {new Date(review.created_at).toLocaleDateString()}
                                    </span>
                                </motion.div>
                            ))}
                        </AnimatePresence>

                        {isLoadingReviews && (
                            <div className="reviews-skeleton">
                                {[1, 2].map(i => (
                                    <div key={i} className="review-card-skeleton shimmer" />
                                ))}
                            </div>
                        )}

                        {isReviewsExpanded && reviews.length > 0 && (
                            <div className="reviews-actions">
                                {hasMoreReviews ? (
                                    <>
                                        <button className="btn-load-more" onClick={fetchMoreReviews} disabled={isLoadingReviews}>
                                            {language === 'ru' ? 'Загрузить еще' : 'Load more'}
                                        </button>
                                        <button className="btn-hide-reviews" onClick={toggleReviews}>
                                            {language === 'ru' ? 'Скрыть отзывы' : 'Hide reviews'}
                                        </button>
                                    </>
                                ) : (
                                    <button className="btn-hide-reviews" onClick={toggleReviews}>
                                        {language === 'ru' ? 'Скрыть отзывы' : 'Hide reviews'}
                                    </button>
                                )}
                            </div>
                        )}
                    </div>
                </div>

                {/* Spacer to allow scrolling past fixed action bar */}
                <div className="bottom-content-spacer" />
            </motion.div>

            {/* Одна кнопка во всю ширину, цена внутри неё. Подпись «Total:»
                рядом врала: там стояла цена за штуку, а у услуги с
                количеством к оплате уходило другое число. */}
            <div className="action-bar">
                <motion.button
                    className="btn-add-to-cart"
                    onClick={handleAddToCart}
                    whileTap={{ scale: 0.97 }}
                    /* Снятый с продажи товар открывается по старой ссылке, но
                       корзина его всё равно не примет — кнопку гасим здесь,
                       чтобы человек не упирался в ошибку после нажатия */
                    disabled={product.is_active === false}
                >
                    <ShoppingCart size={20} />
                    {language === 'ru' ? 'В корзину' : 'Add to cart'} · ${total}
                </motion.button>
            </div>
        </motion.div>
    );
};

const DescriptionText: React.FC<{ text: string | undefined; language: string }> = ({ text, language }) => {
    const [isExpanded, setIsExpanded] = useState(false);
    const maxLength = 150;

    if (!text) return null;

    if (text.length <= maxLength) {
        return <p>{text}</p>;
    }

    return (
        <div className="description-text">
            <p>
                {isExpanded ? text : `${text.slice(0, maxLength)}...`}
            </p>
            <button
                className="btn-toggle-description"
                onClick={() => setIsExpanded(!isExpanded)}
            >
                {isExpanded
                    ? (language === 'ru' ? 'Скрыть описание' : 'Hide description')
                    : (language === 'ru' ? 'Показать полностью' : 'Show more')}
            </button>
        </div>
    );
};
