import type { Deal, DealMessage } from '@/types';
import { formatTon } from '@/lib/ton';

type T = (ru: string, en: string) => string;

/**
 * Сумма в TON для показа: 0.006535948 → 0.0065, 14.553 → 14.55.
 * Сервер отдаёт все девять знаков, а длинный хвост читается как ошибка.
 */
export const ton = (value: string) => formatTon(value);

const locale = (language: string) => (language === 'ru' ? 'ru-RU' : 'en-US');

export const fmtTime = (iso: string, language: string) =>
    new Date(iso).toLocaleTimeString(locale(language), { hour: '2-digit', minute: '2-digit' });

export const fmtDate = (iso: string, language: string) =>
    new Date(iso).toLocaleDateString(locale(language), { day: 'numeric', month: 'long' });

/** «7 окт., 14:02» — когда важна и минута: время оплаты */
export const fmtDateTime = (iso: string, language: string) =>
    new Date(iso).toLocaleString(locale(language), {
        day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit',
    });

/** Комиссия площадки в процентах с одним знаком: 3, 2.5 */
export const commissionPercent = (deal: Pick<Deal, 'amount_ton' | 'commission_ton'>) =>
    Number(deal.amount_ton) > 0
        ? Math.round((Number(deal.commission_ton) / Number(deal.amount_ton)) * 1000) / 10
        : 0;

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

/** «был(а) в сети 5 мин назад» — как у Telegram, без угадывания пола */
export function lastSeen(iso: string | null | undefined, language: string, t: T): string {
    if (!iso) return t('не в сети', 'offline');
    const date = new Date(iso);
    const minutes = Math.floor((Date.now() - date.getTime()) / 60_000);
    if (minutes < 1) return t('был(а) в сети только что', 'last seen just now');
    if (minutes < 60) return t(`был(а) в сети ${minutes} мин назад`, `last seen ${minutes} min ago`);
    const time = fmtTime(iso, language);
    if (dayKey(date) === dayKey(new Date())) {
        return t(`был(а) в сети сегодня в ${time}`, `last seen today at ${time}`);
    }
    if (dayKey(date) === dayKey(new Date(Date.now() - 86_400_000))) {
        return t(`был(а) в сети вчера в ${time}`, `last seen yesterday at ${time}`);
    }
    const day = fmtDate(iso, language);
    return t(`был(а) в сети ${day}`, `last seen ${day}`);
}

/** Сделка закрыта: дальше её состояние не меняется */
export const FINISHED_STATUSES: Deal['status'][] = ['released', 'refunded', 'cancelled', 'confirmed'];

export const isFinished = (deal: Deal) => FINISHED_STATUSES.includes(deal.status);

/**
 * Этапы сделки «Оплачено → Отправлено → Получено» с датами. Общие для
 * карточки над перепиской и страницы сделки — чтобы показывали одно и то же.
 * current — этап, который сейчас ждёт; -1, когда ждать нечего.
 */
export function dealSteps(deal: Deal, language: string, t: T) {
    const received = deal.released_at ?? deal.confirmed_at;
    const deadline = deal.confirm_deadline_at ? fmtDate(deal.confirm_deadline_at, language) : null;
    const steps: { title: string; when: string; done: boolean }[] = [
        { title: t('Оплачено', 'Paid'), when: fmtDate(deal.paid_at, language), done: true },
        {
            title: t('Отправлено', 'Shipped'),
            when: deal.delivered_at ? fmtDate(deal.delivered_at, language) : t('ещё нет', 'not yet'),
            done: Boolean(deal.delivered_at),
        },
        {
            title: t('Получено', 'Received'),
            when: received
                ? fmtDate(received, language)
                : deal.status === 'delivered_claimed' && deadline ? t(`до ${deadline}`, `by ${deadline}`) : '—',
            done: Boolean(received),
        },
    ];
    const current = isFinished(deal) || deal.status === 'disputed' ? -1 : steps.findIndex((s) => !s.done);
    return { steps, current, deadline };
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
