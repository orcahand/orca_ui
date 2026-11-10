// Small components shared by the Tests tab: status chips and copy-to-clipboard path rows.

import { useState } from 'react'
import type { HwStepKind, HwStepStatus } from '../../api/hardwareTests'
import { KIND_LABEL, STATUS_LABEL } from './hwFormat'

export function StatusChip({ status, muted }: { status: HwStepStatus; muted?: boolean }) {
  return (
    <span className={`hwt-chip hwt-status-${status}${muted ? ' hwt-chip-muted' : ''}`}>
      {STATUS_LABEL[status] ?? status}
    </span>
  )
}

export function KindChip({ kind }: { kind: HwStepKind }) {
  return <span className={`hwt-chip hwt-kind hwt-kind-${kind}`}>{KIND_LABEL[kind] ?? kind}</span>
}

// A path the tester hands to a coding agent, with a copy button.
export function CopyPath({ label, path }: { label: string; path: string }) {
  const [state, setState] = useState<'idle' | 'copied' | 'failed'>('idle')
  const copy = () => {
    navigator.clipboard
      .writeText(path)
      .then(() => setState('copied'))
      .catch(() => setState('failed'))
      .finally(() => window.setTimeout(() => setState('idle'), 1500))
  }
  return (
    <div className="hwt-path">
      <span className="hwt-path-label">{label}</span>
      <code className="hwt-path-text" title={path}>
        {path}
      </code>
      <button className="btn btn-secondary hwt-no-shot" onClick={copy}>
        {state === 'copied' ? 'copied' : state === 'failed' ? 'select & copy' : 'copy'}
      </button>
    </div>
  )
}
