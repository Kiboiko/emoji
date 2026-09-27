import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import { LayoutGrid, List, PackageOpen } from 'lucide-react';
import { Header } from '@/components/Header/Header';
import { ProductCard } from '@/components/ProductCard/ProductCard';
import { ProductCardSkeleton } from '@/components/ProductCard/ProductCardSkeleton';
import { ProductRow, ProductRowSkeleton } from '@/components/ProductRow/ProductRow';
import { StoreStrip } from '@/components/StoreStrip/StoreStrip';
import { productsApi, categoriesApi, cartApi, storesApi } from '@/api/client';
import { useAuthStore } from '@/store/authStore';
import { useToastStore, errorText } from '@/store/toastStore';
import { useCartStore } from '@/store/cartStore';
import { useTelegram } from '@/hooks/useTelegram';
import { useWebSocket } from '@/hooks/useWebSocket';
import type { Product, Category, StoreCard } from '@/types';
import './Home.css';

type CatalogView = 'grid' | 'list';

const VIEW_KEY = 'catalog-view';

/**
 * Вид каталога помним между заходами: человек выбирает его один раз под свою
 * привычку, и сбрасывать выбор на каждом открытии Mini App — значит заставлять
 * выбирать заново. localStorage в приватном окне может бросить, поэтому обе
 * стороны обёрнуты.
 */
const readView = (): CatalogView => {
    try {
        return localStorage.getItem(VIEW_KEY) === 'list' ? 'list' : 'grid';
    } catch {
        return 'grid';
    }
};

export const Home: React.FC = () => {
    const navigate = useNavigate();
    const { language } = useAuthStore();
    const { cart, setCart } = useCartStore();
    const { haptic } = useTelegram();
    const showToast = useToastStore((s) => s.show);

    const [products, setProducts] = useState<Product[]>([]);
    const [categories, setCategories] = useState<Category[]>([]);
    const [stores, setStores] = useState<StoreCard[]>([]);
    const [selectedCategory, setSelectedCategory] = useState<string | null>(null);
    const [searchQuery, setSearchQuery] = useState('');
    const [isLoading, setIsLoading] = useState(true);
    const [view, setView] = useState<CatalogView>(readView);

    const t = (ru: string, en: string) => (language === 'ru' ? ru : en);

    const changeView = (next: CatalogView) => {
        setView(next);
        haptic.impact('light');
        try {
            localStorage.setItem(VIEW_KEY, next);
        } catch {
            // Приватный режим: вид просто не переживёт перезапуск
        }
    };

    // Client-side filtering for search - no flickering!
    const filteredProducts = React.useMemo(() => {
        if (!searchQuery.trim()) return products;

        const query = searchQuery.toLowerCase();
        return products.filter(product =>
            product.name.toLowerCase().includes(query) ||
            product.description?.toLowerCase().includes(query)
        );
    }, [products, searchQuery]);

    // Строка магазинов — витрина для разглядывания. Как только человек ищет
    // или выбрал категорию, он знает, что ему нужно, и всё лишнее между ним
    // и результатом только мешает.
    const isBrowsing = !searchQuery.trim() && !selectedCategory;

    // Ленты хитов здесь была: широкая карточка не помещалась в ширину экрана
    // и вторая обрезалась пополам. Хиты и так идут первыми в общей сетке —
    // их сортирует loadData, — и плашка «Хит» на картинке никуда не делась.

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

            // Магазины независимо: без них каталог работает, и падение этого
            // запроса не должно оставлять человека без товаров
            try {
                setStores(await storesApi.getStores());
            } catch (error) {
                console.error('Failed to load stores:', error);
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

        // Услуге нужна ссылка на аккаунт или пост, а её спрашивают на
        // странице товара: класть такое в корзину одним нажатием нельзя
        if (product.type === 'service') {
            haptic.impact('light');
            navigate(`/product/${productId}`);
            return;
        }

        // Товар уже в корзине, и больше взять нельзя: вещь продавца
        // существует в одном экземпляре. Раньше повторное нажатие упиралось
        // в отказ сервера — человек видел красную ошибку там, где ничего не
        // сломалось и надо было просто открыть корзину.
        const inCart = cart?.items
            .filter((item) => item.product_id === productId)
            .reduce((sum, item) => sum + item.quantity, 0) ?? 0;
        const ceiling = Math.min(
            product.max_quantity ?? Number.MAX_SAFE_INTEGER,
            product.stock ?? Number.MAX_SAFE_INTEGER,
        );
        if (inCart > 0 && inCart >= ceiling) {
            haptic.impact('light');
            navigate('/cart');
            return;
        }

        try {
            haptic.impact('light');
            await cartApi.addToCart(productId, product.min_quantity || 1);
            setCart(await cartApi.getCart(language));
            haptic.notification('success');
        } catch (error) {
            // Был window.alert с техническим текстом вроде «Error: Not
            // authenticated»: системное окно поверх Mini App выглядит
            // чужеродно и ничего человеку не объясняет
            haptic.notification('error');
            showToast(errorText(error, language === 'ru'
                ? 'Не удалось добавить в корзину'
                : 'Failed to add to cart'), 'error');
        }
    };

    const openProduct = (id: string) => navigate(`/product/${id}`);

    // Товар рисуется одним из двух видов, но данные и обработчики у них общие
    const renderProduct = (product: Product) => (
        view === 'list'
            ? (
                <ProductRow
                    key={product.id}
                    product={product}
                    onClick={() => openProduct(product.id)}
                    onAddToCart={() => handleAddToCart(product.id)}
                />
            )
            : (
                <ProductCard
                    product={product}
                    onClick={() => openProduct(product.id)}
                    onAddToCart={() => handleAddToCart(product.id)}
                />
            )
    );

    return (
        <div className="home-page">
            <Header
                searchQuery={searchQuery}
                onSearchChange={setSearchQuery}
                pageTitle={t('Каталог', 'Catalog')}
                actions={(
                    <div className="view-switch">
                        <button
                            type="button"
                            className={view === 'grid' ? 'active' : ''}
                            onClick={() => changeView('grid')}
                            aria-label={t('Показать сеткой', 'Show as grid')}
                            aria-pressed={view === 'grid'}
                        >
                            <LayoutGrid size={17} />
                        </button>
                        <button
                            type="button"
                            className={view === 'list' ? 'active' : ''}
                            onClick={() => changeView('list')}
                            aria-label={t('Показать списком', 'Show as list')}
                            aria-pressed={view === 'list'}
                        >
                            <List size={17} />
                        </button>
                    </div>
                )}
            />

            <div className="container">
                {/* Categories */}
                <div className="categories-scroll">
                    <button
                        className={`category-chip ${!selectedCategory ? 'active' : ''}`}
                        onClick={() => setSelectedCategory(null)}
                    >
                        {t('Все', 'All')}
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

                {/* Даже один магазин показываем: строка отвечает на вопрос
                    «кто здесь торгует», и при единственном продавце ответ
                    не менее важен, чем при десяти. */}
                {isBrowsing && !isLoading && stores.length > 0 && (
                    <>
                        <h2 className="home-section">{t('Магазины', 'Stores')}</h2>
                        <StoreStrip stores={stores} />
                    </>
                )}

                {/* Заголовок нужен только когда выше стоят магазины: иначе
                    сетка повисает под чужим разделом */}
                {isBrowsing && !isLoading && stores.length > 0 && (
                    <h2 className="home-section">{t('Товары', 'Products')}</h2>
                )}

                {/* Products */}
                {isLoading ? (
                    <div className={view === 'list' ? 'products-list' : 'products-grid'}>
                        {Array.from({ length: 6 }).map((_, i) => (
                            view === 'list'
                                ? <ProductRowSkeleton key={i} />
                                : <ProductCardSkeleton key={i} />
                        ))}
                    </div>
                ) : filteredProducts.length === 0 ? (
                    <div className="empty-state">
                        <PackageOpen size={40} className="empty-state-icon" />
                        <div className="empty-state-title">
                            {t('Товары не найдены', 'No products found')}
                        </div>
                        {/* Разные подсказки: «ничего нет» и «ничего не подошло под
                            фильтр» — это разные ситуации, и совет во втором случае
                            должен быть про фильтр, а не про магазин */}
                        <p className="empty-state-text">
                            {searchQuery || selectedCategory
                                ? t('Попробуйте изменить запрос или выбрать другую категорию.',
                                    'Try a different search or category.')
                                : t('Каталог пока пуст. Загляните позже.',
                                    'The catalog is empty for now. Check back later.')}
                        </p>
                    </div>
                ) : view === 'list' ? (
                    <div className="products-list">
                        {filteredProducts.map(renderProduct)}
                    </div>
                ) : (
                    <div className="products-grid">
                        {filteredProducts.map((product, index) => (
                            <motion.div
                                key={product.id}
                                initial={{ opacity: 0, y: 20 }}
                                animate={{ opacity: 1, y: 0 }}
                                // Задержку ограничиваем: при множителе без потолка
                                // сотый товар появлялся бы через пять секунд, а
                                // тысячный — почти через минуту
                                transition={{ delay: Math.min(index * 0.05, 0.4) }}
                            >
                                {renderProduct(product)}
                            </motion.div>
                        ))}
                    </div>
                )}
            </div>

            <div className="bottom-nav-spacer" />
        </div>
    );
};
