// Faithful port of the original static/script.js taxel pixel math
// (updateTaxels / updateTaxelArrow / getArrowColor2D, lines 464–650).
// Same constants, same formulas; the only structural change is that arrows
// come from a pre-built pool (visibility toggling) instead of per-frame
// create/remove.

import type { Vec3 } from '../../api/types'
import type { ArrowColorScheme, TactileSettings } from '../../state/appStore'
import { palette } from '../../theme/palette'

export interface TaxelHandles {
  circles: SVGCircleElement[]
  arrows: ArrowPoolEntry[]
  positions: { cx: number; cy: number }[]
}

export interface ArrowPoolEntry {
  group: SVGGElement
  line: SVGLineElement
  head: SVGPolygonElement
}

// Shared by the 2D taxel arrows and the 3D fingertip arrows, so both read
// the same scheme off the same palette and can never disagree about which
// way "more force" points.
export function getArrowColor2D(
  scheme: ArrowColorScheme,
  normalized: number,
): string {
  const { arrows } = palette()
  switch (scheme) {
    case 'intensity': {
      // Pure lightness, so this is the one scheme that genuinely inverts:
      // it climbs toward white on black and falls toward ink on paper.
      const { intensityFrom: from, intensityTo: to } = arrows
      const l = Math.round(from + normalized * (to - from))
      return `hsl(0, 0%, ${l}%)`
    }
    case 'orca': {
      const stops = arrows.orca
      const scaled = normalized * (stops.length - 1)
      const idx = Math.min(Math.floor(scaled), stops.length - 2)
      const frac = scaled - idx
      const r = Math.round(stops[idx][0] + (stops[idx + 1][0] - stops[idx][0]) * frac)
      const g = Math.round(stops[idx][1] + (stops[idx + 1][1] - stops[idx][1]) * frac)
      const b = Math.round(stops[idx][2] + (stops[idx + 1][2] - stops[idx][2]) * frac)
      return `rgb(${r}, ${g}, ${b})`
    }
    default: {
      // 'heat' — blue to red by hue. The hue *is* the reading, so it needs no
      // inversion at all; only the lightness band moves, a notch darker on
      // paper so a mid-ramp cyan still holds against the page.
      const hue = (1 - normalized) * 240
      const { heatSatFrom, heatSatTo, heatLightFrom, heatLightTo } = arrows
      const saturation = heatSatFrom + normalized * (heatSatTo - heatSatFrom)
      const lightness = heatLightFrom + normalized * (heatLightTo - heatLightFrom)
      return `hsl(${hue}, ${saturation}%, ${lightness}%)`
    }
  }
}

export function renderTaxelFrame(
  handles: TaxelHandles,
  taxels: Vec3[],
  settings: TactileSettings,
  maxForce: number,
): void {
  const { taxel, direction } = palette()
  const threshold = settings.thresholdEnabled ? settings.threshold : 0
  const n = Math.min(taxels.length, handles.circles.length)

  for (let i = 0; i < n; i++) {
    const circle = handles.circles[i]
    const [fx, fy, fz] = taxels[i]
    const magnitude = Math.sqrt(fx * fx + fy * fy + fz * fz)

    if (settings.displayMode !== 'arrows') {
      hideArrow(handles.arrows[i])
    }

    // Below threshold: reset to idle and skip.
    if (threshold > 0 && magnitude < threshold) {
      circle.setAttribute('fill', taxel.idle)
      if (settings.displayMode === 'arrows') hideArrow(handles.arrows[i])
      continue
    }

    if (settings.displayMode === 'arrows') {
      circle.setAttribute('fill', taxel.idleArrows)
      renderArrow(
        handles.arrows[i],
        handles.positions[i],
        fx, fy, fz,
        magnitude,
        settings,
        maxForce,
      )
    } else if (settings.displayMode === 'direction') {
      const absX = Math.abs(fx)
      const absY = Math.abs(fy)
      let color = taxel.idle
      if (magnitude >= 0.1) {
        const alpha = Math.min(magnitude / maxForce, 1)
        // Alpha, not lightness, carries the magnitude here — which already
        // reads the right way round on either ground (pale at rest,
        // saturated under load), so only the four hues are re-picked.
        const opacity = 0.3 + alpha * 0.7
        const [r, g, b] =
          absX > absY
            ? fx > 0 ? direction.posX : direction.negX
            : fy > 0 ? direction.posY : direction.negY
        color = `rgba(${r}, ${g}, ${b}, ${opacity})`
      }
      circle.setAttribute('fill', color)
    } else {
      // magnitude: a straight ramp between the palette's two endpoints.
      // Dark runs near-black -> white (force adds light); light runs pale ->
      // ink (force adds ink). Same span, so a given force sits at the same
      // point along the ramp in either theme.
      const t = Math.min(magnitude / maxForce, 1)
      const [r0, g0, b0] = taxel.rampFrom
      const [r1, g1, b1] = taxel.rampTo
      const r = Math.round(r0 + (r1 - r0) * t)
      const g = Math.round(g0 + (g1 - g0) * t)
      const b = Math.round(b0 + (b1 - b0) * t)
      circle.setAttribute('fill', `rgb(${r}, ${g}, ${b})`)
    }
  }
}

export function hideArrow(entry: ArrowPoolEntry | undefined): void {
  if (entry && entry.group.getAttribute('visibility') !== 'hidden') {
    entry.group.setAttribute('visibility', 'hidden')
  }
}

export function hideAllArrows(handles: TaxelHandles): void {
  for (const entry of handles.arrows) hideArrow(entry)
}

function renderArrow(
  entry: ArrowPoolEntry,
  position: { cx: number; cy: number },
  fx: number,
  fy: number,
  fz: number,
  magnitude: number,
  settings: TactileSettings,
  maxForce: number,
): void {
  // Same gating as the original: tiny forces draw nothing.
  if (magnitude < 0.1) {
    hideArrow(entry)
    return
  }

  const { cx, cy } = position
  const normalized = Math.min(magnitude / maxForce, 1)
  const xyMag = Math.sqrt(fx * fx + fy * fy)

  const baseLength = (4 + normalized * 10) * settings.lengthMult
  const zFactor = 1 + (Math.abs(fz) / maxForce) * 0.5
  const arrowLength = baseLength * (xyMag > 0.1 ? 1 : 0.3) * zFactor

  let angle = 0
  if (xyMag > 0.1) {
    angle = Math.atan2(-fy, fx) // SVG Y is down
  }

  const endX = cx + Math.cos(angle) * arrowLength
  const endY = cy + Math.sin(angle) * arrowLength
  const color = getArrowColor2D(settings.colorScheme, normalized)

  entry.group.setAttribute('visibility', 'visible')
  entry.line.setAttribute('x1', String(cx))
  entry.line.setAttribute('y1', String(cy))
  entry.line.setAttribute('x2', String(endX))
  entry.line.setAttribute('y2', String(endY))
  entry.line.setAttribute('stroke', color)
  entry.line.setAttribute(
    'stroke-width',
    String((2 + normalized * 2.5) * settings.thicknessMult),
  )

  if (arrowLength > 4) {
    const headLength = (3 + normalized * 3) * settings.thicknessMult
    const headAngle = 0.6 // rad, ~35 deg
    const head1X = endX - Math.cos(angle - headAngle) * headLength
    const head1Y = endY - Math.sin(angle - headAngle) * headLength
    const head2X = endX - Math.cos(angle + headAngle) * headLength
    const head2Y = endY - Math.sin(angle + headAngle) * headLength
    entry.head.setAttribute(
      'points',
      `${endX},${endY} ${head1X},${head1Y} ${head2X},${head2Y}`,
    )
    entry.head.setAttribute('fill', color)
    entry.head.setAttribute('visibility', 'visible')
  } else {
    entry.head.setAttribute('visibility', 'hidden')
  }
}
