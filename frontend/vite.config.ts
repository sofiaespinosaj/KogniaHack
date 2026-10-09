import { fileURLToPath, URL } from 'node:url'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const BACKEND = 'http://localhost:8000'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: {
    proxy: {
      '/api': BACKEND,
      '/health': BACKEND,
      '/profile': BACKEND,
      '/ws': { target: BACKEND.replace('http', 'ws'), ws: true },
    },
  },
})
