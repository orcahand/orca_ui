// One SVG per finger: static circles positioned from the real taxel
// coordinates (same bounds/scale/padding math as the original
// createCoordinateSVG), plus a pre-built hidden arrow pool. Per-frame
// updates mutate attributes imperatively via useStreamFrame.

import { useEffect, useMemo, useRef } from 'react'
import type { Finger } from '../../api/types'
import { useAppStore } from '../../state/appStore'
import { useStreamFrame } from '../../hooks/useStreamFrame'
import { maxTaxelForce } from '../../theme/tokens'
import type { ArrowPoolEntry, TaxelHandles } from './taxelRender'
import { hideAllArrows, renderTaxelFrame } from './taxelRender'

const SVG_NS = 'http://www.w3.org/2000/svg'

interface Layout {
  svgWidth: number
  svgHeight: number
  points: { cx: number; cy: number }[]
}

function computeLayout(finger: Finger, positions: [number, number, number][]): Layout {
  let minX = Infinity
  let maxX = -Infinity
  let minY = Infinity
  let maxY = -Infinity
  for (const [x, y] of positions) {
    minX = Math.min(minX, x)
    maxX = Math.max(maxX, x)
    minY = Math.min(minY, y)
    maxY = Math.max(maxY, y)
  }
  const padding = 8
  const scale = finger === 'thumb' ? 7.5 : 7
  const svgWidth = (maxX - minX) * scale + padding * 2
  const svgHeight = (maxY - minY) * scale + padding * 2
  const points = positions.map(([x, y]) => ({
    cx: (x - minX) * scale + padding,
    cy: svgHeight - ((y - minY) * scale + padding), // invert Y
  }))
  return { svgWidth, svgHeight, points }
}

export function FingerTaxelSvg({
  finger,
  positions,
}: {
  finger: Finger
  positions: [number, number, number][]
}) {
  const layout = useMemo(() => computeLayout(finger, positions), [finger, positions])
  const svgRef = useRef<SVGSVGElement>(null)
  const handlesRef = useRef<TaxelHandles | null>(null)
  const lastFrameT = useRef(0)
  const taxelRadius = 5
  // This finger's sensor model reaches its own peak force; normalizing every
  // model against one number left the 87-taxel fingers stuck in dark grey.
  const maxForce = maxTaxelForce(finger)

  // Build the arrow pool once per layout; collect circle handles.
  useEffect(() => {
    const svg = svgRef.current
    if (!svg) return
    const circles = Array.from(
      svg.querySelectorAll<SVGCircleElement>('circle.taxel-circle'),
    )
    const arrowLayer = svg.querySelector<SVGGElement>('g.arrow-layer')!
    arrowLayer.replaceChildren()
    const arrows: ArrowPoolEntry[] = layout.points.map(() => {
      const group = document.createElementNS(SVG_NS, 'g')
      group.setAttribute('class', 'taxel-arrow')
      group.setAttribute('visibility', 'hidden')
      const line = document.createElementNS(SVG_NS, 'line')
      line.setAttribute('stroke-linecap', 'round')
      const head = document.createElementNS(SVG_NS, 'polygon')
      group.appendChild(line)
      group.appendChild(head)
      arrowLayer.appendChild(group)
      return { group, line, head }
    })
    handlesRef.current = { circles, arrows, positions: layout.points }
    return () => {
      handlesRef.current = null
    }
  }, [layout])

  useStreamFrame((frames) => {
    const handles = handlesRef.current
    if (!handles) return
    const taxels = frames.tactile.taxels?.[finger]
    if (!taxels || frames.tactile.tTaxels === lastFrameT.current) return
    lastFrameT.current = frames.tactile.tTaxels
    // Transient read: settings changes don't re-render the SVG tree.
    const settings = useAppStore.getState().tactile
    if (settings.displayMode !== 'arrows') hideAllArrows(handles)
    renderTaxelFrame(handles, taxels, settings, maxForce)
  })

  return (
    <div className="taxel-finger" data-finger={finger}>
      <div className="taxel-finger-label">
        {finger.charAt(0).toUpperCase() + finger.slice(1)}
      </div>
      <svg
        ref={svgRef}
        className="taxel-svg"
        viewBox={`0 0 ${layout.svgWidth} ${layout.svgHeight}`}
        width={layout.svgWidth}
        height={layout.svgHeight}
      >
        {layout.points.map((point, index) => (
          <circle
            key={index}
            className="taxel-circle"
            cx={point.cx}
            cy={point.cy}
            r={taxelRadius}
            fill="#1a1a1a"
            stroke="#2a2a2a"
            strokeWidth={0.5}
          />
        ))}
        <g className="arrow-layer" />
      </svg>
    </div>
  )
}
