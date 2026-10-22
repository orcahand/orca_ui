// Which hand this console is looking at, as a menu next to the board picker.
//
// A hand's calibration is filed under the hand, so the console has to know
// which one is in front of it. A board names itself — the serial it was
// provisioned with, else its board id — and auto takes that. A hand with no
// board cannot name itself, and nothing can tell one board-less hand from
// another, so the name is the operator's to give: auto then falls back to the
// first name this machine knows, and the rest are here to pick from.
//
// Adding is how a second board-less hand gets told apart from the first.
// Deleting throws away the calibration filed under that name, so it asks
// first. Neither is remembered between launches yet: auto resolves again next
// time.

import { useEffect, useState } from 'react'
import { api, ApiError } from '../../api/rest'
import type { HandIdsInfo } from '../../api/types'
import { useAppStore } from '../../state/appStore'

const AUTO = ' auto' // leading space: never a valid hand id, so no collision
const ADD = ' add'
const DELETE = ' delete'

export function HandPicker() {
  const setError = useAppStore((s) => s.setError)
  const handState = useAppStore((s) => s.status?.state ?? null)
  const [info, setInfo] = useState<HandIdsInfo | null>(null)
  const [busy, setBusy] = useState(false)

  // Refetched when the connection changes: a hand that just came up may have
  // named itself, which moves what auto means.
  useEffect(() => {
    api.hands().then(setInfo).catch(() => undefined)
  }, [handState])

  // A core too old to keep hands by name offers none: show nothing.
  if (!info || !info.available) return null

  const selected = info.selected
  const resolved = selected ?? info.auto

  function fail(what: string, e: unknown) {
    setError(e instanceof ApiError ? `${what}: ${e.message}` : `${what}.`)
  }

  async function run(what: string, action: () => Promise<HandIdsInfo>) {
    setBusy(true)
    try {
      setInfo(await action())
      setError(null)
    } catch (e) {
      fail(what, e)
    } finally {
      setBusy(false)
    }
  }

  async function choose(value: string) {
    if (value === ADD) {
      const name = window.prompt(
        'Name for this hand (1-20 of letters, digits, dot, dash, underscore):',
      )
      if (name) await run('Could not add that hand', () => api.addHand(name.trim()))
      return
    }
    if (value === DELETE) {
      const name = resolved
      if (!name) return
      // Confirmed before, not after: this throws away a calibration, and only
      // calibrating that hand again can replace it.
      const sure = window.confirm(
        `Forget "${name}" and the calibration filed under it?\n\n` +
          'This cannot be undone — only calibrating that hand again replaces it.',
      )
      if (sure) await run('Could not delete that hand', () => api.deleteHand(name))
      return
    }
    await run('Could not change hand', () =>
      api.selectHand(value === AUTO ? null : value),
    )
  }

  const title =
    selected == null
      ? info.from_board
        ? `Hand: auto — ${info.from_board}, which the board reports. Calibration is filed under it.`
        : info.auto
          ? `Hand: auto — ${info.auto}, the first name this machine knows. No board to ask, so pick the right one if this is not it.`
          : 'Hand: auto — nothing to go on yet. Add a name for this hand to file its calibration under.'
      : `Filed under ${selected}. "auto" hands the choice back to the hardware.`

  return (
    <span className="model-picker hand-picker">
      <select
        className="model-select"
        value={selected == null ? AUTO : selected}
        disabled={busy}
        onFocus={() => void api.hands().then(setInfo).catch(() => undefined)}
        onChange={(event) => void choose(event.target.value)}
        title={title}
        aria-label="Hand"
      >
        <option value={AUTO}>
          {info.auto ? `hand: auto (${info.auto})` : 'hand: auto'}
        </option>
        {info.known.map((name) => (
          <option key={name} value={name}>
            {name}
            {name === info.from_board ? ' — from the board' : ''}
          </option>
        ))}
        <option value={ADD}>add a hand…</option>
        {resolved && <option value={DELETE}>forget {resolved}…</option>}
      </select>
    </span>
  )
}
