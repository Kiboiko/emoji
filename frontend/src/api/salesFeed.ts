import { apiClient } from './client';
export interface Sale { id:string; product_id:string|null; name:string; image_url:string|null; quantity:number; total_usd:string; store_name:string|null; store_slug:string|null; completed_at:string; }
export const salesFeedApi = { get: async (params: {category_id?:string; skip:number; limit:number; lang:string}) => (await apiClient.get<{items:Sale[];has_more:boolean}>('/sales-feed', {params})).data };
