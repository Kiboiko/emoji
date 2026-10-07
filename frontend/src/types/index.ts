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
    /** Язык, выбранный в приложении; null — ещё не выбирал */
    app_language?: 'ru' | 'en' | null;
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
    /** Остальные фотографии товара. Первая совпадает с image_url */
    images?: string[];
    /** Сколько штук осталось. null — товар не кончается (услуга, подписка) */
    stock?: number | null;
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
    /** Сколько отзывов стоит за оценкой продавца. Только на странице товара */
    author_reviews?: number;
    author_deals?: number;
    /** @username канала — у продавца такого адреса нет */
    author_link?: string | null;
}

export type StoreKind = 'seller' | 'channel' | 'platform';

/** Настройки площадки, видимые снаружи. Базисные пункты: 200 = 2% */
export interface PublicSettings {
    commission_p2p_bp: number;
    commission_subscription_bp: number;
    /** Куда писать в поддержку: @username или ссылка. Пусто — адрес не задан */
    support_contact: string;
}

/**
 * Магазин в строке на главной: только то, что помещается под кружком.
 * Полная витрина — Store ниже.
 */
export interface StoreCard {
    kind: StoreKind;
    id: string;
    name: string;
    avatar_url: string | null;
    is_verified: boolean;
    rating: number | null;
    /** Сколько товаров сейчас продаётся */
    products: number;
}

export interface Store {
    kind: StoreKind;
    id: string;
    name: string;
    /** Английское название — только у канала, если автор его задал */
    name_en?: string;
    avatar_url: string | null;
    description: string | null;
    is_verified: boolean;
    rating: number | null;
    rating_count: number;
    deals_completed: number;
    /** Дата регистрации магазина — для строки «на площадке с…» */
    created_at?: string;
    /** Только у канала */
    link?: string | null;
    subscribers?: number;
    /** Те же товары, что и в каталоге: витрина рисует тот же компонент */
    products: Product[];
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
    /** Потолок количества: меньшее из «в одни руки» и остатка. null — без ограничений */
    max_quantity?: number | null;
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
        /** Фотографии на момент покупки: продавец мог их потом сменить */
        images?: string[];
        type?: string;
        /** Товар продавца — по нему есть сделка, в списке покупок он идёт ею */
        is_p2p?: boolean;
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
    /** Заработано на рефералах в TON за всё время — деньги на общем балансе */
    earned_ton?: string;
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

/** Заявка на вывод — в истории выводов в профиле */
export interface MyWithdrawal {
    id: string;
    amount: number;
    currency: 'TON' | 'USD';
    wallet: string;
    /** sending — администратор отправил перевод, ждём подтверждения сети */
    status: 'pending' | 'sending' | 'completed' | 'rejected';
    created_at: string;
    completed_at: string | null;
    reject_reason?: string | null;
}

export interface MySubscription {
    id: string;
    channel_id: string;
    channel_title: string | null;
    channel_title_en?: string | null;
    plan_title: string | null;
    plan_title_en?: string | null;
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
    /** Название для показа: заданное автором, иначе из Telegram */
    title: string;
    title_en?: string;
    /** Что автор задал сам — для формы правки; null — берётся из Telegram */
    custom_title_ru?: string | null;
    custom_title_en?: string | null;
    telegram_title?: string;
    username: string | null;
    description: string | null;
    /** Описание для английского интерфейса */
    description_en: string | null;
    avatar_url: string | null;
    /** Обложка подписок — картинка, которую автор загрузил сам */
    cover_url: string | null;
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

/** Кто написал: я, собеседник, площадка или модератор */
export type DealMessageFrom = 'me' | 'them' | 'system' | 'moderator';

export interface DealMessage {
    id: string;
    from: DealMessageFrom;
    /** Вид системного сообщения: pay / ship / done / refund / dispute / resolved */
    kind: string | null;
    text: string | null;
    /** Английский текст — только у сообщений площадки */
    text_en?: string | null;
    /** Подписанная ссылка на фото — действует несколько часов */
    photo_url: string | null;
    /** Вложение, пришедшее когда-то через бота: самого файла у нас нет */
    legacy_media: string | null;
    created_at: string;
    /** Только у своих: отправлено / прочитано собеседником */
    state: 'sent' | 'read' | null;
}

export interface Deal {
    id: string;
    number: number;
    product_name: string;
    product_image: string | null;
    /** Нужны форме отзыва: эндпоинт опознаёт покупку по заказу и товару */
    order_id: string;
    product_id: string | null;
    /** Покупатель уже оценил продавца по этой сделке */
    reviewed: boolean;
    role: 'buyer' | 'seller';
    status: DealStatus;
    amount_ton: string;
    seller_amount_ton: string;
    commission_ton: string;
    paid_at: string;
    delivered_at: string | null;
    confirm_deadline_at: string | null;
    confirmed_at: string | null;
    released_at: string | null;
    refunded_at: string | null;
    chat_closed: boolean;
    /** Писать в переписку ещё можно */
    chat_open: boolean;
    /** До какого момента закрытую переписку можно прочитать */
    chat_expires_at?: string | null;
    /** Срок вышел — переписки у сторон больше нет */
    chat_expired?: boolean;
    dispute_reason: string | null;
    /** Магазин продавца — только у покупателя; продавец покупателя не видит */
    store: { name: string; verified: boolean; avatar_url: string | null } | null;
    unread: number;
    last_message: {
        from: DealMessageFrom;
        text: string | null;
        text_en?: string | null;
        photo: boolean;
        created_at: string;
    } | null;
    last_activity_at: string;
    counterpart_read_at: string | null;
    /** null — сделка закрыта, «в сети» не показывается */
    counterpart_online: boolean | null;
    counterpart_last_seen_at: string | null;
    created_at: string;
    /** Только у одной сделки (GET /p2p/deals/{id}) — для страницы сделки */
    details?: DealDetails;
}

/** Товар таким, каким его купили, и магазин — для страницы сделки */
export interface DealDetails {
    description: string | null;
    description_en: string | null;
    name_en: string | null;
    images: string[];
    quantity: number;
    /** Только покупателю */
    store: { id: string; rating: number | null; rating_count: number; deals_completed: number } | null;
}

/** Что покупатель получил по позиции заказа у площадки */
export interface OrderDelivery {
    kind: 'digital' | 'instruction' | 'service' | 'subscription' | 'p2p' | string;
    keys: string[];
    instruction: string | null;
    link: string | null;
}

export interface SellerProfile {
    registered: boolean;
    /** id профиля — по нему строится адрес витрины магазина */
    id?: string;
    display_name?: string;
    /** Название уже выбрано владельцем и больше не меняется */
    name_locked?: boolean;
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
    /** Название для английского интерфейса */
    name_en: string | null;
    description: string;
    /** Описание для английского интерфейса */
    description_en: string | null;
    price_usd: string;
    /** Сколько единиц товара у продавца. При публикации уходит в сток */
    quantity: number;
    /** Сколько можно купить прямо сейчас. null — товара в каталоге ещё нет */
    stock: number | null;
    /** Продано по сделкам */
    sold: number;
    /** Оформлено покупателями, но ещё не оплачено */
    reserved: number;
    /** Когда истечёт самая ранняя бронь (UTC, ISO) */
    reserved_until: string | null;
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
