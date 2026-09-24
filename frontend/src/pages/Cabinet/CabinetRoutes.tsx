import React from 'react';
import { useAuthStore } from '@/store/authStore';
import { SellerCabinet } from '@/components/SellerCabinet/SellerCabinet';
import { ChannelCabinet } from '@/components/ChannelCabinet/ChannelCabinet';
import { MyDeals } from '@/components/MyDeals/MyDeals';
import { MyOrders } from '@/components/MyOrders/MyOrders';
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

export const MyOrdersPage: React.FC = () => {
    const t = useT();
    return (
        <CabinetPage title={t('Мои заказы', 'My orders')}>
            <MyOrders />
        </CabinetPage>
    );
};

export const MyDealsPage: React.FC = () => {
    const t = useT();
    return (
        <CabinetPage title={t('Мои сделки', 'My deals')}>
            <MyDeals />
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
