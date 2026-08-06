// Takes over the whole Teleop tab when no usable orca_teleop checkout is
// present. Nothing else renders: a source picker and a Start button that can
// only fail read as broken UI, so the tab states the reason once and offers
// the one action that fixes it. External mode is the exception — a streamer
// launched by hand needs no checkout — and hides behind the footer link.

import { useEffect, useState } from 'react'
import { api } from '../../api/rest'
import type { TeleopInstallTarget } from '../../api/types'
import { useAppStore } from '../../state/appStore'
import { useTeleopStore } from '../../state/teleopStore'
import { SOURCE_TILES } from './sources'

// Why managed teleop can't run, in the user's terms. The backend sends the
// machine-readable reason so this never parses prose.
const REASONS: Record<string, string> = {
  no_checkout: 'No orca_teleop checkout was found on this machine.',
  no_pyproject: 'The configured path is not an orca_teleop checkout.',
  no_streamer_entrypoint:
    'The checkout is on a branch that predates the console streamer, so it ' +
    'has no orca-teleop-streamer entry point.',
  no_uv:
    'uv is not on PATH — install it from https://docs.astral.sh/uv/ and ' +
    'restart the console.',
}

export function TeleopUnavailable({ onExternal }: { onExternal: () => void }) {
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
  const adopting = target?.state === 'existing_checkout'
  const occupied = target?.state === 'occupied'

  const begin = () => {
    setConfirming(false)
    api
      .teleopInstall(path || undefined)
      .then(setInstall)
      .catch((error) =>
        setError(`install failed: ${String((error as Error).message ?? error)}`),
      )
  }

  return (
    <div className="teleop-gate">
      <div className="teleop-gate-eyebrow">Teleoperation</div>
      <h2 className="teleop-gate-title">
        {running ? 'Installing orca_teleop…' : 'Teleop is not installed'}
      </h2>
      <p className="teleop-gate-lede">
        {REASONS[reason] ?? sources?.runner.detail ?? 'No runner available.'}{' '}
        orca_teleop is an optional add-on that installs alongside the console.
      </p>

      <div className="teleop-gate-features">
        {SOURCE_TILES.map(({ id, label, hint }) => (
          <div key={id} className="teleop-gate-feature">
            <span className="teleop-gate-feature-name">{label}</span>
            <span className="teleop-gate-feature-desc">{hint}</span>
          </div>
        ))}
      </div>

      {install?.finished && install.ok === false && install.error && (
        <div className="chain-instruction error">{install.error}</div>
      )}
      {install?.finished && install.ok && (
        <div className="chain-instruction done">
          orca_teleop installed — reload if this panel doesn't clear on its own.
        </div>
      )}

      {uvMissing ? (
        <div className="teleop-gate-note">
          Nothing to install from here: uv builds the environment, so it has to
          come first.
        </div>
      ) : (
        <div className="teleop-gate-actions">
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
              {adopting &&
                '→ already a checkout here; it will be built, not re-cloned'}
              {occupied && `✗ ${target.detail}`}
            </div>
          )}

          {running ? (
            <div className="setup-card-row">
              <span className="setup-card-detail">
                {install?.phase ?? 'working'}… this takes several minutes; the
                log below is live.
              </span>
              <button
                className="btn btn-secondary"
                onClick={() =>
                  void api.teleopInstallCancel().catch(() => undefined)
                }
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
              className="btn btn-primary teleop-gate-install"
              disabled={occupied || !path}
              onClick={() => setConfirming(true)}
            >
              {adopting ? 'Build orca_teleop environment' : 'Install orca_teleop'}
            </button>
          )}
        </div>
      )}

      <button
        className="teleop-gate-link"
        onClick={onExternal}
        title="connect a streamer you launch yourself — no checkout needed on
          this machine"
      >
        Already running orca-teleop-streamer elsewhere? Connect it instead →
      </button>
    </div>
  )
}
