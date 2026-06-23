import { useState, useRef, useEffect, useMemo, forwardRef, useImperativeHandle } from 'react'
import { useTranslation } from 'react-i18next'

function getAncestorPaths(node, taxonomy) {
  if (!node?.parent) return []
  const parent = taxonomy.find((t) => t.full_path === node.parent)
  if (!parent) return []
  return [...getAncestorPaths(parent, taxonomy), parent.full_path]
}

/** Keep only the deepest label per hierarchy path. */
function collapseHierarchy(labels) {
  const sorted = [...new Set(labels)].sort()
  return sorted.filter((a) => !sorted.some((b) => b !== a && b.startsWith(a + ' > ')))
}

const TagSearch = forwardRef(function TagSearch({ taxonomy, selected, onChange }, ref) {
  const { t } = useTranslation()
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState(false)
  const [highlighted, setHighlighted] = useState(-1)
  const inputRef = useRef()
  const listRef = useRef()

  useImperativeHandle(ref, () => ({
    focus: () => inputRef.current?.focus(),
    blur: () => inputRef.current?.blur(),
  }))

  // Close on outside click
  useEffect(() => {
    const handler = (e) => {
      if (!listRef.current?.contains(e.target) && e.target !== inputRef.current) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const suggestions = query
    ? taxonomy.filter((t) => t.full_path.toLowerCase().includes(query.toLowerCase())).slice(0, 24)
    : taxonomy.filter((t) => t.level === 1).slice(0, 14)

  useEffect(() => { setHighlighted(-1) }, [query])

  // Display only deepest labels (collapsed), with full path text
  const displayLabels = useMemo(() => collapseHierarchy(selected), [selected])

  const addTag = (item) => {
    const ancestors = getAncestorPaths(item, taxonomy)
    const toAdd = [...ancestors, item.full_path].filter((fp) => !selected.includes(fp))
    if (toAdd.length) onChange([...selected, ...toAdd])
    setQuery('')
    setOpen(false)
    inputRef.current?.blur()
  }

  const removeTag = (fullPath) => {
    const ancestors = new Set(getAncestorPaths(taxonomy.find((t) => t.full_path === fullPath), taxonomy))
    ancestors.add(fullPath)
    const remaining = selected.filter((fp) => !ancestors.has(fp))
    const neededAncestors = new Set()
    for (const fp of remaining) {
      const node = taxonomy.find((t) => t.full_path === fp)
      if (node) {
        for (const a of getAncestorPaths(node, taxonomy)) {
          neededAncestors.add(a)
        }
      }
    }
    const final = remaining.filter((fp) => {
      if (!ancestors.has(fp)) return true
      return neededAncestors.has(fp)
    })
    onChange(final)
  }

  const handleKeyDown = (e) => {
    if (!open || !suggestions.length) return
    if (e.ctrlKey || e.metaKey) return
    if (e.key === 'ArrowDown') { e.preventDefault(); setHighlighted((h) => Math.min(h + 1, suggestions.length - 1)) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setHighlighted((h) => Math.max(h - 1, 0)) }
    else if ((e.key === 'Enter' || e.key === 'Tab') && highlighted >= 0) {
      e.preventDefault()
      const item = suggestions[highlighted]
      if (item && !selected.includes(item.full_path)) addTag(item)
    }
    else if (e.key === 'Escape') { inputRef.current?.blur(); setOpen(false) }
  }

  return (
    <div className="space-y-2">
      <div className="relative">
        <input
          ref={inputRef}
          type="text"
          value={query}
          disabled={!taxonomy.length}
          placeholder={taxonomy.length ? t('tagsearch.placeholder') : t('tagsearch.noTaxonomy')}
          onChange={(e) => { setQuery(e.target.value); setOpen(true) }}
          onFocus={() => setOpen(true)}
          onKeyDown={handleKeyDown}
          className="input-base disabled:bg-slate-100"
        />
        {open && suggestions.length > 0 && (
          <ul
            ref={listRef}
            className="absolute z-50 w-full mt-1 bg-white border border-slate-200 rounded-xl shadow-xl max-h-60 overflow-y-auto py-1"
          >
            {!query && (
              <li className="px-3 py-1 text-[10px] font-bold uppercase tracking-widest text-slate-400">
                {t('tagsearch.topLevel')}
              </li>
            )}
            {suggestions.map((item, idx) => (
              <li
                key={item.full_path}
                onMouseDown={(e) => { e.preventDefault(); if (!selected.includes(item.full_path)) addTag(item) }}
                className={`flex justify-between items-center px-3 py-2 cursor-pointer text-xs transition
                  ${highlighted === idx ? 'bg-indigo-50' : 'hover:bg-slate-50'}
                  ${selected.includes(item.full_path) ? 'opacity-40 cursor-default' : ''}
                  ${item.level === 1 ? 'font-bold text-slate-800' : 'text-slate-600'}`}
                style={{ paddingLeft: `${(item.level - 1) * 16 + 12}px` }}
              >
                <span>{item.level > 1 ? '↳ ' : ''}{item.name}</span>
                {item.level > 1 && <span className="text-slate-300 text-[10px] font-normal ml-2 truncate max-w-32">{item.full_path}</span>}
              </li>
            ))}
          </ul>
        )}
      </div>

      {displayLabels.length > 0 && (
        <div className="flex flex-wrap gap-1.5 p-2 border border-slate-100 rounded-lg bg-slate-50 min-h-9">
          {displayLabels.map((fp) => (
            <span key={fp} className="tag-chip">
              {fp}
              <button onClick={() => removeTag(fp)} className="ml-0.5 hover:text-indigo-600 text-indigo-400 font-bold">×</button>
            </span>
          ))}
        </div>
      )}
    </div>
  )
})

export default TagSearch
