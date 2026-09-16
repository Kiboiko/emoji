import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
    Store, Star, Plus, Upload, X, Send, Pencil, Trash2,
    EyeOff, Eye, AlertTriangle, ChevronDown, ChevronUp, Check,
} from 'lucide-react';
import { p2pApi, categoriesApi, termsApi } from '@/api/client';
import { useAuthStore } from '@/store/authStore';
import { useTelegram } from '@/hooks/useTelegram';
import type { Category, Listing, SellerProfile } from '@/types';
import './SellerCabinet.css';

/** Статусы, в которых заявку ещё можно править — зеркало EDITABLE_STATUSES на бэкенде */
const EDITABLE = ['draft', 'rejected'];

interface DraftForm {
    name: string;
    description: string;
    price_usd: string;
    category_id: string;
}

const EMPTY_FORM: DraftForm = { name: '', description: '', price_usd: '', category_id: '' };

/**
 * Кабинет продавца.
 *
 * Свёрнут по умолчанию: большинству пользователей продавать нечего, и
 * разворачивать форму на пол-экрана всем подряд незачем.
 */
export const SellerCabinet: React.FC = () => {
    const { language } = useAuthStore();
    const { haptic } = useTelegram();

    const [open, setOpen] = useState(false);
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
        const detail = e?.response?.data?.detail;
        window.alert(typeof detail === 'string' ? detail : fallback);
    };

    if (!profile) return null;

    return (
        <div className="seller-section glass-card">
            <button className="seller-head" onClick={() => setOpen(!open)}>
                <span className="seller-head-left">
                    <Store size={18} />
                    {profile.registered
                        ? t('Кабинет продавца', 'Seller cabinet')
                        : t('Продавать на площадке', 'Sell on the marketplace')}
                </span>
                {open ? <ChevronUp size={18} /> : <ChevronDown size={18} />}
            </button>

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
    const [saving, setSaving] = useState(false);

    const t = (ru: string, en: string) => (language === 'ru' ? ru : en);

    const save = async (e: React.FormEvent) => {
        e.preventDefault();
        setSaving(true);
        try {
            await p2pApi.updateSeller({
                display_name: name.trim(),
                payout_wallet: wallet.trim(),
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

    return (
        <div className="seller-summary">
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
                    <div>
                        <div className="seller-name">{profile.display_name}</div>
                        <div className="seller-wallet">{profile.payout_wallet}</div>
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
                <p className="seller-hint">
                    {t(
                        'Заработок выводится администрацией на указанный кошелёк. Напишите в поддержку для вывода.',
                        'Earnings are paid out by the admins to the wallet above. Contact support to withdraw.',
                    )}
                </p>
            )}
        </div>
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

    const startEdit = (listing: Listing) => {
        setForm({
            name: listing.name,
            description: listing.description,
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
                description: form.description.trim(),
                price_usd: form.price_usd,
                category_id: form.category_id || undefined,
            };

            if (editingId) {
                await p2pApi.updateListing(editingId, payload);
            } else {
                await p2pApi.createListing({ ...payload, accept_terms: true });
            }

            haptic.notification('success');
            setCreating(false);
            setEditingId(null);
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
            await p2pApi.uploadListingImage(uploadTarget, file);
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
                        placeholder={t('Название', 'Title')}
                        minLength={3}
                        maxLength={500}
                        required
                    />
                    <textarea
                        className="seller-input seller-textarea"
                        value={form.description}
                        onChange={(e) => setForm({ ...form, description: e.target.value })}
                        placeholder={t('Описание (минимум 10 символов)', 'Description (min 10 chars)')}
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

                    <div className="seller-row-btns">
                        <button className="seller-btn" type="submit" disabled={busyId === 'form'}>
                            {editingId ? t('Сохранить', 'Save') : t('Создать', 'Create')}
                        </button>
                        <button
                            className="seller-btn seller-btn-ghost"
                            type="button"
                            onClick={() => { setCreating(false); setEditingId(null); }}
                        >
                            {t('Отмена', 'Cancel')}
                        </button>
                    </div>

                    {!editingId && (
                        <p className="seller-hint">
                            {t(
                                'После создания добавьте фото и отправьте на модерацию.',
                                'After creating, add photos and submit for review.',
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
                                        <button
                                            className="seller-btn seller-btn-sm"
                                            disabled={working || listing.images.length === 0 || blocked}
                                            onClick={() => act(listing, () => p2pApi.submitListing(listing.id))}
                                        >
                                            <Send size={13} />
                                            {t('На модерацию', 'Submit')}
                                        </button>
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
                                    </>
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

                            {editable && listing.images.length === 0 && (
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
