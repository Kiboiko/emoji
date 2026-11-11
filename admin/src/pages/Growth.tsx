import { useEffect, useRef, useState } from 'react';
import api from '../api/axios';
import { errorText } from '../components/ui/Toast';

const field = 'w-full rounded bg-gray-900 border border-gray-600 p-2 text-white';
const button = 'rounded bg-blue-600 text-white px-3 py-2 disabled:opacity-40';
const panel = 'rounded-xl bg-gray-800 p-4 space-y-3';

function useRequest() {
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');
    async function run(task: () => Promise<void>) {
        setBusy(true); setError('');
        try { await task(); } catch (e) { setError(errorText(e, 'Не удалось выполнить действие')); }
        finally { setBusy(false); }
    }
    return { busy, error, run };
}

export function MarketRanking() {
    const [data, setData] = useState<any>(null);
    const [skip, setSkip] = useState(0);
    const { busy, error, run } = useRequest();
    const load = async () => setData((await api.get('/api/admin/market-rankings', { params: { skip } })).data);
    useEffect(() => { run(load); }, [skip]);
    async function toggle(kind: string, row: any, key: string) {
        await api.patch(`/api/admin/market-rankings/${kind}/${row.id}`, { [key]: !row[key] });
        await load();
    }
    return <div className="space-y-5">
        <h1 className="text-2xl text-white">Рейтинг маркетов</h1>
        <p className="text-gray-400">70% — оборот, 30% — отзывы. Неделя начинается в понедельник по Москве. Состав фиксируется при открытии недели; изменения участия действуют со следующей. Показ на главной меняется сразу.</p>
        {error && <p role="alert" className="text-red-400">{error}</p>}
        <button className={button} disabled={busy} onClick={() => run(async () => { await api.post('/api/admin/market-rankings/refresh'); await load(); })}>Обновить рейтинг / открыть первый период</button>
        <section className={panel}><h2>Участники и главная</h2>
            {data?.sellers.map((row: any) => <div key={row.id} className="flex flex-wrap gap-3 items-center border-b border-gray-700 py-2">
                <strong className="mr-auto">{row.name}</strong>
                <label><input type="checkbox" checked={row.home_visible} disabled={busy} onChange={() => run(() => toggle('sellers', row, 'home_visible'))} /> На главной</label>
                {!row.is_platform && <label><input type="checkbox" checked={row.ranking_enabled} disabled={busy} onChange={() => run(() => toggle('sellers', row, 'ranking_enabled'))} /> Участие в рейтинге</label>}
            </div>)}
            <div className="flex gap-2"><button disabled={!skip || busy} onClick={() => setSkip(Math.max(0, skip - 100))}>Назад</button><button disabled={busy || (data?.sellers.length ?? 0) < 100} onClick={() => setSkip(skip + 100)}>Далее</button></div>
        </section>
        <section className={panel}><h2>Текущая неделя · финансовая статистика видна только администратору</h2>
            {!data?.ranking.period && <p>Период пока не открыт. Выберите участников и обновите рейтинг.</p>}
            {data?.ranking.period && <p>{new Date(data.ranking.period.start_at).toLocaleString()} — {new Date(data.ranking.period.end_at).toLocaleString()}</p>}
            {data?.ranking.items.map((row: any) => <div key={row.id} className="flex flex-wrap gap-3 border-b border-gray-700 py-2"><b>#{row.rank} {row.name}</b><span>Оборот: ${(Number(row.volume_cents) / 100).toFixed(2)}</span><span>Сделок: {row.sales_count}</span><span>Отзывов: {row.review_count}</span><span>Баллы: {Number(row.score).toFixed(2)}</span></div>)}
        </section>
    </div>;
}

function nanoAmount(value: string) {
    if (!/^[0-9]+(?:[.][0-9]{1,9})?$/.test(value)) throw new Error('Введите Gram, не более 9 знаков после точки');
    const [whole, fraction = ''] = value.split('.');
    const amount = BigInt(whole) * 1000000000n + BigInt(fraction.padEnd(9, '0'));
    if (amount > BigInt(Number.MAX_SAFE_INTEGER)) throw new Error('Слишком большая сумма');
    return Number(amount);
}

export function Publications() {
    const [config, setConfig] = useState<any>(null);
    const [rows, setRows] = useState<any[]>([]);
    const [skip, setSkip] = useState(0);
    const { busy, error, run } = useRequest();
    const load = async () => { const [c, r] = await Promise.all([api.get('/api/admin/publications/config'), api.get('/api/admin/publications', { params: { skip } })]); setConfig(c.data); setRows(r.data); };
    useEffect(() => { run(load); }, [skip]);
    async function resolve(row: any, action: string) {
        const message = action === 'confirmed_sent' ? window.prompt('ID найденного сообщения в чате') : null;
        if (action === 'confirmed_sent' && !message) return;
        if (!window.confirm('Подтвердить результат сверки доставки? Повтор может создать дубль, если сообщение уже есть.')) return;
        await api.post(`/api/admin/publications/${row.id}/resolve`, { action, message_id: message ? Number(message) : null });
        await load();
    }
    return <div className="space-y-5"><h1 className="text-2xl">Крупные сделки</h1>
        <p className="text-gray-400">Публикуются только новые завершённые сделки после включения. Предпросмотр не отправляет сообщений. Неопределённую доставку сначала сверяйте в чате.</p>
        {error && <p className="text-red-400" role="alert">{error}</p>}
        {config && <form className={panel} onSubmit={e => { e.preventDefault(); run(async () => { await api.put('/api/admin/publications/config', { enabled: config.enabled, min_nano: nanoAmount(config.min_gram), chat_id: config.chat_id ? Number(config.chat_id) : null, thread_id: config.thread_id ? Number(config.thread_id) : null }); await load(); }); }}>
            <label className="block">Порог, Gram<input className={field} value={config.min_gram} onChange={e => setConfig({ ...config, min_gram: e.target.value.replace(',', '.') })} /></label>
            <label className="block">ID чата<input className={field} value={config.chat_id} onChange={e => setConfig({ ...config, chat_id: e.target.value })} /></label>
            <label className="block">ID темы, если нужна<input className={field} value={config.thread_id ?? ''} onChange={e => setConfig({ ...config, thread_id: e.target.value })} /></label>
            <label className="block"><input type="checkbox" checked={config.enabled} onChange={e => setConfig({ ...config, enabled: e.target.checked })} /> Включить реальные публикации новых сделок</label>
            <p>Пример: «Завершена крупная сделка · Товар · Магазин · {config.min_gram} Gram»</p>
            <button className={button} disabled={busy}>Проверить права и сохранить</button>
        </form>}
        <section className={panel}><h2>Журнал доставки</h2>
            <button disabled={busy} onClick={() => run(load)}>Обновить</button>
            {rows.map(row => <article key={row.id} className="border-b border-gray-700 py-3"><b>{row.status}</b> · попыток {row.attempts} · {row.error_code}<pre className="whitespace-pre-wrap text-sm">{row.preview}</pre>
                {row.status === 'unknown' && <div className="flex flex-wrap gap-3"><button onClick={() => run(() => resolve(row, 'confirmed_sent'))} disabled={busy}>Сообщение найдено</button><button onClick={() => run(() => resolve(row, 'confirmed_not_sent'))} disabled={busy}>Точно не отправлено — повторить</button><button onClick={() => run(() => resolve(row, 'suppress'))} disabled={busy}>Не отправлять</button></div>}
            </article>)}
            <div className="flex gap-3"><button disabled={!skip || busy} onClick={() => setSkip(Math.max(0, skip - 50))}>Назад</button><button disabled={rows.length < 50 || busy} onClick={() => setSkip(skip + 50)}>Далее</button></div>
        </section>
    </div>;
}

const localTime = (value: string) => { const date = new Date(value); return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16); };
const blank = () => ({ description_ru: '', description_en: '', prize: '', photo_url: '', nft_link: '', post_chat_id: '', start_at: localTime(new Date().toISOString()), end_at: localTime(new Date(Date.now() + 86400000).toISOString()), requirements: [{ chat_id: '', title: '', join_link: '' }] });

export function AdminGiveaways() {
    const [rows, setRows] = useState<any[]>([]);
    const [cleanup, setCleanup] = useState({ pending: 0, retrying: 0 });
    const [draft, setDraft] = useState<any>(null);
    const [participants, setParticipants] = useState<any[] | null>(null);
    const [selected, setSelected] = useState<string | null>(null);
    const [skip, setSkip] = useState(0);
    const [entrySkip, setEntrySkip] = useState(0);
    const [history, setHistory] = useState<{ id: string; rows: any[]; skip: number } | null>(null);
    const [postChannels, setPostChannels] = useState<{ chat_id: string; title: string; username?: string | null }[]>([]);
    const [newPostChannel, setNewPostChannel] = useState('');
    const loadedNFT = useRef('');
    const { busy, error, run } = useRequest();
    const load = async () => {
        const [list, status, channels] = await Promise.all([api.get('/api/admin/giveaways', { params: { skip } }), api.get('/api/admin/giveaways/cleanup-status'), api.get('/api/admin/giveaways/post-channels')]);
        setRows(list.data); setCleanup(status.data); setPostChannels(channels.data);
    };
    useEffect(() => { run(load); }, [skip]);
    useEffect(() => {
        const link = draft?.nft_link?.trim() || '';
        if (!/^https:\/\/t\.me\/nft\/[A-Za-z0-9]+-[1-9][0-9]*\/?(?:[?#].*)?$/.test(link) || loadedNFT.current === link) return;
        let live = true;
        const timer = setTimeout(() => { void run(async () => {
            const response = await api.post('/api/admin/giveaways/photo-from-nft', { url: link });
            if (!live) return;
            loadedNFT.current = link;
            setDraft((current: any) => current?.nft_link?.trim() === link ? { ...current, photo_url: response.data.url, prize: link } : current);
        }); }, 600);
        return () => { live = false; clearTimeout(timer); };
    }, [draft?.nft_link]);
    async function action(id: string, operation: string) { await api.post(`/api/admin/giveaways/${id}/${operation}`); if (operation === 'cancel') { setParticipants(null); setHistory(null); if (draft?.id === id) setDraft(null); } await load(); }
    async function entries(id: string, offset = 0) { setSelected(id); setEntrySkip(offset); setParticipants((await api.get(`/api/admin/giveaways/${id}/participants`, { params: { skip: offset } })).data); }
    async function attempts(id: string, offset = 0) { setHistory({ id, skip: offset, rows: (await api.get(`/api/admin/giveaways/${id}/draw-attempts`, { params: { skip: offset } })).data }); }
    return <div className="space-y-5"><h1 className="text-2xl">Розыгрыши подарков</h1>
        <p className="text-gray-400">Один победитель, бесплатное участие. Приз выдаётся вручную. После публикации условия и сроки нельзя менять.</p>
        {error && <p role="alert" className="text-red-400">{error}</p>}
        {cleanup.pending > 0 && <p role="status">Постов в очереди очистки: {cleanup.pending}. Повторов после ошибки: {cleanup.retrying}. Если очередь не уменьшается, проверьте права бота в канале. Для постов старше 48 часов содержимое заменяется нейтральным сообщением.</p>}
        <div className="flex gap-3"><button className={button} disabled={busy} onClick={() => { loadedNFT.current = ''; setDraft(blank()); }}>Новый розыгрыш</button><button disabled={busy} onClick={() => run(load)}>Обновить</button></div>
        {draft && <form className={panel} onSubmit={e => {
            e.preventDefault();
            const publish = (e.nativeEvent as SubmitEvent).submitter?.getAttribute('value') === 'publish';
            run(async () => {
                const body = { prize: draft.nft_link?.trim() || draft.prize, nft_link: draft.nft_link || null,
                    description_ru: draft.description_ru || '', description_en: draft.description_en || '',
                    start_at: new Date(draft.start_at).toISOString(), end_at: new Date(draft.end_at).toISOString(), photo_url: draft.photo_url || null,
                    post_chat_id: draft.post_chat_id ? Number(draft.post_chat_id) : null, requirements: draft.requirements.map((r: any) => ({ ...r, chat_id: Number(r.chat_id) })) };
                const response = draft.id ? await api.put(`/api/admin/giveaways/${draft.id}`, body) : await api.post('/api/admin/giveaways', body);
                setDraft({ ...draft, id: response.data.id });
                if (publish) await api.post(`/api/admin/giveaways/${response.data.id}/publish`);
                setDraft(null); await load();
            });
        }}>
            <fieldset disabled={busy} className="space-y-3 min-w-0">
            <label className="block">Ссылка Telegram NFT<input className={field} type="url" placeholder="https://t.me/nft/PlushPepe-171" value={draft.nft_link || ''} onChange={e => { loadedNFT.current = ''; setDraft({ ...draft, nft_link: e.target.value, photo_url: '' }); }} /></label>
            <p className="text-sm text-gray-400">Вставьте полную ссылку на подарок, одного номера NFT недостаточно. Фото загрузится автоматически, в том числе при сохранении и запуске.</p>
            <button type="button" disabled={busy || !draft.nft_link} onClick={() => run(async () => {
                const response = await api.post('/api/admin/giveaways/photo-from-nft', { url: draft.nft_link });
                setDraft((d: any) => ({ ...d, photo_url: response.data.url, prize: d.prize || d.nft_link }));
            })}>Загрузить фото по ссылке NFT</button>
            <label className="block">NFT / приз<input aria-label="NFT / приз" className={field} required value={draft.prize} onChange={e => setDraft({ ...draft, prize: e.target.value })} /></label>
            <label className="block">Канал публикации<select className={field} value={draft.post_chat_id || ''} onChange={e => setDraft({ ...draft, post_chat_id: e.target.value })}>
                <option value="">Без публикации поста</option>
                {draft.post_chat_id && !postChannels.some(channel => channel.chat_id === String(draft.post_chat_id)) && <option value={draft.post_chat_id}>Канал {draft.post_chat_id}</option>}
                {postChannels.map(channel => <option key={channel.chat_id} value={channel.chat_id}>{channel.title}{channel.username ? ` · @${channel.username.replace(/^@/, '')}` : ''}</option>)}
            </select></label>
            <div className="flex flex-wrap gap-2"><input className={field} aria-label="Добавить канал публикации" placeholder="@username или ID другого канала" value={newPostChannel} onChange={e => setNewPostChannel(e.target.value)} />
                <button type="button" disabled={busy || !newPostChannel.trim()} onClick={() => run(async () => {
                    const response = await api.post('/api/admin/giveaways/resolve-post-channel', { channel: newPostChannel.trim() });
                    setPostChannels(current => [...current.filter(channel => channel.chat_id !== response.data.chat_id), response.data]);
                    setDraft((current: any) => ({ ...current, post_chat_id: response.data.chat_id })); setNewPostChannel('');
                })}>Проверить и выбрать канал</button></div>
            <p className="text-sm text-gray-400">Если указан канал, после публикации бот отправит фото с кнопкой «Участвовать». Нужны права публикации. Активный розыгрыш нельзя менять; завершённые удаляются через 30 дней.</p>
            <label className="block">Фото подарка<input type="file" accept="image/jpeg,image/png,image/webp" disabled={busy} onChange={e => { const file = e.target.files?.[0]; if (file) run(async () => { const form = new FormData(); form.append('file', file); const response = await api.post('/api/admin/giveaways/photo', form, { headers: { 'Content-Type': 'multipart/form-data' } }); setDraft((d: any) => ({ ...d, photo_url: response.data.url })); }); }} /></label>
            {draft.photo_url && <img src={draft.photo_url} alt="Фото подарка" className="w-24 h-24 object-cover" />}
            {['start_at', 'end_at'].map(key => <label key={key} className="block">{key === 'start_at' ? 'Начало' : 'Окончание'} (в вашем часовом поясе)<input className={field} type="datetime-local" required value={draft[key]} onChange={e => setDraft({ ...draft, [key]: e.target.value })} /></label>)}
            <h3>Обязательные чаты: бот должен быть администратором</h3>
            {draft.requirements.map((r: any, i: number) => <div key={i} className="space-y-1 border border-gray-600 p-2">
                {['chat_id', 'title', 'join_link'].map((key, n) => <label key={key} className="block">{['ID чата (отрицательное число)', 'Название', 'Ссылка https://t.me/...'][n]}<input className={field} required value={r[key]} onChange={e => setDraft({ ...draft, requirements: draft.requirements.map((c: any, k: number) => k === i ? { ...c, [key]: e.target.value } : c) })} /></label>)}
                {draft.requirements.length > 1 && <button type="button" onClick={() => setDraft({ ...draft, requirements: draft.requirements.filter((_: any, k: number) => k !== i) })}>Убрать чат</button>}
            </div>)}
            <div className="flex flex-wrap gap-3"><button type="button" disabled={draft.requirements.length >= 10} onClick={() => setDraft({ ...draft, requirements: [...draft.requirements, { chat_id: '', title: '', join_link: '' }] })}>Добавить чат</button><button type="submit" className={button} value="publish" disabled={busy}>Проверить и запустить</button><button type="submit" value="draft" disabled={busy}>Сохранить черновик</button><button type="button" onClick={() => setDraft(null)}>Закрыть</button></div>
            </fieldset>
        </form>}
        {rows.map(row => <article className={panel} key={row.id}><h2 className="text-lg">{row.title_ru} · {row.status}</h2><p>{row.prize} · до {new Date(row.end_at).toLocaleString()}</p><p>Заявок: {row.participants}; победитель: {row.winner ?? 'пока не определён'}; выдача: {row.fulfillment_status}</p>{row.error_code && <p role="status">Ожидание: {row.error_code}. Проверка продолжится автоматически.</p>}
            <p>Пост бота: {row.post_status}{row.post_message_id ? ` · ID ${row.post_message_id}` : ''}</p>
            {['unknown', 'sending'].includes(row.post_status) && <div className="flex gap-3"><button disabled={busy} onClick={() => {
                const value = window.prompt('После проверки канала введите ID отправленного сообщения. Отмена ничего не изменит.');
                if (value && /^[1-9][0-9]*$/.test(value)) run(async () => { await api.post(`/api/admin/giveaways/${row.id}/post-resolution`, { message_id: Number(value) }); await load(); });
            }}>Указать ID найденного поста</button><button disabled={busy} onClick={() => {
                if (window.confirm('Вы проверили канал и уверены, что пост НЕ отправлен?')) run(async () => { await api.post(`/api/admin/giveaways/${row.id}/post-resolution`, { not_sent: true }); await load(); });
            }}>Подтвердить отсутствие поста</button></div>}
            {row.post_status === 'failed' && <button disabled={busy} onClick={() => run(() => action(row.id, 'post-retry'))}>Повторить отправку поста</button>}
            <div className="flex flex-wrap gap-3">
                {row.status === 'draft' && <><button disabled={busy} onClick={() => { loadedNFT.current = ''; setDraft({ ...row, start_at: localTime(row.start_at), end_at: localTime(row.end_at) }); }}>Редактировать</button><button disabled={busy} onClick={() => run(() => action(row.id, 'publish'))}>Проверить права и опубликовать</button></>}
                {!['finished', 'cancelled'].includes(row.status) && <button disabled={busy} onClick={() => { if (window.confirm('Отменить розыгрыш и удалить его данные? Пост в канале будет удалён или очищен, если Telegram запрещает удаление.')) run(() => action(row.id, 'cancel')); }}>Отменить</button>}
                <button disabled={busy} onClick={() => run(() => entries(row.id))}>Участники и победитель</button>
                <button disabled={busy} onClick={() => run(() => attempts(row.id))}>История выбора</button>
                {row.winner && row.fulfillment_status !== 'delivered' && <button disabled={busy} onClick={() => { if (window.confirm('Подарок действительно передан победителю?')) run(() => action(row.id, 'fulfilled')); }}>Подтвердить ручную выдачу</button>}
            </div>
        </article>)}
        <div className="flex gap-3"><button disabled={!skip || busy} onClick={() => setSkip(Math.max(0, skip - 30))}>Назад</button><button disabled={rows.length < 30 || busy} onClick={() => setSkip(skip + 30)}>Далее</button></div>
        {participants && <section className={panel}><h2>Участники (только администратору)</h2>{participants.map((p: any) => <p key={p.entry_label}>{p.entry_label} · {p.name} · @{p.username ?? '—'} · Telegram {p.telegram_id} · {p.status} · {p.error_code}</p>)}<div className="flex gap-3"><button disabled={!entrySkip || busy} onClick={() => run(() => entries(selected!, Math.max(0, entrySkip - 50)))}>Назад</button><button disabled={participants.length < 50 || busy} onClick={() => run(() => entries(selected!, entrySkip + 50))}>Далее</button><button onClick={() => setParticipants(null)}>Закрыть</button></div></section>}
        {history && <section className={panel}><h2>История выбора</h2>{!history.rows.length && <p>Выбор ещё не начинался.</p>}{history.rows.map(r => <p key={r.ordinal}>#{r.ordinal} · {r.entry_label} · {r.status} · {new Date(r.selected_at).toLocaleString()}</p>)}<div className="flex gap-3"><button disabled={!history.skip || busy} onClick={() => run(() => attempts(history.id, Math.max(0, history.skip - 50)))}>Назад</button><button disabled={history.rows.length < 50 || busy} onClick={() => run(() => attempts(history.id, history.skip + 50))}>Далее</button><button onClick={() => setHistory(null)}>Закрыть</button></div></section>}
    </div>;
}
