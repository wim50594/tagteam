import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { TYPE_ICONS } from '../lib/constants'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { useNavigate } from 'react-router-dom'

export default function HomePage() {
  const { user, isAdmin } = useAuth()
  const { t, i18n } = useTranslation()
  const navigate = useNavigate()
  const [projects, setProjects] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => { load() }, [])

  const load = async () => {
    setLoading(true)
    try { setProjects(await api.get('/api/sessions')) }
    catch (e) { console.error(e) }
    finally { setLoading(false) }
  }

  const fmtDate = (iso) => {
    const locale = i18n.language === 'de' ? 'de-DE' : 'en-GB'
    return new Date(iso).toLocaleDateString(locale)
  }

  const deleteProject = async (e, sid) => {
    e.stopPropagation()
    if (!confirm(t('home.deleteConfirm'))) return
    await api.delete(`/api/sessions/${sid}`)
    load()
  }

  return (
    <div className="space-y-8">
      <div className="flex justify-between items-end border-b border-slate-200 pb-5">
        <div>
          <h1 className="text-2xl font-black text-slate-900">{t('home.title')}</h1>
          <p className="text-sm text-slate-500 mt-1">{t('home.subtitle')}</p>
        </div>
        <button onClick={() => navigate('/config')} className="btn-primary flex items-center gap-2 !py-2.5 !px-5">
          <span className="text-base font-bold">＋</span> {t('home.newProject')}
        </button>
      </div>

      {loading ? (
        <div className="text-center py-16 text-slate-400">{t('common.loading')}</div>
      ) : projects.length === 0 ? (
        <div className="border-2 border-dashed border-slate-200 rounded-2xl p-16 text-center">
          <div className="text-5xl mb-4">🏷️</div>
          <p className="text-slate-500 font-medium">{t('home.noProjects')}</p>
          <button onClick={() => navigate('/config')} className="mt-4 text-indigo-600 font-semibold text-sm hover:underline">
            {t('home.createFirst')}
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
          {projects.map((s) => {
            const stats = s.item_stats || {}
            return (
              <div key={s.id} className="card hover:shadow-md transition flex flex-col gap-4 cursor-pointer"
                onClick={() => navigate(`/workspace/${s.id}`)}>
                <div className="flex justify-between items-start">
                  <div>
                    <h3 className="font-bold text-slate-900 leading-tight">{s.name}</h3>
                    <p className="text-xs text-slate-400 mt-0.5">
                      {fmtDate(s.created_at)}
                      {s.current_user_role && (
                        <span className={`ml-2 text-[10px] font-bold px-1.5 py-0.5 rounded-full border ${
                          s.current_user_role === 'owner' ? 'bg-amber-100 text-amber-700 border-amber-200' :
                          s.current_user_role === 'maintainer' ? 'bg-blue-100 text-blue-700 border-blue-200' :
                          s.current_user_role === 'annotator' ? 'bg-teal-100 text-teal-700 border-teal-200' : ''
                        }`}>
                          {t(`home.role.${s.current_user_role}`, s.current_user_role)}
                        </span>
                      )}
                    </p>
                  </div>
                  {(isAdmin || ['owner', 'maintainer'].includes(s.current_user_role)) && (
                    <div className="flex gap-1">
                      <button
                        onClick={(e) => { e.stopPropagation(); navigate(`/config/${s.id}`) }}
                        className="btn-secondary !px-2 !py-1 !text-xs"
                        title={t('home.edit')}
                      >
                        ✏️
                      </button>
                      <button
                        onClick={(e) => deleteProject(e, s.id)}
                        className="btn-danger !px-2 !py-1 !text-xs"
                        title={t('home.delete')}
                      >
                        🗑
                      </button>
                    </div>
                  )}
                </div>

                <div className="text-xs bg-slate-50 border border-slate-100 rounded-lg p-3 space-y-1.5">
                  <div><span className="font-semibold text-slate-600">👥 {t('home.users')}:</span>{' '}
                    {(s.annotators || []).join(', ')}
                  </div>
                  <div>
                    <span className="font-semibold text-slate-600">📦 {t('home.items')}:</span>{' '}
                    {(s.item_ids || []).length}
                    {Object.entries(stats).filter(([, v]) => v > 0).map(([k, v]) => (
                      <span key={k} className="ml-1 text-slate-400">{TYPE_ICONS[k]}{v}</span>
                    ))}
                  </div>
                  <div><span className="font-semibold text-slate-600">🏷️ {t('home.taxonomy')}:</span>{' '}
                    {(s.taxonomy || []).length} {t('home.labels')}
                  </div>
                  {s.verification_mode && (
                    <div className="text-amber-600 font-semibold">⚡ {t('home.verification')} (k={s.verifiers_per_item || 2})</div>
                  )}
                </div>

                {s.my_progress && (
                  <div className="space-y-1">
                    <div className="flex justify-between text-[10px] font-semibold text-slate-500">
                      <span>{t('workspace.progress')}</span>
                      <span>{s.my_progress.labeled}/{s.my_progress.total} ({s.my_progress.pct}%)</span>
                    </div>
                    <div className="w-full bg-slate-100 rounded-full h-2 overflow-hidden">
                      <div className="bg-emerald-500 h-full rounded-full transition-all" style={{ width: `${s.my_progress.pct}%` }} />
                    </div>
                  </div>
                )}

                <div className="flex gap-2 mt-auto">
                  <button
                    onClick={(e) => { e.stopPropagation(); navigate(`/workspace/${s.id}`) }}
                    className="btn-primary flex-1 justify-center"
                  >
                    {t('home.openWorkspace')}
                  </button>
                  {(isAdmin || ['owner', 'maintainer'].includes(s.current_user_role)) && (
                    <button
                      onClick={(e) => { e.stopPropagation(); navigate(`/review/${s.id}`) }}
                      className="btn-secondary !px-3"
                      title={t('home.reviewExport')}
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
