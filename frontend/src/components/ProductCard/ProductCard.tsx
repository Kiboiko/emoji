import React from 'react';
import { motion } from 'framer-motion';
import { ShoppingCart, Flame, User, Star } from 'lucide-react';
import type { Product } from '@/types';
import './ProductCard.css';

interface ProductCardProps {
    product: Product;
    onClick: () => void;
    onAddToCart: () => void;
}

export const ProductCard: React.FC<ProductCardProps> = ({
    product,
    onClick,
    onAddToCart,
}) => {
    const handleAddToCart = (e: React.MouseEvent) => {
        e.stopPropagation();
        onAddToCart();
    };

    return (
        // Появление карточки задаёт список (Home): здесь была вторая пара
        // initial/animate, и карточка выезжала внутри уже выезжающей обёртки.
        <motion.div
            className="product-card glass-card"
            onClick={onClick}
            whileHover={{ y: -4 }}
            whileTap={{ scale: 0.98 }}
        >
            {product.is_top && (
                <div className="product-badge badge-primary">
                    <Flame size={14} fill="currentColor" />
                </div>
            )}

            <div className="product-image">
                <img
                    src={product.image_url}
                    alt={product.name}
                    loading="lazy"
                />
            </div>

            <div className="product-info">
                {/* Покупатель должен сразу видеть, что товар не от площадки:
                    оплата уходит в escrow и есть срок подтверждения */}
                {product.is_p2p && (
                    <div className="p2p-tag">
                        <User size={12} />
                        <span>{product.seller_name || 'Товар пользователя'}</span>
                        {product.seller_rating != null && (
                            <span className="p2p-rating">
                                <Star size={11} fill="currentColor" />
                                {product.seller_rating}
                            </span>
                        )}
                    </div>
                )}

                <h3 className="product-name">{product.name}</h3>
                <p className="product-description">{product.description}</p>

                <div className="product-footer">
                    <div className="product-price">
                        <span className="price-main">${product.price_usdt}</span>
                    </div>

                    <motion.button
                        className="btn-add-cart"
                        onClick={handleAddToCart}
                        whileHover={{ scale: 1.05 }}
                        whileTap={{ scale: 0.95 }}
                    >
                        <ShoppingCart size={20} />
                    </motion.button>
                </div>
            </div>
        </motion.div>
    );
};
