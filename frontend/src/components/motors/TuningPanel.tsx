// Feedback-loop tuning: Kp / Ki / correction_max / max_current + Apply with
// a status line, plus Rebase — mirrors slider_joint.py's _apply_tuning.

import { useEffect, useState } from 'react'
import { api } from '../../api/rest'
import { useAppStore } from '../../state/appStore'

export function TuningPanel() {
  const control = useAppStore((s) => s.control)
  const [kp, setKp] = useState('')
  const [ki, setKi] = useState('')
  const [corr, setCorr] = useState('')
  const [maxCurrent, setMaxCurrent] = useState('')
  const [statusLine, setStatusLine] = useState('')
  const [seeded, setSeeded] = useState(false)

  useEffect(() => {
    if (!seeded && control) {
      setKp(String(control.gains.kp))
      setKi(String(control.gains.ki))
      setCorr(String(control.gains.correction_max_deg))
      setMaxCurrent(String(control.max_current))
      setSeeded(true)
    }
  }, [control, seeded])

  const apply = async () => {
    const kpValue = parseFloat(kp)
    const kiValue = parseFloat(ki)
    const corrValue = parseFloat(corr)
    const maxCurrentValue = parseInt(maxCurrent, 10)
    if ([kpValue, kiValue, corrValue].some(Number.isNaN) || Number.isNaN(maxCurrentValue)) {
      setStatusLine('parse error: all fields must be numeric')
      return
    }
    try {
      if (control && maxCurrentValue !== control.max_current) {
        await api.setMaxCurrent(maxCurrentValue)
      }
      await api.setGains({
        kp: kpValue,
        ki: kiValue,
        correction_max_deg: corrValue,
      })
      setStatusLine(
        `applied: Kp=${kpValue} Ki=${kiValue} correction_max=${corrValue.toFixed(1)}° max_current=${maxCurrentValue}mA`,
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

  const field = (
    label: string,
    value: string,
    onChange: (v: string) => void,
  ) => (
    <label
      style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 10, color: 'var(--dim)' }}
    >
      {label}
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => e.key === 'Enter' && void apply()}
        style={{
          width: 64,
          background: 'var(--panel-strong)',
          color: 'var(--text)',
          border: '1px solid var(--panel-border-strong)',
          fontFamily: 'var(--font)',
          fontSize: 10,
          padding: '3px 6px',
          outline: 'none',
        }}
      />
    </label>
  )

  return (
    <div
      style={{
        marginTop: 10,
        paddingTop: 10,
        borderTop: '1px solid var(--panel-border)',
        display: 'flex',
        gap: 10,
        alignItems: 'center',
        flexWrap: 'wrap',
      }}
    >
      <span style={{ fontSize: 9, fontWeight: 700, color: 'var(--dimmer)', letterSpacing: 1 }}>
        TUNING
      </span>
      {field('Kp', kp, setKp)}
      {field('Ki', ki, setKi)}
      {field('corr_max °', corr, setCorr)}
      {field('max mA', maxCurrent, setMaxCurrent)}
      <button className="btn btn-primary" onClick={() => void apply()}>
        Apply
      </button>
      <button className="btn btn-secondary" onClick={() => void rebase()}>
        Rebase Loop
      </button>
      <span style={{ fontSize: 9, color: 'var(--dim)' }}>{statusLine}</span>
    </div>
  )
}
