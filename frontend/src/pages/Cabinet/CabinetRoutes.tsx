import React from 'react';
import { useAuthStore } from '@/store/authStore';
import { SellerCabinet } from '@/components/SellerCabinet/SellerCabinet';
import { ChannelCabinet } from '@/components/ChannelCabinet/ChannelCabinet';
import { MyDeals } from '@/components/MyDeals/MyDeals';
import { Purchases } from '@/pages/Purchases/Purchases';
import { MySubscriptions } from '@/components/MySubscriptions/MySubscriptions';
import { CabinetPage } from './CabinetPage';

/**
 * Экраны разделов кабинета.
 *
 * Каждый — та же начинка, что раньше лежала внутри профиля, но во всю
 * высоту и без сворачивания. Жалоба была ровно на это: при десятке товаров
 * и подписок вложенные свёрнутые списки превращались в мелкую кашу.
 */

const useT = () => {
    const { language } = useAuthStore();
    return (ru: string, en: string) => (language === 'ru' ? ru : en);
};

export const MyListingsPage: React.FC = () => {
    const t = useT();
    return (
        <CabinetPage title={t('Мой магазин', 'My store')}>
            <SellerCabinet standalone />
        </CabinetPage>
    );
};

export const MyChannelsPage: React.FC = () => {
    const t = useT();
    return (
        <CabinetPage title={t('Мои каналы', 'My channels')}>
            <ChannelCabinet standalone />
        </CabinetPage>
    );
};

/** Мои сделки: все покупки и продажи, включая покупки у самой площадки */
export const MyDealsPage: React.FC = () => {
    const t = useT();
    return (
        <CabinetPage title={t('Мои сделки', 'My deals')}>
            <Purchases />
        </CabinetPage>
    );
};

/** Вкладка «Чаты» в нижнем меню — переписки по сделкам, без кнопки назад */
export const ChatsPage: React.FC = () => {
    const t = useT();
    return (
        <CabinetPage title={t('Чаты', 'Chats')} back={false}>
            <MyDeals mode="chats" />
        </CabinetPage>
    );
};

export const MySubscriptionsPage: React.FC = () => {
    const t = useT();
    return (
        <CabinetPage title={t('Мои подписки', 'My subscriptions')}>
            <MySubscriptions />
        </CabinetPage>
    );
};
