import { useEffect, useRef, useState } from 'react'
import * as THREE from 'three'
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js'
import { mediaImage } from './media'
import { loadBundle } from './cadAssets'
import { createRepairScene } from './upkeepScene'
import { REPAIR_DURATIONS, REPAIR_POSES, repairCue, repairLesson } from './upkeepTimeline'
import { KNOT_CUES } from './knotSteps'
import { KnotReinforcement } from './TendonPreparation'
import { UPKEEP_STEPS } from './upkeepSteps'

export function UpkeepAnimation({
  selected,
  onSelect,
  active,
}: {
  selected: number
  onSelect: (step: number) => void
  active: boolean
}) {
  const host = useRef<HTMLDivElement>(null)
  const draw = useRef<((step: number, position: number) => void) | null>(null)
  const [enabled, setEnabled] = useState(false),
    [ready, setReady] = useState(false),
    [failed, setFailed] = useState(false)
  const [playing, setPlaying] = useState(false),
    [position, setPosition] = useState(REPAIR_POSES[selected]),
    [attempt, setAttempt] = useState(0)
  const [speed, setSpeed] = useState(1)
  const seek = useRef<number | null>(null),
    chapterPreview = useRef(true)
  const current = useRef({ selected, position })
  current.current = { selected, position }
  const select = useRef(onSelect)
  select.current = onSelect
  useEffect(() => {
    setPosition(seek.current ?? 0)
    seek.current = null
  }, [selected])
  useEffect(() => {
    if (!active) setPlaying(false)
  }, [active])
  useEffect(() => {
    const pause = () => {
      if (document.hidden) setPlaying(false)
    }
    document.addEventListener('visibilitychange', pause)
    const reduce = matchMedia('(prefers-reduced-motion: reduce)')
    const stop = () => setPlaying(false)
    reduce.addEventListener('change', stop)
    const observer = new IntersectionObserver((entries) => {
      if (!entries[0].isIntersecting) setPlaying(false)
    })
    if (host.current) observer.observe(host.current)
    return () => {
      document.removeEventListener('visibilitychange', pause)
      reduce.removeEventListener('change', stop)
      observer.disconnect()
    }
  }, [])
  useEffect(() => {
    if (!enabled) return
    let cancelled = false,
      cleanup = () => {}
    setReady(false)
    setFailed(false)
    loadBundle('base-right-dynamixel')
      .then((bundle) => {
        if (cancelled) return
        const element = host.current!
        let renderer: THREE.WebGLRenderer
        try {
          renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true })
        } catch {
          setFailed(true)
          return
        }
        renderer.setPixelRatio(Math.min(devicePixelRatio, 2))
        renderer.setClearColor(0, 0)
        renderer.toneMapping = THREE.ACESFilmicToneMapping
        renderer.toneMappingExposure = 1.15
        renderer.domElement.setAttribute('aria-label', 'Animated Base right index finger repair')
        renderer.domElement.setAttribute('role', 'img')
        element.appendChild(renderer.domElement)
        const scene = new THREE.Scene(),
          camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0.01, 10000)
        const pmrem = new THREE.PMREMGenerator(renderer),
          room = new RoomEnvironment(),
          environment = pmrem.fromScene(room, 0.04)
        scene.environment = environment.texture
        scene.environmentIntensity = 0.8
        scene.add(new THREE.HemisphereLight('#ffffff', '#6a7470', 1.4))
        const key = new THREE.DirectionalLight('#fff8ec', 2.5),
          fill = new THREE.DirectionalLight('#ddeeff', 1.4)
        scene.add(key, key.target, fill, fill.target)
        const model = createRepairScene(bundle)
        scene.add(model.group)
        const callouts = document.createElement('div')
        callouts.className = 'upkeep-callouts'
        element.appendChild(callouts)
        const lose = (event: Event) => {
          event.preventDefault()
          setFailed(true)
          setReady(false)
          setPlaying(false)
        }
        renderer.domElement.addEventListener('webglcontextlost', lose)
        draw.current = (step, progress) => {
          const lesson = repairLesson(step, progress),
            m = model
          const narrow = element.clientWidth < 580
          const w = element.clientWidth * (lesson && !narrow ? 0.52 : 1),
            h = element.clientHeight * (lesson && narrow ? 0.5 : 1)
          if (!w || !h) return
          m.setStage(step, progress)
          const bounds = m.focus
          const center = bounds.getCenter(new THREE.Vector3()),
            distance = bounds.getSize(new THREE.Vector3()).length() * 4
          camera.up.copy(m.up)
          camera.position.copy(center).addScaledVector(m.direction.clone().normalize(), distance)
          camera.lookAt(center)
          camera.updateMatrixWorld(true)
          const projected = new THREE.Box3()
          for (const x of [bounds.min.x, bounds.max.x])
            for (const y of [bounds.min.y, bounds.max.y])
              for (const z of [bounds.min.z, bounds.max.z])
                projected.expandByPoint(
                  new THREE.Vector3(x, y, z).applyMatrix4(camera.matrixWorldInverse),
                )
          const size = projected.getSize(new THREE.Vector3()),
            middle = projected.getCenter(new THREE.Vector3()),
            half = Math.max(size.y / 2, size.x / 2 / (w / h)) * 1.12
          camera.top = middle.y + half
          camera.bottom = middle.y - half
          camera.left = middle.x - (half * w) / h
          camera.right = middle.x + (half * w) / h
          camera.updateProjectionMatrix()
          key.position.copy(camera.position).addScaledVector(m.up, distance)
          key.target.position.copy(center)
          fill.position.copy(camera.position).add(new THREE.Vector3(-distance, 0, 0))
          fill.target.position.copy(center)
          renderer.domElement.style.width = `${w}px`
          renderer.domElement.style.height = `${h}px`
          renderer.setSize(w, h, false)
          renderer.render(scene, camera)
          callouts.replaceChildren(
            ...(lesson ? [] : m.labels).map((label) => {
              const p = label.point.clone().project(camera),
                el = document.createElement('span')
              el.textContent = label.text
              el.style.left = `${Math.max(8, Math.min(w - 145, ((p.x + 1) * w) / 2 + 12))}px`
              el.style.top = `${Math.max(8, Math.min(h - 25, ((1 - p.y) * h) / 2))}px`
              return el
            }),
          )
        }
        const paint = () => draw.current?.(current.current.selected, current.current.position)
        const resize = new ResizeObserver(paint)
        resize.observe(element)
        cleanup = () => {
          draw.current = null
          resize.disconnect()
          model.dispose()
          callouts.remove()
          renderer.domElement.removeEventListener('webglcontextlost', lose)
          renderer.dispose()
          environment.dispose()
          pmrem.dispose()
          room.dispose()
          renderer.domElement.remove()
        }
        try {
          paint()
          setReady(true)
        } catch {
          cleanup()
          setFailed(true)
        }
      })
      .catch(() => {
        if (!cancelled) setFailed(true)
      })
    return () => {
      cancelled = true
      cleanup()
    }
  }, [enabled, attempt])
  useEffect(() => {
    if (!ready || failed) return
    try {
      draw.current?.(selected, position)
    } catch {
      setPlaying(false)
      setFailed(true)
    }
  }, [selected, position, ready, failed])
  useEffect(() => {
    if (!playing || !ready || failed || !active) return
    let frame = 0,
      last = performance.now(),
      elapsed = 0
    const tick = (now: number) => {
      elapsed += Math.min((now - last) / 1000, 0.1)
      last = now
      if (elapsed >= 1 / 30) {
        const value =
          current.current.position + (elapsed * speed) / REPAIR_DURATIONS[current.current.selected]
        elapsed = 0
        if (value >= 1) {
          if (current.current.selected === UPKEEP_STEPS.length - 1) {
            setPosition(1)
            setPlaying(false)
            return
          }
          setPosition(0)
          select.current(current.current.selected + 1)
        } else setPosition(value)
      }
      frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [playing, ready, failed, active, speed])
  const step = UPKEEP_STEPS[selected]
  const lesson = enabled && ready ? repairLesson(selected, position) : null
  const cue =
    lesson?.kind === 'ashley'
      ? KNOT_CUES[lesson.frame]
      : lesson?.kind === 'reinforce'
        ? [
            'Pull the Ashley stopper tight.',
            'Tie one single knot around the stopper, on top.',
            'Pull snug to make one compact anchor.',
          ][lesson.frame]
        : repairCue(selected, position)
  function showStep(index: number) {
    setPlaying(false)
    chapterPreview.current = true
    if (index !== selected) seek.current = REPAIR_POSES[index]
    onSelect(index)
    setPosition(REPAIR_POSES[index])
  }
  return (
    <section className="upkeep-player" aria-label="Repair animation">
      <div ref={host} className={`upkeep-stage ${lesson ? 'has-lesson' : ''}`}>
        {(!ready || failed) && (
          <img {...mediaImage(`./assembly/upkeep/step-${selected + 1}.png`)} alt={step.example} />
        )}
        {lesson && (
          <div className="upkeep-knot-lesson">
            {lesson.kind === 'ashley' ? (
              <>
                <span>Ashley stopper</span>
                <img
                  {...mediaImage(`./assembly/media/ashley-${lesson.frame + 1}.jpg`)}
                  alt={KNOT_CUES[lesson.frame]}
                />
              </>
            ) : (
              <>
                <span>Reinforcing knot</span>
                <KnotReinforcement count={1} phase={lesson.frame} labelsOnly />
              </>
            )}
          </div>
        )}
      </div>
      {enabled && !ready && !failed && <p role="status">Loading the model…</p>}
      <div className="upkeep-player-caption" aria-live={playing ? 'off' : 'polite'}>
        <span>STEP {selected + 1} / 9</span>
        <h3>{step.title}</h3>
        <p className="upkeep-current-cue">{enabled && ready ? cue : step.instruction}</p>
        <details>
          <summary>Full step instructions</summary>
          {enabled && ready && <p>{step.instruction}</p>}
          <p>{step.detail}</p>
        </details>
      </div>
      {failed && (
        <p role="alert">
          The animation could not load. You can download the illustrated PDF above.{' '}
          <button
            className="assembly-text-button"
            onClick={() => {
              setPlaying(false)
              setAttempt((a) => a + 1)
            }}
          >
            Retry animation
          </button>
        </p>
      )}
      <div className="upkeep-controls">
        {!enabled ? (
          <button
            className="assembly-primary"
            onClick={() => {
              setEnabled(true)
              setPosition(0)
              chapterPreview.current = false
              setPlaying(!matchMedia('(prefers-reduced-motion: reduce)').matches)
            }}
          >
            Watch the repair
          </button>
        ) : (
          <>
            <button
              className="assembly-primary"
              disabled={!ready || failed}
              onClick={() => {
                if (chapterPreview.current) setPosition(0)
                else if (selected === 8 && position === 1) {
                  onSelect(0)
                  setPosition(0)
                }
                chapterPreview.current = false
                setPlaying((p) => !p)
              }}
            >
              {playing
                ? 'Pause'
                : selected === 8 && position === 1 && !chapterPreview.current
                  ? 'Replay'
                  : 'Play'}
            </button>
            <button
              className="assembly-secondary"
              disabled={!ready || failed}
              onClick={() => {
                onSelect(0)
                setPosition(0)
                chapterPreview.current = false
                setPlaying(true)
              }}
            >
              Play from start
            </button>
          </>
        )}
        <button
          className="assembly-secondary"
          disabled={selected === 0}
          onClick={() => {
            showStep(selected - 1)
          }}
        >
          ← Previous
        </button>
        <button
          className="assembly-secondary"
          disabled={selected === 8}
          onClick={() => {
            showStep(selected + 1)
          }}
        >
          Next →
        </button>
        <label className="upkeep-speed">
          Speed{' '}
          <select
            aria-label="Playback speed"
            value={speed}
            onChange={(event) => setSpeed(Number(event.target.value))}
          >
            <option value="0.5">½×</option>
            <option value="1">1×</option>
            <option value="2">2×</option>
          </select>
        </label>
      </div>
      <label className="upkeep-scrub">
        Animation progress
        <input
          aria-label="Animation progress"
          type="range"
          min="0"
          max="9"
          step="0.01"
          value={selected + position}
          disabled={!ready || failed}
          onChange={(e) => {
            const value = Number(e.target.value),
              step = Math.min(8, Math.floor(value)),
              progress = value === 9 ? 1 : value % 1
            setPlaying(false)
            chapterPreview.current = false
            if (step !== selected) seek.current = progress
            onSelect(step)
            setPosition(progress)
          }}
        />
      </label>
      <nav className="upkeep-chapters" aria-label="Repair steps">
        {UPKEEP_STEPS.map((item, index) => (
          <button
            key={item.id}
            className={index === selected ? 'is-selected' : ''}
            aria-current={index === selected ? 'step' : undefined}
            onClick={() => showStep(index)}
          >
            <span>{String(index + 1).padStart(2, '0')}</span>
            {item.title}
          </button>
        ))}
      </nav>
    </section>
  )
}
