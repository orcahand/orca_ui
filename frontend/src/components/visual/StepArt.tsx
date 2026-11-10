// A step's line drawing (art/*.svg, made by art/build_art.py from the rig's
// real geometry). Inlined rather than an <img>, so the theme colours the lines.

import { useEffect, useState } from 'react'
import type { Art } from './instructions'

const LOADERS = import.meta.glob<string>('./art/*.svg', { query: '?raw', import: 'default' })
const cache = new Map<Art, string>()

export function StepArt({ art }: { art: Art }) {
  const [svg, setSvg] = useState(() => cache.get(art) ?? null)
  useEffect(() => {
    let alive = true
    const hit = cache.get(art)
    if (hit) {
      setSvg(hit)
      return
    }
    setSvg(null)
    void LOADERS[`./art/${art}.svg`]?.().then((s) => {
      cache.set(art, s)
      if (alive) setSvg(s)
    })
    return () => {
      alive = false
    }
  }, [art])
  return <div className="visual-cal-art" dangerouslySetInnerHTML={svg ? { __html: svg } : undefined} />
}
