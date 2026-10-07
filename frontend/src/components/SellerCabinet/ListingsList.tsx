import React, { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { Package, Pencil, Plus, Search } from 'lucide-react';
import type { Listing } from '@/types';
import './ListingsList.css';

type T = (ru: string, en: string) => string;
type Filter = 'all' | 'live' | 'review' | 'drafts' | 'off';

/** Ярлык объявления: модерация и продажа вместе, как их понимает продавец */
export function listingBadge(listing: Listing, t: T): { label: string; tone: string } {
    if (listing.status === 'approved') {
        // «Одобрено» висело и на проданной вещи: продавец видел «В продаже»,
        // а в каталоге товара уже не было
        if (listing.stock === 0 && listing.reserved > 0) return { label: t('Ждёт оплаты', 'Awaiting payment'), tone: 'dispute' };
        if (listing.stock === 0) return { label: t('Всё продано', 'Sold out'), tone: 'muted' };
        return { label: t('В продаже', 'On sale'), tone: 'done' };
    }
    const labels: Record<string, [string, string]> = {
        pending: [t('На модерации', 'In review'), 'dispute'],
        rejected: [t('Отклонено', 'Rejected'), 'danger'],
        draft: [t('Черновик', 'Draft'), 'muted'],
        withdrawn: [t('Снято с продажи', 'Unlisted'), 'muted'],
        archived: [t('В архиве', 'Archived'), 'muted'],
    };
    const [label, tone] = labels[listing.status] ?? [listing.status, 'muted'];
    return { label, tone };
}

const FILTER_OF: Record<string, Filter> = {
    approved: 'live', pending: 'review', draft: 'drafts', rejected: 'drafts', withdrawn: 'off',
};

/**
 * Мои объявления: короткий список, удобный и при сотне товаров.
 *
 * Раньше каждое объявление было развёрнутой карточкой с фото, кнопками и
 * формой правки прямо в списке — при десятке товаров это превращалось в
 * простыню. Теперь строка: фото, название, цена, остаток, статус и кнопка
 * правки, а всё остальное — на странице объявления.
 */
export const ListingsList: React.FC<{
    listings: Listing[];
    language: string;
    blocked: boolean;
}> = ({ listings, language, blocked }) => {
    const [filter, setFilter] = useState<Filter>('all');
    const [query, setQuery] = useState('');
    const t: T = (ru, en) => (language === 'ru' ? ru : en);

    const visible = useMemo(
        () => listings.filter((l) => l.status !== 'archived'),
        [listings],
    );

    const counts = useMemo(() => {
        const result: Record<Filter, number> = { all: visible.length, live: 0, review: 0, drafts: 0, off: 0 };
        visible.forEach((l) => {
            const f = FILTER_OF[l.status];
            if (f) result[f] += 1;
        });
        return result;
    }, [visible]);

    const rows = visible
        .filter((l) => filter === 'all' || FILTER_OF[l.status] === filter)
        .filter((l) => {
            const q = query.trim().toLowerCase();
            return !q || l.name.toLowerCase().includes(q) || (l.name_en ?? '').toLowerCase().includes(q);
        });

    const filters: [Filter, string][] = [
        ['all', t('Все', 'All')],
        ['live', t('В продаже', 'On sale')],
        ['review', t('На модерации', 'In review')],
        ['drafts', t('Черновики', 'Drafts')],
        ['off', t('Сняты', 'Unlisted')],
    ];

    return (
        <div className="llist">
            <div className="llist-head">
                <h3>{t('Мои объявления', 'My listings')}</h3>
                {!blocked && (
                    <Link className="llist-new" to="/my/listings/new">
                        <Plus size={16} />
                        {t('Новое', 'New')}
                    </Link>
                )}
            </div>

            {/* Поиск нужен, когда товаров много; на трёх — лишний шум */}
            {visible.length > 5 && (
                <label className="llist-search">
                    <Search size={18} />
                    <input
                        value={query}
                        onChange={(e) => setQuery(e.target.value)}
                        placeholder={t('Поиск по объявлениям', 'Search listings')}
                        aria-label={t('Поиск по объявлениям', 'Search listings')}
                    />
                </label>
            )}

            {visible.length > 0 && (
                <div className="llist-filters">
                    {filters
                        .filter(([id]) => id === 'all' || counts[id] > 0)
                        .map(([id, label]) => (
                            <button
                                key={id}
                                type="button"
                                aria-pressed={filter === id}
                                className={filter === id ? 'is-active' : ''}
                                onClick={() => setFilter(id)}
                            >
                                {label} · {counts[id]}
                            </button>
                        ))}
                </div>
            )}

            {visible.length === 0 ? (
                <p className="llist-empty">
                    {t('Объявлений пока нет. Нажмите «Новое», чтобы выставить товар.', 'No listings yet. Tap «New» to list an item.')}
                </p>
            ) : rows.length === 0 ? (
                <p className="llist-empty">{t('Ничего не нашлось.', 'Nothing found.')}</p>
            ) : (
                <div className="llist-rows">
                    {rows.map((listing) => {
                        const badge = listingBadge(listing, t);
                        const live = listing.status === 'approved' && listing.stock !== null;
                        const stock = live
                            ? (listing.quantity > 1
                                ? t(`${listing.stock} из ${listing.quantity}`, `${listing.stock} of ${listing.quantity}`)
                                : '') + (listing.sold > 0 ? `${listing.quantity > 1 ? ' · ' : ''}${t(`продано ${listing.sold}`, `${listing.sold} sold`)}` : '')
                            : listing.quantity > 1 ? `${listing.quantity} ${t('шт.', 'pcs')}` : '';
                        const dim = listing.status === 'withdrawn' || (live && listing.stock === 0 && !listing.reserved);
                        return (
                            <div key={listing.id} className={`llist-row${dim ? ' is-dim' : ''}`}>
                                <Link className="llist-row-main" to={`/my/listings/${listing.id}`}>
                                    <span className="llist-thumb">
                                        {listing.images[0]
                                            ? <img src={listing.images[0].url} alt="" loading="lazy" />
                                            : <Package size={22} />}
                                    </span>
                                    <span className="llist-text">
                                        <span className="llist-name">{(language === 'en' && listing.name_en) || listing.name}</span>
                                        <span className="llist-price">
                                            ${Number(listing.price_usd).toFixed(2).replace(/\.00$/, '')}
                                        </span>
                                        <span className="llist-meta">
                                            <span className={`dchat-chip ${badge.tone}`}>{badge.label}</span>
                                            <span className="llist-meta-text">
                                                {listing.status === 'rejected' && listing.moderation_comment
                                                    ? listing.moderation_comment
                                                    : stock}
                                            </span>
                                        </span>
                                    </span>
                                </Link>
                                <Link
                                    className="llist-edit"
                                    to={`/my/listings/${listing.id}`}
                                    aria-label={t('Редактировать', 'Edit')}
                                >
                                    <Pencil size={18} />
                                </Link>
                            </div>
                        );
                    })}
                </div>
            )}
        </div>
    );
};
