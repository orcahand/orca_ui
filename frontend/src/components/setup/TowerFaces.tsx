// The two tower faces stacked on the left, each with its eight spools listed
// beside it: the one layout every per-spool result in the Setup tab uses
// (tension check, slack test, measurement, the ratchet step). The caller
// gives the column heads and a cell renderer per joint; the spool mark
// colours the row's edge and the spool on the render.

import type { ReactNode } from 'react'
import { useAppStore } from '../../state/appStore'
import { FaceView, useSpoolMarks, type SpoolMark } from './TowerPreview'
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
}) {
  const side = useAppStore((s) => s.handInfo?.side) ?? 'right'
  const byJoint = useSpoolMarks(marks)
  const listed = new Set(joints ?? marks.map((m) => m.joint))
  const style = { gridTemplateColumns: `44px 110px ${columns}` }
  return (
    <div className={`probe-faces${withList ? '' : ' pictures-only'}`}>
      {(['F', 'B'] as const).map((face: TowerFace) => (
        <div key={face} className={`probe-face-row${withList ? '' : ' pictures-only'}`}>
          <div className="probe-face-view">
            <FaceView side={side} face={face} byJoint={byJoint} tags="motor" />
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
                    <b>M{mark?.motor || '?'}</b>
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
