import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  define: {
    // @ton/core рассчитан на Node и местами ссылается на голый `global`
    // (не только на Buffer — тот полифиллится отдельно в src/lib/polyfills.ts).
    // В браузере такой переменной нет, в Node это был бы globalThis.
    global: 'globalThis',
  },
  build: {
    rollupOptions: {
      output: {
        // Библиотеки — отдельными файлами. Всё в одном куске весило 1,3 МБ, и
        // любая правка кода приложения заставляла телефон заново качать и
        // React, и TonConnect. Теперь после выкатки скачивается только
        // собственный код (он мал), а библиотеки берутся из кеша: файлы с
        // хешем в имени кешируются на год (nginx/nginx.conf, /assets/).
        manualChunks(id: string) {
          if (!id.includes('node_modules')) return undefined
          if (id.includes('@tonconnect') || id.includes('@ton/') || id.includes('@tonconnect')) return 'ton'
          if (id.includes('framer-motion') || id.includes('/motion-')) return 'motion'
          if (id.includes('lucide-react')) return 'icons'
          if (/node_modules\/(react|react-dom|react-router|react-router-dom|scheduler)\//.test(id)) return 'react'
          return undefined
        },
      },
    },
  },
  server: {
    port: 3000,
    host: true,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/uploads': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      }
    }
  }
})
