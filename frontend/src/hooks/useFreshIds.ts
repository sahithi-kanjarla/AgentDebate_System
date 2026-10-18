import { useState } from 'react'
import type { GraphModel } from '../lib/graphModel'

function signatures(model: GraphModel): Map<string, string> {
  const out = new Map<string, string>()
  for (const n of model.nodes) out.set(n.id, `${n.status}|${n.changedMind}`)
  for (const e of model.edges) out.set(e.id, 'edge')
  return out
}

/**
 * Ids that appeared or changed since the previous model, so only they animate. The first model seen
 * is the baseline (a finished debate, or the first batch of a replay) and animates nothing; with
 * `enabled` false nothing ever does. State, not a ref, so this is safe to read while rendering.
 */
export function useFreshIds(model: GraphModel, enabled: boolean): ReadonlySet<string> {
  const [track, setTrack] = useState(() => ({
    model,
    sigs: signatures(model),
    fresh: new Set<string>() as ReadonlySet<string>,
  }))
  if (track.model !== model) {
    const sigs = signatures(model)
    const fresh = new Set<string>()
    if (enabled) for (const [id, sig] of sigs) if (track.sigs.get(id) !== sig) fresh.add(id)
    setTrack({ model, sigs, fresh })
    return fresh
  }
  return track.fresh
}
