import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { Link, useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { ArrowLeft, ImagePlus, Send, X } from 'lucide-react';
import axios from 'axios';
import { inquiriesApi, type InquiryPreview, type InquiryMessage } from '@/api/inquiries';
import { ChatAvatar } from '@/components/ChatAvatar/ChatAvatar';
import { useAuthStore } from '@/store/authStore';
import { useInquiryStore } from '@/store/inquiryStore';
import { errorText } from '@/store/toastStore';
import { realtime } from '@/lib/realtime';
import './InquiryChat.css';

const merge = (old: InquiryMessage[], fresh: InquiryMessage[]) => [...new Map([...old, ...fresh].map(row => [row.id, row])).values()]
    .sort((a, b) => a.created_at.localeCompare(b.created_at) || a.id.localeCompare(b.id));

export function InquiryChat() {
    const { id } = useParams();
    const [search] = useSearchParams();
    const isDraft = id === 'new';
    const storeId = search.get('store') || '';
    const storeKind = search.get('kind') === 'channel' ? 'channel' : 'seller';
    const chatKey = isDraft ? `new:${storeKind}:${storeId}` : id;
    const { language } = useAuthStore();
    const navigate = useNavigate();
    const location = useLocation();
    const ru = language === 'ru';
    const [chat, setChat] = useState<InquiryPreview | null>(null);
    const [messages, setMessages] = useState<InquiryMessage[]>([]);
    const [text, setText] = useState('');
    const [photo, setPhoto] = useState<File | null>(null);
    const [preview, setPreview] = useState('');
    const [error, setError] = useState('');
    const [expired, setExpired] = useState(false);
    const [sending, setSending] = useState(false);
    const [hasMore, setHasMore] = useState(false);
    const [loadingOlder, setLoadingOlder] = useState(false);
    const fileInput = useRef<HTMLInputElement>(null);
    const nonce = useRef<string | null>(null);
    const inFlight = useRef(false);
    const loadedOlder = useRef(false);
    const field = useRef<HTMLTextAreaElement>(null);
    const list = useRef<HTMLDivElement>(null);
    const content = useRef<HTMLDivElement>(null);
    const stickToBottom = useRef(true);
    const prepend = useRef<{ height: number; top: number } | null>(null);
    const activeChatId = useRef<string | null>(null);
    const alive = useRef(false);

    useEffect(() => {
        alive.current = true;
        return () => { alive.current = false; };
    }, []);

    useLayoutEffect(() => {
        const box = list.current;
        if (!box) return;
        if (prepend.current) {
            box.scrollTop = prepend.current.top + box.scrollHeight - prepend.current.height;
            prepend.current = null;
        } else if (stickToBottom.current) box.scrollTop = box.scrollHeight;
    }, [messages]);

    useEffect(() => {
        const box = list.current;
        if (!box || !content.current) return;
        const observer = new ResizeObserver(() => {
            if (stickToBottom.current) box.scrollTop = box.scrollHeight;
        });
        observer.observe(box);
        observer.observe(content.current);
        return () => observer.disconnect();
    }, []);

    useEffect(() => {
        if (!photo) { setPreview(''); return; }
        const url = URL.createObjectURL(photo); setPreview(url); return () => URL.revokeObjectURL(url);
    }, [photo]);
    useEffect(() => {
        if (!id) return;
        let live = true;
        loadedOlder.current = false;
        if (activeChatId.current !== chatKey) {
            activeChatId.current = chatKey ?? null;
            stickToBottom.current = true;
            prepend.current = null;
            setMessages([]); setChat(null);
        }
        setExpired(false);
        if (isDraft) {
            void inquiriesApi.prepare(storeId, storeKind).then(preview => {
                if (!live) return;
                if (preview.deal_id) { navigate(`/my/deals/${preview.deal_id}`, { replace: true }); return; }
                if (preview.id) { navigate(`/chats/seller/${preview.id}`, { replace: true }); return; }
                setChat(preview); setError(''); setHasMore(false);
            }).catch(e => { if (live) setError(errorText(e, ru ? 'Не удалось открыть чат' : 'Could not open conversation')); });
            return () => { live = false; };
        }
        async function load() {
            try {
                const page = await inquiriesApi.detail(id!);
                if (!live) return;
                if (page.chat.deal_id) { navigate(`/my/deals/${page.chat.deal_id}`, { replace: true }); return; }
                setChat(page.chat); setMessages(old => merge(old, page.messages)); setError('');
                if (!loadedOlder.current) setHasMore(page.has_more);
                if (page.chat.unread && document.visibilityState === 'visible') {
                    await inquiriesApi.read(id!); useInquiryStore.getState().clearUnread(id!);
                }
            } catch (e) {
                if (!live) return;
                if (axios.isAxiosError(e) && e.response?.status === 404) { setExpired(true); setMessages([]); }
                setError(errorText(e, ru ? 'Не удалось загрузить переписку' : 'Could not load conversation'));
            }
        }
        void load();
        const interval = setInterval(() => void load(), 4000);
        const unsubscribe = realtime.subscribe(event => { if (event?.type === 'inquiry_message' && event.chat_id === id) void load(); });
        return () => { live = false; clearInterval(interval); unsubscribe(); };
    }, [id, ru, navigate, isDraft, storeId, storeKind]);

    async function older() {
        if (!id || !messages[0] || loadingOlder) return;
        setLoadingOlder(true);
        try {
            const page = await inquiriesApi.detail(id, messages[0].id);
            if (!alive.current || activeChatId.current !== chatKey) return;
            const box = list.current;
            if (box) prepend.current = { height: box.scrollHeight, top: box.scrollTop };
            stickToBottom.current = false;
            loadedOlder.current = true;
            setMessages(old => merge(old, page.messages));
            setHasMore(page.has_more);
        }
        catch (e) { setError(errorText(e, ru ? 'Не удалось загрузить сообщения' : 'Could not load messages')); }
        finally { setLoadingOlder(false); }
    }
    async function send(event: React.FormEvent) {
        event.preventDefault();
        if (!id || !chat || expired || inFlight.current || (!text.trim() && !photo)) return;
        inFlight.current = true; setSending(true); setError('');
        nonce.current ??= crypto.randomUUID();
        const sentText = text;
        const sentPhoto = photo;
        const clientId = nonce.current;
        field.current?.focus({ preventScroll: true });
        stickToBottom.current = true;
        const clearSent = () => {
            setText(current => current.startsWith(sentText) ? current.slice(sentText.length) : current);
            setPhoto(current => current === sentPhoto ? null : current);
            if (nonce.current === clientId) nonce.current = null;
        };
        try {
            if (isDraft) {
                const created = await inquiriesApi.start(storeId, storeKind, sentText, sentPhoto, clientId);
                if (!alive.current || activeChatId.current !== chatKey) return;
                clearSent();
                // Keep the composer mounted during draft -> persisted chat.
                activeChatId.current = created.chat.id;
                setChat(created.chat);
                setMessages([created.message]);
                void useInquiryStore.getState().load().catch(() => undefined);
                navigate(`/chats/seller/${created.chat.id}`, { replace: true });
                return;
            }
            const message = await inquiriesApi.send(id, sentText, sentPhoto, clientId);
            if (!alive.current || activeChatId.current !== chatKey) return;
            setMessages(old => merge(old, [message]));
            clearSent();
            void useInquiryStore.getState().load().catch(() => undefined);
        } catch (e) { setError(errorText(e, ru ? 'Не удалось отправить. Повторите попытку.' : 'Could not send. Try again.')); }
        finally { inFlight.current = false; setSending(false); }
    }

    return <div className="inquiry-chat"><header className="inquiry-chat-head"><Link to="/chats" aria-label={ru ? 'Назад к чатам' : 'Back to chats'}><ArrowLeft size={22} /></Link>
        {(chat || location.state?.storeAvatar) && <ChatAvatar src={chat?.avatar_url ?? location.state?.storeAvatar} />}
        <h1>{chat ? chat.name === 'Покупатель' && !ru ? 'Buyer' : chat.name : location.state?.storeName || (ru ? 'Чат с продавцом' : 'Seller chat')}</h1></header>
        <div className="inquiry-chat-body" ref={list} onScroll={() => {
            const box = list.current;
            if (box) stickToBottom.current = box.scrollHeight - box.scrollTop - box.clientHeight < 80;
        }}>
            {chat && !expired && <p className="inquiry-policy">{chat.paid ? (ru ? 'Покупка подтверждена. Переписка хранится по правилам чатов после покупки.' : 'Purchase confirmed. The after-purchase chat retention policy applies.') : (ru ? 'Если покупки не будет, сообщения и фото будут полностью удалены через 72 часа после первого сообщения.' : 'Without a purchase, messages and photos will be deleted 72 hours after the first message.')}
                {chat.expires_at && <><br />{ru ? 'Удаление: ' : 'Deletion: '}{new Date(chat.expires_at).toLocaleString(ru ? 'ru-RU' : 'en-US')}</>}</p>}
            {error && <p role="alert">{error}</p>}
            {!chat && !error && <p role="status">{ru ? 'Загрузка…' : 'Loading…'}</p>}
            {hasMore && !expired && <button type="button" onClick={() => void older()} disabled={loadingOlder}>{ru ? 'Ранее' : 'Older messages'}</button>}
            <div className="inquiry-messages" ref={content} role="log" aria-live="polite">{messages.map(message => <div key={message.id} className={`inquiry-message-row ${message.mine ? 'is-mine' : ''}`}>
                <ChatAvatar src={message.mine ? chat?.my_avatar_url : chat?.avatar_url} />
                <article className={`inquiry-bubble ${message.mine ? 'is-mine' : ''}`}>
                {message.photo_url && <a href={message.photo_url} target="_blank" rel="noopener noreferrer"><img src={message.photo_url} alt={ru ? 'Фото в переписке' : 'Conversation photo'} loading="lazy" /></a>}
                {message.text && <p>{message.text}</p>}<time dateTime={message.created_at}>{new Date(message.created_at).toLocaleTimeString(ru ? 'ru-RU' : 'en-US', { hour: '2-digit', minute: '2-digit' })}</time>
            </article></div>)}</div>
        </div>
        {chat && !expired && <form className="inquiry-composer" onSubmit={send}>
            {preview && <div className="inquiry-photo-preview"><img src={preview} alt={ru ? 'Выбранное фото' : 'Selected photo'} /><button type="button" disabled={sending} aria-label={ru ? 'Убрать фото' : 'Remove photo'} onClick={() => { setPhoto(null); nonce.current = null; }}><X size={18} /></button></div>}
            <input type="file" ref={fileInput} hidden accept="image/*" onChange={event => { const file = event.target.files?.[0]; event.target.value = ''; if (file) { setPhoto(file); nonce.current = null; } }} />
            <button type="button" disabled={sending} aria-label={ru ? 'Добавить фото' : 'Add photo'} onClick={() => fileInput.current?.click()}><ImagePlus size={22} /></button>
            <textarea ref={field} aria-label={ru ? 'Сообщение' : 'Message'} value={text} maxLength={2000} rows={1} placeholder={ru ? 'Сообщение…' : 'Message…'} onChange={event => { setText(event.target.value); nonce.current = null; }} />
            <button type="submit" onPointerDown={event => event.preventDefault()} disabled={sending || (!text.trim() && !photo)} aria-label={ru ? 'Отправить сообщение' : 'Send message'}><Send size={22} /></button>
        </form>}
    </div>;
}
