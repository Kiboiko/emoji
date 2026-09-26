/**
 * Склонение и даты.
 *
 * Русское число рядом с существительным требует трёх форм, и «1 отзывов»
 * на витрине магазина сразу читается как недоделка. Английскому хватает двух,
 * поэтому у каждой функции есть второй, простой путь.
 */

/** [один отзыв, два отзыва, пять отзывов] */
export type PluralForms = [string, string, string];

export function pluralRu(count: number, forms: PluralForms): string {
    const tail = Math.abs(count) % 10;
    const hundred = Math.abs(count) % 100;

    // 11–14 — исключение: они оканчиваются на 1–4, но требуют формы «пять»
    if (tail === 1 && hundred !== 11) return forms[0];
    if (tail >= 2 && tail <= 4 && (hundred < 12 || hundred > 14)) return forms[1];
    return forms[2];
}

const MONTHS_RU = [
    'января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
    'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря',
];

/**
 * «марта 2025» / «March 2025» — месяц и год без числа.
 *
 * Точная дата регистрации покупателю не нужна и выглядит слежкой; месяц
 * отвечает на единственный настоящий вопрос — давно ли продавец здесь.
 *
 * null, если дата не разобралась: строку «на площадке с Invalid Date»
 * показывать нельзя.
 */
export function monthYear(iso: string | undefined, language: string): string | null {
    if (!iso) return null;

    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return null;

    if (language === 'ru') {
        return `${MONTHS_RU[date.getMonth()]} ${date.getFullYear()}`;
    }
    return date.toLocaleDateString('en-US', { month: 'long', year: 'numeric' });
}
