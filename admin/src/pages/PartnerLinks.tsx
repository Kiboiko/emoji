import { useEffect, useState } from 'react';
import api from '../api/axios';
import { errorText } from '../components/ui/Toast';

type PartnerLink = { id: string; name: string; enabled: boolean; recipient: string; username: string | null;
    telegram_id: string; invited: number; accrued_gram: string; url: string | null };
const field = 'w-full rounded-lg bg-gray-900 text-white border border-gray-600 p-3';

export function PartnerLinks() {
    const [rows, setRows] = useState<PartnerLink[]>([]);
    const [skip, setSkip] = useState(0);
    const [name, setName] = useState('');
    const [telegramId, setTelegramId] = useState('');
    const [error, setError] = useState('');
    const [busy, setBusy] = useState(false);
    const load = async () => setRows((await api.get('/api/admin/partner-links', { params: { skip } })).data);
    async function run(task: () => Promise<void>) {
        setBusy(true); setError('');
        try { await task(); } catch (e) { setError(errorText(e, 'Не удалось выполнить действие')); }
        finally { setBusy(false); }
    }
    useEffect(() => { void run(load); }, [skip]);
    return <section className="space-y-4">
        <p className="text-gray-300">Ссылка закрепляет новых приглашённых за получателем. Ему поступает вся фактически удержанная комиссия P2P и подписок; доля продавца не меняется. Начисление за P2P — после завершения сделки. Для собственных товаров площадки действует обычная ставка первого уровня, без второго уровня.</p>
        <p className="text-gray-400">Отключение останавливает новые регистрации по ссылке. Существующие привязки и начисления сохраняются. Получатель должен сначала открыть приложение. Получатель уже созданной ссылки не меняется.</p>
        {error && <p role="alert" className="text-red-400">{error}</p>}
        <form className="rounded-xl bg-gray-800 p-4 space-y-3" onSubmit={event => {
            event.preventDefault(); void run(async () => {
                await api.post('/api/admin/partner-links', { name: name.trim(), telegram_id: telegramId.trim() });
                setName(''); setTelegramId(''); await load();
            });
        }}><fieldset disabled={busy} className="space-y-3 min-w-0">
            <label className="block">Название ссылки<input className={field} value={name} onChange={e => setName(e.target.value)} maxLength={100} required /></label>
            <label className="block">Telegram ID получателя<input className={field} value={telegramId} onChange={e => setTelegramId(e.target.value)} pattern="[1-9][0-9]*" inputMode="numeric" required /></label>
            <button className="rounded-lg px-4 py-3 bg-blue-600 text-white" disabled={busy}>Создать специальную ссылку</button>
        </fieldset></form>
        {rows.map(row => <article className="rounded-xl bg-gray-800 p-4 space-y-2" key={row.id}>
            <h2 className="text-lg font-semibold text-white">{row.name} · {row.enabled ? 'Активна' : 'Выключена'}</h2>
            <p className="text-gray-300">Получатель: {row.recipient}{row.username ? ` (@${row.username})` : ''} · Telegram {row.telegram_id}</p>
            <p className="text-gray-400">Приглашено: {row.invited} · Начислено: {row.accrued_gram} Gram</p>
            {row.url ? <label className="block text-gray-300">Реферальная ссылка<input className={field} readOnly value={row.url} onFocus={e => e.currentTarget.select()} /></label> : <p role="status">Имя бота не настроено. Укажите VITE_BOT_USERNAME перед использованием ссылки.</p>}
            <button type="button" disabled={busy} className="text-blue-400" onClick={() => void run(async () => { await api.patch(`/api/admin/partner-links/${row.id}`, { enabled: !row.enabled }); await load(); })}>{row.enabled ? 'Выключить новые приглашения' : 'Включить новые приглашения'}</button>
        </article>)}
        <div className="flex gap-3"><button disabled={!skip || busy} onClick={() => setSkip(Math.max(0, skip - 30))}>Назад</button><button disabled={rows.length < 30 || busy} onClick={() => setSkip(skip + 30)}>Далее</button></div>
    </section>;
}
