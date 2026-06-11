/**
 * Batch assignment logic.
 *
 * Round-robin: each item goes to exactly one annotator.
 * Verification: each item is reviewed by k annotators; load is distributed
 *   evenly using a greedy min-load assignment.
 */
export function buildBatches(itemIds, annotators, verifyMode, verifiersPerItem = 2) {
  const a = annotators.length
  if (a === 0) return {}

  const batches = Object.fromEntries(annotators.map((ann) => [ann, []]))

  if (!verifyMode) {
    itemIds.forEach((id, i) => batches[annotators[i % a]].push(id))
    return batches
  }

  const k = Math.min(verifiersPerItem, a)
  const load = Object.fromEntries(annotators.map((ann) => [ann, 0]))

  itemIds.forEach((id) => {
    const chosen = [...annotators].sort((x, y) => load[x] - load[y]).slice(0, k)
    chosen.forEach((ann) => { batches[ann].push(id); load[ann]++ })
  })

  return batches
}

/** Summary string shown in the UI. */
export function batchSummary(itemCount, annotators, verifyMode, verifiersPerItem) {
  const a = annotators.length
  if (!a) return null
  if (!verifyMode) {
    return `~${Math.ceil(itemCount / a)} items/person · ${itemCount} total · ${a} people`
  }
  const k = Math.min(verifiersPerItem, a)
  const total = itemCount * k
  const base = Math.floor(total / a)
  const extra = total % a
  return `${itemCount} items × ${k} people = ${total} annotations · ` +
    (extra > 0
      ? `${extra} person(s) with ${base + 1}, ${a - extra} person(s) with ${base}`
      : `${a} people with ${base} each`)
}
