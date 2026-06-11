import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'

const TYPE_ICONS = { images: '🖼️', pdfs: '📄', texts: '📝', tables: '📊', svgs: '🎨' }

export default function HomePage() {
  const { isAdmin } = useAuth()
  const navigate = useNavigate()
  const [sessions, setSessions] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => { load() }, [])

  const load = async () => {
    setLoading(true)
    try { setSessions(await api.get('/api/sessions')) }
    catch (e) { console.error(e) }
    finally { setLoading(false) }
  }

  const deleteSession = async (e, sid) => {
    e.stopPropagation()
    if (!confirm('Delete this project and all its data permanently?')) return
    await api.delete(`/api/sessions/${sid}`)
    load()
  }

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="flex justify-between items-end border-b border-slate-200 pb-5">
        <div>
          <h1 className="text-2xl font-black text-slate-900">Projects</h1>
          <p className="text-sm text-slate-500 mt-1">Select a project to start annotating.</p>
        </div>
        {isAdmin && (
          <button onClick={() => navigate('/config')} className="btn-primary flex items-center gap-2 !py-2.5 !px-5">
            <span className="text-base font-bold">＋</span> New project
          </button>
        )}
      </div>

      {loading ? (
        <div className="text-center py-16 text-slate-400">Loading…</div>
      ) : sessions.length === 0 ? (
        <div className="border-2 border-dashed border-slate-200 rounded-2xl p-16 text-center">
          <div className="text-5xl mb-4">🏷️</div>
          <p className="text-slate-500 font-medium">No projects yet.</p>
          {isAdmin && (
            <button onClick={() => navigate('/config')} className="mt-4 text-indigo-600 font-semibold text-sm hover:underline">
              Create the first project →
            </button>
          )}
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
          {sessions.map((s) => {
            const stats = s.item_stats || {}
            return (
              <div key={s.id} className="card hover:shadow-md transition flex flex-col gap-4 cursor-pointer"
                onClick={() => navigate(`/workspace/${s.id}`)}>
                <div className="flex justify-between items-start">
                  <div>
                    <h3 className="font-bold text-slate-900 leading-tight">{s.name}</h3>
                    <p className="text-xs text-slate-400 mt-0.5">
                      {new Date(s.created_at).toLocaleDateString('en-GB')}
                    </p>
                  </div>
                  {isAdmin && (
                    <button
                      onClick={(e) => deleteSession(e, s.id)}
                      className="btn-danger"
                    >
                      Delete
                    </button>
                  )}
                </div>

                <div className="text-xs bg-slate-50 border border-slate-100 rounded-lg p-3 space-y-1.5">
                  <div><span className="font-semibold text-slate-600">👥 Annotators:</span>{' '}
                    {(s.annotators || []).join(', ')}
                  </div>
                  <div>
                    <span className="font-semibold text-slate-600">📦 Items:</span>{' '}
                    {(s.item_ids || []).length}
                    {Object.entries(stats).filter(([, v]) => v > 0).map(([k, v]) => (
                      <span key={k} className="ml-1 text-slate-400">{TYPE_ICONS[k]}{v}</span>
                    ))}
                  </div>
                  <div><span className="font-semibold text-slate-600">🏷️ Taxonomy:</span>{' '}
                    {(s.taxonomy || []).length} labels
                  </div>
                  {s.verification_mode && (
                    <div className="text-amber-600 font-semibold">⚡ Verification mode</div>
                  )}
                </div>

                <div className="flex gap-2 mt-auto">
                  <button
                    onClick={(e) => { e.stopPropagation(); navigate(`/workspace/${s.id}`) }}
                    className="btn-primary flex-1 justify-center"
                  >
                    Open workspace →
                  </button>
                  {isAdmin && (
                    <button
                      onClick={(e) => { e.stopPropagation(); navigate(`/review/${s.id}`) }}
                      className="btn-secondary !px-3"
                      title="Review & Export"
                    >
                      📊
                    </button>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
