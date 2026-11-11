import { useEffect, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { ArrowLeft, ArrowRight, Check, Clock3, Gift, Info, RefreshCw, Users, X } from 'lucide-react';
import axios from 'axios';
import { thumb, webImage } from '@/lib/image';
import { apiClient } from '@/api/client';
import { useAuthStore } from '@/store/authStore';
import { errorText } from '@/store/toastStore';
import './Giveaways.css';

type Giveaway = {
    id: string; title_ru: string; title_en: string; prize: string; photo_url?: string | null;
    status: string; start_at: string; end_at: string; participants: number;
    winner: string | null; winner_username?: string | null;
    requirements: { id: string; title: string; join_link: string }[];
};
type Entry = { joined: boolean; status?: string; is_winner?: boolean; entry_label?: string };
type MembershipCheck = { requirement_id: string; joined: boolean };

export function Giveaways() {
    const { id } = useParams();
    const { language, accessToken } = useAuthStore();
    const ru = language === 'ru';
    const t = (r: string, en: string) => ru ? r : en;
    const [rows, setRows] = useState<Giveaway[]>([]);
    const [row, setRow] = useState<Giveaway | null>(null);
    const [entry, setEntry] = useState<Entry | null>(null);
    const [error, setError] = useState('');
    const [loading, setLoading] = useState(true);
    const [busy, setBusy] = useState(false);
    const [checks, setChecks] = useState<MembershipCheck[] | null>(null);
    const [showInfo, setShowInfo] = useState(false);
    const infoRef = useRef<HTMLDivElement>(null);
    const pageGeneration = useRef(0);
    const entryRevision = useRef(0);
    const [now, setNow] = useState(Date.now());
    const [retryAt, setRetryAt] = useState(0);
    const [skip, setSkip] = useState(0);
    const title = (gift: Giveaway) => ru ? gift.title_ru : gift.title_en;
    const date = (value: string) => new Date(value).toLocaleString(ru ? 'ru-RU' : 'en-US', { timeZone: 'Europe/Moscow' });

    useEffect(() => { const timer = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(timer); }, []);
    useEffect(() => {
        if (!showInfo) return;
        const outside = (event: MouseEvent) => { if (!infoRef.current?.contains(event.target as Node)) setShowInfo(false); };
        const escape = (event: KeyboardEvent) => { if (event.key === 'Escape') setShowInfo(false); };
        document.addEventListener('click', outside);
        document.addEventListener('keydown', escape);
        return () => { document.removeEventListener('click', outside); document.removeEventListener('keydown', escape); };
    }, [showInfo]);
    useEffect(() => {
        pageGeneration.current += 1;
        let live = true;
        async function load() {
            try {
                const result = await apiClient.get(id ? `/giveaways/${id}` : '/giveaways', { params: id ? undefined : { skip } });
                if (!live) return;
                if (id) setRow(result.data); else setRows(result.data);
                if (id && accessToken) {
                    const revision = entryRevision.current;
                    const my = await apiClient.get(`/giveaways/${id}/my-entry`);
                    if (live && revision === entryRevision.current) {
                        setEntry(my.data);
                        if (my.data.status === 'excluded') setChecks(null);
                    }
                }
                if (live) setError('');
            } catch (e) {
                if (live) {
                    if (axios.isAxiosError(e) && e.response?.status === 404) { setRow(null); setEntry(null); }
                    setError(errorText(e, t('Не удалось загрузить розыгрыш', 'Could not load giveaway')));
                }
            } finally { if (live) setLoading(false); }
        }
        setRow(null); setEntry(null); setChecks(null); setLoading(true); setError(''); setShowInfo(false); setBusy(false); setRetryAt(0);
        void load();
        const timer = setInterval(load, 15000);
        return () => { live = false; pageGeneration.current += 1; clearInterval(timer); };
    }, [id, accessToken, skip, language]);

    async function join() {
        if (busy || !row) return;
        const generation = pageGeneration.current;
        entryRevision.current += 1;
        setBusy(true); setError(''); setRetryAt(Date.now() + 10000);
        try {
            const response = await apiClient.post(`/giveaways/${row.id}/join`);
            if (generation !== pageGeneration.current) return;
            entryRevision.current += 1;
            setEntry(response.data); setChecks(response.data.checks);
            if (!response.data.joined) setError(t('Подпишитесь на все указанные каналы и чаты и повторите проверку.', 'Join every required channel and chat, then check again.'));
        } catch (e) { if (generation === pageGeneration.current) setError(errorText(e, t('Не удалось проверить подписки', 'Could not verify membership'))); }
        finally { if (generation === pageGeneration.current) setBusy(false); }
    }

    const winner = (gift: Giveaway) => (
        <p className="giveaway-result">{gift.winner ? <>{t('Победитель: ', 'Winner: ')}<strong>{gift.winner}</strong>{gift.winner_username && /^[a-z0-9_]{5,32}$/i.test(gift.winner_username)
            ? <> · <a href={`https://t.me/${gift.winner_username}`} target="_blank" rel="noopener noreferrer">@{gift.winner_username}</a></>
            : <span> · {t('username не задан', 'no username set')}</span>}</>
            : t('Подходящих участников не оказалось.', 'No eligible participants remained.')}</p>
    );
    const active = (gift: Giveaway) => ['open', 'scheduled'].includes(gift.status) && new Date(gift.start_at).getTime() <= now && now < new Date(gift.end_at).getTime();
    const canCheck = !!row && active(row) && !!accessToken && !busy && retryAt <= now && !entry?.joined;
    const rules = t('Подпишитесь на все каналы и оставайтесь подписанными до окончания. Нажмите «Участвовать» или значок справа для проверки. Если все подписки подтверждены, вы получите код участника. При отписке участие отменяется. Участие бесплатное. Имя и username победителя будут опубликованы, подарок передаёт организатор.',
        'Join every channel and stay subscribed until the deadline. Tap Enter or the icon on the right to check. Once all memberships are verified, you receive an entry code. Leaving cancels your entry. Entry is free. The winner’s name and username will be published, and the organizer delivers the gift.');

    function nft(gift: Giveaway) {
        const match = gift.prize.match(/^https:\/\/t\.me\/nft\/([a-z0-9]+)-(\d+)\/?(?:[?#].*)?$/i);
        const name = match?.[1];
        return { name: name ? name.replace(/([a-z0-9])([A-Z])/g, '$1 $2') : title(gift),
            number: match?.[2] || (/^\d+$/.test(gift.prize.trim()) ? gift.prize.trim() : '') };
    }

    function requirementRows(gift: Giveaway) {
        return <div className="giveaway-checklist">{gift.requirements.map(chat => {
            const verified = entry?.joined ? true : checks?.find(check => check.requirement_id === chat.id)?.joined;
            const username = chat.join_link.match(/^https:\/\/t\.me\/([a-z][a-z0-9_]{4,31})\/?$/i)?.[1];
            return <div key={chat.id} className="giveaway-requirement">
                <a href={chat.join_link} target="_blank" rel="noopener noreferrer" onClick={event => {
                    const tg = window.Telegram?.WebApp as unknown as { openTelegramLink?: (url: string) => void } | undefined;
                    if (tg?.openTelegramLink) { event.preventDefault(); tg.openTelegramLink(chat.join_link); }
                }}>{t('Подпишитесь на', 'Subscribe to')} <strong>{username ? `@${username}` : chat.title}</strong></a>
                <button type="button" className={`giveaway-check ${verified === true ? 'is-verified' : verified === false ? 'is-missing' : ''}`}
                    disabled={!canCheck} onClick={() => void join()}
                    aria-label={`${chat.title}: ${verified === true ? t('Подписка подтверждена', 'Membership verified') : t('Проверить подписки и участвовать', 'Check memberships and enter')}`}
                    title={verified === true ? t('Подписка подтверждена', 'Membership verified') : t('Проверить подписки и участвовать', 'Check memberships and enter')}>
                    {busy ? <RefreshCw size={19} className="giveaway-check-spin" /> : verified === true ? <Check size={22} /> : verified === false ? <X size={22} /> : <RefreshCw size={19} />}
                </button>
            </div>;
        })}</div>;
    }

    function countdown(gift: Giveaway, includeLabel = true) {
        const starting = new Date(gift.start_at).getTime() > now;
        const seconds = Math.max(0, Math.ceil((new Date(starting ? gift.start_at : gift.end_at).getTime() - now) / 1000));
        if (!seconds) return t('Подводим итоги', 'Drawing the winner');
        const days = Math.floor(seconds / 86400);
        const hours = Math.floor(seconds / 3600) % 24;
        const minutes = Math.floor(seconds / 60) % 60;
        const label = includeLabel ? `${starting ? t('До начала', 'Starts in') : t('До окончания', 'Ends in')} ` : '';
        return `${label}${days ? `${days} ${t('д', 'd')} ` : ''}${hours} ${t('ч', 'h')} ${minutes} ${t('мин', 'm')} ${seconds % 60} ${t('с', 's')}`;
    }

    function metadata(gift: Giveaway) {
        const number = gift.prize.match(/(?:^|\/)[a-z]+-(\d+)(?:$|[?#])/i)?.[1]
            || (/^\d+$/.test(gift.prize.trim()) ? gift.prize.trim() : null);
        const channels = gift.requirements.map(chat => chat.join_link.match(/^https:\/\/t\.me\/([a-z][a-z0-9_]{4,31})\/?$/i)?.[1]).filter(Boolean);
        return [number ? `#${number}` : '', ...channels.map(channel => `@${channel}`)].filter(Boolean).join(' · ');
    }

    function card(gift: Giveaway) {
        return <article key={gift.id} className="giveaway-tile">
            <div className="giveaway-tile-head">
                <Link className="giveaway-thumbnail" to={`/giveaways/${gift.id}`}>{gift.photo_url ? <img src={thumb(gift.photo_url)} alt={gift.prize} loading="lazy" decoding="async" /> : <Gift size={28} />}</Link>
                <div className="giveaway-name"><h3><Link to={`/giveaways/${gift.id}`}>{title(gift)}</Link></h3>
                    {metadata(gift) && <p>{metadata(gift)}</p>}</div>
                <span className="giveaway-status">{gift.status === 'finished' ? t('Завершён', 'Completed') : active(gift) ? t('Активен', 'Active') : t('Ожидание', 'Pending')}</span>
            </div>
            <div className="giveaway-facts"><p><span><Users size={18} />{t('Участники', 'Participants')}</span><strong>{gift.participants}</strong></p>
                {gift.status !== 'finished' && <p><span><Clock3 size={18} />{new Date(gift.start_at).getTime() > now ? t('До начала', 'Starts in') : t('Оставшееся время', 'Time remaining')}</span><time dateTime={gift.end_at} title={`${date(gift.end_at)} МСК`}>{countdown(gift, false)}</time></p>}
            </div>
            {gift.status === 'finished' && winner(gift)}
            <Link className="giveaway-enter giveaway-card-action" to={`/giveaways/${gift.id}`}>{gift.status === 'finished' ? t('Итоги', 'Results') : active(gift) ? t('Участвовать', 'Enter') : t('Открыть', 'Open')}<ArrowRight size={18} /></Link>
        </article>;
    }

    return <div className="growth-page"><main className="container growth-stack giveaways-page">
        {!id && <><Link className="giveaway-back" to="/profile"><ArrowLeft size={19} />{t('В профиль', 'Back to profile')}</Link>
        <h1 className="giveaways-title">{t('Розыгрыши', 'Giveaways')}</h1></>}
        {error && !id && <p role="alert">{error}</p>}
        {loading && <p role="status">{t('Загрузка…', 'Loading…')}</p>}
        {!id && !loading && <>
            {!!rows.filter(gift => gift.status !== 'finished').length && <section className="giveaway-group"><h2>{t('Активные', 'Active')}</h2>{rows.filter(gift => gift.status !== 'finished').map(card)}</section>}
            {!!rows.filter(gift => gift.status === 'finished').length && <section className="giveaway-group"><h2>{t('Завершённые', 'Completed')}</h2>{rows.filter(gift => gift.status === 'finished').map(card)}</section>}
            {!rows.length && !error && <p>{t('Розыгрышей пока нет.', 'No giveaways yet.')}</p>}
            {(skip > 0 || rows.length === 20) && <div className="growth-actions"><button disabled={!skip} onClick={() => setSkip(Math.max(0, skip - 20))}>{t('Назад', 'Previous')}</button><button disabled={rows.length < 20} onClick={() => setSkip(skip + 20)}>{t('Далее', 'Next')}</button></div>}
        </>}
        {row && <article className="giveaway-tile giveaway-detail" aria-label={t('Розыгрыш NFT', 'NFT giveaway')}>
            <Link className="giveaway-close" to="/giveaways" aria-label={t('Закрыть розыгрыш', 'Close giveaway')}><X size={24} /></Link>
            <div className="giveaway-prize">
                {row.photo_url ? <img src={webImage(row.photo_url)} alt={nft(row).name} decoding="async" /> : <div className="giveaway-prize-placeholder"><Gift size={64} /></div>}
                <div className="giveaway-prize-caption"><h1>{nft(row).name}</h1>{nft(row).number && <p>#{nft(row).number}</p>}</div>
            </div>
            {row.status !== 'finished' && <p className="giveaway-detail-timer"><Clock3 size={16} /><time dateTime={row.end_at} title={`${date(row.end_at)} МСК`}>{countdown(row)}</time></p>}
            {row.status === 'finished' && winner(row)}
            {entry?.is_winner && <p role="status">{t('Вы победили! Свяжитесь с поддержкой для получения подарка.', 'You won! Contact support to receive your gift.')}</p>}
            <div ref={infoRef}>
                <div className="giveaway-requirements-head">
                    <h2>{t('Проверка требований', 'Requirements')}</h2>
                    <button type="button" className="giveaway-info-button" onClick={() => setShowInfo(value => !value)}
                        aria-label={t('Условия участия', 'Entry rules')} aria-expanded={showInfo} aria-controls="giveaway-rules"><Info size={22} /></button>
                </div>
                <div id="giveaway-rules" role="note" className="giveaway-info-note" hidden={!showInfo}>{rules}</div>
            </div>
            {requirementRows(row)}
            {entry?.joined && entry.entry_label && <div className="giveaway-entry-code" role="status"><span>{t('Ваш код участника', 'Your entry code')}</span><strong>{entry.entry_label.replace(/^Участник\s+/i, '')}</strong></div>}
            {entry?.status === 'excluded' && <p role="status">{t('Участие отменено: подписка на обязательный канал или чат не подтверждена.', 'Entry cancelled: a required membership was not confirmed.')}</p>}
            {row.status !== 'finished' && now >= new Date(row.end_at).getTime() && <p role="status">{t('Приём заявок завершён. Определяем победителя.', 'Entries closed. The winner is being determined.')}</p>}
            {error && <p role="alert" className="giveaway-detail-error">{error}</p>}
            {active(row) && <button className="giveaway-enter giveaway-detail-action" disabled={!canCheck} onClick={() => void join()}>{entry?.joined ? <><Check size={19} />{t('Вы участвуете', 'Entered')}</> : busy ? t('Проверяем…', 'Checking…') : retryAt > now ? `${t('Проверить через', 'Check in')} ${Math.ceil((retryAt - now) / 1000)} ${t('с', 's')}` : t('Участвовать', 'Enter')}</button>}
        </article>}
    </main></div>;
}
