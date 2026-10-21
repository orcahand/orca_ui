// Which Setup page is shown. "ccc" is the page as it was committed: fraction
// scoring, no probes or baselines in the tensioning tool. "kai" carries the
// newer tooling: slack scoring, tension probes, travel baselines, click
// counts. Both share the manual-calibration Back option and fault handling.
// The choice is remembered per browser.

import { create } from 'zustand'

export type SetupVariant = 'ccc' | 'kai'

const KEY = 'orca.setup.variant'

// The kai page is retired: the one Setup page is the ccc one.
function load(): SetupVariant {
  return 'ccc'
}

interface SetupVariantState {
  variant: SetupVariant
  setVariant: (variant: SetupVariant) => void
}

export const useSetupVariant = create<SetupVariantState>((set) => ({
  variant: load(),
  setVariant: (variant) => {
    try {
      localStorage.setItem(KEY, variant)
    } catch {
      /* storage unavailable: the choice lasts this page load */
    }
    set({ variant })
  },
}))
