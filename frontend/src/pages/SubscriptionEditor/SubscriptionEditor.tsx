import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { ArrowLeft, Plus, X } from 'lucide-react';
import { subscriptionsApi, termsApi } from '@/api/client';
import { ChannelCard } from '@/components/ChannelCabinet/ChannelCabinet';
import { CommissionNote } from '@/components/CommissionNote/CommissionNote';
import { useAuthStore } from '@/store/authStore';
import { usePublicSettings } from '@/hooks/usePublicSettings';
import { useToastStore, errorText } from '@/store/toastStore';
import type { AuthorChannel } from '@/types';
import './SubscriptionEditor.css';

export function SubscriptionEditor() {
    const { channelId } = useParams<{ channelId: string }>();
    const creating = !channelId;
    const navigate = useNavigate();
    const { language } = useAuthStore();
    const showToast = useToastStore(state => state.show);
    const settings = usePublicSettings();
    const ru = language === 'ru';
    const t = (r: string, en: string) => ru ? r : en;
    const [channel, setChannel] = useState<AuthorChannel | null>(null);
    const [loadFailed, setLoadFailed] = useState(false);
    const [identifier, setIdentifier] = useState('');
    const [title, setTitle] = useState('');
    const [titleEn, setTitleEn] = useState('');
    const [description, setDescription] = useState('');
    const [descriptionEn, setDescriptionEn] = useState('');
    const [price, setPrice] = useState('');
    const [days, setDays] = useState('30');
    const [file, setFile] = useState<File | null>(null);
    const [preview, setPreview] = useState('');
    const [accepted, setAccepted] = useState(false);
    const [termsOpen, setTermsOpen] = useState(false);
    const [terms, setTerms] = useState<string | null>(null);
    const [termsFailed, setTermsFailed] = useState(false);
    const [busy, setBusy] = useState(false);
    const [draftId, setDraftId] = useState<string | null>(null);
    const [saveFailed, setSaveFailed] = useState(false);
    const photoInput = useRef<HTMLInputElement>(null);
    const saving = useRef(false);
    const uploaded = useRef<File | null>(null);

    useEffect(() => {
        if (!file) { setPreview(''); return; }
        const url = URL.createObjectURL(file);
        setPreview(url);
        return () => URL.revokeObjectURL(url);
    }, [file]);

    const load = useCallback(async (afterMutation = false) => {
        if (!channelId) return;
        setLoadFailed(false);
        try {
            const channels = await subscriptionsApi.getMyChannels();
            const found = channels.find(item => item.id === channelId);
            if (!found) {
                if (afterMutation) navigate('/my/channels', { replace: true });
                else setLoadFailed(true);
                return;
            }
            setChannel(found);
        } catch { setLoadFailed(true); }
    }, [channelId, navigate]);
    useEffect(() => { void load(); }, [load]);

    const showTerms = async () => {
        setTermsOpen(value => !value);
        if (terms !== null) return;
        setTermsFailed(false);
        try {
            const data = await termsApi.get(language);
            setTerms(data.is_empty ? '' : data.text);
        } catch { setTermsFailed(true); }
    };

    const submit = async (event: React.FormEvent) => {
        event.preventDefault();
        if (saving.current) return;
        if (!accepted || !title.trim() || !description.trim()) {
            showToast(t('Заполните название и описание и примите условия.', 'Enter a name and description and accept the terms.'), 'error');
            return;
        }
        const normalizedPrice = price.trim().replace(',', '.');
        if (!/^[0-9]{1,8}(\.[0-9]{1,2})?$/.test(normalizedPrice)
            || BigInt(normalizedPrice.replace('.', '')) === 0n) {
            showToast(t('Укажите цену больше нуля, до двух знаков после запятой.', 'Enter a positive price with up to two decimal places.'), 'error');
            return;
        }
        saving.current = true;
        setBusy(true);
        setSaveFailed(false);
        let id = draftId;
        try {
            if (!id) {
                const created = await subscriptionsApi.connectChannel({
                    chat_identifier: identifier.trim(), accept_terms: accepted,
                    description: description.trim(), description_en: descriptionEn.trim() || description.trim(),
                });
                id = created.id;
                setDraftId(id);
            }
            await subscriptionsApi.updateChannel(id, {
                title_ru: title.trim(), title_en: titleEn.trim() || title.trim(),
                description: description.trim(), description_en: descriptionEn.trim() || description.trim(),
            });
            if (file && uploaded.current !== file) {
                await subscriptionsApi.uploadChannelCover(id, file);
                uploaded.current = file;
            }
            // A previous request may have saved its plan before the connection
            // dropped. Read the new draft before retrying to avoid a second plan.
            const current = (await subscriptionsApi.getMyChannels()).find(item => item.id === id);
            if (!current) throw new Error(t('Не удалось загрузить черновик', 'Could not load the draft'));
            if (!file && current.cover_url) {
                await subscriptionsApi.deleteChannelCover(id);
                uploaded.current = null;
            }
            const plan = {
                title_ru: `Доступ на ${days} дн.`, title_en: `${days}-day access`,
                duration_days: Number(days), price_usd: normalizedPrice,
            };
            if (current.plans[0]) await subscriptionsApi.updatePlan(id, current.plans[0].id, plan);
            else await subscriptionsApi.createPlan(id, plan);
            showToast(t('Подписка сохранена. Можно отправить её на проверку.', 'Subscription saved. You can submit it for review.'), 'success');
            navigate(`/my/channels/${id}`, { replace: true });
        } catch (error) {
            setSaveFailed(true);
            showToast(errorText(error, t('Не удалось сохранить подписку. Повторите попытку.', 'Could not save the subscription. Try again.')), 'error');
        } finally {
            saving.current = false;
            setBusy(false);
        }
    };

    return (
        <div className="subscription-editor">
            <div className="container">
                <Link className="btn-back" to="/my/channels"><ArrowLeft size={20} />{t('Мои подписки на каналы', 'My channel subscriptions')}</Link>
                <h1>{creating ? t('Новая подписка', 'New subscription') : channel?.title || t('Подписка', 'Subscription')}</h1>
                {!creating ? (
                    loadFailed ? <div role="alert"><p>{t('Не удалось загрузить подписку.', 'Could not load the subscription.')}</p><button type="button" className="channel-btn" onClick={() => void load()}>{t('Повторить', 'Retry')}</button></div>
                        : channel ? <ChannelCard channel={channel} language={language} reload={() => load(true)} onError={(error, message) => showToast(errorText(error, message), 'error')} />
                            : <p role="status">{t('Загрузка…', 'Loading…')}</p>
                ) : (
                    <form className="subscription-create" onSubmit={submit}>
                        <fieldset disabled={busy}>
                            <div className="subscription-cover-picker">
                                <input ref={photoInput} type="file" accept="image/jpeg,image/png,image/webp" hidden
                                    aria-label={t('Фото подписки', 'Subscription photo')} onChange={event => {
                                        const chosen = event.target.files?.[0];
                                        event.target.value = '';
                                        if (!chosen) return;
                                        if (!['image/jpeg', 'image/png', 'image/webp'].includes(chosen.type) || chosen.size > 20 * 1024 * 1024) {
                                            showToast(t('Выберите JPG, PNG или WebP до 20 МБ.', 'Choose a JPG, PNG or WebP up to 20 MB.'), 'error');
                                            return;
                                        }
                                        setFile(chosen);
                                    }} />
                                <button type="button" className="subscription-cover-button" onClick={() => photoInput.current?.click()}>
                                    {preview ? <img src={preview} alt={t('Обложка подписки', 'Subscription cover')} /> : <><Plus size={32} /><span>{t('Добавьте фото подписки', 'Add a subscription photo')}</span></>}
                                </button>
                                {file && <button type="button" className="subscription-cover-remove" aria-label={t('Удалить фото', 'Remove photo')} onClick={() => setFile(null)}><X size={18} /></button>}
                            </div>
                            <p className="subscription-editor-hint">{t('Одна обложка для всех тарифов канала. Можно выбрать фото до сохранения.', 'One cover for all channel plans. Choose it before saving.')}</p>
                            <label>{t('Название', 'Name')}<input value={title} onChange={e => setTitle(e.target.value)} maxLength={120} required placeholder={t('Например: Закрытый клуб', 'For example: Private club')} /></label>
                            <label>{t('Описание', 'Description')}<textarea value={description} onChange={e => setDescription(e.target.value)} maxLength={2000} required placeholder={t('Что получит подписчик', 'What subscribers will receive')} rows={4} /></label>
                            <div className="subscription-editor-fields">
                                <label>{t('Цена, $', 'Price, $')}<input value={price} onChange={e => setPrice(e.target.value)} inputMode="decimal" pattern="[0-9]{1,8}([.,][0-9]{1,2})?" maxLength={11} required placeholder="5.00" /></label>
                                <label>{t('Дней доступа', 'Days of access')}<input type="number" value={days} onChange={e => setDays(e.target.value)} min={1} max={3650} step={1} required /></label>
                            </div>
                            <CommissionNote price={price.replace(',', '.')} bp={settings?.commission_subscription_bp ?? null} />
                            <label>{t('Канал Telegram', 'Telegram channel')}<input value={identifier} disabled={!!draftId} onChange={e => setIdentifier(e.target.value)} placeholder="@username / -1001234567890" minLength={2} maxLength={100} required /></label>
                            <p className="subscription-editor-hint">{t('Добавьте бота администратором канала с правами приглашать и блокировать участников. Доступ после оплаты он выдаст автоматически.', 'Add the bot as a channel admin with permission to invite and ban members. It will grant access automatically after payment.')}</p>
                            <details className="subscription-editor-translations"><summary>{t('Английская версия', 'English version')}</summary>
                                <label>{t('Название по-английски', 'Name in English')}<input value={titleEn} onChange={e => setTitleEn(e.target.value)} maxLength={120} /></label>
                                <label>{t('Описание по-английски', 'Description in English')}<textarea value={descriptionEn} onChange={e => setDescriptionEn(e.target.value)} maxLength={2000} rows={4} /></label>
                            </details>
                            <label className="subscription-editor-terms"><input type="checkbox" checked={accepted} onChange={e => setAccepted(e.target.checked)} required /><span>{t('Я принимаю ', 'I accept the ')}<button type="button" onClick={() => void showTerms()}>{t('условия площадки', 'platform terms')}</button></span></label>
                            {termsOpen && <div className="channel-terms-text">{termsFailed ? t('Не удалось загрузить условия. Откройте их повторно.', 'Could not load the terms. Open them again.') : terms === null ? t('Загрузка…', 'Loading…') : terms || t('Условия пока не заполнены.', 'Terms are not available yet.')}</div>}
                            {saveFailed && draftId && <p className="subscription-editor-hint" role="status">{t('Канал сохранён в черновиках. Повторите сохранение — фото и тариф будут добавлены в этот же черновик.', 'The channel draft is saved. Retry to save the cover and plan to the same draft.')}</p>}
                            <button className="channel-btn subscription-editor-save" type="submit" disabled={busy}>{busy ? t('Сохраняем…', 'Saving…') : t('Создать подписку', 'Create subscription')}</button>
                        </fieldset>
                    </form>
                )}
            </div>
        </div>
    );
}
