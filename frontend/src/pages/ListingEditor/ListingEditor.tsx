import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useLocation, useNavigate, useParams } from 'react-router-dom';
import {
    AlertTriangle, ArrowLeft, ChevronDown, EyeOff, Minus, Plus, RotateCcw, ShieldCheck, X,
} from 'lucide-react';
import { categoriesApi, p2pApi } from '@/api/client';
import { useAuthStore } from '@/store/authStore';
import { useToastStore, errorText } from '@/store/toastStore';
import { useTelegram } from '@/hooks/useTelegram';
import { useBarHeight } from '@/hooks/useBarHeight';
import { usePublicSettings } from '@/hooks/usePublicSettings';
import { CommissionNote } from '@/components/CommissionNote/CommissionNote';
import { AutoTextarea } from '@/components/AutoTextarea/AutoTextarea';
import { listingBadge } from '@/components/SellerCabinet/ListingsList';
import type { Category, Listing, SellerProfile } from '@/types';
import '@/pages/DealPage/DealPage.css';
import './ListingEditor.css';

/** Столько фото принимает одно объявление — зеркало MAX_IMAGES_PER_LISTING */
const MAX_PHOTOS = 8;

/**
 * В каких статусах объявление ещё правится — зеркало EDITABLE_STATUSES на
 * бэкенде. На модерации — нет: пока модератор смотрит, текст под ним
 * меняться не должен.
 */
const EDITABLE = ['draft', 'rejected', 'approved', 'withdrawn'];
const SUBMITTABLE = ['draft', 'rejected'];
const DELETABLE = ['draft', 'rejected', 'withdrawn'];

interface Form {
    name: string;
    name_en: string;
    description: string;
    description_en: string;
    price_usd: string;
    quantity: number;
    category_id: string;
}

const EMPTY: Form = {
    name: '', name_en: '', description: '', description_en: '',
    price_usd: '', quantity: 1, category_id: '',
};

const formOf = (l: Listing): Form => ({
    name: l.name,
    name_en: l.name_en ?? '',
    description: l.description,
    description_en: l.description_en ?? '',
    price_usd: l.price_usd,
    quantity: l.quantity ?? 1,
    category_id: l.category_id ?? '',
});

type Confirm = 'withdraw' | 'delete' | null;

/**
 * Объявление: просмотр, правка, создание.
 *
 * Раньше правка жила внутри списка — форма разворачивалась посреди карточек,
 * и при десятке товаров было непонятно, что именно правишь. Теперь у
 * объявления своя страница: фото, цифры продаж, поля и действия по статусу.
 */
export const ListingEditor: React.FC = () => {
    const { listingId = 'new' } = useParams();
    const creating = listingId === 'new';
    const navigate = useNavigate();
    const location = useLocation();
    const { language, accessToken } = useAuthStore();
    const { haptic } = useTelegram();
    const showToast = useToastStore((s) => s.show);
    const settings = usePublicSettings();
    const t = useCallback((ru: string, en: string) => (language === 'ru' ? ru : en), [language]);

    const [listing, setListing] = useState<Listing | null>(null);
    const [profile, setProfile] = useState<SellerProfile | null>(null);
    const [categories, setCategories] = useState<Category[]>([]);
    const [form, setForm] = useState<Form>(EMPTY);
    const [failed, setFailed] = useState<string | null>(null);
    const [busy, setBusy] = useState(false);
    const [englishOpen, setEnglishOpen] = useState(creating);
    const [confirm, setConfirm] = useState<Confirm>(null);
    const [cover, setCover] = useState(0);
    const [pending, setPending] = useState<File[]>([]);
    const fileInput = useRef<HTMLInputElement>(null);
    const [barRef, barStyle] = useBarHeight();

    const previews = useMemo(() => pending.map((f) => URL.createObjectURL(f)), [pending]);
    useEffect(() => () => { previews.forEach(URL.revokeObjectURL); }, [previews]);

    const load = useCallback(async () => {
        try {
            const [me, all] = await Promise.all([
                p2pApi.getSellerProfile() as Promise<SellerProfile>,
                creating ? Promise.resolve([] as Listing[]) : p2pApi.getMyListings() as Promise<Listing[]>,
            ]);
            setProfile(me);
            if (!creating) {
                const found = all.find((l) => l.id === listingId);
                if (!found) {
                    setFailed(t('Объявление не найдено', 'Listing not found'));
                    return;
                }
                setListing(found);
                setForm(formOf(found));
            }
            setFailed(null);
        } catch (e) {
            setFailed(errorText(e, t('Не удалось загрузить объявление', 'Failed to load the listing')));
        }
    }, [creating, listingId, t]);

    useEffect(() => {
        if (accessToken) load();
    }, [accessToken, load]);

    useEffect(() => {
        categoriesApi.getCategories(language).then(setCategories).catch(() => setCategories([]));
    }, [language]);

    const goBack = () => (location.key !== 'default' ? navigate(-1) : navigate('/my/listings'));

    const status = listing?.status ?? 'draft';
    const editable = creating || EDITABLE.includes(status);
    const blocked = profile?.status === 'banned' || profile?.status === 'restricted';
    const original = listing ? formOf(listing) : EMPTY;
    const dirty = creating || (Object.keys(form) as (keyof Form)[]).some((k) => String(form[k]).trim() !== String(original[k]).trim());
    // Количество модерации не требует — всё остальное у опубликованного уводит на проверку
    const moderatedChange = listing?.status === 'approved' && (Object.keys(form) as (keyof Form)[])
        .some((k) => k !== 'quantity' && String(form[k]).trim() !== String(original[k]).trim());
    const englishMissing = !form.name_en.trim() || !form.description_en.trim();

    const set = <K extends keyof Form>(key: K, value: Form[K]) => setForm((prev) => ({ ...prev, [key]: value }));

    const run = async (action: () => Promise<unknown>, success?: string) => {
        setBusy(true);
        try {
            await action();
            haptic.notification('success');
            if (success) showToast(success, 'success');
        } catch (e) {
            haptic.notification('error');
            showToast(errorText(e, t('Не получилось', 'Something went wrong')), 'error');
            throw e;
        } finally {
            setBusy(false);
        }
    };

    const payload = () => ({
        name: form.name.trim(),
        name_en: form.name_en.trim(),
        description: form.description.trim(),
        description_en: form.description_en.trim(),
        price_usd: form.price_usd,
        quantity: Math.max(1, form.quantity),
        category_id: form.category_id || undefined,
    });

    const validate = (): boolean => {
        const f = payload();
        if (f.name.length < 3 || f.description.length < 10) {
            showToast(t('Название — от 3 символов, описание — от 10', 'Title: 3+ characters, description: 10+'), 'error');
            return false;
        }
        if (f.name_en.length < 3 || f.description_en.length < 10) {
            setEnglishOpen(true);
            showToast(t('Заполните английскую версию — каталог двуязычный', 'Fill in the English version — the catalog is bilingual'), 'error');
            return false;
        }
        if (!(Number(f.price_usd) > 0)) {
            showToast(t('Укажите цену', 'Set a price'), 'error');
            return false;
        }
        return true;
    };

    const save = async () => {
        if (!validate()) return;
        if (creating) {
            await run(async () => {
                const created = await p2pApi.createListing({ ...payload(), accept_terms: true });
                // Объявление уже создано: неудачное фото — не повод говорить
                // «не сохранилось», иначе человек заведёт товар второй раз
                let lost = 0;
                for (const file of pending) {
                    try {
                        await p2pApi.uploadListingImage(created.id, file);
                    } catch {
                        lost += 1;
                    }
                }
                if (lost) {
                    showToast(t(`Объявление создано, но ${lost} фото не загрузилось`, `Created, but ${lost} photo(s) failed`), 'error');
                }
                navigate(`/my/listings/${created.id}`, { replace: true });
            }, t('Объявление создано. Отправьте его на модерацию', 'Created. Now submit it for review')).catch(() => undefined);
            return;
        }
        await run(async () => {
            const result = await p2pApi.updateListing(listing!.id, payload());
            if (result?.remoderating) {
                showToast(t('Объявление ушло на повторную проверку', 'The listing went back for review'), 'info');
            }
            await load();
        }, t('Сохранено', 'Saved')).catch(() => undefined);
    };

    const onFiles = async (e: React.ChangeEvent<HTMLInputElement>) => {
        const chosen = Array.from(e.target.files ?? []);
        // Сбрасываем сразу: повторный выбор того же файла иначе не даст события
        e.target.value = '';
        if (!chosen.length) return;
        const have = creating ? pending.length : (listing?.images.length ?? 0);
        const room = MAX_PHOTOS - have;
        if (chosen.length > room) {
            showToast(t(`Больше ${MAX_PHOTOS} фото не поместится`, `At most ${MAX_PHOTOS} photos`), 'info');
        }
        const take = chosen.slice(0, Math.max(room, 0));
        if (creating) {
            setPending((prev) => [...prev, ...take]);
            return;
        }
        await run(async () => {
            for (const file of take) {
                const result = await p2pApi.uploadListingImage(listing!.id, file);
                // Фото — тоже предмет модерации: у опубликованного уводит на проверку
                if (result?.remoderating) {
                    showToast(t('Объявление ушло на повторную проверку', 'The listing went back for review'), 'info');
                }
            }
            await load();
        }).catch(() => undefined);
    };

    const removePhoto = async (index: number) => {
        if (creating) {
            setPending((prev) => prev.filter((_, i) => i !== index));
            setCover(0);
            return;
        }
        const image = listing?.images[index];
        if (!image) return;
        await run(async () => {
            await p2pApi.deleteListingImage(listing!.id, image.id);
            setCover(0);
            await load();
        }).catch(() => undefined);
    };

    const photos = creating ? previews : (listing?.images.map((i) => i.url) ?? []);

    if (failed) {
        return (
            <div className="dpage">
                <div className="container dpage-body">
                    <button className="btn-back" onClick={goBack}>
                        <ArrowLeft size={20} />
                        <span>{t('Мои объявления', 'My listings')}</span>
                    </button>
                    <p className="dpage-muted">{failed}</p>
                </div>
            </div>
        );
    }

    if (!profile || (!creating && !listing)) {
        return (
            <div className="dpage">
                <div className="container dpage-body">
                    <div className="skeleton dpage-skeleton-photo" />
                    <div className="skeleton dpage-skeleton-line" />
                </div>
            </div>
        );
    }

    const badge = listing ? listingBadge(listing, t) : null;
    const submittable = !creating && SUBMITTABLE.includes(status);
    const deletable = !creating && DELETABLE.includes(status);

    // Главная кнопка панели — по статусу: несохранённое сначала сохранить
    let primary: { label: string; onClick: () => void; disabled?: boolean } | null = null;
    if (creating) {
        primary = { label: t('Создать объявление', 'Create listing'), onClick: save, disabled: blocked };
    } else if (editable && dirty) {
        primary = { label: t('Сохранить', 'Save'), onClick: save };
    } else if (submittable) {
        primary = {
            label: t('Отправить на модерацию', 'Submit for review'),
            disabled: !listing!.images.length || blocked,
            onClick: () => run(async () => { await p2pApi.submitListing(listing!.id); await load(); },
                t('Отправлено на модерацию', 'Submitted for review')).catch(() => undefined),
        };
    } else if (status === 'withdrawn') {
        primary = {
            label: t('Вернуть в продажу', 'Back on sale'),
            disabled: blocked,
            onClick: () => run(async () => { await p2pApi.republishListing(listing!.id); await load(); },
                t('Снова в продаже', 'Back on sale')).catch(() => undefined),
        };
    } else if (status === 'approved') {
        primary = { label: t('Сохранить', 'Save'), onClick: save, disabled: true };
    }

    let secondary: React.ReactNode = null;
    if (status === 'approved' && !creating && !(listing!.stock === 0 && !listing!.reserved)) {
        secondary = (
            <button type="button" className="dchat-btn ghost" onClick={() => setConfirm('withdraw')} disabled={busy}>
                <EyeOff size={17} />
                {t('Снять с продажи', 'Unlist')}
            </button>
        );
    } else if (deletable) {
        secondary = (
            <button type="button" className="dchat-btn ghost led-delete" onClick={() => setConfirm('delete')} disabled={busy}>
                {t('Удалить', 'Delete')}
            </button>
        );
    }

    const hasBar = Boolean(primary || secondary);

    return (
        <div className="dpage" style={hasBar ? barStyle : undefined}>
            <input
                ref={fileInput}
                type="file"
                accept="image/jpeg,image/png,image/webp"
                multiple
                hidden
                onChange={onFiles}
            />
            <div className={`container dpage-body${hasBar ? ' with-bar' : ''}`}>
                <div className="dpage-top">
                    <button className="btn-back" onClick={goBack}>
                        <ArrowLeft size={20} />
                        <span>{t('Мои объявления', 'My listings')}</span>
                    </button>
                    {badge
                        ? <span className={`dchat-chip ${badge.tone}`}>{badge.label}</span>
                        : <span className="dpage-number">{t('Новое объявление', 'New listing')}</span>}
                </div>

                {/* Фото: главное крупно, ниже все с кнопкой «убрать» и «добавить» */}
                <div className="led-gallery">
                    <div className="led-cover">
                        {photos[cover] ? <img src={photos[cover]} alt="" /> : (
                            <button type="button" className="led-cover-empty" onClick={() => fileInput.current?.click()} disabled={!editable}>
                                <Plus size={28} />
                                {t('Добавьте фото товара', 'Add item photos')}
                            </button>
                        )}
                    </div>
                    {(photos.length > 0 || editable) && (
                        <div className="led-thumbs">
                            {photos.map((url, index) => (
                                <div key={url} className={`led-thumb${index === cover ? ' is-cover' : ''}`}>
                                    <button type="button" className="led-thumb-pick" onClick={() => setCover(index)} aria-label={t('Показать фото', 'Show photo')}>
                                        <img src={url} alt="" />
                                    </button>
                                    {editable && (
                                        <button
                                            type="button"
                                            className="led-thumb-remove"
                                            onClick={() => removePhoto(index)}
                                            disabled={busy}
                                            aria-label={t('Убрать фото', 'Remove photo')}
                                        >
                                            <X size={12} />
                                        </button>
                                    )}
                                </div>
                            ))}
                            {editable && photos.length < MAX_PHOTOS && (
                                <button
                                    type="button"
                                    className="led-thumb-add"
                                    onClick={() => fileInput.current?.click()}
                                    disabled={busy}
                                    aria-label={t('Добавить фото', 'Add photo')}
                                >
                                    <Plus size={20} />
                                </button>
                            )}
                        </div>
                    )}
                    <span className="led-hint">
                        {t(`До ${MAX_PHOTOS} фото. Первое — обложка в каталоге.`, `Up to ${MAX_PHOTOS} photos. The first is the catalog cover.`)}
                    </span>
                </div>

                {listing && ['approved', 'withdrawn'].includes(listing.status) && (
                    <div className="led-stats">
                        <div><strong>{listing.stock ?? 0}</strong><span>{t('в продаже', 'on sale')}</span></div>
                        <div><strong>{listing.sold}</strong><span>{t('продано', 'sold')}</span></div>
                        <div><strong>{listing.reserved}</strong><span>{t('ждёт оплаты', 'awaiting payment')}</span></div>
                    </div>
                )}

                {listing?.status === 'rejected' && listing.moderation_comment && (
                    <div className="led-banner danger">
                        <AlertTriangle size={18} />
                        <span>
                            <strong>{t('Отклонено модератором: ', 'Rejected: ')}</strong>
                            {listing.moderation_comment}
                        </span>
                    </div>
                )}

                {listing?.status === 'pending' && (
                    <div className="led-banner">
                        <ShieldCheck size={18} />
                        <span>{t('Объявление на модерации. Править его можно после решения модератора.', 'The listing is in review. You can edit it once a moderator decides.')}</span>
                    </div>
                )}

                <fieldset className="led-form" disabled={!editable || busy}>
                    <label className="led-field">
                        {t('Название', 'Title')}
                        <input
                            value={form.name}
                            onChange={(e) => set('name', e.target.value)}
                            maxLength={500}
                            placeholder={t('Например: Elden Ring · ключ Steam', 'E.g. Elden Ring · Steam key')}
                        />
                    </label>

                    <label className="led-field">
                        {t('Описание', 'Description')}
                        <AutoTextarea
                            value={form.description}
                            onChange={(e) => set('description', e.target.value)}
                            maxLength={5000}
                            placeholder={t('Что получит покупатель и как', 'What the buyer gets and how')}
                        />
                    </label>

                    <div className="led-pair">
                        <label className="led-field">
                            {t('Цена, $', 'Price, $')}
                            <input
                                inputMode="decimal"
                                value={form.price_usd}
                                onChange={(e) => set('price_usd', e.target.value.replace(',', '.'))}
                                placeholder="0"
                            />
                        </label>
                        <div className="led-field">
                            {t('Количество', 'Quantity')}
                            <div className="led-stepper">
                                <button type="button" onClick={() => set('quantity', Math.max(1, form.quantity - 1))} aria-label={t('Меньше', 'Less')}>
                                    <Minus size={18} />
                                </button>
                                <span>{form.quantity}</span>
                                <button type="button" onClick={() => set('quantity', form.quantity + 1)} aria-label={t('Больше', 'More')}>
                                    <Plus size={18} />
                                </button>
                            </div>
                        </div>
                    </div>
                    <CommissionNote price={form.price_usd} bp={settings?.commission_p2p_bp ?? null} />

                    <label className="led-field">
                        {t('Категория', 'Category')}
                        <select value={form.category_id} onChange={(e) => set('category_id', e.target.value)}>
                            <option value="">{t('Без категории', 'No category')}</option>
                            {categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                        </select>
                    </label>

                    {/* Английская версия обязательна — каталог двуязычный, — но
                        нужна реже: свёрнута, пока заполнена */}
                    <div className={`led-english${englishOpen ? ' is-open' : ''}`}>
                        <button type="button" className="led-english-head" onClick={() => setEnglishOpen(!englishOpen)} aria-expanded={englishOpen}>
                            <span>
                                <strong>{t('Английская версия', 'English version')}</strong>
                                <small className={englishMissing ? 'warn' : ''}>
                                    {englishMissing
                                        ? t('Нужно заполнить — без неё объявление не сохранится', 'Required — the listing will not save without it')
                                        : t('Название и описание для английского каталога', 'Title and description for the English catalog')}
                                </small>
                            </span>
                            <ChevronDown size={18} />
                        </button>
                        {englishOpen && (
                            <div className="led-english-body">
                                <label className="led-field">
                                    {t('Название по-английски', 'Title in English')}
                                    <input value={form.name_en} onChange={(e) => set('name_en', e.target.value)} maxLength={500} />
                                </label>
                                <label className="led-field">
                                    {t('Описание по-английски', 'Description in English')}
                                    <AutoTextarea value={form.description_en} onChange={(e) => set('description_en', e.target.value)} maxLength={5000} />
                                </label>
                            </div>
                        )}
                    </div>
                </fieldset>

                {(creating || ['draft', 'rejected'].includes(status)) ? (
                    <div className="led-banner">
                        <ShieldCheck size={18} />
                        <span>
                            {t(
                                'После создания объявление проверит модератор — без фото его не примут. Количество потом можно менять без проверки.',
                                'A moderator reviews the listing before it goes live — it needs at least one photo. Quantity can be changed later without review.',
                            )}
                        </span>
                    </div>
                ) : status === 'approved' && (
                    <div className={`led-banner${moderatedChange ? ' warn' : ''}`}>
                        <AlertTriangle size={18} />
                        <span>
                            {t(
                                'Название, описание, цену и фото проверяет модератор: после их правки объявление снова уйдёт на проверку. Количество меняется сразу.',
                                'Title, description, price and photos are moderated: editing them sends the listing back for review. Quantity changes instantly.',
                            )}
                        </span>
                    </div>
                )}
            </div>

            {hasBar && (
                <div ref={barRef} className={`dpage-bar led-bar${primary && secondary ? '' : ' single'}`}>
                    {secondary}
                    {primary && (
                        <button type="button" className="dchat-btn primary" onClick={primary.onClick} disabled={busy || primary.disabled}>
                            {primary.label}
                        </button>
                    )}
                </div>
            )}

            {confirm && listing && (
                <div className="dsheet-layer">
                    <div className="dchat-sheet-host" onClick={(e) => { if (e.target === e.currentTarget) setConfirm(null); }}>
                        <div className="dchat-sheet" role="dialog" aria-modal="true">
                            <span className="dchat-grab" />
                            {confirm === 'withdraw' ? (
                                <>
                                    <h3>{t('Снять с продажи?', 'Unlist this item?')}</h3>
                                    <ul className="led-points">
                                        <li><EyeOff size={17} />{t('Товар пропадёт из каталога и витрины магазина.', 'The item disappears from the catalog and your store.')}</li>
                                        <li><ShieldCheck size={17} />{t('Уже оплаченные сделки не отменятся — их нужно довести до конца.', 'Paid deals are not cancelled — complete them as usual.')}</li>
                                        <li><RotateCcw size={17} />{t('Вернуть в продажу можно в любой момент, без повторной проверки.', 'You can put it back on sale any time, without review.')}</li>
                                    </ul>
                                    <div className="dchat-sheet-actions">
                                        <button
                                            type="button"
                                            className="dchat-btn primary"
                                            disabled={busy}
                                            onClick={() => run(async () => { await p2pApi.withdrawListing(listing.id); setConfirm(null); await load(); },
                                                t('Снято с продажи', 'Unlisted')).catch(() => undefined)}
                                        >
                                            <EyeOff size={17} />
                                            {t('Снять с продажи', 'Unlist')}
                                        </button>
                                        <button type="button" className="dchat-btn ghost" onClick={() => setConfirm(null)}>
                                            {t('Отмена', 'Cancel')}
                                        </button>
                                    </div>
                                </>
                            ) : (
                                <>
                                    <h3>{t('Удалить объявление?', 'Delete this listing?')}</h3>
                                    <p>{t('Объявление и его фото пропадут насовсем.', 'The listing and its photos will be gone for good.')}</p>
                                    <div className="dchat-sheet-actions">
                                        <button
                                            type="button"
                                            className="dchat-btn danger"
                                            disabled={busy}
                                            onClick={() => run(async () => { await p2pApi.deleteListing(listing.id); navigate('/my/listings', { replace: true }); },
                                                t('Объявление удалено', 'Listing deleted')).catch(() => undefined)}
                                        >
                                            {t('Удалить', 'Delete')}
                                        </button>
                                        <button type="button" className="dchat-btn ghost" onClick={() => setConfirm(null)}>
                                            {t('Отмена', 'Cancel')}
                                        </button>
                                    </div>
                                </>
                            )}
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
};
