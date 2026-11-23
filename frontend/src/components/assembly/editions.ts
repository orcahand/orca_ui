// Hidden guide editions and tools. All are switched off for builders; set one to
// true and rebuild the frontend to bring it back. Saved progress keeps the
// hidden choices, so a build restored with a flag on resumes where it was.
import type { Build } from './buildContent'

// The Version picker with the Touch and Full builds. Off: all saved versions use Base.
export const SHOW_TOUCH_AND_FULL = false

// The Internal/External edition picker and the flashing chapters (ORCA Console
// or orca_firmware terminal). Off: every build is shown as External.
export const SHOW_INTERNAL_EDITION = false

// Text and background editing for reviewing the guide's wording; exports the edits as JSON.
export const SHOW_GUIDE_EDITOR = false

export function editionBuild(build: Build): Build {
  return {
    ...build,
    version: SHOW_TOUCH_AND_FULL ? build.version : 'base',
    audience: SHOW_INTERNAL_EDITION ? build.audience : 'external',
  }
}
