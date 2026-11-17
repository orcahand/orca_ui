// An app tab's session panel: the launch command, Start / Engage / Stop, and
// what the app reports about itself. The command is asked for on first use
// and stays editable behind "edit".

import { useState, type ReactNode } from 'react'
import { api } from '../../api/rest'
import type { AppEntry, AppId, AppSnapshot } from '../../api/types'
import { useEngageGate } from '../../state/appGate'
import { isAppActive, useAppSessionStore } from '../../state/appSessionStore'
import { useAppStore } from '../../state/appStore'
import { Panel } from '../common/Panel'
import { disengage, enableTorque, engage, fail, stop } from './actions'
import { AppStateBadge, TargetRate, TrackingDot } from './badges'

export function SessionPanel({ app, entry }: { app: AppId; entry: AppEntry | null }) {
  const session = useAppSessionStore((s) => s.session)
  const wsConnected = useAppStore((s) => s.wsConnected)
  const torque = useAppStore((s) => s.control?.torque_enabled ?? false)
  const motors = useAppStore((s) => s.status?.capabilities?.motors ?? false)
  const gate = useEngageGate()
  const [editing, setEditing] = useState(false)

  // The console runs one app at a time; this tab shows only its own session.
  const mine = session?.app === app ? session : null
  const other =
    session && session.app !== app && (isAppActive(session) || session.state === 'stopping')
      ? session
      : null
  const active = isAppActive(mine)
  const command = entry?.command ?? ''
  const title = entry?.title ?? app

  const start = () => void api.appStart(app).catch(fail)

  return (
    <Panel title="Session" toolbar={mine && <AppStateBadge session={mine} />}>
      {(editing || (entry !== null && !command)) && !active ? (
        <CommandEditor
          app={app}
          entry={entry}
          onDone={() => setEditing(false)}
        />
      ) : (
        <div className="setup-card-detail app-command">
          <code>{command || '…'}</code>
          {!active && (
            <button className="link-button" onClick={() => setEditing(true)}>
              edit
            </button>
          )}
        </div>
      )}

      {mine && mine.state !== 'idle' && <SessionDetails session={mine} />}

      <div className="setup-card-row">
        {!active ? (
          <button
            className="btn btn-primary"
            disabled={!wsConnected || !command || other !== null || mine?.state === 'stopping'}
            title={
              other
                ? `${other.title ?? 'another app'} is running — stop it first`
                : !command
                  ? 'set the command first'
                  : `start ${title}; the hand doesn't move until you engage`
            }
            onClick={start}
          >
            ▶ Start
          </button>
        ) : (
          <>
            {mine?.state === 'preview' && motors && !torque && (
              <button
                className="btn btn-info"
                title="the hand holds where it is; Engage then takes over"
                onClick={enableTorque}
              >
                enable torque
              </button>
            )}
            {mine?.state === 'preview' && (
              <button
                className="btn btn-danger"
                disabled={!gate.allowed}
                title={gate.reason ?? 'the hand follows the app, ramping in'}
                onClick={() => mine && engage(mine)}
              >
                ⚡ Engage
              </button>
            )}
            {mine?.state === 'engaged' && (
              <button className="btn btn-secondary" onClick={() => mine && disengage(mine)}>
                Disengage
              </button>
            )}
            <button className="btn btn-secondary" onClick={() => mine && stop(mine)}>
              ■ Stop
            </button>
          </>
        )}
        {mine?.state === 'error' && (
          <button className="btn btn-secondary" onClick={() => mine && stop(mine)}>
            clear
          </button>
        )}
      </div>
      {mine?.state === 'preview' && !gate.allowed && (
        <div className="setup-card-reason">{gate.reason}</div>
      )}
      {mine?.state === 'engaged' && (
        <p className="setup-card-hint">
          Disengage holds the pose. Stop ends the app and turns torque off where
          the hand is.
        </p>
      )}
      {other && (
        <p className="setup-card-hint">
          {other.title ?? 'Another app'} is running. One app drives the hand at
          a time.
        </p>
      )}
    </Panel>
  )
}

function SessionDetails({ session }: { session: AppSnapshot }) {
  const live = session.state === 'preview' || session.state === 'engaged'
  return (
    <>
      {live && (
        <div className="app-stats">
          <Stat label="targets" value={<><TrackingDot session={session} /> <TargetRate session={session} /></>} />
          {Object.entries(session.info).map(([label, text]) => (
            <Stat key={label} label={label} value={text} />
          ))}
        </div>
      )}
      {session.state === 'starting' && (
        <p className="setup-card-hint">
          Waiting for the app to connect. Its first start can take minutes
          while its environment is built; the log below shows progress.
        </p>
      )}
      {session.notice && <div className="setup-card-reason">⚠ {session.notice}</div>}
      {session.state === 'error' && (
        <div className="setup-card-reason">{session.error}</div>
      )}
    </>
  )
}

function Stat({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="app-stat">
      <span className="app-stat-label">{label}</span>
      <span className="app-stat-value">{value}</span>
    </div>
  )
}

function CommandEditor({
  app,
  entry,
  onDone,
}: {
  app: AppId
  entry: AppEntry | null
  onDone: () => void
}) {
  const [draft, setDraft] = useState(entry?.command ?? '')
  const save = () =>
    void api
      .appSetCommand(app, draft)
      .then((body) => {
        useAppSessionStore.getState().setApps(body.apps)
        onDone()
      })
      .catch(fail)
  return (
    <div className="app-command-editor">
      <label className="setup-card-hint" htmlFor={`app-command-${app}`}>
        Command that starts {entry?.title ?? app}. The console adds
        <code> --connect … --token …</code>.
      </label>
      <input
        id={`app-command-${app}`}
        type="text"
        spellCheck={false}
        value={draft}
        placeholder={entry?.example_command}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => e.key === 'Enter' && draft.trim() && save()}
      />
      <div className="setup-card-row">
        <button className="btn btn-primary" disabled={!draft.trim()} onClick={save}>
          save
        </button>
        {entry?.command && (
          <button className="btn btn-secondary" onClick={onDone}>
            cancel
          </button>
        )}
      </div>
    </div>
  )
}
