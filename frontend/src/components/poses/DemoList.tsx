// Movement scripts: orca_core demo presets + orca_ui built-in sequences,
// played as `demo` operations (they acquire the control source and render
// in the transport bar).

import { useState } from 'react'
import { api } from '../../api/rest'
import type { DemoEntry } from '../../api/types'
import { useAppStore } from '../../state/appStore'
import { useStartGate } from '../../state/operationStore'
import { Panel } from '../common/Panel'

// One run by default; one step up is nonstop (loops until stopped from
// the transport bar or E-stop).
const CYCLE_CHOICES = ['1', '∞'] as const
type CycleChoice = (typeof CYCLE_CHOICES)[number]

function fail(error: unknown) {
  useAppStore.getState().setError(String((error as Error).message ?? error))
}

export function DemoList({ demos }: { demos: DemoEntry[] }) {
  const gate = useStartGate('motors')
  const torqueOn = useAppStore((s) => s.control?.torque_enabled ?? false)
  const [cycles, setCycles] = useState<Record<string, CycleChoice>>({})

  // No torque gate: the demo operation enables torque itself and restores
  // it afterwards. Whatever still blocks (another operation, teleop, no
  // motors) is named right here, not just in a tooltip.
  const blocked = gate.blocked
  const reason = gate.reason

  const play = (name: string) => {
    const choice = cycles[name] ?? '1'
    const params =
      choice === '∞' ? { name, loop: true } : { name, cycles: 1 }
    void api.operationStart('demo', params).catch(fail)
  }

  return (
    <Panel title="Movement Scripts">
      {demos.length === 0 ? (
        <div className="panel-empty">no movement scripts available</div>
      ) : (
        <>
          {blocked ? (
            <div className="panel-hint">
              cannot play right now: {reason ?? 'blocked'}
            </div>
          ) : (
            !torqueOn && (
              <div className="panel-hint">
                torque is off — a script enables it for the run and turns it
                back off afterwards
              </div>
            )
          )}
          {demos.map((demo) => (
            <div key={demo.name} className="demo-row">
              <span className="demo-name">{demo.name}</span>
              <span
                className={`source-badge${
                  demo.source === 'orca_core' ? ' core' : ''
                }`}
              >
                {demo.source}
              </span>
              <span className="demo-poses">{demo.poses} poses</span>
              <span className="demo-controls">
                <label className="demo-cycles">
                  cycles
                  <select
                    value={cycles[demo.name] ?? '1'}
                    onChange={(e) =>
                      setCycles((prev) => ({
                        ...prev,
                        [demo.name]: e.target.value as CycleChoice,
                      }))
                    }
                  >
                    {CYCLE_CHOICES.map((n) => (
                      <option key={n} value={n}>
                        {n}
                      </option>
                    ))}
                  </select>
                </label>
                <button
                  className="btn btn-primary"
                  disabled={blocked}
                  title={reason ?? `play ${demo.name}`}
                  onClick={() => play(demo.name)}
                >
                  ▶ play
                </button>
              </span>
            </div>
          ))}
        </>
      )}
    </Panel>
  )
}
