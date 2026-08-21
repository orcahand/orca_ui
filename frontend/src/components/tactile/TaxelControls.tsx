// The taxel display toolbar: mode radios, color scheme, arrow size sliders,
// threshold — plus the backend stream-mode selector and zero buttons.

import { useState } from 'react'
import { api } from '../../api/rest'
import type { TactileMode } from '../../api/types'
import { FINGERS } from '../../api/types'
import type { FunSoundMode, MusicScale } from '../../state/appStore'
import { useAppStore } from '../../state/appStore'
import { funPlayer } from './funSounds'
import { stringSynth } from './stringSynth'

const NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']

const MUSIC_SCALES: { value: MusicScale; label: string }[] = [
  { value: 'major', label: 'major' },
  { value: 'minor', label: 'minor' },
  { value: 'pentMajor', label: 'pent. major' },
  { value: 'pentMinor', label: 'pent. minor' },
  { value: 'majorChord', label: 'chord (maj)' },
  { value: 'minorChord', label: 'chord (min)' },
  { value: 'chromatic', label: 'chromatic' },
]

const FUN_SOUNDS: { value: FunSoundMode; label: string }[] = [
  { value: 'off', label: 'off' },
  { value: 'soundtrack', label: '🎵 soundtrack' },
  { value: 'cow', label: '🐄 swiss cow' },
  { value: 'engine', label: '🏎️ engine' },
  { value: 'squeak', label: '🐤 rubber duck' },
  { value: 'theremin', label: '👽 theremin' },
]

export function TaxelControls() {
  const tactile = useAppStore((s) => s.tactile)
  const setTactile = useAppStore((s) => s.setTactile)
  const control = useAppStore((s) => s.control)
  const setTactileMode = useAppStore((s) => s.setTactileMode)
  const setError = useAppStore((s) => s.setError)
  const [zeroBusy, setZeroBusy] = useState(false)
  const [zeroed, setZeroed] = useState(false)

  const changeStreamMode = async (mode: TactileMode) => {
    try {
      await api.setTactileMode(mode)
      setTactileMode(mode)
    } catch (error) {
      setError(String((error as Error).message ?? error))
    }
  }

  const zero = async () => {
    setZeroBusy(true)
    try {
      await api.zeroTactile(100)
      setZeroed(true)
      setError(null)
    } catch (error) {
      setError(String((error as Error).message ?? error))
    } finally {
      setZeroBusy(false)
    }
  }

  const clearZero = async () => {
    try {
      await api.clearTactileZero()
      setZeroed(false)
    } catch (error) {
      setError(String((error as Error).message ?? error))
    }
  }

  return (
    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
      <div className="toolbar">
        <label className="toggle-label">
          <input
            type="radio"
            name="taxel-display"
            checked={tactile.displayMode === 'magnitude'}
            onChange={() => setTactile({ displayMode: 'magnitude' })}
          />
          Magnitude
        </label>
        <label className="toggle-label">
          <input
            type="radio"
            name="taxel-display"
            checked={tactile.displayMode === 'direction'}
            onChange={() => setTactile({ displayMode: 'direction' })}
          />
          Direction
        </label>
        <label className="toggle-label">
          <input
            type="radio"
            name="taxel-display"
            checked={tactile.displayMode === 'arrows'}
            onChange={() => setTactile({ displayMode: 'arrows' })}
          />
          Arrows
        </label>
        {tactile.displayMode === 'direction' && (
          <span className="color-legend direction-legend">
            <span className="dir-right">+x</span>
            <span className="dir-left">−x</span>
            <span className="dir-up">+y</span>
            <span className="dir-down">−y</span>
          </span>
        )}
        {tactile.displayMode === 'arrows' && (
          <>
            <label className="toggle-label" style={{ gap: 6 }}>
              color
              <select
                value={tactile.colorScheme}
                onChange={(e) =>
                  setTactile({ colorScheme: e.target.value as never })
                }
              >
                <option value="heat">heat</option>
                <option value="intensity">intensity</option>
                <option value="orca">orca</option>
              </select>
            </label>
            <span className="slider-control">
              <span>len</span>
              <input
                type="range"
                min={0.1}
                max={2}
                step={0.1}
                value={tactile.lengthMult}
                onChange={(e) =>
                  setTactile({ lengthMult: parseFloat(e.target.value) })
                }
              />
              <span>{tactile.lengthMult.toFixed(1)}x</span>
            </span>
            <span className="slider-control">
              <span>thick</span>
              <input
                type="range"
                min={0.1}
                max={2}
                step={0.1}
                value={tactile.thicknessMult}
                onChange={(e) =>
                  setTactile({ thicknessMult: parseFloat(e.target.value) })
                }
              />
              <span>{tactile.thicknessMult.toFixed(1)}x</span>
            </span>
          </>
        )}
        <label className="toggle-label">
          <input
            type="checkbox"
            checked={tactile.thresholdEnabled}
            onChange={(e) => setTactile({ thresholdEnabled: e.target.checked })}
          />
          threshold
          <input
            type="number"
            min={0}
            max={25}
            step={0.5}
            value={tactile.threshold}
            disabled={!tactile.thresholdEnabled}
            onChange={(e) =>
              setTactile({ threshold: parseFloat(e.target.value) || 0 })
            }
          />
          N
        </label>
      </div>

      <div className="toolbar">
        <label className="toggle-label">
          <input
            type="checkbox"
            checked={tactile.funEnabled}
            onChange={(e) => {
              const funEnabled = e.target.checked
              // Create/resume the AudioContext inside the click, so the
              // browser's autoplay policy lets sound through.
              funPlayer.setAssignments(funEnabled ? tactile.funSounds : null)
              setTactile({ funEnabled })
            }}
          />
          🔊 fun
        </label>
        {tactile.funEnabled &&
          FINGERS.map((finger) => (
            <label
              key={finger}
              className="toggle-label"
              style={{ gap: 4 }}
              title={finger}
            >
              {finger.charAt(0).toUpperCase()}
              <select
                value={tactile.funSounds[finger]}
                onChange={(e) => {
                  const funSounds = {
                    ...tactile.funSounds,
                    [finger]: e.target.value as FunSoundMode,
                  }
                  funPlayer.setAssignments(funSounds)
                  setTactile({ funSounds })
                }}
              >
                {FUN_SOUNDS.map((m) => (
                  <option key={m.value} value={m.value}>
                    {m.label}
                  </option>
                ))}
              </select>
            </label>
          ))}
        <label className="toggle-label" title="fingers play strings by force (amplitude) and joint position (pitch)">
          <input
            type="checkbox"
            checked={tactile.musicEnabled}
            onChange={(e) => {
              const musicEnabled = e.target.checked
              // AudioContext must be created/resumed inside the click.
              stringSynth.setEnabled(musicEnabled)
              setTactile({ musicEnabled })
            }}
          />
          🎻 music
        </label>
        {tactile.musicEnabled && (
          <>
            <label className="toggle-label" style={{ gap: 4 }} title="harmony: only these notes play">
              <select
                value={tactile.musicRoot}
                onChange={(e) =>
                  setTactile({ musicRoot: parseInt(e.target.value, 10) })
                }
              >
                {NOTE_NAMES.map((name, i) => (
                  <option key={name} value={i}>
                    {name}
                  </option>
                ))}
              </select>
              <select
                value={tactile.musicScale}
                onChange={(e) =>
                  setTactile({ musicScale: e.target.value as MusicScale })
                }
              >
                {MUSIC_SCALES.map((s) => (
                  <option key={s.value} value={s.value}>
                    {s.label}
                  </option>
                ))}
              </select>
            </label>
            <span className="slider-control">
              <span>vol</span>
              <input
                type="range"
                min={0}
                max={1}
                step={0.05}
                value={tactile.musicVol}
                onChange={(e) =>
                  setTactile({ musicVol: parseFloat(e.target.value) })
                }
              />
            </span>
          </>
        )}
        {(tactile.funEnabled || tactile.musicEnabled) && (
          <>
            <span className="slider-control" title="force where sound engages">
              <span>on</span>
              <input
                type="range"
                min={0.2}
                max={5}
                step={0.1}
                value={tactile.funOnN}
                onChange={(e) =>
                  setTactile({ funOnN: parseFloat(e.target.value) })
                }
              />
              <span>{tactile.funOnN.toFixed(1)}N</span>
            </span>
            <span className="slider-control" title="force for full volume/pitch">
              <span>max</span>
              <input
                type="range"
                min={2}
                max={25}
                step={0.5}
                value={tactile.funFullN}
                onChange={(e) =>
                  setTactile({ funFullN: parseFloat(e.target.value) })
                }
              />
              <span>{tactile.funFullN.toFixed(1)}N</span>
            </span>
          </>
        )}
      </div>

      <div className="toolbar">
        {(['resultant', 'taxels', 'combined'] as TactileMode[]).map((mode) => (
          <label key={mode} className="toggle-label">
            <input
              type="radio"
              name="stream-mode"
              checked={control?.tactile_mode === mode}
              onChange={() => void changeStreamMode(mode)}
            />
            {mode}
          </label>
        ))}
      </div>

      <button className="btn btn-info" onClick={() => void zero()} disabled={zeroBusy}>
        {zeroBusy ? 'Zeroing…' : 'Zero'}
      </button>
      {zeroed && (
        <button className="btn btn-secondary" onClick={() => void clearZero()}>
          Reset Zero
        </button>
      )}
    </div>
  )
}
