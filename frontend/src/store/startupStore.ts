import { create } from 'zustand';

const weights = { app: 10, telegram: 10, auth: 20, categories: 10, stores: 10, products: 30, images: 10 };
export type StartupTask = keyof typeof weights | 'intro';
const dataProgress = (completed: Partial<Record<StartupTask, boolean>>) =>
    (Object.keys(weights) as (keyof typeof weights)[]).reduce((sum, key) => sum + (completed[key] ? weights[key] : 0), 0);

interface StartupState {
    active: boolean;
    progress: number;
    dataProgress: number;
    introProgress: number;
    completed: Partial<Record<StartupTask, boolean>>;
    error: string | null;
    retryAction: (() => void) | null;
    introOffset: number;
    mark: (task: StartupTask) => void;
    advanceIntro: (percent: number) => void;
    fail: (message: string, retry: () => void) => void;
    retry: () => void;
    dismiss: () => void;
}

export const useStartupStore = create<StartupState>((set, get) => ({
    active: true, progress: 0, dataProgress: 0, introProgress: 0, completed: {}, error: null, retryAction: null, introOffset: 0,
    mark: task => set(state => {
        if (!state.active || state.completed[task]) return state;
        const completed = { ...state.completed, [task]: true };
        const data = dataProgress(completed);
        const intro = task === 'intro' ? 100 : state.introProgress;
        return { completed, dataProgress: data, introProgress: intro, progress: Math.min(data, intro) };
    }),
    advanceIntro: percent => set(state => {
        if (!state.active || state.completed.intro || !Number.isFinite(percent)) return state;
        const introProgress = Math.max(state.introProgress, Math.min(99, Math.max(0, Math.floor(percent))));
        return { introProgress, progress: Math.min(state.dataProgress, introProgress) };
    }),
    fail: (error, retryAction) => set(state => state.active ? { error, retryAction } : state),
    retry: () => {
        const action = get().retryAction;
        set({ error: null, retryAction: null });
        action?.();
    },
    dismiss: () => set(state => state.progress === 100 && !state.error ? { active: false } : state),
}));

export const markStartup = (task: StartupTask) => useStartupStore.getState().mark(task);
export const advanceStartupIntro = (percent: number) => useStartupStore.getState().advanceIntro(percent);
/** Preserve the part already played by the HTML splash before React mounted. */
export function captureStartupIntro(video: Pick<HTMLVideoElement, 'currentTime' | 'ended'> | null, telegramLaunch = false) {
    // Telegram can cover the HTML splash with its native loading screen until
    // ready() runs. Its user must see a fresh full cycle when React appears.
    if (!video || telegramLaunch) return;
    useStartupStore.setState({ introOffset: Number.isFinite(video.currentTime) ? Math.max(0, video.currentTime) : 0 });
    if (video.ended) markStartup('intro');
}
export const failStartup = (message: string, retry: () => void) => useStartupStore.getState().fail(message, retry);
export const finishStartupData = () => {
    for (const task of ['categories', 'stores', 'products', 'images'] as const) markStartup(task);
};

/** Reuse the browser's normal image cache; only the first visible photos block launch. */
export async function readyStartupImages(urls: (string | null | undefined)[]) {
    if (!useStartupStore.getState().active) return;
    await Promise.all([...new Set(urls.filter((url): url is string => !!url))].slice(0, 2).map(url => new Promise<void>(resolve => {
        const image = new Image();
        const done = () => { clearTimeout(timer); image.onload = image.onerror = null; resolve(); };
        const timer = setTimeout(done, 8000);
        image.onload = image.onerror = done;
        image.src = url;
        if (image.complete) done();
    })));
    markStartup('images');
}
