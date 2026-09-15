import React, { useEffect, useState } from 'react';
import { FileText, ChevronDown, ChevronUp } from 'lucide-react';
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
    const [expanded, setExpanded] = useState(false);

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
                <span>
                    {t('Я соглашаюсь с ', 'I agree to the ')}
                    <button
                        type="button"
                        className="terms-link"
                        onClick={(e) => { e.preventDefault(); setExpanded(!expanded); }}
                    >
                        {t('условиями площадки', 'platform terms')}
                        {expanded ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
                    </button>
                </span>
            </label>

            {expanded && (
                <div className="terms-body">
                    {terms?.is_empty ? (
                        <p className="terms-empty">
                            <FileText size={14} />
                            {t(
                                'Текст условий пока не заполнен администрацией.',
                                'The terms text has not been filled in yet.',
                            )}
                        </p>
                    ) : (
                        <pre className="terms-text">{terms?.text}</pre>
                    )}
                    {terms && (
                        <div className="terms-version">
                            {t('Редакция ', 'Version ')}{terms.version}
                        </div>
                    )}
                </div>
            )}
        </div>
    );
};
