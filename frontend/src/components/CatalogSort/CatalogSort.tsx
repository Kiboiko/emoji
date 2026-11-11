import { useEffect, useId, useRef, useState } from 'react';
import { Check, SlidersHorizontal } from 'lucide-react';
import './CatalogSort.css';

export type CatalogSort = 'default' | 'price_asc' | 'price_desc' | 'rating' | 'sales';

export function CatalogSortMenu({ value, onChange, language }: {
    value: CatalogSort; onChange: (sort: CatalogSort) => void; language: string;
}) {
    const [open, setOpen] = useState(false);
    const wrapper = useRef<HTMLDivElement>(null);
    const trigger = useRef<HTMLButtonElement>(null);
    const options = useRef<HTMLDivElement>(null);
    const id = useId();
    const ru = language === 'ru';
    const choices: { value: CatalogSort; label: string }[] = [
        { value: 'default', label: ru ? 'По умолчанию' : 'Default' },
        { value: 'price_asc', label: ru ? 'Сначала дешевле' : 'Price: low to high' },
        { value: 'price_desc', label: ru ? 'Сначала дороже' : 'Price: high to low' },
        { value: 'rating', label: ru ? 'По рейтингу' : 'Rating' },
        { value: 'sales', label: ru ? 'По продажам' : 'Sales' },
    ];

    useEffect(() => {
        if (!open) return;
        options.current?.querySelector<HTMLButtonElement>('[aria-pressed="true"]')?.focus();
        const outside = (event: Event) => {
            if (!wrapper.current?.contains(event.target as Node)) setOpen(false);
        };
        const escape = (event: KeyboardEvent) => {
            if (event.key === 'Escape') {
                setOpen(false);
                trigger.current?.focus();
            }
        };
        document.addEventListener('pointerdown', outside, true);
        document.addEventListener('focusin', outside);
        document.addEventListener('keydown', escape);
        return () => {
            document.removeEventListener('pointerdown', outside, true);
            document.removeEventListener('focusin', outside);
            document.removeEventListener('keydown', escape);
        };
    }, [open]);

    return (
        <div className="catalog-sort-menu" ref={wrapper}>
            <button type="button" className={`catalog-sort-trigger ${value !== 'default' ? 'active' : ''}`}
                ref={trigger} aria-label={`${ru ? 'Сортировка' : 'Sort by'}: ${choices.find(choice => choice.value === value)?.label}`}
                aria-expanded={open} aria-controls={open ? id : undefined}
                onClick={() => setOpen(current => !current)}>
                <SlidersHorizontal size={20} strokeWidth={1.8} aria-hidden="true" />
            </button>
            {open && (
                <div id={id} className="catalog-sort-options" ref={options} role="group"
                    aria-label={ru ? 'Сортировка товаров' : 'Product sorting'}>
                    {choices.map(choice => (
                        <button type="button" key={choice.value} aria-pressed={value === choice.value}
                            onClick={() => {
                                onChange(choice.value);
                                setOpen(false);
                                trigger.current?.focus();
                            }}>
                            <span>{choice.label}</span>
                            {value === choice.value && <Check size={18} aria-hidden="true" />}
                        </button>
                    ))}
                </div>
            )}
        </div>
    );
}
