// The hand URDF drawn as the camera should see it, for the live overlay: a
// transparent offscreen three.js render the video canvas composites under its
// own rotation. The camera is the solved (or CAD) pinhole, distortion ignored:
// view = camera_from_plate · plate_from_hand, the URDF scaled m → mm, OpenCV
// (x right, y down, z forward) to three.js by flipping y and z. Hidden lines
// are removed like the manual's drawings: a depth-only pass, then a faint fill
// of the front-most surface (the silhouette) and the 30° feature edges on top.
// Loaded lazily, so three.js stays out of the page's main chunk.

import * as THREE from 'three'
import type { URDFRobot } from 'urdf-loader'
import type { JointInfo } from '../../api/types'
import { useAppStore } from '../../state/appStore'
import { latest } from '../../state/streamStore'
import { JointPoseAdapter } from '../three/JointPoseAdapter'
import { loadHandRobot } from '../three/loadHandRobot'
import type { ModelOverlay } from './api'

const NEAR = 10
const FAR = 2000
const EDGE_DEG = 30
const FILL = 0.22

// The pose the 3D view shows: motor estimate under encoder measurements, or
// under the commanded targets on a hand without encoders.
function streamedPose(): Record<string, number> {
  const s = useAppStore.getState()
  const j = latest.joints
  const top = s.status?.capabilities?.encoders ? j.measured : s.control?.effective_pose_source === 'estimate' ? {} : j.target
  return { ...j.estimate, ...top }
}

const mat = (rows: number[][]) => new THREE.Matrix4().set(...(rows.flat() as Parameters<THREE.Matrix4['set']>))

export class HandOverlay {
  readonly canvas: HTMLCanvasElement
  private renderer: THREE.WebGLRenderer
  private scene = new THREE.Scene()
  private camera = new THREE.PerspectiveCamera()
  private mount = new THREE.Group()
  private adapter: JointPoseAdapter
  private materials: THREE.Material[]
  private placed = false
  private cameraFromPlate = new THREE.Matrix4()
  private plateFromHand = new THREE.Matrix4()
  private pose: Record<string, number> | null = null
  private mountOverride: number[][] | null = null

  private constructor(robot: URDFRobot, joints: JointInfo[], color: string) {
    this.renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true })
    this.renderer.setClearColor(0x000000, 0)
    this.canvas = this.renderer.domElement
    robot.rotation.set(0, 0, 0) // the loader stands it Y-up; the model wants the URDF frame
    robot.scale.setScalar(1000)
    this.mount.matrixAutoUpdate = false
    this.mount.add(robot)
    this.scene.add(this.mount)
    this.camera.matrixAutoUpdate = false
    this.adapter = new JointPoseAdapter(robot, joints)

    const offset = { polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1 }
    const depth = new THREE.MeshBasicMaterial({ colorWrite: false, ...offset })
    const fill = new THREE.MeshBasicMaterial({ color, transparent: true, opacity: FILL, depthWrite: false, depthFunc: THREE.EqualDepth, ...offset })
    const line = new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.95 })
    this.materials = [depth, fill, line]
    const meshes: THREE.Mesh[] = []
    robot.traverse((o) => (o as THREE.Mesh).isMesh && meshes.push(o as THREE.Mesh))
    for (const mesh of meshes) {
      mesh.material = depth
      const front = new THREE.Mesh(mesh.geometry, fill)
      front.renderOrder = 1
      const edges = new THREE.LineSegments(new THREE.EdgesGeometry(mesh.geometry, EDGE_DEG), line)
      edges.renderOrder = 2
      mesh.add(front, edges)
    }
  }

  static async create(urdfUrl: string, joints: JointInfo[], color: string): Promise<HandOverlay> {
    return new HandOverlay(await loadHandRobot(urdfUrl), joints, color)
  }

  /** Lens and pose for the current plate angle. */
  place(o: ModelOverlay) {
    const { fx, fy, cx, cy, size } = o.lens
    const [w, h] = size
    const P = this.camera.projectionMatrix
    P.set(
      (2 * fx) / w, 0, 1 - (2 * cx) / w, 0,
      0, (2 * fy) / h, (2 * cy) / h - 1, 0,
      0, 0, -(FAR + NEAR) / (FAR - NEAR), (-2 * FAR * NEAR) / (FAR - NEAR),
      0, 0, -1, 0,
    )
    this.camera.projectionMatrixInverse.copy(P).invert()
    this.cameraFromPlate = mat(o.camera_from_plate)
    this.plateFromHand = mat(o.plate_from_hand)
    this.placed = true
  }

  /** Joint angles (deg, URDF names) to draw instead of the live stream; null: the stream. */
  setPose(q: Record<string, number> | null) {
    this.pose = q
  }

  /** The hand's pose in the plate frame (4×4, mm) instead of the CAD mount; null: the CAD mount. */
  setMount(plateFromHand: number[][] | null) {
    this.mountOverride = plateFromHand
  }

  /** Posed (the live joint stream unless set), rendered at width × height (any size of the raw image's aspect). */
  render(width: number, height: number): HTMLCanvasElement | null {
    if (!this.placed) return null
    if (this.canvas.width !== width || this.canvas.height !== height) this.renderer.setSize(width, height, false)
    const flip = new THREE.Matrix4().makeScale(1, -1, -1)
    const hand = this.mountOverride ? mat(this.mountOverride) : this.plateFromHand
    this.mount.matrix.copy(flip.multiply(this.cameraFromPlate).multiply(hand))
    this.mount.matrixWorldNeedsUpdate = true
    this.adapter.apply(this.pose ?? streamedPose())
    this.renderer.render(this.scene, this.camera)
    return this.canvas
  }

  setColor(color: string) {
    for (const m of this.materials) if ('color' in m) (m as THREE.MeshBasicMaterial).color.set(color)
  }

  dispose() {
    this.scene.traverse((o) => {
      if (o instanceof THREE.LineSegments) o.geometry.dispose()
    })
    this.materials.forEach((m) => m.dispose())
    this.renderer.dispose()
  }
}
