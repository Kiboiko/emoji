import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Activity, LayoutGrid, List, PackageOpen } from 'lucide-react';
import { Header } from '@/components/Header/Header';
import { CategoryFilter } from '@/components/CategoryFilter/CategoryFilter';
import { CatalogSortMenu, type CatalogSort } from '@/components/CatalogSort/CatalogSort';
import { ProductCard } from '@/components/ProductCard/ProductCard';
import { ProductCardSkeleton } from '@/components/ProductCard/ProductCardSkeleton';
import { ProductRow, ProductRowSkeleton } from '@/components/ProductRow/ProductRow';
import { StoreStrip } from '@/components/StoreStrip/StoreStrip';
import { StoreHeading } from '@/components/StoreStrip/StoreHeading';
import { productsApi, categoriesApi, cartApi, storesApi } from '@/api/client';
import { useAuthStore } from '@/store/authStore';
import { useToastStore, errorText } from '@/store/toastStore';
import { useCartStore } from '@/store/cartStore';
import { useTelegram } from '@/hooks/useTelegram';
import { useWebSocket } from '@/hooks/useWebSocket';
import type { Product, Category, StoreCard } from '@/types';
import { markStartup, readyStartupImages, failStartup } from '@/store/startupStore';
import { thumb } from '@/lib/image';
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

/**
 * Последний загруженный каталог — на время жизни приложения.
 *
 * Главная пересоздаётся при каждом возврате на неё из нижнего меню, и раньше
 * каждый раз начинала с пустого места: заглушки, три запроса к серверу один
 * за другим, потом товары. Теперь возврат сразу показывает то, что было, а
 * свежая версия подтягивается молча и подменяет его, если что-то изменилось.
 * Выбранная категория запоминается вместе с товарами: список под ней свой.
 */
let catalogCache: {
    language: string;
    category: string | null;
    root: string | null;
    sort: CatalogSort;
    products: Product[];
    hasMore: boolean;
    categories: Category[];
    stores: StoreCard[];
} | null = null;

/** Сколько товаров приходит за раз: каталог грузится по мере прокрутки */
const PAGE_SIZE = 40;

/** Пауза после последней буквы поиска: запрос на каждую букву — лишняя нагрузка */
const SEARCH_DELAY_MS = 300;

export const Home: React.FC = () => {
    const navigate = useNavigate();
    const { language } = useAuthStore();
    const { cart, setCart } = useCartStore();
    const { haptic } = useTelegram();
    const showToast = useToastStore((s) => s.show);

    const cached = catalogCache?.language === language ? catalogCache : null;
    const [products, setProducts] = useState<Product[]>(cached?.products ?? []);
    const [categories, setCategories] = useState<Category[]>(cached?.categories ?? []);
    const [stores, setStores] = useState<StoreCard[]>(cached?.stores ?? []);
    const [selectedCategory, setSelectedCategory] = useState<string | null>(cached?.category ?? null);
    const [selectedRoot, setSelectedRoot] = useState<string | null>(cached?.root ?? null);
    const [sort, setSort] = useState<CatalogSort>(cached?.sort ?? 'default');
    const [searchQuery, setSearchQuery] = useState('');
    // Запрос уходит на сервер с задержкой, а поле реагирует сразу
    const [activeSearch, setActiveSearch] = useState('');
    const [isLoading, setIsLoading] = useState(!cached);
    const [hasMore, setHasMore] = useState(cached?.hasMore ?? false);
    const [loadingMore, setLoadingMore] = useState(false);
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

    // Поиск идёт на сервере: каталог приходит кусками, и искать только по
    // уже загруженному значило бы не находить то, что ещё не подгрузилось.
    // Пока человек печатает, на экране остаётся прежний список — без
    // заглушек между буквами.
    const filteredProducts = products;

    // Строка магазинов — витрина для разглядывания. Как только человек ищет
    // или выбрал категорию, он знает, что ему нужно, и всё лишнее между ним
    // и результатом только мешает.
    const isBrowsing = !searchQuery.trim() && !selectedCategory;

    // Ленты хитов здесь была: широкая карточка не помещалась в ширину экрана
    // и вторая обрезалась пополам. Хиты и так идут первыми в общей сетке —
    // их сортирует loadData, — и плашка «Хит» на картинке никуда не делась.

    // Номер последней загрузки: при быстром переключении категорий или
    // наборе поиска ответ на прежний запрос мог прийти позже и подменить
    // список чужими товарами
    const lastRequest = React.useRef(0);
    // Сколько товаров сервер уже отдал в этой выдаче. Это сдвиг для
    // следующей страницы, а не длина списка на экране: из списка товар
    // может пропасть по сокету (раскупили), и сдвиг по длине пропустил бы
    // один товар
    const loadedCount = React.useRef(cached?.products.length ?? 0);

    // Свежие данные для слияния читаем из ссылки, а не из замыкания: ответ
    // приходит позже, и список к тому моменту мог вырасти
    const productsRef = React.useRef<Product[]>(products);
    productsRef.current = products;

    // merge — обновить загруженное, а не заменить его первой страницей. Нужен
    // фоновым обновлениям (новый товар по сокету, возврат на вкладку): человек
    // мог пролистать сто двадцать товаров, и откат к сорока на ровном месте —
    // это потерянное место в списке.
    const loadData = async (
        silent = false, term = activeSearch, withExtras = true, merge = false,
    ) => {
        const request = ++lastRequest.current;
        if (!silent) setIsLoading(true);

        // Запросы разом, а не по очереди: по очереди время ответа
        // складывалось, и на мобильной сети каталог ждал втрое дольше.
        // Каждый сам по себе: без категорий и магазинов каталог работает,
        // и падение одного не должно оставлять человека без товаров.
        // withExtras=false — меняется только поиск: категории и магазины от
        // него не зависят, перезапрашивать их незачем
        const [categoriesResult, storesResult, productsResult] = await Promise.allSettled([
            (withExtras ? categoriesApi.getCategories(language) : Promise.resolve(categories))
                .then(value => { markStartup('categories'); return value; }, error => { markStartup('categories'); throw error; }),
            (withExtras ? storesApi.getStores() : Promise.resolve(stores))
                .then(value => { markStartup('stores'); return value; }, error => { markStartup('stores'); throw error; }),
            productsApi.getPage({
                category_id: selectedCategory || undefined,
                sort,
                search: term || undefined,
                lang: language,
                skip: 0,
                limit: PAGE_SIZE,
            }),
        ]);
        if (request !== lastRequest.current) return;

        const nextCategories = categoriesResult.status === 'fulfilled' ? categoriesResult.value : categories;
        if (categoriesResult.status === 'rejected') {
            console.error('Failed to load categories:', categoriesResult.reason);
        }

        const nextStores = storesResult.status === 'fulfilled' ? storesResult.value : stores;
        if (storesResult.status === 'rejected') {
            console.error('Failed to load stores:', storesResult.reason);
        }

        setCategories(nextCategories);
        setStores(nextStores);

        if (productsResult.status === 'fulfilled') {
            markStartup('products');
            // Порядок (хиты первыми) задаёт сервер: сортировать на клиенте
            // нельзя — страницы пришли бы вперемешку
            const { items, hasMore: more } = productsResult.value as { items: Product[]; hasMore: boolean };
            void readyStartupImages(items.slice(0, 2).map(product => thumb(product.image_url)));

            let nextProducts = items;
            let nextHasMore = more;
            if (merge && productsRef.current.length > items.length) {
                // Свежая первая страница встаёт вперёд, всё остальное, что
                // человек уже пролистал, остаётся за ней. «Дальше есть» и сдвиг
                // не трогаем: они про хвост, а не про первую страницу
                const fresh = new Set(items.map((p) => p.id));
                nextProducts = [...items, ...productsRef.current.filter((p) => !fresh.has(p.id))];
                nextHasMore = hasMore;
            } else {
                loadedCount.current = items.length;
            }
            setProducts(nextProducts);
            setHasMore(nextHasMore);
            // В память — только каталог без поиска: результат поиска не то,
            // с чего стоит начинать следующее открытие главной
            if (!term) {
                catalogCache = {
                    language,
                    category: selectedCategory,
                    root: selectedRoot, sort,
                    products: nextProducts,
                    hasMore: nextHasMore,
                    categories: nextCategories,
                    stores: nextStores,
                };
            }
        } else {
            console.error('Failed to load products:', productsResult.reason);
            failStartup(t('Не удалось загрузить товары. Проверьте подключение и повторите попытку.', 'Could not load products. Check your connection and try again.'), () => { void loadData(false, term, true, merge); });
            // Сбой тихого обновления не стирает то, что уже на экране
            if (!silent) {
                setProducts([]);
                setHasMore(false);
            }
        }
        if (!silent) setIsLoading(false);
    };

    // Следующая порция каталога — когда конец списка приближается к экрану
    const loadMore = async () => {
        if (!hasMore || loadingMore || isLoading) return;
        const request = lastRequest.current;
        setLoadingMore(true);
        try {
            const page = await productsApi.getPage({
                category_id: selectedCategory || undefined,
                sort,
                search: activeSearch || undefined,
                lang: language,
                skip: loadedCount.current,
                limit: PAGE_SIZE,
            });
            // Пока шёл запрос, выдача сменилась (другая категория, поиск)
            if (request !== lastRequest.current) return;

            const items = page.items as Product[];
            loadedCount.current += items.length;
            setProducts((prev) => {
                const known = new Set(prev.map((p) => p.id));
                const next = [...prev, ...items.filter((p) => !known.has(p.id))];
                if (!activeSearch && catalogCache) catalogCache = { ...catalogCache, products: next, hasMore: page.hasMore };
                return next;
            });
            setHasMore(page.hasMore);
        } catch (error) {
            // Не страшно: следующая прокрутка попробует снова
            console.error('Failed to load more products:', error);
        } finally {
            setLoadingMore(false);
        }
    };

    // Поиск: запрос уходит, когда человек перестал печатать
    useEffect(() => {
        const id = window.setTimeout(() => setActiveSearch(searchQuery.trim()), SEARCH_DELAY_MS);
        return () => window.clearTimeout(id);
    }, [searchQuery]);

    // Конец списка: наблюдатель следит за невидимой отметкой под сеткой
    const sentinel = React.useRef<HTMLDivElement>(null);
    useEffect(() => {
        const node = sentinel.current;
        if (!node || !hasMore) return;
        const observer = new IntersectionObserver(
            (entries) => { if (entries[0]?.isIntersecting) loadMore(); },
            { rootMargin: '700px 0px' },
        );
        observer.observe(node);
        return () => observer.disconnect();
        // loadMore берёт свежие значения из замыкания: пересоздаём наблюдателя,
        // когда список вырос или загрузка закончилась — если отметка всё ещё
        // на виду, он тут же подгрузит следующую порцию
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [hasMore, loadingMore, products.length, isLoading]);

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
            // Новый товар: тихо обновляем первую страницу, не теряя
            // уже пролистанного
            loadData(true, activeSearch, true, true);
        }
        else if (message.type === 'product_deleted') {
            const deletedId = message.data.id;
            setProducts(prev => prev.filter(p => p.id !== deletedId));
        }
        else if (message.type === 'category_created' || message.type === 'category_updated' || message.type === 'category_deleted') {
            loadData(true, activeSearch, true, true);
        }
    });

    // Загрузка — при смене языка или категории, не при вводе в поиск.
    // Если этот же список уже есть в памяти, он на экране, и обновление
    // идёт без заглушек
    useEffect(() => {
        const fresh = catalogCache?.language === language && catalogCache.category === selectedCategory && catalogCache.sort === sort;
        // Есть в памяти — показано сразу, обновляем молча и со слиянием
        loadData(fresh, activeSearch, true, fresh);
    }, [language, selectedCategory, sort]);

    // Смена строки поиска — только список товаров, молча (без заглушек между
    // буквами). Первый запуск пропускаем: каталог уже грузит эффект выше
    const previousSearch = React.useRef(activeSearch);
    useEffect(() => {
        if (previousSearch.current === activeSearch) return;
        previousSearch.current = activeSearch;
        loadData(true, activeSearch, categories.length === 0);
    }, [activeSearch]);

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
    const renderProduct = (product: Product, index: number) => (
        view === 'list'
            ? (
                <ProductRow
                    key={product.id}
                    product={product}
                    priority={index < 2}
                    onClick={() => openProduct(product.id)}
                    onAddToCart={() => handleAddToCart(product.id)}
                />
            )
            : (
                <ProductCard
                    key={product.id}
                    product={product}
                    priority={index < 2}
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
                searchActions={<CatalogSortMenu value={sort} onChange={setSort} language={language} />}
                searchAside={(
                    <button type="button" className="header-sales-button" onClick={() => navigate('/sales')}>
                        <Activity size={20} strokeWidth={1.8} aria-hidden="true" />
                        <span>{t('Продажи', 'Sales')}</span>
                    </button>
                )}
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
                <CategoryFilter
                    categories={categories}
                    root={selectedRoot}
                    selected={selectedCategory}
                    language={language}
                    onChange={(root, category) => {
                        setSelectedRoot(root);
                        setSelectedCategory(category);
                    }}
                />
                {/* Даже один магазин показываем: строка отвечает на вопрос
                    «кто здесь торгует», и при единственном продавце ответ
                    не менее важен, чем при десяти. */}
                {isBrowsing && !isLoading && stores.length > 0 && (
                    <>
                        <StoreHeading language={language} />
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
                    // Карточки появляются сразу. Здесь был поочерёдный выезд
                    // с задержкой до 0,4 с: при каждом возврате на главную
                    // сетка заново «въезжала» — второе мерцание после смены
                    // экрана, да ещё анимация на каждую карточку
                    <div className="products-grid">
                        {filteredProducts.map((product, index) => (
                            <div key={product.id}>
                                {renderProduct(product, index)}
                            </div>
                        ))}
                    </div>
                )}

                {/* Отметка конца списка: когда она подходит к экрану, подгружается
                    следующая порция. Пока грузится — две заглушки */}
                {hasMore && <div ref={sentinel} className="catalog-sentinel" aria-hidden="true" />}
                {loadingMore && (
                    <div className={view === 'list' ? 'products-list' : 'products-grid'}>
                        {Array.from({ length: 2 }).map((_, i) => (
                            view === 'list'
                                ? <ProductRowSkeleton key={i} />
                                : <ProductCardSkeleton key={i} />
                        ))}
                    </div>
                )}
            </div>

            <div className="bottom-nav-spacer" />
        </div>
    );
};
