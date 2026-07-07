// Palette mirror for canvas/three/uPlot consumers (theme.css is the CSS side).

export const COLORS = {
  bg: '#1a1c2a',
  text: '#dfe3e8',
  muted: '#9faab9',
  dim: '#7f8ea2',
  dimmer: '#5f718b',
  accent: '#22d3ee',
  ok: '#34d399',
  warn: '#c8a870',
  err: '#d4878a',
  purple: '#a78bfa',
  taxelIdle: '#1a1a1a',
} as const

// ORCA gradient stops (getArrowColor2D 'orca' scheme): #474f5e → #e5e7eb
export const ORCA_GRADIENT: [number, number, number][] = [
  [71, 79, 94],
  [127, 142, 162],
  [191, 199, 209],
  [229, 231, 235],
]

export const MAX_TAXEL_FORCE = 25 // N; fz is an unsigned byte * 0.1 N = 25.5 N
export const MAX_FORCE_SCALE = 10 // N; resultant dial normalization
