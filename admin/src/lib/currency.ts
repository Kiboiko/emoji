/**
 * Как валюта называется на экране. Код в базе и API остаётся «TON»,
 * людям заказчик попросил показывать «Gram».
 */
export const currencyLabel = (code: string | null | undefined) =>
    code === 'TON' ? 'Gram' : (code ?? '');
