import React from 'react';
import './ProductCard.css';

/**
 * Заглушка карточки на время загрузки.
 *
 * Повторяет структуру настоящей карточки, а не рисует прямоугольник заданной
 * высоты: иначе список подпрыгивает в момент подстановки товаров. Высота
 * складывается из тех же блоков, что и в карточке.
 */
export const ProductCardSkeleton: React.FC = () => (
    <div className="product-card product-card-skeleton" aria-hidden="true">
        <div className="product-image skeleton" />
        <div className="skeleton skeleton-line skeleton-line-title" />
        <div className="skeleton skeleton-line skeleton-line-buy" />
    </div>
);
