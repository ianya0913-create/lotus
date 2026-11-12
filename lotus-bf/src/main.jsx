// src/main.jsx
import React from 'react'
import { createRoot } from 'react-dom/client'
import App from './App.jsx'
//import './index.css' // 沒有這檔可刪掉這行

function ErrorBoundary({ children }) {
  const [err, setErr] = React.useState(null)
  React.useEffect(() => {
    const handler = (e) => setErr(e?.error || e?.reason || e)
    window.addEventListener('error', handler)
    window.addEventListener('unhandledrejection', handler)
    return () => {
      window.removeEventListener('error', handler)
      window.removeEventListener('unhandledrejection', handler)
    }
  }, [])
  if (err) {
    return (
      <div style="padding:16px; font-family: ui-sans-serif">
        <h2>🚨 執行期錯誤</h2>
        <pre style="white-space:pre-wrap; background:#f5f5f5; padding:12px; border-radius:8px;">
{String(err?.stack || err?.message || err)}
        </pre>
      </div>
    )
  }
  return children
}

console.log('[main] booting...') // smoke test：打開 DevTools 會看到

createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </React.StrictMode>
)

