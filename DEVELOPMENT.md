# Developing orca_ui

Everything here is about working on the console itself. To just *run* it, the
[README](README.md) is enough.

## Working against an unreleased orca_core

The console talks to the hand through
[orca_core](https://github.com/orcahand/orca_core). A plain `uv sync` installs
the **released** `orca_core` from PyPI, which is what you want almost always.

When you are changing both repos at once, point the console at your own
`orca_core` checkout instead. One command:

```bash
uv run orca-dev
```

That reports what you are on, finds your `orca_core` checkout, and offers to
use it:

```
orca_core   0.4.0
source      released package (PyPI)

Found an orca_core checkout at ../orca_core (branch main).
Develop against it? [Y/n]
```

Say yes and you are done. There is nothing else to configure.

### What it actually does

It installs your checkout **editable**, which means the console imports the
Python files in that directory directly — it does not copy them.

The consequences are worth knowing:

- **It follows your current branch.** Whatever is checked out in `orca_core` is
  what the UI runs. Switching branches there needs no reinstall — restart the
  UI and you are on the new code.
- **It follows uncommitted edits too.** Save a file in `orca_core`, restart the
  UI, and the change is live.
- **You never type a path** (unless your checkout is somewhere unusual — see
  below).

The one case that needs more than a restart: if the branch you moved to **adds
a dependency**, run `uv sync` in this repo so the new package gets installed.

### Finding your checkout

`orca-dev` looks in this order, and stops at the first hit:

1. a path you passed explicitly
2. the path it remembered last time (`.orca-dev.json`, gitignored)
3. the `../orca_core` sibling directory
4. a scan of the directories next to this repo for an `orca_core` source tree

If step 4 finds several — normal if you keep worktrees or experiment clones
side by side — it lists them and asks which one, then remembers your answer:

```
Several orca_core checkouts are available:

  1) ../orca_core                [main]
  2) ../orca_core-tactile        [feature/tactile-frames *]
  3) ../orca_core-taxel-frames   [main]

Which one? (number, or a path):
```

To point it somewhere else later, name it once:

```bash
uv run orca-dev local ~/src/orca_core
```

## The four commands

| Command | Use it when |
|---|---|
| `uv run orca-dev` | Day to day. Reports, and offers the obvious next step. |
| `uv run orca-dev local [PATH]` | Use a local checkout. `PATH` only for an unusual location, once. |
| `uv run orca-dev branch NAME` | Track a branch of the `orca_core` repo **without** a local checkout — a colleague's machine, a CI box, a quick test of someone's PR. |
| `uv run orca-dev release` | Back to the published package. |

`local` vs `release` is just *whose orca_core*: your working copy, or the one
on PyPI that users get. `release` is the state the repo is committed in;
`local` is a thing you turn on for yourself.

## Knowing which one you are on

Three places, so it is hard to be wrong about:

```bash
uv run orca-dev status
```

The `orca-ui` startup banner:

```
──────────────────────────────────────────────────────────────
  ORCA UI   http://localhost:5001
  config    …/models/v2/orcahand-full-left/config.yaml
  mode      hardware
  core      orca_core 0.4.0 — local ../orca_core @ feature/wrist (modified)
──────────────────────────────────────────────────────────────
```

And an amber **DEV CORE** badge in the console header, next to the model name,
whenever you are not on a release. It shows the branch, with a `*` if that
checkout has uncommitted changes.

## Committing while in dev mode

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

The commit is byte-identical to what you would have committed from a clean
checkout, so your local setup can never reach a branch or a PR. Everything
else in the commit — including other edits to `pyproject.toml`, like a version
bump — goes in untouched.

The hook is enabled automatically the first time you run `orca-dev local`. To
check, or to enable it by hand in a fresh clone:

```bash
git config core.hooksPath .githooks
```

One case the hook cannot fix by itself: if you **add or remove a dependency**
while in dev mode, the lockfile it keeps is the committed one, which is then
stale. It says so, and tells you the three commands to fix it.

## Frontend

The built frontend (`orca_ui/webui/`) is committed so npm-less machines run
from a plain checkout. If you change anything under `frontend/`:

```bash
cd frontend && npm install && npm run build && cd ..
git add orca_ui/webui
```

The same pre-commit hook stops you committing frontend sources without a
rebuilt bundle.

## Tests

```bash
uv run pytest tests/
```

Worth knowing: the suite runs against whichever `orca_core` is installed. A
failure that appears only in dev mode is usually the console disagreeing with
an unreleased `orca_core` change — check with `uv run orca-dev status` before
hunting for it in this repo.
