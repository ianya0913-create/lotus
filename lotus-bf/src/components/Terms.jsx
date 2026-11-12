import { useEffect, useMemo, useState } from 'react'

// 離線備援檔：放在 public/static/terms.json
// import.meta.env.BASE_URL 是 vite.config.js 裡的 base（'/lotus-bf/'）
const OFFLINE_TERMS_URL = `${import.meta.env.BASE_URL}static/terms.json`

export function Terms ({ onPickTerm }) {
  const [terms, setTerms] = useState([])
  const [search, setSearch] = useState('')
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')
  const [offline, setOffline] = useState(null)   // null = 線上；'sample' / 'cached' = 離線

  useEffect(() => {
    let alive = true
    const ac = new AbortController()
    const load = async () => {
      setLoading(true)
      setErr('')
      try {
        let data
        let usedOffline = false
        try {
          // ① 先試線上 API
          const res = await fetch('/terms', { signal: ac.signal })
          if (!res.ok) throw new Error(`HTTP ${res.status}`)
          data = await res.json()
        } catch (apiErr) {
          if (apiErr?.name === 'AbortError') throw apiErr   // 元件被移除造成的取消，不算失敗
          // ② API 失敗 → 改讀本地檔案 public/static/terms.json
          console.warn('[Terms] API 失敗，改用離線資料：', apiErr)
          const res2 = await fetch(OFFLINE_TERMS_URL, { signal: ac.signal })
          if (!res2.ok) throw new Error(`API 失敗（${apiErr?.message}），離線資料也讀不到（HTTP ${res2.status}）`)
          data = await res2.json()
          usedOffline = true
        }
        if (!alive) return
        setOffline(usedOffline ? (data?._sample ? 'sample' : 'cached') : null)
        setTerms(Array.isArray(data?.terms) ? data.terms : [])
      } catch (e) {
        if (!alive) return
        setErr(`Failed to fetch terms: ${e?.message || e}`)
      } finally {
        if (alive) setLoading(false)
      }
    }
    load()
    return () => { alive = false; ac.abort() }
  }, [])

  const filtered = useMemo(() => {
    const s = search.trim().toLowerCase()
    if (!s) return terms
    return terms.filter(t => t.toLowerCase().includes(s))
  }, [terms, search])

  // 目前展開的是哪個字母（null = 全部收起）
  const [openLetter, setOpenLetter] = useState(null)

  // 依字首字母分組：[['A', [...]], ['B', [...]], ..., ['#', [...]]]
  const groups = useMemo(() => {
    const map = new Map()                       // ≈ Python 的 dict
    for (const t of terms) {
      const c = (t[0] || '').toUpperCase()
      const key = /[A-Z]/.test(c) ? c : '#'     // 非英文字母開頭的歸到 '#'
      if (!map.has(key)) map.set(key, [])
      map.get(key).push(t)
    }
    return [...map.entries()].sort(([a], [b]) =>
      a === '#' ? 1 : b === '#' ? -1 : a.localeCompare(b))   // '#' 排最後
  }, [terms])

  // 單一詞彙的連結（兩種顯示模式共用）
  const renderTerm = (t) => (
    <a
      href="#"
      className='terms__name'
      title={t}
      aria-label={`Add term ${t}`}
      onClick={(e) => { e.preventDefault(); onPickTerm?.(t) }}
    >
      {t}
    </a>
  )

  return (
    <div className='terms'>
      {/* Removed internal <h2> to avoid double "Terms" header. The bold title now comes from App.jsx card__title. */}

      <div className='terms__controls'>
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder='Search terms…'
          className='input'
        />
        <button
          onClick={() => setSearch('')}
          className='btn btn--primary'
        >
          Clear
        </button>
      </div>

      {loading && (
        <div className='terms__skeleton'>
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className='terms__skeleton-row' />
          ))}
        </div>
      )}

      {offline && (
        <div className='terms__offline'>
          {offline === 'sample'
            ? '離線模式：伺服器連不上，目前使用「示範用」詞彙清單（不完整）'
            : '離線模式：伺服器連不上，目前使用本地儲存的詞彙清單'}
        </div>
      )}

      {err && (
        <div className='alert alert--error'>
          {err}
        </div>
      )}

      {!loading && !err && (
        <div className='terms__list'>
          {search.trim() ? (
            // ── 有輸入搜尋字：照舊顯示過濾後的清單 ──
            filtered.length === 0 ? (
              <div className='terms__empty'>No terms found</div>
            ) : (
              <ul className='terms__ul'>
                {filtered.slice(0, 500).map((t, idx) => (
                  <li key={`${t}-${idx}`} className='terms__li'>{renderTerm(t)}</li>
                ))}
              </ul>
            )
          ) : groups.length === 0 ? (
            // ── 沒有任何詞彙（API 回傳空的）：明確顯示出來，不要一片空白 ──
            <div className='terms__empty'>No terms loaded（API 沒有回傳任何詞彙）</div>
          ) : (
            // ── 搜尋框是空的：依字首字母分組，點選展開 ──
            <div className='terms__groups'>
              {groups.map(([letter, list]) => {
                const isOpen = openLetter === letter
                const toggle = () => setOpenLetter(isOpen ? null : letter)
                return (
                  <div key={letter} className='terms__group'>
                    <div
                      className={`terms__group-header${isOpen ? ' is-open' : ''}`}
                      tabIndex={0}
                      aria-expanded={isOpen}
                      onClick={toggle}
                      onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle() } }}
                    >
                      <span>{isOpen ? '▾' : '▸'} {letter}</span>
                      <span className='terms__group-count'>{list.length}</span>
                    </div>
                    {isOpen && (
                      <ul className='terms__ul terms__group-list'>
                        {list.map((t, idx) => (
                          <li key={`${t}-${idx}`} className='terms__li'>{renderTerm(t)}</li>
                        ))}
                      </ul>
                    )}
                  </div>
                )
              })}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

