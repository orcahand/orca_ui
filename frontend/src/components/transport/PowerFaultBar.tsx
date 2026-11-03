// Supply and wiring faults, on every tab and in red. These are the faults
// nothing recovers from: a reboot clears the flag and it latches again on the
// next command, and cooling is irrelevant. The hand should be powered down,
// so saying so has to be impossible to miss rather than a row in a table on
// one tab.

import { useStreamFrame } from '../../hooks/useStreamFrame'
import { useState } from 'react'

type Offender = { id: string; joint: string | null; flags: string }

export function PowerFaultBar() {
  const [offenders, setOffenders] = useState<Offender[]>([])

  useStreamFrame((frames) => {
    const motors = frames.motors.faults?.motors ?? {}
    const found: Offender[] = []
    for (const [id, entry] of Object.entries(motors)) {
      const hw = entry.hw_error
      if (hw && hw.kind === 'power') {
        found.push({
          id,
          joint: entry.joint ?? null,
          flags: hw.flags.join(' + '),
        })
      }
    }
    // Compared as a string so an unchanged set does not re-render at the
    // stream rate.
    const key = found.map((o) => `${o.id}:${o.flags}`).join(',')
    setOffenders((previous) =>
      previous.map((o) => `${o.id}:${o.flags}`).join(',') === key
        ? previous
        : found,
    )
  })

  if (offenders.length === 0) return null

  const who = offenders
    .map((o) => `motor ${o.id}${o.joint ? ` (${o.joint})` : ''} — ${o.flags}`)
    .join('; ')

  return (
    <div className="transport-bar error" role="alert">
      <span className="transport-kind">⚠ power fault</span>
      <span className="transport-detail">
        {`${who}. Turn the hand off. This is a supply or wiring fault: it is `}
        {'not recovered, cooling will not help, and driving on is what damages '}
        {'motors. Check this motor’s cable and connector at both ends, and '}
        {'the rail voltage under load.'}
      </span>
    </div>
  )
}
