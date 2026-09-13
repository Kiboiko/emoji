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
    const [error, setError] = useState<string | null>(null);
    const [request, setRequest] = useState<TonPaymentRequest | null>(null);
    const pollTimer = useRef<ReturnType<typeof setInterval> | null>(null);

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
        async (currency: 'USDT' | 'TON', onPaid: () => void) => {
            setError(null);
            setPhase('creating');

            try {
                const created = await ordersApi.createOrder(currency);
                const orderId: string = created.order_id;
                const payment: TonPaymentRequest = created.payment;
                setRequest(payment);

                setPhase('awaiting_sign');
                await tonConnectUI.sendTransaction({
                    validUntil: payment.valid_until,
                    messages: [
                        {
                            address: payment.address,
                            amount: payment.amount_nano,
                            payload: buildCommentPayload(payment.comment),
                        },
                    ],
                });

                // Кошелёк вернул подписанный BOC — это значит лишь, что
                // пользователь подписал. Дошла ли транзакция и на ту ли сумму,
                // знает только блокчейн, поэтому дальше ждём проверки бэкендом.
                setPhase('confirming');
                pollUntilPaid(orderId, onPaid);
            } catch (e: any) {
                const rejected =
                    e?.name === 'UserRejectsError' ||
                    /reject|cancel|decline/i.test(e?.message ?? '');

                setPhase(rejected ? 'idle' : 'failed');
                if (!rejected) {
                    setError(
                        e?.response?.data?.detail ??
                            e?.message ??
                            'Не удалось создать платёж',
                    );
                }
            }
        },
        [tonConnectUI, pollUntilPaid],
    );

    return {
        pay,
        phase,
        error,
        request,
        isConnected: tonConnectUI.connected,
        stopPolling,
    };
}
