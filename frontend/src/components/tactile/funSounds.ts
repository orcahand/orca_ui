// Fun mode: each finger's resultant force drives its own sound voice; all
// voices mix in one lazily created AudioContext (must be born in a toolbar
// click to satisfy autoplay rules). Per-frame update() maps force -> gain /
// playbackRate over a user-adjustable range [onN, fullN].
// Files in /sounds are CC-licensed — see public/sounds/CREDITS.md.

import type { Finger } from '../../api/types'
import { FINGERS } from '../../api/types'
import type { FunSoundMode } from '../../state/appStore'

const FILES: Record<string, string> = {
  soundtrack: '/sounds/soundtrack.mp3',
  cow: '/sounds/swiss-cows.mp3',
  moo: '/sounds/moo.mp3',
  engine: '/sounds/engine.mp3',
  squeak: '/sounds/squeak.mp3',
  theremin: '/sounds/theremin.mp3',
}

// The looping bed per sound (squeak is one-shots only).
const LOOP_KEY: Partial<Record<FunSoundMode, string>> = {
  soundtrack: 'soundtrack',
  cow: 'cow',
  engine: 'engine',
  theremin: 'theremin',
}

const LOOP_GAIN: Record<string, (n: number) => number> = {
  soundtrack: (n) => 0.1 + 0.9 * n,
  cow: (n) => 0.2 + 0.8 * n,
  engine: (n) => 0.25 + 0.75 * n,
  theremin: (n) => 0.15 + 0.85 * n,
}

const LOOP_RATE: Record<string, (n: number) => number> = {
  soundtrack: () => 1,
  cow: () => 1,
  engine: (n) => 0.5 + 2.2 * n,
  theremin: (n) => 0.5 + 1.8 * n,
}

// Spread the fingers across the stereo field so simultaneous sounds stay
// separable: thumb far left ... pinky far right.
const PAN: Record<Finger, number> = {
  thumb: -0.8,
  index: -0.4,
  middle: 0,
  ring: 0.4,
  pinky: 0.8,
}

interface Voice {
  finger: Finger
  sound: FunSoundMode
  pressed: boolean
  loopSrc: AudioBufferSourceNode | null
  loopGain: GainNode | null
  mooArmed: boolean
  lastSqueakN: number
}

const newVoice = (finger: Finger, sound: FunSoundMode): Voice => ({
  finger,
  sound,
  pressed: false,
  loopSrc: null,
  loopGain: null,
  mooArmed: true,
  lastSqueakN: 0,
})

class FunSoundPlayer {
  private ctx: AudioContext | null = null
  private ready = new Map<string, AudioBuffer>()
  private loading = new Set<string>()
  private voices = new Map<Finger, Voice>()
  // Force engages a voice above onN and reaches full volume/pitch at fullN.
  private onN = 1
  private fullN = 12

  // null disables everything; otherwise one sound per finger ('off' allowed).
  setAssignments(assignment: Record<Finger, FunSoundMode> | null) {
    for (const finger of FINGERS) {
      const sound = assignment?.[finger] ?? 'off'
      const voice = this.voices.get(finger)
      if (voice?.sound === sound) continue
      if (voice) this.release(voice)
      this.voices.set(finger, newVoice(finger, sound))
      if (sound !== 'off') {
        this.ctx ??= new AudioContext()
        if (this.ctx.state === 'suspended') void this.ctx.resume()
        const keys = sound === 'cow' ? ['cow', 'moo'] : [sound]
        keys.forEach((k) => this.load(k))
      }
    }
  }

  setRange(onN: number, fullN: number) {
    this.onN = Math.max(0.1, onN)
    this.fullN = Math.max(this.onN + 0.5, fullN)
  }

  update(magnitudes: Partial<Record<Finger, number>>) {
    if (!this.ctx) return
    for (const finger of FINGERS) {
      const voice = this.voices.get(finger)
      if (!voice || voice.sound === 'off') continue
      this.updateVoice(voice, magnitudes[finger] ?? 0)
    }
  }

  private updateVoice(voice: Voice, magnitude: number) {
    const ctx = this.ctx!
    const n = Math.min(
      Math.max(magnitude - this.onN, 0) / (this.fullN - this.onN),
      1,
    )

    if (!voice.pressed && magnitude > this.onN) this.press(voice, n)
    else if (voice.pressed && magnitude < this.onN * 0.7) this.release(voice)
    if (!voice.pressed) return

    const key = LOOP_KEY[voice.sound]
    if (key && voice.loopGain && voice.loopSrc) {
      const t = ctx.currentTime
      voice.loopGain.gain.setTargetAtTime(LOOP_GAIN[key](n), t, 0.08)
      voice.loopSrc.playbackRate.setTargetAtTime(LOOP_RATE[key](n), t, 0.08)
    }

    if (voice.sound === 'cow') {
      // A hard squeeze earns a moo; back off to re-arm.
      if (voice.mooArmed && n > 0.45) {
        voice.mooArmed = false
        this.oneShot('moo', 0.6 + 0.4 * n, 0.85 + 0.4 * n, PAN[voice.finger])
      } else if (!voice.mooArmed && n < 0.3) {
        voice.mooArmed = true
      }
    } else if (voice.sound === 'squeak' && n - voice.lastSqueakN > 0.2) {
      this.squeak(voice, n)
    }
  }

  private press(voice: Voice, n: number) {
    const key = LOOP_KEY[voice.sound]
    if (key) {
      const buffer = this.ready.get(key)
      if (!buffer) return // still downloading; retry next frame
      const ctx = this.ctx!
      const src = ctx.createBufferSource()
      src.buffer = buffer
      src.loop = true
      src.playbackRate.value = LOOP_RATE[key](n)
      const gain = ctx.createGain()
      gain.gain.value = LOOP_GAIN[key](n)
      const panner = ctx.createStereoPanner()
      panner.pan.value = PAN[voice.finger]
      src.connect(gain).connect(panner).connect(ctx.destination)
      src.start()
      voice.loopSrc = src
      voice.loopGain = gain
    } else if (voice.sound === 'squeak') {
      this.squeak(voice, n)
    }
    voice.pressed = true
    voice.mooArmed = true
  }

  private release(voice: Voice) {
    voice.pressed = false
    voice.lastSqueakN = 0
    const src = voice.loopSrc
    const gain = voice.loopGain
    voice.loopSrc = null
    voice.loopGain = null
    if (!src || !gain || !this.ctx) return
    // Instant stop: a ~15 ms ramp is inaudible as a tail but avoids a click.
    const t = this.ctx.currentTime
    gain.gain.cancelScheduledValues(t)
    gain.gain.setValueAtTime(gain.gain.value, t)
    gain.gain.linearRampToValueAtTime(0, t + 0.015)
    src.stop(t + 0.02)
  }

  private squeak(voice: Voice, n: number) {
    voice.lastSqueakN = n
    this.oneShot('squeak', 0.5 + 0.5 * n, 0.7 + 1.5 * n, PAN[voice.finger])
  }

  private oneShot(key: string, volume: number, rate: number, pan: number) {
    const ctx = this.ctx
    const buffer = this.ready.get(key)
    if (!ctx || !buffer) return
    const src = ctx.createBufferSource()
    src.buffer = buffer
    src.playbackRate.value = rate
    const gain = ctx.createGain()
    gain.gain.value = volume
    const panner = ctx.createStereoPanner()
    panner.pan.value = pan
    src.connect(gain).connect(panner).connect(ctx.destination)
    src.start()
  }

  private load(key: string) {
    if (this.ready.has(key) || this.loading.has(key)) return
    this.loading.add(key)
    fetch(FILES[key])
      .then((r) => r.arrayBuffer())
      .then((data) => this.ctx!.decodeAudioData(data))
      .then((buffer) => this.ready.set(key, buffer))
      .catch(() => {})
      .finally(() => this.loading.delete(key))
  }
}

export const funPlayer = new FunSoundPlayer()
