// The torque-wrench click: a short two-note tone when a spool reaches torque.
// Browsers only let audio start from a user gesture, so the context is
// created (and resumed) from the card's buttons and reused afterwards.

let context: AudioContext | null = null

export function primeAudio(): void {
  try {
    context ??= new AudioContext()
    if (context.state === 'suspended') void context.resume()
  } catch {
    context = null
  }
}

function tone(frequency: number, at: number, durationS: number): void {
  if (!context) return
  const osc = context.createOscillator()
  const gain = context.createGain()
  osc.type = 'sine'
  osc.frequency.value = frequency
  gain.gain.setValueAtTime(0.0001, at)
  gain.gain.exponentialRampToValueAtTime(0.35, at + 0.01)
  gain.gain.exponentialRampToValueAtTime(0.0001, at + durationS)
  osc.connect(gain).connect(context.destination)
  osc.start(at)
  osc.stop(at + durationS + 0.02)
}

export function beep(): void {
  if (!context) return
  try {
    const now = context.currentTime
    tone(880, now, 0.12)
    tone(1320, now + 0.13, 0.18)
  } catch {
    // No audio is not an error; the tile still flashes.
  }
}
