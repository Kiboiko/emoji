import React from 'react';
import { Search } from 'lucide-react';
import { useAuthStore } from '@/store/authStore';
import './Header.css';

interface HeaderProps {
    searchQuery: string;
    onSearchChange: (query: string) => void;
    /** Заголовок экрана */
    pageTitle?: string;
    /** Правый край строки заголовка — переключатель вида каталога */
    actions?: React.ReactNode;
}

/**
 * Шапка каталога: заголовок и поиск.
 *
 * Кнопок темы и языка здесь больше нет — они уехали в профиль. Они висели на
 * каждом экране и занимали треть строки, а нажимают их один раз за всё время
 * пользования: язык и тему выбирают, а не переключают по ходу покупки.
 */
export const Header: React.FC<HeaderProps> = ({
    searchQuery,
    onSearchChange,
    pageTitle,
    actions,
}) => {
    const { language } = useAuthStore();

    // Плейсхолдер был зашит по-русски, и в английском режиме поле оставалось
    // русским — единственная строка интерфейса, не переводившаяся вовсе
    const searchLabel = language === 'ru' ? 'Поиск товаров' : 'Search products';

    return (
        <header className="header">
            {(pageTitle || actions) && (
                <div className="header-top">
                    {pageTitle && <h1 className="header-title">{pageTitle}</h1>}
                    {actions && <div className="header-actions">{actions}</div>}
                </div>
            )}

            <div className="search-container">
                <Search className="search-icon" size={18} />
                {/* Плейсхолдер подписью не считается: он пропадает, как только
                    начали печатать, и поле для диктора становится безымянным */}
                <label htmlFor="catalog-search" className="visually-hidden">
                    {searchLabel}
                </label>
                <input
                    id="catalog-search"
                    type="text"
                    className="search-input"
                    placeholder={searchLabel}
                    value={searchQuery}
                    onChange={(e) => onSearchChange(e.target.value)}
                />
            </div>
        </header>
    );
};
