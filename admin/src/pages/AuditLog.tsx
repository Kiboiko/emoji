import React, { useCallback, useEffect, useState } from 'react';
import { Loader2 } from 'lucide-react';
import { staffApi, type AuditEntry, type Moderator } from '../api/admin';
import { Pagination } from '../components/ui/Pagination';
import { errorText } from '../components/ui/Toast';

const LIMIT = 50;

const ACTIONS: Record<string, string> = {
    'listing.approve': 'Одобрил заявку',
    'listing.reject': 'Отклонил заявку',
    'listing.auto_publish': 'Опубликовано без проверки',
    'deal.message': 'Написал в чат сделки',
    'deal.resolve': 'Решил спор',
    'photo.delete': 'Удалил фото',
    'seller.status': 'Сменил статус продавца',
    'seller.verify': 'Отметил проверенным',
    'seller.unverify': 'Снял галочку проверенного',
    'moderator.create': 'Добавил модератора',
    'moderator.password_reset': 'Сменил пароль модератору',
    'moderator.sessions_reset': 'Завершил сессии модератора',
    'moderator.suspend': 'Приостановил модератора',
    'moderator.activate': 'Вернул модератора',
    'moderator.remove': 'Убрал модератора',
    'auth.password_changed': 'Сменил свой пароль',
    'auth.sessions_reset': 'Вышел со всех устройств',
    'settings.update': 'Изменил настройку',
};

const GROUPS = [
    { value: '', label: 'Все действия' },
    { value: 'listing', label: 'Заявки на товары' },
    { value: 'deal', label: 'Сделки и споры' },
    { value: 'photo', label: 'Удаление фото' },
    { value: 'seller', label: 'Продавцы' },
    { value: 'moderator', label: 'Модераторы' },
    { value: 'auth', label: 'Пароли и сессии' },
    { value: 'settings', label: 'Настройки' },
];

const ROLE_LABEL: Record<string, string> = {
    admin: 'админ', moderator: 'модератор', system: 'система',
};

const ROLE_STYLE: Record<string, string> = {
    admin: 'bg-blue-600/20 text-blue-300',
    moderator: 'bg-violet-600/20 text-violet-300',
    system: 'bg-gray-600/30 text-gray-300',
};

/** Что именно было сделано — коротко, из подробностей записи */
function summary(entry: AuditEntry): string {
    const d = entry.details ?? {};
    const parts: string[] = [];
    if (d.name) parts.push(`«${d.name}»`);
    if (d.store) parts.push(`магазин ${d.store}`);
    else if (d.seller) parts.push(`продавец ${d.seller}`);
    if (d.number) parts.push(`сделка №${d.number}`);
    if (d.username) parts.push(String(d.username));
    if (d.status) parts.push(`→ ${d.status}`);
    if (d.decision) parts.push(String(d.decision));
    if (d.kind === 'store_avatar') parts.push('логотип магазина');
    if (d.kind === 'listing_image') parts.push('фото объявления');
    if (d.value !== undefined) parts.push(`${entry.target_id} = ${String(d.value)}`);
    const note = d.comment ?? d.reason ?? d.text;
    if (note) parts.push(`«${String(note).slice(0, 160)}»`);
    return parts.join(' · ');
}

/**
 * Журнал действий персонала: кто, когда и что сделал.
 *
 * Так владелец проверяет модераторов: каждое решение по заявке, сообщение в
 * споре, удалённое фото и смена пароля остаётся здесь.
 */
export const AuditLog: React.FC = () => {
    const [rows, setRows] = useState<AuditEntry[]>([]);
    const [total, setTotal] = useState(0);
    const [skip, setSkip] = useState(0);
    const [role, setRole] = useState('');
    const [group, setGroup] = useState('');
    const [actor, setActor] = useState('');
    const [moderators, setModerators] = useState<Moderator[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        staffApi.moderators().then(setModerators).catch(() => setModerators([]));
    }, []);

    const load = useCallback(async () => {
        setLoading(true);
        try {
            const page = await staffApi.auditLog({
                role: role || undefined,
                action: group || undefined,
                actor_id: actor || undefined,
                skip, limit: LIMIT,
            });
            setRows(page.items);
            setTotal(page.total);
            setError(null);
        } catch (e) {
            setError(errorText(e, 'Не удалось загрузить журнал'));
        } finally {
            setLoading(false);
        }
    }, [role, group, actor, skip]);

    useEffect(() => { load(); }, [load]);

    const select = 'bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-200 focus:outline-none focus:border-blue-500';

    return (
        <div>
            <h1 className="text-2xl md:text-3xl font-bold text-white mb-6">Журнал действий</h1>

            <div className="flex flex-wrap gap-3 mb-5">
                <select value={role} onChange={(e) => { setRole(e.target.value); setSkip(0); }} className={select}>
                    <option value="">Все роли</option>
                    <option value="admin">Администратор</option>
                    <option value="moderator">Модератор</option>
                    <option value="system">Система</option>
                </select>
                <select value={actor} onChange={(e) => { setActor(e.target.value); setSkip(0); }} className={select}>
                    <option value="">Все модераторы</option>
                    {moderators.map((m) => <option key={m.id} value={m.id}>{m.username}</option>)}
                </select>
                <select value={group} onChange={(e) => { setGroup(e.target.value); setSkip(0); }} className={select}>
                    {GROUPS.map((g) => <option key={g.value} value={g.value}>{g.label}</option>)}
                </select>
            </div>

            {loading && <Loader2 size={22} className="animate-spin text-gray-400" />}
            {error && <div className="text-red-400 text-sm">{error}</div>}
            {!loading && !error && rows.length === 0 && (
                <div className="text-gray-500 py-12 text-center">Записей нет</div>
            )}

            <div className="space-y-2">
                {rows.map((entry) => (
                    <div key={entry.id} className="bg-gray-800 border border-gray-700 rounded-xl px-4 py-3">
                        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                            <span className="text-xs text-gray-500 w-32 shrink-0">
                                {new Date(entry.created_at).toLocaleString('ru', { dateStyle: 'short', timeStyle: 'medium' })}
                            </span>
                            <span className="text-white text-sm font-medium">{entry.actor_name}</span>
                            <span className={`text-xs px-2 py-0.5 rounded-full ${ROLE_STYLE[entry.actor_role] ?? ''}`}>
                                {ROLE_LABEL[entry.actor_role] ?? entry.actor_role}
                            </span>
                            <span className="text-sm text-gray-200">{ACTIONS[entry.action] ?? entry.action}</span>
                        </div>
                        {summary(entry) && (
                            <div className="text-sm text-gray-400 mt-1 sm:pl-[8.75rem] break-words">
                                {summary(entry)}
                            </div>
                        )}
                    </div>
                ))}
            </div>

            <Pagination total={total} skip={skip} limit={LIMIT} onChange={setSkip} />
        </div>
    );
};
