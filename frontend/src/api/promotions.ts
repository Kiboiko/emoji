import { apiClient } from './client';
export interface PromotionConfig {price_nano:string;price_ton:string;duration_hours:number;network:string;}
export interface PromotionInvoice {id:string;product_id:string;status:string;paid:boolean;promoted_until:string|null;credited_nano:string;credit_reason:string|null;payment:{address:string;amount_nano:string;comment:string;valid_until:number;network:string}|null;}
let config:Promise<PromotionConfig>|null=null;
export const promotionsApi = {
 config:()=>config??(config=apiClient.get<PromotionConfig>('/promotions/config').then(r=>r.data).catch(e=>{config=null;throw e;})),
 create:async(productId:string)=>(await apiClient.post<PromotionInvoice>(`/promotions/products/${productId}/invoice`)).data,
 check:async(id:string)=>(await apiClient.get<PromotionInvoice>(`/promotions/${id}/check`)).data,
};
