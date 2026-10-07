import React from 'react';
import { Link } from 'react-router-dom';
import { ChevronRight, FileText, Globe, Headset, Palette } from 'lucide-react';
import { useTheme } from '@/hooks/useTheme';
import { useAuthStore } from '@/store/authStore';
import { useTelegram } from '@/hooks/useTelegram';
import { usePublicSettings } from '@/hooks/usePublicSettings';
import { usersApi } from '@/api/client';
import './AppSettings.css';

/**
 * Адрес поддержки в виде ссылки.
 *
 * Владелец площадки пишет его в админке как придётся: «@support»,
 * «t.me/support» или готовым адресом. Пока адрес не задан, ведём в чат с
 * ботом — это единственное место, которое точно существует, и молчащая
 * кнопка там лучше кнопки, ведущей в никуда.
 */
const supportLink = (contact: string): string => {
    const value = contact.trim();
    if (!value) {
        return `https://t.me/${import.meta.env.VITE_BOT_USERNAME || ''}`;
    }
    if (/^https?:\/\//i.test(value)) return value;
    if (value.startsWith('@')) return `https://t.me/${value.slice(1)}`;
    if (value.startsWith('t.me/')) return `https://${value}`;
    return `https://t.me/${value}`;
};

/**
 * Язык и оформление.
 *
 * Обе настройки жили кнопками в шапке каталога: они висели на каждом экране,
 * занимали треть строки поиска и при этом нажимаются один раз за всё время
 * пользования. Здесь у них есть подписи — по иконке глобуса не было видно,
 * какой язык выбран сейчас, а по луне не было видно, что будет после нажатия.
 *
 * У темы три положения, а не два. «Как в Telegram» в коде было всегда
 * (useTheme.followTelegram) и включалось само до первого ручного выбора, но
 * вернуться к нему из интерфейса было нельзя: один раз нажав на луну, человек
 * навсегда отвязывался от оформления мессенджера.
 */
export const AppSettings: React.FC = () => {
    const { theme, setTheme, followTelegram, followsTelegram } = useTheme();
    const { language, setLanguage } = useAuthStore();
    const { haptic } = useTelegram();
    const settings = usePublicSettings();

    const t = (ru: string, en: string) => (language === 'ru' ? ru : en);

    const pickTheme = (next: 'telegram' | 'light' | 'dark') => {
        haptic.impact('light');
        if (next === 'telegram') followTelegram();
        else setTheme(next);
    };

    const pickLanguage = (next: 'ru' | 'en') => {
        haptic.impact('light');
        setLanguage(next);
        // Сервер запоминает выбор: бот пишет уведомления на этом языке, и
        // приложение откроется с ним в следующий раз. Не дошло — не страшно,
        // в приложении язык уже переключён
        usersApi.setLanguage(next).catch(() => undefined);
    };

    return (
        <section className="appsettings">
            <h2 className="appsettings-title">{t('Настройки', 'Settings')}</h2>

            <div className="appsettings-row">
                <div className="appsettings-head">
                    <span className="appsettings-icon" aria-hidden="true">
                        <Globe size={18} />
                    </span>
                    <span className="appsettings-label">{t('Язык', 'Language')}</span>
                </div>

                <div className="appsettings-switch">
                    <button
                        type="button"
                        className={language === 'ru' ? 'active' : ''}
                        aria-pressed={language === 'ru'}
                        onClick={() => pickLanguage('ru')}
                    >
                        Русский
                    </button>
                    <button
                        type="button"
                        className={language === 'en' ? 'active' : ''}
                        aria-pressed={language === 'en'}
                        onClick={() => pickLanguage('en')}
                    >
                        English
                    </button>
                </div>
            </div>

            <div className="appsettings-row">
                <div className="appsettings-head">
                    <span className="appsettings-icon" aria-hidden="true">
                        <Palette size={18} />
                    </span>
                    <span className="appsettings-label">{t('Оформление', 'Appearance')}</span>
                </div>

                <div className="appsettings-switch">
                    <button
                        type="button"
                        className={followsTelegram ? 'active' : ''}
                        aria-pressed={followsTelegram}
                        onClick={() => pickTheme('telegram')}
                    >
                        {t('Как в Telegram', 'Match Telegram')}
                    </button>
                    <button
                        type="button"
                        className={!followsTelegram && theme === 'light' ? 'active' : ''}
                        aria-pressed={!followsTelegram && theme === 'light'}
                        onClick={() => pickTheme('light')}
                    >
                        {t('Светлая', 'Light')}
                    </button>
                    <button
                        type="button"
                        className={!followsTelegram && theme === 'dark' ? 'active' : ''}
                        aria-pressed={!followsTelegram && theme === 'dark'}
                        onClick={() => pickTheme('dark')}
                    >
                        {t('Тёмная', 'Dark')}
                    </button>
                </div>
            </div>

            {/* Условия площадки читают редко, но искать их человек идёт
                именно в настройки, а не в форму оформления заказа */}
            <Link className="appsettings-link" to="/terms">
                <span className="appsettings-icon" aria-hidden="true">
                    <FileText size={18} />
                </span>
                <span className="appsettings-label">{t('Условия площадки', 'Platform terms')}</span>
                <ChevronRight className="appsettings-chevron" size={18} />
            </Link>

            {/* Поддержка там же, где условия: человек, у которого что-то
                пошло не так, идёт в настройки, а не ищет контакт в описании
                бота. openTelegramLink открывает чат внутри мессенджера —
                обычная ссылка увела бы его в браузер поверх приложения. */}
            <a
                className="appsettings-link"
                href={supportLink(settings?.support_contact ?? '')}
                onClick={(e) => {
                    const link = supportLink(settings?.support_contact ?? '');
                    const tg = (window as any).Telegram?.WebApp;
                    if (tg?.openTelegramLink && link.startsWith('https://t.me/')) {
                        e.preventDefault();
                        haptic.impact('light');
                        tg.openTelegramLink(link);
                    }
                }}
                target="_blank"
                rel="noreferrer"
            >
                {/* Гарнитура, а не спасательный круг: круг читается как
                    «аварийная ситуация», а наушники с микрофоном — это
                    привычный значок живого оператора */}
                <span className="appsettings-icon" aria-hidden="true">
                    <Headset size={18} />
                </span>
                <span className="appsettings-label">
                    {t('Связаться с поддержкой', 'Contact support')}
                </span>
                <ChevronRight className="appsettings-chevron" size={18} />
            </a>
        </section>
    );
};
