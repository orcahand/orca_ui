// JS mirror of theme.css, for the renderers CSS can't reach: the taxel SVG
// heatmaps, the three.js scene, and the uPlot sparklines. Every value here
// has a counterpart in theme.css — change one, change the other.
//
// The dark palette is the original console, value for value. The light one
// is NOT a numeric inversion: each instrument encodes something (force,
// direction, tracking error), and the encoding has to survive the swap.
// Where a scheme reads as "brighter = more" on black it becomes "darker =
// more" on paper; where it reads as hue (the heat ramp, the direction
// quadrants) the hue is kept and only its lightness is retuned. See the
// per-field notes below.
//
// Deliberately free of any `three` import: three.js is lazy-loaded with the
// 3D tab, and importing it here would pull it into the initial bundle.

export type ThemeName = 'dark' | 'light'

/** Blending for the joint-glow rings; mapped to a THREE constant at use. */
export type GlowBlending = 'additive' | 'normal'

export interface Palette {
  name: ThemeName

  // --- semantic colors, mirroring the CSS tokens of the same name ---
  bg: string
  text: string
  textBright: string
  muted: string
  dim: string
  dimmer: string
  accent: string
  ok: string
  warn: string
  err: string
  purple: string

  /** 2D taxel maps (FingerTaxelSvg + taxelRender). */
  taxel: {
    /** The finger tile behind the dots. */
    tile: string
    /** Dot at rest, and below the display threshold. */
    idle: string
    /** Dot in arrows mode — fainter still; the arrow carries the reading. */
    idleArrows: string
    /** Hairline around every dot, so the grid is legible with no load. */
    stroke: string
    /**
     * Magnitude ramp endpoints. Dark runs near-black -> white (force adds
     * light); light runs pale -> ink (force adds ink). Same span either way,
     * so a given force lands at the same distance along the ramp.
     */
    rampFrom: [number, number, number]
    rampTo: [number, number, number]
  }

  /**
   * Arrow color schemes, shared by the 2D taxel arrows and the 3D force
   * arrows (getArrowColor2D).
   */
  arrows: {
    /**
     * ORCA brand ramp. Dark: slate -> near-white. Light: a warm-neutral
     * counterpart running pale -> ink, so zero force still sits just above
     * the ground and full force is maximum contrast against it.
     */
    orca: [number, number, number][]
    /**
     * Pure lightness encoding, so it flips outright: on black it climbs
     * 15% -> 100%, on paper it falls 84% -> 4%.
     */
    intensityFrom: number
    intensityTo: number
    /**
     * Blue -> red by hue, which needs no inversion at all: the hue is the
     * reading. Only lightness moves, down a notch on paper so a mid-ramp
     * cyan doesn't wash out.
     */
    heatSatFrom: number
    heatSatTo: number
    heatLightFrom: number
    heatLightTo: number
  }

  /**
   * Direction mode quadrants. The dark set is Tailwind 500s over near-black;
   * the light set is the console's own err/accent/ok/warn, which is what the
   * legend chips in theme.css use — so on paper the legend and the data
   * finally agree exactly. Alpha still ramps 0.3 -> 1.0 with magnitude,
   * which reads correctly over both grounds (pale -> saturated).
   */
  direction: {
    posX: [number, number, number]
    negX: [number, number, number]
    posY: [number, number, number]
    negY: [number, number, number]
  }

  /** Resultant-force dials (ForceDial). */
  dial: {
    ring: string
    cross: string
    /** Dot under 1 N, and at or over it. */
    low: string
    high: string
  }

  /** ROM bar gauges (RomBarGauge). */
  gauge: {
    track: string
    trackDegraded: string
    border: string
    zero: string
    target: string
  }

  /** uPlot sparklines (JointSparkline). */
  chart: {
    axis: string
    grid: string
    ticks: string
  }

  /** three.js scene (HandScene, JointGlowLayer, loadHandRobot). */
  scene: {
    bg: string
    gridCell: string
    gridSection: string
    hemiSky: string
    hemiGround: string
    hemiIntensity: number
    /** Camera-parented three-point rig: [x, y, z, intensity, color]. */
    lights: [number, number, number, number, string][]
    /** Motor-estimate ghost. */
    ghost: { color: number; opacity: number; emissiveIntensity: number }
    /** Teleop retargeter ghost — always the accent color. */
    teleopGhost: { color: number; opacity: number; emissiveIntensity: number }
    /**
     * Joint-glow rings. Additive blending is invisible over a light ground
     * (it can only brighten, and paper is already near-max), so light mode
     * blends normally and lifts the resting opacity to compensate — normal
     * blending at 0.14 over the hand's black plastic would show nothing.
     * The colors themselves barely move: the rings sit mostly over the dark
     * hand in both themes, so they are picked to read against the plastic
     * AND the background.
     */
    glow: {
      low: string
      mid: string
      high: string
      blending: GlowBlending
      idleOpacity: number
    }
  }
}

const DARK: Palette = {
  name: 'dark',

  bg: '#1a1c2a',
  text: '#dfe3e8',
  textBright: '#ffffff',
  muted: '#9faab9',
  dim: '#7f8ea2',
  dimmer: '#5f718b',
  accent: '#22d3ee',
  ok: '#34d399',
  warn: '#c8a870',
  err: '#d4878a',
  purple: '#a78bfa',

  taxel: {
    tile: '#000000',
    idle: '#1a1a1a',
    idleArrows: '#0a0a0a',
    stroke: '#2a2a2a',
    // 26 -> 255: the original TAXEL_GRAY_FLOOR + TAXEL_GRAY_SPAN, and the
    // floor matches `idle` so an unloaded taxel reads the same in every mode.
    rampFrom: [26, 26, 26],
    rampTo: [255, 255, 255],
  },

  arrows: {
    orca: [
      [71, 79, 94],
      [127, 142, 162],
      [191, 199, 209],
      [229, 231, 235],
    ],
    intensityFrom: 15,
    intensityTo: 100,
    heatSatFrom: 70,
    heatSatTo: 100,
    heatLightFrom: 55,
    heatLightTo: 45,
  },

  direction: {
    posX: [239, 68, 68],
    negX: [6, 182, 212],
    posY: [16, 185, 129],
    negY: [245, 158, 11],
  },

  dial: {
    ring: 'rgba(255,255,255,0.08)',
    cross: 'rgba(255,255,255,0.05)',
    low: '#3b82f6',
    high: '#ef4444',
  },

  gauge: {
    track: 'rgba(255,255,255,0.04)',
    trackDegraded: 'rgba(212,135,138,0.12)',
    border: 'rgba(255,255,255,0.08)',
    zero: '#5f718b',
    target: '#dfe3e8',
  },

  chart: {
    axis: '#5f718b',
    grid: 'rgba(255,255,255,0.05)',
    ticks: 'rgba(255,255,255,0.08)',
  },

  scene: {
    bg: '#14161f',
    gridCell: '#2a2e3e',
    gridSection: '#3a4054',
    hemiSky: '#e2e8f5',
    hemiGround: '#2b3040',
    hemiIntensity: 0.75,
    lights: [
      [-0.55, 0.85, 0.5, 1.8, '#ffffff'], // key: front, above, slightly left
      [0.9, -0.15, 0.45, 0.55, '#c8d2e6'], // fill: opposite side, softens the shadow
      [0.25, 0.7, -1.0, 0.8, '#8fa6c8'], // rim: from behind, lifts the silhouette
    ],
    ghost: { color: 0x7f8ea2, opacity: 0.22, emissiveIntensity: 0 },
    teleopGhost: { color: 0x22d3ee, opacity: 0.45, emissiveIntensity: 0.6 },
    glow: {
      low: '#7f8ea2',
      mid: '#f59e0b',
      high: '#ef4444',
      blending: 'additive',
      idleOpacity: 0.14,
    },
  },
}

const LIGHT: Palette = {
  name: 'light',

  bg: '#f6f5f1',
  text: '#26241d',
  textBright: '#100f0b',
  // Stepped for contrast against #f6f5f1 rather than by eye: 8.7:1, 6.3:1,
  // 4.5:1. `dimmer` carries 9px timestamps and meta labels and is the one
  // that would have slipped under AA if it were picked to "look right".
  muted: '#494434',
  dim: '#605a49',
  dimmer: '#787060',
  accent: '#0f6f78',
  ok: '#3f6212',
  warn: '#a16207',
  err: '#b3261e',
  purple: '#6b21a8',

  taxel: {
    // Brighter than both the page and the panel: on paper a lit readout
    // reads as the whitest surface, the way the black tile reads as a void
    // in dark mode.
    tile: '#ffffff',
    idle: '#eae7df',
    idleArrows: '#f4f2ec',
    stroke: '#dedad0',
    rampFrom: [234, 231, 223],
    rampTo: [28, 26, 21],
  },

  arrows: {
    orca: [
      [214, 210, 200],
      [154, 148, 134],
      [90, 86, 75],
      [35, 33, 28],
    ],
    intensityFrom: 84,
    intensityTo: 4,
    heatSatFrom: 75,
    heatSatTo: 100,
    heatLightFrom: 46,
    heatLightTo: 36,
  },

  direction: {
    posX: [179, 38, 30], // err
    negX: [15, 111, 120], // accent
    posY: [63, 98, 18], // ok
    negY: [161, 98, 7], // warn
  },

  dial: {
    ring: 'rgba(43,38,28,0.16)',
    cross: 'rgba(43,38,28,0.09)',
    low: '#1d4ed8',
    high: '#b3261e',
  },

  gauge: {
    track: 'rgba(43,38,28,0.05)',
    trackDegraded: 'rgba(179,38,30,0.10)',
    border: 'rgba(43,38,28,0.18)',
    zero: '#9a9484',
    target: '#26241d',
  },

  chart: {
    axis: '#787060',
    grid: 'rgba(43,38,28,0.10)',
    ticks: 'rgba(43,38,28,0.18)',
  },

  scene: {
    // A shade below the page so the viewport still reads as an inset, and
    // cooler than the panels so the hand's black plastic sits on something
    // neutral rather than on cream.
    bg: '#edebe3',
    gridCell: '#d3cfc4',
    gridSection: '#b6b1a3',
    hemiSky: '#fffdf6',
    // Bounce off a light floor rather than a dark room.
    hemiGround: '#d8d3c6',
    hemiIntensity: 0.8,
    // Key and fill stay at the dark theme's strength. The hand is dark
    // plastic under either theme, and it is the directional rig — not the
    // ambient term — that puts specular highlights on it and gives it form;
    // trading key for hemisphere flattened it to a charcoal silhouette.
    // Only the rim comes down, and only partway: its job is separating a
    // dark hand from a dark ground, which paper does for free.
    lights: [
      [-0.55, 0.85, 0.5, 1.8, '#ffffff'],
      [0.9, -0.15, 0.45, 0.55, '#efe9dc'],
      [0.25, 0.7, -1.0, 0.5, '#c9c3b4'],
    ],
    // Darker and slightly more opaque than the dark theme's pale slate,
    // which would vanish against paper wherever the ghost leaves the hand —
    // and leaving the hand is the entire point of the ghost.
    ghost: { color: 0x4f4a3c, opacity: 0.3, emissiveIntensity: 0.0 },
    // Still unmistakably the accent, but self-lit far less: emissive at 0.6
    // on paper reads as a pale wash instead of a solid lead.
    teleopGhost: { color: 0x0f6f78, opacity: 0.5, emissiveIntensity: 0.18 },
    glow: {
      low: '#6b6555',
      mid: '#d97706',
      high: '#dc2626',
      blending: 'normal',
      idleOpacity: 0.3,
    },
  },
}

export const PALETTES: Record<ThemeName, Palette> = { dark: DARK, light: LIGHT }

// The imperative renderers (SVG attribute writes, three.js materials, uPlot)
// read this on every frame rather than subscribing; themeStore swaps it.
let active: Palette = DARK

export function palette(): Palette {
  return active
}

export function setActivePalette(name: ThemeName): void {
  active = PALETTES[name]
}
