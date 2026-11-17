// The tower in three.js: each motor slot is tinted by what its motor is
// doing (released, held, hot, faulted, turning), labelled with its number
// and bus id, and clickable. Live state is applied per frame from refs, so
// the 10 Hz stream never re-renders React.

import { Html, OrbitControls } from '@react-three/drei'
import { Canvas, useFrame, useThree, type ThreeEvent } from '@react-three/fiber'
import { useEffect, useMemo, useRef, useState } from 'react'
import * as THREE from 'three'
import type { OrbitControls as OrbitControlsImpl } from 'three-stdlib'
import { useAppStore } from '../../state/appStore'
import { usePalette } from '../../theme/themeStore'
import type { LatestFrames } from '../../state/streamStore'
import { useMotorLive } from '../useMotorLive'
import type { Tower } from './towerModel'

// A shaft turning faster than this glows, so a motor turned by hand shows
// where it sits on the tower.
const TURNING_DEG_S = 8
// Pointer travel (px) between down and up beyond which a click was an orbit.
const CLICK_SLOP_PX = 5

export interface TowerSceneProps {
  tower: Tower
  // Slot → bus id: the bench's numbering, or the draft while identifying.
  slots: Record<number, number>
  selected: number[]
  identifying: boolean
  armed: number | null
  confirmed: number[]
  onPick(slot: number, additive: boolean): void
}

function Fit({ tower }: { tower: Tower }) {
  const camera = useThree((s) => s.camera)
  const controls = useRef<OrbitControlsImpl>(null)
  useEffect(() => {
    const dir = new THREE.Vector3(1.1, 0.55, 1.4).normalize()
    camera.position.copy(tower.center).addScaledVector(dir, tower.size * 1.9)
    controls.current?.target.copy(tower.center)
    controls.current?.update()
  }, [camera, tower])
  return <OrbitControls ref={controls} makeDefault enablePan={false} />
}

function Slots(props: TowerSceneProps) {
  const { tower, slots, selected, identifying, armed, confirmed, onPick } = props
  const palette = usePalette()
  const held = useAppStore((s) => s.control?.held_motors)
  const live = useRef<LatestFrames['motors'] | null>(null)
  const labels = useRef<(HTMLDivElement | null)[]>([])
  const [hover, setHover] = useState<number | null>(null)
  useMotorLive((frames) => {
    live.current = frames.motors
  })

  const colors = useMemo(
    () => ({
      empty: new THREE.Color(palette.name === 'dark' ? '#3a4150' : '#c9ccd0'),
      released: new THREE.Color(palette.name === 'dark' ? '#5b6577' : '#8b929c'),
      held: new THREE.Color(palette.accent),
      warn: new THREE.Color(palette.warn),
      err: new THREE.Color(palette.err),
      ok: new THREE.Color(palette.ok),
      glow: new THREE.Color(palette.textBright),
      pick: new THREE.Color(palette.accent),
    }),
    [palette],
  )
  useEffect(() => {
    tower.frame.color.set(palette.muted)
    tower.frame.opacity = palette.name === 'dark' ? 0.35 : 0.5
  }, [tower, palette])

  const toCamera = useMemo(() => new THREE.Vector3(), [])
  useFrame(({ camera, clock }) => {
    const motors = live.current
    const maxTemp = motors?.maxTempC ?? 70
    const pulse = 0.5 + 0.5 * Math.sin(clock.elapsedTime * 6)
    tower.slots.forEach((s, i) => {
      const id = slots[s.slot]
      const key = id === undefined ? '' : String(id)
      const m = s.material
      const present = id !== undefined
      let color = colors.released
      if (!present) color = colors.empty
      else if (identifying) color = confirmed.includes(s.slot) ? colors.ok : colors.released
      else {
        const fault = motors?.faults?.motors[key]?.hw_error
        const temp = motors?.temps[key]
        if (fault || (temp !== undefined && temp >= maxTemp * 0.9)) color = colors.err
        else if (held?.includes(id)) color = colors.held
        else if (temp !== undefined && temp >= maxTemp * 0.7) color = colors.warn
      }
      m.color.copy(color)
      m.transparent = !present
      m.opacity = present ? 1 : 0.35

      const turning = present && Math.abs(motors?.velocities[key] ?? 0) > TURNING_DEG_S
      const picked = identifying ? armed === s.slot : present && selected.includes(id)
      if (turning) {
        m.emissive.copy(colors.glow)
        m.emissiveIntensity = 0.55
      } else if (picked) {
        m.emissive.copy(colors.pick)
        m.emissiveIntensity = identifying ? 0.25 + 0.45 * pulse : 0.45
      } else {
        m.emissive.copy(colors.pick)
        m.emissiveIntensity = hover === s.slot ? 0.2 : 0
      }

      const el = labels.current[i]
      if (el) {
        toCamera.copy(camera.position).sub(s.center).setY(0).normalize()
        const facing = s.outward.lengthSq() === 0 || s.outward.dot(toCamera) > -0.15
        el.style.opacity = facing || picked ? '1' : '0'
        el.dataset.picked = picked ? '1' : ''
      }
    })
  })

  const down = useRef<{ x: number; y: number } | null>(null)
  const slotOf = (e: ThreeEvent<PointerEvent | MouseEvent>) =>
    tower.slots.find((s) => s.meshes.includes(e.object as THREE.Mesh))?.slot ?? null
  return (
    <>
      <primitive
        object={tower.root}
        onPointerDown={(e: ThreeEvent<PointerEvent>) => {
          down.current = { x: e.clientX, y: e.clientY }
        }}
        onClick={(e: ThreeEvent<MouseEvent>) => {
          e.stopPropagation()
          const slot = slotOf(e)
          const d = down.current
          if (slot === null || (d && Math.hypot(e.clientX - d.x, e.clientY - d.y) > CLICK_SLOP_PX)) return
          onPick(slot, e.shiftKey || e.metaKey || e.ctrlKey)
        }}
        onPointerMove={(e: ThreeEvent<PointerEvent>) => {
          e.stopPropagation()
          const slot = slotOf(e)
          setHover((h) => (h === slot ? h : slot))
          document.body.style.cursor = slot === null ? '' : 'pointer'
        }}
        onPointerOut={() => {
          setHover(null)
          document.body.style.cursor = ''
        }}
      />
      {tower.slots.map((s, i) => (
        <Html
          key={s.slot}
          position={s.center.clone().addScaledVector(s.outward, tower.size * 0.06).toArray()}
          center
          zIndexRange={[20, 0]}
          style={{ pointerEvents: 'none' }}
        >
          <div
            ref={(el) => {
              labels.current[i] = el
            }}
            className={`tower-label ${slots[s.slot] === undefined ? 'empty' : ''}`}
          >
            <b>{s.slot}</b>
            <span>{slots[s.slot] === undefined ? '—' : `id ${slots[s.slot]}`}</span>
          </div>
        </Html>
      ))}
    </>
  )
}

export function TowerScene(props: TowerSceneProps) {
  useEffect(() => () => {
    document.body.style.cursor = ''
  }, [])
  return (
    <Canvas camera={{ fov: 30, near: 0.005, far: 10 }} dpr={[1, 2]}>
      <ambientLight intensity={1.1} />
      <directionalLight position={[0.4, 0.8, 0.6]} intensity={2.2} />
      <directionalLight position={[-0.5, 0.2, -0.6]} intensity={1.2} />
      <Fit tower={props.tower} />
      <Slots {...props} />
    </Canvas>
  )
}
