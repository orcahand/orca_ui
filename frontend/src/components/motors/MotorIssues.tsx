// Active motor problems, one row each, above the per-motor grid.
//
// The grid answers "what is motor 12 doing"; this answers "what is wrong right
// now", which is the question an operator actually arrives with. Rows name the
// motor, the joint it drives and the fault itself — the latched bits verbatim,
// not a category — so nothing has to be hovered or clicked to be seen.

import type { MotorIssue } from './motorIssueRules'
import { RebootButton } from './RebootButton'

function SeverityDot({ severity }: { severity: MotorIssue['severity'] }) {
  const color = severity === 'error' ? 'var(--err)' : 'var(--warn)'
  return (
    <span
      aria-label={severity}
      title={severity}
      style={{
        display: 'inline-block',
        width: 6,
        height: 6,
        borderRadius: '50%',
        background: color,
      }}
    />
  )
}

export function MotorIssues({ issues }: { issues: MotorIssue[] }) {
  if (issues.length === 0) {
    return (
      <div style={{ fontSize: 10, color: 'var(--ok)', marginBottom: 6 }}>
        no motor faults
      </div>
    )
  }

  const errors = issues.filter((i) => i.severity === 'error').length
  const warnings = issues.length - errors

  return (
    <div style={{ marginBottom: 8 }}>
      <div
        style={{
          fontSize: 9,
          fontWeight: 700,
          letterSpacing: 1,
          color: errors > 0 ? 'var(--err)' : 'var(--warn)',
          marginBottom: 3,
        }}
      >
        {errors > 0 && `${errors} ERROR${errors === 1 ? '' : 'S'}`}
        {errors > 0 && warnings > 0 && ' · '}
        {warnings > 0 && `${warnings} WARNING${warnings === 1 ? '' : 'S'}`}
      </div>
      <table className="motor-table motor-issues">
        <thead>
          <tr>
            <th aria-label="severity" />
            <th>MOTOR</th>
            <th>JOINT</th>
            <th title="the latched error bits, or what the reading shows">
              ERROR
            </th>
            <th>DETAIL</th>
            <th aria-label="action" />
          </tr>
        </thead>
        <tbody>
          {issues.map((issue, index) => (
            <tr key={`${issue.motorId}-${issue.label}-${index}`}>
              <td>
                <SeverityDot severity={issue.severity} />
              </td>
              <td>{issue.motorId}</td>
              <td className="motor-joint">{issue.joint ?? '--'}</td>
              <td
                className={issue.severity === 'error' ? 'err' : 'warn'}
                title={issue.checks.join('\n')}
              >
                {issue.label}
              </td>
              <td className="motor-issue-detail">{issue.detail}</td>
              <td>
                {issue.reboot && (
                  <RebootButton
                    id={issue.motorId}
                    needsCooling={issue.reboot.needsCooling}
                  />
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
