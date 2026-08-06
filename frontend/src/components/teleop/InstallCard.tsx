// Shown at the head of the Teleop tab when no usable orca_teleop checkout is
// present. Managed mode is dead without one; external mode still works, which
// is why this card sits alongside the source picker rather than replacing it.

import { useEffect, useState } from 'react'
import { api } from '../../api/rest'
import type { TeleopInstallTarget } from '../../api/types'
import { useAppStore } from '../../state/appStore'
import { useTeleopStore } from '../../state/teleopStore'

// Why managed teleop can't run, in the user's terms. The backend sends the
// machine-readable reason so this never parses prose.
const REASONS: Record<string, string> = {
  no_checkout: 'No orca_teleop checkout was found.',
  no_pyproject: 'The configured path is not an orca_teleop checkout.',
  no_streamer_entrypoint:
    'The checkout is on a branch that predates the console streamer, so it ' +
    'has no orca-teleop-streamer entry point.',
  no_uv: 'uv is not on PATH — install it from https://docs.astral.sh/uv/ and ' +
    'restart the console.',
}

export function InstallCard() {
  const sources = useTeleopStore((s) => s.sources)
  const install = useTeleopStore((s) => s.install)
  const setInstall = useTeleopStore((s) => s.setInstall)
  const mergeInstallLog = useTeleopStore((s) => s.mergeInstallLog)
  const setError = useAppStore((s) => s.setError)

  const [path, setPath] = useState('')
  const [target, setTarget] = useState<TeleopInstallTarget | null>(null)
  const [confirming, setConfirming] = useState(false)

  // Seed the path input and pick up an install already in flight (a reload
  // mid-build must not show an empty card).
  useEffect(() => {
    api
      .teleopInstallState()
      .then((state) => {
        setInstall(state)
        setPath((current) => current || state.default_path)
        if (state.target && typeof state.target !== 'string') {
          setTarget(state.target)
        }
      })
      .catch(() => undefined)
    api.teleopInstallLog().then(mergeInstallLog).catch(() => undefined)
  }, [setInstall, mergeInstallLog])

  // Re-inspect the destination as the user edits it, so "already a checkout"
  // and "occupied" are known before they commit to a multi-minute build.
  useEffect(() => {
    if (!path) return
    const timer = setTimeout(() => {
      api
        .teleopInstallState(path)
        .then((state) => {
          if (state.target && typeof state.target !== 'string') {
            setTarget(state.target)
          }
        })
        .catch(() => undefined)
    }, 300)
    return () => clearTimeout(timer)
  }, [path])

  const running = install?.running ?? false
  const reason = sources?.runner.reason ?? 'no_checkout'
  const uvMissing = reason === 'no_uv'

  const begin = () => {
    setConfirming(false)
    api
      .teleopInstall(path || undefined)
      .then(setInstall)
      .catch((error) =>
        setError(`install failed: ${String((error as Error).message ?? error)}`),
      )
  }

  const adopting = target?.state === 'existing_checkout'
  const occupied = target?.state === 'occupied'

  return (
    <div className="setup-card">
      <div className="setup-card-title">Teleop unavailable</div>
      <div className="setup-card-hint">
        {REASONS[reason] ?? sources?.runner.detail ?? 'No runner available.'}{' '}
        orca_teleop is a separate repository — its retargeting stack is heavy
        and it needs Python &lt;3.13, so it runs in its own environment rather
        than as a dependency of the console.
      </div>

      {install?.finished && install.ok === false && install.error && (
        <div className="chain-instruction error">{install.error}</div>
      )}
      {install?.finished && install.ok && (
        <div className="chain-instruction done">
          orca_teleop installed — managed sources are available now.
        </div>
      )}

      {!uvMissing && (
        <>
          <div className="setup-card-row">
            <label className="setup-card-detail" htmlFor="teleop-install-path">
              Install to
            </label>
            <input
              id="teleop-install-path"
              className="path-input"
              style={{ flex: 1, minWidth: 260 }}
              value={path}
              disabled={running}
              spellCheck={false}
              onChange={(e) => setPath(e.target.value)}
            />
          </div>
          {target && (
            <div className="setup-card-detail">
              {target.state === 'empty' && `→ ${target.detail}`}
              {adopting && '→ already a checkout here; it will be built, not re-cloned'}
              {occupied && `✗ ${target.detail}`}
            </div>
          )}

          {running ? (
            <div className="setup-card-row">
              <span className="setup-card-detail">
                {install?.phase ?? 'working'}…
              </span>
              <button
                className="btn btn-secondary"
                onClick={() => void api.teleopInstallCancel().catch(() => undefined)}
              >
                Cancel
              </button>
            </div>
          ) : confirming ? (
            <div className="chain-confirm">
              <span className="chain-confirm-text">
                ⚠ This clones {install?.repo ?? 'orca_teleop'} (branch{' '}
                {install?.branch ?? 'main'}) and builds its environment —
                mediapipe, pinocchio and nlopt are large downloads, so expect
                several minutes. You can cancel while it runs.
              </span>
              <button className="btn btn-primary" onClick={begin}>
                Continue
              </button>
              <button
                className="btn btn-secondary"
                onClick={() => setConfirming(false)}
              >
                Cancel
              </button>
            </div>
          ) : (
            <button
              className="btn btn-primary"
              disabled={occupied || !path}
              onClick={() => setConfirming(true)}
            >
              {adopting ? 'Build orca_teleop environment' : 'Install orca_teleop'}
            </button>
          )}
        </>
      )}
    </div>
  )
}
