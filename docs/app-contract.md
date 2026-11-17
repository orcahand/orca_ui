# The app contract (protocol 2)

An **app** is a program the console starts and that drives the hand through it:
`orca_teleop` (the Teleop tab) and `orca_rl` (the RL tab). The console owns the
hand and all session safety. The app owns its devices, models, settings and
pictures, and stays runnable on its own. This page is everything an app needs;
`orca_ui/hand/app/protocol.py` is the code version.

## Launch

The console runs the command set in the app's tab, plus two arguments:

```
<command> --connect ws://127.0.0.1:<port>/ws/app --token <token>
```

- Nothing else goes on the command line. Settings arrive over the link.
- The command can only be set from the console's own computer.
- The app's stdout and stderr appear in the tab's log, so plain prints work.
- The app runs in its own process group. Ending a session sends `stop`; if
  the group hasn't exited 1 s later it gets SIGTERM, then SIGKILL 3 s after that.
- The app must exit when it receives `stop` or when the link closes.

For development, an app started by hand gets a token from
`POST /api/app/start {"app": "teleop", "mode": "external"}`.

## The link

One WebSocket at `/ws/app`. JSON text frames, each `{"type": ..., "data": {...}}`.
The first frame must be `hello`, within 5 s. A refused hello closes the socket
with 4001 (bad token), 4002 (wrong protocol or not a hello) or 4004 (no session
is waiting). Unknown message types and fields are ignored on both sides, so
either side can add optional ones without a new protocol version.

### App → console

| Message | Data | When |
|---|---|---|
| `hello` | `token`, `proto: 2`, `app` (a free name, for the log) | first frame |
| `settings` | `schema` (list of settings, below), `values` {key: value}, `errors` {key: text} | after `hello_ok`, and after every `set` |
| `targets` | `angles` {joint id: degrees}; partial sets are fine | streaming, steadily (see holds) |
| `status` | `tracking` (bool, optional), `info` {label: text} shown as-is in the tab | ~1–2 Hz |
| `frame` | `stream` (a name, one per camera or view), `jpeg` (base64) | ≤ 10 Hz per stream |
| `log` | `line`, `level` (optional) | any time |

### Console → app

| Message | Data | When |
|---|---|---|
| `hello_ok` | `session_id`, `proto: 2`, `hand`, `values` (the remembered settings) | answer to `hello` |
| `set` | {key: value} for the settings the user changed | a user change |
| `engaged` | `engaged` (bool) | Engage and Disengage; informational |
| `stop` | {} | the session ends; exit |

`hand` is `{model, side, hardware_version, joints, ranges}`: the model name,
`"left"` or `"right"`, the hardware version in force (an integer such as 21, or
null), the joint ids in order, and each joint's `[min, max]` in degrees. The app
picks its own model files from this and closes the link if it can't drive that
hand. If the hand changes during a session, the console ends the session.

## Settings

The app describes its settings; the tab draws them as a form and remembers the
values for the next start. A setting is a small JSON Schema subset:

```json
{"key": "camera", "title": "Camera", "type": "enum",
 "choices": [{"value": 0, "title": "FaceTime HD"}, {"value": 1, "title": "Desk View"}],
 "default": 0, "help": "which camera tracks your hand", "restart": true, "live": false}
```

- `type` is one of `boolean`, `integer`, `number` (with `minimum`/`maximum`),
  `string`, `enum` (with `choices`). Machine-dependent lists (cameras, trained
  policies) are just choices the app fills in.
- `restart: true`: the change takes effect on the next start.
- `live: true`: may change while engaged. Every other setting is locked while
  engaged ("disengage to change").
- The console keeps only the fields above and drops a malformed setting (an
  unknown type, an enum without valid choices) and any NaN or Infinity in a
  bound, default, choice or value, so check the tab after a change.
- Apply the `values` from `hello_ok` before opening devices.
- Answer every `set` with a full `settings` message: the values actually
  applied, and an error text for each refused key. The tab shows exactly that.
  The console only sends values that fit the setting's type, range and choices.

## What the console does with targets

- **Preview:** targets only pose the ghost. The hand never moves.
- **Engaged:** targets are clamped to each joint's range and forwarded. Engage
  ramps in from the hand's current pose (2 s by default, never under 0.5 s); a
  joint first named later ramps in from where it is too. **In console mode the
  app must not ramp or hold on its own**; the console does both.
- **Holds:** no targets for 250 ms, or `status.tracking` false, holds the pose;
  targets sent while `tracking` is false are not forwarded. When targets return
  the console ramps in again, so the hand never jumps. A hold longer than 10 s
  disengages.
- **Ends:** Disengage holds the pose with torque on. Stop, the app exiting, the
  link closing or a hand change end the session; if it was engaged, torque goes
  off where the hand is. E-STOP cuts torque first.
- Only one app runs at a time.

The hand's state (`joints.measured`, `joints.estimate`, ...) can be read
from the console's `/ws` topics; nothing in this contract needs it.

## Testing an app against the console

Run the console your app pins with `--mock` (no hardware), open an external
session with the REST call above, connect, and check the exchange. orca_rl's
`tests/test_orca_ui_contract.py` does this with `uvx`. The console's own
synthetic app, `scripts/dev_app_synthetic.py`, is a complete example in about
150 lines.
