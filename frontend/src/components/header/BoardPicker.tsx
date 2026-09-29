// Which physical board this console owns, as a menu next to the model picker.
//
// The default — auto — connects to the first board that answers, which is
// right for a bench with one hand. With two hands on one machine (one console
// per hand, e.g. ports 5001 and 5002), first-to-answer is a coin toss: pin a
// board here and this console probes and opens only that board's ports, so
// two dashboards can never trade hands. The pin is deliberately orthogonal to
// the model picker — this says which *hardware* is ours, the model says what
// to run it as.
//
// A board held by another console lists as "in use"; picking it is allowed
// (the pin is a claim that outlives whoever holds it right now).

import { useEffect, useState } from 'react'
import { api, ApiError } from '../../api/rest'
import type { BoardEntry, BoardsInfo } from '../../api/types'
import { useAppStore } from '../../state/appStore'

const AUTO = ' auto' // leading space: never a device path, so no collision

function shortDevice(device: string): string {
  return device.split('/').pop() || device
}

function optionLabel(board: BoardEntry): string {
  const what =
    board.kind === 'motor_adapter'
      ? 'motor adapter'
      : [board.side, board.model_name && `(${board.model_name})`]
          .filter(Boolean)
          .join(' ') || 'unidentified'
  const state = board.held_by_console
    ? ' — this console'
    : board.busy
      ? ' — in use'
      : ''
  return `${shortDevice(board.device)} — ${what}${state}`
}

export function BoardPicker() {
  const status = useAppStore((s) => s.status)
  const setError = useAppStore((s) => s.setError)
  const [info, setInfo] = useState<BoardsInfo | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api.boards().then(setInfo).catch(() => undefined)
  }, [])

  // Prefer the streamed pin over the fetched one, like the model picker: a
  // pin made from another tab moves this select without a refetch.
  const selected = status?.board_pinned ?? info?.selected ?? null

  // Mock mode (or a backend predating /api/boards): nothing to pin.
  if (!info || !info.available) return null

  const known = info.boards.some((board) => board.device === selected)

  async function choose(value: string) {
    setBusy(true)
    try {
      const next = await api.selectBoard(value === AUTO ? null : value)
      setInfo(next)
      setError(null)
    } catch (e) {
      setError(
        e instanceof ApiError
          ? `Could not change board: ${e.message}`
          : 'Could not change board.',
      )
    } finally {
      setBusy(false)
    }
  }

  // The scan is a serial-port probe, so refresh it when the user reaches for
  // the menu rather than on a timer.
  function refresh() {
    api.boards().then(setInfo).catch(() => undefined)
  }

  return (
    <span className="model-picker board-picker">
      <select
        className="model-select"
        value={selected == null ? AUTO : selected}
        disabled={busy}
        onFocus={refresh}
        onChange={(event) => void choose(event.target.value)}
        title={
          selected == null
            ? 'Board: auto — connects to the first board that answers. Pin one when running two consoles on this machine.'
            : `Pinned to ${selected}. This console only ever opens that board's ports; "auto" hands the choice back.`
        }
        aria-label="Controller board"
      >
        <option value={AUTO}>board: auto</option>
        {/* A pinned board that is unplugged right now still has to show. */}
        {selected != null && !known && (
          <option value={selected}>
            {shortDevice(selected)} — unplugged
          </option>
        )}
        {info.boards.map((board) => (
          <option key={board.device} value={board.device}>
            {optionLabel(board)}
          </option>
        ))}
      </select>
    </span>
  )
}
