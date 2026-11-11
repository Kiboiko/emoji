import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ChatAvatar } from '@/components/ChatAvatar/ChatAvatar';
import { useInquiryStore } from '@/store/inquiryStore';
import { useAuthStore } from '@/store/authStore';
import '@/components/MyDeals/MyDeals.css';

export function InquiryList() {
    const { language, accessToken } = useAuthStore();
    const rows = useInquiryStore(state => state.rows);
    const [failed, setFailed] = useState(false);
    const navigate = useNavigate();
    const ru = language === 'ru';
    const load = () => useInquiryStore.getState().load().then(() => setFailed(false)).catch(() => setFailed(true));
    useEffect(() => { if (accessToken) void load(); }, [accessToken]);
    return <section className="inquiry-list">
        <h2>{ru ? 'Переписки с продавцами' : 'Seller conversations'}</h2>
        {failed && <p role="alert">{ru ? 'Не удалось загрузить переписки.' : 'Could not load conversations.'} <button type="button" onClick={() => void load()}>{ru ? 'Повторить' : 'Retry'}</button></p>}
        {!failed && !rows.length && <p className="mydeals-empty">{ru ? 'Задать вопрос до покупки можно кнопкой чата на странице продавца.' : 'To ask before buying, use the chat button on the seller’s page.'}</p>}
        <div className="mydeals">{rows.map(row => <button key={row.id} type="button" className="mydeals-row" onClick={() => navigate(`/chats/seller/${row.id}`)}>
            <ChatAvatar src={row.avatar_url} />
            <span className="mydeals-main"><strong>{row.name === 'Покупатель' && !ru ? 'Buyer' : row.name}</strong>
                <span className="mydeals-last">{row.last_text || (row.last_photo ? (ru ? 'Фото' : 'Photo') : (ru ? 'Задайте вопрос' : 'Ask a question'))}</span>
                <span className="mydeals-foot">{row.paid ? (ru ? 'После покупки' : 'After purchase') : (ru ? 'До покупки · 72 часа' : 'Before purchase · 72 hours')}</span>
            </span>{row.unread > 0 && <span className="inquiry-unread">{row.unread > 99 ? '99+' : row.unread}</span>}
        </button>)}</div>
    </section>;
}
