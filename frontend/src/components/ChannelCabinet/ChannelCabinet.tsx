import React, { useCallback, useEffect, useState } from 'react';
import {
    Radio, Plus, Send, ShieldCheck, ShieldAlert, RefreshCw,
    ChevronDown, ChevronUp, Check, Wallet, Pencil, Trash2, EyeOff, BadgeCheck,
} from 'lucide-react';
import { subscriptionsApi, termsApi, withdrawalsApi } from '@/api/client';
import { useAuthStore } from '@/store/authStore';
import { useToastStore, errorText } from '@/store/toastStore';
import { useTelegram } from '@/hooks/useTelegram';
import { CommissionNote } from '@/components/CommissionNote/CommissionNote';
import { usePublicSettings } from '@/hooks/usePublicSettings';
import type { AuthorChannel, ChannelPlan, ChannelStatus } from '@/types';
import './ChannelCabinet.css';

/** Статусы, в которых канал ещё можно отправить на модерацию */
const SUBMITTABLE: ChannelStatus[] = ['draft', 'rejected'];

const STATUS_LABEL: Record<ChannelStatus, [string, string]> = {
    draft: ['Черновик', 'Draft'],
    pending: ['На модерации', 'In review'],
    active: ['Опубликован', 'Published'],
    suspended: ['Снят администрацией', 'Suspended'],
    rejected: ['Отклонён', 'Rejected'],
};

/**
 * Кабинет автора канала.
 *
 * Свёрнут по умолчанию — как и кабинет продавца: каналы есть у единиц,
 * разворачивать форму всем подряд незачем.
 *
 * Бэкенд для всего этого существовал с этапа 4, но вызывать его было
 * неоткуда: подключить канал мог только разработчик запросом из консоли.
 */
export const ChannelCabinet: React.FC<{ standalone?: boolean }> = ({ standalone = false }) => {
    const { language } = useAuthStore();
    const { haptic } = useTelegram();
    const showToast = useToastStore((s) => s.show);

    // На своём экране сворачивать нечего — см. SellerCabinet
    const [open, setOpen] = useState(standalone);
    const [channels, setChannels] = useState<AuthorChannel[] | null>(null);
    const [connecting, setConnecting] = useState(false);

    const t = (ru: string, en: string) => (language === 'ru' ? ru : en);

    const fail = useCallback((e: unknown, fallback: string) => {
        haptic.notification('error');
        showToast(errorText(e, fallback), 'error');
    }, [haptic, showToast]);

    const load = useCallback(async () => {
        try {
            setChannels(await subscriptionsApi.getMyChannels());
        } catch {
            setChannels([]);
        }
    }, []);

    useEffect(() => {
        if (open && channels === null) load();
    }, [open, channels, load]);

    const hasChannels = (channels?.length ?? 0) > 0;

    return (
        <div className={standalone ? 'channel-section channel-section--page' : 'channel-section glass-card'}>
            {!standalone && (
                <button className="channel-head" onClick={() => setOpen(!open)}>
                    <span className="channel-head-left">
                        <Radio size={18} />
                        {hasChannels
                            ? t('Мои каналы', 'My channels')
                            : t('Продавать подписки', 'Sell subscriptions')}
                    </span>
                    {open ? <ChevronUp size={18} /> : <ChevronDown size={18} />}
                </button>
            )}

            {open && channels !== null && (
                <>
                    {hasChannels && <AuthorPayout language={language} onError={fail} />}

                    {channels.map((channel) => (
                        <ChannelCard
                            key={channel.id}
                            channel={channel}
                            language={language}
                            reload={load}
                            onError={fail}
                        />
                    ))}

                    {(!hasChannels || connecting) && (
                        <ConnectForm
                            language={language}
                            onDone={async () => {
                                setConnecting(false);
                                await load();
                            }}
                            onError={fail}
                        />
                    )}

                    {hasChannels && !connecting && (
                        <button
                            className="channel-btn-secondary"
                            onClick={() => setConnecting(true)}
                        >
                            <Plus size={16} />
                            {t('Подключить ещё канал', 'Connect another channel')}
                        </button>
                    )}
                </>
            )}
        </div>
    );
};

/* ------------------------------------------------------------------ */
/* Заработок автора                                                    */
/* ------------------------------------------------------------------ */

/**
 * Баланс и заявка на вывод.
 *
 * Заработок автора канала лежит на том же счёте в TON, что и заработок
 * продавца, но показывался только в кабинете продавца — то есть человек,
 * продающий подписки и не торгующий вещами, своих денег не видел вообще.
 * В профиле сверху выводится реферальный баланс в USD, и на него легко
 * посмотреть и решить, что заработка нет.
 */
const AuthorPayout: React.FC<{
    language: string;
    onError: (e: unknown, fallback: string) => void;
}> = ({ language, onError }) => {
    const { haptic } = useTelegram();
    const showToast = useToastStore((s) => s.show);

    const [available, setAvailable] = useState<string>('0');
    const [hold, setHold] = useState(0);
    const [formOpen, setFormOpen] = useState(false);
    const [amount, setAmount] = useState('');
    const [wallet, setWallet] = useState('');
    const [busy, setBusy] = useState(false);

    const t = (ru: string, en: string) => (language === 'ru' ? ru : en);

    const load = useCallback(async () => {
        try {
            const data = await withdrawalsApi.getBalances();
            setAvailable(data.TON?.available ?? '0');
            setHold(data.TON?.hold_minor ?? 0);
        } catch {
            setAvailable('0');
        }
    }, []);

    useEffect(() => { load(); }, [load]);

    const submit = async (e: React.FormEvent) => {
        e.preventDefault();
        setBusy(true);
        try {
            await withdrawalsApi.requestWithdrawal({
                amount: amount.trim(),
                wallet: wallet.trim(),
                currency: 'TON',
            });
            haptic.notification('success');
            showToast(t('Заявка на вывод отправлена', 'Withdrawal requested'), 'success');
            setFormOpen(false);
            setAmount('');
            await load();
        } catch (err) {
            onError(err, t('Не удалось отправить заявку', 'Failed to request withdrawal'));
        } finally {
            setBusy(false);
        }
    };

    return (
        <div className="channel-payout">
            <div className="channel-payout-row">
                <span className="channel-payout-label">{t('Заработано, TON', 'Earned, TON')}</span>
                <span className="channel-payout-value">{available}</span>
            </div>

            {hold > 0 && (
                <span className="channel-note">
                    {t('Заморожено по заявкам на вывод: ', 'On hold for withdrawals: ')}
                    {(hold / 1e9).toFixed(9)} TON
                </span>
            )}

            {formOpen ? (
                <form className="channel-form channel-form-inline" onSubmit={submit}>
                    <label className="channel-label">
                        {t('Сумма к выводу', 'Amount')}
                        <input
                            className="channel-input"
                            type="number"
                            step="0.000000001"
                            min="0.000000001"
                            value={amount}
                            onChange={(e) => setAmount(e.target.value)}
                            placeholder={available}
                            required
                        />
                    </label>
                    <label className="channel-label">
                        {t('Кошелёк TON', 'TON wallet')}
                        <input
                            className="channel-input"
                            value={wallet}
                            onChange={(e) => setWallet(e.target.value)}
                            placeholder="UQ..."
                            minLength={10}
                            required
                        />
                    </label>
                    <div className="channel-row">
                        <button className="channel-btn" type="submit" disabled={busy}>
                            {busy ? t('Отправляем...', 'Sending...') : t('Отправить заявку', 'Send request')}
                        </button>
                        <button
                            className="channel-btn-secondary"
                            type="button"
                            onClick={() => setFormOpen(false)}
                        >
                            {t('Отмена', 'Cancel')}
                        </button>
                    </div>
                </form>
            ) : (
                <button
                    className="channel-btn-secondary"
                    onClick={() => setFormOpen(true)}
                    disabled={Number(available) <= 0}
                >
                    <Wallet size={16} />
                    {t('Вывести', 'Withdraw')}
                </button>
            )}
        </div>
    );
};

/* ------------------------------------------------------------------ */
/* Подключение канала                                                  */
/* ------------------------------------------------------------------ */

const ConnectForm: React.FC<{
    language: string;
    onDone: () => Promise<void>;
    onError: (e: unknown, fallback: string) => void;
}> = ({ language, onDone, onError }) => {
    const { haptic } = useTelegram();
    const [identifier, setIdentifier] = useState('');
    const [wallet, setWallet] = useState('');
    const [description, setDescription] = useState('');
    const [accepted, setAccepted] = useState(false);
    const [termsOpen, setTermsOpen] = useState(false);
    const [termsText, setTermsText] = useState<string | null>(null);
    const [busy, setBusy] = useState(false);

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
            await subscriptionsApi.connectChannel({
                chat_identifier: identifier.trim(),
                payout_wallet: wallet.trim(),
                description: description.trim() || undefined,
                accept_terms: accepted,
            });
            haptic.notification('success');
            await onDone();
        } catch (err) {
            onError(err, t('Не удалось подключить канал', 'Failed to connect the channel'));
        } finally {
            setBusy(false);
        }
    };

    return (
        <form className="channel-form" onSubmit={submit}>
            <p className="channel-intro">
                {t(
                    'Продавайте доступ в свой закрытый канал. Бот сам выдаёт приглашение после оплаты и сам закрывает доступ по окончании срока.',
                    'Sell access to your private channel. The bot issues the invite after payment and revokes access when the subscription ends.',
                )}
            </p>

            <div className="channel-hint">
                <strong>{t('Перед подключением', 'Before you connect')}</strong>
                <ol>
                    <li>{t('Добавьте бота в канал администратором', 'Add the bot to your channel as an admin')}</li>
                    <li>{t('Включите права «Пригласительные ссылки» и «Блокировка участников»', 'Enable “Invite links” and “Ban users” permissions')}</li>
                </ol>
                <span className="channel-hint-note">
                    {t(
                        'Без этих прав бот не сможет ни выдать доступ, ни отозвать его — канал не получится опубликовать.',
                        'Without these the bot can neither grant nor revoke access — the channel cannot be published.',
                    )}
                </span>
            </div>

            <label className="channel-label">
                {t('Канал', 'Channel')}
                <input
                    className="channel-input"
                    value={identifier}
                    onChange={(e) => setIdentifier(e.target.value)}
                    placeholder={t('@username или -1001234567890', '@username or -1001234567890')}
                    minLength={2}
                    maxLength={100}
                    required
                />
            </label>

            <label className="channel-label">
                {t('Кошелёк TON для выплат', 'TON payout wallet')}
                <input
                    className="channel-input"
                    value={wallet}
                    onChange={(e) => setWallet(e.target.value)}
                    placeholder="UQ..."
                    minLength={10}
                    maxLength={80}
                    required
                />
            </label>

            <label className="channel-label">
                {t('Описание (необязательно)', 'Description (optional)')}
                <textarea
                    className="channel-input channel-textarea"
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    maxLength={2000}
                />
            </label>

            <div className="channel-terms">
                <label className="channel-check">
                    <input
                        type="checkbox"
                        checked={accepted}
                        onChange={(e) => setAccepted(e.target.checked)}
                    />
                    <span>
                        {t('Я принимаю ', 'I accept the ')}
                        <button type="button" className="channel-link" onClick={showTerms}>
                            {t('условия площадки', 'platform terms')}
                        </button>
                    </span>
                </label>
                {termsOpen && (
                    <div className="channel-terms-text">
                        {termsText
                            ? termsText
                            : t('Текст условий пока не заполнен.', 'The terms text is not filled in yet.')}
                    </div>
                )}
            </div>

            <button className="channel-btn" type="submit" disabled={busy || !accepted}>
                {busy ? t('Подключаем...', 'Connecting...') : t('Подключить канал', 'Connect channel')}
            </button>
        </form>
    );
};

/* ------------------------------------------------------------------ */
/* Карточка канала                                                     */
/* ------------------------------------------------------------------ */

const ChannelCard: React.FC<{
    channel: AuthorChannel;
    language: string;
    reload: () => Promise<void>;
    onError: (e: unknown, fallback: string) => void;
}> = ({ channel, language, reload, onError }) => {
    const { haptic } = useTelegram();
    const showToast = useToastStore((s) => s.show);
    const [busy, setBusy] = useState(false);
    const [addingPlan, setAddingPlan] = useState(false);
    const [editing, setEditing] = useState(false);
    const [editingPlanId, setEditingPlanId] = useState<string | null>(null);

    const t = (ru: string, en: string) => (language === 'ru' ? ru : en);
    const [labelRu, labelEn] = STATUS_LABEL[channel.status];

    /** Действие с подтверждением и перезагрузкой — как в кабинете продавца */
    const act = async (fn: () => Promise<unknown>, confirmText?: string) => {
        if (confirmText && !window.confirm(confirmText)) return;
        setBusy(true);
        try {
            await fn();
            haptic.notification('success');
            await reload();
        } catch (e) {
            onError(e, t('Не удалось', 'Failed'));
        } finally {
            setBusy(false);
        }
    };

    const verify = async () => {
        setBusy(true);
        try {
            const result = await subscriptionsApi.verifyChannel(channel.id);
            haptic.notification(result.bot_is_admin ? 'success' : 'error');
            showToast(
                result.bot_is_admin
                    ? t('Права бота подтверждены', 'Bot permissions confirmed')
                    : result.error || t('Права бота не подтверждены', 'Bot permissions missing'),
                result.bot_is_admin ? 'success' : 'error',
            );
            await reload();
        } catch (e) {
            onError(e, t('Не удалось проверить права', 'Failed to verify permissions'));
        } finally {
            setBusy(false);
        }
    };

    const submit = async () => {
        setBusy(true);
        try {
            await subscriptionsApi.submitChannel(channel.id);
            haptic.notification('success');
            showToast(t('Канал отправлен на модерацию', 'Channel submitted for review'), 'success');
            await reload();
        } catch (e) {
            onError(e, t('Не удалось отправить на модерацию', 'Failed to submit'));
        } finally {
            setBusy(false);
        }
    };

    return (
        <div className="channel-card">
            <div className="channel-card-head">
                {/* Аватар тянется из Telegram: своей картинки у канала нет и
                    заводить её незачем — она уже есть у автора */}
                {channel.avatar_url && (
                    <img className="channel-avatar" src={channel.avatar_url} alt="" />
                )}
                <span className="channel-title">{channel.title}</span>
                {channel.is_verified && (
                    <BadgeCheck
                        className="channel-verified"
                        size={16}
                        aria-label={t('Проверенный автор', 'Verified author')}
                    />
                )}
                <span className={`channel-badge channel-badge--${channel.status}`}>
                    {t(labelRu, labelEn)}
                </span>
            </div>

            {channel.username && <span className="channel-username">@{channel.username}</span>}

            {channel.moderation_comment && (
                <div className="channel-note channel-note--warn">
                    {channel.moderation_comment}
                </div>
            )}

            {editing ? (
                <ChannelEditForm
                    channel={channel}
                    language={language}
                    onDone={async () => {
                        setEditing(false);
                        await reload();
                    }}
                    onCancel={() => setEditing(false)}
                    onError={onError}
                />
            ) : (
                <div className="channel-row-btns">
                    <button
                        className="channel-btn-inline"
                        onClick={() => setEditing(true)}
                        disabled={busy}
                    >
                        <Pencil size={14} />
                        {t('Править', 'Edit')}
                    </button>

                    {channel.status === 'active' && (
                        <button
                            className="channel-btn-inline"
                            disabled={busy}
                            onClick={() => act(
                                () => subscriptionsApi.unpublishChannel(channel.id),
                                t(
                                    'Снять канал с продажи? Уже купленные подписки продолжат действовать.',
                                    'Take the channel off sale? Existing subscriptions keep working.',
                                ),
                            )}
                        >
                            <EyeOff size={14} />
                            {t('Снять с продажи', 'Unlist')}
                        </button>
                    )}

                    <button
                        className="channel-btn-inline channel-btn-danger"
                        disabled={busy}
                        onClick={() => act(
                            () => subscriptionsApi.deleteChannel(channel.id),
                            t('Удалить канал?', 'Delete this channel?'),
                        )}
                    >
                        <Trash2 size={14} />
                        {t('Удалить', 'Delete')}
                    </button>
                </div>
            )}

            {/* Состояние прав бота — главный признак работоспособности канала */}
            <div className={`channel-rights ${channel.bot_is_admin ? 'ok' : 'bad'}`}>
                {channel.bot_is_admin ? <ShieldCheck size={16} /> : <ShieldAlert size={16} />}
                <span>
                    {channel.bot_is_admin
                        ? t('Права бота подтверждены', 'Bot permissions confirmed')
                        : channel.bot_check_error || t('Бот не администратор канала', 'Bot is not a channel admin')}
                </span>
                <button className="channel-btn-inline" onClick={verify} disabled={busy}>
                    <RefreshCw size={14} />
                    {t('Проверить', 'Check')}
                </button>
            </div>

            <div className="channel-plans">
                <span className="channel-plans-title">{t('Тарифы', 'Plans')}</span>
                {channel.plans.length === 0 && (
                    <span className="channel-plans-empty">
                        {t('Пока ни одного. Без тарифа канал не опубликовать.',
                           'None yet. A channel cannot be published without a plan.')}
                    </span>
                )}
                {channel.plans.map((plan) => (
                    editingPlanId === plan.id ? (
                        <PlanForm
                            key={plan.id}
                            channelId={channel.id}
                            plan={plan}
                            language={language}
                            onDone={async () => {
                                setEditingPlanId(null);
                                await reload();
                            }}
                            onCancel={() => setEditingPlanId(null)}
                            onError={onError}
                        />
                    ) : (
                        <div
                            key={plan.id}
                            className={`channel-plan ${plan.is_active ? '' : 'channel-plan--off'}`}
                        >
                            <span className="channel-plan-name">
                                {language === 'ru' ? plan.title_ru : plan.title_en}
                            </span>
                            <span className="channel-plan-meta">
                                {plan.duration_days} {t('дн.', 'days')} · ${plan.price_usd}
                            </span>

                            <span className="channel-plan-actions">
                                <button
                                    className="channel-btn-inline"
                                    disabled={busy}
                                    onClick={() => setEditingPlanId(plan.id)}
                                    aria-label={t('Править тариф', 'Edit plan')}
                                >
                                    <Pencil size={13} />
                                </button>
                                <button
                                    className="channel-btn-inline"
                                    disabled={busy}
                                    onClick={() => act(() => subscriptionsApi.updatePlan(
                                        channel.id, plan.id, { is_active: !plan.is_active },
                                    ))}
                                >
                                    {plan.is_active ? t('Отключить', 'Disable') : t('Включить', 'Enable')}
                                </button>
                                <button
                                    className="channel-btn-inline channel-btn-danger"
                                    disabled={busy}
                                    onClick={() => act(
                                        () => subscriptionsApi.deletePlan(channel.id, plan.id),
                                        t('Удалить тариф?', 'Delete this plan?'),
                                    )}
                                    aria-label={t('Удалить тариф', 'Delete plan')}
                                >
                                    <Trash2 size={13} />
                                </button>
                            </span>
                        </div>
                    )
                ))}

                {addingPlan ? (
                    <PlanForm
                        channelId={channel.id}
                        language={language}
                        onDone={async () => {
                            setAddingPlan(false);
                            await reload();
                        }}
                        onCancel={() => setAddingPlan(false)}
                        onError={onError}
                    />
                ) : (
                    <button className="channel-btn-secondary" onClick={() => setAddingPlan(true)}>
                        <Plus size={16} />
                        {t('Добавить тариф', 'Add plan')}
                    </button>
                )}
            </div>

            {SUBMITTABLE.includes(channel.status) && (
                <button
                    className="channel-btn"
                    onClick={submit}
                    disabled={busy || !channel.bot_is_admin || channel.plans.length === 0}
                >
                    <Send size={16} />
                    {t('Отправить на модерацию', 'Submit for review')}
                </button>
            )}

            {channel.status === 'pending' && (
                <span className="channel-note">
                    {t('Ждём решения модератора.', 'Waiting for the moderator’s decision.')}
                </span>
            )}

            {channel.status === 'active' && (
                <span className="channel-note channel-note--ok">
                    <Check size={14} />
                    {t('Подписки продаются в каталоге.', 'Subscriptions are on sale in the catalog.')}
                </span>
            )}
        </div>
    );
};

/* ------------------------------------------------------------------ */
/* Правка канала                                                       */
/* ------------------------------------------------------------------ */

/**
 * Описание и кошелёк.
 *
 * Название и аватар сюда не входят: и то и другое берётся из Telegram и
 * обновляется по кнопке «Проверить». Своё поле под них означало бы два
 * источника правды и расхождение между каналом и карточкой в каталоге.
 */
const ChannelEditForm: React.FC<{
    channel: AuthorChannel;
    language: string;
    onDone: () => Promise<void>;
    onCancel: () => void;
    onError: (e: unknown, fallback: string) => void;
}> = ({ channel, language, onDone, onCancel, onError }) => {
    const { haptic } = useTelegram();
    const showToast = useToastStore((s) => s.show);
    const [description, setDescription] = useState(channel.description ?? '');
    const [wallet, setWallet] = useState(channel.payout_wallet ?? '');
    const [busy, setBusy] = useState(false);

    const t = (ru: string, en: string) => (language === 'ru' ? ru : en);

    const descriptionChanged = description.trim() !== (channel.description ?? '').trim();
    const willUnpublish = channel.status === 'active' && descriptionChanged;

    const submit = async (e: React.FormEvent) => {
        e.preventDefault();
        setBusy(true);
        try {
            await subscriptionsApi.updateChannel(channel.id, {
                description: description.trim(),
                payout_wallet: wallet.trim(),
            });
            haptic.notification('success');
            if (willUnpublish) {
                showToast(
                    t(
                        'Описание изменено — канал снят с публикации до повторной проверки',
                        'Description changed — the channel is unlisted pending review',
                    ),
                    'info',
                );
            }
            await onDone();
        } catch (err) {
            onError(err, t('Не удалось сохранить', 'Failed to save'));
        } finally {
            setBusy(false);
        }
    };

    return (
        <form className="channel-form channel-form-inline" onSubmit={submit}>
            <label className="channel-label">
                {t('Описание', 'Description')}
                <textarea
                    className="channel-input channel-textarea"
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    maxLength={2000}
                />
            </label>

            <label className="channel-label">
                {t('Кошелёк TON для выплат', 'TON payout wallet')}
                <input
                    className="channel-input"
                    value={wallet}
                    onChange={(e) => setWallet(e.target.value)}
                    placeholder="UQ..."
                    minLength={10}
                    maxLength={80}
                />
            </label>

            {/* Предупреждаем до нажатия, а не тостом после: снятие с продажи —
                не то, что человек ожидает от правки опечатки */}
            {willUnpublish && (
                <span className="channel-note channel-note--warn">
                    {t(
                        'Описание проверяет модератор, поэтому канал уйдёт на повторную проверку и пропадёт из каталога.',
                        'The description is moderated, so the channel will go back for review and leave the catalog.',
                    )}
                </span>
            )}

            <div className="channel-row">
                <button className="channel-btn" type="submit" disabled={busy}>
                    {busy ? t('Сохраняем...', 'Saving...') : t('Сохранить', 'Save')}
                </button>
                <button className="channel-btn-secondary" type="button" onClick={onCancel}>
                    {t('Отмена', 'Cancel')}
                </button>
            </div>
        </form>
    );
};

/* ------------------------------------------------------------------ */
/* Тариф: создание и правка                                            */
/* ------------------------------------------------------------------ */

const PlanForm: React.FC<{
    channelId: string;
    /** Есть — правим существующий тариф, нет — заводим новый */
    plan?: ChannelPlan;
    language: string;
    onDone: () => Promise<void>;
    onCancel: () => void;
    onError: (e: unknown, fallback: string) => void;
}> = ({ channelId, plan, language, onDone, onCancel, onError }) => {
    const { haptic } = useTelegram();
    const commissions = usePublicSettings();
    const [titleRu, setTitleRu] = useState(plan?.title_ru ?? '');
    const [days, setDays] = useState(String(plan?.duration_days ?? 30));
    const [price, setPrice] = useState(plan?.price_usd ?? '');
    const [busy, setBusy] = useState(false);

    const t = (ru: string, en: string) => (language === 'ru' ? ru : en);

    const submit = async (e: React.FormEvent) => {
        e.preventDefault();
        setBusy(true);
        try {
            const payload = {
                title_ru: titleRu.trim(),
                // Отдельного поля под английское название намеренно нет: форма
                // и так на четыре поля, а авторы здесь пишут по-русски.
                // Бэкенд требует непустое title_en, поэтому дублируем — это
                // честнее пустой строки, которую увидел бы англоязычный
                // покупатель в каталоге.
                title_en: titleRu.trim(),
                duration_days: Number(days),
                price_usd: price.trim(),
            };

            if (plan) {
                await subscriptionsApi.updatePlan(channelId, plan.id, payload);
            } else {
                await subscriptionsApi.createPlan(channelId, payload);
            }
            haptic.notification('success');
            await onDone();
        } catch (err) {
            onError(err, plan
                ? t('Не удалось сохранить тариф', 'Failed to save the plan')
                : t('Не удалось создать тариф', 'Failed to create the plan'));
        } finally {
            setBusy(false);
        }
    };

    return (
        <form className="channel-form channel-form-inline" onSubmit={submit}>
            <label className="channel-label">
                {t('Название тарифа', 'Plan name')}
                <input
                    className="channel-input"
                    value={titleRu}
                    onChange={(e) => setTitleRu(e.target.value)}
                    placeholder={t('Месяц', 'Month')}
                    maxLength={255}
                    required
                />
            </label>

            <div className="channel-row">
                <label className="channel-label">
                    {t('Дней доступа', 'Days')}
                    <input
                        className="channel-input"
                        type="number"
                        value={days}
                        onChange={(e) => setDays(e.target.value)}
                        min={1}
                        max={3650}
                        required
                    />
                </label>
                <label className="channel-label">
                    {t('Цена, $', 'Price, $')}
                    <input
                        className="channel-input"
                        type="number"
                        step="0.01"
                        min="0.01"
                        value={price}
                        onChange={(e) => setPrice(e.target.value)}
                        placeholder="5.00"
                        required
                    />
                </label>
            </div>

            {/* У подписок своя ставка комиссии — она задаётся в админке
                отдельно от комиссии на обычные товары */}
            <CommissionNote
                price={price}
                bp={commissions?.commission_subscription_bp ?? null}
            />

            <div className="channel-row">
                <button className="channel-btn" type="submit" disabled={busy}>
                    {busy ? t('Сохраняем...', 'Saving...') : t('Сохранить', 'Save')}
                </button>
                <button className="channel-btn-secondary" type="button" onClick={onCancel}>
                    {t('Отмена', 'Cancel')}
                </button>
            </div>
        </form>
    );
};
