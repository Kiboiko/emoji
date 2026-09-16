import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import { PackageOpen } from 'lucide-react';
import { Header } from '@/components/Header/Header';
import { ProductCard } from '@/components/ProductCard/ProductCard';
import { ProductCardSkeleton } from '@/components/ProductCard/ProductCardSkeleton';
import { productsApi, categoriesApi, cartApi } from '@/api/client';
import { useAuthStore } from '@/store/authStore';
import { useCartStore } from '@/store/cartStore';
import { useTelegram } from '@/hooks/useTelegram';
import { useWebSocket } from '@/hooks/useWebSocket';
import type { Product, Category } from '@/types';
import './Home.css';

export const Home: React.FC = () => {
    const navigate = useNavigate();
    const { language } = useAuthStore();
    const { setCart } = useCartStore();
    const { haptic } = useTelegram();

    const [products, setProducts] = useState<Product[]>([]);
    const [categories, setCategories] = useState<Category[]>([]);
    const [selectedCategory, setSelectedCategory] = useState<string | null>(null);
    const [searchQuery, setSearchQuery] = useState('');
    const [isLoading, setIsLoading] = useState(true);

    // Client-side filtering for search - no flickering!
    const filteredProducts = React.useMemo(() => {
        if (!searchQuery.trim()) return products;

        const query = searchQuery.toLowerCase();
        return products.filter(product =>
            product.name.toLowerCase().includes(query) ||
            product.description?.toLowerCase().includes(query)
        );
    }, [products, searchQuery]);

    const loadData = async (silent = false) => {
        try {
            if (!silent) setIsLoading(true);

            // Fetch categories independently
            try {
                const categoriesData = await categoriesApi.getCategories(language);
                setCategories(categoriesData);
            } catch (error) {
                console.error('Failed to load categories:', error);
                if (!categories.length) setCategories([]);
            }

            // Fetch products independently (without search query - search is client-side now)
            try {
                const productsData = await productsApi.getProducts({
                    category_id: selectedCategory || undefined,
                    lang: language,
                });

                // Sort: TOP items first
                const sortedProducts = productsData.sort((a: Product, b: Product) => {
                    if (a.is_top === b.is_top) return 0;
                    return a.is_top ? -1 : 1;
                });

                setProducts(sortedProducts);
            } catch (error) {
                console.error('Failed to load products:', error);
                setProducts([]);
            }

        } catch (error) {
            console.error('Global load error:', error);
        } finally {
            if (!silent) setIsLoading(false);
        }
    };

    // Listen for WebSocket updates
    useWebSocket((message) => {
        if (message.type === 'product_updated') {
            // Update local state directly without reload
            const rawProduct = message.data;

            // Transform raw backend data (name_ru/name_en) to localized frontend data (name)
            const updatedProduct = {
                ...rawProduct,
                name: language === 'ru' ? rawProduct.name_ru : rawProduct.name_en,
                description: language === 'ru' ? rawProduct.description_ru : rawProduct.description_en,
            };

            setProducts(prev => {
                // If digital and no stock, remove it immediately
                if (updatedProduct.type === 'digital' && (updatedProduct.stock === undefined || updatedProduct.stock <= 0)) {
                    return prev.filter(p => p.id !== updatedProduct.id);
                }

                const exists = prev.find(p => p.id === updatedProduct.id);
                if (exists) {
                    return prev.map(p => p.id === updatedProduct.id ? updatedProduct : p);
                }

                // If it doesn't exist but is now valid (e.g. stock restored), valid addition logic needed.
                // For now, simpler to reload if we wanted to support "appearing" items,
                // but usually stock restore comes via manual edit or cancellation.
                // If cancellation restores stock, we might want it to appear?
                // For now, let's stick to update/remove logic to fix the "hiding" issue.
                // If we want it to appear, we should probably check filter criteria and add it, 
                // but reloading is safer for "appearing".
                // Let's at least handle the "remove" part correctly.
                return prev;
            });
        }
        else if (message.type === 'product_created') {
            // New product: silent reload to ensure correct ordering/filtering
            loadData(true);
        }
        else if (message.type === 'product_deleted') {
            const deletedId = message.data.id;
            setProducts(prev => prev.filter(p => p.id !== deletedId));
        }
        else if (message.type === 'category_created' || message.type === 'category_updated' || message.type === 'category_deleted') {
            loadData(true);
        }
    });

    // Load data only on language or category change, NOT on search query change
    useEffect(() => {
        loadData();
    }, [language, selectedCategory]);

    const handleAddToCart = async (productId: string) => {
        const product = filteredProducts.find(p => p.id === productId);
        if (!product) return;

        console.log('Handling add to cart for:', product);

        if (product.type === 'service') {
            haptic.impact('light');
            navigate(`/product/${productId}`);
            return;
        }

        try {
            haptic.impact('light');
            // Use min_quantity if defined, otherwise 1
            const quantity = product.min_quantity || 1;
            console.log(`Adding ${product.name} with quantity: ${quantity}`);

            await cartApi.addToCart(productId, quantity);
            const cart = await cartApi.getCart(language);
            setCart(cart);
            haptic.notification('success');
            // Alert removed by request
        } catch (error: any) {
            console.error('Failed to add to cart:', error);
            if (error.response?.data?.detail) {
                alert(`Error: ${error.response.data.detail}`);
            } else {
                haptic.notification('error');
            }
        }
    };

    // Detect if user is on mobile device (not desktop Telegram)
    const isMobile = React.useMemo(() => {
        const tg = (window as any).Telegram?.WebApp;
        if (!tg) return false;
        return tg.platform === 'ios' || tg.platform === 'android';
    }, []);

    return (
        <div className="home-page">
            <Header
                searchQuery={searchQuery}
                onSearchChange={setSearchQuery}
                pageTitle={isMobile ? (language === 'ru' ? 'Каталог' : 'Catalog') : undefined}
            />

            <div className="container">
                {/* Categories */}
                <div className="categories-scroll">
                    <button
                        className={`category-chip ${!selectedCategory ? 'active' : ''}`}
                        onClick={() => setSelectedCategory(null)}
                    >
                        {language === 'ru' ? 'Все' : 'All'}
                    </button>
                    {categories.map((category) => (
                        <button
                            key={category.id}
                            className={`category-chip ${selectedCategory === category.id ? 'active' : ''}`}
                            onClick={() => setSelectedCategory(selectedCategory === category.id ? null : category.id)}
                        >
                            {category.name}
                        </button>
                    ))}
                </div>

                {/* Products Grid */}
                <div className="products-grid">
                    {isLoading ? (
                        Array.from({ length: 6 }).map((_, i) => (
                            <ProductCardSkeleton key={i} />
                        ))
                    ) : filteredProducts.length === 0 ? (
                        <div className="empty-state">
                            <PackageOpen size={40} className="empty-state-icon" />
                            <div className="empty-state-title">
                                {language === 'ru' ? 'Товары не найдены' : 'No products found'}
                            </div>
                            {/* Разные подсказки: «ничего нет» и «ничего не подошло под
                                фильтр» — это разные ситуации, и совет во втором случае
                                должен быть про фильтр, а не про магазин */}
                            <p className="empty-state-text">
                                {searchQuery || selectedCategory
                                    ? (language === 'ru'
                                        ? 'Попробуйте изменить запрос или выбрать другую категорию.'
                                        : 'Try a different search or category.')
                                    : (language === 'ru'
                                        ? 'Каталог пока пуст. Загляните позже.'
                                        : 'The catalog is empty for now. Check back later.')}
                            </p>
                        </div>
                    ) : (
                        filteredProducts.map((product, index) => (
                            <motion.div
                                key={product.id}
                                initial={{ opacity: 0, y: 20 }}
                                animate={{ opacity: 1, y: 0 }}
                                // Задержку ограничиваем: при множителе без потолка
                                // сотый товар появлялся бы через пять секунд, а
                                // тысячный — почти через минуту
                                transition={{ delay: Math.min(index * 0.05, 0.4) }}
                            >
                                <ProductCard
                                    product={product}
                                    onClick={() => navigate(`/product/${product.id}`)}
                                    onAddToCart={() => handleAddToCart(product.id)}
                                />
                            </motion.div>
                        ))
                    )}
                </div>
            </div>

            <div className="bottom-nav-spacer" />
        </div>
    );
};
