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
    type?: 'digital' | 'service' | 'instruction';
    min_quantity?: number;
    max_quantity?: number;
    created_at: string;
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
