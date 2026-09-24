import React from 'react';
import { motion } from 'framer-motion';
import { Flame, Star } from 'lucide-react';
import type { Product } from '@/types';
import './ProductCard.css';

interface ProductCardProps {
    product: Product;
    onClick: () => void;
}

/**
 * Карточка товара в сетке каталога.
 *
 * Порядок чтения — цена, название, оценка: сначала «сколько», потом «что».
 * Для витрины с однотипными товарами, где выбирают по цене, так честнее.
 *
 * Подложки и рамки у карточки нет: рисунок лежит прямо на фоне страницы,
 * разделяет карточки воздух. Вместе с убранным описанием и кнопкой корзины
 * это сняло 64 px высоты — карточка стала 216 против 280, а картинка при
 * этом шире. Покупка переехала на страницу товара.
 */
export const ProductCard: React.FC<ProductCardProps> = ({ product, onClick }) => {
    const rating = product.rating ?? null;
    // Округляем до целого только для заливки звёзд: само число показываем
    // как есть, иначе 4.4 и 4.6 выглядели бы одинаково
    const filled = rating != null ? Math.round(rating) : 0;

    return (
        // Появление карточки задаёт список (Home): здесь была вторая пара
        // initial/animate, и карточка выезжала внутри уже выезжающей обёртки.
        <motion.button
            type="button"
            className="product-card"
            onClick={onClick}
            whileTap={{ scale: 0.98 }}
        >
            <div className="product-image">
                <img
                    src={product.image_url}
                    alt={product.name}
                    loading="lazy"
                />

                {product.is_top && (
                    <span className="product-badge" aria-label="Хит продаж">
                        <Flame size={13} fill="currentColor" />
                    </span>
                )}
            </div>

            <span className="product-price">${product.price_usdt}</span>

            <span className="product-name">{product.name}</span>

            {/* Строка держит высоту и без отзывов: иначе соседние карточки в
                ряду встают на разную высоту и сетка выглядит сломанной */}
            <span className="product-rating">
                {rating != null && (
                    <>
                        <span className="product-stars">
                            {[1, 2, 3, 4, 5].map((star) => (
                                <Star
                                    key={star}
                                    size={12}
                                    fill={star <= filled ? 'currentColor' : 'none'}
                                    className={star <= filled ? '' : 'star-empty'}
                                />
                            ))}
                        </span>
                        <span className="product-reviews">{product.reviews_count}</span>
                    </>
                )}
            </span>
        </motion.button>
    );
};
