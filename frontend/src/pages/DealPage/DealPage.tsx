import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom';
import {
    AlertTriangle, ArrowLeft, BadgeCheck, ChevronRight, MessageCircle, Package, ShieldCheck, Star,
} from 'lucide-react';
import { p2pApi } from '@/api/client';
import { useAuthStore } from '@/store/authStore';
import { useDealsStore } from '@/store/dealsStore';
import { useToastStore, errorText } from '@/store/toastStore';
import { useTelegram } from '@/hooks/useTelegram';
import { useBarHeight } from '@/hooks/useBarHeight';
import { formatTon } from '@/lib/ton';
import { GramIcon, withGram } from '@/components/Gram/Gram';
import type { Deal } from '@/types';
import { DealReview } from '@/components/DealChat/DealReview';
import { DealSheet, type SheetKind } from '@/components/DealChat/DealSheet';
import {
    commissionPercent, counterpartName, dealSteps, fmtDateTime, isFinished, statusLabel, statusTone,
} from '@/components/DealChat/dealFormat';
import './DealPage.css';

/**
 * Страница сделки: что купили или продали, на каком она этапе и что делать.
 *
 * Открывается из «Мои сделки». Переписка — отдельным экраном по кнопке
 * «Чат»: здесь товар и действия, там разговор. Действия те же, что в
 * карточке над перепиской, и через те же шторки — решают судьбу денег.
 */
export const DealPage: React.FC = () => {
    const { dealId = '' } = useParams();
    const navigate = useNavigate();
    const location = useLocation();
    const { language, accessToken } = useAuthStore();
    const { haptic } = useTelegram();
    const showToast = useToastStore((s) => s.show);
    const unread = useDealsStore((s) => s.unread[dealId] ?? 0);
    const t = useCallback((ru: string, en: string) => (language === 'ru' ? ru : en), [language]);

    const [deal, setDeal] = useState<Deal | null>(null);
    const [failed, setFailed] = useState<string | null>(null);
    const [sheet, setSheet] = useState<SheetKind | null>(null);
    const [busy, setBusy] = useState(false);
    const [photo, setPhoto] = useState(0);
    const gallery = useRef<HTMLDivElement>(null);
    const [barRef, barStyle] = useBarHeight();

    const load = useCallback(async () => {
        try {
            setDeal(await p2pApi.getDeal(dealId));
            setFailed(null);
        } catch (e: any) {
            setFailed(e?.response?.status === 404
                ? t('Сделка не найдена', 'Deal not found')
                : errorText(e, t('Не удалось загрузить сделку', 'Failed to load the deal')));
        }
    }, [dealId, t]);

    useEffect(() => {
        if (accessToken) load();
    }, [accessToken, load]);

    const goBack = () => (location.key !== 'default' ? navigate(-1) : navigate('/my/deals'));

    const act = async (action: () => Promise<Deal>, success?: string) => {
        setBusy(true);
        try {
            await action();
            setSheet(null);
            haptic.notification('success');
            if (success) showToast(success, 'success');
            await load();
        } catch (e) {
            haptic.notification('error');
            showToast(errorText(e, t('Не получилось', 'Something went wrong')), 'error');
        } finally {
            setBusy(false);
        }
    };

    if (failed && !deal) {
        return (
            <div className="dpage">
                <div className="container dpage-body">
                    <button className="btn-back" onClick={goBack}>
                        <ArrowLeft size={20} />
                        <span>{t('Мои сделки', 'My deals')}</span>
                    </button>
                    <p className="dpage-muted">{failed}</p>
                </div>
            </div>
        );
    }

    if (!deal) {
        return (
            <div className="dpage">
                <div className="container dpage-body">
                    <div className="skeleton dpage-skeleton-photo" />
                    <div className="skeleton dpage-skeleton-line" />
                </div>
            </div>
        );
    }

    const buyer = deal.role === 'buyer';
    const finished = isFinished(deal);
    const details = deal.details;
    const images = details?.images?.length ? details.images : (deal.product_image ? [deal.product_image] : []);
    const name = (language === 'en' && details?.name_en) || deal.product_name;
    const description = (language === 'en' && details?.description_en) || details?.description;
    const { steps, current } = dealSteps(deal, language, t);
    const refunded = deal.status === 'refunded';

    const onGalleryScroll = () => {
        const box = gallery.current;
        if (box) setPhoto(Math.round(box.scrollLeft / box.clientWidth));
    };

    const note = deal.status === 'disputed'
        ? t('Деньги заморожены, пока модератор разбирает спор. Он видит всю переписку.', 'The money is frozen while a moderator reviews the dispute.')
        : refunded
            ? t('Сделка закрыта возвратом: деньги вернулись покупателю.', 'Closed with a refund: the money went back to the buyer.')
            : finished
                ? (buyer
                    ? t('Сделка завершена, деньги переведены продавцу.', 'The deal is complete, the seller has been paid.')
                    // Без суммы: она подписана в блоке «Начислено» выше
                    : t('Деньги начислены на ваш баланс. Вывести их можно в профиле.', 'The money is on your balance. Withdraw it in your profile.'))
                : (buyer
                    ? t('Деньги у площадки. Продавец получит их, когда вы подтвердите получение.', 'The platform holds the money until you confirm receipt.')
                    : t('Деньги у площадки. Вы получите их, когда покупатель подтвердит получение.', 'The platform holds the money until the buyer confirms receipt.'));

    // Главное действие — то, чего сделка ждёт от этого человека
    let primary: React.ReactNode = null;
    if (!finished && deal.status !== 'disputed') {
        if (buyer) {
            primary = (
                <button type="button" className="dchat-btn primary" onClick={() => setSheet('confirm')} disabled={busy}>
                    {t('Товар получен', 'Item received')}
                </button>
            );
        } else if (deal.status !== 'delivered_claimed') {
            primary = (
                <button
                    type="button"
                    className="dchat-btn primary"
                    disabled={busy}
                    onClick={() => act(() => p2pApi.markDelivered(dealId), t('Отправка отмечена', 'Marked as sent'))}
                >
                    {t('Я отправил товар', 'I have sent it')}
                </button>
            );
        }
    }

    const percent = commissionPercent(deal);

    return (
        <div className="dpage" style={barStyle}>
            <div className="container dpage-body with-bar">
                <div className="dpage-top">
                    <button className="btn-back" onClick={goBack}>
                        <ArrowLeft size={20} />
                        <span>{t('Мои сделки', 'My deals')}</span>
                    </button>
                    <span className="dpage-number">{t(`Сделка №${deal.number}`, `Deal #${deal.number}`)}</span>
                </div>

                {images.length > 0 ? (
                    <div className="dpage-gallery">
                        <div className="dpage-photos" ref={gallery} onScroll={onGalleryScroll}>
                            {images.map((url, index) => (
                                <img key={`${url}-${index}`} src={url} alt="" loading={index ? 'lazy' : undefined} />
                            ))}
                        </div>
                        {images.length > 1 && (
                            <div className="dpage-dots" aria-hidden="true">
                                {images.map((url, index) => (
                                    <span key={`${url}-${index}`} className={index === photo ? 'on' : ''} />
                                ))}
                            </div>
                        )}
                    </div>
                ) : (
                    <div className="dpage-nophoto"><Package size={36} /></div>
                )}

                <div className="dpage-title">
                    <div className="dpage-chips">
                        <span className="dchat-chip open">{buyer ? t('Покупка', 'Purchase') : t('Продажа', 'Sale')}</span>
                        <span className={`dchat-chip ${statusTone(deal.status)}`}>{statusLabel(deal.status, t)}</span>
                    </div>
                    <h1>{name}</h1>
                    {/* Крупная цена — только покупателю: это цена покупки. У
                        продавца число без подписи читалось как вторая цена
                        рядом с «Ценой товара» — его сумма подписана в блоках */}
                    {buyer && (
                        <div className={`dpage-price${refunded ? ' struck' : ''}`}>
                            {formatTon(deal.amount_ton)} <GramIcon title="Gram" />
                        </div>
                    )}
                </div>

                {/* Сразу под ценой, а не в конце страницы: внизу блоки уходили
                    под панель действий и из-под неё торчали пустыми краями.
                    Здесь они видны без прокрутки. Продавцу — цепочка «цена −
                    комиссия = ваша сумма»; покупателю — когда оплатил и сколько */}
                <div className="dpage-facts">
                    {buyer ? (
                        <>
                            <div>
                                <span>{t('Оплачено', 'Paid')}</span>
                                <strong>{fmtDateTime(deal.paid_at, language)}</strong>
                            </div>
                            <div>
                                <span>{t('Количество', 'Quantity')}</span>
                                <strong>{details?.quantity ?? 1} {t('шт.', 'pcs')}</strong>
                            </div>
                        </>
                    ) : (
                        <>
                            <div>
                                <span>{t('Цена товара', 'Item price')}</span>
                                <strong>{formatTon(deal.amount_ton)} <GramIcon title="Gram" /></strong>
                            </div>
                            <div>
                                <span>{t(`Комиссия ${percent}%`, `Fee ${percent}%`)}</span>
                                <strong>{formatTon(deal.commission_ton)} <GramIcon title="Gram" /></strong>
                            </div>
                            <div className={`dpage-fact-total${refunded ? ' struck' : ''}`}>
                                <span>
                                    {finished && !refunded
                                        ? t('Начислено на баланс', 'Added to your balance')
                                        : t('Вы получите', 'You get')}
                                </span>
                                <strong>{formatTon(deal.seller_amount_ton)} <GramIcon title="Gram" /></strong>
                            </div>
                        </>
                    )}
                </div>

                {buyer && details?.store && (
                    <Link className="dpage-store" to={`/store/seller/${details.store.id}`}>
                        <span className="dpage-store-ava">
                            {deal.store?.avatar_url
                                ? <img src={deal.store.avatar_url} alt="" />
                                : counterpartName(deal, t).trim().charAt(0).toUpperCase()}
                        </span>
                        <span className="dpage-store-text">
                            <span className="dpage-store-name">
                                {counterpartName(deal, t)}
                                {deal.store?.verified && <BadgeCheck size={15} />}
                            </span>
                            <span className="dpage-store-meta">
                                {t('Продавец', 'Seller')}
                                {details.store.rating != null && (
                                    <> · <Star size={12} fill="currentColor" /> {details.store.rating.toFixed(1)}</>
                                )}
                                {' · '}
                                {t(`${details.store.deals_completed} сделок`, `${details.store.deals_completed} deals`)}
                            </span>
                        </span>
                        <ChevronRight size={18} />
                    </Link>
                )}

                <div className="dpage-steps-card">
                    <div className="dchat-steps">
                        {steps.map(({ title, when, done }, index) => (
                            <span
                                key={title}
                                className={`dchat-step${done ? ' done' : ''}${index === current ? ' current' : ''}`}
                            >
                                <i />
                                {title}
                                <small>{when}</small>
                            </span>
                        ))}
                    </div>
                    <div className="dpage-note">
                        {deal.status === 'disputed' ? <AlertTriangle size={16} /> : <ShieldCheck size={16} />}
                        <span>{withGram(note)}</span>
                    </div>
                </div>

                {description && (
                    <section className="dpage-section">
                        <h2>{t('Описание', 'Description')}</h2>
                        <p>{description}</p>
                    </section>
                )}

                {buyer && deal.status === 'released' && (
                    <DealReview deal={deal} t={t} onDone={load} />
                )}
            </div>

            <div className="dpage-bar" ref={barRef}>
                <div className={`dpage-bar-main${primary ? '' : ' single'}`}>
                    {!deal.chat_expired && (
                        <Link className="dpage-chat" to={`/my/deals/${deal.id}`}>
                            <MessageCircle size={18} />
                            {t('Чат', 'Chat')}
                            {unread > 0 && <span className="dpage-chat-count">{unread}</span>}
                        </Link>
                    )}
                    {primary}
                </div>
                {!finished && (
                    <div className="dpage-bar-links">
                        {!buyer && (
                            <button type="button" onClick={() => setSheet('refund')} disabled={busy}>
                                {t('Вернуть деньги', 'Refund')}
                            </button>
                        )}
                        {deal.status !== 'disputed' && (
                            <button type="button" className="danger" onClick={() => setSheet('dispute')} disabled={busy}>
                                {t('Сообщить о проблеме', 'Report a problem')}
                            </button>
                        )}
                    </div>
                )}
            </div>

            {sheet && (
                <div className="dsheet-layer">
                    <DealSheet
                        kind={sheet}
                        deal={deal}
                        t={t}
                        busy={busy}
                        onClose={() => setSheet(null)}
                        onConfirm={() => act(() => p2pApi.confirmReceipt(dealId))}
                        onRefund={() => act(
                            () => p2pApi.refund(dealId),
                            t('Деньги возвращены покупателю', 'The buyer has been refunded'),
                        )}
                        onDispute={(reason) => act(() => p2pApi.openDispute(dealId, reason))}
                    />
                </div>
            )}
        </div>
    );
};
