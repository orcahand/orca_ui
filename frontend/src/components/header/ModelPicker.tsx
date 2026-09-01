// Which hand config the console is running, as a menu rather than a label.
//
// Normally this is a readout: the backend reads the model off the controller
// board on every detection pass, and the picker just shows what it concluded.
// The hands that need the menu are the ones it cannot ask — a legacy build,
// or any hand on electronics that never answers the board's identity query.
// Those all resolve to the default model whatever they are, so a left hand
// drives mirrored and a touch hand shows no taxels until someone says what
// it is.
//
// Picking a model *pins* it, exactly as `--model` does: detection stops
// revising the answer, because a guess must not overwrite the operator who
// knows better. The first entry hands the choice back.

import { useEffect, useState } from 'react'
import { api, ApiError } from '../../api/rest'
import type { ModelEntry, ModelsInfo } from '../../api/types'
import { useAppStore } from '../../state/appStore'

const AUTO = ' auto' // not a model name, so it can never collide with one

function capabilityLabel(model: ModelEntry): string {
  if (model.tactile && model.encoders) return 'touch + joints'
  if (model.tactile) return 'touch'
  if (model.encoders) return 'joints'
  return 'motors only'
}

function optionLabel(model: ModelEntry): string {
  // The version only earns its space when it is not the current generation.
  const version =
    model.version && model.version !== 'v2' ? ` (${model.version})` : ''
  return `${model.name}${version} — ${capabilityLabel(model)}`
}

export function ModelPicker() {
  const status = useAppStore((s) => s.status)
  const handInfo = useAppStore((s) => s.handInfo)
  const setError = useAppStore((s) => s.setError)
  const [info, setInfo] = useState<ModelsInfo | null>(null)
  const [busy, setBusy] = useState(false)

  // The catalogue is fixed for the process; which model is *selected* streams
  // in on the status topic, so this is fetched once rather than polled.
  useEffect(() => {
    api.models().then(setInfo).catch(() => undefined)
  }, [])

  // Prefer the streamed model over the fetched one: a hand plugged in later
  // moves it with nothing refetching here.
  const selected = status?.model || info?.selected || ''
  const pinned = status?.model_pinned ?? info?.pinned ?? true
  const mock = handInfo?.mock ?? false

  if (!info) {
    // Pre-fetch, and the fallback if /api/models ever fails: the plain badge,
    // so the header never loses the model it is running.
    return selected ? <span className="capability-badge">{selected}</span> : null
  }

  const known = info.models.some((model) => model.name === selected)

  async function choose(value: string) {
    setBusy(true)
    try {
      const next = await api.selectModel(value === AUTO ? null : value)
      setInfo(next)
      setError(null)
    } catch (e) {
      setError(
        e instanceof ApiError
          ? `Could not change model: ${e.message}`
          : 'Could not change model.',
      )
    } finally {
      setBusy(false)
    }
  }

  const sides = ['right', 'left'] as const
  return (
    <span className="model-picker">
      <select
        className="model-select"
        value={known ? selected : ''}
        disabled={busy}
        onChange={(event) => void choose(event.target.value)}
        title={
          pinned
            ? `Running ${selected}. Pinned — hardware detection will not change it.`
            : `Running ${selected}, re-read from the hardware on every detection pass.`
        }
        aria-label="Hand model"
      >
        {/* A --config path has no model name to be selected back by. It still
            has to appear, or the picker would name the wrong hand. */}
        {!known && <option value="">{selected}</option>}
        {info.auto_available && (
          <option value={AUTO}>auto-detect from hardware</option>
        )}
        {sides.map((side) => {
          const models = info.models.filter((model) => model.side === side)
          if (models.length === 0) return null
          return (
            <optgroup key={side} label={side === 'right' ? 'Right' : 'Left'}>
              {models.map((model) => (
                <option
                  key={model.name}
                  value={model.name}
                  disabled={!model.selectable}
                >
                  {optionLabel(model)}
                </option>
              ))}
            </optgroup>
          )
        })}
      </select>
      <span
        className={`model-pin${pinned ? ' pinned' : ''}`}
        title={
          mock
            ? 'Simulated hand — no hardware.'
            : pinned
              ? 'This model was chosen by hand; detection will not override it.'
              : 'Model is re-read from the hardware on every detection pass.'
        }
      >
        {mock ? 'MOCK' : pinned ? 'PINNED' : 'AUTO'}
      </span>
    </span>
  )
}
