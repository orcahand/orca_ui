// The cycle definition's inputs: speed, hold, count or nonstop, glide or
// step, start end. One component for a motor card and for the defaults row,
// so the two never drift apart.

import type { CycleSettings } from './benchStore'

export function CycleFields({
  value,
  onChange,
  disabled,
  name,
}: {
  value: CycleSettings
  onChange: (patch: Partial<CycleSettings>) => void
  disabled?: boolean
  // Radio groups need a per-instance name or every card shares one.
  name: string
}) {
  const number = (
    key: 'speedDegS' | 'holdS' | 'cycles',
    text: string,
    min: number,
    integer = false,
  ) => {
    const parsed = integer ? parseInt(text, 10) : parseFloat(text)
    if (Number.isFinite(parsed) && parsed >= min) onChange({ [key]: parsed })
  }

  return (
    <div className="bench-fields">
      <label className="stress-field" title="shaft speed each leg glides at">
        speed
        <input
          type="number"
          min={1}
          max={2000}
          step={10}
          value={value.speedDegS}
          disabled={disabled}
          onChange={(e) => number('speedDegS', e.target.value, 1)}
        />
        °/s
      </label>
      <label className="stress-field" title="dwell at each end after arriving">
        hold
        <input
          type="number"
          min={0}
          max={60}
          step={0.1}
          value={value.holdS}
          disabled={disabled}
          onChange={(e) => number('holdS', e.target.value, 0)}
        />
        s
      </label>
      <label className="stress-field">
        cycles
        <input
          type="number"
          min={1}
          step={10}
          value={value.cycles}
          disabled={disabled || value.loop}
          onChange={(e) => number('cycles', e.target.value, 1, true)}
        />
      </label>
      <label className="stress-field bench-check" title="run until stopped">
        <input
          type="checkbox"
          checked={value.loop}
          disabled={disabled}
          onChange={(e) => onChange({ loop: e.target.checked })}
        />
        ∞
      </label>
      <span className="toolbar bench-mode">
        <label className="toggle-label" title="stream positions at 50 Hz, like the hand's loop">
          <input
            type="radio"
            name={`${name}-mode`}
            checked={value.mode === 'glide'}
            disabled={disabled}
            onChange={() => onChange({ mode: 'glide' })}
          />
          glide
        </label>
        <label
          className="toggle-label"
          title="one command per leg — the motor runs the range at its own speed"
        >
          <input
            type="radio"
            name={`${name}-mode`}
            checked={value.mode === 'step'}
            disabled={disabled}
            onChange={() => onChange({ mode: 'step' })}
          />
          step
        </label>
      </span>
      <label className="stress-field bench-check" title="begin each cycle at B instead of A">
        <input
          type="checkbox"
          checked={value.startAt === 'b'}
          disabled={disabled}
          onChange={(e) => onChange({ startAt: e.target.checked ? 'b' : 'a' })}
        />
        start at B
      </label>
    </div>
  )
}
