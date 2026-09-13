import { create } from 'zustand';
import type { Cart, CartItem } from '@/types';
import { cartApi } from '@/api/client';
import { useAuthStore } from './authStore';

interface CartStore {
    cart: Cart | null;
    isLoading: boolean;
    error: string | null;
    setCart: (cart: Cart) => void;
    addItem: (item: CartItem) => void;
    updateQuantity: (itemId: string, quantity: number) => void;
    removeItem: (itemId: string) => void;
    clearCart: () => void;
    setLoading: (isLoading: boolean) => void;
    setError: (error: string | null) => void;
    fetchCart: () => Promise<void>;
    get itemCount(): number;
    get totalUSDT(): number;
}

export const useCartStore = create<CartStore>((set, get) => ({
    cart: null,
    isLoading: false,
    error: null,

    setCart: (cart) => set({ cart, error: null }),

    addItem: (item) => {
        const currentCart = get().cart;
        if (currentCart) {
            const existingItem = currentCart.items.find(i => i.product_id === item.product_id);
            if (existingItem) {
                // Update quantity
                const updatedItems = currentCart.items.map(i =>
                    i.product_id === item.product_id
                        ? { ...i, quantity: i.quantity + item.quantity }
                        : i
                );
                set({
                    cart: {
                        ...currentCart,
                        items: updatedItems,
                    },
                });
            } else {
                // Add new item
                set({
                    cart: {
                        ...currentCart,
                        items: [...currentCart.items, item],
                    },
                });
            }
        }
    },

    updateQuantity: (itemId, quantity) => {
        const currentCart = get().cart;
        if (currentCart) {
            const updatedItems = currentCart.items.map(item =>
                item.id === itemId ? { ...item, quantity } : item
            );
            set({
                cart: {
                    ...currentCart,
                    items: updatedItems,
                },
            });
        }
    },

    removeItem: (itemId) => {
        const currentCart = get().cart;
        if (currentCart) {
            const updatedItems = currentCart.items.filter(item => item.id !== itemId);
            set({
                cart: {
                    ...currentCart,
                    items: updatedItems,
                },
            });
        }
    },

    clearCart: () => set({ cart: { items: [], total_usdt: 0 } }),

    setLoading: (isLoading) => set({ isLoading }),

    setError: (error) => set({ error }),

    fetchCart: async () => {
        try {
            const { language } = useAuthStore.getState();
            set({ isLoading: true });

            const cart = await cartApi.getCart(language);
            set({ cart, isLoading: false, error: null });
        } catch (error) {
            console.error('Failed to fetch cart:', error);
            // Don't set error state to avoid showing error UI on empty cart
            set({ isLoading: false });
        }
    },

    get itemCount() {
        return get().cart?.items.reduce((sum, item) => sum + item.quantity, 0) || 0;
    },

    get totalUSDT() {
        return get().cart?.total_usdt || 0;
    },
}));
