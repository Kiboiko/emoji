import { create } from 'zustand';
import { inquiriesApi, type Inquiry } from '@/api/inquiries';
import { realtime } from '@/lib/realtime';
import { useAuthStore } from '@/store/authStore';

let generation = 0;

export const useInquiryStore = create<{ rows: Inquiry[]; load: () => Promise<void>; clearUnread: (id: string) => void }>((set) => ({
    rows: [],
    load: async () => {
        const request = ++generation;
        const token = useAuthStore.getState().accessToken;
        const rows = await inquiriesApi.list();
        if (!Array.isArray(rows)) throw new Error('Invalid chat response');
        if (request !== generation || token !== useAuthStore.getState().accessToken) return;
        set({ rows });
    },
    clearUnread: id => set(state => ({ rows: state.rows.map(row => row.id === id ? { ...row, unread: 0 } : row) })),
}));

export const selectInquiryUnread = (state: { rows: Inquiry[] }) => state.rows.reduce((sum, row) => sum + row.unread, 0);

export function startInquiries() {
    let alive = true;
    const refresh = () => { if (alive) void useInquiryStore.getState().load().catch(() => undefined); };
    refresh();
    const timer = setInterval(refresh, 15000);
    const unsubscribe = realtime.subscribe(event => { if (event?.type === 'inquiry_message') refresh(); });
    const reconnect = realtime.onReconnect(refresh);
    return () => { alive = false; clearInterval(timer); unsubscribe(); reconnect(); };
}
