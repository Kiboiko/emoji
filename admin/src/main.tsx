import './lib/polyfills'

import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { TonConnectUIProvider } from '@tonconnect/ui-react'
import './index.css'
import App from './App.tsx'

// Кошелёк площадки подключается в разделе «Выводы»: выплату подписывает
// админ в своём кошельке, ключа на сервере нет. Манифест общий с витриной —
// админка открыта на том же домене
const MANIFEST_URL = `${window.location.origin}/tonconnect-manifest.json`

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <TonConnectUIProvider manifestUrl={MANIFEST_URL}>
      <App />
    </TonConnectUIProvider>
  </StrictMode>,
)
