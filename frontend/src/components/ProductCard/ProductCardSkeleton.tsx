import React from 'react';
import './ProductCard.css';

/**
 * Заглушка карточки на время загрузки.
 *
 * Повторяет структуру настоящей карточки, а не рисует прямоугольник заданной
 * высоты. Прежний скелетон был жёстко 360px, тогда как на телефоне карточка
 * занимает примерно 240px: список подпрыгивал в момент подстановки товаров.
 * Здесь высота складывается из тех же блоков, что и в карточке, и совпадает
 * на любой ширине сама собой.
 */
export const ProductCardSkeleton: React.FC = () => (
    <div className="product-card glass-card product-card-skeleton" aria-hidden="true">
        <div className="product-image skeleton" />

        <div className="product-info">
            <div className="skeleton skeleton-line skeleton-line-title" />
            <div className="skeleton skeleton-line skeleton-line-text" />

            <div className="product-footer">
                <div className="skeleton skeleton-line skeleton-line-price" />
                <div className="skeleton skeleton-line skeleton-line-button" />
            </div>
        </div>
    </div>
);
