import React, { useState } from 'react';
import { AlertTriangle, Check, ChevronDown, Clock, Package, RotateCcw, ShieldCheck } from 'lucide-react';
import type { Deal } from '@/types';
import { dealSteps, fmtDate, isFinished, statusLabel, statusTone, ton } from './dealFormat';

type T = (ru: string, en: string) => string;

/**
 * Сделка всегда над перепиской: товар, сумма, статус и действия. По нажатию
 * раскрываются этапы и сроки — их спрашивают реже, чем пишут сообщения.
 */
export const DealCard: React.FC<{
    deal: Deal;
    language: string;
    t: T;
    busy: boolean;
    onShip: () => void;
    onConfirm: () => void;
    onProblem: () => void;
    onRefund: () => void;
}> = ({ deal, language, t, busy, onShip, onConfirm, onProblem, onRefund }) => {
    const [expanded, setExpanded] = useState(false);

    const buyer = deal.role === 'buyer';
    const amount = ton(deal.amount_ton);
    const sellerAmount = ton(deal.seller_amount_ton);
    const mine = buyer ? amount : sellerAmount;
    const deadline = deal.confirm_deadline_at ? fmtDate(deal.confirm_deadline_at, language) : null;

    let sub: string;
    if (deal.status === 'released') {
        sub = buyer
            ? t(`${amount} TON · переведено продавцу`, `${amount} TON · paid to the seller`)
            : t(`${sellerAmount} TON · начислено на баланс`, `${sellerAmount} TON · added to your balance`);
    } else if (deal.status === 'refunded') {
        sub = buyer
            ? t(`${amount} TON · возвращено на баланс`, `${amount} TON · refunded to your balance`)
            : t(`${sellerAmount} TON · возвращено покупателю`, `${sellerAmount} TON · refunded to the buyer`);
    } else if (deal.status === 'disputed') {
        sub = t(`${mine} TON · заморожено до решения спора`, `${mine} TON · frozen until the dispute is resolved`);
    } else {
        sub = buyer
            ? t(`${amount} TON · у площадки до подтверждения`, `${amount} TON · held until you confirm`)
            : t(`${sellerAmount} TON · придут после подтверждения`, `${sellerAmount} TON · after the buyer confirms`);
    }

    const finished = isFinished(deal);
    const { steps, current } = dealSteps(deal, language, t);

    const commissionPercent = Number(deal.amount_ton) > 0
        ? Math.round((Number(deal.commission_ton) / Number(deal.amount_ton)) * 1000) / 10
        : 0;

    let note: string;
    if (deal.status === 'disputed') {
        note = t(
            'Деньги заморожены, пока модератор разбирает спор. Он видит всю переписку этой сделки.',
            'Funds are frozen while a moderator reviews the dispute. They can see this entire conversation.',
        );
    } else if (deal.status === 'refunded') {
        note = t('Спор решён возвратом. Переписка остаётся доступной для чтения.', 'The dispute ended with a refund. The conversation stays readable.');
    } else if (finished) {
        note = buyer
            ? t('Сделка завершена. Переписка остаётся доступной для чтения.', 'The deal is complete. The conversation stays readable.')
            : t(`${sellerAmount} TON начислены на ваш баланс. Вывести их можно в профиле.`, `${sellerAmount} TON added to your balance. Withdraw it in your profile.`);
    } else {
        note = buyer
            ? t(
                'Деньги хранятся у площадки. Продавец получит их, когда вы подтвердите получение. Если не подтвердить, сделка закроется сама после срока.',
                'The platform holds the money. The seller gets it once you confirm receipt. If you do not confirm, the deal closes itself after the deadline.',
            )
            : t(
                `Покупатель оплатил ${amount} TON, деньги у площадки. После подтверждения вам начислят ${sellerAmount} TON, комиссия площадки ${commissionPercent}%.`,
                `The buyer paid ${amount} TON, held by the platform. After confirmation you get ${sellerAmount} TON, platform fee ${commissionPercent}%.`,
            );
    }

    const problem = (
        <button type="button" className="dchat-btn danger" onClick={onProblem} disabled={busy}>
            {t('Проблема', 'Problem')}
        </button>
    );

    let actions: React.ReactNode = null;
    if (deal.status === 'disputed') {
        actions = (
            <span className="dchat-wait warn">
                <AlertTriangle size={15} />
                {t('Спор на рассмотрении, модератор в чате', 'Dispute under review, a moderator is in the chat')}
            </span>
        );
    } else if (!finished) {
        if (!buyer) {
            actions = deal.status === 'delivered_claimed' ? (
                <>
                    <span className="dchat-wait">
                        <Clock size={15} />
                        {deadline
                            ? t(`Ждём подтверждения до ${deadline}`, `Awaiting confirmation until ${deadline}`)
                            : t('Ждём подтверждения', 'Awaiting confirmation')}
                    </span>
                    {problem}
                </>
            ) : (
                <>
                    <button type="button" className="dchat-btn primary grow" onClick={onShip} disabled={busy}>
                        <Package size={16} />
                        <span>{t('Я отправил товар', 'I have sent the item')}</span>
                    </button>
                    {problem}
                </>
            );
        } else {
            const shipped = deal.status === 'delivered_claimed';
            actions = (
                <>
                    <button
                        type="button"
                        className={`dchat-btn grow ${shipped ? 'primary' : 'ghost'}`}
                        onClick={onConfirm}
                        disabled={busy}
                    >
                        {shipped && <Check size={16} />}
                        <span>{t('Подтвердить получение', 'Confirm receipt')}</span>
                    </button>
                    {problem}
                </>
            );
        }
    }

    return (
        <div className={`dchat-deal${expanded ? ' expanded' : ''}`}>
            <button
                type="button"
                className="dchat-deal-top"
                onClick={() => setExpanded(!expanded)}
                aria-expanded={expanded}
                aria-label={t('Подробности сделки', 'Deal details')}
            >
                <span className="dchat-thumb">
                    {deal.product_image
                        ? <img src={deal.product_image} alt="" />
                        : <Package size={20} />}
                </span>
                <span className="dchat-deal-info">
                    <span className="dchat-deal-name">{deal.product_name}</span>
                    <span className="dchat-deal-sub">{sub}</span>
                </span>
                <span className="dchat-deal-side">
                    <span className={`dchat-chip ${statusTone(deal.status)}`}>{statusLabel(deal.status, t)}</span>
                    <ChevronDown size={16} className="dchat-chev" />
                </span>
            </button>

            {expanded && (
                <>
                    {/* Номер — в подробностях: на него ссылаются уведомления
                        бота и поддержка, а место в шапке занято «в сети» */}
                    <div className="dchat-deal-num">
                        {t(`Сделка №${deal.number}`, `Deal #${deal.number}`)}
                    </div>
                    <div className="dchat-steps">
                        {steps.map(({ title, when, done }, index) => (
                            <span
                                key={title}
                                className={`dchat-step${done ? ' done' : ''}${index === current ? ' current' : ''}`}
                            >
                                <i />
                                {title}
                                <small>{when}</small>
                            </span>
                        ))}
                    </div>
                    <div className="dchat-note">
                        {deal.status === 'disputed' ? <AlertTriangle size={15} /> : <ShieldCheck size={15} />}
                        <span>{note}</span>
                    </div>
                </>
            )}

            {actions && <div className="dchat-actions">{actions}</div>}

            {/* Возврат — продавцу, пока сделка не закрыта, в том числе в споре.
                Ссылкой, а не третьей кнопкой: действие редкое, и в ряду с
                основным оно бы спорило за внимание */}
            {!buyer && !finished && (
                <button type="button" className="dchat-refund-link" onClick={onRefund} disabled={busy}>
                    <RotateCcw size={14} />
                    {t('Вернуть деньги покупателю', 'Refund the buyer')}
                </button>
            )}
        </div>
    );
};
