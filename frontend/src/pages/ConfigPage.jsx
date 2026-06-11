import { useState, useEffect, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../lib/api'
import { buildBatches, batchSummary } from '../lib/batches'
import DropZone from '../components/DropZone'
import UserAutocomplete from '../components/UserAutocomplete'

const STEPS = [
  { id: 1, label: 'Data', icon: '📥' },
  { id: 2, label: 'Taxonomy', icon: '🗂️' },
  { id: 3, label: 'Team & Start', icon: '🚀' },
]
const TYPE_ICONS = { images: '🖼️', pdfs: '📄', texts: '📝', tables: '📊' }

const formatBytes = (n) => {
  if (!n) return '0 B'
  const u = ['B', 'KB', 'MB', 'GB']
  const i = Math.min(Math.floor(Math.log(n) / Math.log(1024)), u.length - 1)
  return `${(n / 1024 ** i).toFixed(i ? 1 : 0)} ${u[i]}`
}

export default function ConfigPage() {
  const navigate = useNavigate()
  const [step, setStep] = useState(1)
  const [allUsers, setAllUsers] = useState([])

  // Step 1 state
  // `uploadedFiles` remains the authoritative flat list of items for the backend.
  const [uploadedFiles, setUploadedFiles] = useState([])
  const [detectedCols, setDetectedCols] = useState([])
  const [selectedCols, setSelectedCols] = useState([])
  const [uploading, setUploading] = useState(false)
  const [lastSkipped, setLastSkipped] = useState([])
  const [lastDuplicates, setLastDuplicates] = useState([])

  // Step 2 state
  const [taxonomy, setTaxonomy] = useState([])
  const [taxStatus, setTaxStatus] = useState(null)

  // Step 3 state
  const [projectName, setProjectName] = useState('')
  const [selectedAnnotators, setSelectedAnnotators] = useState([])
  const [verifyMode, setVerifyMode] = useState(false)
  const [verifiersPerItem, setVerifiersPerItem] = useState(2)
  const [errors, setErrors] = useState({})
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    api.get('/api/auth/users').then(setAllUsers).catch(console.error)
  }, [])

  // Derived unique item IDs for project creation
  const uploadedIds = useMemo(() => uploadedFiles.map((f) => f.item_id), [uploadedFiles])

  // FIX 1: Accurate unique item counts for the statistics blocks
  const stats = useMemo(() => {
    const s = { images: 0, pdfs: 0, texts: 0, tables: 0 }
    for (const f of uploadedFiles) {
      const key =
        f.category === 'image' ? 'images' :
        f.category === 'pdf'   ? 'pdfs'   :
        f.category === 'text'  ? 'texts'  :
        f.category === 'table' ? 'tables' : null
      if (key) s[key] += 1 // Count each row/file as exactly 1 item
    }
    return s
  }, [uploadedFiles])

  // FIX 2: Group flat items into unique files for the picker UI presentation
  const groupedFiles = useMemo(() => {
    const groups = {}
    for (const f of uploadedFiles) {
      const key = `${f.category}:${f.name}`
      if (!groups[key]) {
        groups[key] = {
          name: f.name,
          category: f.category,
          size: f.size, // Native file size (not multiplied)
          duplicate: f.duplicate,
          row_count: 0,
          item_ids: []
        }
      }
      groups[key].item_ids.push(f.item_id)
      if (f.category === 'table') {
        groups[key].row_count += 1
      }
    }
    return Object.values(groups)
  }, [uploadedFiles])

  // FIX 3: Calculate accurate non-bloated total size from grouped files
  const totalSize = useMemo(() => {
    return groupedFiles.reduce((acc, f) => acc + (f.size || 0), 0)
  }, [groupedFiles])

  const handleDataUpload = async (files) => {
    if (!files?.length) return
    setUploading(true)
    setLastSkipped([])
    setLastDuplicates([])

    const fd = new FormData()
    files.forEach((f) => fd.append('files', f))

    try {
      const d = await api.post('/api/upload-universal', { form: fd })
      const incoming = d.files || []

      // Client-side dedup against already-listed items in this draft.
      const existing = new Set(uploadedFiles.map((f) => f.item_id))
      const toAdd = []
      const dupClient = []
      for (const f of incoming) {
        if (existing.has(f.item_id)) dupClient.push(f.name)
        else toAdd.push(f)
      }

      setUploadedFiles((prev) => [...prev, ...toAdd])

      // Merge detected columns (tables only).
      if ((d.columns || []).length) {
        const merged = Array.from(new Set([...detectedCols, ...d.columns]))
        setDetectedCols(merged)
        setSelectedCols((prev) => prev.length ? prev : merged)
      }

      const serverDups = incoming.filter((f) => f.duplicate).map((f) => f.name)
      setLastDuplicates(Array.from(new Set([...serverDups, ...dupClient])))
      setLastSkipped(d.skipped || [])
    } catch (e) {
      alert('Upload failed: ' + e.message)
    } finally {
      setUploading(false)
    }
  }

  // FIX 4: Delete all items belonging to a grouped file at once
  const removeFile = async (itemIds, fileName) => {
    const previous = uploadedFiles
    // Optimistic UI update: filter out all items matching the file's item_ids
    setUploadedFiles((prev) => prev.filter((f) => !itemIds.includes(f.item_id)))
    try {
      await Promise.all(itemIds.map((id) => api.delete(`/api/items/${id}/draft`)))
    } catch (e) {
      setUploadedFiles(previous)
      alert(`Could not remove file "${fileName}": ` + e.message)
    }
  }

  const clearAll = async () => {
    if (!uploadedFiles.length) return
    if (!confirm(`Remove all ${groupedFiles.length} uploaded file(s)?`)) return
    const snapshot = uploadedFiles
    setUploadedFiles([])
    setDetectedCols([])
    setSelectedCols([])
    // Fire-and-forget; surface a single error if anything fails.
    await api.post('/api/items/draft/batch-delete', { 
        body: { item_ids: snapshot.map((f) => f.item_id) } 
      })
    const failed = results.filter((r) => r.status === 'rejected').length
    if (failed) alert(`${failed} file(s) could not be removed server-side.`)
  }

  const handleTaxUpload = async (files) => {
    if (!files.length) return
    const fd = new FormData()
    fd.append('file', files[0])
    fd.append('has_header', 'true')
    try {
      const d = await api.post('/api/parse-labels', { form: fd })
      setTaxonomy(d.taxonomy || [])
      setTaxStatus(`✅ ${(d.taxonomy || []).length} labels loaded from "${files[0].name}"`)
    } catch (e) { alert('Taxonomy upload failed: ' + e.message) }
  }

  const createProject = async () => {
    const errs = {}
    if (!projectName.trim()) errs.name = 'Project name is required'
    if (!selectedAnnotators.length) errs.annotators = 'At least one annotator is required'
    if (Object.keys(errs).length) { setErrors(errs); return }
    setErrors({})

    setSaving(true)
    const id = crypto.randomUUID()
    const annUsernames = selectedAnnotators.map((u) => u.username)
    const batches = buildBatches(uploadedIds, annUsernames, verifyMode, verifiersPerItem)
    const session = {
      id,
      name: projectName.trim(),
      annotators: annUsernames,
      verification_mode: verifyMode,
      verifiers_per_item: verifyMode ? verifiersPerItem : 1,
      item_ids: uploadedIds,
      batches,
      taxonomy,
      display_columns: selectedCols,
      item_stats: stats,
      created_at: new Date().toISOString(),
    }
    try {
      await api.post('/api/sessions/save-full', { body: session })
      navigate(`/workspace/${id}`)
    } catch (e) { alert('Failed to create project: ' + e.message) }
    setSaving(false)
  }

  const summary = batchSummary(
    uploadedIds.length, selectedAnnotators.map((u) => u.username), verifyMode, verifiersPerItem,
  )

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      {/* Stepper */}
      <div className="flex items-center gap-0">
        {STEPS.map((s, i) => (
          <div key={s.id} className="flex items-center flex-1 last:flex-none">
            <button
              onClick={() => setStep(s.id)}
              className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold transition whitespace-nowrap
                ${step === s.id ? 'bg-indigo-600 text-white shadow' : 'bg-white text-slate-500 border hover:border-indigo-300'}`}
            >
              <span>{s.icon}</span> {s.label}
            </button>
            {i < STEPS.length - 1 && <div className="flex-1 h-0.5 bg-slate-200 mx-1" />}
          </div>
        ))}
      </div>

      {/* ── Step 1: Data ── */}
      {step === 1 && (
        <div className="card space-y-5">
          <div>
            <h2 className="text-lg font-bold text-slate-900">Step 1: Upload data</h2>
            <p className="text-sm text-slate-500 mt-1">
              Supported: images (PNG/JPG/GIF/WEBP/SVG), PDFs, text (TXT/MD), spreadsheets (CSV/TSV/XLSX)
            </p>
          </div>

          <DropZone
            onFiles={handleDataUpload}
            icon="📥" directory
            label={uploading ? 'Uploading…' : 'Drop files or folder here'}
            disabled={uploading}
          />

          {/* Duplicate / skipped warnings (last batch only) */}
          {lastDuplicates.length > 0 && (
            <div className="bg-amber-50 border border-amber-200 rounded-xl p-3 text-xs text-amber-800">
              ⚠ {lastDuplicates.length} file(s) were already uploaded and were skipped:{' '}
              <span className="font-mono">{lastDuplicates.slice(0, 5).join(', ')}</span>
              {lastDuplicates.length > 5 && ` …+${lastDuplicates.length - 5} more`}
            </div>
          )}
          {lastSkipped.length > 0 && (
            <div className="bg-red-50 border border-red-200 rounded-xl p-3 text-xs text-red-700">
              ❌ {lastSkipped.length} file(s) could not be processed:
              <ul className="mt-1 list-disc list-inside">
                {lastSkipped.slice(0, 5).map((s, i) => (
                  <li key={i}><span className="font-mono">{s.name}</span> — {s.reason}</li>
                ))}
              </ul>
            </div>
          )}

          {/* Stats grid */}
          {uploadedFiles.length > 0 && (
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              {Object.entries(stats).filter(([, v]) => v > 0).map(([k, v]) => (
                <div key={k} className="bg-indigo-50 border border-indigo-100 rounded-xl p-3 text-center">
                  <div className="text-2xl">{TYPE_ICONS[k]}</div>
                  <div className="text-xl font-black text-indigo-700">{v}</div>
                  <div className="text-xs text-indigo-500 capitalize">{k}</div>
                </div>
              ))}
            </div>
          )}

          {/* File list with remove buttons */}
          {uploadedFiles.length > 0 && (
            <div className="border border-slate-200 rounded-xl overflow-hidden">
              <div className="flex items-center justify-between bg-slate-50 px-4 py-2.5 border-b border-slate-200">
                <p className="text-sm font-bold text-slate-700">
                  {uploadedFiles.length} item(s) · {groupedFiles.length} unique file(s) · {formatBytes(totalSize)}
                </p>
                <button
                  onClick={clearAll}
                  className="text-xs font-semibold text-red-600 hover:text-red-700 hover:underline"
                >
                  Remove all
                </button>
              </div>
              <ul className="max-h-64 overflow-y-auto divide-y divide-slate-100">
                {groupedFiles.map((f) => (
                  <li key={f.item_ids[0]} className="flex items-center gap-3 px-4 py-2 text-sm">
                    <span className="text-base">
                      {f.category === 'image' ? '🖼️' :
                       f.category === 'pdf'   ? '📄' :
                       f.category === 'text'  ? '📝' :
                       f.category === 'table' ? '📊' : '📁'}
                    </span>
                    <span className="flex-1 truncate font-medium text-slate-800" title={f.name}>
                      {f.name}
                      {f.row_count > 0 && (
                        <span className="text-xs text-slate-400 ml-1">({f.row_count} rows)</span>
                      )}
                    </span>
                    {f.duplicate && (
                      <span className="text-[10px] font-bold uppercase tracking-wide text-amber-700 bg-amber-100 px-1.5 py-0.5 rounded">
                        reused
                      </span>
                    )}
                    <span className="text-xs text-slate-400 tabular-nums">{formatBytes(f.size)}</span>
                    <button
                      onClick={() => removeFile(f.item_ids, f.name)}
                      className="text-slate-400 hover:text-red-600 transition"
                      aria-label={`Remove ${f.name}`}
                      title="Remove"
                    >
                      ✕
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {detectedCols.length > 0 && (
            <div className="bg-amber-50 border border-amber-200 rounded-xl p-4 space-y-2">
              <p className="text-xs font-bold text-amber-800">📋 Table columns detected – select which to show during annotation:</p>
              <div className="flex flex-wrap gap-2">
                {detectedCols.map((c) => (
                  <label key={c} className="flex items-center gap-1.5 bg-white border px-3 py-1.5 rounded-lg cursor-pointer text-xs font-medium hover:border-amber-400 transition">
                    <input
                      type="checkbox" checked={selectedCols.includes(c)}
                      onChange={(e) => e.target.checked
                        ? setSelectedCols([...selectedCols, c])
                        : setSelectedCols(selectedCols.filter((x) => x !== c))}
                      className="rounded"
                    />
                    {c}
                  </label>
                ))}
              </div>
            </div>
          )}

          {uploadedFiles.length > 0 && (
            <div className="flex justify-end">
              <button onClick={() => setStep(2)} className="btn-primary">Taxonomy →</button>
            </div>
          )}
        </div>
      )}

      {/* ── Step 2: Taxonomy ── */}
      {step === 2 && (
        <div className="card space-y-5">
          <div>
            <h2 className="text-lg font-bold text-slate-900">Step 2: Upload taxonomy</h2>
            <p className="text-sm text-slate-500 mt-1">
              CSV/TSV (multiple columns = hierarchy levels) or TXT (one class per line,{' '}
              <code className="bg-slate-100 px-1 rounded text-xs">&gt;</code> for hierarchy)
            </p>
          </div>
          <DropZone onFiles={handleTaxUpload} icon="🗂️" colorClass="teal" accept=".csv,.tsv,.txt"
            label="Drop taxonomy file (CSV, TSV, TXT)" />

          {taxStatus && (
            <div className="text-sm text-teal-800 font-medium bg-teal-50 border border-teal-200 rounded-lg p-3">{taxStatus}</div>
          )}

          {taxonomy.length > 0 && (
            <div className="border border-slate-200 rounded-xl overflow-hidden max-h-56 overflow-y-auto">
              <table className="w-full text-xs">
                <thead className="bg-slate-50 sticky top-0">
                  <tr>
                    {['Name', 'Full path', 'Level'].map((h) => (
                      <th key={h} className="text-left p-2.5 font-bold text-slate-500">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {taxonomy.slice(0, 100).map((t, i) => (
                    <tr key={i} className={i % 2 === 0 ? 'bg-white' : 'bg-slate-50/50'}>
                      <td className="p-2.5 font-medium" style={{ paddingLeft: `${(t.level - 1) * 16 + 10}px` }}>
                        {t.level > 1 ? '↳ ' : ''}{t.name}
                      </td>
                      <td className="p-2.5 text-slate-400 font-mono text-[10px]">{t.full_path}</td>
                      <td className="p-2.5 text-slate-400">{t.level}</td>
                    </tr>
                  ))}
                  {taxonomy.length > 100 && (
                    <tr><td colSpan={3} className="p-2.5 text-center text-slate-400">…and {taxonomy.length - 100} more</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          )}

          <div className="flex justify-between">
            <button onClick={() => setStep(1)} className="text-slate-500 text-sm font-medium hover:underline">← Back</button>
            {taxonomy.length > 0 && (
              <button onClick={() => setStep(3)} className="bg-teal-600 hover:bg-teal-700 text-white font-semibold px-5 py-2 rounded-lg text-sm shadow transition">
                Team & Start →
              </button>
            )}
          </div>
        </div>
      )}

      {/* ── Step 3: Team ── */}
      {step === 3 && (
        <div className="card space-y-5">
          <h2 className="text-lg font-bold text-slate-900">Step 3: Configure team & launch</h2>

          <div>
            <label className="block text-xs font-bold text-slate-600 mb-1 uppercase tracking-wide">
              Project name <span className="text-red-500">*</span>
            </label>
            <input
              type="text" value={projectName}
              onChange={(e) => { setProjectName(e.target.value); setErrors((p) => ({ ...p, name: null })) }}
              placeholder="e.g. Literature Screening Q1 2025"
              className={`input-base ${errors.name ? 'input-error' : ''}`}
            />
            {errors.name && <p className="text-xs text-red-600 mt-1">⚠ {errors.name}</p>}
          </div>

          <div>
            <label className="block text-xs font-bold text-slate-600 mb-1 uppercase tracking-wide">
              Annotators <span className="text-red-500">*</span>
            </label>
            <UserAutocomplete
              allUsers={allUsers}
              selected={selectedAnnotators}
              onChange={(v) => { setSelectedAnnotators(v); setErrors((p) => ({ ...p, annotators: null })) }}
            />
            {errors.annotators && <p className="text-xs text-red-600 mt-1">⚠ {errors.annotators}</p>}
          </div>

          {/* Batch mode */}
          <div className="bg-slate-50 border border-slate-200 rounded-xl p-4 space-y-4">
            <p className="text-sm font-bold text-slate-700">Batch mode:</p>

            <label className="flex items-start gap-3 cursor-pointer">
              <input type="radio" checked={!verifyMode} onChange={() => setVerifyMode(false)} className="mt-0.5" />
              <div>
                <p className="text-sm font-semibold text-slate-800">Split (round-robin)</p>
                <p className="text-xs text-slate-500 mt-0.5">Each item is annotated by exactly one person. Fast, no cross-validation.</p>
                {!verifyMode && summary && (
                  <p className="text-xs text-indigo-600 font-medium mt-1.5 bg-indigo-50 px-2 py-1 rounded">→ {summary}</p>
                )}
              </div>
            </label>

            <label className="flex items-start gap-3 cursor-pointer">
              <input type="radio" checked={verifyMode} onChange={() => setVerifyMode(true)} className="mt-0.5" />
              <div className="w-full">
                <p className="text-sm font-semibold text-slate-800">Verification (k people per item)</p>
                <p className="text-xs text-slate-500 mt-0.5">
                  Each item is reviewed by multiple people; work is distributed evenly. Conflicts are visible in Review.
                </p>
                {verifyMode && (
                  <div className="mt-2 space-y-2">
                    <div className="flex items-center gap-3 bg-white border border-amber-200 rounded-lg px-3 py-2">
                      <label className="text-xs font-semibold text-slate-700 whitespace-nowrap">Reviewers per item:</label>
                      <input
                        type="number" min={1} max={selectedAnnotators.length || 1}
                        value={verifiersPerItem}
                        onChange={(e) => setVerifiersPerItem(Math.max(1, Math.min(Number(e.target.value), selectedAnnotators.length || 1)))}
                        className="w-16 border border-amber-300 rounded px-2 py-1 text-sm font-bold text-amber-700 text-center focus:outline-none"
                      />
                      <span className="text-xs text-slate-400">of {selectedAnnotators.length || '?'} available</span>
                    </div>
                    {summary && (
                      <div className="text-xs bg-amber-50 border border-amber-200 rounded-lg p-2.5">
                        <p className="font-semibold text-amber-800 mb-0.5">📊 Workload estimate:</p>
                        <p className="text-amber-700">{summary}</p>
                      </div>
                    )}
                  </div>
                )}
              </div>
            </label>
          </div>

          <div className="flex justify-between items-center pt-2">
            <button onClick={() => setStep(2)} className="text-slate-500 text-sm font-medium hover:underline">← Back</button>
            <button
              onClick={createProject}
              disabled={saving || !projectName.trim() || !selectedAnnotators.length}
              className="btn-primary !px-8 !py-3 !text-base"
            >
              {saving ? 'Creating…' : '🚀 Launch project'}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}