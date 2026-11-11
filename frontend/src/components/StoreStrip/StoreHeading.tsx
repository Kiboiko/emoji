import { useEffect, useId, useRef, useState } from 'react';
import { Info } from 'lucide-react';

export function StoreHeading({ language }: { language: string }) {
    const [open, setOpen] = useState(false);
    const wrapper = useRef<HTMLDivElement>(null);
    const button = useRef<HTMLButtonElement>(null);
    const tooltipId = useId();
    const ru = language === 'ru';

    useEffect(() => {
        if (!open) return;
        const dismiss = (event: PointerEvent) => {
            if (!wrapper.current?.contains(event.target as Node)) setOpen(false);
        };
        const escape = (event: KeyboardEvent) => {
            if (event.key === 'Escape') {
                setOpen(false);
                button.current?.focus();
            }
        };
        document.addEventListener('pointerdown', dismiss, true);
        document.addEventListener('keydown', escape);
        return () => {
            document.removeEventListener('pointerdown', dismiss, true);
            document.removeEventListener('keydown', escape);
        };
    }, [open]);

    return (
        <div className="home-stores-heading" ref={wrapper} onBlur={event => {
            if (!event.currentTarget.contains(event.relatedTarget as Node)) setOpen(false);
        }}>
            <h2 className="home-section">{ru ? 'Магазины' : 'Stores'}</h2>
            <button type="button" className="home-ranking-info" ref={button}
                aria-label={ru ? 'Информация о рейтинге магазинов' : 'Store ranking information'}
                aria-expanded={open} aria-controls={open ? tooltipId : undefined}
                aria-describedby={open ? tooltipId : undefined}
                onClick={() => setOpen(value => !value)}>
                <Info size={20} strokeWidth={1.8} aria-hidden="true" />
            </button>
            {open && (
                <div id={tooltipId} role="tooltip" className="home-ranking-tooltip">
                    {ru
                        ? 'Рейтинг обновляется каждую неделю — в понедельник в 00:00 (МСК).'
                        : 'The ranking updates every week on Monday at 00:00 Moscow time (UTC+3).'}
                </div>
            )}
        </div>
    );
}
