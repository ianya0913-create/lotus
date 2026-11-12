// vite.config.js
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath, URL } from 'node:url'

// 後端位置：本地替代後端（python server.py，預設 port 5050）
// 不連老師的伺服器，所以老師的伺服器掛掉也不影響。
const API = 'http://localhost:5050'

export default defineConfig({
  base: '/lotus-bf/',
  plugins: [react()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    }
  },
  server: {
    host: '0.0.0.0',
    port: 3000,
    proxy: {
      '/terms': API,
      '/query': API,
      '/help': API
    }
  }
})
