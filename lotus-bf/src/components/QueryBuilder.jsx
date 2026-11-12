import { useRef } from 'react'

export function QueryBuilder({ query, setQuery }) {
  const inputRef = useRef(null)   // 抓到 <input> 元素，才能讀寫游標位置

  // 在游標位置插入 token（取代原本「一律加在最後面」的 append）
  const insertAtCursor = (token) => {
    const el = inputRef.current
    const value = query || ''
    // selectionStart / selectionEnd：游標（或反白選取範圍）的起點與終點
    const start = el?.selectionStart ?? value.length
    const end = el?.selectionEnd ?? value.length
    const before = value.slice(0, start)   // 游標前面的文字
    const after = value.slice(end)         // 游標後面的文字（有反白的話，反白部分會被取代）

    // 前後自動補空格，避免黏成 "fearAND"
    const spaceBefore = before && !/\s$/.test(before) ? ' ' : ''
    const spaceAfter = /^\s/.test(after) ? '' : ' '

    setQuery(before + spaceBefore + token + spaceAfter + after)

    // React 重新渲染後游標會跳到最後，所以等畫面更新完再把游標放回插入點後面
    const caret = before.length + spaceBefore.length + token.length + 1
    requestAnimationFrame(() => {
      el?.focus()
      el?.setSelectionRange(caret, caret)
    })
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      setQuery(e.currentTarget.value);
    }
  };

  return (
    <div className="flex flex-col gap-3 qb">
      {/* Header */}
      <div className="flex items-center">
        <div className="card__title">Query Builder</div>
      </div>

      {/* Input */}
      <input
        ref={inputRef}
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="Create a query here, e.g.: [-22,-4,18] NOT emotion"
        className="qb__input w-full rounded-xl border px-3 py-2 focus:outline-none focus:ring"
        style={{ width: "100%" }}
      />

      {/* Operators + Reset (single row) */}
      <div className="flex gap-2 flex-nowrap overflow-x-auto">
        {[
          { label: 'AND', onClick: () => insertAtCursor('AND') },
          { label: 'OR', onClick: () => insertAtCursor('OR') },
          { label: 'NOT', onClick: () => insertAtCursor('NOT') },
          { label: '(', onClick: () => insertAtCursor('(') },
          { label: ')', onClick: () => insertAtCursor(')') },
          { label: 'Reset', onClick: () => { setQuery(''); inputRef.current?.focus() } },
        ].map((b) => (
          <button
            key={b.label}
            // 按下按鈕時不要讓輸入框失去焦點，游標位置才不會跑掉
            onMouseDown={(e) => e.preventDefault()}
            onClick={b.onClick}
            className="rounded-xl border px-3 py-2 text-sm hover:bg-gray-50"
          >
            {b.label}
          </button>
        ))}
      </div>
    </div>
  );
}
