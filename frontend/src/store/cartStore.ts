import { create } from 'zustand';
import type { Cart, CartItem } from '@/types';
import { cartApi } from '@/api/client';
import { useAuthStore } from './authStore';
import { errorText, useToastStore } from './toastStore';

interface CartStore {
    cart: Cart | null;
    isLoading: boolean;
    isSaving: boolean;
    error: string | null;
    setCart: (cart: Cart) => void;
    addItem: (item: CartItem) => void;
    updateQuantity: (itemId: string, quantity: number) => void;
    removeItem: (itemId: string) => void;
    clearCart: () => void;
    setLoading: (isLoading: boolean) => void;
    setError: (error: string | null) => void;
    fetchCart: () => Promise<void>;
    readonly itemCount: number;
    readonly totalUSDT: number;
}

// One writer survives navigation. New taps replace pending quantities while
// in-flight writes finish in order. Refresh once the batch has settled.
const pending = new Map<string, { quantity: number | null; revision: number }>();
const confirmed = new Map<string, CartItem>();
let revision = 0;
let generation = 0;
let timer: ReturnType<typeof setTimeout> | undefined;
let running = false;
let loading: Promise<void> | undefined;

function totals(items: CartItem[]): Cart {
    const updated = items.map(item => ({
        ...item,
        subtotal_usdt: Math.round(item.price_usdt * 100) * item.quantity / 100,
        subtotal_ton: item.price_ton == null ? undefined : item.price_ton * item.quantity,
    }));
    return {
        items: updated,
        total_usdt: updated.reduce((sum, item) => sum + Math.round(item.subtotal_usdt * 100), 0) / 100,
        total_ton: updated.reduce((sum, item) => sum + (item.subtotal_ton ?? 0), 0) || undefined,
    };
}

function queueChange(itemId: string, quantity: number | null) {
    const cart = useCartStore.getState().cart;
    const item = cart?.items.find(item => item.id === itemId);
    if (!cart || !item) return;
    if (quantity !== null && (!Number.isInteger(quantity) || quantity < 1
        || (item.max_quantity != null && quantity > item.max_quantity))) return;
    if (!confirmed.has(itemId)) confirmed.set(itemId, item);
    pending.set(itemId, { quantity, revision: ++revision });
    useCartStore.setState({
        cart: totals(quantity === null ? cart.items.filter(item => item.id !== itemId)
            : cart.items.map(item => item.id === itemId ? { ...item, quantity } : item)),
        isSaving: true, error: null,
    });
    clearTimeout(timer);
    timer = setTimeout(() => { void saveChanges(); }, 150);
}

async function saveChanges() {
    if (running) return;
    running = true;
    const currentGeneration = generation;
    try {
        do {
            for (const [itemId, change] of pending) {
                if (generation !== currentGeneration) return;
                try {
                    if (change.quantity === null) await cartApi.removeFromCart(itemId);
                    else await cartApi.updateCartItem(itemId, change.quantity);
                    if (generation !== currentGeneration) return;
                    const item = confirmed.get(itemId);
                    if (change.quantity === null) confirmed.delete(itemId);
                    else if (item) confirmed.set(itemId, { ...item, quantity: change.quantity });
                } catch (error) {
                    if (generation !== currentGeneration) return;
                    // Roll back only the failed intent, preserving newer taps.
                    if (pending.get(itemId)?.revision === change.revision) {
                        const cart = useCartStore.getState().cart;
                        const item = confirmed.get(itemId);
                        if (cart && item) {
                            const items = cart.items.filter(row => row.id !== itemId);
                            items.push(item);
                            useCartStore.setState({ cart: totals(items) });
                        }
                    }
                    const language = useAuthStore.getState().language;
                    const message = errorText(error, language === 'ru' ? 'Не удалось сохранить корзину' : 'Failed to save cart');
                    useCartStore.setState({ error: message });
                    useToastStore.getState().show(message, 'error');
                }
                if (pending.get(itemId)?.revision === change.revision) pending.delete(itemId);
            }
            if (generation !== currentGeneration) return;
            if (pending.size) continue;
            const readRevision = revision;
            try {
                const cart = await cartApi.getCart(useAuthStore.getState().language);
                if (generation !== currentGeneration) return;
                if (revision === readRevision) useCartStore.setState({ cart });
            } catch (error) {
                console.error('Failed to refresh cart:', error);
            }
        } while (pending.size);
    } finally {
        running = false;
        if (generation === currentGeneration) {
            confirmed.clear();
            useCartStore.setState({ isSaving: false });
        } else if (pending.size) {
            void saveChanges();
        }
    }
}

export const useCartStore = create<CartStore>((set, get) => ({
    cart: null,
    isLoading: false,
    isSaving: false,
    error: null,
    setCart: cart => {
        if (!get().isSaving) set({ cart, error: null });
    },
    addItem: item => {
        const cart = get().cart;
        if (!cart) return;
        const existing = cart.items.find(row => row.product_id === item.product_id);
        const items = existing ? cart.items.map(row => row.id === existing.id
            ? { ...row, quantity: row.quantity + item.quantity } : row) : [...cart.items, item];
        set({ cart: totals(items) });
    },
    updateQuantity: (itemId, quantity) => queueChange(itemId, quantity),
    removeItem: itemId => queueChange(itemId, null),
    clearCart: () => {
        generation += 1;
        revision += 1;
        clearTimeout(timer);
        pending.clear();
        confirmed.clear();
        set({ cart: { items: [], total_usdt: 0 }, isSaving: false });
    },
    setLoading: isLoading => set({ isLoading }),
    setError: error => set({ error }),
    fetchCart: async () => {
        if (get().isSaving) return;
        if (loading) return loading;
        const readRevision = revision;
        set({ isLoading: true });
        loading = (async () => {
            try {
                const cart = await cartApi.getCart(useAuthStore.getState().language);
                if (readRevision === revision) set({ cart, error: null });
            } catch (error) {
                console.error('Failed to fetch cart:', error);
            } finally {
                set({ isLoading: false });
                loading = undefined;
            }
        })();
        return loading;
    },
    get itemCount() { return get().cart?.items.reduce((sum, item) => sum + item.quantity, 0) || 0; },
    get totalUSDT() { return get().cart?.total_usdt || 0; },
}));
