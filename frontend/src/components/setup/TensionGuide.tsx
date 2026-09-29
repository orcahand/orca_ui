// The tensioning instructions, shared by the Tension card and the Full setup
// card — both put the user in front of the same holding motors, so both say
// the same thing. Steps show their title only; the how sits behind a hover
// note. Wording follows orca_core's tensioning guide: ratchet the top spool
// clockwise until firm, never past it.

import type { ReactNode } from 'react'
import { api } from '../../api/rest'
import { useAppStore } from '../../state/appStore'
import { HoverNote } from '../common/HoverNote'

function fail(error: unknown) {
  useAppStore.getState().setError(String((error as Error).message ?? error))
}

// The one instruction worth repeating in full wherever the motors are held.
const RATCHET = (
  <>
    With the ratchet, turn the top spool of each motor clockwise until the
    tendon feels firm — you should hear it click. A little give is fine;
    over-tightening makes the hand worse, not better.
  </>
)

export function SetupStep({
  n,
  title,
  children,
}: {
  n: number
  title: string
  children: ReactNode
}) {
  return (
    <li className="setup-step">
      <span className="setup-step-num">{n}</span>
      <HoverNote label={title} className="note-title">
        {children}
      </HoverNote>
    </li>
  )
}

export function TensionSteps({ started }: { started?: boolean }) {
  return (
    <ol className="setup-steps">
      {!started && (
        <SetupStep n={1} title="Start tensioning">
          The motors wind the tendons in and then hold them there. Keep clear
          until they stop moving.
        </SetupStep>
      )}
      <SetupStep n={started ? 1 : 2} title="Tighten every spool">
        {RATCHET}
      </SetupStep>
      <SetupStep n={started ? 2 : 3} title="Release">
        Ends the hold and switches torque off. Press it once every spool is
        done.
      </SetupStep>
    </ol>
  )
}

// Shown while the motors hold: the one moment the user has to do something
// physical, so it takes over the card and carries the Release button.
export function TensionHoldCallout({ options }: { options: string[] }) {
  return (
    <div className="setup-callout">
      <div className="setup-callout-title">▸ Tighten the spools now</div>
      <p className="setup-copy">The motors are holding the tendons. {RATCHET}</p>
      {options.map((option) => (
        <button
          key={option}
          className="btn btn-info setup-release"
          onClick={() => void api.operationInput(option).catch(fail)}
        >
          {option === 'Release' ? 'Done — release the motors' : option}
        </button>
      ))}
    </div>
  )
}
