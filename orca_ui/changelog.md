<!-- ===========================================================================

  THE CONSOLE'S CHANGELOG — read by the Changelog button, written by you.

  Plain Markdown. Edit this file, reload the console, and what you wrote is
  what readers see. No rebuild, no restart.

  ---------------------------------------------------------------------------
  WHO WRITES WHAT

  Claude proposes the headers — one "### " line per change, sorted into
  Features and Bugfixes — by reading the branch's commits and diff. Claude
  writes nothing else, ever.

  You delete the headers that do not deserve an entry, and write the text
  under the ones that stay. YOU WRITE EVERYTHING BELOW A "### " LINE: the
  blank space under each header is yours.

      ### A header Claude proposed          <- Claude's
      <- from here down to the next ###, yours

  When the entries are done, Claude reads them back against the code and says
  if the text and the build have drifted apart. It only points; you decide.
  Then the version moves and the Core: line is set to match.

  ---------------------------------------------------------------------------
  THE FOUR LINES THE CONSOLE PARSES

      ## UI 0.3.0 — 2026-10-21     a release. Newest at the top of the file.
      Core: 0.10.1                 the orca_core release to run with it.
      ## Features                  section. Entry numbering restarts here.
      ## Bugfixes                  section.

  A test fails if the version in pyproject.toml has no release heading here,
  or if the Core: line disagrees with the orca-core pin.

  ---------------------------------------------------------------------------
  FORMATTING — what you can use inside an entry

      Leave a blank line between paragraphs. A single newline does not break
      a line; two do.

      **bold**                  -> bold, in the page's ink
      *italic*                  -> italic
      `Motors -> Fault handling` -> a monospace chip, for controls and paths
      [orcahand.com](https://orcahand.com) -> a link, opens in a new tab

      - a bullet                -> a bulleted list. One item per line,
      - another                    no blank line between items.

      1. first                  -> a numbered list. Use it for steps.
      2. second

      > A note                  -> an indented note with a heavy rule down
                                   its left edge. Good for a caveat or a
                                   "this needs X" warning.

      ```                       -> a command block, for something to run
      uv sync                      verbatim. Fence it above and below.
      ```

      #### A sub-heading        -> a small heading inside one entry, if an
                                   entry really needs two parts.

  Not supported, and will show up as literal text: tables, images, and raw
  HTML. Comments like this one never render.

  WRITING THE ENTRIES

  Write for whoever uses the hand. What is different now, and what they do
  with it — the tab and the control by name. Not what changed in the code.

=========================================================================== -->

## UI 0.3.1 — 2026-11-04
Core: 0.12.0

## Features

### Experimental branch: install and run with `uv run orca-ui`

- This version of the orca_ui is an experimental branch that combines the assembly guide, the new tensioning and calibration, and the fixes from `main`. It is unreleased and only lightly tested, and it will be replaced by a release on `main`, at which point you will need a fresh clone.

- For this branch you no longer need a separate `orca_core` clone. A plain `uv run orca-ui` installs the matching unreleased `orca_core` by itself. The header shows **DEV CORE · feature/improve-calibration** while you are on this version.

### Experimental branch: each hand keeps its files in its own folder

- A plain `uv run orca-ui` now keeps each hand's config and calibration in `~/orca_bench/<serial>/<model>/`, created the first time the hand connects. If you already set a hand up in `~/orca_bench/<serial>/`, its files are copied in and the originals stay where they are.

- A hand that reports no serial number uses the shared model folder instead. Starting `uv run orca-ui` with `--config` or `--model` uses exactly what you name, with no hand folder.

### Experimental branch: one hand per orca_ui run

- Each run stays on the first hand it identifies, so one hand's calibration can't end up in another hand's folder. To use another hand, press Ctrl+C and start the orca_ui again.

- Run one orca_ui at a time for each hand. A orca_ui left open in another terminal holds the hand, and the one you are looking at can't connect.

### Assembly guide in the orca_ui

- The assembly guide now ships with the orca_ui, with its images, videos and 3D models.

### Tensioning pulls, then holds at each motor's ceiling

- Motors now pull, settle where they stopped, and then hold at each motor's own ceiling while you ratchet, so a motor no longer turns with the ratchet under a lower hold. The default pull is 15 degrees, and *Pull more* adds another 15.

- The Tensioning current field is gone. Avoid hard pushes on a finger while the motors are holding, as this may loosen the tendon.

### Calibration drives fingers at each motor's ceiling

- Automatic calibration now drives fingers onto their end stops at each motor's own ceiling, because a lower limit can stall a joint short of its stop and record the wrong range. The calibration current sliders are gone.

- Keep your fingers clear and the power switch within reach while it runs.

### Manual calibration with Back

- Manual calibration now asks for one answer per step, and *Back* lets you redo the previous step if you got it wrong.

### Slack test and tension sweep, with currents per motor type

- The Setup tab now has a *Slack test*, where you hold each joint while its motor winds both ways, and a *Tension sweep*, which records each joint's current over its travel after calibration.

- Slack test currents now start from your motor type, 60 mA on Dynamixel and 120 mA on Feetech, and you can still choose another.

- Feetech values are provisional. On Feetech hands a passing slack test can miss small slack, so please also check the tendons by hand, and the sweep can stop short on some joints.

### Reboot one motor with its torque on

- When a motor reports a fault, you can now reboot just that motor with torque on. Its torque is restored afterwards.

## Bugfixes

### Fingertips that join late are picked up

- A fingertip that appears late or is replugged no longer stops the tactile stream. It is picked up without restarting the orca_ui.

### The orca_ui stops retrying a failed sensor link

- A sensor whose link fails no longer sends the orca_ui into a reconnect loop. The motors stay available, and the orca_ui only tries that sensor again when you press *Rescan*.

### Leaving calibration or tensioning no longer looks like a lost hand

- When calibration or tensioning finishes, the orca_ui reconnects to the hand while keeping its views on screen, instead of dropping to the screen you see when no hand is found.

### Stopped manual calibration and stalled sweeps no longer log errors

- Stopping manual calibration now ends cleanly, without an error in the log.

- A tension sweep that stalls before the end of a joint's travel no longer logs an error.

## UI 0.3.0 — 2026-10-21
Core: 0.10.1

## Features

### Detailed motor tuning

- Tune each PID gain and motion profile factor of your joints from the default to your heart's desire. 

- Setting either velocity or acceleration limits to zero disables that respective section of the profile, uncapping velocity or acceleration respectively.

### Fault and error handling.

- The UI will automatically log, notify, and handle errors you may see reported by your motors in a systematic manner.

- A motor overheating will by default zero all torque commanded to all motors until the temperature has decreased by 10 Celsius from the motor's limit. A motor that latches due to an overload of torque or current will be automatically rebooted and logged. If a motor keeps overloading it will stop rebooting, by default, after the fifth time. 

- Voltage input and or electrical shock errors experienced by any motor will pop up immediately on your UI and encourage you to cut power to the hand immediately. 

- Consult the motor tab to identify which motors are faulting and any other configurable error handling settings you may wish to change from their defaults.

### Reworked setup tab

- Hardware 2.1.x hands now support the *Guided Tensioning* option that will minimize slack accumulation in the tendons. The older tensioning variant can be selected if one so wishes in the options for the tensioning tab. 

- After your hand has been tensioned simply utilize the automatic calibration script and then use the *Run-in* option to stress test your hand to validate successful tensioning all from the same setup panel.

## Bugfixes

### A latched motor no longer freezes the whole hand

### Leaving calibration or tensioning no longer looks like a lost hand

### Motor health no longer labels an overload with an unrelated temperature

### The fault column shows live faults only

### A bus that has stopped answering now says so

### Errors on the fault path are no longer swallowed

### A long run no longer hides an overheating motor

### Feetech hands no longer fail their first fault poll

### A short ping reply no longer crashes the liveness check

### Motion waits no longer time out just short of the target

### Accidentally introduced cycle limit of 1000 has been removed.
