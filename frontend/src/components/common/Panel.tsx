import type { ReactNode } from 'react'

export function Panel({
  title,
  toolbar,
  children,
}: {
  title: string
  toolbar?: ReactNode
  children: ReactNode
}) {
  return (
    <section className="panel">
      <div className="panel-header">
        <h2>{title}</h2>
        {toolbar}
      </div>
      {children}
    </section>
  )
}
