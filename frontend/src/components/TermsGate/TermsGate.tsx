import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { ChevronRight } from 'lucide-react';
import { termsApi } from '@/api/client';
import { useAuthStore } from '@/store/authStore';
import type { Terms } from '@/types';
import './TermsGate.css';

interface TermsGateProps {
    /** Вызывается при каждом изменении галочки */
    onChange: (accepted: boolean) => void;
}

/**
 * Галочка «согласен с условиями площадки».
 *
 * Показывается, только если пользователь ещё не принимал текущую редакцию:
 * галочка на каждой покупке приучает щёлкать не читая. Если уже принимал —
 * компонент ничего не рисует и сразу сообщает согласие наверх.
 */
export const TermsGate: React.FC<TermsGateProps> = ({ onChange }) => {
    const { language } = useAuthStore();
    const [terms, setTerms] = useState<Terms | null>(null);
    const [needed, setNeeded] = useState<boolean | null>(null);
    const [checked, setChecked] = useState(false);

    const t = (ru: string, en: string) => (language === 'ru' ? ru : en);

    useEffect(() => {
        let cancelled = false;
        (async () => {
            try {
                const [status, text] = await Promise.all([
                    termsApi.status(),
                    termsApi.get(),
                ]);
                if (cancelled) return;
                setTerms(text);
                setNeeded(!status.accepted);
                if (status.accepted) onChange(true);
            } catch {
                // Не смогли выяснить — считаем, что галочка нужна. Бэкенд всё
                // равно проверит и вернёт 409, так что пропустить согласие
                // мимо себя это не даёт.
                if (!cancelled) setNeeded(true);
            }
        })();
        return () => { cancelled = true; };
    }, [onChange]);

    if (needed === null || needed === false) return null;

    const toggle = () => {
        const next = !checked;
        setChecked(next);
        onChange(next);
    };

    return (
        <div className="terms-gate">
            <label className="terms-check">
                <input type="checkbox" checked={checked} onChange={toggle} />
                <span>{t('Я соглашаюсь с условиями площадки', 'I agree to the platform terms')}</span>
            </label>

            {/* Ссылка вынесена из <label>: клик по ссылке внутри ярлыка
                переключал бы галочку заодно с переходом.

                Текст открывается на своём экране, а не раскрывается здесь:
                условий много, и внутри формы оформления заказа они
                отодвигали кнопку оплаты на несколько экранов вниз. */}
            <Link className="terms-link" to="/terms">
                {terms?.is_empty
                    ? t('Открыть условия', 'Open the terms')
                    : t('Читать условия площадки', 'Read the platform terms')}
                <ChevronRight size={14} />
            </Link>
        </div>
    );
};
