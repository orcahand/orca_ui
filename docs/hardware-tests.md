# Hardware tests: required before every merge to main

orca_ui and orca_core drive a real robot hand: motors that can overheat, tendons that can snap, and fingers that
can pinch. Unit tests can't show that a change is safe on a hand. So **every change to orca_ui or orca_core is
tested on a real hand with the console's Tests tab before it is merged to `main`**, and the pull request carries
a report file that proves it. This applies to everyone: the ORCA team, outside contributors, and the AI agents
working for either.

This page is the rulebook. It covers what to test, on which hands, how to run the tests, how to export the
report, and how maintainers check it. Words in **must** and **never** are rules, not advice.

> **For AI agents:** read the whole page before you start. You may not test a hand yourself. Your job is to
> prepare everything, tell your user exactly what to do (see [What an agent tells its user](#what-an-agent-tells-its-user)),
> and never produce, change or "fix" test results. A PR without a valid report is not ready for review, and
> you must say so.

## Contents

1. [The rule](#1-the-rule)
2. [Which hands](#2-which-hands)
3. [Safety at the bench](#3-safety-at-the-bench)
4. [What to test: your plan](#4-what-to-test-your-plan)
5. [Writing test steps](#5-writing-test-steps)
6. [Setting up](#6-setting-up)
7. [Running the tests](#7-running-the-tests)
8. [The report](#8-the-report)
9. [Rules for the Tests tab](#9-rules-for-the-tests-tab)
10. [What an agent tells its user](#what-an-agent-tells-its-user)
11. [For maintainers: verifying a report](#11-for-maintainers-verifying-a-report)
12. [Until the Tests tab is on main](#12-until-the-tests-tab-is-on-main)

## 1. The rule

- A pull request into `main` of **orca_ui** or **orca_core** is merged only when it carries at least one
  hardware-test report under `hardware-test-reports/` that passes `verify` (section 11), for every motor family
  the change can affect.
- The report must come from the **exact code in the PR**. If you change code after testing, you test again.
  Adding the report file is the only change allowed after the test.
- A failed, missing or skipped required step means the PR is **not ready**. Fix the code, or explain the
  failure in the PR and let a maintainer decide. Never edit the test, the plan or the results to make it pass.
- Documentation-only changes (no code, configs, models or build files) need no report. Say so in the PR.

## 2. Which hands

- **Contributors** test on every ORCA hand they have that the change can affect, and on **at least one real
  hand**. A mock hand never counts.
- If the change touches anything specific to a motor family (Dynamixel or Feetech), a hand of that family is
  required. If it touches tactile sensors, a Touch hand is required.
- **Maintainers** run the same plan on the families and hand types the contributor didn't have before merging.
- **In-house (ORCA team):** test on every relevant hand. Once the shared test bench exists, it is the place
  for this: it holds every relevant hand, and its runs are the reference.
- Write in the PR which hands you tested on (model, motor family, hardware version) and which you couldn't.

## 3. Safety at the bench

- A person **must** stay within reach of the hand and its power switch for the whole session, automatic steps
  included. The console's E-STOP must be on screen.
- The hand must be clamped or mounted, with its fingers free to move their full range. Nothing in its grip,
  no loose cables near the tendons.
- Use the power supply the hand is built for. Unplug power if anything smells, smokes, clicks repeatedly, or a
  motor stays hot to the touch.
- Steps that hold or drive motors make them warm. Let a hand cool before rerunning a holding or current step.
- Hands-on steps tell you what to do with your hands. Never put fingers between moving joints.

## 4. What to test: your plan

Every PR runs one **plan**, a YAML file under `orca_ui/hardware_tests/plans/` that lists features to test.
Your plan **must** contain, in this order:

1. **The base plan** (`base`): checks that must never fail, whatever the change. Connecting, loading every
   model, both test suites, safe current defaults, the hand's own records, a damaged file, calibration as on
   main, the tactile sensors and joint loop where the hand has them, and that every routine lets go of the hand
   on Stop and E-STOP. Most of it runs automatically.
2. **The current release plan**: the plan marked `default: true`, which tests what the release in preparation
   adds. It already includes `base`.
3. **Your own steps**: new or updated feature definitions that test what your change does (section 5).

Write your plan as `plans/change-<short-name>.yaml`:

```yaml
id: change-faster-sweep           # must equal the file name
title: Faster tension sweep
summary: The sweep's new step size, on top of the release plan and the base checks.
includes:
- release-0.14                    # the plan marked default: true; it includes base
features:
- tension-sweep-fast              # your new definition(s)
```

Running only part of a plan doesn't count: the report covers the plan as a whole.

## 5. Writing test steps

A **feature definition** is one YAML file under `orca_ui/hardware_tests/definitions/` with the steps that test
one feature. Look at the existing ones before writing your own.

```yaml
id: tension-sweep-fast
title: Faster tension sweep
group: new                       # new | existing | observation
summary: The sweep with the new step size finishes and stays within the current limit.
steps:
- id: TS1                        # unique across all definitions
  title: The sweep finishes on every finger
  kind: auto                     # auto | compare | manual | observe
  check: sweep_fast_finishes     # a registered check, for auto and compare steps
  applies_to: {motor_family: feetech}
  instructions: The check runs the sweep at 100 mA and reads every motor's current.
  pass_rule: Every finger finishes; no motor holds above the limit; torque is off at the end.
```

Rules for steps:

- **Automatic first.** Every step that a program can decide **must** be `auto` (runs in the console) or
  `compare` (runs the same scenario on main's and your orca_core and compares). Use `manual` only for what
  really needs a person: looking at the hand, touching it, unplugging a cable. Every manual step must say in
  its `instructions` exactly what to do and in `pass_rule` exactly what to look for.
- **Relevant.** Each step tests something your change could break or newly does. No steps that pass whatever
  the code does, and no duplicates of base steps.
- **Strict pass rules.** A step passes only on the result that proves the feature works. A check that can't
  measure what it tests (the motor didn't move, a sensor didn't answer) returns `fail` or `error`, never `pass`.
- **Checks** are Python functions in `orca_ui/hardware_tests/checks/`, registered with
  `@register("<name>")`. They must call `ctx.check_stop()` between slow parts, switch torque off on every way
  out, and return a `CheckResult` with the numbers they decided on.
- `observe` steps record something for the record and never pass or fail. Don't use them to hide a step that
  fails.
- Never change or remove someone else's step to make your change pass. If an existing step is wrong, fix it in
  a separate commit and say why in the PR.

## 6. Setting up

You need three checkouts: the **Tests tab** (orca_ui), the **orca_core under test**, and a clean **orca_core
`main`** for the comparison steps. You also need [uv](https://docs.astral.sh/uv/) and, for orca_ui changes,
Node.js to rebuild the web page.

**orca_core `main` for comparisons** (once):

```sh
git clone https://github.com/orcahand/orca_core.git ~/code/orca_core
git -C ~/code/orca_core worktree add --detach ~/code/worktrees/orca_core-main origin/main
```

Keep that worktree on `origin/main` and never edit it.

### A change to orca_core

```sh
# The orca_core under test: your PR branch, everything committed, nothing uncommitted.
git -C ~/code/orca_core switch <your-branch>

# The Tests tab (see section 12 while it isn't on main).
git clone https://github.com/orcahand/orca_ui.git ~/code/orca_ui
cd ~/code/orca_ui
git switch feature/hardware-tests        # or your tests branch, if you added steps
uv sync
./dev local ~/code/orca_core             # the console now runs your orca_core
uv run orca-ui --hardware-tests --main-core ~/code/worktrees/orca_core-main
```

### A change to orca_ui

The Tests tab must run with your change in it. Make a **test branch** that merges your PR branch with the
Tests tab. Never open a pull request from it:

```sh
cd ~/code/orca_ui
git switch -c hwtest/<your-branch> <your-branch>
git merge --no-edit origin/feature/hardware-tests   # and your tests branch, if you added steps
# A conflict in orca_ui/webui/ only: take either side, then rebuild.
(cd frontend && npm ci && npm run build) && git add orca_ui/webui && git commit --no-edit
uv sync
git -C ~/code/orca_core switch main && git -C ~/code/orca_core pull --ff-only
./dev local ~/code/orca_core             # the released orca_core, from a clean checkout of main
uv run orca-ui --hardware-tests --main-core ~/code/worktrees/orca_core-main
```

The merge may only bring in the Tests tab. Don't change anything else on `hwtest/<your-branch>`. Maintainers
need its exact commit to verify your report, so after testing push it **to your fork** (ORCA team: to
`origin`) and link it from your PR: `git push <your fork> hwtest/<your-branch>`. It is deleted once your PR is
merged.

In both cases the console opens in the browser with a **Tests** tab. It shows only with `--hardware-tests`.
Results go to `~/orca_bench/<hand>/tests/` (change with `--bench-dir`).

## 7. Running the tests

1. Connect one hand and let the console detect it. Check model, side and hardware version in the header.
2. Open **Tests**, choose your plan and start a session.
3. Do the **hands-on steps** first, as each one asks. Mark each one pass or fail and write what you saw in the
   note. A skipped step needs a note saying why.
4. Start the **automatic run** for the rest. Stay at the bench (section 3). It can take an hour or more.
5. A step that **fails**: read its message and files, fix the code, commit, and start a **new session**. Don't
   rerun failed steps in an old session after changing code: the session records the code it started with, and
   a session whose code changed can't be exported.
6. When every applicable step is decided, **end the session** in the Tests tab. Only an ended session can be
   exported.
7. Repeat for each hand (one session per hand).

Everything a session records stays in `~/orca_bench/<hand>/tests/`: a summary (`sessions/<stamp> <plan>.md`),
every event, the readings during each step and each check's output. Read them when a step fails.

## 8. The report

Export one report per session, from the checkout that ran it, straight into the repo the PR targets:

```sh
uv run python -m orca_ui.hardware_tests.report export \
  "~/orca_bench/<hand>/tests/sessions/<stamp> <plan>.json" \
  --out-dir <path to the PR's repo>/hardware-test-reports
```

This writes `hardware-test-reports/<date>_<plan>_<model>_<motor family>.json`. Then, on your PR branch:

```sh
git add hardware-test-reports/<file>.json
git commit -m "Add the hardware test report for <model>, <motor family>"
```

Commit nothing else after it. For an orca_ui change, switch from `hwtest/<your-branch>` back to your PR branch
first; the new file comes along.

**What the report contains:** the commits tested (orca_ui and orca_core, and whether they had uncommitted
changes), the plan and a fingerprint of every plan and step file, the hand's model, side, motor family and
hardware version (its serial only as a hash), every step's kind, result, who decided it and its message and
note, and a checksum over all of it. Home folders and the hand's serial are removed from messages and notes.

**Export refuses** a session that isn't ended, one made before the session recorded its code, one whose code
changed during the session, and one tested with uncommitted changes. `--allow-dirty` exports anyway, but
`verify` then rejects the report: use it only to share results while debugging.

**Never edit a report.** Its checksum and fingerprints make any edit visible, and an edited report counts as a
false report.

## 9. Rules for the Tests tab

1. Test before every merge to `main`, on the exact code of the PR (section 1).
2. Real hands only. A mock hand is for trying the Tests tab, never for a report.
3. Commit everything before you start a session. Change nothing in any checkout while it runs.
4. One session per hand, ended, then exported. Changed code means a new session.
5. Automatic steps are decided by their checks. **Never** mark an automatic step pass or fail yourself.
6. Manual steps are decided by the person who did them, honestly, with a note when they fail or are skipped.
7. Base steps are never skipped when they apply to the hand.
8. **Never** edit a definition, plan, check, result file or report to make a step pass, skip or disappear.
9. A step that fails for a reason that has nothing to do with your change: leave it failed, and describe it in
   the PR. A maintainer decides whether it's a known problem and how to handle it.
10. Never open a pull request from a `hwtest/*` branch, and don't commit `~/orca_bench` files or screenshots.
    Your PR gets only the exported report.
11. Agents never operate the hand, never decide manual steps, and never write or change results. They prepare,
    explain, export and report.

<a id="what-an-agent-tells-its-user"></a>
## 10. What an agent tells its user

Before a PR into `main` is ready, an agent working on orca_ui or orca_core **must** tell its user, in plain
words, all of the following, filled in for this change:

1. **That hardware testing is required** before the merge, and why: the change runs on a real hand.
2. **Which plan to run** (`plans/change-<name>.yaml`), what it includes, and which new steps the agent added.
   Say how many steps are hands-on and roughly how long the automatic run takes.
3. **Which hands** are needed: the motor families and hand types the change can affect, and which of them the
   user has.
4. **The exact setup commands** from section 6 for this change, with real paths and branch names.
5. **The safety rules** from section 3, briefly.
6. **What to do in the Tests tab**: choose the plan, do the hands-on steps (list them with what to look for),
   start the automatic run, stay at the bench, end the session.
7. **The export and commit commands** from section 8, filled in.
8. **What happens next**: the agent reads the session summary and failures with the user, and the PR is ready
   only when `verify` passes on every report.

Agents must not:

- claim a test passed that they didn't see pass in the session files;
- mark, edit, delete or regenerate results, sessions or reports;
- shorten a plan, weaken a pass rule or turn a step into `observe` to get past a failure;
- export with `--allow-dirty` for a PR;
- push or merge anything their user didn't ask for.

When a step fails, the agent shows the user the failing step, its message and the files it wrote, says what it
thinks the cause is and how sure it is, and proposes a fix. It doesn't skip the step.

## 11. For maintainers: verifying a report

Run `verify` from a checkout of the Tests tab. Fetch the PR first, and for an orca_ui PR also the
contributor's `hwtest/<branch>` and any tests branch they merged:

```sh
# orca_ui PR: --repo is an orca_ui clone with the PR and the hwtest branch fetched.
uv run python -m orca_ui.hardware_tests.report verify hardware-test-reports/<file>.json \
  --repo <orca_ui clone> --expect-commit <PR head> [--tests-branch <tests branch they merged>]

# orca_core PR: --repo is an orca_core clone with the PR fetched; --ui-repo has the tested orca_ui commit.
uv run python -m orca_ui.hardware_tests.report verify hardware-test-reports/<file>.json \
  --repo <orca_core clone> --expect-commit <PR head> --ui-repo <orca_ui clone>
```

It prints `note:` and `problem:` lines and ends with `VERIFIED` (exit 0) or `REJECTED (<n> problems)` (exit 1).
It checks, among other things:

- the checksum, and that the summary and verdict match the steps;
- a real hand, and no uncommitted changes in the tested code;
- that the code didn't change during the session;
- that the plan includes `base`, and that the plan and every step file match the tested orca_ui commit
  exactly, so no step was dropped or weakened;
- every applicable step is decided: none failed or pending, automatic steps decided by their check, manual
  steps by a person, skips explained, no base step skipped;
- that the PR head is the tested code plus only files under `hardware-test-reports/`;
- that the session started after the tested commits were made.

A `VERIFIED` report proves the tool ran on that code and that nobody edited the results afterwards. It can't
prove a person judged a manual step honestly. That's why maintainers run the missing hand types themselves
(section 2), and repeat any hands-on step they have doubts about.

Before merging, check that there is a verified report for every motor family and hand type the change can
affect, and run the missing ones yourself.

## 12. Until the Tests tab is on main

For now the Tests tab lives on orca_ui's `feature/hardware-tests` branch, not on `main`. Until it moves to
`main`:

- **New steps and plans** go to a branch made from `feature/hardware-tests` (`tests/<your-branch>`), proposed
  as its own PR into `feature/hardware-tests`, never into `main`. Link it from your main PR.
- **orca_core changes:** run the Tests tab from `feature/hardware-tests`, or from your tests branch if you
  added steps. The maintainer needs that commit to verify (`--ui-repo`).
- **orca_ui changes:** test on the `hwtest/<your-branch>` merge from section 6 and push it to your fork. The
  maintainer verifies with `--tests-branch` set to the tests branch you merged.
- Once the Tests tab is on `main`, the steps and plan live in the same PR as the change, and the `hwtest`
  merge goes away.
