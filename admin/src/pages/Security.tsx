import React, { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { CheckCircle2, Loader2, LogOut, XCircle } from 'lucide-react';
import { securityApi, staffApi, type LoginLogEntry } from '../api/admin';
import { useAuth } from '../context/AuthContext';
import { Pagination } from '../components/ui/Pagination';
import { useToast, errorText } from '../components/ui/Toast';

const LIMIT = 30;

const REASONS: Record<string, string> = {
    ok: 'вход выполнен',
    bad_password: 'неверный пароль',
    unknown_user: 'такого логина нет',
    blocked: 'учётка отключена',
    rate_limited: 'слишком много попыток',
};

/**
 * Безопасность: смена пароля, выход со всех устройств, журнал входов.
 *
 * Смена пароля и «выйти везде» завершают ВСЕ сессии, включая эту: токены
 * живут неделю, и без этого украденный оставался бы рабочим. После них нужно
 * войти заново.
 */
export const Security: React.FC = () => {
    const toast = useToast();
    const navigate = useNavigate();
    const { role, logout } = useAuth();

    const [current, setCurrent] = useState('');
    const [next, setNext] = useState('');
    const [repeat, setRepeat] = useState('');
    const [saving, setSaving] = useState(false);

    const leave = async (message: string) => {
        toast.success(message);
        // Сессия на сервере уже завершена — здесь только чистим состояние
        await logout();
        navigate('/login');
    };

    const changePassword = async (e: React.FormEvent) => {
        e.preventDefault();
        if (next !== repeat) {
            toast.error('Новый пароль и повтор не совпадают');
            return;
        }
        setSaving(true);
        try {
            await securityApi.changePassword(current, next);
            await leave('Пароль изменён. Войдите заново с новым паролем.');
        } catch (err) {
            toast.fromError(err);
        } finally {
            setSaving(false);
        }
    };

    const logoutAll = async () => {
        if (!window.confirm('Завершить все сессии, включая эту? Придётся войти заново.')) return;
        try {
            await securityApi.logoutAll();
            await leave('Все сессии завершены.');
        } catch (err) {
            toast.fromError(err);
        }
    };

    const input = 'mt-1 w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-blue-500';

    return (
        <div>
            <h1 className="text-2xl md:text-3xl font-bold text-white mb-6">Безопасность</h1>

            <div className="grid gap-6 lg:grid-cols-2 mb-8">
                <form onSubmit={changePassword} className="bg-gray-800 border border-gray-700 rounded-xl p-5">
                    <h2 className="text-white font-semibold mb-4">Сменить пароль</h2>
                    <div className="space-y-4">
                        <label className="block text-sm text-gray-400">
                            Текущий пароль
                            <input type="password" value={current} onChange={(e) => setCurrent(e.target.value)}
                                autoComplete="current-password" className={input} />
                        </label>
                        <label className="block text-sm text-gray-400">
                            Новый пароль
                            <input type="password" value={next} onChange={(e) => setNext(e.target.value)}
                                autoComplete="new-password" className={input} />
                            <span className="text-xs text-gray-600">Не меньше 10 символов, не короче и не проще логина</span>
                        </label>
                        <label className="block text-sm text-gray-400">
                            Повторите новый пароль
                            <input type="password" value={repeat} onChange={(e) => setRepeat(e.target.value)}
                                autoComplete="new-password" className={input} />
                        </label>
                    </div>
                    <button
                        type="submit"
                        disabled={saving || !current || !next || !repeat}
                        className="mt-5 flex items-center gap-2 px-4 py-2 rounded-lg bg-blue-600 text-white text-sm hover:bg-blue-500 disabled:opacity-50"
                    >
                        {saving && <Loader2 size={15} className="animate-spin" />}
                        Сменить пароль
                    </button>
                    <p className="text-xs text-gray-500 mt-3">
                        После смены все сессии этой учётки завершатся — войдите заново.
                    </p>
                </form>

                <div className="bg-gray-800 border border-gray-700 rounded-xl p-5">
                    <h2 className="text-white font-semibold mb-2">Выйти везде</h2>
                    <p className="text-sm text-gray-400 mb-4">
                        Сбрасывает все токены этой учётки: админка закроется на всех
                        устройствах, включая это. Нужно, если токен мог утечь или вы
                        открывали админку на чужом устройстве.
                    </p>
                    <button
                        onClick={logoutAll}
                        className="flex items-center gap-2 px-4 py-2 rounded-lg bg-red-600/20 text-red-400 text-sm hover:bg-red-600/30"
                    >
                        <LogOut size={15} /> Завершить все сессии
                    </button>
                </div>
            </div>

            {role === 'admin' && <LoginLog />}
        </div>
    );
};

/* ------------------------------------------------------------------ */

const LoginLog: React.FC = () => {
    const [rows, setRows] = useState<LoginLogEntry[]>([]);
    const [total, setTotal] = useState(0);
    const [skip, setSkip] = useState(0);
    const [onlyFailed, setOnlyFailed] = useState(false);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    const load = useCallback(async () => {
        setLoading(true);
        try {
            const page = await staffApi.loginLog({
                success: onlyFailed ? false : undefined, skip, limit: LIMIT,
            });
            setRows(page.items);
            setTotal(page.total);
            setError(null);
        } catch (e) {
            setError(errorText(e, 'Не удалось загрузить журнал входов'));
        } finally {
            setLoading(false);
        }
    }, [onlyFailed, skip]);

    useEffect(() => { load(); }, [load]);

    return (
        <div>
            <div className="flex items-center justify-between mb-4 flex-wrap gap-3">
                <h2 className="text-xl font-semibold text-white">Журнал входов</h2>
                <label className="flex items-center gap-2 text-sm text-gray-400 cursor-pointer">
                    <input
                        type="checkbox"
                        checked={onlyFailed}
                        onChange={(e) => { setOnlyFailed(e.target.checked); setSkip(0); }}
                    />
                    только неудачные
                </label>
            </div>

            {loading && <Loader2 size={22} className="animate-spin text-gray-400" />}
            {error && <div className="text-red-400 text-sm">{error}</div>}
            {!loading && !error && rows.length === 0 && (
                <div className="text-gray-500 py-8 text-center">Записей нет</div>
            )}

            <div className="space-y-2">
                {rows.map((row) => (
                    <div key={row.id} className="bg-gray-800 border border-gray-700 rounded-xl px-4 py-3 flex flex-wrap items-center gap-x-4 gap-y-1">
                        {row.success
                            ? <CheckCircle2 size={16} className="text-green-400 shrink-0" />
                            : <XCircle size={16} className="text-red-400 shrink-0" />}
                        <span className="text-xs text-gray-500 w-32 shrink-0">
                            {new Date(row.created_at).toLocaleString('ru', { dateStyle: 'short', timeStyle: 'medium' })}
                        </span>
                        <span className="text-white text-sm font-medium">{row.username || '—'}</span>
                        <span className={`text-sm ${row.success ? 'text-gray-300' : 'text-red-300'}`}>
                            {REASONS[row.reason] ?? row.reason}
                        </span>
                        <span className="text-xs text-gray-500">{row.ip ?? 'IP неизвестен'}</span>
                        {row.user_agent && (
                            <span className="text-xs text-gray-600 truncate max-w-full sm:max-w-md" title={row.user_agent}>
                                {row.user_agent}
                            </span>
                        )}
                    </div>
                ))}
            </div>

            <Pagination total={total} skip={skip} limit={LIMIT} onChange={setSkip} />
        </div>
    );
};
