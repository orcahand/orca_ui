import { useEffect, useMemo, useState } from 'react'
import { Canvas } from '@react-three/fiber'
import { OrbitControls } from '@react-three/drei'
import * as THREE from 'three'
import { loadBundle, type Bundle } from './cadAssets'
import { cadPieces, disposePieces, framed, nearest } from './cadScene'
import { anchorStopper } from './anchorStopper'
import type { Build } from './buildContent'

function FingerKit({
  bundle,
  build,
  finger,
  amount,
}: {
  bundle: Bundle
  build: Build
  finger: string
  amount: number
}) {
  const scene = useMemo(() => {
    const pieces = cadPieces(bundle, build),
      group = new THREE.Group()
    const bodies = pieces.filter((p) =>
      /^(Index|Middle|Ring|Pinky|Thumb) (DP|PP|AP|TP)$/.test(p.part.label),
    )
    const names = ['DP', 'PP', 'AP'].map((part) => `${finger} ${part}`)
    const selected = pieces.filter(
      (p) =>
        names.includes(p.part.label) ||
        (['Skins', 'Standard components'].includes(p.part.category) &&
          names.includes(p.owner ?? nearest(bodies, p.center)?.part.label ?? '')),
    )
    const bounds = new THREE.Box3()
    selected.forEach((p) => bounds.union(p.bounds))
    const center = bounds.getCenter(new THREE.Vector3())
    const segments = names.map((name) => bodies.find((p) => p.part.label === name)!)
    const vertical = new THREE.Vector3(0, 1, 0)
    const segmentOffsets = [
      vertical.clone().multiplyScalar(65),
      new THREE.Vector3(),
      vertical.clone().multiplyScalar(-65),
    ]
    const offsets = selected.map((p) => {
      const owner =
        p.owner ??
        (names.includes(p.part.label) ? p.part.label : nearest(segments, p.center).part.label)
      const segment = Math.max(0, names.indexOf(owner)),
        body = segments[segment]
      const shift = segmentOffsets[segment].clone()
      if (p.part.category === 'Standard components') {
        const axis = p.axis.clone()
        if (axis.dot(p.center.clone().sub(body.center)) < 0) axis.negate()
        shift.addScaledVector(axis, 18)
      } else if (p.part.category === 'Skins') {
        // Stack skins along the finger, keeping DP above its body and PP before AP.
        const target = body.center.clone().add(segmentOffsets[segment])
        target.y =
          segment === 0
            ? body.bounds.max.y + segmentOffsets[segment].y + 24
            : body.bounds.min.y + segmentOffsets[segment].y - 24
        shift.copy(target.sub(p.center))
      }
      p.object.position.copy(shift)
      group.add(p.object)
      return shift
    })
    const cords = new THREE.Group(),
      extras: { dispose: () => void }[] = []
    for (let i = 0; i < 4; i++) {
      const points = Array.from({ length: 241 }, (_, n) => {
        const t = (n / 240) * Math.PI * 4
        return new THREE.Vector3(Math.cos(t) * 10, Math.sin(t) * 10, t * 0.24)
      })
      const geometry = new THREE.TubeGeometry(
          new THREE.CatmullRomCurve3(points),
          240,
          0.3,
          8,
          false,
        ),
        material = new THREE.MeshStandardMaterial({ color: i < 2 ? '#408f97' : '#d8ad53' })
      const cord = new THREE.Group()
      cord.add(new THREE.Mesh(geometry, material))
      cord.position
        .copy(center)
        .add(new THREE.Vector3(50 + (i % 2) * 28, 65 - Math.floor(i / 2) * 65, 0))
      cord.rotation.y = 0.4
      cords.add(cord)
      extras.push({
        dispose: () => {
          geometry.dispose()
          material.dispose()
        },
      })
      if (i < 2)
        for (const x of [-5, 5]) {
          const knot = anchorStopper(0.6, 1)
          knot.group.position.set(x, -10, 2)
          cord.add(knot.group)
          extras.push(knot)
        }
    }
    group.add(cords)
    const view = framed(group, build, 350, 600)
    return {
      view,
      update: (t: number) => {
        selected.forEach((p, i) => p.object.position.copy(offsets[i]).multiplyScalar(t))
        cords.visible = t > 0.05
        cords.scale.setScalar(Math.max(0.001, t))
      },
      dispose: () => {
        disposePieces(pieces)
        extras.forEach((x) => x.dispose())
      },
    }
  }, [bundle, build, finger])
  useEffect(() => {
    scene.update(amount)
  }, [scene, amount])
  useEffect(() => () => scene.dispose(), [scene])
  return <primitive object={scene.view} />
}
export function FingerPreparation({
  build,
  otherFingers = false,
}: {
  build: Build
  otherFingers?: boolean
}) {
  const [finger, setFinger] = useState(otherFingers ? 'Middle' : 'Index'),
    [amount, setAmount] = useState(1),
    [bundle, setBundle] = useState<Bundle | null>(null),
    [error, setError] = useState(false)
  const key = `base-${build.side}-dynamixel`
  useEffect(() => {
    let live = true
    setBundle(null)
    setError(false)
    loadBundle(key)
      .then((b) => {
        if (live) setBundle(b)
      })
      .catch(() => {
        if (live) setError(true)
      })
    return () => {
      live = false
    }
  }, [key])
  return (
    <section
      className="assembly-finger-preparation"
      aria-label="Exploded finger parts and tendon stock"
    >
      {otherFingers && (
        <div className="assembly-clip-tabs" role="group" aria-label="Finger to assemble">
          {['Middle', 'Ring', 'Pinky'].map((f) => (
            <button key={f} aria-pressed={finger === f} onClick={() => setFinger(f)}>
              {f}
            </button>
          ))}
        </div>
      )}
      <div className="assembly-cad-detail-canvas">
        {bundle ? (
          <Canvas
            orthographic
            camera={{ position: [0, 0, 1000], near: 0.1, far: 4000 }}
            dpr={[1, 2]}
          >
            <ambientLight intensity={1.4} />
            <directionalLight position={[250, 400, 600]} intensity={3} />
            <directionalLight position={[-300, 0, -500]} intensity={2} />
            <FingerKit bundle={bundle} build={build} finger={finger} amount={amount} />
            <OrbitControls enablePan minZoom={0.5} maxZoom={3} />
          </Canvas>
        ) : (
          <p>
            {error
              ? 'Unable to load the finger parts. Reopen this step to retry.'
              : 'Loading finger parts…'}
          </p>
        )}
      </div>
      <label className="assembly-motion-scrubber">
        <span>Assembled</span>
        <input
          type="range"
          aria-label="Explode finger parts"
          min="0"
          max="100"
          value={amount * 100}
          onChange={(e) => setAmount(+e.target.value / 100)}
        />
        <span>Exploded</span>
      </label>
      <p>DP, PP and AP · matching skins · 6 bearings · 3 Ø2×8 mm pins · 2 Ø2×6 mm pins.</p>
      <p>
        <span style={{ color: '#408f97' }}>Teal: 2 prepared tendons × 2 m</span>, each with two
        Ashley stoppers and one single knot over each stopper.{' '}
        <span style={{ color: '#9a742b' }}>Gold: 2 unknotted AP tendons × 75 cm</span>. Coils show
        the stock separately; lengths are not to scale.
      </p>
    </section>
  )
}
