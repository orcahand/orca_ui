// Is the board plugged into the PC? Three answers, because "nothing works"
// has two very different fixes: no adapter on USB (cable, hub, driver), or
// an adapter the PC sees whose motors do not answer (motor power, data
// line, wrong IDs — the bus scan is the next step).

import { useAppStore } from '../state/appStore'

const KIND_LABEL: Record<string, string> = {
  dynamixel: 'Dynamixel adapter',
  feetech: 'Feetech adapter',
  oh_board: 'ORCA board',
  tactile_sensor: 'tactile board',
  mock: 'simulated bus',
}

export function UsbIndicator({ connected }: { connected: boolean }) {
  const usb = useAppStore((s) => s.usb)
  const wsConnected = useAppStore((s) => s.wsConnected)

  if (!wsConnected || usb === null) {
    return (
      <span className="bench-usb unknown" title="waiting for the backend's USB report">
        <i /> USB ?
      </span>
    )
  }

  const motorDevice =
    usb.devices.find((d) => d.device === usb.motor_port) ??
    usb.devices.find((d) => d.kind !== 'tactile_sensor') ??
    usb.devices[0]
  const devices = usb.devices
    .map((d) => `${d.device} — ${KIND_LABEL[d.kind] ?? d.kind}${d.description ? ` (${d.description})` : ''}`)
    .join('\n')

  if (!usb.present) {
    return (
      <span
        className="bench-usb absent"
        title="no known motor adapter or ORCA board on USB — check the cable, the hub and the driver"
      >
        <i /> No board on USB
      </span>
    )
  }
  if (connected) {
    return (
      <span className="bench-usb live" title={devices}>
        <i /> Board on USB · motors answering
        {motorDevice ? <small>{motorDevice.device}</small> : null}
      </span>
    )
  }
  return (
    <span
      className="bench-usb silent"
      title={`${devices}\n\nthe PC sees the board but no motor answers: motor power, data cable, or motor ids — scan the bus`}
    >
      <i /> Board on USB · motors silent
      {motorDevice ? <small>{motorDevice.device}</small> : null}
    </span>
  )
}
