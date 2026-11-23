import * as THREE from 'three'
import type { Bundle } from './cadAssets'
import { cadPieces, disposePieces, fade, ease, nearest } from './cadScene'
import { motorOwner, motorPieces } from './driveMap'
import { handTendonPath, vectors } from './conduitPaths'
import { anchorStopper } from './anchorStopper'
import { stopperGeometry } from './stopperGeometry'
import {
  repairCord,
  looseSpan,
  hangingTail,
  pathLength,
  portion,
  range,
  vector,
} from './upkeepCord'
import { UPKEEP_BUILD as build } from './upkeepSteps'
import frames from './livePoseFrames.json'
import apRoutes from './fingerApChannelRoutes.json'
import carpalRoutes from './fingerCarpalRoutes.json'
import anchorRoutes from './apAnchorRoutes.json'
import seatedKnots from './seatedApKnots.json'
import winding from './spoolPaths.json'

export type UpkeepScene = {
  group: THREE.Group
  direction: THREE.Vector3
  up: THREE.Vector3
  focus: THREE.Box3
  labels: { text: string; point: THREE.Vector3 }[]
  update: (position: number) => void
  setStage: (step: number, position: number) => void
  dispose: () => void
}
const NEW = '#087f87',
  OTHER = '#77968a',
  OLD = '#c25f41'
const box = (center: THREE.Vector3, size: THREE.Vector3) =>
  new THREE.Box3().setFromCenterAndSize(center, size)
const rotate = (pivot: THREE.Vector3, axis: THREE.Vector3, angle: number) => {
  const q = new THREE.Quaternion().setFromAxisAngle(axis, angle)
  return new THREE.Matrix4().compose(
    pivot.clone().sub(pivot.clone().applyQuaternion(q)),
    q,
    new THREE.Vector3(1, 1, 1),
  )
}

export function createRepairScene(bundle: Bundle): UpkeepScene {
  const pieces = cadPieces(bundle, build),
    group = new THREE.Group(),
    motors = motorPieces(pieces)
  const indexFrames = ['index_abd', 'index_mcp', 'index_pip'].map((name) => ({
    name,
    ...frames['base-right'][name as 'index_abd'],
    matrix: new THREE.Matrix4(),
  }))
  const bodies = pieces.filter((p) =>
    /^(Index|Middle|Ring|Pinky|Thumb) (DP|PP|AP|TP)$/.test(p.part.label),
  )
  const joints = Object.entries(frames['base-right'])
    .filter(([name]) => name !== 'wrist')
    .map(([name, f]) => ({ name, center: vector(f.pivot) }))
  const indexParts = new Map<string, number>()
  for (const piece of pieces) {
    let segment = piece.part.label.startsWith('Index ') ? piece.part.label.split(' ')[1] : undefined
    if (
      !segment &&
      piece.part.label.startsWith('Bearing') &&
      piece.part.areas.Fingers?.includes(piece.name)
    ) {
      const joint = nearest(joints, piece.center)
      if (joint.name.startsWith('index_'))
        segment = joint.name.endsWith('abd') ? 'AP' : joint.name.endsWith('mcp') ? 'PP' : 'DP'
    }
    if (
      !segment &&
      piece.part.label.startsWith('Pin') &&
      piece.part.areas.Fingers?.includes(piece.name)
    ) {
      const candidates = bodies.filter((p) =>
        p.bounds.clone().expandByScalar(1).containsPoint(piece.center),
      )
      const owner =
        piece.part.label === 'Pin · 2 × 6'
          ? (candidates.find((p) => p.part.label === 'Index PP') ??
            nearest(candidates, piece.center))
          : nearest(candidates, piece.center)
      if (owner?.part.label.startsWith('Index ')) segment = owner.part.label.split(' ')[1]
    }
    if (segment && ['AP', 'PP', 'DP'].includes(segment))
      indexParts.set(piece.name, ['AP', 'PP', 'DP'].indexOf(segment))
    group.add(piece.object)
    piece.object.matrixAutoUpdate = false
    const housing =
      piece.part.category === 'Skins' || /cover|plate|board|PCB|fan/i.test(piece.part.label)
    fade(piece, housing ? 0.12 : indexParts.has(piece.name) ? 0.88 : 0.22)
  }
  const holder = nearest(
    pieces.filter((p) => p.part.label === 'Metal spool holder'),
    motors
      .get(4)!
      .center.clone()
      .add(new THREE.Vector3(0, 0, 30)),
  )
  const holderScrew = nearest(
    pieces.filter((p) => p.part.label === 'M3 × 14 socket screw'),
    holder.center,
  )
  fade(holder, 1)
  fade(holderScrew, 1)
  const topLabels = [
    'Top spool / tensioner',
    'Spool cover',
    'Spool ORCA insert',
    'Bearing · 4 × 8 × 3',
  ]
  const lowerLabels = ['Bottom spool', 'Ratchet', 'M2 hex nut', 'M2 × 4 socket screw']
  const hardware = pieces.filter(
    (p) =>
      (topLabels.includes(p.part.label) ||
        lowerLabels.includes(p.part.label) ||
        p.part.label === 'M2.5 × 8 socket screw') &&
      [2, 3, 4].includes(motorOwner(p, motors)!) &&
      p.center.distanceTo(motors.get(motorOwner(p, motors)!)!.center) < 36,
  )
  hardware.forEach((p) => fade(p, 0.9, motorOwner(p, motors) === 4 ? '#547f77' : undefined))
  const indices = [19, 20, 18, 21, 17, 22]
  const routes = indices.map((index, i) => {
    const route = carpalRoutes['base-right'].find((r) => r.index === index)!
    const hand = handTendonPath(build, index)
    const ap = i < 4 ? apRoutes['base-right'][[0, 1, 3, 2][i]] : null
    let fixed = ap ? vectors(ap.fixed) : []
    if (ap) {
      const start = vector(route.moving[0])
      let closest = 0
      fixed.forEach((p, j) => {
        if (p.distanceToSquared(start) < fixed[closest].distanceToSquared(start)) closest = j
      })
      fixed = fixed.slice(0, closest + 1)
    }
    return {
      index,
      root: ap ? vectors(ap.moving) : [],
      fixed,
      moving: vectors(route.moving),
      downstream: hand.slice(route.moving.length),
      motor: i < 2 ? 2 : i < 4 ? 3 : 4,
      kind: i % 2 === 0 ? ('bottom' as const) : ('top' as const),
    }
  })
  const cords = routes.map((_, i) => repairCord(i === 4 ? OLD : OTHER, i >= 4 ? 0.36 : 0.27))
  const brokenTail = repairCord(OLD, 0.36),
    newCord = repairCord(NEW, 0.36),
    insertion = repairCord(NEW, 0.3)
  const coils = routes.map((_, i) => repairCord(i === 4 ? OLD : OTHER, 0.26))
  const knots = routes.map(() => stopperGeometry(0.6))
  const anchor = anchorStopper(0.65, 1),
    anchorPose = seatedKnots['base-right'].Index[0]
  const allCords = [...cords, brokenTail, newCord, insertion, ...coils]
  allCords.forEach((c) => group.add(c.mesh))
  knots.forEach((k) => group.add(k.group))
  group.add(anchor.group)
  anchor.group.traverse((n) => {
    if (n instanceof THREE.Mesh) (n.material as THREE.MeshStandardMaterial).color.set(NEW)
  })
  const marker = new THREE.Mesh(
    new THREE.SphereGeometry(1.2, 12, 8),
    new THREE.MeshBasicMaterial({ color: NEW, depthTest: false }),
  )
  marker.renderOrder = 10
  group.add(marker)
  const markers = [2, 3, 4].map((id) => {
    const m = new THREE.Mesh(
      new THREE.TorusGeometry(12, 0.55, 6, 48),
      new THREE.MeshBasicMaterial({ color: '#e5a030', depthTest: false }),
    )
    m.position.copy(
      nearest(
        hardware.filter((p) => p.part.label === 'Spool cover'),
        motors.get(id)!.center,
      ).center,
    )
    m.position.z += 6
    m.renderOrder = 8
    group.add(m)
    return m
  })
  const arrows = [-1, 1].map((sign) => {
    const g = new THREE.Group(),
      material = new THREE.MeshBasicMaterial({
        color: sign === 1 ? '#087f87' : '#bf883c',
        depthTest: false,
      })
    const arc = new THREE.Mesh(new THREE.TorusGeometry(14, 0.45, 6, 48, Math.PI * 1.6), material)
    const tip = new THREE.Mesh(new THREE.ConeGeometry(1.2, 3.4, 8), material)
    const a = Math.PI * 1.6
    tip.position.set(14 * Math.cos(a), 14 * Math.sin(a), 0)
    tip.rotation.z = a
    g.add(arc, tip)
    g.scale.y = sign
    g.renderOrder = 10
    g.traverse((n) => (n.renderOrder = 10))
    group.add(g)
    return g
  })
  const up = new THREE.Vector3(0, 1, 0),
    direction = new THREE.Vector3(-0.15, 0.12, 1),
    focus = new THREE.Box3(),
    labels: UpkeepScene['labels'] = []
  const lift = new THREE.Vector3(-46, 24, 35),
    opened = new THREE.Vector3(-8, 32, 14)
  const fullBox = box(new THREE.Vector3(-8, 105, 0), new THREE.Vector3(150, 340, 115))
  const towerBox = box(new THREE.Vector3(-20, 15, 45), new THREE.Vector3(110, 220, 160))
  const columnBox = box(new THREE.Vector3(-26, 12, 58), new THREE.Vector3(70, 110, 140))
  const pairBox = (id: number) =>
    box(
      motors
        .get(id)!
        .center.clone()
        .add(new THREE.Vector3(-7, 0, 42)),
      new THREE.Vector3(58, 48, 125),
    )
  const fingerBox = box(new THREE.Vector3(-75, 225, 25), new THREE.Vector3(130, 220, 115))
  const apBox = box(
    vector(anchorPose.position)
      .add(lift)
      .add(new THREE.Vector3(0, 4, 0)),
    new THREE.Vector3(58, 65, 50),
  )
  const routeBox = box(new THREE.Vector3(-45, 135, 20), new THREE.Vector3(180, 390, 125))
  const lerpBox = (a: THREE.Box3, b: THREE.Box3, t: number) => {
    focus.min.copy(a.min).lerp(b.min, ease(t))
    focus.max.copy(a.max).lerp(b.max, ease(t))
  }
  let lastStage = -1,
    lastPosition = -1,
    lastStyle = ''
  function setStage(stage: number, p: number) {
    if (stage === lastStage && p === lastPosition) return
    lastStage = stage
    lastPosition = p
    const holderOut =
      stage < 1
        ? 0
        : stage === 1
          ? ease(range(p, 0.4, 1))
          : stage === 8
            ? 1 - ease(range(p, 0.78, 0.96))
            : 1
    const topOut =
      stage < 2
        ? 0
        : stage === 2
          ? ease(range(p, 0.45, 1))
          : stage === 8
            ? 1 - ease(range(p, 0, 0.35))
            : 1
    const screwOut =
      stage < 2
        ? 0
        : stage === 2
          ? ease(range(p, 0.15, 0.45))
          : stage === 8
            ? 1 - ease(range(p, 0.35, 0.5))
            : 1
    const loose =
      stage < 3
        ? 0
        : stage === 3
          ? ease(range(p, 0, 0.65))
          : stage === 7
            ? 1 - ease(range(p, 0.62, 1))
            : stage > 7
              ? 0
              : 1
    const withdrawn =
      stage < 4
        ? 0
        : stage === 4
          ? ease(range(p, 0.65, 1))
          : stage === 6
            ? 1 - ease(p)
            : stage > 6
              ? 0
              : 1
    const fingerOut =
      stage < 4
        ? 0
        : stage === 4
          ? ease(range(p, 0.22, 0.45))
          : stage === 7
            ? 1 - ease(range(p, 0.2, 0.4))
            : stage > 7
              ? 0
              : 1
    const split =
      stage < 4
        ? 0
        : stage === 4
          ? ease(range(p, 0.45, 0.65))
          : stage === 7
            ? 1 - ease(range(p, 0, 0.2))
            : stage > 7
              ? 0
              : 1
    const rethread = stage === 7 ? ease(range(p, 0.52, 0.68)) : stage > 7 ? 1 : 0
    const released =
      stage < 3
        ? 0
        : stage === 3
          ? ease(range(p, 0.85, 1))
          : stage === 7
            ? 1 - rethread
            : stage > 7
              ? 0
              : 1
    const style = `${stage}-${stage === 8 && p > 0.82}`
    if (style !== lastStyle) {
      lastStyle = style
      cords.forEach((cord, i) => {
        if (i !== 4)
          (cord.mesh.material as THREE.MeshBasicMaterial).opacity = stage === 5 ? 0 : 1
      })
      for (const piece of pieces) {
        const label = piece.part.label,
          selected = indexParts.has(piece.name),
          spool = hardware.includes(piece),
          indexMotor =
            label === 'Dynamixel XC330 motor' && [2, 3, 4].includes(motorOwner(piece, motors)!)
        const body = bodies.includes(piece),
          skin = piece.part.category === 'Skins'
        const structure = ['Carpals', 'Wrist frame', 'Motor tower'].includes(label)
        piece.object.visible =
          selected ||
          spool ||
          body ||
          skin ||
          structure ||
          piece === holder ||
          piece === holderScrew ||
          label === 'Dynamixel XC330 motor' ||
          label === 'Dynamixel XC430 wrist motor'
        if (stage === 5) piece.object.visible = indexParts.get(piece.name) === 0
        const whole = stage === 0 || (stage === 8 && p > 0.82)
        const opacity = selected
          ? skin
            ? 0.18
            : stage >= 4 && stage <= 7 ? 0.7 : 1
          : spool || indexMotor
            ? 1
            : piece === holder || piece === holderScrew
              ? 1
              : whole
                ? skin
                  ? 0.75
                  : body
                    ? 0.9
                    : 0.5
                : skin
                  ? 0
                  : structure
                    ? 0.06
                    : body
                      ? 0.12
                      : 0.035
        if (opacity === 0) piece.object.visible = false
        fade(piece, opacity)
      }
    }
    const angles = [0, 0, 0]
    let wiggled = -1,
      wiggle = 0
    if (stage === 0 && p > 0.15) {
      wiggled = Math.min(2, Math.floor(range(p, 0.15, 1) * 3))
      const local = range(p, 0.15, 1) * 3 - wiggled
      wiggle = Math.sin(local * Math.PI * 2) * 0.32
      angles[2 - wiggled] = wiggle
    }
    if (stage === 8 && p > 0.5 && p < 0.78) {
      wiggle = Math.sin(range(p, 0.5, 0.78) * Math.PI * 4) * 0.15
      angles[1] = wiggle
    }
    indexFrames.forEach((f, i) => {
      f.matrix.copy(rotate(vector(f.pivot), vector(f.axis), angles[i]))
      if (i) f.matrix.premultiply(indexFrames[i - 1].matrix)
      // Whole joints move as units; there is no separate pin or bearing extraction.
    })
    const matrices = indexFrames.map((f, i) =>
      f.matrix.clone().premultiply(
        new THREE.Matrix4().makeTranslation(
          ...(lift
            .clone()
            .multiplyScalar(fingerOut)
            .addScaledVector(opened, i ? split : 0)
            .toArray() as [number, number, number]),
        ),
      ),
    )
    for (const piece of pieces) {
      const segment = indexParts.get(piece.name)
      piece.object.matrix.copy(segment === undefined ? new THREE.Matrix4() : matrices[segment])
      piece.object.matrixWorldNeedsUpdate = true
    }
    holder.object.matrix.makeTranslation(0, 95 * holderOut, 65 * holderOut)
    const hs =
      stage < 1
        ? 0
        : stage === 1
          ? ease(range(p, 0.2, 0.4))
          : stage === 8
            ? 1 - ease(range(p, 0.96, 1))
            : 1
    holderScrew.object.matrix.copy(
      rotate(holderScrew.center, new THREE.Vector3(0, 0, 1), hs * Math.PI * 6),
    )
    holderScrew.object.matrix.premultiply(new THREE.Matrix4().makeTranslation(0, 0, 35 * hs))
    const coilPaths: THREE.Vector3[][] = []
    routes.forEach((r, i) => {
      const affected = i >= 4,
        data = winding[r.kind]
      const amount =
        stage === 3
          ? ease(range(p, i < 2 ? 0 : i < 4 ? 0.3 : 0.55, i < 2 ? 0.3 : i < 4 ? 0.55 : 0.85))
          : loose
      let turns = 3 - amount * (affected ? 3 : 1.2)
      if (stage >= 4 && stage < 7 && affected) turns = 0
      if (stage === 7)
        turns =
          3 -
          (affected ? 3 : 1.2) *
            (1 -
              ease(
                range(
                  p,
                  affected ? 0.68 : r.motor === 2 ? 0.8 : 0.9,
                  affected ? 0.8 : r.motor === 2 ? 0.9 : 1,
                ),
              ))
      const motorWiggle =
        stage === 0 && r.motor === [2, 3, 4][wiggled]
          ? wiggle * 2
          : stage === 8 && p > 0.5 && p < 0.78
            ? wiggle
            : 0
      const rotation = data.direction * (turns - 3) * Math.PI * 2 + motorWiggle
      const spool = nearest(
        hardware.filter(
          (h) => h.part.label === (r.kind === 'top' ? 'Spool cover' : 'Bottom spool'),
        ),
        motors.get(r.motor)!.center,
      )
      const offset = new THREE.Vector3(0, 0, r.kind === 'top' ? 46 * topOut : 0)
      const spin = rotate(spool.center, new THREE.Vector3(0, 0, 1), rotation).premultiply(
        new THREE.Matrix4().makeTranslation(...(offset.toArray() as [number, number, number])),
      )
      for (const h of hardware.filter(
        (h) =>
          motorOwner(h, motors) === r.motor &&
          (r.kind === 'top' ? topLabels : lowerLabels).includes(h.part.label),
      ))
        h.object.matrix.copy(spin)
      // The positive-z index spools mirror the source spool channel in z.
      const local = (v: number[] | THREE.Vector3) => {
        const q = Array.isArray(v) ? vector(v) : v.clone()
        q.z *= -1
        return q.add(spool.center).applyMatrix4(spin)
      }
      const origin = vector(data.origin),
        coil: THREE.Vector3[] = []
      for (let n = 0; n <= 120; n++) {
        const t = n / 120,
          theta = data.theta - data.direction * turns * Math.PI * 2 * (1 - t)
        coil.push(
          local(
            origin
              .clone()
              .add(
                new THREE.Vector3(
                  data.radius * Math.cos(theta),
                  data.radius * Math.sin(theta),
                  r.kind === 'bottom' ? t - 0.5 : 0.5 - t,
                ),
              ),
          ),
        )
      }
      const channel = data.channel.map(local),
        lead = data.lead.map(local)
      const path = [...coil, ...lead.slice(1), ...channel]
      coils[i].set(
        path,
        0,
        affected && stage >= 4 && stage < 7
          ? 0
          : stage === 7 && affected && p < 0.68
            ? rethread
            : affected && stage === 3
              ? 1 - released
              : 1,
      )
      if (i === 4 && (stage >= 6 || (stage === 5 && p >= 0.2)))
        (coils[i].mesh.material as THREE.MeshBasicMaterial).color.set(NEW)
      else if (i === 4) (coils[i].mesh.material as THREE.MeshBasicMaterial).color.set(OLD)
      if (i !== 4)
        (coils[i].mesh.material as THREE.MeshBasicMaterial).color.set(
          stage === 0 && r.motor === [2, 3, 4][wiggled] ? '#c18b2c' : OTHER,
        )
      const end = channel.at(-1)!,
        axis = end.clone().sub(channel.at(-8)!).normalize()
      knots[i].group.position.copy(end).addScaledVector(axis, 0.8)
      knots[i].group.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), axis)
      knots[i].group.visible =
        !affected ||
        stage < 3 ||
        (stage === 3 && p < 0.85) ||
        stage > 7 ||
        (stage === 7 && p >= 0.67)
      if (stage === 5) {
        coils[i].mesh.visible = false
        knots[i].group.visible = false
      }
      coilPaths.push(path)
      if (i >= 4) {
        const a = arrows[i - 4]
        a.visible = (stage === 3 && p >= 0.55 && p < 0.85) || (stage === 7 && p > 0.68 && p < 0.8)
        a.position
          .copy(spool.center)
          .add(offset)
          .add(new THREE.Vector3(0, 0, 4))
        a.scale.y = (stage === 3 ? -1 : 1) * data.direction
        a.rotation.z = (stage === 3 ? -1 : 1) * data.direction * p * Math.PI * 2
      }
    })
    hardware
      .filter((h) => h.part.label === 'M2.5 × 8 socket screw')
      .forEach((s) => {
        s.object.matrix
          .copy(
            rotate(
              s.center,
              new THREE.Vector3(0, 0, 1),
              screwOut * Math.PI * 6 + (stage === 8 ? range(p, 0.7, 0.78) * Math.PI * 2 : 0),
            ),
          )
          .premultiply(new THREE.Matrix4().makeTranslation(0, 0, 86 * screwOut))
      })
    markers.forEach((m, i) => {
      m.visible = stage === 0 && wiggled === i
      m.scale.setScalar(1 + Math.abs(wiggle) * 0.4)
    })
    ;(cords[4].mesh.material as THREE.MeshBasicMaterial).opacity = 1
    ;(brokenTail.mesh.material as THREE.MeshBasicMaterial).opacity = 1
    const paths = routes.map((r, i) => {
      if (i !== 4)
        (cords[i].mesh.material as THREE.MeshBasicMaterial).color.set(
          stage === 0 && r.motor === [2, 3, 4][wiggled] ? '#c18b2c' : OTHER,
        )
      const tx = (v: THREE.Vector3, part: number) => v.clone().applyMatrix4(matrices[part])
      const moving = r.moving.map((v) => tx(v, 0)),
        downstream = r.downstream.map((v) => v.clone())
      let root: THREE.Vector3[] = []
      if (r.root.length) {
        const upper = r.root.map((v) => tx(v, i < 2 && v.y > 216 ? 2 : 1)),
          fixed = r.fixed.map((v) => tx(v, 0))
        root = [
          ...upper,
          ...looseSpan(upper, fixed, split * 4).slice(1),
          ...fixed,
          ...looseSpan(fixed, moving).slice(1),
        ]
      }
      const towerEnd = coilPaths[i]
        .slice(0, 2)
        .map((point) =>
          point.clone().add(new THREE.Vector3(-10, -18, 10).multiplyScalar(i >= 4 ? released : 0)),
        )
      const downstreamPath = [
        ...downstream,
        ...looseSpan(downstream, towerEnd, loose * (i < 4 ? 9 : 4)).slice(1),
      ]
      const connector = looseSpan(moving, downstream, fingerOut * 5)
      const path = [...root, ...moving, ...connector.slice(1), ...downstreamPath]
      let withdrawnPath = path
      if (i >= 4 && withdrawn > 0) {
        // The tail retreats through the fixed channels. Extracted cord collects
        // in the exposed gap, never as a new sideways loop inside a housing.
        const pull = range(withdrawn, 0, 0.8),
          clear = range(withdrawn, 0.8, 1)
        const remaining = portion(downstreamPath, 0, 1 - pull)
        const tail = hangingTail(moving, 66 + i * 2)
        const freeEnd = downstream[0].clone().lerp(tail.at(-1)!, ease(clear))
        const endpoint = [freeEnd, freeEnd.clone().add(new THREE.Vector3(0, -5, 0))]
        const gap = looseSpan(
          moving,
          clear > 0 ? endpoint : downstream,
          5 + pull * 42 * (1 - clear),
        )
        withdrawnPath = [
          ...root,
          ...moving,
          ...gap.slice(1),
          ...(pull < 1 ? remaining.slice(1) : []),
        ]
      }
      if (i !== 4) cords[i].set(i >= 4 ? withdrawnPath : path)
      else {
        const length = pathLength(withdrawnPath),
          breakStart = 6 / length,
          breakEnd = 8 / length
        if (stage < 5) {
          cords[i].set(withdrawnPath, 0, breakStart)
          brokenTail.set(withdrawnPath, breakEnd, 1)
        } else if (stage === 5 && p < 0.2) {
          const pull = ease(range(p, 0.08, 0.2)),
            axis = vector(anchorRoutes['base-right'].up)
          const fragment = portion(withdrawnPath, 0, breakStart).map((point) =>
            point.addScaledVector(axis, pull * 22),
          )
          const tail = [...moving, ...hangingTail(moving, 74 + pull * 22).slice(1)]
          cords[i].set(fragment)
          brokenTail.set(tail, (8 + pull * (pathLength(moving) + 10)) / pathLength(tail), 1)
          ;(cords[i].mesh.material as THREE.MeshBasicMaterial).opacity = 1 - range(p, 0.17, 0.2)
          ;(brokenTail.mesh.material as THREE.MeshBasicMaterial).opacity = 1 - range(p, 0.17, 0.2)
        } else {
          cords[i].mesh.visible = false
          brokenTail.mesh.visible = false
        }
      }
      return { path, tip: withdrawnPath.at(-1)! }
    })
    const activePath = paths[4].path
    if (stage >= 6) {
      const progress = stage === 6 ? ease(p) : 1
      newCord.set(activePath, 0, progress)
      marker.visible = stage === 6
      marker.position.copy(portion(activePath, 0, progress, 1).at(-1)!)
    } else {
      newCord.mesh.visible = false
      marker.visible = false
    }
    if (stage === 4 && p > 0.65) {
      marker.visible = true
      marker.position.copy(paths[4].tip)
    }
    const anchorPoints = vectors(anchorRoutes['base-right'].paths[0]).map((v) =>
        v.applyMatrix4(matrices[0]),
      ),
      seat = anchorPoints.at(-1)!
    const anchorUp = vector(anchorRoutes['base-right'].up)
    const working = seat.clone().addScaledVector(anchorUp, 19)
    const outside = anchorPoints[0].clone().add(new THREE.Vector3(-18, -8, 8))
    insertion.set(
      [
        ...looseSpan([outside.clone().add(new THREE.Vector3(-5, -5, 0)), outside], anchorPoints),
        ...anchorPoints.slice(1),
        working,
      ],
      0,
      stage === 5 ? ease(range(p, 0.2, 0.36)) : 0,
    )
    ;(insertion.mesh.material as THREE.MeshBasicMaterial).opacity =
      stage === 5 ? 1 - ease(range(p, 0.94, 1)) : 0
    anchor.group.visible = stage > 5 || (stage === 5 && p > 0.85)
    const at = vector(anchorPose.position).applyMatrix4(matrices[0])
    anchor.group.position
      .copy(at)
      .addScaledVector(anchorUp, 12 * (1 - ease(range(p, 0.94, 1))) * (stage === 5 ? 1 : 0))
    anchor.group.quaternion.fromArray(anchorPose.quaternion)
    if (stage === 5 && p > 0.94)
      insertion.set(
        [
          ...looseSpan([outside.clone().add(new THREE.Vector3(-5, -5, 0)), outside], anchorPoints),
          ...anchorPoints.slice(1),
          anchor.group.position,
        ],
        0,
        1,
      )
    const front = new THREE.Vector3(-0.15, 0.18, 1),
      towerDirection = new THREE.Vector3(-1, 0.25, 1)
    const anchorDirection = vector(anchorRoutes['base-right'].up)
      .addScaledVector(vector(anchorRoutes['base-right'].front), 0.65)
      .addScaledVector(vector(anchorRoutes['base-right'].across), 0.45)
      .normalize()
    direction.copy(front)
    up.set(0, 1, 0)
    if (stage === 0) focus.copy(fullBox)
    else if (stage === 1) {
      lerpBox(fullBox, towerBox, range(p, 0, 0.25))
      direction.lerp(towerDirection, ease(range(p, 0, 0.25)))
    } else if (stage === 2) {
      lerpBox(towerBox, columnBox, range(p, 0, 0.2))
      direction.copy(towerDirection)
    } else if (stage === 3) {
      const target = p < 0.3 ? pairBox(2) : p < 0.55 ? pairBox(3) : pairBox(4)
      const previous = p < 0.3 ? columnBox : p < 0.55 ? pairBox(2) : pairBox(3)
      lerpBox(
        previous,
        target,
        range(p, p < 0.3 ? 0 : p < 0.55 ? 0.3 : 0.55, p < 0.3 ? 0.15 : p < 0.55 ? 0.42 : 0.67),
      )
      direction.copy(towerDirection)
    } else if (stage === 4) {
      lerpBox(pairBox(4), fingerBox, range(p, 0, 0.22))
      direction.copy(towerDirection).lerp(front, ease(range(p, 0, 0.22)))
    } else if (stage === 5) {
      lerpBox(fingerBox, apBox, range(p, 0, 0.08))
      direction.lerp(anchorDirection, ease(range(p, 0, 0.08)))
      up.lerp(vector(anchorRoutes['base-right'].across), ease(range(p, 0, 0.08))).normalize()
    } else if (stage === 6) {
      const following = box(marker.position, new THREE.Vector3(110, 175, 110))
      if (p < 0.2) lerpBox(apBox, following, range(p, 0, 0.2))
      else lerpBox(following, routeBox, range(p, 0.8, 1))
      direction.copy(anchorDirection).lerp(front, ease(range(p, 0, 0.2)))
      up.copy(vector(anchorRoutes['base-right'].across))
        .lerp(new THREE.Vector3(0, 1, 0), ease(range(p, 0, 0.2)))
        .normalize()
    } else if (stage === 7) {
      if (p < 0.35) lerpBox(routeBox, fingerBox, range(p, 0, 0.15))
      else if (p < 0.8) lerpBox(fingerBox, pairBox(4), range(p, 0.4, 0.52))
      else if (p < 0.9) lerpBox(pairBox(4), pairBox(2), range(p, 0.8, 0.85))
      else lerpBox(pairBox(2), pairBox(3), range(p, 0.9, 0.95))
      direction.lerp(towerDirection, ease(range(p, 0.4, 0.52)))
    } else {
      if (p < 0.15) lerpBox(pairBox(3), columnBox, range(p, 0, 0.15))
      else if (p < 0.78) focus.copy(columnBox)
      else if (p < 0.88) lerpBox(columnBox, towerBox, range(p, 0.78, 0.88))
      else lerpBox(towerBox, fullBox, range(p, 0.88, 1))
      direction.copy(towerDirection).lerp(front, ease(range(p, 0.88, 1)))
    }
    const pts =
      stage === 1
        ? [
            {
              text: 'Spool holder',
              point: holder.center.clone().applyMatrix4(holder.object.matrix),
            },
          ]
        : stage === 3 || (stage === 7 && p > 0.55)
          ? [
              {
                text: `Motor ${stage === 3 ? (p < 0.3 ? 2 : p < 0.55 ? 3 : 4) : p < 0.8 ? 4 : p < 0.9 ? 2 : 3}`,
                point: focus.getCenter(new THREE.Vector3()),
              },
            ]
          : stage <= 3 || stage === 8 || (stage === 7 && p > 0.45)
            ? [2, 3, 4].map((id) => ({
                text: `Motor ${id}`,
                point: motors
                  .get(id)!
                  .center.clone()
                  .add(new THREE.Vector3(0, 0, 25)),
              }))
            : stage === 6
              ? [
                  { text: 'Finger', point: seat },
                  { text: 'Carpals', point: new THREE.Vector3(-30, 125, 5) },
                  { text: 'Wrist', point: new THREE.Vector3(-24, 80, 15) },
                  { text: 'Tower', point: new THREE.Vector3(-26, 0, 45) },
                ]
              : [
                  {
                    text:
                      stage === 5 ? (p < 0.2 ? 'Broken tendon' : 'Replacement tendon') : 'Index AP',
                    point: seat,
                  },
                ]
    labels.splice(0, labels.length, ...pts)
    group.updateMatrixWorld(true)
  }
  setStage(0, 0)
  return {
    group,
    direction,
    up,
    focus,
    labels,
    setStage,
    update: (p) => setStage(0, p),
    dispose: () => {
      disposePieces(pieces)
      allCords.forEach((c) => c.dispose())
      knots.forEach((k) => k.dispose())
      anchor.dispose()
      arrows.forEach((g) =>
        g.traverse((n) => {
          if (n instanceof THREE.Mesh) {
            n.geometry.dispose()
            n.material.dispose()
          }
        }),
      )
      ;[marker, ...markers].forEach((m) => {
        m.geometry.dispose()
        ;(m.material as THREE.Material).dispose()
      })
    },
  }
}
export function upkeepScene(bundle: Bundle, step: number): UpkeepScene {
  const scene = createRepairScene(bundle)
  return { ...scene, update: (p) => scene.setStage(step, p) }
}
export function upkeepBounds(model: UpkeepScene) {
  return model.focus.clone()
}
