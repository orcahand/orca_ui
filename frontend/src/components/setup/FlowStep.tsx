// One tile of the Setup flow: numbered badge, title, a status chip, an info
// note and an optional settings drawer. The body carries the step's controls.

import { useState, type ReactNode } from 'react'
import { HoverNote } from '../common/HoverNote'

export type StepState = 'done' | 'next' | 'todo' | 'running' | 'warn'

const MARK: Record<StepState, string | null> = {
  done: '✓',
  running: '●',
  warn: '!',
  next: null,
  todo: null,
}

export function FlowStep({
  n,
  title,
  state,
  chip,
  info,
  settings,
  children,
}: {
  n: number
  title: string
  state: StepState
  chip?: ReactNode
  info: ReactNode
  settings?: ReactNode
  children: ReactNode
}) {
  const [open, setOpen] = useState(false)
  return (
    <section className={`flow-step ${state}`}>
      <header className="flow-step-head">
        <span className="flow-step-num">{MARK[state] ?? n}</span>
        <span className="flow-step-title">{title}</span>
        {chip !== undefined && <span className="flow-chip">{chip}</span>}
        <span className="flow-step-tools">
          <HoverNote label="">{info}</HoverNote>
          {settings && (
            <button
              type="button"
              className={`flow-settings-toggle${open ? ' on' : ''}`}
              title="Additional settings"
              aria-expanded={open}
              onClick={() => setOpen((o) => !o)}
            >
              <span>Additional Settings</span>
              <span aria-hidden="true">⚙</span>
            </button>
          )}
        </span>
      </header>
      <div className="flow-step-body">{children}</div>
      {settings && open && <div className="flow-settings">{settings}</div>}
    </section>
  )
}

export function FlowProgress({ value }: { value: number | null }) {
  if (value === null) return null
  return (
    <div className="setup-progress">
      <div
        className="setup-progress-fill"
        style={{ width: `${Math.min(Math.max(value, 0), 1) * 100}%` }}
      />
    </div>
  )
}

// Phase chip + detail for a running operation, in one compact line.
export function FlowRunning({
  phase,
  detail,
}: {
  phase: string | null
  detail: string | null
}) {
  return (
    <div className="flow-running">
      {phase && <span className="phase-step active">{phase}</span>}
      {detail && <span className="flow-detail">{detail}</span>}
    </div>
  )
}
