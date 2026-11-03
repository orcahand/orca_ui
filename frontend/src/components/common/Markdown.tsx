// A small Markdown renderer for documents the console ships and users edit —
// the changelog today. It builds React nodes rather than HTML, so nothing
// written into the document can inject markup.
//
// Supported: `##`–`####` headings, paragraphs, `-` and `1.` lists, `>` notes,
// **bold**, *italic*, `code`, ``` fences ``` and [links](https://example.com).
// Two lines are
// structural: an `h2` reading "<version> — <date>" is a release header, and a
// "Core: <version>" line is the core release that pairs with it.

import type { ReactNode } from 'react'

const INLINE = /(\*\*[^*]+\*\*|\*[^*\s][^*]*\*|`[^`]+`|\[[^\]]+\]\([^)\s]+\))/g
const LINK = /^\[([^\]]+)\]\(([^)\s]+)\)$/
const RELEASE = /^(?:UI\s+)?v?(\d+(?:\.\d+)*)\s*(?:[—–-]+\s*(.*))?$/i
const CORE = /^Core:\s*v?(\d+(?:\.\d+)*)$/i
const SAFE_HREF = /^(https?:\/\/|\/|mailto:)/

function inline(text: string, key: string): ReactNode[] {
  return text.split(INLINE).map((part, i) => {
    const k = `${key}i${i}`
    if (!part) return null
    if (part.startsWith('**') && part.endsWith('**'))
      return <strong key={k}>{part.slice(2, -2)}</strong>
    if (part.startsWith('`') && part.endsWith('`')) return <code key={k}>{part.slice(1, -1)}</code>
    if (part.startsWith('*') && part.endsWith('*')) return <em key={k}>{part.slice(1, -1)}</em>
    const link = LINK.exec(part)
    if (link) {
      if (!SAFE_HREF.test(link[2])) return link[1]
      return (
        <a key={k} href={link[2]} target="_blank" rel="noreferrer">
          {link[1]}
        </a>
      )
    }
    return part
  })
}

function heading(level: number, text: string, key: string): ReactNode {
  if (level === 2) {
    const release = RELEASE.exec(text.trim())
    if (release) {
      return (
        <div className="md-release" key={key}>
          <span className="md-release-label">UI</span>
          <span className="md-release-ver">{release[1]}</span>
          {release[2] ? <span className="md-release-date">{release[2]}</span> : null}
        </div>
      )
    }
    return (
      <h2 className="md-section" key={key}>
        <span className="md-section-label">{inline(text, key)}</span>
      </h2>
    )
  }
  if (level === 3) return <h3 key={key}>{inline(text, key)}</h3>
  return <h4 key={key}>{inline(text, key)}</h4>
}

type Pending = { kind: 'p' | 'ul' | 'ol' | 'quote' | 'code'; lines: string[] }

function flush(pending: Pending | null, out: ReactNode[]) {
  if (!pending || pending.lines.length === 0) return
  const key = `b${out.length}`
  if (pending.kind === 'p') {
    out.push(<p key={key}>{inline(pending.lines.join(' '), key)}</p>)
  } else if (pending.kind === 'code') {
    out.push(
      <pre key={key}>
        <code>{pending.lines.join('\n')}</code>
      </pre>,
    )
  } else if (pending.kind === 'quote') {
    out.push(<blockquote key={key}>{inline(pending.lines.join(' '), key)}</blockquote>)
  } else {
    const items = pending.lines.map((line, i) => (
      <li key={`${key}l${i}`}>{inline(line, `${key}l${i}`)}</li>
    ))
    out.push(pending.kind === 'ul' ? <ul key={key}>{items}</ul> : <ol key={key}>{items}</ol>)
  }
}

function renderMarkdown(source: string): ReactNode[] {
  const out: ReactNode[] = []
  let pending: Pending | null = null

  const open = (kind: Pending['kind']) => {
    if (pending?.kind !== kind) {
      flush(pending, out)
      pending = { kind, lines: [] }
    }
    return pending as Pending
  }

  let fenced = false
  for (const raw of source.replace(/<!--[\s\S]*?-->/g, '').split('\n')) {
    const line = raw.trimEnd()
    if (line.trimStart().startsWith('```')) {
      if (fenced) {
        flush(pending, out)
        pending = null
      } else {
        open('code')
      }
      fenced = !fenced
      continue
    }
    if (fenced) {
      open('code').lines.push(raw)
      continue
    }
    const core = CORE.exec(line.trim())
    if (core) {
      flush(pending, out)
      pending = null
      out.push(
        <div className="md-core" key={`b${out.length}`}>
          <span className="md-core-label">core</span>
          <span className="md-core-ver">{core[1]}</span>
        </div>,
      )
      continue
    }
    if (!line.trim()) {
      flush(pending, out)
      pending = null
      continue
    }
    const head = /^(#{1,6})\s+(.*)$/.exec(line)
    if (head) {
      flush(pending, out)
      pending = null
      out.push(heading(Math.min(head[1].length, 4), head[2], `b${out.length}`))
      continue
    }
    const bullet = /^\s*[-*]\s+(.*)$/.exec(line)
    if (bullet) {
      open('ul').lines.push(bullet[1])
      continue
    }
    const numbered = /^\s*\d+[.)]\s+(.*)$/.exec(line)
    if (numbered) {
      open('ol').lines.push(numbered[1])
      continue
    }
    const quote = /^\s*>\s?(.*)$/.exec(line)
    if (quote) {
      open('quote').lines.push(quote[1])
      continue
    }
    open('p').lines.push(line.trim())
  }
  flush(pending, out)
  return out
}

export function Markdown({ source, className }: { source: string; className?: string }) {
  return <div className={className ? `md ${className}` : 'md'}>{renderMarkdown(source)}</div>
}
