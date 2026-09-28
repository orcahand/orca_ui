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
unreleased `orca_core` — check `./dev status` first. The header's DEV CORE
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
bundle.

Everything static the UI serves has to live in `frontend/public/` — the build
runs with `emptyOutDir`, so a file that exists only in `orca_ui/webui/` is
deleted by the next `npm run build` and nobody notices until the feature that
needed it goes quiet.

## Working against an unreleased orca_core

`pyproject.toml` depends on the published `orca_core`, which is what a plain
clone installs and what the wheel declares. To develop against a local
checkout:

```bash
./dev local          # point at the sibling ../orca_core (found automatically)
./dev branch NAME    # or track a branch of the orca_core repo, no checkout
./dev release        # back to the published package
./dev status         # which one is live right now
```

`./dev` rather than `uv run orca-dev` because `uv run` syncs before it spawns,
so it cannot start while the committed pin is unresolvable — which is exactly
when dev mode is needed. Once the project resolves, either works.

`uv` has no local-only override file, so `./dev local` writes a
`[tool.uv.sources]` entry into the **tracked** `pyproject.toml` and `uv.lock`.
A relative path is a fact about one machine: committed, it makes the project
unresolvable everywhere else, and `uv lock` fails outright on a clone with no
sibling `orca_core`.

So it must never reach a commit. Three things enforce that, and none of them
replaces reading your own diff:

- `.githooks/pre-commit` refuses the commit and tells you what to unstage. It
  only runs in clones that set `core.hooksPath` — git will not ship active
  hooks — so it cannot be the only guard.
- `tests/test_no_committed_dev_override.py` reads the *committed* files, so it
  passes while your working tree is in dev mode and fails only if the override
  is staged.
- `.github/workflows/test.yml` runs that test on every pull request and
  installs with `uv sync --locked`, which rejects an override however it is
  spelled, since `pyproject.toml` and `uv.lock` then disagree. This is the
  guard that catches a commit made on a machine without the hook.

A branch that needs an unreleased `orca_core` does **not** get a source entry
of its own. CI pairs it instead: `test.yml` checks `orca_core` out beside this
repo, preferring a branch of the same name as the PR's head or base and
falling back to `main`. Give the two branches the same name and they are
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

Rebuild the frontend before releasing so the committed bundle is current.
