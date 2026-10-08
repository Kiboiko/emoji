import React from 'react';
import { formatTon } from '@/lib/ton';
import './Gram.css';

/**
 * Знак валюты — кристалл с искрой — вместо её названия.
 *
 * Заказчик попросил показывать рядом с суммами сам логотип, а там, где
 * картинку не вставить (бот, всплывашки, админка), — слово «Gram».
 * Контур снят с присланного им образца: скруглённые углы, крупная искра
 * правее и выше центра, как блик. Искра — дырка в контуре (evenodd), а не
 * фигура цветом фона: знак стоит и на карточках, и на кнопках, и в пузырях
 * чата — фон везде разный.
 */
const GEM =
    'M4.85 4.77Q6.03 3.03 8.13 3.03L15.87 3.03Q17.97 3.03 19.15 4.77L22.11 9.16Q23.01 10.48 21.88 11.62'
    + 'L13.2 20.28Q12 21.48 10.8 20.28L2.12 11.62Q0.99 10.48 1.89 9.16Z';
const SPARK =
    'M14.63 5.64Q15.63 8.65 18.63 9.65Q15.63 10.65 14.63 13.65Q13.63 10.65 10.62 9.65Q13.63 8.65 14.63 5.64Z';

export const GramIcon: React.FC<{ size?: number | string; className?: string; title?: string }> = ({
    size = '0.95em', className = '', title,
}) => (
    <svg
        className={`gram-icon ${className}`}
        width={size}
        height={size}
        viewBox="0 0 24 24"
        role={title ? 'img' : undefined}
        aria-label={title}
        aria-hidden={title ? undefined : true}
    >
        <path d={GEM + SPARK} fill="currentColor" fillRule="evenodd" />
    </svg>
);

/**
 * Текст, где название валюты заменено знаком: «12.5 Gram у площадки» →
 * «12.5 ◆ у площадки». Для готовых фраз из t() и системных сообщений
 * сервера — переписывать каждую фразу в разметку незачем. Сервер пишет
 * «Gram», в старых сообщениях осталось «TON» — знаком становятся оба.
 * Заменяется только отдельное слово: «TonConnect», «Telegram» не трогаются.
 */
const CURRENCY_WORD = /\b(?:TON|Gram)\b/;

export function withGram(text: string | null | undefined): React.ReactNode {
    if (!text) return text ?? null;
    // Заодно укорачиваем сумму перед знаком: в старых сообщениях сервера
    // она записана всеми девятью знаками — «0.006535948 TON»
    const short = text.replace(
        /(\d+(?:\.\d+)?)(\s*)(TON|Gram)\b/g,
        (_, n: string, gap: string, word: string) => `${formatTon(n)}${gap}${word}`,
    );
    const parts = short.split(CURRENCY_WORD);
    if (parts.length === 1) return short;
    return parts.map((part, index) => (
        <React.Fragment key={index}>
            {part}
            {index < parts.length - 1 && <GramIcon title="Gram" />}
        </React.Fragment>
    ));
}
