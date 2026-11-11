import { useEffect, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { useAuthStore } from '@/store/authStore';
import { advanceStartupIntro, failStartup, finishStartupData, markStartup, useStartupStore } from '@/store/startupStore';
import './StartupScreen.css';

export function StartupRouteReady() {
    const { pathname } = useLocation();
    useEffect(() => {
        if (pathname.startsWith('/product/')) {
            markStartup('categories'); markStartup('stores');
        } else if (pathname !== '/') finishStartupData();
    }, [pathname]);
    return null;
}

export function StartupScreen() {
    const { active, progress, error, retry, dismiss, completed } = useStartupStore();
    const language = useAuthStore(state => state.language);
    const [staticLogo, setStaticLogo] = useState(() => window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false);
    const ru = language === 'ru';
    useEffect(() => {
        const preference = window.matchMedia?.('(prefers-reduced-motion: reduce)');
        const change = () => setStaticLogo(preference?.matches ?? false);
        preference?.addEventListener('change', change);
        return () => preference?.removeEventListener('change', change);
    }, []);
    useEffect(() => {
        if (staticLogo) markStartup('intro');
    }, [staticLogo]);
    useEffect(() => {
        if (!active || completed.intro) return;
        // A blocked/stalled player must not prevent opening the application.
        const timer = setTimeout(() => setStaticLogo(true), 8000);
        return () => clearTimeout(timer);
    }, [active, completed.intro]);
    useEffect(() => {
        if (!active || progress !== 100 || error) return;
        const timer = setTimeout(dismiss, 220);
        return () => clearTimeout(timer);
    }, [active, progress, error, dismiss]);
    useEffect(() => {
        if (!active || error) return;
        const timer = setTimeout(() => {
            if (useStartupStore.getState().progress < 100) failStartup(ru ? 'Загрузка заняла больше времени. Попробуйте ещё раз.' : 'Loading is taking longer. Please try again.', () => window.location.reload());
        }, 45000);
        return () => clearTimeout(timer);
    }, [active, error, ru]);
    if (!active) return null;

    return <div className={`startup-screen${progress === 100 && !error ? ' startup-complete' : ''}`} aria-busy={!error}>
        <div className="startup-content">
            <div className="startup-logo">
                {staticLogo ? <img src="/launch/safedeal-v3.webp" alt="SafeDeal" />
                    : <video autoPlay muted playsInline preload="auto" poster="/launch/safedeal-v3.webp" aria-label="SafeDeal"
                        onLoadedMetadata={event => {
                            const video = event.currentTarget;
                            const offset = useStartupStore.getState().introOffset;
                            if (offset > 0 && offset < video.duration) video.currentTime = offset;
                        }}
                        onTimeUpdate={event => {
                            const video = event.currentTarget;
                            if (video.duration > 0) advanceStartupIntro(video.currentTime / video.duration * 100);
                        }}
                        onCanPlay={event => { void event.currentTarget.play().catch(() => setStaticLogo(true)); }}
                        onEnded={event => {
                            markStartup('intro');
                            const state = useStartupStore.getState();
                            if (state.active && state.progress < 100) void event.currentTarget.play().catch(() => setStaticLogo(true));
                        }}
                        onError={() => setStaticLogo(true)}>
                        <source src="/launch/safedeal-v3.mp4" type="video/mp4" />
                    </video>}
            </div>
            <div className="startup-progress" role="progressbar" aria-label={ru ? 'Загрузка приложения' : 'Loading app'} aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress}>
                <div className="startup-track"><span style={{ width: `${progress}%` }} /></div>
            </div>
            {error && <div className="startup-error" role="alert"><p>{error}</p><button type="button" onClick={retry}>{ru ? 'Повторить загрузку' : 'Try again'}</button></div>}
        </div>
    </div>;
}
