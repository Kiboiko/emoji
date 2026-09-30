import type { Deal, DealMessage } from '@/types';

type T = (ru: string, en: string) => string;

/** 12.500000000 → 12.5: сервер отдаёт TON со всеми девятью знаками */
export const ton = (value: string) =>
    value.includes('.') ? value.replace(/\.?0+$/, '') : value;

const locale = (language: string) => (language === 'ru' ? 'ru-RU' : 'en-US');

export const fmtTime = (iso: string, language: string) =>
    new Date(iso).toLocaleTimeString(locale(language), { hour: '2-digit', minute: '2-digit' });

export const fmtDate = (iso: string, language: string) =>
    new Date(iso).toLocaleDateString(locale(language), { day: 'numeric', month: 'long' });

const dayKey = (date: Date) => `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`;

/** Разделитель дней в переписке: «Сегодня», «Вчера», «12 сентября» */
export function dayLabel(iso: string, language: string, t: T): string {
    const date = new Date(iso);
    const today = new Date();
    const yesterday = new Date(Date.now() - 86_400_000);
    if (dayKey(date) === dayKey(today)) return t('Сегодня', 'Today');
    if (dayKey(date) === dayKey(yesterday)) return t('Вчера', 'Yesterday');
    return fmtDate(iso, language);
}

export const sameDay = (a: string, b: string) => dayKey(new Date(a)) === dayKey(new Date(b));

/** Время в списке сделок: сегодня — часы, вчера — «вчера», раньше — дата */
export function listTime(iso: string, language: string, t: T): string {
    const date = new Date(iso);
    if (dayKey(date) === dayKey(new Date())) return fmtTime(iso, language);
    if (dayKey(date) === dayKey(new Date(Date.now() - 86_400_000))) return t('вчера', 'yesterday');
    return date.toLocaleDateString(locale(language), { day: 'numeric', month: 'short' }).replace('.', '');
}

export function statusLabel(status: Deal['status'], t: T): string {
    const labels: Record<string, string> = {
        paid_escrow: t('Оплачено', 'Paid'),
        chat_opened: t('Переписка', 'Chatting'),
        delivered_claimed: t('Отправлено', 'Shipped'),
        confirmed: t('Подтверждено', 'Confirmed'),
        released: t('Завершена', 'Completed'),
        disputed: t('Спор', 'Dispute'),
        refunded: t('Возврат', 'Refunded'),
        cancelled: t('Отменена', 'Cancelled'),
    };
    return labels[status] ?? status;
}

/** Цвет метки статуса: идёт сделка, закрыта, спор или возврат */
export function statusTone(status: Deal['status']): 'open' | 'done' | 'dispute' | 'muted' {
    if (status === 'released' || status === 'confirmed') return 'done';
    if (status === 'disputed' || status === 'refunded') return 'dispute';
    if (status === 'cancelled') return 'muted';
    return 'open';
}

/** Кто написал — подпись в списке и в уведомлении */
export function author(deal: Deal, from: DealMessage['from'], t: T): string {
    if (from === 'me') return t('Вы', 'You');
    if (from === 'system') return t('Площадка', 'Marketplace');
    if (from === 'moderator') return t('Модератор', 'Moderator');
    return deal.role === 'buyer' ? (deal.store?.name ?? t('Продавец', 'Seller')) : t('Покупатель', 'Buyer');
}

export function counterpartName(deal: Deal, t: T): string {
    return deal.role === 'buyer' ? (deal.store?.name ?? t('Продавец', 'Seller')) : t('Покупатель', 'Buyer');
}

/**
 * Похоже на попытку увести сделку в личку: @username, ссылки на мессенджеры,
 * телефон. Почту не ловим: логин от аккаунта в сообщении продавца — это и
 * есть товар.
 */
export const CONTACT = /(^|[\s(,:])@[a-z0-9_]{4,}|t\.me\/|telegram\.me|wa\.me|whats ?app|вотсап|ватсап|вацап|телеграм|в личк|в лс\b|(\+7|\+375|\+380|\b8)[\s\-(]*\d{3}[\s\-)]*\d{3}[\s-]*\d{2}[\s-]*\d{2}/i;

/**
 * Текст, разрезанный на обычные куски и `код` в обратных кавычках: ключи и
 * пароли выделяются и копируются одним нажатием.
 */
export function splitCode(text: string): { code: boolean; value: string }[] {
    return text.split('`').map((value, index) => ({ code: index % 2 === 1, value }))
        .filter((part) => part.value !== '');
}
