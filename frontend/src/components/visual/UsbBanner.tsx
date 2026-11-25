// A rig camera on a USB 2 link sends 1080p at most: steps 1a and 1b, the sweeps and the hand
// captures need the config's resolution and refuse its photos. Shown on every step of the
// visual-calibration page and on the dashboard camera, polled every 5 s (the server answers
// from cached USB listings: this opens no camera).

import { useEffect, useState } from 'react'
import { usePageVisible } from '../common/usePageVisible'
import { setupApi, type SetupWarning } from './api'

const POLL_MS = 5000

function useUsbBanner(on = true): SetupWarning[] {
  const [banner, setBanner] = useState<SetupWarning[]>([])
  const visible = usePageVisible()
  useEffect(() => {
    if (!on || !visible) return
    let alive = true
    const poll = () =>
      setupApi.usb().then(
        (u) => alive && setBanner(u.banner),
        () => undefined, // an older server or no experiment: no banner
      )
    void poll()
    const id = window.setInterval(poll, POLL_MS)
    return () => {
      alive = false
      window.clearInterval(id)
    }
  }, [on, visible])
  return banner
}

export function UsbBanner({ on = true }: { on?: boolean }) {
  const banner = useUsbBanner(on)
  if (!banner.length) return null
  return (
    <div className="gt-warning visual-cal-usb-banner">
      {banner.map((w) => {
        const res = w.values.resolution as number[] | undefined
        return (
          <div key={`${w.code}-${String(w.values.serial)}`}>
            <b>{w.message}</b> {w.fix}{' '}
            <span className="dim">
              Setup still works at 1920×1080; 1a, 1b and the sweeps need {res ? `${res[0]}×${res[1]}` : 'the config resolution'} and
              refuse photos until the camera runs at USB 3.
            </span>
          </div>
        )
      })}
    </div>
  )
}
