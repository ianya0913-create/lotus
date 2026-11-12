// vite.config.js
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath, URL } from 'node:url'

// ───────── 後端設定 ─────────
const REMOTE = 'http://hpc.psy.ntu.edu.tw:5000'   // 老師的伺服器（優先使用）
const LOCAL = 'http://localhost:5050'             // 本地替代後端（python server.py）
const REMOTE_TIMEOUT_MS = 4000                    // 老師的伺服器最多等 4 秒
const RETRY_REMOTE_AFTER_MS = 60_000              // 失敗後 60 秒內直接用本地，之後再試一次老師的

let remoteDownUntil = 0   // 在這個時間點之前，都當作老師的伺服器掛了

// 只有老師的伺服器連不上時，才改用本地後端
function lotusApiFallback () {
  return {
    name: 'lotus-api-fallback',
    configureServer (server) {
      const log = server.config.logger

      // 對某個後端發出請求，超過 timeout 就取消
      async function forward (base, url, timeout) {
        const ctrl = new AbortController()
        const timer = setTimeout(() => ctrl.abort(), timeout)
        try {
          return await fetch(base + url, { signal: ctrl.signal })
        } finally {
          clearTimeout(timer)
        }
      }

      server.middlewares.use(async (req, res, next) => {
        // 只處理 API 的請求，其他（網頁、JS、圖片）交給 Vite
        if (!/^\/(terms|query|help)(\/|\?|$)/.test(req.url)) return next()

        let upstream = null
        let used = ''

        // ① 先試老師的伺服器（除非剛剛才失敗過）
        if (Date.now() >= remoteDownUntil) {
          try {
            const r = await forward(REMOTE, req.url, REMOTE_TIMEOUT_MS)
            if (r.status >= 500) throw new Error(`HTTP ${r.status}`)   // 伺服器內部錯誤也算連不上
            upstream = r
            used = 'remote'
          } catch (e) {
            remoteDownUntil = Date.now() + RETRY_REMOTE_AFTER_MS
            const why = e.name === 'AbortError' ? `超過 ${REMOTE_TIMEOUT_MS / 1000} 秒沒回應` : e.message
            log.warn(`[lotus] 老師的伺服器連不上（${why}），改用本地後端 ${LOCAL}`, { timestamp: true })
          }
        }

        // ② 連不上 → 改用本地後端
        if (!upstream) {
          try {
            upstream = await forward(LOCAL, req.url, 30_000)
            used = 'local'
          } catch (e) {
            res.statusCode = 502
            res.setHeader('Content-Type', 'application/json; charset=utf-8')
            res.end(JSON.stringify({
              error: `老師的伺服器和本地後端都連不上（${e.message}）。本地後端有啟動嗎？（python server.py）`
            }))
            return
          }
        }

        // ③ 把結果原封不動交給瀏覽器
        res.statusCode = upstream.status
        for (const h of ['content-type', 'content-disposition']) {
          const v = upstream.headers.get(h)
          if (v) res.setHeader(h, v)
        }
        res.setHeader('X-Lotus-Backend', used)   // 前端可以讀這個 header，知道用的是哪個後端
        res.end(Buffer.from(await upstream.arrayBuffer()))
      })
    }
  }
}

export default defineConfig({
  base: '/lotus-bf/',

  plugins: [react(), lotusApiFallback()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    }
  },
  server: {
    allowedHosts: ['hpc.psy.ntu.edu.tw'],
    host: '0.0.0.0',
    port: 3000
    // 原本的 proxy 設定已經由上面的 lotusApiFallback 取代
  }
})
