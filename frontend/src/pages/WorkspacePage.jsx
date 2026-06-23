import { useState, useEffect, useCallback, useRef } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import ItemDisplay from "../components/ItemDisplay";
import TagSearch from "../components/TagSearch";

const isMac = typeof navigator !== "undefined" && /Mac/.test(navigator.platform || "");
const modKey = (k) => (isMac ? `⌘${k}` : `Ctrl+${k}`);

const PREFETCH_AHEAD = 3;

export default function WorkspacePage() {
  const { sessionId } = useParams();
  const navigate = useNavigate();
  const { user, isAdmin } = useAuth();
  const { t } = useTranslation();

  const [session, setSession] = useState(null);
  const [annotator, setAnnotator] = useState(null);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [currentItem, setCurrentItem] = useState(null);
  const [selectedLabels, setSelectedLabels] = useState([]);
  const [progress, setProgress] = useState({});
  const [saving, setSaving] = useState(false);

  // ── Pre-fetch cache & re-entrancy guard ──
  const cacheRef = useRef(new Map()); // itemId → { item, labels }
  const labeledSetRef = useRef(new Set()); // itemIds with non-empty labels
  const savingRef = useRef(false);
  const tagSearchRef = useRef(null);

  // Clear cache when annotator or session changes
  useEffect(() => {
    cacheRef.current.clear();
    labeledSetRef.current.clear();
  }, [sessionId, annotator]);

  // ── Initialise session ──
  useEffect(() => {
    const init = async () => {
      try {
        const s = await api.get(`/api/sessions/${sessionId}`);
        setSession(s);
        const ann = isAdmin
          ? s.annotators.includes(user.username)
            ? user.username
            : s.annotators[0]
          : user.username;
        setAnnotator(ann);

        const batch = s.batches?.[ann] ?? [];
        if (batch.length > 0) {
          const saved = await api.get(`/api/labels/${sessionId}/${ann}`);
          // Pre-warm cache with just labels (items fetched on demand)
          for (const [id, labels] of Object.entries(saved)) {
            cacheRef.current.set(id, { item: null, labels });
            if (labels && labels.length > 0) {
              labeledSetRef.current.add(id);
            }
          }
          const resumeIdx = batch.findIndex(
            (id) => !saved[id] || saved[id].length === 0,
          );
          setCurrentIndex(resumeIdx === -1 ? batch.length - 1 : resumeIdx);
        }
      } catch {
        navigate("/");
      }
    };
    init();
  }, [sessionId]);

  // ── Item loading + pre-fetch ──
  const fetchItemAndLabels = useCallback(
    async (itemId) => {
      try {
        const [item, saved] = await Promise.all([
          api.get(`/api/items/${itemId}`),
          api.get(`/api/labels/${sessionId}/${annotator}`),
        ]);
        cacheRef.current.set(itemId, { item, labels: saved[itemId] ?? [] });
        return { item, labels: saved[itemId] ?? [] };
      } catch {
        return null;
      }
    },
    [sessionId, annotator],
  );

  const preFetchBackground = useCallback(
    (itemId) => {
      if (cacheRef.current.has(itemId)) return;
      api.get(`/api/items/${itemId}`)
        .then((item) => {
          // Only cache the item; labels come from the all-labels fetch
          const existing = cacheRef.current.get(itemId);
          cacheRef.current.set(itemId, {
            item,
            labels: existing?.labels ?? [],
          });
        })
        .catch(() => {});
    },
    [],
  );

  useEffect(() => {
    if (!session || !annotator) return;
    const batch = session.batches?.[annotator] ?? [];
    if (batch.length === 0) return;

    const idx = Math.min(currentIndex, batch.length - 1);
    const itemId = batch[idx];

    const cached = cacheRef.current.get(itemId);
    if (cached?.item) {
      // Cache hit — instant display
      setCurrentItem(cached.item);
      setSelectedLabels(cached.labels);
    } else {
      // Cache miss — fetch now
      setCurrentItem(null);
      fetchItemAndLabels(itemId).then((result) => {
        if (result) {
          setCurrentItem(result.item);
          setSelectedLabels(result.labels);
        }
      });
    }

    // Pre-fetch upcoming items in background
    for (let i = 1; i <= PREFETCH_AHEAD; i++) {
      const nextIdx = idx + i;
      if (nextIdx < batch.length) {
        preFetchBackground(batch[nextIdx]);
      }
    }
  }, [session, annotator, currentIndex, fetchItemAndLabels, preFetchBackground]);

  // ── Progress (fetch once on mount, then after each save) ──
  const loadProgress = useCallback(async () => {
    try {
      const p = await api.get(`/api/sessions/${sessionId}/progress`);
      setProgress(p);
    } catch {
      /* non-critical */
    }
  }, [sessionId]);

  useEffect(() => {
    if (session) loadProgress();
  }, [session, loadProgress]);

  // ── Keyboard shortcuts (stable refs for callbacks) ──
  const saveAndNavigateRef = useRef(null);

  const saveAndNavigate = useCallback(
    async (skip = false) => {
      if (!session || !annotator || savingRef.current) return;
      savingRef.current = true;
      setSaving(true);

      const batch = session.batches?.[annotator] ?? [];
      const itemId = batch[currentIndex];

      try {
        await api.post(`/api/labels/${sessionId}/${annotator}`, {
          body: { [itemId]: skip ? [] : selectedLabels },
        });
      } catch (e) {
        console.error(e);
      }

      savingRef.current = false;
      setSaving(false);

      // Update cache with saved labels (other items' labels are unaffected)
      const existing = cacheRef.current.get(itemId);
      cacheRef.current.set(itemId, {
        item: currentItem ?? existing?.item,
        labels: skip ? [] : selectedLabels,
      });

      // Track labeled status for the button indicators
      if (skip || !selectedLabels.length) {
        labeledSetRef.current.delete(itemId);
      } else {
        labeledSetRef.current.add(itemId);
      }

      await loadProgress();

      if (currentIndex < batch.length - 1) {
        setCurrentIndex((i) => i + 1);
      } else {
        alert(t("workspace.batchComplete"));
        navigate("/");
      }
    },
    [session, annotator, currentIndex, selectedLabels, currentItem, sessionId, navigate, t, loadProgress],
  );

  saveAndNavigateRef.current = saveAndNavigate;

  useEffect(() => {
    const handler = (e) => {
      const tag = document.activeElement?.tagName;
      const isInput = tag === "INPUT" || tag === "TEXTAREA" || document.activeElement?.isContentEditable;

      const mod = e.metaKey || e.ctrlKey;
      const batch = session?.batches?.[annotator] ?? [];

      if (e.key === "Enter" && mod && !e.shiftKey) {
        // Ctrl+Enter / ⌘Enter → Save & Next (works even when input focused)
        e.preventDefault();
        saveAndNavigateRef.current?.(false);
      } else if (e.key === "Enter" && mod && e.shiftKey) {
        // Ctrl+Shift+Enter / ⌘⇧Enter → Skip
        e.preventDefault();
        saveAndNavigateRef.current?.(true);
      } else if (e.key === "/" && !mod && !isInput) {
        // Slash → focus the label search (like Gmail / Slack)
        e.preventDefault();
        tagSearchRef.current?.focus();
      } else if (e.key === "Escape" && isInput) {
        // Escape → blur the label search (so shortcuts work again)
        e.preventDefault();
        tagSearchRef.current?.blur();
      } else if (isInput) {
        // Don't steal arrow keys from input fields
        return;
      } else if (e.key === "ArrowRight" && !mod) {
        e.preventDefault();
        if (currentIndex < batch.length - 1) {
          setCurrentIndex((i) => i + 1);
        }
      } else if (e.key === "ArrowLeft" && !mod) {
        e.preventDefault();
        if (currentIndex > 0) setCurrentIndex((i) => i - 1);
      }
    };

    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [session, annotator, currentIndex]);

  // ── Render ──
  if (!session || !annotator) {
    return (
      <div className="flex items-center justify-center h-64 text-slate-400">
        {t("workspace.loading")}
      </div>
    );
  }

  const batch = session.batches?.[annotator] ?? [];
  const ann_progress = progress[annotator] ?? {
    labeled: 0,
    total: batch.length,
    pct: 0,
  };
  const taxonomy = session.taxonomy ?? [];

  return (
    <div className="space-y-4">
      <div className="card !py-3 flex flex-col sm:flex-row gap-4 items-center justify-between">
        <div className="flex items-center gap-3">
          <label className="text-xs font-bold text-slate-600 uppercase tracking-wide">
            {t("workspace.user")}
          </label>
          {isAdmin ? (
            <select
              value={annotator}
              onChange={async (e) => {
                const ann = e.target.value;
                setAnnotator(ann);
                const batch = session.batches?.[ann] ?? [];
                if (batch.length > 0) {
                  const saved = await api.get(
                    `/api/labels/${sessionId}/${ann}`,
                  );
                  cacheRef.current.clear();
                  labeledSetRef.current.clear();
                  for (const [id, labels] of Object.entries(saved)) {
                    cacheRef.current.set(id, { item: null, labels });
                    if (labels && labels.length > 0) {
                      labeledSetRef.current.add(id);
                    }
                  }
                  const resumeIdx = batch.findIndex(
                    (id) => !saved[id] || saved[id].length === 0,
                  );
                  setCurrentIndex(
                    resumeIdx === -1 ? batch.length - 1 : resumeIdx,
                  );
                } else {
                  setCurrentIndex(0);
                }
              }}
              className="bg-indigo-50 border border-indigo-200 rounded-lg px-3 py-1.5 text-sm font-bold text-indigo-700 focus:outline-none"
            >
              {session.annotators.map((a) => (
                <option key={a} value={a}>
                  {a}
                </option>
              ))}
            </select>
          ) : (
            <span className="bg-indigo-100 text-indigo-800 font-bold text-sm px-3 py-1.5 rounded-lg">
              {annotator}
            </span>
          )}
          <span className="text-xs text-slate-400">
            {currentIndex + 1} / {batch.length}
          </span>
        </div>

        <div className="w-full sm:w-1/3 space-y-1">
          <div className="flex justify-between text-xs font-semibold text-slate-500">
            <span>{t("workspace.progress")}</span>
            <span>
              {ann_progress.labeled}/{ann_progress.total} ({ann_progress.pct}%)
            </span>
          </div>
          <div className="w-full bg-slate-100 rounded-full h-2.5 overflow-hidden">
            <div
              className="progress-bar h-full"
              style={{ width: `${ann_progress.pct}%` }}
            />
          </div>
        </div>

        {(isAdmin ||
          ["owner", "maintainer"].includes(session?.current_user_role)) && (
          <button
            onClick={() => navigate(`/review/${sessionId}`)}
            className="btn-secondary whitespace-nowrap !text-xs"
          >
            Review →
          </button>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
        <div
          className="lg:col-span-7 card flex flex-col gap-3"
          style={{ minHeight: "540px" }}
        >
          <div className="flex-1 overflow-hidden">
            <ItemDisplay
              item={currentItem}
              displayColumns={session.display_columns}
            />
          </div>
          <div className="border-t pt-3 flex gap-1 flex-wrap justify-center max-h-16 overflow-y-auto">
            {batch
              .slice(Math.max(0, currentIndex - 10), currentIndex + 11)
              .map((_, relIdx) => {
                const absIdx = Math.max(0, currentIndex - 10) + relIdx;
                const itemId = batch[absIdx];
                const isLabeled = labeledSetRef.current.has(itemId);
                return (
                  <button
                    key={absIdx}
                    onClick={() => setCurrentIndex(absIdx)}
                    className={`w-7 h-7 rounded text-xs font-bold transition
                    ${absIdx === currentIndex
                      ? "bg-indigo-600 text-white"
                      : isLabeled
                        ? "bg-emerald-100 text-emerald-700 border border-emerald-300"
                        : "bg-slate-100 text-slate-500 hover:bg-slate-200"}`}
                  >
                    {absIdx + 1}
                  </button>
                );
              })}
          </div>
        </div>

        <div className="lg:col-span-5 card flex flex-col gap-4">
          <div>
            <h3 className="text-xs font-bold uppercase tracking-wider text-slate-600 mb-0.5">
              🏷️ {t("workspace.classify")}
            </h3>
            {currentItem && (
              <p className="text-xs text-slate-400 truncate">
                {currentItem.name}
              </p>
            )}
          </div>

          <div className="flex-1">
            <TagSearch
              ref={tagSearchRef}
              key={batch[currentIndex]}
              taxonomy={taxonomy}
              selected={selectedLabels}
              onChange={setSelectedLabels}
            />
          </div>

          <div className="space-y-2 border-t pt-4">
            <div className="flex gap-2">
              <button
                onClick={() =>
                  currentIndex > 0 && setCurrentIndex((i) => i - 1)
                }
                disabled={currentIndex === 0}
                className="btn-secondary flex-1 justify-center"
                title="← Arrow Left"
              >
                {t("workspace.back")}
              </button>
              <button
                onClick={() => saveAndNavigate(true)}
                disabled={saving}
                className="px-3 bg-amber-50 hover:bg-amber-100 text-amber-700 rounded-lg text-sm font-medium transition border border-amber-200"
                title={`${modKey("Shift+Enter")} — Skip`}
              >
                ⏭
              </button>
              <button
                onClick={() => saveAndNavigate(false)}
                disabled={saving}
                className="btn-primary flex-[2] justify-center"
                title={`${modKey("Enter")} — Save & Next`}
              >
                {saving
                  ? "…"
                  : selectedLabels.length
                    ? t("workspace.saveNext")
                    : t("workspace.next")}
              </button>
            </div>
            {!selectedLabels.length && (
              <p className="text-xs text-slate-400 text-center">
                {t("workspace.noTagHint")}
              </p>
            )}
            <details className="text-[10px] text-slate-400">
              <summary className="cursor-pointer hover:text-slate-500">⌨ Keyboard shortcuts</summary>
              <div className="mt-1.5 grid grid-cols-2 gap-x-3 gap-y-0.5 bg-slate-50 rounded-lg p-2 border">
                <kbd className="font-mono text-slate-600">{modKey("Enter")}</kbd>
                <span>Save &amp; next</span>
                <kbd className="font-mono text-slate-600">{modKey("Shift+Enter")}</kbd>
                <span>Skip (no label)</span>
                <kbd className="font-mono text-slate-600">/</kbd>
                <span>Focus label search</span>
                <kbd className="font-mono text-slate-600">←</kbd>
                <span>Previous item</span>
                <kbd className="font-mono text-slate-600">→</kbd>
                <span>Next item</span>
              </div>
            </details>
          </div>
        </div>
      </div>
    </div>
  );
}
