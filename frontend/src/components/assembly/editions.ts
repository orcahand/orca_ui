// Hidden guide editions. Both are switched off for builders; set one to true
// and rebuild the frontend to bring that content back. Saved progress keeps the
// hidden choices, so a build restored with a flag on resumes where it was.
import type { Build } from './buildContent'

// The Touch version in the Version picker, with its sensor, skin and
// connector-board chapters. Off: a saved Touch build is shown as Base.
export const SHOW_TOUCH = false

// The Internal/External edition picker and the flashing chapters (ORCA Console
// or orca_firmware terminal). Off: every build is shown as External.
export const SHOW_INTERNAL_EDITION = false

export function editionBuild(build: Build): Build {
  return {
    ...build,
    version: !SHOW_TOUCH && build.version === 'touch' ? 'base' : build.version,
    audience: SHOW_INTERNAL_EDITION ? build.audience : 'external',
  }
}
