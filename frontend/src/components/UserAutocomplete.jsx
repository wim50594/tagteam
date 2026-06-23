import { useState, useRef, useEffect } from 'react'

/**
 * Tag-style multi-select with autocomplete from a list of users.
 * Keyboard: ArrowDown/Up to navigate, Tab/Enter to complete, Backspace to remove last.
 */
export default function UserAutocomplete({ allUsers, selected, onChange, placeholder = 'Add user…', hideChips = false }) {
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState(false)
  const [highlighted, setHighlighted] = useState(0)
  const inputRef = useRef()
  const dropRef = useRef()

  useEffect(() => {
    const handler = (e) => {
      if (!dropRef.current?.contains(e.target) && e.target !== inputRef.current) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const available = allUsers.filter(
    (u) =>
      !selected.find((s) => s.username === u.username) &&
      (u.username.toLowerCase().includes(query.toLowerCase()) ||
        u.display_name.toLowerCase().includes(query.toLowerCase()))
  )

  useEffect(() => { setHighlighted(0) }, [query])

  const add = (user) => {
    onChange([...selected, user])
    setQuery('')
    inputRef.current?.focus()
  }

  const remove = (username) => onChange(selected.filter((u) => u.username !== username))

  const handleKeyDown = (e) => {
    if (e.key === 'Backspace' && !query && selected.length) {
      remove(selected[selected.length - 1].username)
      return
    }
    if (!available.length) return
    if (e.key === 'ArrowDown') { e.preventDefault(); setHighlighted((h) => Math.min(h + 1, available.length - 1)) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setHighlighted((h) => Math.max(h - 1, 0)) }
    else if (e.key === 'Enter' || e.key === 'Tab') {
      if (open && available[highlighted]) { e.preventDefault(); add(available[highlighted]) }
    }
    else if (e.key === 'Escape') setOpen(false)
  }

  const ROLE_BADGE = hideChips
    ? { admin: 'bg-violet-100 text-violet-700 border-violet-200', user: 'bg-emerald-100 text-emerald-700 border-emerald-200' }
    : { admin: 'bg-violet-100 text-violet-800 border-violet-200', user: 'bg-teal-100 text-teal-800 border-teal-200' }
  const ROLE_LABEL = hideChips
    ? { admin: 'Admin', user: 'Annotator' }
    : { admin: 'Admin', user: 'User' }

  return (
    <div className="space-y-2">
      {/* Selected chips */}
      {!hideChips && selected.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {selected.map((u) => (
            <span key={u.username} className="inline-flex items-center gap-1 bg-indigo-100 text-indigo-800 rounded-full px-2.5 py-1 text-xs font-semibold">
              👤 {u.display_name}
              <button onClick={() => remove(u.username)} className="hover:text-red-500 font-bold ml-0.5">×</button>
            </span>
          ))}
        </div>
      )}

      {/* Input */}
      <div className="relative">
        <input
          ref={inputRef}
          type="text"
          value={query}
          placeholder={placeholder}
          onChange={(e) => { setQuery(e.target.value); setOpen(true) }}
          onFocus={() => setOpen(true)}
          onKeyDown={handleKeyDown}
          className="input-base"
        />
        {open && available.length > 0 && (
          <ul ref={dropRef} className="absolute z-50 w-full mt-1 bg-white border border-slate-200 rounded-xl shadow-xl max-h-52 overflow-y-auto py-1">
            {available.map((u, idx) => (
              <li
                key={u.username}
                onMouseDown={(e) => { e.preventDefault(); add(u) }}
                className={`flex items-center justify-between px-3 py-2 cursor-pointer text-sm transition
                  ${highlighted === idx ? 'bg-indigo-50' : 'hover:bg-slate-50'}`}
              >
                <div>
                  <span className="font-semibold text-slate-800">{u.display_name}</span>
                  <span className="text-slate-400 ml-1.5 text-xs">@{u.username}</span>
                </div>
                <span className={`text-xs font-bold px-1.5 py-0.5 rounded-full border ${ROLE_BADGE[u.role] ?? ''}`}>{ROLE_LABEL[u.role] ?? u.role}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}
