import type { ReactNode } from 'react'
import type { Build } from './buildContent'
import { CAD_ILLUSTRATIONS } from './cadIllustrations'

const MOTOR_SETUP_STEPS = new Set([
  'p93',
  'p98',
  'p99',
  'p115',
  'p117',
  'p119',
  'p122',
  'p123',
  'p126',
  'p127',
])

export function MotorRenderReference({
  build,
  src,
  children,
}: {
  build: Build
  src?: string
  children: ReactNode
}) {
  const recipe =
    src?.includes('/renders/') && src.includes('-dynamixel/')
      ? CAD_ILLUSTRATIONS.find((r) => src.endsWith(`/${r.file}.webp`))
      : undefined
  if (build.motor !== 'feetech' || !recipe?.motorSpecific || !MOTOR_SETUP_STEPS.has(recipe.step))
    return <>{children}</>
  return (
    <span className="assembly-motor-render">
      {children}
      <small className="assembly-motor-render-notice">Dynamixel motors shown</small>
    </span>
  )
}
