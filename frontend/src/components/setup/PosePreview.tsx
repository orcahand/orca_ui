// The hand at mid-range, for "bring the hand to this pose first": every joint
// halfway between its stops, so no tendon starts a measurement already pulled
// against a hard stop. Loads the model's metadata itself, so any dialog can
// show it with one line.

import { lazy, Suspense, useEffect, useState, type ReactNode } from 'react'
import { api } from '../../api/rest'
import type { ModelMetadata } from '../../api/types'
import { useAppStore } from '../../state/appStore'
import { ErrorBoundary } from '../common/ErrorBoundary'
import { failToBanner } from './setupUtils'

const TensionPreview = lazy(() => import('./TensionPreview').then((m) => ({ default: m.TensionPreview })))

export function PosePreview({ caption }: { caption?: ReactNode }) {
  const handInfo = useAppStore((s) => s.handInfo)
  const caps = useAppStore((s) => s.status?.capabilities)
  const [metadata, setMetadata] = useState<ModelMetadata | null>(null)
  useEffect(() => {
    api.modelMetadata().then(setMetadata).catch(failToBanner)
  }, [handInfo?.side])
  if (!metadata || !handInfo) return <div className="gt-preview">loading model…</div>
  return (
    <ErrorBoundary
      label="The hand preview"
      fallback={(error) => (
        <div className="gt-preview" title={error.message}>
          3D preview unavailable in this window — the steps still work.
        </div>
      )}
    >
      <Suspense fallback={<div className="gt-preview">loading model…</div>}>
        <TensionPreview
          urdfUrl={metadata.urdf_url}
          joints={handInfo.joints}
          mode="still"
          statuses={{}}
          blackSkin={(handInfo.tactile_skin ?? caps?.declared?.tactile ?? caps?.tactile) === true}
          caption={caption}
        />
      </Suspense>
    </ErrorBoundary>
  )
}
