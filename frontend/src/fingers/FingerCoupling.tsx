// Step 2 — coupling: which tendons move each joint, and by how much. Every
// joint is one editable formula line, q = gain · θ(tendon) + gain · θ(tendon)
// + …, grouped by finger. The routing panel at the top holds the one rule a
// hand's fingers share — MCP and PIP as a sum and a difference of the pp
// tendon (proximal phalanx, U) and the pip tendon (fingertip, C) — with its
// radii, and writes the gains it produces into every finger; the lines stay
// editable afterwards.

import { useMemo } from 'react'
import { useFingerStore, groupsOf, resolve, tendonsFor, type FingerJoint } from './fingerStore'
import { couplingProblem, couplingsOf } from './coupling'

function JointFormula({ joint, index, locked }: { joint: FingerJoint; index: number; locked: boolean }) {
  const patchJoint = useFingerStore((s) => s.patchJoint)
  const removeJoint = useFingerStore((s) => s.removeJoint)
  const moveJoint = useFingerStore((s) => s.moveJoint)
  const tendons = useFingerStore((s) => s.tendons)
  // Abduction is one tendon on one motor, never a combination: just the tendon.
  const single = /_abd$/i.test(joint.name)
  const count = useFingerStore((s) => s.joints.length)
  const joints = useFingerStore((s) => s.joints)
  const coupling = useMemo(() => {
    const resolved = resolve(joints, tendons)
    return couplingsOf(resolved).find((c) => c.joints.some((j) => j.name === joint.name))
  }, [joints, tendons, joint.name])
  const problem = coupling ? couplingProblem(coupling) : 'no tendon'
  const offered = tendonsFor(joint, tendons)
  const partners = coupling ? coupling.joints.filter((j) => j.name !== joint.name).map((j) => j.name) : []

  const setTerm = (i: number, patch: Partial<{ tendon: string; gain: number }>) =>
    patchJoint(index, {
      terms: single
        ? [{ tendon: patch.tendon ?? joint.terms[0]?.tendon, gain: 1 }]
        : joint.terms.map((t, k) => (k === i ? { ...t, ...patch } : t)),
    })
  const addTerm = () => {
    const used = new Set(joint.terms.map((t) => t.tendon))
    const free = offered.find((t) => !used.has(t.name))
    if (free) patchJoint(index, { terms: [...joint.terms, { tendon: free.name, gain: 1 }] })
  }
  const removeTerm = (i: number) => patchJoint(index, { terms: joint.terms.filter((_, k) => k !== i) })

  return (
    <div className={`finger-row finger-formula-row ${problem ? 'incomplete' : ''}`}>
      <div className="finger-row-main">
        <span className="finger-q">q</span>
        <input
          className="finger-name"
          value={joint.name}
          disabled={locked}
          title="joint name"
          onChange={(e) => patchJoint(index, { name: e.target.value })}
        />
        <span className="finger-term-times">=</span>
        {(single ? joint.terms.slice(0, 1) : joint.terms).map((term, i) => (
          <span key={i} className="finger-term">
            {i > 0 && <span className="finger-term-plus">+</span>}
            {!single && (
              <input
                type="number"
                step={0.01}
                value={term.gain}
                disabled={locked}
                title="gain: joint degrees per shaft degree of this tendon"
                onChange={(e) => {
                  const gain = parseFloat(e.target.value)
                  if (Number.isFinite(gain)) setTerm(i, { gain })
                }}
              />
            )}
            <span className="finger-term-times">{single ? 'θ(' : '· θ('}</span>
            <select
              value={term.tendon ?? ''}
              disabled={locked}
              title="a tendon of this finger that moves the joint"
              onChange={(e) => setTerm(i, { tendon: e.target.value })}
            >
              {term.tendon === undefined && <option value="">?</option>}
              {offered.map((t) => (
                <option key={t.name} value={t.name}>
                  {t.name}
                </option>
              ))}
            </select>
            <span className="finger-term-times">)</span>
            {!single && joint.terms.length > 1 && (
              <button
                className="btn btn-secondary finger-remove"
                disabled={locked}
                title="drop this tendon"
                onClick={() => removeTerm(i)}
              >
                ×
              </button>
            )}
          </span>
        ))}
        {single ? (
          joint.terms.length === 0 && (
            <button className="btn btn-secondary" disabled={locked || offered.length === 0} onClick={addTerm}>
              pick tendon
            </button>
          )
        ) : (
          <button
            className="btn btn-secondary"
            disabled={locked || joint.terms.length >= offered.length}
            title="another tendon that moves this joint"
            onClick={addTerm}
          >
            + tendon
          </button>
        )}
        <span className="finger-span">
          {problem ? problem : single ? 'abduction: its own motor' : partners.length ? `coupled with ${partners.join(', ')}` : 'independent'}
        </span>
        <span className="finger-row-tools">
          <input
            className="finger-group"
            value={joint.group}
            placeholder="finger"
            disabled={locked}
            title="finger: joints of one finger share a curl slider"
            onChange={(e) => patchJoint(index, { group: e.target.value })}
          />
          <button className="btn btn-secondary" disabled={locked || index === 0} title="move up" onClick={() => moveJoint(index, -1)}>
            ↑
          </button>
          <button className="btn btn-secondary" disabled={locked || index === count - 1} title="move down" onClick={() => moveJoint(index, 1)}>
            ↓
          </button>
          <button className="btn btn-secondary finger-remove" disabled={locked} title="remove this joint" onClick={() => removeJoint(index)}>
            ×
          </button>
        </span>
      </div>
    </div>
  )
}

function RoutingPanel({ locked }: { locked: boolean }) {
  const settings = useFingerStore((s) => s.settings)
  const patchSettings = useFingerStore((s) => s.patchSettings)
  const coupleFingers = useFingerStore((s) => s.coupleFingers)
  const joints = useFingerStore((s) => s.joints)
  const pairs = groupsOf(joints).filter(
    ({ joints: m }) => m.some((j) => /_mcp$/i.test(j.name)) && m.some((j) => /_pip$/i.test(j.name)),
  ).length
  const field = (key: 'spoolRadiusMm' | 'mcpRadiusMm' | 'pipRadiusMm', label: React.ReactNode, title: string) => (
    <label className="stress-field" title={title}>
      {label}
      <input
        type="number"
        step={0.1}
        min={0.1}
        value={settings[key]}
        disabled={locked}
        onChange={(e) => {
          const v = parseFloat(e.target.value)
          if (Number.isFinite(v) && v > 0) patchSettings({ [key]: v })
        }}
      />
      mm
    </label>
  )
  return (
    <div className="finger-helper">
      <span className="thermal-group-title">tendon routing in every finger</span>
      <ul className="finger-formula" aria-label="coupling of MCP and PIP in every finger">
        <li>
          q<sub>MCP</sub> = r<sub>s</sub>(θ<sub>pp</sub> + θ<sub>pip</sub>) / {settings.mcpRadiusMm}
          <small>= {(settings.spoolRadiusMm / settings.mcpRadiusMm).toFixed(3)} · (θ<sub>pp</sub> + θ<sub>pip</sub>)</small>
        </li>
        <li>
          q<sub>PIP</sub> = r<sub>s</sub>(θ<sub>pp</sub> − θ<sub>pip</sub>) / {settings.pipRadiusMm}
          <small>= {(settings.spoolRadiusMm / settings.pipRadiusMm).toFixed(3)} · (θ<sub>pp</sub> − θ<sub>pip</sub>)</small>
        </li>
      </ul>
      <div className="bench-fields">
        {field('spoolRadiusMm', <>r<sub>s</sub></>, 'spool radius on the motor')}
        {field('mcpRadiusMm', <>r<sub>MCP</sub></>, 'effective radius at the MCP joint')}
        {field('pipRadiusMm', <>r<sub>PIP</sub></>, 'effective radius at the PIP joint')}
        <button
          className="btn btn-primary"
          disabled={locked || pairs === 0}
          title="write these gains into the MCP and PIP lines of every finger, on the pp (U) and pip (C) tendons those lines name"
          onClick={coupleFingers}
        >
          apply to {pairs} finger{pairs === 1 ? '' : 's'}
        </button>
        <small className="finger-hint">abduction is one tendon on its own motor; edit any other line below by hand</small>
      </div>
    </div>
  )
}

export function FingerCoupling({ locked }: { locked: boolean }) {
  const joints = useFingerStore((s) => s.joints)
  const tendons = useFingerStore((s) => s.tendons)
  const addJoint = useFingerStore((s) => s.addJoint)
  const resolved = useMemo(() => resolve(joints, tendons), [joints, tendons])
  const okNames = useMemo(
    () => new Set(couplingsOf(resolved).filter((c) => couplingProblem(c) === null).flatMap((c) => c.joints.map((j) => j.name))),
    [resolved],
  )

  return (
    <section className="panel finger-setup">
      <div className="panel-header">
        <h2>Coupling</h2>
        <small className="finger-hint">each joint's angle as a sum of gain × tendon shaft angle</small>
        <button className="btn btn-secondary" disabled={locked || joints.length >= 32} onClick={addJoint}>
          + joint
        </button>
      </div>
      <RoutingPanel locked={locked} />
      {joints.length === 0 ? (
        <p className="panel-empty">No joints yet. Add one per joint, or press full hand in the Tendons step.</p>
      ) : (
        groupsOf(joints).map(({ group, joints: members }) => (
          <details key={group || '\u0000'} className="finger-finger" open>
            <summary>
              {group || 'ungrouped'}
              <small>
                {members.filter((j) => okNames.has(j.name)).length}/{members.length} solvable
              </small>
            </summary>
            {members.map((joint) => (
              <JointFormula key={joint.name} joint={joint} index={joints.indexOf(joint)} locked={locked} />
            ))}
          </details>
        ))
      )}
    </section>
  )
}
