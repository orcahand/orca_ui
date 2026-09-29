// The URDF hand scene as a panel, with its own asset loading. Shared by the
// dashboard (where it is the always-present centrepiece) and the 3D tab
// (where it gets the full window height).
//
// The bundle, fingertips and sensor mounts are all per-side and the backend
// serves whichever hand it currently believes is plugged in, so a model swap
// re-fetches rather than re-renders.

import { useEffect, useState } from 'react'
import { api } from '../../api/rest'
import { useAppStore } from '../../state/appStore'
import { Panel } from '../common/Panel'
import type { HandAssets } from './HandScene'
import { HandScene } from './HandScene'
import { SceneControls } from './SceneControls'

export function HandScenePanel({ height }: { height: string | number }) {
  const status = useAppStore((s) => s.status)
  const handInfo = useAppStore((s) => s.handInfo)
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
    <Panel
      title={`3D View · ${assets.metadata.side} hand`}
      toolbar={<SceneControls />}
    >
      <div style={{ height, minHeight: 320 }}>
        <HandScene assets={assets} joints={handInfo.joints} caps={caps} />
      </div>
    </Panel>
  )
}
