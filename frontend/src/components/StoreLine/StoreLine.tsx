import React from 'react';
import { useNavigate } from 'react-router-dom';
import { BadgeCheck, ChevronRight, Store } from 'lucide-react';
import type { Product } from '@/types';
import { Stars } from '@/components/Stars/Stars';
import './StoreLine.css';

interface StoreLineProps {
    product: Product;
}

/**
 * Магазин товара — строка на странице товара с переходом на его витрину.
 *
 * Заменила подпись автора в сетке каталога: там она перетягивала внимание с
 * самого товара. Здесь у неё есть место и смысл — отсюда можно посмотреть
 * все товары того же продавца.
 *
 * Три вида продавца и одна строка на всех: пользователь, канал и сама
 * площадка. Раньше у площадки лица не было вовсе — товар приходил «ничей».
 */
export const StoreLine: React.FC<StoreLineProps> = ({ product }) => {
    const navigate = useNavigate();
    const {
        author_kind, author_id, author_name, author_avatar,
        author_verified, author_rating, author_deals,
    } = product;

    if (!author_kind || !author_id || !author_name) return null;

    // У площадки своя строка в seller_profiles, поэтому адрес у неё такой же,
    // как у обычного продавца
    const path = author_kind === 'channel'
        ? `/store/channel/${author_id}`
        : `/store/seller/${author_id}`;

    const initial = author_name.trim().charAt(0).toUpperCase();

    return (
        <button className="storeline" onClick={() => navigate(path)}>
            <span className="storeline-avatar">
                {author_avatar
                    ? <img src={author_avatar} alt="" />
                    : <span aria-hidden="true">{initial || <Store size={14} />}</span>}
            </span>

            <span className="storeline-body">
                <span className="storeline-name">
                    {author_name}
                    {author_verified && (
                        <BadgeCheck
                            className="storeline-check"
                            size={15}
                            aria-label="Проверенный продавец"
                        />
                    )}
                </span>

                {/* Показываем только посчитанное: у канала рейтинга нет, и
                    пустые звёзды выглядели бы как нулевая оценка */}
                {(author_rating != null || !!author_deals) && (
                    <span className="storeline-stats">
                        {author_rating != null && (
                            <span className="storeline-rating">
                                <Stars value={author_rating} size={11} />
                                {author_rating}
                            </span>
                        )}
                        {!!author_deals && <span>{author_deals} сделок</span>}
                    </span>
                )}
            </span>

            <ChevronRight className="storeline-arrow" size={18} />
        </button>
    );
};
