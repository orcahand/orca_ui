// The two tower faces stacked on the left, each with its eight spools listed
// beside it: the layout the per-spool results in the Setup tab use (slack
// test, tension sweep). The caller gives the column heads and a cell renderer
// per joint; the spool mark colours the row's edge and the spool on the
// render. Pictures only (the ratchet step) puts the two faces side by side,
// large, with each spool's tag beside its name.

import type { ReactNode } from 'react'
import { useAppStore } from '../../state/appStore'
import { FaceView, useMotorIds, useSpoolMarks, type SpoolMark, type TagStyle } from './TowerPreview'
import { spoolJoint, spoolsOnFace, type TowerFace } from './towerLayout'

export const jointLabel = (joint: string) => joint.replace('_', ' ')

export function TowerFaces({
  marks,
  joints,
  head,
  row,
  columns,
  activeJoints,
  onSelect,
  withList = true,
  tags = 'motor',
}: {
  marks: SpoolMark[]
  // Which joints to list; the rest of the face is left out. Defaults to the marked ones.
  joints?: string[]
  head: ReactNode[]
  // Cells after the motor and joint columns.
  row: (joint: string, mark: SpoolMark | undefined) => ReactNode[]
  // CSS grid columns for the cells after motor and joint.
  columns: string
  activeJoints?: Set<string>
  // Rows become buttons: the caller opens something for that joint.
  onSelect?: (joint: string) => void
  // Pictures only, no list beside them.
  withList?: boolean
  // 'full' puts each spool's tag beside its name on the render.
  tags?: TagStyle
}) {
  const side = useAppStore((s) => s.handInfo?.side) ?? 'right'
  const byJoint = useSpoolMarks(marks)
  const motorIds = useMotorIds()
  const listed = new Set(joints ?? marks.map((m) => m.joint))
  const style = { gridTemplateColumns: `44px 110px ${columns}` }
  return (
    <div className={`probe-faces${withList ? '' : ' pictures-only'}`}>
      {(['F', 'B'] as const).map((face: TowerFace) => (
        <div key={face} className={`probe-face-row${withList ? '' : ' pictures-only'}`}>
          <div className="probe-face-view">
            <FaceView side={side} face={face} byJoint={byJoint} tags={tags} />
          </div>
          {withList && (
          <div className="probe-spool-list">
            <div className="probe-spool-row head" style={style}>
              <span>motor</span>
              <span>joint</span>
              {head.map((h, i) => (
                <span key={i}>{h}</span>
              ))}
            </div>
            {spoolsOnFace(face)
              .map((pos) => ({ pos, joint: spoolJoint(side, pos) }))
              .filter((s) => listed.has(s.joint))
              .map(({ pos, joint }) => {
                const mark = byJoint[joint]
                return (
                  <div
                    key={pos}
                    className={`probe-spool-row mark-${mark?.status ?? 'unscored'}${activeJoints?.has(joint) ? ' active' : ''}${onSelect ? ' clickable' : ''}`}
                    style={style}
                    role={onSelect ? 'button' : undefined}
                    tabIndex={onSelect ? 0 : undefined}
                    title={onSelect ? `show ${jointLabel(joint)}` : undefined}
                    onClick={onSelect ? () => onSelect(joint) : undefined}
                    onKeyDown={onSelect ? (e) => { if (e.key === 'Enter' || e.key === ' ') onSelect(joint) } : undefined}
                  >
                    <b>M{mark?.motor || motorIds[joint] || '?'}</b>
                    <span className="probe-spool-joint">{jointLabel(joint)}</span>
                    {row(joint, mark).map((cell, i) => (
                      <span key={i}>{cell}</span>
                    ))}
                  </div>
                )
              })}
          </div>
          )}
        </div>
      ))}
    </div>
  )
}
