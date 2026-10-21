// The setup workflow as a flowchart under the step tiles: boxes on two rows
// (the tensioning loop, then the calibration loop and Run), arrows with the
// condition that takes you along each one, drawn as one SVG so the eye can
// follow it. Clicking a box shows what happens in that step, why, and what to
// do, in the panel on the right, which stays empty until a box is clicked.
// Edit mode makes every title, note, colour and text editable in place; the
// edits stay in this browser until "Reset".

import { useState } from 'react'
import { useOperationStore } from '../../state/operationStore'
import {
  DEFAULT_WORKFLOW,
  loadWorkflow,
  saveWorkflow,
  WORKFLOW_ARROWS,
  WORKFLOW_LAYOUT,
  type WorkflowStep,
} from './workflow'

// Which step a running operation belongs to, so the chart lights it up.
const STEP_OF_OPERATION: Record<string, string> = {
  tension: 'ratchet',
  guided_tension: 'move',
  slack_test: 'slack',
  calibrate: 'calibrate',
  tension_sweep: 'measure',
  run_in: 'run',
}

// Chart geometry in SVG units.
const BOX_W = 200
const BOX_H = 54
// Wide enough between boxes for an arrow's label.
const COL = 300
const ROW = 118
const PAD_X = 20
// Room above the first row for a loop's label.
const PAD_Y = 36
const COLS = 3
const ROWS = 3
const WIDTH = PAD_X * 2 + (COLS - 1) * COL + BOX_W
const HEIGHT = PAD_Y * 2 + (ROWS - 1) * ROW + BOX_H

function boxAt(key: string): { x: number; y: number } {
  const [col, row] = WORKFLOW_LAYOUT[key] ?? [0, 0]
  return { x: PAD_X + col * COL, y: PAD_Y + row * ROW }
}

export function WorkflowChart() {
  const [steps, setSteps] = useState<WorkflowStep[]>(loadWorkflow)
  const [selected, setSelected] = useState<string | null>(null)
  const [editing, setEditing] = useState(false)
  const operation = useOperationStore((s) => s.operation)
  const runningKey =
    operation && (operation.state === 'running' || operation.state === 'awaiting_input')
      ? (operation.kind === 'guided_tension' && (operation.extra as { step?: string } | null)?.step === 'tension'
          ? (operation.params?.ratchet_joints ? 'again' : 'ratchet')
          : STEP_OF_OPERATION[operation.kind]) ?? null
      : null
  const current = selected ? (steps.find((s) => s.key === selected) ?? null) : null
  const byKey = Object.fromEntries(steps.map((s) => [s.key, s]))

  const update = (key: string, patch: Partial<WorkflowStep>) => {
    const next = steps.map((s) => (s.key === key ? { ...s, ...patch } : s))
    setSteps(next)
    saveWorkflow(next)
  }
  const reset = () => {
    setSteps(DEFAULT_WORKFLOW)
    saveWorkflow(null)
  }

  // An arrow between two boxes: straight to the right, straight down, or a
  // loop that leaves the top of its box and comes back over the boxes between.
  const arrow = (a: (typeof WORKFLOW_ARROWS)[number], i: number) => {
    const from = boxAt(a.from)
    const to = boxAt(a.to)
    let d = ''
    let lx = 0
    let ly = 0
    let anchor: 'start' | 'middle' = 'middle'
    if (a.kind === 'next') {
      const y = from.y + BOX_H / 2
      d = `M ${from.x + BOX_W} ${y} L ${to.x - 6} ${y}`
      lx = (from.x + BOX_W + to.x) / 2
      ly = y - 7
    } else if (a.kind === 'down') {
      const sameCol = from.x === to.x
      const x1 = from.x + BOX_W / 2
      const x2 = to.x + BOX_W / 2
      const yMid = from.y + BOX_H + (to.y - from.y - BOX_H) / 2
      d = sameCol
        ? `M ${x1} ${from.y + BOX_H} L ${x2} ${to.y - 6}`
        : `M ${x1} ${from.y + BOX_H} L ${x1} ${yMid} L ${x2} ${yMid} L ${x2} ${to.y - 6}`
      lx = sameCol ? x1 + 8 : (x1 + x2) / 2
      ly = sameCol ? yMid + 4 : yMid - 6
      anchor = sameCol ? 'start' : 'middle'
    } else {
      // Loop back along the top edge when on one row, along the bottom when it climbs.
      const sameRow = from.y === to.y
      if (sameRow) {
        const y = from.y - 14
        const x1 = from.x + BOX_W / 2
        const x2 = to.x + BOX_W / 2
        d = `M ${x1} ${from.y} L ${x1} ${y} L ${x2} ${y} L ${x2} ${to.y - 6}`
        lx = (x1 + x2) / 2
        ly = y - 5
      } else {
        const x1 = from.x
        const x2 = to.x + BOX_W / 2
        const y1 = from.y + BOX_H / 2
        d = `M ${x1} ${y1} L ${x2} ${y1} L ${x2} ${to.y + BOX_H + 6}`
        lx = (x1 + x2) / 2
        ly = y1 - 7
      }
    }
    return (
      <g key={i} className={`wf-arrow ${a.kind}`}>
        <path d={d} markerEnd="url(#wf-head)" />
        {a.label && (
          <text x={lx} y={ly} textAnchor={anchor}>
            {a.label}
          </text>
        )}
      </g>
    )
  }

  return (
    <section className="workflow" aria-label="Setup workflow">
      <div className="workflow-chart">
        <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img" aria-label="setup workflow">
          <defs>
            <marker id="wf-head" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
              <path d="M 0 0 L 10 5 L 0 10 z" />
            </marker>
          </defs>
          {WORKFLOW_ARROWS.map(arrow)}
          {steps.map((s) => {
            const { x, y } = boxAt(s.key)
            const state = s.key === runningKey ? ' running' : s.key === current?.key ? ' selected' : ''
            return (
              <g
                key={s.key}
                className={`wf-box${state}`}
                style={{ '--box': s.color } as React.CSSProperties}
                transform={`translate(${x} ${y})`}
                role="button"
                tabIndex={0}
                onClick={() => setSelected(s.key === selected ? null : s.key)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') setSelected(s.key)
                }}
              >
                <rect width={BOX_W} height={BOX_H} rx={6} />
                <rect className="wf-bar" width={BOX_W} height={4} rx={2} />
                <text className="wf-title" x={BOX_W / 2} y={25} textAnchor="middle">
                  {s.title}
                </text>
                <text className="wf-note" x={BOX_W / 2} y={42} textAnchor="middle">
                  {s.note}
                </text>
              </g>
            )
          })}
        </svg>
      </div>
      <aside className="workflow-detail" style={{ '--box': current?.color ?? 'var(--panel-border)' } as React.CSSProperties}>
        {!current ? (
          <div className="workflow-empty">
            <span>Click a step for what happens, why, and what to do.</span>
            <span className="gt-header-spacer" />
            <button type="button" className="setup-clear" onClick={() => setEditing((e) => !e)}>
              {editing ? 'done' : 'edit'}
            </button>
            {editing && (
              <button type="button" className="setup-clear" onClick={reset} title="Back to the built-in text and colours">
                reset
              </button>
            )}
          </div>
        ) : (
          <>
            <div className="workflow-detail-head">
              {editing ? (
                <>
                  <input
                    className="workflow-input title"
                    value={current.title}
                    onChange={(e) => update(current.key, { title: e.target.value })}
                    aria-label="step title"
                  />
                  <input
                    className="workflow-input"
                    value={current.note}
                    onChange={(e) => update(current.key, { note: e.target.value })}
                    aria-label="step note"
                  />
                  <input
                    type="color"
                    className="workflow-color"
                    value={toHex(current.color)}
                    onChange={(e) => update(current.key, { color: e.target.value })}
                    aria-label="step colour"
                    title="box colour"
                  />
                </>
              ) : (
                <>
                  <span className="workflow-swatch" />
                  <b>{current.title}</b>
                  <span className="workflow-detail-note">{current.note}</span>
                </>
              )}
              <span className="gt-header-spacer" />
              {editing && (
                <button type="button" className="setup-clear" onClick={reset} title="Back to the built-in text and colours">
                  reset
                </button>
              )}
              <button type="button" className="setup-clear" onClick={() => setEditing((e) => !e)}>
                {editing ? 'done' : 'edit'}
              </button>
              <button type="button" className="gt-close" aria-label="Close" onClick={() => setSelected(null)}>
                ✕
              </button>
            </div>
            <div className="workflow-detail-body">
              {(
                [
                  ['what happens', 'what', 4],
                  ['why', 'why', 3],
                  ['what to do', 'todo', 3],
                ] as const
              ).map(([label, field, rows]) => (
                <div key={field}>
                  <div className="workflow-detail-label">{label}</div>
                  {editing ? (
                    <textarea
                      className="workflow-text"
                      value={byKey[current.key][field]}
                      rows={rows}
                      onChange={(e) => update(current.key, { [field]: e.target.value })}
                      aria-label={label}
                    />
                  ) : (
                    <p className="setup-copy">{byKey[current.key][field]}</p>
                  )}
                </div>
              ))}
            </div>
          </>
        )}
      </aside>
    </section>
  )
}

// <input type="color"> only takes #rrggbb; anything else falls back to grey.
function toHex(color: string): string {
  return /^#[0-9a-f]{6}$/i.test(color) ? color : '#888888'
}
