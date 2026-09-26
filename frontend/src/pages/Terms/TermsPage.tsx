import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowLeft, Check, FileText } from 'lucide-react';
import { termsApi } from '@/api/client';
import { useAuthStore } from '@/store/authStore';
import { useToastStore, errorText } from '@/store/toastStore';
import { useTelegram } from '@/hooks/useTelegram';
import type { Terms } from '@/types';
import './TermsPage.css';

/**
 * Условия площадки целиком, на своём экране.
 *
 * Раньше текст раскрывался прямо в форме оформления заказа — внутри и без
 * того длинной страницы, между кошельком и кнопкой оплаты. Под документ на
 * несколько экранов там места нет: человек либо теряет кнопку из виду, либо
 * не читает вовсе.
 *
 * Принять можно и отсюда: прочитал — согласился, не возвращаясь в корзину.
 */
export const TermsPage: React.FC = () => {
    const navigate = useNavigate();
    const { language } = useAuthStore();
    const { haptic } = useTelegram();
    const showToast = useToastStore((s) => s.show);

    const [terms, setTerms] = useState<Terms | null>(null);
    const [accepted, setAccepted] = useState<boolean | null>(null);
    const [failed, setFailed] = useState(false);
    const [busy, setBusy] = useState(false);

    const t = (ru: string, en: string) => (language === 'ru' ? ru : en);

    useEffect(() => {
        let alive = true;
        (async () => {
            try {
                const [text, status] = await Promise.all([
                    termsApi.get(),
                    // Статус спрашиваем отдельно и не роняем страницу, если
                    // он не пришёл: текст условий читают и до входа
                    termsApi.status().catch(() => null),
                ]);
                if (!alive) return;
                setTerms(text);
                setAccepted(status ? status.accepted : null);
            } catch {
                if (alive) setFailed(true);
            }
        })();
        return () => { alive = false; };
    }, []);

    const accept = async () => {
        if (!terms) return;
        setBusy(true);
        try {
            const result = await termsApi.accept(terms.version);
            if (result.accepted) {
                haptic.notification('success');
                setAccepted(true);
                showToast(t('Условия приняты', 'Terms accepted'), 'success');
            } else {
                // Владелец успел обновить текст, пока страница была открыта
                haptic.notification('warning');
                showToast(
                    result.message
                        ?? t('Условия обновились — перечитайте', 'The terms changed — please re-read'),
                    'info',
                );
                setTerms(await termsApi.get());
            }
        } catch (e) {
            haptic.notification('error');
            showToast(errorText(e, t('Не удалось принять условия', 'Failed to accept the terms')), 'error');
        } finally {
            setBusy(false);
        }
    };

    return (
        <div className="terms-page">
            <div className="container">
                <button className="btn-back" onClick={() => navigate(-1)}>
                    <ArrowLeft size={20} />
                    <span>{t('Назад', 'Back')}</span>
                </button>

                <h1 className="terms-page-title">{t('Условия площадки', 'Platform terms')}</h1>

                {failed ? (
                    <p className="terms-page-empty">
                        {t('Не удалось загрузить условия. Попробуйте позже.',
                           'Could not load the terms. Try again later.')}
                    </p>
                ) : terms === null ? (
                    <>
                        <div className="skeleton terms-page-skeleton" />
                        <div className="skeleton terms-page-skeleton" />
                        <div className="skeleton terms-page-skeleton short" />
                    </>
                ) : terms.is_empty ? (
                    <p className="terms-page-empty">
                        <FileText size={16} />
                        {t('Текст условий пока не заполнен администрацией.',
                           'The terms text has not been filled in yet.')}
                    </p>
                ) : (
                    <>
                        <div className="terms-page-meta">
                            <span className="terms-page-version">
                                {t('Редакция ', 'Version ')}{terms.version}
                            </span>
                            {accepted && (
                                <span className="terms-page-accepted">
                                    <Check size={14} />
                                    {t('Вы приняли эту редакцию', 'You accepted this version')}
                                </span>
                            )}
                        </div>

                        {/* pre-wrap, а не разметка: текст пишет владелец в
                            админке обычным полем, и его абзацы и списки живут
                            переносами строк */}
                        <pre className="terms-page-text">{terms.text}</pre>

                        {accepted === false && (
                            <button
                                className="terms-page-accept"
                                onClick={accept}
                                disabled={busy}
                            >
                                <Check size={18} />
                                {t('Принимаю условия', 'I accept the terms')}
                            </button>
                        )}
                    </>
                )}
            </div>

            <div className="bottom-nav-spacer" />
        </div>
    );
};
