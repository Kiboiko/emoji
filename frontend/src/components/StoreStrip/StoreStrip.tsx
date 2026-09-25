import React from 'react';
import { useNavigate } from 'react-router-dom';
import { Check } from 'lucide-react';
import type { StoreCard } from '@/types';
import './StoreStrip.css';

interface StoreStripProps {
    stores: StoreCard[];
}

/**
 * Строка магазинов на главной.
 *
 * Товар теперь принадлежит магазину, но попасть в магазин можно было только
 * через карточку товара — то есть сначала выбрать вещь и лишь потом узнать,
 * кто её продаёт. Здесь порядок обратный: сначала продавец.
 *
 * Логотип грузит сам продавец, поэтому пока его нет — буква названия.
 * Пустой кружок читается как не загрузившаяся картинка.
 */
export const StoreStrip: React.FC<StoreStripProps> = ({ stores }) => {
    const navigate = useNavigate();

    const open = (store: StoreCard) => {
        navigate(store.kind === 'channel'
            ? `/store/channel/${store.id}`
            : `/store/seller/${store.id}`);
    };

    return (
        <div className="storestrip">
            {stores.map((store) => (
                <button
                    key={`${store.kind}-${store.id}`}
                    type="button"
                    className="storestrip-item"
                    onClick={() => open(store)}
                >
                    <span className="storestrip-avatar">
                        {store.avatar_url
                            ? <img src={store.avatar_url} alt="" loading="lazy" />
                            : <span aria-hidden="true">{store.name.trim().charAt(0).toUpperCase()}</span>}

                        {store.is_verified && (
                            <span className="storestrip-check" aria-hidden="true">
                                <Check size={11} strokeWidth={3} />
                            </span>
                        )}
                    </span>

                    <span className="storestrip-name">{store.name}</span>
                </button>
            ))}
        </div>
    );
};
