import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { useTonConnectUI, useTonWallet } from '@tonconnect/ui-react';
import { beginCell } from '@ton/core';
import { promotionsApi, type PromotionConfig, type PromotionInvoice } from '@/api/promotions';
import { termsApi } from '@/api/client';
import { useAuthStore } from '@/store/authStore';
import { errorText } from '@/store/toastStore';
const pending = (invoice:PromotionInvoice) => ['pending','seen'].includes(invoice.status);
export function PromotionButton({productId,language}:{productId:string;language:string}) {
 const [ui]=useTonConnectUI();const wallet=useTonWallet();const userId=useAuthStore(s=>s.user?.id);const key=`promotion:${userId}:${productId}`;
 const [submitted,setSubmitted]=useState(false);
 const [needsTerms,setNeedsTerms]=useState(false);
 const [config,setConfig]=useState<PromotionConfig|null>(null);const [invoice,setInvoice]=useState<PromotionInvoice|null>(null);const [busy,setBusy]=useState(false);const [error,setError]=useState(''); const alive=useRef(true);
 const t=(ru:string,en:string)=>language==='ru'?ru:en;
 function remember(value:PromotionInvoice){if(!alive.current)return;setInvoice(value);if(!pending(value)){setSubmitted(false);try{localStorage.removeItem(key+':submitted');}catch{}}try{if(pending(value))localStorage.setItem(key,value.id);else localStorage.removeItem(key);}catch{}}
 useEffect(()=>{alive.current=true;promotionsApi.config().then(c=>{if(alive.current)setConfig(c);}).catch(()=>{if(alive.current)setError(t('Не удалось загрузить цену продвижения.','Could not load promotion price.'));});let id:string|null=null;try{id=localStorage.getItem(key);}catch{}try{setSubmitted(localStorage.getItem(key+':submitted')===id&&!!id);}catch{}if(id)promotionsApi.check(id).then(remember).catch(()=>{if(alive.current)setError(t('Не удалось проверить предыдущую оплату. Повторите проверку.','Could not check previous payment. Retry checking.'));});return()=>{alive.current=false;};},[key]);
 useEffect(()=>{if(!invoice||!pending(invoice))return;let live=true;let running=false;let attempts=0;const timer=setInterval(async()=>{if(running)return;running=true;try{const next=await promotionsApi.check(invoice.id);if(live){remember(next);setError('');}}catch{if(live&&++attempts>=3)setError(t('Нет связи. Проверка оплаты продолжится автоматически.','Connection lost. Payment checks will continue.'));}finally{running=false;}},5000);return()=>{live=false;clearInterval(timer);};},[invoice?.id,invoice?.status,key]);
 async function pay(){if(busy)return;setBusy(true);setError('');try{
 if(!config){setConfig(await promotionsApi.config());return;}
 const terms=await termsApi.status();
 if(!terms.accepted){setNeedsTerms(true);setError(t('Для продвижения нужно принять актуальные условия площадки.','Accept the current platform terms before promoting.'));return;}
 setNeedsTerms(false);
 if(!wallet){await ui.openModal();return;}
 const expected=config.network==='testnet'?'-3':'-239';if(wallet.account.chain!==expected){setError(t('Переключите сеть кошелька: ','Switch wallet network: ')+config.network);return;}
 const created=await promotionsApi.create(productId);remember(created);if(!pending(created)||!created.payment)return;
 const payment=created.payment;
 if(submitted||created.status==='seen')return;
 await ui.sendTransaction({validUntil:payment.valid_until,network:expected,messages:[{address:payment.address,amount:payment.amount_nano,payload:beginCell().storeUint(0,32).storeStringTail(payment.comment).endCell().toBoc().toString('base64')}]});
 setSubmitted(true);try{localStorage.setItem(key+':submitted',created.id);}catch{}
 // Signing is not confirmation: only the server check can activate a promotion.
 remember(await promotionsApi.check(created.id));
 }catch(e){if(alive.current){const detail=(e as {response?:{data?:{detail?:{code?:string}}}})?.response?.data?.detail;if(detail?.code==='terms_required'){setNeedsTerms(true);setError(t('Условия обновились. Прочитайте и примите актуальную редакцию, затем продолжите продвижение.','The terms changed. Read and accept the current version, then continue promoting.'));}else setError(errorText(e,t('Оплата не завершена. Проверьте статус перед повторной оплатой.','Payment incomplete. Check status before paying again.')));}}finally{if(alive.current)setBusy(false);}}
 async function check(){setBusy(true);setError('');try{const id=invoice?.id||localStorage.getItem(key);if(id)remember(await promotionsApi.check(id));}catch(e){setError(errorText(e,t('Не удалось проверить оплату.','Could not check payment.')));}finally{setBusy(false);}}
 return <div className="listing-promotion">
 <button type="button" disabled={busy || !!(invoice && pending(invoice) && (submitted || invoice.status === 'seen'))} onClick={pay}>{busy?t('Подождите…','Please wait…'):invoice&&pending(invoice)?(submitted||invoice.status==='seen'?t('Оплата отправлена','Payment sent'):t('Продолжить оплату','Continue payment')):config?`${t('Продвинуть','Promote')} · ${config.price_ton} Gram / ${config.duration_hours} ${t('ч','h')}`:t('Загрузить цену продвижения','Load promotion price')}</button>
 {invoice&&pending(invoice)&&<><span role="status">{t('Ожидаем подтверждения сети','Awaiting network confirmation')}</span><button type="button" disabled={busy} onClick={check}>{t('Проверить оплату','Check payment')}</button></>}
 {!invoice&&error&&!needsTerms&&<button type="button" disabled={busy} onClick={check}>{t('Проверить оплату','Check payment')}</button>}
 {needsTerms&&<Link className="promotion-terms-link" to="/terms">{t('Открыть и принять условия','Read and accept the terms')}</Link>}
 {invoice?.status==='confirmed'&&<span role="status">{t('Продвижение подтверждено до ','Promoted until ')}{invoice.promoted_until?new Date(invoice.promoted_until).toLocaleString(language==='ru'?'ru-RU':'en-US'):''}</span>}
 {invoice?.status==='credited_to_balance'&&<span role="status">{t('Продвижение не включено. На баланс зачислено ','Promotion was not activated. Credited to balance: ')}{(Number(invoice.credited_nano)/1e9).toFixed(9).replace(/0+$/,'').replace(/\.$/,'')} Gram. {invoice.credit_reason==='underpaid'?t('Получена неполная сумма.','Amount received was too low.'):invoice.credit_reason==='late'?t('Оплата поступила после истечения счёта.','Payment arrived after invoice expiry.'):t('Товар недоступен для продвижения.','Product is not eligible for promotion.')}</span>}
 {invoice?.status==='confirmed'&&invoice.credit_reason==='overpaid'&&<span>{t('Переплата зачислена на внутренний баланс.','Excess payment was credited to your balance.')}</span>}
 {invoice?.status==='expired'&&<span>{t('Счёт истёк. Перед новой оплатой проверьте баланс.','Invoice expired. Check your balance before paying again.')}</span>}
 {error&&<span role="alert">{error}</span>}
 </div>;
}
