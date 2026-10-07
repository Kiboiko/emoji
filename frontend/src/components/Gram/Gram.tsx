import React, { useId } from 'react';
import { formatTon } from '@/lib/ton';
import './Gram.css';

/**
 * Знак валюты — кристалл с искрой — вместо слова «TON».
 *
 * Заказчик попросил показывать рядом с суммами сам логотип, а не тикер.
 * Искра вырезана маской, а не нарисована цветом фона: знак стоит и на
 * карточках, и на кнопках, и в пузырях чата — фон везде разный.
 */
export const GramIcon: React.FC<{ size?: number | string; className?: string; title?: string }> = ({
    size = '0.95em', className = '', title,
}) => {
    const mask = `gram-${useId().replace(/:/g, '')}`;
    return (
        <svg
            className={`gram-icon ${className}`}
            width={size}
            height={size}
            viewBox="0 0 24 24"
            role={title ? 'img' : undefined}
            aria-label={title}
            aria-hidden={title ? undefined : true}
        >
            <defs>
                <mask id={mask}>
                    <rect width="24" height="24" fill="white" />
                    <path
                        d="M12 6.6c.35 2.3.95 2.9 3.25 3.25-2.3.35-2.9.95-3.25 3.25-.35-2.3-.95-2.9-3.25-3.25 2.3-.35 2.9-.95 3.25-3.25z"
                        fill="black"
                    />
                </mask>
            </defs>
            <path
                d="M6.4 3.5h11.2l4 5.6L12 20.8 2.4 9.1z"
                fill="currentColor"
                stroke="currentColor"
                strokeWidth="1.6"
                strokeLinejoin="round"
                mask={`url(#${mask})`}
            />
        </svg>
    );
};

/**
 * Текст, где слово «TON» заменено знаком: «12.5 TON у площадки» →
 * «12.5 ◆ у площадки». Для готовых фраз из t() и системных сообщений
 * сервера — переписывать каждую фразу в разметку незачем. Заменяется только
 * отдельное слово заглавными: «TonConnect» и прочее не трогается.
 */
export function withGram(text: string | null | undefined): React.ReactNode {
    if (!text) return text ?? null;
    // Заодно укорачиваем сумму перед знаком: в старых сообщениях сервера
    // она записана всеми девятью знаками — «0.006535948 TON»
    const short = text.replace(/(\d+(?:\.\d+)?)(\s*)TON\b/g, (_, n: string, gap: string) => `${formatTon(n)}${gap}TON`);
    const parts = short.split(/\bTON\b/);
    if (parts.length === 1) return short;
    return parts.map((part, index) => (
        <React.Fragment key={index}>
            {part}
            {index < parts.length - 1 && <GramIcon title="TON" />}
        </React.Fragment>
    ));
}
