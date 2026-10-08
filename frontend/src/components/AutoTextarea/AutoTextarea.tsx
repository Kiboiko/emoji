import React, { useLayoutEffect, useRef } from 'react';

type Props = React.TextareaHTMLAttributes<HTMLTextAreaElement> & {
    /** Выше этого поле не растёт и начинает прокручиваться */
    maxHeight?: number;
};

/**
 * Поле для описаний, которое растёт вместе с текстом.
 *
 * Раньше поля описаний были высокими сразу, на четыре-пять строк: пустой
 * прямоугольник в полэкрана на телефоне, а под ним кнопки уезжали вниз.
 * Теперь поле в две строки и растёт по мере ввода.
 */
export const AutoTextarea: React.FC<Props> = ({ maxHeight = 320, rows = 2, value, ...rest }) => {
    const ref = useRef<HTMLTextAreaElement>(null);

    useLayoutEffect(() => {
        const field = ref.current;
        if (!field) return;
        field.style.height = 'auto';
        // scrollHeight не считает рамку, а высота при box-sizing: border-box — считает
        const border = field.offsetHeight - field.clientHeight;
        const needed = field.scrollHeight + border;
        field.style.height = `${Math.min(needed, maxHeight)}px`;
        field.style.overflowY = needed > maxHeight ? 'auto' : 'hidden';
    }, [value, maxHeight]);

    return <textarea ref={ref} rows={rows} value={value} {...rest} />;
};
