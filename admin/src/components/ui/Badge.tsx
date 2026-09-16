import React from 'react';

type Tone = 'neutral' | 'info' | 'success' | 'warning' | 'danger';

const TONE_CLASS: Record<Tone, string> = {
    neutral: 'bg-gray-700 text-gray-300',
    info: 'bg-blue-500/15 text-blue-400',
    success: 'bg-green-500/15 text-green-400',
    warning: 'bg-amber-500/15 text-amber-400',
    danger: 'bg-red-500/15 text-red-400',
};

/**
 * Статусы со всего проекта в одном месте.
 *
 * Собраны вместе намеренно: один и тот же статус должен выглядеть одинаково
 * в заказах, сделках и заявках, иначе администратор читает цвет как разный
 * смысл.
 */
const STATUS_TONE: Record<string, Tone> = {
    // Заказы
    pending: 'warning',
    paid: 'info',
    completed: 'success',
    cancelled: 'danger',
    // Сделки
    created: 'neutral',
    paid_escrow: 'info',
    chat_opened: 'info',
    delivered_claimed: 'info',
    confirmed: 'success',
    released: 'success',
    disputed: 'warning',
    refunded: 'danger',
    // Заявки и каналы
    draft: 'neutral',
    approved: 'success',
    active: 'success',
    rejected: 'danger',
    withdrawn: 'neutral',
    archived: 'neutral',
    suspended: 'danger',
    // Продавцы
    restricted: 'warning',
    banned: 'danger',
    // Платежи
    expired: 'danger',
    underpaid: 'warning',
};

const STATUS_LABEL: Record<string, string> = {
    pending: 'Ожидает',
    paid: 'Оплачен',
    completed: 'Завершён',
    cancelled: 'Отменён',
    created: 'Создана',
    paid_escrow: 'В эскроу',
    chat_opened: 'Переписка',
    delivered_claimed: 'Отправлено',
    confirmed: 'Подтверждено',
    released: 'Выплачено',
    disputed: 'Спор',
    refunded: 'Возврат',
    draft: 'Черновик',
    approved: 'Одобрено',
    active: 'Активен',
    rejected: 'Отклонено',
    withdrawn: 'Снято',
    archived: 'В архиве',
    suspended: 'Приостановлен',
    restricted: 'Ограничен',
    banned: 'Заблокирован',
    expired: 'Истёк',
    underpaid: 'Недоплата',
};

export const Badge: React.FC<{ tone?: Tone; children: React.ReactNode }> = ({
    tone = 'neutral', children,
}) => (
    <span className={`inline-block px-2 py-0.5 rounded-md text-xs font-medium whitespace-nowrap ${TONE_CLASS[tone]}`}>
        {children}
    </span>
);

export const StatusBadge: React.FC<{ status: string }> = ({ status }) => (
    <Badge tone={STATUS_TONE[status] ?? 'neutral'}>
        {STATUS_LABEL[status] ?? status}
    </Badge>
);
