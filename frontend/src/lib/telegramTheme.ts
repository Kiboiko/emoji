/**
 * Привязка палитры к теме Telegram.
 *
 * Telegram передаёт цвета оформления клиента в themeParams. До этого они
 * читались, но никуда не применялись, и приложение выглядело чужеродным на
 * фоне мессенджера — особенно у людей с нестандартной темой.
 *
 * Применяются только нейтральные цвета: фон, текст, подписи, границы.
 * Акцентный градиент остаётся фирменным: button_color у большинства
 * пользователей — стандартный синий Telegram, и магазин потерял бы всякое
 * визуальное лицо.
 */

export interface TelegramThemeParams {
    bg_color?: string;
    text_color?: string;
    hint_color?: string;
    link_color?: string;
    button_color?: string;
    button_text_color?: string;
    secondary_bg_color?: string;
    section_bg_color?: string;
}

/** Переменные, которые мы переопределяем. Нужны, чтобы уметь всё вернуть. */
const MANAGED = [
    '--bg-primary',
    '--bg-secondary',
    '--bg-tertiary',
    '--bg-card',
    '--bg-glass',
    '--text-primary',
    '--text-secondary',
    '--text-tertiary',
    '--border-color',
];

/** #rrggbb -> "r, g, b". null, если формат неожиданный. */
function toRgb(hex?: string): string | null {
    if (!hex) return null;
    const match = /^#?([0-9a-f]{6})$/i.exec(hex.trim());
    // Группа проверяется отдельно: при noUncheckedIndexedAccess обращение по
    // индексу считается возможно пустым
    if (!match || !match[1]) return null;
    const value = parseInt(match[1], 16);
    return `${(value >> 16) & 255}, ${(value >> 8) & 255}, ${value & 255}`;
}

export function clearTelegramTheme(): void {
    const root = document.documentElement;
    for (const name of MANAGED) {
        root.style.removeProperty(name);
    }
}

export function applyTelegramTheme(params: TelegramThemeParams | undefined): boolean {
    // Без фона и текста подстраиваться не от чего: в браузере (вне Telegram)
    // themeParams пустой, и трогать палитру нельзя
    if (!params?.bg_color || !params?.text_color) return false;

    const bg = toRgb(params.bg_color);
    const text = toRgb(params.text_color);
    if (!bg || !text) return false;

    const root = document.documentElement;
    const secondary = params.secondary_bg_color || params.section_bg_color;

    root.style.setProperty('--bg-primary', params.bg_color);
    root.style.setProperty('--bg-secondary', secondary || `rgba(${text}, 0.04)`);
    root.style.setProperty('--bg-tertiary', `rgba(${text}, 0.08)`);

    // Карточки полупрозрачны поверх фона: сплошной цвет убил бы эффект стекла,
    // на котором держится вся вёрстка витрины
    root.style.setProperty('--bg-card', `rgba(${bg}, 0.8)`);
    root.style.setProperty('--bg-glass', `rgba(${bg}, 0.7)`);

    root.style.setProperty('--text-primary', params.text_color);
    // hint_color Telegram отдаёт не всегда — тогда выводим из основного текста
    root.style.setProperty('--text-secondary', params.hint_color || `rgba(${text}, 0.6)`);
    root.style.setProperty('--text-tertiary', `rgba(${text}, 0.4)`);
    root.style.setProperty('--border-color', `rgba(${text}, 0.12)`);

    return true;
}
