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
 * Карточка товара. Одна и та же в каталоге и на витрине магазина — иначе
 * экраны расходятся, что уже однажды случилось.
 *
 * «Хит» лежит плашкой на картинке, оценка — плашкой под названием. Строка
 * оценки высоту не держит: у товара без отзывов её просто нет, а кнопка
 * покупки всё равно стоит вровень с соседней, потому что прижата к низу
 * карточки, а карточки в ряду сетка растягивает до одной высоты.
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
                        <span className="product-tag">
                            <Flame size={11} fill="currentColor" />
                            Хит
                        </span>
                    )}
                </span>

                <span className="product-name">{product.name}</span>

                {/* Одна звезда и число, а не пять звёзд: пять штук в 12 px
                    сливаются в полоску, а «4.9» читается сразу */}
                {rating != null && (
                    <span className="product-rating">
                        <Star size={12} fill="currentColor" className="product-star" />
                        {rating}
                        <span className="product-reviews">· {product.reviews_count}</span>
                    </span>
                )}
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
