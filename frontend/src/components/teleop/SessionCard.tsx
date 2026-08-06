// Teleop session lifecycle + live status. Start (preview) → Engage →
// Disengage → Stop; the wrist slider is retargeter CONFIG (the camera can't
// see your wrist), never a joint command — it bypasses commandBus entirely.

import { useRef } from 'react'
import { api } from '../../api/rest'
import type { TeleopSnapshot } from '../../api/types'
import { useAppStore } from '../../state/appStore'
import {
  isTeleopActive,
  useEngageGate,
  useTeleopStore,
} from '../../state/teleopStore'

function fail(error: unknown) {
  useAppStore.getState().setError(String((error as Error).message ?? error))
}

const STATE_BADGE: Record<string, string> = {
  starting: 'starting',
  preview: 'preview',
  engaged: 'engaged',
  error: 'error',
}

export function TeleopStateBadge({ session }: { session: TeleopSnapshot }) {
  const label =
    session.state === 'engaged' && session.ramping
      ? 'engaging'
      : (STATE_BADGE[session.state] ?? session.state)
  return (
    <span className={`teleop-state-badge ${session.state}`}>{label}</span>
  )
}

export function TrackingDot({ session }: { session: TeleopSnapshot }) {
  const lost = session.tracking === 'lost'
  return (
    <span
      className={`tracking-dot${lost ? ' lost' : ''}`}
      title={lost ? 'tracking lost — holding last pose' : 'tracking ok'}
    />
  )
}

export function SessionCard() {
  const session = useTeleopStore((s) => s.session)
  const draft = useTeleopStore((s) => s.draft)
  const setDraft = useTeleopStore((s) => s.setDraft)
  const externalToken = useTeleopStore((s) => s.externalToken)
  const setExternalToken = useTeleopStore((s) => s.setExternalToken)
  const sources = useTeleopStore((s) => s.sources)
  const handInfo = useAppStore((s) => s.handInfo)
  const wsConnected = useAppStore((s) => s.wsConnected)
  const engageGate = useEngageGate()
  const wristTimer = useRef<number | null>(null)

  const control = useAppStore((s) => s.control)
  const caps = useAppStore((s) => s.status?.capabilities)

  const active = isTeleopActive(session)
  // Only managed mode needs the checkout; external mode is a manually
  // launched streamer, so it must stay startable without one.
  const managedBlocked =
    !draft.external && sources !== null && !sources.runner.available
  const engaged = session?.state === 'engaged'
  // The most common "why won't it engage" — offer the fix inline.
  const torqueMissing =
    session?.state === 'preview' &&
    !!caps?.motors &&
    !control?.torque_enabled &&
    control?.control_source === 'manual'
  const wristRom = handInfo?.joints.find((j) => j.id === 'wrist')?.rom ?? [
    -30, 30,
  ]

  const start = () => {
    const config: Record<string, unknown> = {
      manual_wrist_deg: draft.manual_wrist_deg,
    }
    if (draft.source === 'mediapipe') {
      config.camera_index = draft.camera_index
      config.orientation_gate = draft.orientation_gate
    }
    if (draft.source === 'manus') config.zmq_addr = draft.zmq_addr
    if (draft.source === 'avp') config.avp_ip = draft.avp_ip
    if (draft.source !== 'synthetic') config.retargeter = draft.retargeter
    const mode = draft.external ? 'external' : 'managed'
    // Armed before the call: the preview transition can arrive over the WS
    // before the start request resolves.
    useTeleopStore.getState().setAutoEngagePending(draft.auto_engage)
    api
      .teleopStart(draft.source, mode, config)
      .then((body) => setExternalToken(body.token ?? null))
      .catch((error) => {
        useTeleopStore.getState().setAutoEngagePending(false)
        fail(error)
      })
  }

  const stop = () => {
    setExternalToken(null)
    useTeleopStore.getState().setAutoEngagePending(false)
    void api.teleopStop().catch(fail)
  }

  const onWrist = (deg: number) => {
    setDraft({ manual_wrist_deg: deg })
    if (!active) return // idle: the value ships with the next start
    if (wristTimer.current !== null) window.clearTimeout(wristTimer.current)
    wristTimer.current = window.setTimeout(() => {
      wristTimer.current = null
      void api.teleopConfig({ manual_wrist_deg: deg }).catch(() => undefined)
    }, 200)
  }

  return (
    <div className="setup-card">
      <div className="setup-card-title">Session</div>
      {session && session.state !== 'idle' ? (
        <>
          <div className="setup-card-row">
            <TeleopStateBadge session={session} />
            {session.source && (
              <span className="setup-card-detail">{session.source}</span>
            )}
            {active && <TrackingDot session={session} />}
          </div>
          <div className="teleop-stats">
            <StatRow label="targets" value={hz(session.stats.target_hz)} />
            <StatRow
              label="ingress"
              value={hz(session.stats.ingress_fps ?? null)}
            />
            <StatRow
              label="retarget"
              value={
                session.stats.retarget_ms != null
                  ? `${session.stats.retarget_ms.toFixed(1)} ms`
                  : '--'
              }
            />
          </div>
          {session.notice && (
            <div className="setup-card-reason">⚠ {session.notice}</div>
          )}
          {session.state === 'preview' && (
            <p className="setup-card-hint">
              preview — poses drive the 3D ghost only; ⚡ Engage hands
              control of the real hand to teleop (ramps in gently)
            </p>
          )}
          {session.calibrating && !session.calibrating.done && (
            <div className="setup-card-reason">
              calibrating scale ({session.calibrating.frames}/
              {session.calibrating.needed}) — hold your hand open toward the
              camera
            </div>
          )}
          {session.state === 'error' && (
            <div className="setup-card-reason">{session.error}</div>
          )}
        </>
      ) : (
        <p className="setup-card-hint">
          No session. Start a preview to stream retargeted poses into the 3D
          ghost; engage to drive the hand (ramps in from the current pose).
        </p>
      )}

      {externalToken && (
        <div className="setup-card-detail teleop-token">
          external token: <code>{externalToken}</code>
          <br />
          launch: <code>orca-teleop-streamer --connect ws://{location.host}
          /ws/teleop --token …</code>
        </div>
      )}

      <div className="setup-card-row" style={{ width: '100%' }}>
        <label className="toggle-label" style={{ gap: 6, flex: 1 }}>
          wrist {draft.manual_wrist_deg.toFixed(0)}°
          <input
            type="range"
            min={wristRom[0]}
            max={wristRom[1]}
            step={1}
            value={draft.manual_wrist_deg}
            style={{ flex: 1, accentColor: 'var(--accent)' }}
            title="manual wrist angle — a retargeter parameter, most sources
              can't track your wrist"
            onChange={(e) => onWrist(parseFloat(e.target.value))}
          />
        </label>
      </div>

      <div className="setup-card-row">
        {!active ? (
          <>
            <button
              className="btn btn-primary"
              disabled={!wsConnected || managedBlocked}
              title={
                managedBlocked
                  ? 'no orca_teleop checkout to launch — keep external mode ' +
                    'on and start the streamer yourself, or install the ' +
                    'checkout from the Teleop tab'
                  : undefined
              }
              onClick={start}
            >
              {draft.auto_engage ? '▶ Start teleop' : '▶ Start preview'}
            </button>
            <label
              className="toggle-label"
              title="when the preview comes up, enable torque and engage
                automatically — one click instead of three"
            >
              <input
                type="checkbox"
                checked={draft.auto_engage}
                onChange={(e) => setDraft({ auto_engage: e.target.checked })}
              />
              auto-engage
            </label>
          </>
        ) : (
          <>
            {!engaged ? (
              <>
                {torqueMissing && (
                  <button
                    className="btn btn-info"
                    title="torque is off — enable it so Engage can take over
                      (the hand holds its current pose)"
                    onClick={() => void api.torqueEnable().catch(fail)}
                  >
                    enable torque
                  </button>
                )}
                <button
                  className="btn btn-danger"
                  disabled={!engageGate.allowed}
                  title={engageGate.reason ?? 'take control of the hand'}
                  onClick={() => void api.teleopEngage().catch(fail)}
                >
                  ⚡ Engage
                </button>
              </>
            ) : (
              <button
                className="btn btn-secondary"
                onClick={() => void api.teleopDisengage().catch(fail)}
              >
                Disengage
              </button>
            )}
            <button className="btn btn-secondary" onClick={stop}>
              ■ Stop
            </button>
          </>
        )}
        {session?.state === 'error' && (
          <button className="btn btn-secondary" onClick={stop}>
            clear
          </button>
        )}
      </div>
      {!active && !engageGate.allowed && session?.state === 'preview' && (
        <div className="setup-card-reason">{engageGate.reason}</div>
      )}
      {active && !engaged && !engageGate.allowed && (
        <div className="setup-card-reason">{engageGate.reason}</div>
      )}
    </div>
  )
}

function StatRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="teleop-stat-row">
      <span className="teleop-stat-label">{label}</span>
      <span className="teleop-stat-value">{value}</span>
    </div>
  )
}

function hz(value: number | null): string {
  return value != null ? `${value.toFixed(1)} Hz` : '--'
}
