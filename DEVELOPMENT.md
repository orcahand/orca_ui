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
uv run pytest tests/            # a few seconds, run in parallel
uv run pytest tests/ -n0        # serial, for debugging one test
```

The frontend has a headless URDF check: `cd frontend && node
scripts/check-urdf.mjs`.

The suite runs against whichever `orca_core` is installed. A failure that
appears only on your machine is usually the console disagreeing with an
unreleased `orca_core`. The header's DEV CORE
badge and the startup banner both name the source that is actually imported.

## Frontend

The built frontend (`orca_ui/webui/`) is committed so npm-less machines run
from a plain checkout, and it ships in the wheel. If you change anything under
`frontend/`:

```bash
cd frontend && npm install && npm run build && cd ..
git add orca_ui/webui
```

The pre-commit hook stops you committing frontend sources without a rebuilt
bundle. Git does not ship active hooks, so turn it on once per clone:
`git config core.hooksPath .githooks`.

Everything static the UI serves has to live in `frontend/public/` — the build
runs with `emptyOutDir`, so a file that exists only in `orca_ui/webui/` is
deleted by the next `npm run build` and nobody notices until the feature that
needed it goes quiet.

## Working against an unreleased orca_core

`pyproject.toml` depends on the published `orca_core`, which is what a plain
clone runs. To flip this checkout onto a local one:

```bash
./dev local          # the sibling ../orca_core, live-editable
./dev local DIR      # a checkout or worktree somewhere else
./dev release        # back to the published package
./dev                # which one is live, and offer to flip
```

The flip sticks until you flip back. It links the checkout into `.venv` and
puts it ahead of the installed package on `sys.path`, so `uv run`, `uv sync`
and an IDE pointed at `.venv` all see it, and nothing tracked changes.
Recreating `.venv` drops it, back to the release.

`./dev local` also installs whatever the checkout's own dependencies need that
the venv does not already satisfy, so a core that adds or bumps one just works.
Those land in the same shim rather than the venv, where `uv run` would put the
locked versions back. Re-run `./dev local` after the core's dependencies
change, or after a `uv sync` that moves the lock.

Do not add a `[tool.uv.sources]` entry for `orca_core` instead. A path is a
fact about one machine: committed, it makes the project unresolvable
everywhere else. `.githooks/pre-commit` refuses to commit one,
`tests/test_no_committed_dev_override.py` fails on one in `HEAD`, and CI
installs PRs into `main` with `uv sync --locked`. `./dev` warns when it finds
one in your working tree.

A branch that needs an unreleased `orca_core` is paired in CI instead:
`test.yml` checks `orca_core` out beside this repo, preferring a branch of the
same name as the PR's head or base and falling back to `main`, and runs the
suite against it. Give the two branches the same name and they are
tested together.

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

The `orca_ui/webui` build output is committed and ships in the wheel; rebuild
the frontend before releasing so it is current.
