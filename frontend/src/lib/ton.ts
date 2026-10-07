/**
 * TON для людей: без хвоста из девяти знаков.
 *
 * Сервер отдаёт суммы точно — «0.061783440». На экране это читается как
 * ошибка: от единицы хватает двух знаков, меньше — четырёх, а совсем
 * мелочь показываем двумя значащими цифрами, чтобы не превратилась в ноль.
 * Только для показа: в расчёты и в поля ввода идёт исходная строка.
 * Зеркало format_ton_short на бэкенде.
 */
export function formatTon(value: string | number | null | undefined): string {
    const n = Number(value);
    if (value === null || value === undefined || value === '' || !Number.isFinite(n)) {
        return String(value ?? '');
    }
    if (n === 0) return '0';

    const magnitude = Math.abs(n);
    let places: number;
    if (magnitude >= 1) places = 2;
    else if (magnitude >= 0.0001) places = 4;
    else places = Math.min(9, -Math.floor(Math.log10(magnitude)) + 1);

    const fixed = n.toFixed(places);
    return fixed.includes('.') ? fixed.replace(/0+$/, '').replace(/\.$/, '') : fixed;
}
