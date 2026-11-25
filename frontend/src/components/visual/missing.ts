// A rig dependency this Python lacks (the backend's 503 with X-Orca-Missing: OpenCV, torch, ...):
// kept once for the page to say prominently, however many requests run into it.

import { create } from "zustand";

export const MISSING_HEADER = "X-Orca-Missing";

export interface Missing {
  module: string;
  message: string; // the backend's detail: what is missing and how to get it
}

export const useRigMissing = create<{ missing: Missing | null }>(() => ({ missing: null }));

/** The response's missing module, if it names one; kept (the first only) for the page. */
export function noteMissing(response: Response, message: string): string | null {
  const module = response.headers.get(MISSING_HEADER);
  if (module && !useRigMissing.getState().missing) useRigMissing.setState({ missing: { module, message } });
  return module;
}
