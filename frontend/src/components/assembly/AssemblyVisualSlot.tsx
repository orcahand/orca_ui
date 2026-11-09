import { MotorRenderReference } from './MotorRenderReference'
import { MEDIA, STEPS } from './guide'
import { CAD_ILLUSTRATIONS } from './cadIllustrations'
import { photoResolution } from './photoResolution'
import { Children, createContext, useContext, useId, useRef, useState, type ReactNode } from 'react'
import type { Build, Figure } from './buildContent'
import { GuideText } from './GuideEditing'

export const VisualSlotContext = createContext(false)
export const useVisualSlot = () => useContext(VisualSlotContext)
export const isRender = (src: string) =>
  /\/(renders|parts|molds|supplies)\//.test(src) && !src.endsWith('.mp4')
type Tab = '3D model' | 'Renders' | 'Photos'
export function AssemblyVisualSlot({
  build,
  figures,
  legacyGallery,
  children,
  step,
  includeStepMedia = false,
}: {
  build: Build
  step: string
  includeStepMedia?: boolean
  figures: Figure[]
  legacyGallery?: ReactNode
  children?: ReactNode
}) {
  const hasModel = Children.toArray(children).length > 0
  const references: Figure[] =
    hasModel && includeStepMedia
      ? [
          ...(STEPS.find((s) => s.id === step)?.pages ?? [])
            .flatMap((p) => MEDIA[String(p)]?.panels ?? [])
            .filter((f) => !f.side || f.side === build.side)
            .map((f) => ({ ...f, src: photoResolution(f.src) })),
          ...CAD_ILLUSTRATIONS.filter((r) => r.step === step).map((r) => ({
            src: `./assembly/renders/base-${build.side}-dynamixel/${r.file}.webp`,
            caption: r.caption,
          })),
        ]
      : []
  const gallery = [...figures, ...references].flatMap((f) => [
    f,
    ...(f.photo ? [{ ...f.photo, instruction: f.instruction }] : []),
  ])
  const unique = gallery.filter((f, i) => gallery.findIndex((other) => other.src === f.src) === i)
  const renders = unique.filter((f) => isRender(f.src)),
    photos = unique.filter((f) => !isRender(f.src))
  const tabs: Tab[] = [
    ...(hasModel ? ['3D model' as const] : []),
    ...(renders.length ? ['Renders' as const] : []),
    ...(photos.length ? ['Photos' as const] : []),
  ]
  const [tab, setTab] = useState<Tab>(tabs[0]),
    [selected, setSelected] = useState(0),
    [enlarged, setEnlarged] = useState(false)
  const dialog = useRef<HTMLDialogElement>(null),
    id = useId(),
    active = tabs.includes(tab) ? tab : tabs[0],
    items = active === 'Renders' ? renders : photos
  if (build.version !== 'base')
    return (
      <>
        {legacyGallery}
        {children}
      </>
    )
  if (!tabs.length) return null
  function open(index: number) {
    setSelected(index)
    setEnlarged(true)
    dialog.current?.showModal()
  }
  return (
    <VisualSlotContext.Provider value={true}>
      <section className="assembly-visual-slot" aria-label="Assembly visual reference">
        <div className="assembly-visual-toolbar">
          <div
            className="assembly-clip-tabs"
            role="tablist"
            aria-label="Visual format"
            onKeyDown={(e) => {
              if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(e.key)) return
              e.preventDefault()
              const next =
                e.key === 'Home'
                  ? 0
                  : e.key === 'End'
                    ? tabs.length - 1
                    : (tabs.indexOf(active) + (e.key === 'ArrowRight' ? 1 : -1) + tabs.length) %
                      tabs.length
              setTab(tabs[next])
              document.getElementById(`${id}-${next}`)?.focus()
            }}
          >
            {tabs.map((name, i) => (
              <button
                key={name}
                id={`${id}-${i}`}
                role="tab"
                aria-selected={active === name}
                aria-controls={`${id}-panel`}
                tabIndex={active === name ? 0 : -1}
                onClick={() => setTab(name)}
              >
                {name}
              </button>
            ))}
          </div>
          {active === '3D model' && (
            <button
              className="assembly-text-button"
              onClick={() => open(0)}
              aria-label="Enlarge 3D model"
            >
              ⤢
            </button>
          )}
        </div>
        <div id={`${id}-panel`} role="tabpanel" aria-labelledby={`${id}-${tabs.indexOf(active)}`}>
          {active === '3D model' ? (
            children
          ) : (
            <div className="assembly-visual-gallery">
              {items.map((item, i) => (
                <figure key={item.src}>
                  <button
                    onClick={() => open(i)}
                    aria-label={`Enlarge ${active === 'Renders' ? 'render' : 'photo'} ${i + 1}`}
                  >
                    <MotorRenderReference build={build} src={item.src}>
                      <img src={item.src} alt={item.caption} loading="lazy" />
                    </MotorRenderReference>
                  </button>
                  {item.showCaption && /\d|CableHolder/.test(item.caption) && (
                    <figcaption>
                      <GuideText
                        field={`caption/${item.src}`}
                        text={item.caption}
                        label="Caption"
                      />
                    </figcaption>
                  )}
                </figure>
              ))}
            </div>
          )}
        </div>
        <dialog
          ref={dialog}
          className="assembly-lightbox assembly-visual-lightbox"
          aria-label={`Enlarged ${active.toLowerCase()}`}
          onClose={() => setEnlarged(false)}
          onCancel={(e) => e.stopPropagation()}
          onClick={(e) => {
            if (e.target === e.currentTarget) dialog.current?.close()
          }}
        >
          <div className="assembly-row">
            <span>{active}</span>
            <button autoFocus onClick={() => dialog.current?.close()}>
              Close ×
            </button>
          </div>
          {enlarged &&
            (active === '3D model' ? (
              children
            ) : (
              <>
                <MotorRenderReference
                  build={build}
                  src={items[Math.min(selected, items.length - 1)]?.src}
                >
                  <img
                    src={items[Math.min(selected, items.length - 1)]?.src}
                    alt={items[Math.min(selected, items.length - 1)]?.caption}
                  />
                </MotorRenderReference>
                <div className="assembly-row">
                  <button
                    disabled={items.length < 2}
                    onClick={() => setSelected((i) => (i - 1 + items.length) % items.length)}
                  >
                    ← Previous
                  </button>
                  <span>
                    {selected + 1} / {items.length}
                  </span>
                  <button
                    disabled={items.length < 2}
                    onClick={() => setSelected((i) => (i + 1) % items.length)}
                  >
                    Next →
                  </button>
                </div>
              </>
            ))}
        </dialog>
      </section>
    </VisualSlotContext.Provider>
  )
}
