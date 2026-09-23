import React from 'react';
import { BadgeCheck, Radio, Star, Store } from 'lucide-react';
import type { Product } from '@/types';
import './AuthorTag.css';

interface AuthorTagProps {
    product: Product;
    /** В карточке товара строка крупнее: там есть место, и автор там важнее */
    size?: 'sm' | 'md';
}

/**
 * Кто стоит за товаром.
 *
 * Раньше здесь была узкая плашка «Товар пользователя» только для P2P, а
 * подписка приходила в витрину вообще без автора — покупатель не видел, в
 * чей канал платит. Теперь строка одна на три источника: продавец, канал и
 * сама площадка (у последней автора нет, и строка не рисуется).
 *
 * Галочку ставит только администратор, поэтому она здесь ничем не
 * обусловлена — просто отражает поле.
 */
export const AuthorTag: React.FC<AuthorTagProps> = ({ product, size = 'sm' }) => {
    const { author_kind, author_name, author_verified, author_rating, author_deals } = product;

    if (!author_kind || !author_name) return null;

    const isChannel = author_kind === 'channel';
    const iconSize = size === 'md' ? 14 : 12;

    // Инициал вместо аватара: своей картинки у продавца нет, а пустой кружок
    // выглядит как не загрузившееся фото.
    const initial = author_name.trim().charAt(0).toUpperCase();

    return (
        <div className={`author-tag author-tag--${size}`}>
            <span className="author-avatar" aria-hidden="true">
                {initial || (isChannel ? <Radio size={iconSize} /> : <Store size={iconSize} />)}
            </span>

            <span className="author-name">{author_name}</span>

            {author_verified && (
                <BadgeCheck
                    className="author-check"
                    size={iconSize + 2}
                    aria-label="Проверенный автор"
                />
            )}

            {author_rating != null && (
                <span className="author-rating">
                    <Star size={iconSize - 1} fill="currentColor" />
                    {author_rating}
                </span>
            )}

            {/* Число сделок показываем только там, где есть место: в сетке
                каталога строка и так упирается в край карточки */}
            {size === 'md' && !isChannel && author_deals ? (
                <span className="author-deals">{author_deals} сделок</span>
            ) : null}
        </div>
    );
};
