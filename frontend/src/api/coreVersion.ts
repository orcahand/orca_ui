// Which orca_core release a console feature needs, and whether the one running
// is older.
//
// The version range in pyproject.toml is deliberately wide, so a console can
// find itself talking to a core that predates a feature it offers. The symptom
// is always the same: the console asks, gets nothing back, and shows an empty
// control — indistinguishable from hardware that genuinely has nothing to show.
// Naming the version is the only way to tell those apart.

import type { CoreSourceInfo } from './types'

/** First release whose clients declare their editable configuration registers. */
export const CORE_WITH_CONFIG_REGISTERS = '0.5.3'

/** First release that reports which bus rates a port's transport can carry. */
export const CORE_WITH_TRANSPORT_BAUDS = '0.5.3'

/** True when `version` is a release earlier than `wanted`. */
export function isOlderRelease(version: string, wanted: string): boolean {
  const parse = (v: string) =>
    v.split('.').map((c) => Number.parseInt(c, 10) || 0)
  const a = parse(version)
  const b = parse(wanted)
  for (let i = 0; i < Math.max(a.length, b.length); i += 1) {
    if ((a[i] ?? 0) !== (b[i] ?? 0)) return (a[i] ?? 0) < (b[i] ?? 0)
  }
  return false
}

/** True when a missing feature is explained by the core being too old.
 *
 * A development checkout carries whatever version it was cut from, so its
 * number says nothing about what it contains: never blame it.
 */
export function corePredates(
  core: CoreSourceInfo | null | undefined,
  wanted: string,
): boolean {
  return core != null && !core.development && isOlderRelease(core.version, wanted)
}

/** What to tell an operator whose core is too old for a feature. */
export function updateHint(): string {
  return 'git pull && uv sync'
}
