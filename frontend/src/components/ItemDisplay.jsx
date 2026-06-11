import { api } from '../lib/api'

export default function ItemDisplay({ item, displayColumns = [] }) {
  if (!item) return (
    <div className="flex items-center justify-center h-full text-slate-300 text-5xl select-none">⏳</div>
  )

  if (item.type === 'image') return (
    <div className="flex flex-col items-center gap-2 h-full justify-center">
      <img
        src={api.mediaUrl(item.filename)}
        alt={item.name}
        className="max-h-[420px] max-w-full object-contain rounded-lg shadow"
      />
      <p className="text-xs text-slate-400 truncate max-w-full px-2">{item.name}</p>
    </div>
  )

  if (item.type === 'pdf') return (
    <div className="flex flex-col h-full gap-2">
      <p className="text-xs text-slate-500 font-semibold truncate">{item.name}</p>
      <embed
        src={api.mediaUrl(item.filename)}
        type="application/pdf"
        className="w-full flex-1 rounded border"
        style={{ minHeight: '400px' }}
      />
    </div>
  )

  if (item.type === 'text') return (
    <div className="h-full overflow-y-auto">
      <p className="text-xs font-bold text-slate-500 mb-2">{item.name}</p>
      <pre className="text-sm bg-slate-50 border rounded-lg p-4 whitespace-pre-wrap font-mono text-slate-700 leading-relaxed">
        {item.content}
      </pre>
    </div>
  )

  if (item.type === 'table') {
    const data = item.data || {}
    const cols = displayColumns?.length ? displayColumns.filter((c) => c in data) : Object.keys(data)
    return (
      <div className="h-full overflow-y-auto space-y-3">
        <p className="text-xs font-bold text-slate-400">{item.source_file || item.name}</p>
        {cols.map(
          (k) =>
            data[k] && (
              <div key={k} className="bg-slate-50 border border-slate-200 rounded-lg p-3">
                <div className="text-[10px] font-bold uppercase tracking-wider text-indigo-500 mb-1">{k}</div>
                <div className="text-sm text-slate-800 leading-relaxed">{data[k]}</div>
              </div>
            )
        )}
      </div>
    )
  }

  return <div className="text-slate-400 text-sm">Unknown item type: {item.type}</div>
}
