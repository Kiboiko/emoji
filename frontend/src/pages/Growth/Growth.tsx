import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Header } from '@/components/Header/Header';
import { RankingFrame } from '@/components/RankingFrame/RankingFrame';
import { apiClient } from '@/api/client';
import { useAuthStore } from '@/store/authStore';
import { errorText } from '@/store/toastStore';
import './Growth.css';

export function Rankings() {
    const { language } = useAuthStore();
    const t = (ru: string, en: string) => language === 'ru' ? ru : en;
    const [data, setData] = useState<any>(null);
    const [periods, setPeriods] = useState<any[]>([]);
    const [periodSkip, setPeriodSkip] = useState(0);
    const [morePeriods, setMorePeriods] = useState(false);
    const [period, setPeriod] = useState('');
    const [error, setError] = useState('');
    const [busy, setBusy] = useState(false);
    useEffect(() => {
        let live = true; setBusy(true); setError('');
        apiClient.get(period ? `/market-rankings/periods/${period}` : '/market-rankings/current')
            .then(r => { if (live) setData(r.data); })
            .catch(e => { if (live) setError(errorText(e, t('Не удалось загрузить рейтинг', 'Could not load ranking'))); })
            .finally(() => { if (live) setBusy(false); });
        return () => { live = false; };
    }, [period, language]);
    useEffect(() => {
        let live = true;
        apiClient.get('/market-rankings/periods', { params: { skip: periodSkip } })
            .then(r => { if (live) { setPeriods(p => periodSkip ? [...p, ...r.data] : r.data); setMorePeriods(r.data.length === 20); } })
            .catch(e => { if (live) setError(errorText(e, t('Не удалось загрузить архив', 'Could not load archive'))); });
        return () => { live = false; };
    }, [periodSkip]);
    return <div className="growth-page"><Header pageTitle={t('Рейтинг маркетов', 'Market ranking')} /><main className="container growth-stack">
        <Link to="/">{t('В каталог', 'Back to catalog')}</Link>
        <p>{t('Рейтинг по завершённым продажам и отзывам. Неделя начинается в понедельник по Москве.', 'Ranked by completed sales and reviews. Weeks start on Monday, Moscow time.')}</p>
        <label>{t('Период', 'Period')}<select value={period} onChange={e => setPeriod(e.target.value)}><option value="">{t('Текущая неделя', 'Current week')}</option>{periods.map(p => <option key={p.id} value={p.id}>{new Date(p.start_at).toLocaleDateString(language)} — {new Date(p.end_at).toLocaleDateString(language)}</option>)}</select></label>
        {morePeriods && <button onClick={() => { setMorePeriods(false); setPeriodSkip(s => s + 20); }}>{t('Ещё периоды', 'More periods')}</button>}
        {busy && <p role="status">{t('Загрузка…', 'Loading…')}</p>}{error && <p role="alert">{error}</p>}
        {!busy && data && <>{data.period && <small>{t('Обновлено: ', 'Updated: ')}{new Date(data.period.updated_at).toLocaleString(language)}</small>}
            {data.items.length === 0 && <p>{t('Участников рейтинга пока нет.', 'There are no ranking participants yet.')}</p>}
            {data.items.map((s: any) => <Link key={s.id} className="growth-card" to={`/store/seller/${s.id}`}>
                <RankingFrame medal={s.medal} rank={s.rank}>
                    {s.avatar_url ? <img src={s.avatar_url} alt="" loading="lazy" /> : <span aria-hidden="true">{s.name.trim().charAt(0).toUpperCase()}</span>}
                </RankingFrame><span>{s.name}{s.rating != null && <small> · ★ {s.rating}</small>}</span>
                {s.medal && <small>{t({gold:'Золото',silver:'Серебро',bronze:'Бронза'}[s.medal as 'gold'], {gold:'Gold',silver:'Silver',bronze:'Bronze'}[s.medal as 'gold'])}</small>}
            </Link>)}</>}
    </main></div>;
}

export { Giveaways } from './Giveaways';
