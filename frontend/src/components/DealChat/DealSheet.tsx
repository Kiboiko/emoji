import React, { useState } from 'react';
import type { Deal } from '@/types';
import { ton } from './dealFormat';

type T = (ru: string, en: string) => string;

export type SheetKind = 'confirm' | 'dispute';

/**
 * Шторки необратимых действий.
 *
 * Подтверждение получения и спор решают судьбу денег, поэтому одним
 * нажатием на кнопку в карточке они не выполняются: сначала шторка
 * объясняет, что произойдёт.
 */
export const DealSheet: React.FC<{
    kind: SheetKind;
    deal: Deal;
    t: T;
    busy: boolean;
    onClose: () => void;
    onConfirm: () => void;
    onDispute: (reason: string) => void;
}> = ({ kind, deal, t, busy, onClose, onConfirm, onDispute }) => {
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
            {kind === 'confirm' ? (
                <div className="dchat-sheet" role="dialog" aria-modal="true">
                    <span className="dchat-grab" />
                    <h3>{t('Подтвердить получение?', 'Confirm receipt?')}</h3>
                    <p>
                        {t(
                            `${ton(deal.amount_ton)} TON уйдут продавцу «${store}». После этого вернуть деньги или открыть спор будет нельзя.`,
                            `${ton(deal.amount_ton)} TON will go to “${store}”. After that you cannot get a refund or open a dispute.`,
                        )}
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
