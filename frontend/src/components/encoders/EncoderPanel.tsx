// Joint-encoder panel: ROM bar gauges grouped by finger, per-joint
// expandable sparklines (collapsed by default, persisted).

import { useState } from 'react'
import type { JointInfo } from '../../api/types'
import { useAppStore } from '../../state/appStore'
import { Panel } from '../common/Panel'
import { JointSparkline } from './JointSparkline'
import { RomBarGauge } from './RomBarGauge'

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

  return (
    <Panel title="Joint Encoders">
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
