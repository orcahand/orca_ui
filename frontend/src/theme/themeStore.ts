// Theme selection. `data-theme` on <html> drives every CSS token; the JS
// palette (palette.ts) is swapped in the same breath so the SVG/three.js/uPlot
// renderers, which CSS can't reach, stay in step.
//
// The console defaults to light; a stored choice (the first click on the
// toggle) wins from then on. The OS preference is deliberately not consulted.
//
// index.html resolves the same rule in a blocking inline script and stamps
// `data-theme` before first paint, so the page never flashes the wrong theme.
// The two must agree — change one, change the other.

import { create } from 'zustand'
import { PALETTES, setActivePalette, type ThemeName } from './palette'

export const THEME_KEY = 'orca-ui.theme'

const DEFAULT_THEME: ThemeName = 'light'

function storedTheme(): ThemeName | null {
  try {
    const raw = localStorage.getItem(THEME_KEY)
    return raw === 'dark' || raw === 'light' ? raw : null
  } catch {
    return null
  }
}

function apply(theme: ThemeName): void {
  const root = document.documentElement
  root.dataset.theme = theme
  setActivePalette(theme)
  // The browser chrome inside the page — scrollbars, native form controls,
  // the canvas the compositor paints behind the body — follows this, not the
  // CSS tokens. Without it a light page keeps dark scrollbars.
  root.style.colorScheme = theme
  // index.html sets this inline to beat the first paint, and an inline style
  // outranks any rule in theme.css — so it has to be kept current here too.
  // Left stale, <html> keeps painting the old theme wherever <body> does not
  // reach: the page margin, and everything below a short page.
  root.style.background = PALETTES[theme].bg
}

interface ThemeState {
  theme: ThemeName
  setTheme(theme: ThemeName): void
  toggle(): void
}

const initialTheme = storedTheme() ?? DEFAULT_THEME
apply(initialTheme)

export const useThemeStore = create<ThemeState>((set, get) => ({
  theme: initialTheme,

  setTheme: (theme) => {
    try {
      localStorage.setItem(THEME_KEY, theme)
    } catch {
      // Private-mode / storage-disabled: the choice just doesn't persist.
    }
    apply(theme)
    set({ theme })
  },

  toggle: () => get().setTheme(get().theme === 'dark' ? 'light' : 'dark'),
}))

/** Re-renders the caller on every theme change; returns the live palette. */
export function usePalette() {
  return PALETTES[useThemeStore((s) => s.theme)]
}
