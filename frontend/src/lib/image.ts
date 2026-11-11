/**
 * Маленькая копия загруженного фото — для каталога и списков.
 *
 * Оригиналы весят до нескольких мегабайт, а в плитке шириной в полэкрана
 * нужно в десятки раз меньше. Копию до 384 px сервер кладёт рядом с
 * оригиналом, nginx отдаёт её по тому же адресу с ?size=thumb (а если копии
 * нет — сам оригинал). Чужие адреса (аватар из Telegram, blob: из формы)
 * не трогаем: там такого параметра нет.
 */
export const thumb = (url?: string | null, size: 'thumb' | 'cart' = 'thumb'): string | undefined => {
    if (!url) return undefined;
    if (!url.startsWith('/uploads/')) return url;
    return `${url}${url.includes('?') ? '&' : '?'}size=${size}&v=3`;
};

/** Refresh previously cached originals when the lighter format is deployed. */
export const webImage = (url: string): string => url.startsWith('/uploads/')
    ? `${url}${url.includes('?') ? '&' : '?'}v=3` : url;
