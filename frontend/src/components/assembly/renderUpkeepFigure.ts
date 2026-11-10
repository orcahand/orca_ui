// Offline figure only: uses the same Base CAD and measured anchor route as the guide.
import * as THREE from 'three'
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js'
import { loadBundle } from './cadAssets'
import { motorId, jointTendons } from './driveMap'
import { REPAIR_POSES } from './upkeepTimeline'
import { upkeepScene } from './upkeepScene'
import { UPKEEP_STEPS } from './upkeepSteps'
import type { Build } from './buildContent'

export async function renderUpkeepFigure() {
  const build: Build = { version: 'base', side: 'right', motor: 'dynamixel', audience: 'external' }
  const bundle = await loadBundle('base-right-dynamixel')
  const width = 2400,
    height = 3240
  const canvas = document.createElement('canvas')
  canvas.width = width
  canvas.height = height
  const ctx = canvas.getContext('2d')!
  const ink = '#20332f',
    accent = '#14786e',
    muted = '#63736c',
    paper = '#f7f7f2'
  const renderer = new THREE.WebGLRenderer({
    alpha: true,
    antialias: true,
    preserveDrawingBuffer: true,
  })
  renderer.setSize(1400, 1680)
  renderer.setClearColor(0, 0)
  renderer.toneMapping = THREE.ACESFilmicToneMapping
  renderer.toneMappingExposure = 1.15
  const pmrem = new THREE.PMREMGenerator(renderer),
    room = new RoomEnvironment()
  const environment = pmrem.fromScene(room, 0.04)
  const scene = new THREE.Scene()
  scene.environment = environment.texture
  scene.environmentIntensity = 0.8
  scene.add(new THREE.HemisphereLight('#ffffff', '#6a7470', 1.4))
  const lights = [
    new THREE.DirectionalLight('#fff8ec', 2.5),
    new THREE.DirectionalLight('#ddeeff', 1.4),
    new THREE.DirectionalLight('#ffffff', 1.8),
  ]
  lights.forEach((light) => {
    scene.add(light)
    scene.add(light.target)
  })

  function text(value: string, x: number, y: number, size = 28, color = ink, weight = 400) {
    ctx.font = `${weight} ${size}px system-ui, sans-serif`
    ctx.textAlign = 'left'
    ctx.textBaseline = 'top'
    ctx.fillStyle = color
    ctx.fillText(value, x, y)
  }
  function leader(
    label: string,
    point: THREE.Vector2,
    x: number,
    y: number,
    side: 'left' | 'right' = 'left',
  ) {
    ctx.font = '600 28px system-ui, sans-serif'
    const w = ctx.measureText(label).width
    const end = side === 'left' ? x + w + 14 : x - 14
    ctx.beginPath()
    ctx.moveTo(point.x, point.y)
    ctx.lineTo(end + (side === 'left' ? 20 : -20), y + 17)
    ctx.lineTo(end, y + 17)
    ctx.strokeStyle = accent
    ctx.lineWidth = 2.2
    ctx.stroke()
    ctx.beginPath()
    ctx.arc(point.x, point.y, 5, 0, Math.PI * 2)
    ctx.fillStyle = accent
    ctx.fill()
    ctx.fillStyle = paper
    ctx.fillRect(x - 8, y - 5, w + 16, 43)
    text(label, x, y, 28, accent, 600)
  }
  function render(
    group: THREE.Group,
    direction: THREE.Vector3,
    up: THREE.Vector3,
    x: number,
    y: number,
    w: number,
    h: number,
    bounds: THREE.Box3,
  ) {
    scene.add(group)
    group.updateMatrixWorld(true)
    const center = bounds.getCenter(new THREE.Vector3())
    const distance = bounds.getSize(new THREE.Vector3()).length() * 4
    const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0.01, distance * 5)
    camera.up.copy(up)
    camera.position.copy(center).addScaledVector(direction.clone().normalize(), distance)
    camera.lookAt(center)
    camera.updateMatrixWorld(true)
    const projected = new THREE.Box3()
    for (const xx of [bounds.min.x, bounds.max.x])
      for (const yy of [bounds.min.y, bounds.max.y])
        for (const zz of [bounds.min.z, bounds.max.z])
          projected.expandByPoint(
            new THREE.Vector3(xx, yy, zz).applyMatrix4(camera.matrixWorldInverse),
          )
    const extent = projected.getSize(new THREE.Vector3()),
      middle = projected.getCenter(new THREE.Vector3())
    const half = Math.max(extent.y / 2, extent.x / 2 / (w / h)) * 1.16
    camera.top = middle.y + half
    camera.bottom = middle.y - half
    camera.left = middle.x - (half * w) / h
    camera.right = middle.x + (half * w) / h
    camera.updateProjectionMatrix()
    const right = new THREE.Vector3(1, 0, 0).applyQuaternion(camera.quaternion)
    lights[0].position
      .copy(camera.position)
      .addScaledVector(up, distance)
      .addScaledVector(right, -distance)
    lights[1].position.copy(camera.position).addScaledVector(right, distance)
    lights[2].position
      .copy(center)
      .addScaledVector(direction, -distance)
      .addScaledVector(up, distance)
    lights.forEach((light) => light.target.position.copy(center))
    renderer.setSize(w * 2, h * 2)
    renderer.render(scene, camera)
    ctx.drawImage(renderer.domElement, x, y, w, h)
    scene.remove(group)
    return (point: THREE.Vector3) => {
      const p = point.clone().project(camera)
      return new THREE.Vector2(x + ((p.x + 1) * w) / 2, y + ((1 - p.y) * h) / 2)
    }
  }

  const steps = UPKEEP_STEPS
  ctx.fillStyle = paper
  ctx.fillRect(0, 0, width, height)
  text('ORCA  /  UPKEEP', 72, 52, 25, accent, 600)
  text('Replace a finger tendon', 72, 108, 66, ink, 600)
  text(
    'Loosen the whole finger → free the damaged pair → replace → rebuild → tension.',
    74,
    196,
    31,
    muted,
  )
  text(
    'Six tendon ends per finger; eight for the thumb. Keep unaffected ends attached to their spools.',
    74,
    244,
    29,
    muted,
  )
  ctx.fillStyle = '#e9eee7'
  ctx.fillRect(72, 308, 2256, 88)
  text('BEFORE STARTING', 98, 334, 25, accent, 700)
  text('Disconnect. Power off. Label cord ends and photograph routes and winding.', 390, 334, 28)
  text('WORKED EXAMPLE · BASE RIGHT · DYNAMIXEL · INDEX BASE TENDON (AP)', 72, 432, 26, accent, 600)
  const images: { name: string; data: string }[] = []
  const captions = [
    ['Power off. Wiggle the finger gently.', 'Watch which motors move with it.'],
    ['Undo the holder screw.', 'Slide the holder up and out.'],
    ['Remove the three top-spool screws.', 'Lift the top spools; bearings stay seated.'],
    ['Counter-rotate to loosen all six ends.', 'Fully free only the damaged joint’s pair.'],
    ['Pop out the finger and expose the AP.', 'Pins and bearings stay in their parts.'],
    ['Pull out the broken cord. Insert new cord.', 'Tie and seat the assembly guide’s knot.'],
    ['Finger → carpals → wrist → tower.', 'Restore all displaced cords in order.'],
    ['Pop the finger back in.', 'Rethread freed ends; rewind all slack.'],
    ['Refit top spools. Tension and tighten.', 'Refit and secure the spool holder.'],
  ]
  for (let i = 0; i < steps.length; i++) {
    const x = 72 + (i % 3) * 768,
      y = 500 + Math.floor(i / 3) * 880
    text(String(i + 1).padStart(2, '0'), x, y + 4, 31, accent, 600)
    text(steps[i].title, x + 60, y, 35, ink, 600)
    const model = upkeepScene(bundle, i)
    model.update(REPAIR_POSES[i])
    const project = render(
      model.group,
      model.direction,
      model.up,
      x + 12,
      y + 110,
      680,
      520,
      model.focus,
    )
    model.labels.forEach((label, j) => {
      const labelY = model.labels.length > 1 ? y + 140 + j * 125 : y + 660
      leader(label.text, project(label.point), x + 20, labelY)
    })
    const panel = document.createElement('canvas')
    panel.width = 700
    panel.height = 620
    panel.getContext('2d')!.drawImage(canvas, x, y + 80, 700, 620, 0, 0, 700, 620)
    images.push({ name: `step-${i + 1}.png`, data: panel.toDataURL('image/png').split(',')[1] })
    captions[i].forEach((line, row) => text(line, x, y + 730 + row * 44, 29, muted))
    model.dispose()
  }
  text(
    'Pins and bearings stay fitted. Transparent housings reveal the cord paths. Match your recorded winding directions.',
    72,
    3170,
    24,
    muted,
  )
  const data = canvas.toDataURL('image/png').split(',')[1]
  // Print frames share the live geometry and timing, with only part labels inside.
  const printFrames: { step: number; pose: number; data: string }[] = []
  const printPoses = [
    [0.32, 0.9],
    [0.35, 1],
    [0.42, 1],
    [0.72, 1],
    [0.6, 1],
    [0.14, 0.98],
    [0.5, 1],
    [0.25, 0.76],
    [0.42, 1],
  ]
  canvas.width = 1200
  canvas.height = 1050
  for (let step = 0; step < steps.length; step++) {
    for (const pose of printPoses[step]) {
      ctx.fillStyle = paper
      ctx.fillRect(0, 0, canvas.width, canvas.height)
      const model = upkeepScene(bundle, step)
      model.update(pose)
      const project = render(model.group, model.direction, model.up, 0, 0, 1200, 1050, model.focus)
      ctx.font = '24px system-ui, sans-serif'
      model.labels.forEach((label) => {
        const point = project(label.point),
          labelWidth = ctx.measureText(label.text).width
        const x = Math.max(20, Math.min(1160 - labelWidth, point.x + 18)),
          y = Math.max(20, Math.min(1010, point.y))
        ctx.fillStyle = paper
        ctx.fillRect(x - 6, y - 4, labelWidth + 12, 36)
        text(label.text, x, y, 24)
      })
      printFrames.push({ step, pose, data: canvas.toDataURL('image/png').split(',')[1] })
      model.dispose()
    }
  }
  renderer.dispose()
  environment.dispose()
  pmrem.dispose()
  room.dispose()
  return {
    data,
    images,
    printFrames,
    steps: steps.map((step) => ({
      title: step.title,
      instruction: step.instruction,
      detail: step.detail,
    })),
    width,
    height,
    model: 'base-right-dynamixel',
    scenes: [
      'createRepairScene:0–8',
      'handTendonPath',
      'spoolPaths',
      'KnotLesson:ashley-1–11',
      'KnotReinforcement:1',
    ],
    motors: ['I-DP', 'I-PP', 'I-AP'].map((joint) => ({
      joint,
      motor: motorId(joint, build),
      tendons: jointTendons(joint).map((t) => t.name),
    })),
  }
}
