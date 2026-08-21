// The tactile section: controls toolbar + per-finger taxel SVGs + resultant
// dials. Panels render based on which streams actually carry data (mode).

import { useEffect, useState } from 'react'
import { api } from '../../api/rest'
import type { Finger, TaxelGeometry } from '../../api/types'
import { FINGERS } from '../../api/types'
import { useStreamFrame } from '../../hooks/useStreamFrame'
import { useAppStore } from '../../state/appStore'
import { Panel } from '../common/Panel'
import { FingerTaxelSvg } from './FingerTaxelSvg'
import { ForceDial } from './ForceDial'
import { funPlayer } from './funSounds'
import { stringSynth } from './stringSynth'
import { TaxelControls } from './TaxelControls'

export function TactilePanel() {
  const [geometry, setGeometry] = useState<TaxelGeometry | null>(null)
  const control = useAppStore((s) => s.control)
  const handInfo = useAppStore((s) => s.handInfo)
  const {
    funEnabled,
    funSounds,
    funOnN,
    funFullN,
    musicEnabled,
    musicVol,
    musicRoot,
    musicScale,
  } = useAppStore((s) => s.tactile)
  const mode = control?.tactile_mode ?? 'combined'

  useEffect(() => {
    api.taxelGeometry().then(setGeometry).catch(() => setGeometry(null))
  }, [])

  // Keep the players in sync when the panel (re)mounts; silence on unmount.
  useEffect(() => {
    funPlayer.setAssignments(funEnabled ? funSounds : null)
    return () => funPlayer.setAssignments(null)
  }, [funEnabled, funSounds])

  useEffect(() => {
    stringSynth.setEnabled(musicEnabled)
    return () => stringSynth.setEnabled(false)
  }, [musicEnabled])

  useEffect(() => {
    funPlayer.setRange(funOnN, funFullN)
    stringSynth.setRange(funOnN, funFullN)
  }, [funOnN, funFullN])

  useEffect(() => {
    stringSynth.setVolume(musicVol)
  }, [musicVol])

  useEffect(() => {
    stringSynth.setHarmony(musicRoot, musicScale)
  }, [musicRoot, musicScale])

  useEffect(() => {
    if (handInfo) stringSynth.setJoints(handInfo.joints)
  }, [handInfo])

  useStreamFrame((frames) => {
    const forces = frames.tactile.forces
    const magnitudes: Partial<Record<Finger, number>> = {}
    if (forces) {
      for (const finger of FINGERS) {
        const f = forces[finger]
        if (f) magnitudes[finger] = Math.hypot(f[0], f[1], f[2])
      }
      funPlayer.update(magnitudes)
    }
    const { measured, estimate, target } = frames.joints
    stringSynth.update(magnitudes, {
      ...target,
      ...estimate,
      ...measured,
    })
  })

  const showTaxels = mode === 'taxels' || mode === 'combined'
  const showForces = mode === 'resultant' || mode === 'combined'

  return (
    <Panel title="Tactile Sensors" toolbar={<TaxelControls />}>
      {showTaxels && geometry && (
        <div className="taxels-container">
          {FINGERS.map((finger: Finger) => {
            const fingerGeometry = geometry[finger]
            if (!fingerGeometry) return null
            return (
              <FingerTaxelSvg
                key={finger}
                finger={finger}
                positions={fingerGeometry.positions}
              />
            )
          })}
        </div>
      )}
      {showForces && (
        <div className="forces-container" style={{ marginTop: showTaxels ? 10 : 0 }}>
          {FINGERS.map((finger) => (
            <ForceDial key={finger} finger={finger} />
          ))}
        </div>
      )}
    </Panel>
  )
}
