// The hand's hardware revision: a header menu, and a setup prompt for hands
// that cannot report it. The board reports its version and that is what runs.
// A version picked here applies to the connected hand for this session only:
// nothing is saved, and connecting another hand drops it. Only v2.1 gets
// guided tensioning and travel-checked calibration (and, on a left hand, the
// reversed thumb MCP/DIP motors).

import { useState } from 'react'
import { api, ApiError } from '../../api/rest'
import { useAppStore } from '../../state/appStore'
import { isOperationActive, useOperationStore } from '../../state/operationStore'
import { formatHardwareVersion, V20, V21, V211 } from '../../state/tensionFlow'

const BOARD = 'board'
const VERSIONS = [V20, V21, V211]

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
  const side = useAppStore((s) => s.handInfo?.side)
  const busy = useOperationStore((s) => isOperationActive(s.operation))
  const [saving, setSaving] = useState(false)
  if (!status || status.bare) return null

  const override = status.hardware_version_override ?? null
  const board = status.board_hardware_version ?? null
  const choose = async (version: number | null) => {
    setSaving(true)
    await save(version)
    setSaving(false)
  }
  const note = (version: number) =>
    version === V20
      ? 'hold-and-ratchet tensioning, one plain calibration pass'
      : `guided tensioning, travel-checked calibration${side === 'left' ? ', thumb MCP/DIP motors reversed' : ''}${version === V211 ? ', its own wrist range' : ''}`

  return (
    <span className="model-picker">
      <select
        className="model-select"
        value={override ?? BOARD}
        disabled={saving || busy}
        onChange={(event) =>
          void choose(event.target.value === BOARD ? null : Number(event.target.value))
        }
        title={
          busy
            ? 'An operation is running — stop it first.'
            : 'Hardware version. A version picked here runs the connected hand for this session only; nothing is saved.'
        }
        aria-label="Hardware version"
      >
        <option value={BOARD}>
          {board != null ? `hw ${formatHardwareVersion(board)} · board` : 'hw ? · no board'}
        </option>
        {VERSIONS.map((version) => (
          <option key={version} value={version} title={note(version)}>
            {version === override
              ? `hw ${formatHardwareVersion(version)}, set by you`
              : `hw ${formatHardwareVersion(version)}`}
          </option>
        ))}
      </select>
      {override != null && (
        <span
          className="model-pin pinned"
          title="Picked in this console for this session; connecting another hand drops it."
        >
          {board != null ? `board says ${formatHardwareVersion(board)}` : 'no board'}
        </span>
      )}
      {override != null && board != null && (
        <button
          className="model-pin hv-use-board"
          disabled={saving || busy}
          onClick={() => void choose(null)}
        >
          use board's
        </button>
      )}
    </span>
  )
}

// Setup prompt for a hand nothing has told the console the version of: no
// board to report it and none picked this session.
export function HardwareVersionPrompt() {
  const status = useAppStore((s) => s.status)
  const [saving, setSaving] = useState(false)
  if (
    !status ||
    status.bare ||
    status.hardware_version_override != null ||
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
        tensioning and calibration steps, and holds until the console closes or another hand
        connects.
      </span>
      {VERSIONS.map((version) => (
        <button
          key={version}
          className="btn btn-secondary btn-sm"
          disabled={saving}
          onClick={() => void pick(version)}
        >
          {formatHardwareVersion(version)}
        </button>
      ))}
    </div>
  )
}
