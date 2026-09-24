import React from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';
import './CabinetPage.css';

/**
 * Обёртка раздела кабинета: кнопка назад, заголовок, содержимое.
 *
 * Разделы разъехались по отдельным экранам — в одном длинном свитке при
 * десятке товаров и подписок всё превращалось в мелкую кашу. Общая обёртка
 * нужна, чтобы шапка и отступы у всех разделов были одни и те же.
 */
export const CabinetPage: React.FC<{
    title: string;
    children: React.ReactNode;
}> = ({ title, children }) => {
    const navigate = useNavigate();

    return (
        <div className="cabinet-page">
            <div className="container">
                <button className="btn-back" onClick={() => navigate('/profile')}>
                    <ArrowLeft size={20} />
                    <span>Профиль</span>
                </button>

                <h1 className="cabinet-title">{title}</h1>

                {children}
            </div>

            {/* Нижняя панель навигации перекрывает последний элемент списка */}
            <div className="cabinet-bottom-spacer" />
        </div>
    );
};
