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

## UI 0.3.0 — 2026-10-21
Core: 0.10.1

## Features

### Automatic recovery from motor faults

### Reboot thresholds you can set per hand

### Overload and thermal recoveries counted separately

### Overheating motors stand down and come back on their own

### A cooling margin, and holding the hand off while one motor cools

### Supply and wiring faults in red on every tab

### Per-motor recovery counts in Motor health

### Rebooting one motor without disarming the hand

### Pose loops that run until you stop them

### Calibration drives at the hand's own current limit

### Per-joint calibration current recorded and compared against the last run

### This changelog, and the What's new button

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
