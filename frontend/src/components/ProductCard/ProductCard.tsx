import React from 'react';
import { ShoppingCart } from 'lucide-react';
import type { Product } from '@/types';
import { Stars } from '@/components/Stars/Stars';
import { thumb } from '@/lib/image';
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
            {/* Отклик на нажатие — в CSS (:active), а не анимацией
                framer-motion: две такие кнопки на каждой карточке держали
                обработчики жестов на всю сетку и тормозили прокрутку */}
            <button
                type="button"
                className="product-open"
                onClick={onClick}
            >
                <span className="product-image">
                    <img src={thumb(product.image_url)} alt="" loading="lazy" decoding="async" />

                    {/* Без огонька: иконка мельче подписи, на фотографии
                        превращалась в жёлтую кляксу и клиенту не нравилась */}
                    {product.is_top && <span className="product-tag">Хит</span>}

                    {/* Оценка лежит на картинке, а не под названием.
                        Под названием она встречалась не у всех товаров, и
                        карточки в ряду выходили разной высоты: держать под
                        неё пустую строку — дыра над кнопкой, не держать —
                        кнопки вразнобой. На картинке место есть всегда, и
                        текстовый блок у всех карточек одинаковый. */}
                    {rating != null && (
                        <span className="product-score">
                            <Stars value={rating} size={11} />
                            {rating}
                        </span>
                    )}
                </span>

                <span className="product-name">{product.name}</span>
            </button>

            <button
                type="button"
                className="product-buy"
                onClick={handleBuy}
                aria-label={`Добавить «${product.name}» в корзину за $${product.price_usdt}`}
            >
                <ShoppingCart size={16} />
                ${product.price_usdt}
            </button>
        </div>
    );
};
