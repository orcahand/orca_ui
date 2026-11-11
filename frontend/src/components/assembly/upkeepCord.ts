import * as THREE from 'three'
import { ChannelCurve } from './channelStrands'

export const vector = (p: number[]) => new THREE.Vector3().fromArray(p)
export const range = (p: number, start: number, end: number) =>
  THREE.MathUtils.clamp((p - start) / (end - start), 0, 1)
export function portion(points: THREE.Vector3[], from = 0, to = 1, count = 180) {
  const curve = new ChannelCurve(points)
  return Array.from({ length: count + 1 }, (_, i) =>
    curve.getPoint(from + ((to - from) * i) / count),
  )
}
export function pathLength(points: THREE.Vector3[]) {
  return points.slice(1).reduce((length, point, i) => length + point.distanceTo(points[i]), 0)
}
// Free cord sags between openings; channel geometry itself is never smoothed.
export function looseSpan(from: THREE.Vector3[], to: THREE.Vector3[], sag = 0) {
  const a = from.at(-1)!,
    b = to[0],
    distance = a.distanceTo(b)
  const outgoing = a
    .clone()
    .sub(from.at(-2) ?? b)
    .normalize()
  const incoming = (to[1] ?? a).clone().sub(b).normalize()
  const handle = Math.min(distance * 0.3, 12)
  const droop = new THREE.Vector3(-sag * 0.35, -sag, sag * 0.25)
  return new THREE.CubicBezierCurve3(
    a,
    a.clone().addScaledVector(outgoing, handle).add(droop),
    b.clone().addScaledVector(incoming, -handle).add(droop),
    b,
  ).getPoints(48)
}
export function hangingTail(channel: THREE.Vector3[], length: number) {
  const start = channel.at(-1)!,
    tangent = start.clone().sub(channel.at(-2)!).normalize()
  const end = start.clone().add(new THREE.Vector3(-0.3, -0.9, 0.2).multiplyScalar(length))
  return new THREE.CubicBezierCurve3(
    start,
    start.clone().addScaledVector(tangent, Math.min(14, length * 0.3)),
    end.clone().add(new THREE.Vector3(0, length * 0.3, 0)),
    end,
  ).getPoints(48)
}
// Fixed-size buffers avoid allocating and uploading a new tube for every video frame.
export function repairCord(color: string, radius = 0.32) {
  const count = 660,
    sides = 6,
    geometry = new THREE.BufferGeometry()
  const positions = new Float32Array((count + 1) * sides * 3),
    indices: number[] = []
  for (let i = 0; i < count; i++)
    for (let j = 0; j < sides; j++) {
      const a = i * sides + j,
        b = i * sides + ((j + 1) % sides)
      indices.push(a, b, a + sides, b, b + sides, a + sides)
    }
  geometry.setAttribute(
    'position',
    new THREE.BufferAttribute(positions, 3).setUsage(THREE.DynamicDrawUsage),
  )
  geometry.setIndex(indices)
  const material = new THREE.MeshBasicMaterial({ color, transparent: true, depthWrite: false })
  const mesh = new THREE.Mesh(geometry, material)
  mesh.frustumCulled = false
  mesh.renderOrder = 5
  const tangent = new THREE.Vector3(),
    across = new THREE.Vector3(),
    up = new THREE.Vector3(),
    axis = new THREE.Vector3(0, 0, 1)
  function set(points: THREE.Vector3[], from = 0, to = 1) {
    mesh.visible = points.length > 1 && to - from > 0.001
    if (!mesh.visible) return
    const sampled = portion(points, from, to, count)
    for (let i = 0; i <= count; i++) {
      tangent
        .copy(sampled[Math.min(count, i + 1)])
        .sub(sampled[Math.max(0, i - 1)])
        .normalize()
      across
        .crossVectors(tangent, Math.abs(tangent.z) < 0.95 ? axis : new THREE.Vector3(0, 1, 0))
        .normalize()
      up.crossVectors(tangent, across)
      for (let j = 0; j < sides; j++) {
        const angle = (j / sides) * Math.PI * 2,
          offset = (i * sides + j) * 3
        positions[offset] =
          sampled[i].x + radius * (across.x * Math.cos(angle) + up.x * Math.sin(angle))
        positions[offset + 1] =
          sampled[i].y + radius * (across.y * Math.cos(angle) + up.y * Math.sin(angle))
        positions[offset + 2] =
          sampled[i].z + radius * (across.z * Math.cos(angle) + up.z * Math.sin(angle))
      }
    }
    geometry.attributes.position.needsUpdate = true
  }
  return {
    mesh,
    set,
    dispose: () => {
      geometry.dispose()
      material.dispose()
    },
  }
}
