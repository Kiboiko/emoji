import React from 'react';
import { BadgeCheck, ShoppingCart } from 'lucide-react';
import type { Product } from '@/types';
import { Stars } from '@/components/Stars/Stars';
import { thumb } from '@/lib/image';
import './ProductRow.css';

interface ProductRowProps {
    product: Product;
    onClick: () => void;
    onAddToCart: () => void;
}

/**
 * Товар строкой — вид каталога «список».
 *
 * На экран помещается вдвое больше товаров, чем в сетке, и у каждого видно
 * магазин. В сетке места под подпись продавца нет — она перетягивала внимание
 * с самого товара, — а при десятке продавцов «чьё это» спрашивают первым.
 *
 * Две кнопки, а не одна: вложенная кнопка внутри кнопки — невалидная
 * разметка, и клавиатура до внутренней не добирается.
 */
export const ProductRow: React.FC<ProductRowProps> = ({
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
        <div className="product-row">
            {/* Отклик на нажатие — в CSS (:active), как в карточке сетки */}
            <button
                type="button"
                className="product-row-open"
                onClick={onClick}
            >
                <span className="product-row-image">
                    <img src={thumb(product.image_url)} alt="" loading="lazy" decoding="async" />
                    {product.is_top && <span className="product-row-tag">Хит</span>}
                </span>

                <span className="product-row-body">
                    <span className="product-row-name">{product.name}</span>

                    {product.author_name && (
                        <span className="product-row-store">
                            <span className="product-row-store-name">{product.author_name}</span>
                            {product.author_verified && (
                                <BadgeCheck className="product-row-check" size={13} />
                            )}
                        </span>
                    )}

                    {rating != null && (
                        <span className="product-row-rating">
                            <Stars value={rating} size={12} />
                            <span>{rating}</span>
                            <span className="product-row-reviews">· {product.reviews_count}</span>
                        </span>
                    )}
                </span>
            </button>

            <div className="product-row-side">
                <span className="product-row-price">${product.price_usdt}</span>
                <button
                    type="button"
                    className="product-row-cart"
                    onClick={handleBuy}
                    aria-label={`Добавить «${product.name}» в корзину за $${product.price_usdt}`}
                >
                    <ShoppingCart size={17} />
                </button>
            </div>
        </div>
    );
};

export const ProductRowSkeleton: React.FC = () => (
    <div className="product-row product-row-skeleton">
        <div className="skeleton product-row-image" />
        <div className="product-row-body">
            <div className="skeleton skeleton-line product-row-line" />
            <div className="skeleton skeleton-line product-row-line short" />
        </div>
    </div>
);
