import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import {
    Store, Star, Pencil, Camera, ChevronRight, AlertTriangle, ChevronDown, ChevronUp, Check,
} from 'lucide-react';
import { p2pApi, termsApi } from '@/api/client';
import { useAuthStore } from '@/store/authStore';
import { useToastStore, errorText } from '@/store/toastStore';
import { useTelegram } from '@/hooks/useTelegram';
import { formatTon } from '@/lib/ton';
import { GramIcon } from '@/components/Gram/Gram';
import type { Listing, SellerProfile } from '@/types';
import { ListingsList } from './ListingsList';
import './SellerCabinet.css';

/**
 * Кабинет продавца.
 *
 * Свёрнут по умолчанию: большинству пользователей продавать нечего, и
 * разворачивать форму на пол-экрана всем подряд незачем.
 */
export const SellerCabinet: React.FC<{ standalone?: boolean }> = ({ standalone = false }) => {
    const { language } = useAuthStore();
    const { haptic } = useTelegram();
    const showToast = useToastStore((s) => s.show);

    // На своём экране сворачивать нечего: заголовок даёт сама
    // страница, и содержимое должно быть видно сразу
    const [open, setOpen] = useState(standalone);
    const [profile, setProfile] = useState<SellerProfile | null>(null);
    const [listings, setListings] = useState<Listing[]>([]);
    const [busy, setBusy] = useState(false);

    const t = (ru: string, en: string) => (language === 'ru' ? ru : en);

    const loadProfile = useCallback(async () => {
        const data: SellerProfile = await p2pApi.getSellerProfile();
        setProfile(data);
        return data;
    }, []);

    const loadListings = useCallback(async () => {
        try {
            setListings(await p2pApi.getMyListings());
        } catch {
            setListings([]);
        }
    }, []);

    useEffect(() => {
        loadProfile().catch(() => setProfile({ registered: false }));
    }, [loadProfile]);

    useEffect(() => {
        if (open && profile?.registered) loadListings();
    }, [open, profile?.registered, loadListings]);

    const fail = (e: any, fallback: string) => {
        haptic.notification('error');
        // Был window.alert: системное окно поверх Mini App выглядит чужеродно
        // и блокирует интерфейс до нажатия «ОК». Тосты появились позже, здесь
        // просто приводим к общему виду.
        showToast(errorText(e, fallback), 'error');
    };

    if (!profile) return null;

    return (
        <div className={standalone ? 'seller-section seller-section--page' : 'seller-section glass-card'}>
            {!standalone && (
                <button className="seller-head" onClick={() => setOpen(!open)}>
                    <span className="seller-head-left">
                        <Store size={18} />
                        {profile.registered
                            ? t('Кабинет продавца', 'Seller cabinet')
                            : t('Продавать на площадке', 'Sell on the marketplace')}
                    </span>
                    {open ? <ChevronUp size={18} /> : <ChevronDown size={18} />}
                </button>
            )}

            {open && !profile.registered && (
                <SellerRegistration
                    language={language}
                    onDone={loadProfile}
                    onError={fail}
                    busy={busy}
                    setBusy={setBusy}
                />
            )}

            {open && profile.registered && (
                <>
                    <SellerSummary
                        profile={profile}
                        language={language}
                        onSaved={loadProfile}
                        onError={fail}
                    />
                    {/* Создание и правка — на странице объявления
                        (/my/listings/:id), здесь только список */}
                    <ListingsList
                        listings={listings}
                        language={language}
                        blocked={profile.status === 'banned' || profile.status === 'restricted'}
                    />
                </>
            )}
        </div>
    );
};

/* ------------------------------------------------------------------ */
/* Регистрация                                                         */
/* ------------------------------------------------------------------ */

const SellerRegistration: React.FC<{
    language: string;
    busy: boolean;
    setBusy: (v: boolean) => void;
    onDone: () => Promise<SellerProfile>;
    onError: (e: any, fallback: string) => void;
}> = ({ language, busy, setBusy, onDone, onError }) => {
    const { haptic } = useTelegram();
    const [name, setName] = useState('');
    const [accepted, setAccepted] = useState(false);
    const [termsOpen, setTermsOpen] = useState(false);
    const [termsText, setTermsText] = useState<string | null>(null);

    const t = (ru: string, en: string) => (language === 'ru' ? ru : en);

    const showTerms = async () => {
        setTermsOpen(!termsOpen);
        if (termsText === null) {
            try {
                const data = await termsApi.get();
                setTermsText(data.is_empty ? '' : data.text);
            } catch {
                setTermsText('');
            }
        }
    };

    const submit = async (e: React.FormEvent) => {
        e.preventDefault();
        setBusy(true);
        try {
            // Кошелька для выплат больше нет: деньги выводятся из профиля на
            // кошелёк, подключённый через TonConnect
            await p2pApi.registerSeller({
                display_name: name.trim(),
                accept_terms: accepted,
            });
            haptic.notification('success');
            await onDone();
        } catch (err) {
            onError(err, t('Не удалось зарегистрироваться', 'Registration failed'));
        } finally {
            setBusy(false);
        }
    };

    return (
        <form className="seller-form" onSubmit={submit}>
            <p className="seller-intro">
                {t(
                    'Разместите свои вещи в каталоге. Деньги покупателя удерживает площадка и передаёт вам после подтверждения получения.',
                    'List your items in the catalog. The platform holds the buyer’s money and releases it to you once receipt is confirmed.',
                )}
            </p>

            <label className="seller-label">
                {t('Название маркета', 'Store name')}
                <input
                    className="seller-input"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder={t('Видно покупателям', 'Visible to buyers')}
                    minLength={2}
                    maxLength={100}
                    required
                />
            </label>

            {/* Предупреждение до кнопки, а не после: сказать «имя навсегда»
                нужно до того, как человек его отправит */}
            <p className="seller-hint seller-hint--warn">
                <AlertTriangle size={13} />
                {t(
                    'Название навсегда: поменять его потом нельзя, и занять чужое тоже.',
                    'The name is permanent: it cannot be changed later, and a name someone already took is unavailable.',
                )}
            </p>

            <label className="seller-check">
                <input
                    type="checkbox"
                    checked={accepted}
                    onChange={(e) => setAccepted(e.target.checked)}
                />
                <span>
                    {t('Я принимаю ', 'I accept the ')}
                    <button type="button" className="seller-link" onClick={showTerms}>
                        {t('условия площадки', 'platform terms')}
                    </button>
                </span>
            </label>

            {termsOpen && (
                <pre className="seller-terms">
                    {termsText || t('Текст условий пока не заполнен.', 'Terms text is not filled in yet.')}
                </pre>
            )}

            <button className="seller-btn" type="submit" disabled={busy || !accepted}>
                {t('Стать продавцом', 'Become a seller')}
            </button>
        </form>
    );
};

/* ------------------------------------------------------------------ */
/* Сводка профиля                                                      */
/* ------------------------------------------------------------------ */

const SellerSummary: React.FC<{
    profile: SellerProfile;
    language: string;
    onSaved: () => Promise<SellerProfile>;
    onError: (e: any, fallback: string) => void;
}> = ({ profile, language, onSaved, onError }) => {
    const { haptic } = useTelegram();
    const [editing, setEditing] = useState(false);
    const [name, setName] = useState(profile.display_name ?? '');
    const [about, setAbout] = useState(profile.description ?? '');
    const [saving, setSaving] = useState(false);
    const avatarInput = useRef<HTMLInputElement | null>(null);

    const t = (ru: string, en: string) => (language === 'ru' ? ru : en);

    const save = async (e: React.FormEvent) => {
        e.preventDefault();
        setSaving(true);
        try {
            await p2pApi.updateSeller({
                // Запертое имя не отправляем вовсе: сервер такую правку
                // отклоняет, и сохранение описания падало бы вместе с ней
                display_name: profile.name_locked ? undefined : name.trim(),
                description: about.trim(),
            });
            haptic.notification('success');
            await onSaved();
            setEditing(false);
        } catch (err) {
            onError(err, t('Не удалось сохранить', 'Save failed'));
        } finally {
            setSaving(false);
        }
    };

    const pickAvatar = async (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0];
        // Сбрасываем сразу: иначе повторный выбор того же файла
        // не даст события
        e.target.value = '';
        if (!file) return;

        setSaving(true);
        try {
            await p2pApi.uploadSellerAvatar(file);
            haptic.notification('success');
            await onSaved();
        } catch (err) {
            onError(err, t('Не удалось загрузить логотип', 'Logo upload failed'));
        } finally {
            setSaving(false);
        }
    };

    return (
        <div className="seller-summary">
            {/* Логотип грузится вручную, а не тянется из Telegram, как у
                каналов: с личным аватаром магазин выглядит аккаунтом */}
            <div className="seller-brand">
                <button
                    className="seller-logo"
                    onClick={() => avatarInput.current?.click()}
                    disabled={saving}
                    aria-label={profile.avatar_url
                        ? t('Заменить логотип магазина', 'Replace the store logo')
                        : t('Загрузить логотип магазина', 'Upload a store logo')}
                >
                    {profile.avatar_url
                        ? <img src={profile.avatar_url} alt="" />
                        : <span aria-hidden="true">
                            {(profile.display_name ?? '?').trim().charAt(0).toUpperCase()}
                          </span>}
                    {/* Фотоаппарат, а не стрелка вверх: стрелка читается как
                        «отправить», а здесь выбирают картинку */}
                    <span className="seller-logo-edit" aria-hidden="true">
                        <Camera size={13} />
                    </span>
                </button>

                <div className="seller-brand-text">
                    <div className="seller-brand-name">{profile.display_name}</div>

                    {/* Продавец должен видеть свой магазин глазами покупателя:
                        иначе непонятно, что вообще даёт логотип и описание.

                        Link, а не <a href>: обычная ссылка перезагружала всё
                        приложение целиком — медленно, и тема при этом
                        сбрасывалась на светлую. */}
                    {profile.id && (
                        <Link className="seller-storefront" to={`/store/seller/${profile.id}`}>
                            {t('Открыть витрину', 'Open storefront')}
                            <ChevronRight size={14} />
                        </Link>
                    )}

                    {/* Отдельной кнопки «Заменить логотип» больше нет: кружок
                        со значком фотоаппарата и есть эта кнопка, а вторая
                        рядом дублировала его */}
                </div>
            </div>

            <input
                ref={avatarInput}
                type="file"
                accept="image/jpeg,image/png,image/webp"
                hidden
                onChange={pickAvatar}
            />

            <div className="seller-stats">
                <div className="seller-stat">
                    <span className="seller-stat-value">
                        {profile.rating != null ? (
                            <>
                                <Star size={13} fill="currentColor" />
                                {profile.rating.toFixed(1)}
                            </>
                        ) : '—'}
                    </span>
                    <span className="seller-stat-label">
                        {t('Рейтинг', 'Rating')}
                        {profile.rating_count ? ` (${profile.rating_count})` : ''}
                    </span>
                </div>
                <div className="seller-stat">
                    <span className="seller-stat-value">{profile.deals_completed ?? 0}</span>
                    <span className="seller-stat-label">{t('Сделок', 'Deals')}</span>
                </div>
                <div className="seller-stat">
                    <span className="seller-stat-value">
                        {formatTon(profile.balance_ton ?? '0')} <GramIcon title="Gram" />
                    </span>
                    <span className="seller-stat-label">{t('Заработано', 'Earned')}</span>
                </div>
            </div>

            {profile.status === 'banned' && (
                <div className="seller-warning">
                    <AlertTriangle size={14} />
                    {t('Аккаунт продавца заблокирован.', 'Seller account is blocked.')}
                </div>
            )}

            {profile.status === 'restricted' && (
                <div className="seller-warning">
                    <AlertTriangle size={14} />
                    {t('Размещение ограничено', 'Listing restricted')}
                    {profile.restricted_until &&
                        ` ${t('до', 'until')} ${new Date(profile.restricted_until).toLocaleDateString()}`}
                    {profile.restriction_reason ? `. ${profile.restriction_reason}` : ''}
                </div>
            )}

            {!editing ? (
                <div className="seller-identity">
                    <div className="seller-identity-text">
                        <div className="seller-name">{profile.display_name}</div>
                        {profile.description && (
                            <div className="seller-about">{profile.description}</div>
                        )}
                    </div>
                    <button className="seller-icon-btn" onClick={() => setEditing(true)}>
                        <Pencil size={14} />
                    </button>
                </div>
            ) : (
                <form className="seller-form seller-form-inline" onSubmit={save}>
                    {/* Название выбирается один раз. У магазина, заведённого
                        вместе с каналом, владелец его ещё не выбирал — там
                        поле есть, но с тем же предупреждением. */}
                    {profile.name_locked ? (
                        <div className="seller-locked">
                            <span className="seller-locked-value">{profile.display_name}</span>
                            <span className="seller-locked-note">
                                {t('Название магазина изменить нельзя',
                                   'The store name cannot be changed')}
                            </span>
                        </div>
                    ) : (
                        <>
                            <input
                                className="seller-input"
                                value={name}
                                onChange={(e) => setName(e.target.value)}
                                placeholder={t('Название маркета', 'Store name')}
                                minLength={2}
                                maxLength={100}
                                required
                            />
                            <p className="seller-hint seller-hint--warn">
                                <AlertTriangle size={13} />
                                {t(
                                    'Название навсегда: после сохранения поменять его нельзя.',
                                    'The name is permanent: once saved it cannot be changed.',
                                )}
                            </p>
                        </>
                    )}
                    <textarea
                        className="seller-input seller-textarea"
                        value={about}
                        onChange={(e) => setAbout(e.target.value)}
                        placeholder={t('О магазине (необязательно)', 'About the store (optional)')}
                        maxLength={1000}
                    />
                    <div className="seller-row-btns">
                        <button className="seller-btn" type="submit" disabled={saving}>
                            <Check size={14} />
                            {t('Сохранить', 'Save')}
                        </button>
                        <button
                            className="seller-btn seller-btn-ghost"
                            type="button"
                            onClick={() => setEditing(false)}
                        >
                            {t('Отмена', 'Cancel')}
                        </button>
                    </div>
                </form>
            )}

            {/* Вывод — в профиле: баланс у человека один на всё (продажи,
                подписки, возвраты, реферальные), и выводится он на кошелёк,
                подключённый через TonConnect. Отдельного кошелька для выплат
                у магазина больше нет */}
            {Number(profile.balance_ton ?? 0) > 0 && (
                <Link className="seller-payout seller-storefront" to="/profile">
                    {t('Вывести — в профиле', 'Withdraw in your profile')}
                    <ChevronRight size={14} />
                </Link>
            )}
        </div>
    );
};
