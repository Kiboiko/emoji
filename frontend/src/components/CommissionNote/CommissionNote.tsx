import React from 'react';
import { useAuthStore } from '@/store/authStore';
import './CommissionNote.css';

interface CommissionNoteProps {
    /** Цена как её ввели в поле — строка из input */
    price: string | number;
    /** Комиссия в базисных пунктах (200 = 2%). null — ещё не загрузилась */
    bp: number | null;
}

/**
 * Сколько площадка удержит с этой цены.
 *
 * Стоит рядом с полем цены, а не в условиях мелким шрифтом: процент нужен
 * ровно в тот момент, когда цену назначают. Раньше продавец узнавал размер
 * комиссии после первой выплаты.
 *
 * Пока цена не введена, показываем один процент — это уже ответ на вопрос
 * «сколько вы берёте».
 */
export const CommissionNote: React.FC<CommissionNoteProps> = ({ price, bp }) => {
    const { language } = useAuthStore();
    const t = (ru: string, en: string) => (language === 'ru' ? ru : en);

    // Без процента писать нечего: придумать его нельзя, а промолчать честно
    if (bp === null) return null;

    // 200 -> «2», 350 -> «3.5». Хвост из нулей обрезаем: «2.00%» выглядит
    // как точность, которой тут нет
    const percent = String(Number((bp / 100).toFixed(2)));

    const value = Number(price);
    const priced = Number.isFinite(value) && value > 0;

    if (!priced) {
        return (
            <p className="commission-note">
                {t(`Комиссия площадки — ${percent}% с продажи.`,
                   `Platform fee — ${percent}% per sale.`)}
            </p>
        );
    }

    const fee = (value * bp) / 10000;
    const payout = value - fee;

    return (
        <p className="commission-note">
            {t('Комиссия площадки ', 'Platform fee ')}
            <strong>{percent}%</strong>
            {' — '}
            <strong>${fee.toFixed(2)}</strong>
            {t('. Вы получите ', '. You get ')}
            <strong>${payout.toFixed(2)}</strong>
        </p>
    );
};
