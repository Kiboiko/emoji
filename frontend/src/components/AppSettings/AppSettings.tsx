import React from 'react';
import { Globe, Palette } from 'lucide-react';
import { useTheme } from '@/hooks/useTheme';
import { useAuthStore } from '@/store/authStore';
import { useTelegram } from '@/hooks/useTelegram';
import './AppSettings.css';

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

    const t = (ru: string, en: string) => (language === 'ru' ? ru : en);

    const pickTheme = (next: 'telegram' | 'light' | 'dark') => {
        haptic.impact('light');
        if (next === 'telegram') followTelegram();
        else setTheme(next);
    };

    const pickLanguage = (next: 'ru' | 'en') => {
        haptic.impact('light');
        setLanguage(next);
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
        </section>
    );
};
