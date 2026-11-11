import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { Check, ChevronDown, X } from 'lucide-react';
import type { Category } from '@/types';
import './CategoryFilter.css';

type Props = {
    categories: Category[];
    root: string | null;
    selected: string | null;
    language: string;
    onChange: (root: string | null, category: string | null) => void;
};

export function CategoryFilter({ categories, root, selected, language, onChange }: Props) {
    const [open, setOpen] = useState(false);
    const container = useRef<HTMLDivElement>(null);
    const trigger = useRef<HTMLButtonElement>(null);
    const options = useRef<HTMLDivElement>(null);
    const scroll = useRef<HTMLDivElement>(null);
    const optionsId = useId();
    const t = (ru: string, en: string) => language === 'ru' ? ru : en;
    const roots = categories.filter(category => !category.parent_id);
    const current = roots.find(category => category.id === root);
    const children = categories.filter(category => category.parent_id === root && root !== null);

    useLayoutEffect(() => {
        const rail = scroll.current;
        if (!rail) return;
        if (!root || selected === root) {
            rail.scrollLeft = 0;
            return;
        }
        const active = rail.querySelector<HTMLButtonElement>('[aria-pressed="true"]');
        if (active) {
            // Move only the category rail, without scrolling the page vertically.
            rail.scrollLeft = active.offsetLeft - (rail.clientWidth - active.offsetWidth) / 2;
        }
    }, [root, selected, language, categories]);

    useEffect(() => {
        if (!open) return;
        options.current?.querySelector<HTMLButtonElement>('[aria-pressed="true"]')?.focus();
        const dismiss = (event: Event) => {
            if (!container.current?.contains(event.target as Node)) setOpen(false);
        };
        const escape = (event: KeyboardEvent) => {
            if (event.key === 'Escape') {
                setOpen(false);
                trigger.current?.focus();
            }
        };
        document.addEventListener('pointerdown', dismiss);
        // WebViews can report relatedTarget=null when tapping a menu item.
        // Close after focus actually enters an outside element, not on blur
        // before the item's click has had a chance to select the category.
        document.addEventListener('focusin', dismiss);
        document.addEventListener('keydown', escape);
        return () => {
            document.removeEventListener('pointerdown', dismiss);
            document.removeEventListener('focusin', dismiss);
            document.removeEventListener('keydown', escape);
        };
    }, [open]);

    const chooseRoot = (id: string | null) => {
        onChange(id, id);
        setOpen(false);
        trigger.current?.focus();
    };

    return (
        <div className="category-filter" ref={container}>
            <div className="category-filter-row" role="group" aria-label={t('Категории', 'Categories')}>
                <div className="category-filter-scroll" ref={scroll} key={current?.id ?? 'all'}>
                    {current && (
                        <button type="button" ref={trigger} className="category-chip category-picker-trigger"
                            aria-expanded={open} aria-controls={optionsId}
                            onClick={() => setOpen(value => !value)}>
                            {t('Все категории', 'All categories')}<ChevronDown size={14} aria-hidden="true" />
                        </button>
                    )}
                    {!current ? (
                        <>
                            <button type="button" className="category-chip active" aria-pressed="true"
                                onClick={() => onChange(null, null)}>{t('Все', 'All')}</button>
                            {roots.map(category => (
                                <button type="button" key={category.id} className="category-chip" aria-pressed="false"
                                    onClick={() => onChange(category.id, category.id)}>{category.name}</button>
                            ))}
                        </>
                    ) : (
                        <>
                            <button type="button" className={`category-chip ${selected === root ? 'active' : ''}`}
                                aria-pressed={selected === root}
                                aria-label={t(`Всё в категории: ${current.name}`, `All in category: ${current.name}`)}
                                onClick={() => onChange(root, root)}>
                                {children.length ? t('Все', 'All') : current.name}
                            </button>
                            {children.map(category => (
                                <button type="button" key={category.id}
                                    className={`category-chip ${selected === category.id ? 'active' : ''}`}
                                    aria-pressed={selected === category.id}
                                    onClick={() => onChange(root, category.id)}>{category.name}</button>
                            ))}
                        </>
                    )}
                </div>
                {current && (
                    <button type="button" className="category-filter-reset"
                        aria-label={t('Сбросить категорию и вернуться ко всем категориям', 'Clear category and return to all categories')}
                        onClick={() => chooseRoot(null)}><X size={19} aria-hidden="true" /></button>
                )}
            </div>
            {open && current && (
                <div id={optionsId} className="category-picker" ref={options}
                    role="group" aria-label={t('Выбрать категорию', 'Choose a category')}>
                    <button type="button" aria-pressed={!root} onClick={() => chooseRoot(null)}>
                        <span>{t('Все категории', 'All categories')}</span>
                    </button>
                    {roots.map(category => (
                        <button type="button" key={category.id} aria-pressed={root === category.id}
                            onClick={() => chooseRoot(category.id)}>
                            <span>{category.name}</span>
                            {root === category.id && <Check size={18} aria-hidden="true" />}
                        </button>
                    ))}
                </div>
            )}
        </div>
    );
}
