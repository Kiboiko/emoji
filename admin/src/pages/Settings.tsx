import React, { useEffect, useState } from 'react';
import { Save, RotateCcw, Loader2 } from 'lucide-react';
import { settingsApi, type SettingDef } from '../api/admin';
import { useToast, errorText } from '../components/ui/Toast';

/**
 * Группы настроек.
 *
 * Ключи перечислены явно, а не выводятся по префиксу: настройка может
 * называться как угодно, а список на экране должен оставаться осмысленным.
 * Ключи, не попавшие ни в одну группу, показываются в «Прочем» — так новая
 * настройка не пропадёт с экрана, если забыть добавить её сюда.
 */
const GROUPS: Array<{ title: string; keys: string[] }> = [
    {
        title: 'Комиссии',
        keys: ['commission_p2p_bp', 'commission_subscription_bp'],
    },
    {
        title: 'Реферальная программа',
        keys: ['referral_l1_bp', 'referral_l2_bp', 'referral_applies_to'],
    },
    {
        title: 'Оплата',
        keys: [
            'ton_rate_source', 'ton_rate_fixed_usd', 'ton_rate_ttl_sec',
            'order_payment_ttl_min',
        ],
    },
    {
        title: 'Выплаты',
        keys: ['payout_min_ton_nano'],
    },
    {
        title: 'Маркетплейс',
        keys: [
            'p2p_max_pending_listings', 'p2p_reject_block_threshold',
            'p2p_confirm_deadline_days', 'chat_retention_days',
        ],
    },
    {
        title: 'Условия площадки',
        keys: ['terms_version', 'terms_text'],
    },
    {
        title: 'Поддержка',
        keys: ['support_contact'],
    },
];

/**
 * Человеческие названия. Ключ остаётся мелкой подписью — по нему настройку
 * ищут в документации и логах.
 */
const TITLES: Record<string, string> = {
    commission_p2p_bp: 'Комиссия с продажи товара',
    commission_subscription_bp: 'Комиссия с подписки',
    referral_l1_bp: 'Реферальные, первый уровень',
    referral_l2_bp: 'Реферальные, второй уровень',
    referral_applies_to: 'С каких покупок начислять реферальные',
    payout_min_ton_nano: 'Минимальная сумма вывода',
    chat_retention_days: 'Сколько дней хранить переписку после сделки',
    p2p_confirm_deadline_days: 'Автоподтверждение получения, дней',
    p2p_max_pending_listings: 'Заявок на модерации у продавца, не больше',
    p2p_reject_block_threshold: 'Отказов подряд до ограничения продавца',
    order_payment_ttl_min: 'Сколько минут ждать оплату заказа',
    support_contact: 'Контакт поддержки',
    terms_version: 'Версия условий площадки',
    terms_text: 'Текст условий площадки',
};

/**
 * Единицы, в которых настройку удобно вводить. В базе проценты хранятся в
 * базисных пунктах (300 = 3%), суммы — в нанотонах (1 TON = 1 000 000 000):
 * так считать точно. Но вводить «1000000000», имея в виду 1 TON, — верный
 * способ ошибиться на порядок, поэтому экран переводит туда и обратно.
 */
type Unit = { label: string; factor: number; step: string };

const unitOf = (def: SettingDef): Unit | null => {
    if (def.type !== 'int') return null;
    if (def.key.endsWith('_bp')) return { label: '%', factor: 100, step: '0.01' };
    if (def.key.endsWith('_nano')) return { label: 'TON', factor: 1e9, step: '0.000000001' };
    return null;
};

const toDisplay = (def: SettingDef, raw: number | null | undefined) => {
    const unit = unitOf(def);
    if (raw === null || raw === undefined) return '—';
    return unit ? String(Number(raw) / unit.factor) : String(raw);
};

export const Settings: React.FC = () => {
    const toast = useToast();
    const [defs, setDefs] = useState<SettingDef[]>([]);
    const [drafts, setDrafts] = useState<Record<string, string>>({});
    const [saving, setSaving] = useState<string | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    const load = async () => {
        setLoading(true);
        try {
            const data = await settingsApi.list();
            setDefs(data);
            setDrafts(Object.fromEntries(data.map((d) => [d.key, serialize(d)])));
            setError(null);
        } catch (e) {
            setError(errorText(e, 'Не удалось загрузить настройки'));
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => { load(); }, []);

    const save = async (def: SettingDef) => {
        setSaving(def.key);
        try {
            const value = parse(def, drafts[def.key]);
            const result = await settingsApi.update(def.key, value);
            setDefs((current) =>
                current.map((d) => (d.key === def.key ? { ...d, value: result.value } : d)),
            );
            toast.success(`${def.key} сохранена`);
        } catch (e) {
            toast.fromError(e);
        } finally {
            setSaving(null);
        }
    };

    if (loading) {
        return (
            <div className="text-gray-400">
                <Loader2 size={22} className="animate-spin" />
            </div>
        );
    }
    if (error) return <div className="p-8 text-red-400">{error}</div>;

    const grouped = new Set(GROUPS.flatMap((g) => g.keys));
    const sections = [
        ...GROUPS.map((g) => ({
            title: g.title,
            items: g.keys.map((k) => defs.find((d) => d.key === k)).filter(Boolean) as SettingDef[],
        })),
        { title: 'Прочее', items: defs.filter((d) => !grouped.has(d.key)) },
    ].filter((s) => s.items.length > 0);

    return (
        <div className="max-w-4xl">
            <h1 className="text-2xl md:text-3xl font-bold text-white mb-2">Настройки</h1>
            <p className="text-gray-400 text-sm mb-6">
                Применяются сразу, перезапуск не нужен.
            </p>

            <div className="space-y-6">
                {sections.map((section) => (
                    <div key={section.title} className="bg-gray-800 rounded-xl border border-gray-700 p-5">
                        <h2 className="text-lg font-semibold text-white mb-4">{section.title}</h2>

                        <div className="space-y-5">
                            {section.items.map((def) => {
                                const draft = drafts[def.key] ?? '';
                                const changed = draft !== serialize(def);
                                const unit = unitOf(def);

                                return (
                                    <div key={def.key}>
                                        <label className="block text-sm font-medium text-gray-300 mb-1">
                                            {TITLES[def.key] ?? def.key}
                                            {unit && <span className="text-gray-500 font-normal">, {unit.label}</span>}
                                        </label>
                                        <p className="text-xs text-gray-500 mb-2">
                                            {def.description}
                                            {TITLES[def.key] && <span className="text-gray-600"> · {def.key}</span>}
                                        </p>

                                        <div className="flex gap-2">
                                            {def.type === 'bool' ? (
                                                <select
                                                    value={draft}
                                                    onChange={(e) => setDrafts({ ...drafts, [def.key]: e.target.value })}
                                                    className="flex-1 px-3 py-2 rounded-lg bg-gray-900 border border-gray-700 text-white text-sm focus:outline-none focus:border-blue-500"
                                                >
                                                    <option value="true">включено</option>
                                                    <option value="false">выключено</option>
                                                </select>
                                            ) : def.key === 'terms_text' ? (
                                                <textarea
                                                    value={draft}
                                                    onChange={(e) => setDrafts({ ...drafts, [def.key]: e.target.value })}
                                                    rows={10}
                                                    className="flex-1 px-3 py-2 rounded-lg bg-gray-900 border border-gray-700 text-white text-sm font-mono focus:outline-none focus:border-blue-500"
                                                />
                                            ) : (
                                                <input
                                                    type={def.type === 'int' ? 'number' : 'text'}
                                                    value={draft}
                                                    step={unit?.step}
                                                    min={def.min !== null ? toDisplay(def, def.min) : undefined}
                                                    max={def.max !== null ? toDisplay(def, def.max) : undefined}
                                                    onChange={(e) => setDrafts({ ...drafts, [def.key]: e.target.value })}
                                                    className="flex-1 px-3 py-2 rounded-lg bg-gray-900 border border-gray-700 text-white text-sm focus:outline-none focus:border-blue-500"
                                                />
                                            )}

                                            <button
                                                onClick={() => save(def)}
                                                disabled={!changed || saving === def.key}
                                                className="px-3 py-2 rounded-lg bg-blue-600 text-white text-sm disabled:opacity-40 hover:bg-blue-500 self-start"
                                                title="Сохранить"
                                            >
                                                {saving === def.key
                                                    ? <Loader2 size={16} className="animate-spin" />
                                                    : <Save size={16} />}
                                            </button>

                                            {changed && (
                                                <button
                                                    onClick={() => setDrafts({ ...drafts, [def.key]: serialize(def) })}
                                                    className="px-3 py-2 rounded-lg bg-gray-700 text-gray-300 text-sm hover:bg-gray-600 self-start"
                                                    title="Вернуть"
                                                >
                                                    <RotateCcw size={16} />
                                                </button>
                                            )}
                                        </div>

                                        {def.type === 'list' && (
                                            <p className="text-xs text-gray-600 mt-1">
                                                Через запятую. Сейчас: {serialize(def) || '—'}
                                            </p>
                                        )}
                                        {def.type === 'int' && (def.min !== null || def.max !== null) && (
                                            <p className="text-xs text-gray-600 mt-1">
                                                Допустимо: {toDisplay(def, def.min)}…{toDisplay(def, def.max)}
                                                {unit ? ` ${unit.label}` : ''}
                                            </p>
                                        )}
                                    </div>
                                );
                            })}
                        </div>
                    </div>
                ))}
            </div>
        </div>
    );
};

function serialize(def: SettingDef): string {
    if (Array.isArray(def.value)) return def.value.join(', ');
    const unit = unitOf(def);
    if (unit && def.value !== null && def.value !== undefined) {
        return String(Number(def.value) / unit.factor);
    }
    return String(def.value ?? '');
}

/** Приводит введённое к типу настройки. Границы всё равно проверит бэкенд. */
function parse(def: SettingDef, raw: string): unknown {
    const unit = unitOf(def);
    // Округление обязательно: 0.07 * 100 в плавающей точке — 7.000000000000001
    if (unit) return Math.round(Number(raw.replace(',', '.')) * unit.factor);
    if (def.type === 'int') return Number(raw);
    if (def.type === 'bool') return raw === 'true';
    if (def.type === 'list') {
        return raw.split(',').map((s) => s.trim()).filter(Boolean);
    }
    return raw;
}
