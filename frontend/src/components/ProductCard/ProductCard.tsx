import React from 'react';
import { motion } from 'framer-motion';
import { Flame, ShoppingCart, Star } from 'lucide-react';
import type { Product } from '@/types';
import './ProductCard.css';

interface ProductCardProps {
    product: Product;
    onClick: () => void;
    onAddToCart: () => void;
}

/**
 * Карточка товара в сетке каталога.
 *
 * Пометки — «хит» и оценка — лежат плашками на картинке, а не строками под
 * ней. Отдельная строка оценки держала высоту и без отзывов, чтобы карточки
 * в ряду совпадали; отзывов на площадке пока нет ни у одного товара, и под
 * каждым названием висела пустая дыра. На картинке плашки просто нет, когда
 * показывать нечего.
 *
 * Цена лежит в кнопке покупки. Так она не стоит отдельной строки, и покупка
 * из сетки вернулась, не прибавив карточке высоты.
 *
 * Две кнопки, а не одна на всю карточку: вложенная кнопка внутри кнопки —
 * невалидная разметка, и клавиатура до внутренней не добирается.
 */
export const ProductCard: React.FC<ProductCardProps> = ({
    product,
    onClick,
    onAddToCart,
}) => {
    const rating = product.rating ?? null;

    const handleBuy = (e: React.MouseEvent) => {
        e.stopPropagation();
        onAddToCart();
    };

    return (
        <div className="product-card">
            {/* Появление карточки задаёт список (Home): здесь была вторая пара
                initial/animate, и карточка выезжала внутри уже выезжающей
                обёртки. */}
            <motion.button
                type="button"
                className="product-open"
                onClick={onClick}
                whileTap={{ scale: 0.98 }}
            >
                <span className="product-image">
                    <img src={product.image_url} alt="" loading="lazy" />

                    {product.is_top && (
                        <span className="product-tag product-tag-top">
                            <Flame size={11} fill="currentColor" />
                            Хит
                        </span>
                    )}

                    {/* Одна звезда и число, а не пять звёзд: пять штук в 12 px
                        сливаются в полоску, а «4.9» читается сразу */}
                    {rating != null && (
                        <span className="product-tag product-tag-rating">
                            <Star size={11} fill="currentColor" className="product-star" />
                            {rating}
                            <span className="product-reviews">· {product.reviews_count}</span>
                        </span>
                    )}
                </span>

                <span className="product-name">{product.name}</span>
            </motion.button>

            <motion.button
                type="button"
                className="product-buy"
                onClick={handleBuy}
                whileTap={{ scale: 0.97 }}
                aria-label={`Добавить «${product.name}» в корзину за $${product.price_usdt}`}
            >
                <ShoppingCart size={16} />
                ${product.price_usdt}
            </motion.button>
        </div>
    );
};
