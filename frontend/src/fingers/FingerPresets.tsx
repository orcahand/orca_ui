// Named setups. What is on screen autosaves beside the bench config and is
// back on the next start; a preset is a copy under a name, so a hand that
// was set up once can be brought back after another has been on the bench.

import { useState } from 'react'
import { useAppStore } from '../state/appStore'
import { useFingerStore } from './fingerStore'

export function FingerPresets({ locked }: { locked: boolean }) {
  const presets = useFingerStore((s) => s.presets)
  const savePreset = useFingerStore((s) => s.savePreset)
  const loadPreset = useFingerStore((s) => s.loadPreset)
  const deletePreset = useFingerStore((s) => s.deletePreset)
  const setError = useAppStore((s) => s.setError)
  const [chosen, setChosen] = useState('')
  const [busy, setBusy] = useState(false)

  const call = async (action: () => Promise<unknown>) => {
    setBusy(true)
    try {
      await action()
      setError(null)
    } catch (error) {
      setError(String((error as Error).message ?? error))
    } finally {
      setBusy(false)
    }
  }
  const saveAs = () => {
    const name = window.prompt('Save the current setup as…', chosen || 'hand')
    if (!name) return
    void call(async () => {
      await savePreset(name.trim())
      setChosen(name.trim())
    })
  }
  const load = () => {
    if (!chosen) return
    if (!window.confirm(`Replace the current setup with "${chosen}"? The current setup is kept only if you saved it.`)) return
    void call(() => loadPreset(chosen))
  }
  const remove = () => {
    if (!chosen || !window.confirm(`Delete the preset "${chosen}"?`)) return
    void call(async () => {
      await deletePreset(chosen)
      setChosen('')
    })
  }

  return (
    <div className="finger-presets" title="the setup on screen is saved as you edit; presets are named copies">
      <span className="finger-presets-label">setup</span>
      <select value={chosen} disabled={busy} onChange={(e) => setChosen(e.target.value)}>
        <option value="">{presets.length ? 'saved setups…' : 'no saved setups'}</option>
        {presets.map((p) => (
          <option key={p.name} value={p.name}>
            {p.name} · {new Date(p.saved_at * 1000).toLocaleDateString()}
          </option>
        ))}
      </select>
      <button className="btn btn-secondary" disabled={busy || locked || !chosen} onClick={load}>
        load
      </button>
      <button className="btn btn-secondary" disabled={busy} onClick={saveAs}>
        save as…
      </button>
      <button className="btn btn-secondary finger-remove" disabled={busy || !chosen} onClick={remove}>
        delete
      </button>
      <small>autosaved · comes back on restart</small>
    </div>
  )
}
