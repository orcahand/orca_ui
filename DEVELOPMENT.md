# Developing orca_ui

Everything here is about working on the console itself. To just *run* it, the
[README](README.md) is enough.

## Running from source

```bash
uv run orca-ui --mock --no-browser        # backend on :5001
cd frontend && npm run dev                # Vite dev server on :5173, proxied
```

The Vite server proxies API and WebSocket traffic to the backend, so you get
hot reload on the frontend while the backend keeps running.

## Tests

```bash
uv run pytest tests/
```

The frontend has a headless URDF check: `cd frontend && node
scripts/check-urdf.mjs`.

The suite runs against whichever `orca_core` is installed. A failure that
appears only in dev mode is usually the console disagreeing with an unreleased
`orca_core` change — check with `./dev status` before hunting for it in this
repo.

## Frontend

The built frontend (`orca_ui/webui/`) is committed so npm-less machines run
from a plain checkout, and it ships in the wheel. If you change anything under
`frontend/`:

```bash
cd frontend && npm install && npm run build && cd ..
git add orca_ui/webui
```

The pre-commit hook stops you committing frontend sources without a rebuilt
bundle.

Everything static the UI serves has to live in `frontend/public/` — the build
runs with `emptyOutDir`, so a file that exists only in `orca_ui/webui/` is
deleted by the next `npm run build` and nobody notices until the feature that
needed it goes quiet. (The fun-sound mp3s were in exactly that state.)

## Working against an unreleased orca_core

The console talks to the hand through
[orca_core](https://github.com/orcahand/orca_core). A plain `uv sync` installs
the **released** `orca_core` from PyPI, which is what you want almost always.

When you are changing both repos at once, point the console at your own
`orca_core` checkout instead. One command:

```bash
./dev
```

That reports what you are on, finds your `orca_core` checkout, and offers to
use it:

```
orca_core   0.4.0
source      released package (PyPI)

Found an orca_core checkout at ../orca_core (branch main).
Develop against it? [Y/n]
```

### What it actually does

It installs your checkout **editable**: the console imports the Python files in
that directory directly rather than copying them. So it follows whatever branch
you have checked out, and it follows uncommitted edits — save a file in
`orca_core`, restart the UI, and the change is live. Switching branches there
needs no reinstall.

The one case that needs more than a restart: if the branch you moved to **adds
a dependency**, run `uv sync` in this repo so the new package gets installed.

### Finding your checkout

You do not normally pass a path. `./dev` looks in this order, and stops at the
first hit:

1. a path you passed explicitly
2. the path it remembered last time (`.orca-dev.json`, gitignored)
3. the `../orca_core` sibling directory
4. a scan of the directories next to this repo for an `orca_core` source tree

If step 4 finds several — normal if you keep worktrees or experiment clones
side by side — it lists them with their branches and asks which one, then
remembers your answer. To point it somewhere else later, name it once:

```bash
./dev local ~/src/orca_core
```

### The four commands

| Command | Use it when |
|---|---|
| `./dev` | Day to day. Reports, and offers the obvious next step. |
| `./dev local [PATH]` | Use a local checkout. `PATH` only for an unusual location, once. |
| `./dev branch NAME` | Track a branch of the `orca_core` repo **without** a local checkout — a colleague's machine, a CI box, a quick test of someone's PR. |
| `./dev release` | Back to the published package. |

`release` is the state the repo is committed in; `local` is a thing you turn on
for yourself.

`./dev` and `uv run orca-dev` are the same program, with one difference that
matters exactly when you need it: `uv run` syncs the project before it spawns
anything, so it cannot start while the committed `orca_core` pin is
unresolvable — which is the usual reason to be turning dev mode on. That
happens whenever this repo has adapted to an `orca_core` that is not published
yet: a fresh clone asks PyPI for a version that does not exist, and `uv run
orca-dev` dies with the resolution error instead of fixing it.

`./dev` runs the same code under a bare `python3`, so it works from a fresh
clone with no virtualenv at all. Prefer it; `uv run orca-dev` stays valid.

### Knowing which one you are on

`./dev status` reports it, and so does the `orca-ui` startup banner:

```
──────────────────────────────────────────────────────────────
  ORCA UI   http://localhost:5001
  config    …/models/v2/orcahand-full-left/config.yaml
  mode      hardware
  core      orca_core 0.4.0 — local ../orca_core @ feature/wrist (modified)
──────────────────────────────────────────────────────────────
```

An amber **DEV CORE** badge also appears in the console header, next to the
model name, whenever you are not on a release. It shows the branch, with a `*`
if that checkout has uncommitted changes.

### Committing while in dev mode

**Just commit. You do not have to remember to switch back.**

`uv` has no local-only override file — `[tool.uv.sources]` has to live in the
tracked `pyproject.toml` — so turning on dev mode does modify `pyproject.toml`
and `uv.lock`. Seeing them as modified in `git status` is expected.

The pre-commit hook removes that override from **what gets committed**, and
leaves your working tree in dev mode. You will see:

```
orca-dev: committing without your local orca_core override
(pyproject.toml, uv.lock). Your working tree stays in dev mode.
```

Everything else in the commit — including other edits to `pyproject.toml`, like
a version bump — goes in untouched.

The hook is enabled automatically the first time you run `./dev local`. To
check, or to enable it by hand in a fresh clone:

```bash
git config core.hooksPath .githooks
```

One case the hook cannot fix by itself: if you **add or remove a dependency**
while in dev mode, the lockfile it keeps is the committed one, which is then
stale. It says so, and tells you the three commands to fix it.

### Pulling while in dev mode

Dev mode lives in tracked files, so incoming changes to `pyproject.toml` revert
it. A `post-merge` / `post-checkout` / `post-rewrite` hook puts it back — the
mirror image of the pre-commit one. After a pull you will see:

```
orca-dev: restoring your local orca_core override (../orca_core).
$ uv add --editable ../orca_core
```

You do not have to do anything. It only acts when dev mode was on *and* the
operation removed it, so a checkout that never used dev mode pays nothing.
`./dev release` is remembered too: going back to the published package is not
undone by the next pull.

If a pull is refused because your `pyproject.toml` is modified, discard and
pull — the hook restores dev mode afterwards:

```bash
git checkout -- pyproject.toml uv.lock
git pull
```

Discarding on its own is deliberately *not* undone: `git checkout -- <file>` is
how you clear the override to let that pull through, so restoring it there
would just re-block the pull.

Two things fire no git hook at all, so dev mode stays off until the next merge
or branch checkout: **`git reset --hard`** and **`git stash`**. If you use
those, `./dev status` tells you where you stand and `./dev local` puts it back.

## 3D asset bundle

`orca_ui/models/hand_v2/` is generated from the `orcahand_description` repo by

```bash
uv run --group assets python scripts/build_hand_bundle.py
```

which renames the Fusion-exported URDF joints to orca_core canonical ids,
decimates the meshes to browser-friendly GLBs, adds fingertip frames, and
prints a per-joint ROM report cross-checking the URDF limits against
orca_core's ROMs (orca_core degrees map onto the URDF 1:1 — there is no
per-joint correction table). Verify joint directions with the mock sweep tool,
one joint at a time.

## Releasing

```bash
cd frontend && npm run build && cd ..
uv build
```

Rebuild the frontend before releasing so the committed bundle is current.
