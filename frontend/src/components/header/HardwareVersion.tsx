// The hand's hardware revision: a header badge that opens a picker, and a
// setup prompt for hands that cannot report it. The board reports its version;
// a hand on a plain Feetech/Dynamixel adapter has no board, so the operator
// sets it here and it is pinned as `hardware_version:` in the hand's
// config.yaml. Only v2.1 gets guided tensioning and travel-checked
// calibration (and, on a left hand, the reversed thumb MCP/DIP motors).

import { useState } from 'react'
import { createPortal } from 'react-dom'
import { api, ApiError } from '../../api/rest'
import { useAppStore } from '../../state/appStore'
import { isOperationActive, useOperationStore } from '../../state/operationStore'
import { formatHardwareVersion, V21 } from '../../state/tensionFlow'

const V20 = 2
type Choice = 'auto' | typeof V20 | typeof V21

async function save(version: number | null): Promise<boolean> {
  try {
    useAppStore.getState().setStatus(await api.setHardwareVersion(version))
    useAppStore.getState().setError(null)
    return true
  } catch (e) {
    useAppStore
      .getState()
      .setError(
        e instanceof ApiError
          ? `Could not set the hardware version: ${e.message}`
          : 'Could not set the hardware version.',
      )
    return false
  }
}

export function HardwareVersionBadge() {
  const status = useAppStore((s) => s.status)
  const [open, setOpen] = useState(false)
  if (!status || status.bare) return null

  const version = status.hardware_version ?? null
  const pinned = status.hardware_version_pinned ?? false
  return (
    <>
      <button
        className="model-picker hw-version"
        onClick={() => setOpen(true)}
        title="Hardware version — click to change"
      >
        <span className="model-select">hw {formatHardwareVersion(version)}</span>
        <span className={`model-pin${pinned ? ' pinned' : ''}`}>
          {pinned ? 'PINNED' : status.board_hardware_version != null ? 'BOARD' : 'UNSET'}
        </span>
      </button>
      {open && <HardwareVersionDialog onClose={() => setOpen(false)} />}
    </>
  )
}

function HardwareVersionDialog({ onClose }: { onClose: () => void }) {
  const status = useAppStore((s) => s.status)
  const side = useAppStore((s) => s.handInfo?.side)
  const busy = useOperationStore((s) => isOperationActive(s.operation))
  const pinned = status?.hardware_version_pinned ?? false
  const current: Choice = pinned ? ((status?.hardware_version as Choice) ?? 'auto') : 'auto'
  const [choice, setChoice] = useState<Choice>(current)
  const [saving, setSaving] = useState(false)
  const board = status?.board_hardware_version ?? null

  const options: { value: Choice; title: string; note: string }[] = [
    {
      value: 'auto',
      title: 'From the board',
      note:
        board != null
          ? `the controller board reports ${formatHardwareVersion(board)}`
          : 'no controller board answers, so the version stays unknown (treated like v2.0)',
    },
    {
      value: V20,
      title: 'v2.0',
      note: 'hold-and-ratchet tensioning, one plain calibration pass',
    },
    {
      value: V21,
      title: 'v2.1',
      note: `guided tensioning, travel-checked calibration${side === 'left' ? ', thumb MCP/DIP motors reversed' : ''}`,
    },
  ]

  const apply = async () => {
    setSaving(true)
    const ok = await save(choice === 'auto' ? null : choice)
    setSaving(false)
    if (ok) onClose()
  }

  return createPortal(
    <div className="gt-overlay" role="dialog" aria-modal="true" aria-label="Hardware version">
      <div className="gt-dialog hv-dialog">
        <header className="gt-header">
          <span className="gt-title">Hardware version</span>
          <span className="gt-header-spacer" />
          <button className="btn btn-secondary" onClick={onClose}>
            Cancel
          </button>
        </header>
        <section className="gt-content">
          <div className="hv-options">
            {options.map((option) => (
              <label key={option.value} className={`hv-option${choice === option.value ? ' active' : ''}`}>
                <input
                  type="radio"
                  name="hardware-version"
                  checked={choice === option.value}
                  onChange={() => setChoice(option.value)}
                />
                <span>
                  <div className="gt-step-title">{option.title}</div>
                  <div className="hv-note">{option.note}</div>
                </span>
              </label>
            ))}
          </div>
          <p className="hv-note">
            Select the hardware version of your hand from this menu. Your selected change will
            write into the hand's local_config.yaml (next to its config.yaml) and overwrite any
            automatic detection.
          </p>
          {busy && <div className="gt-warning">An operation is running — stop it first.</div>}
          <div className="gt-actions">
            <button
              className="btn btn-primary"
              disabled={saving || busy || choice === current}
              onClick={() => void apply()}
            >
              Save
            </button>
          </div>
        </section>
      </div>
    </div>,
    document.body,
  )
}

// Setup prompt for a hand nothing has told the console the version of: no
// board to report it and none pinned. Answering pins it in config.yaml.
export function HardwareVersionPrompt() {
  const status = useAppStore((s) => s.status)
  const [saving, setSaving] = useState(false)
  if (
    !status ||
    status.bare ||
    status.hardware_version_pinned ||
    status.board_hardware_version != null
  ) {
    return null
  }
  const pick = async (version: number) => {
    setSaving(true)
    await save(version)
    setSaving(false)
  }
  return (
    <div className="flow-info hv-prompt">
      <span>
        No controller board reports this hand's hardware version. Which is it? It decides the
        tensioning and calibration steps.
      </span>
      <button className="btn btn-secondary btn-sm" disabled={saving} onClick={() => void pick(V20)}>
        v2.0
      </button>
      <button className="btn btn-secondary btn-sm" disabled={saving} onClick={() => void pick(V21)}>
        v2.1
      </button>
    </div>
  )
}
