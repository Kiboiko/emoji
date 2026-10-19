/**
 * Маленькая копия загруженного фото — для каталога и списков.
 *
 * Оригиналы весят до нескольких мегабайт, а в плитке шириной в полэкрана
 * нужно в десятки раз меньше. Копию до 600 px сервер кладёт рядом с
 * оригиналом, nginx отдаёт её по тому же адресу с ?size=thumb (а если копии
 * нет — сам оригинал). Чужие адреса (аватар из Telegram, blob: из формы)
 * не трогаем: там такого параметра нет.
 */
export const thumb = (url?: string | null): string | undefined => {
    if (!url) return undefined;
    if (!url.startsWith('/uploads/')) return url;
    return `${url}${url.includes('?') ? '&' : '?'}size=thumb`;
};
