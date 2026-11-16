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

## UI 0.6.0 — 2026-11-16
Core: 0.14.0

## Features

### One folder per hand

Each hand now keeps its calibration and setup records in its own folder, `~/.orca/hands/<hand id>`, so two hands of the same model no longer share or overwrite their calibrations and records. The console's own library, recordings and assembly progress move once from `~/.orca_ui` to `~/.orca/ui`; a link is created pointing at the old location (macOS and Linux only, no link is created on Windows).

> After the update every hand reads as uncalibrated once, unless its board holds a calibration. Calibrate it once in *Setup → Calibrate*.

### Hand menu

Click the hand chip in the header to see which hand is connected: its id, a nickname you can set, when it was calibrated, and where its joint ranges come from. Hover the id to see the hand's folder.

### Restore previous calibration

The console keeps the calibration before the current one. *restore previous calibration* in the hand menu swaps back to it; press it again to undo. Switch torque off first.

### Hardware version for this session

The version picker in the header now applies to this session only and is never saved. A choice made for one hand stays with that hand; plugging in another hand goes back to what its board reports.

### Notice for older files

Calibration and setup files from before this version are listed once and left untouched; they are no longer used.

### Motors-holding warning

If a routine ends without confirming that every motor switched torque off, for example after a USB drop, a red banner names the motors that may still be holding. Press E-STOP or power-cycle the hand. Once the hand reconnects and every motor confirms torque off, the banner turns green.

## Bugfixes

### Stop after a USB error

Stop and Disconnect now switch torque off even after a USB error in the middle of a motor command.

### Guided tensioning scores and clicks

The score screen no longer says every joint passed when nothing was checked in that round. A joint you test again, or one that was never swept, gets the right number of clicks.

### Unchecked joints in guided tensioning

Joints that were not range-checked show *not checked* and get no clicks. A banner says when live readings stop or when torque could not be confirmed off.

### Slack test with every joint skipped

A slack test where you skipped every joint shows as nothing tested, and no longer lifts an earlier block on calibration.

### Faster first load

The console opens faster: the 3D tower preview in the Setup dialogs loads when you first open it, and tries again if loading fails.

## UI 0.5.0 — 2026-11-11
Core: 0.13.0

## Features

### Maintenance guide overlay

*Setup → Maintenance* now opens in a separate overlay, like the assembly guide. The close control and E-stop remain within reach, and you can open the assembly guide from the maintenance steps.

### Base-only assembly setup

The assembly guide now uses Base automatically, without a Base/Full selector. You can still choose the side and motor type. Saved Full or Touch choices display the Base guide for now; those choices are retained for when the other versions return.

## Bugfixes

### Assembly guide editing disabled

Guide text and background colors can no longer be edited in the assembly manual. Previously saved text and color overrides no longer change what the guide displays.

### Tendon animation and framing

The maintenance animation has smoother slack transitions and finer tendon paths. The routing camera follows the replacement tendon more closely, the anchor view has less clutter, and the animation background now matches dark mode.

### HIVE board naming

The assembly instructions, board diagrams, parts lists and motor-chain display now call the board HIVE instead of OH.

## UI 0.4.0 — 2026-11-10
Core: 0.13.0

## Features

### Assembly guide

- *Setup → Open assembly guide* walks you through building a Base or Full hand, left or right, with Dynamixel or Feetech motors, step by step with photos, videos and 3D models.

- Your choices, position and checked steps are saved, so you can close the console and carry on later. Media downloads the first time you open a step and is cached after that. Feetech builds have no 3D model yet.

### Maintenance: replacing the index AP tendon

- *Setup → Maintenance* shows an animated, step-by-step repair of the index AP tendon on a Base right Dynamixel hand.

### Slack test

- You hold one joint at a time while the motor winds each way at low current. The remaining slack is then shown in motor degrees. It also shows how many ratchet clicks are needed to remove the remaining slack.

### Tension sweep

- After calibration, the tension sweep measures how tight each tendon is by feeling how hard each motor has to work to move its joint. If the tension sweep lists no clicks that means your hand is well tensioned.

### Guided and simple tensioning

- On v2.1 hands, guided tensioning alternates ratcheting the marked spools with moving each finger through its range. You can jump back to any finger, redo a joint, and see the current each motor holds.

- v2.0 gets *Simple tensioning*: the motors hold while you ratchet.

### Manual calibration

- A new button in the *Calibrate* step: with torque off, lets you calibrate manually by holding each joint on its stops and records their positions.

### v2.1.1 hands

- Hardware versions now read v2.0.0, v2.1.0 and v2.1.1, and the version picker offers v2.1.1. A v2.1.1 hand uses its own joint ranges.

## Bugfixes

### The console no longer falls out of step with the touch sensors

### The 3D view no longer spills out of its dashboard card

### Forcing simple tensioning no longer reopens the last guided run

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
