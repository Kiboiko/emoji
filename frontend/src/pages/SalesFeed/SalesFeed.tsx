import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';
import { CategoryFilter } from '@/components/CategoryFilter/CategoryFilter';
import { categoriesApi } from '@/api/client';
import { salesFeedApi, type Sale } from '@/api/salesFeed';
import { useAuthStore } from '@/store/authStore';
import { thumb } from '@/lib/image';
import type { Category } from '@/types';
import './SalesFeed.css';
export function SalesFeed() {
 const {language} = useAuthStore(); const navigate = useNavigate(); const t=(ru:string,en:string)=>language==='ru'?ru:en;
 const [categories,setCategories]=useState<Category[]>([]); const [root,setRoot]=useState(''); const [child,setChild]=useState('');
 const [items,setItems]=useState<Sale[]>([]); const [more,setMore]=useState(false); const [loading,setLoading]=useState(false); const [error,setError]=useState(false); const request=useRef(0); const offset=useRef(0);
 useEffect(()=>{let live=true; categoriesApi.getCategories(language).then(data=>{if(live)setCategories(data);}).catch(()=>{}); return ()=>{live=false;};},[language]);
 async function load(append=false) { const seq=++request.current; setLoading(true);setError(false);try {const page=await salesFeedApi.get({category_id:child||root||undefined,skip:append?offset.current:0,limit:30,lang:language});if(seq!==request.current)return; offset.current=(append?offset.current:0)+page.items.length;setItems(prev=>append?[...prev,...page.items.filter(s=>!prev.some(p=>p.id===s.id))]:page.items);setMore(page.has_more);}catch{if(seq===request.current)setError(true);}finally{if(seq===request.current)setLoading(false);}}
 useEffect(()=>{setItems([]);setMore(false);load();return ()=>{request.current++;};},[language,root,child]);
 return <div className="sales-page"><header className="sales-header">
 <button type="button" onClick={()=>navigate('/')} aria-label={t('Назад в каталог','Back to catalog')}><ArrowLeft size={22}/></button>
 <h1>{t('Лента продаж','Sales feed')}</h1>
 </header><div className="container">
 <CategoryFilter categories={categories} root={root || null} selected={child || root || null} language={language}
    onChange={(nextRoot, category) => {setRoot(nextRoot || '');setChild(category && category !== nextRoot ? category : '');}} />
 <div className="sales-rows">{items.map(s=><button type="button" className="sale-row" key={s.id} disabled={!s.product_id} onClick={()=>{if(s.product_id)navigate(`/product/${s.product_id}`);}}>{s.image_url&&<img src={thumb(s.image_url,'cart')} alt="" loading="lazy"/>}<span className="sale-content"><strong>{s.name}</strong><span>{s.store_name}</span><span>{s.quantity} {t('шт.','pcs')} · ${s.total_usd}</span><time dateTime={s.completed_at}>{new Date(s.completed_at).toLocaleString(language==='ru'?'ru-RU':'en-US')}</time></span></button>)}</div>
 {loading&&<p role="status">{t('Загрузка…','Loading…')}</p>}{error&&<p role="alert">{t('Не удалось загрузить продажи.','Could not load sales.')} <button onClick={()=>load(items.length>0)}>{t('Повторить','Retry')}</button></p>}{!loading&&!error&&!items.length&&<p>{t('Завершённых продаж пока нет.','No completed sales yet.')}</p>}{more&&!loading&&!error&&<button className="sales-more" onClick={()=>load(true)}>{t('Показать ещё','Load more')}</button>}
 </div></div>;
}
