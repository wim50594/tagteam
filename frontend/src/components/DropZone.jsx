import { useState, useRef } from 'react'

/**
 * Drag-and-drop + click file upload zone.
 * Supports folder uploads via webkitdirectory.
 */
export default function DropZone({ onFiles, accept, label, icon, colorClass = 'indigo', directory = false, disabled = false }) {
  const [active, setActive] = useState(false)
  const fileRef = useRef()
  const dirRef = useRef()

  const colors = {
    indigo: { border: 'border-indigo-300', bg: 'bg-indigo-50/40', text: 'text-indigo-700', btn: 'btn-primary' },
    teal:   { border: 'border-teal-300',   bg: 'bg-teal-50/40',   text: 'text-teal-700',   btn: 'bg-teal-600 hover:bg-teal-700 text-white font-semibold px-3 py-1.5 rounded-md text-xs shadow-sm transition' },
  }
  const c = colors[colorClass] ?? colors.indigo

  const handleDrop = (e) => {
    e.preventDefault()
    if (disabled) return
    setActive(false)
    const items = e.dataTransfer.items
    if (!items) { onFiles(Array.from(e.dataTransfer.files)); return }

    const files = []
    const traverse = (entry) =>
      entry.isFile
        ? new Promise((res) => entry.file((f) => { files.push(f); res() }))
        : new Promise((res) => {
            const reader = entry.createReader()
            reader.readEntries(async (entries) => {
              await Promise.all(entries.map(traverse))
              res()
            })
          })

    Promise.all(Array.from(items).map((i) => traverse(i.webkitGetAsEntry()))).then(
      () => files.length && onFiles(files)
    )
  }

  return (
    <div
      onDragOver={(e) => { e.preventDefault(); !disabled && setActive(true) }}
      onDragLeave={() => setActive(false)}
      onDrop={handleDrop}
      className={`border-2 border-dashed rounded-xl p-6 text-center transition-all
        ${c.border} ${c.bg}
        ${active ? 'ring-2 ring-indigo-400 scale-[1.01]' : ''}
        ${disabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}`}
    >
      <div className="text-3xl mb-2">{icon}</div>
      <p className={`text-sm font-semibold mb-3 ${c.text}`}>{label}</p>
      <div className="flex justify-center gap-2 flex-wrap">
        <button
          type="button"
          disabled={disabled}
          onClick={() => fileRef.current?.click()}
          className={c.btn}
        >
          Choose files
        </button>
        {directory && (
          <button
            type="button"
            disabled={disabled}
            onClick={() => dirRef.current?.click()}
            className="bg-slate-700 hover:bg-slate-800 text-white font-semibold px-3 py-1.5 rounded-md text-xs shadow-sm transition disabled:opacity-40"
          >
            Choose folder 📁
          </button>
        )}
      </div>
      <input ref={fileRef} type="file" multiple accept={accept} onChange={(e) => onFiles(Array.from(e.target.files))} className="hidden" />
      {directory && (
        <input ref={dirRef} type="file" webkitdirectory="true" multiple onChange={(e) => onFiles(Array.from(e.target.files))} className="hidden" />
      )}
      <p className="text-xs text-slate-400 mt-2">or drag & drop here</p>
    </div>
  )
}
