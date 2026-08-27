// The dashboard's 3D block: URDF hand scene with the motor panel beside it.
// Not a tab of its own — DashboardView lazy-loads it so three.js stays out
// of the shell bundle.

import { useEffect, useState } from 'react'
import { api } from '../../api/rest'
import { useAppStore } from '../../state/appStore'
import { Panel } from '../common/Panel'
import { MotorPanel } from '../motors/MotorPanel'
import { CameraPreview } from '../teleop/CameraPreview'
import type { HandAssets } from '../three/HandScene'
import { HandScene } from '../three/HandScene'
import { SceneControls } from '../three/SceneControls'

export function ThreeDView() {
  const status = useAppStore((s) => s.status)
  const handInfo = useAppStore((s) => s.handInfo)
  // The URDF bundle, fingertips and sensor mounts are all per-side, and the
  // backend serves whichever hand it currently believes is plugged in — so a
  // model swap has to re-fetch them, not just re-render.
  const side = handInfo?.side ?? null
  const [assets, setAssets] = useState<HandAssets | null>(null)
  const [assetError, setAssetError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    Promise.all([
      api.modelMetadata(),
      api.modelFingertips(),
      // Tactile extras are optional — non-touch hands have neither.
      api.modelSensorMounts().catch(() => null),
      api.taxelGeometry().catch(() => null),
    ])
      .then(([metadata, fingertips, sensorMounts, taxelGeometry]) => {
        if (cancelled) return
        setAssets({ metadata, fingertips, sensorMounts, taxelGeometry })
        setAssetError(null)
      })
      .catch((error) => {
        if (!cancelled) setAssetError(String(error.message ?? error))
      })
    return () => {
      cancelled = true
    }
  }, [side])

  const caps = status?.capabilities

  if (assetError) {
    return (
      <Panel title="3D View">
        <div className="detecting-card">
          <div className="big">3D MODEL BUNDLE MISSING</div>
          <div>{assetError}</div>
        </div>
      </Panel>
    )
  }

  if (!assets || !handInfo || !caps) {
    return (
      <Panel title="3D View">
        <div className="detecting-card">
          <div className="big">LOADING</div>
          <div>fetching hand model…</div>
        </div>
      </Panel>
    )
  }

  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: caps.motors ? 'minmax(0, 1fr) 460px' : '1fr',
        gap: 12,
        alignItems: 'start',
      }}
    >
      <Panel
        title={`3D View · ${assets.metadata.side} hand`}
        toolbar={<SceneControls />}
      >
        {/* Capped: the health strip above and the encoder/tactile panels
            below must stay reachable without a marathon scroll. */}
        <div
          style={{ height: 'min(calc(100vh - 320px), 620px)', minHeight: 420 }}
        >
          <HandScene assets={assets} joints={handInfo.joints} caps={caps} />
        </div>
      </Panel>
      {/* CameraPreview self-hides unless a camera teleop session is live. */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        {caps.motors && <MotorPanel />}
        <CameraPreview />
      </div>
    </div>
  )
}
