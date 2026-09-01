# Claude Code Instructions

## Project: ORCA UI

Browser console for the ORCA Hand. A FastAPI backend (`orca_ui/`) drives the
hand through [orca_core](https://github.com/orcahand/orca_core) and serves a
React frontend (`frontend/`, built into `orca_ui/webui/`).

See [DEVELOPMENT.md](DEVELOPMENT.md) for running from source, the frontend
build, and working against an unreleased `orca_core`.

---

## Testing policy

**This suite is deliberately small. Keep it that way.**

The console drives real hardware that can damage itself and hurt whoever is
holding it. A test earns its place here by catching a bug that would *hurt
someone, break the hand, or break the frontend* — not by covering a line.

The suite is capped at roughly **70 tests**. Adding one that is not
safety- or contract-critical means removing one that is, or leaving it out.

### What belongs here

- **Safety interlocks.** E-stop; torque gates (nothing moves without torque);
  current ceilings; ROM clamping; unknown-joint rejection; anything that
  refuses a dangerous command.
- **Ownership and arbitration.** Only one operation at a time; the
  control-source arbiter; leases released on failure; teleop yielding on
  torque loss or tracking loss; operations blocking a disconnect or a model
  change.
- **Letting go of the hardware.** Disconnect leaves torque off and refuses
  further hardware calls; reconnect restores.
- **Fault handling.** Bus-error accounting, stall detection, and latched
  hardware-error classification — a power fault must never be reported as
  "let it cool".
- **Connection and identity.** The degradation ladder; adopting the model the
  boards report; a pinned model never being revised.
- **The frontend's contract.** The REST and WebSocket shapes the UI reads.
  Break these and the console goes blank with no Python traceback anywhere.

### What does not

- Developer tooling (which `orca_core` is installed, dev-mode overrides).
- Exhaustive variants of a behaviour already covered once. One replay-pacing
  test, not eight.
- Analytics and bookkeeping (usage stats, histograms, session naming).
- Secondary interfaces beyond their safety gates — the MCP server keeps
  e-stop registration, the torque gate, and the real-hardware confirm gate,
  and nothing else.
- Installer and build plumbing (cloning, npm builds, remembered paths).
- Asset sanity beyond the one check that the bundle's joints match
  `orca_core`'s.

### Before adding a test

Ask which of the bullets above it falls under. If the answer is "none, but it
would be nice to have covered", do not add it. If it is genuinely critical and
the suite is at cap, say which existing test it displaces.

### Before deleting a test

Deleting is the easy half — the hard half is not deleting the one thing that
was holding a real bug down. Check `git log` on the file first: a test added
in the same commit as a bug fix is guarding that fix.

### Running

```bash
uv run pytest tests/            # ~70 tests, a few seconds
uv run pytest tests/ -n0        # serial, for debugging one test
```

The suite runs against whichever `orca_core` is installed. A failure that
appears only in dev mode is usually the console disagreeing with an
unreleased `orca_core` — check `./dev status` first.

---

## Code Style

- Write concise, self-documenting code; avoid excessive comments.
- Comments describe the current state of the code, never its history. Don't
  reference previous versions, past bugs, or prior approaches.
- Max 1-2 lines per comment, except file/class/function headstrings.
- Follow existing patterns; remove commented-out code before committing.

## Frontend

The built bundle in `orca_ui/webui/` is committed and ships in the wheel.
After changing anything under `frontend/`:

```bash
cd frontend && npm install && npm run build && cd ..
git add orca_ui/webui
```

A pre-commit hook blocks committing frontend sources without a rebuilt bundle.
Everything static the UI serves must live in `frontend/public/` — the build
runs with `emptyOutDir`, so a file that exists only in `orca_ui/webui/` is
deleted by the next build.

## Git

- Work on feature branches; never push directly to `main`.
- Conventional commit subjects: `Add feature`, `Fix bug`, `Update docs`.
