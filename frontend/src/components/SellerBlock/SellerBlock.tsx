import React from 'react';
import { useNavigate } from 'react-router-dom';
import { BadgeCheck, Check, ChevronRight, MessageCircle, ShieldCheck, Store } from 'lucide-react';
import type { Product } from '@/types';
import { Stars } from '@/components/Stars/Stars';
import { useAuthStore } from '@/store/authStore';
import { pluralRu } from '@/lib/format';
import './SellerBlock.css';

interface SellerBlockProps {
    product: Product;
}

/**
 * Кто продаёт и что защищает покупателя. Стоит после описания — до него
 * человек читает про сам товар, после решает, можно ли доверять продавцу.
 *
 * Заменила короткую строку магазина под названием: два упоминания продавца
 * на одном экране читались как сбой, а короткой строке негде было
 * рассказать про эскроу и чат.
 *
 * Обещания разные, потому что и сделки разные. У товара продавца деньги
 * держит площадка до подтверждения получения, работает спор и открывается
 * чат. У товара самой площадки ничего этого нет — выдача идёт сразу, и
 * писать про эскроу было бы враньём.
 */
export const SellerBlock: React.FC<SellerBlockProps> = ({ product }) => {
    const navigate = useNavigate();
    const { language } = useAuthStore();
    const t = (ru: string, en: string) => (language === 'ru' ? ru : en);

    const {
        author_kind, author_id, author_name, author_avatar,
        author_verified, author_rating, author_reviews,
    } = product;

    if (!author_kind || !author_id || !author_name) return null;

    const path = author_kind === 'channel'
        ? `/store/channel/${author_id}`
        : `/store/seller/${author_id}`;

    const initial = author_name.trim().charAt(0).toUpperCase();
    const reviews = author_reviews ?? 0;

    const reviewWord = (n: number) => (language === 'ru'
        ? pluralRu(n, ['отзыв', 'отзыва', 'отзывов'])
        : (n === 1 ? 'review' : 'reviews'));

    // Товар продавца идёт через эскроу и сделку, товар площадки — нет
    const escrow = product.is_p2p === true;

    // Подписка деньги в эскроу не держит, но и площадкой не продаётся:
    // доступ выдаёт бот, а канал принадлежит автору. Строка «Продаёт сама
    // площадка» здесь была прямым враньём.
    const subscription = product.type === 'subscription';

    const points = escrow
        ? [
            t('Деньги держит площадка до подтверждения получения',
              'The marketplace holds the money until you confirm delivery'),
            t('Возврат средств, если вы не получили товар',
              'Refund if the item never arrives'),
            t('Возврат средств, если товар не соответствует описанию',
              'Refund if the item does not match the description'),
        ]
        : subscription
        ? [
            t('Доступ в канал откроется сразу после оплаты',
              'Channel access opens right after payment'),
            t('Доступ закроется, когда подписка закончится',
              'Access closes when the subscription ends'),
        ]
        : [
            product.type === 'service'
                ? t('Заказ берут в работу сразу после оплаты',
                    'The order is picked up right after payment')
                : t('Выдача сразу после оплаты', 'Delivered right after payment'),
            ...(author_kind === 'platform'
                ? [t('Продаёт сама площадка', 'Sold by the marketplace itself')]
                : []),
        ];

    return (
        <section className="sellerblock">
            <h2 className="sellerblock-title">{t('Продавец', 'Seller')}</h2>

            <button type="button" className="sellerblock-head" onClick={() => navigate(path)}>
                <span className="sellerblock-avatar">
                    {author_avatar
                        ? <img src={author_avatar} alt="" />
                        : <span aria-hidden="true">{initial || <Store size={20} />}</span>}
                </span>

                <span className="sellerblock-ident">
                    <span className="sellerblock-name">
                        {author_name}
                        {author_verified && (
                            <BadgeCheck
                                className="sellerblock-check"
                                size={17}
                                aria-label={t('Проверенный продавец', 'Verified seller')}
                            />
                        )}
                    </span>

                    {/* Пустые звёзды читались бы как нулевая оценка, поэтому
                        строки просто нет, пока отзывов не было */}
                    {author_rating != null && (
                        <span className="sellerblock-rating">
                            <Stars value={author_rating} size={15} />
                            <span className="sellerblock-rating-value">{author_rating}</span>
                            <span className="sellerblock-rating-count">
                                {reviews} {reviewWord(reviews)}
                            </span>
                        </span>
                    )}
                </span>

                <ChevronRight className="sellerblock-arrow" size={18} />
            </button>

            <div className="sellerblock-safe">
                <span className="sellerblock-safe-title">
                    <ShieldCheck size={16} />
                    {t('Безопасная оплата', 'Secure payment')}
                </span>

                <ul className="sellerblock-points">
                    {points.map((point) => (
                        <li key={point}>
                            <Check size={16} aria-hidden="true" />
                            <span>{point}</span>
                        </li>
                    ))}
                </ul>
            </div>

            {/* Чат живёт внутри сделки, а сделка заводится только под товар
                продавца: у товара площадки писать некому */}
            {escrow && (
                <p className="sellerblock-chat">
                    <MessageCircle size={14} aria-hidden="true" />
                    {t('После покупки будет доступен чат с продавцом',
                       'A chat with the seller opens after the purchase')}
                </p>
            )}
        </section>
    );
};
