// Joint-encoder panel: ROM bar gauges grouped by finger, per-joint
// expandable sparklines (collapsed by default, persisted), with the
// electrical monitor's health verdict fused in as a dot per joint.

import { useState } from 'react'
import type { EncoderJointHealth, JointInfo } from '../../api/types'
import { useSensorsHealth } from '../../hooks/useSensorsHealth'
import { useAppStore } from '../../state/appStore'
import { Diagnosable } from '../common/Diagnosable'
import { Panel } from '../common/Panel'
import { encoderDiagnosis, VERDICT_COLOR } from '../monitor/monitorShared'
import { JointSparkline } from './JointSparkline'
import { RomBarGauge } from './RomBarGauge'

// Windowed health verdict from sensors.health (1 Hz): green = live frames,
// amber = parity errors, red = chip angle error, grey = no chip answering.
// A suppressed sensor (distrusted, measured stream dropped) stays amber
// even while its windows read clean. Clickable — the popover says what is
// wrong and what to check.
function VerdictDot({
  joint,
  health,
  suppressedReason,
  restoreAfterS,
}: {
  joint: string
  health: EncoderJointHealth | undefined
  suppressedReason?: string | null
  restoreAfterS?: number
}) {
  if (!health) return null
  const suppressed = suppressedReason != null
  return (
    <Diagnosable
      diagnoses={[
        encoderDiagnosis(joint, health, suppressedReason, restoreAfterS),
      ]}
      label={`diagnose ${joint} joint sensor`}
    >
      <span
        title={
          suppressed
            ? 'sensor distrusted — using the motor estimate; click for details'
            : health.reason === 'ok'
              ? 'encoder live — click for details'
              : `${health.verdict}: ${health.reason} — click for details`
        }
        style={{
          width: 7,
          height: 7,
          borderRadius: '50%',
          background: suppressed
            ? 'var(--warn)'
            : (VERDICT_COLOR[health.verdict] ?? 'var(--dimmer)'),
          flexShrink: 0,
          display: 'inline-block',
        }}
      />
    </Diagnosable>
  )
}

const GROUP_ORDER = ['wrist', 'thumb', 'index', 'middle', 'ring', 'pinky']

function groupOf(jointId: string): string {
  const prefix = jointId.split('_')[0]
  return GROUP_ORDER.includes(prefix) ? prefix : 'other'
}

function loadExpanded(): Set<string> {
  try {
    return new Set(JSON.parse(localStorage.getItem('orca-ui.sparklines') ?? '[]'))
  } catch {
    return new Set()
  }
}

export function EncoderPanel() {
  const handInfo = useAppStore((s) => s.handInfo)
  const showTarget = useAppStore((s) => s.showSparklineTarget)
  const setShowTarget = useAppStore((s) => s.setShowSparklineTarget)
  const encHealth = useSensorsHealth()?.encoders ?? null
  const [expanded, setExpanded] = useState<Set<string>>(loadExpanded)

  if (!handInfo) return null
  const joints = handInfo.joints.filter((j) => j.encoder_backed)
  if (joints.length === 0) return null

  const toggle = (jointId: string) => {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(jointId)) next.delete(jointId)
      else next.add(jointId)
      localStorage.setItem('orca-ui.sparklines', JSON.stringify([...next]))
      return next
    })
  }

  const groups = new Map<string, JointInfo[]>()
  for (const joint of joints) {
    const group = groupOf(joint.id)
    if (!groups.has(group)) groups.set(group, [])
    groups.get(group)!.push(joint)
  }

  const toolbar = (
    <div className="toolbar">
      {encHealth && (
        <span
          title="encoder slots streaming healthy frames (all slots, including
joints not listed below) · stream rate"
          style={{
            fontSize: 9,
            color:
              encHealth.live === encHealth.total ? 'var(--dim)' : 'var(--warn)',
            marginRight: 8,
            cursor: 'help',
          }}
        >
          {encHealth.live}/{encHealth.total} live · {encHealth.hz.toFixed(0)} Hz
        </span>
      )}
      <label
        className="toggle-label"
        title="overlay the commanded target (purple) on expanded history charts"
      >
        <input
          type="checkbox"
          checked={showTarget}
          onChange={(e) => setShowTarget(e.target.checked)}
        />
        target in history
      </label>
    </div>
  )

  return (
    <Panel title="Joint Encoders" toolbar={toolbar}>
      {GROUP_ORDER.filter((g) => groups.has(g)).map((group) => (
        <div key={group} style={{ marginBottom: 8 }}>
          <div
            style={{
              fontSize: 9,
              fontWeight: 700,
              color: 'var(--dimmer)',
              textTransform: 'uppercase',
              letterSpacing: 1,
              padding: '4px 0 2px',
            }}
          >
            {group}
          </div>
          {groups.get(group)!.map((joint) => (
            <div key={joint.id}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                <VerdictDot
                  joint={joint.id}
                  health={encHealth?.joints[joint.id]}
                  suppressedReason={encHealth?.suppressed?.[joint.id] ?? null}
                  restoreAfterS={encHealth?.restore_after_s}
                />
                <button
                  onClick={() => toggle(joint.id)}
                  title="toggle history"
                  style={{
                    background: 'none',
                    border: 'none',
                    color: expanded.has(joint.id) ? 'var(--accent)' : 'var(--dimmer)',
                    cursor: 'pointer',
                    fontSize: 9,
                    fontFamily: 'var(--font)',
                    padding: '0 2px',
                    width: 14,
                  }}
                >
                  {expanded.has(joint.id) ? '▾' : '▸'}
                </button>
                <div style={{ flex: 1 }}>
                  <RomBarGauge joint={joint} />
                </div>
              </div>
              {expanded.has(joint.id) && <JointSparkline joint={joint} />}
            </div>
          ))}
        </div>
      ))}
    </Panel>
  )
}
