import { useState, useEffect, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import ItemDisplay from '../components/ItemDisplay'
import TagSearch from '../components/TagSearch'

export default function WorkspacePage() {
  const { sessionId } = useParams()
  const navigate = useNavigate()
  const { user, isAdmin } = useAuth()

  const [session, setSession] = useState(null)
  // Admins default to themselves if assigned, otherwise first annotator
  const [annotator, setAnnotator] = useState(null)
  const [currentIndex, setCurrentIndex] = useState(0)
  const [currentItem, setCurrentItem] = useState(null)
  const [selectedLabels, setSelectedLabels] = useState([])
  const [progress, setProgress] = useState({})
  const [saving, setSaving] = useState(false)

  // Load session on mount, then resume at first unlabeled item
  useEffect(() => {
    const init = async () => {
      try {
        const s = await api.get(`/api/sessions/${sessionId}`)
        setSession(s)
        const ann = isAdmin
          ? (s.annotators.includes(user.username) ? user.username : s.annotators[0])
          : user.username
        setAnnotator(ann)

        // Resume: jump to first item without saved labels
        const batch = s.batches?.[ann] ?? []
        if (batch.length > 0) {
          const saved = await api.get(`/api/labels/${sessionId}/${ann}`)
          const resumeIdx = batch.findIndex((id) => !saved[id] || saved[id].length === 0)
          setCurrentIndex(resumeIdx === -1 ? batch.length - 1 : resumeIdx)
        }
      } catch {
        navigate('/')
      }
    }
    init()
  }, [sessionId])

  // Load item + saved labels when annotator or index changes
  useEffect(() => {
    if (!session || !annotator) return
    const batch = session.batches?.[annotator] ?? []
    if (batch.length === 0) return
    const itemId = batch[Math.min(currentIndex, batch.length - 1)]
    setCurrentItem(null)
    Promise.all([
      api.get(`/api/items/${itemId}`),
      api.get(`/api/labels/${sessionId}/${annotator}`),
    ]).then(([item, saved]) => {
      setCurrentItem(item)
      setSelectedLabels(saved[itemId] ?? [])
    }).catch(console.error)
    loadProgress()
  }, [session, annotator, currentIndex])

  const loadProgress = useCallback(async () => {
    try {
      const p = await api.get(`/api/sessions/${sessionId}/progress`)
      setProgress(p)
    } catch { /* non-critical */ }
  }, [sessionId])

  const saveAndNavigate = async (skip = false) => {
    if (!session || !annotator) return
    const batch = session.batches?.[annotator] ?? []
    const itemId = batch[currentIndex]
    setSaving(true)
    await api.post(`/api/labels/${sessionId}/${annotator}`, {
      body: { [itemId]: skip ? [] : selectedLabels },
    }).catch(console.error)
    setSaving(false)
    await loadProgress()
    if (currentIndex < batch.length - 1) {
      setCurrentIndex((i) => i + 1)
    } else {
      alert('✅ Batch complete!')
      navigate('/')
    }
  }

  if (!session || !annotator) {
    return <div className="flex items-center justify-center h-64 text-slate-400">Loading workspace…</div>
  }

  const batch = session.batches?.[annotator] ?? []
  const ann_progress = progress[annotator] ?? { labeled: 0, total: batch.length, pct: 0 }
  const taxonomy = session.taxonomy ?? []

  return (
    <div className="space-y-4">
      {/* Top bar */}
      <div className="card !py-3 flex flex-col sm:flex-row gap-4 items-center justify-between">
        <div className="flex items-center gap-3">
          <label className="text-xs font-bold text-slate-600 uppercase tracking-wide">Annotator:</label>
          {isAdmin ? (
            <select
              value={annotator}
              onChange={async (e) => {
                const ann = e.target.value
                setAnnotator(ann)
                const batch = session.batches?.[ann] ?? []
                if (batch.length > 0) {
                  const saved = await api.get(`/api/labels/${sessionId}/${ann}`)
                  const resumeIdx = batch.findIndex((id) => !saved[id] || saved[id].length === 0)
                  setCurrentIndex(resumeIdx === -1 ? batch.length - 1 : resumeIdx)
                } else {
                  setCurrentIndex(0)
                }
              }}
              className="bg-indigo-50 border border-indigo-200 rounded-lg px-3 py-1.5 text-sm font-bold text-indigo-700 focus:outline-none"
            >
              {session.annotators.map((a) => (
                <option key={a} value={a}>{a}</option>
              ))}
            </select>
          ) : (
            <span className="bg-indigo-100 text-indigo-800 font-bold text-sm px-3 py-1.5 rounded-lg">
              {annotator}
            </span>
          )}
          <span className="text-xs text-slate-400">{currentIndex + 1} / {batch.length}</span>
        </div>

        {/* Progress bar */}
        <div className="w-full sm:w-1/3 space-y-1">
          <div className="flex justify-between text-xs font-semibold text-slate-500">
            <span>Progress</span>
            <span>{ann_progress.labeled}/{ann_progress.total} ({ann_progress.pct}%)</span>
          </div>
          <div className="w-full bg-slate-100 rounded-full h-2.5 overflow-hidden">
            <div className="progress-bar h-full" style={{ width: `${ann_progress.pct}%` }} />
          </div>
        </div>

        {isAdmin && (
          <button onClick={() => navigate(`/review/${sessionId}`)} className="btn-secondary whitespace-nowrap !text-xs">
            Review →
          </button>
        )}
      </div>

      {/* Main grid */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
        {/* Item display */}
        <div className="lg:col-span-7 card flex flex-col gap-3" style={{ minHeight: '540px' }}>
          <div className="flex-1 overflow-hidden">
            <ItemDisplay item={currentItem} displayColumns={session.display_columns} />
          </div>
          {/* Pagination dots */}
          <div className="border-t pt-3 flex gap-1 flex-wrap justify-center max-h-16 overflow-y-auto">
            {batch.slice(Math.max(0, currentIndex - 10), currentIndex + 11).map((_, relIdx) => {
              const absIdx = Math.max(0, currentIndex - 10) + relIdx
              return (
                <button
                  key={absIdx}
                  onClick={() => setCurrentIndex(absIdx)}
                  className={`w-7 h-7 rounded text-xs font-bold transition
                    ${absIdx === currentIndex ? 'bg-indigo-600 text-white' : 'bg-slate-100 text-slate-500 hover:bg-slate-200'}`}
                >
                  {absIdx + 1}
                </button>
              )
            })}
          </div>
        </div>

        {/* Labeling panel */}
        <div className="lg:col-span-5 card flex flex-col gap-4">
          <div>
            <h3 className="text-xs font-bold uppercase tracking-wider text-slate-600 mb-0.5">🏷️ Classify</h3>
            {currentItem && <p className="text-xs text-slate-400 truncate">{currentItem.name}</p>}
          </div>

          <div className="flex-1">
            <TagSearch taxonomy={taxonomy} selected={selectedLabels} onChange={setSelectedLabels} />
          </div>

          <div className="space-y-2 border-t pt-4">
            <div className="flex gap-2">
              <button
                onClick={() => currentIndex > 0 && setCurrentIndex((i) => i - 1)}
                disabled={currentIndex === 0}
                className="btn-secondary flex-1 justify-center"
              >
                ← Back
              </button>
              <button
                onClick={() => saveAndNavigate(true)}
                className="px-3 bg-amber-50 hover:bg-amber-100 text-amber-700 rounded-lg text-sm font-medium transition border border-amber-200"
                title="Skip"
              >
                ⏭
              </button>
              <button
                onClick={() => saveAndNavigate(false)}
                disabled={saving}
                className="btn-primary flex-[2] justify-center"
              >
                {saving ? '…' : selectedLabels.length ? 'Save & Next →' : 'Next →'}
              </button>
            </div>
            {!selectedLabels.length && (
              <p className="text-xs text-slate-400 text-center">No tag selected – choose at least one or skip.</p>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}