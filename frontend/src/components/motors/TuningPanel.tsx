// Feedback-loop tuning: a hand-wide Kp / Ki / correction_max row (applies to
// every loop joint) + max_current with Apply and Rebase, plus a per-joint
// table showing the gains the controller is actually running. Joints the loop
// doesn't control have no PI channel — gains never apply to them, so they're
// listed as open-loop rather than made editable.

import { useEffect, useState } from 'react'
import { api } from '../../api/rest'
import type { JointGains } from '../../api/types'
import { useAppStore } from '../../state/appStore'

interface GainEdit {
  kp: string
  ki: string
  corr: string
}

const toEdit = (gains: JointGains): GainEdit => ({
  kp: String(gains.kp),
  ki: String(gains.ki),
  corr: String(gains.correction_max_deg),
})

/** Parsed gain payload, or null when any field isn't a number. */
function parseEdit(edit: GainEdit) {
  const parsed = {
    kp: parseFloat(edit.kp),
    ki: parseFloat(edit.ki),
    correction_max_deg: parseFloat(edit.corr),
  }
  return Object.values(parsed).some(Number.isNaN) ? null : parsed
}

const EMPTY_EDIT: GainEdit = { kp: '', ki: '', corr: '' }

const sameEdit = (a: GainEdit, b: GainEdit): boolean =>
  a.kp === b.kp && a.ki === b.ki && a.corr === b.corr

const sameGains = (a: JointGains | undefined, b: JointGains | undefined): boolean =>
  a !== undefined &&
  b !== undefined &&
  a.kp === b.kp &&
  a.ki === b.ki &&
  a.correction_max_deg === b.correction_max_deg

const inputStyle = {
  width: 56,
  background: 'var(--panel-strong)',
  color: 'var(--text)',
  border: '1px solid var(--panel-border-strong)',
  fontFamily: 'var(--font)',
  fontSize: 10,
  padding: '3px 6px',
  outline: 'none',
} as const

const smallBtn = { padding: '2px 6px', fontSize: 9 } as const

export function TuningPanel() {
  const control = useAppStore((s) => s.control)
  const handInfo = useAppStore((s) => s.handInfo)
  const [handWide, setHandWide] = useState<GainEdit | null>(null)
  const [maxCurrent, setMaxCurrent] = useState('')
  // Only joints the user has typed into; everything else renders live state.
  const [edits, setEdits] = useState<Record<string, GainEdit>>({})
  const [expanded, setExpanded] = useState(false)
  const [statusLine, setStatusLine] = useState('')

  useEffect(() => {
    if (!handWide && control) {
      // control.gains is null when the joints carry different gains — the
      // hand-wide fields then start blank rather than claiming a value.
      setHandWide(control.gains ? toEdit(control.gains) : EMPTY_EDIT)
      setMaxCurrent(String(control.max_current))
    }
  }, [control, handWide])

  const live = control?.joint_gains ?? {}
  const configGains = control?.config_gains ?? {}
  const loopJoints = (handInfo?.joints ?? [])
    .filter((joint) => joint.loop_controlled === true)
    .map((joint) => joint.id)
  const openLoopJoints = (handInfo?.joints ?? [])
    .filter((joint) => joint.loop_controlled === false)
    .map((joint) => joint.id)

  const rowEdit = (joint: string): GainEdit =>
    edits[joint] ?? (live[joint] ? toEdit(live[joint]) : EMPTY_EDIT)

  const setRow = (joint: string, patch: Partial<GainEdit>) =>
    setEdits((prev) => ({ ...prev, [joint]: { ...rowEdit(joint), ...patch } }))
  const clearRows = (joints: string[]) =>
    setEdits((prev) => {
      const next = { ...prev }
      joints.forEach((joint) => delete next[joint])
      return next
    })

  const applyHandWide = async () => {
    if (!handWide) return
    const values = parseEdit(handWide)
    const maxCurrentValue = parseInt(maxCurrent, 10)
    if (!values || Number.isNaN(maxCurrentValue)) {
      setStatusLine('parse error: all fields must be numeric')
      return
    }
    try {
      if (control && maxCurrentValue !== control.max_current) {
        await api.setMaxCurrent(maxCurrentValue)
      }
      await api.setGains(values)
      clearRows(loopJoints)
      setStatusLine(
        `applied to all ${loopJoints.length} loop joints: Kp=${values.kp} ` +
          `Ki=${values.ki} correction_max=${values.correction_max_deg.toFixed(1)}° ` +
          `max_current=${maxCurrentValue}mA`,
      )
    } catch (error) {
      setStatusLine(`apply failed: ${(error as Error).message}`)
    }
  }

  const applyJoints = async (joints: string[]) => {
    if (joints.length === 0) return
    const requests: { joint: string; values: NonNullable<ReturnType<typeof parseEdit>> }[] = []
    for (const joint of joints) {
      const values = parseEdit(rowEdit(joint))
      if (!values) {
        setStatusLine(`parse error on ${joint}: all fields must be numeric`)
        return
      }
      requests.push({ joint, values })
    }
    try {
      // Per-joint calls: each row can carry its own gain set.
      for (const { joint, values } of requests) {
        await api.setGains({ ...values, joints: [joint] })
      }
      clearRows(joints)
      const [first] = requests
      setStatusLine(
        requests.length === 1
          ? `${first.joint}: Kp=${first.values.kp} Ki=${first.values.ki} ` +
              `correction_max=${first.values.correction_max_deg.toFixed(1)}°`
          : `applied gains to ${requests.length} joints`,
      )
    } catch (error) {
      setStatusLine(`apply failed: ${(error as Error).message}`)
    }
  }

  const rebase = async () => {
    try {
      await api.rebase()
      setStatusLine('loop rebased to current pose')
    } catch (error) {
      setStatusLine(`rebase failed: ${(error as Error).message}`)
    }
  }

  const resetJoints = async (joints?: string[]) => {
    try {
      await api.resetGains(joints)
      clearRows(joints ?? loopJoints)
      setStatusLine(
        joints
          ? `${joints.join(', ')} back on the config gains`
          : 'every loop joint back on the config gains',
      )
    } catch (error) {
      setStatusLine(`reset failed: ${(error as Error).message}`)
    }
  }

  const field = (
    label: string,
    value: string,
    onChange: (v: string) => void,
    onEnter: () => void,
  ) => (
    <label
      style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 10, color: 'var(--dim)' }}
    >
      {label}
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => e.key === 'Enter' && onEnter()}
        style={inputStyle}
      />
    </label>
  )

  const cellInput = (joint: string, key: keyof GainEdit) => (
    <input
      value={rowEdit(joint)[key]}
      onChange={(e) => setRow(joint, { [key]: e.target.value })}
      onKeyDown={(e) => e.key === 'Enter' && void applyJoints([joint])}
      style={{ ...inputStyle, width: 52, textAlign: 'right' }}
    />
  )

  const dirtyJoints = loopJoints.filter(
    (joint) =>
      joint in edits && live[joint] && !sameEdit(edits[joint], toEdit(live[joint])),
  )
  const tunedJoints = loopJoints.filter(
    (joint) => joint in configGains && !sameGains(live[joint], configGains[joint]),
  )

  return (
    <div
      style={{
        marginTop: 10,
        paddingTop: 10,
        borderTop: '1px solid var(--panel-border)',
        display: 'flex',
        flexDirection: 'column',
        gap: 8,
      }}
    >
      <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
        <span style={{ fontSize: 9, fontWeight: 700, color: 'var(--dimmer)', letterSpacing: 1 }}>
          TUNING
        </span>
        {handWide && (
          <>
            {field('Kp', handWide.kp, (v) => setHandWide({ ...handWide, kp: v }), () =>
              void applyHandWide(),
            )}
            {field('Ki', handWide.ki, (v) => setHandWide({ ...handWide, ki: v }), () =>
              void applyHandWide(),
            )}
            {field('corr_max °', handWide.corr, (v) => setHandWide({ ...handWide, corr: v }), () =>
              void applyHandWide(),
            )}
          </>
        )}
        {field('max mA', maxCurrent, setMaxCurrent, () => void applyHandWide())}
        <button className="btn btn-primary" onClick={() => void applyHandWide()}>
          Apply To All
        </button>
        <button className="btn btn-secondary" onClick={() => void rebase()}>
          Rebase Loop
        </button>
        <span style={{ fontSize: 9, color: 'var(--dim)' }}>{statusLine}</span>
      </div>

      <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
        <button
          className="btn btn-secondary"
          style={smallBtn}
          onClick={() => setExpanded((open) => !open)}
        >
          {expanded ? '▾' : '▸'} PER-JOINT GAINS ({loopJoints.length})
        </button>
        <span style={{ fontSize: 9, color: 'var(--dimmer)' }}>
          {control && control.gains === null
            ? 'joints are tuned individually'
            : 'every loop joint on the same gains'}
          {tunedJoints.length > 0 &&
            ` · ${tunedJoints.length} changed from config: ${tunedJoints.join(', ')}`}
        </span>
      </div>

      {expanded && (
        <div>
          {loopJoints.length === 0 ? (
            <div style={{ fontSize: 10, color: 'var(--dimmer)' }}>
              no loop-controlled joints — nothing to tune
            </div>
          ) : (
            <>
              <table className="motor-table" style={{ maxWidth: 500 }}>
                <thead>
                  <tr>
                    <th>JOINT</th>
                    <th>Kp</th>
                    <th>Ki</th>
                    <th>CORR °</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {loopJoints.map((joint) => (
                    <tr key={joint}>
                      <td>
                        {joint}
                        {tunedJoints.includes(joint) && (
                          <span style={{ color: 'var(--accent)', marginLeft: 4 }}>*</span>
                        )}
                      </td>
                      <td>{cellInput(joint, 'kp')}</td>
                      <td>{cellInput(joint, 'ki')}</td>
                      <td>{cellInput(joint, 'corr')}</td>
                      <td style={{ whiteSpace: 'nowrap' }}>
                        <button
                          className="btn btn-primary"
                          style={smallBtn}
                          onClick={() => void applyJoints([joint])}
                        >
                          Set
                        </button>{' '}
                        <button
                          className="btn btn-secondary"
                          style={smallBtn}
                          disabled={!tunedJoints.includes(joint) && !(joint in edits)}
                          onClick={() => void resetJoints([joint])}
                        >
                          Reset
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div
                style={{
                  display: 'flex',
                  gap: 8,
                  alignItems: 'center',
                  flexWrap: 'wrap',
                  marginTop: 6,
                }}
              >
                <button
                  className="btn btn-primary"
                  style={smallBtn}
                  disabled={dirtyJoints.length === 0}
                  onClick={() => void applyJoints(dirtyJoints)}
                >
                  Apply Edited ({dirtyJoints.length})
                </button>
                <button
                  className="btn btn-secondary"
                  style={smallBtn}
                  disabled={tunedJoints.length === 0}
                  onClick={() => void resetJoints()}
                >
                  Reset All To Config
                </button>
                <span style={{ fontSize: 9, color: 'var(--dimmer)' }}>
                  * = changed from config.yaml's joint_control_gains
                </span>
              </div>
              {openLoopJoints.length > 0 && (
                <div style={{ fontSize: 9, color: 'var(--warn)', marginTop: 6 }}>
                  open-loop (no PI channel, gains don't apply):{' '}
                  {openLoopJoints.join(', ')} — recalibrate to bring them into the loop
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  )
}
