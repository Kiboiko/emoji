export interface User {
    id: string;
    telegram_id: number;
    username?: string;
    first_name: string;
    language_code: string;
    is_admin: boolean;
    referral_code: string;
    referral_earnings: number;
    created_at: string;
}

export interface Category {
    id: string;
    name: string;
    sort_order: number;
}

export interface Product {
    id: string;
    name: string;
    description: string;
    price_usdt: number;
    price_ton?: number;
    image_url: string;
    category_id: string;
    is_top: boolean;
    type?: 'digital' | 'service' | 'instruction' | 'subscription' | 'p2p';
    min_quantity?: number;
    max_quantity?: number;
    created_at: string;
    /** Снят с продажи: в каталоге такого нет, но по старой ссылке открыть можно */
    is_active?: boolean;
    /** Товар пользователя, а не площадки: оплата уходит в escrow */
    is_p2p?: boolean;

    /** Оценка товара. null — отзывов нет: карточка не рисует ни звёзд, ни нуля */
    rating?: number | null;
    reviews_count?: number;

    /** Чей это магазин: продавца, канала или самой площадки */
    author_kind?: 'seller' | 'channel' | 'platform' | null;
    /** id магазина — по нему строится ссылка на его витрину */
    author_id?: string | null;
    author_name?: string | null;
    author_avatar?: string | null;
    author_verified?: boolean;
    author_rating?: number | null;
    author_deals?: number;
    /** @username канала — у продавца такого адреса нет */
    author_link?: string | null;
}

/** Карточка товара на витрине магазина: автор там один и назван сверху */
export interface StoreProduct {
    id: string;
    name: string;
    price_usdt: string;
    image_url: string;
    type: string;
    is_top: boolean;
}

export type StoreKind = 'seller' | 'channel' | 'platform';

export interface Store {
    kind: StoreKind;
    id: string;
    name: string;
    avatar_url: string | null;
    description: string | null;
    is_verified: boolean;
    rating: number | null;
    rating_count: number;
    deals_completed: number;
    /** Только у канала */
    link?: string | null;
    subscribers?: number;
    products: StoreProduct[];
}

/** Счётчики разделов кабинета — для строк на главной странице профиля */
export interface ProfileSummary {
    is_seller: boolean;
    seller_id: string | null;
    listings: number;
    channels: number;
    orders: number;
    subscriptions: number;
    deals: number;
}

export interface CartItem {
    id: string;
    product_id: string;
    name: string;
    image_url: string;
    price_usdt: number;
    price_ton?: number;
    quantity: number;
    subtotal_usdt: number;
    subtotal_ton?: number;
    type?: 'digital' | 'service' | 'instruction';
    user_data?: {
        link?: string;
        [key: string]: any;
    };
}

export interface Cart {
    items: CartItem[];
    total_usdt: number;
    total_ton?: number;
}

export interface OrderItem {
    id: string;
    product_id: string;
    quantity: number;
    price_usdt: number;
    price_ton?: number;
    product_snapshot: {
        name_ru: string;
        name_en: string;
        description_ru: string;
        description_en: string;
        content_data: any;
        image_url?: string;
    };
    is_reviewed: boolean;
}

export interface Order {
    id: string;
    user_id: string;
    total_usdt: number;
    total_ton?: number;
    currency: 'USDT' | 'TON';
    status: 'pending' | 'paid' | 'completed' | 'cancelled';
    cryptobot_invoice_id?: string;
    created_at: string;
    paid_at?: string;
    items: OrderItem[];
}

export interface Review {
    id: string;
    user_id: string | null;
    user: {
        first_name: string;
    } | null;
    product_id: string;
    order_id: string | null;
    text: string;
    rating?: number;
    is_hidden: boolean;
    is_fake?: boolean;
    fake_username?: string | null;
    created_at: string;
}

export interface ReferralStats {
    referral_code: string;
    referral_count: number;
    total_earnings: number;
    /** Заработок со второго уровня. 0, когда второй уровень выключен. */
    level2_earnings?: number;
    /** Процент первого уровня: без него непонятно, от чего считается сумма */
    referral_percent?: number;
    /** Сколько оплаченных заказов сделали приглашённые */
    paid_orders_count?: number;
    referrals: Array<{
        user_id: string;
        telegram_id: number;
        username?: string;
        orders_count: number;
        total_spent: number;
        commission_earned: number;
    }>;
}

export interface AuthResponse {
    access_token: string;
    token_type: string;
    user: User;
}

export type Theme = 'light' | 'dark';
export type Language = 'ru' | 'en';

export interface MySubscription {
    id: string;
    channel_id: string;
    channel_title: string | null;
    plan_title: string | null;
    status: 'pending' | 'active' | 'expired' | 'revoked';
    started_at: string | null;
    expires_at: string | null;
    days_left: number | null;
    joined: boolean;
    /** Одноразовая ссылка. null, если уже использована или истекла. */
    invite_link: string | null;
}

/** Статусы канала автора — зеркало ChannelStatus на бэкенде */
export type ChannelStatus = 'draft' | 'pending' | 'active' | 'suspended' | 'rejected';

export interface ChannelPlan {
    id: string;
    product_id: string | null;
    title_ru: string;
    title_en: string;
    duration_days: number;
    price_usd: string;
    is_active: boolean;
}

export interface AuthorChannel {
    id: string;
    title: string;
    username: string | null;
    description: string | null;
    avatar_url: string | null;
    status: ChannelStatus;
    /** Галочку проверенного автора ставит только администратор */
    is_verified: boolean;
    moderation_comment: string | null;
    payout_wallet: string | null;
    /** Без прав бота канал нельзя опубликовать: доступ невозможно ни выдать, ни отозвать */
    bot_is_admin: boolean;
    bot_check_error: string | null;
    plans: ChannelPlan[];
}

export type DealStatus =
    | 'created' | 'paid_escrow' | 'chat_opened' | 'delivered_claimed'
    | 'confirmed' | 'released' | 'disputed' | 'refunded' | 'cancelled';

export interface Deal {
    id: string;
    number: number;
    product_name: string;
    /** Нужны форме отзыва: эндпоинт опознаёт покупку по заказу и товару */
    order_id: string;
    product_id: string;
    /** Покупатель уже оценил продавца по этой сделке */
    reviewed: boolean;
    role: 'buyer' | 'seller';
    status: DealStatus;
    amount_ton: string;
    seller_amount_ton: string;
    confirm_deadline_at: string | null;
    chat_closed: boolean;
    dispute_reason: string | null;
    created_at: string;
}

export interface SellerProfile {
    registered: boolean;
    /** id профиля — по нему строится адрес витрины магазина */
    id?: string;
    display_name?: string;
    payout_wallet?: string;
    /** Логотип магазина. Грузится вручную: аватар Telegram сделал бы магазин похожим на личный аккаунт */
    avatar_url?: string | null;
    description?: string | null;
    is_verified?: boolean;
    status?: 'active' | 'restricted' | 'banned';
    restricted_until?: string | null;
    restriction_reason?: string | null;
    rating?: number | null;
    rating_count?: number;
    deals_completed?: number;
    /** Заработок на внутреннем счёте, ещё не выведенный */
    balance_ton?: string;
}

export type ListingStatus =
    | 'draft' | 'pending' | 'approved' | 'rejected' | 'withdrawn' | 'archived';

export interface ListingImage {
    id: string;
    url: string;
}

export interface Listing {
    id: string;
    name: string;
    description: string;
    price_usd: string;
    status: ListingStatus;
    moderation_comment: string | null;
    product_id: string | null;
    category_id: string | null;
    images: ListingImage[];
    created_at: string;
}

export interface Terms {
    version: string;
    text: string;
    is_empty: boolean;
}
