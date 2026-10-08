import { useCallback, useRef, useState, type CSSProperties } from 'react';

/**
 * Настоящая высота нижней панели действий — для запаса под ней.
 *
 * Высота плавает: в панели бывает лишняя строка ссылок, плюс отступ под
 * системные кнопки телефона. Число на глаз то не дотягивало, и последний
 * блок страницы оставался под панелью, то давало лишнюю пустоту.
 *
 * Возвращает ref для панели и стиль для корня страницы: в нём переменная
 * --dpage-bar, которую читает .dpage-body.with-bar.
 */
export function useBarHeight(): [(node: HTMLElement | null) => void, CSSProperties | undefined] {
    const [height, setHeight] = useState<number | null>(null);
    const observer = useRef<ResizeObserver | null>(null);

    const ref = useCallback((node: HTMLElement | null) => {
        observer.current?.disconnect();
        observer.current = null;
        if (!node) return;
        const next = new ResizeObserver(() => setHeight(node.offsetHeight));
        next.observe(node);
        observer.current = next;
    }, []);

    const style = height ? ({ '--dpage-bar': `${height}px` } as CSSProperties) : undefined;
    return [ref, style];
}
