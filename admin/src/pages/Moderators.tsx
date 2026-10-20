import React, { useCallback, useEffect, useState } from 'react';
import { KeyRound, Loader2, LogOut, Pause, Play, Plus, Trash2 } from 'lucide-react';
import { staffApi, type Moderator } from '../api/admin';
import { useToast, errorText } from '../components/ui/Toast';

const fmt = (iso: string | null) =>
    iso ? new Date(iso).toLocaleString('ru', { dateStyle: 'short', timeStyle: 'short' }) : '—';

/**
 * Модераторы: свой логин и пароль у каждого.
 *
 * Модератор видит только проверку товаров и споры по сделкам, и всё, что он
 * сделал, остаётся в «Журнале действий». Страница только для администратора.
 */
export const Moderators: React.FC = () => {
    const toast = useToast();
    const [rows, setRows] = useState<Moderator[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [busy, setBusy] = useState<string | null>(null);

    const [username, setUsername] = useState('');
    const [displayName, setDisplayName] = useState('');
    const [password, setPassword] = useState('');
    const [creating, setCreating] = useState(false);

    const load = useCallback(async () => {
        setLoading(true);
        try {
            setRows(await staffApi.moderators());
            setError(null);
        } catch (e) {
            setError(errorText(e, 'Не удалось загрузить модераторов'));
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => { load(); }, [load]);

    const run = async (id: string, fn: () => Promise<unknown>, done: string) => {
        setBusy(id);
        try {
            await fn();
            toast.success(done);
            await load();
        } catch (e) {
            toast.fromError(e);
        } finally {
            setBusy(null);
        }
    };

    const create = async (e: React.FormEvent) => {
        e.preventDefault();
        setCreating(true);
        try {
            await staffApi.createModerator({
                username: username.trim(),
                password,
                display_name: displayName.trim() || undefined,
            });
            toast.success(`Модератор ${username.trim()} добавлен`);
            setUsername('');
            setDisplayName('');
            setPassword('');
            await load();
        } catch (err) {
            toast.fromError(err);
        } finally {
            setCreating(false);
        }
    };

    const resetPassword = (m: Moderator) => {
        const next = window.prompt(`Новый пароль для ${m.username} (не меньше 10 символов):`);
        if (!next) return;
        return run(m.id, () => staffApi.resetPassword(m.id, next), 'Пароль изменён, сессии завершены');
    };

    const remove = (m: Moderator) => {
        if (!window.confirm(`Убрать модератора ${m.username}? Его действия в журнале останутся.`)) return;
        return run(m.id, () => staffApi.remove(m.id), 'Модератор убран');
    };

    return (
        <div>
            <h1 className="text-2xl md:text-3xl font-bold text-white mb-2">Модераторы</h1>
            <p className="text-sm text-gray-400 mb-6 max-w-2xl">
                Модератор входит в эту же админку со своим логином и паролем, но видит только
                «Модерацию» и «Сделки»: проверка товаров, споры, удаление фото. Все его действия
                сохраняются в журнале.
            </p>

            <form onSubmit={create} className="bg-gray-800 border border-gray-700 rounded-xl p-5 mb-6">
                <h2 className="text-white font-semibold mb-4">Новый модератор</h2>
                <div className="grid gap-4 md:grid-cols-3">
                    <label className="block text-sm text-gray-400">
                        Логин
                        <input
                            value={username}
                            onChange={(e) => setUsername(e.target.value)}
                            placeholder="anna_mod"
                            autoComplete="off"
                            className="mt-1 w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-blue-500"
                        />
                        <span className="text-xs text-gray-600">Латиница, цифры, . _ -, 3–32 символа</span>
                    </label>
                    <label className="block text-sm text-gray-400">
                        Имя (необязательно)
                        <input
                            value={displayName}
                            onChange={(e) => setDisplayName(e.target.value)}
                            placeholder="Анна"
                            className="mt-1 w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-blue-500"
                        />
                    </label>
                    <label className="block text-sm text-gray-400">
                        Пароль
                        <input
                            type="password"
                            value={password}
                            onChange={(e) => setPassword(e.target.value)}
                            autoComplete="new-password"
                            className="mt-1 w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-blue-500"
                        />
                        <span className="text-xs text-gray-600">Не меньше 10 символов</span>
                    </label>
                </div>
                <button
                    type="submit"
                    disabled={creating || !username.trim() || !password}
                    className="mt-4 flex items-center gap-2 px-4 py-2 rounded-lg bg-blue-600 text-white text-sm hover:bg-blue-500 disabled:opacity-50"
                >
                    {creating ? <Loader2 size={15} className="animate-spin" /> : <Plus size={15} />}
                    Добавить
                </button>
            </form>

            {loading && <Loader2 size={22} className="animate-spin text-gray-400" />}
            {error && <div className="text-red-400 text-sm">{error}</div>}
            {!loading && !error && rows.length === 0 && (
                <div className="text-gray-500 py-10 text-center">Модераторов пока нет</div>
            )}

            <div className="space-y-3">
                {rows.map((m) => (
                    <div key={m.id} className="bg-gray-800 border border-gray-700 rounded-xl p-4 flex flex-wrap items-center gap-4 justify-between">
                        <div className="min-w-0">
                            <div className="text-white font-medium flex items-center gap-2">
                                {m.username}
                                {m.display_name !== m.username && (
                                    <span className="text-gray-500 font-normal">· {m.display_name}</span>
                                )}
                                <span className={`text-xs px-2 py-0.5 rounded-full ${
                                    m.active ? 'bg-green-600/20 text-green-400' : 'bg-yellow-600/20 text-yellow-400'
                                }`}>
                                    {m.active ? 'работает' : 'приостановлен'}
                                </span>
                            </div>
                            <div className="text-xs text-gray-500 mt-1">
                                Добавлен {fmt(m.created_at)} · последний вход {fmt(m.last_login)} · действий: {m.actions}
                            </div>
                        </div>

                        <div className="flex gap-2">
                            <button
                                onClick={() => resetPassword(m)}
                                disabled={busy === m.id}
                                className="p-2 rounded-lg bg-gray-700 text-gray-200 hover:bg-gray-600 disabled:opacity-50"
                                title="Задать новый пароль"
                            >
                                <KeyRound size={16} />
                            </button>
                            <button
                                onClick={() => run(m.id, () => staffApi.revokeSessions(m.id), 'Сессии завершены')}
                                disabled={busy === m.id}
                                className="p-2 rounded-lg bg-gray-700 text-gray-200 hover:bg-gray-600 disabled:opacity-50"
                                title="Завершить все его сессии"
                            >
                                <LogOut size={16} />
                            </button>
                            <button
                                onClick={() => run(
                                    m.id, () => staffApi.setActive(m.id, !m.active),
                                    m.active ? 'Модератор приостановлен' : 'Модератор возвращён',
                                )}
                                disabled={busy === m.id}
                                className="p-2 rounded-lg bg-gray-700 text-gray-200 hover:bg-gray-600 disabled:opacity-50"
                                title={m.active ? 'Приостановить' : 'Вернуть'}
                            >
                                {m.active ? <Pause size={16} /> : <Play size={16} />}
                            </button>
                            <button
                                onClick={() => remove(m)}
                                disabled={busy === m.id}
                                className="p-2 rounded-lg bg-red-600/20 text-red-400 hover:bg-red-600/30 disabled:opacity-50"
                                title="Убрать модератора"
                            >
                                <Trash2 size={16} />
                            </button>
                        </div>
                    </div>
                ))}
            </div>
        </div>
    );
};
