import { useEffect, useRef, useState } from 'react';
import { useAuthStore } from '@/store/authStore';
import { thumb } from '@/lib/image';
import './ProductImage.css';

/** Start near the viewport and cancel unfinished requests far behind the user. */
export function ProductImage({ url, priority = false }: { url: string; priority?: boolean }) {
    const language = useAuthStore(state => state.language);
    const box = useRef<HTMLSpanElement>(null);
    const [nearby, setNearby] = useState(false);
    const [loaded, setLoaded] = useState(false);
    const [failed, setFailed] = useState(false);
    const [attempt, setAttempt] = useState(0);
    const source = thumb(url);
    // A mounted card can become a top result when the catalog is filtered or sorted.
    const shouldLoad = priority || nearby;

    useEffect(() => {
        if (!box.current || priority || loaded) return;
        if (typeof IntersectionObserver === 'undefined') { setNearby(true); return; }
        const observer = new IntersectionObserver(entries => {
            setNearby(entries.some(entry => entry.isIntersecting));
        }, { rootMargin: '500px 0px' });
        observer.observe(box.current);
        return () => observer.disconnect();
    }, [priority, loaded]);

    useEffect(() => {
        if (!shouldLoad || !failed || attempt >= 2) return;
        const timer = setTimeout(() => {
            setFailed(false);
            setAttempt(current => current + 1);
        }, (attempt + 1) * 700);
        return () => clearTimeout(timer);
    }, [shouldLoad, failed, attempt]);

    const retrySource = attempt && source?.startsWith('/uploads/')
        ? `${source}&image_retry=${attempt}` : source;

    return <span className="product-image-loader" ref={box}>
        {(shouldLoad || loaded) && source && <img key={`${source}-${attempt}`} src={retrySource} alt=""
            width={384} height={384} fetchPriority={priority ? 'high' : 'auto'} decoding="async"
            onLoad={() => { setLoaded(true); setFailed(false); }} onError={() => setFailed(true)} />}
        {!loaded && <span className="product-image-status">
            {(!source || (failed && attempt >= 2))
                ? (language === 'ru' ? 'Фото недоступно' : 'Photo unavailable')
                : (language === 'ru' ? 'Загрузка…' : 'Loading…')}
        </span>}
    </span>;
}
