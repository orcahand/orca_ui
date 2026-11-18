// Step 2 — coupling: which tendons move each joint, and by how much. Every
// joint is one editable formula line, q = gain · θ(tendon) + gain · θ(tendon)
// + …, grouped by finger. The routing panel at the top holds the one rule a
// hand's fingers share — MCP and PIP as a sum and a difference of tendons U
// and C, U being tendon 2 or 1 as set — with its radii, and writes the gains
// it produces into every finger; the lines stay editable afterwards. Under
// each finger a check card tests the coupling on the hand.

import { useMemo } from 'react'
import { CouplingCheck } from './CouplingCheck'
import { useFingerStore, gainPresets, groupsOf, resolve, tendonsFor, type FingerJoint } from './fingerStore'
import { couplingProblem, couplingsOf } from './coupling'

// A term's gain, picked from the routing's ratios and plain numbers; one
// that matches none is listed as it stands.
function GainPick({ gain, disabled, onPick }: { gain: number; disabled: boolean; onPick(value: number): void }) {
  const settings = useFingerStore((s) => s.settings)
  const presets = gainPresets(settings)
  const size = Math.abs(gain)
  const at = presets.findIndex((p) => Math.abs(p.value - size) < 1e-4)
  return (
    <select
      value={at < 0 ? 'custom' : String(at)}
      disabled={disabled}
      title="gain: joint degrees per shaft degree of this tendon"
      onChange={(e) => e.target.value !== 'custom' && onPick(presets[Number(e.target.value)].value)}
    >
      {presets.map((p, i) => (
        <option key={p.label} value={i}>
          {p.value.toFixed(3)} {p.label.startsWith('r_') ? `(${p.label})` : ''}
        </option>
      ))}
      {at < 0 && <option value="custom">{size.toFixed(3)}</option>}
    </select>
  )
}

function JointFormula({ joint, index, locked: panelLocked }: { joint: FingerJoint; index: number; locked: boolean }) {
  const confirmed = joint.confirmed ?? false
  const locked = panelLocked || confirmed
  const patchJoint = useFingerStore((s) => s.patchJoint)
  const removeJoint = useFingerStore((s) => s.removeJoint)
  const moveJoint = useFingerStore((s) => s.moveJoint)
  const swapTerms = useFingerStore((s) => s.swapTerms)
  const setConfirmed = useFingerStore((s) => s.setConfirmed)
  const tendons = useFingerStore((s) => s.tendons)
  // Abduction is one tendon on one motor, never a combination: just the tendon and its sign.
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
        ? [{ tendon: patch.tendon ?? joint.terms[0]?.tendon, gain: Math.sign(patch.gain ?? joint.terms[0]?.gain ?? 1) || 1 }]
        : joint.terms.map((t, k) => (k === i ? { ...t, ...patch } : t)),
    })
  const addTerm = () => {
    const used = new Set(joint.terms.map((t) => t.tendon))
    const free = offered.find((t) => !used.has(t.name))
    if (free) patchJoint(index, { terms: [...joint.terms, { tendon: free.name, gain: 1 }] })
  }
  const removeTerm = (i: number) => patchJoint(index, { terms: joint.terms.filter((_, k) => k !== i) })

  return (
    <div className={`finger-row finger-formula-row ${problem ? 'incomplete' : ''} ${confirmed ? 'confirmed' : ''}`}>
      <div className="finger-row-main">
        <label
          className="finger-confirm"
          title={
            confirmed
              ? 'confirmed: the equation is locked — untick to change it'
              : 'confirm this equation once it checks out on the hand: locks it'
          }
        >
          <input
            type="checkbox"
            checked={confirmed}
            disabled={panelLocked || joint.terms.length === 0}
            onChange={(e) => setConfirmed(index, e.target.checked)}
          />
          ✓
        </label>
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
            <button
              className={`btn btn-secondary finger-sign ${term.gain < 0 ? 'neg' : ''}`}
              disabled={locked}
              title="sign of this term: + or −"
              onClick={() => setTerm(i, { gain: -term.gain })}
            >
              {term.gain < 0 ? '−' : '+'}
            </button>
            {!single && (
              <GainPick gain={term.gain} disabled={locked} onPick={(v) => setTerm(i, { gain: Math.sign(term.gain || 1) * v })} />
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
        {!single && joint.terms.length === 2 && (
          <button
            className="btn btn-secondary"
            disabled={locked}
            title="exchange the two tendons of this equation only (the gains and signs stay in place)"
            onClick={() => swapTerms(index)}
          >
            ⇄
          </button>
        )}
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
          {confirmed
            ? 'confirmed'
            : problem
              ? problem
              : single
                ? 'abduction: its own motor'
                : partners.length
                  ? `coupled with ${partners.join(', ')}`
                  : 'independent'}
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
          <button className="btn btn-secondary" disabled={panelLocked || index === 0} title="move up" onClick={() => moveJoint(index, -1)}>
            ↑
          </button>
          <button className="btn btn-secondary" disabled={panelLocked || index === count - 1} title="move down" onClick={() => moveJoint(index, 1)}>
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
  const u = settings.uTendon ?? 2
  const c = 3 - u
  const pairs = groupsOf(joints).filter(
    ({ joints: m }) =>
      m.some((j) => /_mcp$/i.test(j.name) && !j.confirmed) || m.some((j) => /_pip$/i.test(j.name) && !j.confirmed),
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
      <div className="finger-u-switch" role="radiogroup" aria-label="which flexion tendon is U">
        <span>U is tendon</span>
        {([2, 1] as const).map((n) => (
          <button
            key={n}
            role="radio"
            aria-checked={u === n}
            className={`btn ${u === n ? 'btn-primary' : 'btn-secondary'}`}
            disabled={locked}
            title={`U = <finger>_${n}, C = <finger>_${3 - n}; press apply to rewrite the fingers`}
            onClick={() => patchSettings({ uTendon: n })}
          >
            {n}
          </button>
        ))}
        <span>C is tendon {c}</span>
      </div>
      <ul className="finger-formula" aria-label="coupling of MCP and PIP in every finger">
        <li>
          q<sub>MCP</sub> = r<sub>s</sub>(θ<sub>{u}</sub> + θ<sub>{c}</sub>) / {settings.mcpRadiusMm}
          <small>= {(settings.spoolRadiusMm / settings.mcpRadiusMm).toFixed(3)} · (θ<sub>{u}</sub> + θ<sub>{c}</sub>)</small>
        </li>
        <li>
          q<sub>PIP</sub> = r<sub>s</sub>(θ<sub>{u}</sub> − θ<sub>{c}</sub>) / {settings.pipRadiusMm}
          <small>= {(settings.spoolRadiusMm / settings.pipRadiusMm).toFixed(3)} · (θ<sub>{u}</sub> − θ<sub>{c}</sub>)</small>
        </li>
      </ul>
      <div className="bench-fields">
        {field('spoolRadiusMm', <>r<sub>s</sub></>, 'spool radius on the motor')}
        {field('mcpRadiusMm', <>r<sub>MCP</sub></>, 'effective radius at the MCP joint')}
        {field('pipRadiusMm', <>r<sub>PIP</sub></>, 'effective radius at the PIP joint')}
        <button
          className="btn btn-primary"
          disabled={locked || pairs === 0}
          title={`write these gains into the MCP and PIP lines of every finger, with <finger>_${u} as U and <finger>_${c} as C; confirmed lines are kept`}
          onClick={coupleFingers}
        >
          apply to {pairs} finger{pairs === 1 ? '' : 's'}
        </button>
        <small className="finger-hint">tendon 1 is the flexion tendon nearer the thumb, 2 the other; abduction is one tendon on its own motor. Each line below is its own: change it with its sign, gain and tendon pickers, check the finger on the hand in its card, then tick ✓ to lock the line. A tendon wound the other way round its spool is just a − on its terms</small>
      </div>
    </div>
  )
}

export function FingerCoupling({ connected, locked }: { connected: boolean; locked: boolean }) {
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
                {` · ${members.filter((j) => j.confirmed).length}/${members.length} confirmed`}
              </small>
            </summary>
            {members.map((joint) => (
              <JointFormula key={joint.name} joint={joint} index={joints.indexOf(joint)} locked={locked} />
            ))}
            <CouplingCheck group={group} connected={connected} locked={locked} />
          </details>
        ))
      )}
    </section>
  )
}
