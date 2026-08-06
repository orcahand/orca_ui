// The teleop source catalogue as the UI names it. Shared by the source picker
// and by the install gate, which lists the same sources to say what fetching
// orca_teleop buys — one place to keep the wording honest.

import type { TeleopSourceId } from '../../api/types'

export const SOURCE_TILES: {
  id: TeleopSourceId
  label: string
  hint: string
}[] = [
  {
    id: 'mediapipe',
    label: 'Webcam',
    hint: 'MediaPipe hand tracking — just a camera',
  },
  {
    id: 'avp',
    label: 'Vision Pro',
    hint: 'Tracking Streamer visionOS app over WiFi',
  },
  {
    id: 'manus',
    label: 'Manus gloves',
    hint: 'SDK publisher on a Linux box (see docs)',
  },
  {
    id: 'synthetic',
    label: 'Synthetic',
    hint: 'waveform generator — no hardware, dev/demo',
  },
]
