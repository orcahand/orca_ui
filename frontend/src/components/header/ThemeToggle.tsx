// Dark/light switch, sitting between the view tabs and the E-stop.
//
// The glyph shows what a click gets you, not what you are looking at — a sun
// while dark, a moon while light — and the tooltip says it in words, since
// that convention runs both ways in the wild.

import { useThemeStore } from '../../theme/themeStore'

function SunIcon() {
  return (
    <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" aria-hidden="true">
      <circle cx="8" cy="8" r="3.1" />
      <path
        strokeLinecap="round"
        d="M8 1.2v1.6M8 13.2v1.6M14.8 8h-1.6M2.8 8H1.2M12.8 3.2l-1.13 1.13M4.33 11.67L3.2 12.8M12.8 12.8l-1.13-1.13M4.33 4.33L3.2 3.2"
      />
    </svg>
  )
}

function MoonIcon() {
  return (
    <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" aria-hidden="true">
      <path
        strokeLinejoin="round"
        d="M13.2 9.6A5.6 5.6 0 0 1 6.4 2.8a5.6 5.6 0 1 0 6.8 6.8Z"
      />
    </svg>
  )
}

export function ThemeToggle() {
  const theme = useThemeStore((s) => s.theme)
  const toggle = useThemeStore((s) => s.toggle)
  const next = theme === 'dark' ? 'light' : 'dark'

  return (
    <button
      type="button"
      className="theme-toggle"
      onClick={toggle}
      title={`Switch to ${next} theme`}
      aria-label={`Switch to ${next} theme`}
    >
      {theme === 'dark' ? <SunIcon /> : <MoonIcon />}
    </button>
  )
}
