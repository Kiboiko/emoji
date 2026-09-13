import React from 'react'
import ReactDOM from 'react-dom/client'
import { TonConnectUIProvider } from '@tonconnect/ui-react'
import { App } from './App'
import './index.css'

// Манифест должен раздаваться по тому же origin, что и приложение, иначе
// кошельки его не примут. Файл лежит в public/ и попадает в корень сборки.
const MANIFEST_URL = `${window.location.origin}/tonconnect-manifest.json`

// Внутри Telegram Mini App кошелёк открывается в отдельном приложении.
// Без returnStrategy пользователь после подписи остаётся в кошельке и не
// видит, что заказ оплачен.
const BOT_USERNAME = import.meta.env.VITE_BOT_USERNAME

ReactDOM.createRoot(document.getElementById('root')!).render(
    <React.StrictMode>
        <TonConnectUIProvider
            manifestUrl={MANIFEST_URL}
            actionsConfiguration={{
                twaReturnUrl: BOT_USERNAME
                    ? `https://t.me/${BOT_USERNAME}`
                    : undefined,
            }}
        >
            <App />
        </TonConnectUIProvider>
    </React.StrictMode>,
)
