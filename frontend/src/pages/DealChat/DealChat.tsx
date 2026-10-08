import React, { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { useLocation, useNavigate, useParams } from 'react-router-dom';
import {
    AlertTriangle, ArrowLeft, ArrowUp, BadgeCheck, Lock, Paperclip, User as UserIcon, X,
} from 'lucide-react';
import { p2pApi } from '@/api/client';
import { realtime } from '@/lib/realtime';
import { isAppActive, onAppActiveChange } from '@/lib/appActive';
import { useAuthStore } from '@/store/authStore';
import { useDealsStore, selectIsTyping } from '@/store/dealsStore';
import { useToastStore, errorText } from '@/store/toastStore';
import { useTelegram } from '@/hooks/useTelegram';
import type { Deal, DealMessage } from '@/types';
import { DealCard } from '@/components/DealChat/DealCard';
import { DealReview } from '@/components/DealChat/DealReview';
import { DealSheet, type SheetKind } from '@/components/DealChat/DealSheet';
import { MessageList, type ChatMessage } from '@/components/DealChat/MessageList';
import { CONTACT, counterpartName, fmtDate, lastSeen } from '@/components/DealChat/dealFormat';
import './DealChat.css';

// Как на сервере (DEAL_MEDIA_MAX_SIZE): там фото всё равно уменьшается
const MAX_PHOTO = 20 * 1024 * 1024;
// «Печатает» шлём не на каждую букву: собеседнику хватит сигнала раз в пару секунд
const TYPING_EVERY = 2500;

// Черновики переживают уход в список и обратно: человек начал писать,
// заглянул в другую сделку — текст не должен пропасть
const drafts = new Map<string, string>();

/**
 * Переписка по одной сделке.
 *
 * Открывается из списка «Мои сделки» и по кнопке «Открыть чат» из
 * уведомления бота — поэтому сама загружает сделку, а не ждёт её от списка.
 * Экран во весь рост и без нижнего меню: сверху шапка и карточка сделки,
 * снизу поле ввода, между ними лента.
 */
export const DealChat: React.FC = () => {
    const { dealId = '' } = useParams();
    const navigate = useNavigate();
    const location = useLocation();
    // Назад — туда, откуда пришли: во вкладку «Чаты» или в «Мои сделки».
    // Открыли по кнопке из уведомления бота — истории внутри приложения нет,
    // тогда в «Чаты»
    const goBack = () => (location.key !== 'default' ? navigate(-1) : navigate('/chats'));
    const { language, accessToken } = useAuthStore();
    const { haptic } = useTelegram();
    const showToast = useToastStore((s) => s.show);
    const t = useCallback((ru: string, en: string) => (language === 'ru' ? ru : en), [language]);

    const [deal, setDeal] = useState<Deal | null>(null);
    const [messages, setMessages] = useState<ChatMessage[]>([]);
    const [failed, setFailed] = useState<string | null>(null);
    const [draft, setDraftState] = useState(() => drafts.get(dealId) ?? '');
    const [sheet, setSheet] = useState<SheetKind | null>(null);
    const [busy, setBusy] = useState(false);
    const [viewer, setViewer] = useState<string | null>(null);

    const typing = useDealsStore(selectIsTyping(dealId));
    const elsewhere = useDealsStore((s) =>
        Object.entries(s.unread).reduce((sum, [id, n]) => (id === dealId ? sum : sum + n), 0));

    const listRef = useRef<HTMLDivElement>(null);
    const fieldRef = useRef<HTMLTextAreaElement>(null);
    const fileRef = useRef<HTMLInputElement>(null);
    const stickToBottom = useRef(true);
    const lastTypingSent = useRef(0);
    const readTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

    const setDraft = (value: string) => {
        drafts.set(dealId, value);
        setDraftState(value);
    };

    // --- Загрузка ------------------------------------------------------------

    const load = useCallback(async () => {
        try {
            const [card, history] = await Promise.all([
                p2pApi.getDeal(dealId),
                p2pApi.getMessages(dealId),
            ]);
            setDeal(card);
            setMessages((prev) => [
                ...history.messages,
                // Свои сообщения в пути не теряем при перечитывании
                ...prev.filter((m) => m.pending),
            ]);
            setFailed(null);
        } catch (e: any) {
            setFailed(e?.response?.status === 404
                ? t('Сделка не найдена', 'Deal not found')
                : errorText(e, t('Не удалось загрузить переписку', 'Failed to load the conversation')));
        }
    }, [dealId, t]);

    useEffect(() => {
        stickToBottom.current = true;
        setDraftState(drafts.get(dealId) ?? '');
        setMessages([]);
        setDeal(null);
    }, [dealId]);


    // --- Прочтение -----------------------------------------------------------
    //
    // Отмечаем прочитанным, только пока экран на виду: в свёрнутом приложении
    // чат формально открыт, но человек его не видит — тогда пусть счётчик
    // растёт, а бот пришлёт уведомление.

    const markRead = useCallback(() => {
        if (!isAppActive()) return;
        if (readTimer.current) clearTimeout(readTimer.current);
        readTimer.current = setTimeout(() => {
            // Без токена запрос получил бы 401, а он разлогинивает приложение
            if (!useAuthStore.getState().accessToken) return;
            p2pApi.markRead(dealId).catch(() => undefined);
            useDealsStore.getState().clearUnread(dealId);
        }, 300);
    }, [dealId]);

    // По токену: по ссылке из уведомления чат открывается сразу, и вход в
    // этот момент может ещё идти — без токена сервер ответил бы 401
    useEffect(() => {
        if (!accessToken) return;
        load();
        markRead();
    }, [accessToken, load, markRead]);

    useEffect(() => {
        const store = useDealsStore.getState();
        const update = (active: boolean) => {
            store.setViewing(active ? dealId : null);
            if (active) markRead();
            else if (readTimer.current) clearTimeout(readTimer.current);
        };
        update(isAppActive());
        const off = onAppActiveChange(update);
        return () => {
            off();
            store.setViewing(null);
            if (readTimer.current) clearTimeout(readTimer.current);
        };
    }, [dealId, markRead]);

    // «Был(а) в сети 5 минут назад» стареет само по себе — перерисовываем
    const [, setClock] = useState(0);
    useEffect(() => {
        if (!deal || deal.counterpart_online !== false) return;
        const timer = setInterval(() => setClock((n) => n + 1), 30_000);
        return () => clearInterval(timer);
    }, [deal]);

    // --- Живые события -------------------------------------------------------

    const reconcile = useCallback((server: DealMessage, localId?: string) => {
        setMessages((prev) => {
            const known = prev.some((m) => m.id === server.id);
            if (localId) {
                return known
                    ? prev.filter((m) => m.localId !== localId)
                    : prev.map((m) => (m.localId === localId ? { ...server } : m));
            }
            if (known) return prev;
            // Событие о своём сообщении может прийти раньше ответа на отправку
            if (server.from === 'me') {
                const index = prev.findIndex((m) => m.pending === 'sending'
                    && (m.text ?? '') === (server.text ?? '')
                    && Boolean(m.localPhoto) === Boolean(server.photo_url));
                if (index >= 0) {
                    const next = [...prev];
                    next[index] = { ...server };
                    return next;
                }
            }
            return [...prev, server];
        });
    }, []);

    useEffect(() => {
        const off = realtime.subscribe((event) => {
            if (event?.deal_id !== dealId && event?.deal?.id !== dealId) return;

            if (event.type === 'deal_message') {
                reconcile(event.message);
                if (event.message.from !== 'me') markRead();
            } else if (event.type === 'deal_read') {
                setMessages((prev) => prev.map((m) =>
                    m.from === 'me' && !m.pending && m.created_at <= event.read_at
                        ? { ...m, state: 'read' } : m));
            } else if (event.type === 'deal_updated') {
                setDeal(event.deal);
            } else if (event.type === 'deal_presence') {
                setDeal((prev) => prev && {
                    ...prev,
                    counterpart_online: event.online,
                    counterpart_last_seen_at: event.last_seen_at ?? prev.counterpart_last_seen_at,
                });
            }
        });
        const offReconnect = realtime.onReconnect(() => { load(); });
        return () => {
            off();
            offReconnect();
        };
    }, [dealId, reconcile, markRead, load]);

    // --- Прокрутка -----------------------------------------------------------

    const onScroll = () => {
        const box = listRef.current;
        if (!box) return;
        stickToBottom.current = box.scrollHeight - box.scrollTop - box.clientHeight < 80;
    };

    useLayoutEffect(() => {
        const box = listRef.current;
        if (box && stickToBottom.current) box.scrollTop = box.scrollHeight;
    }, [messages, deal?.status]);

    // --- Отправка ------------------------------------------------------------

    const localMessage = (extra: Partial<ChatMessage>): ChatMessage => {
        const localId = `local-${Date.now()}-${Math.random().toString(36).slice(2)}`;
        return {
            id: localId,
            localId,
            from: 'me',
            kind: null,
            text: null,
            photo_url: null,
            legacy_media: null,
            created_at: new Date().toISOString(),
            state: null,
            pending: 'sending',
            ...extra,
        };
    };

    const deliver = async (message: ChatMessage, file?: File) => {
        stickToBottom.current = true;
        try {
            const server = file
                ? await p2pApi.sendPhoto(dealId, file, message.text ?? undefined)
                : await p2pApi.sendMessage(dealId, message.text ?? '');
            reconcile(server, message.localId);
            if (message.localPhoto) URL.revokeObjectURL(message.localPhoto);
        } catch (e) {
            haptic.notification('error');
            showToast(errorText(e, t('Сообщение не отправлено', 'Message not sent')), 'error');
            setMessages((prev) => prev.map((m) =>
                m.localId === message.localId ? { ...m, pending: 'failed', retryFile: file } : m));
        }
    };

    const sendText = () => {
        const text = draft.trim();
        if (!text || !deal?.chat_open) return;
        haptic.impact('light');
        const message = localMessage({ text });
        setMessages((prev) => [...prev, message]);
        setDraft('');
        fieldRef.current?.focus();
        deliver(message);
    };

    const pickPhoto = (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0];
        // Сбрасываем сразу: повторный выбор того же файла иначе не даст события
        e.target.value = '';
        if (!file) return;
        if (!file.type.startsWith('image/')) {
            showToast(t('Можно отправить только фото', 'Only photos can be sent'), 'error');
            return;
        }
        if (file.size > MAX_PHOTO) {
            showToast(t('Фото больше 20 МБ', 'The photo is larger than 20 MB'), 'error');
            return;
        }
        const message = localMessage({ localPhoto: URL.createObjectURL(file) });
        setMessages((prev) => [...prev, message]);
        deliver(message, file);
    };

    const retry = (message: ChatMessage) => {
        setMessages((prev) => prev.map((m) =>
            m.localId === message.localId ? { ...m, pending: 'sending' } : m));
        deliver({ ...message, pending: 'sending' }, message.retryFile);
    };

    // Поле растёт по тексту до 120px, дальше прокручивается. По черновику, а не
    // в обработчике ввода: после отправки поле должно снова стать в строку,
    // и черновик, восстановленный при возврате в чат, — сразу своей высоты
    useLayoutEffect(() => {
        const field = fieldRef.current;
        if (!field) return;
        field.style.height = 'auto';
        const needed = field.scrollHeight + 2;     // + рамка: scrollHeight её не считает
        field.style.height = `${Math.min(needed, 120)}px`;
        field.style.overflowY = needed > 120 ? 'auto' : 'hidden';
    }, [draft]);

    const onInput = (value: string) => {
        setDraft(value);
        if (value.trim() && Date.now() - lastTypingSent.current > TYPING_EVERY) {
            lastTypingSent.current = Date.now();
            realtime.send({ type: 'typing', deal_id: dealId });
        }
    };

    const copy = async (value: string) => {
        try {
            await navigator.clipboard.writeText(value);
            haptic.notification('success');
            showToast(t('Скопировано', 'Copied'), 'success');
        } catch {
            // navigator.clipboard есть не везде: в WebView Telegram он бывает
            // недоступен, поэтому запасной путь через выделение текста
            const area = document.createElement('textarea');
            area.value = value;
            area.style.position = 'fixed';
            area.style.opacity = '0';
            document.body.appendChild(area);
            area.select();
            const ok = document.execCommand('copy');
            area.remove();
            showToast(ok ? t('Скопировано', 'Copied') : t('Не удалось скопировать', 'Copy failed'), ok ? 'success' : 'error');
        }
    };

    // --- Действия по сделке ----------------------------------------------------

    const act = async (action: () => Promise<Deal>, success?: string) => {
        setBusy(true);
        try {
            setDeal(await action());
            setSheet(null);
            haptic.notification('success');
            if (success) showToast(success, 'success');
            stickToBottom.current = true;
            // Системное сообщение приходит событием; перечитываем на случай,
            // если сокет в этот момент переподключался
            const history = await p2pApi.getMessages(dealId);
            setMessages((prev) => [...history.messages, ...prev.filter((m) => m.pending)]);
        } catch (e) {
            haptic.notification('error');
            showToast(errorText(e, t('Не получилось', 'Something went wrong')), 'error');
        } finally {
            setBusy(false);
        }
    };

    // --- Разметка --------------------------------------------------------------

    if (failed && !deal) {
        return (
            <div className="dchat dchat-empty">
                <button className="btn-back" onClick={() => navigate('/chats')}>
                    <ArrowLeft size={20} />
                    <span>{t('Чаты', 'Chats')}</span>
                </button>
                <p>{failed}</p>
            </div>
        );
    }

    const warn = Boolean(deal?.chat_open) && CONTACT.test(draft);
    const buyer = deal?.role === 'buyer';
    const name = deal ? counterpartName(deal, t) : '';

    return (
        <div className="dchat">
            <header className="dchat-head">
                <button
                    type="button"
                    className="dchat-icon-btn"
                    onClick={goBack}
                    aria-label={t('Назад', 'Back')}
                >
                    <ArrowLeft size={22} />
                    {elsewhere > 0 && <span className="dchat-back-count">{elsewhere}</span>}
                </button>

                {deal && (
                    <span className="dchat-ava-wrap">
                        {buyer ? (
                            <span className="dchat-ava">
                                {deal.store?.avatar_url
                                    ? <img src={deal.store.avatar_url} alt="" />
                                    : name.trim().charAt(0).toUpperCase()}
                            </span>
                        ) : (
                            <span className="dchat-ava anon"><UserIcon size={20} /></span>
                        )}
                        {deal.counterpart_online && <span className="dchat-online-dot" />}
                    </span>
                )}

                <span className="dchat-head-text">
                    <span className="dchat-head-name">
                        <span>{name}</span>
                        {buyer && deal?.store?.verified && <BadgeCheck size={16} />}
                    </span>
                    {typing ? (
                        <span className="dchat-head-sub typing">{t('печатает…', 'typing…')}</span>
                    ) : deal?.counterpart_online ? (
                        <span className="dchat-head-sub online">{t('в сети', 'online')}</span>
                    ) : (
                        <span className="dchat-head-sub">
                            {deal
                                ? (deal.counterpart_online === false
                                    ? lastSeen(deal.counterpart_last_seen_at, language, t)
                                    : t(`Сделка №${deal.number}`, `Deal #${deal.number}`))
                                : ' '}
                        </span>
                    )}
                </span>
            </header>

            <div className="dchat-deal-wrap">
                {deal ? (
                    <DealCard
                        deal={deal}
                        language={language}
                        t={t}
                        busy={busy}
                        onShip={() => act(
                            () => p2pApi.markDelivered(dealId),
                            t('Отправка отмечена', 'Marked as sent'),
                        )}
                        onConfirm={() => setSheet('confirm')}
                        onProblem={() => setSheet('dispute')}
                        onRefund={() => setSheet('refund')}
                    />
                ) : (
                    <div className="dchat-deal skeleton dchat-deal-skeleton" />
                )}
            </div>

            <div className="dchat-msgs" ref={listRef} onScroll={onScroll} role="log" aria-live="polite">
                {deal?.chat_expired ? (
                    <div className="dchat-day">
                        {/* Без числа дней: срок меняется в настройках админки */}
                        {t(
                            'Переписка удалена: после завершения сделки она хранится несколько дней.',
                            'The conversation was deleted: it is kept for a few days after the deal ends.',
                        )}
                    </div>
                ) : deal && messages.length === 0 && (
                    <div className="dchat-day">
                        {t('Сообщений пока нет', 'No messages yet')}
                    </div>
                )}
                <MessageList
                    messages={messages}
                    language={language}
                    t={t}
                    onCopy={copy}
                    onRetry={retry}
                    onOpenPhoto={setViewer}
                />
            </div>

            <div className="dchat-compose">
                {warn && (
                    <div className="dchat-warn">
                        <AlertTriangle size={15} />
                        <span>
                            {t(
                                'Похоже на контакт. Договариваться в личке небезопасно: деньги защищены, только пока переписка идёт здесь.',
                                'Looks like contact details. Moving to private chat is unsafe: your money is protected only while you talk here.',
                            )}
                        </span>
                    </div>
                )}

                {deal && buyer && deal.status === 'released' && (
                    <DealReview deal={deal} t={t} onDone={load} />
                )}

                {deal && !deal.chat_open ? (
                    <div className="dchat-closed">
                        <Lock size={15} />
                        <span>
                            {deal.chat_expired
                                ? t('Сделка завершена.', 'The deal is closed.')
                                : deal.chat_expires_at
                                    ? t(
                                        `Сделка завершена, писать больше нельзя. Переписка удалится ${fmtDate(deal.chat_expires_at, language)} — сохраните ключи и данные, если они нужны.`,
                                        `The deal is closed, you can no longer write. The conversation will be deleted on ${fmtDate(deal.chat_expires_at, language)} — save any keys and details you need.`,
                                    )
                                    : t(
                                        'Сделка завершена. Писать больше нельзя.',
                                        'The deal is closed. You can no longer write.',
                                    )}
                        </span>
                    </div>
                ) : (
                    <div className="dchat-bar">
                        <button
                            type="button"
                            className="dchat-icon-btn muted"
                            onClick={() => fileRef.current?.click()}
                            disabled={!deal}
                            aria-label={t('Прикрепить фото', 'Attach a photo')}
                        >
                            <Paperclip size={21} />
                        </button>
                        <textarea
                            ref={fieldRef}
                            className="dchat-field"
                            rows={1}
                            value={draft}
                            onChange={(e) => onInput(e.target.value)}
                            onKeyDown={(e) => {
                                if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
                                    e.preventDefault();
                                    sendText();
                                }
                            }}
                            placeholder={t('Сообщение', 'Message')}
                            aria-label={t('Сообщение', 'Message')}
                            maxLength={2000}
                            disabled={!deal}
                        />
                        <button
                            type="button"
                            className="dchat-send"
                            onClick={sendText}
                            disabled={!draft.trim() || !deal}
                            aria-label={t('Отправить', 'Send')}
                        >
                            <ArrowUp size={19} />
                        </button>
                    </div>
                )}
                <input ref={fileRef} type="file" accept="image/*" hidden onChange={pickPhoto} />
            </div>

            {deal && sheet && (
                <DealSheet
                    kind={sheet}
                    deal={deal}
                    t={t}
                    busy={busy}
                    onClose={() => setSheet(null)}
                    onConfirm={() => act(() => p2pApi.confirmReceipt(dealId))}
                    onRefund={() => act(
                        () => p2pApi.refund(dealId),
                        t('Деньги возвращены покупателю', 'The buyer has been refunded'),
                    )}
                    onDispute={(reason) => act(() => p2pApi.openDispute(dealId, reason))}
                />
            )}

            {viewer && (
                <div className="dchat-viewer" onClick={() => setViewer(null)}>
                    <button type="button" className="dchat-viewer-close" aria-label={t('Закрыть', 'Close')}>
                        <X size={22} />
                    </button>
                    <img src={viewer} alt="" />
                </div>
            )}
        </div>
    );
};
