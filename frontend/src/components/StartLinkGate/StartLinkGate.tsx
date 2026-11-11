import React, { useEffect, useRef } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { giveawayStartId, productStartId } from '@/lib/productLink';

/** Resolve a Telegram launch link before mounting the catalog underneath it. */
export const StartLinkGate: React.FC<{
    startParam?: string | null;
    children: React.ReactNode;
}> = ({ startParam, children }) => {
    const navigate = useNavigate();
    const location = useLocation();
    const handled = useRef<string | null>(null);
    const gift = giveawayStartId(startParam);
    const product = productStartId(startParam);
    const target = gift ? `/giveaways/${gift}` : product ? `/product/${product}` : null;
    const pending = target !== null && handled.current !== target && location.pathname !== target;

    useEffect(() => {
        if (target && handled.current !== target) {
            handled.current = target;
            if (location.pathname !== target) navigate(target, { replace: true });
        }
    }, [target, location.pathname, navigate]);

    return pending ? <div className="boot-screen"><div className="skeleton boot-placeholder" /></div> : children;
};
