import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import {
    Store, Star, Plus, Upload, X, Send, Pencil, Trash2, Camera, ChevronRight,
    EyeOff, Eye, AlertTriangle, ChevronDown, ChevronUp, Check, Wallet,
} from 'lucide-react';
import { p2pApi, categoriesApi, termsApi, withdrawalsApi } from '@/api/client';
import { useAuthStore } from '@/store/authStore';
import { useToastStore, errorText } from '@/store/toastStore';
import { useTelegram } from '@/hooks/useTelegram';
import { CommissionNote } from '@/components/CommissionNote/CommissionNote';
import { usePublicSettings } from '@/hooks/usePublicSettings';
import type { Category, Listing, SellerProfile } from '@/types';
import './SellerCabinet.css';

/**
 * Статусы, в которых заявку ещё можно править — зеркало EDITABLE_STATUSES
 * на бэкенде. Там в наборе всегда были и approved с withdrawn, а здесь
 * стояли только два: сервер правку опубликованного товара принимал, а
 * кнопки «Править» у него не было — продавец мог только снять его с
 * продажи и завести заново, потеряв отзывы и историю.
 */
const EDITABLE = ['draft', 'rejected', 'approved', 'withdrawn'];

/** Столько фото принимает одна заявка — зеркало MAX_IMAGES_PER_LISTING */
const MAX_PHOTOS = 8;

/** Отправить на проверку можно только то, что там ещё не было или вернулось */
const SUBMITTABLE = ['draft', 'rejected'];

/**
 * Удалять опубликованное и ждущее проверки нельзя: сначала «снять с
 * продажи». Сервер это и так запрещает — кнопка просто не должна вести
 * в отказ.
 */
const DELETABLE = ['draft', 'rejected', 'withdrawn'];

interface DraftForm {
    name: string;
    name_en: string;
    description: string;
    description_en: string;
    price_usd: string;
    category_id: string;
}

const EMPTY_FORM: DraftForm = {
    name: '', name_en: '', description: '', description_en: '',
    price_usd: '', category_id: '',
};

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
    const [categories, setCategories] = useState<Category[]>([]);
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
                    <ListingManager
                        listings={listings}
                        categories={categories}
                        setCategories={setCategories}
                        language={language}
                        blocked={profile.status === 'banned' || profile.status === 'restricted'}
                        reload={loadListings}
                        onError={fail}
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
    const [wallet, setWallet] = useState('');
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
            await p2pApi.registerSeller({
                display_name: name.trim(),
                payout_wallet: wallet.trim(),
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
                {t('Имя продавца', 'Seller name')}
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

            <label className="seller-label">
                {t('Кошелёк TON для выплат', 'TON payout wallet')}
                <input
                    className="seller-input"
                    value={wallet}
                    onChange={(e) => setWallet(e.target.value)}
                    placeholder="UQ..."
                    minLength={10}
                    maxLength={80}
                    required
                />
            </label>

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
    const [wallet, setWallet] = useState(profile.payout_wallet ?? '');
    const [about, setAbout] = useState(profile.description ?? '');
    const [saving, setSaving] = useState(false);
    const avatarInput = useRef<HTMLInputElement | null>(null);

    const t = (ru: string, en: string) => (language === 'ru' ? ru : en);

    const save = async (e: React.FormEvent) => {
        e.preventDefault();
        setSaving(true);
        try {
            await p2pApi.updateSeller({
                display_name: name.trim(),
                payout_wallet: wallet.trim(),
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

                    {/* Настоящая кнопка вместо серой подписи: подпись выглядела
                        ярлыком, и было неясно, что логотип вообще куда-то
                        грузится — значок на кружке к тому же обрезался его
                        собственным скруглением */}
                    <button
                        className="seller-logo-btn"
                        onClick={() => avatarInput.current?.click()}
                        disabled={saving}
                    >
                        <Upload size={13} />
                        {profile.avatar_url
                            ? t('Заменить логотип', 'Replace the logo')
                            : t('Загрузить логотип', 'Upload a logo')}
                    </button>
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
                    <span className="seller-stat-value">{profile.balance_ton ?? '0'}</span>
                    <span className="seller-stat-label">{t('TON заработано', 'TON earned')}</span>
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
                        <div className="seller-wallet">{profile.payout_wallet}</div>
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
                    <input
                        className="seller-input"
                        value={name}
                        onChange={(e) => setName(e.target.value)}
                        minLength={2}
                        maxLength={100}
                        required
                    />
                    <textarea
                        className="seller-input seller-textarea"
                        value={about}
                        onChange={(e) => setAbout(e.target.value)}
                        placeholder={t('О магазине (необязательно)', 'About the store (optional)')}
                        maxLength={1000}
                    />
                    <input
                        className="seller-input"
                        value={wallet}
                        onChange={(e) => setWallet(e.target.value)}
                        minLength={10}
                        maxLength={80}
                        required
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

            {Number(profile.balance_ton ?? 0) > 0 && (
                <Payout
                    balance={profile.balance_ton ?? '0'}
                    wallet={profile.payout_wallet ?? ''}
                    language={language}
                    onDone={onSaved}
                    onError={onError}
                />
            )}
        </div>
    );
};

/**
 * Вывод заработка продавца.
 *
 * Деньги уходят не мгновенно: заявка замораживает сумму на счёте, а перевод
 * делает администрация вручную. Так написано и в тексте — иначе продавец ждёт
 * поступления сразу и идёт в поддержку.
 */
const Payout: React.FC<{
    balance: string;
    wallet: string;
    language: string;
    onDone: () => Promise<SellerProfile>;
    onError: (e: any, fallback: string) => void;
}> = ({ balance, wallet, language, onDone, onError }) => {
    const { haptic } = useTelegram();
    const [open, setOpen] = useState(false);
    const [amount, setAmount] = useState(balance);
    const [busy, setBusy] = useState(false);
    const [sent, setSent] = useState(false);

    const t = (ru: string, en: string) => (language === 'ru' ? ru : en);

    const submit = async (e: React.FormEvent) => {
        e.preventDefault();
        if (Number(amount) <= 0 || Number(amount) > Number(balance)) {
            onError(null, t('Некорректная сумма', 'Invalid amount'));
            return;
        }

        setBusy(true);
        try {
            await withdrawalsApi.requestWithdrawal({
                amount, wallet, currency: 'TON',
            });
            haptic.notification('success');
            setSent(true);
            setOpen(false);
            await onDone();
        } catch (err) {
            onError(err, t('Не удалось создать заявку', 'Request failed'));
        } finally {
            setBusy(false);
        }
    };

    if (sent) {
        return (
            <p className="seller-hint">
                {t(
                    'Заявка на вывод создана. Администрация переведёт средства на указанный кошелёк.',
                    'Withdrawal requested. The admins will send the funds to the wallet above.',
                )}
            </p>
        );
    }

    if (!open) {
        return (
            <div className="seller-payout">
                <button className="seller-btn" onClick={() => setOpen(true)}>
                    <Wallet size={14} />
                    {t('Вывести', 'Withdraw')} {balance} TON
                </button>
            </div>
        );
    }

    return (
        <form className="seller-form" onSubmit={submit}>
            <label className="seller-label">
                {t('Сумма к выводу', 'Amount')}
                <input
                    className="seller-input"
                    type="number"
                    step="0.000000001"
                    min="0.000000001"
                    max={balance}
                    value={amount}
                    onChange={(e) => setAmount(e.target.value)}
                    required
                />
            </label>

            <p className="seller-hint">
                {t('На кошелёк ', 'To wallet ')}
                <span className="seller-wallet-inline">{wallet}</span>
                {t('. Изменить его можно выше.', '. You can change it above.')}
            </p>

            <div className="seller-row-btns">
                <button className="seller-btn" type="submit" disabled={busy}>
                    {t('Отправить заявку', 'Request')}
                </button>
                <button
                    className="seller-btn seller-btn-ghost"
                    type="button"
                    onClick={() => setOpen(false)}
                >
                    {t('Отмена', 'Cancel')}
                </button>
            </div>
        </form>
    );
};

/* ------------------------------------------------------------------ */
/* Заявки                                                              */
/* ------------------------------------------------------------------ */

const ListingManager: React.FC<{
    listings: Listing[];
    categories: Category[];
    setCategories: (c: Category[]) => void;
    language: string;
    blocked: boolean;
    reload: () => Promise<void>;
    onError: (e: any, fallback: string) => void;
}> = ({ listings, categories, setCategories, language, blocked, reload, onError }) => {
    const { haptic } = useTelegram();
    const [creating, setCreating] = useState(false);
    const [editingId, setEditingId] = useState<string | null>(null);
    const commissions = usePublicSettings();
    const showToast = useToastStore((s) => s.show);

    // Фото, выбранные в форме создания. Заявки ещё нет, грузить некуда —
    // ждут до её создания. Раньше товар приходилось сначала создать, потом
    // найти в списке и только там добавить фотографии.
    const [pendingFiles, setPendingFiles] = useState<File[]>([]);
    const formInput = useRef<HTMLInputElement>(null);

    const previews = React.useMemo(
        () => pendingFiles.map((file) => URL.createObjectURL(file)),
        [pendingFiles],
    );

    // Ссылки на объекты держат файл в памяти, пока их не отозвать
    useEffect(() => () => { previews.forEach(URL.revokeObjectURL); }, [previews]);

    const onFormFiles = (e: React.ChangeEvent<HTMLInputElement>) => {
        const chosen = Array.from(e.target.files ?? []);
        // Сбрасываем сразу: иначе повторный выбор того же файла не даст события
        e.target.value = '';
        if (!chosen.length) return;

        const room = MAX_PHOTOS - pendingFiles.length;
        if (chosen.length > room) {
            showToast(t(
                `Больше ${MAX_PHOTOS} фото в одну заявку не поместится`,
                `A listing takes at most ${MAX_PHOTOS} photos`,
            ), 'info');
        }
        setPendingFiles((prev) => [...prev, ...chosen.slice(0, Math.max(room, 0))]);
    };

    const dropPending = (index: number) =>
        setPendingFiles((prev) => prev.filter((_, i) => i !== index));
    const [form, setForm] = useState<DraftForm>(EMPTY_FORM);
    const [busyId, setBusyId] = useState<string | null>(null);
    const fileInput = useRef<HTMLInputElement>(null);
    const [uploadTarget, setUploadTarget] = useState<string | null>(null);

    const t = (ru: string, en: string) => (language === 'ru' ? ru : en);

    useEffect(() => {
        if ((creating || editingId) && categories.length === 0) {
            categoriesApi.getCategories(language).then(setCategories).catch(() => setCategories([]));
        }
    }, [creating, editingId, categories.length, language, setCategories]);

    const statusLabel: Record<string, string> = {
        draft: t('Черновик', 'Draft'),
        pending: t('На модерации', 'In review'),
        approved: t('В продаже', 'Listed'),
        rejected: t('Отклонено', 'Rejected'),
        withdrawn: t('Снято с продажи', 'Withdrawn'),
        archived: t('В архиве', 'Archived'),
    };

    const startCreate = () => {
        setForm(EMPTY_FORM);
        setEditingId(null);
        setCreating(true);
    };

    // Правка уже одобренного товара уводит его на повторную проверку —
    // об этом надо сказать до нажатия «Сохранить», а не после
    const editingApproved = editingId !== null
        && listings.find((item) => item.id === editingId)?.status === 'approved';

    const closeForm = () => {
        setCreating(false);
        setEditingId(null);
        setPendingFiles([]);
    };

    const startEdit = (listing: Listing) => {
        setForm({
            name: listing.name,
            name_en: listing.name_en ?? '',
            description: listing.description,
            description_en: listing.description_en ?? '',
            price_usd: listing.price_usd,
            category_id: listing.category_id ?? '',
        });
        setCreating(false);
        setEditingId(listing.id);
    };

    const submitForm = async (e: React.FormEvent) => {
        e.preventDefault();
        setBusyId('form');
        try {
            const payload = {
                name: form.name.trim(),
                name_en: form.name_en.trim(),
                description: form.description.trim(),
                description_en: form.description_en.trim(),
                price_usd: form.price_usd,
                category_id: form.category_id || undefined,
            };

            if (editingId) {
                const result = await p2pApi.updateListing(editingId, payload);
                // Сервер снимает изменённый товар с витрины и отправляет его
                // на повторную проверку. Без этой строки он просто пропадал
                // из каталога, и продавец решал, что что-то сломалось.
                if (result?.remoderating) {
                    showToast(t(
                        'Товар снят с витрины и ушёл на повторную проверку',
                        'The item was unlisted and sent back for review',
                    ), 'info');
                }
            } else {
                const created = await p2pApi.createListing({ ...payload, accept_terms: true });

                // Заявка уже создана, поэтому неудачную загрузку фото нельзя
                // показывать как «не удалось сохранить заявку»: человек решит,
                // что товара нет, и заведёт его второй раз
                let failed = 0;
                for (const file of pendingFiles) {
                    try {
                        await p2pApi.uploadListingImage(created.id, file);
                    } catch {
                        failed += 1;
                    }
                }
                if (failed) {
                    showToast(t(
                        `Заявка создана, но ${failed} фото не загрузилось — добавьте их в списке`,
                        `The listing was created, but ${failed} photo(s) failed — add them from the list`,
                    ), 'error');
                }
            }

            haptic.notification('success');
            closeForm();
            setForm(EMPTY_FORM);
            await reload();
        } catch (err) {
            onError(err, t('Не удалось сохранить заявку', 'Failed to save the listing'));
        } finally {
            setBusyId(null);
        }
    };

    const pickFile = (listingId: string) => {
        setUploadTarget(listingId);
        fileInput.current?.click();
    };

    const onFileChosen = async (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0];
        // Сбрасываем сразу: иначе повторный выбор того же файла не даст события
        e.target.value = '';
        if (!file || !uploadTarget) return;

        setBusyId(uploadTarget);
        try {
            const result = await p2pApi.uploadListingImage(uploadTarget, file);
            // Фотография — такая же часть карточки, как текст, поэтому у
            // опубликованного товара она тоже уводит его на проверку
            if (result?.remoderating) {
                showToast(t(
                    'Товар снят с витрины и ушёл на повторную проверку',
                    'The item was unlisted and sent back for review',
                ), 'info');
            }
            haptic.notification('success');
            await reload();
        } catch (err) {
            onError(err, t('Не удалось загрузить фото', 'Upload failed'));
        } finally {
            setBusyId(null);
            setUploadTarget(null);
        }
    };

    const act = async (listing: Listing, fn: () => Promise<unknown>, confirmText?: string) => {
        if (confirmText && !window.confirm(confirmText)) return;
        setBusyId(listing.id);
        try {
            await fn();
            haptic.notification('success');
            await reload();
        } catch (err) {
            onError(err, t('Не удалось', 'Failed'));
        } finally {
            setBusyId(null);
        }
    };

    return (
        <div className="listings-block">
            <input
                ref={fileInput}
                type="file"
                accept="image/jpeg,image/png,image/webp"
                hidden
                onChange={onFileChosen}
            />

            <div className="listings-head">
                <h3>{t('Мои объявления', 'My listings')}</h3>
                {!creating && !editingId && !blocked && (
                    <button className="seller-btn seller-btn-sm" onClick={startCreate}>
                        <Plus size={14} />
                        {t('Добавить', 'Add')}
                    </button>
                )}
            </div>

            {(creating || editingId) && (
                <form className="seller-form" onSubmit={submitForm}>
                    <input
                        className="seller-input"
                        value={form.name}
                        onChange={(e) => setForm({ ...form, name: e.target.value })}
                        placeholder={t('Название по-русски', 'Title in Russian')}
                        minLength={3}
                        maxLength={500}
                        required
                    />
                    {/* Английские тексты обязательны: каталог двуязычный, и
                        без них покупатель с английским языком видел русское,
                        а переключатель языка на такой товар не влиял */}
                    <input
                        className="seller-input"
                        value={form.name_en}
                        onChange={(e) => setForm({ ...form, name_en: e.target.value })}
                        placeholder={t('Название по-английски', 'Title in English')}
                        minLength={3}
                        maxLength={500}
                        required
                    />
                    <textarea
                        className="seller-input seller-textarea"
                        value={form.description}
                        onChange={(e) => setForm({ ...form, description: e.target.value })}
                        placeholder={t('Описание по-русски (минимум 10 символов)',
                                       'Description in Russian (min 10 chars)')}
                        minLength={10}
                        maxLength={5000}
                        required
                    />
                    <textarea
                        className="seller-input seller-textarea"
                        value={form.description_en}
                        onChange={(e) => setForm({ ...form, description_en: e.target.value })}
                        placeholder={t('Описание по-английски (минимум 10 символов)',
                                       'Description in English (min 10 chars)')}
                        minLength={10}
                        maxLength={5000}
                        required
                    />
                    <div className="seller-row">
                        <input
                            className="seller-input"
                            type="number"
                            step="0.01"
                            min="0.01"
                            value={form.price_usd}
                            onChange={(e) => setForm({ ...form, price_usd: e.target.value })}
                            placeholder={t('Цена, $', 'Price, $')}
                            required
                        />
                        <select
                            className="seller-input"
                            value={form.category_id}
                            onChange={(e) => setForm({ ...form, category_id: e.target.value })}
                        >
                            <option value="">{t('Категория', 'Category')}</option>
                            {categories.map((c) => (
                                <option key={c.id} value={c.id}>{c.name}</option>
                            ))}
                        </select>
                    </div>

                    {/* Фото выбирают здесь же. Заявки ещё нет, поэтому файлы
                        ждут до её создания и уходят сразу после — раньше товар
                        надо было сначала создать, потом найти в списке и
                        только там добавить фотографии. */}
                    {creating && (
                        <div className="form-photos">
                            <input
                                ref={formInput}
                                type="file"
                                accept="image/jpeg,image/png,image/webp"
                                multiple
                                hidden
                                onChange={onFormFiles}
                            />

                            {previews.length > 0 && (
                                <div className="form-photos-list">
                                    {previews.map((url, index) => (
                                        <div key={url} className="form-photo">
                                            <img src={url} alt="" />
                                            <button
                                                type="button"
                                                className="thumb-remove"
                                                onClick={() => dropPending(index)}
                                                aria-label={t('Убрать фото', 'Remove photo')}
                                            >
                                                <X size={11} />
                                            </button>
                                        </div>
                                    ))}
                                </div>
                            )}

                            <button
                                className="seller-btn seller-btn-sm seller-btn-ghost"
                                type="button"
                                onClick={() => formInput.current?.click()}
                                disabled={pendingFiles.length >= MAX_PHOTOS}
                            >
                                <Upload size={13} />
                                {previews.length
                                    ? t('Ещё фото', 'More photos')
                                    : t('Добавить фото', 'Add photos')}
                            </button>
                        </div>
                    )}

                    {/* Сколько удержит площадка — рядом с полем цены, а не
                        в условиях мелким шрифтом: процент нужен ровно в тот
                        момент, когда цену назначают */}
                    <CommissionNote
                        price={form.price_usd}
                        bp={commissions?.commission_p2p_bp ?? null}
                    />

                    {editingApproved && (
                        <p className="seller-hint seller-hint--warn">
                            <AlertTriangle size={13} />
                            {t(
                                'Товар уже в каталоге. После сохранения он уйдёт на повторную проверку и пропадёт с витрины до её окончания.',
                                'This item is live. Saving sends it back for review and hides it from the catalog until that is done.',
                            )}
                        </p>
                    )}

                    <div className="seller-row-btns">
                        <button className="seller-btn" type="submit" disabled={busyId === 'form'}>
                            {editingId ? t('Сохранить', 'Save') : t('Создать', 'Create')}
                        </button>
                        <button
                            className="seller-btn seller-btn-ghost"
                            type="button"
                            onClick={closeForm}
                        >
                            {t('Отмена', 'Cancel')}
                        </button>
                    </div>

                    {!editingId && (
                        <p className="seller-hint">
                            {previews.length
                                ? t(
                                    'Фото загрузятся вместе с заявкой. Дальше останется отправить её на модерацию.',
                                    'Photos upload together with the listing. Then just submit it for review.',
                                )
                                : t(
                                    'Без фото заявку не примут — добавьте хотя бы одно.',
                                    'A listing needs at least one photo.',
                                )}
                        </p>
                    )}
                </form>
            )}

            {listings.length === 0 && !creating && (
                <p className="seller-empty">
                    {t('Объявлений пока нет.', 'No listings yet.')}
                </p>
            )}

            <div className="listings-list">
                {listings.map((listing) => {
                    const editable = EDITABLE.includes(listing.status);
                    const submittable = SUBMITTABLE.includes(listing.status);
                    const deletable = DELETABLE.includes(listing.status);
                    const working = busyId === listing.id;

                    return (
                        <div key={listing.id} className={`listing-item listing-${listing.status}`}>
                            <div className="listing-head">
                                <span className="listing-name">{listing.name}</span>
                                <span className={`listing-badge badge-${listing.status}`}>
                                    {statusLabel[listing.status] ?? listing.status}
                                </span>
                            </div>

                            <div className="listing-price">${listing.price_usd}</div>

                            {listing.status === 'rejected' && listing.moderation_comment && (
                                <div className="listing-reject">
                                    <AlertTriangle size={13} />
                                    {listing.moderation_comment}
                                </div>
                            )}

                            {listing.images.length > 0 && (
                                <div className="listing-images">
                                    {listing.images.map((img) => (
                                        <div key={img.id} className="listing-thumb">
                                            <img src={img.url} alt="" />
                                            {editable && (
                                                <button
                                                    className="thumb-remove"
                                                    disabled={working}
                                                    onClick={() => act(listing, () =>
                                                        p2pApi.deleteListingImage(listing.id, img.id))}
                                                >
                                                    <X size={11} />
                                                </button>
                                            )}
                                        </div>
                                    ))}
                                </div>
                            )}

                            <div className="listing-actions">
                                {editable && (
                                    <>
                                        <button
                                            className="seller-btn seller-btn-sm seller-btn-ghost"
                                            disabled={working}
                                            onClick={() => pickFile(listing.id)}
                                        >
                                            <Upload size={13} />
                                            {t('Фото', 'Photo')}
                                        </button>
                                        <button
                                            className="seller-btn seller-btn-sm seller-btn-ghost"
                                            disabled={working}
                                            onClick={() => startEdit(listing)}
                                        >
                                            <Pencil size={13} />
                                            {t('Править', 'Edit')}
                                        </button>
                                    </>
                                )}

                                {submittable && (
                                    <button
                                        className="seller-btn seller-btn-sm"
                                        disabled={working || listing.images.length === 0 || blocked}
                                        onClick={() => act(listing, () => p2pApi.submitListing(listing.id))}
                                    >
                                        <Send size={13} />
                                        {t('На модерацию', 'Submit')}
                                    </button>
                                )}

                                {deletable && (
                                    <button
                                        className="seller-btn seller-btn-sm seller-btn-danger"
                                        disabled={working}
                                        onClick={() => act(
                                            listing,
                                            () => p2pApi.deleteListing(listing.id),
                                            t('Удалить объявление?', 'Delete this listing?'),
                                        )}
                                    >
                                        <Trash2 size={13} />
                                    </button>
                                )}

                                {listing.status === 'approved' && (
                                    <button
                                        className="seller-btn seller-btn-sm seller-btn-ghost"
                                        disabled={working}
                                        onClick={() => act(
                                            listing,
                                            () => p2pApi.withdrawListing(listing.id),
                                            t('Снять товар с продажи?', 'Remove this item from sale?'),
                                        )}
                                    >
                                        <EyeOff size={13} />
                                        {t('Снять с продажи', 'Unlist')}
                                    </button>
                                )}

                                {listing.status === 'withdrawn' && (
                                    <button
                                        className="seller-btn seller-btn-sm"
                                        disabled={working || blocked}
                                        onClick={() => act(listing, () => p2pApi.republishListing(listing.id))}
                                    >
                                        <Eye size={13} />
                                        {t('Вернуть в продажу', 'Relist')}
                                    </button>
                                )}
                            </div>

                            {submittable && listing.images.length === 0 && (
                                <p className="seller-hint">
                                    {t(
                                        'Добавьте хотя бы одно фото — без него заявку не примут.',
                                        'Add at least one photo — the listing cannot be submitted without it.',
                                    )}
                                </p>
                            )}
                        </div>
                    );
                })}
            </div>
        </div>
    );
};
