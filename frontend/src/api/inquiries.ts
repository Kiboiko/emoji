import { apiClient } from './client';

export type Inquiry = { id: string; name: string; role: 'buyer' | 'seller'; store_id: string; expires_at: string | null;
    avatar_url: string | null; my_avatar_url: string | null;
    paid: boolean; deal_id: string | null; unread: number; last_text: string | null; last_photo: boolean; last_activity_at: string };
export type InquiryPreview = Omit<Inquiry, 'id'> & { id: string | null };
export type InquiryMessage = { id: string; mine: boolean; text: string | null; photo_url: string | null; created_at: string };
export type InquiryPage = { chat: Inquiry; messages: InquiryMessage[]; has_more: boolean };

export const inquiriesApi = {
    prepare: async (store: string, kind: string) => (await apiClient.get<InquiryPreview>(`/inquiries/store/${store}`, { params: { kind } })).data,
    start: async (store: string, kind: string, text: string, file: File | null, nonce: string) => {
        const form = new FormData(); form.append('body', text); form.append('client_id', nonce);
        if (file) form.append('photo', file);
        return (await apiClient.post<{ chat: Inquiry; message: InquiryMessage }>(`/inquiries/store/${store}/messages`, form,
            { params: { kind }, headers: { 'Content-Type': undefined } })).data;
    },
    open: async (store: string, kind: string) => (await apiClient.post<Inquiry>(`/inquiries/store/${store}`, null, { params: { kind } })).data,
    list: async () => (await apiClient.get<Inquiry[]>('/inquiries')).data,
    detail: async (id: string, before?: string) => (await apiClient.get<InquiryPage>(`/inquiries/${id}`, { params: { before } })).data,
    read: async (id: string) => apiClient.post(`/inquiries/${id}/read`),
    send: async (id: string, text: string, file: File | null, nonce: string) => {
        const form = new FormData(); form.append('body', text); form.append('client_id', nonce);
        if (file) form.append('photo', file);
        return (await apiClient.post<InquiryMessage>(`/inquiries/${id}/messages`, form, { headers: { 'Content-Type': undefined } })).data;
    },
};
