// The tactile section: controls toolbar + per-finger taxel SVGs + resultant
// dials. Panels render based on which streams actually carry data (mode).

import { useEffect, useState } from 'react'
import { api } from '../../api/rest'
import type { Finger, TaxelGeometry } from '../../api/types'
import { FINGERS } from '../../api/types'
import { useAppStore } from '../../state/appStore'
import { Panel } from '../common/Panel'
import { FingerTaxelSvg } from './FingerTaxelSvg'
import { ForceDial } from './ForceDial'
import { TaxelControls } from './TaxelControls'

export function TactilePanel() {
  const [geometry, setGeometry] = useState<TaxelGeometry | null>(null)
  const control = useAppStore((s) => s.control)
  const mode = control?.tactile_mode ?? 'combined'

  useEffect(() => {
    api.taxelGeometry().then(setGeometry).catch(() => setGeometry(null))
  }, [])

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
