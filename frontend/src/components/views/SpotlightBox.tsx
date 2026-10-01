// The spotlight itself: one joint, large enough to read at a distance.
//
// A vertical bar over the joint's calibrated range, its position in degrees,
// and the averaged current. Deliberately sparse — this is watched, not
// studied, and every extra number competes with the one that matters.

import type { JointInfo } from '../../api/types'
import { latest } from '../../state/streamStore'
import { Panel } from '../common/Panel'

const RAD2DEG = 180 / Math.PI

export function SpotlightBox({
  joint,
  looping,
  tick,
}: {
  joint: JointInfo | undefined
  looping: boolean
  // Only to force a redraw: the frame store is mutated in place, so nothing
  // in it can be depended on by React directly.
  tick: number
}) {
  void tick
  if (!looping) {
    return (
      <Panel title="Spotlight">
        <div style={{ fontSize: 11, color: 'var(--dimmer)', padding: '8px 0' }}>
          Waiting for a loop. Start one from Poses and this follows along,
          a joint at a time.
        </div>
      </Panel>
    )
  }
  if (!joint) {
    return (
      <Panel title="Spotlight">
        <div style={{ fontSize: 11, color: 'var(--warn)', padding: '8px 0' }}>
          No joint carries a calibrated range, so there is nothing to show a
          position as a fraction of.
        </div>
      </Panel>
    )
  }

  const spot = latest.spotlight
  const motor = String(joint.motor_id)
  const positionRad = spot.positions[motor]
  const measured = latest.joints.measured[joint.id]
  const estimate = latest.joints.estimate[joint.id]
  // Prefer a real joint angle; the raw motor position is a fallback that is
  // in motor space, not joint space, so it is only shown when nothing better
  // exists and is labelled as such.
  const deg =
    measured ?? estimate ?? (positionRad === undefined ? null : positionRad * RAD2DEG)
  const fromMotorSpace = measured === undefined && estimate === undefined

  const [low, high] = joint.rom
  const fraction =
    deg === null ? null : Math.max(0, Math.min(1, (deg - low) / (high - low)))
  const current = spot.currents[motor]
  const peak = spot.peaks[motor]
  const temp = spot.temps[motor]

  return (
    <Panel title="Spotlight">
      <div style={{ display: 'flex', gap: 16, alignItems: 'stretch' }}>
        <Bar fraction={fraction} />
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, minWidth: 0 }}>
          <div
            style={{
              fontSize: 22,
              fontWeight: 700,
              letterSpacing: 0.5,
              color: 'var(--err)',
              textTransform: 'uppercase',
            }}
          >
            {joint.id.replace(/_/g, ' ')}
          </div>
          <div style={{ fontSize: 30, fontVariantNumeric: 'tabular-nums' }}>
            {deg === null ? '--' : deg.toFixed(1)}
            <span style={{ fontSize: 14, color: 'var(--dim)' }}>°</span>
          </div>
          <div style={{ fontSize: 10, color: 'var(--dimmer)' }}>
            of {low.toFixed(0)}° to {high.toFixed(0)}°
            {fromMotorSpace && ' — motor space, no joint angle available'}
          </div>
          <div style={{ fontSize: 20, fontVariantNumeric: 'tabular-nums' }}>
            {current === undefined ? '--' : current.toFixed(0)}
            <span style={{ fontSize: 13, color: 'var(--dim)' }}> mA</span>
            {peak !== undefined && (
              <span style={{ fontSize: 11, color: 'var(--dimmer)' }}>
                {'  peak '}
                {peak.toFixed(0)}
              </span>
            )}
          </div>
          <div style={{ fontSize: 10, color: 'var(--dimmer)' }}>
            {temp === undefined ? '' : `${temp.toFixed(0)} °C · `}
            {spot.achievedHz.toFixed(0)} Hz sampled
          </div>
        </div>
      </div>
    </Panel>
  )
}

/** Travel as a share of the calibrated range, drawn bottom-up. */
function Bar({ fraction }: { fraction: number | null }) {
  return (
    <div
      style={{
        width: 46,
        minHeight: 150,
        alignSelf: 'stretch',
        border: '1px solid var(--dimmer)',
        borderRadius: 3,
        position: 'relative',
        overflow: 'hidden',
        background: 'var(--bg)',
      }}
    >
      <div
        style={{
          position: 'absolute',
          left: 0,
          right: 0,
          bottom: 0,
          height: `${(fraction ?? 0) * 100}%`,
          background: 'var(--err)',
          opacity: 0.75,
          // No transition: the bar is already redrawn at the publish rate, and
          // easing on top of that would lag the hand rather than smooth it.
        }}
      />
    </div>
  )
}
