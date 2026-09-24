import React from 'react';
import { useNavigate } from 'react-router-dom';
import { ChevronRight } from 'lucide-react';
import './CabinetNav.css';

export interface CabinetLink {
    to: string;
    icon: React.ReactNode;
    label: string;
    /** Число рядом со строкой. null — считать нечего, показывать не надо */
    count?: number | null;
    /** Строка есть всегда, даже когда пусто: иначе раздел некуда завести */
    hint?: string;
}

/**
 * Список разделов личного кабинета.
 *
 * Разделы разъехались по отдельным экранам: в одном длинном свитке при
 * десятке товаров и подписок всё превращалось в мелкую кашу. Здесь остаются
 * только строки со счётчиками, а списки живут каждый на своей странице во
 * всю высоту.
 */
export const CabinetNav: React.FC<{ links: CabinetLink[] }> = ({ links }) => {
    const navigate = useNavigate();

    return (
        <nav className="cabnav glass-card">
            {links.map((link) => (
                <button
                    key={link.to}
                    className="cabnav-row"
                    onClick={() => navigate(link.to)}
                >
                    <span className="cabnav-icon">{link.icon}</span>

                    <span className="cabnav-body">
                        <span className="cabnav-label">{link.label}</span>
                        {link.hint && <span className="cabnav-hint">{link.hint}</span>}
                    </span>

                    {/* Ноль показываем тоже: «заказов 0» — это ответ, а
                        пропавший счётчик читается как «ещё не загрузилось» */}
                    {link.count != null && (
                        <span className="cabnav-count">{link.count}</span>
                    )}

                    <ChevronRight className="cabnav-arrow" size={18} />
                </button>
            ))}
        </nav>
    );
};
