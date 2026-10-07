import React, { useState } from 'react';
import type { Deal } from '@/types';
import { ton } from './dealFormat';
import { withGram } from '@/components/Gram/Gram';

type T = (ru: string, en: string) => string;

export type SheetKind = 'confirm' | 'dispute' | 'refund';

/**
 * Шторки необратимых действий.
 *
 * Подтверждение получения, возврат и спор решают судьбу денег, поэтому
 * одним нажатием на кнопку в карточке они не выполняются: сначала шторка
 * объясняет, что произойдёт.
 */
export const DealSheet: React.FC<{
    kind: SheetKind;
    deal: Deal;
    t: T;
    busy: boolean;
    onClose: () => void;
    onConfirm: () => void;
    onRefund: () => void;
    onDispute: (reason: string) => void;
}> = ({ kind, deal, t, busy, onClose, onConfirm, onRefund, onDispute }) => {
    const [reason, setReason] = useState<string | null>(null);
    const [note, setNote] = useState('');

    const reasons = deal.role === 'buyer'
        ? [
            t('Ключ не активируется', 'The key does not activate'),
            t('Товар не получен', 'Item not received'),
            t('Не соответствует описанию', 'Not as described'),
            t('Другое', 'Other'),
        ]
        : [
            t('Покупатель не выходит на связь', 'The buyer does not respond'),
            t('Покупатель просит вернуть деньги', 'The buyer asks for a refund'),
            t('Другое', 'Other'),
        ];

    const store = deal.store?.name ?? t('продавца', 'the seller');

    return (
        <div
            className="dchat-sheet-host"
            onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
        >
            {kind === 'refund' ? (
                <div className="dchat-sheet" role="dialog" aria-modal="true">
                    <span className="dchat-grab" />
                    <h3>{t('Вернуть деньги покупателю?', 'Refund the buyer?')}</h3>
                    <p>
                        {withGram(t(
                            `Все ${ton(deal.amount_ton)} TON сразу вернутся на баланс покупателя, сделка закроется. Отменить возврат будет нельзя.`,
                            `All ${ton(deal.amount_ton)} TON go straight back to the buyer's balance and the deal closes. The refund cannot be undone.`,
                        ))}
                    </p>
                    <p>
                        {t(
                            'Товар снова станет доступен для покупки. Если его больше нет — уменьшите количество в объявлении.',
                            'The item becomes available for purchase again. If you no longer have it, lower the quantity in the listing.',
                        )}
                    </p>
                    <div className="dchat-sheet-actions">
                        <button type="button" className="dchat-btn danger" onClick={onRefund} disabled={busy}>
                            {t('Да, вернуть деньги', 'Yes, refund')}
                        </button>
                        <button type="button" className="dchat-btn ghost" onClick={onClose}>
                            {t('Отмена', 'Cancel')}
                        </button>
                    </div>
                </div>
            ) : kind === 'confirm' ? (
                <div className="dchat-sheet" role="dialog" aria-modal="true">
                    <span className="dchat-grab" />
                    <h3>{t('Подтвердить получение?', 'Confirm receipt?')}</h3>
                    <p>
                        {withGram(t(
                            `${ton(deal.amount_ton)} TON уйдут продавцу «${store}». После этого вернуть деньги или открыть спор будет нельзя.`,
                            `${ton(deal.amount_ton)} TON will go to “${store}”. After that you cannot get a refund or open a dispute.`,
                        ))}
                    </p>
                    <div className="dchat-sheet-actions">
                        <button type="button" className="dchat-btn primary" onClick={onConfirm} disabled={busy}>
                            {t('Да, товар получен', 'Yes, I received it')}
                        </button>
                        <button type="button" className="dchat-btn ghost" onClick={onClose}>
                            {t('Отмена', 'Cancel')}
                        </button>
                    </div>
                </div>
            ) : (
                <div className="dchat-sheet" role="dialog" aria-modal="true">
                    <span className="dchat-grab" />
                    <h3>{t('Что случилось?', 'What happened?')}</h3>
                    <p>
                        {t(
                            'Деньги останутся у площадки, пока модератор разбирается. Он подключится к этому чату и увидит всю переписку.',
                            'The money stays with the platform while a moderator looks into it. They will join this chat and see the whole conversation.',
                        )}
                    </p>
                    <div className="dchat-reasons">
                        {reasons.map((item) => (
                            <button
                                key={item}
                                type="button"
                                className="dchat-reason"
                                aria-pressed={reason === item}
                                onClick={() => setReason(item)}
                            >
                                {item}
                            </button>
                        ))}
                    </div>
                    <textarea
                        value={note}
                        onChange={(e) => setNote(e.target.value)}
                        placeholder={t('Подробности, если нужно', 'Details, if needed')}
                        maxLength={300}
                        aria-label={t('Подробности', 'Details')}
                    />
                    <div className="dchat-sheet-actions">
                        <button
                            type="button"
                            className="dchat-btn danger"
                            disabled={!reason || busy}
                            onClick={() => reason && onDispute(note.trim() ? `${reason}. ${note.trim()}` : reason)}
                        >
                            {t('Открыть спор', 'Open a dispute')}
                        </button>
                        <button type="button" className="dchat-btn ghost" onClick={onClose}>
                            {t('Отмена', 'Cancel')}
                        </button>
                    </div>
                </div>
            )}
        </div>
    );
};
