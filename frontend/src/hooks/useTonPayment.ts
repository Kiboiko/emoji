import { useCallback, useRef, useState } from 'react';
import { useTonConnectUI } from '@tonconnect/ui-react';
import { beginCell } from '@ton/core';
import { ordersApi, paymentsApi } from '@/api/client';

export interface TonPaymentRequest {
    address: string;
    amount_nano: string;
    amount_ton: string;
    comment: string;
    valid_until: number;
    network: string;
    rate_usd_per_ton: string;
    usd_amount: string;
}

export type PaymentPhase =
    | 'idle'
    | 'creating'      // создаём заказ и счёт
    | 'awaiting_sign' // ждём подпись в кошельке
    | 'confirming'    // транзакция ушла, ждём подтверждения сети
    | 'paid'
    | 'failed';

/**
 * Комментарий платежа в виде ячейки для TON Connect.
 *
 * Формат простого текстового перевода: 32 нулевых бита (опкод) + текст.
 * Именно по этому комментарию бэкенд находит нашу транзакцию среди всех
 * входящих на кошелёк платформы, поэтому менять его нельзя.
 */
function buildCommentPayload(comment: string): string {
    return beginCell()
        .storeUint(0, 32)
        .storeStringTail(comment)
        .endCell()
        .toBoc()
        .toString('base64');
}

export function useTonPayment() {
    const [tonConnectUI] = useTonConnectUI();
    const [phase, setPhase] = useState<PaymentPhase>('idle');
    const [orderId, setOrderId] = useState<string | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [request, setRequest] = useState<TonPaymentRequest | null>(null);
    const pollTimer = useRef<ReturnType<typeof setInterval> | null>(null);
    // TonConnect отдаёт функцию, которая открывает кошелёк заново на тот же
    // запрос. Нужна, когда кошелёк открылся не до конца или его закрыли:
    // повторная отправка создала бы второй запрос на подпись.
    const reopenRef = useRef<(() => void) | null>(null);

    const stopPolling = useCallback(() => {
        if (pollTimer.current) {
            clearInterval(pollTimer.current);
            pollTimer.current = null;
        }
    }, []);

    /**
     * Опрос статуса заказа.
     *
     * Факт оплаты определяет бэкенд по блокчейну. Фронт только спрашивает
     * «уже?» и никогда не сообщает серверу, что оплата прошла: иначе оплату
     * можно было бы подделать одним запросом из консоли браузера.
     */
    const pollUntilPaid = useCallback(
        (orderId: string, onPaid: () => void) => {
            stopPolling();
            const startedAt = Date.now();
            const timeoutMs = 15 * 60 * 1000;

            pollTimer.current = setInterval(async () => {
                try {
                    const status = await paymentsApi.checkPaymentStatus(orderId);
                    if (status.paid) {
                        stopPolling();
                        setPhase('paid');
                        onPaid();
                        return;
                    }
                    if (status.status === 'underpaid') {
                        stopPolling();
                        setPhase('failed');
                        setError('Пришла сумма меньше ожидаемой. Свяжитесь с поддержкой.');
                        return;
                    }
                    if (status.status === 'expired') {
                        stopPolling();
                        setPhase('failed');
                        setError('Время оплаты истекло. Оформите заказ заново.');
                        return;
                    }
                } catch {
                    // Недоступность бэкенда или индексера — не повод считать
                    // заказ неоплаченным. Просто пробуем в следующий раз.
                }

                if (Date.now() - startedAt > timeoutMs) {
                    stopPolling();
                    setPhase('failed');
                    setError('Не дождались подтверждения. Проверьте статус заказа в профиле.');
                }
            }, 5000);
        },
        [stopPolling],
    );

    const pay = useCallback(
        async (currency: 'USDT' | 'TON', acceptTerms: boolean, onPaid: () => void) => {
            setError(null);
            setPhase('creating');
            let signing = false;

            try {
                // Повторное нажатие не плодит заказы: сервер вернёт тот же
                // неоплаченный заказ с тем же переводом, если корзина не менялась
                const created = await ordersApi.createOrder(currency, acceptTerms);
                const orderId: string = created.order_id;
                const payment: TonPaymentRequest = created.payment;
                setRequest(payment);
                // Запоминаем: заказ уже создан и держит товар в резерве. Если
                // оплата не состоится, пользователю нужна возможность снять его
                // самому, не дожидаясь планировщика.
                setOrderId(orderId);

                setPhase('awaiting_sign');
                signing = true;
                await tonConnectUI.sendTransaction(
                    {
                        validUntil: payment.valid_until,
                        messages: [
                            {
                                address: payment.address,
                                amount: payment.amount_nano,
                                payload: buildCommentPayload(payment.comment),
                            },
                        ],
                    },
                    {
                        onRequestSent: (redirectToWallet) => {
                            reopenRef.current = redirectToWallet;
                        },
                    },
                );

                // Кошелёк вернул подписанный BOC — это значит лишь, что
                // пользователь подписал. Дошла ли транзакция и на ту ли сумму,
                // знает только блокчейн, поэтому дальше ждём проверки бэкендом.
                setPhase('confirming');
                pollUntilPaid(orderId, onPaid);
            } catch (e: any) {
                if (!signing) {
                    // Бэкенд отдаёт detail объектом для машиночитаемых ошибок
                    // (например terms_required) — показывать [object Object]
                    // пользователю нельзя
                    const detail = e?.response?.data?.detail;
                    setPhase('failed');
                    setError(
                        (typeof detail === 'string' ? detail : detail?.message) ??
                            'Не удалось создать платёж. Проверьте связь и попробуйте ещё раз.',
                    );
                    return;
                }

                // Закрытое окно TonConnect приходит не отказом, а ошибкой
                // «Transaction was not sent» — по-английски и красным. Для
                // человека это одно и то же: он передумал или закрыл кошелёк.
                const rejected =
                    e?.name === 'UserRejectsError' ||
                    /reject|cancel|decline|not sent/i.test(e?.message ?? '');

                setPhase(rejected ? 'idle' : 'failed');
                if (!rejected) {
                    setError(
                        'Кошелёк не ответил. Нажмите «Оплатить» ещё раз — откроется тот же заказ, дважды платить не придётся.',
                    );
                }
            } finally {
                reopenRef.current = null;
            }
        },
        [tonConnectUI, pollUntilPaid],
    );

    /**
     * Открывает кошелёк заново на тот же запрос подписи.
     *
     * Кошелёк Telegram иногда открывается не до конца. Без этой кнопки
     * оставалось закрыть окно TonConnect и начинать оплату заново.
     */
    const reopenWallet = useCallback(() => {
        reopenRef.current?.();
    }, []);

    /**
     * Снимает созданный, но не оплаченный заказ и освобождает товар.
     *
     * Нужна, когда оплата не состоялась: кошелёк отклонил, не хватило
     * средств, человек передумал. Без неё товар остаётся зарезервированным
     * до прогона планировщика — для вещи в единственном экземпляре это значит,
     * что она пропадает с витрины у всех.
     */
    const cancel = useCallback(async () => {
        if (!orderId) return false;

        stopPolling();
        try {
            await ordersApi.cancelOrder(orderId);
            setOrderId(null);
            setRequest(null);
            setError(null);
            setPhase('idle');
            return true;
        } catch (e: any) {
            const detail = e?.response?.data?.detail;
            setError(
                (typeof detail === 'string' ? detail : detail?.message) ??
                    'Не удалось отменить заказ',
            );
            return false;
        }
    }, [orderId, stopPolling]);

    return {
        pay,
        cancel,
        reopenWallet,
        phase,
        error,
        request,
        orderId,
        isConnected: tonConnectUI.connected,
        stopPolling,
    };
}
