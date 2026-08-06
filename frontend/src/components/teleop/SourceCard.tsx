// Teleop source picker + per-source config. Sources render as selectable
// tiles; cameras are auto-detected through the streamer child (which also
// gets host camera names, so the built-in webcam wins over an iPhone
// Continuity Camera) with the most likely one pre-selected.

import { useEffect, useRef, useState } from 'react'
import { api } from '../../api/rest'
import type { TeleopSourceId } from '../../api/types'
import { useAppStore } from '../../state/appStore'
import { isTeleopActive, useTeleopStore } from '../../state/teleopStore'

const SOURCE_TILES: { id: TeleopSourceId; label: string; hint: string }[] = [
  {
    id: 'mediapipe',
    label: 'Webcam',
    hint: 'MediaPipe hand tracking — just a camera',
  },
  {
    id: 'avp',
    label: 'Vision Pro',
    hint: 'Tracking Streamer visionOS app over WiFi',
  },
  {
    id: 'manus',
    label: 'Manus gloves',
    hint: 'SDK publisher on a Linux box (see docs)',
  },
  {
    id: 'synthetic',
    label: 'Synthetic',
    hint: 'waveform generator — no hardware, dev/demo',
  },
]

export function SourceCard() {
  const sources = useTeleopStore((s) => s.sources)
  const setSources = useTeleopStore((s) => s.setSources)
  const draft = useTeleopStore((s) => s.draft)
  const setDraft = useTeleopStore((s) => s.setDraft)
  const session = useTeleopStore((s) => s.session)
  const wsConnected = useAppStore((s) => s.wsConnected)
  const [scanning, setScanning] = useState(false)
  const [scanError, setScanError] = useState<string | null>(null)
  const autoScanned = useRef(false)

  const active = isTeleopActive(session)
  const cameras = sources?.cameras ?? null

  const applyScan = (
    scanned: { index: number }[],
    defaultIndex: number | null,
  ) => {
    // Auto-select the most likely camera unless the user picked one that
    // still exists.
    const draftNow = useTeleopStore.getState().draft
    const stillValid =
      draftNow.camera_manual &&
      scanned.some((c) => c.index === draftNow.camera_index)
    if (!stillValid && defaultIndex !== null) {
      setDraft({ camera_index: defaultIndex, camera_manual: false })
    }
  }

  const scan = async () => {
    setScanning(true)
    setScanError(null)
    try {
      const result = await api.teleopScanCameras()
      const info = await api.teleopSources()
      setSources(info)
      applyScan(result.cameras, result.default_camera_index)
    } catch (error) {
      setScanError(String((error as Error).message ?? error))
    } finally {
      setScanning(false)
    }
  }

  useEffect(() => {
    if (!wsConnected) return
    api
      .teleopSources()
      .then((info) => {
        setSources(info)
        // First visit: probe cameras once so the dropdown is ready.
        if (
          info.cameras === null &&
          info.runner.available &&
          !autoScanned.current &&
          !isTeleopActive(useTeleopStore.getState().session)
        ) {
          autoScanned.current = true
          void scan()
        } else if (info.cameras !== null) {
          applyScan(info.cameras, info.default_camera_index)
        }
      })
      .catch(() => setSources(null))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wsConnected])

  const runnerMissing = sources !== null && !sources.runner.available

  const onGateToggle = (enabled: boolean) => {
    setDraft({ orientation_gate: enabled })
    if (active) {
      void api
        .teleopConfig({ orientation_gate: enabled })
        .catch(() => undefined)
    }
  }

  return (
    <div className="setup-card">
      <div className="setup-card-title">Source</div>
      <div className="teleop-source-grid">
        {SOURCE_TILES.map(({ id, label, hint }) => {
          const availability = sources?.sources[id]
          const unavailable = availability ? !availability.installed : false
          const selected = draft.source === id
          return (
            <button
              key={id}
              className={`teleop-source-tile${selected ? ' selected' : ''}`}
              disabled={active || unavailable}
              title={availability?.detail ?? hint}
              onClick={() => setDraft({ source: id })}
            >
              <span className="teleop-source-name">
                {label}
                <span
                  className={`teleop-source-dot${
                    availability?.ready ? ' ready' : ''
                  }`}
                />
              </span>
              <span className="teleop-source-desc">
                {availability?.detail ?? hint}
              </span>
            </button>
          )
        })}
      </div>
      {runnerMissing && (
        <div className="setup-card-reason">
          no orca_teleop checkout — see the card above to install one. Managed
          start is unavailable until then; external mode still works.
        </div>
      )}

      {draft.source === 'mediapipe' && (
        <>
          <div className="setup-card-row" style={{ width: '100%' }}>
            <label className="toggle-label" style={{ gap: 6, flex: 1 }}>
              camera
              {cameras && cameras.length > 0 ? (
                <select
                  value={draft.camera_index}
                  disabled={active}
                  style={{ flex: 1, minWidth: 0 }}
                  onChange={(e) =>
                    setDraft({
                      camera_index: parseInt(e.target.value, 10),
                      camera_manual: true,
                    })
                  }
                >
                  {cameras.map((camera) => (
                    <option key={camera.index} value={camera.index}>
                      {camera.name ?? `camera ${camera.index}`}
                      {camera.width ? ` (${camera.width}×${camera.height})` : ''}
                      {camera.index === sources?.default_camera_index
                        ? ' ★'
                        : ''}
                      {camera.available === false
                        ? ' — not reachable (wake it near your Mac?)'
                        : ''}
                    </option>
                  ))}
                </select>
              ) : (
                <input
                  type="number"
                  min={0}
                  max={9}
                  value={draft.camera_index}
                  disabled={active}
                  style={{ width: 48 }}
                  title="no cameras detected yet — scan, or type an index"
                  onChange={(e) =>
                    setDraft({
                      camera_index: parseInt(e.target.value || '0', 10),
                      camera_manual: true,
                    })
                  }
                />
              )}
              <button
                className="btn btn-scan"
                disabled={scanning || active}
                title={
                  active
                    ? 'stop the session to scan cameras'
                    : 'probe cameras (auto-picks the built-in one over ' +
                      'iPhone/Continuity cameras)'
                }
                onClick={() => void scan()}
              >
                {scanning ? 'scanning…' : '↻ scan'}
              </button>
            </label>
          </div>
          {scanError && <div className="setup-card-reason">{scanError}</div>}
          <label
            className="toggle-label"
            title="only track when the palm faces the camera in a plausible
              teleop pose — turn off if tracking keeps dropping"
          >
            <input
              type="checkbox"
              checked={draft.orientation_gate}
              onChange={(e) => onGateToggle(e.target.checked)}
            />
            orientation gate
          </label>
        </>
      )}
      {draft.source === 'manus' && (
        <div className="setup-card-row">
          <label className="toggle-label" style={{ gap: 6 }}>
            ZMQ address
            <input
              type="text"
              value={draft.zmq_addr}
              disabled={active}
              style={{ width: 170 }}
              onChange={(e) => setDraft({ zmq_addr: e.target.value })}
            />
          </label>
        </div>
      )}
      {draft.source === 'avp' && (
        <div className="setup-card-row">
          <label className="toggle-label" style={{ gap: 6 }}>
            Vision Pro IP
            <input
              type="text"
              placeholder="10.0.0.x"
              value={draft.avp_ip}
              disabled={active}
              style={{ width: 120 }}
              onChange={(e) => setDraft({ avp_ip: e.target.value })}
            />
          </label>
        </div>
      )}

      {draft.source !== 'synthetic' && (
        <div className="setup-card-row">
          <label className="toggle-label" style={{ gap: 6 }}>
            retargeter
            <select
              value={draft.retargeter}
              disabled={active}
              title="rmsprop: fast (~12 ms/frame on CPU). adaptive: higher
                quality but ~100 ms/frame without a GPU"
              onChange={(e) =>
                setDraft({
                  retargeter: e.target.value as typeof draft.retargeter,
                })
              }
            >
              <option value="rmsprop">rmsprop (fast)</option>
              <option value="adaptive_analytical">adaptive (quality)</option>
            </select>
          </label>
        </div>
      )}

      <div className="setup-card-row">
        <label
          className="toggle-label"
          title="don't spawn the streamer — start it yourself (e.g. on another
            machine) with the token shown after start"
        >
          <input
            type="checkbox"
            checked={draft.external}
            disabled={active}
            onChange={(e) => setDraft({ external: e.target.checked })}
          />
          external streamer
        </label>
      </div>
    </div>
  )
}
