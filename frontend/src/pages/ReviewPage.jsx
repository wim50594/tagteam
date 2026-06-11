import { useState, useEffect } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import ItemDisplay from "../components/ItemDisplay";

export default function ReviewPage() {
  const { sessionId } = useParams();
  const navigate = useNavigate();
  const [session, setSession] = useState(null);
  const [progress, setProgress] = useState({});
  const [conflicts, setConflicts] = useState([]);
  const [exportMode, setExportMode] = useState("raw");
  const [modalItem, setModalItem] = useState(null);
  const [modalItemData, setModalItemData] = useState(null);
  const [modalSelected, setModalSelected] = useState([]);

  useEffect(() => {
    load();
  }, [sessionId]);

  const load = async () => {
    const [s, p] = await Promise.all([
      api.get(`/api/sessions/${sessionId}`),
      api.get(`/api/sessions/${sessionId}/progress`),
    ]);
    setSession(s);
    if (!s.verification_mode) setExportMode("raw");
    setProgress(p);
    if (s.verification_mode) {
      const c = await api.get(`/api/sessions/${sessionId}/conflicts`);
      setConflicts(c.conflicts ?? []);
    }
  };

  const openModal = async (c) => {
    setModalItem(c);
    setModalSelected(c.final_labels ?? []);
    setModalItemData(null);
    try {
      const itemData = await api.get(`/api/items/${c.item_id}`);
      setModalItemData(itemData);
    } catch {
      /* non-critical, fallback to name */
    }
  };

  const saveResolution = async () => {
    await api.post(`/api/sessions/${sessionId}/resolve`, {
      body: { item_id: modalItem.item_id, final_labels: modalSelected },
    });
    setModalItem(null);
    setModalItemData(null);
    load();
  };

  const downloadExport = async () => {
    const res = await api.get(`/api/sessions/${sessionId}/export`, {
      params: { mode: exportMode },
    });
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `multitag_${sessionId.slice(0, 8)}_${exportMode}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  if (!session)
    return (
      <div className="flex items-center justify-center h-64 text-slate-400">
        Loading…
      </div>
    );

  const allChoices = modalItem
    ? [...new Set(modalItem.details.flatMap((d) => d.labels))]
    : [];
  const openConflicts = conflicts.filter((c) => !c.resolved);
  const resolvedConflicts = conflicts.filter((c) => c.resolved);
  const canMerge = session.verification_mode && !openConflicts.length;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="card space-y-5">
        <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 border-b pb-4">
          <div>
            <h1 className="text-xl font-black text-slate-900">
              Review & Export
            </h1>
            <p className="text-sm text-slate-500">{session.name}</p>
          </div>
          <div className="flex items-center gap-3 flex-wrap">
            <select
              value={exportMode}
              onChange={(e) => setExportMode(e.target.value)}
              className="input-base !w-auto"
            >
              <option value="raw">Raw (per annotator)</option>
              <option value="merged" disabled={!canMerge}>
                Merged (consolidated)
              </option>
            </select>
            {session.verification_mode && !canMerge && (
              <span className="text-xs text-amber-600 font-bold whitespace-nowrap">
                ⚠ {openConflicts.length} open conflict
                {openConflicts.length !== 1 ? "s" : ""}
              </span>
            )}
            <button
              onClick={downloadExport}
              className="btn-primary bg-emerald-600 hover:bg-emerald-700"
            >
              Export CSV 📥
            </button>
          </div>
        </div>

        {/* Progress per annotator */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {Object.entries(progress).map(([ann, stat]) => (
            <div
              key={ann}
              className="bg-slate-50 border border-slate-200 rounded-xl p-4"
            >
              <div className="flex justify-between items-center mb-2">
                <span className="font-bold text-slate-800 text-sm">{ann}</span>
                <span className="text-xs font-bold text-indigo-600">
                  {stat.pct}%
                </span>
              </div>
              <div className="w-full bg-slate-200 rounded-full h-2 overflow-hidden mb-1">
                <div
                  className="progress-bar h-full"
                  style={{ width: `${stat.pct}%` }}
                />
              </div>
              <p className="text-xs text-slate-500">
                {stat.labeled} of {stat.total} annotated
              </p>
            </div>
          ))}
        </div>

        {/* Conflicts – only shown in verification mode */}
        {session.verification_mode && (
          <div className="border-t pt-5 space-y-3">
            <h3 className="text-sm font-bold text-slate-700 flex items-center gap-2">
              ⚡ Conflicts
              {openConflicts.length > 0 && (
                <span className="bg-red-100 text-red-700 px-2 py-0.5 rounded-full text-xs font-bold">
                  {openConflicts.length} open
                </span>
              )}
              {resolvedConflicts.length > 0 && (
                <span className="bg-emerald-100 text-emerald-700 px-2 py-0.5 rounded-full text-xs font-bold">
                  {resolvedConflicts.length} resolved
                </span>
              )}
            </h3>
            {conflicts.length === 0 ? (
              <div className="border-2 border-dashed border-slate-200 rounded-xl p-8 text-center text-slate-400 text-sm">
                No conflicts found ✅
              </div>
            ) : (
              <div className="border border-slate-200 rounded-xl overflow-hidden">
                <table className="w-full text-xs">
                  <thead className="bg-slate-50 border-b">
                    <tr>
                      {["Item", "Type", "Submissions", "Status", ""].map(
                        (h) => (
                          <th
                            key={h}
                            className="text-left p-3 font-bold text-slate-500"
                          >
                            {h}
                          </th>
                        ),
                      )}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {conflicts.map((c) => (
                      <tr
                        key={c.item_id}
                        className={`hover:bg-slate-50 transition ${c.resolved ? "opacity-60" : ""}`}
                      >
                        <td className="p-3 font-mono text-indigo-600 font-bold max-w-[160px] truncate">
                          {c.name?.substring(0, 30) ||
                            c.item_id.substring(0, 8) + "…"}
                        </td>
                        <td className="p-3 text-slate-500">{c.type}</td>
                        <td className="p-3 space-y-0.5">
                          {c.details.map((d) => (
                            <div key={d.annotator}>
                              <b>{d.annotator}:</b>{" "}
                              {d.labels.length ? (
                                d.labels.slice(0, 2).join(", ") +
                                (d.labels.length > 2 ? "…" : "")
                              ) : (
                                <em>none</em>
                              )}
                            </div>
                          ))}
                        </td>
                        <td className="p-3">
                          {c.resolved ? (
                            <span className="bg-emerald-100 text-emerald-700 px-2 py-0.5 rounded font-bold">
                              ✅ Resolved
                            </span>
                          ) : (
                            <span className="bg-amber-100 text-amber-700 px-2 py-0.5 rounded font-bold">
                              ⚠ Open
                            </span>
                          )}
                        </td>
                        <td className="p-3">
                          <button
                            onClick={() => openModal(c)}
                            className="btn-secondary !text-xs !px-2.5 !py-1"
                          >
                            Resolve
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}
      </div>

      <button
        onClick={() => navigate(`/workspace/${sessionId}`)}
        className="text-indigo-600 text-sm font-semibold hover:underline"
      >
        ← Back to workspace
      </button>

      {/* ── Conflict modal ── */}
      {modalItem && (
        <div className="fixed inset-0 bg-slate-900/60 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl shadow-2xl max-w-lg w-full overflow-hidden">
            <div className="bg-slate-900 text-white px-6 py-4 flex justify-between items-center">
              <h3 className="font-bold">Resolve conflict</h3>
              <button
                onClick={() => {
                  setModalItem(null);
                  setModalItemData(null);
                }}
                className="text-slate-400 hover:text-white text-2xl leading-none"
              >
                ×
              </button>
            </div>
            <div className="p-6 space-y-4">
              {/* Item preview */}
              <div
                className="border rounded-xl overflow-hidden bg-slate-50"
                style={{ minHeight: "180px", maxHeight: "280px" }}
              >
                <ItemDisplay
                  item={modalItemData}
                  displayColumns={session?.display_columns}
                />
              </div>

              {/* Submissions summary */}
              <div className="bg-slate-50 rounded-lg p-3 space-y-1 border">
                {modalItem.details.map((d) => (
                  <div key={d.annotator} className="text-xs">
                    <span className="font-bold text-slate-700">
                      {d.annotator}:
                    </span>{" "}
                    {d.labels.join(", ") || (
                      <em className="text-slate-400">no labels</em>
                    )}
                  </div>
                ))}
              </div>

              {/* Final tag selection */}
              <div>
                <div className="flex items-center justify-between mb-2">
                  <p className="text-xs font-bold text-slate-500 uppercase tracking-wide">
                    Select final tags:
                  </p>
                  <div className="flex gap-1.5">
                    <button
                      onClick={() => setModalSelected([...allChoices])}
                      className="text-xs bg-indigo-50 hover:bg-indigo-100 text-indigo-700 font-semibold px-2.5 py-1 rounded-lg border border-indigo-200 transition"
                    >
                      Select all
                    </button>
                    <button
                      onClick={() => setModalSelected([])}
                      className="text-xs bg-slate-100 hover:bg-slate-200 text-slate-600 font-semibold px-2.5 py-1 rounded-lg transition"
                    >
                      Clear
                    </button>
                  </div>
                </div>
                <div className="space-y-1.5 max-h-52 overflow-y-auto">
                  {allChoices.map((lbl) => (
                    <label
                      key={lbl}
                      className="flex items-center gap-2.5 bg-slate-50 p-2.5 border rounded-lg cursor-pointer hover:border-indigo-300 text-xs font-medium transition"
                    >
                      <input
                        type="checkbox"
                        checked={modalSelected.includes(lbl)}
                        onChange={(e) =>
                          e.target.checked
                            ? setModalSelected([...modalSelected, lbl])
                            : setModalSelected(
                                modalSelected.filter((x) => x !== lbl),
                              )
                        }
                        className="h-4 w-4 text-indigo-600 rounded"
                      />
                      {lbl}
                    </label>
                  ))}
                </div>
              </div>
            </div>
            <div className="bg-slate-50 px-6 py-3 border-t flex justify-end gap-2">
              <button
                onClick={() => {
                  setModalItem(null);
                  setModalItemData(null);
                }}
                className="btn-secondary"
              >
                Cancel
              </button>
              <button onClick={saveResolution} className="btn-primary">
                Save resolution
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
