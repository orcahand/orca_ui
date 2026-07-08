// Movement scripts: orca_core demo presets + orca_ui built-in sequences,
// played as `demo` operations (they acquire the control source and render
// in the transport bar).

import { useState } from 'react'
import { api } from '../../api/rest'
import type { DemoEntry } from '../../api/types'
import { useAppStore } from '../../state/appStore'
import { useStartGate } from '../../state/operationStore'
import { Panel } from '../common/Panel'

const CYCLE_CHOICES = Array.from({ length: 10 }, (_, i) => i + 1)

function fail(error: unknown) {
  useAppStore.getState().setError(String((error as Error).message ?? error))
}

export function DemoList({ demos }: { demos: DemoEntry[] }) {
  const gate = useStartGate('motors')
  const torqueOn = useAppStore((s) => s.control?.torque_enabled ?? false)
  const [cycles, setCycles] = useState<Record<string, number>>({})

  const blocked = gate.blocked || !torqueOn
  const reason =
    gate.reason ?? (!torqueOn ? 'enable torque to play scripts' : null)

  const play = (name: string) =>
    void api
      .operationStart('demo', { name, cycles: cycles[name] ?? 1 })
      .catch(fail)

  return (
    <Panel title="Movement Scripts">
      {demos.length === 0 ? (
        <div className="panel-empty">no movement scripts available</div>
      ) : (
        <>
          {blocked && <div className="panel-hint">{reason}</div>}
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
                    value={cycles[demo.name] ?? 1}
                    onChange={(e) =>
                      setCycles((prev) => ({
                        ...prev,
                        [demo.name]: Number(e.target.value),
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
