import React, { useEffect, useRef, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { TonConnectButton, useTonAddress, useTonConnectUI, useTonWallet } from '@tonconnect/ui-react';
import { AlertTriangle, Check, Wallet } from 'lucide-react';
import { paymentsApi } from '@/api/client';
import { useAuthStore } from '@/store/authStore';
import { useToastStore } from '@/store/toastStore';
import { useTelegram } from '@/hooks/useTelegram';
import './PaymentWallet.css';

/**
 * Идентификаторы сетей в TON Connect.
 *
 * Приходят строками в wallet.account.chain. Держим их здесь, а не сверяем с
 * CHAIN из библиотеки: значение всё равно надо сопоставить с ответом
 * /payments/config, который отдаёт человеческое «testnet»/«mainnet».
 */
const CHAIN_MAINNET = '-239';
const CHAIN_TESTNET = '-3';

/**
 * Кошелёк для оплаты.
 *
 * Раньше подключался прямо в оформлении заказа: человек доходил до оплаты и
 * упирался в ещё один шаг с переключением в другое приложение. Теперь
 * подключается заранее и одним местом — TON Connect держит сессию сам, так
 * что к оплате кошелёк уже на месте.
 *
 * Здесь же проверяется сеть. Прод работает в testnet, и кошелёк из основной
 * сети подпишет транзакцию, которая никуда не дойдёт — без этой проверки
 * человек узнал бы об этом только по пропавшим деньгам.
 */
export const PaymentWallet: React.FC = () => {
    const { language } = useAuthStore();
    const { haptic } = useTelegram();
    const showToast = useToastStore((s) => s.show);
    const wallet = useTonWallet();
    // Именно useTonAddress, а не wallet.account.address: второй отдаёт сырой
    // формат 0:abc…, который человек нигде больше не видит и не узнаёт.
    // Здесь нужен тот же вид UQ…, что показывает кошелёк.
    const friendlyAddress = useTonAddress();
    const [tonConnectUI] = useTonConnectUI();
    const [network, setNetwork] = useState<string | null>(null);
    const { hash } = useLocation();
    const box = useRef<HTMLElement | null>(null);
    const [highlight, setHighlight] = useState(false);

    const t = (ru: string, en: string) => (language === 'ru' ? ru : en);

    useEffect(() => {
        // Сеть площадки спрашиваем один раз: она не меняется в рамках сессии
        paymentsApi.getConfig()
            .then((config) => setNetwork(config.network ?? null))
            .catch(() => setNetwork(null));
    }, []);

    // Приход из оформления заказа по якорю. Браузерный переход по id
    // здесь не срабатывает: блок появляется после отрисовки маршрута, когда
    // адресная строка уже отработана.
    useEffect(() => {
        if (hash !== '#wallet' || !box.current) return;

        box.current.scrollIntoView({ behavior: 'smooth', block: 'center' });
        setHighlight(true);
        const timer = setTimeout(() => setHighlight(false), 1800);
        return () => clearTimeout(timer);
    }, [hash]);

    const address = friendlyAddress || null;
    const chain = wallet?.account?.chain ?? null;
    const walletName = wallet && 'name' in wallet ? (wallet as { name?: string }).name : undefined;

    // Несовпадение считаем только когда знаем обе стороны: пока конфиг не
    // пришёл, пугать сообщением не за что
    const mismatch =
        network !== null && chain !== null
            ? (network === 'testnet' && chain === CHAIN_MAINNET) ||
              (network === 'mainnet' && chain === CHAIN_TESTNET)
            : false;

    const showChain = chain !== null && (chain === CHAIN_TESTNET || mismatch);

    const disconnect = async () => {
        try {
            await tonConnectUI.disconnect();
            haptic.impact('light');
            showToast(t('Кошелёк отключён', 'Wallet disconnected'), 'info');
        } catch {
            showToast(t('Не удалось отключить', 'Failed to disconnect'), 'error');
        }
    };

    return (
        <section
            className={`paywallet glass-card${highlight ? ' highlight' : ''}`}
            id="wallet"
            ref={box}
        >
            <div className="paywallet-head">
                <span className="paywallet-title">
                    <Wallet size={18} />
                    {t('Кошелёк для оплаты', 'Payment wallet')}
                </span>

                {address && !mismatch && (
                    <span className="paywallet-pill">
                        <Check size={12} />
                        {t('подключён', 'connected')}
                    </span>
                )}
            </div>

            {address ? (
                <>
                    {/* Адрес отдельной строкой с «Копировать» не показываем:
                        его и так видно на кнопке ниже, а скопировать можно из
                        её меню. Пометка сети — только когда она что-то
                        значит: тестовая или не та, что у площадки */}
                    {(walletName || showChain) && (
                        <div className="paywallet-meta">
                            {walletName && <span>{walletName}</span>}
                            {showChain && (
                                <span className={mismatch ? 'paywallet-chain bad' : 'paywallet-chain'}>
                                    {chain === CHAIN_TESTNET ? 'testnet' : 'mainnet'}
                                </span>
                            )}
                        </div>
                    )}

                    {mismatch && (
                        <div className="paywallet-warn">
                            <AlertTriangle size={15} />
                            <span>
                                {t(
                                    `Площадка принимает оплату в сети ${network}, а кошелёк подключён к другой. Платёж не дойдёт — переключите сеть в кошельке и подключите заново.`,
                                    `The marketplace accepts payments on ${network}, but this wallet is on a different network. The payment will not arrive — switch networks in your wallet and reconnect.`,
                                )}
                            </span>
                        </div>
                    )}

                    <div className="paywallet-actions">
                        {/* Родная кнопка умеет и сменить кошелёк, и показать
                            меню — свою рисовать незачем */}
                        <TonConnectButton />
                        <button className="paywallet-disconnect" onClick={disconnect}>
                            {t('Отключить', 'Disconnect')}
                        </button>
                    </div>
                </>
            ) : (
                <>
                    <p className="paywallet-empty">
                        {t(
                            'Подключите кошелёк один раз — при оплате он подставится сам, и лишнего шага в корзине не будет.',
                            'Connect your wallet once — it will be used automatically at checkout, with no extra step in the cart.',
                        )}
                    </p>

                    {network === 'testnet' && (
                        <div className="paywallet-warn">
                            <AlertTriangle size={15} />
                            <span>
                                {t(
                                    'Площадка сейчас работает в тестовой сети — подключайте кошелёк, переключённый на testnet.',
                                    'The marketplace is currently on the test network — connect a wallet switched to testnet.',
                                )}
                            </span>
                        </div>
                    )}

                    <div className="paywallet-actions">
                        <TonConnectButton />
                    </div>
                </>
            )}
        </section>
    );
};
