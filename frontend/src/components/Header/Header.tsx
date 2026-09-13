import React from 'react';
import { Search, Moon, Sun, Globe } from 'lucide-react';
import { useTheme } from '@/hooks/useTheme';
import { useAuthStore } from '@/store/authStore';
import './Header.css';

interface HeaderProps {
    searchQuery: string;
    onSearchChange: (query: string) => void;
    pageTitle?: string; // Optional page title for mobile
}

export const Header: React.FC<HeaderProps> = ({ searchQuery, onSearchChange, pageTitle }) => {
    const { theme, toggleTheme } = useTheme();
    const { language, setLanguage } = useAuthStore();

    const toggleLanguage = () => {
        setLanguage(language === 'ru' ? 'en' : 'ru');
    };

    return (
        <header className="header glass-card">
            {pageTitle && (
                <div className="header-page-title">
                    <h1>{pageTitle}</h1>
                </div>
            )}

            <div className="header-row">
                <div className="search-container">
                    <Search className="search-icon" size={20} />
                    <input
                        type="text"
                        className="search-input"
                        placeholder="Поиск товаров..."
                        value={searchQuery}
                        onChange={(e) => onSearchChange(e.target.value)}
                    />
                </div>

                <div className="header-actions">
                    <button
                        className="icon-btn"
                        onClick={toggleLanguage}
                        aria-label="Toggle language"
                    >
                        <Globe size={20} />
                        <span className="lang-code">{language.toUpperCase()}</span>
                    </button>

                    <button
                        className="icon-btn"
                        onClick={toggleTheme}
                        aria-label="Toggle theme"
                    >
                        {theme === 'light' ? <Moon size={20} /> : <Sun size={20} />}
                    </button>
                </div>
            </div>
        </header>
    );
};
