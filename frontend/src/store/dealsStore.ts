import { create } from 'zustand';
import { p2pApi } from '@/api/client';
import { realtime } from '@/lib/realtime';
import type { Deal, DealMessage } from '@/types';

/**
 * Сделки и непрочитанное по ним.
 *
 * Одно место на всё приложение: значок на «Профиле» в нижнем меню, строка
 * «Мои сделки» в профиле, список сделок и шапка чата показывают одни и те же
 * числа. Живые события приходят сюда один раз, а не в каждый экран отдельно.
 */

// Сколько держится «печатает…» после последнего сигнала собеседника
const TYPING_MS = 3500;

interface DealsState {
    deals: Deal[] | null;
    unread: Record<string, number>;
    typing: Record<string, number>;
    /** Сделка, чат которой открыт на экране прямо сейчас */
    viewing: string | null;

    loadDeals: () => Promise<void>;
    loadUnread: () => Promise<void>;
    upsertDeal: (deal: Deal) => void;
    setViewing: (dealId: string | null) => void;
    clearUnread: (dealId: string) => void;
}

const byActivity = (a: Deal, b: Deal) => b.last_activity_at.localeCompare(a.last_activity_at);

export const useDealsStore = create<DealsState>((set, get) => ({
    deals: null,
    unread: {},
    typing: {},
    viewing: null,

    loadDeals: async () => {
        const deals = await p2pApi.getMyDeals();
        const unread: Record<string, number> = {};
        deals.forEach((d) => {
            if (d.unread && d.id !== get().viewing) unread[d.id] = d.unread;
        });
        set({ deals, unread });
    },

    loadUnread: async () => {
        const { deals } = await p2pApi.getUnread();
        const viewing = get().viewing;
        if (viewing) delete deals[viewing];
        set({ unread: deals });
    },

    upsertDeal: (deal) => set((state) => {
        const unread = { ...state.unread };
        if (deal.unread && deal.id !== state.viewing) unread[deal.id] = deal.unread;
        else delete unread[deal.id];

        if (!state.deals) return { unread };
        const rest = state.deals.filter((d) => d.id !== deal.id);
        return { unread, deals: [deal, ...rest].sort(byActivity) };
    }),

    setViewing: (dealId) => {
        set({ viewing: dealId });
        if (dealId) get().clearUnread(dealId);
    },

    clearUnread: (dealId) => set((state) => {
        if (!state.unread[dealId]) return {};
        const unread = { ...state.unread };
        delete unread[dealId];
        return { unread };
    }),
}));

export const selectUnreadTotal = (state: DealsState) =>
    Object.values(state.unread).reduce((sum, n) => sum + n, 0);

export const selectIsTyping = (dealId: string) => (state: DealsState) =>
    (state.typing[dealId] ?? 0) > Date.now();

function onMessage(dealId: string, message: DealMessage) {
    useDealsStore.setState((state) => {
        const typing = { ...state.typing };
        delete typing[dealId];

        const unread = { ...state.unread };
        if (message.from !== 'me' && state.viewing !== dealId) {
            unread[dealId] = (unread[dealId] ?? 0) + 1;
        }

        const deals = state.deals?.map((d) => d.id !== dealId ? d : {
            ...d,
            last_message: {
                from: message.from,
                text: message.text,
                photo: Boolean(message.photo_url || message.legacy_media),
                created_at: message.created_at,
            },
            last_activity_at: message.created_at,
        }).sort(byActivity) ?? null;

        return { typing, unread, deals };
    });
}

function onTyping(dealId: string) {
    const until = Date.now() + TYPING_MS;
    useDealsStore.setState((state) => ({ typing: { ...state.typing, [dealId]: until } }));
    // Перерисовка по истечении: сам по себе «печатает…» не погаснет — стор
    // не узнает, что время вышло, пока что-нибудь его не тронет
    setTimeout(() => {
        useDealsStore.setState((state) => {
            if ((state.typing[dealId] ?? 0) > Date.now()) return {};
            const typing = { ...state.typing };
            delete typing[dealId];
            return { typing };
        });
    }, TYPING_MS + 50);
}

let started = false;

/** Подписка на живые события сделок — один раз, после входа */
export function startDeals() {
    const store = useDealsStore.getState();
    store.loadUnread().catch(() => undefined);
    if (started) return;
    started = true;

    realtime.subscribe((event) => {
        if (event?.type === 'deal_message') onMessage(event.deal_id, event.message);
        else if (event?.type === 'deal_typing') onTyping(event.deal_id);
        else if (event?.type === 'deal_updated') useDealsStore.getState().upsertDeal(event.deal);
    });

    // После обрыва события, ушедшие в мёртвый сокет, не повторятся —
    // дочитываем счётчики и список запросом
    realtime.onReconnect(() => {
        const state = useDealsStore.getState();
        state.loadUnread().catch(() => undefined);
        if (state.deals) state.loadDeals().catch(() => undefined);
    });
}
