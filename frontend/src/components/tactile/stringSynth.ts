// Music mode: the hand as a string section. One synthesized string voice per
// finger — resultant touch force opens its amplitude, the finger's joint
// positions (normalized over their calibrated hardstop range, averaged) pick
// the note over two octaves from C. Pitch is stepped: only halftones sound,
// with hysteresis so a note holds until the joints clearly move to the next.
// Thumb plays two octaves up. The wrist is a bass two octaves down that only
// sounds while the wrist joint is actually moving.
//
// Timbre: two detuned saws + bow noise through a pitch-keyed lowpass, per-
// finger stereo panning, and shared "body" resonance filters on the master.

import type { Finger, JointInfo } from '../../api/types'
import { FINGERS } from '../../api/types'
import type { MusicScale } from '../../state/appStore'

type VoiceId = Finger | 'wrist'
const VOICE_IDS: VoiceId[] = [...FINGERS, 'wrist']

// Base MIDI note per voice; every voice spans two octaves (24 semitones) up.
const BASE_MIDI: Record<VoiceId, number> = {
  index: 60, // C4
  middle: 60,
  ring: 60,
  pinky: 60,
  thumb: 84, // C6 — two octaves up
  wrist: 36, // C2 — two octaves down
}

// Spread the section across the stereo field so voices stay separable.
const PAN: Record<VoiceId, number> = {
  thumb: -0.8,
  index: -0.4,
  middle: 0,
  ring: 0.4,
  pinky: 0.8,
  wrist: 0,
}

const WRIST_GAIN = 0.5
const WRIST_FULL_VEL = 30 // deg/s of wrist motion for full bass level
const DETUNE_CENTS = 5
const VIBRATO_HZ = 4.5
const VIBRATO_CENTS = 6
const BOW_NOISE_GAIN = 0.1
// A new note must be clearly closer than the sounding one by this margin —
// hysteresis, so notes step cleanly instead of fluttering at boundaries.
const NOTE_SWITCH_MARGIN = 0.4

// Harmony: pitch-class intervals from the root that are allowed to sound.
const SCALES: Record<MusicScale, number[]> = {
  chromatic: [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11],
  major: [0, 2, 4, 5, 7, 9, 11],
  minor: [0, 2, 3, 5, 7, 8, 10],
  pentMajor: [0, 2, 4, 7, 9],
  pentMinor: [0, 3, 5, 7, 10],
  majorChord: [0, 4, 7],
  minorChord: [0, 3, 7],
}

interface JointRange {
  id: string
  min: number
  max: number
}

interface Voice {
  oscs: OscillatorNode[]
  filter: BiquadFilterNode
  noiseFilter: BiquadFilterNode
  noiseGain: GainNode
  gain: GainNode
  sounding: boolean
  note: number | null
  // Wrist motion gate state.
  lastAngle: number | null
  lastT: number
  level: number
}

const midiToFreq = (m: number) => 440 * 2 ** ((m - 69) / 12)

class StringSynth {
  private ctx: AudioContext | null = null
  private master: GainNode | null = null
  private vibrato: OscillatorNode | null = null
  private vibratoDepth: GainNode | null = null
  private noiseSrc: AudioBufferSourceNode | null = null
  private voices = new Map<VoiceId, Voice>()
  private jointRanges = new Map<VoiceId, JointRange[]>()
  private onN = 1
  private fullN = 12
  private volume = 0.5
  // Semitone offsets (0..24 above each voice's base C) allowed by the
  // current harmony. Default: C major.
  private allowedNotes = this.buildAllowed(0, 'major')

  setEnabled(on: boolean) {
    if (!on) {
      this.teardown()
      return
    }
    if (this.master) return
    const ctx = (this.ctx ??= new AudioContext())
    if (ctx.state === 'suspended') void ctx.resume()

    // Master: volume -> violin-ish body resonances -> out.
    this.master = ctx.createGain()
    this.master.gain.value = this.volume
    const body1 = ctx.createBiquadFilter()
    body1.type = 'peaking'
    body1.frequency.value = 350
    body1.Q.value = 1.5
    body1.gain.value = 4
    const body2 = ctx.createBiquadFilter()
    body2.type = 'peaking'
    body2.frequency.value = 1500
    body2.Q.value = 2
    body2.gain.value = 3
    this.master.connect(body1).connect(body2).connect(ctx.destination)

    this.vibrato = ctx.createOscillator()
    this.vibrato.frequency.value = VIBRATO_HZ
    this.vibratoDepth = ctx.createGain()
    this.vibratoDepth.gain.value = VIBRATO_CENTS
    this.vibrato.connect(this.vibratoDepth)
    this.vibrato.start()

    // Shared looped white-noise source feeding every voice's bow filter.
    const noiseBuffer = ctx.createBuffer(1, ctx.sampleRate, ctx.sampleRate)
    const samples = noiseBuffer.getChannelData(0)
    for (let i = 0; i < samples.length; i++) samples[i] = Math.random() * 2 - 1
    this.noiseSrc = ctx.createBufferSource()
    this.noiseSrc.buffer = noiseBuffer
    this.noiseSrc.loop = true
    this.noiseSrc.start()

    for (const id of VOICE_IDS) {
      const panner = ctx.createStereoPanner()
      panner.pan.value = PAN[id]
      panner.connect(this.master)

      const gain = ctx.createGain()
      gain.gain.value = 0
      gain.connect(panner)

      const filter = ctx.createBiquadFilter()
      filter.type = 'lowpass'
      filter.Q.value = 0.7
      filter.connect(gain)

      const baseFreq = midiToFreq(BASE_MIDI[id])
      const oscs = [-DETUNE_CENTS, DETUNE_CENTS].map((cents) => {
        const osc = ctx.createOscillator()
        osc.type = 'sawtooth'
        osc.detune.value = cents
        this.vibratoDepth!.connect(osc.detune)
        osc.connect(filter)
        osc.frequency.value = baseFreq
        osc.start()
        return osc
      })

      // Bow noise: bandpass tracking the note, mixed in below the saws.
      const noiseFilter = ctx.createBiquadFilter()
      noiseFilter.type = 'bandpass'
      noiseFilter.frequency.value = baseFreq * 2.5
      noiseFilter.Q.value = 1
      const noiseGain = ctx.createGain()
      noiseGain.gain.value = 0
      this.noiseSrc.connect(noiseFilter).connect(noiseGain).connect(panner)

      this.voices.set(id, {
        oscs,
        filter,
        noiseFilter,
        noiseGain,
        gain,
        sounding: false,
        note: null,
        lastAngle: null,
        lastT: 0,
        level: 0,
      })
    }
  }

  setJoints(joints: JointInfo[]) {
    this.jointRanges.clear()
    for (const joint of joints) {
      const voice = VOICE_IDS.find(
        (id) => joint.id === id || joint.id.startsWith(`${id}_`),
      )
      if (!voice) continue
      const rom = joint.rom_effective ?? joint.rom_measured ?? joint.rom
      const [min, max] = rom
      if (Math.abs(max - min) < 1e-6) continue
      let ranges = this.jointRanges.get(voice)
      if (!ranges) this.jointRanges.set(voice, (ranges = []))
      ranges.push({ id: joint.id, min, max })
    }
  }

  setRange(onN: number, fullN: number) {
    this.onN = Math.max(0.1, onN)
    this.fullN = Math.max(this.onN + 0.5, fullN)
  }

  setHarmony(root: number, scale: MusicScale) {
    this.allowedNotes = this.buildAllowed(root, scale)
    // Re-quantize sounding notes into the new harmony.
    for (const voice of this.voices.values()) {
      if (voice.note !== null && !this.allowedNotes.includes(voice.note)) {
        voice.note = null
      }
    }
  }

  private buildAllowed(root: number, scale: MusicScale): number[] {
    const classes = SCALES[scale] ?? SCALES.chromatic
    const notes: number[] = []
    for (let n = 0; n <= 24; n++) {
      if (classes.includes((((n - root) % 12) + 12) % 12)) notes.push(n)
    }
    return notes
  }

  setVolume(volume: number) {
    this.volume = volume
    if (this.master && this.ctx) {
      this.master.gain.setTargetAtTime(volume, this.ctx.currentTime, 0.03)
    }
  }

  update(
    forces: Partial<Record<Finger, number>>,
    angles: Record<string, number>,
  ) {
    const ctx = this.ctx
    if (!ctx || !this.master) return
    const t = ctx.currentTime

    for (const id of VOICE_IDS) {
      const voice = this.voices.get(id)
      if (!voice) continue

      const amp =
        id === 'wrist'
          ? this.wristAmp(voice, angles.wrist, t)
          : this.fingerAmp(voice, forces[id] ?? 0)

      if (amp > 0) {
        // Bowed attack: a little slower in than out.
        voice.gain.gain.setTargetAtTime(amp, t, 0.07)
        voice.noiseGain.gain.setTargetAtTime(amp * BOW_NOISE_GAIN, t, 0.07)
        voice.sounding = true
      } else if (voice.sounding) {
        // Instant, click-free cut.
        voice.gain.gain.cancelScheduledValues(t)
        voice.gain.gain.setValueAtTime(voice.gain.gain.value, t)
        voice.gain.gain.linearRampToValueAtTime(0, t + 0.03)
        voice.noiseGain.gain.setTargetAtTime(0, t, 0.02)
        voice.sounding = false
        voice.note = null // re-quantize fresh on the next bow stroke
      }

      // Pitch: average normalized joint position -> stepped halftones.
      const ranges = this.jointRanges.get(id)
      if (!ranges?.length) continue
      let sum = 0
      let count = 0
      for (const { id: jointId, min, max } of ranges) {
        const angle = angles[jointId]
        if (angle === undefined) continue
        sum += Math.min(Math.max((angle - min) / (max - min), 0), 1)
        count++
      }
      if (!count) continue
      const semis = (sum / count) * 24
      let nearest = this.allowedNotes[0]
      for (const note of this.allowedNotes) {
        if (Math.abs(semis - note) < Math.abs(semis - nearest)) nearest = note
      }
      if (
        voice.note === null ||
        Math.abs(semis - nearest) + NOTE_SWITCH_MARGIN <
          Math.abs(semis - voice.note)
      ) {
        voice.note = nearest
      }
      const freq = midiToFreq(BASE_MIDI[id] + voice.note)
      for (const osc of voice.oscs) {
        // Short glide: fast enough to hear a step, no zipper noise.
        osc.frequency.setTargetAtTime(freq, t, 0.012)
      }
      voice.filter.frequency.setTargetAtTime(
        Math.min(Math.max(freq * 3, 150), 7000),
        t,
        0.03,
      )
      voice.noiseFilter.frequency.setTargetAtTime(freq * 2.5, t, 0.03)
    }
  }

  private fingerAmp(voice: Voice, force: number): number {
    if (force > this.onN || (voice.sounding && force > this.onN * 0.7)) {
      return (
        0.15 + 0.85 * Math.min((force - this.onN) / (this.fullN - this.onN), 1)
      )
    }
    return 0
  }

  // The wrist only sounds while the wrist joint is moving: level follows
  // |velocity| with a short hold so normal playing motion sustains the bass.
  private wristAmp(voice: Voice, angle: number | undefined, t: number): number {
    if (angle === undefined) return 0
    const dt = t - voice.lastT
    if (voice.lastAngle !== null && dt > 0.005) {
      const vel = Math.abs(angle - voice.lastAngle) / dt
      const target = Math.min(vel / WRIST_FULL_VEL, 1)
      // Fast attack, ~1 s release once the wrist stops.
      voice.level = Math.max(target, voice.level * Math.exp(-dt / 0.35))
      voice.lastAngle = angle
      voice.lastT = t
    } else if (voice.lastAngle === null) {
      voice.lastAngle = angle
      voice.lastT = t
    }
    return voice.level > 0.02 ? WRIST_GAIN * voice.level : 0
  }

  private teardown() {
    if (!this.ctx || !this.master) return
    const t = this.ctx.currentTime
    this.master.gain.setTargetAtTime(0, t, 0.02)
    const oldVoices = [...this.voices.values()]
    const oldMaster = this.master
    const oldVibrato = this.vibrato
    const oldNoise = this.noiseSrc
    setTimeout(() => {
      oldVoices.forEach((v) => v.oscs.forEach((o) => o.stop()))
      oldVibrato?.stop()
      oldNoise?.stop()
      oldMaster.disconnect()
    }, 200)
    this.voices.clear()
    this.master = null
    this.vibrato = null
    this.vibratoDepth = null
    this.noiseSrc = null
  }
}

export const stringSynth = new StringSynth()
