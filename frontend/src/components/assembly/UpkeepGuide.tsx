import { Component, lazy, Suspense, useEffect, useState, type ReactNode } from 'react'
import { UPKEEP_STEPS } from './upkeepSteps'
import './assembly.css'
import './upkeep.css'

const Animation = lazy(() =>
  import('./UpkeepAnimation').then((m) => ({ default: m.UpkeepAnimation })),
)
class AnimationBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false }
  static getDerivedStateFromError() {
    return { failed: true }
  }
  render() {
    return this.state.failed ? (
      <p role="alert">
        The animation could not load.{' '}
        <a href="./assembly/upkeep/index-ap-maintenance.pdf" download>
          Download the illustrated PDF
        </a>{' '}
        or reload to try again.
      </p>
    ) : (
      this.props.children
    )
  }
}
const STORAGE_KEY = 'orca-ui.upkeep.v3'
function readStep() {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? 'null')
    const index = UPKEEP_STEPS.findIndex((step) => step.id === saved?.current)
    return index < 0 ? 0 : index
  } catch {
    return 0
  }
}
export function UpkeepGuide({
  onOpenAssembly,
  active = true,
}: {
  onOpenAssembly: () => void
  active?: boolean
}) {
  const [selected, setSelected] = useState(readStep)
  useEffect(() => {
    try {
      const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? 'null')
      localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({ ...saved, current: UPKEEP_STEPS[selected].id }),
      )
    } catch {
      /* Playback remains available without browser storage. */
    }
  }, [selected])
  return (
    <section id="maintenance" className="assembly-app upkeep-app" aria-label="Maintenance">
      <div className="upkeep-main">
        <div className="upkeep-section-heading">
          <span className="assembly-eyebrow">MAINTENANCE · BASE RIGHT · DYNAMIXEL</span>
          <a href="./assembly/upkeep/index-ap-maintenance.pdf" download>
            Download PDF ↓
          </a>
        </div>
        <p className="upkeep-intro">
          A finger has six tendon ends; the thumb has eight. Keep the other ends attached to their
          spools. Pop out only the parts needed for access. Keep their pins and bearings fitted.
        </p>
        <h2>Step-by-step walkthrough of replacing the index AP tendon</h2>
        <AnimationBoundary>
          <Suspense fallback={<p role="status">Loading the walkthrough…</p>}>
            <Animation selected={selected} onSelect={setSelected} active={active} />
          </Suspense>
        </AnimationBoundary>
        <button className="assembly-text-button upkeep-reference" onClick={onOpenAssembly}>
          Assembly guide: knots and routing →
        </button>
      </div>
    </section>
  )
}
