// Hold / release the motors, and the current ceiling they hold with.
// "Hold" is the tensioning posture: torque on, each motor pinned where it
// is, jog buttons live. "Release" lets the spools be turned by hand — which
// is how a range gets captured.

import { useEffect, useState } from 'react'
import { api } from '../api/rest'
import { useAppStore } from '../state/appStore'
import { useOperationActive } from '../state/operationStore'

export function TorqueBar({ connected }: { connected: boolean }) {
  const control = useAppStore((s) => s.control)
  const torque = useAppStore((s) => s.status?.torque_enabled ?? false)
  const total = useAppStore((s) => s.handInfo?.joints.filter((j) => j.motor_id !== null).length ?? 0)
  const heldCount = control?.held_motors?.length ?? 0
  const partial = torque && total > 0 && heldCount < total
  const motors = useAppStore((s) => s.status?.capabilities?.motors ?? false)
  const setError = useAppStore((s) => s.setError)
  const opActive = useOperationActive()
  const [busy, setBusy] = useState(false)
  const [draft, setDraft] = useState('')

  const maxCurrent = control?.max_current ?? null
  useEffect(() => {
    if (maxCurrent !== null) setDraft(String(maxCurrent))
  }, [maxCurrent])

  const owned = control !== null && control !== undefined && control.control_source !== 'manual'
  const canToggle = connected && motors && !busy && !opActive && !owned

  const toggle = async () => {
    setBusy(true)
    try {
      if (torque) await api.torqueDisable()
      else await api.torqueEnable()
      setError(null)
    } catch (error) {
      setError(String((error as Error).message ?? error))
    } finally {
      setBusy(false)
    }
  }

  const commitCurrent = async () => {
    const value = parseInt(draft, 10)
    if (!Number.isFinite(value) || value === maxCurrent) return
    try {
      await api.setMaxCurrent(value)
      setError(null)
    } catch (error) {
      setError(String((error as Error).message ?? error))
      if (maxCurrent !== null) setDraft(String(maxCurrent))
    }
  }

  return (
    <section className="panel bench-torque">
      <button
        className={`btn-estop bench-hold ${torque ? '' : 'btn-torque-arm'}`}
        disabled={!canToggle}
        title={
          !connected
            ? 'no motor bus'
            : opActive
              ? 'a run is in progress — stop it first'
              : torque
                ? 'release: torque off, spools turn freely'
                : 'hold: torque on, motors pin where they are'
        }
        onClick={() => void toggle()}
      >
        {torque ? '◼ Release all' : '⏻ Hold all'}
      </button>
      <span className={`bench-torque-state ${torque ? 'on' : 'off'}`}>
        {!torque
          ? 'all released — turn a spool by hand, then Set A / Set B; hold one motor to wind against it'
          : partial
            ? `${heldCount} of ${total} held — the rest turn freely`
            : 'all held — jog to tension, Start to cycle'}
      </span>
      <div className="header-spacer" />
      <label className="stress-field" title="current ceiling for every motor (Goal Current)">
        max current
        <input
          type="number"
          min={control?.max_current_floor ?? 0}
          step={10}
          value={draft}
          disabled={!connected || maxCurrent === null}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={() => void commitCurrent()}
          onKeyDown={(e) => {
            if (e.key === 'Enter') (e.target as HTMLInputElement).blur()
          }}
        />
        mA
      </label>
      {control?.direct_motor_mode && (
        <span className="capability-badge" title="raw motor-space writes armed (jogging)">
          DIRECT
        </span>
      )}
    </section>
  )
}
