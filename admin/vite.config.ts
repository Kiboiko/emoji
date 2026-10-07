import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  base: '/admin/',
  plugins: [
    react(),
    tailwindcss(),
  ],
  define: {
    // @ton/core рассчитан на Node и местами ссылается на голый `global`
    global: 'globalThis',
  },
})
