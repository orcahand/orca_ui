// Studio lighting for the small hand and tower renders: the palette's
// three-point rig parented to the camera (so the model is lit from the
// viewer's side at any orbit angle), a hemisphere fill, and an environment
// map built in the browser from a few soft panels, which gives the printed
// plastic and the silicone their sheen without any texture to download.
// A soft contact shadow under the model grounds it.

import { ContactShadows, Environment, Lightformer } from '@react-three/drei'
import { useThree } from '@react-three/fiber'
import { useEffect } from 'react'
import * as THREE from 'three'
import { usePalette } from '../../theme/themeStore'

function CameraRig({ rig }: { rig: [number, number, number, number, string][] }) {
  const camera = useThree((s) => s.camera)
  const scene = useThree((s) => s.scene)
  const invalidate = useThree((s) => s.invalidate)
  useEffect(() => {
    const detached = !camera.parent
    if (detached) scene.add(camera)
    const lights = rig.map(([x, y, z, intensity, color]) => {
      const light = new THREE.DirectionalLight(color, intensity)
      light.position.set(x, y, z)
      light.target.position.set(0, 0, -1)
      camera.add(light, light.target)
      return light
    })
    invalidate()
    return () => {
      for (const light of lights) {
        camera.remove(light, light.target)
        light.dispose()
      }
      if (detached) scene.remove(camera)
    }
  }, [camera, scene, invalidate, rig])
  return null
}

export function StudioLights({ shadowY = 0, shadowScale = 0.5 }: { shadowY?: number; shadowScale?: number }) {
  const { scene } = usePalette()
  return (
    <>
      <hemisphereLight args={[scene.hemiSky, scene.hemiGround, scene.hemiIntensity * 0.8]} />
      <CameraRig rig={scene.lights} />
      <Environment resolution={64} frames={1}>
        <Lightformer intensity={2} form="rect" position={[0, 2, 1]} scale={[3, 2, 1]} target={[0, 0, 0]} />
        <Lightformer intensity={0.8} form="rect" position={[-2, 1, -1]} scale={[2, 1.5, 1]} target={[0, 0, 0]} />
        <Lightformer intensity={0.5} form="rect" position={[2, 0.5, -1]} scale={[2, 1, 1]} target={[0, 0, 0]} />
        <Lightformer intensity={0.3} form="ring" position={[0, -1.5, 0]} scale={2} target={[0, 0, 0]} />
      </Environment>
      <ContactShadows position={[0, shadowY, 0]} opacity={0.35} scale={shadowScale} blur={2.2} far={shadowScale} frames={1} />
    </>
  )
}
