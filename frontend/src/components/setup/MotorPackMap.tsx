// A blueprint of the forearm motor pack for the Spooling tab. The pack has
// two sides, back and front, each a block of two columns by four rows. The
// IDs run down the left column and back up the right one: side A (the back)
// is 2, 3, 4, 5 down the left and 6, 7, 8, 9 up the right; side B (the
// front) repeats that with 10 to 17. Back is drawn on the left, front on the
// right. Every motor is coloured by how far its spooling has come, and
// clicking one makes it the spool to work on next.

import type { SpoolMotor, SpoolingExtra } from '../../api/types'

type Stage = 'off' | 'pending' | 'winding' | 'bottom' | 'top' | 'over'

const W = 270
const PANEL_W = 122
const PANEL_GAP = 10
const TOP = 46
const ROW = 48
const COLUMN_DX = 27
const RADIUS = 13
const SIDE_NAMES = ['back', 'front']

function stageOf(motor: SpoolMotor | undefined): Stage {
  if (!motor) return 'off'
  if (motor.state === 'over') return 'over'
  if (motor.done || motor.state === 'reached') return 'top'
  if (motor.state === 'winding') return 'winding'
  if (motor.state === 'pending') return 'pending'
  return 'bottom'
}

const STAGE_TITLE: Record<Stage, string> = {
  off: 'not in this run',
  pending: 'waiting',
  winding: 'winding to the hard stop',
  bottom: 'bottom spool done — holding',
  top: 'top spool screwed in',
  over: 'too tight — back the spool off',
}

// Grid slot of the n-th motor of a side: down the left column, then up the
// right one from the bottom.
function slotOf(index: number, rows: number): { column: number; row: number } {
  return index < rows
    ? { column: 0, row: index }
    : { column: 1, row: rows - 1 - (index - rows) }
}

export function MotorPackMap({
  extra,
  onSelect,
}: {
  extra: SpoolingExtra
  onSelect: (joint: string) => void
}) {
  const byId = new Map(extra.motors.map((m) => [m.id, m]))
  const sides = extra.sides
  const rows = Math.max(
    ...sides.map((s) => Math.ceil(s.motor_ids.length / 2)),
    1,
  )
  const panelH = TOP + rows * ROW - 10
  const height = panelH + 66
  const panelsW = sides.length * PANEL_W + (sides.length - 1) * PANEL_GAP
  const left = (W - panelsW) / 2

  return (
    <div className="pack-map">
      <svg
        viewBox={`0 0 ${W} ${height}`}
        className="pack-svg"
        role="img"
        aria-label="motor pack"
      >
        {sides.map((side, panel) => {
          const x0 = left + panel * (PANEL_W + PANEL_GAP)
          const cx = x0 + PANEL_W / 2
          const ids = [...side.motor_ids].sort((a, b) => a - b)
          return (
            <g key={side.id}>
              <rect
                x={x0}
                y={16}
                width={PANEL_W}
                height={panelH}
                rx={10}
                className="pack-body"
              />
              <text x={cx} y={32} className="pack-side-label">
                {SIDE_NAMES[panel] ?? ''} · side {side.id}
              </text>
              {ids.map((id, index) => {
                const { column, row } = slotOf(index, rows)
                const x = cx + (column === 0 ? -COLUMN_DX : COLUMN_DX)
                const y = TOP + row * ROW + RADIUS
                const motor = byId.get(id)
                const stage = stageOf(motor)
                const active = motor !== undefined && motor.joint === extra.active
                const classes = [
                  'pack-motor',
                  stage,
                  active ? 'active' : '',
                  motor?.cooling ? 'cooling' : '',
                ]
                  .filter(Boolean)
                  .join(' ')
                const title = motor
                  ? `${motor.joint} · M${id} · ${STAGE_TITLE[stage]} — click to work on it next`
                  : `M${id} · ${STAGE_TITLE.off}`
                return (
                  <g
                    key={id}
                    className={classes}
                    onClick={motor ? () => onSelect(motor.joint) : undefined}
                    role={motor ? 'button' : undefined}
                    tabIndex={motor ? 0 : undefined}
                    onKeyDown={
                      motor
                        ? (e) => {
                            if (e.key === 'Enter' || e.key === ' ') onSelect(motor.joint)
                          }
                        : undefined
                    }
                  >
                    <title>{title}</title>
                    <circle cx={x} cy={y} r={RADIUS + 5} className="pack-ring" />
                    <circle cx={x} cy={y} r={RADIUS} className="pack-spool" />
                    <text x={x} y={y + 3} className="pack-id">
                      {id}
                    </text>
                    <text x={x} y={y + RADIUS + 10} className="pack-joint">
                      {motor ? motor.joint.replace('_', ' ') : ''}
                    </text>
                  </g>
                )
              })}
            </g>
          )
        })}

        {/* the wrist motor: end of the chain, no spool */}
        <g className="pack-motor off">
          <circle cx={W / 2} cy={height - 34} r={RADIUS} className="pack-spool" />
          <text x={W / 2} y={height - 31} className="pack-id">
            1
          </text>
          <text x={W / 2} y={height - 12} className="pack-joint">
            wrist · no spool
          </text>
        </g>
      </svg>
      <div className="pack-legend">
        <span className="pack-key pending">waiting</span>
        <span className="pack-key winding">winding</span>
        <span className="pack-key bottom">bottom done</span>
        <span className="pack-key top">top screwed in</span>
        <span className="pack-key over">too tight</span>
      </div>
    </div>
  )
}
