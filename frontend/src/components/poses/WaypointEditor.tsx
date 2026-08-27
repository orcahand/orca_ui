// Waypoint sequence editor: a modal with the 3D hand posed at the selected
// step and one ROM-bounded slider per joint. Steps can be edited, duplicated,
// reordered and deleted; Save overwrites the recording (or writes a copy
// under a new name) so sequences can be adapted after recording. Purely
// offline — nothing here commands the physical hand.
//
// Lazy-loaded from TrajectoryPanel so three.js stays out of the shell bundle.

import { useEffect, useMemo, useState } from 'react'
import { Canvas, useThree } from '@react-three/fiber'
import { OrbitControls } from '@react-three/drei'
import * as THREE from 'three'
import type { URDFRobot } from 'urdf-loader'
import { api } from '../../api/rest'
import {
  LIBRARY_NAME_RE,
  type JointInfo,
  type ModelMetadata,
} from '../../api/types'
import { useAppStore } from '../../state/appStore'
import { JointPoseAdapter } from '../three/JointPoseAdapter'
import { loadHandRobot } from '../three/loadHandRobot'

interface EditorJoint {
  id: string
  rom: [number, number]
}

function PosedRobot({
  robot,
  joints,
  angles,
}: {
  robot: URDFRobot
  joints: JointInfo[]
  angles: Record<string, number>
}) {
  const invalidate = useThree((s) => s.invalidate)
  const adapter = useMemo(
    () => new JointPoseAdapter(robot, joints),
    [robot, joints],
  )
  useEffect(() => {
    adapter.apply(angles)
    invalidate()
  }, [adapter, angles, invalidate])
  return <primitive object={robot} />
}

export function WaypointEditor({
  name,
  onClose,
  onSaved,
}: {
  name: string
  onClose(): void
  onSaved(savedAs: string): void
}) {
  const handInfo = useAppStore((s) => s.handInfo)
  const [jointIds, setJointIds] = useState<string[]>([])
  const [waypoints, setWaypoints] = useState<number[][] | null>(null)
  const [step, setStep] = useState(0)
  const [robot, setRobot] = useState<URDFRobot | null>(null)
  const [saveName, setSaveName] = useState(name)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [dirty, setDirty] = useState(false)

  // Load the recording and the 3D model bundle.
  useEffect(() => {
    let cancelled = false
    Promise.all([api.trajectoryGet(name), api.modelMetadata()])
      .then(async ([data, metadata]: [Awaited<ReturnType<typeof api.trajectoryGet>>, ModelMetadata]) => {
        if (cancelled) return
        if (!data.waypoints) {
          setError('only waypoint recordings are editable')
          return
        }
        setJointIds(data.metadata.joint_ids ?? [])
        setWaypoints(data.waypoints.map((row) => [...row]))
        const loaded = await loadHandRobot(metadata.urdf_url)
        if (!cancelled) setRobot(loaded)
      })
      .catch((e) => {
        if (!cancelled) setError(String((e as Error).message ?? e))
      })
    return () => {
      cancelled = true
    }
  }, [name])

  // Escape closes (the browser back-of-mind default for modals).
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  const editorJoints: EditorJoint[] = useMemo(() => {
    const roms = new Map(
      (handInfo?.joints ?? []).map((j) => [j.id, j.rom] as const),
    )
    return jointIds.map((id) => ({
      id,
      rom: roms.get(id) ?? [-90, 90],
    }))
  }, [jointIds, handInfo])

  const current = waypoints?.[step] ?? null
  const angles = useMemo(() => {
    if (!current) return {}
    return Object.fromEntries(jointIds.map((id, i) => [id, current[i]]))
  }, [current, jointIds])

  // Camera framing from the model bounds, computed once per robot.
  const framing = useMemo(() => {
    if (!robot) return null
    const box = new THREE.Box3().setFromObject(robot)
    const sphere = box.getBoundingSphere(new THREE.Sphere())
    const distance = sphere.radius * 2.8
    return {
      target: sphere.center,
      position: new THREE.Vector3(
        sphere.center.x + distance * 0.65,
        sphere.center.y + distance * 0.55,
        sphere.center.z + distance * 0.65,
      ),
      near: distance / 100,
      far: distance * 50,
    }
  }, [robot])

  const setJoint = (index: number, value: number) => {
    setWaypoints((prev) => {
      if (!prev) return prev
      const next = prev.map((row) => [...row])
      next[step][index] = value
      return next
    })
    setDirty(true)
  }

  const duplicateStep = () => {
    setWaypoints((prev) => {
      if (!prev) return prev
      const next = prev.map((row) => [...row])
      next.splice(step + 1, 0, [...next[step]])
      return next
    })
    setStep((s) => s + 1)
    setDirty(true)
  }

  const deleteStep = () => {
    setWaypoints((prev) => {
      if (!prev || prev.length <= 1) return prev
      const next = prev.map((row) => [...row])
      next.splice(step, 1)
      return next
    })
    setStep((s) => Math.max(0, Math.min(s, (waypoints?.length ?? 2) - 2)))
    setDirty(true)
  }

  const moveStep = (delta: number) => {
    setWaypoints((prev) => {
      if (!prev) return prev
      const target = step + delta
      if (target < 0 || target >= prev.length) return prev
      const next = prev.map((row) => [...row])
      const [row] = next.splice(step, 1)
      next.splice(target, 0, row)
      return next
    })
    setStep((s) => {
      const target = s + delta
      return target < 0 || target >= (waypoints?.length ?? 0) ? s : target
    })
    setDirty(true)
  }

  const nameValid = LIBRARY_NAME_RE.test(saveName)
  const save = () => {
    if (!waypoints || !nameValid) return
    setBusy(true)
    void api
      .trajectoryUpdate(
        name,
        waypoints,
        saveName !== name ? saveName : undefined,
      )
      .then((r) => onSaved(r.name))
      .catch((e) => setError(String((e as Error).message ?? e)))
      .finally(() => setBusy(false))
  }

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 100,
        background: 'rgb(0 0 0 / 0.55)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: 20,
      }}
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div
        style={{
          background: 'var(--bg)',
          border: '1px solid rgb(var(--accent-rgb) / 0.35)',
          boxShadow: '0 12px 40px var(--pop-shadow-color)',
          width: 'min(1040px, 100%)',
          maxHeight: 'calc(100vh - 40px)',
          display: 'flex',
          flexDirection: 'column',
          padding: 14,
          gap: 10,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 10 }}>
          <span style={{ fontWeight: 700 }}>edit waypoints · {name}</span>
          <span style={{ fontSize: 10, color: 'var(--dim)' }}>
            pose each step with the sliders — nothing moves the real hand
            until you replay it
          </span>
          <button
            className="btn btn-secondary"
            style={{ marginLeft: 'auto' }}
            onClick={onClose}
          >
            ✕ close
          </button>
        </div>

        {error && (
          <div style={{ color: 'var(--err)', fontSize: 11 }}>{error}</div>
        )}

        {!waypoints || !current ? (
          <div className="detecting-card">
            <div className="big">LOADING</div>
            <div>fetching recording…</div>
          </div>
        ) : (
          <>
            <div
              style={{
                display: 'flex',
                gap: 4,
                flexWrap: 'wrap',
                alignItems: 'center',
              }}
            >
              <span style={{ fontSize: 10, color: 'var(--dim)' }}>steps</span>
              {waypoints.map((_, i) => (
                <button
                  key={i}
                  className={`view-tab ${i === step ? 'active' : ''}`}
                  onClick={() => setStep(i)}
                >
                  {i + 1}
                </button>
              ))}
              <span style={{ display: 'inline-flex', gap: 4, marginLeft: 8 }}>
                <button
                  className="btn btn-secondary"
                  title="move this step earlier"
                  disabled={step === 0}
                  onClick={() => moveStep(-1)}
                >
                  ◀
                </button>
                <button
                  className="btn btn-secondary"
                  title="move this step later"
                  disabled={step >= waypoints.length - 1}
                  onClick={() => moveStep(1)}
                >
                  ▶
                </button>
                <button
                  className="btn btn-secondary"
                  title="duplicate this step after itself"
                  onClick={duplicateStep}
                >
                  ⧉ duplicate
                </button>
                <button
                  className="btn btn-danger"
                  title="delete this step"
                  disabled={waypoints.length <= 1}
                  onClick={deleteStep}
                >
                  🗑
                </button>
              </span>
            </div>

            <div
              style={{
                display: 'grid',
                gridTemplateColumns: 'minmax(0, 1fr) 360px',
                gap: 12,
                minHeight: 0,
                flex: 1,
              }}
            >
              <div
                style={{
                  minHeight: 380,
                  border: '1px solid var(--panel-border)',
                  background: 'var(--panel)',
                }}
              >
                {robot && framing ? (
                  <Canvas
                    frameloop="demand"
                    camera={{
                      fov: 40,
                      position: framing.position.toArray(),
                      near: framing.near,
                      far: framing.far,
                    }}
                  >
                    <ambientLight intensity={0.8} />
                    <directionalLight position={[1, 2, 1]} intensity={1.4} />
                    <directionalLight
                      position={[-1, 1, -1]}
                      intensity={0.6}
                    />
                    <PosedRobot
                      robot={robot}
                      joints={handInfo?.joints ?? []}
                      angles={angles}
                    />
                    <OrbitControls
                      makeDefault
                      target={framing.target.toArray()}
                    />
                  </Canvas>
                ) : (
                  <div className="detecting-card">
                    <div className="big">LOADING</div>
                    <div>loading 3D model…</div>
                  </div>
                )}
              </div>

              <div style={{ overflowY: 'auto', paddingRight: 4 }}>
                {editorJoints.map((joint, index) => (
                  <div
                    key={joint.id}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 6,
                      padding: '2px 0',
                      fontSize: 10,
                    }}
                  >
                    <span
                      style={{
                        width: 86,
                        textAlign: 'right',
                        color: 'var(--text)',
                      }}
                    >
                      {joint.id}
                    </span>
                    <input
                      type="range"
                      min={joint.rom[0]}
                      max={joint.rom[1]}
                      step={0.5}
                      value={current[index]}
                      onChange={(e) =>
                        setJoint(index, parseFloat(e.target.value))
                      }
                      style={{ flex: 1, height: 3 }}
                    />
                    <input
                      type="number"
                      value={Number(current[index].toFixed(1))}
                      min={joint.rom[0]}
                      max={joint.rom[1]}
                      step={0.5}
                      onChange={(e) => {
                        const v = parseFloat(e.target.value)
                        if (Number.isFinite(v)) {
                          setJoint(
                            index,
                            Math.min(
                              joint.rom[1],
                              Math.max(joint.rom[0], v),
                            ),
                          )
                        }
                      }}
                      style={{ width: 62 }}
                    />
                  </div>
                ))}
              </div>
            </div>

            <div
              style={{
                display: 'flex',
                gap: 8,
                alignItems: 'center',
                borderTop: '1px solid var(--panel-border)',
                paddingTop: 10,
              }}
            >
              <span style={{ fontSize: 10, color: 'var(--dim)' }}>
                save as
              </span>
              <input
                className="record-name"
                type="text"
                value={saveName}
                onChange={(e) => setSaveName(e.target.value)}
                style={{ width: 220 }}
              />
              <button
                className="btn btn-primary"
                disabled={busy || !nameValid || (!dirty && saveName === name)}
                title={
                  !nameValid
                    ? 'letters, digits, _ and - only (max 64)'
                    : saveName !== name
                      ? `save a copy as ${saveName}`
                      : 'overwrite the recording'
                }
                onClick={save}
              >
                {saveName !== name ? '⧉ Save copy' : '💾 Save'}
              </button>
              {dirty && (
                <span style={{ fontSize: 10, color: 'var(--warn)' }}>
                  unsaved changes
                </span>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  )
}
